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


class PlaylistTrackSyncTests(unittest.TestCase):
    """Songs added/removed inside playlists sync both ways; no duplicates."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.desk = Path(self.temp.name) / 'desk' / 'playlists.json'
        self.phone = Path(self.temp.name) / 'phone' / 'playlists.json'

    def save(self, path, rows):  # what app.save_playlists does
        path.parent.mkdir(parents=True, exist_ok=True)
        before = json.loads(path.read_text()) if path.exists() else []
        playlist_sync.record_changes(path, before, rows)
        path.write_text(json.dumps(rows))

    def rows(self, path):
        return json.loads(path.read_text()) if path.exists() else []

    def sync(self):
        # The phone posts its snapshot; the desktop merges it and replies with
        # its own; the phone merges the reply (device_sync /sync).
        playlist_sync.merge(self.desk, playlist_sync.export(self.phone))
        playlist_sync.merge(self.phone, playlist_sync.export(self.desk))

    def songs(self, path, key='p'):
        return [t['spotify_id'] for p in self.rows(path) if p['id'] == key for t in p['tracks']]

    @staticmethod
    def track(spotify_id):
        return {'title': spotify_id, 'artist': 'A', 'spotify_id': spotify_id}

    def playlist(self, key, ids, url=''):
        return {'id': key, 'name': 'Mix', 'spotify_url': url, 'tracks': [self.track(i) for i in ids]}

    def edit(self, path, key, add=(), remove=()):
        rows = self.rows(path)
        for row in rows:
            if row['id'] == key:
                row['tracks'] = [t for t in row['tracks'] if t['spotify_id'] not in remove] + [self.track(i) for i in add]
        self.save(path, rows)

    def fresh_phone(self):
        self.phone.parent.mkdir(parents=True)
        self.phone.write_text('[]')

    def test_songs_added_and_deleted_on_both_devices_between_syncs_all_apply(self):
        self.save(self.desk, [self.playlist('p', ['a', 'b', 'c'])])
        self.fresh_phone()
        self.sync()
        self.edit(self.desk, 'p', add=['d'], remove=['a'])   # desktop: +d -a
        self.edit(self.phone, 'p', add=['e'], remove=['b'])  # phone:   +e -b
        self.sync()
        self.assertEqual(sorted(self.songs(self.desk)), ['c', 'd', 'e'])
        self.assertEqual(self.songs(self.desk), self.songs(self.phone))

    def test_phone_only_changes_reach_the_desktop(self):
        self.save(self.desk, [self.playlist('p', ['a', 'b'])])
        self.fresh_phone()
        self.sync()
        self.edit(self.phone, 'p', add=['x'], remove=['a'])
        self.sync()
        self.assertEqual(self.songs(self.desk), ['b', 'x'])
        self.edit(self.desk, 'p', remove=['x'])
        self.sync()
        self.assertEqual(self.songs(self.phone), ['b'])

    def test_same_spotify_playlist_imported_on_both_devices_becomes_one(self):
        url = 'https://open.spotify.com/playlist/04jci0CMM7mqk07Fm6YsFB?si=x'
        self.save(self.desk, [self.playlist('desk-id', ['a', 'b'], url)])
        self.save(self.phone, [self.playlist('phone-id', ['b', 'c'], url)])
        for _ in range(3):
            self.sync()
        for path in (self.desk, self.phone):
            rows = self.rows(path)
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0]['id'], 'desk-id')  # both keep the smaller id
            self.assertEqual(sorted(t['spotify_id'] for t in rows[0]['tracks']), ['a', 'b', 'c'])
        self.assertEqual(self.rows(self.desk), self.rows(self.phone))

    def test_repeated_syncs_are_stable_and_never_duplicate_tracks(self):
        self.save(self.desk, [self.playlist('p', ['a', 'b'])])
        self.save(self.phone, [self.playlist('p', ['b', 'a', 'a'])])
        self.sync()
        first = self.rows(self.desk)
        for _ in range(3):
            self.sync()
        self.assertEqual(self.rows(self.desk), first)
        self.assertEqual(self.rows(self.desk), self.rows(self.phone))
        self.assertEqual(sorted(self.songs(self.desk)), ['a', 'b'])
        self.assertEqual(playlist_sync.merge(self.desk, playlist_sync.export(self.phone)), 0)

    def test_deleting_a_whole_playlist_still_wins_over_older_edits(self):
        self.save(self.desk, [self.playlist('p', ['a'])])
        self.fresh_phone()
        self.sync()
        self.edit(self.phone, 'p', add=['z'])
        self.save(self.desk, [])  # deleted after the phone's edit
        self.sync()
        self.assertEqual(self.rows(self.desk), [])
        self.assertEqual(self.rows(self.phone), [])


class SyncTransportTests(unittest.TestCase):
    """Sync bodies used to be cut at 8 MB, which broke every sync once the
    listening history grew (a real desktop export was ~10 MB of JSON)."""

    def test_large_messages_round_trip_compressed(self):
        import device_sync
        payload = {"statistics": {"tables": {"listening_events": [
            {"id": i, "metadata_json": json.dumps({"title": f"Song {i}", "n": i * 7919})} for i in range(160000)]}}}
        raw = device_sync._encode_body(payload)
        self.assertGreater(len(json.dumps(payload)), 8 * 1024 * 1024)
        self.assertLess(len(raw), len(json.dumps(payload)) / 3)
        self.assertEqual(device_sync._decode_body(raw, "gzip"), payload)

    def test_uncompressed_messages_from_older_versions_still_decode(self):
        import device_sync
        self.assertEqual(device_sync._decode_body(b'{"ok": true}', ""), {"ok": True})

    def test_decompression_is_capped(self):
        import device_sync
        from unittest.mock import patch
        bomb = device_sync._encode_body({"x": "0" * 5_000_000})
        with patch.object(device_sync, "MAX_DECODED_BYTES", 1_000_000):
            with self.assertRaises(ValueError):
                device_sync._decode_body(bomb, "gzip")
