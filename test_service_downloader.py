import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
