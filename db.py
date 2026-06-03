from __future__ import annotations

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
