from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_yt_dlp():
    import importlib

    try:
        return importlib.import_module("yt_dlp")
    except ModuleNotFoundError as exc:
        raise RuntimeError("yt-dlp is not installed in this environment") from exc


def _quality_to_codec(quality: str) -> str:
    value = str(quality or "").strip().lower()
    if value == "mp3":
        return "mp3"
    return "m4a"


def _safe_outtmpl(output_dir: Path) -> str:
    return str(output_dir / "%(title).200B - %(uploader).100B.%(ext)s")


def _resolved_youtube_url(job: dict) -> str:
    from service_downloader import resolve_download_url

    track = job.get("track") if isinstance(job.get("track"), dict) else {}
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    merged = {**metadata, **track}

    direct = (
        job.get("resolved_url")
        or merged.get("youtube_url")
        or merged.get("youtube")
        or merged.get("external_url")
        or ""
    )
    if isinstance(direct, str) and ("youtube.com" in direct or "youtu.be" in direct):
        return direct

    resolved = resolve_download_url(merged, service="youtube", kind=job.get("kind", "track"))
    if resolved:
        return resolved

    # Fall back to any direct YouTube-ish URL present in metadata.
    for value in (merged.get("url"), merged.get("source_url")):
        if isinstance(value, str) and ("youtube.com" in value or "youtu.be" in value):
            return value

    return ""


def run(output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files

    if job["id"] in manager._cancel_flags:
        return

    url = _resolved_youtube_url(job)
    if not url:
        raise RuntimeError("ytp-dl could not resolve a YouTube URL from the selected track metadata")

    codec = _quality_to_codec(job.get("quality") or "m4a")
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress_cb(payload: dict) -> None:
        status = str(payload.get("status") or "")
        if status == "downloading":
            downloaded = int(payload.get("downloaded_bytes") or 0)
            total = int(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
            if total > 0:
                percent = int((downloaded / total) * 100)
                with manager._lock:
                    job["progress"] = percent
                    job["last_status"] = f"Downloading from YouTube... {percent}%"
        elif status == "finished":
            with manager._lock:
                job["last_status"] = "Finalizing YouTube download..."

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": _safe_outtmpl(output_dir),
        "paths": {"home": str(output_dir)},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [progress_cb],
        "writethumbnail": True,
        "addmetadata": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"},
            {"key": "FFmpegMetadata"},
        ],
    }

    with manager._lock:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["resolved_url"] = url
        job["last_status"] = "Downloading from YouTube..."
        job["active_provider"] = "ytp-dl"
    manager._append_cache_event(job, "trying", f"Downloading via ytp-dl ({codec})...")

    try:
        yt_dlp = _get_yt_dlp()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        raise RuntimeError(f"ytp-dl failed: {exc}") from exc

    audio_files = _find_audio_files(output_dir)
    if not audio_files:
        raise RuntimeError("ytp-dl reported success but no playable audio file was found")

    final = audio_files[0]
    with manager._lock:
        job["library_path"] = str(final)
        job["provider_used"] = "ytp-dl"
        job["progress"] = 100
        job["last_status"] = "YouTube download complete"
    manager._append_cache_event(job, "provider", f"ytp-dl produced {final.name}")
