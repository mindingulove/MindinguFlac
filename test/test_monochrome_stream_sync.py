"""The browser stream and sync matcher reuse the same growing fetch."""
import ast
import hashlib
import re
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import native_audio
import video_sync


def app_functions():
    tree = ast.parse(Path('app.py').read_text())
    names = {'_monochrome_stream_url', '_video_sync_audio_key', '_video_sync_audio_path', '_video_sync'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
    methods = [node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name in {'do_GET', 'stream_local_path'}]
    namespace = dict(Path=Path, hashlib=hashlib, re=re, urlparse=urlparse, parse_qs=parse_qs,
                     time=time, HTTPStatus=HTTPStatus, os=__import__('os'), db=Mock())
    exec(compile(ast.Module(body=nodes + methods, type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace


class StreamSyncTests(unittest.TestCase):
    def test_official_stream_urls_only_and_retry_query_has_same_identity(self):
        ns = app_functions()
        canonical = ns['_monochrome_stream_url']
        self.assertEqual(canonical('https://tracks.monochrome.st/track/123?t=123'),
                         'https://tracks.monochrome.st/track/123')
        for url in ('http://127.0.0.1/track/123', 'https://tracks.monochrome.st.evil/track/1',
                    'https://tracks.monochrome.st@evil/track/1', 'https://tracks.monochrome.st/search',
                    'https://tracks.monochrome.st/track/1/../secret'):
            self.assertEqual(canonical(url), '')
        key = ns['_video_sync_audio_key']
        self.assertEqual(key({'stream_url': 'https://tracks.monochrome.st/track/123?t=1'}),
                         key({'stream_url': 'https://tracks.monochrome.st/track/123?t=2'}))
        self.assertNotEqual(key({'isrc': 'original'}), key({'isrc': 'edit'}))

    def test_partial_stream_match_is_retried_without_caching_a_negative(self):
        ns = app_functions()
        ns['_video_sync_ids'] = lambda body: (1, 2)
        ns['_video_sync_audio_path'] = lambda body: Path('buffer.audio')
        ns['db'].get_track_clip_sync.return_value = None
        body = {'stream_url': 'https://tracks.monochrome.st/track/123', 'video_path': 'video.mp4'}
        with patch.object(video_sync, 'decoder_available', return_value=True), \
                patch.object(video_sync, 'compute_offset', return_value={'matched': False, 'audio_seconds': 45}):
            self.assertEqual(ns['_video_sync'](body)['status'], 'pending')
        ns['db'].save_track_clip_sync.assert_not_called()
        with patch.object(video_sync, 'decoder_available', return_value=True), \
                patch.object(video_sync, 'compute_offset', return_value={'matched': True, 'offset': -32, 'confidence': 8}):
            self.assertEqual(ns['_video_sync'](body)['status'], 'matched')
        ns['db'].save_track_clip_sync.assert_called_once()

    def test_growing_ranges_use_the_shared_fetch_and_matcher_reads_its_path(self):
        ns = app_functions()

        class Handler(BaseHTTPRequestHandler):
            do_GET = ns['do_GET']
            stream_local_path = ns['stream_local_path']
            def require_api_authorization(self, path): return True
            def send_cors_headers(self): pass
            def log_message(self, *args): pass
            def send_error_json(self, message, status): self.send_error(status, message)

        ns['_sniff_audio_mime'] = lambda path: 'audio/flac'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'stream.audio'
            path.write_bytes(b'fLaC1234')
            fetch = SimpleNamespace(path=path, size=8, total=16, done=False, error='',
                                    cancelled=threading.Event(), condition=threading.Condition())
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
            url = f'http://127.0.0.1:{server.server_port}/api/monochrome/stream?url=https%3A%2F%2Ftracks.monochrome.st%2Ftrack%2F123'
            def grow():
                time.sleep(0.1)
                with path.open('ab') as handle: handle.write(b'567890ab')
                with fetch.condition:
                    fetch.size = 16; fetch.done = True; fetch.condition.notify_all()
            with patch.object(native_audio, '_monochrome_fetch', return_value=fetch) as shared, \
                    patch.object(native_audio, '_release_monochrome_fetch') as release, \
                    patch.dict(native_audio._monochrome_fetches, {'https://tracks.monochrome.st/track/123': fetch}):
                threading.Thread(target=grow, daemon=True).start()
                with urlopen(url, timeout=3) as response:
                    self.assertEqual(response.headers['Content-Length'], '16')
                    self.assertEqual(response.read(), b'fLaC1234567890ab')
                with urlopen(Request(url, headers={'Range': 'bytes=4-9'}), timeout=3) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers['Content-Range'], 'bytes 4-9/16')
                    self.assertEqual(response.read(), b'123456')
                self.assertEqual(ns['_video_sync_audio_path']({'stream_url': 'https://tracks.monochrome.st/track/123?t=2'}), path)
                self.assertEqual(shared.call_count, 2)  # same fetch, two browser requests
                self.assertEqual(release.call_count, 2)
