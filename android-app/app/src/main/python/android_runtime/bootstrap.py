from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from android_runtime import capabilities


_server = None
_thread: threading.Thread | None = None


def _get_json(port: int, token: str, path: str) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-Mindinguflac-Token": token},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Backend returned invalid JSON for {path}")
    return value


def _preflight(port: int, token: str, cache_dir: Path, music_dir: Path) -> None:
    """Prove the authenticated HTTP backend is usable before showing the UI."""
    last_error: Exception | None = None
    for _ in range(25):
        try:
            health = _get_json(port, token, "/api/health")
            settings = _get_json(port, token, "/api/settings")
            if not health.get("ok") or not health.get("android"):
                raise RuntimeError("Backend health check did not report Android mode")
            expected = {
                "cache_dir": str(cache_dir),
                "music_dir": str(music_dir),
                "ai_provider": "android",
            }
            mismatch = {
                key: settings.get(key)
                for key, value in expected.items()
                if settings.get(key) != value
            }
            if mismatch:
                raise RuntimeError(f"Backend phone settings mismatch: {mismatch}")
            engine = str(settings.get("download_engine") or "")
            provider = str(settings.get("download_service") or "")
            quality = str(settings.get("default_quality") or "")
            # The engine must be one the capability probe proved usable, and
            # its service/quality must be one that engine actually supports.
            # Anything else means the UI could offer a download that cannot run.
            entry = (capabilities.runtime_report()["engines"].get(engine) or {})
            if not entry.get("available"):
                raise RuntimeError(
                    f"Backend selected unavailable engine {engine!r}: "
                    f"{entry.get('reason') or 'engine not reported by the runtime probe'}"
                )
            if provider not in entry.get("services", []) or quality not in entry.get("qualities", []):
                raise RuntimeError(
                    f"Backend phone download settings mismatch: {engine}/{provider}/{quality}"
                )
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.08)
    raise RuntimeError(f"Embedded backend preflight failed: {last_error}")


def _initialize_config(data_dir: Path, cache_dir: Path, music_dir: Path) -> None:
    """Normalize phone-only settings while preserving unrelated preferences."""
    config_path = data_dir / "config.json"
    existing = {}
    if config_path.exists():
        try:
            value = json.loads(config_path.read_text("utf-8"))
            if isinstance(value, dict):
                existing = value
        except Exception:
            existing = {}
    report = capabilities.runtime_report()
    engines = report["engines"]
    engine = str(existing.get("download_engine") or "").lower()
    if not (engines.get(engine) or {}).get("available"):
        engine = capabilities.default_engine()
    entry = engines.get(engine) or {}
    services = entry.get("services") or ["youtube"]
    qualities = entry.get("qualities") or ["m4a"]
    service = str(existing.get("download_service") or "").lower()
    if service not in services:
        service = services[0]
    quality = str(existing.get("default_quality") or "")
    if quality not in qualities:
        quality = qualities[0]
    existing.update(
        {
            "cache_dir": str(cache_dir),
            "music_dir": str(music_dir),
            "download_engine": engine,
            "download_service": service,
            "default_quality": quality,
            "ai_provider": "android",
            "gemini_model": "gemini-3.5-flash-lite",
            "tour_source": existing.get("tour_source") or "hypebot",
        }
    )
    config_path.write_text(
        json.dumps(existing, indent=2),
        encoding="utf-8",
    )


def start(data_path: str, cache_path: str, music_path: str, token: str) -> int:
    """Start the real Mindinguflac backend on an authenticated loopback port."""
    global _server, _thread
    if _server is not None:
        # The Python interpreter and HTTP server survive an Activity-only
        # recreate within the same process — Android reclaiming the Activity
        # under memory pressure without killing the process is common after
        # the app has been opened and closed repeatedly. MainActivity always
        # generates a fresh per-launch token and cookie regardless, so the
        # server has to adopt it here too. This branch used to return the
        # cached port without touching app.API_TOKEN, so the server kept
        # enforcing whatever token the *previous* launch had set; the new
        # cookie never matched it, and every authenticated request — search,
        # downloads, and the range-stream endpoint playback depends on —
        # started failing with 401 from that point on, with nothing in the UI
        # distinguishing it from any other playback failure.
        import app

        app.API_TOKEN = token
        port = int(_server.server_address[1])
        _preflight(port, token, Path(cache_path), Path(music_path))
        return port

    data_dir = Path(data_path) / "mindinguflac"
    cache_dir = Path(cache_path)
    music_dir = Path(music_path)
    for directory in (data_dir, cache_dir, music_dir):
        directory.mkdir(parents=True, exist_ok=True)

    os.environ["MINDINGUFLAC_ANDROID"] = "1"
    os.environ.pop("MINDINGUFLAC_DESKTOP", None)
    os.environ["MINDINGUFLAC_DATA_DIR"] = str(data_dir)
    os.environ["MINDINGUFLAC_CACHE_DIR"] = str(cache_dir)
    os.environ["MINDINGUFLAC_MUSIC_DIR"] = str(music_dir)
    os.environ["MINDINGUFLAC_API_TOKEN"] = token
    os.environ["MINDINGUFLAC_STATIC_DIR"] = str(Path(__file__).resolve().parent / "static")
    os.environ["MINDINGUFLAC_AI_RERANK_PROVIDER"] = "none"
    # The APK bundles RapidFuzz's complete Python source distribution. Force
    # the pure-Python implementation so Android never attempts to load a
    # desktop native extension that is not in the APK.
    os.environ["RAPIDFUZZ_IMPLEMENTATION"] = "python"
    # ``compat`` holds last-resort stand-ins (a four-function ``rapidfuzz``
    # among them). It must be *appended*: prepending it shadowed the real
    # bundled RapidFuzz and broke ``rapidfuzz.process``/``rapidfuzz.distance``
    # for every caller.
    compatibility_dir = Path(__file__).resolve().parent / "compat"
    if str(compatibility_dir) not in sys.path:
        sys.path.append(str(compatibility_dir))
    import mornye_runtime
    mornye_runtime.configure()
    _initialize_config(data_dir, cache_dir, music_dir)

    import app

    # Python modules survive an Activity close/reopen inside the same Android
    # process. Refresh the per-launch token explicitly instead of leaving the
    # cached module bound to a dead session.
    app.API_TOKEN = token
    import device_sync
    device_sync.start_android_pairing(data_dir)
    _server = app.create_server("127.0.0.1", 0)
    _thread = threading.Thread(
        target=_server.serve_forever,
        daemon=True,
        name="mindinguflac-android-http",
    )
    _thread.start()
    port = int(_server.server_address[1])
    try:
        _preflight(port, token, cache_dir, music_dir)
    except Exception:
        _server.shutdown()
        _server.server_close()
        _server = None
        _thread = None
        raise
    return port


def stop() -> None:
    global _server, _thread
    try:
        import device_sync
        device_sync.stop_android_pairing()
    except Exception:
        pass
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        finally:
            _server = None
    _thread = None
    import mornye_runtime
    mornye_runtime.stop()
