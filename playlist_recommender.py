from __future__ import annotations

import json
import random
import re
import uuid
from pathlib import Path

import db
from catalog import discover_catalog
from config import app_data_dir, load_config
from taste_profile import normalize_artist_key, normalize_genre_key


PLAYLISTS_PATH = app_data_dir() / "playlists.json"


def _load_playlists() -> list[dict]:
    try:
        return json.loads(PLAYLISTS_PATH.read_text("utf-8"))
    except Exception:
        return []


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _track_key(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    spotify_id = str(item.get("spotify_id") or item.get("track_key") or "").strip()
    if spotify_id:
        return spotify_id
    title = _normalize_text(item.get("title") or item.get("name") or "")
    artist = _normalize_text(item.get("artist") or "")
    if not title and not artist:
        return ""
    return f"{artist}||{title}"


def _candidate_to_item(item: dict, source: str = "local_cache") -> dict:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    candidate = {
        "track_key": _track_key(item),
        "title": item.get("title") or item.get("name") or metadata.get("title") or "",
        "artist": item.get("artist") or metadata.get("artist") or "",
        "album": item.get("album") or metadata.get("album") or "",
        "artwork_url": item.get("artwork_url") or metadata.get("artwork_url") or "",
        "duration_ms": int(item.get("duration_ms") or metadata.get("duration_ms") or 0),
        "metadata": metadata,
        "source": source,
        "artist_id": item.get("artist_id") or metadata.get("artist_id") or "",
        "spotify_id": item.get("spotify_id") or metadata.get("spotify_id") or "",
    }
    if not candidate["track_key"]:
        candidate["track_key"] = _track_key(candidate)
    return candidate


def get_playlist_track_keys(playlist_id: str) -> set[str]:
    playlist = next((pl for pl in _load_playlists() if pl.get("id") == playlist_id), None)
    if not playlist:
        return set()
    keys = set()
    for track in playlist.get("tracks") or []:
        key = _track_key(track)
        if key:
            keys.add(key)
    return keys


def get_current_queue_track_keys(queue_track_keys: set[str] | None = None) -> set[str]:
    return {str(key).strip() for key in (queue_track_keys or set()) if str(key).strip()}


def get_current_session_shown_track_keys(session_id: str) -> set[str]:
    return db.get_playlist_recommendation_session_shown(session_id)


def get_playlist_recommendation_feedback_keys(playlist_id: str, actions: list[str]) -> set[str]:
    return db.get_playlist_recommendation_feedback(playlist_id, actions)


def build_playlist_seed_profile(playlist_id: str) -> dict:
    playlist = next((pl for pl in _load_playlists() if pl.get("id") == playlist_id), None) or {}
    tracks = list(playlist.get("tracks") or [])
    artist_counts: dict[str, int] = {}
    album_counts: dict[str, int] = {}
    genre_counts: dict[str, int] = {}
    years: list[int] = []
    title_words: set[str] = set()
    track_keys: set[str] = set()

    for track in tracks:
        if not isinstance(track, dict):
            continue
        key = _track_key(track)
        if key:
            track_keys.add(key)
        artist = _normalize_text(track.get("artist") or track.get("name") or "")
        album = _normalize_text(track.get("album") or "")
        if artist:
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
        if album:
            album_counts[album] = album_counts.get(album, 0) + 1
        metadata = track.get("metadata") if isinstance(track.get("metadata"), dict) else {}
        for genre in (metadata.get("genres") or []):
            key_g = normalize_genre_key(genre)
            if key_g:
                genre_counts[key_g] = genre_counts.get(key_g, 0) + 1
        for genre in track.get("genres") or []:
            key_g = normalize_genre_key(genre)
            if key_g:
                genre_counts[key_g] = genre_counts.get(key_g, 0) + 1
        year = track.get("year") or track.get("release_year")
        try:
            year_int = int(year)
            if 1900 <= year_int <= 2100:
                years.append(year_int)
        except Exception:
            pass

    playlist_text = f"{playlist.get('name', '')} {playlist.get('description', '')}".lower()
    for word in re.findall(r"[a-z0-9]+", playlist_text):
        if len(word) > 2:
            title_words.add(word)

    top_artist = max(artist_counts.items(), key=lambda kv: kv[1])[0] if artist_counts else ""
    top_artist_count = artist_counts.get(top_artist, 0)
    is_artist_specific = bool(top_artist and tracks and top_artist_count / max(len(tracks), 1) >= 0.6)
    decade = None
    if years:
        decade = (sorted(years)[len(years) // 2] // 10) * 10

    return {
        "playlist_id": playlist_id,
        "name": playlist.get("name", ""),
        "description": playlist.get("description", ""),
        "artists": artist_counts,
        "albums": album_counts,
        "genres": genre_counts,
        "years": years,
        "decade": decade,
        "title_words": sorted(title_words),
        "track_keys": track_keys,
        "is_artist_specific": is_artist_specific,
    }


def _expand_catalog_items() -> list[dict]:
    cfg = load_config()
    catalog = discover_catalog(cfg)
    out: list[dict] = []
    for key in ("personal_tracks", "recent_tracks", "top_tracks", "artists", "albums"):
        for item in catalog.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "album" and isinstance(item.get("tracks"), list):
                for track in item.get("tracks") or []:
                    if isinstance(track, dict):
                        out.append(_candidate_to_item(track, source="metadata"))
            else:
                out.append(_candidate_to_item(item, source="local_cache"))
    for item in db.get_known_tracks(limit=4000):
        if isinstance(item, dict):
            out.append(_candidate_to_item(item, source="local_cache"))
    return out


def _metadata_confidence(candidate: dict) -> float:
    score = 0.0
    if candidate.get("title"):
        score += 0.4
    if candidate.get("artist"):
        score += 0.3
    if candidate.get("duration_ms"):
        score += 0.2
    if candidate.get("artwork_url"):
        score += 0.1
    return score


def score_recommendation_candidate(candidate: dict, seed_profile: dict, taste_profile: dict) -> float:
    score = 0.0
    artist = _normalize_text(candidate.get("artist"))
    album = _normalize_text(candidate.get("album"))
    title = _normalize_text(candidate.get("title"))
    genres = [normalize_genre_key(g) for g in (candidate.get("genres") or []) if normalize_genre_key(g)]
    years = []
    for key in ("year", "release_year"):
        try:
            if candidate.get(key):
                years.append(int(candidate.get(key)))
        except Exception:
            pass

    if artist and artist in seed_profile.get("artists", {}):
        score += 22.0
    if album and album in seed_profile.get("albums", {}):
        score += 10.0
    if genres:
        for genre in genres:
            if genre in seed_profile.get("genres", {}):
                score += 8.0
    if years and seed_profile.get("decade"):
        cand_decade = (years[0] // 10) * 10
        if cand_decade == seed_profile["decade"]:
            score += 5.0
    if artist and seed_profile.get("is_artist_specific"):
        score += 6.0 if artist in seed_profile.get("artists", {}) else -2.0
    if title:
        for word in seed_profile.get("title_words", []):
            if word in title or word in album or word in artist:
                score += 2.0

    track_key = candidate.get("track_key") or _track_key(candidate)
    score += float(db.get_taste_score_for_track(track_key) or 0.0) * 0.8
    score += float(db.get_taste_score_for_artist(candidate.get("artist") or "") or 0.0) * 0.35
    if genres:
        for genre in genres:
            affinity = db.get_genre_affinity(genre) or {}
            score += float(affinity.get("score") or 0.0) * 0.25

    if db.is_track_taste_soft_blacklisted(track_key):
        score -= 30.0
    artist_affinity = db.get_artist_affinity(candidate.get("artist") or "")
    if artist_affinity and artist_affinity.get("status") == "soft_blacklisted":
        score -= 8.0
    track_affinity = db.get_track_affinity(track_key) or {}
    if track_affinity and track_affinity.get("total_skips", 0) > track_affinity.get("total_plays", 0):
        score -= 6.0

    score += _metadata_confidence(candidate) * 3.0
    if re.search(r"\b(live|remix|karaoke|cover)\b", f"{title} {album}", re.I):
        score -= 4.0

    return score


def _hard_excluded(candidate: dict, playlist_keys: set[str], queue_keys: set[str], exclude_track_keys: set[str], session_id: str | None) -> bool:
    key = candidate.get("track_key") or _track_key(candidate)
    if not key:
        return True
    if key in playlist_keys or key in queue_keys or key in exclude_track_keys:
        return True
    if db.is_track_taste_hard_blacklisted(key):
        return True
    if db.is_blacklisted(candidate.get("resolved_url", "")):
        return True
    artist_affinity = db.get_artist_affinity(candidate.get("artist") or "")
    if artist_affinity and artist_affinity.get("status") == "hard_blacklisted":
        return True
    if session_id and key in get_current_session_shown_track_keys(session_id):
        return True
    return False


def weighted_random_sample(candidates: list[dict], limit: int, session_id: str | None = None) -> list[dict]:
    if not candidates or limit <= 0:
        return []
    seed = session_id or str(uuid.uuid4())
    rng = random.Random(seed)
    pool = [dict(item) for item in candidates]
    chosen: list[dict] = []
    while pool and len(chosen) < limit:
        min_score = min(float(item.get("score") or 0.0) for item in pool)
        weights = [max(float(item.get("score") or 0.0) - min_score + 0.01, 0.01) for item in pool]
        selected = rng.choices(pool, weights=weights, k=1)[0]
        chosen.append(selected)
        pool = [item for item in pool if item.get("track_key") != selected.get("track_key")]
    return chosen


def _apply_diversity_limit(candidates: list[dict], max_per_artist: int = 2, artist_specific: bool = False) -> list[dict]:
    if artist_specific:
        return candidates[:]
    counts: dict[str, int] = {}
    out: list[dict] = []
    for candidate in candidates:
        artist = _normalize_text(candidate.get("artist"))
        counts[artist] = counts.get(artist, 0)
        if artist and counts[artist] >= max_per_artist:
            continue
        out.append(candidate)
        if artist:
            counts[artist] += 1
    return out


def _candidate_reason(candidate: dict, seed_profile: dict) -> str:
    artist = _normalize_text(candidate.get("artist"))
    album = _normalize_text(candidate.get("album"))
    if artist and artist in seed_profile.get("artists", {}):
        return "Matches the playlist artist"
    if album and album in seed_profile.get("albums", {}):
        return "Matches the playlist album"
    if candidate.get("score", 0) > 15:
        return "Strong taste match"
    if candidate.get("score", 0) > 5:
        return "Good fit for this playlist"
    return "Recommended from your listening taste"


def generate_playlist_recommendations(
    playlist_id: str,
    limit: int = 10,
    refresh: bool = False,
    exclude_track_keys: set[str] | None = None,
    queue_track_keys: set[str] | None = None,
    session_id: str | None = None,
) -> dict:
    seed_profile = build_playlist_seed_profile(playlist_id)
    playlist_keys = set(seed_profile.get("track_keys") or set())
    queue_keys = get_current_queue_track_keys(queue_track_keys)
    excluded = set(exclude_track_keys or set()) | playlist_keys | queue_keys
    if refresh or not session_id:
        session_id = str(uuid.uuid4())
        db.save_playlist_recommendation_session(session_id, playlist_id)
    else:
        db.touch_playlist_recommendation_session(session_id, playlist_id)

    feedback_exclusions = get_playlist_recommendation_feedback_keys(playlist_id, ["added", "dismissed"])
    session_shown = get_current_session_shown_track_keys(session_id)
    excluded |= feedback_exclusions | session_shown

    taste_snapshot = {
        "track_affinities": db.get_liked_tracks(200) + db.get_soft_blacklisted_tracks(200) + db.get_hard_blacklisted_tracks(200),
    }

    candidates: list[dict] = []
    for raw in _expand_catalog_items():
        candidate = dict(raw)
        candidate["track_key"] = candidate.get("track_key") or _track_key(candidate)
        if _hard_excluded(candidate, playlist_keys, queue_keys, excluded, session_id):
            continue
        candidate["score"] = score_recommendation_candidate(candidate, seed_profile, taste_snapshot)
        if candidate["score"] <= -50:
            continue
        candidates.append(candidate)

    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    candidates = candidates[:50]
    candidates = _apply_diversity_limit(candidates, 2, bool(seed_profile.get("is_artist_specific")))
    chosen = weighted_random_sample(candidates, limit, session_id=session_id)

    items: list[dict] = []
    for candidate in chosen:
        item = {
            "track_key": candidate.get("track_key"),
            "title": candidate.get("title", ""),
            "artist": candidate.get("artist", ""),
            "album": candidate.get("album", ""),
            "artwork_url": candidate.get("artwork_url", ""),
            "duration_ms": int(candidate.get("duration_ms") or 0),
            "score": float(candidate.get("score") or 0.0),
            "reason": _candidate_reason(candidate, seed_profile),
            "source": candidate.get("source", "local_cache"),
            "already_in_playlist": False,
            "already_in_queue": False,
        }
        db.record_playlist_recommendation_feedback(playlist_id, item["track_key"], "shown", session_id)
        db.save_playlist_recommendation_cache(item, playlist_id, item["score"], item["reason"])
        items.append(item)
    return {"playlist_id": playlist_id, "session_id": session_id, "items": items}


def generate_one_replacement_recommendation(
    playlist_id: str,
    exclude_track_keys: set[str],
    queue_track_keys: set[str] | None = None,
    session_id: str | None = None,
) -> dict | None:
    result = generate_playlist_recommendations(
        playlist_id,
        limit=1,
        refresh=False,
        exclude_track_keys=exclude_track_keys,
        queue_track_keys=queue_track_keys,
        session_id=session_id,
    )
    items = result.get("items") or []
    return items[0] if items else None


def record_recommendation_feedback(playlist_id: str, track_key: str, action: str, session_id: str | None = None) -> None:
    if not track_key or not action:
        return
    db.record_playlist_recommendation_feedback(playlist_id, track_key, action, session_id)
