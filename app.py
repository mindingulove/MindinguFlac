from __future__ import annotations

import json
import asyncio
import hashlib
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
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/ogg", ".opus")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
import os
import re
import shutil
import signal
import tempfile
import threading
import time
import urllib.request
import uuid
import rapidfuzz
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from catalog import discover_catalog
from config import AppConfig, app_data_dir, load_config, save_config
import db
from music_metadata import album_metadata, album_tracks, artist_page, artist_tour, build_music_indexers, enrich_albums_batch, enrich_artwork_batch, enrich_track_identifiers, release_year, search_music, search_relevance, track_credits
from playlist_recommender import generate_one_replacement_recommendation, generate_playlist_recommendations, get_playlist_track_keys, record_recommendation_feedback
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
LYRICS_DIR = DATA / "lyrics"
VIDEO_CACHE_PATH = DATA / "video_cache.json"
VIDEO_FILES_DIR = DATA / "video_files"
VIDEO_CACHE_VERSION = 2

config_lock = threading.Lock()
lyrics_prefetch_lock = threading.Lock()
lyrics_prefetch_inflight: set[str] = set()
video_cache_lock = threading.Lock()
_video_fetch_jobs: dict[str, str] = {}   # cache_key -> "downloading"|"ready"|"failed"
_video_fetch_lock = threading.Lock()


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".__mindinguflac_write_test__"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _writable_cache_fallback() -> Path:
    candidates = [
        DATA / "cache",
        Path(tempfile.gettempdir()) / "Mindinguflac" / "cache",
    ]
    for candidate in candidates:
        if _is_writable_directory(candidate):
            return candidate
    return candidates[-1]


def _sanitize_runtime_config(config: AppConfig) -> AppConfig:
    DATA.mkdir(parents=True, exist_ok=True)
    config.music_dir.mkdir(parents=True, exist_ok=True)
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not _is_writable_directory(config.cache_dir):
        fallback = _writable_cache_fallback()
        print(f"[Config] Cache dir is not writable: {config.cache_dir}; using {fallback}")
        config.cache_dir = fallback
        try:
            save_config(CONFIG_PATH, config)
        except Exception:
            pass
    if not CONFIG_PATH.exists():
        try:
            save_config(CONFIG_PATH, config)
        except Exception:
            pass
    return config


app_config = _sanitize_runtime_config(load_config(CONFIG_PATH))
service_downloader = ServiceDownloadManager(app_config)


playlists_lock = threading.Lock()
album_playlist_backfill_lock = threading.Lock()
album_playlist_backfill_in_progress: set[str] = set()
dock_recent_items_lock = threading.Lock()
_dock_recent_items: list[dict] = []

# Callbacks set by desktop.py for macOS Now Playing / Touch Bar integration
_np_update_fn = None   # (info: dict) -> None
_np_state_fn = None    # (state: int) -> None
_np_clear_fn = None    # () -> None
_macos_media_command_fn = None   # (action: str) -> None


def reverse_geocode_location(lat: float, lon: float) -> dict:
    url = "https://nominatim.openstreetmap.org/reverse?" + urlencode({
        "format": "jsonv2",
        "lat": f"{lat}",
        "lon": f"{lon}",
        "zoom": "18",
        "addressdetails": "1",
    })
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mindinguflac/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    address = data.get("address") or {}
    city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("hamlet") or ""
    state = address.get("state") or address.get("region") or address.get("province") or address.get("county") or ""
    country = address.get("country") or ""
    return {
        "city": city,
        "state": state,
        "country": country,
        "country_code": str(address.get("country_code") or "").upper(),
    }


def search_location_suggestions(term: str, limit: int = 6, country_code: str = "", state_code: str = "") -> list[dict]:
    term = str(term or "").strip()
    if not term:
        return []
    code = str(country_code or "").strip().upper()
    state = str(state_code or "").strip().upper()
    if code:
        try:
            from countrystatecity_countries import get_country_by_code, get_state_by_code, search_cities
            country = get_country_by_code(code)
            if country:
                cities = search_cities(code, state or None, term)
                if cities:
                    out: list[dict] = []
                    for item in cities[: max(1, min(10, int(limit or 6)))]:
                        state_obj = None
                        if item.state_code:
                            try:
                                state_obj = get_state_by_code(code, item.state_code)
                            except Exception:
                                state_obj = None
                        label = item.name
                        subtitle_parts = [state_obj.name if state_obj else "", country.name if country else ""]
                        subtitle = ", ".join(part for part in subtitle_parts if part)
                        out.append({
                            "label": label,
                            "city": item.name,
                            "state": state_obj.name if state_obj else "",
                            "country": country.name if country else "",
                            "country_code": code,
                            "lat": str(item.latitude or ""),
                            "lon": str(item.longitude or ""),
                            "subtitle": subtitle,
                        })
                    return out
        except Exception:
            pass
    url = "https://nominatim.openstreetmap.org/search?" + urlencode({
        "format": "jsonv2",
        "q": term,
        "addressdetails": "1",
        "limit": str(max(1, min(10, int(limit or 6)))),
    })
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mindinguflac/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or {}
        city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("hamlet") or item.get("name") or ""
        state = address.get("state") or address.get("region") or address.get("province") or address.get("county") or ""
        country = address.get("country") or ""
        country_code = str(address.get("country_code") or "").upper()
        label = city or item.get("display_name") or ""
        if state and state.lower() not in label.lower():
            label = f"{label}, {state}"
        if country and country.lower() not in label.lower():
            label = f"{label}, {country}"
        out.append({
            "label": label,
            "city": city,
            "state": state,
            "country": country,
            "country_code": country_code,
            "lat": item.get("lat") or "",
            "lon": item.get("lon") or "",
            "subtitle": ", ".join(part for part in [state, country] if part),
        })
    return out


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


def _track_match_key(track: dict) -> str:
    spotify_id = str(track.get("spotify_id") or track.get("track_key") or "").strip()
    if spotify_id:
        return spotify_id
    artist = str(track.get("artist") or "").strip().lower()
    title = str(track.get("title") or track.get("name") or "").strip().lower()
    album = str(track.get("album") or "").strip().lower()
    return "||".join([artist, title, album])


def _refresh_album_playlist_metadata(playlist: dict) -> bool:
    if not playlist or str(playlist.get("playlist_origin") or "").strip().lower() != "album":
        return False

    tracks = list(playlist.get("tracks") or [])
    seed = next(
        (
            track
            for track in tracks
            if isinstance(track, dict) and (track.get("artist") or track.get("album") or track.get("title") or track.get("spotify_id"))
        ),
        {},
    )
    artist = str(seed.get("artist") or playlist.get("owner") or "").strip()
    album = str(seed.get("album") or playlist.get("name") or "").strip()
    release_id = str(seed.get("musicbrainz_release_id") or "").strip()
    spotify_id = str(seed.get("spotify_id") or "").strip()
    if not artist or not album:
        return False

    refreshed = album_tracks(app_config, artist, album, release_id, spotify_id)
    hydrated_tracks = list(refreshed.get("tracks") or [])
    if not hydrated_tracks:
        return False

    merged_tracks = []
    used_keys = set()
    for track in hydrated_tracks:
        key = _track_match_key(track)
        used_keys.add(key)
        existing = next((saved for saved in tracks if _track_match_key(saved) == key), None)
        merged = merge_nonempty_track_metadata(existing or {}, track)
        if not str(merged.get("album") or "").strip():
            merged["album"] = album
        if not str(merged.get("artist") or "").strip():
            merged["artist"] = artist
        merged_tracks.append(merged)
    for saved in tracks:
        key = _track_match_key(saved)
        if key and key not in used_keys:
            saved = dict(saved)
            if not str(saved.get("album") or "").strip():
                saved["album"] = album
            if not str(saved.get("artist") or "").strip():
                saved["artist"] = artist
            merged_tracks.append(saved)

    playlist["tracks"] = merged_tracks
    if refreshed.get("artwork_url"):
        playlist["artwork_url"] = refreshed["artwork_url"]
    if refreshed.get("artist"):
        playlist["owner"] = refreshed["artist"]
    if refreshed.get("year"):
        playlist["year"] = refreshed["year"]
    playlist["metadata_fetched"] = True
    return True


def start_album_playlist_backfill(playlist_id: str) -> None:
    playlist_id = str(playlist_id or "").strip()
    if not playlist_id:
        return
    with album_playlist_backfill_lock:
        if playlist_id in album_playlist_backfill_in_progress:
            return
        album_playlist_backfill_in_progress.add(playlist_id)

    def run() -> None:
        try:
            with playlists_lock:
                data = load_playlists()
                playlist = next((entry for entry in data if entry.get("id") == playlist_id), None)
                if not playlist:
                    return
                if not _refresh_album_playlist_metadata(playlist):
                    return
                save_playlists(data)
        finally:
            with album_playlist_backfill_lock:
                album_playlist_backfill_in_progress.discard(playlist_id)

    threading.Thread(target=run, daemon=True, name=f"album-playlist-backfill-{playlist_id}").start()


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


_TRACK_KEY_PREFIXES = {"spotify_id", "isrc", "musicbrainz_recording_id", "musicbrainz_track_id", "deezer_id", "tidal_id"}

def _strip_track_key_prefix(key: str) -> str:
    if ":" in key:
        prefix, _, value = key.partition(":")
        if prefix in _TRACK_KEY_PREFIXES:
            return value
    return key


def playlist_track_key(track: dict) -> str:
    spotify_id = str(track.get("spotify_id") or track.get("track_key") or "").strip()
    if spotify_id:
        return spotify_id
    artist = str(track.get("artist") or "").strip().lower()
    title = str(track.get("title") or track.get("name") or "").strip().lower()
    return f"{artist}||{title}" if artist or title else ""


def enrich_download_payload(body: dict) -> dict:
    track = body.get("track") if isinstance(body.get("track"), dict) else {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else track
    source = {**metadata, **track}
    track_key = str(source.get("track_key") or body.get("track_key") or "").strip()
    if track_key:
        prefix, sep, value = track_key.partition(":")
        if sep and prefix in _TRACK_KEY_PREFIXES and value and not source.get(prefix):
            source[prefix] = value
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


def _spotify_import_playlist(spotify_url: str) -> dict:
    """Returns {name, artwork_url, description, owner, followers, tracks} from Spotify."""
    playlist_m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", spotify_url)
    album_m = re.search(r"(?:album/|spotify:album:)([A-Za-z0-9]+)", spotify_url)
    
    try:
        from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
        from spotiflac_compat import call_sync_or_async
        client = SpotifyMetadataClient()
        pl_year = ""
        
        if playlist_m:
            playlist_id = playlist_m.group(1)
            info, imported_tracks, playlist_cover = call_sync_or_async(
                client, "get_playlist_tracks", "get_playlist_tracks_async", playlist_id
            )
            pl_name = info.get("name", "")
            pl_artwork = info.get("cover_url", "") or playlist_cover
            pl_description = info.get("description", "") or ""
            pl_owner = info.get("owner", "") or ""
            pl_followers = info.get("followers", 0) or 0
        elif album_m:
            album_id = album_m.group(1)
            info, imported_tracks = call_sync_or_async(
                client, "get_album_tracks", "get_album_tracks_async", album_id
            )
            pl_name = info.get("name", "")
            pl_artwork = info.get("cover_url", "")
            pl_owner = info.get("artist") or info.get("artists") or ""
            if isinstance(pl_owner, list) and pl_owner:
                pl_owner = pl_owner[0]
            pl_description = f"Album by {pl_owner}" if pl_owner else ""
            pl_followers = 0
            pl_year = release_year(str(info.get("release_date") or info.get("date") or info.get("year") or ""))
        else:
            return {"name": "", "artwork_url": "", "description": "", "owner": "", "followers": 0, "tracks": []}

        tracks = []
        for track in imported_tracks:
            # Handle both objects and dictionaries
            def get_val(obj, key, default=""):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            t_id = get_val(track, "id") or get_val(track, "spotify_id")
            if not t_id:
                continue
                
            tracks.append({
                "type": "track",
                "title": get_val(track, "title") or get_val(track, "name"),
                "artist": get_val(track, "artists") or get_val(track, "artist"),
                "artist_id": get_val(track, "artist_id"),
                "album": get_val(track, "album"),
                "year": get_val(track, "year") or (pl_year if album_m else ""),
                "artwork_url": get_val(track, "cover_url") or get_val(track, "artwork_url"),
                "spotify_id": t_id,
                "spotify_url": get_val(track, "external_url") or f"https://open.spotify.com/track/{t_id}",
                "duration_ms": get_val(track, "duration_ms", 0),
                "isrc": get_val(track, "isrc"),
            })

        return {
            "name": pl_name, "artwork_url": pl_artwork, "description": pl_description,
            "owner": pl_owner, "followers": pl_followers, "year": pl_year if album_m else "", "tracks": tracks,
        }
    except Exception as e:
        print(f"[Spotify import] Error importing {spotify_url}: {e}")
        import traceback
        traceback.print_exc()
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
    results.sort(key=lambda item: search_relevance(term, item), reverse=True)
    return results[:limit]


def log_taste_cache_event(action: str, payload: dict) -> None:
    title = str(payload.get("title") or payload.get("artist") or payload.get("track_key") or "Taste").strip()
    artist = str(payload.get("artist") or "").strip()
    track = str(payload.get("title") or "").strip()
    label = track or artist or title
    prefix = {
        "manual_like": "Taste: like",
        "manual_remove_taste_profile": "Taste: remove profile",
        "manual_hard_blacklist": "Taste: blacklist",
        "manual_remove_hard_blacklist": "Taste: remove blacklist",
        "play": "Taste: listening",
        "skip": "Taste: skip",
        "complete": "Taste: complete",
    }.get(action, f"Taste: {action}")
    message = f"{prefix} - {label}"
    if artist and track and label != artist:
        message = f"{prefix} - {track} by {artist}"
    service_downloader.append_cache_event("taste", message, title=label)


def _seed_saved_track_taste(track: dict, playlist_origin: str) -> None:
    origin = str(playlist_origin or "").strip().lower()
    if origin not in {"manual", "album"} or not isinstance(track, dict):
        return
    payload = {
        "track_key": track.get("track_key") or "",
        "title": track.get("title") or track.get("name") or "",
        "artist": track.get("artist") or "",
        "album": track.get("album") or "",
        "duration_ms": int(track.get("duration_ms") or 0),
        "source_engine": track.get("source_engine") or track.get("source") or "",
        "source_service": track.get("source_service") or track.get("source") or "",
        "resolved_url": track.get("resolved_url") or track.get("url") or track.get("spotify_url") or "",
        "metadata": track.get("metadata") if isinstance(track.get("metadata"), dict) else dict(track),
        "event_type": "manual_like",
    }
    try:
        result = db.process_listening_event(payload)
        if result.get("ok"):
            log_taste_cache_event("manual_like", payload)
    except Exception:
        pass


def json_bytes(value: object) -> bytes:
    return json.dumps(value, indent=2).encode("utf-8")


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if not length:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _lyrics_field(payload: dict, key: str) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
    value = payload.get(key)
    if value in (None, ""):
        value = metadata.get(key)
    if value in (None, ""):
        value = track.get(key)
    return str(value or "").strip()


def _lyrics_duration_s(payload: dict) -> int:
    for key in ("duration_s", "duration", "duration_seconds"):
        value = _lyrics_field(payload, key)
        if value:
            try:
                return max(0, int(float(value)))
            except (TypeError, ValueError):
                pass
    for key in ("duration_ms", "durationMillis", "duration_millis"):
        value = _lyrics_field(payload, key)
        if value:
            try:
                return max(0, int(float(value) / 1000))
            except (TypeError, ValueError):
                pass
    return 0


def _lyrics_identity(payload: dict) -> dict:
    title = _lyrics_field(payload, "title") or _lyrics_field(payload, "name")
    artist = _lyrics_field(payload, "artist") or _lyrics_field(payload, "artists")
    album = _lyrics_field(payload, "album")
    spotify_id = _lyrics_field(payload, "spotify_id") or _lyrics_field(payload, "track_id")
    isrc = _lyrics_field(payload, "isrc")
    return {
        "title": title,
        "artist": artist,
        "album": album,
        "duration_s": _lyrics_duration_s(payload),
        "spotify_id": spotify_id,
        "isrc": isrc,
        "track_key": _lyrics_field(payload, "track_key"),
    }


def _lyrics_cache_key(identity: dict) -> str:
    preferred = {
        "spotify_id": identity.get("spotify_id") or "",
        "isrc": identity.get("isrc") or "",
        "title": (identity.get("title") or "").casefold(),
        "artist": (identity.get("artist") or "").casefold(),
        "album": (identity.get("album") or "").casefold(),
        "duration_s": int(identity.get("duration_s") or 0),
    }
    return hashlib.sha1(json.dumps(preferred, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _lyrics_is_synced(text: str) -> bool:
    return bool(re.search(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]", text or ""))


def _lyrics_cache_paths(identity: dict) -> tuple[Path, Path]:
    key = _lyrics_cache_key(identity)
    return LYRICS_DIR / f"{key}.lrc", LYRICS_DIR / f"{key}.json"


def _read_cached_lyrics(identity: dict) -> dict | None:
    lyrics_path, meta_path = _lyrics_cache_paths(identity)
    if not lyrics_path.exists():
        return None
    try:
        lyrics = lyrics_path.read_text(encoding="utf-8")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return {
            "ok": True,
            "found": bool(lyrics.strip()),
            "lyrics": lyrics,
            "provider": meta.get("provider") or "",
            "synced": bool(meta.get("synced")) or _lyrics_is_synced(lyrics),
            "source": "cache",
            "identity": identity,
        }
    except Exception:
        return None


def _write_cached_lyrics(identity: dict, lyrics: str, provider: str) -> None:
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    lyrics_path, meta_path = _lyrics_cache_paths(identity)
    lyrics_path.write_text(lyrics, encoding="utf-8")
    meta_path.write_text(json.dumps({
        "provider": provider,
        "synced": _lyrics_is_synced(lyrics),
        "identity": identity,
        "updated_at": int(time.time()),
    }, indent=2), encoding="utf-8")


def _fetch_lyrics(identity: dict) -> dict:
    cached = _read_cached_lyrics(identity)
    if cached:
        return cached
    if not identity.get("title") or not identity.get("artist"):
        return {"ok": False, "found": False, "error": "Missing title or artist", "identity": identity}
    try:
        from SpotiFLAC.core.lyrics import fetch_lyrics_async
        lyrics, provider = asyncio.run(fetch_lyrics_async(
            track_name=identity.get("title") or "",
            artist_name=identity.get("artist") or "",
            album_name=identity.get("album") or "",
            duration_s=int(identity.get("duration_s") or 0),
            track_id=identity.get("spotify_id") or "",
            isrc=identity.get("isrc") or "",
            providers=["spotify", "apple", "musixmatch", "lrclib", "amazon"],
        ))
        if lyrics and lyrics.strip():
            _write_cached_lyrics(identity, lyrics.strip(), provider or "")
            return {
                "ok": True,
                "found": True,
                "lyrics": lyrics.strip(),
                "provider": provider or "",
                "synced": _lyrics_is_synced(lyrics),
                "source": "fetch",
                "identity": identity,
            }
        return {"ok": True, "found": False, "lyrics": "", "provider": "", "synced": False, "source": "fetch", "identity": identity}
    except Exception as exc:
        return {"ok": False, "found": False, "error": str(exc), "identity": identity}


def _start_lyrics_prefetch(payload: dict) -> dict:
    identity = _lyrics_identity(payload)
    key = _lyrics_cache_key(identity)
    cached = _read_cached_lyrics(identity)
    if cached:
        return {"ok": True, "queued": False, "cached": True, "identity": identity}
    with lyrics_prefetch_lock:
        if key in lyrics_prefetch_inflight:
            return {"ok": True, "queued": True, "cached": False, "identity": identity}
        lyrics_prefetch_inflight.add(key)

    def _worker() -> None:
        try:
            _fetch_lyrics(identity)
        finally:
            with lyrics_prefetch_lock:
                lyrics_prefetch_inflight.discard(key)

    threading.Thread(target=_worker, name=f"lyrics-prefetch-{key[:8]}", daemon=True).start()
    return {"ok": True, "queued": True, "cached": False, "identity": identity}


def _video_norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _video_tokens(value: str) -> set[str]:
    ignored = {"a", "an", "and", "the", "feat", "ft", "official", "music", "video", "audio", "lyrics", "remaster", "hd"}
    return {part for part in _video_norm(value).split() if len(part) > 1 and part not in ignored}


def _video_identity(payload: dict) -> dict:
    return {
        "artist": _lyrics_field(payload, "artist"),
        "title": _lyrics_field(payload, "title") or _lyrics_field(payload, "name"),
        "album": _lyrics_field(payload, "album"),
        "duration_s": _lyrics_duration_s(payload),
        "track_key": _lyrics_field(payload, "track_key"),
        "spotify_id": _lyrics_field(payload, "spotify_id") or _lyrics_field(payload, "track_id"),
        "isrc": _lyrics_field(payload, "isrc"),
        "artist_id": _lyrics_field(payload, "artist_id") or _lyrics_field(payload, "spotify_artist_id"),
        "musicbrainz_recording_id": _lyrics_field(payload, "musicbrainz_recording_id") or _lyrics_field(payload, "musicbrainz_track_id"),
        "musicbrainz_artist_id": _lyrics_field(payload, "musicbrainz_artist_id"),
        "deezer_id": _lyrics_field(payload, "deezer_id"),
        "tidal_id": _lyrics_field(payload, "tidal_id"),
    }


def _video_cache_key(identity: dict) -> str:
    stable = {
        "version": VIDEO_CACHE_VERSION,
        "track_key": identity.get("track_key") or "",
        "spotify_id": identity.get("spotify_id") or "",
        "isrc": identity.get("isrc") or "",
    }
    if stable["track_key"] or stable["spotify_id"] or stable["isrc"]:
        value = stable
    else:
        value = {
            "version": VIDEO_CACHE_VERSION,
            "artist": _video_norm(identity.get("artist") or ""),
            "title": _video_norm(identity.get("title") or ""),
            "album": _video_norm(identity.get("album") or ""),
        }
    return hashlib.sha1(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _load_video_cache() -> dict:
    try:
        return json.loads(VIDEO_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_video_cache(cache: dict) -> None:
    try:
        VIDEO_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        VIDEO_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def _youtube_embed_url(webpage_url: str, video_id: str = "") -> str:
    vid = video_id
    if not vid:
        parsed = urlparse(webpage_url or "")
        if "youtu.be" in (parsed.netloc or ""):
            vid = parsed.path.strip("/")
        else:
            vid = parse_qs(parsed.query).get("v", [""])[0]
    return f"https://www.youtube.com/embed/{vid}?autoplay=1&rel=0" if vid else ""


def _youtube_video_id(entry_or_url) -> str:
    if isinstance(entry_or_url, dict):
        video_id = str(entry_or_url.get("id") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id
        webpage_url = str(entry_or_url.get("webpage_url") or entry_or_url.get("url") or "")
    else:
        webpage_url = str(entry_or_url or "")
    match = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", webpage_url)
    return match.group(1) if match else ""


def _music_video_start_offset(entry: dict, identity: dict) -> int:
    try:
        override = db.get_youtube_video_override(identity, youtube_url=entry.get("webpage_url") or entry.get("url") or "")
        if override:
            return max(0, int(override.get("start_offset_s") or 0))
    except Exception:
        pass
    video_id = _youtube_video_id(entry)
    artist_norm = _video_norm(identity.get("artist") or "")
    title_norm = _video_norm(identity.get("title") or "")
    entry_title = _video_norm(entry.get("title") or "")
    duration = entry.get("duration")
    try:
        duration_s = int(duration or 0)
    except Exception:
        duration_s = 0
    if "michael jackson" in artist_norm and "thriller" in title_norm:
        if video_id == "sOnqjkJTMaA" or ("thriller" in entry_title and duration_s >= 700):
            return 252
    if "michael jackson" in artist_norm and title_norm == "bad":
        if "bad" in entry_title and duration_s >= 900:
            return 815
    return 0


_VIDEO_MOVIE_TERMS = (
    "documentary",
    "feature film",
    "full film",
    "full movie",
    "movie",
    "short film",
    "soundtrack",
    "the film",
    "the movie",
    "trailer",
)


def _video_candidate_rejected(entry: dict, identity: dict) -> bool:
    if _music_video_start_offset(entry, identity) > 0:
        return False
    title_raw = str(entry.get("title") or "")
    channel_raw = str(entry.get("uploader") or entry.get("channel") or "")
    hay_norm = _video_norm(" ".join([title_raw, channel_raw]))
    if any(token in hay_norm for token in _VIDEO_MOVIE_TERMS):
        return True
    try:
        expected_duration = int(identity.get("duration_s") or 0)
        candidate_duration = int(entry.get("duration") or 0)
    except Exception:
        expected_duration = 0
        candidate_duration = 0
    if expected_duration > 0 and candidate_duration > 0:
        tolerance = max(45, int(expected_duration * 0.35))
        if candidate_duration > expected_duration + tolerance:
            return True
    return False


def _score_video_candidate(entry: dict, identity: dict) -> int:
    if _video_candidate_rejected(entry, identity):
        return -999
    title_raw = str(entry.get("title") or "")
    channel_raw = str(entry.get("uploader") or entry.get("channel") or "")
    haystack = " ".join([title_raw, channel_raw])
    hay_norm = _video_norm(haystack)
    title_norm = _video_norm(title_raw)
    channel_norm = _video_norm(channel_raw)
    artist_tokens = _video_tokens(identity.get("artist") or "")
    title_tokens = _video_tokens(identity.get("title") or "")
    score = 0
    if title_tokens:
        score += int(55 * (len(title_tokens & _video_tokens(title_raw)) / max(1, len(title_tokens))))
    if artist_tokens:
        score += int(30 * (len(artist_tokens & _video_tokens(haystack)) / max(1, len(artist_tokens))))
        # Bonus when the channel itself is the artist (e.g. "DireStraitsOfficial", "MichaelJacksonVEVO")
        if artist_tokens and artist_tokens <= _video_tokens(channel_norm):
            score += 20
    if "official" in hay_norm:
        score += 14
    if "music video" in hay_norm or "official video" in hay_norm:
        score += 16
    if "vevo" in channel_norm:
        score += 20
    # Non-official content — penalise hard so covers/tributes never beat the real thing
    if "cover" in title_norm:
        score -= 50
    if any(t in hay_norm for t in ("tribute", "reaction", "parody", "remix", "fan made", "fan video")):
        score -= 40
    # Static-image / audio-only uploads — no real video content
    if any(token in hay_norm for token in ("official audio", "audio only", "provided to youtube", "auto-generated", "topic")):
        score -= 40
    if any(token in hay_norm for token in ("lyrics", "lyric video", "visualizer", "karaoke")):
        score -= 24
    if any(token in hay_norm for token in ("live", "concert")):
        score -= 10
    # Movie / documentary / compilation — wrong content type
    if any(token in hay_norm for token in ("this is it", "documentary", "soundtrack", "the movie", "film", "trailer", "teaser", "short film")):
        score -= 50
    duration = entry.get("duration")
    if isinstance(duration, (int, float)) and duration:
        if 90 <= duration <= 720:
            score += 8
        elif duration > 1200:
            score -= 22
    return score


def _lookup_youtube_video(identity: dict) -> dict:
    if not identity.get("title") or not identity.get("artist"):
        return {"ok": False, "found": False, "error": "Missing title or artist", "identity": identity}
    key = _video_cache_key(identity)
    with video_cache_lock:
        cached = _load_video_cache().get(key)
    if cached:
        return {**cached, "source": "cache", "identity": identity}

    try:
        override = db.get_youtube_video_override(identity)
    except Exception:
        override = None
    if override and override.get("webpage_url"):
        url = str(override.get("webpage_url") or "")
        video_id = str(override.get("youtube_video_id") or _youtube_video_id(url))
        result = {
            "ok": True,
            "found": True,
            "source": "youtube_override",
            "title": override.get("video_title") or "",
            "uploader": override.get("channel_title") or "",
            "duration": override.get("duration_s") or 0,
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
            "webpage_url": url,
            "embed_url": _youtube_embed_url(url, video_id),
            "score": 1000,
            "video_start_offset": max(0, int(override.get("start_offset_s") or 0)),
            "identity": identity,
        }
        with video_cache_lock:
            cache = _load_video_cache()
            cache[key] = {k: v for k, v in result.items() if k != "identity"}
            _save_video_cache(cache)
        return result

    query = f'{identity["artist"]} {identity["title"]} official music video'
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "socket_timeout": 8,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch12:{query}", download=False)
        entries = [entry for entry in (info or {}).get("entries") or [] if isinstance(entry, dict)]
        scored = sorted(((_score_video_candidate(entry, identity), entry) for entry in entries), key=lambda item: item[0], reverse=True)

        # AI advisor runs in a thread with a timeout so a slow Duck.ai never
        # stalls the download. It both reranks candidates and can suggest a
        # known official URL directly from training data.
        best_entry = None
        best_score = -1
        suggested_url = ""
        try:
            import ai_reranker
            ai_provider = getattr(app_config, "ai_provider", "duckai")
            if ai_reranker.is_enabled(ai_provider) and scored:
                target = {
                    "title": identity.get("title") or "",
                    "artist": identity.get("artist") or "",
                    "album": identity.get("album") or "",
                    "duration": 0,
                }
                id_to_entry: dict[int, tuple[int, dict]] = {}
                ai_candidates = []
                for idx, (sc, entry) in enumerate(scored[:12], start=1):
                    video_id = str(entry.get("id") or "")
                    url = entry.get("webpage_url") or entry.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
                    id_to_entry[idx] = (sc, entry)
                    ai_candidates.append({
                        "id": idx,
                        "title": entry.get("title") or url,
                        "source": entry.get("uploader") or entry.get("channel") or "YouTube",
                        "seeders": 0,
                        "score": sc,
                        "query": "youtube",
                        "url": url,
                    })
                duck_model = getattr(app_config, "duck_model", "1")
                gemini_model = getattr(app_config, "gemini_model", "gemini-1.5-flash")
                ai_result: dict = {}
                ai_done = threading.Event()

                def _run_video_ai() -> None:
                    try:
                        ranked = ai_reranker.rank_candidates(
                            target, ai_candidates, duck_model, ai_provider, gemini_model,
                            include_urls=True, video_mode=True,
                        )
                        if isinstance(ranked, dict):
                            ai_result.update(ranked)
                        elif isinstance(ranked, list):
                            ai_result["ranked_ids"] = ranked
                    except Exception:
                        pass
                    finally:
                        ai_done.set()

                threading.Thread(target=_run_video_ai, daemon=True, name="video-ai-lookup").start()
                ai_done.wait(timeout=45)

                ranked_ids = ai_result.get("ranked_ids")
                suggested_url = str(ai_result.get("suggested_url") or "").strip()
                if not suggested_url and isinstance(ranked_ids, list):
                    for value in ranked_ids:
                        try:
                            item = id_to_entry.get(int(value))
                        except Exception:
                            item = None
                        if item:
                            best_score, best_entry = item
                            break
        except Exception:
            pass

        if best_entry is None and not suggested_url and scored and scored[0][0] >= 58:
            best_score, best_entry = scored[0]

        if suggested_url:
            # AI knows the official URL directly — use it, metadata resolved on download
            video_id = ""
            m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", suggested_url)
            if m:
                video_id = m.group(1)
            start_offset = _music_video_start_offset(
                {"id": video_id, "webpage_url": suggested_url, "title": identity.get("title") or "", "duration": 0},
                identity,
            )
            result = {
                "ok": True,
                "found": True,
                "source": "youtube_ai",
                "title": "",
                "uploader": "",
                "duration": 0,
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else "",
                "webpage_url": suggested_url,
                "embed_url": _youtube_embed_url(suggested_url, video_id),
                "score": 999,
                "video_start_offset": start_offset,
                "identity": identity,
            }
        elif not best_entry or best_score < 40:
            result = {"ok": True, "found": False, "source": "youtube", "identity": identity}
        else:
            video_id = str(best_entry.get("id") or "")
            url = best_entry.get("webpage_url") or best_entry.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
            start_offset = _music_video_start_offset({**best_entry, "webpage_url": url}, identity)
            result = {
                "ok": True,
                "found": True,
                "source": "youtube",
                "title": best_entry.get("title") or "",
                "uploader": best_entry.get("uploader") or best_entry.get("channel") or "",
                "duration": best_entry.get("duration") or 0,
                "thumbnail": best_entry.get("thumbnail") or "",
                "webpage_url": url,
                "embed_url": _youtube_embed_url(url, video_id),
                "score": best_score,
                "video_start_offset": start_offset,
                "identity": identity,
            }
        with video_cache_lock:
            cache = _load_video_cache()
            cache[key] = {k: v for k, v in result.items() if k != "identity"}
            _save_video_cache(cache)
        return result
    except Exception as exc:
        return {"ok": False, "found": False, "error": str(exc), "source": "youtube", "identity": identity}


def _try_votify_video_fetch(identity: dict, mp4_path: Path) -> bool:
    try:
        from backend_ytpdl import _ffmpeg_location, _spotify_track_url, _votify_command
        from service_downloader import _find_audio_files
    except Exception:
        return False
    spotify_url = _spotify_track_url({"metadata": identity, **identity})
    if not spotify_url:
        return False
    cmd = _votify_command()
    if not cmd:
        return False
    import subprocess

    VIDEO_FILES_DIR.mkdir(parents=True, exist_ok=True)
    votify_dir = VIDEO_FILES_DIR / f"{mp4_path.stem}.votify"
    temp_dir = votify_dir / ".temp"
    before = {path.resolve() for path in votify_dir.rglob("*") if path.is_file()} if votify_dir.exists() else set()
    args = [
        *cmd,
        spotify_url,
        "--prefer-video",
        "--output", str(votify_dir),
        "--temp", str(temp_dir),
        "--video-format", "mp4",
        "--video-remux-mode", "ffmpeg",
        "--overwrite",
    ]
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        args.extend(["--ffmpeg-path", ffmpeg])
    try:
        result = subprocess.run(args, cwd=str(VIDEO_FILES_DIR), capture_output=True, text=True, timeout=900)
    except Exception:
        return False
    if result.returncode != 0:
        return False
    produced = [path for path in _find_audio_files(votify_dir) if path.resolve() not in before]
    if not produced:
        produced = _find_audio_files(votify_dir)
    videos = [path for path in produced if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}]
    if not videos:
        return False
    videos.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    source = videos[0]
    tmp_path = mp4_path.with_suffix(".votify.tmp.mp4")
    try:
        shutil.copy2(source, tmp_path)
        if tmp_path.stat().st_size <= 65536:
            tmp_path.unlink(missing_ok=True)
            return False
        tmp_path.replace(mp4_path)
        return True
    except Exception:
        tmp_path.unlink(missing_ok=True)
        return False


def _download_youtube_video_bg(identity: dict, key: str) -> None:
    mp4_path = VIDEO_FILES_DIR / f"{key}.mp4"
    tmp_path = VIDEO_FILES_DIR / f"{key}.tmp.mp4"
    try:
        try:
            override = db.get_youtube_video_override(identity)
        except Exception:
            override = None

        # Try backend_video torrent clip search first (own session, parallel with music downloads)
        if not override:
            try:
                import backend_video
                _vid_title = f"{identity.get('artist', '')} – {identity.get('title', '')}".strip(" –")
                def _vid_log(msg, _t=_vid_title):
                    service_downloader.append_cache_event("trying", msg, title=_t)
                if backend_video.fetch_clip_to_path(identity, mp4_path, log_cb=_vid_log):
                    with _video_fetch_lock:
                        _video_fetch_jobs[key] = "ready"
                    return
            except Exception:
                pass

        lookup = _lookup_youtube_video(identity)
        if not lookup.get("found") or not lookup.get("webpage_url"):
            with _video_fetch_lock:
                _video_fetch_jobs[key] = "failed"
            return
        url = lookup["webpage_url"]
        start_offset = int(lookup.get("video_start_offset") or 0)
        VIDEO_FILES_DIR.mkdir(parents=True, exist_ok=True)
        import yt_dlp
        # H.264 + AAC mp4 for Safari/WKWebView compatibility.
        # Fallback chain: prefer avc≤480p, then any avc, then any mp4, then best.
        opts = {
            "format": (
                "bestvideo[vcodec^=avc][height<=480]+bestaudio[ext=m4a]/"
                "bestvideo[vcodec^=avc][height<=480]+bestaudio/"
                "bestvideo[vcodec^=avc]+bestaudio[ext=m4a]/"
                "bestvideo[vcodec^=avc]+bestaudio/"
                "bestvideo[height<=480]+bestaudio[ext=m4a]/"
                "bestvideo[height<=480]+bestaudio/"
                "bestvideo+bestaudio/"
                "best"
            ),
            "merge_output_format": "mp4",
            "outtmpl": str(tmp_path),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 3,
            "fragment_retries": 3,
            "http_chunk_size": 10 * 1024 * 1024,  # avoids 416 range errors on retries
        }
        if start_offset > 0:
            from yt_dlp.utils import download_range_func
            opts["download_ranges"] = download_range_func(None, [(start_offset, None)])
            opts["force_keyframes_at_cuts"] = True
        from backend_ytpdl import _add_youtube_cookie_file, _ffmpeg_location
        ffmpeg = _ffmpeg_location()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        # Prefer an explicit cookies.txt file, then browser cookies, then no cookies.
        def _try_download(download_opts: dict) -> bool:
            tmp_path.unlink(missing_ok=True)
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                ydl.download([url])
            return tmp_path.exists() and tmp_path.stat().st_size > 65536

        downloaded = False
        attempts = []
        cookie_opts = dict(opts)
        if _add_youtube_cookie_file(cookie_opts):
            attempts.append(cookie_opts)
        for _browser in ("safari", "chrome", "firefox"):
            attempt_opts = dict(opts)
            attempt_opts["cookiesfrombrowser"] = (_browser,)
            attempts.append(attempt_opts)
        attempts.append(dict(opts))

        for attempt_opts in attempts:
            try:
                downloaded = _try_download(attempt_opts)
                if downloaded:
                    break
            except Exception:
                tmp_path.unlink(missing_ok=True)
                continue

        if downloaded:
            tmp_path.rename(mp4_path)
            with _video_fetch_lock:
                _video_fetch_jobs[key] = "ready"
        else:
            tmp_path.unlink(missing_ok=True)
            with _video_fetch_lock:
                _video_fetch_jobs[key] = "failed"
    except Exception as exc:
        print(f"[VideoFetch] Download failed for key {key}: {exc}")
        tmp_path.unlink(missing_ok=True)
        with _video_fetch_lock:
            _video_fetch_jobs[key] = "failed"


def _get_video_fetch(identity: dict, force: bool = False) -> dict:
    if not identity.get("title") or not identity.get("artist"):
        return {"status": "not_found"}
    key = _video_cache_key(identity)
    mp4_path = VIDEO_FILES_DIR / f"{key}.mp4"
    if force:
        mp4_path.unlink(missing_ok=True)
        with video_cache_lock:
            cache = _load_video_cache()
            cache.pop(key, None)
            _save_video_cache(cache)
        with _video_fetch_lock:
            _video_fetch_jobs.pop(key, None)
    if mp4_path.exists() and mp4_path.stat().st_size > 65536:
        return {"status": "ready", "path": str(mp4_path)}
    with _video_fetch_lock:
        job_status = _video_fetch_jobs.get(key)
    if job_status == "ready":
        return {"status": "ready", "path": str(mp4_path)} if mp4_path.exists() else {"status": "not_found"}
    if job_status == "downloading":
        return {"status": "downloading"}
    if job_status == "failed":
        return {"status": "not_found"}
    with _video_fetch_lock:
        _video_fetch_jobs[key] = "downloading"
    threading.Thread(target=_download_youtube_video_bg, args=(identity, key), daemon=True).start()
    return {"status": "downloading"}


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

    if suffix_name.endswith((".mp4", ".mov")):
        return "video/mp4"
    if suffix_name.endswith(".webm"):
        return "video/webm"
    if b"ftyp" in header[:16] or suffix_name.endswith((".m4a", ".aac")):
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
    server_version = "SpotiFLACStreamer/1.2.2"
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
            if path == "/api/test/hypebot/concerts":
                import hypebot_tour
                artist = query.get("artist", [""])[0].strip()
                letter = query.get("letter", [""])[0].strip()
                url = query.get("url", [""])[0].strip()
                try:
                    limit = max(1, min(10, int(query.get("limit", ["1"])[0] or 1)))
                except Exception:
                    limit = 1
                try:
                    timeout_s = max(1.0, min(30.0, float(query.get("timeout_s", ["15"])[0] or 15)))
                except Exception:
                    timeout_s = 15.0
                if not artist and not letter and not url:
                    self.send_error_json("Missing artist, letter, or url", HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(hypebot_tour.fetch_artist_concerts(
                    artist=artist,
                    letter=letter,
                    url=url,
                    limit=limit,
                    timeout=timeout_s,
                ))
                return
            if path == "/api/settings":
                print(f"[API] GET /api/settings -> {app_config.cache_dir}, {app_config.music_dir}")
                settings_dict = app_config.public_dict()
                settings_dict["native_now_playing_active"] = bool(_np_update_fn)
                self.send_json(settings_dict)
                return
            if path == "/api/lyrics":
                payload = {key: values[0] for key, values in query.items() if values}
                result = _fetch_lyrics(_lyrics_identity(payload))
                self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY)
                return
            if path == "/api/video/lookup":
                payload = {key: values[0] for key, values in query.items() if values}
                result = _lookup_youtube_video(_video_identity(payload))
                self.send_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY)
                return
            if path == "/api/video/fetch":
                payload = {key: values[0] for key, values in query.items() if values}
                force = payload.get("force", "") in ("1", "true")
                result = _get_video_fetch(_video_identity(payload), force=force)
                self.send_json(result, HTTPStatus.OK)
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
                    playlists = load_playlists()
                for playlist in playlists:
                    if str(playlist.get("playlist_origin") or "").strip().lower() == "album":
                        tracks = list(playlist.get("tracks") or [])
                        needs_backfill = not playlist.get("metadata_fetched") or any(
                            not (track.get("plays") or track.get("album") or track.get("artist"))
                            for track in tracks
                            if isinstance(track, dict)
                        )
                        if needs_backfill:
                            start_album_playlist_backfill(playlist.get("id", ""))
                self.send_json(playlists)
                return
            m = re.fullmatch(r"/api/playlists/([^/]+)/recommendations", path)
            if m:
                playlist_id = m.group(1)
                limit = int(query.get("limit", ["10"])[0] or 10)
                refresh = query.get("refresh", ["0"])[0] in {"1", "true", "True"}
                session_id = query.get("session_id", [""])[0].strip() or None
                exclude = {
                    _strip_track_key_prefix(key.strip())
                    for key in (query.get("exclude", [""])[0] or "").split(",")
                    if key.strip()
                }
                queue_track_keys = {
                    _strip_track_key_prefix(key.strip())
                    for key in (query.get("queue_track_keys", [""])[0] or "").split(",")
                    if key.strip()
                }
                self.send_json(generate_playlist_recommendations(
                    playlist_id,
                    limit=limit,
                    refresh=refresh,
                    exclude_track_keys=exclude,
                    queue_track_keys=queue_track_keys,
                    session_id=session_id,
                ))
                return
            if path == "/api/taste/liked":
                self.send_json({"items": db.get_liked_tracks()})
                return
            if path == "/api/taste/blacklist":
                self.send_json({
                    "soft_blacklisted": db.get_soft_blacklisted_tracks(),
                    "hard_blacklisted": db.get_hard_blacklisted_tracks(),
                })
                return
            if path == "/api/stats/listened":
                track_key = query.get("track_key", [""])[0].strip() or None
                artist = query.get("artist", [""])[0].strip() or None
                period = query.get("period", ["all"])[0].strip() or "all"
                self.send_json(db.get_listened_time(track_key, artist, period))
                return
            if path == "/api/stats/summary":
                period = query.get("period", ["month"])[0].strip() or "month"
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                _mr = query.get("months", [""])[0].strip()
                months = [int(m) for m in _mr.split(",") if m.strip().isdigit()] if _mr else None
                self.send_json(db.get_stats_summary(period, year=year, month=month, months=months))
                return
            if path == "/api/stats/top-listened-tracks":
                period = query.get("period", ["month"])[0].strip() or "month"
                limit = int(query.get("limit", ["10"])[0] or 10)
                offset = int(query.get("offset", ["0"])[0] or 0)
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                _mr = query.get("months", [""])[0].strip()
                months = [int(m) for m in _mr.split(",") if m.strip().isdigit()] if _mr else None
                self.send_json(db.get_top_listened_tracks(period, limit=limit, offset=offset, year=year, month=month, months=months))
                return
            if path == "/api/stats/top-listened-artists":
                period = query.get("period", ["month"])[0].strip() or "month"
                limit = int(query.get("limit", ["10"])[0] or 10)
                offset = int(query.get("offset", ["0"])[0] or 0)
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                _mr = query.get("months", [""])[0].strip()
                months = [int(m) for m in _mr.split(",") if m.strip().isdigit()] if _mr else None
                self.send_json(db.get_top_listened_artists(period, limit=limit, offset=offset, year=year, month=month, months=months))
                return
            if path == "/api/stats/top-listened-albums":
                period = query.get("period", ["month"])[0].strip() or "month"
                limit = int(query.get("limit", ["10"])[0] or 10)
                offset = int(query.get("offset", ["0"])[0] or 0)
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                _mr = query.get("months", [""])[0].strip()
                months = [int(m) for m in _mr.split(",") if m.strip().isdigit()] if _mr else None
                self.send_json(db.get_top_listened_albums(period, limit=limit, offset=offset, year=year, month=month, months=months))
                return
            if path == "/api/stats/listening-over-time":
                period = query.get("period", ["month"])[0].strip() or "month"
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                bucket = query.get("bucket", [""])[0].strip() or None
                # months=1,2,3 from multiselect filter
                months_raw = query.get("months", [""])[0].strip()
                months_list = [int(m) for m in months_raw.split(",") if m.strip().isdigit()] if months_raw else None
                self.send_json(db.get_listening_over_time(period, bucket=bucket, year=year, month=month, months=months_list))
                return
            if path == "/api/stats/top-genres":
                period = query.get("period", ["month"])[0].strip() or "month"
                limit = int(query.get("limit", ["10"])[0] or 10)
                offset = int(query.get("offset", ["0"])[0] or 0)
                year = query.get("year", [""])[0].strip() or None
                month = query.get("month", [""])[0].strip() or None
                _mr = query.get("months", [""])[0].strip()
                months = [int(m) for m in _mr.split(",") if m.strip().isdigit()] if _mr else None
                self.send_json(db.get_top_genres(period, limit=limit, offset=offset, year=year, month=month, months=months))
                return
            if path == "/api/taste/track":
                track_key = query.get("track_key", [""])[0].strip()
                self.send_json(db.get_track_affinity(track_key) or {})
                return
            if path == "/api/taste/artist":
                artist = query.get("artist", [""])[0].strip()
                self.send_json(db.get_artist_affinity(artist) or {})
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
            if path == "/api/gemini/status":
                import gemini_proxy
                self.send_json(gemini_proxy.fetch_status())
                return
            if path == "/api/location/reverse":
                try:
                    lat = float(query.get("lat", [""])[0])
                    lon = float(query.get("lon", [""])[0])
                except Exception:
                    self.send_error_json("Invalid coordinates", HTTPStatus.BAD_REQUEST)
                    return
                try:
                    self.send_json(reverse_geocode_location(lat, lon))
                except Exception as exc:
                    self.send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
                return
            if path == "/api/location/search":
                term = query.get("term", [""])[0].strip()
                country_code = query.get("country_code", [""])[0].strip()
                state_code = query.get("state_code", [""])[0].strip()
                if not term:
                    self.send_json({"results": []})
                    return
                try:
                    self.send_json({"results": search_location_suggestions(term, country_code=country_code, state_code=state_code)})
                except Exception as exc:
                    self.send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
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
                audio_only = query.get("audio", [""])[0] == "1"
                self.stream_local_path(file_path, audio_hint=audio_only)
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
                # If the candidate file is already fully on disk, serve it with
                # Content-Length + Accept-Ranges instead of chunked encoding.
                # Chunked encoding confuses WebKit's <audio> element for FLAC
                # files (it buffers indefinitely without ever starting playback).
                try:
                    active_audio_size = int(job.get("active_audio_size") or 0)
                    active_audio_ready = int(job.get("active_audio_ready_bytes") or 0)
                    file_complete = active_audio_size > 0 and active_audio_ready >= active_audio_size
                except (OSError, TypeError, ValueError):
                    file_complete = False
                self.stream_local_path(candidate, is_active_job=not is_finished and not file_complete, audio_hint=True)
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
        global app_config, service_downloader
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
            if path == "/api/lyrics/prefetch":
                items = body.get("tracks") if isinstance(body.get("tracks"), list) else [body]
                results = [_start_lyrics_prefetch(item if isinstance(item, dict) else {}) for item in items[:10]]
                self.send_json({"ok": True, "results": results})
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
            if path == "/api/listening/event":
                result = db.process_listening_event(body)
                if result.get("ok"):
                    log_taste_cache_event(str(body.get("event_type") or "play"), body)
                self.send_json(result)
                return
            if path == "/api/taste/manual-like":
                payload = dict(body or {})
                payload["event_type"] = "manual_like"
                result = db.process_listening_event(payload)
                if result.get("ok"):
                    resolved_url = str(payload.get("resolved_url") or payload.get("spotify_url") or payload.get("url") or "").strip()
                    if resolved_url:
                        db.remove_from_blacklist(resolved_url)
                    log_taste_cache_event("manual_like", payload)
                self.send_json(result)
                return
            if path == "/api/taste/remove-from-taste-profile":
                payload = dict(body or {})
                payload["event_type"] = "manual_remove_taste_profile"
                result = db.process_listening_event(payload)
                if result.get("ok"):
                    log_taste_cache_event("manual_remove_taste_profile", payload)
                self.send_json(result)
                return
            if path == "/api/taste/manual-hard-blacklist":
                payload = dict(body or {})
                payload["event_type"] = "manual_hard_blacklist"
                result = db.process_listening_event(payload)
                if result.get("ok"):
                    resolved_url = str(payload.get("resolved_url") or payload.get("spotify_url") or payload.get("url") or "").strip()
                    if resolved_url:
                        db.add_to_blacklist(resolved_url, "manual taste blacklist", [str(payload.get("track_key") or "").strip()])
                    log_taste_cache_event("manual_hard_blacklist", payload)
                self.send_json(result)
                return
            m = re.fullmatch(r"/api/playlists/([^/]+)/recommendations/replacement", path)
            if m:
                playlist_id = m.group(1)
                exclude = {_strip_track_key_prefix(str(key).strip()) for key in (body.get("exclude_track_keys") or []) if str(key).strip()}
                queue_track_keys = {_strip_track_key_prefix(str(key).strip()) for key in (body.get("queue_track_keys") or []) if str(key).strip()}
                item = generate_one_replacement_recommendation(
                    playlist_id,
                    exclude,
                    queue_track_keys=queue_track_keys,
                    session_id=body.get("session_id") or None,
                )
                self.send_json({"item": item})
                return
            m = re.fullmatch(r"/api/playlists/([^/]+)/recommendations/([^/]+)/dismiss", path)
            if m:
                playlist_id, track_key = m.group(1), m.group(2)
                record_recommendation_feedback(playlist_id, track_key, "dismissed", body.get("session_id") or None)
                self.send_json({"ok": True})
                return
            m = re.fullmatch(r"/api/playlists/([^/]+)/recommendations/([^/]+)/feedback", path)
            if m:
                playlist_id, track_key = m.group(1), m.group(2)
                action = str(body.get("action") or "").strip()
                if not action:
                    self.send_error_json("Missing action", HTTPStatus.BAD_REQUEST)
                    return
                record_recommendation_feedback(playlist_id, track_key, action, body.get("session_id") or None)
                self.send_json({"ok": True})
                return
            if path == "/api/artist/about":
                try:
                    from music_metadata import artist_about
                    self.send_json(artist_about(body.get("artist_id"), body.get("name")))
                except Exception as _e:
                    self.send_json({"error": str(_e), "monthly_listeners": 0, "followers": 0, "biography": "", "avatar": "", "gallery": [], "related_artists": []})
                return
            if path == "/api/artist/related":
                from music_metadata import related_artists
                self.send_json(related_artists(body.get("artist_id", ""), body.get("name", ""), limit=int(body.get("limit") or 8)))
                return
            if path == "/api/artist/top_tracks":
                from music_metadata import spotify_artist_top_tracks
                self.send_json({"tracks": spotify_artist_top_tracks(body.get("name"), artist_id=body.get("artist_id"))})
                return
            if path == "/api/artist/tour":
                tour_url = (
                    body.get("url")
                    or body.get("hypebot_url")
                    or body.get("artist_url")
                    or body.get("page_url")
                    or ""
                )
                self.send_json(artist_tour(
                    body.get("artist_id", ""),
                    body.get("name") or body.get("artist", ""),
                    live=bool(body.get("live")),
                    refresh=bool(body.get("refresh")),
                    ai_provider=app_config.ai_provider,
                    gemini_model=app_config.gemini_model,
                    timeout_s=float(body.get("timeout_s") or 0) or None,
                    tour_source=app_config.tour_source,
                    tour_url=str(tour_url or "").strip(),
                ))
                return
            if path == "/api/track/credits":
                self.send_json(track_credits(body.get("track") or body))
                return
            if path == "/api/music/enrich":
                import queue as _queue
                tracks = body.get("tracks") or []
                _result_q: _queue.Queue = _queue.Queue()
                def _run_enrich():
                    try:
                        _result_q.put(enrich_artwork_batch(tracks))
                    except Exception:
                        _result_q.put(None)
                threading.Thread(target=_run_enrich, daemon=True).start()
                try:
                    enriched = _result_q.get(timeout=8) or tracks
                except _queue.Empty:
                    enriched = tracks
                self.send_json({"tracks": enriched})
                return

            m = re.fullmatch(r"/api/playlists/([^/]+)/tracks", path)
            if m:
                playlist_id = m.group(1)
                track = body.get("track") if isinstance(body.get("track"), dict) else body
                if not isinstance(track, dict):
                    self.send_error_json("Missing track payload", HTTPStatus.BAD_REQUEST)
                    return
                action = str(body.get("action") or "add").strip().lower()
                source = str(body.get("source") or "").strip().lower()
                session_id = str(body.get("session_id") or "").strip() or None
                track = dict(track)
                track.setdefault("track_key", playlist_track_key(track))
                with playlists_lock:
                    data = load_playlists()
                    pl = next((p for p in data if p["id"] == playlist_id), None)
                    if not pl:
                        self.send_error_json("Playlist not found", HTTPStatus.NOT_FOUND)
                        return

                    def same_track(t):
                        if track.get("spotify_id") and t.get("spotify_id"):
                            return t["spotify_id"] == track["spotify_id"]
                        if track.get("track_key") and t.get("track_key"):
                            return t["track_key"] == track["track_key"]
                        return (
                            t.get("title", "").lower() == track.get("title", "").lower()
                            and t.get("artist", "").lower() == track.get("artist", "").lower()
                        )

                    existing = next((t for t in pl["tracks"] if same_track(t)), None)
                    if action == "remove":
                        pl["tracks"] = [t for t in pl["tracks"] if not same_track(t)]
                        in_playlist = False
                    else:
                        if not existing:
                            pl["tracks"].append(track)
                            in_playlist = True
                        else:
                            in_playlist = True
                    save_playlists(data)
                if in_playlist and not existing:
                    threading.Thread(
                        target=enrich_and_persist_track,
                        args=(track,),
                        daemon=True,
                        name="playlist-track-enrich",
                    ).start()
                if source == "recommendation" and session_id:
                    record_recommendation_feedback(playlist_id, track.get("track_key", ""), "added", session_id)
                self.send_json({"ok": True, "in_playlist": in_playlist, "track": track})
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

                    seen_keys = {_track_match_key(t) for t in pl.get("tracks", [])}
                    added_count = 0
                    changed_existing = False
                    added_tracks: list[dict] = []
                    for t in tracks_to_add:
                        enriched = enrich_track_identifiers(dict(t))
                        key = _track_match_key(enriched)
                        existing = next((saved for saved in pl.get("tracks", []) if _track_match_key(saved) == key), None)
                        if existing:
                            merged = merge_nonempty_track_metadata(existing, enriched)
                            if merged != existing:
                                idx = pl["tracks"].index(existing)
                                pl["tracks"][idx] = merged
                                changed_existing = True
                            seen_keys.add(key)
                            continue
                        if key not in seen_keys:
                            pl["tracks"].append(enriched)
                            seen_keys.add(key)
                            added_tracks.append(enriched)
                            added_count += 1
                    if str(pl.get("playlist_origin") or "").strip().lower() == "album":
                        _refresh_album_playlist_metadata(pl)
                    if added_count > 0 or changed_existing or str(pl.get("playlist_origin") or "").strip().lower() == "album":
                        save_playlists(data)
                if added_count > 0:
                    origin = str(pl.get("playlist_origin") or "").strip().lower()
                    if origin in {"manual", "album"}:
                        for enriched in added_tracks:
                            _seed_saved_track_taste(enriched, origin)
                if added_count > 0:
                    start_playlist_identifier_enrichment(playlist_id)
                
                self.send_json({"ok": True, "added": added_count})
                return
            if path == "/api/settings":
                updated = _sanitize_runtime_config(AppConfig.from_public_dict(body))
                with config_lock:
                    app_config = updated
                    save_config(CONFIG_PATH, app_config)
                    service_downloader.update_config(app_config)
                self.send_json({"ok": True})
                return
            if path == "/api/playlists":
                user_name = body.get("name", "").strip()
                spotify_url = body.get("spotify_url", "").strip()
                origin = str(body.get("origin") or "manual").strip().lower() or "manual"
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
                    "year": imported.get("year", ""),
                    "spotify_url": spotify_url,
                    "playlist_origin": origin,
                    "tracks": imported["tracks"],
                    "metadata_fetched": bool(spotify_url and imported["tracks"] and (origin != "album" or imported.get("year"))),
                    "created_at": time.time(),
                }
                with playlists_lock:
                    data = load_playlists()
                    data.append(playlist)
                    save_playlists(data)
                if imported["tracks"] and origin in {"manual", "album"}:
                    for track in imported["tracks"]:
                        _seed_saved_track_taste(track, origin)
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
                    _seed_saved_track_taste(track, pl.get("playlist_origin") or "")
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
            if path == "/api/gemini/chat":
                import gemini_proxy
                self.send_json(gemini_proxy.send_chat(
                    prompt=body.get("prompt", ""),
                    messages=body.get("messages", []),
                    ensure_model=body.get("model", "flash"),
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
                raw_volume = body.get("volume", 1)
                raw_position = body.get("position", 0)
                self.send_json(native_audio.play(
                    body.get("path", ""),
                    body.get("device_uid", ""),
                    float(1 if raw_volume is None else raw_volume),
                    float(0 if raw_position is None else raw_position),
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
                raw_position = body.get("position", 0)
                self.send_json(native_audio.seek(float(0 if raw_position is None else raw_position)))
                return
            if path == "/api/native_audio/volume":
                raw_volume = body.get("volume", 1)
                self.send_json(native_audio.set_volume(float(1 if raw_volume is None else raw_volume)))
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
                # Also clear fetched music video files and their lookup cache
                try:
                    for _vf in VIDEO_FILES_DIR.glob("*.mp4"):
                        _vf.unlink(missing_ok=True)
                    VIDEO_CACHE_PATH.unlink(missing_ok=True)
                    with _video_fetch_lock:
                        _video_fetch_jobs.clear()
                except Exception:
                    pass
                # Clear transient YouTube blacklist entries (403/bot-detection blocks
                # accumulate during a session and poison future searches)
                try:
                    db.clear_youtube_blacklist()
                except Exception:
                    pass
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

    def stream_local_path(self, path: Path, is_active_job: bool = False, audio_hint: bool = False) -> None:
        try:
            size = path.stat().st_size
            if is_active_job:
                mime = _sniff_audio_mime(path)
            else:
                mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
            # <audio> element can't play video/mp4 reliably; use audio/mp4 for audio requests
            if audio_hint and mime == "video/mp4":
                mime = "audio/mp4"

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


def _shutdown_browser_workers() -> None:
    for mod_name, fn_name in (("duck_proxy", "shutdown"), ("gemini_proxy", "shutdown")):
        try:
            module = __import__(mod_name)
            getattr(module, fn_name)()
        except Exception:
            pass


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8888"))
    server = create_server(host, port)
    print(f"Serving on http://{host}:{port}")
    shutting_down = False

    def _handle_signal(signum, frame):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        _shutdown_browser_workers()
        try:
            server.shutdown()
        except Exception:
            pass

    try:
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
    except Exception:
        pass
    try:
        server.serve_forever()
    finally:
        _shutdown_browser_workers()
        apply_shutdown_cache_cleanup()


if __name__ == "__main__":
    main()
