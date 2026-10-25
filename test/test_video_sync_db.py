import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class NormalizedVideoSyncTests(unittest.TestCase):
    """Sync offsets live in track_identities / video_clips / track_clip_sync."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # A brand-new database runs the app's one-time backfills, which read
        # the real playlists and call MusicBrainz; tests must stay offline.
        for item in (patch.object(db, "_DB_PATH", Path(self.tmp.name) / "test.db"),
                     patch.object(db, "_local", threading.local()),
                     patch.object(db, "_run_one_time_migrations", lambda conn: None)):
            item.start()
            self.addCleanup(item.stop)

    def test_track_is_keyed_by_spotify_id_not_by_its_name(self):
        first = db.resolve_track_identity("spotify-1", "GBAHT9601125", "Missing", "Everything But The Girl")
        renamed = db.resolve_track_identity("spotify-1", "", "Missing (Todd Terry Remix)", "EBTG")
        self.assertEqual(first, renamed)
        other_release = db.resolve_track_identity("spotify-2", "GBAHT9601125", "Missing", "Everything But The Girl")
        self.assertNotEqual(first, other_release)  # same ISRC, another Spotify release: its own row

    def test_identifiers_learned_later_attach_to_the_same_row(self):
        by_isrc = db.resolve_track_identity("", "usgf19942501", "Smells Like Teen Spirit", "Nirvana")
        with_spotify = db.resolve_track_identity("5ghIJDpPoe3CfHMGu71E6T", "USGF19942501", "", "")
        self.assertEqual(by_isrc, with_spotify)
        row = db._get_conn().execute("SELECT * FROM track_identities WHERE track_id = ?", (by_isrc,)).fetchone()
        self.assertEqual((row["spotify_id"], row["isrc"], row["title"]),
                         ("5ghIJDpPoe3CfHMGu71E6T", "USGF19942501", "Smells Like Teen Spirit"))

    def test_title_only_identifies_tracks_without_ids(self):
        a = db.resolve_track_identity("", "", "Untitled", "Local Band")
        b = db.resolve_track_identity("", "", "untitled", "local band")
        c = db.resolve_track_identity("", "XX1234567890", "Untitled", "Local Band")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertIsNone(db.resolve_track_identity("", "", "", ""))

    def test_offset_is_per_track_and_clip_and_keeps_manual_nudges(self):
        track = db.resolve_track_identity("spotify-1", "", "Lovefool", "The Cardigans")
        clip = db.resolve_video_clip("youtube", "nN7QA6pZXeA")
        self.assertEqual(clip, db.resolve_video_clip("youtube", "nN7QA6pZXeA"))
        db.nudge_track_clip_sync(track, clip, 0.25)
        db.save_track_clip_sync(track, clip, 12.4, True, 21.8)
        db.nudge_track_clip_sync(track, clip, 0.25)
        self.assertEqual(db.get_track_clip_sync(track, clip),
                         {"offset": 12.4, "matched": True, "confidence": 21.8, "manual_offset": 0.5})
        other_clip = db.resolve_video_clip("youtube", "aaaaaaaaaaa")
        self.assertIsNone(db.get_track_clip_sync(track, other_clip))

    def test_album_and_edit_audio_do_not_reuse_offsets_or_failed_matches(self):
        track = db.resolve_track_identity("spotify-1", "", "Song", "Artist")
        clip = db.resolve_video_clip("youtube", "abcdefghijk")
        db.save_track_clip_sync(track, clip, 0, False, 1)
        self.assertIsNone(db.get_track_clip_sync(track, clip, audio_key="studio"))
        db.nudge_track_clip_sync(track, clip, 0.25, audio_key="studio")
        db.save_track_clip_sync(track, clip, -32, True, 9, audio_key="studio")
        db.save_track_clip_sync(track, clip, 2, True, 8, audio_key="edit")
        self.assertEqual(db.get_track_clip_sync(track, clip, audio_key="studio")["offset"], -32)
        self.assertEqual(db.get_track_clip_sync(track, clip, audio_key="studio")["manual_offset"], 0.25)
        self.assertEqual(db.get_track_clip_sync(track, clip, audio_key="edit")["manual_offset"], 0)

    def test_empty_legacy_name_keyed_table_is_dropped(self):
        conn = db._get_conn()
        conn.execute("CREATE TABLE video_sync (sync_key TEXT PRIMARY KEY)")
        db._drop_empty_legacy_video_sync(conn)
        self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'video_sync'").fetchone())
        conn.execute("CREATE TABLE video_sync (sync_key TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO video_sync VALUES ('kept')")
        db._drop_empty_legacy_video_sync(conn)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'video_sync'").fetchone())


class ClipIdentityTests(unittest.TestCase):
    def _clip_identity(self, cache):
        import hashlib
        source = Path("app.py").read_text()
        start = source.index("def _video_clip_identity(")
        end = source.index("def _video_sync_ids(")
        namespace = {"Path": Path, "hashlib": hashlib, "video_cache_lock": threading.Lock(),
                     "_load_video_cache": lambda: cache,
                     "_youtube_video_id": lambda url: url.split("v=")[-1] if "v=" in url else ""}
        exec(source[start:end], namespace)
        return namespace["_video_clip_identity"]

    def test_downloaded_clip_is_named_by_its_youtube_id_so_redownloads_keep_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "cachekey123.mp4"
            video.write_bytes(b"first download")
            identity = self._clip_identity({"cachekey123": {"webpage_url": "https://www.youtube.com/watch?v=hTWKbfoikeg"}})
            self.assertEqual(identity(video), ("youtube", "hTWKbfoikeg"))
            video.write_bytes(b"a re-download with a different size")
            self.assertEqual(identity(video), ("youtube", "hTWKbfoikeg"))

    def test_clip_without_youtube_id_is_named_by_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "votify.mp4"
            video.write_bytes(b"spotify video bytes")
            source, external_id = self._clip_identity({})(video)
            self.assertEqual(source, "file")
            self.assertTrue(external_id.endswith(":19"))


if __name__ == "__main__":
    unittest.main()
