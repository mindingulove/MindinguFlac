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
        CREATE TABLE IF NOT EXISTS blacklist (
            url TEXT PRIMARY KEY,
            reason TEXT,
            last_failed REAL
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
    conn.commit()


def save_resolved_source(track_key: str, engine: str, service: str, quality: str, resolved_url: str):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO sources (track_key, engine, service, quality, resolved_url, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (track_key, engine, service, quality, resolved_url, time.time()))
    conn.commit()


def get_resolved_source(track_key: str) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sources WHERE track_key = ?", (track_key,)).fetchone()
    return dict(row) if row else None


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


def save_track_metadata(track_key: str, data: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO tracks (track_key, metadata_json, last_updated)
        VALUES (?, ?, ?)
    """, (track_key, json.dumps(data), time.time()))
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


def add_to_blacklist(url: str, reason: str = ""):
    if not url: return
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO blacklist (url, reason, last_failed)
        VALUES (?, ?, ?)
    """, (url, reason, time.time()))
    conn.commit()


def is_blacklisted(url: str) -> bool:
    if not url: return False
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM blacklist WHERE url = ?", (url,)).fetchone()
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
