import unittest

import backend_torrent


class TestBackendTorrentHelpers(unittest.TestCase):
    def test_torrent_num_files_handles_missing_metadata(self):
        self.assertEqual(backend_torrent._torrent_num_files(None), 0)

    def test_torrent_num_files_handles_bad_objects(self):
        class BrokenInfo:
            def num_files(self):
                raise RuntimeError("boom")

        self.assertEqual(backend_torrent._torrent_num_files(BrokenInfo()), 0)

    def test_adult_content_filter_blocks_unrelated_terms(self):
        allowed = backend_torrent._adult_terms_in_text("Lucky Man Trilogy")

        self.assertTrue(
            backend_torrent._has_disallowed_adult_content(
                "EverythingBut Charlotte Sins Rocky Emerson XXX XviD.avi",
                allowed,
            )
        )
        self.assertTrue(
            backend_torrent._has_disallowed_adult_content(
                "SlutInspection Tall Slut Rocky Emerson Gets Creampie",
                allowed,
            )
        )

    def test_adult_content_filter_allows_requested_music_title_term(self):
        allowed = backend_torrent._adult_terms_in_text("Sex on Fire Only By The Night")

        self.assertFalse(
            backend_torrent._has_disallowed_adult_content("Kings of Leon - Sex on Fire.flac", allowed)
        )
        self.assertTrue(
            backend_torrent._has_disallowed_adult_content("Random Sexcapade XXX 1080p", allowed)
        )

    def test_video_torrent_marker_blocks_video_releases(self):
        self.assertTrue(backend_torrent._has_video_torrent_marker("release.1080p.x264.mkv"))
        self.assertTrue(backend_torrent._has_video_torrent_marker("clip.avi"))
        self.assertFalse(backend_torrent._has_video_torrent_marker("Emerson Lake Palmer Trilogy.flac"))

    def test_blocks_prefetch_adult_video_names_from_screenshot(self):
        allowed = backend_torrent._adult_terms_in_text(
            "Still...You Turn Me On Brain Salad Surgery Emerson Lake Palmer"
        )

        bad_names = [
            "EverythingBut.24.07.10.Charlotte.Sins.And.Rocky.Emerson.XXX.XviD-iPT.Team.avi",
            "OnlyBBC - Rocky Emerson - Tall Tatted Rocky Rides Big Black Cock.mp4",
            "SlutInspection.24.07.17.Tall.Slut.Rocky.Emerson.Gets.Creampie.From.My.Husband.XXX.1080p.HEVC.x265.mkv",
        ]
        for name in bad_names:
            with self.subTest(name=name):
                self.assertTrue(backend_torrent._has_disallowed_adult_content(name, allowed))
                self.assertTrue(backend_torrent._has_video_torrent_marker(name))


class TestSharedSessionCleanup(unittest.TestCase):
    """A same-album prefetch and the active track resolve to the same magnet and
    share one handle/_race dir. Unregistering one job must NOT report the files as
    deletable while another job still downloads them, or the live download stalls
    ("no byte progress"/"stalled during streaming")."""

    def setUp(self):
        self._orig_key = backend_torrent._torrent_key
        self._orig_remove = backend_torrent._GLOBAL_SES.remove_torrent
        backend_torrent._torrent_key = lambda m: "SHAREDKEY"
        backend_torrent._GLOBAL_SES.remove_torrent = lambda h: None

        class _Handle:
            def is_valid(self):
                return True

        backend_torrent._ACTIVE_SESSIONS["SHAREDKEY"] = {
            "handle": _Handle(),
            "refs": {"jobA", "jobB"},
            "save_path": "/tmp/race",
        }

    def tearDown(self):
        backend_torrent._torrent_key = self._orig_key
        backend_torrent._GLOBAL_SES.remove_torrent = self._orig_remove
        backend_torrent._ACTIVE_SESSIONS.pop("SHAREDKEY", None)

    def test_unregister_keeps_files_while_other_job_holds_ref(self):
        # First job leaves; another still downloads -> files must be kept.
        self.assertFalse(backend_torrent._unregister_job_from_torrent("magnet:x", "jobA"))
        self.assertIn("SHAREDKEY", backend_torrent._ACTIVE_SESSIONS)
        # Last job leaves -> now safe to delete and entry is gone.
        self.assertTrue(backend_torrent._unregister_job_from_torrent("magnet:x", "jobB"))
        self.assertNotIn("SHAREDKEY", backend_torrent._ACTIVE_SESSIONS)

    def test_unregister_unknown_magnet_is_deletable(self):
        backend_torrent._ACTIVE_SESSIONS.pop("SHAREDKEY", None)  # nothing registered
        self.assertTrue(backend_torrent._unregister_job_from_torrent("magnet:gone", "jobZ"))


class TestPrefetchTorrentGate(unittest.TestCase):
    def test_active_job_is_never_gated(self):
        # Exhaust all prefetch slots, then confirm an active (non-prefetch) job
        # still passes straight through and is never blocked by prefetch.
        held = [backend_torrent._PREFETCH_TORRENT_GATE.acquire() for _ in range(backend_torrent._PREFETCH_TORRENT_SLOTS)]
        try:
            with backend_torrent.prefetch_torrent_gate({"prefetch": False}):
                pass  # must not block
        finally:
            for _ in held:
                backend_torrent._PREFETCH_TORRENT_GATE.release()

    def test_prefetch_promoted_mid_wait_stops_waiting(self):
        # A prefetch job blocked behind a full gate must proceed the instant it is
        # promoted to the active track (job['prefetch'] cleared), so adopting a
        # prefetched track to play it now never strands it behind the throttle.
        import threading
        import time as _time

        held = [backend_torrent._PREFETCH_TORRENT_GATE.acquire() for _ in range(backend_torrent._PREFETCH_TORRENT_SLOTS)]
        job = {"prefetch": True}
        entered = threading.Event()

        def worker():
            with backend_torrent.prefetch_torrent_gate(job):
                entered.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            self.assertFalse(entered.wait(timeout=0.5), "should be blocked while slots are full")
            job["prefetch"] = False  # promote_job clears this under the lock in prod
            self.assertTrue(entered.wait(timeout=2.0), "promoted job must stop waiting and proceed")
        finally:
            for _ in held:
                backend_torrent._PREFETCH_TORRENT_GATE.release()
            t.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
