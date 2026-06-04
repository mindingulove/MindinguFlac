from __future__ import annotations

import json
import time
import functools
import urllib.parse
import urllib.request
import rapidfuzz
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from config import AppConfig, MusicIndexerConfig
from discogs_metadata import discogs_album_images
from spotify_web_metadata import spotify_album_playcounts, spotify_artist_about, fetch_wikipedia_bio


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


def _get_spotify_client():
    global _spotify_client_cache
    with _spotify_client_lock:
        if _spotify_client_cache is not None:
            return _spotify_client_cache if _spotify_client_cache is not False else None
        try:
            from SpotiFLAC.providers.spotify_metadata import SpotifyMetadataClient  # type: ignore
            _spotify_client_cache = SpotifyMetadataClient()
            return _spotify_client_cache
        except ImportError:
            _spotify_client_cache = False
            return None


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
        })
    return results


def _best_raw_image(image: dict | None) -> str:
    sources = (image or {}).get("sources", [])
    if not sources:
        sources = (image or {}).get("image", {}).get("data", {}).get("sources", [])
    return max(sources, key=lambda item: item.get("width", 0), default={}).get("url", "")


def _public_client_get(client: object, endpoint: str, params: dict) -> dict:
    """Expose SpotiFLAC 0.6.1 public methods in the legacy response shape."""
    if endpoint == "search":
        query = params.get("q", "")
        limit = int(params.get("limit", 20))
        results = client.search(query, limit=limit)
        albums = results.get("albums", []) or _raw_search_simple_items(client, query, limit, "album")
        artists = results.get("artists", []) or _raw_search_simple_items(client, query, limit, "artist")
        return {
            "tracks": {"items": [_legacy_track_item(item) for item in results.get("tracks", [])]},
            "albums": {"items": [_legacy_simple_item(item, "album") for item in albums]},
            "artists": {"items": [_legacy_simple_item(item, "artist") for item in artists]},
        }

    playlist_match = re.fullmatch(r"playlists/([^/]+)/tracks", endpoint)
    if playlist_match:
        playlist_result = client.get_playlist_tracks(playlist_match.group(1))
        tracks = playlist_result[1] if len(playlist_result) > 1 else []
        limit = int(params.get("limit", len(tracks)))
        return {"items": [{"track": _legacy_track_item(item)} for item in tracks[:limit]]}

    album_match = re.fullmatch(r"albums/([^/]+)", endpoint)
    if album_match:
        info, tracks = client.get_album_tracks(album_match.group(1))
        cover_url = info.get("cover_url", "")
        return {
            "id": album_match.group(1),
            "name": info.get("name", ""),
            "images": [{"url": cover_url}] if cover_url else [],
            "tracks": {"items": [_legacy_track_item(item) for item in tracks]},
        }

    artist_top_match = re.fullmatch(r"artists/([^/]+)/top-tracks", endpoint)
    if artist_top_match and hasattr(client, "get_artist_profile"):
        profile = client.get_artist_profile(artist_top_match.group(1))
        artist = profile.get("profile", {}).get("name", "")
        tracks = client.search_tracks(artist, limit=20) if artist else []
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
    if cached:
        # Merge cached IDs into current track
        enriched = dict(track)
        for key in ["spotify_id", "isrc", "musicbrainz_recording_id", "musicbrainz_release_id", "deezer_id", "tidal_id", "amazon_id", "apple_music_id"]:
            if cached.get(key) and not enriched.get(key):
                enriched[key] = cached[key]
        return enriched

    enriched = dict(track)
    if not enriched.get("spotify_id") and enriched.get("title"):
        for key, value in spotify_search_track(
            enriched.get("artist", ""),
            enriched.get("title", ""),
        ).items():
            if value and not enriched.get(key):
                enriched[key] = value
    spotify_id = enriched.get("spotify_id", "")
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


@functools.lru_cache(maxsize=128)
def spotify_artist_artwork(artist: str, artist_id: str = "") -> str:
    data = _sp("search", q=f"artist:{artist}", type="artist", limit=3)
    items = (data.get("artists") or {}).get("items") or []
    for a in items:
        if norm_name(a.get("name", "")) == norm_name(artist):
            images = a.get("images") or []
            if images:
                return proxy_artwork_url(images[0]["url"])
    if items:
        images = items[0].get("images") or []
        if images:
            return proxy_artwork_url(images[0]["url"])
    client = _get_spotify_client()
    raw_artwork = _raw_artist_profile_artwork(client, artist_id or spotify_artist_id(artist)) if client else ""
    if raw_artwork:
        return proxy_artwork_url(raw_artwork)
    return ""


@functools.lru_cache(maxsize=128)
def spotify_artist_id(artist_name: str) -> str:
    data = _sp("search", q=f"artist:{artist_name}", type="artist", limit=3)
    sp_artists = (data.get("artists") or {}).get("items") or []
    for item in sp_artists:
        if norm_name(item.get("name", "")) == norm_name(artist_name):
            return item.get("id", "")
    return sp_artists[0].get("id", "") if sp_artists else ""


@functools.lru_cache(maxsize=128)
def spotify_artist_top_tracks(artist_name: str, limit: int = 25, artist_id: str = "") -> list[dict]:
    sp_artist_id = spotify_artist_id(artist_name) or artist_id
    if not sp_artist_id:
        return []
    data = _sp(f"artists/{sp_artist_id}/top-tracks", market="US")
    sp_tracks = (data.get("tracks") or [])[:limit]
    results = []
    for t in sp_tracks:
        images = (t.get("album") or {}).get("images") or []
        art = proxy_artwork_url(images[0]["url"]) if images else ""
        album_name = (t.get("album") or {}).get("name", "")
        if not art and album_name:
            art = spotify_album_artwork(artist_name, album_name)
        results.append({
            "title": t.get("name", ""),
            "artist": artist_name,
            "album": album_name,
            "artwork_url": art,
            "duration": format_duration_ms(t.get("duration_ms", 0)),
            "length": t.get("duration_ms", 0),
            "plays": t.get("popularity", 0) * 10000,
            "spotify_url": (t.get("external_urls") or {}).get("spotify", ""),
            "spotify_id": t.get("id", ""),
            "isrc": (t.get("external_ids") or {}).get("isrc", ""),
            "source": "Spotify",
        })
    return results


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
        client = _get_spotify_client()
        web_client = getattr(client, "web_client", None)
        payload_builder = getattr(client, "_search_payload", None)
        if not web_client or not payload_builder:
            return []
        try:
            data = web_client.query(payload_builder(query, 20))
            search_v2 = data.get("data", {}).get("searchV2", {})
        except Exception:
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


@functools.lru_cache(maxsize=128)
def search_music(config: AppConfig, query: str) -> list[dict]:
    # We strip and lower-case the query for the cache key to be effective
    query = query.strip().lower()
    if not query: return []
    results, seen = [], set()
    for idx in build_music_indexers(config):
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
    return results


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
    kind_prio = {"artist": 100, "track": 50, "album": 10}.get(kind, 0)
    return (score, kind_prio, int(result.get("plays") or 0), 0)


def artist_page(config: AppConfig, artist: str, artist_id: str = ""):
    resolved_artist_id = spotify_artist_id(artist) or artist_id
    art = spotify_artist_artwork(artist, resolved_artist_id)
    if resolved_artist_id:
        from catalog import save_artist_identity
        save_artist_identity(artist, resolved_artist_id, art)
    yield {"type": "artist_info", "artist": artist, "artist_id": resolved_artist_id, "artwork_url": art}
    
    top_tracks = spotify_artist_top_tracks(artist, artist_id=resolved_artist_id)
    yield {"type": "top_tracks", "tracks": top_tracks}

    client = _get_spotify_client()
    album_items = _raw_artist_discography_items(client, resolved_artist_id) if client and resolved_artist_id else []
    if album_items:
        source_items = [_legacy_simple_item(item, "album") for item in album_items]
    else:
        data = _sp("search", q=f"artist:{artist}", type="album", limit=50)
        source_items = (data.get("albums") or {}).get("items") or []
    albums = []
    for item in source_items:
        images = item.get("images") or []
        albums.append({
            "type": "album", "title": item["name"], "artist": artist, "album": item["name"],
            "year": release_year(item.get("release_date", "")),
            "artwork_url": proxy_artwork_url(images[0].get("url", "")) if images else "",
            "spotify_id": item["id"], "source": "Spotify"
        })
    yield {"type": "albums", "albums": albums}


def album_tracks(config: AppConfig, artist: str, album: str, release_id: str = "", spotify_id: str = "") -> dict:
    import db
    album_key = f"{str(artist or '').strip().lower()}||{str(album or '').strip().lower()}"
    cached = db.get_album_metadata(album_key)
    if cached:
        print(f"[Metadata] Using cached album metadata for: {artist} - {album}")
        return cached

    tracks, art, yr, total_ms = [], "", "", 0
    if spotify_id:
        try:
            sp_album = _sp(f"albums/{spotify_id}", market="US")
            if sp_album:
                playcounts = spotify_album_playcounts(spotify_id)
                art = proxy_artwork_url(sp_album.get("images", [{}])[0].get("url", ""))
                yr = release_year(sp_album.get("release_date", ""))
                album_name = sp_album["name"]
                for t in sp_album.get("tracks", {}).get("items") or []:
                    tracks.append({
                        "type": "track", "title": t["name"], "artist": artist,
                        "album": album_name, "year": yr, "track_number": t.get("track_number"),
                        "duration": format_duration_ms(t.get("duration_ms", 0)),
                        "artwork_url": art, "spotify_id": t["id"], "source": "Spotify",
                        "length": t.get("duration_ms", 0), "plays": playcounts.get(t["id"], 0),
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
                        "source": "MusicBrainz", "length": ln
                    })
        except Exception: pass

    if not tracks:
        try:
            data = _sp("search", q=f"artist:{artist} album:{album}", type="album", limit=1)
            items = (data.get("albums") or {}).get("items") or []
            if items: return album_tracks(config, artist, album, "", items[0]["id"])
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
    }
    
    # Cache it!
    import db
    album_key = f"{str(artist or '').strip().lower()}||{str(album or '').strip().lower()}"
    db.save_album_metadata(album_key, result)
    
    return result



def album_metadata(config: AppConfig, artist: str, album: str, track: str = "") -> dict:
    return {"artist": artist, "album": album, "title": track}


def artist_about(artist_id: str, artist_name: str) -> dict:
    about = spotify_artist_about(artist_id)
    
    # If we have monthly listeners or followers, we've found the real artist on Spotify.
    # In this case, we trust Spotify data and do NOT fallback to Wikipedia name-searching.
    has_spotify_stats = bool(about.get("monthly_listeners") or about.get("followers"))
    spotify_bio = (about.get("biography") or "").strip()
    
    if has_spotify_stats or len(spotify_bio) > 5:
        about["biography"] = spotify_bio or "Official biography currently unavailable."
        about["bio_source"] = "Spotify"
    else:
        # ABSOLUTE FALLBACK: Only if Spotify has zero stats AND zero bio.
        wiki_bio = fetch_wikipedia_bio(f"{artist_name} (musician)") or fetch_wikipedia_bio(artist_name)
        if wiki_bio and "may refer to:" not in wiki_bio:
            about["biography"] = wiki_bio
            about["bio_source"] = "Wikipedia"
        else:
            about["biography"] = "Official artist information is currently unavailable."
            about["bio_source"] = "Spotify"
        
    return about


def enrich_artwork_batch(results: list[dict]) -> list[dict]:
    # We use a simple sequential loop here because ThreadPoolExecutor
    # can cause freezes/timeouts in some desktop webview environments (WebKit)
    # when making concurrent network requests.
    enriched = []
    for item in results:
        if item.get("artwork_url"): 
            enriched.append(item)
            continue
        try:
            if item.get("type") == "artist": 
                item["artwork_url"] = spotify_artist_artwork(item.get("artist", ""))
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
