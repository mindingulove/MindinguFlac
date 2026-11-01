"""Android Mornye support: bundled extension seeding and the Custom Tab solver shim."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
ANDROID_PYTHON = REPO_ROOT / "android-app" / "app" / "src" / "main" / "python"
for entry in (str(REPO_ROOT), str(ANDROID_PYTHON)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from android_runtime import mornye_android  # noqa: E402


def _extension(root: Path, name: str, version: str, body: str = "") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"name": name, "version": version}))
    (folder / "index.js").write_text(body or f"// {name} {version}")
    return folder


class SeedExtensionsTests(unittest.TestCase):
    def test_missing_and_older_extensions_are_installed_newer_ones_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundled, target = Path(tmp) / "bundled", Path(tmp) / "extensions"
            _extension(bundled, "deezer", "1.3.4", "bundled deezer")
            _extension(bundled, "tidal-web", "1.2.2", "bundled tidal")
            _extension(bundled, "qobuz-web", "1.2.10", "bundled qobuz")
            _extension(target, "tidal-web", "1.2.1", "old tidal")
            _extension(target, "qobuz-web", "1.3.0", "user qobuz")

            installed = mornye_android.seed_extensions(target, bundled)

            self.assertEqual(sorted(installed), ["deezer", "tidal-web"])
            self.assertEqual((target / "deezer" / "index.js").read_text(), "bundled deezer")
            self.assertEqual((target / "tidal-web" / "index.js").read_text(), "bundled tidal")
            self.assertEqual((target / "qobuz-web" / "index.js").read_text(), "user qobuz")
            self.assertEqual(sorted(p.name for p in target.iterdir()), ["deezer", "qobuz-web", "tidal-web"])
            self.assertEqual(mornye_android.seed_extensions(target, bundled), [])

    def test_repository_bundle_is_complete(self):
        bundled = REPO_ROOT / "vendor" / "mornye-extensions"
        names = {p.name for p in bundled.iterdir() if (p / "manifest.json").is_file()}
        self.assertTrue({"deezer", "tidal-web", "qobuz-web", "amazon"} <= names)
        for name in names:
            self.assertTrue((bundled / name / "index.js").is_file(), name)


class SolverShimTests(unittest.TestCase):
    CHALLENGE = ("https://api.zarz.moe/v2/challenge?id=abc&cb="
                 "http%3A%2F%2F127.0.0.1%3A1%2Fcallback%3Fcb_version%3Dv2grant%26state%3Dzarz-v2")

    def test_callback_becomes_the_deep_link_keeping_its_state(self):
        url = mornye_android._with_callback(self.CHALLENGE)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["id"], ["abc"])
        self.assertEqual(query["cb"], ["mornye://session-grant?cb_version=v2grant&state=zarz-v2"])
        self.assertEqual(mornye_android._callback_state(self.CHALLENGE), "zarz-v2")

    def _verification(self, grants):
        calls = []

        class Verification:
            @staticmethod
            def request(url, state):
                calls.append(("request", url, state))
                return True

            @staticmethod
            def awaitGrant(timeout_ms):
                return grants.pop(0) if grants else ""

            @staticmethod
            def finish(verified):
                calls.append(("finish", verified))

        return Verification, calls

    def test_grant_from_the_deep_link_is_returned(self):
        verification, calls = self._verification(["", "grant-123"])
        with patch.dict(sys.modules, {"java": SimpleNamespace(jclass=lambda name: verification)}):
            self.assertEqual(mornye_android.solve_with_callback("key", self.CHALLENGE, 90), ("", "grant-123"))
        self.assertEqual(calls[0][2], "zarz-v2")
        self.assertIn("mornye%3A%2F%2Fsession-grant", calls[0][1])
        self.assertEqual(calls[-1], ("finish", True))

    def test_no_grant_before_cancel_is_reported_as_none(self):
        cancel = threading.Event()
        cancel.set()
        verification, calls = self._verification([])
        with patch.dict(sys.modules, {"java": SimpleNamespace(jclass=lambda name: verification)}):
            result = mornye_android.solve_with_callback("key", self.CHALLENGE, 10, cancel_event=cancel)
        self.assertEqual(result, ("", None))
        self.assertEqual(calls[-1], ("finish", False))


if __name__ == "__main__":
    unittest.main()
