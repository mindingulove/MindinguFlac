from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import re
import struct
import time
import urllib.parse
import urllib.request


WEB_PLAYER_ALBUM_URL = "https://open.spotify.com/album/{album_id}"
QUERY_URL = "https://api-partner.spotify.com/pathfinder/v2/query"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
APP_VERSION = "896000000"
_playcount_cache: dict[str, tuple[float, dict[str, int]]] = {}
_artist_about_cache: dict[str, tuple[float, dict]] = {}


def _request_text(url: str, headers: dict[str, str] | None = None, data: bytes | None = None) -> str:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=request_headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def _totp(secret: bytes, timestamp: float) -> str:
    counter = int(timestamp) // 30
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 1_000_000).zfill(6)


def _web_player_config(path_id: str, is_artist: bool = False) -> tuple[int, str]:
    path = f"artist/{path_id}" if is_artist else f"album/{path_id}"
    html = _request_text(f"https://open.spotify.com/{path}")
    server_config = re.search(r'id="appServerConfig"[^>]*>([^<]+)', html)
    script = re.search(r'<script src="([^"]+/web-player\.[^"]+\.js)"', html)
    if not server_config or not script:
        raise ValueError("Spotify web-player configuration was not found")
    config = json.loads(base64.b64decode(server_config.group(1)))
    return int(config.get("serverTime") or time.time()), script.group(1)


@functools.lru_cache(maxsize=16)
def _query_contract(script_url: str) -> dict[str, str]:
    javascript = _request_text(script_url)
    
    # We need multiple hashes for different queries
    contracts = {}
    patterns = {
        "album": r'queryAlbumTracks","query","([0-9a-f]{64})"',
        "artist": r'queryArtistOverview","query","([0-9a-f]{64})"',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, javascript)
        if match:
            contracts[key] = match.group(1)
            
    token_secret = re.search(r"let eU=\[\{secret:(['\"])(.*?)\1,version:(\d+)", javascript)
    if not token_secret:
        raise ValueError("Spotify web-player secret contract was not found")
        
    encoded_secret = token_secret.group(2).encode("utf-8").decode("unicode_escape")
    secret = "".join(str(ord(char) ^ (index % 33 + 9)) for index, char in enumerate(encoded_secret)).encode()
    contracts["secret"] = secret
    contracts["token_version"] = token_secret.group(3)
    return contracts


def _anonymous_token(server_time: int, secret: bytes, token_version: str) -> str:
    query = urllib.parse.encode({
        "reason": "init",
        "productType": "web_player",
        "totp": _totp(secret, time.time()),
        "totpServer": _totp(secret, server_time),
        "totpVer": token_version,
    }) if hasattr(urllib.parse, 'encode') else urllib.parse.urlencode({
        "reason": "init",
        "productType": "web_player",
        "totp": _totp(secret, time.time()),
        "totpServer": _totp(secret, server_time),
        "totpVer": token_version,
    })
    response = json.loads(_request_text(f"https://open.spotify.com/api/token?{query}"))
    return response.get("accessToken", "")


def _load_album_playcounts(album_id: str) -> dict[str, int]:
    server_time, script_url = _web_player_config(album_id)
    contract = _query_contract(script_url)
    token = _anonymous_token(server_time, contract["secret"], contract["token_version"])
    if not token:
        return {}
    body = {
        "operationName": "queryAlbumTracks",
        "variables": {
            "uri": f"spotify:album:{album_id}",
            "locale": "",
            "offset": 0,
            "limit": 50,
        },
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": contract["album"]}},
    }
    response = json.loads(_request_text(
        QUERY_URL,
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "spotify-app-version": APP_VERSION,
        },
        json.dumps(body).encode("utf-8"),
    ))
    items = response.get("data", {}).get("albumUnion", {}).get("tracksV2", {}).get("items", [])
    playcounts = {}
    for item in items:
        track = item.get("track") or {} if isinstance(item, dict) else {}
        track_id = track.get("id") or str(track.get("uri", "")).removeprefix("spotify:track:")
        if track_id and str(track.get("playcount", "")).isdigit():
            playcounts[track_id] = int(track["playcount"])
    return playcounts


def spotify_album_playcounts(album_id: str) -> dict[str, int]:
    if not album_id:
        return {}
    cached = _playcount_cache.get(album_id)
    if cached and time.time() - cached[0] < 300:
        return cached[1]
    try:
        result = _load_album_playcounts(album_id)
    except Exception:
        result = {}
    _playcount_cache[album_id] = (time.time(), result)
    return result


def _load_artist_about(artist_id: str) -> dict:
    server_time, script_url = _web_player_config(artist_id, is_artist=True)
    contract = _query_contract(script_url)
    if "artist" not in contract:
        return {}
    token = _anonymous_token(server_time, contract["secret"], contract["token_version"])
    if not token:
        return {}
    
    body = {
        "operationName": "queryArtistOverview",
        "variables": {
            "uri": f"spotify:artist:{artist_id}",
            "locale": "",
            "includePrerelease": True,
        },
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": contract["artist"]}},
    }
    response = json.loads(_request_text(
        QUERY_URL,
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "spotify-app-version": APP_VERSION,
        },
        json.dumps(body).encode("utf-8"),
    ))
    
    data = response.get("data", {})
    artist = data.get("artistUnion") or data.get("artist") or {}
    stats = artist.get("stats") or {}
    visuals = artist.get("visuals") or {}
    profile = artist.get("profile") or {}
    
    # Extract images from visuals
    gallery = []
    for item in visuals.get("gallery", {}).get("items", []):
        sources = item.get("sources") or []
        if sources:
            # Pick highest resolution source
            top = max(sources, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
            gallery.append({
                "url": top["url"],
                "width": top.get("width"),
                "height": top.get("height"),
            })

    # Artist profile picture (distinct from gallery, which is often empty)
    avatar_sources = (visuals.get("avatarImage") or {}).get("sources") or []
    if not avatar_sources:
        # Fallback to visualIdentity if avatarImage is missing
        avatar_sources = (visuals.get("visualIdentity", {}).get("avatarImage") or {}).get("sources") or []
    
    avatar = ""
    if avatar_sources:
        top_avatar = max(avatar_sources, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
        avatar = top_avatar.get("url", "")

    return {
        "name": profile.get("name", ""),
        "monthly_listeners": stats.get("monthlyListeners") or stats.get("monthly_listeners") or 0,
        "global_chart_position": stats.get("globalChartPosition") or stats.get("global_chart_position") or 0,
        "followers": stats.get("followers") or 0,
        "biography": profile.get("biography", {}).get("text", ""),
        "top_cities": [
            {"city": c.get("city", ""), "country": c.get("country", ""), "count": c.get("numberOfListeners", c.get("numberOf_listeners", 0))}
            for c in (stats.get("topCities", {}).get("items") or [])
        ],
        "gallery": gallery,
        "avatar": avatar,
        "verified": bool(profile.get("verified")),
    }


def spotify_artist_about(artist_id: str) -> dict:
    if not artist_id:
        return {}
    cached = _artist_about_cache.get(artist_id)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    try:
        result = _load_artist_about(artist_id)
    except Exception as e:
        print(f"[SpotifyWeb] Error loading artist about for {artist_id}: {e}")
        result = {}
    _artist_about_cache[artist_id] = (time.time(), result)
    return result


def fetch_wikipedia_bio(artist_name: str) -> str:
    try:
        params = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "titles": artist_name,
            "redirects": 1,
        })
        url = f"https://en.wikipedia.org/w/api.php?{params}"
        data = json.loads(_request_text(url))
        pages = data.get("query", {}).get("pages", {})
        for page_id in pages:
            return pages[page_id].get("extract", "")
    except Exception:
        pass
    return ""
