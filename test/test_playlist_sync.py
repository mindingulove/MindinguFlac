import json
import tempfile
import unittest
from pathlib import Path
import playlist_sync


class PlaylistSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.a = Path(self.temp.name) / 'a' / 'playlists.json'
        self.b = Path(self.temp.name) / 'b' / 'playlists.json'

    def write(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        before = json.loads(path.read_text()) if path.exists() else []
        playlist_sync.record_changes(path, before, rows)
        path.write_text(json.dumps(rows))

    def row(self, key='p', tracks=None):
        return {'id': key, 'name': 'Playlist', 'tracks': tracks or [{'title': 'Song', 'artist': 'Artist'}]}

    def test_transfer_both_directions_preserves_local_playlists(self):
        self.write(self.a, [self.row('a')])
        self.write(self.b, [self.row('b')])
        self.assertEqual(playlist_sync.merge(self.b, playlist_sync.export(self.a)), 1)
        self.assertEqual(playlist_sync.merge(self.a, playlist_sync.export(self.b)), 1)
        self.assertEqual({p['id'] for p in json.loads(self.a.read_text())}, {'a', 'b'})
        self.assertEqual(playlist_sync.merge(self.a, playlist_sync.export(self.b)), 0)

    def test_edits_removals_and_deletion_tombstones_do_not_resurrect(self):
        self.write(self.a, [self.row()])
        playlist_sync.merge(self.b, playlist_sync.export(self.a))
        stale = playlist_sync.export(self.b)
        self.write(self.a, [self.row(tracks=[{'title': 'Replacement', 'artist': 'Artist'}])])
        playlist_sync.merge(self.b, playlist_sync.export(self.a))
        self.assertEqual(json.loads(self.b.read_text())[0]['tracks'][0]['title'], 'Replacement')
        self.write(self.a, [])
        playlist_sync.merge(self.b, playlist_sync.export(self.a))
        playlist_sync.merge(self.a, stale)
        self.assertEqual(json.loads(self.a.read_text()), [])
        self.assertEqual(json.loads(self.b.read_text()), [])

    def test_legacy_conflicts_preserve_tracks_and_converge(self):
        for path, title in ((self.a, 'One'), (self.b, 'Two')):
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps([self.row(tracks=[{'title': title, 'artist': 'Artist'}])]))
        a, b = playlist_sync.export(self.a), playlist_sync.export(self.b)
        playlist_sync.merge(self.a, b)
        playlist_sync.merge(self.b, a)
        self.assertEqual(json.loads(self.a.read_text()), json.loads(self.b.read_text()))
        self.assertEqual(len(json.loads(self.a.read_text())[0]['tracks']), 2)
        self.assertEqual(playlist_sync.merge(self.a, playlist_sync.export(self.b)), 0)

    def test_local_file_paths_do_not_sync_and_backup_is_kept(self):
        row = self.row()
        row['tracks'][0]['library_path'] = '/private/phone/song.flac'
        self.write(self.a, [row])
        snapshot = playlist_sync.export(self.a)
        self.assertNotIn('library_path', snapshot[0]['playlist']['tracks'][0])
        self.write(self.b, [self.row('original')])
        playlist_sync.merge(self.b, snapshot)
        backup = self.b.parent / 'device_sync/playlists.before-first-sync.json'
        self.assertEqual(json.loads(backup.read_text())[0]['id'], 'original')

    def test_corrupt_store_is_not_overwritten(self):
        self.a.parent.mkdir(parents=True)
        self.a.write_text('corrupt')
        with self.assertRaises(json.JSONDecodeError):
            playlist_sync.merge(self.a, [])
        self.assertEqual(self.a.read_text(), 'corrupt')

    def test_device_snapshot_includes_and_applies_playlists(self):
        from unittest.mock import patch
        import app
        import db
        import device_sync
        self.write(self.a, [self.row()])
        with patch.object(app, 'PLAYLISTS_PATH', self.a), patch.object(db, 'sync_export', return_value={'tables': {}, 'cursor': 0}):
            payload = device_sync._local_snapshot('desktop')
        self.assertEqual(payload['playlists'][0]['id'], 'p')
        payload.pop('settings')
        payload['recent'] = []
        with patch.object(app, 'PLAYLISTS_PATH', self.b), patch.object(db, 'sync_import', return_value=0):
            counts = device_sync._apply_snapshot(payload, 'desktop')
        self.assertEqual(counts['playlists'], 1)
        self.assertEqual(json.loads(self.b.read_text())[0]['name'], 'Playlist')
