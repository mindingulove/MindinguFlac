"""Remote control acknowledgement, identity, cleanup and paired TLS transport."""
import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import device_sync
import remote_playback as rp


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.now=100.
        self.r=rp.Receiver(lambda:self.now)
        self.r.bridge({'snapshot':{'track':{'title':'Song'},'queue':[{'title':'Song'}]}})

    def acknowledge(self, future):
        deadline=time.monotonic()+1
        while not self.r.pending and time.monotonic()<deadline:time.sleep(.001)
        result=self.r.bridge({'snapshot':{'track':{'title':'Song'},'queue':[{'title':'Song'}]}})
        self.assertTrue(result['commands'])
        commands=result['commands']
        self.r.bridge({'snapshot':{'track':{'title':'Song'},'playing':True},'acks':[{'id':c['id']} for c in commands]})
        return future.result(timeout=2),commands

    def connect(self):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            result,commands=self.acknowledge(pool.submit(self.r.connect,'phone','Phone'))
        self.assertEqual(commands[0]['action'],'connect')
        return result['session']['id']

    def test_connection_and_commands_require_actual_player_ack(self):
        sid=self.connect()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future=pool.submit(self.r.command,'phone',sid,'seek',{'position':21})
            result,commands=self.acknowledge(future)
        self.assertEqual(commands[0]['payload'],{'position':21.0})
        self.assertTrue(result['snapshot']['playing'])
        self.assertNotIn('secret',json.dumps(result))

    def test_other_device_and_stale_sessions_cannot_command_or_ack(self):
        sid=self.connect()
        for peer,session in [('other',sid),('phone','stale')]:
            with self.assertRaises(ValueError):self.r.status(peer,session)
        self.r.disconnect('other',sid);self.assertIsNotNone(self.r.session)
        self.r.disconnect('phone','stale');self.assertIsNotNone(self.r.session)
        self.r.disconnect('phone',sid);self.assertIsNone(self.r.session)
        with self.assertRaises(ValueError):self.r.status('phone',sid)

    def test_controller_loss_player_loss_close_and_revocation_clear_banners(self):
        sid=self.connect();self.now+=rp.LEASE_SECONDS+1
        self.assertIsNone(self.r.bridge({'snapshot':{}})['session'])
        sid=self.connect();self.now+=rp.PLAYER_SECONDS+1
        with self.assertRaises(ValueError):self.r.status('phone',sid)
        self.r.bridge({'snapshot':{}});self.connect()
        self.assertIsNone(self.r.bridge({'snapshot':{},'closing':True})['session'])
        self.assertFalse(self.r.pending)

    def test_status_reports_snapshot_age_and_controller_adds_the_trip_back(self):
        rp._lan_exchanges.clear()
        sid=self.connect()
        self.now+=0.4
        self.assertAlmostEqual(self.r.status('phone',sid)['snapshot_age'],0.4)
        from unittest.mock import Mock
        client=Mock();client.lock=threading.RLock();client.state={'pair':{'device_id':'mac'}}
        client.remote_request.return_value={'ok':True,'snapshot':{},'snapshot_age':0.4,'_exchange_seconds':0.06}
        with patch.object(device_sync,'_android',client),patch.object(rp,'_controller',{'device_id':'mac','session_id':'live'}):
            result=rp.controller_request('status')
        self.assertAlmostEqual(result['snapshot_age'],0.43)
        self.assertAlmostEqual(result['lan_rtt'],0.06)
        # One slow exchange among steady ones does not move the estimate.
        with patch.object(device_sync,'_android',client),patch.object(rp,'_controller',{'device_id':'mac','session_id':'live'}):
            for exchange in (0.06,0.9,0.06):
                client.remote_request.return_value={'ok':True,'snapshot':{},'snapshot_age':0.4,'_exchange_seconds':exchange}
                result=rp.controller_request('status')
        self.assertAlmostEqual(result['lan_rtt'],0.06)

    def test_offline_inventory_requires_current_owner_and_removes_device_paths(self):
        sid=self.connect()
        with patch.object(rp,'receiver',self.r),patch.object(rp,'offline_catalog',return_value={'tracks':[{'title':'Downloaded','library_path':'/private/song.flac','artwork_url':'/api/library/artwork?path=/private/song.flac','offline':True,'isrc':'TEST123'}]}) as provider:
            for peer,session in [('other',sid),('phone','stale')]:
                with self.assertRaises(ValueError):rp.paired_request(peer,'Phone','/remote/offline',{'session_id':session})
            provider.assert_not_called()
            result=rp.paired_request('phone','Phone','/remote/offline',{'session_id':sid})
        self.assertEqual(result['tracks'][0]['isrc'],'TEST123')
        self.assertNotIn('/private',json.dumps(result));self.assertNotIn('library_path',result['tracks'][0])

    def test_timeout_is_not_a_successful_connection(self):
        with patch.object(rp,'COMMAND_SECONDS',.01):
            with self.assertRaises(TimeoutError):self.r.connect('phone','Phone')
        self.assertIsNone(self.r.session);self.assertFalse(self.r.pending)

    def test_artwork_is_portable_and_status_mirrors_receiver(self):
        from urllib.parse import quote
        public='https://i.scdn.co/image/album-cover'
        for prefix in ('', 'http://127.0.0.1:55900', 'http://192.168.1.2:55900'):
            self.assertEqual(rp.track({'title':'Song','artwork_url':prefix+'/api/image?url='+quote(public,safe='')})['artwork_url'],public)
        for art in ('/api/library/artwork?path=/private/song.flac','file:///private/image.png','http://localhost:55900/art','http://127.0.0.2/art','http://192.168.1.2/art','http://mac.local/art','http://[::1]/art','https://user:password@example.com/art','data:image/png;base64,pixels'):
            self.assertNotIn('artwork_url',rp.track({'title':'Song','artwork_url':art}))
        result=rp.snapshot({'track':{'title':'Song'},'status':'Fetching audio','status_mode':'downloading','progress':37,'quality_label':'HI-RES','queue_title':'Exact deluxe edition'})
        self.assertEqual((result['status'],result['status_mode'],result['progress'],result['quality_label'],result['queue_title']),('Fetching audio','downloading',37,'HI-RES','Exact deluxe edition'))

    def test_metadata_projection_never_transmits_local_paths_or_executes_arbitrary_commands(self):
        t=rp.track({'title':'Song','library_path':'/private/file.flac','offline':True,
                    'stream_url':'file:///private/file','metadata':{'secret':'hidden'},'album_context':{'spotify_id':'exact','path':'secret'}})
        self.assertNotIn('/private',json.dumps(t));self.assertNotIn('secret',json.dumps(t));self.assertNotIn('stream_url',t)
        with self.assertRaises(ValueError):rp.command_payload('shell',{})
        with self.assertRaises(ValueError):rp.command_payload('volume',{'volume':float('nan')})
        with self.assertRaises(ValueError):rp.command_payload('seek',{'position':-1})
        with self.assertRaises(ValueError):rp.queue([{'title':'Song'}]*(rp.MAX_QUEUE+1))


class PairedTransportTests(unittest.TestCase):
    def test_real_tls_authentication_pin_command_ack_and_revocation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(device_sync,'_state_dir',return_value=Path(tmp)),patch.object(device_sync.DesktopPairingService,'_advertise'),patch.object(rp,'receiver',rp.Receiver()):
            service=device_sync.DesktopPairingService();service.start()
            try:
                service.state['devices']['phone-identity']={'name':'Test phone','secret':'test-only-secret'}
                client=object.__new__(device_sync.AndroidPairingClient)
                device={'address':'127.0.0.1','port':service.port,'fingerprint':service.fingerprint}
                rp.receiver.bridge({'snapshot':{}})
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future=pool.submit(client._connect,device,'/remote/connect',{'device_id':'phone-identity'},'test-only-secret',3)
                    deadline=time.monotonic()+2
                    while not rp.receiver.pending and time.monotonic()<deadline:time.sleep(.005)
                    commands=rp.receiver.bridge({'snapshot':{}})['commands']
                    self.assertTrue(commands)
                    rp.receiver.bridge({'snapshot':{},'acks':[{'id':commands[0]['id']}]})
                    result=future.result(timeout=3)
                self.assertTrue(result['session']);sid=result['session']['id']
                with self.assertRaises(RuntimeError):client._connect(device,'/remote/status',{'device_id':'phone-identity','session_id':sid},'wrong-secret',3)
                with self.assertRaises(ValueError):client._connect({**device,'fingerprint':'0'*64},'/remote/status',{},'',3)
                service.remove_device('phone-identity')
                self.assertIsNone(rp.receiver.session)
                self.assertEqual(client._connect(device,'/remote/status',{'device_id':'phone-identity','session_id':sid},'test-only-secret',3)['_status'],410)
            finally:
                service._running=False;service.httpd.shutdown();service.httpd.server_close()

    def test_android_cannot_target_an_unpaired_or_changed_identity(self):
        c=object.__new__(device_sync.AndroidPairingClient);c.lock=threading.RLock()
        c.state={'phone_id':'phone','pair':{'device_id':'mac','fingerprint':'pinned','secret':'private'}}
        c.discovered={'mac':{'fingerprint':'changed'}}
        with self.assertRaises(ValueError):c.remote_request('/remote/connect',{},'another')
        with self.assertRaises(ValueError):c.remote_request('/remote/connect',{},'mac')

class ControllerRaceTests(unittest.TestCase):
    def test_cancel_inflight_connect_cannot_leave_a_hidden_remote_route(self):
        from unittest.mock import Mock
        entered=threading.Event();finish=threading.Event();requests=[]
        client=Mock()
        def remote(path,body,target):
            requests.append((path,body,target))
            if path=='/remote/connect':
                entered.set();finish.wait(2)
                return {'ok':True,'device_id':'mac','name':'Mac','session':{'id':'cancelled-session'}}
            return {'ok':True}
        client.remote_request.side_effect=remote
        with patch.object(device_sync,'_android',client),patch.object(rp,'_controller',None):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future=pool.submit(rp.controller_request,'connect',{'device_id':'mac'})
                self.assertTrue(entered.wait(1));rp.controller_request('disconnect');finish.set()
                with self.assertRaisesRegex(RuntimeError,'cancelled'):future.result(timeout=2)
            self.assertIsNone(rp._controller)
            self.assertTrue(any(p=='/remote/disconnect' and b['session_id']=='cancelled-session' for p,b,_ in requests))

    def test_controller_projects_phone_local_paths_before_paired_request(self):
        from unittest.mock import Mock
        client=Mock();client.remote_request.return_value={'ok':True}
        with patch.object(device_sync,'_android',client),patch.object(rp,'_controller',{'device_id':'mac','session_id':'live'}):
            rp.controller_request('command',{'action':'select','payload':{'track':{'title':'Song','library_path':'/phone/private'},'queue':[]}})
        self.assertNotIn('/phone/private',json.dumps(client.remote_request.call_args.args))

    def test_removed_pair_clears_controller_route_without_sending_commands(self):
        from unittest.mock import Mock
        client=Mock();client.lock=threading.RLock();client.state={'pair':None}
        with patch.object(device_sync,'_android',client),patch.object(rp,'_controller',{'device_id':'mac','session_id':'live'}):
            self.assertIsNone(rp.controller_request('status')['route'])
            self.assertIsNone(rp._controller)
        client.remote_request.assert_not_called()
