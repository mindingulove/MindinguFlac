from __future__ import annotations

import functools
import urllib.parse


def resolve_isrc(title: str, artist: str, spotify_id: str = "") -> str:
    """Return ISRC for a track using available fallback sources.

    Sources tried in order:
    1. Spotify direct track lookup (requires spotify_id)
    2. Qobuz Squid API (qobuz.squid.wtf) — no auth required, title+artist search
    """
    if spotify_id:
        isrc = _spotify_isrc(spotify_id)
        if isrc:
            return isrc
    return _squid_isrc(title, artist)


@functools.lru_cache(maxsize=1024)
def _spotify_isrc(spotify_id: str) -> str:
    if not spotify_id:
        return ""
    try:
        from music_metadata import _sp
        data = _sp("tracks", ids=spotify_id)
        tracks = data.get("tracks") or []
        if tracks and isinstance(tracks, list):
            ext = (tracks[0].get("external_ids") or {})
            return ext.get("isrc") or ""
        # single-track endpoint fallback
        data = _sp(f"tracks/{spotify_id}")
        return (data.get("external_ids") or {}).get("isrc") or ""
    except Exception:
        return ""


@functools.lru_cache(maxsize=1024)
def _squid_isrc(title: str, artist: str) -> str:
    if not title and not artist:
        return ""
    try:
        import requests as _requests
        q = urllib.parse.quote(f"{title} {artist}")
        resp = _requests.get(
            f"https://qobuz.squid.wtf/api/get-music?q={q}&offset=0",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://qobuz.squid.wtf/",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = ((resp.json().get("data") or {}).get("tracks") or {}).get("items") or []
        if items:
            return items[0].get("isrc") or ""
    except Exception:
        pass
    return ""
