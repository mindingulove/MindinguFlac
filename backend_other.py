from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
import sys
from urllib.parse import urlparse

# Add project root to sys.path to ensure other_providers is importable
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# We import the providers and core models directly
# This uses the "reverse engineered" logic (the engines) without the SpotiFLAC wrapper
try:
    from other_providers.providers import PROVIDER_REGISTRY
    from other_providers.core.models import TrackMetadata
except ImportError as e:
    raise RuntimeError(f"Failed to import providers from other_providers: {e}")

_SERVICE_MAP = {
    "apple_music": "apple",
    "spotify": "spoti",
    "spotiflac": "spoti",
}

_QUALITY_MAP = {
    "qobuz": {
        "DOLBY_ATMOS": "27",
        "HI_RES": "27",
        "HI_RES_LOSSLESS": "27",
        "LOSSLESS": "6",
    },
    "apple": {
        "LOSSLESS": "alac",
        "HI_RES": "alac",
        "HI_RES_LOSSLESS": "alac",
        "DOLBY_ATMOS": "alac",
        "256": "aac",
        "192": "aac",
        "128": "aac",
    },
    "youtube": {
        "HIGH": "256",
        "LOW": "128",
        "LOSSLESS": "256",
    },
    "soundcloud": {
        "HIGH": "HIGH",
        "LOW": "LOW",
        "LOSSLESS": "HIGH",
    },
    "pandora": {
        "HIGH": "mp3_192",
        "LOW": "mp3_128",
        "LOSSLESS": "mp3_192",
    },
}


def _spotify_id_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower()
    if "spotify.com" not in host:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[-2] in {"track", "album"}:
        return parts[-1]
    return ""


def _first_metadata_value(job: dict, *keys: str) -> str:
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    for key in keys:
        value = job.get(key) or metadata.get(key)
        if value not in ("", None):
            return str(value)
    return ""


def _provider_quality(service_key: str, requested_quality: str) -> str:
    requested = str(requested_quality or "LOSSLESS").upper()
    return _QUALITY_MAP.get(service_key, {}).get(requested, requested_quality or "LOSSLESS")

_FALLBACK_SERVICES = ["qobuz", "deezer", "tidal", "apple", "amazon"]


def _provider_kwargs(service_key: str, manager) -> dict:
    if service_key in ("tidal", "qobuz"):
        return {"qobuz_token": manager.config.qobuz_token}
    return {}


def _service_candidates(selected_service: str) -> list[tuple[str, str]]:
    selected_key = _SERVICE_MAP.get(selected_service, selected_service)
    if selected_key not in PROVIDER_REGISTRY:
        raise RuntimeError(f"Unknown provider: {selected_service}")
    keys = [selected_key, *[key for key in _FALLBACK_SERVICES if key != selected_key]]
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen or key not in PROVIDER_REGISTRY:
            continue
        seen.add(key)
        raw = "apple_music" if key == "apple" else key
        result.append((raw, key))
    return result


def _metadata_for_job(url: str, job: dict) -> TrackMetadata:
    spotify_id = (
        _first_metadata_value(job, "spotify_id")
        or _spotify_id_from_url(url)
        or _first_metadata_value(job, "id")
    )
    if isinstance(spotify_id, str) and ":" in spotify_id:
        spotify_id = spotify_id.split(":")[-1]
    if not spotify_id or (len(spotify_id) == 36 and "-" in spotify_id):
        raise RuntimeError("Direct providers need a Spotify track ID or URL before download")

    return TrackMetadata(
        id=spotify_id,
        title=job.get("title", "Unknown"),
        artists=job.get("artist", "Unknown"),
        album=job.get("album", "Unknown"),
        album_artist=job.get("artist", "Unknown"),
        isrc=job.get("isrc", ""),
        duration_ms=int(job.get("duration", 0) * 1000) if job.get("duration") else 0,
        cover_url=_first_metadata_value(job, "cover_url", "artwork_url"),
        external_url=url,
    )


def _download_with_provider(raw_service: str, service_key: str, metadata: TrackMetadata, output_dir: Path, job: dict, manager):
    provider_cls = PROVIDER_REGISTRY[service_key]
    provider = provider_cls(**_provider_kwargs(service_key, manager))
    requested_quality = _provider_quality(service_key, str(job.get("quality") or "LOSSLESS"))

    def progress_cb(current, total):
        if total > 0:
            percent = int((current / total) * 100)
            with manager._lock:
                job["progress"] = percent
                job["last_status"] = f"Downloading via {raw_service}... {percent}%"

    provider.set_progress_callback(progress_cb)

    with manager._lock:
        job["last_status"] = f"Downloading via {raw_service}..."
        job["active_provider"] = raw_service
    manager._append_cache_event(job, "trying", f"Using {raw_service} engine at {requested_quality}...")

    return provider.download_track(
        metadata,
        str(output_dir),
        quality=requested_quality,
        allow_fallback=True,
        embed_lyrics=True,
        enrich_metadata=True,
        track_max_retries=int(getattr(manager.config, "track_max_retries", 3) or 3),
    )


def run(url: str, output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files

    if job["id"] in manager._cancel_flags:
        return

    selected_service = (job.get("service") or "tidal").lower()
    metadata = _metadata_for_job(url, job)
    errors: list[str] = []

    for raw_service, service_key in _service_candidates(selected_service):
        if job["id"] in manager._cancel_flags:
            return
        try:
            result = _download_with_provider(raw_service, service_key, metadata, output_dir, job, manager)
            if not result.success:
                raise RuntimeError(str(result.error or "provider reported failure"))
            if result.file_path:
                with manager._lock:
                    job["library_path"] = str(result.file_path)
                    job["provider_used"] = raw_service
                    job["progress"] = 100
            audio_files = _find_audio_files(output_dir)
            if not audio_files:
                raise RuntimeError(f"{raw_service} engine reported success but no playable audio file was found")
            manager._append_cache_event(job, "provider", f"{raw_service} produced {audio_files[0].name}")
            return
        except Exception as exc:
            message = f"{raw_service} engine failed: {exc}"
            errors.append(message)
            manager._append_cache_event(job, "provider", f"{message}; trying next provider")
            with manager._lock:
                job["last_status"] = f"{raw_service} failed, trying next provider..."

    raise RuntimeError("All direct providers failed: " + " | ".join(errors))
