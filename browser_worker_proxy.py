"""Shared lifecycle manager for line-delimited JSON browser workers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable


class JsonLineWorker:
    def __init__(
        self,
        script: str,
        frozen_flag: str,
        ready_timeout: float,
        reply_padding: float,
        *,
        hide_frozen_stderr: bool = False,
        env_factory: Callable[[], dict] | None = None,
    ) -> None:
        self.script = script
        self.frozen_flag = frozen_flag
        self.ready_timeout = ready_timeout
        self.reply_padding = reply_padding
        self.hide_frozen_stderr = hide_frozen_stderr
        self.env_factory = env_factory or (lambda: dict(os.environ))
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.request_id = 0
        self.last_error = ""

    def _alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                try:
                    process.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass
                try:
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except Exception:
                        pass
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass

    def _start(self) -> bool:
        self._stop()
        frozen = bool(getattr(sys, "frozen", False))
        command = [sys.executable, self.frozen_flag] if frozen else [sys.executable, self.script]
        stderr = subprocess.DEVNULL if frozen and self.hide_frozen_stderr else None
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=os.path.dirname(self.script),
                env=self.env_factory(),
            )
        except Exception as exc:
            self.last_error = f"spawn failed: {exc}"
            self.process = None
            return False

        deadline = time.time() + self.ready_timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                self.last_error = "worker exited during startup"
                self._stop()
                return False
            line = self.process.stdout.readline()
            if not line:
                continue
            try:
                banner = json.loads(line.strip())
            except (json.JSONDecodeError, TypeError):
                continue
            if banner.get("ready"):
                self.last_error = ""
                return True
            self.last_error = str(banner.get("error") or "worker not ready")
            self._stop()
            return False

        self.last_error = "worker readiness timed out"
        self._stop()
        return False

    def _ensure(self) -> bool:
        return self._alive() or self._start()

    def ensure(self, retry_when: Callable[[str], bool] | None = None) -> bool:
        with self.lock:
            ok = self._ensure()
            if not ok and retry_when and retry_when(self.last_error):
                ok = self._ensure()
            return ok

    def _exchange(self, payload: dict, reply_timeout: float | None) -> dict:
        self.request_id += 1
        request_id = self.request_id
        message = dict(payload)
        message["id"] = request_id
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except Exception as exc:
            self.last_error = f"write failed: {exc}"
            self._stop()
            return {"ok": False, "error": self.last_error}

        deadline = (
            None if reply_timeout is None or reply_timeout <= 0
            else time.time() + reply_timeout + self.reply_padding
        )
        while deadline is None or time.time() < deadline:
            if not self._alive():
                self.last_error = "worker died while awaiting reply"
                self._stop()
                return {"ok": False, "error": self.last_error}
            line = self.process.stdout.readline()
            if not line:
                continue
            try:
                reply = json.loads(line.strip())
            except (json.JSONDecodeError, TypeError):
                continue
            if reply.get("id") == request_id:
                return reply

        self.last_error = "reply timed out"
        self._stop()
        return {"ok": False, "error": self.last_error}

    def request(self, payload: dict, reply_timeout: float | None = None) -> dict:
        with self.lock:
            if not self._ensure():
                return {"ok": False, "error": self.last_error or "browser worker unavailable"}
            result = self._exchange(payload, reply_timeout)
            if not result.get("ok") and not self._alive() and self._start():
                result = self._exchange(payload, reply_timeout)
            return result

    def shutdown(self) -> None:
        with self.lock:
            self._stop()
