"""YouTube-only music video clip downloader, separate from music torrents."""

from __future__ import annotations

import shutil
import os
from pathlib import Path

def _ffmpeg_exe() -> str:
    """Return path to bundled ffmpeg (via imageio-ffmpeg) or fall back to PATH."""
    try:
        from backend_ytpdl import _ffmpeg_location
        return _ffmpeg_location()
    except Exception:
        pass
    import shutil, os
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return shutil.which(name) or "ffmpeg"


def _ffprobe_exe() -> str:
    """Return path to ffprobe alongside the bundled ffmpeg, or fall back to PATH."""
    import os, shutil
    ffmpeg = _ffmpeg_exe()
    if ffmpeg and ffmpeg != "ffmpeg":
        # imageio-ffmpeg ships ffprobe next to ffmpeg
        probe = str(Path(ffmpeg).with_name("ffprobe" + (".exe" if os.name == "nt" else "")))
        if Path(probe).exists():
            return probe
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    import sys
    bundled = Path(getattr(sys, "_MEIPASS", "")) / name
    if getattr(sys, "frozen", False) and bundled.is_file():
        return str(bundled)
    return shutil.which(name) or "ffprobe"


def _video_duration_s(path: Path) -> float:
    """Return video duration in seconds via ffprobe, or 0 on failure."""
    try:
        import subprocess, json as _json
        result = subprocess.run(
            [_ffprobe_exe(), "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return float(_json.loads(result.stdout).get("format", {}).get("duration") or 0)
    except Exception:
        pass
    return 0.0


_WEB_SAFE_AUDIO = frozenset({"aac", "mp3", "opus", "vorbis", "mp4a"})

def _ensure_web_safe_audio(path: Path) -> bool:
    """If the video has AC3/DTS/unsupported audio, re-encode the audio track to AAC in-place.

    Video stream is copied (no quality loss, fast). Returns True when the file is
    ready to play in WKWebView, False if ffmpeg fails and the file should be discarded.
    """
    import subprocess, json as _json
    try:
        r = subprocess.run(
            [_ffprobe_exe(), "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return True  # can't probe — pass through, let player decide
        streams = _json.loads(r.stdout).get("streams", [])
        audio_codecs = [
            (s.get("codec_name") or "").lower()
            for s in streams if s.get("codec_type") == "audio"
        ]
        needs_remux = any(c and c not in _WEB_SAFE_AUDIO for c in audio_codecs)
        if not needs_remux:
            return True
        print(f"[VideoBackend] re-encoding audio {audio_codecs} → AAC for WebKit compatibility")
        tmp = path.with_suffix(".reencode.mp4")
        res = subprocess.run(
            [_ffmpeg_exe(), "-y", "-i", str(path),
             "-c:v", "copy",        # video: no re-encode
             "-c:a", "aac", "-b:a", "192k",  # audio: AC3/DTS → AAC
             "-c:s", "mov_text",    # subtitle passthrough (or drop if unsupported)
             "-map", "0:v:0", "-map", "0:a:0",  # keep first video + first audio track only
             str(tmp)],
            capture_output=True, text=True, timeout=600,
        )
        if res.returncode == 0 and tmp.exists() and tmp.stat().st_size > 65536:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
        print(f"[VideoBackend] audio re-encode failed: {res.stderr[-200:]}")
        return False
    except Exception as exc:
        print(f"[VideoBackend] _ensure_web_safe_audio error: {exc}")
        return True  # don't reject on unexpected errors


def _clip_duration_ok(path: Path, expected_s: float) -> bool:
    """Return False when the downloaded video is absurdly longer than the track.

    Tolerance: allow up to max(3× expected, expected + 600 s, 900 s).
    This lets the Thriller short film (13:43 for a 5:57 track) through,
    but rejects concert recordings and multi-video dumps.
    When expected_s is unknown (0), fall back to a 30-minute hard cap.
    """
    actual = _video_duration_s(path)
    if actual <= 0:
        return True  # can't probe — accept and let playback decide
    # Dynamic ceiling: track length + 50% padding (max +10 min), floor 15 min.
    # Examples: 3-min pop → 15 min cap | 5:57 Thriller → 15 min | 15-min Voodoo Chile → 22.5 min
    if expected_s > 0:
        ceiling = max(expected_s + min(expected_s * 0.5, 600), 900)
    else:
        ceiling = 900  # 15-min default when duration unknown
    ok = actual <= ceiling
    if not ok:
        print(f"[VideoBackend] duration {actual:.0f}s > ceiling {ceiling:.0f}s — rejected")
    return ok


# ── YouTube fallback download ────────────────────────────────────────────────

def _download_youtube_clip(url: str, start_offset: int, output_path: Path, log_cb=None) -> bool:
    """Download a YouTube music video at 480p H.264/AAC into output_path."""
    from video_motion import preview_youtube, StaticVideoError, VideoPreviewError, mark_file_preview
    preview = preview_youtube(url, start_offset, log_cb)
    if preview.get("status") == "static":
        raise StaticVideoError("No video available: preview contains only static artwork")
    if preview.get("status") != "moving":
        raise VideoPreviewError(preview.get("reason") or "Video preview could not be checked")
    try:
        import yt_dlp
        from backend_ytpdl import _ffmpeg_location, _youtube_metadata_opts, _add_youtube_cookie_file, _youtube_session_signed_out, _youtube_js_runtime_opts
    except Exception:
        return False

    tmp = output_path.with_suffix(".ytmp.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    opts: dict = {
        "format": (
            "bestvideo[vcodec^=avc][height<=480]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc][height<=480]+bestaudio/"
            "bestvideo[vcodec^=avc]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc]+bestaudio/"
            "bestvideo[height<=480]+bestaudio[ext=m4a]/"
            "bestvideo[height<=480]+bestaudio/"
            "bestvideo+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[height<=480]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(tmp),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "http_chunk_size": 10 * 1024 * 1024,
    }
    opts.update(_youtube_js_runtime_opts())
    is_android = os.environ.get("MINDINGUFLAC_ANDROID") == "1"
    if is_android:
        # Progressive MP4 already contains sound; adaptive formats need FFmpeg,
        # which isn't shipped in the Android APK.
        opts.update(_youtube_metadata_opts(skip_download=False))
        opts["format"] = "best[ext=mp4][vcodec!=none][acodec!=none][height<=720]/best[ext=mp4][vcodec!=none][acodec!=none]"
        opts.pop("merge_output_format", None)
    if start_offset > 0 and not is_android:
        from yt_dlp.utils import download_range_func
        opts["download_ranges"] = download_range_func(None, [(start_offset, None)])
        opts["force_keyframes_at_cuts"] = True
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg

    attempts = []
    cookie_opts = dict(opts)
    if _add_youtube_cookie_file(cookie_opts):
        attempts.append(cookie_opts)
    if not is_android and not _youtube_session_signed_out():
        for browser in ("safari", "chrome", "firefox"):
            attempts.append({**opts, "cookiesfrombrowser": (browser,)})
    attempts.append(dict(opts))
    for attempt in attempts:
        try:
            tmp.unlink(missing_ok=True)
            with yt_dlp.YoutubeDL(attempt) as ydl:
                ydl.download([url])
            if tmp.exists() and tmp.stat().st_size > 65536:
                tmp.replace(output_path)
                mark_file_preview(output_path, preview)
                return True
        except Exception as exc:
            if log_cb:
                log_cb(f"Video download failed: {exc}")
            tmp.unlink(missing_ok=True)
    return False


# ── Main entry point ─────────────────────────────────────────────────────────

def fetch_clip_to_path(identity: dict, output_path: Path, log_cb=None, advisor_config=None) -> bool:
    """Screen matching previews, then download only a candidate with motion."""
    from video_motion import StaticVideoError, VideoPreviewError
    log = log_cb if callable(log_cb) else print
    artist, title = (str(identity.get(field) or "").strip() for field in ("artist", "title"))
    if not artist or not title:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        expected_s = float(identity.get("duration_s") or 0) or float(identity.get("duration_ms") or 0) / 1000
    except (TypeError, ValueError):
        expected_s = 0.0
    track_key = str(identity.get("track_key") or "")
    candidates = []
    def add(url, offset=0):
        if url and url not in [item[0] for item in candidates]:
            candidates.append((url, int(offset or 0)))
    explicit = bool(identity.get("youtube_id"))
    if explicit:
        add(f"https://www.youtube.com/watch?v={identity['youtube_id']}")
    else:
        try:
            import db
            override = db.get_youtube_video_override(identity) or {}
            if override.get("youtube_video_id"):
                explicit = True
                add(f"https://www.youtube.com/watch?v={override['youtube_video_id']}", override.get("start_offset_s"))
            elif track_key:
                saved = db.get_video_source(track_key) or {}
                url = str(saved.get("youtube_url") or "")
                if url not in db.get_video_blacklist():
                    add(url)
        except Exception:
            pass
    if not explicit:
        log(f"Searching YouTube video for: {artist} – {title}")
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "noprogress": True,
                    "noplaylist": True, "extract_flat": True, "socket_timeout": 8}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch5:{artist} {title} official music video", download=False) or {}
            artist_words = [word.casefold() for word in artist.split() if len(word) > 3]
            title_words = [word.casefold() for word in title.split() if len(word) > 2]
            for entry in info.get("entries") or []:
                name = str(entry.get("title") or "").casefold()
                duration = float(entry.get("duration") or 0)
                if duration and duration > (max(expected_s * 3, 900) if expected_s else 900):
                    continue
                if not (artist.casefold() in name or any(word in name for word in artist_words)):
                    continue
                if not (title.casefold() in name or title_words and all(word in name for word in title_words)):
                    continue
                url = str(entry.get("webpage_url") or entry.get("url") or "")
                if entry.get("id") and not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={entry['id']}"
                add(url)
        except Exception:
            pass
    if not candidates:
        from app import _lookup_youtube_video
        result = _lookup_youtube_video(identity) or {}
        if not result.get("ok"):
            raise VideoPreviewError("Video search failed. Check your connection and try again.")
        if result.get("found"):
            add(result.get("webpage_url"), result.get("video_start_offset"))
    uncertain = []
    static = 0
    for url, offset in candidates[:3]:
        try:
            if not _download_youtube_clip(url, offset, output_path, log):
                uncertain.append("Video download failed. Try again.")
                continue
        except StaticVideoError:
            static += 1
            log("Skipping video containing only static artwork")
            continue
        except VideoPreviewError as exc:
            uncertain.append(str(exc))
            continue
        if not _clip_duration_ok(output_path, expected_s):
            output_path.unlink(missing_ok=True)
            continue
        if track_key:
            try:
                import db
                db.save_video_source(track_key, youtube_url=url)
            except Exception:
                pass
        log(f"Video saved from YouTube → {output_path.name}")
        return True
    if uncertain:
        raise VideoPreviewError(uncertain[0])
    if static:
        raise StaticVideoError("No video available: matching previews contain only static artwork")
    return False
