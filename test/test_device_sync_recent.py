"""Recent rows sync between devices without coming back as duplicates."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app
import db
import device_sync


class RecentEchoTests(unittest.TestCase):
    def manager(self, jobs):
        return SimpleNamespace(_lock=threading.RLock(), jobs=jobs, _save_jobs=lambda: None)

    def snapshot(self, recent):
        return {"schema": device_sync.PROTOCOL, "recent": recent}

    def apply(self, manager, recent, local_id="desk"):
        with patch.object(app, "service_downloader", manager), patch.object(db, "sync_import", return_value=0):
            return device_sync._apply_snapshot(self.snapshot(recent), "phone", local_id)

    def test_own_rows_sent_back_are_not_imported_again(self):
        manager = self.manager({"job1": {"id": "job1", "status": "finished", "title": "Song"}})
        self.apply(manager, [{"sync_id": "desk:job1", "title": "Song"},
                             {"sync_id": "phone:j9", "title": "Phone song"}])
        titles = sorted(job["title"] for job in manager.jobs.values())
        self.assertEqual(titles, ["Phone song", "Song"])

    def test_earlier_echoes_are_removed_and_hiding_still_syncs(self):
        manager = self.manager({
            "job1": {"id": "job1", "status": "finished", "title": "Song"},
            "sync-old": {"id": "sync-old", "sync_id": "desk:job1", "status": "finished", "title": "Song"},
            "sync-gone": {"id": "sync-gone", "sync_id": "desk:removed", "status": "finished", "title": "Removed"},
        })
        self.apply(manager, [{"sync_id": "desk:job1", "title": "Song", "hidden_from_recent": True}])
        self.assertEqual(list(manager.jobs), ["job1"])
        self.assertTrue(manager.jobs["job1"]["hidden_from_recent"])


if __name__ == "__main__":
    unittest.main()
