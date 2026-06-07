#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hypebot_tour


TOUR_CACHE_TTL = 12 * 3600


def iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(timestamp)))


def should_backfill(data: dict) -> bool:
    source = str(data.get("source") or "")
    return source == "Hypebot/Bandsintown"


def existing_url(data: dict) -> str:
    for key in ("hypebot_url", "artist_url", "tour_url", "url"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    for page in data.get("pages") or []:
        value = str((page or {}).get("url") or "").strip()
        if value:
            return value
    return ""


def clear_url_aliases(data: dict) -> None:
    for key in ("hypebot_url", "artist_url", "tour_url", "url"):
        data.pop(key, None)


def find_hypebot_url(artist: str, timeout: float) -> str:
    matches = hypebot_tour.search_artist_pages(artist=artist, limit=1, timeout=timeout)
    if not matches:
        return ""
    return str((matches[0] or {}).get("url") or "").strip()


def stamp(data: dict, row_last_updated: float) -> None:
    cached_at = float(data.get("cached_at") or row_last_updated or time.time())
    ttl = float(data.get("cache_ttl_seconds") or TOUR_CACHE_TTL)
    expires_at = cached_at + ttl
    data["cached_at"] = cached_at
    data["cached_at_iso"] = iso(cached_at)
    data["cache_ttl_seconds"] = ttl
    data["expires_at"] = expires_at
    data["expires_at_iso"] = iso(expires_at)
    data["refresh_needed"] = (time.time() - cached_at) > ttl
    data["stale"] = data["refresh_needed"]


def update_database(path: Path, timeout: float = 12.0) -> tuple[int, int, int]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT artist_key, metadata_json, last_updated FROM artist_tours ORDER BY last_updated DESC"
    ).fetchall()
    updated = 0
    skipped = 0
    errors = 0
    for row in rows:
        try:
            data = json.loads(row["metadata_json"] or "{}")
            if not isinstance(data, dict):
                skipped += 1
                continue
            stamp(data, float(row["last_updated"] or 0))
            url = existing_url(data)
            if should_backfill(data):
                artist = str(data.get("artist") or row["artist_key"] or "").strip()
                if artist:
                    resolved_url = find_hypebot_url(artist, timeout=timeout)
                    if resolved_url:
                        url = resolved_url
                    else:
                        clear_url_aliases(data)
                        url = ""
            if url:
                data["url"] = url
                data["hypebot_url"] = url
                data["artist_url"] = url
                data["tour_url"] = url
            else:
                skipped += 1
            conn.execute(
                "UPDATE artist_tours SET metadata_json = ? WHERE artist_key = ?",
                (json.dumps(data, ensure_ascii=False), row["artist_key"]),
            )
            updated += 1
        except Exception as exc:
            errors += 1
            print(f"[backfill] {path}: {row['artist_key']} failed: {exc}")
    conn.commit()
    conn.close()
    return updated, skipped, errors


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: backfill_hypebot_tour_urls.py DB_PATH [DB_PATH ...]")
        return 2
    exit_code = 0
    for raw_path in argv:
        path = Path(raw_path).expanduser()
        if not path.exists():
            print(f"[backfill] missing: {path}")
            exit_code = 1
            continue
        updated, skipped, errors = update_database(path)
        print(f"[backfill] {path}: updated={updated} skipped={skipped} errors={errors}")
        if errors:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
