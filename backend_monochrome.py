from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import unicodedata
from pathlib import Path

_DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}

def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())

def _item_value(item: dict, key: str) -> str:
    value = item.get(key)
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")

def _candidate_artist(item: dict) -> str:
    return _item_value(item, "performer") or _item_value(item, "artist")

def _same_artist(expected: str, actual: str) -> bool:
    expected_norm = _norm(expected)
    actual_norm = _norm(actual)
    return bool(
        expected_norm
        and actual_norm
        and (
            expected_norm == actual_norm
            or expected_norm in actual_norm
            or actual_norm in expected_norm
        )
    )

def _select_matching_item(items: list[dict], title: str, artist: str, isrc: str) -> dict | None:
    isrc_norm = _norm(isrc) if isrc else ""
    title_norm = _norm(title) if title and title != "Unknown" else ""
    expected_artist_norm = _norm(artist) if artist and artist != "Unknown" else ""

    for item in items:
        item_isrc = _norm(item.get("isrc"))
        item_title = _norm(item.get("title"))
        item_artist = _candidate_artist(item)
        
        if isrc_norm and item_isrc == isrc_norm:
            if not expected_artist_norm or _same_artist(artist, item_artist):
                return item
        if title_norm and item_title == title_norm:
            if not expected_artist_norm or _same_artist(artist, item_artist):
                return item
        if title_norm and expected_artist_norm:
            if _same_artist(artist, item_artist) and (title_norm in item_title or item_title in title_norm):
                return item
    return None

def _search_items(requests_module, query: str, offset: int = 0) -> list[dict]:
    # We use multiple sources for search to "fight the captcha"
    search_urls = [
        f"https://qobuz.squid.wtf/api/get-music?q={urllib.parse.quote(query)}&offset={offset}",
        f"https://qobuz.kennyy.com.br/api/get-music?q={urllib.parse.quote(query)}&offset={offset}",
        f"https://qobuz.squid.wtf/api/search?q={urllib.parse.quote(query)}",
    ]
    
    for url in search_urls:
        try:
            resp = requests_module.get(url, headers=_DEFAULT_HEADERS, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success"):
                    d = data.get("data", {})
                    if isinstance(d, dict):
                        if "tracks" in d and "items" in d["tracks"]:
                            return d["tracks"]["items"]
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], dict) and "items" in data["data"]:
                        return data["data"]["items"]
                    if "items" in data:
                        return data["items"]
                    if "tracks" in data and "items" in data["tracks"]:
                        return data["tracks"]["items"]
        except Exception:
            continue
    return []

def _extract_qobuz_stream_url(body: bytes) -> str | None:
    try:
        data = json.loads(body)
        for key in ["download_url", "url"]:
            val = data.get(key)
            if val and str(val).startswith("http"):
                return str(val)
        nested = data.get("data", {})
        if isinstance(nested, dict):
            for key in ["download_url", "url"]:
                val = nested.get(key)
                if val and str(val).startswith("http"):
                    return str(val)
    except Exception:
        pass
    return None

def _fetch_dab(track_id: str, qid: str) -> str | None:
    from curl_cffi import requests as _requests
    # Expanded list of mirrors and subdomains
    endpoints = [
        ("Kennyy",    "https://qobuz.kennyy.com.br/api/download-music", f"?track_id={track_id}&quality={qid}"),
        ("Squid US",  "https://us.qobuz.squid.wtf/api/download-music", f"?trackId={track_id}&quality={qid}"),
        ("Squid FR",  "https://fr.qobuz.squid.wtf/api/download-music", f"?trackId={track_id}&quality={qid}"),
        ("Squid DE",  "https://de.qobuz.squid.wtf/api/download-music", f"?trackId={track_id}&quality={qid}"),
        ("Squid",     "https://qobuz.squid.wtf/api/download-music", f"?trackId={track_id}&quality={qid}"),
        ("DAB Yeet",  "https://dab.yeet.su/api/stream", f"?trackId={track_id}&quality={qid}"),
        ("DAB Music", "https://dabmusic.xyz/api/stream", f"?trackId={track_id}&quality={qid}"),
    ]
    for name, base, params in endpoints:
        try:
            url = base + params
            # chrome120 impersonation is quite strong against CF
            resp = _requests.get(url, headers=_DEFAULT_HEADERS, impersonate="chrome120", timeout=60)
            if resp.status_code == 200:
                u = _extract_qobuz_stream_url(resp.content)
                if u: return u
        except Exception: continue
    return None

def run(output_dir: Path, job: dict, manager) -> None:
    import requests as _requests
    from service_downloader import is_valid_audio_file

    isrc = job.get("isrc") or (job.get("metadata") or {}).get("isrc") or ""
    quality_str = str(job.get("quality") or "27")
    fmt = "mp3" if quality_str == "5" else "flac"
    ext = ".mp3" if fmt == "mp3" else ".flac"
    mode = job.get("mode", "stream")

    title = job.get("title") or "Unknown"
    artist = job.get("artist") or "Unknown"
    query = isrc if isrc else f"{title} {artist}"

    if mode == "stream":
        label = f"ISRC {isrc}" if isrc else f"{title} – {artist}"
        manager._append_cache_event(job, "trying", f"Looking up {label} via DAB/Squid...")

    selected = None
    all_returned_items = []
    
    items = _search_items(_requests, query, offset=0)
    all_returned_items.extend(items)
    selected = _select_matching_item(items, title, artist, isrc)
    
    if selected is None and isrc:
        fallback_items = _search_items(_requests, f"{title} {artist}", offset=0)
        all_returned_items.extend(fallback_items)
        selected = _select_matching_item(fallback_items, title, artist, isrc)
    
    if selected is None:
        deep_items = _search_items(_requests, query, offset=10)
        all_returned_items.extend(deep_items)
        selected = _select_matching_item(deep_items, title, artist, isrc)

    if not selected:
        returned_artists = sorted({_candidate_artist(item) for item in all_returned_items if _candidate_artist(item)})
        details = f"; returned: {', '.join(returned_artists[:5])}" if returned_artists else ""
        raise RuntimeError(f"DAB/Squid: no matching track for {title!r}{details}")

    # Ensure track_id is a raw string/number as expected by proxies
    track_id_val = str(selected["id"])

    if mode == "stream":
        manager._append_cache_event(job, "trying", f"Fetching stream URL for ID {track_id_val}...")

    qid = "27" if quality_str == "27" else "7" if quality_str == "7" else "6"
    stream_url = _fetch_dab(track_id_val, qid)

    if not stream_url:
        raise RuntimeError("DAB and Squid proxies failed to provide a stream URL (Captcha required)")

    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / f"{title} - {artist}{ext}.part"
    final_path = output_dir / f"{title} - {artist}{ext}"

    with _requests.get(stream_url, headers=_DEFAULT_HEADERS, stream=True, timeout=600) as cdn_resp:
        cdn_resp.raise_for_status()
        total = int(cdn_resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(part_path, "wb") as f:
            for chunk in cdn_resp.iter_content(chunk_size=65536):
                if job["id"] in manager._cancel_flags:
                    part_path.unlink(missing_ok=True)
                    raise RuntimeError("Download cancelled")
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    with manager._lock:
                        job["progress"] = min(95, int(downloaded / total * 95))

    part_path.rename(final_path)
    if not is_valid_audio_file(final_path):
        final_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is not valid audio")
