from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

from config import jobs_path


def clean_part(value: str) -> str:
    cleaned = "".join(char for char in value if char not in '/\\:*?"<>|').strip()
    return cleaned or "Unknown"


def is_valid_audio_file(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size < 100 * 1024:
            return False
        with path.open("rb") as audio_file:
            header = audio_file.read(64)
    except Exception:
        return False
    suffix = path.suffix.lower()
    if suffix == ".flac":
        return b"fLaC" in header
    if suffix in {".ogg", ".opus"}:
        return b"OggS" in header
    if suffix == ".mp3":
        return b"ID3" in header or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)
    if suffix in {".m4a", ".aac"}:
        return b"ftyp" in header or b"M4A " in header or suffix == ".aac"
    if suffix == ".wav":
        return b"RIFF" in header and b"WAVE" in header
    return any(byte != 0 for byte in header)


AUDIO_SUFFIXES = {
    ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".alac", ".webm",
    ".wma", ".wv", ".ape", ".mpc", ".mp4", ".m4b", ".m4p", ".m4r",
    ".mp2", ".mp1", ".mpa", ".m2a", ".m3a",
    ".aiff", ".aif", ".aifc",
    ".au", ".snd",
    ".ra", ".ram", ".rm", ".rmvb",
    ".spx", ".oga", ".ogv",
    ".amr", ".awb",
    ".dsf", ".dff", ".dsd",
    ".caf", ".shn",
    ".tta", ".tak",
    ".ac3", ".dts", ".eac3",
    ".mka", ".mkv",
    ".ts", ".mts", ".m2ts",
}


def is_download_audio_candidate(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    return (
        suffix in AUDIO_SUFFIXES
        or suffix in {".part", ".ytdl", ".tmp", ".temp", ".crdownload"}
        or name.endswith(".m4a.tmp")
        or ".temp" in name
    )


IDENTIFIER_FIELDS = (
    "spotify_id",
    "isrc",
    "deezer_id",
    "tidal_id",
    "amazon_id",
    "apple_music_id",
    "musicbrainz_recording_id",
    "musicbrainz_release_id",
    "musicbrainz_artist_id",
)

SERVICE_PLATFORM_KEYS = {
    "spotify": "spotify",
    "tidal": "tidal",
    "deezer": "deezer",
    "amazon": "amazon",
    "apple_music": "appleMusic",
    "soundcloud": "soundcloud",
    "youtube": "youtube",
}

DIRECT_URL_KEYS = {
    "track": (
        "itunes_track_url",
        "deezer_track_url",
        "spotify_url",
        "tidal_url",
        "apple_music_url",
        "soundcloud_url",
        "youtube_url",
        "pandora_url",
    ),
    "album": (
        "itunes_collection_url",
        "deezer_album_url",
        "spotify_url",
        "tidal_url",
        "apple_music_url",
        "soundcloud_url",
        "youtube_url",
        "pandora_url",
    ),
}


def _first_value(*values: object) -> str:
    for value in values:
        if value not in ("", None):
            return str(value)
    return ""


def _candidate_urls(track: dict, kind: str = "track") -> list[str]:
    metadata = track.get("metadata") if isinstance(track.get("metadata"), dict) else {}
    candidates = []
    for key in DIRECT_URL_KEYS.get(kind, DIRECT_URL_KEYS["track"]):
        value = _first_value(track.get(key), metadata.get(key))
        if value:
            candidates.append(value)
    return candidates


_SERVICE_DOMAINS: dict[str, str] = {
    "spotify": "spotify.com",
    "tidal": "tidal.com",
    "deezer": "deezer.com",
    "amazon": "amazon.",
    "apple_music": "music.apple.com",
    "soundcloud": "soundcloud.com",
    "youtube": "youtube.com",
}


def _resolve_platform_url(candidate_url: str, service: str) -> str:
    platform = SERVICE_PLATFORM_KEYS.get(service, service)
    if not candidate_url:
        return ""
    try:
        api_url = "https://api.song.link/v1-alpha.1/links?" + urllib.parse.urlencode({
            "url": candidate_url,
            "userCountry": "US",
        })
        request = urllib.request.Request(api_url, headers={"User-Agent": "Streambox/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        links = data.get("linksByPlatform") or {}
        platform_info = links.get(platform) or {}
        resolved = platform_info.get("url") or platform_info.get("nativeAppUri") or ""

        if resolved:
            r_low = resolved.lower()
            if r_low.endswith("amazon.com") or r_low.endswith("amazon.com/") or \
               r_low.endswith("deezer.com") or r_low.endswith("tidal.com"):
                return ""
            return resolved
    except Exception:
        pass
    domain = _SERVICE_DOMAINS.get(service, "")
    if domain and domain in candidate_url:
        return candidate_url
    return ""


def _search_spotify_url(artist: str, title: str, album: str = "", kind: str = "track", isrc: str = "") -> str:
    try:
        from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
        client = SpotifyMetadataClient()
        
        queries = []
        if isrc and kind == "track":
            queries.append(f"isrc:{isrc}")
        
        queries.append(f"artist:{artist} album:{album}" if kind == "album" and album else (
            f"artist:{artist}" if kind == "album" else (
                f"artist:{artist} track:{title}" if title else f"artist:{artist} {album}"
            )
        ))

        for q in queries:
            if not hasattr(client, "_get"):
                data = client.search(q, limit=3)
                items = data.get("albums" if kind == "album" else "tracks", [])
                for item in items:
                    url = item.get("external_url", "") if isinstance(item, dict) else getattr(item, "external_url", "")
                    if url:
                        return url
                continue

            if kind == "album":
                data = client._get("search", params={"q": q, "type": "album", "limit": 3})
                items = data.get("albums", {}).get("items", [])
            else:
                data = client._get("search", params={"q": q, "type": "track", "limit": 3})
                items = data.get("tracks", {}).get("items", [])
            
            for item in items:
                url = (item.get("external_urls") or {}).get("spotify", "")
                if url:
                    return url
    except Exception:
        pass
    return ""


def resolve_download_url(track: dict, service: str = "tidal", kind: str = "track") -> str:
    spotify_url = _first_value(track.get("spotify_url"), (track.get("metadata") or {}).get("spotify_url"))
    if spotify_url and "spotify.com" in spotify_url:
        print(f"[Resolve] Using provided Spotify URL: {spotify_url}")
        return spotify_url
    spotify_id = _first_value(track.get("spotify_id"), (track.get("metadata") or {}).get("spotify_id"))
    if spotify_id:
        spotify_url = f"https://open.spotify.com/{'album' if kind == 'album' else 'track'}/{spotify_id}"
        print(f"[Resolve] Using provided Spotify ID: {spotify_url}")
        return spotify_url

    for candidate in _candidate_urls(track, kind):
        resolved = _resolve_platform_url(candidate, service)
        if resolved:
            print(f"[Resolve] Odesli resolved {candidate} -> {resolved}")
            return resolved

    artist = _first_value(track.get("artist"), (track.get("metadata") or {}).get("artist"))
    album = _first_value(track.get("album"), (track.get("metadata") or {}).get("album"))
    title = _first_value(track.get("title"), (track.get("metadata") or {}).get("title"))
    isrc = _first_value(track.get("isrc"), (track.get("metadata") or {}).get("isrc"))

    if artist and (title or album or isrc):
        res = _search_spotify_url(artist, title, album, kind, isrc)
        if res:
            print(f"[Resolve] Search resolved '{artist} - {title}' (ISRC: {isrc}) -> {res}")
            return res

    return ""


def _find_audio_files(root: Path, delete_invalid: bool = False) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
            if is_valid_audio_file(path):
                files.append(path)
            elif delete_invalid:
                try:
                    path.unlink()
                except Exception: pass
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files


def _parse_duration_ms(value: object) -> int:
    if value in ("", None):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds * 1000


def _audio_duration_ms(path: Path) -> int:
    try:
        from mutagen import File as MutagenFile  # type: ignore
        audio = MutagenFile(path)
        length = getattr(getattr(audio, "info", None), "length", 0)
        return int(float(length) * 1000) if length else 0
    except Exception:
        return 0


def downloaded_track_matches_request(path: Path, job: dict) -> tuple[bool, str]:
    """Valida se o arquivo baixado corresponde ao pedido, principalmente via duração."""
    meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    expected_ms = (
        _parse_duration_ms(meta.get("duration_ms"))
        or _parse_duration_ms(meta.get("length"))
        or _parse_duration_ms(meta.get("duration"))
    )
    if expected_ms <= 0:
        return True, ""

    actual_ms = _audio_duration_ms(path)
    if actual_ms <= 0:
        # Se não conseguirmos ler a duração (arquivo corrompido ou formato não suportado), 
        # confiamos no processo por enquanto, mas logamos.
        return True, ""

    diff_s = abs(expected_ms - actual_ms) / 1000
    # Tolerância de 15 segundos (comum para remasters, intros extras, etc.)
    if diff_s > 15:
        return False, f"Duration mismatch: expected {expected_ms/1000:.1f}s, got {actual_ms/1000:.1f}s (diff {diff_s:.1f}s)"

    return True, ""


def _estimated_total_bytes(job: dict, detected_ext: str = "") -> int:
    meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    duration_ms = (
        _parse_duration_ms(meta.get("duration_ms"))
        or _parse_duration_ms(meta.get("length"))
        or _parse_duration_ms(meta.get("duration"))
    )
    minutes = max(1.0, duration_ms / 60000) if duration_ms else 5.0

    ext = detected_ext.lower()
    for tmp in (".part", ".ytdl", ".tmp", ".temp", ".crdownload"):
        if ext.endswith(tmp):
            ext = ext[:-len(tmp)]
            if "." in ext:
                ext = ext[ext.rfind("."):]
            break

    quality = str(job.get("quality") or "").lower()
    url = str(job.get("resolved_url") or "").lower()
    is_youtube = "youtube.com" in url or "googlevideo.com" in url or "youtu.be" in url

    if ext in {".webm", ".opus", ".ogg"}:
        mb_per_min = 1.0 if is_youtube else 2.0
    elif ext in {".mp3"}:
        if "320" in quality: mb_per_min = 2.4
        elif "256" in quality: mb_per_min = 1.9
        elif "192" in quality: mb_per_min = 1.45
        else: mb_per_min = 1.2
    elif ext in {".m4a", ".aac"}:
        mb_per_min = 1.8
    elif ext in {".flac", ".alac", ".wav"}:
        mb_per_min = 6.5
    elif is_youtube:
        mb_per_min = 1.2
    elif any(token in quality for token in ("flac", "lossless", "27")):
        mb_per_min = 6.5
    elif "320" in quality:
        mb_per_min = 2.4
    elif "256" in quality:
        mb_per_min = 1.9
    elif "192" in quality:
        mb_per_min = 1.45
    elif "128" in quality:
        mb_per_min = 1.0
    else:
        mb_per_min = 3.0
    estimated = int(minutes * mb_per_min * 1024 * 1024)
    return max(estimated, 1)


def _downloaded_candidate_size(root: Path) -> int:
    if not root.exists():
        return 0
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_download_audio_candidate(path):
            candidates.append(path)
    if not candidates:
        return 0
    return max((path.stat().st_size for path in candidates), default=0)


def _norm(value: object) -> str:
    return clean_part(str(value or "")).casefold()


def _payload_metadata(payload: dict) -> dict:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
    return {**metadata, **track, **payload}


def _merge_nonempty_metadata(saved: dict, incoming: dict) -> dict:
    merged = dict(saved)
    for key, value in incoming.items():
        if value not in ("", None, [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def _audio_path_matches_track(path: Path, title: str, artist: str = "") -> bool:
    expected_stems = {_norm(title)}
    if artist:
        expected_stems.add(_norm(f"{clean_part(title)} - {clean_part(artist)}"))
    return _norm(path.stem) in expected_stems


def _track_identity_from_payload(payload: dict) -> dict:
    meta = _payload_metadata(payload)
    artist = meta.get("artist")
    album = meta.get("album")
    title = meta.get("title") or meta.get("name")
    return {
        "artist": _norm(artist),
        "album": _norm(album),
        "title": _norm(title),
        "title_part": clean_part(title or "Unknown Track"),
        "artist_part": clean_part(artist or "Unknown Artist"),
        "album_part": clean_part(album or "Unknown Album"),
        "library_path": str(meta.get("library_path") or ""),
        "isrc": str(meta.get("isrc") or "").strip().casefold(),
        "spotify_id": str(meta.get("spotify_id") or meta.get("id") or "").strip(),
        "musicbrainz_recording_id": str(meta.get("musicbrainz_recording_id") or meta.get("musicbrainz_track_id") or "").strip(),
    }


def _job_matches_identity(job: dict, identity: dict) -> bool:
    meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    if identity["isrc"] and str(job.get("isrc") or meta.get("isrc") or "").strip().casefold() == identity["isrc"]:
        return True
    if identity["spotify_id"] and str(job.get("spotify_id") or meta.get("spotify_id") or meta.get("id") or "").strip() == identity["spotify_id"]:
        return True
    if identity["musicbrainz_recording_id"]:
        mbid = str(meta.get("musicbrainz_recording_id") or meta.get("musicbrainz_track_id") or "").strip()
        if mbid == identity["musicbrainz_recording_id"]:
            return True
    return (
        _norm(job.get("artist") or meta.get("artist")) == identity["artist"]
        and _norm(job.get("title") or meta.get("title")) == identity["title"]
        and (not identity["album"] or _norm(job.get("album") or meta.get("album")) == identity["album"])
    )


_QUALITY_RANK = {
    ".flac": 700,
    ".alac": 690,
    ".wav": 650,
    ".m4a": 430,
    ".aac": 400,
    ".ogg": 390,
    ".opus": 380,
    ".mp3": 300,
}


def _quality_rank(path: Path, quality: object = "") -> int:
    rank = _QUALITY_RANK.get(path.suffix.lower(), 0)
    text = str(quality or "").casefold()
    if "lossless" in text or "flac" in text:
        rank = max(rank, 700)
    elif "320" in text:
        rank = max(rank, 320)
    elif "256" in text:
        rank = max(rank, 256)
    elif "192" in text:
        rank = max(rank, 192)
    elif "128" in text:
        rank = max(rank, 128)
    return rank


ROOT = Path(__file__).resolve().parent
JOBS_PATH = jobs_path()


class ServiceDownloadManager:
    def __init__(self, config):
        self.config = config
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._cancel_flags: set[str] = set()
        self._progress_thread_running = False
        self._cache_events: list[dict] = []
        self._cache_file_sizes: dict[tuple[str, str], int] = {}
        self._load_jobs()

    def _ensure_progress_thread(self) -> None:
        if self._progress_thread_running:
            return
        self._progress_thread_running = True
        def _loop():
            while True:
                with self._lock:
                    has_running = any(j.get("status") == "running" for j in self.jobs.values())
                if not has_running:
                    self._progress_thread_running = False
                    return
                self._sync_progress()
                time.sleep(1)
        threading.Thread(target=_loop, daemon=True, name="progress-sync").start()

    def update_config(self, config) -> None:
        with self._lock:
            self.config = config

    def cache_log_snapshot(self, limit: int = 80) -> dict:
        with self._lock:
            events = list(self._cache_events[-max(1, min(limit, 200)):])
            cache_dir = str(self.config.cache_dir)
        return {"cache_dir": cache_dir, "events": events}

    def clear_cache(self) -> dict:
        cache_dir = Path(self.config.cache_dir)
        with self._lock:
            stream_job_ids = {
                job_id
                for job_id, job in self.jobs.items()
                if job.get("mode", "stream") == "stream"
            }
            active_ids = {
                job_id
                for job_id in stream_job_ids
                if self.jobs[job_id].get("status") in ("starting", "running")
            }
            self._cancel_flags.update(active_ids)
            for job_id in stream_job_ids:
                self.jobs.pop(job_id, None)
            self._cache_events.clear()
            self._cache_file_sizes.clear()

        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._save_jobs()
        return {
            "ok": True,
            "cache_dir": str(cache_dir),
            "removed_jobs": len(stream_job_ids),
            "cancelled_jobs": len(active_ids),
        }

    def _append_cache_event(self, job: dict, kind: str, message: str) -> None:
        if job.get("prefetch"):
            message = f"Prefetch: {message}"
        event = {
            "timestamp": time.time(),
            "job_id": job.get("id", ""),
            "title": job.get("title", ""),
            "kind": kind,
            "message": message,
        }
        with self._lock:
            self._cache_events.append(event)
            if len(self._cache_events) > 200:
                del self._cache_events[:-200]

    @staticmethod
    def _cache_size_text(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    def _capture_cache_activity(self, job: dict) -> None:
        if job.get("mode", "stream") != "stream" or not job.get("output_dir"):
            return
        root = Path(job["output_dir"])
        try:
            files = sorted(path for path in root.rglob("*") if path.is_file())
        except Exception:
            return

        seen: set[str] = set()
        changes: list[tuple[str, str]] = []
        with self._lock:
            for path in files:
                path_text = str(path)
                seen.add(path_text)
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                key = (job["id"], path_text)
                previous = self._cache_file_sizes.get(key)
                self._cache_file_sizes[key] = size
                relative = str(path.relative_to(root))
                if previous is None:
                    changes.append(("created", f"Created {relative} ({self._cache_size_text(size)})"))
                elif previous != size:
                    changes.append(("updated", f"Updated {relative} ({self._cache_size_text(size)})"))

            tracked = [
                key for key in self._cache_file_sizes
                if key[0] == job["id"] and key[1] not in seen
            ]
            for key in tracked:
                relative = str(Path(key[1]).relative_to(root))
                del self._cache_file_sizes[key]
                changes.append(("removed", f"Removed {relative}"))

        for kind, message in changes:
            self._append_cache_event(job, kind, message)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") not in ("starting", "running"):
                return False
            self._cancel_flags.add(job_id)
            job["status"] = "error"
            job["error"] = "Cancelled by user"
            job["library_requested"] = False

            output_dir = job.get("output_dir")
            if output_dir:
                try:
                    p = Path(output_dir)
                    if p.exists():
                        shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass

        self._append_cache_event(job, "cancelled", "Cache download cancelled and partial files removed")
        self._save_jobs()
        return True

    def _load_jobs(self) -> None:
        if JOBS_PATH.exists():
            try:
                with JOBS_PATH.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    for job in data:
                        if isinstance(job, dict) and "id" in job:
                            if job.get("status") in ("starting", "running"):
                                job["status"] = "error"
                                job["error"] = "Interrupted by server restart"
                                job["library_requested"] = False
                            self.jobs[job["id"]] = job
            except Exception:
                pass

    def _save_jobs(self) -> None:
        JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = list(self.jobs.values())
        try:
            with JOBS_PATH.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def promote_to_library(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
        if not job or job.get("status") != "finished":
            return None

        if job.get("mode") == "download":
            return self._public_job(job)

        old_path = Path(job["library_path"])
        if not old_path.exists():
            return None

        new_job_id = str(uuid.uuid4())
        new_job = {
            **job,
            "id": new_job_id,
            "mode": "download",
            "created_at": time.time(),
        }

        new_dir = self._output_dir(new_job)
        new_dir.mkdir(parents=True, exist_ok=True)
        new_file_path = new_dir / old_path.name

        try:
            old_dir = old_path.parent
            for item in old_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, new_dir / item.name)

            new_job["library_path"] = str(new_file_path)
            new_job["output_dir"] = str(new_dir)

            with self._lock:
                self.jobs[new_job_id] = new_job
            self._save_jobs()
            return self._public_job(new_job)
        except Exception:
            return None

    def _library_file_index(self) -> dict[str, list[Path]]:
        indexed: dict[str, list[Path]] = {}
        for path in _find_audio_files(self.config.music_dir):
            try:
                relative = path.relative_to(self.config.music_dir)
            except ValueError:
                continue
            artist = relative.parts[0] if len(relative.parts) > 1 else "Unknown Artist"
            indexed.setdefault(_norm(artist), []).append(path)
        return indexed

    def library_status_batch(self, payloads: list) -> list:
        library_files = self._library_file_index()
        return [self.library_status(payload, library_files) for payload in payloads]

    def library_status(self, payload: dict, library_files: dict[str, list[Path]] | None = None) -> dict:
        identity = _track_identity_from_payload(payload)
        library = self._find_library_entry(identity, library_files)
        cache = self._find_cache_entry(identity)
        active = self._find_active_library_job(identity)
        if active:
            self._refresh_job_file_progress(active.get("id", ""))
            active = self._find_active_library_job(identity)
        return {
            "in_library": bool(library),
            "library_path": str(library["path"]) if library else "",
            "library_quality": library["quality"] if library else 0,
            "cached": bool(cache),
            "cache_path": str(cache["path"]) if cache else "",
            "cache_quality": cache["quality"] if cache else 0,
            "active_job_id": active.get("id", "") if active else "",
            "active_job_status": active.get("status", "") if active else "",
            "library_requested": bool(active.get("library_requested") or active.get("mode") == "download") if active else False,
            "progress": active.get("progress", 0) if active else 0,
            "last_status": active.get("last_status", "") if active else "",
        }

    def _refresh_job_file_progress(self, job_id: str) -> None:
        if not job_id:
            return
        with self._lock:
            job = self.jobs.get(job_id)
        if not job:
            return
        if self._sync_progress_from_files(job):
            self._save_jobs()

    def playback_source(self, payload: dict) -> dict:
        status = self.library_status(payload)
        library_path = Path(status["library_path"]) if status["library_path"] else None
        cache_path = Path(status["cache_path"]) if status["cache_path"] else None
        if library_path and cache_path:
            if status["cache_quality"] > status["library_quality"]:
                return {"source": "cache", "path": str(cache_path), **status}
            return {"source": "library", "path": str(library_path), **status}
        if library_path:
            return {"source": "library", "path": str(library_path), **status}
        if cache_path:
            return {"source": "cache", "path": str(cache_path), **status}
        return {"source": "", "path": "", **status}

    def toggle_library(self, payload: dict) -> dict:
        identity = _track_identity_from_payload(payload)
        library = self._find_library_entry(identity)
        if library:
            self._delete_library_entry(library["path"])
            return {"ok": True, "action": "deleted", **self.library_status(payload)}

        cache = self._find_cache_entry(identity)
        if cache:
            job = cache.get("job") or self._job_from_payload(payload, mode="download")
            if cache.get("job"):
                with self._lock:
                    self._merge_payload_into_job(job, payload)
                self._save_jobs()
            result = self._copy_job_audio_to_library(job, cache["path"])
            return {"ok": True, "action": "copied", **result, **self.library_status(payload)}

        active = self._find_active_cache_job(identity)
        if active:
            with self._lock:
                job = self.jobs.get(active["id"])
                if job:
                    self._merge_payload_into_job(job, payload)
                    job["library_requested"] = True
                    job["library_request_payload"] = payload
            self._save_jobs()
            return {"ok": True, "action": "queued", **self.library_status(payload)}

        new_payload = {**payload, "mode": "download"}
        job = self.start_job(new_payload)
        return {"ok": True, "action": "started", "job": job, **self.library_status(payload)}

    def _merge_payload_into_job(self, job: dict, payload: dict) -> None:
        incoming = _payload_metadata(payload)
        job["metadata"] = _merge_nonempty_metadata(job.get("metadata") or {}, incoming)
        for key in IDENTIFIER_FIELDS:
            if incoming.get(key):
                job[key] = incoming[key]
        for key in ("artwork_url",):
            if incoming.get(key):
                job[key] = incoming[key]

    def _job_from_payload(self, payload: dict, mode: str = "download") -> dict:
        meta = _payload_metadata(payload)
        return {
            "id": str(uuid.uuid4()),
            "artist": clean_part(meta.get("artist") or "Unknown Artist"),
            "album": clean_part(meta.get("album") or "Unknown Album"),
            "title": clean_part(meta.get("title") or meta.get("name") or "Unknown Track"),
            "artwork_url": meta.get("artwork_url") or "",
            "kind": "track",
            "mode": mode,
            "isrc": meta.get("isrc") or "",
            "metadata": meta,
            "service": (payload.get("service") or getattr(self.config, "download_service", "tidal") or "tidal").lower(),
            "engine": (payload.get("engine") or getattr(self.config, "download_engine", "spotiflac") or "spotiflac").lower(),
            "quality": payload.get("quality") or getattr(self.config, "default_quality", "flac") or "flac",
            "status": "finished",
            "progress": 100,
            "created_at": time.time(),
            "error": "",
            "resolved_url": "",
            "output_dir": "",
            "library_path": "",
        }

    def _find_library_entry(self, identity: dict, library_files: dict[str, list[Path]] | None = None) -> dict | None:
        with self._lock:
            jobs = list(self.jobs.values())
        exact_matches = []
        fallback_matches = []
        explicit_path = Path(identity.get("library_path") or "")
        if explicit_path.exists() and explicit_path.is_file() and is_valid_audio_file(explicit_path):
            exact_matches.append({"path": explicit_path, "job": None, "quality": _quality_rank(explicit_path)})

        for job in jobs:
            path_text = job.get("library_path") or ""
            if job.get("status") == "finished" and job.get("mode") == "download" and path_text:
                path = Path(path_text)
                if path.exists() and is_valid_audio_file(path) and _job_matches_identity(job, identity):
                    exact_matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})
                elif path.exists() and is_valid_audio_file(path) and _norm(job.get("artist")) == identity["artist"] and _norm(job.get("title")) == identity["title"]:
                    fallback_matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})

        album_dir = self.config.music_dir / identity["artist_part"] / identity["album_part"]
        if library_files is None:
            album_paths = _find_audio_files(album_dir) if album_dir.exists() else []
            artist_dir = self.config.music_dir / identity["artist_part"]
            artist_paths = _find_audio_files(artist_dir) if artist_dir.exists() else []
        else:
            artist_paths = library_files.get(identity["artist"], [])
            album_paths = [path for path in artist_paths if path.parent == album_dir]
        for path in album_paths:
            if _audio_path_matches_track(path, identity["title_part"], identity["artist_part"]):
                exact_matches.append({"path": path, "job": None, "quality": _quality_rank(path)})
        for path in artist_paths:
            if _audio_path_matches_track(path, identity["title_part"], identity["artist_part"]):
                fallback_matches.append({"path": path, "job": None, "quality": _quality_rank(path)})

        matches = exact_matches or fallback_matches
        if not matches:
            return None
        matches.sort(key=lambda item: (item["quality"], item["path"].stat().st_mtime), reverse=True)
        return matches[0]

    def _find_cache_entry(self, identity: dict) -> dict | None:
        changed = False
        with self._lock:
            jobs = list(self.jobs.values())
        matches = []
        for job in jobs:
            if self._repair_finished_audio_path(job):
                changed = True
            path_text = job.get("library_path") or ""
            if job.get("status") == "finished" and job.get("mode", "stream") == "stream" and path_text:
                path = Path(path_text)
                matches_audio, _ = downloaded_track_matches_request(path, job) if path.exists() else (False, "")
                if path.exists() and is_valid_audio_file(path) and matches_audio and _job_matches_identity(job, identity):
                    normalized = self._normalize_downloaded_audio(path, job)
                    if normalized != path:
                        with self._lock:
                            job["library_path"] = str(normalized)
                        path = normalized
                        changed = True
                    matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})
        if changed:
            self._save_jobs()
        if not matches:
            return None
        matches.sort(key=lambda item: (item["quality"], item["path"].stat().st_mtime), reverse=True)
        return matches[0]

    def _repair_finished_audio_path(self, job: dict) -> bool:
        if job.get("status") != "finished" or not job.get("output_dir"):
            return False
        current = Path(job.get("library_path") or "")
        if current.exists() and is_valid_audio_file(current):
            return False
        for candidate in _find_audio_files(Path(job["output_dir"])):
            matches, _ = downloaded_track_matches_request(candidate, job)
            if not matches:
                continue
            repaired = self._normalize_downloaded_audio(candidate, job)
            with self._lock:
                job["library_path"] = str(repaired)
            return True
        return False

    def _find_active_cache_job(self, identity: dict) -> dict | None:
        with self._lock:
            jobs = list(self.jobs.values())
        for job in sorted(jobs, key=lambda item: item.get("created_at", 0), reverse=True):
            if job.get("status") in ("starting", "running") and job.get("mode", "stream") == "stream" and _job_matches_identity(job, identity):
                return self._public_job(job)
        return None

    def _find_active_library_job(self, identity: dict) -> dict | None:
        with self._lock:
            jobs = list(self.jobs.values())
        for job in sorted(jobs, key=lambda item: item.get("created_at", 0), reverse=True):
            if job.get("status") not in ("starting", "running") or not _job_matches_identity(job, identity):
                continue
            if job.get("mode") == "download" or job.get("library_requested"):
                return self._public_job(job)
        return None

    def _copy_job_audio_to_library(self, job: dict, source_path: Path | None = None) -> dict:
        if not source_path:
            source_path = Path(job.get("library_path") or "")
        if not source_path or not source_path.exists():
            raise RuntimeError("Cached audio file was not found")

        dest_dir = self.config.music_dir / clean_part(job.get("artist") or "Unknown Artist") / clean_part(job.get("album") or "Unknown Album")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / source_path.name
        if source_path.resolve() != dest_path.resolve():
            shutil.copy2(source_path, dest_path)

        for sidecar_name in ("cover.png", "cover.jpg", "cover.jpeg"):
            sidecar = source_path.parent / sidecar_name
            if sidecar.exists() and not (dest_dir / sidecar.name).exists():
                shutil.copy2(sidecar, dest_dir / sidecar.name)

        self._save_sidecar_files(dest_dir, {**job, "mode": "download"})
        with self._lock:
            existing = next((item for item in self.jobs.values() if item.get("mode") == "download" and _job_matches_identity(item, _track_identity_from_payload(job))), None)
            if existing:
                existing.update({**job, "mode": "download", "status": "finished", "progress": 100, "library_path": str(dest_path), "output_dir": str(dest_dir)})
                public = existing
            else:
                library_job = {**job, "id": str(uuid.uuid4()), "mode": "download", "status": "finished", "progress": 100, "library_path": str(dest_path), "output_dir": str(dest_dir), "created_at": time.time()}
                self.jobs[library_job["id"]] = library_job
                public = library_job
        self._save_jobs()
        return {"library_path": str(dest_path), "job": self._public_job(public)}

    def _sync_existing_library_sidecar(self, job: dict) -> None:
        album_dir = self.config.music_dir / clean_part(job.get("artist") or "Unknown Artist") / clean_part(job.get("album") or "Unknown Album")
        if not album_dir.exists():
            return
        if not any(_audio_path_matches_track(path, job.get("title") or "", job.get("artist") or "") for path in _find_audio_files(album_dir)):
            return
        self._save_sidecar_files(album_dir, job)

    def _normalize_downloaded_audio(self, path: Path, job: dict) -> Path:
        title = clean_part(job.get("title") or "Unknown Track")
        artist = clean_part(job.get("artist") or "Unknown Artist")
        target = path.with_name(f"{title} - {artist}{path.suffix.lower()}")
        if path != target:
            try:
                if target.exists():
                    target.unlink()
                path.rename(target)
                path = target
            except OSError:
                pass

        try:
            from mutagen import File as MutagenFile  # type: ignore
            audio = MutagenFile(path, easy=True)
            if audio is not None:
                audio["title"] = [job.get("title") or title]
                audio["artist"] = [job.get("artist") or artist]
                audio["albumartist"] = [job.get("artist") or artist]
                if job.get("album"):
                    audio["album"] = [job["album"]]
                audio.save()
        except Exception:
            pass
        return path

    def _delete_library_entry(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

        album_dir = path.parent
        info_path = album_dir / "metadata.json"
        if info_path.exists():
            try:
                data = json.loads(info_path.read_text("utf-8"))
                tracks = data.get("tracks") if isinstance(data, dict) else None
                if isinstance(tracks, dict):
                    album_artist = (data.get("album_info") or {}).get("artist", "")
                    for key in list(tracks.keys()):
                        track_artist = (tracks.get(key) or {}).get("artist") or album_artist
                        if _audio_path_matches_track(path, key, track_artist):
                            tracks.pop(key, None)
                    info_path.write_text(json.dumps(data, indent=2), "utf-8")
            except Exception:
                pass

        with self._lock:
            for job in self.jobs.values():
                if job.get("mode") == "download" and job.get("library_path") == str(path):
                    job["status"] = "deleted"
                    job["library_path"] = ""
        self._save_jobs()

    def update_job_metadata(self, job_id: str, metadata: dict, artwork_url: str) -> None:
        updated_job = None
        with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job["metadata"] = {**(job.get("metadata") or {}), **metadata}
                for key in IDENTIFIER_FIELDS:
                    if metadata.get(key):
                        job[key] = metadata[key]
                if artwork_url:
                    job["artwork_url"] = artwork_url
                updated_job = dict(job)
        self._save_jobs()
        if updated_job and updated_job.get("status") == "finished":
            output_dir = Path(updated_job.get("output_dir") or "")
            if output_dir.exists():
                self._save_sidecar_files(output_dir, updated_job)
            self._sync_existing_library_sidecar(updated_job)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            items = list(self.jobs.values())
        changed = False
        for job in items:
            if self._repair_finished_audio_path(job):
                changed = True
        if changed:
            self._save_jobs()
        items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return [self._public_job(job) for job in items]

    def _sync_progress(self) -> None:
        updated = False
        try:
            from SpotiFLAC.core.progress import DownloadManager
            stats = DownloadManager().get_stats()
            queue = stats.get("queue", [])
            with self._lock:
                for item in queue:
                    s_id = item.get("id") or item.get("spotify_id")
                    i_title = item.get("track_name")
                    i_artist = item.get("artist_name")
                    if not s_id and not i_title: continue

                    for job in self.jobs.values():
                        if job.get("status") != "running": continue

                        matched = False
                        meta = job.get("metadata") or {}

                        if s_id and (job.get("isrc") == s_id or job.get("id") == s_id or meta.get("id") == s_id or meta.get("spotify_id") == s_id):
                            matched = True
                        if not matched and i_title and i_artist:
                            if clean_part(i_title).lower() == clean_part(job.get("title", "")).lower() and \
                               clean_part(i_artist).lower() == clean_part(job.get("artist", "")).lower():
                                matched = True
                        if not matched and s_id and "open.spotify.com/track/" in job.get("resolved_url", ""):
                            u_id = job["resolved_url"].split("/track/")[1].split("?")[0].split("/")[0]
                            if u_id == s_id: matched = True

                        if matched:
                            prog_mb = float(item.get("progress") or 0)
                            total_mb = float(item.get("total_size") or 0)

                            if total_mb > 0.1:
                                progress = min(95.0, (prog_mb / total_mb) * 100.0)
                            else:
                                dur = (
                                    _parse_duration_ms(meta.get("duration_ms"))
                                    or _parse_duration_ms(meta.get("length"))
                                    or _parse_duration_ms(meta.get("duration"))
                                )
                                if dur > 0:
                                    factor = 9.5 if any(k in job.get("quality", "").lower() for k in ["flac", "lossless", "27"]) else 2.2
                                    est = (dur / 60000) * factor
                                    progress = min(95.0, (prog_mb / max(0.1, est)) * 100.0)
                                else:
                                    progress = min(95.0, prog_mb * 4.0)

                            if progress > float(job.get("progress") or 0):
                                job["progress"] = progress
                                updated = True

                            if job["progress"] > 0:
                                print(f"[Progress] {job.get('title')} -> {job['progress']:.1f}%")
        except Exception:
            pass

        with self._lock:
            running_jobs = [job for job in self.jobs.values() if job.get("status") == "running"]

        for job in running_jobs:
            self._capture_cache_activity(job)
            if self._sync_progress_from_files(job):
                updated = True

        if updated:
            self._save_jobs()

    def _sync_progress_from_files(self, job: dict) -> bool:
        output_dir = job.get("output_dir")
        if not output_dir:
            return False
        root = Path(output_dir)
        try:
            candidates = [p for p in root.rglob("*") if p.is_file() and is_download_audio_candidate(p)]
            if not candidates:
                return False
            biggest = max(candidates, key=lambda p: p.stat().st_size)
            downloaded_bytes = biggest.stat().st_size
            detected_ext = biggest.suffix.lower()
        except Exception:
            return False
        if downloaded_bytes <= 0:
            return False

        total_bytes = max(int(job.get("estimated_total_bytes") or 0), _estimated_total_bytes(job, detected_ext))
        if downloaded_bytes >= total_bytes:
            total_bytes = int(downloaded_bytes * 1.1)
        progress = min(95.0, (downloaded_bytes / total_bytes) * 100.0)
        if progress <= 0:
            return False

        # Watchdog: If bytes haven't changed for 5 minutes, it's probably a dead socket
        now = time.time()
        prev_bytes = int(job.get("_last_active_bytes") or 0)
        last_time = float(job.get("_last_active_time") or now)

        if downloaded_bytes > prev_bytes:
            job["_last_active_bytes"] = downloaded_bytes
            job["_last_active_time"] = now
        elif now - last_time > 300: # 5 minutes of zero progress
            with self._lock:
                if job.get("status") == "running":
                    job["status"] = "error"
                    job["error"] = "Download timed out (no progress for 5 minutes). Check your connection."
            return True

        with self._lock:
            current = float(job.get("progress") or 0)
            if progress <= current and current < 95:
                return False
            job["progress"] = progress
            job["downloaded_bytes"] = downloaded_bytes
            job["estimated_total_bytes"] = total_bytes
            print(f"[Progress] {job.get('title')} (file) -> {job['progress']:.1f}% ({downloaded_bytes}/{total_bytes} bytes)")
        return True

    def start_job(self, payload: dict) -> dict:
        with self._start_lock:
            if payload.get("mode", "stream") == "stream":
                identity = _track_identity_from_payload(payload)
                cache = self._find_cache_entry(identity)
                if cache and cache.get("job"):
                    return self._public_job(cache["job"])
                active = self._find_active_cache_job(identity)
                if active:
                    return active
            return self._create_job(payload)

    def _create_job(self, payload: dict) -> dict:
        job_id = str(uuid.uuid4())
        isrc = (
            payload.get("isrc")
            or (payload.get("track") or {}).get("isrc")
            or (payload.get("metadata") or {}).get("isrc")
            or ""
        )
        metadata = payload.get("metadata") or payload.get("track") or {}
        track_key = f"{(payload.get('artist') or metadata.get('artist') or '').lower()}||{(payload.get('title') or metadata.get('title') or '').lower()}"

        job = {
            "id": job_id,
            "track_key": track_key,
            "artist": clean_part(payload.get("artist") or metadata.get("artist") or "Unknown Artist"),
            "album": clean_part(payload.get("album") or metadata.get("album") or "Unknown Album"),
            "title": clean_part(payload.get("title") or metadata.get("title") or "Unknown Track"),
            "artwork_url": payload.get("artwork_url") or metadata.get("artwork_url") or "",
            "kind": payload.get("kind", "track"),
            "mode": payload.get("mode", "stream"),
            "prefetch": bool(payload.get("prefetch")),
            "isrc": isrc,
            "metadata": metadata,
            "service": (payload.get("service") or getattr(self.config, "download_service", "tidal") or "tidal").lower(),
            "engine": (payload.get("engine") or getattr(self.config, "download_engine", "spotiflac") or "spotiflac").lower(),
            "quality": payload.get("quality") or getattr(self.config, "default_quality", "flac") or "flac",
            "status": "starting",
            "last_status": "Starting...",
            "progress": 0,
            "created_at": time.time(),
            "error": "",
            "resolved_url": "",
            "output_dir": "",
            "library_path": "",
        }
        for key in IDENTIFIER_FIELDS:
            value = payload.get(key) or metadata.get(key)
            if value:
                job[key] = value
        with self._lock:
            self.jobs[job_id] = job
        threading.Thread(target=self._worker, args=(job_id, payload), daemon=True).start()
        return self._public_job(job)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
        if job and self._repair_finished_audio_path(job):
            self._save_jobs()
        return self._public_job(job) if job else None

    def update_job_identifiers(self, job_id: str, enriched_payload: dict) -> None:
        enriched = enriched_payload.get("track") or enriched_payload.get("metadata") or {}
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") in ("finished", "error"):
                return
            for key in IDENTIFIER_FIELDS:
                if enriched.get(key) and not job.get(key):
                    job[key] = enriched[key]
            meta = job.get("metadata")
            if isinstance(meta, dict):
                for key in IDENTIFIER_FIELDS:
                    if enriched.get(key) and not meta.get(key):
                        meta[key] = enriched[key]

    def _worker(self, job_id: str, payload: dict) -> None:
        with self._lock:
            job = self.jobs.get(job_id)
        if not job:
            return

        try:
            track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            merged = {**metadata, **track}
            kind = payload.get("kind", job.get("kind", "track"))

            output_dir = self._output_dir(job)
            if output_dir.exists():
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                except Exception:
                    pass
            output_dir.mkdir(parents=True, exist_ok=True)

            engine = job.get("engine", "spotiflac")

            if engine == "monochrome":
                with self._lock:
                    job["status"] = "running"
                    job["output_dir"] = str(output_dir)
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "watching", f"Watching cache folder for {job['title']}")
                self._ensure_progress_thread()
                import backend_monochrome
                backend_monochrome.run(output_dir, job, self)

            elif engine == "musicdl":
                with self._lock:
                    job["status"] = "running"
                    job["output_dir"] = str(output_dir)
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "watching", f"Watching cache folder for {job['title']}")
                self._ensure_progress_thread()
                import backend_musicdl
                backend_musicdl.run(output_dir, job, self)

            elif engine == "qobuz-dlp":
                with self._lock:
                    job["status"] = "running"
                    job["output_dir"] = str(output_dir)
                self._ensure_progress_thread()
                import backend_qobuz_dlp
                backend_qobuz_dlp.run(output_dir, job, self)

            elif engine == "torrent":
                with self._lock:
                    job["status"] = "running"
                    job["output_dir"] = str(output_dir)
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "watching", f"Watching cache folder for {job['title']}")
                self._ensure_progress_thread()
                import backend_torrent
                backend_torrent.run(output_dir, job, self)

            elif engine == "tidal_hifi":
                # Use the specific service selected in the UI (amazon, apple, etc.)
                svc = job.get("service") or self.config.download_service or "tidal"
                
                # Priority 1: Try specific service (Amazon, etc.)
                resolved_url = resolve_download_url(merged, service=svc, kind=kind)
                
                # Priority 2: Fallback to searching for the Spotify URL (The engines handle Spotify -> Service resolution best)
                if not resolved_url:
                    print(f"[Engine] {svc} resolution failed, falling back to Spotify metadata...")
                    resolved_url = resolve_download_url(merged, service="spotify", kind=kind)
                
                if not resolved_url:
                    raise RuntimeError(f"Could not resolve a {svc} or Spotify URL for this track")
                
                with self._lock:
                    job["status"] = "running"
                    job["resolved_url"] = resolved_url
                    job["output_dir"] = str(output_dir)
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "watching", f"Watching cache folder for {job['title']}")
                self._ensure_progress_thread()
                import backend_other
                backend_other.run(resolved_url, output_dir, job, self)

            else:  # spotiflac (default)
                resolved_url = resolve_download_url(merged, service="spotify", kind=kind)
                if not resolved_url:
                    raise RuntimeError("Could not resolve a Spotify URL from the selected track metadata")
                with self._lock:
                    job["status"] = "running"
                    job["resolved_url"] = resolved_url
                    job["output_dir"] = str(output_dir)
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "watching", f"Watching cache folder for {job['title']}")
                self._ensure_progress_thread()
                import backend_spotiflac
                backend_spotiflac.run(resolved_url, output_dir, job, self)

            self._save_sidecar_files(output_dir, job)
            self._capture_cache_activity(job)

            with self._lock:
                already_finished = job.get("status") == "finished" and bool(job.get("library_path"))
                library_requested = bool(job.get("library_requested"))

            if already_finished:
                audio_path = Path(job["library_path"])
            else:
                audio_files = _find_audio_files(output_dir)
                if not audio_files:
                    raise RuntimeError("Download finished but no playable audio file was found")
                matches, message = downloaded_track_matches_request(audio_files[0], job)
                if not matches:
                    raise RuntimeError(message)
                audio_path = self._normalize_downloaded_audio(audio_files[0], job)
                with self._lock:
                    job["library_path"] = str(audio_path)
                    job["progress"] = 100
                    job["status"] = "finished"
                    job["error"] = ""
                if job.get("mode", "stream") == "stream":
                    self._append_cache_event(job, "finished", f"Ready to play {audio_path.name}")

            self._save_jobs()
            self._sync_existing_library_sidecar(job)
            if library_requested and job.get("mode", "stream") == "stream":
                try:
                    self._copy_job_audio_to_library(job, audio_path)
                except Exception as exc:
                    with self._lock:
                        job["library_promote_error"] = str(exc)
                    self._save_jobs()
        except Exception as exc:
            with self._lock:
                job["status"] = "error"
                job["error"] = str(exc)
            if job.get("mode", "stream") == "stream":
                self._append_cache_event(job, "error", f"Cache job failed: {exc}")
            self._save_jobs()

    def _save_sidecar_files(self, directory: Path, job: dict) -> None:
        try:
            info_path = directory / "metadata.json"
            current_meta = dict(job.get("metadata") or {})
            for key in ("title", "artist", "album", "artwork_url", *IDENTIFIER_FIELDS):
                value = job.get(key)
                if value and not current_meta.get(key):
                    current_meta[key] = value
            track_title = job.get("title") or "Unknown"

            data = {"album_info": {}, "tracks": {}}
            if info_path.exists():
                try:
                    loaded = json.loads(info_path.read_text("utf-8"))
                    if isinstance(loaded, dict):
                        if "album_info" in loaded:
                            data = loaded
                        else:
                            data["album_info"] = loaded
                except Exception: pass

            for key in ["artist", "album", "year", "artwork_url", "genre"]:
                val = current_meta.get(key) or job.get(key)
                if val and (not data["album_info"].get(key) or key == "artwork_url"):
                    data["album_info"][key] = val

            saved_track = data["tracks"].get(track_title) if isinstance(data["tracks"].get(track_title), dict) else {}
            data["tracks"][track_title] = _merge_nonempty_metadata(saved_track, current_meta)
            info_path.write_text(json.dumps(data, indent=2), "utf-8")

            cover_path = directory / "cover.png"
            if not cover_path.exists():
                art_url = job.get("artwork_url")
                if art_url:
                    if art_url.startswith("/api/image?url="):
                        from urllib.parse import unquote
                        art_url = unquote(art_url.split("url=")[1])
                    if not art_url.startswith(("http://", "https://")):
                        art_url = None
                    if art_url:
                        req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            directory.mkdir(parents=True, exist_ok=True)
                            cover_path.write_bytes(resp.read())
        except Exception as e:
            logging.getLogger("service_downloader").warning(f"Failed to save sidecar files: {e}")

    def _output_dir(self, job: dict) -> Path:
        if job.get("mode", "stream") == "download":
            artist = clean_part(job.get("artist") or "Unknown Artist")
            album = clean_part(job.get("album") or job.get("title") or "Unknown Album")
            return self.config.music_dir / artist / album

        return self.config.cache_dir / clean_part(job["id"])

    def _public_job(self, job: dict | None) -> dict:
        if not job:
            return {}
        return {key: value for key, value in job.items()}
