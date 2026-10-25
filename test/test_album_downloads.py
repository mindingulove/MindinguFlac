"""Bulk download intent cannot delete saved tracks or borrow sibling progress."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import service_downloader as sd


class AlbumDownloadSafetyTests(unittest.TestCase):
    def manager(self):
        manager=object.__new__(sd.ServiceDownloadManager)
        manager._library_toggle_lock=threading.RLock()
        manager._lock=threading.Lock()
        manager.config=SimpleNamespace(default_quality='LOSSLESS')
        manager._find_library_entry=Mock(return_value=None)
        manager._find_cache_entry=Mock(return_value=None)
        manager._find_active_library_job=Mock(return_value=None)
        manager._find_active_cache_job=Mock(return_value=None)
        manager.library_status=Mock(return_value={'in_library':False,'download_satisfied':False})
        manager._delete_library_entry=Mock()
        manager.start_job=Mock(return_value={'id':'new','mode':'download'})
        return manager

    def test_album_intent_preserves_equal_quality_file_but_row_toggle_still_removes(self):
        m=self.manager();m._find_library_entry.return_value={'path':Path('/saved.flac'),'quality':700}
        result=m.toggle_library({'title':'Song','ensure_download':True,'quality':'LOSSLESS'})
        self.assertEqual(result['action'],'saved');m._delete_library_entry.assert_not_called();m.start_job.assert_not_called()
        self.assertEqual(m.toggle_library({'title':'Song'})['action'],'deleted')
        m._delete_library_entry.assert_called_once()

    def test_quality_upgrade_keeps_lower_quality_file_and_ignores_lower_cache(self):
        m=self.manager();m._find_library_entry.return_value={'path':Path('/saved.mp3'),'quality':400}
        m._find_cache_entry.return_value={'path':Path('/cache.mp3'),'quality':400}
        self.assertEqual(m.toggle_library({'title':'Song','ensure_download':True})['action'],'started')
        m._delete_library_entry.assert_not_called();m.start_job.assert_called_once()
        self.assertEqual(m.start_job.call_args.args[0]['mode'],'download')

    def test_overlapping_album_and_row_requests_join_one_download(self):
        m=self.manager();active=[]
        m._find_active_library_job.side_effect=lambda identity: active[0] if active else None
        def start(payload):
            active.append({'id':'one','mode':'download','status':'running'});return active[0]
        m.start_job.side_effect=start
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(m.toggle_library,[{'title':'Song','ensure_download':True}]*2))
        self.assertEqual(sorted(r['action'] for r in results),['queued','started'])
        m.start_job.assert_called_once()

    def test_shared_album_siblings_do_not_create_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Other - Artist.flac').write_bytes(b'fLaC'+b'0'*200000)
            m=self.manager();job={'id':'job','title':'Wanted','artist':'Artist','mode':'download','engine':'ytp-dl','status':'running','output_dir':str(root)}
            self.assertFalse(m._sync_progress_from_files(job))
            self.assertNotIn('progress',job)
            job['engine']='monochrome'
            self.assertFalse(m._sync_progress_from_files(job))

    def test_monochrome_progress_uses_its_shared_fetch_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);album=root/'album';album.mkdir();audio=root/'shared.audio';audio.write_bytes(b'fLaC'+b'0'*1000)
            m=self.manager();job={'id':'job','title':'Wanted','artist':'Artist','mode':'download','engine':'monochrome','status':'running',
                'output_dir':str(album),'active_audio_path':str(audio),'active_audio_ready_bytes':500,'active_audio_size':1000}
            self.assertTrue(m._sync_progress_from_files(job));self.assertEqual(job['progress'],50)

    def test_repair_never_renames_an_unrelated_saved_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Other - Artist.flac').write_bytes(b'fLaC'+b'0'*100000)
            m=self.manager();m._normalize_downloaded_audio=Mock()
            job={'status':'finished','mode':'download','title':'Wanted','artist':'Artist','output_dir':str(root),'library_path':str(root/'missing.flac')}
            with patch.object(sd,'is_valid_audio_file',return_value=True):self.assertFalse(m._repair_finished_audio_path(job))
            m._normalize_downloaded_audio.assert_not_called()

class AlbumQueuePersistenceTests(unittest.TestCase):
    def test_device_queue_survives_new_origin_and_ignores_out_of_order_saves(self):
        import ast,json
        tree=ast.parse(Path('app.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'load_album_download_queue','save_album_download_queue'}]
        with tempfile.TemporaryDirectory() as tmp:
            ns={'json':json,'ALBUM_DOWNLOAD_QUEUE_PATH':Path(tmp)/'queue.json','album_download_queue_lock':threading.Lock()}
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),ns)
            batch={'key':'album','items':[{'track':{'title':'Song'},'payload':{'engine':'monochrome'}}]}
            self.assertTrue(ns['save_album_download_queue']({'updated_at':2,'batches':[batch]}))
            self.assertTrue(ns['save_album_download_queue']({'updated_at':1,'batches':[]}))
            self.assertEqual(ns['load_album_download_queue']()['batches'],[batch])
            self.assertTrue(ns['save_album_download_queue']({'updated_at':3,'batches':[]}))
            self.assertEqual(ns['load_album_download_queue']()['batches'],[])
            self.assertFalse(ns['save_album_download_queue']({'updated_at':4,'batches':'invalid'}))
            ns['ALBUM_DOWNLOAD_QUEUE_PATH'].write_text('{bad json')
            self.assertEqual(ns['load_album_download_queue']()['batches'],[])
            self.assertTrue(ns['save_album_download_queue']({'updated_at':5,'batches':[batch]}))

    def test_explicit_download_preserves_engine_during_stream_cooldown(self):
        import backend_monochrome
        m=object.__new__(sd.ServiceDownloadManager)
        m.config=SimpleNamespace(download_engine='monochrome',download_service='monochrome',default_quality='flac')
        with patch.object(backend_monochrome,'stream_block_reason',return_value='Temporary provider cooldown'):
            self.assertEqual(m._requested_engine({'mode':'download'})[0],'monochrome')
            self.assertEqual(m._requested_engine({'mode':'stream'})[0],'ytp-dl')

class DownloadAcceptanceTests(unittest.TestCase):
    def test_job_is_acknowledged_before_slow_metadata_and_identifiers_are_still_persisted(self):
        import time
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        manager=object.__new__(sd.ServiceDownloadManager)
        manager.config=SimpleNamespace(download_engine='monochrome',download_service='monochrome',default_quality='LOSSLESS')
        manager.jobs={};manager._lock=threading.Lock();manager._start_lock=threading.Lock();manager._cancel_flags=set()
        manager.on_track_metadata=Mock()
        def enrich(payload,engine,metadata,**options):
            self.assertTrue(options['force']);entered.set();release.wait(2)
            return {**metadata,'isrc':'USAA12345678','spotify_id':'track-id'}
        def worker(job_id,payload):
            manager._resolve_job_metadata(manager.jobs[job_id],payload);finished.set()
        manager._worker=worker
        with patch.object(sd,'_enrich_download_metadata_for_search',side_effect=enrich):
            started=time.monotonic()
            job=manager.start_job({'title':'Song','artist':'Artist','mode':'download','engine':'monochrome',
                                   '_defer_metadata':True,'client_request_id':'request-id','track':{'title':'Song','artist':'Artist','genre':'Rock'}})
            self.assertLess(time.monotonic()-started,.5)
            self.assertTrue(entered.wait(1));self.assertFalse(finished.is_set())
            self.assertEqual(job['client_request_id'],'request-id')
            release.set();self.assertTrue(finished.wait(2))
        self.assertEqual(manager.jobs[job['id']]['isrc'],'USAA12345678')
        self.assertEqual(manager.on_track_metadata.call_args.args[0]['isrc'],'USAA12345678')
