from __future__ import annotations

import re
import time
import unicodedata


_REPEAT_CACHE: dict[str, tuple[int, int, int]] = {}


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def normalize_artist_key(artist_name: str) -> str:
    return _normalize_text(artist_name)


def normalize_genre_key(genre_name: str) -> str:
    return _normalize_text(genre_name)


def calculate_score_delta(event_type: str, listened_percent: float, manual_weight: float = 0) -> float:
    event_type = (event_type or "").strip().lower()
    if manual_weight:
        return float(manual_weight)
    if event_type == "manual_like":
        return 20.0
    if event_type == "manual_dislike":
        return -20.0
    pct = float(listened_percent or 0.0)
    if pct < 5:
        return -5.0
    if pct < 30:
        return -2.0
    if pct < 70:
        return 1.0
    if pct < 95:
        return 4.0
    return 6.0


def derive_status(score: float, hard_blacklisted: bool = False) -> str:
    if hard_blacklisted:
        return "hard_blacklisted"
    if score >= 15:
        return "liked"
    if score <= -15:
        return "soft_blacklisted"
    return "neutral"


def extract_genres_from_metadata(metadata: dict) -> list[str]:
    if not isinstance(metadata, dict):
        return []

    values: list[str] = []
    for key in ("genres", "genre", "primary_genre", "secondary_genres", "style", "styles"):
        raw = metadata.get(key)
        if isinstance(raw, str):
            values.extend(re.split(r"[,/;|]", raw))
        elif isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, str):
                    values.extend(re.split(r"[,/;|]", item))

    for nested_key in ("artists", "album", "metadata"):
        nested = metadata.get(nested_key)
        if isinstance(nested, dict):
            values.extend(extract_genres_from_metadata(nested))
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    values.extend(extract_genres_from_metadata(item))

    seen = set()
    out: list[str] = []
    for value in values:
        key = normalize_genre_key(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value.strip())
    return out


def calculate_repeat_bonus(track_key: str, event_timestamp: float) -> float:
    # The persisted repeat detection happens in db.py. This helper keeps a small
    # in-process cache so call sites can still ask for the repeat bump directly.
    key = normalize_artist_key(track_key)
    tm = time.localtime(float(event_timestamp or 0.0))
    day = (tm.tm_year, tm.tm_yday, tm.tm_mday)
    last = _REPEAT_CACHE.get(key)
    _REPEAT_CACHE[key] = day
    return 2.0 if last == day else 0.0
