from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config import app_data_dir

_DB_PATH = app_data_dir() / "mindinguflac.db"
_local = threading.local()


def _get_conn():
    if not hasattr(_local, "conn"):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH, timeout=15.0)
        _local.conn.row_factory = sqlite3.Row
        _init_db(_local.conn)
    return _local.conn


def _init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            track_key TEXT PRIMARY KEY,
            engine TEXT,
            service TEXT,
            quality TEXT,
            resolved_url TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_aliases (
            alias_key TEXT PRIMARY KEY,
            track_key TEXT NOT NULL,
            alias_type TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            url TEXT PRIMARY KEY,
            reason TEXT,
            last_failed REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blacklist_aliases (
            alias_key TEXT NOT NULL,
            url TEXT NOT NULL,
            reason TEXT,
            last_failed REAL,
            PRIMARY KEY (alias_key, url)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            album_key TEXT PRIMARY KEY,
            metadata_json TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            track_key TEXT PRIMARY KEY,
            metadata_json TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS album_sources (
            album_key TEXT PRIMARY KEY,
            engine TEXT,
            resolved_url TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS adult_filter_terms (
            term TEXT PRIMARY KEY,
            kind TEXT DEFAULT 'adult',
            match_mode TEXT DEFAULT 'word',
            enabled INTEGER DEFAULT 1,
            source TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artist_tours (
            artist_key TEXT PRIMARY KEY,
            metadata_json TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_credits (
            credit_key TEXT PRIMARY KEY,
            metadata_json TEXT,
            last_updated REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listening_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            track_key TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            album TEXT,
            source_engine TEXT,
            source_service TEXT,
            resolved_url TEXT,
            started_at REAL,
            ended_at REAL,
            listened_ms INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            listened_percent REAL DEFAULT 0,
            event_type TEXT NOT NULL,
            reason TEXT,
            metadata_json TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_affinity (
            track_key TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            album TEXT,
            score REAL DEFAULT 0,
            status TEXT DEFAULT 'neutral',
            total_plays INTEGER DEFAULT 0,
            total_skips INTEGER DEFAULT 0,
            total_completed INTEGER DEFAULT 0,
            total_listened_ms INTEGER DEFAULT 0,
            last_listened_at REAL,
            last_skipped_at REAL,
            first_seen_at REAL,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artist_affinity (
            artist_key TEXT PRIMARY KEY,
            artist_name TEXT,
            score REAL DEFAULT 0,
            status TEXT DEFAULT 'neutral',
            total_plays INTEGER DEFAULT 0,
            total_skips INTEGER DEFAULT 0,
            total_completed INTEGER DEFAULT 0,
            total_listened_ms INTEGER DEFAULT 0,
            last_listened_at REAL,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS genre_affinity (
            genre_key TEXT PRIMARY KEY,
            genre_name TEXT,
            score REAL DEFAULT 0,
            total_plays INTEGER DEFAULT 0,
            total_skips INTEGER DEFAULT 0,
            total_completed INTEGER DEFAULT 0,
            total_listened_ms INTEGER DEFAULT 0,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS affinity_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_key TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            old_score REAL,
            new_score REAL,
            changed_at REAL NOT NULL,
            reason TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_recommendation_sessions (
            session_id TEXT PRIMARY KEY,
            playlist_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_used_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_recommendation_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT NOT NULL,
            track_key TEXT NOT NULL,
            action TEXT NOT NULL,
            session_id TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS playlist_recommendation_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT NOT NULL,
            track_key TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            album TEXT,
            artwork_url TEXT,
            score REAL DEFAULT 0,
            reason TEXT,
            candidate_json TEXT,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            UNIQUE(playlist_id, track_key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listening_events_track_key ON listening_events(track_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listening_events_started_at ON listening_events(started_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listening_events_event_type ON listening_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_track_affinity_status ON track_affinity(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artist_affinity_status ON artist_affinity(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_genre_affinity_genre_key ON genre_affinity(genre_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_sessions_playlist_id ON playlist_recommendation_sessions(playlist_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_feedback_playlist_id ON playlist_recommendation_feedback(playlist_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_feedback_track_key ON playlist_recommendation_feedback(track_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_feedback_action ON playlist_recommendation_feedback(action)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_feedback_session_id ON playlist_recommendation_feedback(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_cache_playlist_id ON playlist_recommendation_cache(playlist_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_cache_score ON playlist_recommendation_cache(score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_recommendation_cache_expires_at ON playlist_recommendation_cache(expires_at)")
    conn.commit()
    _run_one_time_migrations(conn)


# Artist-id fields that can carry a wrong/non-Spotify id cached before the
# name-fallback fix in music_metadata.artist_about. Scrubbing them forces a
# fresh, correct re-resolution on next lookup.
_ARTIST_ID_FIELDS = ("spotify_artist_id", "artist_id")


def _run_one_time_migrations(conn: sqlite3.Connection):
    """Idempotent, sentinel-guarded migrations. Safe to call on every connect:
    each migration runs once per database (flagged in the meta table)."""
    try:
        done = conn.execute(
            "SELECT value FROM meta WHERE key = 'artist_id_scrub_v1'"
        ).fetchone()
        if not done:
            _clear_cached_artist_ids_conn(conn, None)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('artist_id_scrub_v1', ?)",
                (str(time.time()),),
            )
            conn.commit()
        done = conn.execute(
            "SELECT value FROM meta WHERE key = 'listening_event_source_backfill_v1'"
        ).fetchone()
        if not done:
            _backfill_listening_event_sources(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('listening_event_source_backfill_v1', ?)",
                (str(time.time()),),
            )
            conn.commit()
        done = conn.execute(
            "SELECT value FROM meta WHERE key = 'saved_playlist_taste_backfill_v1'"
        ).fetchone()
        if not done:
            _backfill_saved_playlist_taste(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('saved_playlist_taste_backfill_v1', ?)",
                (str(time.time()),),
            )
            conn.commit()
    except Exception:
        pass


def save_resolved_source(track_key: str, engine: str, service: str, quality: str, resolved_url: str):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO sources (track_key, engine, service, quality, resolved_url, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (track_key, engine, service, quality, resolved_url, time.time()))
    conn.commit()


def _backfill_listening_event_sources(conn: sqlite3.Connection) -> int:
    rows = conn.execute("""
        SELECT id, source_engine, source_service, resolved_url, metadata_json
        FROM listening_events
    """).fetchall()
    changed = 0
    for row in rows:
        source_engine = str(row["source_engine"] or "").strip()
        source_service = str(row["source_service"] or "").strip()
        resolved_url = str(row["resolved_url"] or "").strip()
        if source_engine and source_service and resolved_url:
            continue
        metadata = _json_load_maybe(row["metadata_json"])
        if not metadata:
            continue
        next_source = str(metadata.get("source_engine") or metadata.get("source") or "").strip()
        next_service = str(metadata.get("source_service") or metadata.get("source") or "").strip()
        next_url = str(metadata.get("resolved_url") or metadata.get("spotify_url") or metadata.get("url") or "").strip()
        updated = {
            "source_engine": source_engine or next_source,
            "source_service": source_service or next_service,
            "resolved_url": resolved_url or next_url,
        }
        if updated["source_engine"] == source_engine and updated["source_service"] == source_service and updated["resolved_url"] == resolved_url:
            continue
        conn.execute("""
            UPDATE listening_events
            SET source_engine = COALESCE(NULLIF(source_engine, ''), ?),
                source_service = COALESCE(NULLIF(source_service, ''), ?),
                resolved_url = COALESCE(NULLIF(resolved_url, ''), ?)
            WHERE id = ?
        """, (
            updated["source_engine"],
            updated["source_service"],
            updated["resolved_url"],
            row["id"],
        ))
        changed += 1
    conn.commit()
    return changed


def _backfill_saved_playlist_taste(conn: sqlite3.Connection) -> int:
    try:
        from config import app_data_dir
        playlists_path = app_data_dir() / "playlists.json"
        if not playlists_path.exists():
            return 0
        playlists = json.loads(playlists_path.read_text("utf-8"))
    except Exception:
        return 0

    from taste_profile import normalize_artist_key, normalize_genre_key  # noqa: F401

    seen: set[str] = set()
    added = 0
    for playlist in playlists if isinstance(playlists, list) else []:
        if not isinstance(playlist, dict):
            continue
        origin = str(playlist.get("playlist_origin") or "").strip().lower()
        if origin not in {"manual", "album"}:
            continue
        for track in playlist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            track_key = str(track.get("track_key") or track.get("spotify_id") or track.get("isrc") or "").strip()
            if not track_key:
                title = str(track.get("title") or "").strip().lower()
                artist = str(track.get("artist") or "").strip().lower()
                album = str(track.get("album") or "").strip().lower()
                track_key = "||".join([artist, title, album])
            if not track_key or track_key in seen:
                continue
            seen.add(track_key)
            event_id = f"saved-playlist-taste:{track_key}"
            payload = {
                "event_id": event_id,
                "track_key": track_key,
                "title": track.get("title") or "",
                "artist": track.get("artist") or "",
                "album": track.get("album") or "",
                "duration_ms": int(track.get("duration_ms") or 0),
                "source_engine": track.get("source_engine") or track.get("source") or "saved_playlist",
                "source_service": track.get("source_service") or track.get("source") or "saved_playlist",
                "resolved_url": track.get("resolved_url") or track.get("spotify_url") or track.get("url") or "",
                "metadata": track.get("metadata") if isinstance(track.get("metadata"), dict) else dict(track),
                "event_type": "manual_like",
                "created_at": float(track.get("created_at") or time.time()),
                "started_at": float(track.get("created_at") or time.time()),
                "ended_at": float(track.get("created_at") or time.time()),
                "listened_ms": 0,
                "duration_ms": int(track.get("duration_ms") or 0),
                "listened_percent": 0.0,
                "reason": "saved playlist seed",
            }
            try:
                result = process_listening_event(payload)
                if result.get("ok"):
                    added += 1
            except Exception:
                continue
    return added


def backfill_saved_playlist_taste() -> int:
    conn = _get_conn()
    done = conn.execute(
        "SELECT value FROM meta WHERE key = 'saved_playlist_taste_backfill_v1'"
    ).fetchone()
    if done:
        return 0
    count = _backfill_saved_playlist_taste(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('saved_playlist_taste_backfill_v1', ?)",
        (str(time.time()),),
    )
    conn.commit()
    return count


def save_source_alias(alias_key: str, track_key: str, alias_type: str = ""):
    alias_key = (alias_key or "").strip()
    track_key = (track_key or "").strip()
    if not alias_key or not track_key:
        return
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO source_aliases (alias_key, track_key, alias_type, last_updated)
        VALUES (?, ?, ?, ?)
    """, (alias_key, track_key, alias_type, time.time()))
    conn.commit()


def _resolve_source_track_key(conn: sqlite3.Connection, lookup_key: str) -> str:
    lookup_key = (lookup_key or "").strip()
    if not lookup_key:
        return ""
    row = conn.execute("SELECT track_key FROM sources WHERE track_key = ?", (lookup_key,)).fetchone()
    if row:
        return str(row["track_key"])
    alias = conn.execute("SELECT track_key FROM source_aliases WHERE alias_key = ?", (lookup_key,)).fetchone()
    if alias:
        return str(alias["track_key"])
    return ""


def get_resolved_source(track_key: str) -> dict[str, Any] | None:
    conn = _get_conn()
    resolved_key = _resolve_source_track_key(conn, track_key)
    row = conn.execute("SELECT * FROM sources WHERE track_key = ?", (resolved_key or track_key,)).fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get("resolved_url") and is_blacklisted(data["resolved_url"]):
        return None
    if data.get("resolved_url") and is_blacklisted_for_alias(track_key, data["resolved_url"]):
        return None
    return data


def get_resolved_source_for_keys(track_keys: list[str]) -> dict[str, Any] | None:
    conn = _get_conn()
    for track_key in track_keys:
        resolved_key = _resolve_source_track_key(conn, track_key)
        row = conn.execute("SELECT * FROM sources WHERE track_key = ?", (resolved_key or track_key,)).fetchone()
        if row:
            data = dict(row)
            if data.get("resolved_url") and is_blacklisted(data["resolved_url"]):
                continue
            if data.get("resolved_url") and is_blacklisted_for_alias(track_key, data["resolved_url"]):
                continue
            return data
    return None


def delete_resolved_source(track_key: str):
    conn = _get_conn()
    conn.execute("DELETE FROM sources WHERE track_key = ?", (track_key,))
    conn.commit()


def save_album_metadata(album_key: str, data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO albums (album_key, metadata_json, last_updated)
        VALUES (?, ?, ?)
    """, (album_key, json.dumps(data), time.time()))
    conn.commit()


def get_album_metadata(album_key: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT metadata_json FROM albums WHERE album_key = ?", (album_key,)).fetchone()
    if row:
        try:
            data = json.loads(row["metadata_json"])
            # Self-heal corrupted/empty cache entries
            if data and not data.get("tracks"):
                return None
            return data
        except Exception:
            pass
    return None


def save_artist_tour(artist_key: str, data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO artist_tours (artist_key, metadata_json, last_updated)
        VALUES (?, ?, ?)
    """, (artist_key, json.dumps(data), time.time()))
    conn.commit()


def get_artist_tour(artist_key: str, max_age: float | None = None) -> dict | None:
    """Return cached tour data, or None if missing or older than max_age seconds."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT metadata_json, last_updated FROM artist_tours WHERE artist_key = ?",
        (artist_key,),
    ).fetchone()
    if not row:
        return None
    if max_age is not None and (time.time() - (row["last_updated"] or 0)) > max_age:
        return None
    try:
        data = json.loads(row["metadata_json"])
        if isinstance(data, dict):
            last_updated = float(row["last_updated"] or 0)
            data.setdefault("cached_at", last_updated)
            data["_cache_last_updated"] = last_updated
        return data
    except Exception:
        return None


def save_track_credits(credit_key: str, data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO track_credits (credit_key, metadata_json, last_updated)
        VALUES (?, ?, ?)
    """, (credit_key, json.dumps(data), time.time()))
    conn.commit()


def get_track_credits(credit_key: str, max_age: float | None = None) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT metadata_json, last_updated FROM track_credits WHERE credit_key = ?",
        (credit_key,),
    ).fetchone()
    if not row:
        return None
    if max_age is not None and (time.time() - (row["last_updated"] or 0)) > max_age:
        return None
    try:
        return json.loads(row["metadata_json"])
    except Exception:
        return None


def save_track_metadata(track_key: str, data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO tracks (track_key, metadata_json, last_updated)
        VALUES (?, ?, ?)
    """, (track_key, json.dumps(data), time.time()))
    for key in ("spotify_id", "isrc", "musicbrainz_recording_id", "musicbrainz_release_id", "musicbrainz_artist_id", "deezer_id", "tidal_id", "amazon_id", "apple_music_id"):
        value = str(data.get(key) or "").strip()
        if value:
            save_source_alias(f"{key}:{value}", track_key, key)
    conn.commit()


def get_track_metadata(track_key: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT metadata_json FROM tracks WHERE track_key = ?", (track_key,)).fetchone()
    if row:
        try:
            return json.loads(row["metadata_json"])
        except Exception:
            pass
    return None


def _clear_cached_artist_ids_conn(conn: sqlite3.Connection, artist: str | None) -> int:
    changed = 0
    for table, key_col in (("tracks", "track_key"), ("albums", "album_key")):
        if artist:
            prefix = f"{str(artist).strip().lower()}||%"
            rows = conn.execute(
                f"SELECT {key_col} AS k, metadata_json AS j FROM {table} WHERE {key_col} LIKE ?",
                (prefix,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {key_col} AS k, metadata_json AS j FROM {table}"
            ).fetchall()
        for row in rows:
            try:
                data = json.loads(row["j"])
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            dirty = False
            for field in _ARTIST_ID_FIELDS:
                if data.get(field):
                    data[field] = ""
                    dirty = True
            # Album rows embed a tracklist; scrub each track's id too.
            for track in (data.get("tracks") or []):
                if isinstance(track, dict):
                    for field in _ARTIST_ID_FIELDS:
                        if track.get(field):
                            track[field] = ""
                            dirty = True
            if dirty:
                conn.execute(
                    f"UPDATE {table} SET metadata_json = ? WHERE {key_col} = ?",
                    (json.dumps(data), row["k"]),
                )
                changed += 1
    conn.commit()
    return changed


def clear_cached_artist_ids(artist: str | None = None) -> int:
    """Strip cached Spotify/generic artist-id fields from track & album metadata
    so the next lookup re-resolves them from scratch. Use to scrub 'poisoned'
    rows where a wrong/non-Spotify artist id was cached (which would otherwise
    feed the sidebar/tour/credits a bad id). Pass an artist name to limit the
    scrub to that artist (matched on the 'artist||...' key prefix), or None to
    scrub every cached row. Returns the number of rows changed."""
    return _clear_cached_artist_ids_conn(_get_conn(), artist)


def save_album_source(album_key: str, engine: str, resolved_url: str):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO album_sources (album_key, engine, resolved_url, last_updated)
        VALUES (?, ?, ?, ?)
    """, (album_key, engine, resolved_url, time.time()))
    conn.commit()


def get_album_source(album_key: str) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM album_sources WHERE album_key = ?", (album_key,)).fetchone()
    return dict(row) if row else None


def delete_album_source(album_key: str):
    conn = _get_conn()
    conn.execute("DELETE FROM album_sources WHERE album_key = ?", (album_key,))
    conn.commit()


def add_to_blacklist(url: str, reason: str = "", alias_keys: list[str] | None = None):
    if not url: return
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO blacklist (url, reason, last_failed)
        VALUES (?, ?, ?)
    """, (url, reason, time.time()))
    if alias_keys:
        conn.executemany("""
            INSERT OR REPLACE INTO blacklist_aliases (alias_key, url, reason, last_failed)
            VALUES (?, ?, ?, ?)
        """, [
            ((alias_key or "").strip(), url, reason, time.time())
            for alias_key in alias_keys
            if (alias_key or "").strip()
        ])
    conn.commit()


def is_blacklisted(url: str) -> bool:
    if not url: return False
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM blacklist WHERE url = ?", (url,)).fetchone()
    return bool(row)


def is_blacklisted_for_alias(alias_key: str, url: str = "") -> bool:
    alias_key = (alias_key or "").strip()
    if not alias_key:
        return False
    conn = _get_conn()
    if url:
        row = conn.execute(
            "SELECT 1 FROM blacklist_aliases WHERE alias_key = ? AND url = ?",
            (alias_key, url),
        ).fetchone()
        return bool(row)
    row = conn.execute("SELECT 1 FROM blacklist_aliases WHERE alias_key = ?", (alias_key,)).fetchone()
    return bool(row)


def remove_from_blacklist(url: str):
    if not url:
        return
    conn = _get_conn()
    conn.execute("DELETE FROM blacklist WHERE url = ?", (url,))
    conn.execute("DELETE FROM blacklist_aliases WHERE url = ?", (url,))
    conn.commit()


def seed_adult_filter_terms(terms: list[str] | set[str], source: str = "builtin"):
    normalized = sorted({
        str(term).strip().lower()
        for term in terms
        if str(term).strip()
    })
    if not normalized:
        return
    conn = _get_conn()
    now = time.time()
    conn.executemany("""
        INSERT OR IGNORE INTO adult_filter_terms
            (term, kind, match_mode, enabled, source, last_updated)
        VALUES (?, 'adult', 'word', 1, ?, ?)
    """, [(term, source, now) for term in normalized])
    conn.commit()


def get_adult_filter_terms() -> set[str]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT term FROM adult_filter_terms
        WHERE kind = 'adult' AND enabled = 1
    """).fetchall()
    return {
        str(row["term"]).strip().lower()
        for row in rows
        if str(row["term"]).strip()
    }


def save_adult_filter_term(term: str, enabled: bool = True, source: str = "manual"):
    term = (term or "").strip().lower()
    if not term:
        return
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO adult_filter_terms
            (term, kind, match_mode, enabled, source, last_updated)
        VALUES (?, 'adult', 'word', ?, ?, ?)
    """, (term, 1 if enabled else 0, source, time.time()))
    conn.commit()


def _json_load_maybe(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _track_identity_from_metadata(track_key: str, metadata: dict | None = None) -> dict:
    metadata = dict(metadata or {})
    track = get_track_metadata(track_key) or {}
    merged = {**track, **metadata}
    merged.setdefault("track_key", track_key)
    return merged


def _same_day_bounds(ts: float) -> tuple[float, float]:
    tm = time.localtime(ts)
    start = time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday, 0, 0, 0, tm.tm_wday, tm.tm_yday, tm.tm_isdst))
    return start, start + 86400.0


def _normalize_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _extract_metadata_bundle(event: dict, track_key: str) -> dict:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    merged = _track_identity_from_metadata(track_key, metadata)
    for key in ("title", "artist", "album", "source_engine", "source_service", "resolved_url", "duration_ms"):
        value = event.get(key)
        if value not in (None, "") and not merged.get(key):
            merged[key] = value
    return merged


def _track_status_row(track_key: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM track_affinity WHERE track_key = ?", (track_key,)).fetchone()
    return dict(row) if row else None


def _artist_status_row(artist_key: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM artist_affinity WHERE artist_key = ?", (artist_key,)).fetchone()
    return dict(row) if row else None


def _genre_status_row(genre_key: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM genre_affinity WHERE genre_key = ?", (genre_key,)).fetchone()
    return dict(row) if row else None


def _store_status_history(conn: sqlite3.Connection, track_key: str, old_status: str, new_status: str, old_score: float, new_score: float, reason: str = "") -> None:
    conn.execute("""
        INSERT INTO affinity_status_history
            (track_key, old_status, new_status, old_score, new_score, changed_at, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (track_key, old_status, new_status, old_score, new_score, time.time(), reason))


def _update_affinity_row(
    conn: sqlite3.Connection,
    table: str,
    key_col: str,
    key: str,
    name_col: str,
    name: str,
    score_delta: float,
    listened_ms: int,
    event_type: str,
    listened_percent: float,
    status: str | None = None,
    hard_blacklisted: bool = False,
    reason: str = "",
    include_completed: bool = True,
) -> dict:
    now = time.time()
    row = conn.execute(f"SELECT * FROM {table} WHERE {key_col} = ?", (key,)).fetchone()
    data = dict(row) if row else {}
    old_status = data.get("status", "neutral")
    old_score = float(data.get("score") or 0.0)
    new_score = old_score + float(score_delta or 0.0)
    from taste_profile import derive_status

    new_status = status or derive_status(new_score, hard_blacklisted=hard_blacklisted or old_status == "hard_blacklisted")
    if hard_blacklisted:
        new_status = "hard_blacklisted"
    counts = {
        "total_plays": int(data.get("total_plays") or 0),
        "total_skips": int(data.get("total_skips") or 0),
        "total_completed": int(data.get("total_completed") or 0),
        "total_listened_ms": int(data.get("total_listened_ms") or 0) + int(listened_ms or 0),
    }
    et = (event_type or "").lower()
    if et in {"skip", "manual_dislike"}:
        counts["total_skips"] += 1
        data["last_skipped_at"] = now
    elif include_completed and et == "complete":
        counts["total_completed"] += 1
        counts["total_plays"] += 1
    elif et.startswith("manual_") or et in {"play", "complete"}:
        counts["total_plays"] += 1
    if data.get("first_seen_at") is None:
        data["first_seen_at"] = now

    values = {
        key_col: key,
        name_col: name or data.get(name_col, ""),
        "score": new_score,
        "status": new_status,
        "last_listened_at": now if listened_ms or et in {"play", "complete", "manual_like"} else data.get("last_listened_at"),
        "updated_at": now,
    }
    if table == "track_affinity":
        values.update({
            "title": data.get("title") or name or "",
            "artist": data.get("artist") or "",
            "album": data.get("album") or "",
            "total_plays": counts["total_plays"],
            "total_skips": counts["total_skips"],
            "total_completed": counts["total_completed"],
            "total_listened_ms": counts["total_listened_ms"],
            "last_skipped_at": data.get("last_skipped_at"),
            "first_seen_at": data.get("first_seen_at"),
        })
    else:
        values.update({
            "score": new_score,
            "status": new_status,
            "total_plays": counts["total_plays"],
            "total_skips": counts["total_skips"],
            "total_completed": counts["total_completed"],
            "total_listened_ms": counts["total_listened_ms"],
        })
    placeholders = ", ".join([f"{col} = ?" for col in values.keys() if col != key_col])
    params = [values[col] for col in values.keys() if col != key_col] + [key]
    if row:
        conn.execute(f"UPDATE {table} SET {placeholders} WHERE {key_col} = ?", params)
    else:
        insert_cols = ", ".join(values.keys())
        insert_vals = ", ".join(["?"] * len(values))
        conn.execute(f"INSERT INTO {table} ({insert_cols}) VALUES ({insert_vals})", list(values.values()))
    if old_status != new_status or abs(old_score - new_score) > 0.00001:
        _store_status_history(conn, key if table == "track_affinity" else str(data.get(key_col) or key), old_status, new_status, old_score, new_score, reason)
    return get_track_affinity(key) if table == "track_affinity" else (get_artist_affinity(name or key) if table == "artist_affinity" else get_genre_affinity(name or key))


def save_listening_event(event: dict) -> dict:
    event = dict(event or {})
    track_key = (event.get("track_key") or "").strip()
    if not track_key:
        return {"ok": False, "error": "Missing track_key"}
    conn = _get_conn()
    event_id = str(event.get("event_id") or uuid.uuid4())
    existing = conn.execute("SELECT * FROM listening_events WHERE event_id = ?", (event_id,)).fetchone()
    if existing:
        return dict(existing)
    created_at = float(event.get("created_at") or time.time())
    started_at = float(event.get("started_at") or created_at)
    ended_at = float(event.get("ended_at") or created_at)
    listened_ms = int(event.get("listened_ms") or 0)
    duration_ms = int(event.get("duration_ms") or 0)
    listened_percent = float(event.get("listened_percent") or 0.0)
    conn.execute("""
        INSERT INTO listening_events
            (event_id, track_key, title, artist, album, source_engine, source_service, resolved_url,
             started_at, ended_at, listened_ms, duration_ms, listened_percent, event_type, reason,
             metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        track_key,
        event.get("title", ""),
        event.get("artist", ""),
        event.get("album", ""),
        event.get("source_engine", ""),
        event.get("source_service", ""),
        event.get("resolved_url", ""),
        started_at,
        ended_at,
        listened_ms,
        duration_ms,
        listened_percent,
        str(event.get("event_type") or "play"),
        event.get("reason", ""),
        json.dumps(event.get("metadata") if isinstance(event.get("metadata"), dict) else {}),
        created_at,
    ))
    conn.commit()
    return dict(conn.execute("SELECT * FROM listening_events WHERE event_id = ?", (event_id,)).fetchone())


def _count_same_day_completions(conn: sqlite3.Connection, track_key: str, event_timestamp: float) -> int:
    start, end = _same_day_bounds(event_timestamp)
    row = conn.execute("""
        SELECT COUNT(*) AS c FROM listening_events
        WHERE track_key = ? AND event_type = 'complete' AND started_at >= ? AND started_at < ?
    """, (track_key, start, end)).fetchone()
    return int(row["c"] or 0) if row else 0


def update_track_affinity(event: dict) -> dict:
    conn = _get_conn()
    track_key = (event.get("track_key") or "").strip()
    if not track_key:
        return {}
    metadata = _extract_metadata_bundle(event, track_key)
    artist = (metadata.get("artist") or event.get("artist") or "").strip()
    title = (metadata.get("title") or event.get("title") or "").strip()
    album = (metadata.get("album") or event.get("album") or "").strip()
    listened_ms = int(event.get("listened_ms") or 0)
    listened_percent = float(event.get("listened_percent") or 0.0)
    event_type = str(event.get("event_type") or "play").strip().lower()
    row = conn.execute("SELECT * FROM track_affinity WHERE track_key = ?", (track_key,)).fetchone()
    current = dict(row) if row else {}
    old_status = current.get("status", "neutral")
    old_score = float(current.get("score") or 0.0)
    score_delta = 0.0
    hard_blacklisted = False
    reason = str(event.get("reason") or "")
    from taste_profile import calculate_score_delta, derive_status
    if event_type == "manual_like":
        score_delta = 20.0
    elif event_type == "manual_dislike":
        score_delta = -20.0
    elif event_type == "manual_remove_taste_profile":
        score_delta = -old_score
    elif event_type == "manual_hard_blacklist":
        hard_blacklisted = True
        score_delta = -old_score
    elif event_type == "manual_remove_hard_blacklist":
        score_delta = 0.0
    else:
        score_delta = calculate_score_delta(event_type, listened_percent)
        if event_type == "complete":
            repeat_count = _count_same_day_completions(conn, track_key, float(event.get("started_at") or event.get("created_at") or time.time()))
            if repeat_count:
                score_delta += 2.0
    preserve_hard = old_status == "hard_blacklisted" and event_type not in {"manual_remove_hard_blacklist", "manual_like"}
    if row:
        score = old_score + float(score_delta)
        status = "hard_blacklisted" if hard_blacklisted or preserve_hard else derive_status(score)
        total_plays = int(current.get("total_plays") or 0)
        total_skips = int(current.get("total_skips") or 0)
        total_completed = int(current.get("total_completed") or 0)
        total_listened_ms = int(current.get("total_listened_ms") or 0) + listened_ms
        if event_type in {"skip", "manual_dislike"}:
            total_skips += 1
            current["last_skipped_at"] = time.time()
        elif event_type not in {"manual_remove_taste_profile", "manual_remove_hard_blacklist", "manual_hard_blacklist"}:
            total_plays += 1
        if event_type == "complete":
            total_completed += 1
        conn.execute("""
            UPDATE track_affinity
            SET title = ?, artist = ?, album = ?, score = ?, status = ?, total_plays = ?, total_skips = ?,
                total_completed = ?, total_listened_ms = ?, last_listened_at = ?, last_skipped_at = ?,
                updated_at = ?
            WHERE track_key = ?
        """, (
            title or current.get("title", ""),
            artist or current.get("artist", ""),
            album or current.get("album", ""),
            score,
            status,
            total_plays,
            total_skips,
            total_completed,
            total_listened_ms,
            float(event.get("ended_at") or event.get("created_at") or time.time()),
            current.get("last_skipped_at"),
            time.time(),
            track_key,
        ))
        if old_status != status or abs(old_score - score) > 0.00001:
            _store_status_history(conn, track_key, old_status, status, old_score, score, reason)
    else:
        score = float(score_delta)
        status = "hard_blacklisted" if hard_blacklisted else derive_status(score)
        conn.execute("""
            INSERT INTO track_affinity
                (track_key, title, artist, album, score, status, total_plays, total_skips, total_completed,
                 total_listened_ms, last_listened_at, last_skipped_at, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            track_key,
            title,
            artist,
            album,
            score,
            status,
            1 if event_type not in {"skip", "manual_dislike", "manual_hard_blacklist"} else 0,
            1 if event_type in {"skip", "manual_dislike"} else 0,
            1 if event_type == "complete" else 0,
            listened_ms,
            float(event.get("ended_at") or event.get("created_at") or time.time()),
            float(event.get("ended_at") or event.get("created_at") or time.time()) if event_type in {"skip", "manual_dislike"} else None,
            float(event.get("created_at") or time.time()),
            time.time(),
        ))
        _store_status_history(conn, track_key, None, status, 0.0, score, reason)
    conn.commit()
    return get_track_affinity(track_key) or {}


def update_artist_affinity(event: dict) -> dict:
    conn = _get_conn()
    metadata = _extract_metadata_bundle(event, (event.get("track_key") or "").strip())
    artist = (event.get("artist") or metadata.get("artist") or "").strip()
    if not artist:
        return {}
    from taste_profile import calculate_score_delta, derive_status, normalize_artist_key
    event_type = str(event.get("event_type") or "play").strip().lower()
    listened_percent = float(event.get("listened_percent") or 0.0)
    key = normalize_artist_key(artist)
    row = conn.execute("SELECT * FROM artist_affinity WHERE artist_key = ?", (key,)).fetchone()
    current = dict(row) if row else {}
    if event_type in {"manual_hard_blacklist", "manual_remove_hard_blacklist"}:
        score_delta = 0.0
    elif event_type == "manual_remove_taste_profile":
        score_delta = -float(current.get("score") or 0.0)
    else:
        score_delta = 20.0 if event_type == "manual_like" else -20.0 if event_type == "manual_dislike" else calculate_score_delta(event_type, listened_percent)
    score = float(current.get("score") or 0.0) + float(score_delta)
    status = "hard_blacklisted" if current.get("status") == "hard_blacklisted" else derive_status(score)
    total_plays = int(current.get("total_plays") or 0) + (0 if event_type in {"skip", "manual_dislike", "manual_remove_taste_profile", "manual_remove_hard_blacklist", "manual_hard_blacklist"} else 1)
    total_skips = int(current.get("total_skips") or 0) + (1 if event_type in {"skip", "manual_dislike"} else 0)
    total_completed = int(current.get("total_completed") or 0) + (1 if event_type == "complete" else 0)
    total_listened_ms = int(current.get("total_listened_ms") or 0) + int(event.get("listened_ms") or 0)
    if row:
        conn.execute("""
            UPDATE artist_affinity
            SET artist_name = ?, score = ?, status = ?, total_plays = ?, total_skips = ?, total_completed = ?,
                total_listened_ms = ?, last_listened_at = ?, updated_at = ?
            WHERE artist_key = ?
        """, (artist, score, status, total_plays, total_skips, total_completed, total_listened_ms, time.time(), time.time(), key))
    else:
        conn.execute("""
            INSERT INTO artist_affinity
                (artist_key, artist_name, score, status, total_plays, total_skips, total_completed,
                 total_listened_ms, last_listened_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (key, artist, score, status, total_plays, total_skips, total_completed, total_listened_ms, time.time(), time.time()))
    conn.commit()
    return get_artist_affinity(artist) or {}


def update_genre_affinity(event: dict) -> dict:
    conn = _get_conn()
    metadata = _extract_metadata_bundle(event, (event.get("track_key") or "").strip())
    from taste_profile import calculate_score_delta, normalize_genre_key, extract_genres_from_metadata
    genres = extract_genres_from_metadata(metadata)
    if not genres:
        return {}
    event_type = str(event.get("event_type") or "play").strip().lower()
    listened_percent = float(event.get("listened_percent") or 0.0)
    no_count_events = {"manual_remove_taste_profile", "manual_remove_hard_blacklist", "manual_hard_blacklist"}
    if event_type in {"manual_hard_blacklist", "manual_remove_hard_blacklist"}:
        score_delta = 0.0
    else:
        score_delta = 20.0 if event_type == "manual_like" else -20.0 if event_type == "manual_dislike" else calculate_score_delta(event_type, listened_percent)
    for genre in genres:
        key = normalize_genre_key(genre)
        row = conn.execute("SELECT * FROM genre_affinity WHERE genre_key = ?", (key,)).fetchone()
        current = dict(row) if row else {}
        effective_delta = -float(current.get("score") or 0.0) if event_type == "manual_remove_taste_profile" else float(score_delta)
        score = float(current.get("score") or 0.0) + float(effective_delta)
        total_plays = int(current.get("total_plays") or 0) + (0 if event_type in {"skip", "manual_dislike"} | no_count_events else 1)
        total_skips = int(current.get("total_skips") or 0) + (1 if event_type in {"skip", "manual_dislike"} else 0)
        total_completed = int(current.get("total_completed") or 0) + (1 if event_type == "complete" else 0)
        total_listened_ms = int(current.get("total_listened_ms") or 0) + int(event.get("listened_ms") or 0)
        if row:
            conn.execute("""
                UPDATE genre_affinity
                SET genre_name = ?, score = ?, total_plays = ?, total_skips = ?, total_completed = ?,
                    total_listened_ms = ?, updated_at = ?
                WHERE genre_key = ?
            """, (genre, score, total_plays, total_skips, total_completed, total_listened_ms, time.time(), key))
        else:
            conn.execute("""
                INSERT INTO genre_affinity
                    (genre_key, genre_name, score, total_plays, total_skips, total_completed, total_listened_ms, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, genre, score, total_plays, total_skips, total_completed, total_listened_ms, time.time()))
    conn.commit()
    return get_genre_affinity(genres[0]) or {}


def process_listening_event(event: dict) -> dict:
    event = dict(event or {})
    track_key = (event.get("track_key") or "").strip()
    if not track_key:
        return {"ok": False, "error": "Missing track_key"}
    event_id = str(event.get("event_id") or uuid.uuid4())
    event["event_id"] = event_id
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM listening_events WHERE event_id = ?", (event_id,)).fetchone()
    if existing:
        return {
            "ok": True,
            "duplicate": True,
            "event": dict(existing),
            "track_affinity": get_track_affinity(track_key) or {},
            "artist_affinity": get_artist_affinity(event.get("artist") or "") or {},
            "genre_affinity": {},
        }
    event["track_key"] = track_key
    saved = save_listening_event(event)
    if not saved or saved.get("ok") is False:
        return saved
    affinity = update_track_affinity({**event, "created_at": saved.get("created_at"), "event_id": saved.get("event_id")})
    artist_aff = update_artist_affinity(event)
    genre_aff = update_genre_affinity(event)
    return {
        "ok": True,
        "event": saved,
        "track_affinity": affinity,
        "artist_affinity": artist_aff,
        "genre_affinity": genre_aff,
    }


def get_track_affinity(track_key: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM track_affinity WHERE track_key = ?", ((track_key or "").strip(),)).fetchone()
    return dict(row) if row else None


def get_artist_affinity(artist_name: str) -> dict | None:
    from taste_profile import normalize_artist_key
    key = normalize_artist_key(artist_name)
    row = _get_conn().execute("SELECT * FROM artist_affinity WHERE artist_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def get_genre_affinity(genre_name: str) -> dict | None:
    from taste_profile import normalize_genre_key
    key = normalize_genre_key(genre_name)
    row = _get_conn().execute("SELECT * FROM genre_affinity WHERE genre_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def _affinity_tracks(status: str, limit: int = 100) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT * FROM track_affinity WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
        (status, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_soft_blacklisted_tracks(limit: int = 100) -> list[dict]:
    return _affinity_tracks("soft_blacklisted", limit)


def get_hard_blacklisted_tracks(limit: int = 100) -> list[dict]:
    return _affinity_tracks("hard_blacklisted", limit)


def get_liked_tracks(limit: int = 100) -> list[dict]:
    return _affinity_tracks("liked", limit)


def get_recently_recovered_tracks(limit: int = 50) -> list[dict]:
    rows = _get_conn().execute("""
        SELECT * FROM affinity_status_history
        WHERE old_status = 'soft_blacklisted' AND new_status IN ('neutral', 'liked')
        ORDER BY changed_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    out = []
    for row in rows:
        affinity = get_track_affinity(row["track_key"]) or {}
        if affinity:
            out.append(affinity)
    return out


def get_listened_time(track_key: str | None, artist: str | None, period: str) -> dict:
    conn = _get_conn()
    now = time.time()
    period = (period or "all").lower()
    if period == "today":
        start, end = _same_day_bounds(now)
    elif period == "week":
        start = now - 7 * 86400.0
        end = now
    elif period == "month":
        start = now - 30 * 86400.0
        end = now
    else:
        start = 0.0
        end = now
    clauses = ["started_at >= ?", "started_at <= ?"]
    params: list[Any] = [start, end]
    if track_key:
        clauses.append("track_key = ?")
        params.append(track_key)
    if artist:
        clauses.append("artist = ?")
        params.append(artist)
    where = " AND ".join(clauses)
    row = conn.execute(
        f"SELECT COALESCE(SUM(listened_ms), 0) AS listened_ms, COALESCE(SUM(duration_ms), 0) AS duration_ms, COUNT(*) AS events FROM listening_events WHERE {where}",
        params,
    ).fetchone()
    return {
        "track_key": track_key,
        "artist": artist,
        "period": period,
        "listened_ms": int(row["listened_ms"] or 0) if row else 0,
        "duration_ms": int(row["duration_ms"] or 0) if row else 0,
        "events": int(row["events"] or 0) if row else 0,
    }


def get_taste_score_for_track(track_key: str) -> float:
    row = get_track_affinity(track_key or "")
    return float(row.get("score") or 0.0) if row else 0.0


def get_taste_score_for_artist(artist_name: str) -> float:
    row = get_artist_affinity(artist_name or "")
    return float(row.get("score") or 0.0) if row else 0.0


def is_track_taste_hard_blacklisted(track_key: str) -> bool:
    row = get_track_affinity(track_key or "")
    return bool(row and row.get("status") == "hard_blacklisted")


def is_track_taste_soft_blacklisted(track_key: str) -> bool:
    row = get_track_affinity(track_key or "")
    return bool(row and row.get("status") == "soft_blacklisted")


def get_known_tracks(limit: int = 2000) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT track_key, metadata_json, last_updated FROM tracks ORDER BY last_updated DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for row in rows:
        metadata = _json_load_maybe(row["metadata_json"])
        metadata["track_key"] = row["track_key"]
        metadata["last_updated"] = row["last_updated"]
        out.append(metadata)
    return out


def save_playlist_recommendation_session(session_id: str, playlist_id: str) -> None:
    now = time.time()
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO playlist_recommendation_sessions
            (session_id, playlist_id, created_at, last_used_at)
        VALUES (?, ?, COALESCE((SELECT created_at FROM playlist_recommendation_sessions WHERE session_id = ?), ?), ?)
    """, (session_id, playlist_id, session_id, now, now))
    conn.commit()


def touch_playlist_recommendation_session(session_id: str, playlist_id: str = "") -> None:
    conn = _get_conn()
    conn.execute("""
        UPDATE playlist_recommendation_sessions
        SET last_used_at = ?, playlist_id = COALESCE(NULLIF(?, ''), playlist_id)
        WHERE session_id = ?
    """, (time.time(), playlist_id, session_id))
    conn.commit()


def get_playlist_recommendation_session(session_id: str) -> dict | None:
    row = _get_conn().execute("SELECT * FROM playlist_recommendation_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def record_playlist_recommendation_feedback(playlist_id: str, track_key: str, action: str, session_id: str | None = None) -> None:
    conn = _get_conn()
    conn.execute("""
        INSERT INTO playlist_recommendation_feedback
            (playlist_id, track_key, action, session_id, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (playlist_id, track_key, action, session_id, time.time()))
    conn.commit()


def get_playlist_recommendation_feedback(playlist_id: str, actions: list[str]) -> set[str]:
    if not actions:
        return set()
    q = ",".join(["?"] * len(actions))
    rows = _get_conn().execute(
        f"SELECT track_key FROM playlist_recommendation_feedback WHERE playlist_id = ? AND action IN ({q})",
        [playlist_id, *actions],
    ).fetchall()
    return {str(row["track_key"]) for row in rows if row["track_key"]}


def get_playlist_recommendation_session_shown(session_id: str) -> set[str]:
    rows = _get_conn().execute(
        "SELECT track_key FROM playlist_recommendation_feedback WHERE session_id = ? AND action = 'shown'",
        (session_id,),
    ).fetchall()
    return {str(row["track_key"]) for row in rows if row["track_key"]}


def save_playlist_recommendation_cache(item: dict, playlist_id: str, score: float, reason: str, ttl_s: float = 86400.0) -> None:
    track_key = (item.get("track_key") or "").strip()
    if not track_key:
        return
    conn = _get_conn()
    now = time.time()
    conn.execute("""
        INSERT OR REPLACE INTO playlist_recommendation_cache
            (playlist_id, track_key, title, artist, album, artwork_url, score, reason, candidate_json, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        playlist_id,
        track_key,
        item.get("title", ""),
        item.get("artist", ""),
        item.get("album", ""),
        item.get("artwork_url", ""),
        float(score or 0.0),
        reason,
        json.dumps(item),
        now,
        now + float(ttl_s),
    ))
    conn.commit()


def get_playlist_recommendation_cache(playlist_id: str) -> list[dict]:
    rows = _get_conn().execute("""
        SELECT * FROM playlist_recommendation_cache
        WHERE playlist_id = ? AND expires_at >= ?
        ORDER BY score DESC, created_at DESC
    """, (playlist_id, time.time())).fetchall()
    return [dict(row) for row in rows]
