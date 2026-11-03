"""backend_mornye stops at once while the provider gateway answers 429."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend_mornye  # noqa: E402
from mornye.core import signed_session_mobile  # noqa: E402


class _Manager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_flags = set()

    def _append_cache_event(self, job, kind, message):
        pass


class RateLimitTests(unittest.TestCase):
    def tearDown(self):
        signed_session_mobile._RATE_LIMITED_UNTIL.clear()

    def _run(self, request):
        with tempfile.TemporaryDirectory() as tmp, patch.object(backend_mornye, "request", side_effect=request), \
             patch.object(backend_mornye.time, "sleep"):
            backend_mornye.run("https://open.spotify.com/track/x", Path(tmp), {"id": "j1", "service": "amazon"}, _Manager())

    def test_rate_limited_gateway_skips_mornye_without_requests(self):
        signed_session_mobile._RATE_LIMITED_UNTIL["zarz-v2"] = time.time() + 81000
        calls = []
        with self.assertRaisesRegex(backend_mornye.MornyeRateLimited, r"resets in about 22 h"):
            self._run(lambda *args, **kwargs: calls.append(args))
        self.assertEqual(calls, [])

    def test_running_job_is_cancelled_when_429_arrives(self):
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path))
            if path == "/extensions":
                return {"providers": [{"provider": "ext:amazon", "installed": True}]}
            if path == "/downloads":
                return {"id": "m1"}
            # The provider got a 429 while the job was running.
            signed_session_mobile._RATE_LIMITED_UNTIL["zarz-v2"] = time.time() + 3600
            return {"status": "running"}

        with self.assertRaises(backend_mornye.MornyeRateLimited):
            self._run(request)
        self.assertEqual(calls[-1], ("POST", "/downloads/m1/cancel"))

    def test_short_wait_still_tries(self):
        signed_session_mobile._RATE_LIMITED_UNTIL["zarz-v2"] = time.time() + 30

        def request(method, path, payload=None):
            if path == "/extensions":
                return {"providers": [{"provider": "ext:amazon", "installed": True}]}
            if path == "/downloads":
                return {"id": "m1"}
            return {"status": "done"}

        self._run(request)


if __name__ == "__main__":
    unittest.main()
