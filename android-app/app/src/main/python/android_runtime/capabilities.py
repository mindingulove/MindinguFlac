"""What the phone build can actually run.

The Android APK ships a deliberately smaller runtime than the desktop app:
no desktop ``libtorrent`` wheel, no Playwright/Chromium, no Node.js, and no
cloud advisor. Every download engine therefore has to be *proved* available
before the UI offers it, so a user can never pick an engine whose runtime is
not in the APK and get a silent failure instead of a download.

This module answers two questions:

``dependency_manifest()``
    Which third-party runtimes are packaged (bundled wheel or vendored
    source), and does each one import on this device?

``engine_availability()``
    Which download engines are usable, and for the unusable ones, why?

``runtime_report()`` bundles both, and ``app.py`` serves it on
``/api/runtime`` so the frontend builds its engine picker from measured
capability instead of a hard-coded list.
"""

from __future__ import annotations

import importlib
import os
import shutil
import threading
from pathlib import Path


#: Third-party runtimes the Android backend depends on, as
#: ``import name -> (distribution or vendored source, what needs it)``.
#: ``None`` as the distribution means the APK carries the Python source
#: directly rather than installing a wheel.
PACKAGED_RUNTIMES: dict[str, tuple[str | None, str]] = {
    "mornye": (None, "Spotify metadata, search, artist/album/playlist, lyrics"),
    "rapidfuzz": (None, "deterministic fuzzy artist/title/album matching"),
    "pydantic": ("pydantic", "Mornye REST request and response validation"),
    "pydantic_core": ("pydantic_core", "native Mornye REST validation"),
    "fastapi": ("fastapi", "embedded Mornye REST API"),
    "uvicorn": ("uvicorn", "embedded Mornye HTTP server"),
    "yt_dlp": ("yt-dlp", "YouTube audio engine"),
    "mutagen": ("mutagen", "audio tag read/write and format validation"),
    "requests": ("requests", "torrent source search and HTTP metadata"),
    "socks": ("PySocks", "SOCKS proxy support for yt-dlp"),
    "httpx": ("httpx", "Mornye async HTTP transport"),
    "aiofiles": ("aiofiles", "Mornye async file IO"),
    "tenacity": ("tenacity", "Mornye retry policy"),
    "tqdm": ("tqdm", "Mornye progress reporting"),
    "packaging": ("packaging", "Mornye version handling"),
    "dotenv": ("python-dotenv", "Mornye configuration loading"),
    "typing_extensions": ("typing-extensions", "Mornye typing backports"),
    "cryptography": ("cryptography", "Mornye signed-session provider calls"),
    "_cffi_backend": ("cffi", "native cryptography bindings"),
    "Crypto": ("pycryptodome", "Mornye provider payload decryption"),
    "PIL": ("Pillow", "artwork decoding and embedded cover art"),
    "PIL._imaging": ("Pillow", "native artwork decoder"),
}

#: Engines the desktop app offers that the phone deliberately does not ship.
_DESKTOP_ONLY_ENGINES = {
    "qobuz-dlp": "backend_qobuz_dlp is not packaged in the Android build.",
}

_lock = threading.Lock()
_cache: dict | None = None


def _is_android() -> bool:
    return os.environ.get("MINDINGUFLAC_ANDROID") == "1"


def _probe_import(name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, str(getattr(module, "__file__", "") or "built-in")


def _module_version(name: str) -> str:
    try:
        import importlib.metadata as metadata

        return metadata.version(name)
    except Exception:
        pass
    try:
        return str(getattr(importlib.import_module(name), "__version__", "") or "")
    except Exception:
        return ""


def dependency_manifest() -> dict:
    """Import every packaged runtime and report what resolved where."""
    from mornye_runtime import configure
    configure()
    entries: dict[str, dict] = {}
    for import_name, (distribution, used_for) in sorted(PACKAGED_RUNTIMES.items()):
        imported, detail = _probe_import(import_name)
        entry = {
            "imported": imported,
            "packaged_as": distribution or "vendored source in APK",
            "used_for": used_for,
            "detail": detail,
        }
        if imported:
            entry["version"] = _module_version(distribution or import_name)
            if import_name == "cryptography":
                try:
                    from cryptography.hazmat.backends.openssl.backend import backend

                    entry["openssl_version"] = backend.openssl_version_text()
                except Exception as exc:
                    entry["imported"] = False
                    entry["detail"] = f"OpenSSL backend failed: {type(exc).__name__}: {exc}"
        entries[import_name] = entry
    missing = sorted(name for name, entry in entries.items() if not entry["imported"])
    return {"runtimes": entries, "missing": missing, "ok": not missing}


def _native_torrent_status() -> dict:
    """Prove the jlibtorrent JNI library is loadable, without opening a session."""
    if not _is_android():
        return {"ok": False, "error": "Not running on Android"}
    try:
        from java import jclass  # type: ignore

        engine = jclass("com.mindinguflac.android.AndroidTorrentEngine")
    except Exception as exc:
        return {"ok": False, "error": f"Java bridge unavailable: {exc}"}
    try:
        import json

        return json.loads(str(engine.nativeStatus()))
    except Exception as exc:
        return {"ok": False, "error": f"jlibtorrent native library failed to load: {exc}"}


def _spotiflac_provider_status() -> dict:
    """Is there a Mornye *download* provider this device can actually run?

    Mornye supplies download providers through extensions.
    JavaScript extensions need ``node`` on PATH; Python ``.sflx`` extensions
    are imported in-process and so only need to be installed. The phone ships
    neither, which is why the Mornye engine stays off until one is present.
    """
    imported, detail = _probe_import("mornye")
    if not imported:
        return {"ok": False, "error": f"Mornye is not importable ({detail})"}

    from mornye_runtime import configure
    configure()
    node = shutil.which("node")
    installed: list[str] = []
    error = ""
    try:
        from mornye.extensions import ExtensionManager  # type: ignore

        manager = ExtensionManager(auto_install_downloads=False)
        for extension in manager.list_installed():
            try:
                if not extension.is_download_provider:
                    continue
                if extension.runtime == "python" or node:
                    installed.append(extension.name)
            except Exception:
                continue
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    if installed:
        return {"ok": True, "providers": sorted(installed), "node": bool(node)}
    reason = (
        "Mornye 1.0.4 imports, but its download path needs a provider "
        "extension: JavaScript extensions require Node.js (not in the APK) and "
        "no Python provider extension is installed."
    )
    if error:
        reason = f"{reason} Extension manager probe: {error}"
    return {"ok": False, "error": reason, "node": bool(node)}


def engine_availability() -> dict:
    """Report every engine the UI could offer, available or not, with a reason."""
    engines: dict[str, dict] = {}

    yt_ok, yt_detail = _probe_import("yt_dlp")
    tags_ok, tags_detail = _probe_import("mutagen")
    engines["ytp-dl"] = {
        "label": "YouTube Music",
        "available": yt_ok and tags_ok,
        "reason": "" if (yt_ok and tags_ok) else f"yt-dlp: {yt_detail}; mutagen: {tags_detail}",
        "services": ["youtube"],
        "qualities": ["best", "m4a"],
        "lossless": False,
    }

    sources_ok, sources_detail = _probe_import("torrent_sources")
    fuzzy_ok, fuzzy_detail = _probe_import("rapidfuzz")
    native = _native_torrent_status()
    torrent_ok = sources_ok and fuzzy_ok and bool(native.get("ok"))
    torrent_reason = ""
    if not torrent_ok:
        parts = []
        if not sources_ok:
            parts.append(f"torrent_sources: {sources_detail}")
        if not fuzzy_ok:
            parts.append(f"rapidfuzz: {fuzzy_detail}")
        if not native.get("ok"):
            parts.append(str(native.get("error") or "jlibtorrent unavailable"))
        torrent_reason = "; ".join(parts)
    engines["torrent"] = {
        "label": "Torrent (Experimental)",
        "available": torrent_ok,
        "reason": torrent_reason,
        "services": ["all", "torlock", "torrentdownloads", "limetorrents", "1337x", "kickass"],
        "qualities": ["LOSSLESS", "MP3"],
        "lossless": True,
        "native": native,
    }

    provider = _spotiflac_provider_status()
    engines["spotiflac"] = {
        "label": "Mornye",
        "available": bool(provider.get("ok")),
        "reason": "" if provider.get("ok") else str(provider.get("error") or ""),
        "services": ["tidal", "qobuz", "deezer", "amazon"],
        "qualities": ["LOSSLESS"],
        "lossless": True,
        "provider": provider,
    }

    mono_requests, mono_requests_detail = _probe_import("requests")
    mono_mutagen, mono_mutagen_detail = _probe_import("mutagen")
    mono_ok = mono_requests and mono_mutagen
    engines["monochrome"] = {
        "label": "Monochrome (FLAC)",
        "available": mono_ok,
        "reason": "" if mono_ok else f"requests: {mono_requests_detail}; mutagen: {mono_mutagen_detail}",
        "services": ["monochrome"],
        "qualities": ["LOSSLESS"],
        "lossless": True,
    }

    for name, reason in _DESKTOP_ONLY_ENGINES.items():
        engines[name] = {
            "label": name,
            "available": False,
            "reason": reason,
            "services": [],
            "qualities": [],
            "lossless": False,
        }

    return engines


def available_engines() -> list[str]:
    report = runtime_report()
    return [name for name, entry in report["engines"].items() if entry.get("available")]


def default_engine() -> str:
    """The engine a fresh phone install should start on."""
    engines = available_engines()
    for preferred in ("ytp-dl", "monochrome", "torrent", "spotiflac"):
        if preferred in engines:
            return preferred
    return "ytp-dl"


def clamp_choice(engine: str, service: str, quality: str) -> tuple[str, str, str]:
    """Clamp a requested engine/service/quality to something this phone can run.

    The persisted config is already guarded, but a download payload carries its
    own engine/service/quality, so a stale phone client or a replayed request
    could still name a desktop-only engine. That would fall through
    ``service_downloader``'s engine dispatch to the Mornye default and fail
    with an import error instead of downloading, so clamp it against the
    measured capability report instead.
    """
    engines = runtime_report()["engines"]
    chosen = (engine or "").lower()
    if not (engines.get(chosen) or {}).get("available"):
        chosen = default_engine()
    entry = engines.get(chosen) or {}
    services = entry.get("services") or ["youtube"]
    qualities = entry.get("qualities") or ["m4a"]
    chosen_service = (service or "").lower()
    if chosen_service not in services:
        chosen_service = services[0]
    chosen_quality = quality or ""
    if chosen_quality not in qualities:
        chosen_quality = qualities[0]
    return chosen, chosen_service, chosen_quality


def runtime_report(refresh: bool = False) -> dict:
    """Cached capability report. Probing starts no torrent session."""
    global _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
    dependencies = dependency_manifest()
    engines = engine_availability()
    report = {
        "android": _is_android(),
        "dependencies": dependencies,
        "engines": engines,
        "available_engines": [name for name, entry in engines.items() if entry.get("available")],
        "storage_root": str(Path(os.environ.get("MINDINGUFLAC_MUSIC_DIR", "")).parent or ""),
    }
    with _lock:
        _cache = report
    return report
