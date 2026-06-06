from __future__ import annotations

import json
import mimetypes
import socket

# Optimize mimetypes to prevent slow Windows Registry scanning
if not mimetypes.inited:
    mimetypes.init(files=[])
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/ogg", ".opus")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
import rapidfuzz
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from catalog import discover_catalog
from config import AppConfig, app_data_dir, load_config, save_config
from music_metadata import album_metadata, album_tracks, artist_page, artist_tour, build_music_indexers, enrich_albums_batch, enrich_artwork_batch, enrich_track_identifiers, search_music, search_relevance, track_credits
from native_audio import native_audio
from service_downloader import ServiceDownloadManager, is_download_audio_candidate, is_valid_audio_file


def _list_audio_output_devices() -> list[dict]:
    """Return audio output devices as [{name, uid}]. macOS uses CoreAudio; Windows uses WMI."""
    import sys
    if sys.platform == "win32":
        return _list_audio_output_devices_windows()
    if sys.platform != "darwin":
        return []
    import ctypes
    try:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

        def _fcc(s: str) -> int:
            return int.from_bytes(s.encode(), "big")

        class _PA(ctypes.Structure):
            _fields_ = [("mSel", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mEl", ctypes.c_uint32)]

        kSys       = ctypes.c_uint32(1)
        kGlob      = _fcc("glob")
        kOutp      = _fcc("outp")
        kDevices   = _fcc("dev#")
        kName      = _fcc("lnam")
        kUID       = _fcc("uid ")
        kStreamCfg = _fcc("slay")
        kUTF8      = 0x08000100

        def _cfstr(ptr: int) -> str:
            if not ptr:
                return ""
            buf = ctypes.create_string_buffer(512)
            cf.CFStringGetCString(ctypes.c_void_p(ptr), buf, 512, kUTF8)
            try:
                cf.CFRelease(ctypes.c_void_p(ptr))
            except Exception:
                pass
            return buf.value.decode("utf-8", errors="replace")

        def _get_str(dev: int, sel: int) -> str:
            pa = _PA(sel, kGlob, 0)
            v  = ctypes.c_void_p(0)
            sz = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
            if ca.AudioObjectGetPropertyData(dev, ctypes.byref(pa), 0, None, ctypes.byref(sz), ctypes.byref(v)):
                return ""
            return _cfstr(v.value)

        def _has_outputs(dev: int) -> bool:
            pa = _PA(kStreamCfg, kOutp, 0)
            sz = ctypes.c_uint32(0)
            if ca.AudioObjectGetPropertyDataSize(dev, ctypes.byref(pa), 0, None, ctypes.byref(sz)):
                return False
            # Virtual devices often report 4 bytes (0 buffers). Real ones > 4.
            return sz.value > 4

        # Enumerate
        pa = _PA(kDevices, kGlob, 0)
        sz = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz)):
            return []
        n = sz.value // 4
        ids = (ctypes.c_uint32 * n)()
        if ca.AudioObjectGetPropertyData(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz), ids):
            return []

        # Keywords to ignore (virtual drivers, strictly inputs, specific default labels)
        ignore_list = [
            "microphone", "input", "background music", "microsoft teams", 
            "zoom", "mirror", "instashare", "airbeam", "ace", "driver"
        ]
        
        # CoreAudio labels for built-in speakers vary: "MacBook Pro Speakers", "iMac Speakers", "Internal Speakers"
        default_ignore = ["speaker", "internal speaker", "built-in"]

        devices = []
        for dev_id in ids:
            if not _has_outputs(dev_id):
                continue
            name = _get_str(dev_id, kName)
            uid  = _get_str(dev_id, kUID)
            
            if not name:
                continue
                
            lname = name.lower()
            # Strict ignore list (virtual/inputs)
            if any(k in lname for k in ignore_list):
                continue
            
            # Hide built-in speakers to avoid duplicating "This computer"
            # We check for "speaker" (singular) to catch "MacBook Pro Speakers"
            if any(k in lname for k in default_ignore) and "airplay" not in lname and "edifier" not in lname:
                continue
                
            devices.append({"name": name, "uid": uid})
        return devices
    except Exception:
        return []


def _list_audio_output_devices_windows() -> list[dict]:
    import subprocess, json as _json
    devices: list[dict] = []
    
    # Hide terminal window on Windows
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE

    try:
        import sounddevice as sd

        for index, info in enumerate(sd.query_devices()):
            if int(info.get("max_output_channels") or 0) <= 0:
                continue
            name = str(info.get("name") or f"Output {index}")
            hostapi = sd.query_hostapis(info.get("hostapi", 0)).get("name", "")
            devices.append({"name": name, "uid": f"sounddevice:{index}", "driver": hostapi})
    except Exception:
        devices = []
    if devices:
        return devices

    script = r"""
try {
    $out = Get-WmiObject -Class Win32_SoundDevice -ErrorAction SilentlyContinue |
        Where-Object { $_.Status -eq 'OK' } |
        ForEach-Object { @{ name=$_.Name; uid=$_.DeviceID } }
    $out | ConvertTo-Json -Compress
} catch { '[]' }
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=8,
            startupinfo=startupinfo
        )
        items = _json.loads(r.stdout.strip() or "[]")
        if isinstance(items, dict):
            items = [items]
        return items or []
    except Exception:
        return []


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

print(f"[Debug] ROOT: {ROOT}")
print(f"[Debug] STATIC: {STATIC} (exists: {STATIC.exists()})")
DATA = app_data_dir()
CONFIG_PATH = DATA / "config.json"
PLAYLISTS_PATH = DATA / "playlists.json"
DOCK_RECENTS_PATH = DATA / "dock_recents.json"

config_lock = threading.Lock()
app_config = load_config(CONFIG_PATH)
service_downloader = ServiceDownloadManager(app_config)


playlists_lock = threading.Lock()
dock_recent_items_lock = threading.Lock()
_dock_recent_items: list[dict] = []

# Callbacks set by desktop.py for macOS Now Playing / Touch Bar integration
_np_update_fn = None   # (info: dict) -> None
_np_state_fn = None    # (state: int) -> None
_np_clear_fn = None    # () -> None
_macos_media_command_fn = None   # (action: str) -> None


def load_playlists() -> list[dict]:
    try:
        return json.loads(PLAYLISTS_PATH.read_text("utf-8"))
    except Exception:
        return []


def save_playlists(data: list[dict]) -> None:
    PLAYLISTS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


def merge_nonempty_track_metadata(saved: dict, enriched: dict) -> dict:
    merged = dict(saved)
    for key, value in enriched.items():
        if value not in ("", None, [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def enrich_and_persist_track(track: dict) -> dict:
    enriched = enrich_track_identifiers(track)
    spotify_id = enriched.get("spotify_id", "")
    changed = False
    with playlists_lock:
        data = load_playlists()
        for playlist in data:
            for index, saved in enumerate(playlist.get("tracks") or []):
                same_spotify_id = spotify_id and saved.get("spotify_id") == spotify_id
                same_title_artist = (
                    not saved.get("spotify_id")
                    and saved.get("title", "").casefold() == enriched.get("title", "").casefold()
                    and saved.get("artist", "").casefold() == enriched.get("artist", "").casefold()
                )
                if same_spotify_id or same_title_artist:
                    merged = merge_nonempty_track_metadata(saved, enriched)
                    if merged == saved:
                        continue
                    playlist["tracks"][index] = merged
                    changed = True
        if changed:
            save_playlists(data)
    return enriched


def backfill_playlist_isrcs(playlist_id: str = "", max_workers: int = 8) -> dict:
    from isrc_resolver import resolve_isrc

    with playlists_lock:
        playlists = load_playlists()
        targets = [
            (playlist.get("id", ""), index, dict(track))
            for playlist in playlists
            if not playlist_id or playlist.get("id") == playlist_id
            for index, track in enumerate(playlist.get("tracks") or [])
            if not track.get("isrc")
        ]

    def resolve_target(target):
        pid, index, track = target
        isrc = resolve_isrc(
            track.get("title", ""),
            track.get("artist", ""),
            spotify_id=track.get("spotify_id", ""),
        )
        return pid, index, track, isrc

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        resolved = list(executor.map(resolve_target, targets))

    filled = 0
    with playlists_lock:
        playlists = load_playlists()
        by_id = {playlist.get("id"): playlist for playlist in playlists}
        for pid, index, original, isrc in resolved:
            tracks = (by_id.get(pid) or {}).get("tracks") or []
            if not isrc or index >= len(tracks) or tracks[index].get("isrc"):
                continue
            current = tracks[index]
            if original.get("spotify_id") and current.get("spotify_id") != original.get("spotify_id"):
                continue
            if not original.get("spotify_id") and (
                current.get("title") != original.get("title")
                or current.get("artist") != original.get("artist")
            ):
                continue
            current["isrc"] = isrc
            filled += 1
        if filled:
            save_playlists(playlists)
    return {"missing": len(targets), "filled": filled, "remaining": len(targets) - filled}


def backfill_library_sidecars(music_root: Path | None = None) -> dict:
    root = Path(music_root or app_config.music_dir)
    result = {
        "root": str(root),
        "sidecars_scanned": 0,
        "tracks_scanned": 0,
        "tracks_updated": 0,
        "sidecars_updated": 0,
        "errors": [],
    }
    for info_path in sorted(root.rglob("metadata.json")):
        result["sidecars_scanned"] += 1
        try:
            data = json.loads(info_path.read_text("utf-8"))
            tracks = data.get("tracks") if isinstance(data, dict) else None
            if not isinstance(tracks, dict):
                continue
            changed = False
            for title, saved in list(tracks.items()):
                if not isinstance(saved, dict):
                    continue
                result["tracks_scanned"] += 1
                source = dict(saved)
                source.setdefault("title", title)
                try:
                    enriched = enrich_track_identifiers(source)
                except Exception as exc:
                    result["errors"].append(f"{info_path}: {title}: {exc}")
                    continue
                merged = merge_nonempty_track_metadata(saved, enriched)
                if merged == saved:
                    continue
                tracks[title] = merged
                changed = True
                result["tracks_updated"] += 1
            if changed:
                info_path.write_text(json.dumps(data, indent=2), "utf-8")
                result["sidecars_updated"] += 1
        except Exception as exc:
            result["errors"].append(f"{info_path}: {exc}")
    return result


def enrich_saved_playlist_tracks(playlist_id: str) -> None:
    with playlists_lock:
        playlist = next((entry for entry in load_playlists() if entry.get("id") == playlist_id), None)
        tracks = list((playlist or {}).get("tracks") or [])
    for track in tracks:
        enrich_and_persist_track(track)


def start_playlist_identifier_enrichment(playlist_id: str) -> None:
    threading.Thread(
        target=enrich_saved_playlist_tracks,
        args=(playlist_id,),
        name=f"playlist-identifiers-{playlist_id}",
        daemon=True,
    ).start()


def enrich_download_payload(body: dict) -> dict:
    track = body.get("track") if isinstance(body.get("track"), dict) else {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else track
    source = {**metadata, **track}
    enriched = enrich_and_persist_track(source)
    if not enriched:
        return body
    return {
        **body,
        "track": enriched,
        "metadata": enriched,
        "spotify_id": enriched.get("spotify_id", body.get("spotify_id", "")),
        "isrc": enriched.get("isrc", body.get("isrc", "")),
    }


def dock_recent_item_key(entry: dict) -> str:
    data = entry["data"]
    if entry["kind"] == "playlist":
        return f"playlist:{data.get('id') or entry['title']}"
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    identity = data.get("spotify_id") or metadata.get("spotify_id")
    fallback = f"{entry['title']}:{data.get('artist', '')}"
    return f"track:{identity or fallback}"


def valid_dock_recent_items(entries: list[dict]) -> list[dict]:
    items = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        kind = entry.get("kind")
        data = entry.get("data")
        if title and kind in {"track", "playlist"} and isinstance(data, dict):
            item = {"title": title, "kind": kind, "data": data}
            key = dock_recent_item_key(item)
            if key not in seen:
                seen.add(key)
                items.append(item)
            if len(items) == 3:
                break
    return items


def set_dock_recent_items(entries: list[dict]) -> None:
    items = valid_dock_recent_items(entries)
    with dock_recent_items_lock:
        _dock_recent_items[:] = items
        DOCK_RECENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOCK_RECENTS_PATH.write_text(json.dumps(items, indent=2), "utf-8")


def initialize_dock_recent_items() -> None:
    try:
        saved = valid_dock_recent_items(json.loads(DOCK_RECENTS_PATH.read_text("utf-8")))
    except Exception:
        saved = []
    if saved:
        set_dock_recent_items(saved)
        return

    catalog = discover_catalog(app_config, refresh_global=False)
    set_dock_recent_items([
        {"kind": "track", "title": track.get("title", "Unknown Track"), "data": track}
        for track in catalog.get("recent_tracks", [])[:3]
    ])


def get_dock_recent_items() -> list[dict]:
    with dock_recent_items_lock:
        return list(_dock_recent_items)


def _spotify_import_playlist(playlist_url: str) -> dict:
    """Returns {name, artwork_url, description, owner, followers, tracks} from Spotify."""
    m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", playlist_url)
    if not m:
        return {"name": "", "artwork_url": "", "description": "", "owner": "", "followers": 0, "tracks": []}
    playlist_id = m.group(1)
    try:
        from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
        client = SpotifyMetadataClient()
        info, imported_tracks, playlist_cover = client.get_playlist_tracks(playlist_id)
        pl_name = info.get("name", "")
        pl_artwork = info.get("cover_url", "") or playlist_cover
        pl_description = info.get("description", "") or ""
        pl_owner = info.get("owner", "") or ""
        pl_followers = info.get("followers", 0) or 0

        tracks = [{
            "type": "track",
            "title": track.title,
            "artist": track.artists,
            "artist_id": track.artist_id if hasattr(track, 'artist_id') else "",
            "album": track.album,
            "artwork_url": track.cover_url,
            "spotify_id": track.id,
            "spotify_url": track.external_url or f"https://open.spotify.com/track/{track.id}",
            "duration_ms": track.duration_ms,
            "isrc": track.isrc,
        } for track in imported_tracks if track.id]

        return {
            "name": pl_name, "artwork_url": pl_artwork, "description": pl_description,
            "owner": pl_owner, "followers": pl_followers, "tracks": tracks,
        }
    except Exception as e:
        print(f"[Spotify import] {e}")
        return {"name": "", "artwork_url": "", "description": "", "owner": "", "followers": 0, "tracks": []}


def directory_stats(path: Path) -> dict:
    total = 0
    files = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    files += 1
                except OSError:
                    pass
    return {"path": str(path), "bytes": total, "files": files}


def cache_stats() -> dict:
    stats = directory_stats(app_config.cache_dir)
    stats["frequency"] = app_config.cache_cleanup_frequency
    stats["last_cleanup"] = app_config.last_cache_cleanup
    return stats


def cache_cleanup_due() -> bool:
    frequency = app_config.cache_cleanup_frequency
    if frequency in {"startup", "close_restart"}:
        return True
    intervals = {
        "daily": 24 * 60 * 60,
        "weekly": 7 * 24 * 60 * 60,
        "monthly": 30 * 24 * 60 * 60,
    }
    interval = intervals.get(frequency)
    if not interval:
        return False
    return time.time() - float(app_config.last_cache_cleanup or 0) >= interval


def apply_scheduled_cache_cleanup() -> None:
    if not cache_cleanup_due():
        return
    cache_dir = app_config.cache_dir
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
        except Exception: pass
    cache_dir.mkdir(parents=True, exist_ok=True)
    app_config.last_cache_cleanup = time.time()
    save_config(CONFIG_PATH, app_config)


def apply_shutdown_cache_cleanup() -> None:
    if app_config.cache_cleanup_frequency != "close_restart":
        return
    try:
        service_downloader.clear_cache()
    except Exception:
        cache_dir = app_config.cache_dir
        if cache_dir.exists():
            try:
                shutil.rmtree(cache_dir)
            except Exception:
                pass
        cache_dir.mkdir(parents=True, exist_ok=True)
    app_config.last_cache_cleanup = time.time()
    save_config(CONFIG_PATH, app_config)


def indexed_music() -> list[dict]:
    catalog = discover_catalog(app_config)
    indexed = []
    for item in catalog["personal_tracks"]:
        indexed.append(
            {
                "type": "track",
                "title": item["title"],
                "artist": item["artist"],
                "album": item["album"],
                "artwork_url": "",
                "lyrics_url": "",
                "source": "Your History",
                "plays": item["plays"],
            }
        )
    return enrich_artwork_batch(indexed)


def quick_music_suggestions(term: str, limit: int = 24) -> list[dict]:
    wanted = term.strip().lower()
    if not wanted:
        return []
    catalog = discover_catalog(app_config)
    pool = []
    for key in ("personal_tracks", "recent_tracks", "top_tracks", "artists", "albums"):
        pool.extend(catalog.get(key, []))

    results, seen = [], set()
    for item in pool:
        haystack = " ".join(str(item.get(key, "")) for key in ("artist", "album", "title", "name")).lower()
        if wanted not in haystack:
            continue
        dedupe = (
            item.get("type"),
            (item.get("artist") or item.get("name") or "").lower(),
            (item.get("album") or "").lower(),
            (item.get("title") or "").lower(),
        )
        if dedupe in seen:
            continue
        seen.add(dedupe)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def json_bytes(value: object) -> bytes:
    return json.dumps(value, indent=2).encode("utf-8")


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if not length:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def safe_static_path(request_path: str) -> Path | None:
    rel = unquote(request_path.lstrip("/"))
    if rel == "":
        rel = "index.html"
    path = (STATIC / rel).resolve()
    if STATIC.resolve() not in path.parents and path != STATIC.resolve():
        return None
    return path


def active_audio_candidate(output_dir: Path) -> Path | None:
    files = [f for f in output_dir.rglob("*") if f.is_file() and f.stat().st_size > 0]
    if not files:
        return None
    priority = (
        lambda f: (
            0 if f.name.lower().endswith(".m4a.part") else   # 0.6+: M4A in-progress
            1 if f.name.lower().endswith(".m4a.tmp") else    # 0.5 compat
            2 if f.name.lower().endswith(".flac.part") else
            3 if f.name.lower().endswith(".mp3.part") else
            4 if f.suffix.lower() in {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac"} else
            5,
            -f.stat().st_size,
            -f.stat().st_mtime,
        )
    )
    candidates = [
        f
        for f in files
        if is_download_audio_candidate(f) and (_candidate_is_streamable(f) or is_valid_audio_file(f))
    ]
    return sorted(candidates, key=priority)[0] if candidates else None


# Formats/files SpotiFLAC may expose before the final rename. Some providers write
# MP4/AAC bytes first even when the final requested output is FLAC.
_STREAMABLE_EXTS = {".mp3", ".ogg", ".opus", ".flac", ".wav", ".m4a", ".mp4", ".aac"}


def _audio_header(path: Path) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(64)
    except Exception:
        return b""


def _sniff_audio_mime(path: Path) -> str:
    header = _audio_header(path)
    name = path.name.lower()
    suffix_name = name
    for suffix in (".part", ".tmp"):
        if suffix_name.endswith(suffix):
            suffix_name = suffix_name[: -len(suffix)]

    if b"ftyp" in header[:16] or suffix_name.endswith((".m4a", ".mp4", ".aac")):
        return "audio/mp4"
    if b"fLaC" in header or suffix_name.endswith(".flac"):
        return "audio/flac"
    if b"OggS" in header or suffix_name.endswith((".ogg", ".opus")):
        return "audio/ogg"
    if b"RIFF" in header and b"WAVE" in header or suffix_name.endswith(".wav"):
        return "audio/wav"
    if suffix_name.endswith(".mp3"):
        return "audio/mpeg"
    return mimetypes.guess_type(suffix_name)[0] or "audio/mpeg"


def _candidate_is_streamable(path: Path) -> bool:
    """True if path (or a .part/.tmp variant) is a browser-progressively-playable format."""
    name = path.name.lower()
    for suffix in (".part", ".tmp"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return Path(name).suffix in _STREAMABLE_EXTS or b"ftyp" in _audio_header(path)[:16]


class Handler(BaseHTTPRequestHandler):
    server_version = "SpotiFLACStreamer/0.9.2"
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, value: object, status: int = 200) -> None:
        payload = json_bytes(value)
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, message: str, status: int = 400) -> None:
        try:
            self.send_json({"error": message}, status)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_response(self, code, message=None):
        super().send_response(code, message)
        self.send_header("Connection", "keep-alive")

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE, PUT")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Duck-UA")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()


    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/api/discover":
                refresh_global = query.get("refresh", ["1"])[0] != "0"
                catalog = discover_catalog(app_config, refresh_global=refresh_global)

                if not refresh_global:
                    self.send_json(catalog)
                    return

                # Only enrich a small batch of each section to keep response time low.
                catalog["personal_tracks"] = enrich_artwork_batch(catalog["personal_tracks"][:6]) + catalog["personal_tracks"][6:]

                recent_raw = catalog["recent_tracks"][:6]
                recent_enriched = enrich_artwork_batch(recent_raw)
                for track in recent_enriched:
                    job_id = track.get("id")
                    if job_id:
                        service_downloader.update_job_metadata(job_id, track.get("metadata") or {}, track.get("artwork_url") or "")
                catalog["recent_tracks"] = recent_enriched + catalog["recent_tracks"][6:]

                catalog["top_tracks"] = enrich_artwork_batch(catalog["top_tracks"][:6]) + catalog["top_tracks"][6:]
                catalog["artists"] = enrich_artwork_batch(catalog["artists"][:6]) + catalog["artists"][6:]
                catalog["albums"] = enrich_artwork_batch(catalog["albums"][:6]) + catalog["albums"][6:]

                self.send_json(catalog)
                return

            if path == "/api/music/index":
                self.send_json({"results": indexed_music()})
                return
            if path == "/api/music/suggest":
                term = query.get("q", [""])[0].strip()
                self.send_json({"results": search_music(app_config, term) if term else []})
                return
            if path == "/api/music/suggest/stream":
                term = query.get("q", [""])[0].strip()
                self.stream_music_suggestions(term)
                return
            if path == "/api/music/search" or path == "/api/search":
                term = query.get("q", [""])[0].strip()
                if not term:
                    self.send_json({"results": []})
                    return
                self.send_json({"results": search_music(app_config, term)})
                return
            if path == "/api/music/album":
                artist = query.get("artist", [""])[0].strip()
                album = query.get("album", [""])[0].strip()
                title = query.get("title", [""])[0].strip()
                self.send_json(album_metadata(app_config, artist, album, title))
                return
            if path == "/api/music/artist":
                artist = query.get("artist", [""])[0].strip()
                artist_id = query.get("artist_id", [""])[0].strip()

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_cors_headers()
                self.end_headers()

                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    for part in artist_page(app_config, artist, artist_id):
                        chunk = json.dumps(part)
                        self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    self.wfile.write(b"event: done\ndata: {}\n\n")
                    self.wfile.flush()
                except Exception as e:
                    print(f"SSE error: {e}")
                return
            if path == "/api/music/album_tracks":
                artist = query.get("artist", [""])[0].strip()
                album = query.get("album", [""])[0].strip()
                release_id = query.get("release_id", [""])[0].strip()
                spotify_id = query.get("spotify_id", [""])[0].strip()
                self.send_json(album_tracks(app_config, artist, album, release_id, spotify_id))
                return
            if path == "/api/settings":
                print(f"[API] GET /api/settings -> {app_config.cache_dir}, {app_config.music_dir}")
                self.send_json(app_config.public_dict())
                return
            if path == "/api/image":
                url = query.get("url", [""])[0].strip()
                if not url:
                    self.send_error_json("Missing URL", HTTPStatus.BAD_REQUEST)
                    return
                try:
                    # Stricter timeout and standard headers
                    image_headers = {
                        "User-Agent": "Mindinguflac/1.0 +https://www.discogs.com/developers/",
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                    }
                    image_host = (urlparse(url).hostname or "").lower()
                    if app_config.discogs_token and (
                        image_host == "discogs.com"
                        or image_host.endswith(".discogs.com")
                    ):
                        image_headers["Authorization"] = f"Discogs token={app_config.discogs_token}"
                    req = urllib.request.Request(url, headers=image_headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
                        data = resp.read()
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "public, max-age=604800")
                        self.end_headers()
                        self.wfile.write(data)
                except Exception as e:
                    print(f"[ImageProxy] Error fetching {url}: {e}")
                    self.send_error_json("Failed to fetch image", HTTPStatus.BAD_GATEWAY)
                return
            if path == "/api/playlists":
                with playlists_lock:
                    self.send_json(load_playlists())
                return
            if path == "/api/cache":
                self.send_json(cache_stats())
                return
            if path == "/api/cache/logs":
                self.send_json(service_downloader.cache_log_snapshot())
                return
            if path == "/api/service/downloads":
                self.send_json({"jobs": service_downloader.list_jobs()})
                return
            if path == "/api/audio/devices":
                self.send_json({"devices": _list_audio_output_devices(), "native_available": native_audio.available()})
                return
            if path == "/api/ddg/status":
                import duck_proxy
                self.send_json(duck_proxy.fetch_status())
                return
            if path == "/api/native_audio/status":
                self.send_json(native_audio.status())
                return
            if path == "/api/bluetooth/state":
                import bluetooth_scan
                self.send_json(bluetooth_scan.get_state())
                return
            if path == "/api/bluetooth/scan/start":
                import bluetooth_scan
                bluetooth_scan.start_scan()
                self.send_json({"ok": True})
                return
            if path == "/api/bluetooth/scan/stop":
                import bluetooth_scan
                bluetooth_scan.stop_scan()
                self.send_json({"ok": True})
                return
            if path == "/api/bluetooth/pair":
                # For GET, we check query params instead of body
                addr = query.get("address", [""])[0]
                import bluetooth_scan
                error = bluetooth_scan.pair_device(addr)
                self.send_json({"ok": not error, "error": error})
                return
            if path == "/api/library/stream":
                file_path = Path(query.get("path", [""])[0].strip())
                if not file_path.exists():
                    self.send_error_json("File not found", HTTPStatus.NOT_FOUND)
                    return
                self.stream_local_path(file_path)
                return
            if path == "/api/library/stream_active_job":
                job_id = query.get("job_id", [""])[0].strip()
                job = service_downloader.get_job(job_id)
                if not job:
                    self.send_error_json("Job not found", HTTPStatus.NOT_FOUND)
                    return

                output_dir = Path(job.get("output_dir") or "")
                candidate = None
                for _ in range(900):
                    job = service_downloader.get_job(job_id)
                    if not job or job.get("status") == "error":
                        self.send_error_json(job.get("error", "Download failed") if job else "Job not found", HTTPStatus.CONFLICT)
                        return
                    if job.get("status") == "finished" and job.get("library_path"):
                        final_path = Path(job["library_path"])
                        if final_path.exists():
                            candidate = final_path
                            break

                    engine = str(job.get("engine") or "").lower()
                    if job.get("active_audio_path"):
                        active_path = Path(job.get("active_audio_path") or "")
                        ready_bytes = int(job.get("active_audio_ready_bytes") or 0)
                        if active_path.exists() and ready_bytes > 512 * 1024 and is_valid_audio_file(active_path):
                            candidate = active_path
                    if not candidate and engine != "torrent":
                        if not output_dir.parts:
                            output_dir = Path(job.get("output_dir") or "")
                        if output_dir.exists():
                            candidate = active_audio_candidate(output_dir)
                    if candidate:
                        break
                    time.sleep(1)

                if not candidate:
                    self.send_error_json("No audio data available yet", HTTPStatus.ACCEPTED)
                    return

                is_finished = job.get("status") == "finished"
                self.stream_local_path(candidate, is_active_job=not is_finished)
                return

            if path == "/api/tidal_proxy":
                target_url = query.get("url", [""])[0].strip()
                if not target_url or not target_url.startswith("https://"):
                    self.send_error_json("Invalid URL", 400)
                    return
                try:
                    import urllib.request as _ureq
                    req = _ureq.Request(target_url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Origin": "https://monochrome.samidy.com",
                        "Referer": "https://monochrome.samidy.com/",
                        "Accept": "*/*",
                    })
                    with _ureq.urlopen(req, timeout=30) as resp:
                        data = resp.read()
                        ctype = resp.headers.get("Content-Type", "audio/mp4")
                    self.send_response(200)
                    self.send_cors_headers()
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    self.send_error_json(str(exc), 502)
                return

            static_path = safe_static_path(path)
            if static_path and static_path.is_file():
                self.send_static(static_path)
                return

            self.send_error_json("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = read_body(self)
        try:
            if path == "/api/dock/recent":
                set_dock_recent_items(body.get("entries") or [])
                self.send_json({"ok": True})
                return
            if path == "/api/dock/playing-state":
                import desktop as _desktop
                _desktop._macos_dock_state["playing"] = bool(body.get("playing"))
                self.send_json({"ok": True})
                return
            if path == "/api/now_playing":
                if _np_update_fn:
                    _np_update_fn(body)
                self.send_json({"ok": True})
                return
            if path == "/api/now_playing/state":
                if _np_state_fn:
                    _np_state_fn(int(body.get("state", 2)))
                self.send_json({"ok": True})
                return
            if path == "/api/now_playing/clear":
                if _np_clear_fn:
                    _np_clear_fn()
                self.send_json({"ok": True})
                return
            if path == "/api/macos_media_command":
                action = str(body.get("action") or "")
                if _macos_media_command_fn and action:
                    _macos_media_command_fn(action)
                self.send_json({"ok": True})
                return
            if path == "/api/bluetooth/scan/start":
                import bluetooth_scan
                bluetooth_scan.start_scan()
                self.send_json({"ok": True})
                return
            if path == "/api/bluetooth/scan/stop":
                import bluetooth_scan
                bluetooth_scan.stop_scan()
                self.send_json({"ok": True})
                return
            if path == "/api/bluetooth/pair":
                import bluetooth_scan
                error = bluetooth_scan.pair_device(body.get("address", ""))
                self.send_json({"ok": not error, "error": error})
                return
            if path == "/api/artist/about":
                from music_metadata import artist_about
                self.send_json(artist_about(body.get("artist_id"), body.get("name")))
                return
            if path == "/api/artist/tour":
                self.send_json(artist_tour(body.get("artist_id", ""), body.get("name", "")))
                return
            if path == "/api/track/credits":
                self.send_json(track_credits(body.get("track") or body))
                return
            if path == "/api/music/enrich":
                tracks = body.get("tracks") or []
                enriched = enrich_artwork_batch(tracks)
                # Also enrich identifiers for the batch if it's small (to avoid timeout)
                if len(enriched) <= 20:
                    for i in range(len(enriched)):
                        enriched[i] = enrich_track_identifiers(enriched[i])
                self.send_json({"tracks": enriched})
                return

            if path == "/api/playlists/tracks/add":
                playlist_id = body.get("id", "")
                tracks_to_add = body.get("tracks") or []
                if not playlist_id or not tracks_to_add:
                    self.send_error_json("Missing ID or tracks", HTTPStatus.BAD_REQUEST)
                    return
                with playlists_lock:
                    data = load_playlists()
                    pl = next((p for p in data if p["id"] == playlist_id), None)
                    if not pl:
                        self.send_error_json("Playlist not found", HTTPStatus.NOT_FOUND)
                        return
                    
                    seen_keys = set()
                    def track_key(t):
                        return f"{str(t.get('artist') or '').strip().lower()}||{str(t.get('title') or '').strip().lower()}"
                    
                    for t in pl.get("tracks", []):
                        seen_keys.add(track_key(t))
                    
                    added_count = 0
                    for t in tracks_to_add:
                        if track_key(t) not in seen_keys:
                            pl["tracks"].append(t)
                            seen_keys.add(track_key(t))
                            added_count += 1
                    
                    if added_count > 0:
                        save_playlists(data)
                        start_playlist_identifier_enrichment(playlist_id)
                
                self.send_json({"ok": True, "added": added_count})
                return
            if path == "/api/settings":
                updated = AppConfig.from_public_dict(body)
                with config_lock:
                    global app_config, service_downloader
                    app_config = updated
                    save_config(CONFIG_PATH, app_config)
                    service_downloader.update_config(app_config)
                self.send_json({"ok": True})
                return
            if path == "/api/playlists":
                user_name = body.get("name", "").strip()
                spotify_url = body.get("spotify_url", "").strip()
                imported = {"name": "", "artwork_url": "", "tracks": []}
                if spotify_url:
                    imported = _spotify_import_playlist(spotify_url)
                    if not imported["name"] and not imported["tracks"]:
                        self.send_error_json("Spotify import failed", HTTPStatus.BAD_GATEWAY)
                        return
                playlist = {
                    "id": str(uuid.uuid4()),
                    "name": user_name or imported["name"] or "New Playlist",
                    "artwork_url": imported.get("artwork_url", ""),
                    "description": imported.get("description", ""),
                    "owner": imported.get("owner", ""),
                    "followers": imported.get("followers", 0),
                    "spotify_url": spotify_url,
                    "tracks": imported["tracks"],
                    "metadata_fetched": bool(spotify_url and imported["tracks"]),
                    "created_at": time.time(),
                }
                with playlists_lock:
                    data = load_playlists()
                    data.append(playlist)
                    save_playlists(data)
                if imported["tracks"]:
                    start_playlist_identifier_enrichment(playlist["id"])
                self.send_json({**playlist, "imported": bool(imported["tracks"])}, 201)
                return
            if path == "/api/playlists/refresh":
                playlist_id = body.get("id", "")
                with playlists_lock:
                    data = load_playlists()
                    pl = next((p for p in data if p["id"] == playlist_id), None)
                    if not pl:
                        self.send_error_json("Playlist not found", HTTPStatus.NOT_FOUND)
                        return
                    spotify_url = pl.get("spotify_url", "")
                if not spotify_url:
                    self.send_error_json("No Spotify URL", HTTPStatus.BAD_REQUEST)
                    return
                imported = _spotify_import_playlist(spotify_url)
                if not imported["name"] and not imported["tracks"]:
                    self.send_error_json("Spotify import failed", HTTPStatus.BAD_GATEWAY)
                    return
                with playlists_lock:
                    data = load_playlists()
                    pl = next((p for p in data if p["id"] == playlist_id), None)
                    if pl:
                        if imported["name"]: pl["name"] = imported["name"]
                        if imported["artwork_url"]: pl["artwork_url"] = imported["artwork_url"]
                        pl["description"] = imported.get("description", "")
                        pl["owner"] = imported.get("owner", "")
                        pl["followers"] = imported.get("followers", 0)
                        pl["tracks"] = imported["tracks"]
                        pl["metadata_fetched"] = True
                        save_playlists(data)
                if pl and pl.get("tracks"):
                    start_playlist_identifier_enrichment(playlist_id)
                self.send_json(pl)
                return
            if path == "/api/playlists/tracks":
                playlist_id = body.get("playlist_id", "")
                track = body.get("track") or {}
                action = body.get("action", "toggle")
                with playlists_lock:
                    data = load_playlists()
                    pl = next((p for p in data if p["id"] == playlist_id), None)
                    if not pl:
                        self.send_error_json("Playlist not found", HTTPStatus.NOT_FOUND)
                        return
                    def same_track(t):
                        if track.get("spotify_id") and t.get("spotify_id"):
                            return t["spotify_id"] == track["spotify_id"]
                        return (t.get("title", "").lower() == track.get("title", "").lower() and
                                t.get("artist", "").lower() == track.get("artist", "").lower())
                    existing = next((t for t in pl["tracks"] if same_track(t)), None)
                    if action == "remove" or (action == "toggle" and existing):
                        pl["tracks"] = [t for t in pl["tracks"] if not same_track(t)]
                        in_playlist = False
                    else:
                        if not existing:
                            pl["tracks"].append(track)
                        in_playlist = True
                    save_playlists(data)
                if in_playlist and not existing:
                    threading.Thread(
                        target=enrich_and_persist_track,
                        args=(track,),
                        daemon=True,
                        name="playlist-track-enrich",
                    ).start()
                self.send_json({"ok": True, "in_playlist": in_playlist})
                return
            if path == "/api/service/download":
                job = service_downloader.start_job(enrich_download_payload(body))
                self.send_json(job, 201)
                return
            if path == "/api/service/promote":
                ok = service_downloader.promote_job(body.get("job_id"))
                self.send_json({"ok": ok})
                return
            if path == "/api/ddg/chat":
                import duck_proxy
                self.send_json(duck_proxy.send_chat(
                    token=body.get("vqd_hash_1", ""),
                    messages=body.get("messages", []),
                    model=body.get("model", "gpt-5-mini"),
                ))
                return
            if path == "/api/library/status":
                self.send_json(service_downloader.library_status(body))
                return
            if path == "/api/library/status/batch":
                self.send_json(service_downloader.library_status_batch(body.get("tracks", [])))
                return
            if path == "/api/library/toggle":
                self.send_json(service_downloader.toggle_library(enrich_download_payload(body)))
                return
            if path == "/api/playback/source":
                self.send_json(service_downloader.playback_source(enrich_download_payload(body)))
                return
            if path == "/api/native_audio/play":
                self.send_json(native_audio.play(
                    body.get("path", ""),
                    body.get("device_uid", ""),
                    float(body.get("volume", 1) or 1),
                    float(body.get("position", 0) or 0),
                    body.get("metadata"),
                ))
                return
            if path == "/api/native_audio/pause":
                self.send_json(native_audio.pause())
                return
            if path == "/api/native_audio/resume":
                self.send_json(native_audio.resume())
                return
            if path == "/api/native_audio/stop":
                self.send_json(native_audio.stop())
                return
            if path == "/api/native_audio/seek":
                self.send_json(native_audio.seek(float(body.get("position", 0) or 0)))
                return
            if path == "/api/native_audio/volume":
                self.send_json(native_audio.set_volume(float(body.get("volume", 1) or 1)))
                return
            if path == "/api/service/promote":
                result = service_downloader.promote_to_library(
                    body.get("job_id"),
                )
                self.send_json(result or {"ok": False}, 200 if result else 409)
                return
            self.send_error_json("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/playlists":
                body = read_body(self)
                playlist_id = body.get("id", "")
                with playlists_lock:
                    data = load_playlists()
                    data = [p for p in data if p["id"] != playlist_id]
                    save_playlists(data)
                self.send_json({"ok": True})
                return
            if path == "/api/service/cancel":
                body = read_body(self)
                service_downloader.cancel_job(body.get("job_id"))
                self.send_json({"ok": True})
                return
            if path == "/api/cache":
                result = service_downloader.clear_cache()
                app_config.last_cache_cleanup = time.time()
                save_config(CONFIG_PATH, app_config)
                self.send_json({**result, **cache_stats()})
                return
            self.send_error_json("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)

    def send_static(self, path: Path) -> None:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", mime)
        if path.suffix.lower() in {".html", ".js", ".css"}:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def stream_local_path(self, path: Path, is_active_job: bool = False) -> None:
        try:
            size = path.stat().st_size
            mime = _sniff_audio_mime(path) if is_active_job else (mimetypes.guess_type(path.name)[0] or "audio/mpeg")

            if is_active_job and _candidate_is_streamable(path):
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", mime)
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()

                with path.open("rb") as f:
                    last_pos = 0
                    consecutive_no_data = 0
                    while True:
                        f.seek(last_pos)
                        chunk = f.read(64 * 1024)
                        if chunk:
                            last_pos += len(chunk)
                            try:
                                self.wfile.write(hex(len(chunk))[2:].encode() + b"\r\n")
                                self.wfile.write(chunk + b"\r\n")
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                return
                            consecutive_no_data = 0
                        else:
                            time.sleep(0.5)
                            consecutive_no_data += 1
                            if consecutive_no_data > 240:
                                break
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return

            start = 0
            end = max(0, size - 1)
            status = 200
            range_header = self.headers.get("Range", "").strip()
            if range_header.startswith("bytes="):
                spec = range_header.split("=", 1)[1].split(",", 1)[0].strip()
                try:
                    left, right = spec.split("-", 1)
                    if left:
                        start = int(left)
                        end = int(right) if right else size - 1
                    elif right:
                        suffix_len = int(right)
                        start = max(0, size - suffix_len)
                        end = size - 1
                    if start < 0 or start >= size or end < start:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_cors_headers()
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    end = min(end, size - 1)
                    status = 206
                except Exception:
                    start = 0
                    end = max(0, size - 1)
                    status = 200

            content_length = max(0, end - start + 1)
            self.send_response(status)
            self.send_cors_headers()
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            print(f"Streaming error: {exc}")
    def stream_music_suggestions(self, term: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_cors_headers()
        self.end_headers()
        try:
            results = quick_music_suggestions(term)
            chunk = json.dumps({"results": results})
            self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass


def create_server(host: str = "0.0.0.0", port: int = 8888) -> ThreadingHTTPServer:
    DATA.mkdir(parents=True, exist_ok=True)
    app_config.cache_dir.mkdir(parents=True, exist_ok=True)
    app_config.music_dir.mkdir(parents=True, exist_ok=True)
    apply_scheduled_cache_cleanup()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8888"))
    server = create_server(host, port)
    print(f"Serving on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        apply_shutdown_cache_cleanup()


if __name__ == "__main__":
    main()
