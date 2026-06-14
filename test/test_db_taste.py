import sqlite3
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


if __name__ == "__main__":
    unittest.main()
