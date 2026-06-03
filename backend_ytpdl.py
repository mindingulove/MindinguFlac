from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _ffmpeg_location() -> str:
    """Return a path yt-dlp can use to find ffmpeg.

    yt-dlp's postprocessors (FFmpegMetadata, FFmpegExtractAudio) require an
    ffmpeg binary. Rather than expecting the user to install one, ship it via
    the ``imageio-ffmpeg`` pip package, which bundles a static ffmpeg binary
    per platform. Fall back to a frozen-bundle binary (``sys._MEIPASS``) or a
    PATH ffmpeg if the package is unavailable."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), name)
        if os.path.exists(bundled):
            return bundled
    return shutil.which(name) or shutil.which("ffmpeg") or ""


def _get_yt_dlp():
    import importlib

    try:
        return importlib.import_module("yt_dlp")
    except ModuleNotFoundError as exc:
        raise RuntimeError("yt-dlp is not installed in this environment") from exc


def _quality_mode(quality: str) -> str:
    value = str(quality or "").strip().lower()
    if value in {"mp3", "m4a"}:
        return value
    return "best"


def _quality_to_codec(quality: str) -> str:
    mode = _quality_mode(quality)
    if mode == "mp3":
        return "mp3"
    if mode == "m4a":
        return "m4a"
    return ""


def _format_selector(quality: str) -> str:
    mode = _quality_mode(quality)
    if mode == "m4a":
        return "bestaudio[ext=m4a][has_drm!=true]/bestaudio[acodec^=mp4a][has_drm!=true]/bestaudio[has_drm!=true]/best[has_drm!=true]"
    if mode == "mp3":
        return "bestaudio[has_drm!=true]/best[has_drm!=true]"
    return "bestaudio[has_drm!=true]/best[has_drm!=true]"


def _is_youtube_url(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        host = (urlparse(value).netloc or "").lower()
    except Exception:
        return False
    return "youtube.com" in host or "youtu.be" in host or "music.youtube.com" in host


def _safe_outtmpl(output_dir: Path) -> str:
    return str(output_dir / "%(title).200B - %(uploader).100B.%(ext)s")


def _job_metadata(job: dict) -> dict:
    track = job.get("track") if isinstance(job.get("track"), dict) else {}
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    return {**metadata, **track}


def _parse_duration_seconds(value: object) -> int:
    if value in ("", None):
        return 0
    if isinstance(value, (int, float)):
        number = int(value)
        return number // 1000 if number > 10000 else number
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        number = int(text)
        return number // 1000 if number > 10000 else number
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _expected_track(job: dict) -> dict:
    merged = _job_metadata(job)
    return {
        "artist": str(merged.get("artist") or job.get("artist") or "").strip(),
        "title": str(merged.get("title") or merged.get("name") or job.get("title") or "").strip(),
        "album": str(merged.get("album") or job.get("album") or "").strip(),
        "duration": (
            _parse_duration_seconds(merged.get("duration_ms"))
            or _parse_duration_seconds(merged.get("length"))
            or _parse_duration_seconds(merged.get("duration"))
        ),
    }


def _resolved_youtube_url(job: dict) -> str:
    merged = _job_metadata(job)

    direct = (
        job.get("resolved_url")
        or merged.get("youtube_url")
        or merged.get("youtube")
        or merged.get("external_url")
        or ""
    )
    if _is_youtube_url(direct):
        return direct

    # Fall back to any direct YouTube-ish URL present in metadata.
    for value in (merged.get("url"), merged.get("source_url")):
        if _is_youtube_url(value):
            return value

    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = wanted["title"]
    album = wanted["album"]
    if artist and title:
        query_parts = [artist, title]
        if album and album.lower() not in {"unknown album", "unknown"}:
            query_parts.append(album)
        query_parts.extend(["official", "audio"])
        return "ytsearch15:" + " ".join(query_parts)

    return ""


def _norm_text(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_BAD_MATCH_TERMS = {
    "background music",
    "compilation",
    "cover",
    "full album",
    "gaming",
    "mix",
    "no copyright",
    "playlist",
    "royalty free",
    "sound effect",
    "sound effects",
    "sound fx",
    "drm",
    "karaoke",
    "instrumental",
    "protected",
    "tutorial",
    "reaction",
    "remix",
    "sped up",
    "slowed",
    "nightcore",
    "loop",
    "1 hour",
    "10 hours",
    "extended",
}


def _tokens(value: str) -> list[str]:
    ignored = {"a", "an", "and", "feat", "ft", "official", "audio", "video", "lyrics", "the"}
    return [token for token in _norm_text(value).split() if token and token not in ignored]


def _token_coverage(needles: list[str], haystack: str) -> int:
    if not needles:
        return 0
    hay_tokens = set(_tokens(haystack))
    if not hay_tokens:
        return 0
    matched = sum(1 for token in needles if token in hay_tokens)
    return int((matched / len(needles)) * 100)


def _candidate_url(entry: dict) -> str:
    return str(entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "")


def _candidate_has_drm(entry: dict) -> bool:
    drm_fields = (
        entry.get("has_drm"),
        entry.get("is_drm"),
        entry.get("drm"),
        entry.get("drm_family"),
        entry.get("license_url"),
    )
    if any(value not in ("", None, False) for value in drm_fields):
        return True

    formats = entry.get("formats")
    if not isinstance(formats, list) or not formats:
        return False
    playable = 0
    drm = 0
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("has_drm") is True or fmt.get("drm_family") or fmt.get("license_url"):
            drm += 1
        else:
            playable += 1
    return drm > 0 and playable == 0


def _source_score(wanted_artist: str, uploader: str, candidate_title: str) -> int:
    from rapidfuzz import fuzz

    artist_tokens = _tokens(wanted_artist)
    uploader_norm = _norm_text(uploader)
    title_norm = _norm_text(candidate_title)
    if not artist_tokens:
        return 0

    # Official releases are frequently hosted on label/aggregator channels whose
    # name does not contain the artist (so uploader_coverage is 0). Treat the
    # title itself as a trust signal when it is clearly an official release that
    # names the artist, e.g. "CeCe Peniston - Finally (Official Music Video)".
    title_artist_coverage = _token_coverage(artist_tokens, title_norm)
    official_release = "official" in title_norm and any(
        marker in title_norm for marker in (" video", " audio")
    )
    official_titled_by_artist = official_release and title_artist_coverage >= 70

    uploader_coverage = _token_coverage(artist_tokens, uploader_norm)
    source = max(
        uploader_coverage,
        fuzz.token_set_ratio(_norm_text(wanted_artist), uploader_norm),
    )
    if uploader_coverage == 0:
        # Stay skeptical of unrelated channels, but don't reject an official
        # video just because the label channel name omits the artist.
        source = max(source, 70) if official_titled_by_artist else min(source, 30)

    if uploader_coverage == 100:
        source = max(source, 95)
    if uploader_norm.endswith(" topic") and uploader_coverage >= 80:
        source = 100
    if "vevo" in uploader_norm and uploader_coverage >= 70:
        source = 100
    if "official" in uploader_norm and uploader_coverage >= 70:
        source = max(source, 95)
    if "official" in title_norm and uploader_coverage >= 70:
        source = max(source, 90)
    return int(min(100, source))


def _score_youtube_candidate(entry: dict, job: dict) -> tuple[int, dict]:
    from rapidfuzz import fuzz

    wanted = _expected_track(job)
    wanted_artist = _norm_text(wanted["artist"])
    wanted_title = _norm_text(wanted["title"])
    wanted_full = _norm_text(f"{wanted['artist']} {wanted['title']}")
    raw_title = str(entry.get("title") or "")
    raw_uploader = str(entry.get("uploader") or entry.get("channel") or entry.get("creator") or "")
    candidate_title = _norm_text(raw_title)
    uploader = _norm_text(raw_uploader)
    combined = _norm_text(f"{candidate_title} {uploader}")

    if not wanted_artist or not wanted_title or not candidate_title:
        return 0, {"reason": "missing title metadata"}
    if _candidate_has_drm(entry):
        return -999, {
            "title": raw_title,
            "uploader": raw_uploader,
            "url": _candidate_url(entry),
            "title_score": 0,
            "artist_score": 0,
            "source_score": 0,
            "title_coverage": 0,
            "artist_coverage": 0,
            "duration_score": 0,
            "score": -999,
            "drm": True,
        }

    wanted_title_tokens = _tokens(wanted_title)
    wanted_artist_tokens = _tokens(wanted_artist)
    title_coverage = _token_coverage(wanted_title_tokens, candidate_title)
    artist_coverage = _token_coverage(wanted_artist_tokens, combined)
    source_score = _source_score(wanted_artist, uploader, candidate_title)

    title_score = max(
        fuzz.WRatio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_full, candidate_title),
    )
    artist_score = max(artist_coverage, fuzz.token_set_ratio(wanted_artist, combined))

    expected_duration = int(wanted.get("duration") or 0)
    candidate_duration = _parse_duration_seconds(entry.get("duration"))
    duration_score = 50
    duration_penalty = 0
    if expected_duration and candidate_duration:
        diff = abs(expected_duration - candidate_duration)
        if diff <= 5:
            duration_score = 100
        elif diff <= 15:
            duration_score = 80
        elif diff <= 30:
            duration_score = 45
        else:
            duration_score = 0
            duration_penalty = min(80, diff)

    penalty = 0
    candidate_text = f" {combined} "
    requested_tokens = f" {wanted_title} "
    for term in _BAD_MATCH_TERMS:
        if f" {term} " in candidate_text and f" {term} " not in requested_tokens:
            penalty += 35

    if title_coverage < 70:
        penalty += 35
    if artist_coverage < 70:
        penalty += 40
    if source_score < 45 and any(term in candidate_text for term in (" background music ", " compilation ", " gaming ", " sound fx ")):
        penalty += 60

    score = int(
        (title_score * 0.42)
        + (artist_score * 0.18)
        + (source_score * 0.22)
        + (duration_score * 0.12)
        + (title_coverage * 0.06)
        - penalty
        - duration_penalty
    )
    details = {
        "title": raw_title,
        "uploader": raw_uploader,
        "url": _candidate_url(entry),
        "title_score": int(title_score),
        "artist_score": int(artist_score),
        "source_score": int(source_score),
        "title_coverage": int(title_coverage),
        "artist_coverage": int(artist_coverage),
        "duration_score": int(duration_score),
        "score": score,
        "drm": False,
    }
    return score, details


def _scored_youtube_candidates(search_info: dict, job: dict) -> list[tuple[int, dict, str]]:
    entries = [entry for entry in (search_info.get("entries") or []) if isinstance(entry, dict)]
    scored = []
    for entry in entries:
        url = _candidate_url(entry)
        if not url:
            continue
        score, details = _score_youtube_candidate(entry, job)
        scored.append((score, details, url))

    if not scored:
        raise RuntimeError("ytp-dl search returned no downloadable YouTube candidates")

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _candidate_is_confident(score: int, details: dict) -> bool:
    return not (
        score < 65
        or details.get("title_score", 0) < 60
        or details.get("artist_score", 0) < 65
        or details.get("source_score", 0) < 35
    )


def _best_youtube_search_match(search_info: dict, job: dict) -> tuple[str, dict]:
    scored = _scored_youtube_candidates(search_info, job)
    best_score, best_details, best_url = scored[0]
    if not _candidate_is_confident(best_score, best_details):
        title = best_details.get("title") or "unknown result"
        raise RuntimeError(f"ytp-dl could not find a confident YouTube match; best was {best_score}%: {title}")
    return best_url, best_details


def _ranked_youtube_matches(search_info: dict, job: dict) -> list[tuple[str, dict]]:
    """Return every confident candidate, best first, so the caller can fall
    back to the next match if a chosen video turns out to be unavailable
    (removed, private, or geo-blocked)."""
    scored = _scored_youtube_candidates(search_info, job)
    confident = [(url, details) for score, details, url in scored if _candidate_is_confident(score, details)]
    if not confident:
        best_score, best_details, _ = scored[0]
        title = best_details.get("title") or "unknown result"
        raise RuntimeError(f"ytp-dl could not find a confident YouTube match; best was {best_score}%: {title}")
    return confident


def run(output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files

    if job["id"] in manager._cancel_flags:
        return

    url = _resolved_youtube_url(job)
    if not url:
        raise RuntimeError("ytp-dl could not build a YouTube URL or search query from the selected track metadata")

    quality = job.get("quality") or "best"
    codec = _quality_to_codec(quality)
    format_selector = _format_selector(quality)
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

    postprocessors = [{"key": "FFmpegMetadata"}]
    if codec:
        postprocessors.insert(0, {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"})

    ydl_opts = {
        "format": format_selector,
        "outtmpl": _safe_outtmpl(output_dir),
        "paths": {"home": str(output_dir)},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "allow_unplayable_formats": False,
        "progress_hooks": [progress_cb],
        "writethumbnail": True,
        "addmetadata": True,
        "postprocessors": postprocessors,
    }

    ffmpeg_path = _ffmpeg_location()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    with manager._lock:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["resolved_url"] = url
        job["last_status"] = "Searching YouTube..." if url.startswith("ytsearch") else "Downloading from YouTube..."
        job["active_provider"] = "ytp-dl"
    label = codec.upper() if codec else "best native audio"
    manager._append_cache_event(job, "trying", f"Downloading via ytp-dl ({label})...")

    try:
        yt_dlp = _get_yt_dlp()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if url.startswith("ytsearch"):
                search_info = ydl.extract_info(url, download=False)
                if not isinstance(search_info, dict):
                    raise RuntimeError("ytp-dl search did not return candidate metadata")
                candidates = _ranked_youtube_matches(search_info, job)
            else:
                candidates = [(url, None)]

            # Try matches in score order; an unavailable video (removed,
            # private, geo-blocked) should fall back to the next candidate
            # rather than failing the whole download.
            attempts = candidates[:5]
            last_error: Exception | None = None
            downloaded = False
            for index, (download_url, selected) in enumerate(attempts):
                if job["id"] in manager._cancel_flags:
                    return
                if selected:
                    with manager._lock:
                        job["resolved_url"] = download_url
                        job["ytpdl_match"] = selected
                        job["last_status"] = f"Downloading YouTube match: {selected.get('title', '')[:80]}"
                    verb = "Trying next YouTube match" if index else "Selected YouTube match"
                    manager._append_cache_event(
                        job,
                        "trying",
                        f"{verb} ({selected.get('score', 0)}%): {selected.get('title', '')[:80]}",
                    )
                try:
                    ydl.download([download_url])
                    last_error = None
                    downloaded = True
                    break
                except Exception as exc:
                    last_error = exc
                    if index + 1 < len(attempts):
                        manager._append_cache_event(
                            job, "trying", f"YouTube candidate unavailable, trying another: {exc}"
                        )

            if not downloaded and last_error is not None:
                raise last_error
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
