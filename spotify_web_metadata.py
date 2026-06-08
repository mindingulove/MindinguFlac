from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request


WEB_PLAYER_ALBUM_URL = "https://open.spotify.com/album/{album_id}"
QUERY_URL = "https://api-partner.spotify.com/pathfinder/v2/query"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
APP_VERSION = "896000000"
REQUEST_TIMEOUT_S = 18
REQUEST_RETRIES = 3
REQUEST_RETRY_DELAY_S = 0.5
ARTIST_ABOUT_CACHE_TTL_S = 600
ARTIST_ABOUT_FAILURE_TTL_S = 45
_playcount_cache: dict[str, tuple[float, dict[str, int]]] = {}
_artist_about_cache: dict[str, tuple[float, dict]] = {}


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionResetError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (TimeoutError, socket.timeout, ConnectionResetError, OSError))
    return isinstance(exc, OSError)


def _request_text(
    url: str,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = REQUEST_TIMEOUT_S,
    retries: int = REQUEST_RETRIES,
) -> str:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=request_headers)
    attempts = max(1, int(retries or 1))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _is_retryable_error(exc):
                raise
            delay = REQUEST_RETRY_DELAY_S * attempt
            print(f"[SpotifyWeb] Request retry {attempt}/{attempts - 1} for {url}: {exc}")
            time.sleep(delay)
    if last_error:
        raise last_error
    return ""


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

    def _pick_feature_image() -> str:
        if not gallery:
            return avatar
        def score(item: dict) -> tuple[int, int, int]:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            area = width * height
            aspect = (width / height) if width and height else 0
            # Prefer a real photo over a square logo/avatar tile.
            photo_bias = 1 if aspect >= 1.2 or aspect <= 0.85 else 0
            square_penalty = 1 if 0.9 <= aspect <= 1.1 else 0
            return (photo_bias, area, -square_penalty)
        picked = max(gallery, key=score)
        return picked.get("url", "") or avatar

    hero_image = _pick_feature_image()

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
        "hero_image": hero_image,
        "verified": bool(profile.get("verified")),
    }


def spotify_artist_about(artist_id: str) -> dict:
    if not artist_id:
        return {}
    cached = _artist_about_cache.get(artist_id)
    if cached:
        ttl = ARTIST_ABOUT_CACHE_TTL_S if cached[1] else ARTIST_ABOUT_FAILURE_TTL_S
        if time.time() - cached[0] < ttl:
            return cached[1]
    started = time.time()
    try:
        result = _load_artist_about(artist_id)
    except Exception as e:
        print(f"[SpotifyWeb] Error loading artist about for {artist_id} after {round(time.time() - started, 1)}s: {e}")
        if cached:
            return cached[1]
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


_WIKI_BASE = "https://en.wikipedia.org"


def _wiki_href_ok(href: str) -> str:
    """Keep only main-namespace article links (/wiki/Title with no namespace
    colon). Drops File:/Help:/Category: links, #cite anchors, and /w/index.php
    red links. Returns the absolute https URL or "" to unwrap to plain text."""
    if not href or not href.startswith("/wiki/"):
        return ""
    title = href[len("/wiki/"):]
    head = title.split("#", 1)[0]
    if not head or ":" in head:
        return ""
    return _WIKI_BASE + href


def _wiki_serialize_child(node) -> str:
    """Serialize one lxml node to a sanitized HTML string: keep p/a/b/i with
    safe attrs, drop references/IPA/style, unwrap everything else to text."""
    import html as _htmlmod
    tag = node.tag if isinstance(node.tag, str) else ""
    tail = _htmlmod.escape(node.tail or "")
    cls = node.get("class") or ""
    if tag in ("sup", "style", "script") or "IPA" in cls or "reference" in cls or "noprint" in cls:
        return tail
    inner = _htmlmod.escape(node.text or "")
    for child in node:
        inner += _wiki_serialize_child(child)
    if tag == "a":
        href = _wiki_href_ok(node.get("href") or "")
        if href:
            return (
                f'<a href="{_htmlmod.escape(href, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">{inner}</a>' + tail
            )
        return inner + tail
    if tag in ("b", "strong"):
        return f"<b>{inner}</b>" + tail
    if tag in ("i", "em"):
        return f"<i>{inner}</i>" + tail
    return inner + tail


def fetch_wikipedia_about(artist_name: str) -> dict:
    """Return {"text", "html", "image"} for an artist's Wikipedia page. "html"
    is the lead section with its inline article links preserved and sanitized;
    "text" is the plain-text fallback; "image" is the raw page-image URL (the
    caller is responsible for proxying it). Used as the bio fallback when
    Spotify has no data for the artist."""
    result = {"text": "", "html": "", "image": ""}
    try:
        from lxml import html as lxml_html
    except Exception:
        lxml_html = None

    try:
        params = urllib.parse.urlencode({
            "action": "parse", "format": "json", "prop": "text",
            "section": 0, "redirects": 1, "page": artist_name, "formatversion": 2,
        })
        data = json.loads(_request_text(f"https://en.wikipedia.org/w/api.php?{params}"))
        raw_html = (data.get("parse") or {}).get("text") or ""
        if isinstance(raw_html, dict):
            raw_html = raw_html.get("*", "")
        if raw_html and lxml_html is not None:
            root = lxml_html.fromstring(raw_html)
            paras, text_parts = [], []
            import html as _htmlmod
            # Skip infobox/hatnote paragraphs by excluding anything inside a table.
            for p in root.xpath("//p[not(ancestor::table)]"):
                # Drop reference markers, IPA pronunciation blobs and inline CSS so
                # both the plain text and the serialized HTML are clean.
                for bad in p.xpath(
                    './/style | .//sup | .//span[contains(@class,"IPA")] '
                    '| .//span[contains(@class,"reference")] '
                    '| .//span[contains(@class,"noprint")]'
                ):
                    bad.getparent().remove(bad)
                txt = " ".join((p.text_content() or "").split()).strip()
                if len(txt) < 40:
                    continue
                html_p = (_htmlmod.escape(p.text or "") + "".join(
                    _wiki_serialize_child(c) for c in p
                )).strip()
                if html_p:
                    paras.append(f"<p>{html_p}</p>")
                    text_parts.append(txt)
                if len(paras) >= 2:
                    break
            result["html"] = "".join(paras)
            result["text"] = "\n\n".join(text_parts)
    except Exception:
        pass

    try:
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "pageimages",
            "piprop": "original|thumbnail", "pithumbsize": 640,
            "titles": artist_name, "redirects": 1, "formatversion": 2,
        })
        data = json.loads(_request_text(f"https://en.wikipedia.org/w/api.php?{params}"))
        pages = (data.get("query") or {}).get("pages") or []
        if isinstance(pages, dict):
            pages = list(pages.values())
        for pg in pages:
            src = ((pg.get("original") or {}).get("source")) or ((pg.get("thumbnail") or {}).get("source")) or ""
            if src:
                result["image"] = src
                break
    except Exception:
        pass

    return result
