import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import service_downloader
import backend_spotiflac


class PlaybackSourceTests(unittest.TestCase):
    def test_physical_lossy_file_is_not_lossless_just_because_job_requested_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'youtube.webm'
            path.write_bytes(b'webm')
            self.assertLess(service_downloader._quality_rank(path, 'LOSSLESS'), 700)
            self.assertEqual(service_downloader._quality_rank(Path('requested.LOSSLESS'), 'LOSSLESS'), 700)

    def test_saved_m4a_uses_actual_codec_for_lossless_rank(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Song.m4a"
            path.write_bytes(b"test")
            for codec, expected in (("alac", 700), ("mp4a.40.2", 430)):
                with self.subTest(codec=codec), patch("mutagen.mp4.MP4", return_value=SimpleNamespace(info=SimpleNamespace(codec=codec))):
                    self.assertEqual(service_downloader._quality_rank(path, "LOSSLESS"), expected)

    def test_reuses_equal_or_better_file_across_engines_and_only_fetches_for_upgrade(self):
        manager = object.__new__(service_downloader.ServiceDownloadManager)
        manager.config = SimpleNamespace(default_quality='LOSSLESS')
        for quality in (700, 800, 380):
            status = {'library_path': '/Music/Song.flac', 'cache_path': '', 'library_quality': quality, 'cache_quality': 0}
            with self.subTest(saved_rank=quality), patch.object(manager, 'library_status', return_value=status):
                source = manager.playback_source({'engine': 'monochrome', 'quality': 'LOSSLESS'})
            self.assertEqual(bool(source['path']), quality >= 700)
        self.assertEqual(service_downloader._quality_rank(Path('Song.wav')), service_downloader._quality_rank(Path('Song.flac')))

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

    def test_library_status_batch_walks_the_cache_directory_only_once(self):
        # _find_cache_entry used to re-walk the entire cache directory and
        # re-check every job's file on disk for every single track in a
        # batch — a playlist of a few hundred tracks meant a few hundred full
        # re-walks for the exact same, search-independent answer each time,
        # which could take minutes or simply never return. The cache side of
        # the fix mirrors the music-library side tested just above.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_track = root / "cache" / "job-1" / "For Your Babies - Simply Red.m4a"
            cache_track.parent.mkdir(parents=True)
            cache_track.write_bytes(b"ftyp" + b"\0" * (101 * 1024))
            (cache_track.parent / "metadata.json").write_text(
                '{"tracks": {"For Your Babies": {"artist": "Simply Red", "album": "Stars"}}}',
                encoding="utf-8",
            )
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
                    statuses = manager.library_status_batch([payload, payload, payload])

        self.assertEqual([status["in_library"] for status in statuses], [False, False, False])
        self.assertTrue(all(status["cached"] for status in statuses))
        self.assertEqual([status["cache_path"] for status in statuses], [str(cache_track)] * 3)
        # Once for the music-library walk, once for the cache-directory walk
        # — not once per track for either.
        self.assertEqual(find_audio.call_count, 2)

    def test_cache_status_still_matches_a_sidecar_entry_missing_its_own_artist(self):
        # _cache_job_from_sidecar used to fall back to the identity being
        # *searched for* when a sidecar entry had no artist/album of its own,
        # which made that one comparison trivially succeed. It now falls back
        # to a neutral "Unknown Artist" instead, since there is no search
        # identity at the point this now runs — ISRC/Spotify id/MusicBrainz
        # id matching in _job_matches_identity still finds it regardless.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_track = root / "cache" / "job-1" / "Mystery Track.m4a"
            cache_track.parent.mkdir(parents=True)
            cache_track.write_bytes(b"ftyp" + b"\0" * (101 * 1024))
            (cache_track.parent / "metadata.json").write_text(
                '{"tracks": {"Mystery Track": {"isrc": "USUM71700001"}}}',
                encoding="utf-8",
            )
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            payload = {"artist": "Any Artist", "album": "Any Album", "title": "Mystery Track", "isrc": "USUM71700001"}
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                status = manager.library_status(payload)

        self.assertTrue(status["cached"])
        self.assertEqual(status["cache_path"], str(cache_track))

    def test_hide_from_recent_flags_every_job_matching_the_track_not_just_one(self):
        # A replayed track can have multiple finished jobs (replays,
        # re-downloads) — "remove from recently played" must hide all of
        # them, or the row would just reappear from an older job on refresh.
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
                manager.jobs["job-1"] = {
                    "id": "job-1", "status": "finished", "mode": "stream",
                    "title": "Thriller", "artist": "Michael Jackson", "album": "Thriller",
                    "spotify_id": "2LlQb7Uoj1kKyGhlkBf9aC", "created_at": 100,
                }
                manager.jobs["job-2"] = {
                    "id": "job-2", "status": "finished", "mode": "stream",
                    "title": "Thriller", "artist": "Michael Jackson", "album": "Thriller",
                    "spotify_id": "2LlQb7Uoj1kKyGhlkBf9aC", "created_at": 200,
                }
                manager.jobs["job-3"] = {
                    "id": "job-3", "status": "finished", "mode": "stream",
                    "title": "Beat It", "artist": "Michael Jackson", "album": "Thriller",
                    "spotify_id": "3BovdzfaX4jb5KFQwoPfAw", "created_at": 150,
                }
                hidden = manager.hide_from_recent({
                    "artist": "Michael Jackson", "album": "Thriller", "title": "Thriller",
                    "spotify_id": "2LlQb7Uoj1kKyGhlkBf9aC",
                })

        self.assertEqual(hidden, 2)
        self.assertTrue(manager.jobs["job-1"]["hidden_from_recent"])
        self.assertTrue(manager.jobs["job-2"]["hidden_from_recent"])
        self.assertFalse(manager.jobs["job-3"].get("hidden_from_recent"))

    def test_selected_track_metadata_replaces_unknown_provider_artist(self):
        class Track:
            title = "Two Hearts"
            artists = "Unknown"
            album = "Love Songs"
            album_artist = "Unknown"

            def model_copy(self, update):
                return update

        updated = backend_spotiflac.requested_spotiflac_track_metadata(Track(), {
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
        options = backend_spotiflac.spotiflac_download_options(
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
        message = backend_spotiflac.spotiflac_failure_message([
            "[tidal] gist fetch failed: Tidal API gist did not return a JSON array",
        ])

        self.assertEqual(message, "All providers failed and no playable audio file was found")

    def test_atmos_fallback_stays_with_lossless_providers_and_translates_quality(self):
        services = backend_spotiflac.spotiflac_fallback_services("tidal", "DOLBY_ATMOS")

        self.assertEqual(services, ["tidal", "qobuz", "deezer", "amazon", "apple"])
        self.assertEqual(backend_spotiflac.spotiflac_provider_quality("DOLBY_ATMOS", "qobuz"), "27")
        self.assertEqual(backend_spotiflac.spotiflac_provider_quality("DOLBY_ATMOS", "deezer"), "LOSSLESS")

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

    def test_ytpdl_job_enriches_genre_metadata_before_backend_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="youtube",
                default_quality="LOSSLESS",
                download_engine="ytp-dl",
            )
            fake_db = SimpleNamespace(get_resolved_source_for_keys=Mock(return_value=None))
            fake_music_metadata = SimpleNamespace(
                enrich_track_identifiers=Mock(return_value={
                    "artist": "Antonio Vivaldi",
                    "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti",
                    "genres": ["Classical", "Baroque"],
                    "genre": "Classical",
                })
            )

            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    with patch.dict(sys.modules, {"db": fake_db, "music_metadata": fake_music_metadata}):
                        manager = service_downloader.ServiceDownloadManager(config)
                        job = manager.start_job({
                            "mode": "stream",
                            "engine": "ytp-dl",
                            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti",
                            "artist": "Antonio Vivaldi",
                            "metadata": {},
                        })

        self.assertEqual(job["metadata"]["genre"], "Classical")
        self.assertEqual(job["metadata"]["genres"], ["Classical", "Baroque"])
        fake_music_metadata.enrich_track_identifiers.assert_called_once()
        thread.assert_called_once()

    def test_ytpdl_job_recovers_spotify_id_from_track_key_before_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="youtube",
                default_quality="LOSSLESS",
                download_engine="ytp-dl",
            )
            fake_db = SimpleNamespace(get_resolved_source_for_keys=Mock(return_value=None))
            fake_music_metadata = SimpleNamespace(
                enrich_track_identifiers=Mock(return_value={
                    "spotify_id": "7DZb1nzqvKMVcN8KEfu6kk",
                    "artist": "Antonio Vivaldi",
                    "title": "Mentre dormi amor fomenti",
                    "genre": "Classical",
                })
            )

            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                with patch.object(service_downloader.threading, "Thread") as thread:
                    with patch.dict(sys.modules, {"db": fake_db, "music_metadata": fake_music_metadata}):
                        manager = service_downloader.ServiceDownloadManager(config)
                        job = manager.start_job({
                            "mode": "stream",
                            "engine": "ytp-dl",
                            "title": "Mentre dormi amor fomenti",
                            "artist": "Antonio Vivaldi",
                            "metadata": {"track_key": "spotify_id:7DZb1nzqvKMVcN8KEfu6kk"},
                        })

        fake_music_metadata.enrich_track_identifiers.assert_called_once()
        self.assertEqual(
            fake_music_metadata.enrich_track_identifiers.call_args.args[0]["spotify_id"],
            "7DZb1nzqvKMVcN8KEfu6kk",
        )
        self.assertEqual(job["metadata"]["spotify_id"], "7DZb1nzqvKMVcN8KEfu6kk")
        self.assertEqual(job["metadata"]["genre"], "Classical")
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

    def test_reuses_completed_audio_despite_remaster_duration_drift(self):
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

        self.assertEqual(source["source"], "cache")
        self.assertTrue(source["cached"])

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

    def test_recovers_cache_file_from_disk_when_job_record_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache" / "lost-job"
            cache_path = cache_dir / "Bad - Michael Jackson.flac"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"fLaC" + b"\0" * (101 * 1024))
            (cache_dir / "metadata.json").write_text(
                '{"album_info":{"artist":"Michael Jackson","album":"Bad"},"tracks":{"Bad":{"title":"Bad","artist":"Michael Jackson","spotify_id":"spotify-id"}}}',
                "utf-8",
            )
            config = SimpleNamespace(
                music_dir=root / "music",
                cache_dir=root / "cache",
                download_service="tidal",
                default_quality="LOSSLESS",
            )
            with patch.object(service_downloader, "JOBS_PATH", root / "jobs.json"):
                manager = service_downloader.ServiceDownloadManager(config)
                source = manager.playback_source({
                    "artist": "Michael Jackson",
                    "album": "Bad",
                    "title": "Bad",
                    "spotify_id": "spotify-id",
                    "quality": "LOSSLESS",
                })

        self.assertEqual(source["source"], "cache")
        self.assertEqual(source["path"], str(cache_path))

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

    def test_repairs_mislabeled_flac_cache_file_before_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "cache" / "job-id"
            output_dir.mkdir(parents=True)
            mislabeled = output_dir / "My Vision - Seal.flac"
            mislabeled.write_bytes(b"\0\0\0\x18ftypM4A " + b"\0" * (101 * 1024))

            audio_files = service_downloader._find_audio_files(output_dir)

        self.assertEqual([path.name for path in audio_files], ["My Vision - Seal.m4a"])
        self.assertFalse(mislabeled.exists())

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

    def test_progress_watcher_does_not_mark_stable_partial_audio_finished(self):
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

        self.assertEqual(job["status"], "running")
        self.assertLess(job["progress"], 100)

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

    def test_rejects_movie_length_video_duration_mismatch(self):
        with patch.object(service_downloader, "_audio_duration_ms", return_value=5400000):
            ok, msg = service_downloader.downloaded_track_matches_request(
                Path("x.mp4"),
                {"quality": "video", "metadata": {"duration_ms": 313000}},
            )
        self.assertFalse(ok)
        self.assertIn("video duration mismatch", msg)


if __name__ == "__main__":
    unittest.main()


class MonochromeStreamFallbackTests(unittest.TestCase):
    """A Monochrome catalog miss must not leave a stream with nothing to play."""

    def _run(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            manager = service_downloader.ServiceDownloadManager.__new__(service_downloader.ServiceDownloadManager)
            import threading
            manager._lock = threading.RLock()
            manager._cancel_flags = set()
            manager.jobs = {}
            events = []
            manager._append_cache_event = lambda job, kind, message: events.append((kind, message))
            manager._ensure_progress_thread = lambda: None
            manager._save_jobs = lambda: None
            manager._output_dir = lambda job: Path(tmp) / job["id"]
            job = {"id": "j1", "mode": mode, "engine": "monochrome", "service": "monochrome", "quality": "LOSSLESS",
                   "title": "Our House", "artist": "Madness", "status": "queued", "source_recording": {"title": "x"}}
            manager.jobs["j1"] = job
            ran = []
            miss = RuntimeError("Monochrome official instances failed: https://tracks.monochrome.st: no exact ISRC or title/artist match")
            fake_mono = SimpleNamespace(run=Mock(side_effect=miss))
            fake_yt = SimpleNamespace(run=lambda out, j, m: ran.append(dict(j)) or (_ for _ in ()).throw(RuntimeError("stop after YouTube")))
            with patch.dict(sys.modules, {"backend_monochrome": fake_mono, "backend_ytpdl": fake_yt}), \
                 patch.object(manager, "_resolve_job_metadata", side_effect=lambda j, p: p, create=True):
                manager._worker("j1", {"metadata": {}})
            return job, ran, events

    def test_stream_continues_on_youtube(self):
        job, ran, events = self._run("stream")
        self.assertEqual(len(ran), 1, "YouTube takes over the same job")
        self.assertEqual((ran[0]["engine"], ran[0]["service"], ran[0]["quality"]), ("ytp-dl", "youtube", "best"))
        self.assertNotIn("source_recording", ran[0])
        self.assertTrue(any("using YouTube for this track" in message for _, message in events))

    def test_explicit_download_keeps_the_monochrome_error(self):
        job, ran, events = self._run("download")
        self.assertEqual(ran, [], "a lossless download never silently becomes YouTube")
        self.assertIn("no exact ISRC", job.get("error") or "")
