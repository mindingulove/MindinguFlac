import unittest
from unittest.mock import patch

from browser_worker_proxy import JsonLineWorker


class BrowserWorkerProxyTests(unittest.TestCase):
    def test_request_restarts_once_after_worker_dies(self):
        worker = JsonLineWorker("worker.py", "--worker", 1, 1)
        with patch.object(worker, "_ensure", return_value=True):
            with patch.object(worker, "_alive", return_value=False):
                with patch.object(worker, "_start", return_value=True) as start:
                    with patch.object(
                        worker,
                        "_exchange",
                        side_effect=[{"ok": False}, {"ok": True, "text": "done"}],
                    ):
                        result = worker.request({"prompt": "hello"})
        self.assertEqual(result, {"ok": True, "text": "done"})
        start.assert_called_once()

    def test_ensure_can_retry_a_known_first_install_error(self):
        worker = JsonLineWorker("worker.py", "--worker", 1, 1)
        worker.last_error = ""

        def ensure_side_effect():
            if ensure_mock.call_count == 1:
                worker.last_error = "install restart required"
                return False
            return True

        with patch.object(worker, "_ensure", side_effect=ensure_side_effect) as ensure_mock:
            result = worker.ensure(lambda error: "restart" in error)
        self.assertTrue(result)
        self.assertEqual(ensure_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
