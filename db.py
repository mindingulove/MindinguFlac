from __future__ import annotations

import json
import sqlite3
import threading
import time
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
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
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
    except Exception:
        pass


def save_resolved_source(track_key: str, engine: str, service: str, quality: str, resolved_url: str):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO sources (track_key, engine, service, quality, resolved_url, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (track_key, engine, service, quality, resolved_url, time.time()))
    conn.commit()


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
            return json.loads(row["metadata_json"])
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
    conn = _get_conn()
    conn.execute("DELETE FROM blacklist WHERE url = ?", (url,))
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
