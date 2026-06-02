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
            header = audio_file.read(512)
    except Exception:
        return False
    suffix = path.suffix.lower()
    if suffix == ".flac":
        return header.startswith(b"fLaC")
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (len(header) > 0 and header[0] == 0xFF)
    if suffix in (".m4a", ".mp4", ".aac", ".alac"):
        return b"ftyp" in header[:32]
    # For others, assume valid if it exists and has size
    return size > 0


AUDIO_SUFFIXES = {
    ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".alac", ".webm",
    ".wma", ".wv", ".ape", ".mpc", ".mp4", ".m4b", ".m4p", ".m4r",
    ".mp2", ".mp1", ".mpa", ".m2a", ".m3a",
    ".aiff", ".aif", ".aifc",
    ".au", ".snd",
}

IDENTIFIER_FIELDS = [
    "spotify_id",
    "isrc",
    "deezer_id",
    "tidal_id",
    "amazon_id",
    "apple_id",
    "musicbrainz_id",
    "musicbrainz_album_id",
    "musicbrainz_artist_id",
]


def _track_identity_from_payload(payload: dict) -> str:
    """Stable key for a track to avoid duplicate cache jobs."""
    # Priority 1: Spotify ID
    s_id = payload.get("spotify_id")
    if not s_id and "track" in payload:
        s_id = payload["track"].get("spotify_id")
    if s_id:
        return f"spotify:{s_id}"
    # Priority 2: ISRC
    isrc = payload.get("isrc")
    if not isrc and "track" in payload:
        isrc = payload["track"].get("isrc")
    if isrc:
        return f"isrc:{isrc}"
    # Priority 3: Artist + Title
    artist = (payload.get("artist") or (payload.get("track") or {}).get("artist") or "unknown").lower()
    title = (payload.get("title") or (payload.get("track") or {}).get("title") or "unknown").lower()
    return f"meta:{artist}||{title}"


def _search_spotify_url(artist: str, title: str, album: str = "", kind: str = "track", isrc: str = "") -> str:
    """Direct fallback search using SpotiFLAC's internal credentials."""
    try:
        from SpotiFLAC.core.code_search import search_track
        query = f"artist:\"{artist}\" track:\"{title}\""
        if isrc:
            query = f"isrc:{isrc}"
        elif album:
            query += f" album:\"{album}\""
        
        results = search_track(query)
        if results and len(results) > 0:
            return f"https://open.spotify.com/track/{results[0]['id']}"
    except Exception:
        pass
    return ""


def resolve_download_url(metadata: dict, service: str = "spotify", kind: str = "track") -> str:
    """
    Resolve a playable/metadata URL for a service.
    SpotiFLAC usually wants a Spotify URL for metadata regardless of the download service.
    """
    # 1. Already have the right URL?
    if service == "spotify" and metadata.get("spotify_url"):
        return metadata["spotify_url"]
    
    # 2. Try song.link/Odesli (Very fast, multi-platform)
    try:
        import isrc_resolver
        res = isrc_resolver.resolve_song_link(metadata, target_service=service)
        if res:
            return res
    except Exception:
        pass

    # 3. SpotiFLAC fallback: it always needs a Spotify URL as the primary resolver key
    if service == "spotify":
        artist = metadata.get("artist")
        title = metadata.get("title")
        album = metadata.get("album")
        isrc = metadata.get("isrc")
        if artist and (title or album or isrc):
            res = _search_spotify_url(artist, title, album, kind, isrc)
            if res:
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
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        # Handle MM:SS or HH:MM:SS
        parts = value.split(":")
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds * 1000
    return 0


def downloaded_track_matches_request(path: Path, request_title: str, request_duration_ms: int = 0) -> tuple[bool, str]:
    """Verify that a found file actually matches what we asked for."""
    from music_metadata import get_audio_duration_ms
    actual_ms = get_audio_duration_ms(path)
    if actual_ms <= 0:
        # Se não conseguirmos ler a duração (arquivo corrompido ou formato não suportado),
        # confiamos no processo por enquanto, mas logamos.
        return True, ""
    
    # Tolerância de 5 segundos ou 5% (o que for maior)
    diff = abs(actual_ms - request_duration_ms)
    tolerance = max(5000, request_duration_ms * 0.05)
    
    if request_duration_ms > 0 and diff > tolerance:
        return False, f"Duration mismatch: expected {request_duration_ms}ms, got {actual_ms}ms"
    
    return True, ""


class ServiceDownloadManager:
    def __init__(self, config, music_dir: Path, cache_dir: Path):
        self.config = config
        self.music_dir = music_dir
        self.cache_dir = cache_dir
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._cache_events: list[dict] = []
        self._load_jobs()
        self._cancel_flags: set[str] = set()
        self._progress_thread_active = False

    def _load_jobs(self) -> None:
        if not jobs_path.exists():
            return
        try:
            data = json.loads(jobs_path.read_text("utf-8"))
            # Only keep recent jobs (last 24h) if they aren't finished/error
            # but keep finished jobs that exist on disk.
            now = time.time()
            for j in data.get("jobs", []):
                if not isinstance(j, dict) or "id" not in j: continue
                # Basic validation: if it's finished, verify the file still exists
                if j.get("status") == "finished":
                    lib_p = j.get("library_path")
                    if lib_p and Path(lib_p).exists():
                        self.jobs[j["id"]] = j
                elif now - j.get("created_at", 0) < 86400:
                    # Keep recent non-finished jobs as 'interrupted'
                    if j.get("status") == "running":
                        j["status"] = "error"
                        j["error"] = "Interrupted by server restart"
                    self.jobs[j["id"]] = j
        except Exception as e:
            print(f"[Jobs] Failed to load: {e}")

    def _save_jobs(self) -> None:
        try:
            with self._lock:
                # Limit saved jobs to last 100 to keep file small
                sorted_jobs = sorted(self.jobs.values(), key=lambda x: x.get("created_at", 0), reverse=True)
                data = {"jobs": sorted_jobs[:100]}
            jobs_path.write_text(json.dumps(data, indent=2), "utf-8")
        except Exception:
            pass

    def _public_job(self, job: dict) -> dict:
        """Return a copy of the job with internal fields removed."""
        res = job.copy()
        # Keep id, status, progress, error, library_path, etc.
        return res

    def _output_dir(self, job: dict) -> Path:
        if job.get("mode") == "download":
            artist = job.get("artist", "Unknown Artist")
            album = job.get("album", "Unknown Album")
            return self.music_dir / clean_part(artist) / clean_part(album)
        return self.cache_dir / job["id"]

    def _find_cache_entry(self, identity: str) -> dict | None:
        """Check if we already have this track cached and ready."""
        # identity is e.g. "spotify:abc" or "isrc:xyz"
        with self._lock:
            for j in self.jobs.values():
                if j.get("mode") == "stream" and j.get("status") == "finished":
                    if j.get("spotify_id") and identity == f"spotify:{j['spotify_id']}":
                        return {"job": j}
                    if j.get("isrc") and identity == f"isrc:{j['isrc']}":
                        return {"job": j}
                    if j.get("track_key") and identity == f"meta:{j['track_key']}":
                        return {"job": j}
        return None

    def _find_active_cache_job(self, identity: str) -> dict | None:
        """Check if we are already downloading this track."""
        with self._lock:
            for j in self.jobs.values():
                if j.get("mode") == "stream" and j.get("status") in ("starting", "running"):
                    if j.get("spotify_id") and identity == f"spotify:{j['spotify_id']}":
                        return self._public_job(j)
                    if j.get("isrc") and identity == f"isrc:{j['isrc']}":
                        return self._public_job(j)
                    if j.get("track_key") and identity == f"meta:{j['track_key']}":
                        return self._public_job(j)
        return None

    def _append_cache_event(self, job: dict, type_val: str, message: str) -> None:
        event = {
            "time": time.strftime("%H:%M:%S"),
            "job_id": job["id"],
            "title": job.get("title", "Unknown"),
            "type": type_val,
            "message": message,
            "prefetch": job.get("prefetch", False)
        }
        with self._lock:
            self._cache_events.append(event)
            if len(self._cache_events) > 200:
                del self._cache_events[:-200]

    @staticmethod
    def _cache_size_text(size: int) -> str:
        if size > 1024 * 1024:
            return f"{size / (1024*1024):.1f} MB"
        return f"{size / 1024:.1f} KB"

    def _capture_cache_activity(self, job: dict) -> None:
        """Scan the job's output directory for new files and log them."""
        root = Path(job.get("output_dir") or "")
        if not root.is_dir():
            return
        
        try:
            files = sorted(path for path in root.rglob("*") if path.is_file())
        except Exception:
            return

        seen: set[str] = set()
        changes: list[tuple[str, str]] = []

        with self._lock:
            for path in files:
                path_text = str(path.relative_to(root))
                seen.add(path_text)
                try:
                    size = path.stat().st_size
                    size_text = self._cache_size_text(size)
                except Exception:
                    size_text = "?"

                # We store a mini 'manifest' of seen files in the job to detect NEW ones
                manifest = job.setdefault("_file_manifest", {})
                if path_text not in manifest:
                    manifest[path_text] = size
                    changes.append(("Created", f"{path_text} ({size_text})"))
                elif manifest[path_text] != size:
                    manifest[path_text] = size
                    changes.append(("Updated", f"{path_text} ({size_text})"))

        for action, msg in changes:
            self._append_cache_event(job, "file", f"{action} {msg}")

    def get_cache_events(self) -> list[dict]:
        with self._lock:
            return list(self._cache_events)

    def _ensure_progress_thread(self) -> None:
        if self._progress_thread_active:
            return
        self._progress_thread_active = True
        threading.Thread(target=self._progress_watcher, daemon=True, name="download-progress-watcher").start()

    def _progress_watcher(self) -> None:
        """Background thread that periodically captures filesystem changes for active jobs."""
        while True:
            active_jobs = []
            with self._lock:
                for j in self.jobs.values():
                    if j.get("status") == "running":
                        active_jobs.append(j.copy())
            
            if not active_jobs:
                self._progress_thread_active = False
                break

            for j in active_jobs:
                if j["id"] in self._cancel_flags:
                    continue
                self._capture_cache_activity(j)
                self._update_job_file_progress(j)
            
            time.sleep(1.5)

    def _update_job_file_progress(self, job: dict) -> bool:
        """Check if an active file is growing and update job progress."""
        # This is for engines that don't provide their own progress (like spotiflac)
        output_dir = Path(job.get("output_dir") or "")
        if not output_dir.exists():
            return False
        
        # Look for the target audio file or any flac/mp3/m4a
        audio_files = _find_audio_files(output_dir)
        if not audio_files:
            return False
        
        audio_path = audio_files[0]
        try:
            downloaded_bytes = audio_path.stat().st_size
        except Exception:
            return False
        
        # Estimate total bytes if not known (avg FLAC is 30-40MB, MP3 8-12MB)
        # Or better: if we know duration, estimate based on bitrate.
        duration_ms = _parse_duration_ms(job.get("metadata", {}).get("duration_ms") or job.get("metadata", {}).get("duration") or 0)
        
        quality = str(job.get("quality", "flac")).lower()
        is_lossless = quality in ("flac", "alac", "lossless", "27", "6")
        # FLAC ~900kbps, MP3-320 ~320kbps
        bitrate = 900 if is_lossless else 320
        total_bytes = int((duration_ms / 1000) * (bitrate * 1024 / 8))
        
        if total_bytes <= 0:
            total_bytes = 35 * 1024 * 1024 if is_lossless else 10 * 1024 * 1024

        with self._lock:
            job = self.jobs.get(job["id"])
            if not job or job.get("status") != "running":
                return False
            # Don't overwrite engine-reported progress (e.g. from torrent)
            if job.get("engine") == "torrent" and job.get("progress", 0) > 0:
                return True
                
            job["progress"] = min(99.9, (downloaded_bytes / total_bytes) * 100)
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
            # Stream cache dirs are per-job UUIDs and safe to wipe. Download
            # dirs are the shared album folder (music_dir/artist/album), so
            # wiping them would delete sibling tracks already in the library.
            if job.get("mode", "stream") == "stream" and output_dir.exists():
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

            # If the engine resolved a different album (e.g. the torrent engine
            # fell back to a MusicBrainz album), the download-mode folder was
            # created under the original album name. Relocate the files to the
            # correct album folder so the library reflects the real album.
            if job.get("mode") == "download":
                desired_dir = self._output_dir(job)
                if desired_dir.resolve() != output_dir.resolve():
                    try:
                        desired_dir.mkdir(parents=True, exist_ok=True)
                        for f in output_dir.glob("*"):
                            if f.is_file():
                                target = desired_dir / f.name
                                if target.exists():
                                    target.unlink()
                                shutil.move(str(f), str(target))
                        try:
                            output_dir.rmdir()
                        except OSError:
                            pass # Folder not empty
                        output_dir = desired_dir
                    except Exception as e:
                        print(f"[Worker] Failed to relocate downloads to real album folder: {e}")

            # Verify we actually have a playable file
            audio_files = _find_audio_files(output_dir)
            if not audio_files:
                raise RuntimeError(f"Engine finished but no valid audio files were found in {output_dir}")
            
            # Match the best file for this job (relevant if folder has multiple tracks)
            best_path = audio_files[0]
            if len(audio_files) > 1:
                # If we have multiple, try to find one matching the title exactly
                clean_title = job["title"].lower()
                for f in audio_files:
                    if clean_title in f.name.lower():
                        best_path = f
                        break
            
            with self._lock:
                job["status"] = "finished"
                job["error"] = ""
                job["progress"] = 100
                job["library_path"] = str(best_path.resolve())
            
            if job.get("mode", "stream") == "stream":
                self._append_cache_event(job, "finished", f"Ready to play {best_path.name}")
            else:
                self._append_cache_event(job, "finished", f"Saved {best_path.name} to library")

        except Exception as exc:
            logging.error(f"Job {job_id} failed: {exc}")
            with self._lock:
                job["status"] = "error"
                job["error"] = str(exc)
            self._append_cache_event(job, "error", str(exc))
        finally:
            self._save_jobs()
            if job_id in self._cancel_flags:
                self._cancel_flags.remove(job_id)

    def _save_sidecar_files(self, output_dir: Path, job: dict) -> None:
        """Write metadata.json and cover.png next to the audio."""
        try:
            meta_path = output_dir / "metadata.json"
            meta = job.get("metadata") or {}
            # Update meta with any resolved identifiers from the job
            for key in IDENTIFIER_FIELDS:
                if job.get(key):
                    meta[key] = job[key]
            
            # Merged album metadata storage
            if job.get("mode") == "download":
                self._merge_album_metadata(meta_path, job["title"], meta)
            else:
                meta_path.write_text(json.dumps(meta, indent=2), "utf-8")

            artwork_url = job.get("artwork_url")
            if artwork_url:
                cover_path = output_dir / "cover.png"
                if not cover_path.exists():
                    try:
                        with urllib.request.urlopen(artwork_url, timeout=10) as response:
                            cover_path.write_bytes(response.read())
                    except Exception:
                        pass
        except Exception:
            pass

    def _merge_album_metadata(self, info_path: Path, track_title: str, current_meta: dict) -> None:
        """Ensure album folder metadata.json contains entries for all tracks."""
        from music_metadata import _merge_nonempty_metadata
        try:
            data = json.loads(info_path.read_text("utf-8")) if info_path.exists() else {}
            if "tracks" not in data:
                data = {"tracks": {}}
            saved_track = data["tracks"].get(track_title) if isinstance(data["tracks"].get(track_title), dict) else {}
            data["tracks"][track_title] = _merge_nonempty_metadata(saved_track, current_meta)
            info_path.write_text(json.dumps(data, indent=2), "utf-8")
        except Exception:
            pass

    def _repair_finished_audio_path(self, job: dict) -> bool:
        """If a job is finished but its library_path is missing/invalid, try to re-find it."""
        if job.get("status") != "finished":
            return False
        lib_p = job.get("library_path")
        if lib_p and Path(lib_p).exists() and is_valid_audio_file(Path(lib_p)):
            return False
        
        output_dir = self._output_dir(job)
        audio_files = _find_audio_files(output_dir)
        if audio_files:
            job["library_path"] = str(audio_files[0].resolve())
            return True
        return False

    def stop_job(self, job_id: str) -> bool:
        self._cancel_flags.add(job_id)
        return True

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            job = self.jobs.pop(job_id, None)
        if job:
            self._cancel_flags.add(job_id)
            output_dir = self._output_dir(job)
            if job.get("mode") == "stream" and output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
            self._save_jobs()
            return True
        return False

    def clear_cache(self) -> dict:
        """Delete all cached stream files."""
        count = 0
        with self._lock:
            to_delete = [jid for jid, j in self.jobs.items() if j.get("mode") == "stream"]
            for jid in to_delete:
                job = self.jobs.pop(jid)
                output_dir = self._output_dir(job)
                if output_dir.exists():
                    shutil.rmtree(output_dir, ignore_errors=True)
                    count += 1
        self._save_jobs()
        # Also clean any orphaned folders in cache_dir
        if self.cache_dir.exists():
            for d in self.cache_dir.iterdir():
                if d.is_dir() and d.name not in self.jobs:
                    shutil.rmtree(d, ignore_errors=True)
        return {"ok": True, "deleted": count}

    def toggle_library(self, payload: dict) -> dict:
        """Add or remove a finished job's file from the permanent library."""
        # Find if already in library
        artist = payload.get("artist")
        album = payload.get("album")
        title = payload.get("title")
        if not (artist and album and title):
            return {"ok": False, "error": "Missing metadata"}
        
        dest_dir = self.music_dir / clean_part(artist) / clean_part(album)
        existing = _find_audio_files(dest_dir)
        found = next((f for f in existing if title.lower() in f.name.lower()), None)
        
        if found:
            # REMOVE
            try:
                found.unlink()
                # Clean up empty album/artist folders
                if not any(dest_dir.iterdir()):
                    dest_dir.rmdir()
                    if not any(dest_dir.parent.iterdir()):
                        dest_dir.parent.rmdir()
                return {"ok": True, "in_library": False}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        else:
            # ADD (requires a source file, usually from cache)
            job_id = payload.get("active_job_id")
            if not job_id:
                return {"ok": False, "error": "No cached source found for this track"}
            return self.promote_to_library(job_id)

    def promote_to_library(self, job_id: str) -> dict:
        """Copy a finished cache job to the permanent library."""
        job = self.get_job(job_id)
        if not job or job.get("status") != "finished":
            return {"ok": False, "error": "Job not finished"}
        
        src_path = Path(job["library_path"])
        if not src_path.exists():
            return {"ok": False, "error": "Source file missing"}
            
        dest_dir = self.music_dir / clean_part(job["artist"]) / clean_part(job["album"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / src_path.name
        
        try:
            if dest_path.resolve() != src_path.resolve():
                shutil.copy2(src_path, dest_path)
            self._save_sidecar_files(dest_dir, job)
            return {"ok": True, "in_library": True, "path": str(dest_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def playback_source(self, payload: dict) -> dict:
        """Fast-path to get a streamable URL if already cached/in library."""
        # 1. Check Library
        artist = payload.get("artist")
        album = payload.get("album")
        title = payload.get("title")
        if artist and album and title:
            lib_dir = self.music_dir / clean_part(artist) / clean_part(album)
            files = _find_audio_files(lib_dir)
            match = next((f for f in files if title.lower() in f.name.lower()), None)
            if match:
                return {"ok": True, "path": str(match.resolve()), "source": "library"}
        
        # 2. Check Cache
        identity = _track_identity_from_payload(payload)
        cache = self._find_cache_entry(identity)
        if cache and cache.get("job"):
            job = cache["job"]
            return {
                "ok": True, 
                "path": job["library_path"], 
                "source": "cache",
                "active_job_id": job["id"]
            }
        
        # 3. Check active download
        active = self._find_active_cache_job(identity)
        if active:
            return {
                "ok": True, 
                "active_job_id": active["id"], 
                "status": active["status"],
                "progress": active.get("progress", 0)
            }
            
        return {"ok": False}

    def _library_file_index(self) -> dict[str, Path]:
        """Map Artist||Title to absolute file path for all tracks in library."""
        index = {}
        if not self.music_dir.exists():
            return index
        for artist_dir in self.music_dir.iterdir():
            if not artist_dir.is_dir(): continue
            for album_dir in artist_dir.iterdir():
                if not album_dir.is_dir(): continue
                for f in _find_audio_files(album_dir):
                    # Guess title from filename: "01. Title.flac" or "Title.flac"
                    name = f.stem
                    # Common pattern: "01. Title"
                    if ". " in name and name[:2].isdigit():
                        name = name.split(". ", 1)[1]
                    # Common pattern: "01 - Title"
                    elif " - " in name and (name[:2].isdigit() or artist_dir.name.lower() in name.lower()):
                        parts = name.split(" - ")
                        name = parts[-1]
                    
                    key = f"{artist_dir.name.lower()}||{name.lower()}"
                    index[key] = f.resolve()
        return index

    def library_status_batch(self, payloads: list) -> list:
        library_files = self._library_file_index()
        results = []
        
        # Also check current cache jobs
        with self._lock:
            cache_index = {}
            for j in self.jobs.values():
                if j.get("mode") == "stream" and j.get("status") == "finished":
                    cache_index[j["track_key"]] = j["id"]
                elif j.get("mode") == "stream" and j.get("status") in ("starting", "running"):
                    cache_index[j["track_key"]] = f"active:{j['id']}"

        for p in payloads:
            artist = (p.get("artist") or "").lower()
            title = (p.get("title") or "").lower()
            key = f"{artist}||{title}"
            
            in_lib = key in library_files
            cache_id = cache_index.get(key)
            
            results.append({
                "in_library": in_lib,
                "path": str(library_files[key]) if in_lib else None,
                "active_job_id": cache_id if cache_id and not str(cache_id).startswith("active:") else None,
                "pending_job_id": str(cache_id).split(":", 1)[1] if cache_id and str(cache_id).startswith("active:") else None
            })
        return results
