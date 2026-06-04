import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import service_downloader


class PlaybackSourceTests(unittest.TestCase):
    def test_builds_spotify_track_url_from_existing_spotify_id(self):
        url = service_downloader.resolve_download_url(
            {"spotify_id": "7J1uxwnxfQLu4APicE5Rnj", "title": "Billie Jean"},
            service="spotify",
        )

        self.assertEqual(url, "https://open.spotify.com/track/7J1uxwnxfQLu4APicE5Rnj")

    def test_uses_library_track_when_no_cache_copy_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            music_dir = root / "music"
            track_path = music_dir / "Pink Floyd" / "Wish You Were Here" / "Shine On You Crazy Diamond.flac"
            track_path.parent.mkdir(parents=True)
            track_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=music_dir,
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                source = manager.playback_source({
                    "artist": "Pink Floyd",
                    "album": "Wish You Were Here",
                    "title": "Shine On You Crazy Diamond",
                })

        self.assertEqual(source["source"], "library")
        self.assertEqual(source["path"], str(track_path))
        self.assertFalse(source["cached"])

    def test_library_status_batch_scans_saved_music_only_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            track_path = root / "music" / "Simply Red" / "Stars" / "For Your Babies - Simply Red.m4a"
            track_path.parent.mkdir(parents=True)
            track_path.write_bytes(b"ftyp" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            payload = {"artist": "Simply Red", "album": "Stars", "title": "For Your Babies"}
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                with patch.object(service_downloader, "_find_audio_files", wraps=service_downloader._find_audio_files) as find_audio:
                    statuses = manager.library_status_batch([payload, payload])

        self.assertEqual([status["in_library"] for status in statuses], [True, True])
        self.assertEqual(find_audio.call_count, 1)

    def test_selected_track_metadata_replaces_unknown_provider_artist(self):
        class Track:
            title = "Two Hearts"
            artists = "Unknown"
            album = "Love Songs"
            album_artist = "Unknown"

            def model_copy(self, update):
                return update

        updated = service_downloader.requested_spotiflac_track_metadata(Track(), {
            "title": "Two Hearts",
            "artist": "Phil Collins",
            "album": "Love Songs",
            "artwork_url": "/cover",
            "metadata": {"duration_ms": 204386},
        })

        self.assertEqual(updated["artists"], "Phil Collins")
        self.assertEqual(updated["album_artist"], "Phil Collins")
        self.assertEqual(updated["duration_ms"], 204386)

    def test_spotiflac_options_only_use_supported_enrichment_parameters(self):
        options = service_downloader.spotiflac_download_options(
            Path("/tmp/cache"),
            {
                "title": "Shout",
                "artist": "Tears For Fears",
                "resolved_url": "https://open.spotify.com/track/spotify-id",
                "quality": "LOSSLESS",
            },
            1,
            ["qobuz", "deezer"],
        )

        self.assertEqual(options["output_path"], "/tmp/cache/Shout - Tears For Fears.flac")
        self.assertTrue(options["embed_lyrics"])
        self.assertTrue(options["enrich_metadata"])
        self.assertNotIn("metadata", options)
        self.assertNotIn("cover", options)
        self.assertNotIn("verbose", options)

    def test_spotiflac_error_does_not_surface_incidental_tidal_gist_warning(self):
        message = service_downloader.spotiflac_failure_message([
            "[tidal] gist fetch failed: Tidal API gist did not return a JSON array",
        ])

        self.assertEqual(message, "All providers failed and no playable audio file was found")

    def test_atmos_fallback_stays_with_lossless_providers_and_translates_quality(self):
        services = service_downloader.spotiflac_fallback_services("tidal", "DOLBY_ATMOS")

        self.assertEqual(services, ["tidal", "qobuz", "amazon", "deezer"])
        self.assertEqual(service_downloader.spotiflac_provider_quality("DOLBY_ATMOS", "qobuz"), "27")
        self.assertEqual(service_downloader.spotiflac_provider_quality("DOLBY_ATMOS", "deezer"), "LOSSLESS")

    def test_spotiflac_does_not_consult_sqlite_source_recovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
                download_engine="spotiflac",
            )
            fake_db = SimpleNamespace(
                get_resolved_source=Mock(side_effect=AssertionError("spotiflac should not consult sqlite sources")),
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    with patch.dict(sys.modules, {"db": fake_db}):
                        manager = service_downloader.ServiceDownloadManager(config)
                        job = manager.start_job({
                            "mode": "stream",
                            "title": "Song",
                            "artist": "Artist",
                            "metadata": {"spotify_id": "spotify-id"},
                        })

        self.assertEqual(job["engine"], "spotiflac")
        self.assertEqual(job["resolved_url"], "")
        thread.assert_called_once()

    def test_ytpdl_source_lookup_prefers_identifier_keys_before_title_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
                download_engine="ytp-dl",
            )
            calls = []

            def fake_get_resolved_source_for_keys(keys):
                calls.extend(keys)
                if "isrc:ISRC-123" in keys:
                    return {
                        "track_key": "isrc:ISRC-123",
                        "engine": "ytp-dl",
                        "service": "youtube",
                        "resolved_url": "https://www.youtube.com/watch?v=abc123",
                    }
                return None

            fake_db = SimpleNamespace(get_resolved_source_for_keys=fake_get_resolved_source_for_keys)

            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    with patch.dict(sys.modules, {"db": fake_db}):
                        manager = service_downloader.ServiceDownloadManager(config)
                        job = manager.start_job({
                            "mode": "stream",
                            "engine": "ytp-dl",
                            "title": "Song",
                            "artist": "Artist",
                            "metadata": {
                                "spotify_id": "spotify-123",
                                "isrc": "ISRC-123",
                            },
                        })

        self.assertEqual(calls[:2], ["spotify_id:spotify-123", "isrc:ISRC-123"])
        self.assertEqual(job["resolved_url"], "https://www.youtube.com/watch?v=abc123")
        thread.assert_called_once()

    def test_ignores_deleted_finished_cache_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_path = root / "jobs.json"
            missing_path = root / "cache" / "old-job" / "Billie Jean - Michael Jackson.flac"
            jobs_path.write_text(
                '[{"id":"old-job","mode":"stream","status":"finished",'
                '"title":"Billie Jean","artist":"Michael Jackson","album":"Thriller",'
                f'"library_path":"{missing_path}","spotify_id":"track-id"}}]',
                "utf-8",
            )
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", jobs_path):
                manager = service_downloader.ServiceDownloadManager(config)
                source = manager.playback_source({
                    "artist": "Michael Jackson",
                    "album": "Thriller",
                    "title": "Billie Jean",
                    "spotify_id": "track-id",
                })

        self.assertEqual(source["source"], "")
        self.assertEqual(source["path"], "")
        self.assertFalse(source["cached"])

    def test_ignores_cached_provider_result_with_wrong_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "cache" / "job-id" / "Two Hearts.flac"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["job-id"] = {
                    "id": "job-id",
                    "mode": "stream",
                    "status": "finished",
                    "artist": "Phil Collins",
                    "album": "Love Songs",
                    "title": "Two Hearts",
                    "metadata": {"duration_ms": 204386, "spotify_id": "two-hearts"},
                    "library_path": str(cache_path),
                }
                with patch.object(service_downloader, "_audio_duration_ms", return_value=216120):
                    source = manager.playback_source({
                        "artist": "Phil Collins",
                        "album": "Love Songs",
                        "title": "Two Hearts",
                        "spotify_id": "two-hearts",
                    })

        self.assertEqual(source["source"], "")
        self.assertFalse(source["cached"])

    def test_renames_valid_unknown_cache_file_from_saved_track_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "cache" / "job-id" / "Song - Unknown.flac"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["job-id"] = {
                    "id": "job-id",
                    "mode": "stream",
                    "status": "finished",
                    "artist": "Artist",
                    "album": "Album",
                    "title": "Song",
                    "metadata": {"duration_ms": 100000, "spotify_id": "song-id"},
                    "library_path": str(cache_path),
                }
                with patch.object(service_downloader, "_audio_duration_ms", return_value=100000):
                    source = manager.playback_source({
                        "artist": "Artist",
                        "album": "Album",
                        "title": "Song",
                        "spotify_id": "song-id",
                    })

        self.assertEqual(Path(source["path"]).name, "Song - Artist.flac")

    def test_recovers_converted_audio_extension_when_recorded_path_was_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "cache" / "job-id"
            output_dir.mkdir(parents=True)
            converted_path = output_dir / "Lemon Tree - Fools Garden.m4a"
            converted_path.write_bytes(b"ftyp" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="DOLBY_ATMOS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["job-id"] = {
                    "id": "job-id",
                    "mode": "stream",
                    "status": "finished",
                    "artist": "Fools Garden",
                    "album": "Dish Of The Day",
                    "title": "Lemon Tree",
                    "metadata": {"duration_ms": 191026, "spotify_id": "lemon-tree"},
                    "output_dir": str(output_dir),
                    "library_path": str(output_dir / "Lemon Tree - Fools Garden.webm"),
                }
                with patch.object(service_downloader, "_audio_duration_ms", return_value=191026):
                    source = manager.playback_source({
                        "artist": "Fools Garden",
                        "title": "Lemon Tree",
                        "spotify_id": "lemon-tree",
                    })

        self.assertEqual(source["path"], str(converted_path))
        self.assertEqual(manager.jobs["job-id"]["library_path"], str(converted_path))

    def test_cache_activity_reports_created_updated_and_removed_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                output_dir = config.cache_dir / "job-id"
                output_dir.mkdir(parents=True)
                job = {
                    "id": "job-id",
                    "mode": "stream",
                    "title": "Cache Track",
                    "output_dir": str(output_dir),
                }
                partial = output_dir / "Cache Track.m4a"

                partial.write_bytes(b"a" * 12)
                manager._capture_cache_activity(job)
                partial.write_bytes(b"a" * 24)
                manager._capture_cache_activity(job)
                partial.unlink()
                manager._capture_cache_activity(job)

                events = manager.cache_log_snapshot()["events"]

        self.assertEqual([event["kind"] for event in events], ["created", "updated", "removed"])
        self.assertIn("Cache Track.m4a", events[0]["message"])

    def test_prefetch_cache_activity_is_labeled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                output_dir = config.cache_dir / "prefetch-job"
                output_dir.mkdir(parents=True)
                job = {
                    "id": "prefetch-job",
                    "mode": "stream",
                    "prefetch": True,
                    "title": "Shout",
                    "output_dir": str(output_dir),
                }
                (output_dir / "Shout.flac").write_bytes(b"fLaC")
                manager._capture_cache_activity(job)
                event = manager.cache_log_snapshot()["events"][0]

        self.assertEqual(event["message"], "Prefetch: Created Shout.flac (4 B)")

    def test_clear_cache_removes_stream_jobs_and_files_but_keeps_library_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache"
            cached_file = cache_dir / "stream-job" / "Song.flac"
            cached_file.parent.mkdir(parents=True)
            cached_file.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=cache_dir,
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["stream-job"] = {"id": "stream-job", "mode": "stream", "status": "finished"}
                manager.jobs["library-job"] = {"id": "library-job", "mode": "download", "status": "finished"}
                result = manager.clear_cache()

        self.assertEqual(result["removed_jobs"], 1)
        self.assertFalse(cached_file.exists())
        self.assertEqual(set(manager.jobs), {"library-job"})

    def test_completed_stream_clears_stale_cancel_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "cache" / "job-id"
            output_dir.mkdir(parents=True)
            (output_dir / "Song - Artist.flac").write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            job = {
                "id": "job-id",
                "mode": "stream",
                "status": "running",
                "error": "Cancelled by user",
                "title": "Song",
                "artist": "Artist",
                "output_dir": str(output_dir),
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                with patch.object(service_downloader, "is_valid_audio_file", return_value=True):
                    manager._sync_progress_from_files(job)
                    manager._sync_progress_from_files(job)

        self.assertEqual(job["status"], "finished")
        self.assertEqual(job["error"], "")

    def test_intermediate_webm_does_not_finish_stream_before_conversion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "cache" / "job-id"
            output_dir.mkdir(parents=True)
            (output_dir / "Song - Artist.webm").write_bytes(b"audio" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="youtube",
                default_quality="HIGH",
            )
            job = {
                "id": "job-id",
                "mode": "stream",
                "status": "running",
                "error": "",
                "title": "Song",
                "artist": "Artist",
                "output_dir": str(output_dir),
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager._sync_progress_from_files(job)
                manager._sync_progress_from_files(job)

        self.assertEqual(job["status"], "running")
        self.assertEqual(job.get("library_path", ""), "")

    def test_started_job_exposes_enriched_identifier_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            payload = {
                "title": "Shout",
                "artist": "Tears For Fears",
                "metadata": {
                    "spotify_id": "spotify-id",
                    "isrc": "isrc-id",
                    "deezer_id": "deezer-id",
                    "musicbrainz_recording_id": "mbid",
                },
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    manager = service_downloader.ServiceDownloadManager(config)
                    job = manager.start_job(payload)

        self.assertEqual(job["spotify_id"], "spotify-id")
        self.assertEqual(job["isrc"], "isrc-id")
        self.assertEqual(job["deezer_id"], "deezer-id")
        self.assertEqual(job["musicbrainz_recording_id"], "mbid")
        thread.assert_called_once()

    def test_stream_start_reuses_active_job_for_same_track(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            payload = {
                "mode": "stream",
                "title": "Thank You",
                "artist": "Dido",
                "metadata": {"spotify_id": "spotify-id", "isrc": "USAR19900870"},
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    manager = service_downloader.ServiceDownloadManager(config)
                    first = manager.start_job(payload)
                    second = manager.start_job(payload)

        self.assertEqual(second["id"], first["id"])
        thread.assert_called_once()

    def test_stream_start_reuses_finished_cache_instead_of_creating_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "cache" / "old-job" / "Thank You - Dido.flac"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            payload = {
                "mode": "stream",
                "title": "Thank You",
                "artist": "Dido",
                "metadata": {"spotify_id": "spotify-id", "duration_ms": 100000},
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    manager = service_downloader.ServiceDownloadManager(config)
                    manager.jobs["old-job"] = {
                        "id": "old-job",
                        "mode": "stream",
                        "status": "finished",
                        "title": "Thank You",
                        "artist": "Dido",
                        "metadata": {"spotify_id": "spotify-id", "duration_ms": 100000},
                        "library_path": str(cache_path),
                    }
                    with patch.object(service_downloader, "_audio_duration_ms", return_value=100000):
                        result = manager.start_job(payload)

        self.assertEqual(result["id"], "old-job")
        thread.assert_not_called()

    def test_stream_jobs_with_same_isrc_have_independent_work_directories(self):
        config = SimpleNamespace(cache_dir=Path("/tmp/cache"), music_dir=Path("/tmp/music"))
        manager = service_downloader.ServiceDownloadManager.__new__(service_downloader.ServiceDownloadManager)
        manager.config = config

        first = manager._output_dir({"id": "first-job", "mode": "stream", "isrc": "USAR19900870"})
        second = manager._output_dir({"id": "second-job", "mode": "stream", "isrc": "USAR19900870"})

        self.assertEqual(first, Path("/tmp/cache/first-job"))
        self.assertEqual(second, Path("/tmp/cache/second-job"))

    def test_sync_existing_library_sidecar_writes_enriched_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            title = "My Vision (feat. Jakatta) - Jakatta Mix Radio Edit"
            audio_path = root / "music" / "Seal, Jakatta" / "Best 1991 - 2004" / f"{title} - Seal, Jakatta.flac"
            audio_path.parent.mkdir(parents=True)
            audio_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            job = {
                "title": title,
                "artist": "Seal, Jakatta",
                "album": "Best 1991 - 2004",
                "metadata": {
                    "title": title,
                    "artist": "Seal, Jakatta",
                    "album": "Best 1991 - 2004",
                    "spotify_id": "spotify-id",
                    "deezer_id": "deezer-id",
                    "tidal_id": "tidal-id",
                },
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager._sync_existing_library_sidecar(job)
                saved = __import__("json").loads((audio_path.parent / "metadata.json").read_text("utf-8"))

        metadata = saved["tracks"][title]
        self.assertEqual(metadata["spotify_id"], "spotify-id")
        self.assertEqual(metadata["deezer_id"], "deezer-id")
        self.assertEqual(metadata["tidal_id"], "tidal-id")

    def test_finished_cache_metadata_update_rewrites_cache_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "cache" / "finished-job"
            output_dir.mkdir(parents=True)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["finished-job"] = {
                    "id": "finished-job",
                    "status": "finished",
                    "mode": "stream",
                    "title": "Track",
                    "artist": "Artist",
                    "album": "Album",
                    "output_dir": str(output_dir),
                    "metadata": {"spotify_id": "spotify-id"},
                }
                manager.update_job_metadata("finished-job", {"deezer_id": "deezer-id"}, "")
                saved = __import__("json").loads((output_dir / "metadata.json").read_text("utf-8"))

        self.assertEqual(saved["tracks"]["Track"]["spotify_id"], "spotify-id")
        self.assertEqual(saved["tracks"]["Track"]["deezer_id"], "deezer-id")

    def test_copy_cached_track_to_library_keeps_identifiers_from_library_click(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "cache" / "job" / "Song - Artist.flac"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
                download_engine="spotiflac",
            )
            payload = {
                "track": {
                    "title": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "spotify_id": "spotify-id",
                    "isrc": "ISRC-ID",
                },
                "metadata": {
                    "title": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "spotify_id": "spotify-id",
                    "isrc": "ISRC-ID",
                },
            }
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                manager.jobs["job"] = {
                    "id": "job",
                    "mode": "stream",
                    "status": "finished",
                    "title": "Song",
                    "artist": "Artist",
                    "album": "Album",
                    "metadata": {"title": "Song", "artist": "Artist", "album": "Album"},
                    "library_path": str(cache_path),
                    "quality": "LOSSLESS",
                }
                result = manager.toggle_library(payload)
                saved = __import__("json").loads(
                    (root / "music" / "Artist" / "Album" / "metadata.json").read_text("utf-8")
                )

        self.assertEqual(result["action"], "copied")
        self.assertEqual(saved["tracks"]["Song"]["spotify_id"], "spotify-id")
        self.assertEqual(saved["tracks"]["Song"]["isrc"], "ISRC-ID")


class DownloadedTrackMatchesRequestTests(unittest.TestCase):
    """Final validation should not reject solely on duration metadata drift."""

    def _job(self, expected_ms):
        return {"metadata": {"duration_ms": expected_ms}}

    def test_trusts_when_expected_duration_unknown(self):
        ok, _ = service_downloader.downloaded_track_matches_request(Path("x.flac"), {"metadata": {}})
        self.assertTrue(ok)

    def test_trusts_when_file_duration_unreadable(self):
        with patch.object(service_downloader, "_audio_duration_ms", return_value=0):
            ok, _ = service_downloader.downloaded_track_matches_request(Path("x.flac"), self._job(200000))
        self.assertTrue(ok)

    def test_accepts_within_tolerance(self):
        with patch.object(service_downloader, "_audio_duration_ms", return_value=208000):
            ok, _ = service_downloader.downloaded_track_matches_request(Path("x.flac"), self._job(200000))
        self.assertTrue(ok)  # 8s off

    def test_accepts_duration_mismatch_as_diagnostic(self):
        with patch.object(service_downloader, "_audio_duration_ms", return_value=320000):
            ok, msg = service_downloader.downloaded_track_matches_request(Path("x.flac"), self._job(200000))
        self.assertTrue(ok)
        self.assertIn("duration differs", msg)


if __name__ == "__main__":
    unittest.main()
