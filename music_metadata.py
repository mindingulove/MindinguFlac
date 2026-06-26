from __future__ import annotations

import base64
import hashlib
import hmac
import json
import html
import socket
import struct
import time
import functools
from collections import OrderedDict
import urllib.error
import urllib.parse
import urllib.request
import rapidfuzz
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import db
from config import AppConfig, MusicIndexerConfig
from discogs_metadata import discogs_album_images


USER_AGENT = "Streambox/1.0 (self-hosted; https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)"


def release_year(value: str) -> str:
    return (value or "")[:4] if value and len(value) >= 4 and value[:4].isdigit() else ""


def norm_name(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def query_tokens(value: str) -> list[str]:
    ignored = {"the", "a", "an", "and", "or", "of", "in", "on", "to", "for"}
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if len(token) > 1 and token not in ignored]


def format_duration_ms(milliseconds: int) -> str:
    if not milliseconds:
        return ""
    total_seconds = max(0, int(milliseconds // 1000))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@functools.lru_cache(maxsize=1024)
def get_json(url: str, timeout: int = 10) -> dict:
    # Respectful delay for MusicBrainz
    time.sleep(0.5)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def cover_art_url(release_id: str) -> str:
    return f"/api/artwork/{urllib.parse.quote(release_id)}" if release_id else ""


def caa_artwork(release_id: str) -> list[dict]:
    if not release_id:
        return []
    try:
        data = get_json(f"https://coverartarchive.org/release/{release_id}")
        images = []
        for img in data.get("images") or []:
            # The 'image' key in CAA is the original uncompressed upload
            url = img.get("image")
            if not url:
                continue
            images.append({
                "url": proxy_artwork_url(url),
                "full_url": proxy_artwork_url(url),
                "source": "MusicBrainz CAA",
                "label": "Original Scan" if img.get("front") else "Artwork",
                "width": 1200,  # Placeholder, will be sorted by 'front' priority
                "height": 1200,
                "is_front": bool(img.get("front")),
            })
        return images
    except Exception:
        return []


def proxy_artwork_url(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    spotify_prefix = "ab67616d000082c1"
    image_id = parsed.path.rsplit("/", 1)[-1]
    if parsed.netloc == "i.scdn.co" and image_id.startswith(spotify_prefix):
        repaired_id = image_id[len(spotify_prefix):]
        if re.fullmatch(r"[0-9a-fA-F]{40}", repaired_id):
            url = urllib.parse.urlunparse(parsed._replace(path=parsed.path.rsplit("/", 1)[0] + "/" + repaired_id))
    # Always route through our backend proxy to fix CORS/Broken images
    return "/api/image?" + urllib.parse.urlencode({"url": url})


def lyrics_lookup_url(artist: str, title: str) -> str:
    return "https://api.lyrics.ovh/v1/" + urllib.parse.quote(artist) + "/" + urllib.parse.quote(title) if artist and title else ""


# ---------------------------------------------------------------------------
# SpotiFLAC / Spotify helpers
# ---------------------------------------------------------------------------

_spotify_client_cache = None
_spotify_client_lock = threading.Lock()


def _get_spotify_client(force_refresh: bool = False):
    global _spotify_client_cache
    with _spotify_client_lock:
        if force_refresh and _spotify_client_cache not in (None, False):
            _spotify_client_cache = None
        if _spotify_client_cache is not None:
            return _spotify_client_cache if _spotify_client_cache is not False else None
        try:
            from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
            _spotify_client_cache = SpotifyMetadataClient()
            return _spotify_client_cache
        except ImportError:
            _spotify_client_cache = False
            return None
        except Exception:
            _spotify_client_cache = None
            return None


def _reset_spotify_client_cache() -> None:
    global _spotify_client_cache
    with _spotify_client_lock:
        _spotify_client_cache = None


_spotify_artist_id_cache_lock = threading.Lock()
_spotify_artist_id_cache: OrderedDict[str, str] = OrderedDict()
_spotify_artist_top_tracks_cache_lock = threading.Lock()
_spotify_artist_top_tracks_cache: OrderedDict[tuple[str, int, str], list[dict]] = OrderedDict()
_SPOTIFY_ARTIST_CACHE_SIZE = 128


def clear_spotify_artist_caches() -> None:
    with _spotify_artist_id_cache_lock:
        _spotify_artist_id_cache.clear()
    with _spotify_artist_top_tracks_cache_lock:
        _spotify_artist_top_tracks_cache.clear()


def _numeric_plays(value: object) -> int:
    try:
        return int(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _legacy_track_item(item: object) -> dict:
    if isinstance(item, dict) and "name" in item:
        return item
    artist_names = [name.strip() for name in str(getattr(item, "artists", "") or "").split(",") if name.strip()]
    cover_url = getattr(item, "cover_url", "") or ""
    return {
        "id": getattr(item, "id", "") or "",
        "name": getattr(item, "title", "") or "",
        "artists": [{"name": name} for name in artist_names],
        "album": {
            "name": getattr(item, "album", "") or "",
            "images": [{"url": cover_url}] if cover_url else [],
        },
        "duration_ms": getattr(item, "duration_ms", 0) or 0,
        "external_urls": {"spotify": getattr(item, "external_url", "") or ""},
        "external_ids": {"isrc": getattr(item, "isrc", "") or ""},
        "popularity": _numeric_plays(getattr(item, "plays", 0)) // 10000,
    }


def _legacy_simple_item(item: dict, kind: str) -> dict:
    cover_url = item.get("cover_url", "")
    artists = item.get("artists", "")
    if isinstance(artists, str):
        artists = [{"name": name.strip()} for name in artists.split(",") if name.strip()]
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "artists": artists or [],
        "images": [{"url": cover_url}] if cover_url else [],
        "release_date": item.get("release_date", ""),
        "release_type": item.get("release_type", ""),
        "external_urls": {"spotify": item.get("external_url", "")},
        "popularity": _numeric_plays(item.get("plays", 0)) // 10000,
        "type": kind,
    }


def _raw_search_simple_items(client: object, query: str, limit: int, kind: str) -> list[dict]:
    web_client = getattr(client, "web_client", None)
    payload_builder = getattr(client, "_search_payload", None)
    if not web_client or not payload_builder:
        return []
    try:
        search = web_client.query(payload_builder(query, limit)).get("data", {}).get("searchV2", {})
    except Exception:
        return []
    section = search.get("albumsV2" if kind == "album" else "artists", {})
    results = []
    for wrapper in section.get("items", []):
        node = wrapper.get("data") or wrapper.get("item", {}).get("data", {})
        uri = node.get("uri", "")
        spotify_id = node.get("id", "") or (uri.rsplit(":", 1)[-1] if uri else "")
        if not spotify_id:
            continue
        if kind == "album":
            results.append({
                "id": spotify_id,
                "name": node.get("name", ""),
                "artists": ", ".join(
                    item.get("profile", {}).get("name", "")
                    for item in node.get("artists", {}).get("items", [])
                    if item.get("profile", {}).get("name")
                ),
                "cover_url": _best_raw_image(node.get("coverArt", {})),
                "release_date": node.get("date", {}).get("isoString", ""),
                "external_url": f"https://open.spotify.com/album/{spotify_id}",
            })
        else:
            results.append({
                "id": spotify_id,
                "name": node.get("profile", {}).get("name", node.get("name", "")),
                "cover_url": _best_raw_image((node.get("visualIdentity") or {}).get("squareCoverImage", {})),
                "external_url": f"https://open.spotify.com/artist/{spotify_id}",
            })
    return results


def _raw_artist_discography_items(client: object, artist_id: str) -> list[dict]:
    web_client = getattr(client, "web_client", None)
    fetch_discography = getattr(web_client, "get_artist_discography", None)
    if not fetch_discography or not artist_id:
        return []
    try:
        items = fetch_discography(artist_id)
    except Exception:
        return []

    results = []
    seen = set()
    for item in items:
        release = {}
        releases = item.get("releases") if isinstance(item, dict) else None
        release_items = releases.get("items") if isinstance(releases, dict) else None
        if release_items:
            release = release_items[0] or {}
        elif isinstance(item, dict):
            release = item.get("album") or item
        release_type = str(release.get("type", "")).upper()
        if release_type == "APPEARS_ON":
            continue
        uri = release.get("uri", "")
        spotify_id = release.get("id", "") or (uri.rsplit(":", 1)[-1] if uri else "")
        if not spotify_id or spotify_id in seen:
            continue
        seen.add(spotify_id)
        results.append({
            "id": spotify_id,
            "name": release.get("name", ""),
            "cover_url": _best_raw_image(release.get("coverArt", {})),
            "release_date": release.get("date", {}).get("isoString", ""),
            "external_url": f"https://open.spotify.com/album/{spotify_id}",
            "release_type": release_type,
        })
    return results


def _raw_artist_top_track_items(client: object, artist_id: str, limit: int = 20) -> list[dict]:
    web_client = getattr(client, "web_client", None)
    if not web_client or not artist_id:
        return []
    payload = {
        "operationName": "queryArtistOverview",
        "variables": {"uri": f"spotify:artist:{artist_id}", "locale": ""},
        "extensions": {"persistedQuery": {
            "version": 1,
            "sha256Hash": "446130b4a0aa6522a686aafccddb0ae849165b5e0436fd802f96e0243617b5d8",
        }},
    }
    try:
        artist_data = web_client.query(payload).get("data", {}).get("artistUnion", {})
    except Exception:
        return []
    items = (
        artist_data.get("discography", {})
        .get("topTracks", {})
        .get("items", [])
    )
    results = []
    for wrapper in items[:limit]:
        track = wrapper.get("track") if isinstance(wrapper, dict) else None
        if not isinstance(track, dict):
            continue
        uri = track.get("uri", "")
        spotify_id = track.get("id", "") or (uri.rsplit(":", 1)[-1] if uri else "")
        if not spotify_id:
            continue
        album = track.get("albumOfTrack", {}) or {}
        artists = []
        artist_items = (track.get("artists", {}) or {}).get("items", [])
        for item in artist_items:
            if not isinstance(item, dict):
                continue
            name = (item.get("profile") or {}).get("name", "")
            if name:
                artists.append({"name": name})
        results.append({
            "id": spotify_id,
            "name": track.get("name", ""),
            "artists": artists,
            "album": {
                "name": album.get("name", ""),
                "images": [{"url": _best_raw_image(album.get("coverArt", {}))}] if album.get("coverArt") else [],
            },
            "duration_ms": (track.get("duration") or {}).get("totalMilliseconds", 0) or 0,
            "external_urls": {"spotify": f"https://open.spotify.com/track/{spotify_id}"},
            "external_ids": {"isrc": ""},
            "popularity": _numeric_plays(track.get("playcount")) // 10000,
        })
    return results


def _best_raw_image(image: dict | None) -> str:
    sources = (image or {}).get("sources", [])
    if not sources:
        sources = (image or {}).get("image", {}).get("data", {}).get("sources", [])
    return max(sources, key=lambda item: item.get("width", 0), default={}).get("url", "")


def _public_client_get(client: object, endpoint: str, params: dict) -> dict:
    """Expose SpotiFLAC 0.6.1 public methods in the legacy response shape."""
    from spotiflac_compat import call_sync_or_async

    if endpoint == "search":
        query = params.get("q", "")
        limit = int(params.get("limit", 20))
        results = call_sync_or_async(client, "search", "search_async", query, limit=limit)
        albums = results.get("albums", []) or _raw_search_simple_items(client, query, limit, "album")
        artists = results.get("artists", []) or _raw_search_simple_items(client, query, limit, "artist")
        return {
            "tracks": {"items": [_legacy_track_item(item) for item in results.get("tracks", [])]},
            "albums": {"items": [_legacy_simple_item(item, "album") for item in albums]},
            "artists": {"items": [_legacy_simple_item(item, "artist") for item in artists]},
        }

    playlist_match = re.fullmatch(r"playlists/([^/]+)/tracks", endpoint)
    if playlist_match:
        playlist_result = call_sync_or_async(
            client, "get_playlist_tracks", "get_playlist_tracks_async", playlist_match.group(1)
        )
        tracks = playlist_result[1] if len(playlist_result) > 1 else []
        limit = int(params.get("limit", len(tracks)))
        return {"items": [{"track": _legacy_track_item(item)} for item in tracks[:limit]]}

    album_match = re.fullmatch(r"albums/([^/]+)", endpoint)
    if album_match:
        info, tracks = call_sync_or_async(
            client, "get_album_tracks", "get_album_tracks_async", album_match.group(1)
        )
        cover_url = info.get("cover_url", "")
        return {
            "id": album_match.group(1),
            "name": info.get("name", ""),
            "images": [{"url": cover_url}] if cover_url else [],
            "tracks": {"items": [_legacy_track_item(item) for item in tracks]},
        }

    artist_top_match = re.fullmatch(r"artists/([^/]+)/top-tracks", endpoint)
    if artist_top_match and (
        hasattr(client, "get_artist_profile")
        or hasattr(client, "get_artist_profile_async")
        or getattr(client, "web_client", None)
    ):
        from spotiflac_compat import call_sync_or_async

        artist_id = artist_top_match.group(1)
        limit = int(params.get("limit", 20) or 20)
        tracks = _raw_artist_top_track_items(client, artist_id, limit=limit)
        if tracks:
            return {"tracks": tracks}
        profile = call_sync_or_async(
            client, "get_artist_profile", "get_artist_profile_async", artist_id
        )
        artist = profile.get("profile", {}).get("name", "")
        tracks = (
            call_sync_or_async(client, "search_tracks", "search_tracks_async", artist, limit=limit)
            if artist
            else []
        )
        return {"tracks": [_legacy_track_item(item) for item in tracks]}

    return {}


def _sp(endpoint: str, **params) -> dict:
    client = _get_spotify_client()
    if not client:
        return {}
    try:
        if hasattr(client, "_get"):
            return client._get(endpoint, params=params) or {}
        return _public_client_get(client, endpoint, params)
    except Exception:
        return {}


def odesli_lookup(spotify_url: str) -> dict:
    if not spotify_url: return {}
    try:
        url = "https://api.song.link/v1-alpha.1/links?" + urllib.parse.urlencode({"url": spotify_url, "userCountry": "US"})
        req = urllib.request.Request(url, headers={"User-Agent": "Streambox/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        links = data.get("linksByPlatform") or {}
        entities = data.get("entitiesByUniqueId") or {}
        results = {}
        for platform, info in links.items():
            results[f"{platform}_url"] = info.get("url")
            u = info.get("url", "")
            entity = entities.get(info.get("entityUniqueId", "")) or {}
            provider_id = entity.get("id", "")
            if platform == "deezer" or "deezer.com" in u:
                results["deezer_id"] = provider_id or u.split("/")[-1].split("?")[0]
            if platform == "tidal" or "tidal.com" in u:
                results["tidal_id"] = provider_id or u.split("/")[-1].split("?")[0]
            if platform in {"amazonMusic", "amazonStore"} or "amazon.com" in u:
                results["amazon_id"] = provider_id or u.split("/")[-1].split("?")[0]
            if platform == "appleMusic" or "apple.com" in u:
                results["apple_music_id"] = provider_id or u.split("/")[-1].split("?")[0]
        return results
    except Exception: return {}


@functools.lru_cache(maxsize=2048)
def deezer_track_identifiers(deezer_id: str, artist: str, title: str, duration_ms: int = 0) -> dict:
    if not deezer_id:
        return {}
    try:
        data = get_json(f"https://api.deezer.com/track/{urllib.parse.quote(str(deezer_id))}")
    except Exception:
        return {}
    deezer_artist = (data.get("artist") or {}).get("name", "")
    if norm_name(data.get("title", "")) != norm_name(title):
        return {}
    if artist and deezer_artist and norm_name(deezer_artist) != norm_name(artist):
        return {}
    deezer_duration_ms = int(data.get("duration") or 0) * 1000
    tolerance = max(5000, int(duration_ms * 0.03)) if duration_ms else 0
    if duration_ms and deezer_duration_ms and abs(deezer_duration_ms - duration_ms) > tolerance:
        return {}
    identifiers = {
        "isrc": data.get("isrc", ""),
        "deezer_artist_id": (data.get("artist") or {}).get("id", ""),
        "deezer_album_id": (data.get("album") or {}).get("id", ""),
    }
    return {key: value for key, value in identifiers.items() if value}


@functools.lru_cache(maxsize=2048)
def musicbrainz_recording_identifiers(artist: str, title: str, album: str = "", duration_ms: int = 0) -> dict:
    if not artist or not title:
        return {}
    album_candidates = []
    for candidate in (album, re.sub(r"\s*\([^)]*\)", "", album).strip()):
        if candidate and candidate not in album_candidates:
            album_candidates.append(candidate)
    if not album_candidates:
        album_candidates.append("")

    candidates = []
    for album_candidate in album_candidates:
        terms = [f'recording:"{title}"', f'artist:"{artist}"']
        if album_candidate:
            terms.append(f'release:"{album_candidate}"')
        try:
            url = "https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode({
                "query": " AND ".join(terms),
                "limit": "20",
                "fmt": "json",
                "inc": "isrcs+artist-credits",
            })
            candidates = get_json(url).get("recordings", [])
        except Exception:
            continue
        if candidates:
            break

    exact = [
        recording for recording in candidates
        if norm_name(recording.get("title", "")) == norm_name(title)
        and any(norm_name(credit.get("name", "")) == norm_name(artist) for credit in recording.get("artist-credit", []))
    ]
    if not exact:
        return {}
    if duration_ms:
        exact.sort(key=lambda item: abs(int(item.get("length") or 0) - duration_ms) if item.get("length") else 10**12)
        selected = exact[0]
        selected_length = int(selected.get("length") or 0)
        tolerance = max(5000, int(duration_ms * 0.03))
        if selected_length and abs(selected_length - duration_ms) > tolerance:
            return {}
    else:
        selected = exact[0]

    identifiers = {"musicbrainz_recording_id": selected.get("id", "")}
    isrcs = selected.get("isrcs") or []
    if isrcs:
        identifiers["isrc"] = isrcs[0]
    artist_fields = _ac_fields(selected.get("artist-credit") or [])
    identifiers.update({key: value for key, value in artist_fields.items() if value})
    return {key: value for key, value in identifiers.items() if value}


def _musicbrainz_unique_genres(raw: object) -> list[str]:
    genres: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                genres.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("genre") or item.get("title")
                if isinstance(name, str) and name:
                    genres.append(name)
    elif isinstance(raw, dict):
        for item in raw.values():
            if isinstance(item, str):
                genres.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("genre") or item.get("title")
                if isinstance(name, str) and name:
                    genres.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for genre in genres:
        key = norm_name(genre)
        if key and key not in seen:
            seen.add(key)
            out.append(genre)
    return out


_MB_GENRE_RELEASE_CACHE: dict[str, list] = {}
_MB_GENRE_RECORDING_CACHE: dict[str, list] = {}
_MB_GENRE_TRACK_CACHE: dict[tuple, list] = {}


def musicbrainz_genres_for_release(release_id: str) -> list[str]:
    release_id = str(release_id or "").strip()
    if not release_id:
        return []
    if release_id in _MB_GENRE_RELEASE_CACHE:
        return _MB_GENRE_RELEASE_CACHE[release_id]
    try:
        data = get_json(
            f"https://musicbrainz.org/ws/2/release/{urllib.parse.quote(release_id)}?"
            + urllib.parse.urlencode({"inc": "genres", "fmt": "json"})
        )
        result = _musicbrainz_unique_genres(data.get("genres") or data.get("genre") or [])
    except Exception:
        result = []
    if result:
        _MB_GENRE_RELEASE_CACHE[release_id] = result
    return result


def musicbrainz_genres_for_recording(recording_id: str) -> list[str]:
    recording_id = str(recording_id or "").strip()
    if not recording_id:
        return []
    if recording_id in _MB_GENRE_RECORDING_CACHE:
        return _MB_GENRE_RECORDING_CACHE[recording_id]
    try:
        data = get_json(
            f"https://musicbrainz.org/ws/2/recording/{urllib.parse.quote(recording_id)}?"
            + urllib.parse.urlencode({"inc": "genres", "fmt": "json"})
        )
        result = _musicbrainz_unique_genres(data.get("genres") or data.get("genre") or [])
    except Exception:
        result = []
    if result:
        _MB_GENRE_RECORDING_CACHE[recording_id] = result
    return result


def musicbrainz_genres_for_track(artist: str, title: str, album: str = "", duration_ms: int = 0) -> list[str]:
    artist = str(artist or "").strip()
    title = str(title or "").strip()
    album = str(album or "").strip()
    if not artist or not title:
        return []
    _cache_key = (artist.lower(), title.lower(), album.lower(), duration_ms)
    if _cache_key in _MB_GENRE_TRACK_CACHE:
        return _MB_GENRE_TRACK_CACHE[_cache_key]
    ids = musicbrainz_recording_identifiers(artist, title, album, duration_ms)
    recording_id = str(ids.get("musicbrainz_recording_id") or "").strip()
    result: list[str] = []
    if recording_id:
        result = musicbrainz_genres_for_recording(recording_id)
    if result:
        _MB_GENRE_TRACK_CACHE[_cache_key] = result
    return result


@functools.lru_cache(maxsize=1024)
def get_artist_id(artist_name: str) -> str | None:
    """Fetch MusicBrainz Artist ID."""
    if not artist_name: return None
    try:
        url = "https://musicbrainz.org/ws/2/artist/?" + urllib.parse.urlencode({
            "query": f'artist:"{artist_name}"',
            "fmt": "json",
        })
        data = get_json(url)
        artists = data.get("artists") or []
        if artists:
            # Prefer exact match if possible
            for a in artists[:3]:
                if norm_name(a.get("name", "")) == norm_name(artist_name):
                    return a["id"]
            return artists[0]["id"]
    except Exception: pass
    return None


@functools.lru_cache(maxsize=1024)
def get_alternative_albums(artist: str, title: str) -> list[str]:
    """Fetch all known album titles for a specific track from MusicBrainz."""
    if not artist or not title:
        return []
    try:
        url = "https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode({
            "query": f'recording:"{title}" AND artist:"{artist}"',
            "limit": "30",
            "fmt": "json",
            "inc": "releases",
        })
        data = get_json(url)
        albums = set()
        for rec in data.get("recordings") or []:
            if norm_name(rec.get("title", "")) == norm_name(title):
                for rel in rec.get("releases") or []:
                    album_name = rel.get("title")
                    if album_name:
                        albums.add(album_name)
        return sorted(list(albums), key=len)
    except Exception:
        return []


@functools.lru_cache(maxsize=1024)
def get_alternative_albums_hierarchical(artist: str, title: str) -> list[str]:
    """
    Fetch all albums for an artist from MusicBrainz, categorized by type, 
    and filter for those containing the specific track.
    Follows priority: Album -> Compilation -> Live -> EP -> Single.
    """
    artist_id = get_artist_id(artist)
    if not artist_id:
        return get_alternative_albums(artist, title)
    
    try:
        # 1. Get ALL recordings matching title + artist to find which Releases (and thus RGs) have it
        rec_url = "https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode({
            "query": f'recording:"{title}" AND arid:{artist_id}',
            "fmt": "json", "limit": "100", "inc": "releases"
        })
        rec_data = get_json(rec_url)
        
        # Track which Release Group IDs contain this recording
        # (We need RG IDs to match against the artist's discography list)
        valid_rg_ids = set()
        for rec in rec_data.get("recordings") or []:
            if norm_name(rec.get("title", "")) == norm_name(title):
                for rel in rec.get("releases") or []:
                    # Release -> Release Group is not in this specific inc=releases output 
                    # but we can fetch release-groups for the artist and match titles,
                    # or better: we use the Release Group list and check if the recording search confirms the album.
                    pass

        # 2. Get the official Discography (Release Groups)
        url = f"https://musicbrainz.org/ws/2/release-group?artist={artist_id}&fmt=json&limit=100"
        data = get_json(url)
        groups = data.get("release-groups") or []
        
        # 3. Use get_alternative_albums to get the "Truth Set" of album titles where the track exists
        confirmed_titles = get_alternative_albums(artist, title)
        confirmed_set = {norm_name(t) for t in confirmed_titles}

        # 4. Categorize based on MusicBrainz official hierarchy
        # Priority order: Album, Compilation, Live, EP, Single
        hierarchy = ["album", "compilation", "live", "ep", "single", "other"]
        cats = {k: [] for k in hierarchy}
        
        for rg in groups:
            p_type = (rg.get("primary-type") or "").lower()
            s_types = [t.lower() for t in (rg.get("secondary-types") or [])]
            rg_title = rg.get("title")

            # Hard override for common metadata errors (e.g. Videograffitti)
            if rg_title and artist.lower() == "extreme" and rg_title.lower() == "videograffitti":
                rg_title = "Pornograffitti"

            # FILTER: Skip obvious video content
            if rg_title and any(k in rg_title.lower() for k in ["video", "dvd", "blu-ray", "concert film", "laserdisc"]):
                continue

            if not rg_title or norm_name(rg_title) not in confirmed_set:
                continue
            target = "other"
            if p_type == "album":
                if "compilation" in s_types: target = "compilation"
                elif "live" in s_types: target = "live"
                else: target = "album"
            elif p_type == "ep":
                target = "ep"
            elif p_type == "single":
                target = "single"
            
            if rg_title not in cats[target]:
                cats[target].append(rg_title)

        # 5. Flatten in hierarchy order
        result_order = []
        for key in hierarchy:
            # Sort each category by name length to find most likely "original" titles
            result_order.extend(sorted(cats[key], key=len))
            
        # 6. Final fallback: Any confirmed titles we missed (e.g. from Other artists / Various)
        seen = {norm_name(t) for t in result_order}
        for t in confirmed_titles:
            if norm_name(t) not in seen:
                result_order.append(t)
                
        return result_order
    except Exception:
        return get_alternative_albums(artist, title)


def enrich_track_identifiers(track: dict) -> dict:
    if not isinstance(track, dict) or track.get("type", "track") != "track":
        return dict(track or {})

    import db
    track_key = f"{str(track.get('artist') or '').strip().lower()}||{str(track.get('title') or '').strip().lower()}"
    cached = db.get_track_metadata(track_key)
    enriched = dict(track)
    if cached:
        # Merge cached IDs into current track
        for key in ["spotify_id", "isrc", "musicbrainz_recording_id", "musicbrainz_release_id", "deezer_id", "tidal_id", "amazon_id", "apple_music_id"]:
            if cached.get(key) and not enriched.get(key):
                enriched[key] = cached[key]

    if not enriched.get("spotify_id") and enriched.get("title"):
        for key, value in spotify_search_track(
            enriched.get("artist", ""),
            enriched.get("title", ""),
        ).items():
            if value and not enriched.get(key):
                enriched[key] = value
    spotify_id = enriched.get("spotify_id", "")
    if spotify_id:
        for key, value in spotify_track_metadata(spotify_id).items():
            if not value:
                continue
            if key in {"title", "artist", "artist_id", "album", "duration_ms", "isrc", "artwork_url", "spotify_url"}:
                enriched[key] = value
            elif not enriched.get(key):
                enriched[key] = value
    spotify_url = enriched.get("spotify_url", "") or (
        f"https://open.spotify.com/track/{spotify_id}" if spotify_id else ""
    )
    if spotify_url:
        enriched["spotify_url"] = spotify_url
        for key, value in odesli_lookup(spotify_url).items():
            if value and not enriched.get(key):
                enriched[key] = value

    duration_ms = int(enriched.get("duration_ms") or enriched.get("length") or 0)
    for key, value in deezer_track_identifiers(
        str(enriched.get("deezer_id", "")),
        enriched.get("artist", ""),
        enriched.get("title", ""),
        duration_ms,
    ).items():
        if value and not enriched.get(key):
            enriched[key] = value
    mb_ids = musicbrainz_recording_identifiers(
        enriched.get("artist", ""),
        enriched.get("title", ""),
        enriched.get("album", ""),
        duration_ms,
    )
    for key, value in mb_ids.items():
        if value and not enriched.get(key):
            enriched[key] = value
    if not enriched.get("genres"):
        genres = []
        release_id = str(enriched.get("musicbrainz_release_id") or "").strip()
        recording_id = str(enriched.get("musicbrainz_recording_id") or "").strip()
        if release_id:
            genres = musicbrainz_genres_for_release(release_id)
        if not genres and recording_id:
            genres = musicbrainz_genres_for_recording(recording_id)
        if not genres:
            genres = musicbrainz_genres_for_track(
                enriched.get("artist", ""),
                enriched.get("title", ""),
                enriched.get("album", ""),
                duration_ms,
            )
        if not genres:
            artist_id = str(enriched.get("artist_id") or "").strip()
            if artist_id:
                try:
                    artist_data = _sp(f"artists/{artist_id}")
                    genres = [g for g in (artist_data.get("genres") or []) if isinstance(g, str) and g]
                except Exception:
                    genres = []
        if genres:
            enriched["genres"] = genres
            enriched["genre"] = genres[0]

    if not enriched.get("isrc"):
        from isrc_resolver import resolve_isrc
        isrc = resolve_isrc(
            enriched.get("title", ""),
            enriched.get("artist", ""),
            spotify_id=enriched.get("spotify_id", ""),
        )
        if isrc:
            enriched["isrc"] = isrc

    # Final result!
    import db
    track_key = f"{str(enriched.get('artist') or '').strip().lower()}||{str(enriched.get('title') or '').strip().lower()}"
    db.save_track_metadata(track_key, enriched)

    return enriched


@functools.lru_cache(maxsize=1024)
def spotify_search_track(artist: str, title: str) -> dict:
    q = f"artist:{artist} track:{title}" if title else f"artist:{artist}"
    data = _sp("search", q=q, type="track", limit=3)
    items = (data.get("tracks") or {}).get("items") or []
    for item in items:
        images = (item.get("album") or {}).get("images") or []
        ext_ids = item.get("external_ids") or {}
        artist_id = ""
        artists = item.get("artists") or []
        if artists:
            artist_id = artists[0].get("id") or ""
        return {
            "spotify_url": (item.get("external_urls") or {}).get("spotify", ""),
            "spotify_id": item.get("id", ""),
            "artist_id": artist_id,
            "album": (item.get("album") or {}).get("name", ""),
            "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
            "isrc": ext_ids.get("isrc", ""),
            "ean": ext_ids.get("ean", ""),
            "upc": ext_ids.get("upc", ""),
            "spotify_popularity": item.get("popularity", 0),
        }
    return {}


def _spotify_embed_track_metadata(spotify_id: str) -> dict:
    try:
        embed_url = "https://open.spotify.com/embed/track/" + urllib.parse.quote(spotify_id, safe="")
        req = urllib.request.Request(
            embed_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception:
        return {}
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text)
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1)))
    except Exception:
        return {}
    entity = (
        data.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("data", {})
        .get("entity", {})
    )
    if not isinstance(entity, dict) or entity.get("type") != "track":
        return {}
    artists = entity.get("artists") or []
    artist_names = ", ".join(
        a.get("name", "") for a in artists
        if isinstance(a, dict) and a.get("name")
    )
    artist_id = ""
    if artists and isinstance(artists[0], dict):
        artist_id = str(artists[0].get("uri") or "").rsplit(":", 1)[-1]
    artwork = ""
    cover_art = entity.get("coverArt") or entity.get("visualIdentity", {}).get("image")
    if isinstance(cover_art, dict):
        sources = cover_art.get("sources") or []
        if sources and isinstance(sources[0], dict):
            artwork = sources[0].get("url", "")
        else:
            artwork = cover_art.get("url", "")
    return {
        "spotify_url": f"https://open.spotify.com/track/{spotify_id}",
        "spotify_id": entity.get("id", spotify_id),
        "title": entity.get("title") or entity.get("name", ""),
        "artist": artist_names,
        "artist_id": artist_id,
        "artwork_url": proxy_artwork_url(artwork) if artwork else "",
        "duration_ms": entity.get("duration") or 0,
    }


@functools.lru_cache(maxsize=2048)
def spotify_track_metadata(spotify_id: str) -> dict:
    spotify_id = str(spotify_id or "").strip()
    if not spotify_id:
        return {}
    try:
        item = _sp(f"tracks/{spotify_id}", market="US")
    except Exception:
        item = {}
    if not isinstance(item, dict) or not item.get("id"):
        return _spotify_embed_track_metadata(spotify_id)
    images = (item.get("album") or {}).get("images") or []
    ext_ids = item.get("external_ids") or {}
    artists = item.get("artists") or []
    artist_names = ", ".join(
        a.get("name", "") for a in artists
        if isinstance(a, dict) and a.get("name")
    )
    artist_id = artists[0].get("id", "") if artists and isinstance(artists[0], dict) else ""
    return {
        "spotify_url": (item.get("external_urls") or {}).get("spotify", "") or f"https://open.spotify.com/track/{spotify_id}",
        "spotify_id": item.get("id", spotify_id),
        "title": item.get("name", ""),
        "artist": artist_names,
        "artist_id": artist_id,
        "album": (item.get("album") or {}).get("name", ""),
        "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
        "duration_ms": item.get("duration_ms", 0),
        "isrc": ext_ids.get("isrc", ""),
        "ean": ext_ids.get("ean", ""),
        "upc": ext_ids.get("upc", ""),
        "spotify_popularity": item.get("popularity", 0),
    }


@functools.lru_cache(maxsize=1024)
def spotify_album_artwork(artist: str, album: str) -> str:
    q = f"artist:{artist} album:{album}"
    data = _sp("search", q=q, type="album", limit=3)
    items = (data.get("albums") or {}).get("items") or []
    for item in items:
        images = item.get("images") or []
        if images:
            return proxy_artwork_url(images[0]["url"])
    return ""


def _raw_artist_profile_artwork(client: object, artist_id: str) -> str:
    web_client = getattr(client, "web_client", None)
    if not web_client or not artist_id:
        return ""
    payload = {
        "operationName": "queryArtistOverview",
        "variables": {"uri": f"spotify:artist:{artist_id}", "locale": ""},
        "extensions": {"persistedQuery": {
            "version": 1,
            "sha256Hash": "446130b4a0aa6522a686aafccddb0ae849165b5e0436fd802f96e0243617b5d8",
        }},
    }
    try:
        artist_data = web_client.query(payload).get("data", {}).get("artistUnion", {})
    except Exception:
        return ""
    return _best_raw_image(artist_data.get("visuals", {}).get("avatarImage", {}))


def spotify_artist_artwork(artist: str, artist_id: str = "") -> str:
    key = (artist.strip().lower(), artist_id.strip())
    with _spotify_artist_id_cache_lock:
        cached = _spotify_artist_id_cache.get(f"artwork:{key[0]}::{key[1]}")
        if cached is not None:
            return cached

    for attempt in range(2):
        sp_id = artist_id or spotify_artist_id(artist)
        if not sp_id:
            data = _sp("search", q=f"artist:{artist}", type="artist", limit=3)
            items = (data.get("artists") or {}).get("items") or []
            for a in items:
                if norm_name(a.get("name", "")) == norm_name(artist):
                    images = a.get("images") or []
                    if images:
                        result = proxy_artwork_url(images[0]["url"])
                        with _spotify_artist_id_cache_lock:
                            _spotify_artist_id_cache[f"artwork:{key[0]}::{key[1]}"] = result
                        return result
            if attempt == 0:
                _reset_spotify_client_cache()
                continue
            return ""

        data = _sp(f"artists/{sp_id}")
        images = data.get("images") or []
        if images:
            result = proxy_artwork_url(images[0]["url"])
            with _spotify_artist_id_cache_lock:
                _spotify_artist_id_cache[f"artwork:{key[0]}::{key[1]}"] = result
            return result

        client = _get_spotify_client(force_refresh=attempt > 0)
        raw_artwork = _raw_artist_profile_artwork(client, sp_id) if client else ""
        if raw_artwork:
            result = proxy_artwork_url(raw_artwork)
            with _spotify_artist_id_cache_lock:
                _spotify_artist_id_cache[f"artwork:{key[0]}::{key[1]}"] = result
            return result
        if attempt == 0:
            _reset_spotify_client_cache()
            continue
        return ""
    return ""


def spotify_artist_id(artist_name: str) -> str:
    key = artist_name.strip().lower()
    if not key:
        return ""
    with _spotify_artist_id_cache_lock:
        cached = _spotify_artist_id_cache.get(key)
        if cached is not None:
            _spotify_artist_id_cache.move_to_end(key)
            return cached

    for attempt in range(2):
        data = _sp("search", q=f'artist:"{artist_name}"', type="artist", limit=3)
        sp_artists = (data.get("artists") or {}).get("items") or []
        for item in sp_artists:
            if norm_name(item.get("name", "")) == norm_name(artist_name):
                artist_id = item.get("id", "")
                if artist_id:
                    with _spotify_artist_id_cache_lock:
                        _spotify_artist_id_cache[key] = artist_id
                        _spotify_artist_id_cache.move_to_end(key)
                        while len(_spotify_artist_id_cache) > _SPOTIFY_ARTIST_CACHE_SIZE:
                            _spotify_artist_id_cache.popitem(last=False)
                return artist_id
        fallback_id = (sp_artists[0].get("id") or "") if sp_artists else ""
        if fallback_id:
            with _spotify_artist_id_cache_lock:
                _spotify_artist_id_cache[key] = fallback_id
                _spotify_artist_id_cache.move_to_end(key)
                while len(_spotify_artist_id_cache) > _SPOTIFY_ARTIST_CACHE_SIZE:
                    _spotify_artist_id_cache.popitem(last=False)
            return fallback_id
        if attempt == 0:
            _reset_spotify_client_cache()
            continue
        try:
            from catalog import load_discovery_cache
            cached_identity = (load_discovery_cache().get("artist_identities") or {}).get(key, {})
            cached_id = str(cached_identity.get("spotify_id") or "").strip()
            if cached_id:
                with _spotify_artist_id_cache_lock:
                    _spotify_artist_id_cache[key] = cached_id
                    _spotify_artist_id_cache.move_to_end(key)
                    while len(_spotify_artist_id_cache) > _SPOTIFY_ARTIST_CACHE_SIZE:
                        _spotify_artist_id_cache.popitem(last=False)
                return cached_id
        except Exception:
            pass
        return ""
    return ""


def _resolve_spotify_artist_id(artist_name: str, artist_id: str = "") -> str:
    supplied_id = str(artist_id or "").strip()
    resolved_id = spotify_artist_id(artist_name)
    return resolved_id or supplied_id


def spotify_artist_top_tracks(artist_name: str, limit: int = 25, artist_id: str = "") -> list[dict]:
    key = (artist_name.strip().lower(), int(limit or 0), artist_id.strip())
    with _spotify_artist_top_tracks_cache_lock:
        cached = _spotify_artist_top_tracks_cache.get(key)
        if cached is not None:
            _spotify_artist_top_tracks_cache.move_to_end(key)
            return [dict(r) for r in cached]

    for attempt in range(2):
        sp_artist_id = artist_id or spotify_artist_id(artist_name)
        if not sp_artist_id:
            return []
        data = _sp(f"artists/{sp_artist_id}/top-tracks", market="US")
        sp_tracks = (data.get("tracks") or [])[:limit]
        if not sp_tracks:
            client = _get_spotify_client(force_refresh=attempt > 0)
            search_tracks = getattr(client, "search_tracks", None)
            if search_tracks:
                try:
                    sp_tracks = list(search_tracks(artist_name, limit=limit) or [])[:limit]
                except Exception:
                    sp_tracks = []
        results = []
        for t in sp_tracks:
            legacy_track = _legacy_track_item(t)
            images = (legacy_track.get("album") or {}).get("images") or []
            art = proxy_artwork_url(images[0]["url"]) if images else ""
            album_name = (legacy_track.get("album") or {}).get("name", "")
            if not art and album_name:
                art = spotify_album_artwork(artist_name, album_name)
            results.append({
                "title": legacy_track.get("name", ""),
                "artist": artist_name,
                "album": album_name,
                "artwork_url": art,
                "duration": format_duration_ms(legacy_track.get("duration_ms", 0)),
                "length": legacy_track.get("duration_ms", 0),
                "plays": legacy_track.get("popularity", 0) * 10000,
                "spotify_url": (legacy_track.get("external_urls") or {}).get("spotify", ""),
                "spotify_id": legacy_track.get("id", ""),
                "isrc": (legacy_track.get("external_ids") or {}).get("isrc", ""),
                "source": "Spotify",
            })
        if results:
            cached_results = tuple(results)
            with _spotify_artist_top_tracks_cache_lock:
                _spotify_artist_top_tracks_cache[key] = results
                _spotify_artist_top_tracks_cache.move_to_end(key)
                while len(_spotify_artist_top_tracks_cache) > _SPOTIFY_ARTIST_CACHE_SIZE:
                    _spotify_artist_top_tracks_cache.popitem(last=False)
            return [dict(r) for r in cached_results]
        if attempt == 0:
            _reset_spotify_client_cache()
            continue
        if artist_id:
            resolved_id = spotify_artist_id(artist_name)
            if resolved_id and resolved_id != artist_id:
                return spotify_artist_top_tracks(artist_name, limit=limit, artist_id=resolved_id)
        return []
    return []


# ---------------------------------------------------------------------------
# MusicBrainz helpers
# ---------------------------------------------------------------------------

def _ac_fields(artist_credit: list) -> dict:
    if not artist_credit:
        return {"musicbrainz_artist_id": "", "artist_sort": ""}
    ac0 = artist_credit[0]
    a = ac0.get("artist") or {}
    return {"musicbrainz_artist_id": a.get("id", ""), "artist_sort": a.get("sort-name", "")}


@functools.lru_cache(maxsize=128)
def find_artist_id(artist: str) -> str:
    try:
        data = get_json("https://musicbrainz.org/ws/2/artist?" + urllib.parse.urlencode({
            "query": f'artist:"{artist}"', "fmt": "json", "limit": "5",
        }))
        for item in data.get("artists", []):
            if norm_name(item.get("name", "")) == norm_name(artist):
                return item.get("id", "")
        return (data.get("artists") or [{}])[0].get("id", "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Indexers
# ---------------------------------------------------------------------------

class BaseMusicIndexer:
    name = "base"
    def search(self, query: str) -> list[dict]: raise NotImplementedError


class SpotifyIndexer(BaseMusicIndexer):
    def search(self, query: str) -> list[dict]:
        search_v2 = {}
        for attempt in range(2):
            client = _get_spotify_client(force_refresh=attempt > 0)
            web_client = getattr(client, "web_client", None)
            payload_builder = getattr(client, "_search_payload", None)
            if not web_client or not payload_builder:
                if attempt == 0:
                    _reset_spotify_client_cache()
                    continue
                return []
            try:
                data = web_client.query(payload_builder(query, 20))
                search_v2 = data.get("data", {}).get("searchV2", {})
            except Exception:
                if attempt == 0:
                    _reset_spotify_client_cache()
                    continue
                return []
            if search_v2 or attempt > 0:
                break
            _reset_spotify_client_cache()
        if not search_v2:
            return []

        def _join_artists(node):
            if not node: return "", ""
            items = node.get("items") or []
            names = ", ".join(a.get("profile", {}).get("name") or a.get("name") or ""
                              for a in items if isinstance(a, dict))
            first_id = ""
            if items:
                # Some API versions use 'uri', others use 'data' -> 'uri'
                first = items[0]
                uri = (first.get("uri") or (first.get("data") or {}).get("uri")) if isinstance(first, dict) else ""
                if uri: first_id = uri.split(":")[-1]
            return names, first_id

        results = []

        # Tracks
        for item in search_v2.get("tracksV2", {}).get("items", []):
            t = item.get("item", {}).get("data", {})
            if not t.get("id"): continue
            cover = _best_raw_image(t.get("albumOfTrack", {}).get("coverArt"))
            names, aid = _join_artists(t.get("artists"))
            results.append({
                "type": "track", "title": t.get("name", "Unknown"),
                "artist": names, "artist_id": aid,
                "album": t.get("albumOfTrack", {}).get("name", "Unknown"),
                "artwork_url": proxy_artwork_url(cover),
                "spotify_url": f"https://open.spotify.com/track/{t['id']}",
                "spotify_id": t["id"], "isrc": "",
                "source": "Spotify", "plays": _numeric_plays(t.get("playcount")),
            })

        # Albums
        for item in search_v2.get("albumsV2", {}).get("items", []):
            node = item.get("data", {})
            uri = node.get("uri", "")
            if not uri: continue
            album_id = uri.split(":")[-1]
            cover = _best_raw_image(node.get("coverArt"))
            names, aid = _join_artists(node.get("artists"))
            results.append({
                "type": "album", "title": node.get("name", "Unknown"),
                "artist": names, "artist_id": aid,
                "album": node.get("name", ""),
                "artwork_url": proxy_artwork_url(cover),
                "spotify_id": album_id, "source": "Spotify", "plays": 0,
            })

        # Artists
        for item in search_v2.get("artists", {}).get("items", []):
            node = item.get("data", {})
            uri = node.get("uri", "")
            if not uri: continue
            artist_id = uri.split(":")[-1]
            # Try visuals -> avatarImage, then visualIdentity -> squareCoverImage
            cover = _best_raw_image(node.get("visuals", {}).get("avatarImage") if node.get("visuals") else None) or \
                    _best_raw_image(node.get("visualIdentity", {}).get("squareCoverImage") if node.get("visualIdentity") else None)
            name = node.get("profile", {}).get("name", "Unknown")
            results.append({
                "type": "artist", "title": name, "artist": name, "artist_id": artist_id,
                "artwork_url": proxy_artwork_url(cover),
                "spotify_id": artist_id, "source": "Spotify", "plays": 0,
            })

        return results

    def top_tracks(self, limit: int = 20) -> list[dict]:
        results = []
        offset = 0
        while len(results) < limit:
            batch_limit = min(50, limit - len(results))
            data = _sp("playlists/37i9dQZEVXbMDoHDwVN2tF/tracks", market="US", limit=batch_limit, offset=offset)
            items = data.get("items") or []
            if not items: break
            for entry in items:
                item = entry.get("track")
                if not item: continue
                images = (item.get("album") or {}).get("images") or []
                results.append({
                    "type": "track", "title": item.get("name", ""), "name": item.get("name", ""),
                    "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                    "album": (item.get("album") or {}).get("name", ""),
                    "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                    "spotify_id": item.get("id", ""), "source": "Spotify", "plays": item.get("popularity", 0) * 10000,
                })
            offset += len(items)
        return results[:limit]

    def new_releases(self, limit: int = 20) -> list[dict]:
        results = []
        offset = 0
        while len(results) < limit:
            batch_limit = min(50, limit - len(results))
            data = _sp("browse/new-releases", market="US", limit=batch_limit, offset=offset)
            items = (data.get("albums") or {}).get("items") or []
            if not items: break
            for item in items:
                images = item.get("images") or []
                results.append({
                    "type": "album", "title": item.get("name", ""), "name": item.get("name", ""),
                    "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                    "album": item.get("name", ""), "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                    "spotify_id": item.get("id", ""), "source": "Spotify", "plays": 0,
                })
            offset += len(items)
        return results[:limit]

    def top_artists(self, limit: int = 20) -> list[dict]:
        results = []
        offset = 0
        while len(results) < limit:
            batch_limit = min(50, limit - len(results))
            data = _sp("search", q="year:2024", type="artist", limit=batch_limit, offset=offset)
            items = (data.get("artists") or {}).get("items") or []
            if not items: break
            for item in items:
                images = item.get("images") or []
                results.append({
                    "type": "artist", "title": item.get("name", ""), "name": item.get("name", ""),
                    "artist": item.get("name", ""),
                    "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                    "spotify_id": item.get("id", ""), "source": "Spotify", "plays": item.get("popularity", 0) * 10000,
                })
            offset += len(items)
        return results[:limit]


def build_music_indexers(config: AppConfig) -> list[BaseMusicIndexer]:
    return [SpotifyIndexer()] if _get_spotify_client() else []


_search_music_cache_lock = threading.Lock()
_search_music_cache: OrderedDict[str, tuple[dict, ...]] = OrderedDict()
_SEARCH_MUSIC_CACHE_SIZE = 128


def clear_search_music_cache() -> None:
    with _search_music_cache_lock:
        _search_music_cache.clear()


def search_music(config: AppConfig, query: str) -> list[dict]:
    # `config` is accepted for API symmetry but is NOT part of the cache key:
    # AppConfig is an unhashable dataclass, so caching search_music on it crashed
    # every text search with "unhashable type: 'AppConfig'". build_music_indexers
    # ignores config anyway, so the results depend only on the query. Cache on the
    # lower-cased query alone and hand callers fresh dicts. Do not cache empty
    # results so a transient provider failure does not poison later searches.
    query = query.strip().lower()
    if not query: return []
    with _search_music_cache_lock:
        cached = _search_music_cache.get(query)
        if cached is not None:
            _search_music_cache.move_to_end(query)
            return [dict(r) for r in cached]

    results, seen = [], set()
    for idx in build_music_indexers(None):
        try:
            for res in idx.search(query):
                sid = res.get("spotify_id")
                norm_key = f"{res['type']}||{norm_name(res['title'])}||{norm_name(res['artist'])}"
                if sid:
                    if sid in seen: continue
                    seen.add(sid)
                else:
                    if norm_key in seen: continue
                    seen.add(norm_key)
                res["_relevance"] = search_relevance(query, res)
                results.append(res)
        except Exception: pass
    results.sort(key=lambda x: x.get("_relevance", (0, 0, 0, 0)), reverse=True)
    for r in results: r.pop("_relevance", None)
    cached_results = tuple(results)
    if cached_results:
        with _search_music_cache_lock:
            _search_music_cache[query] = cached_results
            _search_music_cache.move_to_end(query)
            while len(_search_music_cache) > _SEARCH_MUSIC_CACHE_SIZE:
                _search_music_cache.popitem(last=False)
    return [dict(r) for r in cached_results]


def search_relevance(query: str, result: dict) -> tuple[int, int, int, int]:
    wanted = query.strip().lower()
    wanted_norm = norm_name(wanted)
    kind = result.get("type", "track")
    artist = (result.get("artist") or "").lower()
    title = (result.get("title") or "").lower()
    primary = artist if kind == "artist" else title
    score = rapidfuzz.fuzz.WRatio(wanted, primary)
    if norm_name(primary) == wanted_norm: score += 1000
    if primary.startswith(wanted): score += 500
    track_key = str(result.get("track_key") or result.get("spotify_id") or "").strip()
    if kind == "track" and track_key:
        score += int(db.get_taste_score_for_track(track_key) * 2.0)
    if artist:
        score += int(db.get_taste_score_for_artist(artist) * 1.0)
    kind_prio = {"artist": 100, "track": 50, "album": 10}.get(kind, 0)
    return (score, kind_prio, int(result.get("plays") or 0), 0)


def artist_page(config: AppConfig, artist: str, artist_id: str = ""):
    resolved_artist_id = _resolve_spotify_artist_id(artist, artist_id)
    art = ""
    if resolved_artist_id:
        art = spotify_artist_artwork(artist, resolved_artist_id)
        from catalog import save_artist_identity
        save_artist_identity(artist, resolved_artist_id, art)
    
    yield {"type": "artist_info", "artist": artist, "artist_id": resolved_artist_id, "artwork_url": art}
    
    top_tracks = spotify_artist_top_tracks(artist, artist_id=resolved_artist_id)
    top_tracks.sort(
        key=lambda track: (
            db.get_taste_score_for_track(str(track.get("track_key") or track.get("spotify_id") or "")),
            db.get_taste_score_for_artist(str(track.get("artist") or artist or "")),
            int(track.get("plays") or 0),
        ),
        reverse=True,
    )
    yield {"type": "top_tracks", "tracks": top_tracks}

    album_items = []
    if resolved_artist_id:
        for attempt in range(2):
            client = _get_spotify_client(force_refresh=attempt > 0)
            if not client:
                break
            try:
                album_items = _raw_artist_discography_items(client, resolved_artist_id)
            except Exception:
                album_items = []
            if album_items or attempt > 0:
                break
            _reset_spotify_client_cache()
    
    if album_items:
        source_items = [_legacy_simple_item(item, "album") for item in album_items]
    else:
        # Fallback to search if discography fetch failed or no ID
        data = _sp("search", q=f'artist:"{artist}"', type="album", limit=50)
        source_items = (data.get("albums") or {}).get("items") or []
    albums = []
    for item in source_items:
        images = item.get("images") or []
        albums.append({
            "type": "album", "title": item["name"], "artist": artist, "album": item["name"],
            "year": release_year(item.get("release_date", "")),
            "artwork_url": proxy_artwork_url(images[0].get("url", "")) if images else "",
            "spotify_id": item["id"], "source": "Spotify",
            "release_type": item.get("release_type", "")
        })
    
    # Sort albums to prioritize main studio albums over singles/compilations
    def _album_sort_key(a):
        rt = a.get("release_type", "").upper()
        # 0 for ALBUM, 1 for COMPILATION, 2 for SINGLE/EP, 3 for others
        priority = 0 if rt == "ALBUM" else (1 if rt == "COMPILATION" else (2 if rt == "SINGLE" else 3))
        # Secondary sort by year (newest first, fallback to empty)
        year = a.get("year", "")
        return (priority, "" if not year else str(9999 - int(year)) if year.isdigit() else year)
    
    albums.sort(key=_album_sort_key)
    
    yield {"type": "albums", "albums": albums}

    related = related_artists(resolved_artist_id, artist)
    yield {"type": "related_artists", "artists": related.get("artists", [])}


def album_tracks(config: AppConfig, artist: str, album: str, release_id: str = "", spotify_id: str = "") -> dict:
    import db
    album_key = f"{str(artist or '').strip().lower()}||{str(album or '').strip().lower()}"
    cached = db.get_album_metadata(album_key)
    if cached:
        print(f"[Metadata] Using cached album metadata for: {artist} - {album}")
        return cached

    tracks, art, yr, total_ms = [], "", "", 0
    release_genres = musicbrainz_genres_for_release(release_id) if release_id else []
    if spotify_id:
        try:
            sp_album = _sp(f"albums/{spotify_id}", market="US")
            if sp_album:
                playcounts = spotify_album_playcounts(spotify_id)
                art = proxy_artwork_url(sp_album.get("images", [{}])[0].get("url", ""))
                yr = release_year(sp_album.get("release_date", ""))
                album_name = sp_album["name"]
                albumartist = (sp_album.get("artists") or [{}])[0].get("name") or artist
                for t in sp_album.get("tracks", {}).get("items") or []:
                    track_artist = ((t.get("artists") or [{}])[0].get("name") or albumartist)
                    tracks.append({
                        "type": "track", "title": t["name"], "artist": track_artist,
                        "album": album_name, "year": yr, "track_number": t.get("track_number"),
                        "duration": format_duration_ms(t.get("duration_ms", 0)),
                        "artwork_url": art, "spotify_id": t["id"], "source": "Spotify",
                        "length": t.get("duration_ms", 0), "plays": playcounts.get(t["id"], 0),
                        "genres": release_genres,
                        "genre": release_genres[0] if release_genres else "",
                    })
                total_ms = sum(int(t.get("duration_ms", 0)) for t in sp_album.get("tracks", {}).get("items") or [])
        except Exception: pass

    if not tracks and release_id:
        try:
            data = get_json(f"https://musicbrainz.org/ws/2/release/{urllib.parse.quote(release_id)}?inc=recordings+artist-credits+isrcs&fmt=json")
            album_name, yr = data.get("title", album), release_year(data.get("date", ""))
            albumartist = (data.get("artist-credit") or [{}])[0].get("name", artist)
            for m in (data.get("media") or []):
                for it in m.get("tracks", []):
                    rec = it.get("recording") or {}
                    ln = int(it.get("length") or rec.get("length") or 0)
                    total_ms += ln
                    tracks.append({
                        "type": "track", "title": rec.get("title", it.get("title")),
                        "artist": albumartist, "album": album_name, "year": yr,
                        "track_number": it.get("number", ""), "duration": format_duration_ms(ln),
                        "artwork_url": art or spotify_album_artwork(artist, album_name),
                        "musicbrainz_recording_id": rec.get("id", ""), "musicbrainz_release_id": release_id,
                        "source": "MusicBrainz", "length": ln,
                        "genres": release_genres or musicbrainz_genres_for_recording(rec.get("id", "")),
                        "genre": (release_genres or musicbrainz_genres_for_recording(rec.get("id", "")) or [""])[0],
                    })
        except Exception: pass

    if not tracks:
        try:
            # Fallback search if ID fetch failed or wasn't provided
            search_q = f'artist:"{artist}" album:"{album}"'
            data = _sp("search", q=search_q, type="album", limit=1)
            items = (data.get("albums") or {}).get("items") or []
            if items and items[0].get("id") and items[0]["id"] != spotify_id:
                return album_tracks(config, artist, album, "", items[0]["id"])
        except Exception: pass

    if not art: art = spotify_album_artwork(artist, album)
    gallery_images = []
    
    # 1. Add Spotify (Primary Base)
    if art:
        gallery_images.append({
            "url": art, "full_url": art, "source": "Spotify", "label": "Spotify Cover",
            "width": 640, "height": 640, "is_spotify": True
        })

    # 2. Add MusicBrainz CAA (Ultra-HD Scans)
    if release_id:
        gallery_images.extend(caa_artwork(release_id))

    # 3. Add Discogs (Collector Scans)
    discogs_release = discogs_album_images(artist, album, yr, config.discogs_token)
    for image in discogs_release.get("images", []):
        if not image.get("url"):
            continue
        gallery_images.append({
            "url": proxy_artwork_url(image.get("url", "")),
            "full_url": proxy_artwork_url(image.get("full_url") or image.get("url", "")),
            "source": "Discogs",
            "label": "Vinyl image",
            "width": image.get("width", 0),
            "height": image.get("height", 0),
            "is_primary": image.get("type") == "primary"
        })

    # 4. Global Ranking: Spotify ALWAYS first, then Primary/Front, then by Area
    def quality_score(img: dict) -> int:
        if img.get("is_spotify"):
            return 100_000_000 # Absolute priority
        
        score = img.get("width", 0) * img.get("height", 0)
        if img.get("source") == "MusicBrainz CAA" and img.get("is_front"):
            score += 10_000_000 # Massive boost for official HD front scans
        if img.get("is_primary"):
            score += 5_000_000
        return score

    gallery_images.sort(key=quality_score, reverse=True)

    # Use the best quality image as the main artwork_url if available
    top_art = gallery_images[0]["url"] if gallery_images else art

    result = {
        "artist": artist, "album": album, "year": yr, "track_count": len(tracks),
        "total_duration": format_duration_ms(total_ms), "artwork_url": top_art,
        "artist_artwork_url": spotify_artist_artwork(artist), "tracks": tracks,
        "gallery_images": gallery_images,
        "release_id": release_id,
        "spotify_id": spotify_id,
        "genres": release_genres,
        "genre": release_genres[0] if release_genres else "",
    }
    
    # Cache it!
    if tracks:
        import db
        album_key = f"{str(artist or '').strip().lower()}||{str(album or '').strip().lower()}"
        db.save_album_metadata(album_key, result)

    return result



def album_metadata(config: AppConfig, artist: str, album: str, track: str = "") -> dict:
    return {"artist": artist, "album": album, "title": track}


def artist_about(artist_id: str, artist_name: str) -> dict:
    # Tracks played from album pages carry no artist_id; resolve it from the
    # (full, untruncated) artist name so the sidebar shows the right artist's
    # listeners/photo instead of falling back to the album cover.
    if not artist_id and artist_name:
        try:
            artist_id = spotify_artist_id(artist_name) or ""
        except Exception:
            artist_id = ""

    about = spotify_artist_about(artist_id)

    # A non-empty but wrong id resolves to nothing on Spotify's API and would
    # otherwise short-circuit the reliable name-based lookup, leaving the sidebar
    # with 0 listeners/followers and the album cover as the artist photo. This
    # happens when an album/compilation-page track carries a non-Spotify
    # artist_id (e.g. a MusicBrainz id) or a stale/wrong id. When the supplied id
    # yields no stats, re-resolve the id from the name and retry. Guarding on
    # stats (not name) leaves valid ids that legitimately resolve untouched.
    if artist_name and not (about.get("monthly_listeners") or about.get("followers")):
        try:
            resolved_id = spotify_artist_id(artist_name) or ""
        except Exception:
            resolved_id = ""
        if resolved_id and resolved_id != artist_id:
            retry = spotify_artist_about(resolved_id)
            if retry.get("monthly_listeners") or retry.get("followers"):
                about, artist_id = retry, resolved_id

    # Ensure a real artist image is always available as a fallback for the
    # frontend (gallery is frequently empty even for the correct artist).
    if artist_name and not about.get("avatar") and not (about.get("gallery") or []):
        try:
            art = spotify_artist_artwork(artist_name, artist_id)
            if art:
                about = {**about, "avatar": art}
        except Exception:
            pass

    # If we have monthly listeners or followers, we've found the real artist on Spotify.
    # In this case, we trust Spotify data and do NOT fallback to Wikipedia name-searching.
    has_spotify_stats = bool(about.get("monthly_listeners") or about.get("followers"))
    spotify_bio = (about.get("biography") or "").strip()
    
    if has_spotify_stats or len(spotify_bio) > 5:
        about["biography"] = spotify_bio or "Official biography currently unavailable."
        about["bio_source"] = "Spotify"
    else:
        # ABSOLUTE FALLBACK: Only if Spotify has zero stats AND zero bio. Pull the
        # Wikipedia lead section (with its inline article links preserved) and the
        # page image, so the sidebar can show linked text and a real photo instead
        # of the album cover.
        wiki = fetch_wikipedia_about(f"{artist_name} (musician)")
        if not (wiki.get("text") or "").strip():
            wiki = fetch_wikipedia_about(artist_name)
        wiki_text = (wiki.get("text") or "").strip()
        if wiki_text and "may refer to:" not in wiki_text:
            about["biography"] = wiki_text
            if wiki.get("html"):
                about["biography_html"] = wiki["html"]
            about["bio_source"] = "Wikipedia"
            # Use the Wikipedia page image when Spotify gave us no artist photo.
            if wiki.get("image") and not about.get("avatar") and not (about.get("gallery") or []):
                proxied = proxy_artwork_url(wiki["image"])
                about["avatar"] = proxied
                about.setdefault("hero_image", proxied)
        else:
            about["biography"] = "Official artist information is currently unavailable."
            about["bio_source"] = "Spotify"

    return about


def musicbrainz_related_artists(artist_name: str, limit: int = 100) -> list[dict]:
    """Relationship-based related artists from MusicBrainz (band members,
    collaborators, etc.). MusicBrainz has no true 'similar artists', so this is
    a best-effort fallback when Spotify has no 'fans also like' data. No images
    are available from MusicBrainz, so tiles fall back to a placeholder."""
    if not artist_name:
        return []
    try:
        q = urllib.parse.quote(f'artist:"{artist_name}"')
        data = get_json(f"https://musicbrainz.org/ws/2/artist/?query={q}&fmt=json&limit=1")
        arts = data.get("artists") or []
        mbid = (arts[0].get("id") if arts else "") or ""
        if not mbid:
            return []
        detail = get_json(f"https://musicbrainz.org/ws/2/artist/{mbid}?inc=artist-rels&fmt=json")
        out, seen = [], {norm_name(artist_name)}
        for rel in (detail.get("relations") or []):
            target = rel.get("artist") or {}
            name = (target.get("name") or "").strip()
            key = norm_name(name)
            if not name or key in seen:
                continue
            seen.add(key)
            out.append({
                "name": name,
                "artist_id": "",
                "musicbrainz_artist_id": target.get("id", ""),
                "artwork_url": "",
                "type": "artist",
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def related_artists(artist_id: str, artist_name: str, limit: int = 20) -> dict:
    """Return {"artists": [...]} of related artists from the Spotify overview."""
    if not artist_id and artist_name:
        artist_id = spotify_artist_id(artist_name)
    
    if not artist_id:
        return {"artists": [], "source": ""}

    about = spotify_artist_about(artist_id)
    raw_related = about.get("related_artists") or []
    
    items = []
    for entry in raw_related:
        name = (entry.get("name") or "").strip()
        art = entry.get("image") or ""
        sid = entry.get("id") or ""
        if not name or not sid:
            continue
            
        items.append({
            "name": name,
            "artist_id": sid,
            "spotify_artist_id": sid,
            "artwork_url": proxy_artwork_url(art) if art else "",
            "type": "artist",
        })
        if len(items) >= limit:
            break

    return {"artists": items, "source": "Spotify"}


def _split_people(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r",|;|/|\s+\&\s+", str(value))
    people = []
    seen = set()
    for item in raw:
        name = str(item).strip()
        if not name:
            continue
        key = norm_name(name)
        if key and key not in seen:
            seen.add(key)
            people.append(name)
    return people


def _credit_row(name: str, role: str, musicbrainz_id: str = "") -> dict:
    row = {"name": name, "role": role}
    if musicbrainz_id:
        row["musicbrainz_id"] = musicbrainz_id
    return row


def _dedupe_credit_rows(rows: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for row in rows:
        name = str(row.get("name") or "").strip()
        role = str(row.get("role") or "").strip()
        if not name:
            continue
        key = (norm_name(name), role.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({**row, "name": name, "role": role})
    return deduped


def _recording_credit_sections(recording: dict, title: str, artist: str) -> dict:
    artist_rows = []
    composition_rows = []
    production_rows = []
    work_ids = []

    for index, credit in enumerate(recording.get("artist-credit") or []):
        artist_data = credit.get("artist") or {}
        name = credit.get("name") or artist_data.get("name") or ""
        if not name:
            continue
        artist_rows.append(_credit_row(
            name,
            "Main Artist" if index == 0 else "Featured Artist",
            artist_data.get("id", ""),
        ))

    production_roles = {
        "producer": "Producer",
        "co-producer": "Co-Producer",
        "executive producer": "Executive Producer",
        "mix": "Mixer",
        "mixer": "Mixer",
        "engineer": "Engineer",
        "recording engineer": "Recording Engineer",
        "mastering": "Mastering Engineer",
        "mastering engineer": "Mastering Engineer",
        "arranger": "Arranger",
        "instrument arranger": "Arranger",
        "vocal arranger": "Vocal Arranger",
    }
    composition_roles = {
        "composer": "Composer",
        "lyricist": "Lyricist",
        "writer": "Writer",
        "songwriter": "Writer",
        "librettist": "Librettist",
    }

    for relation in recording.get("relations") or []:
        rel_type = str(relation.get("type") or "").lower()
        artist_data = relation.get("artist") or {}
        work_data = relation.get("work") or {}
        if work_data.get("id"):
            work_ids.append(work_data["id"])
        if artist_data.get("name"):
            if rel_type in production_roles:
                production_rows.append(_credit_row(artist_data["name"], production_roles[rel_type], artist_data.get("id", "")))
            elif rel_type in composition_roles:
                composition_rows.append(_credit_row(artist_data["name"], composition_roles[rel_type], artist_data.get("id", "")))

    for work_id in dict.fromkeys(work_ids):
        try:
            work = get_json(f"https://musicbrainz.org/ws/2/work/{urllib.parse.quote(work_id)}?inc=artist-rels&fmt=json")
        except Exception:
            continue
        for relation in work.get("relations") or []:
            rel_type = str(relation.get("type") or "").lower()
            artist_data = relation.get("artist") or {}
            if artist_data.get("name") and rel_type in composition_roles:
                composition_rows.append(_credit_row(artist_data["name"], composition_roles[rel_type], artist_data.get("id", "")))

    if not artist_rows and artist:
        for index, name in enumerate(_split_people(artist)):
            artist_rows.append(_credit_row(name, "Main Artist" if index == 0 else "Featured Artist"))

    return {
        "title": title or recording.get("title") or "Track",
        "artist": artist,
        "source": "MusicBrainz",
        "musicbrainz_recording_id": recording.get("id", ""),
        "sections": [
            {"title": "Artist", "rows": _dedupe_credit_rows(artist_rows)},
            {"title": "Composition and lyrics", "rows": _dedupe_credit_rows(composition_rows)},
            {"title": "Production", "rows": _dedupe_credit_rows(production_rows)},
        ],
    }


def _musicbrainz_recording_for_credits(track: dict, title: str, artist: str) -> dict:
    recording_id = track.get("musicbrainz_recording_id") or (track.get("metadata") or {}).get("musicbrainz_recording_id") or ""
    isrc = track.get("isrc") or (track.get("metadata") or {}).get("isrc") or ""
    duration_ms = int(track.get("duration_ms") or track.get("length") or (track.get("metadata") or {}).get("duration_ms") or 0)

    if not recording_id and isrc:
        try:
            data = get_json("https://musicbrainz.org/ws/2/recording/?" + urllib.parse.urlencode({
                "query": f'isrc:"{isrc}"',
                "limit": "10",
                "fmt": "json",
                "inc": "artist-credits+isrcs",
            }))
            candidates = data.get("recordings") or []
            exact = [
                item for item in candidates
                if (not title or norm_name(item.get("title", "")) == norm_name(title))
                and (not artist or any(norm_name(c.get("name", "")) == norm_name(artist) for c in item.get("artist-credit") or []))
            ]
            if exact:
                recording_id = exact[0].get("id", "")
            elif candidates:
                recording_id = candidates[0].get("id", "")
        except Exception:
            pass

    if not recording_id:
        ids = musicbrainz_recording_identifiers(
            artist,
            title,
            track.get("album") or (track.get("metadata") or {}).get("album") or "",
            duration_ms,
        )
        recording_id = ids.get("musicbrainz_recording_id", "")

    if not recording_id:
        return {}

    try:
        return get_json(
            f"https://musicbrainz.org/ws/2/recording/{urllib.parse.quote(recording_id)}?"
            + urllib.parse.urlencode({"inc": "artist-credits+artist-rels+work-rels+isrcs", "fmt": "json"})
        )
    except Exception:
        return {}


def _track_credits_cache_key(track: dict, title: str, artist: str) -> str:
    metadata = track.get("metadata") or {}
    identifiers = [
        ("musicbrainz_recording_id", track.get("musicbrainz_recording_id") or metadata.get("musicbrainz_recording_id")),
        ("isrc", track.get("isrc") or metadata.get("isrc")),
        ("spotify_id", track.get("spotify_id") or metadata.get("spotify_id")),
    ]
    for kind, value in identifiers:
        value = str(value or "").strip()
        if value:
            return f"{kind}:{norm_name(value)}"

    album = track.get("album") or metadata.get("album") or ""
    duration = track.get("duration_ms") or track.get("length") or metadata.get("duration_ms") or metadata.get("length") or ""
    parts = [norm_name(artist), norm_name(title), norm_name(album), str(duration or "").strip()]
    key = "||".join(part for part in parts if part)
    return f"track:{key}" if key else ""


def track_credits(track: dict) -> dict:
    metadata = track.get("metadata") or {}
    title = track.get("title") or metadata.get("title") or "Track"
    artists = _split_people(track.get("artist") or metadata.get("artist"))
    main = artists[:1]
    featured = artists[1:]
    artist_name = track.get("artist") or metadata.get("artist") or ""
    cache_key = _track_credits_cache_key(track, title, artist_name)

    if cache_key:
        try:
            import db
            cached = db.get_track_credits(cache_key)
            if cached is not None:
                return cached
        except Exception:
            pass

    mb_recording = _musicbrainz_recording_for_credits(track, title, main[0] if main else "")
    if mb_recording:
        result = _recording_credit_sections(mb_recording, title, artist_name)
        if cache_key:
            try:
                import db
                db.save_track_credits(cache_key, result)
            except Exception:
                pass
        return result

    artist_rows = [{"name": name, "role": "Main Artist"} for name in main]
    artist_rows.extend({"name": name, "role": "Featured Artist"} for name in featured)

    writer_names = []
    for key in ("writer", "writers", "composer", "composers", "lyricist", "lyricists"):
        writer_names.extend(_split_people(track.get(key) or metadata.get(key)))
    producer_names = []
    for key in ("producer", "producers", "mixer", "mixers"):
        producer_names.extend(_split_people(track.get(key) or metadata.get(key)))

    composition_rows = [{"name": name, "role": "Writer"} for name in _split_people(writer_names)]
    production_rows = [{"name": name, "role": "Producer"} for name in _split_people(producer_names)]

    result = {
        "title": title,
        "artist": artist_name,
        "source": "Track metadata",
        "sections": [
            {"title": "Artist", "rows": artist_rows},
            {"title": "Composition and lyrics", "rows": composition_rows},
            {"title": "Production", "rows": production_rows},
        ],
    }
    if cache_key:
        try:
            import db
            db.save_track_credits(cache_key, result)
        except Exception:
            pass
    return result


def _bandsintown_events(artist_name: str) -> list[dict]:
    if not artist_name:
        return []
    try:
        url = (
            "https://rest.bandsintown.com/artists/"
            + urllib.parse.quote(artist_name, safe="")
            + "/events?"
            + urllib.parse.urlencode({"app_id": "mindinguflac"})
        )
        data = get_json(url, timeout=8)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    events = []
    for event in data[:50]:
        venue = event.get("venue") or {}
        datetime_value = event.get("datetime") or ""
        date_part = datetime_value.split("T", 1)[0]
        time_part = datetime_value.split("T", 1)[1][:5] if "T" in datetime_value else ""
        month = ""
        day = ""
        if date_part:
            try:
                parsed = time.strptime(date_part, "%Y-%m-%d")
                month = time.strftime("%b", parsed)
                day = str(parsed.tm_mday)
            except Exception:
                pass
        location = ", ".join(part for part in [venue.get("city", ""), venue.get("region", "") or venue.get("country", "")] if part)
        events.append({
            "name": event.get("title") or venue.get("name") or "Event",
            "artist": artist_name,
            "date": date_part,
            "datetime": datetime_value,
            "time": time_part,
            "month": month,
            "day": day,
            "city": venue.get("city") or location,
            "state": venue.get("region") or "",
            "location": location,
            "venue": venue.get("name") or "",
            "country": venue.get("country") or "",
            "url": event.get("url") or "",
            "source": "Bandsintown",
        })
    return events


_TOUR_CACHE_TTL = 12 * 3600  # real listings: refresh roughly twice a day
_TOUR_EMPTY_TTL = _TOUR_CACHE_TTL


def _tour_iso(timestamp: float) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(timestamp)))
    except Exception:
        return ""


def _tour_cache_ttl(cached: dict) -> float:
    return _TOUR_CACHE_TTL if (cached.get("events")) else _TOUR_EMPTY_TTL


def _stamp_tour_cache(payload: dict, cached_at: float | None = None) -> dict:
    cached_at = float(cached_at or payload.get("cached_at") or time.time())
    ttl = float(payload.get("cache_ttl_seconds") or _tour_cache_ttl(payload))
    expires_at = cached_at + ttl
    payload["cached_at"] = cached_at
    payload["cached_at_iso"] = _tour_iso(cached_at)
    payload["cache_ttl_seconds"] = ttl
    payload["expires_at"] = expires_at
    payload["expires_at_iso"] = _tour_iso(expires_at)
    payload["refresh_needed"] = False
    payload["stale"] = False
    return payload


def _annotate_tour_cache(cached: dict) -> dict:
    if not isinstance(cached, dict):
        return cached
    annotated = dict(cached)
    cached_at = float(annotated.get("cached_at") or annotated.get("_cache_last_updated") or 0)
    ttl = float(annotated.get("cache_ttl_seconds") or _tour_cache_ttl(annotated))
    expires_at = cached_at + ttl if cached_at else 0
    age = time.time() - cached_at if cached_at else float("inf")
    is_stale = age > ttl
    annotated["cached_at"] = cached_at
    annotated["cached_at_iso"] = _tour_iso(cached_at) if cached_at else ""
    annotated["cache_ttl_seconds"] = ttl
    annotated["expires_at"] = expires_at
    annotated["expires_at_iso"] = _tour_iso(expires_at) if expires_at else ""
    annotated["cache_age_seconds"] = max(0, round(age, 3)) if cached_at else None
    annotated["refresh_needed"] = is_stale
    annotated["stale"] = is_stale
    return annotated


def _tour_cache_fresh(cached: dict) -> bool:
    return not _annotate_tour_cache(cached).get("refresh_needed")


def artist_tour(
    artist_id: str,
    artist_name: str,
    live: bool = False,
    refresh: bool = False,
    ai_provider: str = "duckai",
    gemini_model: str = "gemini-1.5-flash",
    timeout_s: float | None = None,
    tour_source: str = "ai",
    tour_url: str = "",
) -> dict:
    """Resolve concert/tour dates for an artist.

    Live data comes from the selected tour source. "ai" uses Duck.ai/Gemini via
    `tour_ai`; "hypebot" scrapes Hypebot/Bandsintown JSON-LD first and falls
    back to the selected AI provider when no matching artist/events are found.
    Results are cached in SQLite. The sidebar calls with live=False
    (cache-only, instant); the full tour page calls live=True to refresh.
    """
    artist_name = (artist_name or "").strip()
    tour_url = (tour_url or "").strip()
    if tour_url:
        live = True
    key = norm_name(artist_name)

    if key and not refresh and not tour_url:
        cached = get_artist_tour_cache(key, None)
        if cached is not None:
            cached = _annotate_tour_cache(cached)
            if _tour_cache_fresh(cached):
                return cached
            if not live:
                cached["pending"] = True
                return cached

    if not live:
        # Cache-only request (sidebar): don't trigger the slow worker.
        # Show any cached preview, even if stale, while marking it for refresh.
        stale = get_artist_tour_cache(key, None) if key else None
        if stale is not None:
            stale = _annotate_tour_cache(stale)
            stale["pending"] = True
            return stale
        return {"artist": artist_name, "events": [], "source": "", "pending": bool(artist_name)}

    def _fetch_ai() -> dict:
        try:
            import tour_ai
            return tour_ai.fetch_tour(
                artist_name,
                ai_provider=ai_provider,
                gemini_model=gemini_model,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            return {"artist": artist_name, "events": [], "source": "", "error": str(exc)}

    def _fetch_hypebot() -> dict:
        try:
            import hypebot_tour
            return hypebot_tour.fetch_artist_concerts(
                artist=artist_name,
                url=tour_url,
                limit=1,
                timeout=max(1.0, min(30.0, float(timeout_s or 15))),
            )
        except Exception as exc:
            return {"artist": artist_name, "events": [], "source": "Hypebot/Bandsintown", "error": str(exc)}

    # Live request (tour page): fetch from the selected source.
    selected_source = (tour_source or "ai").strip().lower()
    if tour_url:
        selected_source = "hypebot"
    print(f"[artist_tour] Live lookup for {artist_name!r} using {selected_source}")
    result = {}
    hypebot_error = ""
    if selected_source == "hypebot":
        result = _fetch_hypebot()
        events = (result or {}).get("events") or []
        pages = (result or {}).get("pages") or []
        message = str((result or {}).get("message") or "").strip()
        print(f"[artist_tour] Hypebot returned {len(events)} events for {artist_name!r}")
        if not events and pages and message:
            print(f"[artist_tour] Hypebot has no events for {artist_name!r}: {message}")
        elif not events:
            hypebot_error = str((result or {}).get("error") or "Hypebot found no matching tour dates.")
            print(f"[artist_tour] Falling back to AI for {artist_name!r}: {hypebot_error}")
            result = _fetch_ai()
            if not result.get("error"):
                result["fallback_from"] = "Hypebot/Bandsintown"
                result["fallback_reason"] = hypebot_error
    else:
        print(f"[artist_tour] Using AI provider {ai_provider!r} for {artist_name!r}")
        result = _fetch_ai()

    events = (result or {}).get("events") or []
    error = (result or {}).get("error")
    if error and "timeout" in str(error).lower():
        return {
            "artist": artist_name,
            "events": [],
            "source": result.get("source", ""),
            "error": "Tour lookup timed out. Please try again.",
        }
    # Cache any successful query (even an empty result) so a non-touring artist
    # doesn't keep re-triggering the slow worker. Errors are never cached, so
    # they retry on the next open.
    if not error:
        pages = (result or {}).get("pages") or []
        page_url = str((result or {}).get("url") or "").strip()
        if not page_url and pages:
            page_url = str((pages[0] or {}).get("url") or "").strip()
        payload = {
            "artist": artist_name,
            "events": events,
            "source": result.get("source") or "Duck.ai",
        }
        _stamp_tour_cache(payload)
        if page_url:
            payload["url"] = page_url
            payload["hypebot_url"] = page_url
            payload["artist_url"] = page_url
            payload["tour_url"] = page_url
        if pages:
            payload["pages"] = pages
        if result.get("message"):
            payload["message"] = result.get("message")
        if result.get("fallback_from"):
            payload["fallback_from"] = result.get("fallback_from")
        if result.get("fallback_reason"):
            payload["fallback_reason"] = result.get("fallback_reason")
        if key:
            try:
                import db
                db.save_artist_tour(key, payload)
            except Exception:
                pass
        return payload

    # Errored fetch: fall back to any stale cache, else surface the error.
    stale = get_artist_tour_cache(key, None) if key else None
    if stale is not None:
        return stale
    return {"artist": artist_name, "events": [], "source": result.get("source", ""), "error": error}


def get_artist_tour_cache(key: str, max_age):
    if not key:
        return None
    try:
        import db
        return db.get_artist_tour(key, max_age)
    except Exception:
        return None


def enrich_artwork_batch(results: list[dict]) -> list[dict]:
    # We use a simple sequential loop here because ThreadPoolExecutor
    # can cause freezes/timeouts in some desktop webview environments (WebKit)
    # when making concurrent network requests.
    enriched = []
    for item in results:
        if item.get("type") == "artist" and item.get("monthly_listeners"):
             enriched.append(item)
             continue
        if item.get("type") != "artist" and item.get("artwork_url"):
            enriched.append(item)
            continue
        try:
            if item.get("type") == "artist":
                artist_name = item.get("artist", "")
                artist_id = item.get("artist_id", "") or item.get("spotify_id", "")
                about = artist_about(artist_id, artist_name)
                if about:
                    item["artwork_url"] = about.get("avatar") or item.get("artwork_url")
                    item["monthly_listeners"] = about.get("monthly_listeners")
                    item["followers"] = about.get("followers")
                    if not item.get("biography"):
                        item["biography"] = about.get("biography")
            elif item.get("type") == "album":
 
                item["artwork_url"] = spotify_album_artwork(item.get("artist", ""), item.get("title", ""))
            else:
                sp = spotify_search_track(item.get("artist", ""), item.get("title", ""))
                if sp.get("artwork_url"): 
                    item["artwork_url"] = sp["artwork_url"]
        except Exception: 
            pass
        enriched.append(item)
    return enriched

def enrich_albums_batch(results: list[dict]) -> list[dict]:
    return results


# ---------------------------------------------------------------------------
# Spotify Web / Wikipedia helpers (merged from spotify_web_metadata)
# ---------------------------------------------------------------------------

_WEB_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
_WEB_QUERY_URL = "https://api-partner.spotify.com/pathfinder/v2/query"
_WEB_APP_VERSION = "896000000"
_WEB_REQUEST_TIMEOUT_S = 18
_WEB_REQUEST_RETRIES = 3
_WEB_REQUEST_RETRY_DELAY_S = 0.5
_ARTIST_ABOUT_CACHE_TTL_S = 600
_ARTIST_ABOUT_FAILURE_TTL_S = 45
_playcount_cache: dict[str, tuple[float, dict[str, int]]] = {}
_artist_about_cache: dict[str, tuple[float, dict]] = {}


def _web_is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionResetError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (TimeoutError, socket.timeout, ConnectionResetError, OSError))
    return isinstance(exc, OSError)


def _web_request_text(
    url: str,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = _WEB_REQUEST_TIMEOUT_S,
    retries: int = _WEB_REQUEST_RETRIES,
) -> str:
    request_headers = {"User-Agent": _WEB_USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=request_headers)
    attempts = max(1, int(retries or 1))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _web_is_retryable_error(exc):
                raise
            delay = _WEB_REQUEST_RETRY_DELAY_S * attempt
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
    html_text = _web_request_text(f"https://open.spotify.com/{path}")
    server_config = re.search(r'id="appServerConfig"[^>]*>([^<]+)', html_text)
    script = re.search(r'<script src="([^"]+/web-player\.[^"]+\.js)"', html_text)
    if not server_config or not script:
        raise ValueError("Spotify web-player configuration was not found")
    config = json.loads(base64.b64decode(server_config.group(1)))
    return int(config.get("serverTime") or time.time()), script.group(1)


@functools.lru_cache(maxsize=16)
def _query_contract(script_url: str) -> dict[str, str]:
    javascript = _web_request_text(script_url)
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


@functools.lru_cache(maxsize=16)
def _query_artist_hash(script_url: str) -> str:
    """Extract only the queryArtistOverview persisted-query hash from the JS bundle.
    Does not attempt TOTP secret extraction — that inline format no longer exists."""
    try:
        javascript = _web_request_text(script_url)
        m = re.search(r'queryArtistOverview","query","([0-9a-f]{64})"', javascript)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _anonymous_token(server_time: int, secret: bytes, token_version: str) -> str:
    query = urllib.parse.urlencode({
        "reason": "init",
        "productType": "web_player",
        "totp": _totp(secret, time.time()),
        "totpServer": _totp(secret, server_time),
        "totpVer": token_version,
    })
    response = json.loads(_web_request_text(f"https://open.spotify.com/api/token?{query}"))
    return response.get("accessToken", "")


def _load_album_playcounts(album_id: str) -> dict[str, int]:
    server_time, script_url = _web_player_config(album_id)
    contract = _query_contract(script_url)
    token = _anonymous_token(server_time, contract["secret"], contract["token_version"])
    if not token:
        return {}
    body = {
        "operationName": "queryAlbumTracks",
        "variables": {"uri": f"spotify:album:{album_id}", "locale": "", "offset": 0, "limit": 50},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": contract["album"]}},
    }
    response = json.loads(_web_request_text(
        _WEB_QUERY_URL,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "spotify-app-version": _WEB_APP_VERSION},
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
    # Use SpotiFLAC's SpotifyWebClient — it handles TOTP via the community secrets
    # repo and adds the required Client-Token header. The old approach of extracting
    # the TOTP secret from Spotify's JS bundle (let eU=[{secret:...}]) no longer
    # works because Spotify removed that inline format.
    sf_client = _get_spotify_client()
    web_client = getattr(sf_client, "web_client", None) if sf_client else None
    if not web_client:
        return {}

    # Try to pull the live queryArtistOverview hash from Spotify's JS bundle so we
    # always use the current persisted-query document (which includes relatedContent).
    # Fall back to a known working hash if the JS scrape fails.
    artist_hash = "446130b4a0aa6522a686aafccddb0ae849165b5e0243617b5d8"
    try:
        _, script_url = _web_player_config(artist_id, is_artist=True)
        live_hash = _query_artist_hash(script_url)
        if live_hash:
            artist_hash = live_hash
    except Exception:
        pass

    body = {
        "operationName": "queryArtistOverview",
        "variables": {"uri": f"spotify:artist:{artist_id}", "locale": "", "includePrerelease": True},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": artist_hash}},
    }
    try:
        response = web_client.query(body)
    except Exception as e:
        print(f"[SpotifyWeb] queryArtistOverview failed for {artist_id}: {e}")
        return {}
    data = response.get("data", {})
    artist = data.get("artistUnion") or data.get("artist") or {}
    stats = artist.get("stats") or {}
    visuals = artist.get("visuals") or {}
    profile = artist.get("profile") or {}
    gallery = []
    for item in visuals.get("gallery", {}).get("items", []):
        sources = item.get("sources") or []
        if sources:
            top = max(sources, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
            gallery.append({"url": top["url"], "width": top.get("width"), "height": top.get("height")})
    avatar_sources = (visuals.get("avatarImage") or {}).get("sources") or []
    if not avatar_sources:
        avatar_sources = (visuals.get("visualIdentity", {}).get("avatarImage") or {}).get("sources") or []
    avatar = ""
    if avatar_sources:
        top_avatar = max(avatar_sources, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
        avatar = top_avatar.get("url", "")

    def _pick_feature_image() -> str:
        if not gallery:
            return avatar
        def score(i: dict) -> tuple[int, int, int]:
            w = int(i.get("width") or 0)
            h = int(i.get("height") or 0)
            area = w * h
            aspect = (w / h) if w and h else 0
            photo_bias = 1 if aspect >= 1.2 or aspect <= 0.85 else 0
            square_penalty = 1 if 0.9 <= aspect <= 1.1 else 0
            return (photo_bias, area, -square_penalty)
        return max(gallery, key=score).get("url", "") or avatar

    related_artists = []
    for item in ((artist.get("relatedContent") or {}).get("relatedArtists") or {}).get("items") or []:
        node = item.get("data") or item
        node_profile = node.get("profile") or {}
        node_name = node_profile.get("name") or ""
        if not node_name:
            continue
        node_id = str(node.get("uri") or "").rsplit(":", 1)[-1]
        node_sources = ((node.get("visuals") or {}).get("avatarImage") or {}).get("sources") or []
        node_image = ""
        if node_sources:
            top = max(node_sources, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
            node_image = top.get("url", "")
        related_artists.append({"name": node_name, "id": node_id, "image": node_image})

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
        "hero_image": _pick_feature_image(),
        "verified": bool(profile.get("verified")),
        "related_artists": related_artists,
    }


def spotify_artist_about(artist_id: str) -> dict:
    if not artist_id:
        return {}
    cached = _artist_about_cache.get(artist_id)
    if cached:
        ttl = _ARTIST_ABOUT_CACHE_TTL_S if cached[1] else _ARTIST_ABOUT_FAILURE_TTL_S
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
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": 1, "explaintext": 1, "titles": artist_name, "redirects": 1,
        })
        data = json.loads(_web_request_text(f"https://en.wikipedia.org/w/api.php?{params}"))
        pages = data.get("query", {}).get("pages", {})
        for page_id in pages:
            return pages[page_id].get("extract", "")
    except Exception:
        pass
    return ""


_WIKI_BASE = "https://en.wikipedia.org"


def _wiki_href_ok(href: str) -> str:
    if not href or not href.startswith("/wiki/"):
        return ""
    title = href[len("/wiki/"):]
    head = title.split("#", 1)[0]
    if not head or ":" in head:
        return ""
    return _WIKI_BASE + href


def _wiki_serialize_child(node) -> str:
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
            return f'<a href="{_htmlmod.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">{inner}</a>' + tail
        return inner + tail
    if tag in ("b", "strong"):
        return f"<b>{inner}</b>" + tail
    if tag in ("i", "em"):
        return f"<i>{inner}</i>" + tail
    return inner + tail


def fetch_wikipedia_about(artist_name: str) -> dict:
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
        data = json.loads(_web_request_text(f"https://en.wikipedia.org/w/api.php?{params}"))
        raw_html = (data.get("parse") or {}).get("text") or ""
        if isinstance(raw_html, dict):
            raw_html = raw_html.get("*", "")
        if raw_html and lxml_html is not None:
            root = lxml_html.fromstring(raw_html)
            paras, text_parts = [], []
            import html as _htmlmod
            for p in root.xpath("//p[not(ancestor::table)]"):
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
        data = json.loads(_web_request_text(f"https://en.wikipedia.org/w/api.php?{params}"))
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
