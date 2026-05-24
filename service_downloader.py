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

# SpotiFLAC's DownloadManager is a process-wide singleton that calls reset()
# at the start of every run(), wiping progress for any concurrent download.
# Serialize all SpotiFLAC() calls so they never overlap.
_spotiflac_lock = threading.Lock()

def clean_part(value: str) -> str:
    cleaned = "".join(char for char in value if char not in '/\\:*?"<>|').strip()
    return cleaned or "Unknown"


def is_valid_audio_file(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        header = path.read_bytes()[:64]
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

# Maps our service names to SpotiFLAC's PROVIDER_REGISTRY keys.
_SPOTIFLAC_SERVICE_MAP: dict[str, str] = {
    "apple_music": "apple",
}

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
            return resolved
    except Exception:
        pass
    # Only fall back to the raw candidate if it already belongs to the target service.
    domain = _SERVICE_DOMAINS.get(service, "")
    if domain and domain in candidate_url:
        return candidate_url
    return ""


def _search_spotify_url(artist: str, title: str, album: str = "", kind: str = "track") -> str:
    try:
        from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
        client = SpotifyMetadataClient()
        if kind == "album":
            q = f"artist:{artist} album:{album}" if album else f"artist:{artist}"
            data = client._get("search", params={"q": q, "type": "album", "limit": 3})
            items = data.get("albums", {}).get("items", [])
        else:
            q = f"artist:{artist} track:{title}" if title else f"artist:{artist} {album}"
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
    for candidate in _candidate_urls(track, kind):
        resolved = _resolve_platform_url(candidate, service)
        if resolved:
            return resolved

    artist = _first_value(track.get("artist"), (track.get("metadata") or {}).get("artist"))
    album = _first_value(track.get("album"), (track.get("metadata") or {}).get("album"))
    title = _first_value(track.get("title"), (track.get("metadata") or {}).get("title"))

    # Last resort: search Spotify directly using SpotiFLAC's own client credentials.
    if artist and (title or album):
        return _search_spotify_url(artist, title, album, kind)

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


def _estimated_total_bytes(job: dict, detected_ext: str = "") -> int:
    meta = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    duration_ms = (
        _parse_duration_ms(meta.get("duration_ms"))
        or _parse_duration_ms(meta.get("length"))
        or _parse_duration_ms(meta.get("duration"))
    )
    minutes = max(1.0, duration_ms / 60000) if duration_ms else 5.0
    
    ext = detected_ext.lower()
    # Strip temporary/downloader extensions
    for tmp in (".part", ".ytdl", ".tmp", ".temp", ".crdownload"):
        if ext.endswith(tmp):
            ext = ext[:-len(tmp)]
            if "." in ext:
                ext = ext[ext.rfind("."):]
            break
            
    quality = str(job.get("quality") or "").lower()
    url = str(job.get("resolved_url") or "").lower()
    is_youtube = "youtube.com" in url or "googlevideo.com" in url or "youtu.be" in url

    # Use the actual on-disk format when known — quality setting may not match
    # the fallback provider (e.g. quality=LOSSLESS but YouTube delivers .webm)
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
        mb_per_min = 12.0
    elif is_youtube:
        # YouTube is never lossless
        mb_per_min = 1.2
    elif any(token in quality for token in ("flac", "lossless", "27")):
        mb_per_min = 12.0
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
        suffix = path.suffix.lower()
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


def _track_identity_from_payload(payload: dict) -> dict:
    meta = _payload_metadata(payload)
    artist = meta.get("artist")
    album = meta.get("album")
    title = meta.get("title") or meta.get("name")
    return {
        "artist": _norm(artist),
        "album": _norm(album),
        "title": _norm(title),
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
_STREAM_CAPTURE = threading.local()
_STREAM_CAPTURE_INSTALLED = False

# ---------------------------------------------------------------------------
# Tor SOCKS5 bypass
# ---------------------------------------------------------------------------
_TOR_SOCKS = "socks5h://127.0.0.1:9050"
_TOR_BINARY = "/opt/homebrew/bin/tor"
_TOR_DATA_DIR = Path("/tmp/streambox-tor")
_tor_process: object = None   # subprocess.Popen or None
_tor_lock = threading.Lock()


def _tor_is_up() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9050), timeout=2):
            return True
    except Exception:
        return False


def _start_tor() -> bool:
    """Start Tor if not already running. Returns True when SOCKS port is ready."""
    global _tor_process
    import subprocess

    if _tor_is_up():
        return True

    tor_bin = _TOR_BINARY
    if not Path(tor_bin).exists():
        # Try PATH fallback
        import shutil
        tor_bin = shutil.which("tor") or ""
    if not tor_bin:
        print("[Tor] tor binary not found — install with: brew install tor")
        return False

    _TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("[Tor] Starting local Tor daemon…")
    try:
        proc = subprocess.Popen(
            [tor_bin, "--SocksPort", "9050", "--DataDirectory", str(_TOR_DATA_DIR),
             "--Log", "notice stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        _tor_process = proc
    except Exception as e:
        print(f"[Tor] Failed to start: {e}")
        return False

    # Wait up to 30 s for bootstrap
    for _ in range(30):
        time.sleep(1)
        if _tor_is_up():
            print("[Tor] SOCKS5 ready on 127.0.0.1:9050")
            return True

    print("[Tor] Timed out waiting for Tor to bootstrap.")
    return False


def _ensure_tor() -> bool:
    """Thread-safe: ensure Tor is running. Returns True if SOCKS port is available."""
    with _tor_lock:
        return _start_tor()


def prefetch_proxy_pool() -> None:
    """Start Tor and build HTTP proxy pool in background at download start."""
    def _warmup():
        _ensure_tor()
        with _proxy_pool_lock:
            if not _proxy_pool or (time.time() - _proxy_pool_time > _PROXY_POOL_TTL):
                _build_fallback_pool()
    
    t = threading.Thread(target=_warmup, daemon=True, name="proxy-warmup")
    t.start()


# Fallback HTTP proxy pool (used only if Tor is unavailable)
_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=http&timeout=3000&proxy_format=ipport&format=text",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

_proxy_pool: list[str] = []
_proxy_pool_lock = threading.Lock()
_proxy_pool_time: float = 0
_PROXY_POOL_TTL = 600


def _test_proxy(proxy: str, timeout: int = 5) -> str | None:
    import socket
    try:
        host, port_str = proxy.rsplit(":", 1)
        sock = socket.create_connection((host, int(port_str)), timeout=timeout)
        sock.settimeout(timeout)
        sock.sendall(b"CONNECT accounts.spotify.com:443 HTTP/1.1\r\nHost: accounts.spotify.com:443\r\n\r\n")
        response = sock.recv(64).decode("ascii", errors="ignore")
        sock.close()
        return f"http://{proxy}" if "200" in response else None
    except Exception:
        return None


def _build_fallback_pool() -> None:
    import random
    from concurrent.futures import ThreadPoolExecutor, as_completed
    global _proxy_pool_time
    candidates: list[str] = []
    for url in _PROXY_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                lines = resp.read().decode().splitlines()
                candidates.extend(l.strip() for l in lines if l.strip() and ":" in l)
            if len(candidates) >= 200:
                break
        except Exception:
            continue
    random.shuffle(candidates)
    candidates = candidates[:150]
    working: list[str] = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(_test_proxy, p): p for p in candidates}
        for future in as_completed(futures):
            result = future.result()
            if result:
                working.append(result)
    with _proxy_pool_lock:
        _proxy_pool.clear()
        _proxy_pool.extend(working)
        _proxy_pool_time = time.time()
    print(f"[Proxy] Fallback pool ready: {len(working)} HTTP proxies.")


def _pop_fallback_proxy() -> str | None:
    with _proxy_pool_lock:
        if _proxy_pool:
            import random
            p = random.choice(_proxy_pool)
            _proxy_pool.remove(p)
            return p
    print("[Proxy] Building fallback HTTP proxy pool…")
    _build_fallback_pool()
    with _proxy_pool_lock:
        return _proxy_pool.pop() if _proxy_pool else None


def _install_stream_capture() -> None:
    global _STREAM_CAPTURE_INSTALLED
    if _STREAM_CAPTURE_INSTALLED:
        return
    try:
        from SpotiFLAC.core.http import HttpClient  # type: ignore
    except Exception:
        return

    original = HttpClient.stream_to_file

    def wrapped_stream_to_file(self, url, dest_path, progress_cb=None, chunk_size=256 * 1024, extra_headers=None):
        manager = getattr(_STREAM_CAPTURE, "manager", None)
        job_id = getattr(_STREAM_CAPTURE, "job_id", "")
        if manager and job_id:
            with manager._lock:
                job = manager.jobs.get(job_id)
                if job:
                    job["active_stream_url"] = url
                    job["active_stream_dest_path"] = str(dest_path)
                    job["active_stream_headers"] = extra_headers or {}
        return original(self, url, dest_path, progress_cb, chunk_size, extra_headers)

    HttpClient.stream_to_file = wrapped_stream_to_file
    _STREAM_CAPTURE_INSTALLED = True


class ServiceDownloadManager:
    def __init__(self, config):
        self.config = config
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._cancel_flags: set[str] = set()
        self._progress_thread_running = False
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

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") not in ("starting", "running"):
                return False
            self._cancel_flags.add(job_id)
            job["status"] = "error"
            job["error"] = "Cancelled by user"
            job["library_requested"] = False
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

    def library_status(self, payload: dict) -> dict:
        identity = _track_identity_from_payload(payload)
        library = self._find_library_entry(identity)
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
            result = self._copy_job_audio_to_library(job, cache["path"])
            return {"ok": True, "action": "copied", **result, **self.library_status(payload)}

        active = self._find_active_cache_job(identity)
        if active:
            with self._lock:
                job = self.jobs.get(active["id"])
                if job:
                    job["library_requested"] = True
                    job["library_request_payload"] = payload
            self._save_jobs()
            return {"ok": True, "action": "queued", **self.library_status(payload)}

        new_payload = {**payload, "mode": "download"}
        job = self.start_job(new_payload)
        return {"ok": True, "action": "started", "job": job, **self.library_status(payload)}

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
            "service": (payload.get("service") or self.config.download_service or "tidal").lower(),
            "quality": payload.get("quality") or self.config.default_quality or "flac",
            "status": "finished",
            "progress": 100,
            "created_at": time.time(),
            "error": "",
            "resolved_url": "",
            "output_dir": "",
            "library_path": "",
        }

    def _find_library_entry(self, identity: dict) -> dict | None:
        with self._lock:
            jobs = list(self.jobs.values())
        exact_matches = []
        fallback_matches = []
        explicit_path = Path(identity.get("library_path") or "")
        if explicit_path.exists() and explicit_path.is_file():
            exact_matches.append({"path": explicit_path, "job": None, "quality": _quality_rank(explicit_path)})

        for job in jobs:
            path_text = job.get("library_path") or ""
            if job.get("status") == "finished" and job.get("mode") == "download" and path_text:
                path = Path(path_text)
                if path.exists() and _job_matches_identity(job, identity):
                    exact_matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})
                elif path.exists() and _norm(job.get("artist")) == identity["artist"] and _norm(job.get("title")) == identity["title"]:
                    fallback_matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})

        album_dir = self.config.music_dir / identity["artist_part"] / identity["album_part"]
        if album_dir.exists():
            for path in _find_audio_files(album_dir):
                title = _norm(path.stem.split(" - ")[0])
                if title == identity["title"]:
                    exact_matches.append({"path": path, "job": None, "quality": _quality_rank(path)})

        artist_dir = self.config.music_dir / identity["artist_part"]
        if artist_dir.exists():
            for path in _find_audio_files(artist_dir):
                title = _norm(path.stem.split(" - ")[0])
                if title == identity["title"]:
                    fallback_matches.append({"path": path, "job": None, "quality": _quality_rank(path)})

        matches = exact_matches or fallback_matches
        if not matches:
            return None
        matches.sort(key=lambda item: (item["quality"], item["path"].stat().st_mtime), reverse=True)
        return matches[0]

    def _find_cache_entry(self, identity: dict) -> dict | None:
        with self._lock:
            jobs = list(self.jobs.values())
        matches = []
        for job in jobs:
            path_text = job.get("library_path") or ""
            if job.get("status") == "finished" and job.get("mode", "stream") == "stream" and path_text:
                path = Path(path_text)
                if path.exists() and _job_matches_identity(job, identity):
                    matches.append({"path": path, "job": job, "quality": _quality_rank(path, job.get("quality"))})
        if not matches:
            return None
        matches.sort(key=lambda item: (item["quality"], item["path"].stat().st_mtime), reverse=True)
        return matches[0]

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
                    title = path.stem.split(" - ")[0]
                    for key in list(tracks.keys()):
                        if _norm(key) == _norm(title):
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
        with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job["metadata"] = {**(job.get("metadata") or {}), **metadata}
                if artwork_url:
                    job["artwork_url"] = artwork_url
        self._save_jobs()

    def list_jobs(self) -> list[dict]:
        # Don't sync here, it's too slow and blocks the UI. 
        # Progress is synced in the background or during worker execution.
        with self._lock:
            items = list(self.jobs.values())
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
            total_bytes = int(downloaded_bytes * 1.3)
        progress = min(95.0, (downloaded_bytes / total_bytes) * 100.0)
        if progress <= 0:
            return False

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
        job_id = str(uuid.uuid4())
        isrc = (
            payload.get("isrc")
            or (payload.get("track") or {}).get("isrc")
            or (payload.get("metadata") or {}).get("isrc")
            or ""
        )
        metadata = payload.get("metadata") or payload.get("track") or {}
        # Calculate a stable track key for UI matching
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
            "isrc": isrc,
            "metadata": metadata,
            "service": (payload.get("service") or self.config.download_service or "tidal").lower(),
            "quality": payload.get("quality") or self.config.default_quality or "flac",
            "status": "starting",
            "last_status": "Starting...",
            "progress": 0,
            "created_at": time.time(),
            "error": "",
            "resolved_url": "",
            "output_dir": "",
            "library_path": "",
        }
        with self._lock:
            self.jobs[job_id] = job
        threading.Thread(target=self._worker, args=(job_id, payload), daemon=True).start()
        return self._public_job(job)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            job = self.jobs.get(job_id)
            return self._public_job(job) if job else None

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
            
            resolved_url = resolve_download_url(merged, service="spotify", kind=kind)
            if not resolved_url:
                raise RuntimeError("Could not resolve a Spotify URL from the selected track metadata")

            output_dir = self._output_dir(job)
            output_dir.mkdir(parents=True, exist_ok=True)

            with self._lock:
                job["status"] = "running"
                job["resolved_url"] = resolved_url
                job["output_dir"] = str(output_dir)

            self._ensure_progress_thread()
            self._run_spotiflac(resolved_url, output_dir, job)
            self._save_sidecar_files(output_dir, job)

            audio_files = _find_audio_files(output_dir)
            if not audio_files:
                raise RuntimeError("SpotiFLAC finished but no playable audio file was found")

            with self._lock:
                job["library_path"] = str(audio_files[0])
                job["progress"] = 100
                job["status"] = "finished"
                library_requested = bool(job.get("library_requested"))
            self._save_jobs()
            if library_requested and job.get("mode", "stream") == "stream":
                try:
                    self._copy_job_audio_to_library(job, audio_files[0])
                except Exception as exc:
                    with self._lock:
                        job["library_promote_error"] = str(exc)
                    self._save_jobs()
        except Exception as exc:
            with self._lock:
                job["status"] = "error"
                job["error"] = str(exc)
            self._save_jobs()

    def _save_sidecar_files(self, directory: Path, job: dict) -> None:
        try:
            info_path = directory / "metadata.json"
            current_meta = job.get("metadata") or {}
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
            
            data["tracks"][track_title] = current_meta
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

    def _run_spotiflac(self, url: str, output_dir: Path, job: dict) -> None:
        if job["id"] in self._cancel_flags:
            return

        # Kick off proxy pool build in background immediately — ready if download fails
        prefetch_proxy_pool()

        try:
            from SpotiFLAC import SpotiFLAC  # type: ignore
        except Exception as exc:
            raise RuntimeError("SpotiFLAC is not installed in this environment") from exc
        _install_stream_capture()

        raw_service = job["service"]
        spotiflac_service = _SPOTIFLAC_SERVICE_MAP.get(raw_service, raw_service)

        # Map our metadata to SpotiFLAC's internal keys
        meta = job.get("metadata") or {}
        sp_meta = {
            "MUSICBRAINZ_TRACKID": meta.get("musicbrainz_recording_id"),
            "MUSICBRAINZ_ALBUMID": meta.get("musicbrainz_release_id"),
            "MUSICBRAINZ_ARTISTID": meta.get("musicbrainz_artist_id"),
            "MUSICBRAINZ_RELEASEGROUPID": meta.get("musicbrainz_release_group_id"),
            "MUSICBRAINZ_ALBUMARTISTID": meta.get("musicbrainz_albumartist_id"),
            "ALBUMARTISTSORT": meta.get("albumartist_sort"),
            "ARTISTSORT": meta.get("artist_sort"),
            "ISRC": meta.get("isrc") or job.get("isrc") or meta.get("external_ids", {}).get("isrc"),
            "SPOTIFY_ID": meta.get("spotify_id") or job.get("spotify_id"),
            "DEEZER_ID": meta.get("deezer_id"),
            "TIDAL_ID": meta.get("tidal_id"),
            "AMAZON_ID": meta.get("amazon_id"),
            "APPLE_MUSIC_ID": meta.get("apple_music_id"),
            "UPC": meta.get("upc") or meta.get("external_ids", {}).get("upc"),
            "EAN": meta.get("ean") or meta.get("external_ids", {}).get("ean"),
        }
        # Filter out empty values
        sp_meta = {k: v for k, v in sp_meta.items() if v}

        # Create a fallback list, keeping the requested service first. Tidal is
        # intentionally last unless it is the selected service in settings.
        fallback_services = ["qobuz", "amazon", "deezer", "soundcloud", "youtube", "tidal"]
        services_list = [spotiflac_service] + [s for s in fallback_services if s != spotiflac_service]

        kwargs = {
            "url": url,
            "output_dir": str(output_dir),
            "services": services_list,
            "track_max_retries": 3,
            "verbose": True,
            "metadata": sp_meta if sp_meta else True,
            "cover": True,
            "lrc": True,
            "album_artwork": True,
            "allow_fallback": True,
        }

        quality = job.get("quality") or ""
        if quality:
            kwargs["quality"] = quality

        def _exec_sf(proxy=None):
            import os
            old_http = os.environ.get("HTTP_PROXY")
            old_https = os.environ.get("HTTPS_PROXY")
            old_ua = os.environ.get("USER_AGENT")
            
            if proxy:
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
            
            try:
                from fake_useragent import UserAgent
                os.environ["USER_AGENT"] = UserAgent().random
            except Exception:
                pass
            
            try:
                known_problematic = ("track_max_retries", "verbose", "quality", "metadata", "cover", "lrc", "album_artwork")
                for i in range(len(known_problematic) + 1):
                    if job["id"] in self._cancel_flags:
                        raise RuntimeError("Download cancelled")
                    try:
                        SpotiFLAC(**kwargs)
                        # Check for rate limiting in SF logs
                        for msg in captured:
                            if "(429)" in msg or "rate limited" in msg.lower():
                                print(f"[Bypass] Rate limit detected in logs: {msg}")
                                return False
                        return True
                    except TypeError as e:
                        msg = str(e)
                        found_any = False
                        for key in known_problematic:
                            if f"'{key}'" in msg:
                                kwargs.pop(key, None)
                                found_any = True
                                break
                        if not found_any:
                            if i < len(known_problematic):
                                kwargs.pop(known_problematic[i], None)
                            else:
                                raise e
                return False
            except Exception:
                return False
            finally:
                if old_http: os.environ["HTTP_PROXY"] = old_http
                elif "HTTP_PROXY" in os.environ: del os.environ["HTTP_PROXY"]
                if old_https: os.environ["HTTPS_PROXY"] = old_https
                elif "HTTPS_PROXY" in os.environ: del os.environ["HTTPS_PROXY"]
                if old_ua: os.environ["USER_AGENT"] = old_ua
                elif "USER_AGENT" in os.environ: del os.environ["USER_AGENT"]

        captured: list[str] = []
        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno >= logging.ERROR:
                    captured.append(record.getMessage())

        handler = _Capture()
        sf_logger = logging.getLogger("SpotiFLAC")
        sf_logger.addHandler(handler)
        
        def _has_audio(delete_invalid: bool = False) -> bool:
            return bool(_find_audio_files(output_dir, delete_invalid=delete_invalid))

        with _spotiflac_lock:
            try:
                _STREAM_CAPTURE.manager = self
                _STREAM_CAPTURE.job_id = job["id"]
                success = False
                kwargs["allow_fallback"] = False # We handle the provider loop ourselves now

                for service in services_list:
                    if success: break
                    kwargs["services"] = [service]
                    
                    # 1. Try Direct
                    with self._lock:
                        job["last_status"] = f"Trying {service}..."
                    self._save_jobs()
                    
                    captured.clear()
                    sf_success = _exec_sf()
                    if _has_audio() or sf_success:
                        print(f"[Bypass] ✓ {service} (Direct) succeeded.")
                        success = True
                        break

                    # 2. Try Tor
                    if _tor_is_up() or _ensure_tor():
                        with self._lock:
                            job["last_status"] = f"Trying {service} (Tor)..."
                        self._save_jobs()
                        
                        captured.clear()
                        sf_success = _exec_sf(_TOR_SOCKS)
                        if _has_audio(delete_invalid=True) or sf_success:
                            print(f"[Bypass] ✓ {service} (Tor) succeeded.")
                            success = True
                            break

                    # 3. Try HTTP Proxies (as ultimate fallback for this service)
                    for attempt in range(2): # Try 2 proxies per service to keep it moving
                        proxy = _pop_fallback_proxy()
                        if not proxy: break
                        
                        with self._lock:
                            job["last_status"] = f"Trying {service} (Proxy {attempt+1})..."
                        self._save_jobs()
                        
                        captured.clear()
                        sf_success = _exec_sf(proxy)
                        if _has_audio(delete_invalid=True) or sf_success:
                            print(f"[Bypass] ✓ {service} (Proxy) succeeded.")
                            success = True
                            break
                        
                    if success: break
                    print(f"[Bypass] ✗ {service} failed all modes, moving to next provider...")

            finally:
                _STREAM_CAPTURE.manager = None
                _STREAM_CAPTURE.job_id = ""
                sf_logger.removeHandler(handler)

        if not success:
            msg = captured[0] if captured else "All providers failed and no proxy bypass succeeded"
            raise RuntimeError(f"SpotiFLAC ({spotiflac_service}): {msg}")

    def _output_dir(self, job: dict) -> Path:
        identity = clean_part(job.get("isrc") or job.get("id") or job["id"])
        if job.get("mode", "stream") == "download":
            artist = clean_part(job.get("artist") or "Unknown Artist")
            album = clean_part(job.get("album") or job.get("title") or "Unknown Album")
            return self.config.music_dir / artist / album
        
        return self.config.cache_dir / identity

    def _public_job(self, job: dict | None) -> dict:
        if not job:
            return {}
        return {key: value for key, value in job.items()}
