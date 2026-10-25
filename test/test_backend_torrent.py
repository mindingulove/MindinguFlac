import unittest

import backend_torrent


class TestBackendTorrentHelpers(unittest.TestCase):
    def test_all_trackers_first_pass_calls_every_settings_provider(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import torrent_sources

        names = (
            "search_torlock", "search_torrentdownloads", "search_limetorrents",
            "search_1337x", "search_kickass", "search_solid", "search_knaben",
            "search_apibay",
        )
        patches = [patch.object(torrent_sources, name, return_value=[{"source": name}]) for name in names]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], \
                patch.object(torrent_sources, "torrentdownloads_category_from_metadata", return_value="5"), \
                patch.object(backend_torrent, "torrfetch", SimpleNamespace(
                    search_torrents=Mock(side_effect=lambda query, only: [{"source": only[0]}])
                )):
            results = backend_torrent._search_all_tracker_providers("artist album FLAC", {})

        self.assertEqual(
            set(results),
            {"torlock", "torrentdownloads", "limetorrents", "1337x", "kickass",
             "solidtorrents", "knaben", "apibay", "piratebay", "yts"},
        )
        self.assertEqual(results["1337x"][0]["source"], "search_1337x")
        self.assertEqual(results["piratebay"][0]["source"], "piratebay")
        self.assertEqual(results["yts"][0]["source"], "yts")

    def test_provider_fuzzy_filter_orders_by_seed_count_then_ratio(self):
        rows = backend_torrent._filter_and_rank_provider_results(
            {
                "1337x": [
                    {"title": "wrong release", "seeders": 999, "leechers": 1},
                    {"title": "wanted album", "seeders": 114, "leechers": 20},
                ],
                "torlock": [
                    {"title": "wanted album", "seeders": 6, "leechers": 2},
                ],
            },
            lambda row: 100 if row["title"] == "wanted album" else 0,
        )
        self.assertEqual([row["seeders"] for row in rows], [114, 6])
        self.assertTrue(all(row["_score"] == 100 for row in rows))

    def test_desktop_release_fuzzy_score_matches_android_for_1337x_electric_ladyland(self):
        import sys
        from pathlib import Path
        android_python = Path(__file__).resolve().parent.parent / "android-app" / "app" / "src" / "main" / "python"
        if str(android_python) not in sys.path:
            sys.path.insert(0, str(android_python))
        from android_runtime.torrent_backend import _score as android_score

        candidate = {
            "title": "The Jimi Hendrix Experience - Electric Ladyland (50th Anniversary Deluxe Edition) (2018) [3CD] FLAC",
            "category": "Audio",
            "seeders": 193,
            "leechers": 101,
        }
        desktop = backend_torrent._android_parity_torrent_score(
            candidate, "Jimi Hendrix", "Come On Let the Good Times Roll", "Electric Ladyland"
        )
        mobile = android_score(
            candidate, "Jimi Hendrix", "Come On Let the Good Times Roll", "Electric Ladyland"
        )
        self.assertGreater(desktop, 0)
        self.assertEqual(desktop, mobile)

    def test_desktop_android_parity_rejects_album_hit_without_artist_match(self):
        candidate = {
            "title": "Electric Ladyland (50th Anniversary Deluxe Edition) FLAC",
            "category": "Audio",
            "seeders": 193,
        }
        self.assertEqual(
            backend_torrent._android_parity_torrent_score(
                candidate, "Jimi Hendrix", "Come On Let the Good Times Roll", "Electric Ladyland"
            ),
            -1.0,
        )

    def test_large_swarm_beats_tiny_zero_leecher_ratio_swarm(self):
        rows = backend_torrent._filter_and_rank_provider_results(
            {"1337x": [
                {"title": "wanted album", "seeders": 3, "leechers": 0},
                {"title": "wanted album", "seeders": 193, "leechers": 101},
            ]},
            lambda row: 100,
        )
        self.assertEqual([row["seeders"] for row in rows], [193, 3])

    def test_provider_candidates_with_zero_seeders_are_excluded(self):
        rows = backend_torrent._filter_and_rank_provider_results(
            {"1337x": [
                {"title": "wanted album", "seeders": 0, "leechers": 50},
                {"title": "wanted album", "seeders": 193, "leechers": 101},
            ]},
            lambda row: 100,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seeders"], 193)

    def test_album_similarity_ignores_requested_track_and_feature_words(self):
        score = backend_torrent._album_similarity_without_track_words(
            "Electric Ladyland feat. Jimi Hendrix",
            "The Jimi Hendrix Experience - Electric Ladyland - Voodoo Chile feat. Guest Artist [3CD FLAC]",
            "Voodoo Chile feat. Guest Artist",
        )
        self.assertGreaterEqual(score, 85)

    def test_album_similarity_rejects_unrelated_release_title(self):
        score = backend_torrent._album_similarity_without_track_words(
            "Electric Ladyland",
            "The Jimi Hendrix Experience - Axis Bold as Love - Voodoo Chile",
            "Voodoo Chile",
        )
        self.assertLess(score, 85)

    def test_same_name_album_and_title_require_the_track_in_the_filename(self):
        album = backend_torrent._clean_torrent_album_title("Eye In The Sky (Expanded Edition)")
        self.assertEqual(album, "Eye In The Sky")
        self.assertEqual(
            backend_torrent._track_filename_match_ratio(
                "Eye In The Sky", "01. Eye In The Sky.flac",
                "The Alan Parsons Project/Eye In The Sky", album,
            ),
            1.0,
        )

    def test_album_folder_cannot_make_sirius_match_eye_in_the_sky(self):
        self.assertLess(
            backend_torrent._track_filename_match_ratio(
                "Eye In The Sky", "01. Sirius (Instrumental).flac",
                "The Alan Parsons Project/Eye In The Sky", "Eye In The Sky",
            ),
            0.85,
        )

    def test_same_name_album_still_allows_other_tracks_from_that_release(self):
        self.assertEqual(
            backend_torrent._track_filename_match_ratio(
                "Sirius", "01. Sirius.flac",
                "The Alan Parsons Project/Eye In The Sky", "Eye In The Sky",
            ),
            1.0,
        )

    def test_registration_disables_unrequested_album_files_from_the_start(self):
        if backend_torrent.lt is None:
            self.skipTest("desktop torrent registration now uses the shared jlibtorrent JNI engine")
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        lt = backend_torrent.lt
        metadata = lt.torrent_info(lt.bencode({
            "info": {"name": "album", "piece length": 16384, "pieces": bytes(20),
                     "files": [{"length": 4000, "path": ["one.flac"]},
                               {"length": 4000, "path": ["two.flac"]}]}}))
        handle = SimpleNamespace(is_valid=lambda: True)
        captured = []
        session = SimpleNamespace(add_torrent=lambda params: (captured.append(params) or handle))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(backend_torrent, "_GLOBAL_SES", session), \
                patch.object(backend_torrent, "_ACTIVE_SESSIONS", {}), \
                patch.object(backend_torrent, "_torrent_info_from_url", return_value=metadata), \
                patch.object(lt, "add_magnet_uri", side_effect=lambda ses, magnet, params: (captured.append(params) or handle)):
            backend_torrent._register_job_to_torrent("magnet:direct", "one", Path(directory), None, "https://metadata")
            self.assertEqual(captured[0].file_priorities, [0, 0])
            self.assertTrue(captured[0].flags & lt.torrent_flags.default_dont_download)
            backend_torrent._register_job_to_torrent("magnet:dht", "two", Path(directory), None)
            self.assertTrue(captured[1]["flags"] & lt.torrent_flags.default_dont_download)

    def test_streamable_bytes_stop_at_first_missing_piece(self):
        from types import SimpleNamespace
        info = SimpleNamespace(
            map_file=lambda *args: SimpleNamespace(piece=2, start=4096),
            piece_length=lambda: 16384,
            file_at=lambda _: SimpleNamespace(size=40000),
        )
        handle = SimpleNamespace(have_piece=lambda piece: piece in {2, 4})
        self.assertEqual(backend_torrent._torrent_contiguous_ready(handle, info, 0), 12288)
        handle.have_piece = lambda piece: piece in {3, 4}
        self.assertEqual(backend_torrent._torrent_contiguous_ready(handle, info, 0), 0)
        handle.have_piece = lambda piece: True
        self.assertEqual(backend_torrent._torrent_contiguous_ready(handle, info, 0), 40000)

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
        if backend_torrent._GLOBAL_SES is None:
            self.skipTest("legacy Python-libtorrent session cleanup was replaced by the shared JNI engine")
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


class TestRollingTorrentRace(unittest.TestCase):
    def test_http_metadata_fetches_run_concurrently_outside_session_lock(self):
        if backend_torrent.lt is None:
            self.skipTest("legacy Python-libtorrent registration was replaced by the shared JNI engine")
        import concurrent.futures
        import tempfile
        import threading
        from pathlib import Path
        from unittest.mock import Mock, patch
        barrier = threading.Barrier(3)
        def metadata(_url):
            barrier.wait(timeout=2)
            return None
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(backend_torrent._ACTIVE_SESSIONS, {}, clear=True), \
                patch.object(backend_torrent, "_torrent_info_from_url", side_effect=metadata), \
                patch.object(backend_torrent.lt, "add_magnet_uri", side_effect=lambda *args: Mock()):
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                futures = [pool.submit(
                    backend_torrent._register_job_to_torrent,
                    f"magnet:?xt=urn:btih:test{index}", "job", Path(directory) / str(index),
                    None, f"https://provider.invalid/{index}.torrent",
                ) for index in range(3)]
                for future in futures:
                    self.assertIsNotNone(future.result(timeout=3)[0])

    def test_failed_middle_slot_refills_before_slow_first_slot_finishes(self):
        queue = iter(["slow", "dead", "slow2", "working"])
        started, cleaned = [], []
        def start(candidate):
            started.append(candidate)
            return candidate
        def poll(candidate):
            if candidate == "dead":
                return False
            if candidate == "working":
                return 32000
            return None
        race = backend_torrent._rolling_torrent_race(
            lambda: next(queue, None), start, poll, cleaned.append, lambda: False,
            sleep=lambda _: self.fail("must refill the failed slot immediately"),
        )
        try:
            self.assertEqual(next(race), "working")
            self.assertEqual(started, ["slow", "dead", "slow2", "working"])
            self.assertEqual(cleaned, ["dead"])
        finally:
            race.close()
        self.assertCountEqual(cleaned, ["dead", "slow", "slow2"])

    def test_fastest_bytes_win_even_when_ranked_last(self):
        queue = iter([100, 1000, 5000])
        cleaned = []
        race = backend_torrent._rolling_torrent_race(
            lambda: next(queue, None), lambda x: x, lambda x: x,
            cleaned.append, lambda: False,
        )
        self.assertEqual(next(race), 5000)
        race.close()
        self.assertCountEqual(cleaned, [100, 1000])

    def test_fallback_remains_alive_when_first_winner_later_fails(self):
        queue = iter(["a", "b", "c", "d"])
        started = []
        def start(item):
            started.append(item)
            return item
        race = backend_torrent._rolling_torrent_race(
            lambda: next(queue, None), start,
            lambda item: {"a": 300, "b": 200, "c": 100, "d": 1}[item],
            lambda _: None, lambda: False,
        )
        self.assertEqual(next(race), "a")
        self.assertEqual(next(race), "b")
        self.assertEqual(started, ["a", "b", "c", "d"])
        race.close()

    def test_promotion_expands_prefetch_slots(self):
        from types import SimpleNamespace
        config = SimpleNamespace(torrent_playback_candidates=5, torrent_prefetch_candidates=1)
        job = {"prefetch": True}
        queue = iter(range(10))
        started = []
        def start(item):
            started.append(item)
            return item
        def poll(item):
            job["prefetch"] = False
            return 1
        race = backend_torrent._rolling_torrent_race(
            lambda: next(queue, None), start, poll, lambda _: None, lambda: False,
            slots=lambda: backend_torrent._torrent_race_slots(config, job["prefetch"]),
        )
        next(race)
        self.assertEqual(len(started), 1)
        next(race)
        self.assertEqual(len(started), 6)
        race.close()

    def test_cancellation_cleans_pending_candidates(self):
        queue = iter([1, 2, 3])
        cancelled = [False]
        cleaned = []
        race = backend_torrent._rolling_torrent_race(
            lambda: next(queue, None), lambda x: x, lambda _: None,
            cleaned.append, lambda: cancelled[0],
            sleep=lambda _: cancelled.__setitem__(0, True),
        )
        with self.assertRaisesRegex(RuntimeError, "Cancelled"):
            next(race)
        self.assertCountEqual(cleaned, [1, 2, 3])


class TestTorrentSettings(unittest.TestCase):
    def test_album_source_key_ignores_release_edition_noise_and_keeps_legacy_key(self):
        stable, legacy = backend_torrent._album_source_keys(
            "The Jimi Hendrix Experience", "Electric Ladyland (50th Anniversary Deluxe Edition)",
        )
        same, _ = backend_torrent._album_source_keys(
            "Jimi Hendrix Experience", "Electric Ladyland",
        )
        self.assertEqual(stable, same)
        self.assertEqual(legacy, "the jimi hendrix experience||electric ladyland (50th anniversary deluxe edition)")

    def test_counts_roundtrip_to_disk_and_old_configs_get_defaults(self):
        import tempfile
        from pathlib import Path
        from config import AppConfig, load_config, save_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = AppConfig.from_public_dict({"torrent_playback_candidates": 5, "torrent_prefetch_candidates": 1})
            save_config(path, config)
            actual = load_config(path)
            self.assertEqual(actual.torrent_playback_candidates, 5)
            self.assertEqual(actual.torrent_prefetch_candidates, 1)
        old = AppConfig.from_public_dict({})
        self.assertEqual((old.torrent_playback_candidates, old.torrent_prefetch_candidates), (3, 2))
    def test_invalid_counts_cannot_overload_or_disable_racing(self):
        from config import AppConfig
        for value, expected in [(0, 1), (99, 8), (None, 3), ("bad", 3)]:
            with self.subTest(value=value):
                actual = AppConfig.from_public_dict({"torrent_playback_candidates": value})
                self.assertEqual(actual.torrent_playback_candidates, expected)


if __name__ == "__main__":
    unittest.main()
