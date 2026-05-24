from __future__ import annotations

import json
import mimetypes
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
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from catalog import discover_catalog
from config import AppConfig, app_data_dir, load_config, save_config
from music_metadata import album_metadata, album_tracks, artist_page, build_music_indexers, enrich_albums_batch, enrich_artwork_batch, search_music, search_relevance
from service_downloader import ServiceDownloadManager, is_download_audio_candidate, is_valid_audio_file


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = app_data_dir()
CONFIG_PATH = DATA / "config.json"
PLAYLISTS_PATH = DATA / "playlists.json"

config_lock = threading.Lock()
app_config = load_config(CONFIG_PATH)
service_downloader = ServiceDownloadManager(app_config)


playlists_lock = threading.Lock()


def load_playlists() -> list[dict]:
    try:
        return json.loads(PLAYLISTS_PATH.read_text("utf-8"))
    except Exception:
        return []


def save_playlists(data: list[dict]) -> None:
    PLAYLISTS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


def _spotify_import_playlist(playlist_url: str) -> dict:
    """Returns {name, artwork_url, description, owner, followers, tracks} from Spotify."""
    m = re.search(r"playlist/([A-Za-z0-9]+)", playlist_url)
    if not m:
        return {"name": "", "artwork_url": "", "description": "", "owner": "", "followers": 0, "tracks": []}
    playlist_id = m.group(1)
    try:
        from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
        client = SpotifyMetadataClient()

        info = client._get(f"playlists/{playlist_id}", params={
            "fields": "name,description,images,owner(display_name),followers(total)"
        })
        pl_name = info.get("name", "")
        images = info.get("images") or []
        pl_artwork = images[0].get("url", "") if images else ""
        pl_description = info.get("description", "") or ""
        pl_owner = (info.get("owner") or {}).get("display_name", "")
        pl_followers = (info.get("followers") or {}).get("total", 0)

        tracks = []
        offset = 0
        while True:
            data = client._get(f"playlists/{playlist_id}/tracks", params={"limit": 100, "offset": offset})
            items = data.get("items", [])
            for item in items:
                t = item.get("track")
                if not t or not t.get("id"):
                    continue
                spotify_id = t["id"]
                tracks.append({
                    "type": "track",
                    "title": t.get("name", ""),
                    "artist": ", ".join(a["name"] for a in (t.get("artists") or [])),
                    "album": (t.get("album") or {}).get("name", ""),
                    "artwork_url": ((t.get("album") or {}).get("images") or [{}])[0].get("url", ""),
                    "spotify_id": spotify_id,
                    "spotify_url": f"https://open.spotify.com/track/{spotify_id}",
                    "duration_ms": t.get("duration_ms", 0),
                })
            if not data.get("next") or len(items) < 100:
                break
            offset += 100

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
    if frequency == "startup":
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
    candidates = [f for f in files if is_download_audio_candidate(f)]
    return sorted(candidates or files, key=priority)[0] if (candidates or files) else None


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
    server_version = "SpotiFLACStreamer/0.1"
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
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
                catalog = discover_catalog(app_config)
                catalog["personal_tracks"] = enrich_artwork_batch(catalog["personal_tracks"][:12]) + catalog["personal_tracks"][12:]
                
                recent_enriched = enrich_artwork_batch(catalog["recent_tracks"][:12])
                for track in recent_enriched:
                    job_id = track.get("id")
                    if job_id:
                        service_downloader.update_job_metadata(job_id, track.get("metadata") or {}, track.get("artwork_url") or "")
                
                catalog["recent_tracks"] = recent_enriched + catalog["recent_tracks"][12:]
                
                # Enrich Global Top Tracks
                catalog["top_tracks"] = enrich_artwork_batch(catalog["top_tracks"][:12]) + catalog["top_tracks"][12:]
                
                catalog["artists"] = enrich_artwork_batch(catalog["artists"][:12]) + catalog["artists"][12:]
                catalog["albums"] = enrich_artwork_batch(catalog["albums"][:12]) + catalog["albums"][12:]
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
                self.send_json(app_config.public_dict())
                return
            if path == "/api/image":
                url = query.get("url", [""])[0].strip()
                if not url:
                    self.send_error_json("Missing URL", HTTPStatus.BAD_REQUEST)
                    return
                try:
                    # Stricter timeout and standard headers
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                    })
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
            if path == "/api/service/downloads":
                self.send_json({"jobs": service_downloader.list_jobs()})
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
                
                output_dir = Path(job["output_dir"])
                candidate = None
                for _ in range(900):
                    candidate = active_audio_candidate(output_dir)
                    if candidate:
                        break
                    job = service_downloader.get_job(job_id)
                    if not job or job.get("status") == "error":
                        self.send_error_json(job.get("error", "Download failed") if job else "Job not found", HTTPStatus.CONFLICT)
                        return
                    if job.get("status") == "finished" and job.get("library_path"):
                        final_path = Path(job["library_path"])
                        if final_path.exists():
                            candidate = final_path
                            break
                    time.sleep(1)
                
                if not candidate:
                    self.send_error_json("No audio data available yet", HTTPStatus.ACCEPTED)
                    return
                
                self.stream_local_path(candidate, is_active_job=True)
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
        try:
            if path == "/api/settings":
                body = read_body(self)
                updated = AppConfig.from_public_dict(body)
                with config_lock:
                    global app_config, service_downloader
                    app_config = updated
                    save_config(CONFIG_PATH, app_config)
                    service_downloader.update_config(app_config)
                self.send_json({"ok": True})
                return
            if path == "/api/playlists":
                body = read_body(self)
                user_name = body.get("name", "").strip()
                spotify_url = body.get("spotify_url", "").strip()
                imported = {"name": "", "artwork_url": "", "tracks": []}
                if spotify_url:
                    imported = _spotify_import_playlist(spotify_url)
                playlist = {
                    "id": str(uuid.uuid4()),
                    "name": user_name or imported["name"] or "New Playlist",
                    "artwork_url": imported.get("artwork_url", ""),
                    "description": imported.get("description", ""),
                    "owner": imported.get("owner", ""),
                    "followers": imported.get("followers", 0),
                    "spotify_url": spotify_url,
                    "tracks": imported["tracks"],
                    "created_at": time.time(),
                }
                with playlists_lock:
                    data = load_playlists()
                    data.append(playlist)
                    save_playlists(data)
                self.send_json({**playlist, "imported": bool(imported["tracks"])}, 201)
                return
            if path == "/api/playlists/refresh":
                body = read_body(self)
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
                        save_playlists(data)
                self.send_json(pl)
                return
            if path == "/api/playlists/tracks":
                body = read_body(self)
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
                self.send_json({"ok": True, "in_playlist": in_playlist})
                return
            if path == "/api/service/download":
                body = read_body(self)
                job = service_downloader.start_job(body)
                self.send_json(job, 201)
                return
            if path == "/api/library/status":
                self.send_json(service_downloader.library_status(read_body(self)))
                return
            if path == "/api/library/toggle":
                self.send_json(service_downloader.toggle_library(read_body(self)))
                return
            if path == "/api/playback/source":
                self.send_json(service_downloader.playback_source(read_body(self)))
                return
            if path == "/api/service/promote":
                body = read_body(self)
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
                            self.wfile.write(hex(len(chunk))[2:].encode() + b"\r\n")
                            self.wfile.write(chunk + b"\r\n")
                            self.wfile.flush()
                            consecutive_no_data = 0
                        else:
                            time.sleep(0.5)
                            consecutive_no_data += 1
                            if consecutive_no_data > 240:
                                break
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                return

            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with path.open("rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
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
    server.serve_forever()


if __name__ == "__main__":
    main()
