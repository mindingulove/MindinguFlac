"""Acknowledged playback control over the existing pinned, paired LAN transport.

Only the local player bridge executes commands. Pairing secrets never leave
Python, and neither controller metadata nor snapshots can carry local paths.
"""
from __future__ import annotations

import math
import secrets
import threading
import time
import uuid
import urllib.parse
import ipaddress

LEASE_SECONDS = 30
PLAYER_SECONDS = 18
COMMAND_SECONDS = 7
MAX_QUEUE = 2000
_ACTIONS = {'connect', 'play', 'pause', 'next', 'previous', 'select', 'seek',
            'volume', 'shuffle', 'repeat', 'queue_append', 'queue_remove', 'queue_reorder'}
_TRACK_FIELDS = ('title', 'artist', 'album', 'spotify_id', 'spotify_url', 'isrc',
                 'album_spotify_id', 'album_artist', 'artist_id', 'year')


def number(value, minimum=0, maximum=86400):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError('Invalid playback number')
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('Playback number out of range')
    return value


def portable_artwork(value):
    artwork = str(value or '')
    if len(artwork) > 8192:
        return ''
    parsed = urllib.parse.urlparse(artwork)
    if parsed.path == '/api/image':
        artwork = (urllib.parse.parse_qs(parsed.query).get('url') or [''])[0]
        parsed = urllib.parse.urlparse(artwork)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        return ''
    if parsed.hostname == 'localhost' or parsed.hostname.endswith(('.localhost', '.local')):
        return ''
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            return ''
    except ValueError:
        pass
    return artwork[:4096]


def track(value):
    if not isinstance(value, dict) or not value.get('title'):
        raise ValueError('A song title is required')
    result = {key: str(value.get(key) or '')[:1000] for key in _TRACK_FIELDS}
    result.update(type='track', duration_ms=number(value.get('duration_ms') or 0, 0, 86400000))
    artwork = portable_artwork(value.get('artwork_url'))
    if artwork:
        result['artwork_url'] = artwork
    result['is_compilation'] = bool(value.get('is_compilation'))
    context = value.get('album_context')
    if isinstance(context, dict):
        result['album_context'] = {key: str(context.get(key) or '')[:1000]
                                   for key in ('spotify_id', 'album', 'album_artist')}
    return result


def queue(value):
    if not isinstance(value, list) or len(value) > MAX_QUEUE:
        raise ValueError('Playback queue is too large')
    return [track(item) for item in value]


def snapshot(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid player state')
    return {'track': track(value['track']) if value.get('track') else None,
            'queue': queue(value.get('queue') or []),
            'queue_index': int(number(value.get('queue_index') or 0, -1, MAX_QUEUE)),
            'position': number(value.get('position') or 0),
            'duration': number(value.get('duration') or 0),
            'volume': number(value.get('volume') or 0, 0, 1),
            'playing': bool(value.get('playing')), 'buffering': bool(value.get('buffering')),
            'shuffle': bool(value.get('shuffle')), 'repeat': bool(value.get('repeat')),
            'status': str(value.get('status') or '')[:500],
            'status_mode': value.get('status_mode') if value.get('status_mode') in ('ready', 'downloading', 'buffering', 'error') else 'ready',
            'progress': number(value.get('progress') or 0, 0, 100),
            'quality_label': str(value.get('quality_label') or '')[:32],
            'queue_title': str(value.get('queue_title') or '')[:200],
            'error': str(value.get('error') or '')[:300]}


def command_payload(action, payload):
    if action not in _ACTIONS:
        raise ValueError('Unsupported remote playback command')
    if not isinstance(payload, dict):
        raise ValueError('Invalid playback command')
    if action == 'select':
        return {'track': track(payload.get('track')), 'queue': queue(payload.get('queue') or [])}
    if action == 'queue_append':
        return {'tracks': queue(payload.get('tracks') or [])}
    if action in ('queue_remove', 'queue_reorder'):
        return {key: int(number(payload.get(key), 0, MAX_QUEUE))
                for key in (('index',) if action == 'queue_remove' else ('from_index', 'to_index'))}
    if action in ('seek', 'volume'):
        key = 'position' if action == 'seek' else 'volume'
        return {key: number(payload.get(key), 0, 86400 if action == 'seek' else 1)}
    if action in ('shuffle', 'repeat'):
        if not isinstance(payload.get('enabled'), bool):
            raise ValueError('Playback mode must be true or false')
        return {'enabled': payload['enabled']}
    return {}


class Receiver:
    def __init__(self, clock=time.monotonic):
        self.lock = threading.RLock()
        self.clock = clock
        self.player_seen = 0.0
        self.player_state = snapshot({})
        self.session = None
        self.pending = {}

    def _clear(self, error):
        for entry in self.pending.values():
            entry['error'] = error
            entry['event'].set()
        self.pending.clear()
        self.session = None

    def _expire(self):
        now = self.clock()
        if self.session and (now - self.session['seen'] > LEASE_SECONDS
                             or now - self.player_seen > PLAYER_SECONDS):
            self._clear('Remote playback disconnected')

    def _public(self):
        if not self.session or not self.session['acknowledged']:
            return None
        return {key: self.session[key] for key in ('id', 'controller_id', 'controller_name')}

    def bridge(self, body):
        value = snapshot(body.get('snapshot') or {})
        with self.lock:
            self._expire()
            if body.get('closing'):
                self._clear('Receiving player closed')
                self.player_seen = 0
                return {'ok': True, 'session': None, 'commands': []}
            self.player_state = value
            self.player_seen = self.clock()
            for ack in (body.get('acks') or [])[:32]:
                if not isinstance(ack, dict):
                    continue
                entry = self.pending.get(str(ack.get('id') or ''))
                if not entry or not self.session or entry['session_id'] != self.session['id']:
                    continue
                entry['error'] = str(ack.get('error') or '')[:300]
                if entry['action'] == 'connect' and not entry['error']:
                    self.session['acknowledged'] = True
                entry['event'].set()
            return {'ok': True, 'session': self._public(),
                    'commands': [{key: value for key, value in entry.items() if key not in ('event', 'error')}
                                 for entry in self.pending.values() if not entry['event'].is_set()]}

    def connect(self, peer_id, name):
        with self.lock:
            self._expire()
            if self.clock() - self.player_seen > PLAYER_SECONDS:
                raise RuntimeError('Open Mindinguflac on the receiving computer first')
            self._clear('Playback controller changed')
            self.session = {'id': secrets.token_urlsafe(24), 'controller_id': peer_id,
                            'controller_name': str(name or 'Android phone')[:100],
                            'seen': self.clock(), 'acknowledged': False}
            session_id = self.session['id']
        try:
            return self.command(peer_id, session_id, 'connect', {})
        except Exception:
            with self.lock:
                if self.session and self.session['id'] == session_id:
                    self._clear('Connection was not acknowledged')
            raise

    def _require(self, peer_id, session_id):
        self._expire()
        if not self.session or self.session['controller_id'] != peer_id or not secrets.compare_digest(
                self.session['id'], str(session_id or '')):
            raise ValueError('Remote playback session ended. Select the device again.')
        self.session['seen'] = self.clock()

    def status(self, peer_id, session_id):
        with self.lock:
            self._require(peer_id, session_id)
            return {'ok': True, 'session': self._public(), 'snapshot': self.player_state}

    def command(self, peer_id, session_id, action, payload):
        payload = command_payload(action, payload)
        with self.lock:
            self._require(peer_id, session_id)
            if len(self.pending) >= 16:
                raise RuntimeError('The receiver is busy. Please wait.')
            command_id = str(uuid.uuid4())
            entry = {'id': command_id, 'session_id': self.session['id'], 'action': action,
                     'payload': payload, 'event': threading.Event(), 'error': ''}
            self.pending[command_id] = entry
        try:
            if not entry['event'].wait(COMMAND_SECONDS):
                raise TimeoutError('The receiving player did not acknowledge the command')
            if entry['error']:
                raise RuntimeError(entry['error'])
            return self.status(peer_id, session_id)
        finally:
            with self.lock:
                self.pending.pop(command_id, None)

    def disconnect(self, peer_id, session_id=None):
        with self.lock:
            if self.session and self.session['controller_id'] == peer_id:
                if session_id is None or secrets.compare_digest(self.session['id'], str(session_id)):
                    self._clear('Remote playback session ended')
            return {'ok': True, 'session': None}


receiver = Receiver()
_controller = None
_controller_generation = 0
_controller_lock = threading.Lock()


def local_bridge(body):
    return receiver.bridge(body)


def offline_catalog():
    # Read the same completed-file inventory as this device's Offline playlist.
    from app import service_downloader
    from offline_playlist import build_offline_playlist
    return build_offline_playlist(service_downloader) or {'tracks': []}


def paired_request(peer_id, name, path, body):
    if path == '/remote/connect':
        return receiver.connect(peer_id, name)
    if path == '/remote/status':
        return receiver.status(peer_id, body.get('session_id'))
    if path == '/remote/offline':
        receiver.status(peer_id, body.get('session_id'))
        catalog = offline_catalog()
        return {'ok': True, 'tracks': [track(item) for item in catalog.get('tracks', [])]}
    if path == '/remote/command':
        return receiver.command(peer_id, body.get('session_id'), str(body.get('action') or ''), body.get('payload') or {})
    if path == '/remote/disconnect':
        return receiver.disconnect(peer_id, body.get('session_id'))
    raise ValueError('Unknown remote playback request')


def controller_request(action, body=None):
    global _controller, _controller_generation
    import device_sync
    client = device_sync._android
    body = body or {}
    if client is None:
        raise RuntimeError('Remote control is available on a paired Android phone')
    with _controller_lock:
        route = dict(_controller or {})
    if action == 'connect':
        with _controller_lock:
            _controller_generation += 1
            generation = _controller_generation
        result = client.remote_request('/remote/connect', {}, str(body.get('device_id') or ''))
        route = {'device_id': result['device_id'], 'name': result['name'],
                 'session_id': result['session']['id']}
        with _controller_lock:
            superseded = generation != _controller_generation
            if not superseded:
                _controller = route
        if superseded:
            client.remote_request('/remote/disconnect', {'session_id': route['session_id']}, route['device_id'])
            raise RuntimeError('Remote connection was cancelled')
        return {**result, 'route': route}
    if action == 'disconnect':
        with _controller_lock:
            _controller_generation += 1
            _controller = None
        if route:
            try:
                client.remote_request('/remote/disconnect', {'session_id': route['session_id']}, route['device_id'])
            except Exception:
                pass  # receiver lease also expires when the phone cannot reach it
        return {'ok': True, 'route': None}
    if not route:
        return {'ok': True, 'route': None}
    if action in ('status', 'offline'):
        with client.lock:
            pair = dict(client.state.get('pair') or {})
        if pair.get('device_id') != route['device_id']:
            with _controller_lock:
                if _controller == route:
                    _controller = None
                    _controller_generation += 1
            return {'ok': True, 'route': None}
    if action not in ('status', 'offline'):
        # Project before sending anything over the LAN, including offline
        # tracks selected on the phone. Device-local paths are not portable.
        body = {'action': str(body.get('action') or ''),
                'payload': command_payload(str(body.get('action') or ''), body.get('payload') or {})}
    try:
        result = client.remote_request('/remote/' + action if action in ('status', 'offline') else '/remote/command',
                                       {'session_id': route['session_id'], 'action': body.get('action'),
                                        'payload': body.get('payload') or {}}, route['device_id'])
        return {**result, 'route': route}
    except Exception as exc:
        if 'Remote playback session ended.' in str(exc) or 'removed this device pairing' in str(exc):
            with _controller_lock:
                if _controller == route:
                    _controller = None
                    _controller_generation += 1
            return {'ok': False, 'route': None, 'error': str(exc)[:300]}
        return {'ok': False, 'route': route, 'error': str(exc)[:300]}
