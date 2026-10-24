"""Provider jobs through Mornye's versioned local REST API."""
from __future__ import annotations

import time
from pathlib import Path

from mornye_runtime import request


def run(url: str, output_dir: Path, job: dict, manager):
    providers = request("GET", "/extensions").get("providers", [])
    installed = [row["provider"] for row in providers if row.get("installed")]
    if not installed:
        raise RuntimeError("Mornye needs an installed provider extension. Monochrome and YouTube remain available independently.")
    selected = str(job.get("service") or "").replace("apple_music", "apple")
    # Explicit installed IDs are more robust than assuming upstream ships
    # providers. Put the user's selected service first, then installed peers.
    installed.sort(key=lambda name: (not name.removeprefix("ext:").startswith(selected), name))
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
        result = request("GET", f"/downloads/{remote_id}")
        status = result.get("status")
        if status == "done":
            return
        if status in {"failed", "cancelled"}:
            raise RuntimeError(result.get("error") or f"Mornye download {status}")
        payload = result.get("payload") or {}
        total = int(payload.get("items") or 0)
        completed = int(payload.get("completed_items") or 0)
        with manager._lock:
            job["last_status"] = f"Mornye: {status or 'running'}"
            if total:
                job["progress"] = max(float(job.get("progress") or 0), min(95, completed / total * 100))
        time.sleep(0.5)
