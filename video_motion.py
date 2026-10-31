"""Check sparse preview frames before downloading or aligning a music video."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path

_VERSION = 1
_lock = threading.RLock()


class StaticVideoError(RuntimeError):
    pass


class VideoPreviewError(RuntimeError):
    pass


def _cache_path() -> Path:
    from config import app_data_dir
    return app_data_dir() / "video-motion.json"


def _cached(key: str) -> dict | None:
    with _lock:
        try:
            item = json.loads(_cache_path().read_text("utf-8")).get(key)
            if item and item.get("version") == _VERSION and time.time() - item.get("checked_at", 0) < 30 * 86400:
                return item
        except (OSError, ValueError, TypeError):
            pass
    return None


def _remember(key: str, result: dict) -> dict:
    if result.get("status") not in {"moving", "static"}:
        return result
    result = {**result, "version": _VERSION, "checked_at": time.time()}
    with _lock:
        path = _cache_path()
        try:
            entries = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            entries = {}
        entries[key] = result
        if len(entries) > 500:
            entries = dict(sorted(entries.items(), key=lambda pair: pair[1].get("checked_at", 0))[-500:])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries), "utf-8")
        temporary.replace(path)
    return result


def assess_frames(frames: list) -> dict:
    """Ignore small JPEG differences; require motion across several samples."""
    from PIL import Image
    if len(frames) < 6:
        return {"status": "unknown", "reason": "Not enough video preview frames", "samples": len(frames)}
    samples = [list(frame.convert("L").resize((64, 36), Image.Resampling.BILINEAR).tobytes()) for frame in frames]

    def difference(a, b):
        delta = [abs(x - y) for x, y in zip(a, b)]
        return sum(delta) / (255 * len(delta)), sum(value > 12 for value in delta) / len(delta)

    pairs = [difference(a, b) for a, b in zip(samples, samples[1:])]
    largest_cluster = max(sum(difference(a, b)[0] < .015 and difference(a, b)[1] < .05 for b in samples) for a in samples)
    moving_pairs = sum(mean > .02 or changed > .08 for mean, changed in pairs)
    if largest_cluster >= math.ceil(len(samples) * .8):
        status = "static"
    elif moving_pairs >= 2:
        status = "moving"
    else:
        status = "unknown"
    return {"status": status, "samples": len(samples), "moving_pairs": moving_pairs,
            "max_difference": round(max(mean for mean, _ in pairs), 5),
            "reason": "Only static artwork in the video preview" if status == "static" else
                      "Video preview contains motion" if status == "moving" else "Video motion could not be confirmed"}


def storyboard_preview(info: dict, start_offset: float = 0) -> dict:
    """Read at most three small storyboard sheets, never the media stream."""
    from PIL import Image
    import requests
    duration = float(info.get("duration") or 0)
    choices = [fmt for fmt in info.get("formats", []) if fmt.get("protocol") == "mhtml"
               and fmt.get("fragments") and fmt.get("rows") and fmt.get("columns") and fmt.get("fps")]
    if not choices or duration <= 0:
        return {"status": "unknown", "reason": "Video has no usable storyboard preview"}
    choices.sort(key=lambda fmt: (int(fmt.get("width") or 0) < 80, int(fmt.get("width") or 0)))
    fmt = choices[0]
    columns, rows = int(fmt["columns"]), int(fmt["rows"])
    per_sheet = columns * rows
    fps = float(fmt["fps"])
    count = max(1, int(round(duration * fps)))
    start = min(max(0, start_offset), duration * .95)
    indices = []
    for fraction in (.15, .5, .85):
        center = min(count - 1, int((start + (duration - start) * fraction) * fps))
        first = center // per_sheet * per_sheet
        end = min(count, first + per_sheet)
        base = max(first, min(center - 1, end - 3))
        indices.extend(range(base, min(end, base + 3)))
    sheets = {}
    frames = []
    for index in sorted(set(indices)):
        sheet_index, tile = divmod(index, per_sheet)
        if sheet_index >= len(fmt["fragments"]):
            continue
        if sheet_index not in sheets:
            response = requests.get(fmt["fragments"][sheet_index]["url"], timeout=(5, 8))
            response.raise_for_status()
            if len(response.content) > 4 * 1024 * 1024:
                raise VideoPreviewError("Storyboard preview is too large")
            sheets[sheet_index] = Image.open(io.BytesIO(response.content)).convert("RGB")
        sheet = sheets[sheet_index]
        width, height = sheet.width // columns, sheet.height // rows
        x, y = tile % columns * width, tile // columns * height
        frames.append(sheet.crop((x, y, x + width, y + height)))
    return {**assess_frames(frames), "method": "storyboard", "sheets": len(sheets)}


def preview_youtube(url: str, start_offset: float = 0, log=None) -> dict:
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    key = f"youtube:{match[1]}:{int(start_offset)}" if match else ""
    if key:
        cached = _cached(key)
        if cached:
            return cached
    if log:
        log("Checking video motion from preview images…")
    try:
        import yt_dlp
        from backend_ytpdl import _youtube_metadata_opts, _youtube_js_runtime_opts, _add_youtube_cookie_file
        opts = _youtube_metadata_opts(skip_download=True)
        opts.update(_youtube_js_runtime_opts())
        opts.update(quiet=True, no_warnings=True, noplaylist=True, socket_timeout=10,
                    retries=1, ignore_no_formats_error=True)
        _add_youtube_cookie_file(opts)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        result = storyboard_preview(info, start_offset)
    except Exception as exc:
        result = {"status": "unknown", "reason": f"Could not check video preview: {type(exc).__name__}"}
    if key:
        return _remember(key, result)
    return result


def _file_key(path: Path) -> str:
    stat = path.stat()
    return "file:" + hashlib.sha256(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


def cached_file_preview(path: Path) -> dict | None:
    try:
        return _cached(_file_key(path))
    except OSError:
        return None


def mark_file_preview(path: Path, result: dict) -> dict:
    return _remember(_file_key(path), result)


def preview_file(path: Path) -> dict:
    cached = cached_file_preview(path)
    if cached:
        return cached
    from PIL import Image
    frames = []
    try:
        if os.environ.get("MINDINGUFLAC_ANDROID") == "1":
            from java import jclass
            retriever = jclass("android.media.MediaMetadataRetriever")()
            try:
                retriever.setDataSource(str(path))
                if str(retriever.extractMetadata(17)).lower() != "yes":
                    return mark_file_preview(path, {"status": "static", "reason": "File has no video track", "method": "local_frames"})
                duration = float(str(retriever.extractMetadata(9))) / 1000
                for fraction in (.1, .25, .4, .55, .7, .85):
                    bitmap = retriever.getFrameAtTime(int(duration * fraction * 1000000), 2)
                    if bitmap is None:
                        continue
                    scaled = jclass("android.graphics.Bitmap").createScaledBitmap(bitmap, 160, 90, True)
                    output = jclass("java.io.ByteArrayOutputStream")()
                    scaled.compress(jclass("android.graphics.Bitmap$CompressFormat").JPEG, 80, output)
                    frames.append(Image.open(io.BytesIO(bytes(output.toByteArray()))).copy())
                    if not scaled.equals(bitmap):
                        scaled.recycle()
                    bitmap.recycle()
            finally:
                retriever.release()
        else:
            from backend_video import _ffprobe_exe, _ffmpeg_exe
            probe = subprocess.run([_ffprobe_exe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                   capture_output=True, timeout=10)
            if probe.returncode != 0:
                raise VideoPreviewError("Could not inspect media tracks")
            metadata = json.loads(probe.stdout)
            if not any(stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
                       for stream in metadata.get("streams", [])):
                return mark_file_preview(path, {"status": "static", "reason": "File has no video track", "method": "local_frames"})
            duration = float(metadata.get("format", {}).get("duration") or 0)
            if duration <= 0:
                return {"status": "unknown", "reason": "Could not read video duration"}
            for fraction in (.1, .25, .4, .55, .7, .85):
                result = subprocess.run([_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(duration * fraction),
                    "-i", str(path), "-frames:v", "1", "-an", "-vf", "scale=160:90", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode == 0 and len(result.stdout) == 160 * 90 * 3:
                    frames.append(Image.frombytes("RGB", (160, 90), result.stdout))
        return mark_file_preview(path, {**assess_frames(frames), "method": "local_frames"})
    except Exception as exc:
        return {"status": "unknown", "reason": f"Could not check cached video: {type(exc).__name__}"}
