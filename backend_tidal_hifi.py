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
    "https://api.monochrome.tf",
    "https://eu-central.monochrome.tf",
    "https://us-west.monochrome.tf",
    "https://hifi.geeked.wtf",
    "https://wolf.qqdl.site",
    "https://maus.qqdl.site",
    "https://vogel.qqdl.site",
    "https://katze.qqdl.site",
    "https://hund.qqdl.site",
    "https://tidal.kinoplus.online",
]
_FALLBACK_STREAMING = _FALLBACK_API.copy()

import base64
import random

_ORIGINS = [
    "https://monochrome.tf",
    "https://monochrome.samidy.com",
    "https://lossless.wtf",
    "https://if-it-runs-ship-it.lol",
]

def _get_headers() -> dict:
    origin = random.choice(_ORIGINS)
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": origin,
        "Referer": f"{origin}/",
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
        return {**_get_headers(), "Authorization": f"Bearer {token}"}
    except Exception:
        return _get_headers()

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
        resp = requests_module.get(_UPTIME_URL, headers=_get_headers(), timeout=10)
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
    hdrs = headers or _get_headers()
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
    resp = requests_module.get(media_m3u8_url, headers=_get_headers(), timeout=15)
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
            
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0 # SW_HIDE

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
            startupinfo=si,
        )

        # Parse ffmpeg stderr for time= progress in a background thread
        _time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        err_lines = []
        def _read_stderr():
            for line in proc.stderr:
                err_lines.append(line)
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
            err_output = "".join(err_lines)
            raise RuntimeError(f"ffmpeg HLS→FLAC failed (rc={proc.returncode}):\n{err_output}")
        if not flac_out.exists() or flac_out.stat().st_size < 1024:
            err_output = "".join(err_lines)
            raise RuntimeError(f"ffmpeg produced no output.\nFFmpeg log:\n{err_output}")
    finally:
        if tmp_m3u8 and os.path.exists(tmp_m3u8):
            os.unlink(tmp_m3u8)


def _download_dash_native(requests_module, mpd_url: str, flac_out: Path, job: dict, manager) -> None:
    """Parse a DASH MPD in python, download the fMP4 segments, and pipe them to ffmpeg for FLAC conversion."""
    import subprocess
    import sys as _sys
    import threading as _threading
    import xml.etree.ElementTree as ET

    headers = _get_headers()
    
    # Download and parse the MPD manifest
    resp = requests_module.get(mpd_url, headers=headers, timeout=20)
    resp.raise_for_status()
    mpd_text = resp.text

    try:
        root = ET.fromstring(mpd_text)
    except Exception as e:
        raise RuntimeError(f"Failed to parse DASH XML: {e}")

    ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
    template = root.find('.//dash:SegmentTemplate', ns)
    if template is None:
        # Fallback to direct download if no SegmentTemplate (e.g. single file DASH)
        base_url_node = root.find('.//dash:BaseURL', ns)
        if base_url_node is not None and base_url_node.text:
            return _download_direct(requests_module, base_url_node.text, flac_out, job, manager)
        raise RuntimeError("DASH manifest has no SegmentTemplate or BaseURL")

    init_url_template = template.attrib.get('initialization')
    media_url_template = template.attrib.get('media')
    start_number = int(template.attrib.get('startNumber', '1'))

    if not init_url_template or not media_url_template:
        raise RuntimeError("DASH SegmentTemplate missing initialization or media URLs")

    # Handle relative URLs using the original mpd_url
    from urllib.parse import urljoin
    init_url = urljoin(mpd_url, init_url_template)
    
    total_segments = 0
    for s in template.findall('.//dash:S', ns):
        r = int(s.attrib.get('r', '0'))
        total_segments += 1 + r

    if total_segments == 0:
        raise RuntimeError("No segments found in DASH manifest")

    if getattr(_sys, "frozen", False):
        _ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        _ffmpeg = os.path.join(_sys._MEIPASS, _ffmpeg_name)
    else:
        _ffmpeg = "ffmpeg"

    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0 # SW_HIDE

    # Start ffmpeg listening on stdin
    proc = subprocess.Popen(
        [
            _ffmpeg, "-y",
            "-i", "pipe:0",
            "-c:a", "flac",
            str(flac_out),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=si,
    )

    streaming_ready = False
    downloaded_chunks = 0
    
    # Strip Origin and Referer for actual media segments to avoid 403 Forbidden from Tidal's CDN
    cdn_headers = {"User-Agent": headers.get("User-Agent", "Mozilla/5.0")}
    
    try:
        # Route Init and Media segments through the audio proxy to ensure full track access
        def _get_proxied_resp(url: str):
            # Encode URL to ensure it passes through the proxy safely
            from urllib.parse import quote
            proxy_url = f"{_AUDIO_PROXY}/proxy-audio/{url}"
            r = requests_module.get(proxy_url, headers=cdn_headers, timeout=25)
            r.raise_for_status()
            return r

        # 1. Download Init segment
        init_resp = _get_proxied_resp(init_url)
        proc.stdin.write(init_resp.content)

        # 2. Download Media segments
        for i in range(total_segments):
            if job["id"] in manager._cancel_flags:
                raise RuntimeError("Download cancelled")

            current_number = start_number + i
            media_url = urljoin(mpd_url, media_url_template.replace("$Number$", str(current_number)))
            
            chunk_resp = _get_proxied_resp(media_url)
            proc.stdin.write(chunk_resp.content)

            
            downloaded_chunks += 1
            with manager._lock:
                job["progress"] = min(95, int((downloaded_chunks / total_segments) * 95))

            if not streaming_ready and flac_out.exists() and flac_out.stat().st_size > 0:
                if job.get("mode") == "stream":
                    manager._append_cache_event(job, "ready", f"Ready to play {flac_out.name}")
                streaming_ready = True

    except Exception as e:
        proc.kill()
        flac_out.unlink(missing_ok=True)
        raise RuntimeError(f"DASH streaming failed: {e}")
    finally:
        if proc.stdin:
            proc.stdin.close()

    proc.wait(timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg DASH→FLAC failed (rc={proc.returncode})")
    if not flac_out.exists() or flac_out.stat().st_size < 1024:
        raise RuntimeError("ffmpeg produced no output")


def _download_direct(requests_module, cdn_url: str, out: Path, job: dict, manager) -> None:
    """Stream a single BTS URL through the audio proxy, flushing each chunk."""
    proxy_url = f"{_AUDIO_PROXY}/proxy-audio/{cdn_url}"
    with requests_module.get(proxy_url, headers=_get_headers(), stream=True, timeout=600) as resp:
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

def _fetch_manifest(requests_module, base_url: str, track_id: int, quality: str = "LOSSLESS", headers: dict | None = None) -> tuple[str, str, str, bool] | None:
    """Return (manifest_text, mime_type, cdn_url, is_full) or None. Handle HLS, DASH, and BTS."""
    
    # Logic: Only send our Authorization token to official domains. 
    # Sending a 'free' client credentials token to community proxies often
    # causes them to downgrade the stream to a PREVIEW sample.
    hdrs = headers or _get_headers()
    is_official = any(x in base_url for x in ["monochrome.tf", "samidy.com", "lossless.wtf", "ship-it.lol"])
    
    if not is_official and "Authorization" in hdrs:
        hdrs = hdrs.copy()
        del hdrs["Authorization"]
        
    perms = [
        {"manifestType": "HLS",       "usage": "PLAYBACK"},
        {"manifestType": "HLS",       "usage": "DOWNLOAD"},
        {"manifestType": "MPEG_DASH", "usage": "PLAYBACK"},
        {"manifestType": "MPEG_DASH", "usage": "DOWNLOAD"},
    ]
    
    best_preview = None
    formats = "FLAC_HIRES" if "HI_RES" in quality else "FLAC"
    for p in perms:
        try:
            params = {"id": str(track_id), "quality": quality, "formats": formats, "adaptive": "false"}
            params.update(p)
            resp = requests_module.get(f"{base_url}/trackManifests/", params=params, headers=hdrs, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                attr = data.get("data", {}).get("data", {}).get("attributes", {}) or \
                       data.get("data", {}).get("attributes", {}) or \
                       data.get("attributes", {})
                
                is_preview = (attr.get("trackPresentation") == "PREVIEW")
                
                master_url = attr.get("uri", "") or data.get("uri", "")
                if master_url:
                    r2 = requests_module.get(master_url, headers=hdrs, timeout=12)
                    if r2.status_code == 200:
                        content = r2.text
                        mime = r2.headers.get("Content-Type", "") or p["manifestType"]
                        if "MPD" in content: mime = "application/dash+xml"
                        elif "EXTM3U" in content: mime = "application/vnd.apple.mpegurl"
                        
                        res = (content, mime, master_url, not is_preview)
                        if not is_preview:
                            return res
                        elif best_preview is None:
                            best_preview = res

        except Exception:
            continue

    if best_preview:
        return best_preview

    # 2. Try legacy /track/ endpoint
    try:
        resp = requests_module.get(f"{base_url}/track/", params={"id": track_id, "quality": quality}, headers=hdrs, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "data" in data: data = data["data"]
            manifest_b64 = data.get("manifest")
            mime = data.get("manifestMimeType", "")
            if manifest_b64:
                import base64
                content = base64.b64decode(manifest_b64).decode("utf-8", "ignore")
                return content, mime, "", True # Assume legacy is full if it works
    except Exception:
        pass

    return None

def _parse_bts(manifest_text: str) -> str:
    import json as _json
    import base64
    try:
        if manifest_text.strip().startswith("{"):
            decoded = _json.loads(manifest_text)
        else:
            decoded = _json.loads(base64.b64decode(manifest_text))
        
        urls = decoded.get("urls", [])
        if not urls:
            raise RuntimeError("BTS manifest has no URLs")
        return urls[0]
    except Exception as exc:
        raise RuntimeError(f"Failed to parse BTS manifest: {exc}")


def _find_best_hls_chunklist(requests_module, content: str, master_url: str, hdrs: dict) -> str | None:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            url_line = lines[i + 1].strip()
            if url_line.startswith("http"):
                return url_line
            else:
                from urllib.parse import urljoin
                return urljoin(master_url, url_line)
    return None

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

    # Prioritize official and known high-quality proxies
    prioritized_proxies = [
        "https://hifi-api.kennyy.com.br",
        "https://monochrome-api.samidy.com",
        "https://api.monochrome.tf",
    ]
    all_instances = prioritized_proxies + [u for u in api_instances if u not in prioritized_proxies]

    _log(f"Fetching stream manifest for track {track_id}...")
    manifest_info = None
    best_preview = None

    for s_url in all_instances:
        # Pass headers=None to use _get_headers() inside, which handles the is_official logic
        res = _fetch_manifest(requests, s_url, track_id, quality, headers=None)
        if res:
            if res[3]: # Is full
                manifest_info = res
                break
            elif best_preview is None:
                best_preview = res

    if not manifest_info:
        manifest_info = best_preview

    if manifest_info and not manifest_info[3]:
        _log("Full track unavailable on all known proxies, using PREVIEW sample.")

    if not manifest_info and quality == "HI_RES_LOSSLESS":
        _log("Hi-Res unavailable, trying LOSSLESS...")
        for s_url in all_instances:
            res = _fetch_manifest(requests, s_url, track_id, "LOSSLESS", headers=None)
            if res:
                if res[3]:
                    manifest_info = res
                    break
                elif best_preview is None:
                    best_preview = res
        
        if not manifest_info:
            manifest_info = best_preview

    if not manifest_info:
        raise RuntimeError(f"Tidal HiFi: no stream manifest for track {track_id} (proxies failed)")

    content, mime, master_url, is_full = manifest_info

    if "#EXTM3U" in content:
        chunklist = _find_best_hls_chunklist(requests, content, master_url, authed_headers)
        if not chunklist:
            raise RuntimeError("HLS manifest found, but no usable chunklist")
        
        _log(f"Downloading track {track_id} to FLAC via HLS...")
        flac_out = out_base.parent / (out_base.name + ".flac")
        _download_hls_ffmpeg(requests, chunklist, flac_out, job, manager)
        out = flac_out

    elif "dash" in mime.lower() or "<MPD" in content:
        _log(f"Downloading track {track_id} to FLAC via DASH...")
        flac_out = out_base.parent / (out_base.name + ".flac")
        _download_dash_native(requests, master_url, flac_out, job, manager)
        out = flac_out

    elif "bts" in mime.lower() or content.strip().startswith("{") or "urls" in content:
        cdn_url = _parse_bts(content)
        ext = ".flac" if ".flac" in cdn_url.lower() else ".m4a"
        out = out_base.parent / (out_base.name + ext)
        _log("Downloading Tidal stream via audio proxy...")
        _download_direct(requests, cdn_url, out, job, manager)
        
    else:
        raise RuntimeError("Unknown manifest format — cannot stream")

    if not is_valid_audio_file(out):
        out.unlink(missing_ok=True)
        raise RuntimeError("Tidal HiFi: downloaded file failed audio validation")

