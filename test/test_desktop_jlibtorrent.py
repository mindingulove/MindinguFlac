import unittest
from unittest.mock import patch
import sys
from types import SimpleNamespace
from pathlib import Path

import desktop_jlibtorrent
import backend_video


class DesktopJlibtorrentPackagingTest(unittest.TestCase):
    def test_native_artifact_matches_each_supported_desktop_architecture(self):
        with patch.object(desktop_jlibtorrent.platform, "system", return_value="Darwin"), \
                patch.object(desktop_jlibtorrent.platform, "machine", return_value="arm64"):
            self.assertEqual(desktop_jlibtorrent._platform_jar(),
                             "jlibtorrent-macosx-arm64-2.0.12.9.jar")
        with patch.object(desktop_jlibtorrent.platform, "system", return_value="Darwin"), \
                patch.object(desktop_jlibtorrent.platform, "machine", return_value="x86_64"):
            self.assertEqual(desktop_jlibtorrent._platform_jar(),
                             "jlibtorrent-macosx-x86_64-2.0.12.9.jar")
        with patch.object(desktop_jlibtorrent.platform, "system", return_value="Windows"), \
                patch.object(desktop_jlibtorrent.platform, "machine", return_value="AMD64"):
            self.assertEqual(desktop_jlibtorrent._platform_jar(),
                             "jlibtorrent-windows-2.0.12.9.jar")

    def test_android_engine_source_generates_desktop_bridge(self):
        from desktop_torrent.build_bridge import ANDROID_SOURCE
        source = ANDROID_SOURCE.read_text(encoding="utf-8")
        desktop = source.replace("package com.mindinguflac.android;", "package com.mindinguflac.desktop;")
        desktop = desktop.replace("AndroidTorrentEngine", "DesktopTorrentEngine")
        self.assertIn("Priority.SEVEN", desktop)
        self.assertIn("session.fetchMagnet", desktop)
        self.assertIn("handle.prioritizeFiles", desktop)
        self.assertIn("class DesktopTorrentEngine", desktop)
        self.assertNotIn("package com.mindinguflac.android;", desktop)

    def test_video_clip_download_uses_youtube_without_torrent_engine(self):
        class FakeYoutubeDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _query, download=False):
                return {"entries": [{
                    "id": "video123", "title": "Jimi Hendrix Voodoo Chile Official Music Video",
                    "channel": "Official", "duration": 300,
                }]}

        with patch.dict(sys.modules, {"yt_dlp": SimpleNamespace(YoutubeDL=FakeYoutubeDL)}), \
                patch.object(backend_video, "_download_youtube_clip", return_value=True) as download, \
                patch.object(backend_video, "_clip_duration_ok", return_value=True):
            result = backend_video.fetch_clip_to_path(
                {"artist": "Jimi Hendrix", "title": "Voodoo Chile"},
                Path("/tmp/clip-test.mp4"), log_cb=lambda _message: None,
            )
        self.assertTrue(result)
        self.assertEqual(download.call_args.args[0], "https://www.youtube.com/watch?v=video123")


if __name__ == "__main__":
    unittest.main()
