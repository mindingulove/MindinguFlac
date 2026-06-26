from __future__ import annotations

import logging
import os
import threading
import time
import inspect
from dataclasses import fields
from pathlib import Path

from spotiflac_compat import run_async_blocking

# ---------------------------------------------------------------------------
# SpotiFLAC state
# ---------------------------------------------------------------------------
_spotiflac_job_local = threading.local()
_spotiflac_patch_installed = False
_spotiflac_patch_lock = threading.Lock()
_STREAM_CAPTURE = threading.local()
_STREAM_CAPTURE_INSTALLED = False

# Thread-safe httpx client management for parallel SpotiFLAC runs
_sf_clients_lock = threading.Lock()
_sf_clients: dict[str | None, object] = {}
_sf_async_clients_lock = threading.Lock()
_sf_async_clients: dict[str | None, object] = {}

def _get_sf_client(proxy: str | None = None):
    import httpx
    with _sf_clients_lock:
        if proxy not in _sf_clients:
            # Create a dedicated client for this proxy configuration (or direct)
            # SpotiFLAC uses httpx.Client internally; we provide a pooled one.
            limits = httpx.Limits(max_keepalive_connections=30, max_connections=100)
            _sf_clients[proxy] = httpx.Client(limits=limits, timeout=300.0, proxy=proxy)
        return _sf_clients[proxy]

def _get_sf_async_client(proxy: str | None = None):
    import httpx
    with _sf_async_clients_lock:
        if proxy not in _sf_async_clients:
            limits = httpx.Limits(max_keepalive_connections=30, max_connections=100)
            _sf_async_clients[proxy] = httpx.AsyncClient(limits=limits, timeout=300.0, proxy=proxy)
        return _sf_async_clients[proxy]

def _patched_get_sync_client(cls):
    # Returns a client configured with the current thread's proxy
    proxy = getattr(_spotiflac_job_local, "proxy", None)
    return _get_sf_client(proxy)

def _patched_get_async_client(cls):
    # Returns an async client configured with the current thread's proxy
    proxy = getattr(_spotiflac_job_local, "proxy", None)
    return _get_sf_async_client(proxy)


async def _patched_get_async_client_safe(cls):
    # SpotiFLAC 1.2.6+ routes provider traffic through this async-only accessor.
    proxy = getattr(_spotiflac_job_local, "proxy", None)
    return _get_sf_async_client(proxy)

_SPOTIFLAC_SERVICE_MAP: dict[str, str] = {
    "apple_music": "apple",
}

_LOSSY_ONLY_SERVICES = {"soundcloud", "youtube"}
_LOSSLESS_REQUEST_QUALITIES = {"DOLBY_ATMOS", "HI_RES_LOSSLESS", "HI_RES", "LOSSLESS", "27", "7", "6", "ALAC"}

# ---------------------------------------------------------------------------
# Tor SOCKS5 bypass
# ---------------------------------------------------------------------------
_TOR_SOCKS = "socks5h://127.0.0.1:9050"
_TOR_BINARY = "/opt/homebrew/bin/tor"
_TOR_DATA_DIR = Path("/tmp/streambox-tor")
_tor_process: object = None
_tor_lock = threading.Lock()


def _tor_is_up() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 9050), timeout=2):
            return True
    except Exception:
        return False


def _start_tor() -> bool:
    global _tor_process
    import subprocess
    import shutil as _shutil

    if _tor_is_up():
        return True

    tor_bin = _TOR_BINARY
    if not Path(tor_bin).exists():
        tor_bin = _shutil.which("tor") or ""
    if not tor_bin:
        print("[Tor] tor binary not found — install with: brew install tor")
        return False

    _TOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("[Tor] Starting local Tor daemon…")
    try:
        # Hide terminal window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0 # SW_HIDE

        proc = subprocess.Popen(
            [tor_bin,
             "--SocksPort", "9050",
             "--ControlPort", "9051",
             "--CookieAuthentication", "0",
             "--DataDirectory", str(_TOR_DATA_DIR),
             "--Log", "notice stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            startupinfo=startupinfo
        )
        _tor_process = proc
    except Exception as e:
        print(f"[Tor] Failed to start: {e}")
        return False

    for _ in range(30):
        time.sleep(1)
        if _tor_is_up():
            print("[Tor] SOCKS5 ready on 127.0.0.1:9050")
            return True

    print("[Tor] Timed out waiting for Tor to bootstrap.")
    return False


def _ensure_tor() -> bool:
    with _tor_lock:
        return _start_tor()


def _rotate_tor_circuit() -> None:
    import socket as _socket

    def _send_newnym(auth_line: bytes) -> bool:
        try:
            with _socket.create_connection(("127.0.0.1", 9051), timeout=3) as ctrl:
                ctrl.sendall(auth_line + b"\r\nSIGNAL NEWNYM\r\n")
                resp = ctrl.recv(256)
                return b"250" in resp
        except Exception:
            return False

    if _send_newnym(b'AUTHENTICATE ""'):
        time.sleep(1)
        print("[Tor] Rotated to new exit node.")
        return

    cookie_paths = [
        _TOR_DATA_DIR / "control_auth_cookie",
        Path("/var/run/tor/control.authcookie"),
        Path("/usr/local/var/run/tor/control.authcookie"),
        Path(Path.home() / "Library/Application Support/TorBrowser-Data/Tor/control_auth_cookie"),
    ]
    for cookie_path in cookie_paths:
        if cookie_path.exists():
            try:
                cookie = cookie_path.read_bytes()
                auth_line = b"AUTHENTICATE " + cookie.hex().encode()
                if _send_newnym(auth_line):
                    time.sleep(1)
                    print("[Tor] Rotated to new exit node (cookie auth).")
                    return
            except Exception:
                pass

    print("[Tor] Circuit rotation failed — control port unreachable or auth unknown.")


def prefetch_tor() -> None:
    t = threading.Thread(target=_ensure_tor, daemon=True, name="tor-warmup")
    t.start()


# ---------------------------------------------------------------------------
# SpotiFLAC helpers
# ---------------------------------------------------------------------------

def spotiflac_fallback_services(selected_service: str, quality: str) -> list[str]:
    # Prioritize Qobuz and Deezer over Amazon for better stability
    fallback_order = ["qobuz", "deezer", "amazon", "tidal"]
    if selected_service in _LOSSY_ONLY_SERVICES:
        peers = []
        lossless = [service for service in fallback_order if service not in _LOSSY_ONLY_SERVICES and service != selected_service]
        return [selected_service, *peers, *lossless]
    candidates = [selected_service, *[service for service in fallback_order if service != selected_service]]
    if str(quality or "").upper() in _LOSSLESS_REQUEST_QUALITIES:
        return [service for service in candidates if service not in _LOSSY_ONLY_SERVICES]
    return candidates


def spotiflac_provider_quality(requested_quality: str, service: str) -> str:
    requested = str(requested_quality or "LOSSLESS").upper()
    if requested == "DOLBY_ATMOS":
        return {"tidal": "DOLBY_ATMOS", "qobuz": "27", "amazon": "LOSSLESS", "deezer": "LOSSLESS"}.get(service, requested)
    if requested in {"HI_RES", "HI_RES_LOSSLESS"}:
        return {"tidal": "HI_RES_LOSSLESS", "qobuz": "27", "amazon": "LOSSLESS", "deezer": "LOSSLESS"}.get(service, requested)
    if requested == "LOSSLESS":
        return {"qobuz": "6"}.get(service, requested)
    return requested_quality


def spotiflac_failure_message(messages: list[str]) -> str:
    incidental = ("gist fetch failed", "failed to refresh api list")
    meaningful = [message for message in messages if not any(token in message.lower() for token in incidental)]
    return meaningful[-1] if meaningful else "All providers failed and no playable audio file was found"


def spotiflac_download_options(output_dir: Path, job: dict, track_max_retries: int, services: list[str]) -> dict:
    from service_downloader import clean_part
    title = clean_part(job.get("title") or "Unknown Track")
    artist = clean_part(job.get("artist") or "Unknown Artist")
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    include_featuring = bool(
        job.get("include_featuring") or metadata.get("include_featuring")
    )
    options = {
        "url": job.get("resolved_url") or job.get("url") or "",
        "output_dir": str(output_dir),
        "output_path": str(output_dir / f"{title} - {artist}.flac"),
        "services": services,
        "track_max_retries": track_max_retries,
        "filename_format": "{title} - {artist}",
        "embed_lyrics": True,
        "lyrics_providers": ["spotify", "apple", "musixmatch", "lrclib", "amazon"],
        "enrich_metadata": True,
        "enrich_providers": ["deezer", "apple", "qobuz", "tidal", "soundcloud"],
        "allow_fallback": True,
        "use_artist_subfolders": False,
        "use_album_subfolders": False,
    }
    if include_featuring:
        options["include_featuring"] = True
    if job.get("quality"):
        options["quality"] = job["quality"]
    return options


def _spotiflac_url_for_options(url: str, include_featuring: bool) -> str:
    if not include_featuring:
        return url
    try:
        from SpotiFLAC.providers.spotify_metadata import parse_spotify_url  # type: ignore

        parsed = parse_spotify_url(url)
    except Exception:
        return url
    if parsed.get("type") not in {"artist", "artist_discography"}:
        return url
    artist_id = parsed.get("id")
    if not artist_id:
        return url
    return f"spotify:artist:{artist_id}:discography:all"


def _run_spotiflac_download(kwargs: dict) -> None:
    try:
        from SpotiFLAC.downloader import DownloadOptions, SpotiflacDownloader  # type: ignore
    except Exception:
        from SpotiFLAC import SpotiFLAC  # type: ignore

        SpotiFLAC(**kwargs)
        return

    option_fields = {field.name for field in fields(DownloadOptions)}
    options_kwargs = {
        key: value for key, value in kwargs.items() if key in option_fields
    }
    include_featuring = bool(options_kwargs.get("include_featuring"))
    url = _spotiflac_url_for_options(str(kwargs.get("url") or ""), include_featuring)
    loop_minutes = kwargs.get("loop")
    downloader = SpotiflacDownloader(DownloadOptions(**options_kwargs))
    run_async_blocking(downloader.run_async(url, loop_minutes=loop_minutes))


def requested_spotiflac_track_metadata(track, job: dict):
    from service_downloader import _parse_duration_ms
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    updates = {
        "title": job.get("title") or metadata.get("title") or track.title,
        "artists": job.get("artist") or metadata.get("artist") or track.artists,
        "album": job.get("album") or metadata.get("album") or track.album,
        "album_artist": job.get("artist") or metadata.get("artist") or track.album_artist,
    }
    expected_duration = (
        _parse_duration_ms(metadata.get("duration_ms"))
        or _parse_duration_ms(metadata.get("length"))
        or _parse_duration_ms(metadata.get("duration"))
    )
    if expected_duration:
        updates["duration_ms"] = expected_duration
    if job.get("isrc") or metadata.get("isrc"):
        updates["isrc"] = job.get("isrc") or metadata.get("isrc")
    if job.get("artwork_url") or metadata.get("artwork_url"):
        updates["cover_url"] = job.get("artwork_url") or metadata.get("artwork_url")
    return track.model_copy(update=updates)


def _install_stream_capture() -> None:
    global _STREAM_CAPTURE_INSTALLED
    if _STREAM_CAPTURE_INSTALLED:
        return
    http_client_cls = None
    try:
        from SpotiFLAC.core.http import HttpClient  # type: ignore
        http_client_cls = HttpClient
    except Exception:
        try:
            from SpotiFLAC.core.http import AsyncHttpClient  # type: ignore
            http_client_cls = AsyncHttpClient
        except Exception:
            return

    original = http_client_cls.stream_to_file

    def _capture(url, dest_path, extra_headers):
        manager = getattr(_STREAM_CAPTURE, "manager", None)
        job_id = getattr(_STREAM_CAPTURE, "job_id", "")
        if manager and job_id:
            with manager._lock:
                job = manager.jobs.get(job_id)
                if job:
                    job["active_stream_url"] = url
                    job["active_stream_dest_path"] = str(dest_path)
                    job["active_stream_headers"] = extra_headers or {}

    if inspect.iscoroutinefunction(original):
        async def wrapped_stream_to_file(self, url, dest_path, progress_cb=None, chunk_size=256 * 1024, extra_headers=None, stop_event=None):
            _capture(url, dest_path, extra_headers)
            return await original(self, url, dest_path, progress_cb, chunk_size, extra_headers, stop_event)
    else:
        def wrapped_stream_to_file(self, url, dest_path, progress_cb=None, chunk_size=256 * 1024, extra_headers=None, stop_event=None):
            _capture(url, dest_path, extra_headers)
            return original(self, url, dest_path, progress_cb, chunk_size, extra_headers, stop_event)

    http_client_cls.stream_to_file = wrapped_stream_to_file
    _STREAM_CAPTURE_INSTALLED = True


def _ensure_spotiflac_metadata_patch() -> None:
    global _spotiflac_patch_installed
    if _spotiflac_patch_installed:
        return
    with _spotiflac_patch_lock:
        if _spotiflac_patch_installed:
            return
        try:
            from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
            if hasattr(SpotifyMetadataClient, "get_track"):
                _original_get_track = SpotifyMetadataClient.get_track

                def _thread_local_get_track(client, track_id):
                    job = getattr(_spotiflac_job_local, "current_job", None)
                    track = _original_get_track(client, track_id)
                    if job is None:
                        return track
                    return requested_spotiflac_track_metadata(track, job)

                SpotifyMetadataClient.get_track = _thread_local_get_track

            if hasattr(SpotifyMetadataClient, "get_track_async"):
                _original_get_track_async = SpotifyMetadataClient.get_track_async

                async def _thread_local_get_track_async(client, track_id):
                    job = getattr(_spotiflac_job_local, "current_job", None)
                    track = await _original_get_track_async(client, track_id)
                    if job is None:
                        return track
                    return requested_spotiflac_track_metadata(track, job)

                SpotifyMetadataClient.get_track_async = _thread_local_get_track_async

            # Also patch the NetworkManager to return our proxy-aware clients
            from SpotiFLAC.core.http import NetworkManager  # type: ignore
            if hasattr(NetworkManager, "get_sync_client"):
                NetworkManager.get_sync_client = classmethod(_patched_get_sync_client)
            if hasattr(NetworkManager, "get_async_client"):
                NetworkManager.get_async_client = classmethod(_patched_get_async_client)
            if hasattr(NetworkManager, "get_async_client_safe"):
                NetworkManager.get_async_client_safe = classmethod(_patched_get_async_client_safe)

            _spotiflac_patch_installed = True
        except Exception:
            pass


def run(url: str, output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files, downloaded_track_matches_request

    if job["id"] in manager._cancel_flags:
        return

    prefetch_tor()

    try:
        from SpotiFLAC import SpotiFLAC  # type: ignore
    except Exception as exc:
        raise RuntimeError("SpotiFLAC is not installed in this environment. Install it with: pip install -r requirements.txt") from exc
    _install_stream_capture()

    raw_service = job["service"]
    spotiflac_service = _SPOTIFLAC_SERVICE_MAP.get(raw_service, raw_service)

    requested_quality = str(job.get("quality") or "LOSSLESS")
    services_list = spotiflac_fallback_services(spotiflac_service, requested_quality)
    # Increase retries to handle intermittent network failures better
    max_retries = max(2, manager.config.track_max_retries + 1)
    kwargs = spotiflac_download_options(output_dir, {**job, "resolved_url": url}, max_retries, services_list)

    def _exec_sf(proxy=None) -> tuple[bool, bool]:
        # No lock here! Parallel downloads are enabled.
        # Set the thread-local proxy for the NetworkManager patch
        _spotiflac_job_local.proxy = proxy
        
        old_ua = os.environ.get("USER_AGENT")
        try:
            from fake_useragent import UserAgent
            os.environ["USER_AGENT"] = UserAgent().random
        except Exception:
            pass

        try:
            if job["id"] in manager._cancel_flags:
                raise RuntimeError("Download cancelled")
            
            # Use DownloadOptions directly so newer SpotiFLAC fields are not
            # dropped by the compatibility constructor.
            _run_spotiflac_download(kwargs)
            
            tor_needed = False
            for msg in captured:
                m = msg.lower()
                if "429" in m or "rate limit" in m or "ratelimit" in m or "too many requests" in m:
                    print(f"[Bypass] Rate limit detected: {msg}")
                    tor_needed = True
                elif "403" in m or "forbidden" in m or "access denied" in m or "cloudflare" in m or "unauthorized" in m:
                    print(f"[Bypass] Access blocked (403): {msg}")
                    tor_needed = True
            if tor_needed:
                return False, True
            for msg in captured:
                m = msg.lower()
                if "all providers fail" in m or "failures" in m or "failed : 1" in m:
                    print(f"[Bypass] SpotiFLAC reported failure: {msg}")
                    return False, False
                if "quality" in m and "unavailable" in m and "falling back" in m:
                    print(f"[Bypass] Quality unavailable: {msg}")
                    return False, False
            return True, False
        except Exception:
            return False, False
        finally:
            if old_ua: os.environ["USER_AGENT"] = old_ua
            elif "USER_AGENT" in os.environ: del os.environ["USER_AGENT"]
            _spotiflac_job_local.proxy = None

    captured: list[str] = []
    rejected_paths: set[str] = set()
    _capture_thread = threading.current_thread()

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if threading.current_thread() is _capture_thread:
                captured.append(record.getMessage())

    handler = _Capture()
    sf_logger = logging.getLogger("SpotiFLAC")
    sf_logger.addHandler(handler)

    def _has_audio(delete_invalid: bool = False) -> bool:
        for path in _find_audio_files(output_dir, delete_invalid=delete_invalid):
            matches, message = downloaded_track_matches_request(path, job)
            if matches:
                return True
            path_text = str(path)
            if path_text not in rejected_paths:
                rejected_paths.add(path_text)
                print(f"[Validation] {message}")
                if job.get("mode", "stream") == "stream":
                    manager._append_cache_event(job, "rejected", message)
            if delete_invalid:
                try:
                    path.unlink()
                except OSError:
                    pass
        return False

    _ensure_spotiflac_metadata_patch()

    try:
        _spotiflac_job_local.current_job = job
        _STREAM_CAPTURE.manager = manager
        _STREAM_CAPTURE.job_id = job["id"]
        success = False
        # Allow internal fallback so SpotiFLAC can try its other mirrors if one is 503
        kwargs["allow_fallback"] = True
        immediate_tor = manager.config.track_max_retries == 0
        max_direct = manager.config.track_max_retries

        for service in services_list:
            if success: break
            if job["id"] in manager._cancel_flags:
                print(f"[Bypass] Job {job['id']} cancelled, stopping loop.")
                break

            kwargs["services"] = [service]
            provider_quality = spotiflac_provider_quality(requested_quality, service)
            kwargs["quality"] = provider_quality
            kwargs["track_max_retries"] = 0

            try_tor = immediate_tor

            if not immediate_tor:
                for attempt in range(max_direct):
                    if job["id"] in manager._cancel_flags: break
                    label = f" (attempt {attempt + 1}/{max_direct})" if max_direct > 1 else ""
                    quality_note = f", quality {provider_quality}" if provider_quality != requested_quality else ""
                    with manager._lock:
                        job["last_status"] = f"Trying {service}{quality_note}..."
                    manager._append_cache_event(job, "trying", f"Trying {service} (direct{quality_note}){label}...")
                    manager._save_jobs()

                    captured.clear()
                    sf_success, detected_tor = _exec_sf()
                    if detected_tor:
                        try_tor = True

                    if sf_success and _has_audio():
                        print(f"[Bypass] ✓ {service} (direct) succeeded.")
                        success = True
                        break
                    else:
                        msg = spotiflac_failure_message(captured)
                        print(f"[Bypass] ✗ {service} (direct) failed: {msg}")
                        if job.get("mode", "stream") == "stream":
                            manager._append_cache_event(job, "trying", f"{service} failed: {msg}")
                        _has_audio(delete_invalid=True)

            if success or job["id"] in manager._cancel_flags: break

            if try_tor and (_tor_is_up() or _ensure_tor()):
                quality_note = f", quality {provider_quality}" if provider_quality != requested_quality else ""
                with manager._lock:
                    job["last_status"] = f"Trying {service} (Tor{quality_note})..."
                tor_label = "Tor bypass" if immediate_tor else "rate limit bypass"
                manager._append_cache_event(job, "trying", f"Trying {service} via Tor ({tor_label}{quality_note})...")
                manager._save_jobs()

                kwargs["track_max_retries"] = 1
                captured.clear()
                sf_success, _ = _exec_sf(_TOR_SOCKS)
                if sf_success and _has_audio():
                    print(f"[Bypass] ✓ {service} (Tor) succeeded.")
                    success = True
                else:
                    msg = spotiflac_failure_message(captured)
                    print(f"[Bypass] ✗ {service} (Tor) failed: {msg}")
                    if job.get("mode", "stream") == "stream":
                        manager._append_cache_event(job, "trying", f"{service} (Tor) failed: {msg}")
                    _has_audio(delete_invalid=True)

            if success: break
            print(f"[Bypass] ✗ {service} failed, moving to next provider...")
            manager._append_cache_event(job, "trying", f"{service} failed, trying next provider...")
            _rotate_tor_circuit()

    finally:
        _spotiflac_job_local.current_job = None
        _STREAM_CAPTURE.manager = None
        _STREAM_CAPTURE.job_id = ""
        sf_logger.removeHandler(handler)

    if not success:
        msg = spotiflac_failure_message(captured)
        raise RuntimeError(f"SpotiFLAC ({spotiflac_service}): {msg}")
