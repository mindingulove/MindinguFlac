"""Android YouTube sign-in: CookieManager strings become the desktop session file."""
import os
import sys
import tempfile
import unittest
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_PYTHON = REPO_ROOT / "android-app" / "app" / "src" / "main" / "python"
for entry in (str(REPO_ROOT), str(ANDROID_PYTHON)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from android_runtime import youtube_login  # noqa: E402
import backend_ytpdl  # noqa: E402


class SaveTests(unittest.TestCase):
    def test_signed_in_cookies_are_saved_for_yt_dlp(self):
        with tempfile.TemporaryDirectory() as tmp, patch("config.app_data_dir", return_value=Path(tmp)):
            self.assertTrue(youtube_login.save("PREF=f6=40; SAPISID=abc/def; __Secure-3PSID=x=y", "SID=g1; HSID=g2"))
            jar = MozillaCookieJar(str(Path(tmp) / "youtube-webview-cookies.txt"))
            jar.load(ignore_discard=True, ignore_expires=True)
            cookies = {(c.domain, c.name): c.value for c in jar}
            self.assertEqual(cookies[(".youtube.com", "SAPISID")], "abc/def")
            self.assertEqual(cookies[(".youtube.com", "__Secure-3PSID")], "x=y")
            self.assertEqual(cookies[(".google.com", "SID")], "g1")
            self.assertTrue((Path(tmp) / "youtube-webview-session.json").is_file())
            self.assertEqual(backend_ytpdl._youtube_cookie_file(), str(Path(tmp) / "youtube-webview-cookies.txt"))

    def test_signed_out_cookies_are_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp, patch("config.app_data_dir", return_value=Path(tmp)):
            self.assertFalse(youtube_login.save("PREF=f6=40; VISITOR_INFO1_LIVE=v", ""))
            self.assertFalse((Path(tmp) / "youtube-webview-cookies.txt").exists())


class DownloadOptionTests(unittest.TestCase):
    def test_signed_in_phone_uses_node_and_cookie_capable_clients(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}), \
                patch.object(backend_ytpdl, "_youtube_cookie_file", return_value="/data/youtube-webview-cookies.txt"), \
                patch("shutil.which", return_value="/data/cache/mornye-bin/node"):
            self.assertEqual(backend_ytpdl._youtube_extractor_args(), {})
            self.assertEqual(backend_ytpdl._youtube_js_runtime_opts(),
                             {"js_runtimes": {"node": {"path": "/data/cache/mornye-bin/node"}}})

    def test_signed_out_phone_keeps_the_mobile_clients(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_ANDROID": "1"}), \
                patch.object(backend_ytpdl, "_youtube_cookie_file", return_value=""), \
                patch("shutil.which", return_value=None):
            self.assertEqual(backend_ytpdl._youtube_extractor_args()["youtube"]["player_client"], ["android", "ios", "web"])
            self.assertEqual(backend_ytpdl._youtube_js_runtime_opts(), {})


if __name__ == "__main__":
    unittest.main()
