from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from config import jobs_path, ROOT

DISCOVERY_CACHE_PATH = ROOT / "data" / "discovery_cache.json"

# "Most listened in the world" / Discovery defaults
DEFAULT_GLOBAL_TRACKS = [
    {"title": "Blinding Lights", "artist": "The Weeknd", "album": "After Hours", "plays": 482000},
    {"title": "Starboy", "artist": "The Weeknd", "album": "Starboy", "plays": 475000},
    {"title": "Sweater Weather", "artist": "The Neighbourhood", "album": "I Love You.", "plays": 468000},
    {"title": "Another Love", "artist": "Tom Odell", "album": "Long Way Down", "plays": 461000},
    {"title": "Believer", "artist": "Imagine Dragons", "album": "Evolve", "plays": 454000},
    {"title": "Perfect", "artist": "Ed Sheeran", "album": "÷", "plays": 447000},
    {"title": "Heat Waves", "artist": "Glass Animals", "album": "Dreamland", "plays": 440000},
    {"title": "Get Lucky", "artist": "Daft Punk", "album": "Random Access Memories", "plays": 436000},
    {"title": "Nuthin' But a G Thang", "artist": "Dr. Dre", "album": "The Chronic", "plays": 429000},
    {"title": "Hyperballad", "artist": "Björk", "album": "Post", "plays": 422000},
    {"title": "Come As You Are", "artist": "Nirvana", "album": "Nevermind", "plays": 415000},
    {"title": "The Less I Know the Better", "artist": "Tame Impala", "album": "Currents", "plays": 408000},
    {"title": "Black Hole Sun", "artist": "Soundgarden", "album": "Superunknown", "plays": 401000},
    {"title": "Feel Good Inc.", "artist": "Gorillaz", "album": "Demon Days", "plays": 394000},
    {"title": "No Surprises", "artist": "Radiohead", "album": "OK Computer", "plays": 387000},
    {"title": "Walking on a Dream", "artist": "Empire of the Sun", "album": "Walking on a Dream", "plays": 380000},
    {"title": "Digital Bath", "artist": "Deftones", "album": "White Pony", "plays": 373000},
    {"title": "Yellow", "artist": "Coldplay", "album": "Parachutes", "plays": 366000},
    {"title": "Wonderwall", "artist": "Oasis", "album": "(What's the Story) Morning Glory?", "plays": 359000},
    {"title": "Smells Like Teen Spirit", "artist": "Nirvana", "album": "Nevermind", "plays": 352000},
    {"title": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera", "plays": 345000},
    {"title": "Dreams", "artist": "Fleetwood Mac", "album": "Rumours", "plays": 338000},
    {"title": "Lose Yourself", "artist": "Eminem", "album": "8 Mile", "plays": 331000},
    {"title": "Hotel California", "artist": "Eagles", "album": "Hotel California", "plays": 324000},
]


def load_discovery_cache() -> dict:
    if DISCOVERY_CACHE_PATH.exists():
        try:
            return json.loads(DISCOVERY_CACHE_PATH.read_text("utf-8"))
        except Exception: pass
    return {"top_tracks": DEFAULT_GLOBAL_TRACKS, "top_artists": [], "top_albums": []}


def save_discovery_cache(data: dict) -> None:
    try:
        DISCOVERY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DISCOVERY_CACHE_PATH.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception: pass


def discover_catalog(config) -> dict:
    cache = load_discovery_cache()
    library = []
    music_dir = config.music_dir
    if music_dir.exists():
        try:
            from music_metadata import is_valid_audio_file
            # Find audio files in music dir
            for path in music_dir.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac"}:
                    # Basic metadata extraction
                    parts = path.parts[len(music_dir.parts):]
                    artist = parts[0] if len(parts) > 1 else "Unknown Artist"
                    album = parts[1] if len(parts) > 2 else "Unknown Album"
                    title = path.stem
                    
                    library.append({
                        "type": "track",
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "plays": 1,
                        "library_path": str(path),
                        "artwork_url": "",
                        "source": "Your Library"
                    })
        except Exception: pass
    
    recent = []
    if JOBS_PATH.exists():
        try:
            with JOBS_PATH.open("r", encoding="utf-8") as f:
                jobs = json.load(f)
                jobs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
                for job in jobs[:20]:
                    if job.get("status") == "finished":
                        recent.append({
                            "type": "track",
                            "id": job["id"],
                            "title": job["title"],
                            "artist": job["artist"],
                            "album": job.get("album", ""),
                            "artwork_url": job.get("artwork_url", ""),
                            "library_path": job.get("library_path", ""),
                            "metadata": job.get("metadata", {}),
                            "plays": 1,
                            "source": "Recently Played"
                        })
        except Exception: pass

    # Top Global from Spotify
    base_global = []
    top_artists = []
    top_albums = []
    
    try:
        from music_metadata import SpotifyIndexer
        sp = SpotifyIndexer()
        base_global = sp.top_tracks(24)
        top_artists = sp.top_artists(24)
        top_albums = sp.new_releases(24)
        
        # Update cache on successful fetch
        if base_global:
            save_discovery_cache({
                "top_tracks": base_global,
                "top_artists": top_artists,
                "top_albums": top_albums
            })
    except Exception:
        # Use cached data as fallback
        base_global = [{**t, "type": "track", "source": "Global Discovery"} for t in cache.get("top_tracks", DEFAULT_GLOBAL_TRACKS)]
        top_artists = cache.get("top_artists", [])
        top_albums = cache.get("top_albums", [])

    # Deduplicate library artists/albums for full lists
    all_artists = {}
    all_albums = {}
    
    for t in library + recent + base_global:
        art_name = t.get("artist") or "Unknown Artist"
        if art_name not in all_artists:
            all_artists[art_name] = {
                "type": "artist", 
                "name": art_name, 
                "artist": art_name, 
                "tracks": 0, 
                "plays": 0, 
                "artwork_url": t.get("artwork_url", ""),
                "spotify_id": t.get("spotify_id"),
                "musicbrainz_artist_id": t.get("musicbrainz_artist_id") or (t.get("metadata") or {}).get("musicbrainz_artist_id")
            }
        all_artists[art_name]["tracks"] += 1
        all_artists[art_name]["plays"] += t.get("plays", 0)

    for t in library + recent + base_global:
        alb_title = t.get("album") or "Unknown Album"
        art_name = t.get("artist") or "Unknown Artist"
        key = (art_name, alb_title)
        if key not in all_albums:
            all_albums[key] = {
                "type": "album", 
                "title": alb_title, 
                "album": alb_title, 
                "artist": art_name, 
                "plays": 0, 
                "artwork_url": t.get("artwork_url", ""),
                "spotify_id": t.get("spotify_id") if t.get("type") == "album" else None,
                "musicbrainz_release_id": t.get("musicbrainz_release_id") or (t.get("metadata") or {}).get("musicbrainz_release_id")
            }
        all_albums[key]["plays"] += t.get("plays", 0)

    # Merge in dedicated Top Artists/Albums from Spotify
    for a in top_artists:
        if a["artist"] not in all_artists:
            all_artists[a["artist"]] = a
        else:
            if not all_artists[a["artist"]].get("artwork_url"):
                all_artists[a["artist"]]["artwork_url"] = a.get("artwork_url")

    for al in top_albums:
        key = (al["artist"], al["title"])
        if key not in all_albums:
            all_albums[key] = al

    return {
        "personal_tracks": library,
        "recent_tracks": recent,
        "top_tracks": base_global,
        "artists": sorted(all_artists.values(), key=lambda x: (-x["plays"], x.get("name", "").lower())),
        "albums": sorted(all_albums.values(), key=lambda x: (-x["plays"], x.get("artist", "").lower(), x.get("title", "").lower())),
    }
