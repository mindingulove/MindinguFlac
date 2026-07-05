"""Gemini chat access via a real, headed Chromium driven by Playwright."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_browser.py")
_READY_TIMEOUT_S = 90
_REPLY_TIMEOUT_S = 120

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_req_id = 0
_last_error = ""


def _worker_env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env

def _worker_alive() -> bool:
    return _proc is not None and _proc.poll() is None

def _compose_prompt(prompt: str, messages: list | None = None) -> str:
    """Flatten a chat request into the single prompt string the worker types."""
    if messages:
        parts = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            role = str(message.get("role") or "user").strip()
            parts.append(f"{role.title()}: {content}" if role else content)
        merged = "\n\n".join(parts).strip()
        if merged:
            return merged
    return str(prompt or "")

def _start_worker() -> bool:
    global _proc, _last_error
    _stop_worker()
    
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--gemini-worker"]
    else:
        cmd = [sys.executable, _WORKER_SCRIPT]
        
    try:
        _proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL if getattr(sys, "frozen", False) else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=os.path.dirname(_WORKER_SCRIPT),
            env=_worker_env(),
        )
    except Exception as exc:
        _last_error = f"spawn failed: {exc}"
        _proc = None
        return False

    deadline = time.time() + _READY_TIMEOUT_S
    while time.time() < deadline:
        if _proc.poll() is not None:
            _last_error = "worker exited during startup"
            _stop_worker()
            return False
        line = _proc.stdout.readline()
        if not line: continue
        line = line.strip()
        if not line: continue
        try:
            banner = json.loads(line)
        except Exception: continue
        
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
                except Exception: pass
                try:
                    _proc.wait(timeout=5)
                except Exception:
                    _proc.kill()
                    try:
                        _proc.wait(timeout=2)
                    except Exception:
                        pass
        except Exception: pass
        for stream in (_proc.stdin, _proc.stdout, _proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
    _proc = None

def _ensure_worker() -> bool:
    if _worker_alive(): return True
    return _start_worker()

def _exchange(payload: dict, reply_timeout: float | None = None) -> dict:
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

    deadline = None if reply_timeout is None or reply_timeout <= 0 else time.time() + (reply_timeout + 30)
    while deadline is None or time.time() < deadline:
        if _proc.poll() is not None:
            _last_error = "worker died while awaiting reply"
            _stop_worker()
            return {"ok": False, "error": _last_error}
        line = _proc.stdout.readline()
        if not line: continue
        line = line.strip()
        if not line: continue
        try:
            reply = json.loads(line)
        except Exception: continue
        if reply.get("id") == rid:
            return reply
            
    _last_error = "reply timed out"
    _stop_worker()
    return {"ok": False, "error": _last_error}

def fetch_status() -> dict:
    with _lock:
        ok = _ensure_worker()
    if ok:
        return {"ok": True, "error": ""}
    return {"ok": False, "error": _last_error or "gemini worker unavailable"}

def send_chat(prompt: str, messages: list | None = None, ensure_model: str = "", timeout_s: float | None = None) -> dict:
    payload = {"prompt": _compose_prompt(prompt, messages)}
    if ensure_model:
        payload["ensure_model"] = ensure_model
    if timeout_s is not None and timeout_s > 0:
        payload["timeout_s"] = timeout_s
        
    with _lock:
        if not _ensure_worker():
            return {"ok": False, "error": _last_error or "gemini worker unavailable"}
        res = _exchange(dict(payload), reply_timeout=timeout_s)
        if not res.get("ok") and not _worker_alive():
            if _start_worker():
                res = _exchange(dict(payload), reply_timeout=timeout_s)
    return res


def shutdown() -> None:
    """Stop the long-running Gemini worker if it is running."""
    with _lock:
        _stop_worker()
