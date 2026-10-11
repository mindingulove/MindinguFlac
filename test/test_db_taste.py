import sqlite3
import time
import unittest
from unittest.mock import patch

import db


class DbTasteTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db._init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_duplicate_listening_event_is_ignored(self):
        event = {
            "event_id": "evt-1",
            "track_key": "track-1",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "event_type": "complete",
            "listened_ms": 240000,
            "duration_ms": 240000,
            "listened_percent": 100,
            "metadata": {"genres": ["Rock"]},
        }
        with patch.object(db, "_get_conn", return_value=self.conn):
            first = db.process_listening_event(event)
            second = db.process_listening_event(event)
            count = self.conn.execute("SELECT COUNT(*) AS c FROM listening_events").fetchone()["c"]
        self.assertTrue(first["ok"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(count, 1)

    def test_youtube_video_override_matches_stable_ids_not_names(self):
        with patch.object(db, "_get_conn", return_value=self.conn):
            saved = db.save_youtube_video_override({
                "spotify_id": "spotify-track-id",
                "isrc": "USSM18200005",
                "youtube_video_id": "sOnqjkJTMaA",
                "webpage_url": "https://www.youtube.com/watch?v=sOnqjkJTMaA",
                "channel_id": "UCulYu1HEIa7f70L2lYZWHOw",
                "video_title": "Michael Jackson - Thriller (Official 4K Video)",
                "title": "Thriller",
                "artist": "Michael Jackson",
                "album": "Thriller",
                "start_offset_s": 252,
            })
            by_spotify = db.get_youtube_video_override({"spotify_id": "spotify-track-id"})
            by_isrc = db.get_youtube_video_override({"isrc": "USSM18200005"})
            by_name_only = db.get_youtube_video_override({"title": "Thriller", "artist": "Michael Jackson"})

        self.assertTrue(saved["ok"])
        self.assertEqual(by_spotify["youtube_video_id"], "sOnqjkJTMaA")
        self.assertEqual(by_isrc["start_offset_s"], 252)
        self.assertIsNone(by_name_only)

    def test_stats_fall_back_to_listening_events_when_derived_tables_are_empty(self):
        now = time.time()
        event = {
            "event_id": "evt-stats-1",
            "track_key": "track-stats-1",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "started_at": now,
            "ended_at": now + 120,
            "listened_ms": 120000,
            "duration_ms": 120000,
            "listened_percent": 100,
            "event_type": "complete",
            "reason": "",
            "metadata_json": """{
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
                "artwork_url": "https://example.com/cover.jpg",
                "genres": ["Rock", "Pop Rock"]
            }""",
            "created_at": now,
        }
        self.conn.execute("""
            INSERT INTO listening_events
                (event_id, track_key, title, artist, album, started_at, ended_at,
                 listened_ms, duration_ms, listened_percent, event_type, reason,
                 metadata_json, created_at)
            VALUES
                (:event_id, :track_key, :title, :artist, :album, :started_at, :ended_at,
                 :listened_ms, :duration_ms, :listened_percent, :event_type, :reason,
                 :metadata_json, :created_at)
        """, event)
        self.conn.commit()

        with patch.object(db, "_get_conn", return_value=self.conn):
            artists = db.get_top_listened_artists("month", limit=5)
            albums = db.get_top_listened_albums("month", limit=5)
            genres = db.get_top_genres("month", limit=5)

        self.assertEqual(artists["total"], 1)
        self.assertEqual(artists["items"][0]["artist_name"], "Artist")
        self.assertEqual(albums["total"], 1)
        self.assertEqual(albums["items"][0]["album"], "Album")
        self.assertEqual(genres["total"], 2)
        self.assertEqual(genres["items"][0]["listened_ms"], 120000)
        self.assertIn(genres["items"][0]["genre"], {"Rock", "Pop Rock"})

    def _play(self, track_key, title, artist, album, genres=None):
        event = {
            "event_id": f"evt-{track_key}",
            "track_key": track_key,
            "title": title,
            "artist": artist,
            "album": album,
            "event_type": "complete",
            "listened_ms": 180000,
            "duration_ms": 180000,
            "listened_percent": 100,
            "metadata": {"genres": genres or []},
        }
        with patch.object(db, "_get_conn", return_value=self.conn):
            db.process_listening_event(event)

    def test_delete_track_from_stats_cascades_to_artist_album_genre_tables(self):
        self._play("track-1", "Song One", "Artist", "Album", genres=["Rock"])
        self._play("track-2", "Song Two", "Artist", "Album", genres=["Rock"])

        with patch.object(db, "_get_conn", return_value=self.conn):
            deleted = db.delete_track_from_stats("track-1")

        self.assertGreater(deleted, 0)
        remaining_tracks = {r["track_key"] for r in self.conn.execute(
            "SELECT track_key FROM track_listen_stats_events").fetchall()}
        self.assertEqual(remaining_tracks, {"track-2"})
        for table in ("listening_events", "artist_listen_stats_events",
                      "album_listen_stats_events", "genre_listen_stats_events"):
            remaining = {r["track_key"] for r in self.conn.execute(f"SELECT track_key FROM {table}").fetchall()}
            self.assertNotIn("track-1", remaining)
            self.assertIn("track-2", remaining)

    def test_delete_track_from_stats_removes_it_from_top_listened_tracks(self):
        # get_top_listened_tracks reads listening_events directly, not
        # track_listen_stats_events (which nothing queries) — this is the
        # actual user-visible contract, not just an internal table check.
        self._play("track-1", "Song One", "Artist", "Album", genres=["Rock"])
        self._play("track-2", "Song Two", "Artist", "Album", genres=["Rock"])

        with patch.object(db, "_get_conn", return_value=self.conn):
            db.delete_track_from_stats("track-1")
            top_tracks = db.get_top_listened_tracks("all", limit=10)
            summary = db.get_stats_summary("all")

        keys = {item["track_key"] for item in top_tracks["items"]}
        self.assertNotIn("track-1", keys)
        self.assertIn("track-2", keys)
        self.assertEqual(summary["tracks_played"], 1)

    def test_delete_artist_from_stats_removes_every_track_they_are_credited_on(self):
        self._play("track-1", "Song One", "Artist", "Album", genres=["Rock"])
        self._play("track-2", "Song Two", "Artist", "Other Album", genres=["Rock"])
        self._play("track-3", "Song Three", "Other Artist", "Third Album", genres=["Jazz"])

        with patch.object(db, "_get_conn", return_value=self.conn):
            artist_key = self.conn.execute(
                "SELECT artist_key FROM artist_listen_stats_events WHERE track_key = 'track-1'"
            ).fetchone()["artist_key"]
            deleted = db.delete_artist_from_stats(artist_key)

        self.assertGreater(deleted, 0)
        for table in ("track_listen_stats_events", "artist_listen_stats_events",
                      "album_listen_stats_events", "genre_listen_stats_events"):
            remaining = {r["track_key"] for r in self.conn.execute(f"SELECT track_key FROM {table}").fetchall()}
            self.assertNotIn("track-1", remaining)
            self.assertNotIn("track-2", remaining)
            self.assertIn("track-3", remaining)

    def test_delete_album_from_stats_removes_every_track_on_it(self):
        self._play("track-1", "Song One", "Artist", "Album", genres=["Rock"])
        self._play("track-2", "Song Two", "Artist", "Other Album", genres=["Rock"])

        with patch.object(db, "_get_conn", return_value=self.conn):
            album_key = self.conn.execute(
                "SELECT album_key FROM album_listen_stats_events WHERE track_key = 'track-1'"
            ).fetchone()["album_key"]
            deleted = db.delete_album_from_stats(album_key)

        self.assertGreater(deleted, 0)
        for table in ("track_listen_stats_events", "artist_listen_stats_events",
                      "album_listen_stats_events", "genre_listen_stats_events"):
            remaining = {r["track_key"] for r in self.conn.execute(f"SELECT track_key FROM {table}").fetchall()}
            self.assertNotIn("track-1", remaining)
            self.assertIn("track-2", remaining)

    def test_init_db_adds_spotify_artist_id_to_a_pre_refactor_artist_affinity_table(self):
        # Simulate a database created before spotify_artist_id was added to the
        # artist_affinity CREATE TABLE statement — CREATE TABLE IF NOT EXISTS is
        # a no-op against it, so _init_db must backfill the column itself.
        old_conn = sqlite3.connect(":memory:")
        old_conn.row_factory = sqlite3.Row
        old_conn.execute("""
            CREATE TABLE artist_affinity (
                artist_key TEXT PRIMARY KEY,
                artist_name TEXT,
                score REAL DEFAULT 0,
                status TEXT DEFAULT 'neutral',
                total_plays INTEGER DEFAULT 0,
                total_skips INTEGER DEFAULT 0,
                total_completed INTEGER DEFAULT 0,
                total_listened_ms INTEGER DEFAULT 0,
                last_listened_at REAL,
                updated_at REAL NOT NULL
            )
        """)
        columns_before = {r["name"] for r in old_conn.execute("PRAGMA table_info(artist_affinity)").fetchall()}
        self.assertNotIn("spotify_artist_id", columns_before)

        db._init_db(old_conn)

        columns_after = {r["name"] for r in old_conn.execute("PRAGMA table_info(artist_affinity)").fetchall()}
        self.assertIn("spotify_artist_id", columns_after)
        with patch.object(db, "_get_conn", return_value=old_conn):
            result = db.update_artist_affinity({
                "artist": "Artist", "artist_id": "spotify-artist-1", "event_type": "complete", "listened_percent": 100,
            })
        self.assertEqual(result.get("spotify_artist_id"), "spotify-artist-1")
        old_conn.close()

    def test_a_broken_artist_affinity_update_does_not_fail_the_whole_event(self):
        # save_listening_event() already committed the event row by the time
        # update_artist_affinity() runs — a schema-drift exception there must
        # not turn an otherwise-successful write into ok:False for the caller.
        event = {
            "event_id": "evt-resilience-1",
            "track_key": "track-resilience-1",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "event_type": "complete",
            "listened_ms": 180000,
            "duration_ms": 180000,
            "listened_percent": 100,
        }
        with patch.object(db, "_get_conn", return_value=self.conn), \
             patch.object(db, "update_artist_affinity", side_effect=RuntimeError("no column named spotify_artist_id")):
            result = db.process_listening_event(event)

        self.assertTrue(result["ok"])
        self.assertEqual(result["artist_affinity"], {})
        stored = self.conn.execute(
            "SELECT * FROM listening_events WHERE event_id = ?", ("evt-resilience-1",)
        ).fetchone()
        self.assertIsNotNone(stored)

    def test_delete_from_stats_with_blank_key_is_a_noop(self):
        self._play("track-1", "Song One", "Artist", "Album", genres=["Rock"])
        with patch.object(db, "_get_conn", return_value=self.conn):
            self.assertEqual(db.delete_track_from_stats(""), 0)
            self.assertEqual(db.delete_artist_from_stats(""), 0)
            self.assertEqual(db.delete_album_from_stats(""), 0)
            count = self.conn.execute("SELECT COUNT(*) AS c FROM track_listen_stats_events").fetchone()["c"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
