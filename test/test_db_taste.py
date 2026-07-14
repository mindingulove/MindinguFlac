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


if __name__ == "__main__":
    unittest.main()
