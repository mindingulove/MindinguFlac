"""Focused tests for the Android port's configuration, routing and streaming.

These run on the desktop interpreter, so every probe that would touch the
phone's Java bridge or its packaged wheels is patched. What is under test is
the *decision* logic: which engines the phone offers, what it clamps a request
to, how the native torrent bridge's JSON contract is consumed, and that the
audio range endpoint answers correctly. Whether the packaged runtimes import
on the device is a separate, measured check (see android-app/README.md).
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
ANDROID_PYTHON = REPO_ROOT / "android-app" / "app" / "src" / "main" / "python"
for entry in (str(REPO_ROOT), str(ANDROID_PYTHON)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from android_runtime import capabilities  # noqa: E402
from android_runtime import torrent_backend  # noqa: E402


def _engines(torrent=True, youtube=True, spotiflac=False):
    """A capability report shaped like the real one, without probing."""
    return {
        "ytp-dl": {
            "label": "YouTube audio",
            "available": youtube,
            "reason": "" if youtube else "yt-dlp missing",
            "services": ["youtube"],
            "qualities": ["best", "m4a"],
            "lossless": False,
        },
        "torrent": {
            "label": "Torrent (Experimental)",
            "available": torrent,
            "reason": "" if torrent else "jlibtorrent native library failed to load",
            "services": ["all", "torlock", "torrentdownloads", "limetorrents", "1337x", "kickass"],
            "qualities": ["LOSSLESS", "MP3"],
            "lossless": True,
        },
        "spotiflac": {
            "label": "SpotiFLAC",
            "available": spotiflac,
            "reason": "" if spotiflac else "needs a provider extension",
            "services": ["tidal", "qobuz", "deezer", "amazon"],
            "qualities": ["LOSSLESS"],
            "lossless": True,
        },
        "monochrome": {"label": "Monochrome (FLAC)", "available": True, "reason": "",
                       "services": ["monochrome"], "qualities": ["LOSSLESS"], "lossless": True},
    }


def _report(**kwargs):
    engines = _engines(**kwargs)
    return {
        "android": True,
        "dependencies": {"runtimes": {}, "missing": [], "ok": True},
        "engines": engines,
        "available_engines": [name for name, entry in engines.items() if entry["available"]],
        "storage_root": "/storage/Mindinguflac",
    }


class AndroidCapabilityReportTest(unittest.TestCase):
    def setUp(self):
        capabilities._cache = None
        self.addCleanup(setattr, capabilities, "_cache", None)

    def test_torrent_engine_is_unavailable_without_the_native_library(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "_probe_import", return_value=(True, "ok")), \
                patch.object(capabilities, "_native_torrent_status",
                             return_value={"ok": False, "error": "UnsatisfiedLinkError"}), \
                patch.object(capabilities, "_spotiflac_provider_status",
                             return_value={"ok": False, "error": "no provider"}):
            engines = capabilities.engine_availability()

        self.assertFalse(engines["torrent"]["available"])
        self.assertIn("UnsatisfiedLinkError", engines["torrent"]["reason"])
        self.assertTrue(engines["ytp-dl"]["available"])

    def test_torrent_engine_is_available_when_every_probe_passes(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "_probe_import", return_value=(True, "ok")), \
                patch.object(capabilities, "_native_torrent_status",
                             return_value={"ok": True, "jlibtorrent_version": "2.0.12.9"}), \
                patch.object(capabilities, "_spotiflac_provider_status",
                             return_value={"ok": False, "error": "no provider"}):
            engines = capabilities.engine_availability()

        self.assertTrue(engines["torrent"]["available"])
        self.assertEqual(engines["torrent"]["reason"], "")
        self.assertEqual(engines["torrent"]["qualities"], ["LOSSLESS", "MP3"])

    def test_monochrome_is_available_on_android_without_a_browser_runtime(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "_probe_import", return_value=(True, "ok")), \
                patch.object(capabilities, "_native_torrent_status", return_value={"ok": True}), \
                patch.object(capabilities, "_spotiflac_provider_status", return_value={"ok": True}):
            engines = capabilities.engine_availability()

        self.assertTrue(engines["monochrome"]["available"])
        self.assertEqual(engines["monochrome"]["services"], ["monochrome"])
        self.assertIn("qobuz-dlp", engines)
        self.assertFalse(engines["qobuz-dlp"]["available"])

    def test_spotiflac_stays_off_without_node_or_a_python_provider_extension(self):
        with patch.object(capabilities, "_probe_import", return_value=(True, "ok")), \
                patch.object(capabilities.shutil, "which", return_value=None):
            status = capabilities._spotiflac_provider_status()

        self.assertFalse(status["ok"])
        self.assertIn("provider extension", status["error"])
        self.assertFalse(status["node"])

    def test_dependency_manifest_lists_every_runtime_that_failed_to_import(self):
        def probe(name):
            if name in {"yt_dlp", "SpotiFLAC"}:
                return False, "ModuleNotFoundError: nope"
            return True, "ok"

        with patch.object(capabilities, "_probe_import", side_effect=probe), \
                patch.object(capabilities, "_module_version", return_value="1.0"):
            manifest = capabilities.dependency_manifest()

        self.assertFalse(manifest["ok"])
        self.assertEqual(manifest["missing"], ["SpotiFLAC", "yt_dlp"])
        self.assertEqual(manifest["runtimes"]["mutagen"]["version"], "1.0")
        self.assertIn("used_for", manifest["runtimes"]["mutagen"])

    def test_default_engine_prefers_monochrome_then_youtube_and_torrent(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(capabilities.default_engine(), "monochrome")
        with patch.object(capabilities, "runtime_report", return_value=_report(youtube=False)):
            self.assertEqual(capabilities.default_engine(), "monochrome")

    def test_runtime_report_is_cached_until_refresh_is_requested(self):
        calls = []

        def engines():
            calls.append(1)
            return _engines()

        with patch.object(capabilities, "engine_availability", side_effect=engines), \
                patch.object(capabilities, "dependency_manifest",
                             return_value={"runtimes": {}, "missing": [], "ok": True}):
            capabilities.runtime_report()
            capabilities.runtime_report()
            self.assertEqual(len(calls), 1)
            capabilities.runtime_report(refresh=True)
            self.assertEqual(len(calls), 2)


class AndroidEngineClampTest(unittest.TestCase):
    def test_monochrome_engine_keeps_its_provider_and_lossless_quality(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(
                capabilities.clamp_choice("monochrome", "monochrome", "LOSSLESS"),
                ("monochrome", "monochrome", "LOSSLESS"),
            )

    def test_an_available_engine_keeps_a_service_and_quality_it_supports(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(
                capabilities.clamp_choice("torrent", "1337x", "LOSSLESS"),
                ("torrent", "1337x", "LOSSLESS"),
            )

    def test_an_unsupported_service_or_quality_is_replaced_not_passed_through(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            # piratebay and yts exist on desktop but the Android torrent
            # backend does not implement them; AAC is not a supported quality.
            self.assertEqual(
                capabilities.clamp_choice("torrent", "piratebay", "AAC"),
                ("torrent", "all", "LOSSLESS"),
            )

    def test_youtube_never_inherits_a_flac_quality_label(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            engine, service, quality = capabilities.clamp_choice("ytp-dl", "tidal", "LOSSLESS")
        self.assertEqual((engine, service), ("ytp-dl", "youtube"))
        self.assertNotEqual(quality, "LOSSLESS")
        self.assertIn(quality, {"best", "m4a"})

    def test_a_saved_torrent_engine_survives_when_the_native_library_is_present(self):
        with patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(
                capabilities.clamp_choice("torrent", "all", "LOSSLESS")[0], "torrent")

    def test_a_saved_torrent_engine_is_rewritten_when_jlibtorrent_is_missing(self):
        with patch.object(capabilities, "runtime_report", return_value=_report(torrent=False)):
            self.assertEqual(
                capabilities.clamp_choice("torrent", "all", "LOSSLESS"),
                ("monochrome", "monochrome", "LOSSLESS"),
            )


class AndroidWarmRestartAuthTest(unittest.TestCase):
    """A warm Activity-only restart must adopt its new token, not keep the old one.

    The Python interpreter and HTTP server survive an Activity recreate within
    the same process — Android reclaiming the Activity under memory pressure
    without killing the process, common after repeated open/close. Java always
    generates a fresh per-launch token and cookie regardless of whether this
    happens; bootstrap.start() has to make the server adopt it, or every
    authenticated request — search, downloads, and the stream endpoint
    playback depends on — starts failing with 401 against a cookie the server
    no longer recognizes, with nothing distinguishing it from any other
    playback failure.
    """

    def test_a_second_start_call_adopts_its_new_token(self):
        import tempfile
        import urllib.error
        import urllib.request

        from android_runtime import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            files = str(Path(tmp) / "files")
            cache = str(Path(tmp) / "cache")
            music = str(Path(tmp) / "music")
            # Settings validation is covered elsewhere; skip it here so this
            # test stays about token adoption only. `app`'s module-level
            # config path is computed once, the first time it is imported in
            # the process, so whichever test imports it first under a real
            # (non-Android) environment permanently fixes it for every test
            # that runs after — coupling this test to _preflight's settings
            # check would make it depend on suite ordering it has no control
            # over.
            with patch.object(capabilities, "runtime_report", return_value=_report()), \
                    patch.object(bootstrap, "_preflight", lambda *a, **k: None):
                port_cold = bootstrap.start(files, cache, music, "token-one")
                try:
                    port_warm = bootstrap.start(files, cache, music, "token-two")

                    def health(token):
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{port_warm}/api/health",
                            headers={"X-Mindinguflac-Token": token},
                        )
                        try:
                            with urllib.request.urlopen(request, timeout=3) as response:
                                return response.status
                        except urllib.error.HTTPError as exc:
                            return exc.code

                    self.assertEqual(port_warm, port_cold)
                    self.assertEqual(health("token-two"), 200)
                    self.assertEqual(health("token-one"), 401)
                finally:
                    bootstrap.stop()


class AndroidBootstrapConfigTest(unittest.TestCase):
    def _write_config(self, directory: Path, value: dict) -> Path:
        path = directory / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_initialize_config_keeps_an_available_engine_and_unrelated_keys(self):
        import tempfile

        from android_runtime import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            config_path = self._write_config(data, {
                "download_engine": "torrent",
                "download_service": "1337x",
                "default_quality": "LOSSLESS",
                "volume": 0.42,
            })
            with patch.object(capabilities, "runtime_report", return_value=_report()):
                bootstrap._initialize_config(data, Path(tmp) / "cache", Path(tmp) / "music")
            saved = json.loads(config_path.read_text("utf-8"))

        self.assertEqual(saved["download_engine"], "torrent")
        self.assertEqual(saved["download_service"], "1337x")
        self.assertEqual(saved["default_quality"], "LOSSLESS")
        self.assertEqual(saved["volume"], 0.42)
        self.assertEqual(saved["ai_provider"], "android")
        self.assertEqual(saved["cache_dir"], str(Path(tmp) / "cache"))
        self.assertEqual(saved["music_dir"], str(Path(tmp) / "music"))

    def test_initialize_config_rewrites_an_engine_whose_runtime_is_absent(self):
        import tempfile

        from android_runtime import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            config_path = self._write_config(data, {
                "download_engine": "torrent",
                "download_service": "1337x",
                "default_quality": "LOSSLESS",
            })
            with patch.object(capabilities, "runtime_report", return_value=_report(torrent=False)):
                bootstrap._initialize_config(data, Path(tmp) / "cache", Path(tmp) / "music")
            saved = json.loads(config_path.read_text("utf-8"))

        self.assertEqual(saved["download_engine"], "monochrome")
        self.assertEqual(saved["download_service"], "monochrome")
        self.assertEqual(saved["default_quality"], "LOSSLESS")

    def test_initialize_config_survives_a_corrupt_config_file(self):
        import tempfile

        from android_runtime import bootstrap

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / "config.json").write_text("{not json", encoding="utf-8")
            with patch.object(capabilities, "runtime_report", return_value=_report()):
                bootstrap._initialize_config(data, Path(tmp) / "cache", Path(tmp) / "music")
            saved = json.loads((data / "config.json").read_text("utf-8"))

        self.assertEqual(saved["download_engine"], "monochrome")


class AndroidSettingsSanitizerTest(unittest.TestCase):
    def test_sanitizer_clamps_the_engine_and_pins_phone_managed_storage(self):
        import app
        from config import AppConfig

        config = AppConfig()
        config.download_engine = "monochrome"
        config.download_service = "monochrome"
        config.default_quality = "LOSSLESS"
        config.ai_provider = "duckai"

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            sanitized = app._sanitize_runtime_config(config)

        self.assertEqual(sanitized.download_engine, "monochrome")
        self.assertEqual(sanitized.download_service, "monochrome")
        self.assertEqual(sanitized.default_quality, "LOSSLESS")
        self.assertEqual(sanitized.ai_provider, "android")
        self.assertEqual(sanitized.cache_dir, app.default_cache_dir())
        self.assertEqual(sanitized.music_dir, app.default_music_dir())

    def test_sanitizer_keeps_a_torrent_selection_the_phone_can_run(self):
        import app
        from config import AppConfig

        config = AppConfig()
        config.download_engine = "torrent"
        config.download_service = "torlock"
        config.default_quality = "MP3"

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            sanitized = app._sanitize_runtime_config(config)

        self.assertEqual(sanitized.download_engine, "torrent")
        self.assertEqual(sanitized.download_service, "torlock")
        self.assertEqual(sanitized.default_quality, "MP3")

    def test_runtime_endpoint_report_is_the_measured_android_one(self):
        import app

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()) as probe:
            report = app.runtime_capability_report(refresh=True)

        probe.assert_called_once_with(refresh=True)
        self.assertTrue(report["android"])
        self.assertIn("torrent", report["engines"])
        self.assertNotIn("ed2k", report["engines"]["torrent"]["services"])
        self.assertNotIn("ed2k", report["engines"])
        self.assertIn("monochrome", report["engines"])

    def test_runtime_endpoint_report_on_desktop_does_not_probe_android(self):
        import app

        with patch.dict(os.environ, {}, clear=True):
            report = app.runtime_capability_report()

        self.assertFalse(report["android"])
        self.assertIn("spotiflac", report["available_engines"])


class AndroidDownloadRoutingTest(unittest.TestCase):
    def _manager(self, engine="ytp-dl", service="youtube", quality="m4a"):
        import service_downloader

        manager = service_downloader.ServiceDownloadManager.__new__(
            service_downloader.ServiceDownloadManager)
        manager.config = SimpleNamespace(
            download_engine=engine, download_service=service, default_quality=quality)
        return manager

    def test_a_payload_naming_a_desktop_engine_is_clamped_on_android(self):
        manager = self._manager()
        payload = {"engine": "spotiflac", "service": "tidal", "quality": "LOSSLESS"}

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(manager._requested_engine(payload), ("monochrome", "monochrome", "LOSSLESS"))

    def test_a_payload_is_left_alone_on_desktop(self):
        manager = self._manager(engine="spotiflac", service="tidal", quality="LOSSLESS")
        payload = {"engine": "spotiflac", "service": "tidal", "quality": "LOSSLESS"}

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(manager._requested_engine(payload), ("spotiflac", "tidal", "LOSSLESS"))

    def test_an_empty_payload_falls_back_to_the_saved_phone_settings(self):
        manager = self._manager(engine="torrent", service="torlock", quality="LOSSLESS")

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            self.assertEqual(manager._requested_engine({}), ("torrent", "torlock", "LOSSLESS"))

    def test_the_job_built_from_a_payload_carries_the_clamped_engine(self):
        manager = self._manager()
        manager.config.download_engine = "ytp-dl"
        payload = {
            "engine": "monochrome",
            "service": "monochrome",
            "quality": "LOSSLESS",
            "metadata": {"artist": "Daft Punk", "title": "Veridis Quo", "album": "Discovery"},
        }

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            job = manager._job_from_payload(payload, mode="stream")

        self.assertEqual(job["engine"], "monochrome")
        self.assertEqual(job["service"], "monochrome")
        self.assertEqual(job["quality"], "LOSSLESS")
        self.assertEqual(job["title"], "Veridis Quo")

    def test_android_torrent_jobs_route_to_the_native_bridge(self):
        import backend_torrent

        calls = []
        with patch.object(backend_torrent, "_IS_ANDROID", True), \
                patch.object(torrent_backend, "run", side_effect=lambda *a: calls.append(a)):
            backend_torrent.run(Path("/tmp/out"), {"id": "job-1"}, object())

        self.assertEqual(len(calls), 1)

    def test_cancelling_an_android_torrent_job_releases_the_native_handle(self):
        import backend_torrent

        cancelled = []
        with patch.object(backend_torrent, "_IS_ANDROID", True), \
                patch.object(torrent_backend, "cancel", side_effect=cancelled.append):
            backend_torrent._unregister_all_for_job("job-7", delete_files=True)

        self.assertEqual(cancelled, ["job-7"])


class AndroidInterruptedJobRecoveryTest(unittest.TestCase):
    """Process death is the normal way an Android app stops.

    Chaquopy keeps the interpreter alive across an Activity close/reopen, so a
    running download legitimately keeps running there. A real process kill
    reloads the persisted job list instead, and a job that was mid-download
    must not come back claiming to be running — on the phone that reads as a
    download stuck at "Downloading…" with nothing behind it.
    """

    def test_a_job_persisted_as_running_is_reloaded_as_interrupted(self):
        import tempfile

        import service_downloader

        persisted = [
            {"id": "a", "status": "running", "title": "Veridis Quo", "progress": 41.0,
             "library_requested": True},
            {"id": "b", "status": "starting", "title": "Aerodynamic", "progress": 0},
            {"id": "c", "status": "finished", "title": "Digital Love", "progress": 100,
             "library_path": "/music/Digital Love.m4a"},
            {"id": "d", "status": "error", "title": "One More Time", "error": "boom"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jobs_file = Path(tmp) / "jobs.json"
            jobs_file.write_text(json.dumps(persisted), encoding="utf-8")
            manager = service_downloader.ServiceDownloadManager.__new__(
                service_downloader.ServiceDownloadManager)
            manager.jobs = {}
            with patch.object(service_downloader, "JOBS_PATH", jobs_file):
                manager._load_jobs()

        self.assertEqual(set(manager.jobs), {"a", "b", "c", "d"})
        for job_id in ("a", "b"):
            self.assertEqual(manager.jobs[job_id]["status"], "error")
            self.assertEqual(manager.jobs[job_id]["error"], "Interrupted by server restart")
            self.assertFalse(manager.jobs[job_id]["library_requested"])
        # A finished download stays finished: its file is still on disk.
        self.assertEqual(manager.jobs["c"]["status"], "finished")
        self.assertEqual(manager.jobs["c"]["library_path"], "/music/Digital Love.m4a")
        self.assertEqual(manager.jobs["d"]["error"], "boom")

    def test_a_corrupt_job_file_does_not_stop_the_backend_from_starting(self):
        import tempfile

        import service_downloader

        with tempfile.TemporaryDirectory() as tmp:
            jobs_file = Path(tmp) / "jobs.json"
            jobs_file.write_text("[{broken", encoding="utf-8")
            manager = service_downloader.ServiceDownloadManager.__new__(
                service_downloader.ServiceDownloadManager)
            manager.jobs = {}
            with patch.object(service_downloader, "JOBS_PATH", jobs_file):
                manager._load_jobs()

        self.assertEqual(manager.jobs, {})


class AndroidTorrentCandidateRankingTest(unittest.TestCase):
    """Deterministic filtering runs before any AI ranking and can veto it."""

    def test_video_releases_are_rejected_outright(self):
        score = torrent_backend._score(
            {"title": "Daft Punk Interstella 5555 1080p BluRay x264", "seeders": 900},
            "Daft Punk", "Veridis Quo", "Discovery")
        self.assertLess(score, 0)

    def test_a_non_audio_category_is_rejected_even_with_a_matching_title(self):
        score = torrent_backend._score(
            {"title": "Daft Punk - Discovery", "category": "Movies", "seeders": 50},
            "Daft Punk", "Veridis Quo", "Discovery")
        self.assertLess(score, 0)

    def test_a_different_artist_is_rejected_however_healthy_the_swarm(self):
        score = torrent_backend._score(
            {"title": "Justice - Cross FLAC", "seeders": 5000},
            "Daft Punk", "Veridis Quo", "Discovery")
        self.assertLess(score, 0)

    def test_a_lossless_release_outranks_the_same_release_in_lossy(self):
        lossless = torrent_backend._score(
            {"title": "Daft Punk - Discovery (2001) FLAC", "category": "Audio", "seeders": 10},
            "Daft Punk", "Veridis Quo", "Discovery")
        lossy = torrent_backend._score(
            {"title": "Daft Punk - Discovery (2001) MP3 320", "category": "Audio", "seeders": 10},
            "Daft Punk", "Veridis Quo", "Discovery")
        self.assertGreater(lossless, lossy)
        self.assertGreater(lossy, 0)

    def test_mp3_quality_prefers_mp3_releases_and_selects_lossy_files(self):
        mp3_score = torrent_backend._score(
            {"title": "Daft Punk - Discovery MP3 320", "category": "Audio", "seeders": 10},
            "Daft Punk", "Veridis Quo", "Discovery", quality="MP3")
        flac_score = torrent_backend._score(
            {"title": "Daft Punk - Discovery FLAC", "category": "Audio", "seeders": 10},
            "Daft Punk", "Veridis Quo", "Discovery", quality="MP3")
        self.assertGreater(mp3_score, flac_score)
        self.assertFalse(torrent_backend._require_lossless({"quality": "MP3"}))
        self.assertTrue(torrent_backend._require_lossless({"quality": "LOSSLESS"}))

    def test_feature_credit_in_title_or_album_does_not_block_candidate(self):
        score = torrent_backend._score(
            {"title": "Artist feat Guest Artist - Album feat Guest Artist FLAC",
             "category": "Audio", "seeders": 4},
            "Artist", "Track feat Guest Artist", "Album feat Guest Artist")
        self.assertGreater(score, 0)

    def test_single_word_album_adds_release_year_to_first_pass_searches(self):
        job = {
            "artist": "Michael Jackson",
            "title": "Bad - 2012 Remaster",
            "album": "Bad",
            "metadata": {"year": "1987"},
        }
        queries = torrent_backend._first_pass_queries(job)
        self.assertIn("Michael Jackson Bad 1987 FLAC", queries)

    def test_first_pass_searches_artist_album_title_combinations(self):
        queries = torrent_backend._first_pass_queries({
            "artist": "Jimi Hendrix",
            "title": "Voodoo Chile",
            "album": "Electric Ladyland",
            "metadata": {},
        })
        normalized = {" ".join(query.split()).casefold() for query in queries}
        self.assertIn("jimi hendrix electric ladyland voodoo chile flac", normalized)
        self.assertIn("jimi hendrix electric ladyland flac", normalized)
        self.assertIn("jimi hendrix voodoo chile flac", normalized)
        self.assertIn("electric ladyland voodoo chile flac", normalized)

    def test_mp3_first_pass_uses_mp3_queries_instead_of_flac_queries(self):
        queries = torrent_backend._first_pass_queries({
            "artist": "Jimi Hendrix", "title": "Voodoo Chile",
            "album": "Electric Ladyland", "quality": "MP3", "metadata": {},
        })
        normalized = {query.casefold() for query in queries}
        self.assertIn("jimi hendrix electric ladyland voodoo chile mp3", normalized)
        self.assertFalse(any("flac" in query.casefold() for query in normalized))

    def test_release_year_breaks_ties_for_ambiguous_single_word_albums(self):
        target = {"artist": "Michael Jackson", "title": "Bad - 2012 Remaster", "album": "Bad"}
        matching_year = torrent_backend._score(
            {"title": "Michael Jackson - Bad 25th Anniversary (2012) (1987) FLAC", "seeders": 40},
            **target, album_year="1987")
        remaster_year_only = torrent_backend._score(
            {"title": "Michael Jackson - Bad Remastered 2012 FLAC", "seeders": 40},
            **target, album_year="1987")
        self.assertGreater(matching_year, remaster_year_only)

    def test_the_magnet_hash_is_what_deduplicates_candidates(self):
        first = "magnet:?xt=urn:btih:ABCDEF0123456789&dn=one"
        second = "magnet:?xt=urn:btih:abcdef0123456789&dn=two&tr=udp%3A%2F%2Ftracker"
        self.assertEqual(torrent_backend._key(first), torrent_backend._key(second))

    def test_candidates_handed_to_the_advisor_carry_their_magnet_uri(self):
        """Without the magnet the advisor loses its DN/tracker context."""
        import ai_reranker

        job = {"id": "j", "artist": "Daft Punk", "title": "Veridis Quo",
               "album": "Discovery", "service": "all", "metadata": {}}
        manager = SimpleNamespace(_append_cache_event=lambda *a: None, config=None)
        results = [
            {"title": "Daft Punk - Discovery FLAC", "category": "Audio", "seeders": 30,
             "magnet": "magnet:?xt=urn:btih:aaaa&dn=Discovery+FLAC", "source": "torlock"},
            {"title": "Daft Punk - Discovery 24bit lossless", "category": "Audio", "seeders": 12,
             "magnet": "magnet:?xt=urn:btih:bbbb&dn=Discovery+24bit", "source": "1337x"},
        ]
        seen = {}

        def fake_rank(target, candidates, *args, **kwargs):
            seen["candidates"] = candidates
            return [entry["id"] for entry in reversed(candidates)]

        with patch.object(torrent_backend, "_search", return_value=results), \
                patch.object(ai_reranker, "rank_candidates", side_effect=fake_rank), \
                patch.object(ai_reranker, "provider_settings", return_value=("1", "android", "")):
            ordered = torrent_backend._ordered_candidates(job, manager)

        self.assertEqual(len(ordered), 2)
        self.assertTrue(all(entry.get("magnet") for entry in seen["candidates"]))
        # The pooled source list launches by swarm health; AI may only break
        # ties, so the healthier TorLock result stays first.
        self.assertEqual(ordered[0]["magnet"], "magnet:?xt=urn:btih:aaaa&dn=Discovery+FLAC")

    def test_merged_candidate_list_prioritizes_seed_to_leecher_ratio(self):
        job = {"id": "j", "artist": "Jimi Hendrix", "title": "Voodoo Chile",
               "album": "Electric Ladyland", "service": "all", "metadata": {}}
        manager = SimpleNamespace(_append_cache_event=lambda *a: None, config=None)
        candidates = [
            {"title": "The Jimi Hendrix Experience - Electric Ladyland 3CD FLAC",
             "category": "Audio", "seeders": 6, "leechers": 2,
             "magnet": "magnet:?xt=urn:btih:lowratio", "source": "torlock"},
            {"title": "The Jimi Hendrix Experience - Electric Ladyland 50th Anniversary FLAC",
             "category": "Audio", "seeders": 114, "leechers": 20,
             "magnet": "magnet:?xt=urn:btih:highratio", "source": "1337x"},
        ]
        with patch.object(torrent_backend, "_search", return_value=candidates):
            ordered = torrent_backend._ordered_candidates(job, manager)

        self.assertEqual(ordered[0]["magnet"], "magnet:?xt=urn:btih:highratio")

    def test_large_seed_count_beats_tiny_swarm_with_a_better_ratio(self):
        job = {"id": "j", "artist": "Jimi Hendrix", "title": "Voodoo Chile",
               "album": "Electric Ladyland", "service": "all", "metadata": {}}
        manager = SimpleNamespace(_append_cache_event=lambda *a: None, config=None)
        candidates = [
            {"title": "The Jimi Hendrix Experience - Electric Ladyland FLAC",
             "category": "Audio", "seeders": 3, "leechers": 0,
             "magnet": "magnet:?xt=urn:btih:tiny", "source": "torlock"},
            {"title": "The Jimi Hendrix Experience - Electric Ladyland 50th Anniversary FLAC",
             "category": "Audio", "seeders": 193, "leechers": 101,
             "magnet": "magnet:?xt=urn:btih:large", "source": "1337x"},
        ]
        with patch.object(torrent_backend, "_search", return_value=candidates):
            ordered = torrent_backend._ordered_candidates(job, manager)

        self.assertEqual(ordered[0]["magnet"], "magnet:?xt=urn:btih:large")

    def test_unseeded_candidates_never_enter_the_android_race(self):
        job = {"id": "j", "artist": "Jimi Hendrix", "title": "Voodoo Chile",
               "album": "Electric Ladyland", "service": "all", "metadata": {}}
        manager = SimpleNamespace(_append_cache_event=lambda *a: None, config=None)
        candidates = [
            {"title": "Jimi Hendrix - Electric Ladyland FLAC", "category": "Audio",
             "seeders": 0, "leechers": 40,
             "magnet": "magnet:?xt=urn:btih:unseeded", "source": "1337x"},
            {"title": "Jimi Hendrix - Electric Ladyland 50th Anniversary FLAC", "category": "Audio",
             "seeders": 193, "leechers": 101,
             "magnet": "magnet:?xt=urn:btih:healthy", "source": "1337x"},
        ]
        with patch.object(torrent_backend, "_search", return_value=candidates):
            ordered = torrent_backend._ordered_candidates(job, manager)

        self.assertEqual([row["magnet"] for row in ordered], ["magnet:?xt=urn:btih:healthy"])

    def test_a_failing_advisor_leaves_the_deterministic_order_intact(self):
        import ai_reranker

        job = {"id": "j", "artist": "Daft Punk", "title": "Veridis Quo",
               "album": "Discovery", "service": "all", "metadata": {}}
        events = []
        manager = SimpleNamespace(
            _append_cache_event=lambda job, kind, message: events.append((kind, message)),
            config=None)
        results = [
            {"title": "Daft Punk - Discovery FLAC", "category": "Audio", "seeders": 300,
             "magnet": "magnet:?xt=urn:btih:aaaa&dn=a", "source": "torlock"},
            {"title": "Daft Punk - Discovery MP3", "category": "Audio", "seeders": 1,
             "magnet": "magnet:?xt=urn:btih:bbbb&dn=b", "source": "1337x"},
        ]

        with patch.object(torrent_backend, "_search", return_value=results), \
                patch.object(ai_reranker, "rank_candidates", side_effect=RuntimeError("no model")), \
                patch.object(ai_reranker, "provider_settings", return_value=("1", "android", "")):
            ordered = torrent_backend._ordered_candidates(job, manager)

        self.assertEqual(ordered[0]["magnet"], "magnet:?xt=urn:btih:aaaa&dn=a")
        self.assertTrue(any("deterministic" in message for _, message in events))


class AndroidAdvisorFallbackTest(unittest.TestCase):
    """Nano -> imported local Gemma -> deterministic, and never past it."""

    def _prompt(self):
        return json.dumps({
            "task": "rank",
            "target": {"artist": "Daft Punk", "title": "Veridis Quo", "album": "Discovery"},
            "candidates": [
                {"id": 1, "title": "lossy", "local_score": 10, "seeders": 2},
                {"id": 2, "title": "flac", "local_score": 90, "seeders": 40},
            ],
        })

    def test_gemini_nano_is_used_first_when_it_answers(self):
        import ai_reranker

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(ai_reranker, "_android_nano_text", return_value='{"ranked_ids":[1,2]}'), \
                patch.object(ai_reranker, "_android_local_model_text", return_value='{"ranked_ids":[2,1]}'):
            result = ai_reranker._android_request(self._prompt(), "")

        self.assertEqual(result["ranked_ids"], [1, 2])

    def test_a_local_model_answers_when_nano_is_unavailable(self):
        import ai_reranker

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(ai_reranker, "_android_nano_text", return_value=""), \
                patch.object(ai_reranker, "_android_local_model_text", return_value='{"ranked_ids":[2,1]}'):
            result = ai_reranker._android_request(self._prompt(), "")

        self.assertEqual(result["ranked_ids"], [2, 1])

    def test_deterministic_ranking_answers_offline_with_no_model_at_all(self):
        import ai_reranker

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(ai_reranker, "_android_nano_text", return_value=""), \
                patch.object(ai_reranker, "_android_local_model_text", return_value=""):
            result = ai_reranker._android_request(self._prompt(), "")

        # Highest local score first: the deterministic ranker never defers to
        # candidate order.
        self.assertEqual(result["ranked_ids"], [2, 1])

    def test_no_android_advisor_ever_reaches_a_cloud_provider(self):
        import ai_reranker

        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(ai_reranker, "_android_nano_text", return_value=""), \
                patch.object(ai_reranker, "_android_local_model_text", return_value=""), \
                patch.object(ai_reranker, "_duck_request", side_effect=AssertionError("Duck.ai called")), \
                patch.object(ai_reranker, "_gemini_request", side_effect=AssertionError("Gemini called")), \
                patch.object(ai_reranker, "_codex_request", side_effect=AssertionError("Codex called")), \
                patch.object(ai_reranker, "_openai_compatible_request", side_effect=AssertionError("OpenAI called")):
            result = ai_reranker._request(self._prompt(), "1", "duckai", "gemini-3.5-flash-lite")

        self.assertEqual(result["ranked_ids"], [2, 1])

    def test_the_advisor_cannot_invent_a_candidate_the_filter_rejected(self):
        import ai_reranker

        candidates = [
            {"id": 1, "title": "Daft Punk - Discovery FLAC", "seeders": 10, "score": 90,
             "magnet": "magnet:?xt=urn:btih:aaaa&dn=a"},
        ]
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(ai_reranker, "_request", return_value={"ranked_ids": [1, 42, 7]}):
            ranked = ai_reranker.rank_candidates(
                {"artist": "Daft Punk", "title": "Veridis Quo", "album": "Discovery"}, candidates)

        self.assertEqual(ranked, [1])


class FakeNativeTorrentEngine:
    """Stands in for ``com.mindinguflac.android.AndroidTorrentEngine``.

    The real bridge hands Python JSON strings, so the fake does too — that
    string contract is the thing worth testing from this side.
    """

    def __init__(self, scripts):
        self.scripts = scripts
        self.started = []
        self.released = []
        self._status_calls = 0
        self._jobs = {}
        self._counts = {}

    def startDownload(self, job_id, magnet, output, artist, title, album, track, lossless,
                      metadata_timeout=None):
        self.started.append({"magnet": magnet, "lossless": lossless, "output": output})
        self._jobs[job_id] = self.scripts[magnet]
        self._counts[job_id] = 0
        start = self._jobs[job_id]["start"]
        if start.get("ok") and start.get("create"):
            path = Path(start["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00" * int(start.get("size") or 0))
        return json.dumps(start)

    def status(self, job_id):
        frames = self._jobs[job_id]["frames"]
        frame = frames[min(self._counts[job_id], len(frames) - 1)]
        self._counts[job_id] += 1
        return json.dumps(frame)

    def release(self, job_id):
        self.released.append(job_id)

    def cancel(self, job_id):
        self.released.append(job_id)


class FakeManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_flags = set()
        self.events = []
        self.config = None

    def _append_cache_event(self, job, kind, message):
        self.events.append((kind, message))


class AndroidNativeTorrentJobTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "out"
        self.out.mkdir()
        self.job = {
            "id": "job-1", "artist": "Daft Punk", "title": "Veridis Quo",
            "album": "Discovery", "service": "all", "metadata": {"track_number": "7"},
        }
        self.manager = FakeManager()

    def _candidates(self, *magnets):
        return [{"magnet": magnet, "title": f"Daft Punk - Discovery FLAC {index}",
                 "seeders": 10, "_score": 100 - index}
                for index, magnet in enumerate(magnets)]

    def test_known_album_download_does_not_start_provider_search(self):
        path = self.out / "known.flac"
        engine = FakeNativeTorrentEngine({"magnet:?xt=urn:btih:known": {
            "start": {"ok": True, "path": str(path), "size": 1000, "create": True},
            "frames": [{"ok": True, "ready": 1000, "size": 1000, "finished": True}],
        }})
        self.job["resolved_url"] = "magnet:?xt=urn:btih:stale-track-source"
        self.manager.config = object()
        import db
        with patch.object(torrent_backend, '_engine', return_value=engine), \
                patch.object(torrent_backend, '_ordered_candidates', return_value=[]) as search, \
                patch.object(db, 'get_album_source', return_value={
                    'engine': 'torrent', 'resolved_url': 'magnet:?xt=urn:btih:known'
                }):
            torrent_backend.run(self.out, self.job, self.manager)
        search.assert_not_called()
        self.assertEqual(self.job['resolved_url'], 'magnet:?xt=urn:btih:known')

    def test_track_specific_failure_replaces_saved_album_magnet(self):
        import db
        bad = "magnet:?xt=urn:btih:bad-track-match"
        good = "magnet:?xt=urn:btih:replacement"
        path = self.out / "replacement.flac"
        engine = FakeNativeTorrentEngine({
            bad: {"start": {"ok": False, "error": "No matching lossless audio file in torrent"}, "frames": []},
            good: {"start": {"ok": True, "path": str(path), "size": 1000, "create": True},
                   "frames": [{"ok": True, "ready": 1000, "size": 1000, "finished": True}]},
        })
        self.manager.config = object()
        cached = {"album_key": "daft punk||discovery", "engine": "torrent", "resolved_url": bad}
        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=self._candidates(good)), \
                patch.object(db, "get_album_source", return_value=cached), \
                patch.object(db, "delete_album_source") as delete_source:
            torrent_backend.run(self.out, self.job, self.manager)
        delete_source.assert_called_once_with("daft punk||discovery")
        self.assertIn("Removed failed saved album torrent", " ".join(message for _kind, message in self.manager.events))

    def test_out_of_order_pieces_do_not_keep_a_stalled_saved_album_source_alive(self):
        import db

        known = "magnet:?xt=urn:btih:saved-album"
        replacement = "magnet:?xt=urn:btih:replacement"
        good_path = self.out / "replacement.flac"

        class OutOfOrderEngine(FakeNativeTorrentEngine):
            def status(inner, native_id):
                if native_id.endswith("::1"):
                    inner._counts[native_id] += 1
                    # Total downloaded bytes keep climbing, but the first
                    # contiguous bytes needed to begin playback remain stuck.
                    return json.dumps({
                        "ok": True, "ready": 20000 + inner._counts[native_id] * 4096,
                        "contiguous": 0, "size": 1000000, "peers": 1,
                        "finished": False,
                    })
                return json.dumps({
                    "ok": True, "ready": 1000, "contiguous": 1000,
                    "size": 1000, "peers": 5, "finished": True,
                })

        engine = OutOfOrderEngine({
            known: {"start": {"ok": True, "path": str(self.out / "saved.flac"),
                              "size": 1000000, "create": True}, "frames": []},
            replacement: {"start": {"ok": True, "path": str(good_path),
                                    "size": 1000, "create": True}, "frames": []},
        })
        self.manager.config = object()
        cached = {"album_key": "daft punk||discovery", "engine": "torrent", "resolved_url": known}
        clock = [0.0]

        def tick(_seconds):
            clock[0] += 30.0

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=self._candidates(replacement)), \
                patch.object(db, "get_album_source", return_value=cached), \
                patch.object(db, "delete_album_source") as delete_source, \
                patch.object(torrent_backend.time, "monotonic", lambda: clock[0]), \
                patch.object(torrent_backend.time, "sleep", side_effect=tick):
            torrent_backend.run(self.out, self.job, self.manager)

        self.assertEqual(self.job["resolved_url"], replacement)
        self.assertEqual({entry["magnet"] for entry in engine.started}, {known, replacement})
        delete_source.assert_called_once_with("daft punk||discovery")
        self.assertTrue(any("no track byte progress" in message.lower()
                            for _kind, message in self.manager.events))

    def test_failed_saved_album_magnet_is_deleted_before_parallel_replacements(self):
        import db
        path = self.out / "replacement.flac"
        bad = "magnet:?xt=urn:btih:bad"
        good = "magnet:?xt=urn:btih:good"
        engine = FakeNativeTorrentEngine({
            bad: {"start": {"ok": False, "error": "metadata timed out"}, "frames": []},
            good: {"start": {"ok": True, "path": str(path), "size": 1000, "create": True},
                   "frames": [{"ok": True, "ready": 1000, "size": 1000, "finished": True}]},
        })
        self.manager.config = object()
        cached = {"engine": "torrent", "resolved_url": bad}
        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=self._candidates(good)), \
                patch.object(db, "get_album_source", return_value=cached), \
                patch.object(db, "delete_album_source") as delete_source:
            torrent_backend.run(self.out, self.job, self.manager)
        self.assertEqual({row["magnet"] for row in engine.started}, {bad, good})
        delete_source.assert_called_once_with("daft punk||discovery")
        self.assertEqual(self.job["resolved_url"], good)

    def test_stalled_winner_uses_previously_started_alternative_and_keeps_partial(self):
        import itertools
        partial = self.out / 'partial.flac'
        good = self.out / 'alternative.flac'
        engine = FakeNativeTorrentEngine({
            'first': {'start': {'ok': True, 'path': str(partial), 'size': 1000000, 'create': True},
                      'frames': [{'ok': True, 'ready': 100000, 'size': 1000000, 'finished': False}]},
            'other': {'start': {'ok': True, 'path': str(good), 'size': 1000, 'create': True},
                      'frames': [{'ok': True, 'ready': 1000, 'size': 1000, 'finished': True}]},
        })
        clock = itertools.count(0, 30)
        with patch.object(torrent_backend, '_engine', return_value=engine), \
                patch.object(torrent_backend, '_ordered_candidates', return_value=self._candidates('first', 'other')), \
                patch.object(torrent_backend.time, 'monotonic', lambda: next(clock)), \
                patch.object(torrent_backend.time, 'sleep', lambda _: None):
            torrent_backend.run(self.out, self.job, self.manager)
        self.assertTrue(partial.is_file())
        self.assertEqual(self.job['resolved_url'], 'other')
        self.assertEqual({row['magnet'] for row in engine.started}, {'first', 'other'})

    def test_slots_refill_while_selected_source_is_still_downloading(self):
        import time
        real_sleep = time.sleep
        clock = [0.0]
        good = self.out / "healthy.flac"
        partial = self.out / "trickle.flac"
        class Engine(FakeNativeTorrentEngine):
            def status(inner, native_id):
                if native_id.endswith("::1"):
                    # Progress keeps this source alive while other slots expire.
                    return json.dumps({"ok": True, "ready": 20000 + int(clock[0]) * 10,
                                       "size": 27000000, "finished": False})
                return super().status(native_id)
        engine = Engine({
            "trickle": {"start": {"ok": True, "path": str(partial), "size": 27000000, "create": True}, "frames": []},
            **{key: {"start": {"ok": True, "path": str(self.out / (key + ".flac")), "size": 27000000},
                     "frames": [{"ok": True, "ready": 0, "size": 27000000, "finished": False}]} for key in ("dead1", "dead2")},
            "healthy": {"start": {"ok": True, "path": str(good), "size": 1000, "create": True},
                        "frames": [{"ok": True, "ready": 1000, "size": 1000, "finished": True}]},
        })
        def tick(_seconds):
            clock[0] += 1
            self.assertLess(clock[0], 100, str((engine.started, self.manager.events)))
            real_sleep(.001)
        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=self._candidates("trickle", "dead1", "dead2", "healthy")), \
                patch.object(torrent_backend.time, "monotonic", lambda: clock[0]), \
                patch.object(torrent_backend.time, "sleep", side_effect=tick):
            torrent_backend.run(self.out, self.job, self.manager)
        self.assertEqual(self.job["resolved_url"], "healthy")
        self.assertEqual(len(engine.started), 4)
        self.assertTrue(partial.is_file())
        self.assertTrue(any("trickle.flac" in message for _, message in self.manager.events))

    def test_three_native_candidates_start_while_first_metadata_is_blocked(self):
        barrier = threading.Barrier(3)
        unblock = threading.Event()
        good = self.out / "winner.flac"
        good.write_bytes(b"fLaC" + bytes(996))
        class Engine:
            def __init__(self):
                self.started = []
                self.cancelled = []
            def startDownload(inner, native_id, magnet, *args):
                inner.started.append(magnet)
                barrier.wait(timeout=3)
                if magnet == "first":
                    if not unblock.wait(timeout=3):
                        raise AssertionError("slow metadata blocked the healthy candidate")
                    return json.dumps({"ok": False, "error": "Cancelled"})
                return json.dumps({"ok": True, "path": str(good), "size": 1000})
            def status(inner, native_id):
                ready = 1000 if native_id.endswith("::2") else 0
                return json.dumps({"ok": True, "ready": ready, "size": 1000, "finished": ready == 1000})
            def cancel(inner, native_id):
                inner.cancelled.append(native_id)
                unblock.set()
            def release(inner, native_id):
                pass
        engine = Engine()
        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=self._candidates("first", "second", "third", "fourth")):
            torrent_backend.run(self.out, self.job, self.manager)
        self.assertCountEqual(engine.started, ["first", "second", "third"])
        self.assertEqual(self.job["resolved_url"], "second")
        self.assertTrue(any(item.endswith("::1") for item in engine.cancelled))

    def test_a_finished_download_reports_the_selected_file_and_full_progress(self):
        path = self.out / "07 Veridis Quo.flac"
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:aaaa": {
                "start": {"ok": True, "path": str(path), "size": 1000, "create": True},
                "frames": [
                    {"ok": True, "ready": 400, "size": 1000, "peers": 6, "finished": False},
                    {"ok": True, "ready": 1000, "size": 1000, "peers": 8, "finished": True},
                ],
            },
        })

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates("magnet:?xt=urn:btih:aaaa")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None):
            torrent_backend.run(self.out, self.job, self.manager)

        self.assertTrue(engine.started[0]["lossless"])
        self.assertEqual(self.job["active_audio_path"], str(path))
        self.assertEqual(self.job["downloaded_bytes"], 1000)
        self.assertEqual(self.job["resolved_url"], "magnet:?xt=urn:btih:aaaa")
        self.assertTrue(engine.released)
        self.assertTrue(all(item.startswith("job-1::torrent::") for item in engine.released))

    def test_a_stalled_source_is_abandoned_for_the_next_candidate(self):
        good = self.out / "07 Veridis Quo.flac"
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:dead": {
                "start": {"ok": True, "path": str(self.out / "dead.flac"), "size": 900},
                "frames": [{"ok": True, "ready": 0, "size": 900, "peers": 0, "finished": False}],
            },
            "magnet:?xt=urn:btih:live": {
                "start": {"ok": True, "path": str(good), "size": 900, "create": True},
                "frames": [{"ok": True, "ready": 900, "size": 900, "peers": 9, "finished": True}],
            },
        })
        clock = iter([0.0] + [float(value) for value in range(0, 4000, 100)])

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates(
                                 "magnet:?xt=urn:btih:dead", "magnet:?xt=urn:btih:live")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None), \
                patch.object(torrent_backend.time, "monotonic", lambda: next(clock)):
            torrent_backend.run(self.out, self.job, self.manager)

        # Candidate start calls happen on independent executor threads, so
        # scheduler order is intentionally nondeterministic.
        self.assertEqual({entry["magnet"] for entry in engine.started},
                         {"magnet:?xt=urn:btih:dead", "magnet:?xt=urn:btih:live"})
        self.assertEqual(self.job["active_audio_path"], str(good))

    def test_a_source_that_refuses_to_start_is_skipped(self):
        good = self.out / "07 Veridis Quo.flac"
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:nometa": {
                "start": {"ok": False, "error": "Torrent metadata timed out"},
                "frames": [],
            },
            "magnet:?xt=urn:btih:live": {
                "start": {"ok": True, "path": str(good), "size": 10, "create": True},
                "frames": [{"ok": True, "ready": 10, "size": 10, "peers": 3, "finished": True}],
            },
        })

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates(
                                 "magnet:?xt=urn:btih:nometa", "magnet:?xt=urn:btih:live")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None):
            torrent_backend.run(self.out, self.job, self.manager)

        self.assertEqual(self.job["active_audio_path"], str(good))

    def test_every_source_failing_raises_the_last_real_reason(self):
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:aaaa": {
                "start": {"ok": False, "error": "No matching lossless audio file in torrent"},
                "frames": [],
            },
        })

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates("magnet:?xt=urn:btih:aaaa")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None):
            with self.assertRaises(RuntimeError) as caught:
                torrent_backend.run(self.out, self.job, self.manager)

        self.assertIn("No matching lossless audio file", str(caught.exception))
        self.assertTrue(engine.released)
        self.assertTrue(all(item.startswith("job-1::torrent::") for item in engine.released))

    def test_no_candidates_is_an_actionable_error_not_a_silent_finish(self):
        with patch.object(torrent_backend, "_engine", return_value=FakeNativeTorrentEngine({})), \
                patch.object(torrent_backend, "_ordered_candidates", return_value=[]):
            with self.assertRaises(RuntimeError) as caught:
                torrent_backend.run(self.out, self.job, self.manager)

        self.assertIn("No matching FLAC torrent sources", str(caught.exception))

    def test_cancelling_before_start_does_not_launch_native_downloads(self):
        path = self.out / "07 Veridis Quo.flac"
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:aaaa": {
                "start": {"ok": True, "path": str(path), "size": 1000, "create": True},
                "frames": [{"ok": True, "ready": 100, "size": 1000, "peers": 4, "finished": False}],
            },
        })
        self.manager._cancel_flags.add("job-1")

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates("magnet:?xt=urn:btih:aaaa")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None):
            with self.assertRaises(RuntimeError) as caught:
                torrent_backend.run(self.out, self.job, self.manager)

        self.assertIn("Cancelled", str(caught.exception))
        self.assertEqual(engine.started, [])
        self.assertEqual(engine.released, [])

    def test_a_finished_torrent_with_a_missing_file_is_an_error(self):
        engine = FakeNativeTorrentEngine({
            "magnet:?xt=urn:btih:aaaa": {
                "start": {"ok": True, "path": str(self.out / "gone.flac"), "size": 10},
                "frames": [{"ok": True, "ready": 10, "size": 10, "peers": 2, "finished": True}],
            },
        })

        with patch.object(torrent_backend, "_engine", return_value=engine), \
                patch.object(torrent_backend, "_ordered_candidates",
                             return_value=self._candidates("magnet:?xt=urn:btih:aaaa")), \
                patch.object(torrent_backend.time, "sleep", lambda _s: None):
            with self.assertRaises(RuntimeError) as caught:
                torrent_backend.run(self.out, self.job, self.manager)

        self.assertIn("selected FLAC file is missing", str(caught.exception))

    def test_runtime_status_degrades_to_an_error_dict_off_device(self):
        with patch.object(torrent_backend, "_engine", side_effect=RuntimeError("no java")):
            status = torrent_backend.runtime_status()

        self.assertFalse(status["ok"])
        self.assertIn("no java", status["error"])


class AndroidAudioStreamingTest(unittest.TestCase):
    """Range responses for /api/library/stream, which is how the phone plays."""

    @classmethod
    def setUpClass(cls):
        import tempfile

        import app

        cls.tmp = tempfile.TemporaryDirectory()
        cls.audio = Path(cls.tmp.name) / "track.flac"
        cls.payload = bytes(range(256)) * 8  # 2048 bytes
        cls.audio.write_bytes(cls.payload)
        cls.token = "android-stream-token"
        cls._saved_token = app.API_TOKEN
        app.API_TOKEN = cls.token
        cls.server = app.create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        import app

        cls.server.shutdown()
        cls.server.server_close()
        app.API_TOKEN = cls._saved_token
        cls.tmp.cleanup()

    def _get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        request_headers = {"X-Mindinguflac-Token": self.token}
        request_headers.update(headers or {})
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def _stream_path(self):
        from urllib.parse import urlencode

        return "/api/library/stream?" + urlencode({"path": str(self.audio), "audio": "1"})

    def test_an_unauthenticated_request_is_refused(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", self._stream_path())
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 401)

    def test_a_full_request_advertises_range_support_and_returns_everything(self):
        response, body = self._get(self._stream_path())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Accept-Ranges"), "bytes")
        self.assertEqual(int(response.getheader("Content-Length")), len(self.payload))
        self.assertEqual(body, self.payload)

    def test_a_mid_file_range_returns_206_with_exactly_those_bytes(self):
        response, body = self._get(self._stream_path(), {"Range": "bytes=100-199"})
        self.assertEqual(response.status, 206)
        self.assertEqual(response.getheader("Content-Range"), f"bytes 100-199/{len(self.payload)}")
        self.assertEqual(int(response.getheader("Content-Length")), 100)
        self.assertEqual(body, self.payload[100:200])

    def test_an_open_ended_range_runs_to_the_end_of_the_file(self):
        response, body = self._get(self._stream_path(), {"Range": "bytes=2000-"})
        self.assertEqual(response.status, 206)
        self.assertEqual(body, self.payload[2000:])

    def test_a_suffix_range_returns_the_tail(self):
        response, body = self._get(self._stream_path(), {"Range": "bytes=-48"})
        self.assertEqual(response.status, 206)
        self.assertEqual(body, self.payload[-48:])

    def test_a_range_past_the_end_is_416_with_the_real_size(self):
        response, _ = self._get(self._stream_path(), {"Range": "bytes=99999-"})
        self.assertEqual(response.status, 416)
        self.assertEqual(response.getheader("Content-Range"), f"bytes */{len(self.payload)}")

    def test_a_missing_file_is_404_rather_than_an_empty_stream(self):
        from urllib.parse import urlencode

        response, _ = self._get(
            "/api/library/stream?" + urlencode({"path": str(self.audio) + ".missing"}))
        self.assertEqual(response.status, 404)

    def test_health_reports_android_mode_from_the_environment(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False):
            response, body = self._get("/api/health")
        self.assertEqual(response.status, 200)
        self.assertTrue(json.loads(body)["android"])

    def test_the_runtime_endpoint_answers_with_the_capability_report(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}, clear=False), \
                patch.object(capabilities, "runtime_report", return_value=_report()):
            response, body = self._get("/api/runtime")

        self.assertEqual(response.status, 200)
        report = json.loads(body)
        self.assertTrue(report["android"])
        self.assertIn("ytp-dl", report["available_engines"])
        self.assertTrue(report["engines"]["monochrome"]["available"])


if __name__ == "__main__":
    unittest.main()
