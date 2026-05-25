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


def proxy_artwork_url(url: str) -> str:
    if not url:
        return ""
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


def _sp(endpoint: str, **params) -> dict:
    client = _get_spotify_client()
    if not client:
        return {}
    try:
        return client._get(endpoint, params=params) or {}
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
        results = {}
        for platform, info in links.items():
            results[f"{platform}_url"] = info.get("url")
            u = info.get("url", "")
            if "deezer.com" in u: results["deezer_id"] = u.split("/")[-1].split("?")[0]
            if "tidal.com" in u: results["tidal_id"] = u.split("/")[-1].split("?")[0]
            if "amazon.com" in u: results["amazon_id"] = u.split("/")[-1].split("?")[0]
            if "apple.com" in u: results["apple_music_id"] = u.split("/")[-1].split("?")[0]
        return results
    except Exception: return {}


@functools.lru_cache(maxsize=1024)
def spotify_search_track(artist: str, title: str) -> dict:
    q = f"artist:{artist} track:{title}" if title else f"artist:{artist}"
    data = _sp("search", q=q, type="track", limit=3)
    items = (data.get("tracks") or {}).get("items") or []
    for item in items:
        images = (item.get("album") or {}).get("images") or []
        ext_ids = item.get("external_ids") or {}
        return {
            "spotify_url": (item.get("external_urls") or {}).get("spotify", ""),
            "spotify_id": item.get("id", ""),
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


@functools.lru_cache(maxsize=128)
def spotify_artist_artwork(artist: str) -> str:
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
    return ""


@functools.lru_cache(maxsize=128)
def spotify_artist_top_tracks(artist_name: str, limit: int = 25) -> list[dict]:
    data = _sp("search", q=f"artist:{artist_name}", type="artist", limit=3)
    sp_artists = (data.get("artists") or {}).get("items") or []
    artist_item = None
    for a in sp_artists:
        if norm_name(a.get("name", "")) == norm_name(artist_name):
            artist_item = a
            break
    if not artist_item and sp_artists:
        artist_item = sp_artists[0]
    if not artist_item:
        return []
    sp_artist_id = artist_item["id"]
    data = _sp(f"artists/{sp_artist_id}/top-tracks", market="US")
    sp_tracks = (data.get("tracks") or [])[:limit]
    results = []
    for t in sp_tracks:
        images = (t.get("album") or {}).get("images") or []
        art = proxy_artwork_url(images[0]["url"]) if images else ""
        results.append({
            "title": t.get("name", ""),
            "artist": artist_name,
            "album": (t.get("album") or {}).get("name", ""),
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
        data = _sp("search", q=query, type="track,album,artist", limit=20)
        results = []
        for item in (data.get("tracks") or {}).get("items") or []:
            images = (item.get("album") or {}).get("images") or []
            results.append({
                "type": "track", "title": item.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                "album": (item.get("album") or {}).get("name", ""),
                "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_url": (item.get("external_urls") or {}).get("spotify", ""),
                "spotify_id": item.get("id", ""), "isrc": (item.get("external_ids") or {}).get("isrc", ""),
                "source": "Spotify", "plays": item.get("popularity", 0) * 1000,
            })
        for item in (data.get("albums") or {}).get("items") or []:
            images = item.get("images") or []
            results.append({
                "type": "album", "title": item.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                "album": item.get("name", ""), "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_id": item["id"], "source": "Spotify", "plays": 0,
            })
        for item in (data.get("artists") or {}).get("items") or []:
            images = item.get("images") or []
            results.append({
                "type": "artist", "title": item.get("name", ""), "artist": item.get("name", ""),
                "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_id": item.get("id", ""), "source": "Spotify", "plays": item.get("popularity", 0) * 1000,
            })
        return results

    def top_tracks(self, limit: int = 20) -> list[dict]:
        data = _sp("playlists/37i9dQZEVXbMDoHDwVN2tF/tracks", market="US", limit=limit)
        results = []
        for entry in data.get("items") or []:
            item = entry.get("track")
            if not item: continue
            images = (item.get("album") or {}).get("images") or []
            results.append({
                "type": "track", "title": item.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                "album": (item.get("album") or {}).get("name", ""),
                "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_id": item.get("id", ""), "source": "Spotify", "plays": item.get("popularity", 0) * 10000,
            })
        return results

    def new_releases(self, limit: int = 20) -> list[dict]:
        data = _sp("browse/new-releases", market="US", limit=limit)
        results = []
        for item in (data.get("albums") or {}).get("items") or []:
            images = item.get("images") or []
            results.append({
                "type": "album", "title": item.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                "album": item.get("name", ""), "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_id": item.get("id", ""), "source": "Spotify", "plays": 0,
            })
        return results

    def top_artists(self, limit: int = 20) -> list[dict]:
        data = _sp("search", q="year:2024", type="artist", limit=limit)
        results = []
        for item in (data.get("artists") or {}).get("items") or []:
            images = item.get("images") or []
            results.append({
                "type": "artist", "title": item.get("name", ""), "artist": item.get("name", ""),
                "artwork_url": proxy_artwork_url(images[0]["url"]) if images else "",
                "spotify_id": item.get("id", ""), "source": "Spotify", "plays": item.get("popularity", 0) * 10000,
            })
        return results


def build_music_indexers(config: AppConfig) -> list[BaseMusicIndexer]:
    return [SpotifyIndexer()] if _get_spotify_client() else []


def search_music(config: AppConfig, query: str) -> list[dict]:
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
    art = spotify_artist_artwork(artist)
    yield {"type": "artist_info", "artist": artist, "artist_id": artist_id, "artwork_url": art}
    
    top_tracks = spotify_artist_top_tracks(artist)
    yield {"type": "top_tracks", "tracks": top_tracks}

    data = _sp("search", q=f"artist:{artist}", type="album", limit=15)
    albums = []
    for item in (data.get("albums") or {}).get("items") or []:
        albums.append({
            "type": "album", "title": item["name"], "artist": artist, "album": item["name"],
            "year": release_year(item.get("release_date", "")),
            "artwork_url": proxy_artwork_url(item.get("images", [{}])[0].get("url", "")),
            "spotify_id": item["id"], "source": "Spotify"
        })
    yield {"type": "albums", "albums": albums}


def album_tracks(config: AppConfig, artist: str, album: str, release_id: str = "", spotify_id: str = "") -> dict:
    tracks, art, yr, total_ms = [], "", "", 0
    if spotify_id:
        try:
            sp_album = _sp(f"albums/{spotify_id}", market="US")
            if sp_album:
                art = proxy_artwork_url(sp_album.get("images", [{}])[0].get("url", ""))
                yr = release_year(sp_album.get("release_date", ""))
                album_name = sp_album["name"]
                for t in sp_album.get("tracks", {}).get("items") or []:
                    tracks.append({
                        "type": "track", "title": t["name"], "artist": artist,
                        "album": album_name, "year": yr, "track_number": t.get("track_number"),
                        "duration": format_duration_ms(t.get("duration_ms", 0)),
                        "artwork_url": art, "spotify_id": t["id"], "source": "Spotify",
                        "length": t.get("duration_ms", 0)
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
                        "artwork_url": art or proxy_artwork_url(spotify_album_artwork(artist, album_name)),
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

    if not art: art = proxy_artwork_url(spotify_album_artwork(artist, album))
    return {
        "artist": artist, "album": album, "year": yr, "track_count": len(tracks),
        "total_duration": format_duration_ms(total_ms), "artwork_url": art,
        "artist_artwork_url": spotify_artist_artwork(artist), "tracks": tracks,
    }


def album_metadata(config: AppConfig, artist: str, album: str, track: str = "") -> dict:
    return {"artist": artist, "album": album, "title": track}


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
