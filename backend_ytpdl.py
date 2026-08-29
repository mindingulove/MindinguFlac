from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,}$")
_YOUTUBE_CHANNEL_ID_CACHE: dict[str, str] = {}
_YOUTUBE_AUTH_COOKIE_NAMES = {
    "APISID", "HSID", "LOGIN_INFO", "SAPISID", "SID", "SSID",
    "__Secure-1PAPISID", "__Secure-1PSID", "__Secure-3PAPISID", "__Secure-3PSID",
}
_BROWSER_COOKIE_EXPORTS: dict[str, Path] = {}
_BROWSER_COOKIE_EXPORTS_LOCK = threading.Lock()


def _youtube_extractor_args() -> dict:
    return {"youtube": {"player_client": ["android", "ios", "web"]}}


def _youtube_metadata_opts(**overrides) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 8,
        "extractor_args": _youtube_extractor_args(),
        "http_headers": {"Accept-Encoding": "identity"},
    }
    opts.update(overrides)
    return opts


def _youtube_cookie_file() -> str:
    paths: list[Path] = []
    env_path = os.environ.get("MINDINGUFLAC_YOUTUBE_COOKIES") or os.environ.get("YTDLP_COOKIES")
    if env_path:
        paths.append(Path(env_path).expanduser())
    try:
        from config import app_data_dir

        paths.append(app_data_dir() / "cookies.txt")
    except Exception:
        pass
    paths.extend([
        Path.cwd() / "cookies.txt",
        Path(__file__).resolve().parent / "cookies.txt",
    ])
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        app_contents = exe_dir.parent if exe_dir.name == "MacOS" else exe_dir
        paths.extend([
            exe_dir / "cookies.txt",
            app_contents / "Resources" / "cookies.txt",
            Path(getattr(sys, "_MEIPASS", "")) / "cookies.txt",
        ])

    for path in paths:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
        except Exception:
            continue
    return ""


def _add_youtube_cookie_file(opts: dict) -> bool:
    cookie_file = _youtube_cookie_file()
    if not cookie_file:
        return False
    opts["cookiefile"] = cookie_file
    return True


def _has_youtube_auth_opts(opts: dict) -> bool:
    return bool(opts.get("cookiefile") or opts.get("cookiesfrombrowser"))


def _without_youtube_auth_opts(opts: dict) -> dict:
    no_auth_opts = dict(opts)
    no_auth_opts.pop("cookiefile", None)
    no_auth_opts.pop("cookiesfrombrowser", None)
    return no_auth_opts


def _has_youtube_auth_cookie(cookiejar) -> bool:
    """Avoid selecting a browser profile that has no signed-in YouTube session."""
    try:
        return any(
            str(getattr(cookie, "name", "")) in _YOUTUBE_AUTH_COOKIE_NAMES
            and str(getattr(cookie, "domain", "")).lstrip(".").endswith(("youtube.com", "google.com"))
            and not bool(getattr(cookie, "is_expired", lambda: False)())
            for cookie in cookiejar
        )
    except Exception:
        return False


def _add_browser_youtube_cookies(opts: dict, output_dir: Path, job_id: str) -> bool:
    """Discover signed-in YouTube cookies without selecting or naming a browser."""
    try:
        import browser_cookie3
        from http.cookiejar import MozillaCookieJar

        discovered = browser_cookie3.load(domain_name="youtube.com")
        if not _has_youtube_auth_cookie(discovered):
            return False
        cookie_dir = output_dir / ".cache"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        cookie_path = cookie_dir / "youtube-browser-cookies.txt"
        exported = MozillaCookieJar(str(cookie_path))
        for cookie in discovered:
            domain = str(getattr(cookie, "domain", "")).lstrip(".").lower()
            if domain.endswith("youtube.com") or domain.endswith("google.com"):
                exported.set_cookie(cookie)
        exported.save(ignore_discard=True, ignore_expires=True)
        try:
            cookie_path.chmod(0o600)
        except OSError:
            pass
        with _BROWSER_COOKIE_EXPORTS_LOCK:
            previous = _BROWSER_COOKIE_EXPORTS.pop(job_id, None)
            _BROWSER_COOKIE_EXPORTS[job_id] = cookie_path
        if previous and previous != cookie_path:
            previous.unlink(missing_ok=True)
        opts["cookiefile"] = str(cookie_path)
        return True
    except Exception as exc:
        logger.info("Browser cookie discovery unavailable: %s", exc)
        return False


def cleanup_browser_cookie_export(job_id: str) -> None:
    with _BROWSER_COOKIE_EXPORTS_LOCK:
        cookie_path = _BROWSER_COOKIE_EXPORTS.pop(str(job_id or ""), None)
    if cookie_path:
        try:
            cookie_path.unlink(missing_ok=True)
        except OSError:
            pass


def _mark_youtube_login_required(job: dict, manager) -> None:
    with manager._lock:
        job["youtube_login_required"] = True
        job["youtube_login_url"] = "https://www.youtube.com/"
        job["last_status"] = "YouTube login required"
        job["active_provider"] = "ytp-dl"
    manager._append_cache_event(
        job,
        "login_required",
        "No signed-in YouTube browser cookies were found; waiting for browser login",
    )


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
    if value in {"video", "mp4-video", "music_video"}:
        return "video"
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
    if mode == "video":
        # H.264 required — Safari <audio> cannot play AV1-in-mp4 containers
        return (
            "bestvideo[vcodec^=avc][height<=480][has_drm!=true]+bestaudio[ext=m4a][has_drm!=true]/"
            "bestvideo[vcodec^=avc][has_drm!=true]+bestaudio[has_drm!=true]/"
            "bestvideo[ext=mp4][vcodec!=none][acodec=none][has_drm!=true]+bestaudio[ext=m4a][has_drm!=true]/"
            "best[vcodec!=none][has_drm!=true]"
        )
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


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove text in parentheses or brackets like (Remastered 2010) or [Official Video]
    text = re.sub(r"\s*[\(\[].*?[\)\]]", "", text)
    # Strip common suffixes that follow a dash or space
    text = re.sub(
        r"\s*[-–]\s*(remaster|remastered|single|ep|deluxe|expanded|anniversary|edition|version|mono|stereo|re-?master).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _extract_catalog_ids(value: object) -> set[str]:
    text = str(value or "").casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ids: set[str] = set()
    # Keep this intentionally conservative. These catalogue numbers are strong
    # classical identifiers; looser forms like "op. 3" are too common for
    # YouTube matching and can make pop searches less strict.
    for prefix, number in re.findall(r"\b(rv|bwv|hwv|kv|k)\s*\.?\s*(\d{1,5}[a-z]?)\b", text, flags=re.IGNORECASE):
        ids.add(f"{prefix.casefold()}{number.casefold()}")
    for number in re.findall(r"\bhob\s*\.?\s*(?:[ivxlcdm]+:)?\s*(\d{1,4}[a-z]?)\b", text, flags=re.IGNORECASE):
        ids.add(f"hob{number.casefold()}")
    return ids


def _classical_search_terms(title: str) -> str:
    catalog_ids = _extract_catalog_ids(title)
    if not catalog_ids:
        return ""
    tokens = _tokens(title)
    ignored = {
        "vivaldi", "bach", "handel", "haendel", "mozart", "haydn",
        "beethoven", "schubert", "chopin", "liszt", "verdi", "puccini",
        "concerto", "symphony", "sonata", "opera", "aria", "major", "minor",
        "op", "no", "nr", "act", "scene", "i", "ii", "iii", "iv", "v",
        "vi", "vii", "viii", "ix", "x",
    }
    catalog_tokens = set()
    for catalog_id in catalog_ids:
        match = re.match(r"([a-z]+)(\d.*)", catalog_id)
        if match:
            catalog_tokens.update(match.groups())
    distinctive = [
        token for token in tokens
        if token not in ignored and token not in catalog_tokens and len(token) > 1
    ]
    return " ".join([*sorted(catalog_tokens), *distinctive[:6]]).strip()


_CLASSICAL_GENRE_TERMS = {
    "classical",
    "baroque",
    "opera",
    "oratorio",
    "chamber music",
    "concerto",
    "symphony",
}


def _metadata_values_for_keys(data: dict, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = data.get(key)
        if isinstance(raw, str):
            values.extend(part.strip() for part in re.split(r"[,/;|]", raw) if part.strip())
        elif isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, str):
                    values.extend(part.strip() for part in re.split(r"[,/;|]", item) if part.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("genre") or item.get("title")
                    if name:
                        values.append(str(name).strip())
    return [value for value in values if value]


def _ytpdl_search_profile(job: dict) -> str:
    merged = _job_metadata(job)
    genre_values = _metadata_values_for_keys(
        merged,
        ("genre", "genres", "primary_genre", "secondary_genres", "style", "styles"),
    )
    genre_text = _norm_text(" ".join(genre_values))
    if any(term in genre_text for term in _CLASSICAL_GENRE_TERMS):
        return "classical"
    return "default"


def _classical_youtube_search_query(job: dict, clean: bool = False) -> str:
    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = _clean_text(wanted["title"]) if clean else wanted["title"]
    terms = _classical_search_terms(title)
    if not terms:
        return ""
    parts = [artist, terms] if artist else [terms]
    if not clean and wanted["album"]:
        album_terms = _classical_search_terms(wanted["album"])
        if album_terms:
            parts.append(album_terms)
    return "ytsearch15:" + " ".join(part for part in parts if part)


def _youtube_search_query(job: dict, clean: bool = False) -> str:
    if _ytpdl_search_profile(job) == "classical":
        query = _classical_youtube_search_query(job, clean=clean)
        if query:
            return query

    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = wanted["title"]
    album = wanted["album"]
    video_mode = _quality_mode(job.get("quality") or "best") == "video"
    
    if clean:
        title = _clean_text(title)
        album = "" # Don't include album in clean search
    
    if artist and title:
        query_parts = [artist, title]
        if not video_mode and not clean and album and album.lower() not in {"unknown album", "unknown"}:
            query_parts.append(album)
        query_parts.extend(["official", "video" if video_mode else "audio"])
        return "ytsearch15:" + " ".join(query_parts)
    if title:
        return "ytsearch15:" + " ".join([title, "official", "video" if video_mode else "audio"])
    return ""


def _youtube_video_search_text(job: dict, clean: bool = False) -> str:
    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = _clean_text(wanted["title"]) if clean else wanted["title"]
    if artist and title:
        return " ".join([artist, title, "official video"])
    if title:
        return " ".join([title, "official video"])
    return ""


def _youtube_channel_search_query(channel_id: str, job: dict, clean: bool = False) -> str:
    query = _youtube_video_search_text(job, clean=clean)
    if not channel_id or not query:
        return ""
    return f"ytsearch12:{query} channel:{channel_id}"


def _broad_youtube_search_query(job: dict) -> str:
    profile = _ytpdl_search_profile(job)
    if profile == "classical":
        query = _classical_youtube_search_query(job, clean=True)
        if query:
            return query

    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = _clean_text(wanted["title"])
    if artist and title:
        return "ytsearch15:" + " ".join([artist, title])
    if title:
        return "ytsearch15:" + title
    return ""


def _is_youtube_search_target(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("ytsearch"):
        return True
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    return "youtube.com" in host and parsed.path.endswith("/search")


def _youtube_search_channel_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("ytsearch"):
        return ""
    match = re.search(r"\bchannel:(UC[A-Za-z0-9_-]{20,})\b", value)
    return match.group(1) if match else ""


def _youtube_search_without_channel_filter(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("ytsearch"):
        return value
    return re.sub(r"\s+\bchannel:UC[A-Za-z0-9_-]{20,}\b", "", value).strip()


def _filter_youtube_entries_by_channel(search_info: dict, channel_id: str) -> dict:
    if not channel_id or not isinstance(search_info, dict):
        return search_info
    entries = search_info.get("entries")
    if not isinstance(entries, list):
        return search_info
    filtered = [
        entry for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("channel_id") or entry.get("uploader_id") or "").strip() == channel_id
    ]
    return {**search_info, "entries": filtered}


def _youtube_channel_id_from_info(info: object) -> str:
    if not isinstance(info, dict):
        return ""
    for key in ("channel_id", "uploader_id", "id"):
        value = str(info.get(key) or "").strip()
        if _YOUTUBE_CHANNEL_ID_RE.match(value):
            return value
    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            channel_id = _youtube_channel_id_from_info(entry)
            if channel_id:
                return channel_id
    return ""


def _metadata_youtube_channel_ids(job: dict) -> list[tuple[str, str]]:
    merged = _job_metadata(job)
    ids: list[tuple[str, str]] = []
    for key in ("youtube_channel_id", "channel_id", "artist_youtube_channel_id"):
        value = str(merged.get(key) or "").strip()
        if _YOUTUBE_CHANNEL_ID_RE.match(value):
            ids.append((value, key))
    for key in ("youtube_channel_url", "artist_youtube_url", "channel_url"):
        value = str(merged.get(key) or "").strip()
        match = re.search(r"/channel/(UC[A-Za-z0-9_-]{20,})", value)
        if match:
            ids.append((match.group(1), key))
    return ids


def _youtube_handle_slug(value: str) -> str:
    return "".join(_tokens(value))


def _youtube_channel_probe_urls(job: dict, group: str) -> list[tuple[str, str]]:
    artist = _expected_track(job).get("artist") or ""
    slug = _youtube_handle_slug(artist)
    if not slug:
        return []
    if group == "artist":
        handles = [slug, f"{slug}official", f"{slug}music"]
    elif group == "vevo":
        handles = [f"{slug}vevo", "vevo"]
    else:
        handles = ["rhino", "warnerrecords", "sonymusic", "universalmusicgroup"]
    return [(f"https://www.youtube.com/@{handle}/videos", f"@{handle}") for handle in handles]


def _resolve_youtube_channel_id(ydl, url: str) -> str:
    cached = _YOUTUBE_CHANNEL_ID_CACHE.get(url)
    if cached is not None:
        return cached
    channel_id = ""
    try:
        info = ydl.extract_info(url, download=False, process=False)
        channel_id = _youtube_channel_id_from_info(info)
    except Exception:
        channel_id = ""
    if not channel_id:
        try:
            yt_dlp = _get_yt_dlp()
            opts = _youtube_metadata_opts(extract_flat=True, playlistend=1)
            with yt_dlp.YoutubeDL(opts) as flat_ydl:
                info = flat_ydl.extract_info(url, download=False)
            channel_id = _youtube_channel_id_from_info(info)
        except Exception:
            channel_id = ""
    _YOUTUBE_CHANNEL_ID_CACHE[url] = channel_id
    return channel_id


def _youtube_channel_search_attempts(ydl, job: dict):
    if _quality_mode(job.get("quality") or "best") != "video":
        return

    seen_ids: set[str] = set()

    for channel_id, source in _metadata_youtube_channel_ids(job):
        if channel_id in seen_ids:
            continue
        seen_ids.add(channel_id)
        search_query = _youtube_channel_search_query(channel_id, job)
        if search_query:
            yield search_query, f"saved YouTube channel ({source})"

    for group, label in (
        ("artist", "artist channel"),
        ("vevo", "VEVO channel"),
        ("clips", "music-video channel"),
    ):
        for url, handle in _youtube_channel_probe_urls(job, group):
            channel_id = _resolve_youtube_channel_id(ydl, url)
            if not channel_id or channel_id in seen_ids:
                continue
            seen_ids.add(channel_id)
            search_query = _youtube_channel_search_query(channel_id, job)
            if search_query:
                yield search_query, f"{label} {handle}"


def _youtube_search_profile_label(job: dict, query: str) -> str:
    profile = _ytpdl_search_profile(job)
    kind = "classical" if profile == "classical" and query.startswith("ytsearch") else profile
    return f"{kind} search"


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
    if _quality_mode(job.get("quality") or merged.get("quality") or "best") == "video":
        try:
            import db
            override = db.get_youtube_video_override({**merged, **job})
            if override and override.get("webpage_url"):
                return str(override.get("webpage_url") or "")
        except Exception:
            pass

    # Fall back to any direct YouTube-ish URL present in metadata.
    for value in (merged.get("url"), merged.get("source_url")):
        if _is_youtube_url(value):
            return value

    return _youtube_search_query(job)


def _spotify_track_url(job: dict) -> str:
    merged = _job_metadata(job)
    for key in ("spotify_url", "external_url", "url", "source_url", "resolved_url"):
        value = str(merged.get(key) or job.get(key) or "").strip()
        if "open.spotify.com/track/" in value:
            return value
    spotify_id = str(
        merged.get("spotify_id")
        or merged.get("spotify_track_id")
        or merged.get("track_id")
        or job.get("spotify_id")
        or ""
    ).strip()
    if spotify_id and re.fullmatch(r"[A-Za-z0-9]{12,}", spotify_id):
        return f"https://open.spotify.com/track/{spotify_id}"
    track_key = str(job.get("track_key") or merged.get("track_key") or "").strip()
    if track_key.startswith("spotify_id:"):
        value = track_key.split(":", 1)[1].strip()
        if value:
            return f"https://open.spotify.com/track/{value}"
    return ""


def _video_db_override(job: dict) -> dict | None:
    if _quality_mode(job.get("quality") or "best") != "video":
        return None
    try:
        import db
        return db.get_youtube_video_override({**_job_metadata(job), **job})
    except Exception:
        return None


def _votify_command() -> list[str]:
    exe = shutil.which("votify")
    if exe:
        return [exe]
    try:
        import importlib.util
        if importlib.util.find_spec("votify"):
            return [sys.executable, "-m", "votify"]
    except Exception:
        pass
    return []


def _try_votify_video(output_dir: Path, job: dict, manager) -> Path | None:
    if _quality_mode(job.get("quality") or "best") != "video":
        return None
    spotify_url = _spotify_track_url(job)
    if not spotify_url:
        manager._append_cache_event(job, "trying", "Votify skipped: missing Spotify track ID/URL for music video lookup")
        return None
    cmd = _votify_command()
    if not cmd:
        manager._append_cache_event(job, "trying", "Votify skipped: command/module is not installed; falling back to YouTube")
        return None

    before = {path.resolve() for path in output_dir.rglob("*") if path.is_file()} if output_dir.exists() else set()
    temp_dir = output_dir / ".votify-temp"
    args = [
        *cmd,
        spotify_url,
        "--prefer-video",
        "--output", str(output_dir),
        "--temp", str(temp_dir),
        "--video-format", "mp4",
        "--video-remux-mode", "ffmpeg",
        "--overwrite",
    ]
    ffmpeg_path = _ffmpeg_location()
    if ffmpeg_path:
        args.extend(["--ffmpeg-path", ffmpeg_path])

    with manager._lock:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["resolved_url"] = spotify_url
        job["active_provider"] = "votify"
        job["last_status"] = "Downloading Spotify music video via Votify..."
    manager._append_cache_event(job, "trying", "Trying Votify Spotify music video before YouTube fallback...")

    try:
        result = subprocess.run(args, cwd=str(output_dir), capture_output=True, text=True, timeout=900)
    except Exception as exc:
        manager._append_cache_event(job, "trying", f"Votify failed to start: {str(exc)[:100]}; falling back to YouTube")
        return None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        manager._append_cache_event(job, "trying", f"Votify did not produce a video ({message[:100]}); falling back to YouTube")
        return None

    from service_downloader import _find_audio_files
    produced = [path for path in _find_audio_files(output_dir) if path.resolve() not in before]
    if not produced:
        produced = _find_audio_files(output_dir)
    video_files = [path for path in produced if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}]
    if not video_files:
        manager._append_cache_event(job, "trying", "Votify completed but no playable video file was found; falling back to YouTube")
        return None
    video_files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    final = video_files[0]
    try:
        import db
        track_key = job.get("track_key") or f"{job.get('artist','').lower()}||{job.get('title','').lower()}"
        db.save_resolved_source(
            track_key=track_key,
            engine="votify",
            service="spotify",
            quality="video",
            resolved_url=spotify_url,
        )
    except Exception:
        pass
    with manager._lock:
        job["library_path"] = str(final)
        job["provider_used"] = "votify"
        job["progress"] = 100
        job["last_status"] = "Votify music video download complete"
    manager._append_cache_event(job, "provider", f"Votify produced {final.name}")
    return final


def _current_track_youtube_url(job: dict) -> str:
    """Return an explicit YouTube URL already attached to the selected track.

    This is different from _resolved_youtube_url(): it never falls back to a
    search query. The AI race should see this user/current-track URL as the
    first candidate when present, but search still supplies alternatives.
    """
    merged = _job_metadata(job)
    for key in ("youtube_url", "youtube", "url", "source_url", "external_url"):
        value = merged.get(key)
        if _is_youtube_url(value):
            return str(value)
    return ""


def _prepend_current_youtube_candidate(
    candidates: list[tuple[str, dict]],
    job: dict,
) -> list[tuple[str, dict]]:
    current_url = _current_track_youtube_url(job)
    if not current_url:
        return candidates
    if current_url == job.get("ytpdl_rejected_direct_url"):
        return candidates
    if any(url == current_url for url, _details in candidates):
        return candidates
    wanted = _expected_track(job)
    details = {
        "title": f"{wanted.get('artist', '')} - {wanted.get('title', '')}".strip(" -"),
        "uploader": "Current track YouTube link",
        "duration": wanted.get("duration") or 0,
        "score": 100,
        "url": current_url,
        "source": "current_youtube_link",
    }
    return [(current_url, details), *candidates]


def _norm_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_BAD_MATCH_TERMS = {
    "background music",
    "compilation",
    "cover",
    "full album",
    "gaming",
    "karaoke",
    "mix",
    "no copyright",
    "playlist",
    "royalty free",
    "sound effect",
    "sound effects",
    "sound fx",
    "tribute",
    "drm",
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
    "archive",
    "extended",
}

_VIDEO_MOVIE_TERMS = (
    " documentary ",
    " feature film ",
    " full film ",
    " full movie ",
    " movie ",
    " short film ",
    " soundtrack ",
    " the film ",
    " the movie ",
    " trailer ",
)


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


def _classical_match_adjustment(wanted: dict, raw_title: str, raw_uploader: str) -> tuple[int, dict]:
    wanted_text = f"{wanted.get('artist', '')} {wanted.get('title', '')} {wanted.get('album', '')}"
    candidate_text = f"{raw_title} {raw_uploader}"
    wanted_catalog = _extract_catalog_ids(wanted_text)
    if not wanted_catalog:
        return 0, {}
    candidate_catalog = _extract_catalog_ids(candidate_text)
    if not candidate_catalog:
        return 0, {"classical_catalog": "missing"}
    if wanted_catalog.isdisjoint(candidate_catalog):
        return -90, {"classical_catalog": "mismatch"}

    wanted_terms = _classical_search_terms(str(wanted.get("title") or ""))
    candidate_norm = _norm_text(candidate_text)
    wanted_tokens = [
        token for token in _tokens(wanted_terms)
        if not token.isdigit() and not re.fullmatch(r"[a-z]{1,4}", token)
    ]
    term_coverage = _token_coverage(wanted_tokens, candidate_norm)
    if term_coverage < 60:
        return -45, {"classical_catalog": "matched", "classical_term_coverage": term_coverage}
    return 28, {"classical_catalog": "matched", "classical_term_coverage": term_coverage}


def _candidate_url(entry: dict) -> str:
    return str(entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "")


def _youtube_video_id(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    if "youtu.be" in (parsed.netloc or "").lower():
        return parsed.path.strip("/")
    if "youtube.com" in (parsed.netloc or "").lower():
        from urllib.parse import parse_qs

        return parse_qs(parsed.query).get("v", [""])[0]
    return ""


def _video_music_start_offset(entry: dict, job: dict) -> int:
    if _quality_mode(job.get("quality") or "best") != "video":
        return 0
    try:
        import db
        override = db.get_youtube_video_override(job, youtube_url=_candidate_url(entry))
        if override:
            return max(0, int(override.get("start_offset_s") or 0))
    except Exception:
        pass
    wanted = _expected_track(job)
    artist = _norm_text(wanted.get("artist") or "")
    title = _norm_text(wanted.get("title") or "")
    candidate_title = _norm_text(entry.get("title") or "")
    video_id = _youtube_video_id(_candidate_url(entry))
    duration = _parse_duration_seconds(entry.get("duration"))

    if artist == "michael jackson":
        # Official long-form MJ short films have several minutes of cinematic
        # intro before the actual song. Keep the official clip, but cut the
        # downloaded MP4 to the music section.
        if title == "thriller" and (video_id == "sOnqjkJTMaA" or ("thriller" in candidate_title and duration >= 700)):
            return 252
        if title == "bad" and "bad" in candidate_title and duration >= 900:
            return 815
    return 0


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

    return False


def _candidate_requires_auth(entry: dict) -> bool:
    """Return True if the candidate likely requires age verification or
    authentication (e.g. age-restricted or premium-only content)."""
    # Age-restricted music videos are often still extractable through yt-dlp's
    # mobile clients. Treat premium/sign-in-only availability as blocking, but
    # do not reject age_limit alone before those clients get a chance.
    # 'needs_auth' can mean age verification; mobile clients may still extract
    # those videos, so let the download attempt decide.
    # 'premium_only' means YouTube Premium required.
    if entry.get("availability") == "premium_only":
        return True
    return False

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


def _candidate_description(entry: dict) -> str:
    return str(
        entry.get("description")
        or entry.get("full_description")
        or entry.get("short_description")
        or ""
    )


def _video_candidate_reject_reason(entry: dict, job: dict, candidate_title: str, uploader: str, description: str, start_offset: int = 0) -> str:
    if _quality_mode(job.get("quality") or "best") != "video":
        return ""
    if start_offset > 0:
        return ""
    combined = f" {_norm_text(candidate_title)} {_norm_text(uploader)} {_norm_text(description)} "
    if any(term in combined for term in _VIDEO_MOVIE_TERMS):
        return "movie_or_documentary"
    expected_duration = int(_expected_track(job).get("duration") or 0)
    candidate_duration = _parse_duration_seconds(entry.get("duration"))
    if expected_duration > 0 and candidate_duration > 0:
        tolerance = max(45, int(expected_duration * 0.35))
        if candidate_duration > expected_duration + tolerance:
            return "video_duration_mismatch"
    return ""


def _source_score(
    wanted_artist: str,
    uploader: str,
    candidate_title: str,
    description: str = "",
    *,
    verified_source: bool = False,
    video_mode: bool = False,
) -> int:
    from rapidfuzz import fuzz

    artist_tokens = _tokens(wanted_artist)
    uploader_norm = _norm_text(uploader)
    title_norm = _norm_text(candidate_title)
    description_norm = _norm_text(description)
    if not artist_tokens:
        return 0

    # Official releases are frequently hosted on label/aggregator channels whose
    # name does not contain the artist (so uploader_coverage is 0). Treat the
    # title itself as a trust signal when it is clearly an official release that
    # names the artist, e.g. "CeCe Peniston - Finally (Official Music Video)".
    title_artist_coverage = _token_coverage(artist_tokens, title_norm)
    description_artist_coverage = _token_coverage(artist_tokens, description_norm)
    description_official_release = (
        "official" in description_norm
        and any(marker in description_norm for marker in (" video", " audio", " music video"))
    )
    music_video_by_artist = (
        "music video by" in description_norm
        and description_artist_coverage >= 70
    )
    official_release = (
        "official" in title_norm
        and any(marker in title_norm for marker in (" video", " audio"))
    )
    official_titled_by_artist = (
        (official_release and title_artist_coverage >= 70)
        or ((description_official_release or music_video_by_artist) and max(title_artist_coverage, description_artist_coverage) >= 70)
    )

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
    elif "vevo" in uploader_norm and max(title_artist_coverage, description_artist_coverage) >= 70:
        source = max(source, 88)
    if "official" in uploader_norm and uploader_coverage >= 70:
        source = max(source, 95)
    if "official" in title_norm and uploader_coverage >= 70:
        source = max(source, 90)
    if music_video_by_artist or (description_official_release and description_artist_coverage >= 70):
        source = max(source, 82)
    if video_mode and not verified_source and "vevo" not in uploader_norm and uploader_coverage >= 70:
        source = min(source, 72)
    return int(min(100, source))


def _video_match_adjustment(entry: dict, job: dict, wanted_artist: str, candidate_title: str, uploader: str, description: str) -> tuple[int, dict]:
    if _quality_mode(job.get("quality") or "best") != "video":
        return 0, {}

    title_text = f" {candidate_title} "
    uploader_text = f" {uploader} "
    description_text = f" {description} "
    combined_text = f"{title_text} {uploader_text} {description_text}"
    wanted_title = _norm_text(_expected_track(job).get("title") or "")
    wanted_title_text = f" {wanted_title} "

    adjustment = 0
    reasons: list[str] = []

    official_video_title = (
        "official" in title_text
        and "video" in title_text
        and "lyric video" not in title_text
    )
    music_video_description = " music video " in description_text and " official " in description_text
    positive_video_signal = official_video_title or any(term in title_text for term in (
        " music video ",
        " official video ",
        " live ",
        " performance ",
        " concert ",
        " hd ",
        " 4k ",
    )) or music_video_description
    static_audio_marker = any(term in combined_text for term in (
        " official audio ",
        " audio only ",
        " topic ",
        " album ",
    ))
    autogenerated_audio = " provided to youtube by " in description_text or " auto generated by youtube " in description_text
    unofficial_recreation = any(term in combined_text for term in (
        " ai music video ",
        " ai video ",
        " fan made ",
        " fanmade ",
        " fan video ",
        " fans made ",
        " what if ",
        " unofficial video ",
        " dance video ",
    ))
    official_artist_source = (
        entry.get("channel_is_verified") is True
        and wanted_artist
        and _token_coverage(_tokens(wanted_artist), f"{uploader} {description}") >= 70
        and not static_audio_marker
        and not autogenerated_audio
    )
    if official_video_title:
        adjustment += 36
        reasons.append("official_video_title")
    elif music_video_description:
        adjustment += 22
        reasons.append("official_video_description")
    if official_artist_source:
        adjustment += 12
        reasons.append("verified_artist_source")

    if autogenerated_audio:
        adjustment -= 100
        reasons.append("auto_generated_audio")
    audio_or_static = static_audio_marker and not (official_video_title or music_video_description)
    if audio_or_static and " official video " not in title_text:
        adjustment -= 90
        reasons.append("audio_or_static_video")

    weaker_video_terms = (" lyric video ", " lyrics ", " visualizer ", " live ")
    if any(term in title_text for term in weaker_video_terms) and not any(term in wanted_title_text for term in weaker_video_terms):
        adjustment -= 28
        reasons.append("weaker_video_variant")
    if unofficial_recreation:
        adjustment -= 95
        reasons.append("unofficial_recreation")

    details = {
        "video_mode_candidate": True,
        "video_positive_signal": bool(positive_video_signal),
    }
    if reasons:
        details["video_match_adjustment"] = adjustment
        details["video_match_reasons"] = reasons
    if autogenerated_audio or audio_or_static:
        details["video_static_audio"] = True
    if unofficial_recreation:
        details["video_unofficial_recreation"] = True
    return adjustment, details


def _score_youtube_candidate(entry: dict, job: dict) -> tuple[int, dict]:
    from rapidfuzz import fuzz

    wanted = _expected_track(job)
    wanted_artist = _norm_text(wanted["artist"])
    wanted_title = _norm_text(wanted["title"])
    wanted_full = _norm_text(f"{wanted['artist']} {wanted['title']}")
    raw_title = str(entry.get("title") or "")
    raw_uploader = str(entry.get("uploader") or entry.get("channel") or entry.get("creator") or "")
    raw_description = _candidate_description(entry)
    candidate_title = _norm_text(raw_title)
    uploader = _norm_text(raw_uploader)
    description = _norm_text(raw_description)
    visible_candidate_text = _norm_text(f"{candidate_title} {uploader}")
    artist_evidence_text = _norm_text(f"{visible_candidate_text} {description}")
    start_offset = _video_music_start_offset(entry, job)

    if not wanted_title or not candidate_title:
        return 0, {"reason": "missing title metadata"}
    video_reject = _video_candidate_reject_reason(entry, job, raw_title, raw_uploader, raw_description, start_offset)
    if video_reject:
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
            "drm": False,
            "video_mode_candidate": True,
            "video_reject_reason": video_reject,
        }
    if _candidate_has_drm(entry) or _candidate_requires_auth(entry):
        reason = "drm" if _candidate_has_drm(entry) else "auth_required"
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
            "drm": reason == "drm",
            "auth": reason == "auth_required",
        }

    wanted_title_tokens = _tokens(wanted_title)
    wanted_artist_tokens = _tokens(wanted_artist)
    title_coverage = _token_coverage(wanted_title_tokens, candidate_title)
    artist_coverage = _token_coverage(wanted_artist_tokens, artist_evidence_text) if wanted_artist else 100
    description_artist_coverage = _token_coverage(wanted_artist_tokens, description) if wanted_artist else 100
    source_score = _source_score(
        wanted_artist,
        uploader,
        candidate_title,
        description,
        verified_source=entry.get("channel_is_verified") is True,
        video_mode=_quality_mode(job.get("quality") or "best") == "video",
    ) if wanted_artist else 50

    title_score = max(
        fuzz.WRatio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_full, candidate_title),
    )
    
    # Use token_set_ratio for artist to handle variations like "Artist - Topic" or "ArtistVEVO"
    artist_score = max(artist_coverage, fuzz.token_set_ratio(wanted_artist, artist_evidence_text)) if wanted_artist else 70

    expected_duration = int(wanted.get("duration") or 0)
    candidate_duration = _parse_duration_seconds(entry.get("duration"))
    duration_score = 50
    duration_penalty = 0
    if expected_duration and candidate_duration and start_offset > 0:
        duration_score = 100
    elif expected_duration and candidate_duration:
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
    candidate_text = f" {visible_candidate_text} "
    requested_tokens = f" {wanted_title} "
    for term in _BAD_MATCH_TERMS:
        if f" {term} " in candidate_text and f" {term} " not in requested_tokens:
            penalty += 35
    if "archive" in uploader and "official" not in candidate_text:
        penalty += 45

    if title_coverage < 70:
        penalty += 35
    if wanted_artist and artist_coverage < 70:
        penalty += 40
    if source_score < 45 and any(term in candidate_text for term in (" background music ", " compilation ", " gaming ", " sound fx ")):
        penalty += 60

    classical_adjustment = 0
    classical_details = {}
    if _ytpdl_search_profile(job) == "classical":
        classical_adjustment, classical_details = _classical_match_adjustment(wanted, raw_title, raw_uploader)
    video_adjustment, video_details = _video_match_adjustment(entry, job, wanted_artist, candidate_title, uploader, description)

    score = min(100, int(
        (title_score * 0.42)
        + (artist_score * 0.18)
        + (source_score * 0.22)
        + (duration_score * 0.12)
        + (title_coverage * 0.06)
        + classical_adjustment
        + video_adjustment
        - penalty
        - duration_penalty
    ))
    details = {
        "title": raw_title,
        "uploader": raw_uploader,
        "url": _candidate_url(entry),
        "title_score": int(title_score),
        "artist_score": int(artist_score),
        "source_score": int(source_score),
        "title_coverage": int(title_coverage),
        "artist_coverage": int(artist_coverage),
        "description_artist_coverage": int(description_artist_coverage),
        "duration_score": int(duration_score),
        "score": score,
        "drm": False,
        **classical_details,
        **video_details,
    }
    if start_offset > 0:
        details["video_start_offset"] = start_offset
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
    if details.get("video_static_audio"):
        return False
    if details.get("video_unofficial_recreation"):
        return False
    if details.get("video_mode_candidate") and not details.get("video_positive_signal"):
        return False
    return not (
        score < 55
        or details.get("title_score", 0) < 55
        or details.get("artist_score", 0) < 50
        or (details.get("source_score", 0) < 25 and score < 70)
    )


def _best_youtube_search_match(search_info: dict, job: dict) -> tuple[str, dict]:
    scored = _scored_youtube_candidates(search_info, job)
    best_score, best_details, best_url = scored[0]
    if not _candidate_is_confident(best_score, best_details):
        title = best_details.get("title") or "unknown result"
        raise RuntimeError(f"ytp-dl could not find a confident YouTube match; best was {best_score}%: {title}")
    return best_url, best_details


def _ranked_youtube_matches(search_info: dict, job: dict) -> list[tuple[str, dict]]:
    """Return candidates sorted by score so the caller can fall back to the
    next match if a chosen video turns out to be unavailable. If no highly
    confident matches exist, we still try the top somewhat-plausible matches."""
    scored = _scored_youtube_candidates(search_info, job)
    
    # We prefer 'confident' matches
    confident = [(url, details) for score, details, url in scored if _candidate_is_confident(score, details)]
    if confident:
        return confident

    # If no matches are 'confident', we still try anything with a decent score (>40%)
    # rather than failing immediately. This handles cases where metadata is slightly off.
    plausible = [(url, details) for score, details, url in scored if score > 40]
    if plausible:
        return plausible

    # If everything is <40%, it's likely total junk/unrelated.
    best_score, best_details, _ = scored[0]
    title = best_details.get("title") or "unknown result"
    raise RuntimeError(f"ytp-dl could not find any plausible YouTube match; best was {best_score}%: {title}")


def _extract_youtube_search_info(yt_dlp, target_url: str, ydl_opts: dict) -> dict | None:
    search_opts = {
        key: value
        for key, value in ydl_opts.items()
        if key not in {
            "format",
            "outtmpl",
            "paths",
            "progress_hooks",
            "writethumbnail",
            "addmetadata",
            "postprocessors",
            "merge_output_format",
            "download_ranges",
            "force_keyframes_at_cuts",
        }
    }
    # Search extraction should surface YouTube/network errors. The download path
    # uses ignoreerrors=True so one bad candidate does not abort all fallbacks,
    # but inheriting it here turns DNS/cookie/rate-limit failures into an empty
    # result list and hides the real reason from cache logs.
    search_opts["ignoreerrors"] = False
    search_opts["extract_flat"] = "in_playlist"

    def _extract_with(opts: dict) -> dict | None:
        with yt_dlp.YoutubeDL(opts) as search_ydl:
            search_info = search_ydl.extract_info(target_url, download=False)
        return search_info if isinstance(search_info, dict) else None

    def _entry_count(search_info: dict | None) -> int:
        if not isinstance(search_info, dict):
            return 0
        return len([entry for entry in (search_info.get("entries") or []) if isinstance(entry, dict)])

    first_error: Exception | None = None
    try:
        search_info = _extract_with(search_opts)
        if _entry_count(search_info) > 0 or not _has_youtube_auth_opts(search_opts):
            return search_info
    except Exception as exc:
        first_error = exc
        if not _has_youtube_auth_opts(search_opts):
            raise RuntimeError(f"yt-dlp YouTube search failed for {target_url}: {exc}") from exc

    if _has_youtube_auth_opts(search_opts):
        no_cookie_opts = _without_youtube_auth_opts(search_opts)
        try:
            search_info = _extract_with(no_cookie_opts)
            if _entry_count(search_info) > 0:
                return search_info
            if first_error is not None:
                raise RuntimeError(
                    f"yt-dlp YouTube search returned no entries without browser cookies; "
                    f"cookie search first failed with: {first_error}"
                ) from first_error
        except Exception as exc:
            if first_error is not None:
                raise RuntimeError(
                    f"yt-dlp YouTube search failed with browser cookies and without them; "
                    f"cookie error: {first_error}; no-cookie error: {exc}"
                ) from exc
            raise RuntimeError(f"yt-dlp YouTube search failed without browser cookies: {exc}") from exc

    raise RuntimeError(f"yt-dlp YouTube search returned no entries for {target_url}")


def _youtube_ai_race_timeout() -> float:
    try:
        return max(0.0, min(30.0, float(os.environ.get("MINDINGUFLAC_YOUTUBE_AI_RACE_TIMEOUT", "15"))))
    except Exception:
        return 15.0


def _ranked_youtube_matches_with_ai(
    candidates: list[tuple[str, dict]],
    job: dict,
    manager,
) -> list[tuple[str, dict]]:
    candidates = _prepend_current_youtube_candidate(candidates, job)
    if len(candidates) < 3:
        return candidates
    try:
        import ai_reranker
        config = getattr(manager, "config", None)
        duck_model, ai_provider, gemini_model = ai_reranker.provider_settings(config)
        if not ai_reranker.is_enabled(ai_provider):
            return candidates
    except Exception as exc:
        manager._append_cache_event(job, "trying", f"YouTube AI advisor unavailable ({exc})")
        return candidates
    ai_timeout = _youtube_ai_race_timeout()
    if ai_timeout <= 0:
        return candidates

    done = threading.Event()
    result: dict[str, object] = {}
    id_to_candidate: dict[int, tuple[str, dict]] = {}
    target = _expected_track(job)
    ai_candidates = []
    for idx, (url, details) in enumerate(candidates[:20], start=1):
        details = details or {}
        id_to_candidate[idx] = (url, details)
        ai_candidates.append({
            "id": idx,
            "title": details.get("title") or url,
            "source": details.get("uploader") or "YouTube",
            "seeders": 0,
            "score": details.get("score") or 0,
            "query": "youtube",
            "url": url,
        })

    def run_ai_advisor() -> None:
        try:
            import ai_reranker
            ranked = ai_reranker.rank_candidates(
                target,
                ai_candidates,
                duck_model,
                ai_provider,
                gemini_model,
                include_urls=True,
            )
            if isinstance(ranked, dict):
                result.update(ranked)
            elif ranked:
                result["ranked_ids"] = ranked
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            done.set()

    threading.Thread(target=run_ai_advisor, daemon=True, name=f"youtube-ai-rerank-{job.get('id', '')}").start()
    manager._append_cache_event(job, "trying", "YouTube AI advisor running in parallel")

    if not done.wait(ai_timeout):
        manager._append_cache_event(job, "trying", "YouTube local selector won before AI advisor responded")
        return candidates
    if result.get("error"):
        manager._append_cache_event(job, "trying", f"YouTube AI advisor unavailable ({result['error']})")
        return candidates

    ranked_ids = result.get("ranked_ids")
    ranked_urls = result.get("ranked_urls")
    if not isinstance(ranked_ids, list) and not isinstance(ranked_urls, list):
        return candidates

    ordered: list[tuple[str, dict]] = []
    seen_urls: set[str] = set()

    if isinstance(ranked_urls, list):
        valid_urls = {url for url, _details in candidates}
        for value in ranked_urls:
            url = str(value or "").strip()
            if not url or url not in valid_urls or url in seen_urls:
                continue
            seen_urls.add(url)
            item = next((candidate for candidate in candidates if candidate[0] == url), None)
            if item:
                ordered.append(item)

    if isinstance(ranked_ids, list):
        for value in ranked_ids:
            try:
                item = id_to_candidate.get(int(value))
            except Exception:
                item = None
            if not item:
                continue
            url = item[0]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            ordered.append(item)
    for item in candidates:
        if item[0] not in seen_urls:
            ordered.append(item)

    if ordered:
        manager._append_cache_event(job, "trying", f"YouTube AI advisor ranked {len(ordered)} candidates first")
        return ordered
    return candidates


def _video_download_ranges(selected: dict | None, job: dict):
    if not selected or _quality_mode(job.get("quality") or "best") != "video":
        return None
    start = int(selected.get("video_start_offset") or 0)
    if start <= 0:
        return None
    wanted_duration = int(_expected_track(job).get("duration") or 0)
    end = start + wanted_duration + 10 if wanted_duration > 0 else None
    from yt_dlp.utils import download_range_func

    return download_range_func(None, [(start, end)])


def run(output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files

    if job["id"] in manager._cancel_flags:
        return

    import db
    url = _resolved_youtube_url(job)
    if not url:
        raise RuntimeError("ytp-dl could not build a YouTube URL or search query from the selected track metadata")

    quality = job.get("quality") or "best"
    video_mode = _quality_mode(quality) == "video"
    codec = _quality_to_codec(quality)
    format_selector = _format_selector(quality)
    output_dir.mkdir(parents=True, exist_ok=True)

    override = _video_db_override(job) if video_mode else None
    if video_mode and override:
        manager._append_cache_event(job, "trying", "Using DB video override")

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
        "outtmpl": "%(title)s.%(ext)s",
        "paths": {"home": str(output_dir)},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "cachedir": str(output_dir / ".cache"),
        "allow_unplayable_formats": False,
        "extractor_args": _youtube_extractor_args(),
        # Some upstream/CDN proxies advertise a deflate body but return plain
        # bytes. Asking for identity lets yt-dlp's own retry paths run.
        "http_headers": {"Accept-Encoding": "identity"},
        "progress_hooks": [progress_cb],

        "writethumbnail": True,
        "addmetadata": True,
        "postprocessors": postprocessors,
    }
    if video_mode:
        ydl_opts["merge_output_format"] = "mp4"

    ffmpeg_path = _ffmpeg_location()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    yt_dlp = _get_yt_dlp()
    # browser_cookie3 discovers supported local cookie stores itself. Export
    # only YouTube cookies into this job's private cache directory for yt-dlp,
    # then service_downloader removes the temporary export when the job ends.
    browser_cookie_source = _add_browser_youtube_cookies(ydl_opts, output_dir, str(job.get("id") or ""))
    if not _has_youtube_auth_opts(ydl_opts):
        _add_youtube_cookie_file(ydl_opts)

    if not _has_youtube_auth_opts(ydl_opts):
        _mark_youtube_login_required(job, manager)
        raise RuntimeError(
            "YouTube login required. Click the Mindinguflac notification, sign in in your browser, then return to retry."
        )

    with manager._lock:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["resolved_url"] = url
        job["last_status"] = "Searching YouTube..." if url.startswith("ytsearch") else "Downloading from YouTube..."
        job["active_provider"] = "ytp-dl"
    label = "video" if video_mode else (codec.upper() if codec else "best native audio")
    if browser_cookie_source:
        manager._append_cache_event(job, "trying", "Using signed-in YouTube cookies discovered from the system browsers")
    manager._append_cache_event(job, "trying", f"Downloading via ytp-dl ({label})...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            def _try_download(target_url: str) -> str | None:
                if _is_youtube_search_target(target_url):
                    try:
                        channel_id = _youtube_search_channel_id(target_url)
                        extract_target = _youtube_search_without_channel_filter(target_url)
                        search_info = _extract_youtube_search_info(yt_dlp, extract_target, ydl_opts)
                        if not isinstance(search_info, dict):
                            return None
                        if channel_id:
                            search_info = _filter_youtube_entries_by_channel(search_info, channel_id)
                        candidates = _ranked_youtube_matches(search_info, job)
                        candidates = _prepend_current_youtube_candidate(candidates, job)
                        candidates = _ranked_youtube_matches_with_ai(candidates, job, manager)
                    except Exception as exc:
                        manager._append_cache_event(job, "trying", f"YouTube search failed: {exc}")
                        return None
                else:
                    try:
                        direct_info = ydl.extract_info(target_url, download=False)
                    except Exception as exc:
                        manager._append_cache_event(job, "trying", f"Could not verify direct YouTube URL before download ({exc}); trying it anyway")
                        candidates = [(target_url, None)]
                    else:
                        if isinstance(direct_info, dict):
                            score, selected = _score_youtube_candidate(direct_info, job)
                            if _candidate_is_confident(score, selected):
                                selected["score"] = score
                                candidates = [(_candidate_url(direct_info) or target_url, selected)]
                            else:
                                with manager._lock:
                                    job["ytpdl_rejected_direct_url"] = target_url
                                manager._append_cache_event(
                                    job,
                                    "trying",
                                    f"Direct YouTube URL did not match this track ({score}%): {selected.get('title', '')[:80]}",
                                )
                                return None
                        else:
                            candidates = [(target_url, None)]

                # Try up to 8 candidates in order of score
                attempts = [(u, s) for u, s in candidates if not db.is_blacklisted(u)][:8]
                if not attempts:
                    return None

                for index, (download_url, selected) in enumerate(attempts):
                    if job["id"] in manager._cancel_flags:
                        return None
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
                        def _download_with(download_ydl) -> tuple[int, bool]:
                            previous_ranges = download_ydl.params.get("download_ranges")
                            previous_force_keyframes = download_ydl.params.get("force_keyframes_at_cuts")
                            before = {path.resolve() for path in output_dir.rglob("*") if path.is_file()}
                            try:
                                ranges = _video_download_ranges(selected, job)
                                if ranges:
                                    download_ydl.params["download_ranges"] = ranges
                                    download_ydl.params["force_keyframes_at_cuts"] = True
                                    manager._append_cache_event(
                                        job,
                                        "trying",
                                        f"Starting video at music section ({int(selected.get('video_start_offset') or 0)}s)",
                                    )
                                else:
                                    download_ydl.params.pop("download_ranges", None)
                                    download_ydl.params.pop("force_keyframes_at_cuts", None)
                                result = download_ydl.download([download_url])
                            finally:
                                if previous_ranges is not None:
                                    download_ydl.params["download_ranges"] = previous_ranges
                                else:
                                    download_ydl.params.pop("download_ranges", None)
                                if previous_force_keyframes is not None:
                                    download_ydl.params["force_keyframes_at_cuts"] = previous_force_keyframes
                                else:
                                    download_ydl.params.pop("force_keyframes_at_cuts", None)
                            produced = [path for path in _find_audio_files(output_dir) if path.resolve() not in before]
                            result_code = result if isinstance(result, int) else 0
                            return result_code, bool(produced or _find_audio_files(output_dir))

                        result_code, has_file = _download_with(ydl)
                        if result_code == 0 or has_file:
                            return download_url

                        if _has_youtube_auth_opts(ydl.params):
                            no_cookie_opts = _without_youtube_auth_opts(ydl_opts)
                            manager._append_cache_event(job, "trying", "YouTube candidate produced no file with cookies; retrying without cookies...")
                            with yt_dlp.YoutubeDL(no_cookie_opts) as no_cookie_ydl:
                                result_code, has_file = _download_with(no_cookie_ydl)
                            if result_code == 0 or has_file:
                                return download_url

                        # This can be caused by transient YouTube cookie/session failures, so do not
                        # permanently blacklist the URL unless yt-dlp raises a concrete non-transient error.
                        if index + 1 < len(attempts):
                            manager._append_cache_event(
                                job, "trying", f"YouTube candidate produced no file, trying another..."
                            )
                        continue
                    except Exception as exc:
                        exc_str = str(exc)
                        # 403/429 = bot detection / rate limit — transient, don't blacklist
                        # "Requested format is not available" is cookie-induced: a signed-in
                        # session can be served SABR-style streams with no downloadable
                        # formats, while the same video resolves fine anonymously. Treating
                        # it as non-transient skipped the no-cookie retry below *and*
                        # permanently blacklisted videos that are perfectly downloadable.
                        transient = any(t in exc_str for t in ("403", "429", "Forbidden", "Too Many Requests", "Sign in", "cookies", "PO Token", "SABR", "Requested format is not available"))
                        if transient and _has_youtube_auth_opts(ydl.params):
                            no_cookie_opts = _without_youtube_auth_opts(ydl_opts)
                            manager._append_cache_event(job, "trying", f"YouTube candidate unavailable with cookies ({exc_str[:60]}), retrying without cookies...")
                            try:
                                with yt_dlp.YoutubeDL(no_cookie_opts) as no_cookie_ydl:
                                    result_code, has_file = _download_with(no_cookie_ydl)
                                if result_code == 0 or has_file:
                                    return download_url
                            except Exception as retry_exc:
                                exc_str = f"{exc_str}; no-cookie retry: {retry_exc}"
                        if not transient:
                            db.add_to_blacklist(download_url, f"ytp-dl error: {exc_str[:120]}")
                        if index + 1 < len(attempts):
                            manager._append_cache_event(
                                job, "trying", f"YouTube candidate unavailable ({exc_str[:60]}), trying another..."
                            )
                        else:
                            manager._append_cache_event(job, "trying", f"YouTube candidate failed: {exc_str[:80]}")
                return None

            worked_url = None
            if not video_mode and url.startswith("ytsearch"):
                for channel_query, channel_label in _youtube_channel_search_attempts(ydl, job):
                    manager._append_cache_event(job, "trying", f"Trying YouTube {channel_label} before broad search...")
                    worked_url = _try_download(channel_query)
                    if worked_url:
                        break

            if not worked_url and url:
                worked_url = _try_download(url)
            
            if not worked_url:
                if url and not url.startswith("ytsearch"):
                    if job.get("ytpdl_rejected_direct_url") != url:
                        db.add_to_blacklist(url, "direct url failed")
                
                # Phase 2: Full Search (Artist + Title + Album)
                search_query = _youtube_search_query(job, clean=False)
                if search_query and search_query != url:
                    manager._append_cache_event(job, "trying", f"Falling back to full YouTube search ({_youtube_search_profile_label(job, search_query)})...")
                    worked_url = _try_download(search_query)
            
            if not worked_url:
                # Phase 3: Clean Search (Artist + Base Title, stripping Remastered/Deluxe/etc.)
                clean_query = _youtube_search_query(job, clean=True)
                if clean_query and clean_query != url:
                    manager._append_cache_event(job, "trying", f"Falling back to clean YouTube search ({_youtube_search_profile_label(job, clean_query)}, stripping version suffixes)...")
                    worked_url = _try_download(clean_query)

            if not worked_url:
                # Phase 4: Broad Search (Artist + Base Title, no "official audio" constraint)
                broad_query = _broad_youtube_search_query(job)
                if broad_query and broad_query != url:
                    manager._append_cache_event(job, "trying", f"Falling back to broad YouTube search ({_youtube_search_profile_label(job, broad_query)}, no official/audio constraint)...")
                    worked_url = _try_download(broad_query)

            if not worked_url:
                raise RuntimeError("All YouTube download attempts failed")

    except Exception as exc:
        raise RuntimeError(f"ytp-dl failed: {exc}") from exc

    audio_files = _find_audio_files(output_dir)
    if not audio_files:
        raise RuntimeError("ytp-dl reported success but no playable audio file was found")

    final = audio_files[0]
    
    # Persistence: save the successful URL
    if worked_url:
        track_key = job.get("track_key") or f"{job.get('artist','').lower()}||{job.get('title','').lower()}"
        existing = db.get_resolved_source(track_key)
        if not (job.get("engine") == "torrent" and existing and existing.get("engine") == "torrent"):
            db.save_resolved_source(
                track_key=track_key,
                engine="ytp-dl",
                service="youtube",
                quality=job.get("quality") or "best",
                resolved_url=worked_url
            )

    with manager._lock:
        job["library_path"] = str(final)
        job["provider_used"] = "ytp-dl"
        job["progress"] = 100
        job["last_status"] = "YouTube download complete"
    manager._append_cache_event(job, "provider", f"ytp-dl produced {final.name}")
