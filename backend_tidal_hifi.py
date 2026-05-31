from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path

_UPTIME_URL = "https://tidal-uptime.geeked.wtf/"
_AUDIO_PROXY = "https://audio-proxy.binimum.org"

# tidal-proxy.monochrome.tf: authenticated Tidal proxy — always tried first
_MONOCHROME_PROXY = "https://tidal-proxy.monochrome.tf"
_AUTH_URL = "https://auth.tidal.com/v1/oauth2/token"
_CLIENT_ID = "txNoH4kkV41MfH25"
_CLIENT_SECRET = "dQjy0MinCEvxi1O4UmxvxWnDjt4cgHBPw8ll6nYBk98="

_FALLBACK_API = [
    "https://monochrome-api.samidy.com",
    "https://hifi-api.kennyy.com.br",
    "https://api.monochrome.tf",
    "https://tidal.kinoplus.online",
    "https://hifi.geeked.wtf",
    "https://hifi.binimum.org",
    "https://wolf.qqdl.site",
    "https://maus.qqdl.site",
    "https://vogel.qqdl.site",
    "https://katze.qqdl.site",
    "https://hund.qqdl.site",
]
_FALLBACK_STREAMING = [
    "https://monochrome-api.samidy.com",
    "https://hifi-api.kennyy.com.br",
    "https://api.monochrome.tf",
    "https://tidal.kinoplus.online",
    "https://hifi.geeked.wtf",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://monochrome.tf",
}

# ---------------------------------------------------------------------------
# Bearer token cache
# ---------------------------------------------------------------------------

_token_lock = threading.Lock()
_token_cache: dict = {}  # {"token": str, "expires_at": float}


def _get_bearer_token(requests_module) -> str:
    with _token_lock:
        if _token_cache.get("token") and time.time() < _token_cache.get("expires_at", 0):
            return _token_cache["token"]
        creds = base64.b64encode(f"{_CLIENT_ID}:{_CLIENT_SECRET}".encode()).decode()
        resp = requests_module.post(
            _AUTH_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "client_id": _CLIENT_ID, "client_secret": _CLIENT_SECRET},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        return _token_cache["token"]


def _auth_headers(requests_module) -> dict:
    try:
        token = _get_bearer_token(requests_module)
        return {**_HEADERS, "Authorization": f"Bearer {token}"}
    except Exception:
        return _HEADERS

_QUALITY_MAP = {
    "27": "HI_RES_LOSSLESS",
    "7":  "HI_RES_LOSSLESS",
    "6":  "LOSSLESS",
    "FLAC":            "LOSSLESS",
    "LOSSLESS":        "LOSSLESS",
    "HI_RES":          "HI_RES_LOSSLESS",
    "HI_RES_LOSSLESS": "HI_RES_LOSSLESS",
    "320": "HIGH",
    "HIGH": "HIGH",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


# ---------------------------------------------------------------------------
# Proxy list
# ---------------------------------------------------------------------------

def _fetch_instances(requests_module) -> tuple[list[str], list[str]]:
    try:
        resp = requests_module.get(_UPTIME_URL, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            live_api = [x["url"] for x in data.get("api", []) if x.get("url")]
            live_streaming = [x["url"] for x in data.get("streaming", []) if x.get("url")]
            # Always append fallbacks so all known instances are tried
            api = live_api + [u for u in _FALLBACK_API if u not in live_api]
            streaming = live_streaming + [u for u in _FALLBACK_STREAMING if u not in live_streaming]
            return api, streaming
    except Exception:
        pass
    return _FALLBACK_API, _FALLBACK_STREAMING


# ---------------------------------------------------------------------------
# Search / select
# ---------------------------------------------------------------------------

def _search(requests_module, base_url: str, title: str, artist: str, isrc: str, headers: dict | None = None) -> list[dict]:
    hdrs = headers or _HEADERS
    if isrc:
        try:
            resp = requests_module.get(
                f"{base_url}/search/",
                params={"i": isrc, "limit": 5},
                headers=hdrs,
                timeout=15,
            )
            if resp.status_code == 200:
                items = resp.json().get("data", {}).get("items", [])
                if items:
                    return items
        except Exception:
            pass
    query = f"{title} {artist}".strip()
    if not query:
        return []
    try:
        resp = requests_module.get(
            f"{base_url}/search/",
            params={"s": query, "limit": 15},
            headers=hdrs,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("items", [])
    except Exception:
        pass
    return []


def _select(items: list[dict], title: str, artist: str, isrc: str) -> dict | None:
    isrc_norm = _norm(isrc)
    title_norm = _norm(title)
    artist_norm = _norm(artist)
    for item in items:
        if isrc_norm and _norm(item.get("isrc", "")) == isrc_norm:
            return item
    for item in items:
        if title_norm and _norm(item.get("title", "")) == title_norm:
            item_artist = _norm((item.get("artist") or {}).get("name", ""))
            if not artist_norm or artist_norm in item_artist or item_artist in artist_norm:
                return item
    return items[0] if items else None


# ---------------------------------------------------------------------------
# HLS manifest from trackManifests endpoint
# ---------------------------------------------------------------------------

def _get_hls_url(requests_module, base_url: str, track_id: int, quality: str = "LOSSLESS", headers: dict | None = None) -> str | None:
    """Return the nested (media-level) m3u8 URL for a track, or None."""
    try:
        # Map quality to Tidal internal strings
        t_quality = "LOSSLESS"
        if "HI_RES" in quality: t_quality = "HI_RES"
        elif "HIGH" in quality: t_quality = "HIGH"

        hdrs = headers or _HEADERS
        resp = requests_module.get(
            f"{base_url}/trackManifests/",
            params={
                "id": str(track_id),
                "formats": "FLAC",
                "adaptive": "false",
                "manifestType": "HLS",
                "uriScheme": "HTTPS",
                "usage": "DOWNLOAD",
                "soundQuality": t_quality,
            },
            headers=hdrs,
            timeout=20,
        )
        if resp.status_code != 200:
            return None

        manifest_data = resp.json().get("data", {})
        master_url = manifest_data.get("data", {}).get("attributes", {}).get("uri", "")
        if not master_url:
            master_url = manifest_data.get("attributes", {}).get("uri", "")
        if not master_url:
            return None

        r2 = requests_module.get(master_url, headers=hdrs, timeout=15)
        if r2.status_code != 200:
            return None

        # master m3u8 → find the media-level m3u8 URL
        media_url = None
        for line in r2.text.splitlines():
            if line.strip() and not line.startswith("#"):
                media_rel = line.strip()
                media_url = urllib.parse.urljoin(master_url, media_rel)
                if "?" not in media_rel and "?" in master_url:
                    media_url += master_url[master_url.find("?"):]
                break

        if not media_url:
            return None

        # Fetch media playlist and reject previews by summing #EXTINF durations
        r3 = requests_module.get(media_url, headers=hdrs, timeout=15)
        if r3.status_code != 200:
            return None
        total_dur = sum(
            float(line.split(":")[1].split(",")[0])
            for line in r3.text.splitlines()
            if line.startswith("#EXTINF:")
        )
        if total_dur > 0 and total_dur < 60:
            return None

        return media_url
    except Exception:
        pass
    return None


def _rewrite_m3u8_for_proxy(m3u8_text: str, base_url: str) -> str:
    """Replace CDN URLs with audio-proxy URLs (for ffmpeg server-side download)."""
    out = []
    base_query = ""
    if "?" in base_url:
        base_query = base_url[base_url.find("?"):]

    for line in m3u8_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-MAP:URI=\""):
            def _sub(m):
                rel = m.group(1)
                url = urllib.parse.urljoin(base_url, rel)
                if "?" not in rel and base_query:
                    url += base_query
                return f'URI="{_AUDIO_PROXY}/proxy-audio/{url}"'
            line = re.sub(r'URI="([^"]+)"', _sub, line)
        elif stripped and not stripped.startswith("#"):
            url = urllib.parse.urljoin(base_url, stripped)
            if "?" not in stripped and base_query:
                url += base_query
            line = f"{_AUDIO_PROXY}/proxy-audio/{url}"
        out.append(line)
    return "\n".join(out)


def _rewrite_m3u8_for_local_proxy(m3u8_text: str, base_url: str) -> str:
    """Replace CDN URLs with /api/tidal_proxy?url=… (same-origin, for Safari HLS streaming)."""
    out = []
    base_query = ""
    if "?" in base_url:
        base_query = base_url[base_url.find("?"):]

    for line in m3u8_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-MAP:URI=\""):
            def _sub(m):
                rel = m.group(1)
                url = urllib.parse.urljoin(base_url, rel)
                if "?" not in rel and base_query:
                    url += base_query
                enc = urllib.parse.quote(url, safe="")
                return f'URI="/api/tidal_proxy?url={enc}"'
            line = re.sub(r'URI="([^"]+)"', _sub, line)
        elif stripped and not stripped.startswith("#"):
            url = urllib.parse.urljoin(base_url, stripped)
            if "?" not in stripped and base_query:
                url += base_query
            enc = urllib.parse.quote(url, safe="")
            line = f"/api/tidal_proxy?url={enc}"
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

def _download_hls_ffmpeg(requests_module, media_m3u8_url: str, flac_out: Path, job: dict, manager) -> None:
    """
    Fetch the HLS media playlist, rewrite segment URLs through audio-proxy,
    write a temp .m3u8, and run ffmpeg to convert → FLAC progressively.
    ffmpeg writes FLAC frames as it downloads each segment, so the output
    file grows in real-time and can be streamed to the browser immediately.
    """
    resp = requests_module.get(media_m3u8_url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    m3u8_text = resp.text
    rewritten = _rewrite_m3u8_for_proxy(m3u8_text, media_m3u8_url)

    total_dur = sum(
        float(line.split(":")[1].split(",")[0])
        for line in m3u8_text.splitlines()
        if line.startswith("#EXTINF:")
    )

    tmp_m3u8 = None
    proc = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".m3u8", delete=False) as f:
            f.write(rewritten)
            tmp_m3u8 = f.name

        import sys as _sys
        import threading as _threading
        if getattr(_sys, "frozen", False):
            _ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
            _ffmpeg = os.path.join(_sys._MEIPASS, _ffmpeg_name)
        else:
            _ffmpeg = "ffmpeg"
        proc = subprocess.Popen(
            [
                _ffmpeg, "-y",
                "-allowed_extensions", "ALL",
                "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-i", tmp_m3u8,
                "-c:a", "flac",
                str(flac_out),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Parse ffmpeg stderr for time= progress in a background thread
        _time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        def _read_stderr():
            for line in proc.stderr:
                m = _time_re.search(line)
                if m and total_dur > 0:
                    h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    current = h * 3600 + mn * 60 + s
                    with manager._lock:
                        job["progress"] = min(95, int(current / total_dur * 95))
        _stderr_thread = _threading.Thread(target=_read_stderr, daemon=True)
        _stderr_thread.start()

        streaming_ready = False
        while proc.poll() is None:
            if job["id"] in manager._cancel_flags:
                proc.terminate()
                proc.wait(timeout=5)
                flac_out.unlink(missing_ok=True)
                raise RuntimeError("Download cancelled")
            if not streaming_ready and flac_out.exists() and flac_out.stat().st_size > 0:
                if job.get("mode") == "stream":
                    manager._append_cache_event(job, "ready", f"Ready to play {flac_out.name}")
                streaming_ready = True
            time.sleep(0.5)
        _stderr_thread.join(timeout=2)

        if proc.returncode != 0:
            err_output = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"ffmpeg HLS→FLAC failed (rc={proc.returncode}): {err_output}")
        if not flac_out.exists() or flac_out.stat().st_size < 1024:
            raise RuntimeError("ffmpeg produced no output")
    finally:
        if tmp_m3u8 and os.path.exists(tmp_m3u8):
            os.unlink(tmp_m3u8)


def _download_direct(requests_module, cdn_url: str, out: Path, job: dict, manager) -> None:
    """Stream a single BTS URL through the audio proxy, flushing each chunk."""
    proxy_url = f"{_AUDIO_PROXY}/proxy-audio/{cdn_url}"
    with requests_module.get(proxy_url, headers=_HEADERS, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        streaming_ready = False
        with out.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if job["id"] in manager._cancel_flags:
                    out.unlink(missing_ok=True)
                    raise RuntimeError("Download cancelled")
                f.write(chunk)
                f.flush()
                done += len(chunk)

                if not streaming_ready and done > 0:
                    if job.get("mode") == "stream":
                        manager._append_cache_event(job, "ready", f"Ready to play {out.name}")
                    streaming_ready = True

                if total:
                    with manager._lock:
                        job["progress"] = min(95, int(done / total * 95))


# ---------------------------------------------------------------------------
# BTS manifest (direct single URL)
# ---------------------------------------------------------------------------

def _parse_bts(manifest_b64: str) -> str:
    import json as _json
    decoded = _json.loads(base64.b64decode(manifest_b64))
    urls = decoded.get("urls", [])
    if not urls:
        raise RuntimeError("BTS manifest has no URLs")
    return urls[0]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(output_dir: Path, job: dict, manager) -> None:
    import requests
    from service_downloader import is_valid_audio_file

    title  = job.get("title")  or "Unknown"
    artist = job.get("artist") or "Unknown"
    isrc   = job.get("isrc")   or (job.get("metadata") or {}).get("isrc") or ""
    quality = _QUALITY_MAP.get(str(job.get("quality") or "").upper(), "LOSSLESS")
    mode = job.get("mode", "stream")

    def _log(msg: str) -> None:
        if mode == "stream":
            manager._append_cache_event(job, "trying", msg)

    _log("Fetching Tidal proxy list...")
    api_instances, stream_instances = _fetch_instances(requests)

    # tidal-proxy.monochrome.tf with Bearer auth is the most reliable source — try first
    authed_headers = _auth_headers(requests)
    selected = None
    items = _search(requests, _MONOCHROME_PROXY, title, artist, isrc, headers=authed_headers)
    selected = _select(items, title, artist, isrc)

    if not selected:
        for api_url in api_instances:
            items = _search(requests, api_url, title, artist, isrc)
            selected = _select(items, title, artist, isrc)
            if selected:
                break

    if not selected:
        raise RuntimeError(f"Tidal HiFi: no match for {title!r} by {artist!r}")

    track_id = selected["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    out_base = output_dir / f"{title} - {artist}"

    # All instances to try: authenticated monochrome proxy first, then hifi proxies
    all_instances = list(stream_instances) + [u for u in api_instances if u not in stream_instances]

    # --- Try HLS: authenticated proxy first, then hifi instances ---
    hls_url = _get_hls_url(requests, _MONOCHROME_PROXY, track_id, quality, headers=authed_headers)
    if not hls_url:
        for s_url in all_instances:
            hls_url = _get_hls_url(requests, s_url, track_id, quality)
            if hls_url:
                break

    if hls_url:
        _log(f"Downloading track {track_id} to FLAC...")
        flac_out = out_base.parent / (out_base.name + ".flac")
        _download_hls_ffmpeg(requests, hls_url, flac_out, job, manager)
        out = flac_out
    else:
        # --- Fallback: /track/ BTS manifest — authenticated proxy first ---

        _log(f"HLS unavailable, fetching stream manifest for track {track_id}...")
        manifest_data = _get_manifest_raw(requests, _MONOCHROME_PROXY, track_id, quality, headers=authed_headers)
        if not manifest_data:
            for s_url in all_instances:
                manifest_data = _get_manifest_raw(requests, s_url, track_id, quality)
                if manifest_data:
                    break
        if not manifest_data and quality == "HI_RES_LOSSLESS":
            _log("Hi-Res unavailable, trying LOSSLESS...")
            manifest_data = _get_manifest_raw(requests, _MONOCHROME_PROXY, track_id, "LOSSLESS", headers=authed_headers)
            if not manifest_data:
                for s_url in all_instances:
                    manifest_data = _get_manifest_raw(requests, s_url, track_id, "LOSSLESS")
                    if manifest_data:
                        break
        if not manifest_data:
            raise RuntimeError(f"Tidal HiFi: no stream manifest for track {track_id}")

        manifest_b64  = manifest_data.get("manifest", "")
        manifest_mime = manifest_data.get("manifestMimeType", "")

        if "bts" in manifest_mime.lower():
            cdn_url = _parse_bts(manifest_b64)
            ext = ".flac" if ".flac" in cdn_url.lower() else ".m4a"
            out = out_base.parent / (out_base.name + ext)
            _log("Downloading Tidal stream via audio proxy...")
            _download_direct(requests, cdn_url, out, job, manager)
        else:
            raise RuntimeError("DASH-only manifest and HLS unavailable — cannot stream")

    if not is_valid_audio_file(out):
        out.unlink(missing_ok=True)
        raise RuntimeError("Tidal HiFi: downloaded file failed audio validation")


def _get_manifest_raw(requests_module, base_url: str, track_id: int, quality: str, headers: dict | None = None) -> dict | None:
    try:
        resp = requests_module.get(
            f"{base_url}/track/",
            params={"id": track_id, "quality": quality},
            headers=headers or _HEADERS,
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json().get("data")
    except Exception:
        pass
    return None
