"""Provider jobs through Mornye's versioned local REST API."""
from __future__ import annotations

import os
import time
from pathlib import Path

from mornye_runtime import request


class MornyeRateLimited(RuntimeError):
    """The provider gateway refused this address with 429."""


def rate_limit_remaining() -> float:
    """Seconds the provider gateway still refuses requests (0 when unknown)."""
    try:
        from mornye.core.signed_session_mobile import rate_limited_seconds
    except ImportError:
        return 0.0
    return rate_limited_seconds()


def _raise_if_rate_limited() -> None:
    # Every provider goes through the same gateway, so retrying another one
    # only spends more requests; a long wait means the daily quota is gone.
    remaining = rate_limit_remaining()
    if remaining > 60:
        hours, minutes = divmod(int(remaining + 59) // 60, 60)
        wait = f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"
        raise MornyeRateLimited(f"Mornye download limit reached; it resets in about {wait}")


def run(url: str, output_dir: Path, job: dict, manager):
    _raise_if_rate_limited()
    providers = request("GET", "/extensions").get("providers", [])
    installed = [row["provider"] for row in providers if row.get("installed")]
    if not installed:
        raise RuntimeError("Mornye needs an installed provider extension. Monochrome and YouTube remain available independently.")
    selected = str(job.get("service") or "").replace("apple_music", "apple")
    # Explicit installed IDs are more robust than assuming upstream ships
    # providers. Put the user's selected service first, then installed peers.
    installed.sort(key=lambda name: (not name.removeprefix("ext:").startswith(selected), name))
    if os.environ.get("MINDINGUFLAC_ANDROID") == "1":
        # Each provider has its own signed session, and a lapsed one needs a
        # Cloudflare check the user must tap. Falling back through every
        # provider would ask for one per provider, so the phone uses only
        # the selected service when it is installed.
        chosen = [name for name in installed if name.removeprefix("ext:").startswith(selected)]
        installed = chosen or installed
        if not job.get("prefetch"):
            # A failed check pauses verification for 5 min, then 15, ...; in
            # the pause the extension only reports "Download API failed" and
            # no challenge is shown. A song the user picked tries again.
            _clear_verification_pause()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = request("POST", "/downloads", payload={
        "url": url, "quality": job.get("quality") or "LOSSLESS",
        "services": installed, "output_dir": str(output_dir.resolve()),
    })
    remote_id = str(result["id"])
    with manager._lock:
        job["mornye_job_id"] = remote_id
    manager._append_cache_event(job, "provider", "Mornye provider job queued")
    while True:
        if job["id"] in manager._cancel_flags:
            request("POST", f"/downloads/{remote_id}/cancel", payload={})
            return
        try:
            _raise_if_rate_limited()
        except MornyeRateLimited:
            request("POST", f"/downloads/{remote_id}/cancel", payload={})
            raise
        result = request("GET", f"/downloads/{remote_id}")
        status = result.get("status")
        if status == "done":
            return
        if status in {"failed", "cancelled"}:
            error = result.get("error") or f"Mornye download {status}"
            if status == "failed" and _verification_paused():
                error = ("Provider verification did not complete, so the download was refused. "
                         "Play the song again to retry the check.")
            raise RuntimeError(error)
        payload = result.get("payload") or {}
        total = int(payload.get("items") or 0)
        completed = int(payload.get("completed_items") or 0)
        with manager._lock:
            job["last_status"] = f"Mornye: {status or 'running'}"
            if total:
                job["progress"] = max(float(job.get("progress") or 0), min(95, completed / total * 100))
        time.sleep(0.5)


def _verification_pauses() -> list[Path]:
    """Mornye's per-gateway pause files after a failed signed-session check."""
    root = os.environ.get("MORNYE_DATA_DIR")
    return list((Path(root) / "signed_sessions").glob(".*.auth-backoff.json")) if root else []


def _clear_verification_pause() -> None:
    for path in _verification_pauses():
        path.unlink(missing_ok=True)


def _verification_paused() -> bool:
    return bool(_verification_pauses())
