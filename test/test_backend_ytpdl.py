import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import backend_ytpdl


class TestBackendYtpDl(unittest.TestCase):
    def test_quality_to_codec(self):
        self.assertEqual(backend_ytpdl._quality_to_codec("mp3"), "mp3")
        self.assertEqual(backend_ytpdl._quality_to_codec("m4a"), "m4a")
        self.assertEqual(backend_ytpdl._quality_to_codec(""), "m4a")

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.m4a")])
    def test_run_uses_youtube_resolution_and_records_output(self, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {"id": "job-1", "quality": "m4a", "track": {}, "metadata": {}}
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        yt_dlp_instance.download.assert_called_once()
        self.assertEqual(job["provider_used"], "ytp-dl")
        self.assertEqual(job["library_path"], "/tmp/out/song.m4a")


if __name__ == "__main__":
    unittest.main()
