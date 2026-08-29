"""Duck.ai chat through its real frontend in a managed browser worker."""
from __future__ import annotations

import os

from browser_worker_proxy import JsonLineWorker

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ddg_browser.py")
_READY_TIMEOUT_S = float(os.environ.get("MINDINGUFLAC_DDG_READY_TIMEOUT", "90"))
_worker = JsonLineWorker(
    _WORKER_SCRIPT,
    "--ddg-worker",
    _READY_TIMEOUT_S,
    20,
)


def fetch_status(user_agent: str = "") -> dict:
    """Ensure Duck.ai is ready and return the legacy-compatible status shape."""
    del user_agent
    ok = _worker.ensure(
        lambda error: "Playwright Sync API inside the asyncio loop" in error
    )
    if ok:
        return {"vqd_hash_1": "browser", "error": ""}
    return {
        "vqd_hash_1": "",
        "error": _worker.last_error or "browser worker unavailable",
    }


def send_chat(
    token: str,
    messages: list,
    model: str = "gpt-5-mini",
    web_search: bool = False,
    ensure_model: str = "",
    reply_timeout: float | None = None,
    **kwargs,
) -> dict:
    """Run one chat turn through Duck.ai's browser frontend."""
    del token, kwargs
    payload = {"messages": messages, "model": model}
    if web_search:
        payload["web_search"] = True
    if ensure_model:
        payload["ensure_model"] = ensure_model
    if reply_timeout is not None and reply_timeout > 0:
        payload["timeout_s"] = reply_timeout
    return _worker.request(payload, reply_timeout=reply_timeout)


def shutdown() -> None:
    """Stop the long-running Duck.ai worker if it is running."""
    _worker.shutdown()
