"""Gemini chat access via a real, headed Chromium driven by Playwright."""
from __future__ import annotations

import os

from browser_worker_proxy import JsonLineWorker

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_browser.py")
_worker = JsonLineWorker(
    _WORKER_SCRIPT,
    "--gemini-worker",
    90,
    30,
    hide_frozen_stderr=True,
    env_factory=lambda: {
        **os.environ,
        "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING", "utf-8"),
        "PYTHONUTF8": os.environ.get("PYTHONUTF8", "1"),
    },
)


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


def fetch_status() -> dict:
    if _worker.ensure():
        return {"ok": True, "error": ""}
    return {"ok": False, "error": _worker.last_error or "gemini worker unavailable"}


def send_chat(
    prompt: str,
    messages: list | None = None,
    ensure_model: str = "",
    timeout_s: float | None = None,
) -> dict:
    payload = {"prompt": _compose_prompt(prompt, messages)}
    if ensure_model:
        payload["ensure_model"] = ensure_model
    if timeout_s is not None and timeout_s > 0:
        payload["timeout_s"] = timeout_s
    return _worker.request(payload, reply_timeout=timeout_s)


def shutdown() -> None:
    """Stop the long-running Gemini worker if it is running."""
    _worker.shutdown()
