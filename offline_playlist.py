"""The device-local, automatic playlist of completed music downloads."""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from mutagen import File as AudioFile
from mutagen.flac import Picture

from service_downloader import AUDIO_SUFFIXES, _audio_path_matches_track, is_valid_audio_file

OFFLINE_PLAYLIST_ID = "__offline__"
_COVERS = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp", "folder.jpg")


def _stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return 0, 0


@lru_cache(maxsize=512)
def _sidecar(path: str, stamp: tuple) -> dict:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _embedded_art(audio) -> tuple[bytes, str] | None:
    pictures = getattr(audio, "pictures", None) or []
    if pictures:
        picture = next((p for p in pictures if p.type == 3), pictures[0])
        return picture.data, picture.mime
    tags = getattr(audio, "tags", None) or {}
    for key, value in tags.items():
        if key.startswith("APIC"):
            return value.data, value.mime
    if tags.get("covr"):
        cover = tags["covr"][0]
        return bytes(cover), "image/png" if cover.imageformat == 14 else "image/jpeg"
    if tags.get("metadata_block_picture"):
        picture = Picture(base64.b64decode(tags["metadata_block_picture"][0]))
        return picture.data, picture.mime
    return None


@lru_cache(maxsize=2048)
def _audio_metadata(path: str, stamp: tuple) -> tuple[dict, str, bool]:
    """Cache tag parsing, without retaining embedded image bytes in memory."""
    metadata, art_key = {}, ""
    try:
        audio = AudioFile(path)
        if audio is None:
            return {}, "", False
        tags = audio.tags or {}
        for field, keys in {
            "title": ("title", "TIT2", "\xa9nam"),
            "artist": ("artist", "TPE1", "\xa9ART"),
            "album": ("album", "TALB", "\xa9alb"),
            "year": ("date", "TDRC", "\xa9day"),
            "isrc": ("isrc", "TSRC"),
        }.items():
            value = next((tags.get(k) for k in keys if tags.get(k)), None)
            if value is not None:
                value = getattr(value, "text", value)
                metadata[field] = str(value[0] if isinstance(value, (list, tuple)) else value)
        metadata["duration_ms"] = round(float(getattr(audio.info, "length", 0)) * 1000)
        art = _embedded_art(audio)
        if art:
            art_key = hashlib.sha256(art[0]).hexdigest()
        return metadata, art_key, True
    except Exception:
        return metadata, art_key, False


def _cover_path(path: Path, root: Path) -> Path | None:
    for name in _COVERS:
        cover = path.parent / name
        if cover.is_file() and cover.resolve().is_relative_to(root):
            return cover
    return None


def read_artwork(path: Path, music_root: Path) -> tuple[bytes, str] | None:
    root = Path(music_root).resolve()
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
        return None
    cover = _cover_path(path, root)
    if cover:
        mime = {".png": "image/png", ".webp": "image/webp"}.get(cover.suffix.lower(), "image/jpeg")
        return cover.read_bytes(), mime
    try:
        return _embedded_art(AudioFile(path))
    except Exception:
        return None


def build_offline_playlist(manager) -> dict | None:
    """Read real saved files, independent of history, sync and online providers."""
    root = Path(manager.config.music_dir).resolve()
    if not root.is_dir():
        return None
    with manager._lock:
        jobs = [dict(job) for job in manager.jobs.values()]
    saved_jobs = {}
    unfinished = []
    for job in jobs:
        if job.get("mode") != "download":
            continue
        if job.get("status") == "finished" and job.get("library_path"):
            saved_jobs[str(Path(job["library_path"]).resolve())] = job
        elif job.get("output_dir"):
            unfinished.append(job)
    tracks, artwork, seen_art, seen_paths = [], [], set(), set()
    for candidate in root.rglob("*"):
        if candidate.suffix.lower() not in AUDIO_SUFFIXES or "_race" in candidate.relative_to(root).parts:
            continue
        try:
            path = candidate.resolve()
            if path in seen_paths or not path.is_relative_to(root) or not path.is_file():
                continue
            stamp = _stamp(path)
            if not stamp[1]:
                continue
            job = saved_jobs.get(str(path), {})
            if not job and any(
                Path(j["output_dir"]).resolve() == path.parent
                and _audio_path_matches_track(path, j.get("title", ""), j.get("artist", ""))
                for j in unfinished
            ):
                continue
            tags, embedded_key, valid = _audio_metadata(str(path), stamp)
            if not valid and not is_valid_audio_file(path):
                continue
            seen_paths.add(path)
            parts = path.relative_to(root).parts
            meta = {
                "title": path.stem,
                "artist": parts[-3] if len(parts) >= 3 else "Unknown Artist",
                "album": parts[-2] if len(parts) >= 3 else "Unknown Album",
                **tags,
            }
            info_path = path.parent / "metadata.json"
            sidecar = _sidecar(str(info_path), _stamp(info_path))
            album_info = sidecar.get("album_info") if isinstance(sidecar.get("album_info"), dict) else {}
            entries = sidecar.get("tracks") if isinstance(sidecar.get("tracks"), dict) else {}
            for title, entry in entries.items():
                if isinstance(entry, dict) and _audio_path_matches_track(path, str(title), entry.get("artist") or album_info.get("artist") or meta["artist"]):
                    meta.update({k: v for k, v in {**album_info, **entry}.items() if v not in (None, "", [], {})})
                    break
            meta.update({k: v for k, v in (job.get("metadata") or {}).items() if v not in (None, "", [], {})})
            for key in ("title", "artist", "album", "isrc", "spotify_id"):
                if job.get(key) and not (job.get("metadata") or {}).get(key):
                    meta[key] = job[key]
            cover = _cover_path(path, root)
            art_key = str(cover) if cover else embedded_key
            art_stamp = _stamp(cover) if cover else stamp
            art_url = "/api/library/artwork?" + urlencode({"path": str(path), "v": f"{art_stamp[0]}-{art_stamp[1]}"}) if art_key else ""
            meta.update({
                "type": "track", "kind": "track", "offline": True,
                "library_path": str(path), "artwork_url": art_url,
                "source": "Offline", "track_key": meta.get("track_key") or "offline:" + hashlib.sha256(str(path).encode()).hexdigest(),
            })
            tracks.append((stamp[0], str(path), meta, art_key))
        except (OSError, ValueError, TypeError):
            # A file can disappear or finish downloading during this scan.
            continue
    tracks.sort(key=lambda item: (-item[0], item[1]))
    for _, _, track, art_key in tracks:
        if art_key and art_key not in seen_art:
            artwork.append(track["artwork_url"])
            seen_art.add(art_key)
            if len(artwork) == 4:
                break
    if not tracks:
        return None
    return {
        "id": OFFLINE_PLAYLIST_ID, "name": "Offline", "playlist_origin": "offline",
        "read_only": True, "description": "All your downloaded songs, ready to play offline.",
        "artwork_url": "", "artwork_urls": artwork,
        "tracks": [item[2] for item in tracks], "metadata_fetched": True,
    }
