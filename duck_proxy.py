"""Duck.ai chat access via a real, headed Chromium driven by the genuine frontend.

Background: DuckDuckGo gates the chat endpoint behind "RoboShield"
(`418 / ERR_CHALLENGE / type:"brs"`). That challenge is solved by Duck.ai's own
bundled frontend JavaScript, not by any header we can forge — a static
`x-vqd-hash-1`, a hand-solved challenge, or a headless-shell browser are all
fingerprinted and rejected. The only reliable path is to let a real headed
browser run the actual frontend and send the chat itself.

This module manages a single long-running browser worker subprocess
(`ddg_browser.py`) and speaks line-delimited JSON to it. Playwright's sync API
is single-threaded, so all access is serialized behind a lock; the threaded HTTP
server in app.py can call these functions from any thread safely.

Public API (unchanged for callers like ai_reranker.py):
  - fetch_status() -> {"vqd_hash_1": <sentinel|"">, "error": str}
  - send_chat(token, messages, model) -> {"ok": bool, "text": str, ...}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ddg_browser.py")
_READY_TIMEOUT_S = float(os.environ.get("MINDINGUFLAC_DDG_READY_TIMEOUT", "90"))
_REPLY_TIMEOUT_S = float(os.environ.get("MINDINGUFLAC_DDG_REPLY_TIMEOUT", "75")) + 20

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_req_id = 0
_last_error = ""


def _worker_alive() -> bool:
    return _proc is not None and _proc.poll() is None


def _start_worker() -> bool:
    """Spawn the browser subprocess and block until it reports readiness."""
    global _proc, _last_error
    _stop_worker()
    # In a frozen app (PyInstaller) sys.executable is the app binary, not python,
    # so re-enter via a flag the app handles; in dev, run the worker script.
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--ddg-worker"]
    else:
        cmd = [sys.executable, _WORKER_SCRIPT]
    try:
        _proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # inherit -> worker logs land in the server console
            text=True,
            bufsize=1,  # line-buffered
            cwd=os.path.dirname(_WORKER_SCRIPT),
            env=dict(os.environ),
        )
    except Exception as exc:
        _last_error = f"spawn failed: {exc}"
        _proc = None
        return False

    deadline = time.time() + _READY_TIMEOUT_S
    while time.time() < deadline:
        if _proc.poll() is not None:
            _last_error = "worker exited during startup"
            _proc = None
            return False
        line = _proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            banner = json.loads(line)
        except Exception:
            continue
        if banner.get("ready"):
            _last_error = ""
            return True
        _last_error = banner.get("error", "worker not ready")
        _stop_worker()
        return False
    _last_error = "worker readiness timed out"
    _stop_worker()
    return False


def _stop_worker():
    global _proc
    if _proc is not None:
        try:
            if _proc.poll() is None:
                try:
                    _proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                    _proc.stdin.flush()
                except Exception:
                    pass
                try:
                    _proc.wait(timeout=5)
                except Exception:
                    _proc.kill()
        except Exception:
            pass
    _proc = None


def _ensure_worker() -> bool:
    if _worker_alive():
        return True
    return _start_worker()


def _exchange(payload: dict, reply_timeout: float | None = None) -> dict:
    """Send one request and read its matching reply (caller holds _lock)."""
    global _req_id, _last_error
    _req_id += 1
    rid = _req_id
    payload["id"] = rid
    try:
        _proc.stdin.write(json.dumps(payload) + "\n")
        _proc.stdin.flush()
    except Exception as exc:
        _last_error = f"write failed: {exc}"
        _stop_worker()
        return {"ok": False, "error": _last_error}

    # Web-search / GPT-5 turns can run well past the default reply window; let
    # callers extend it. Pad past the worker's own deadline so it answers first.
    wait_s = (reply_timeout + 20) if reply_timeout else _REPLY_TIMEOUT_S
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _proc.poll() is not None:
            _last_error = "worker died while awaiting reply"
            _stop_worker()
            return {"ok": False, "error": _last_error}
        line = _proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            reply = json.loads(line)
        except Exception:
            continue
        if reply.get("id") == rid:
            return reply
        # Ignore stray/non-matching lines (shouldn't normally happen).
    _last_error = "reply timed out"
    _stop_worker()
    return {"ok": False, "error": _last_error}


def fetch_status(user_agent: str = "") -> dict:
    """Compatibility gate. Ensures the browser worker is up.

    Returns a sentinel token so existing callers proceed; the real anti-bot
    handling happens inside the browser, not here.
    """
    with _lock:
        ok = _ensure_worker()
    if ok:
        return {"vqd_hash_1": "browser", "error": ""}
    return {"vqd_hash_1": "", "error": _last_error or "browser worker unavailable"}


def send_chat(
    token: str,
    messages: list,
    model: str = "gpt-5-mini",
    web_search: bool = False,
    ensure_model: str = "",
    reply_timeout: float | None = None,
    **kwargs,
) -> dict:
    """Run one chat turn through the real Duck.ai frontend in the browser worker.

    `token` is ignored (legacy x-vqd-4 placeholder). `model` is best-effort: the
    browser uses Duck.ai's currently selected model. Set `web_search=True` to
    turn on Duck.ai's Web Search tool for the turn (live, sourced answers) and
    `ensure_model` (e.g. "GPT-5") to force a specific model. `reply_timeout`
    extends the wait for slow web-search turns. Returns {"ok", "text", ...}.
    """
    payload = {"messages": messages, "model": model}
    if web_search:
        payload["web_search"] = True
    if ensure_model:
        payload["ensure_model"] = ensure_model
    if reply_timeout:
        payload["timeout_s"] = reply_timeout
    with _lock:
        if not _ensure_worker():
            return {"ok": False, "error": _last_error or "browser worker unavailable"}
        res = _exchange(dict(payload), reply_timeout=reply_timeout)
        # One automatic restart+retry if the worker dropped mid-exchange.
        if not res.get("ok") and not _worker_alive():
            if _start_worker():
                res = _exchange(dict(payload), reply_timeout=reply_timeout)
    return res


def save_bypass(data):  # retained for backward compatibility
    pass
