"""Live artist tour/concert lookup via Duck.ai (GPT-5 + Web Search).

Separate from `ai_reranker.py` (which keeps doing torrent reranking) — this
module only fetches concert listings. It drives the same long-running headed
Duck.ai browser worker through `duck_proxy.send_chat`, but forces GPT-5 with the
"Web Search" tool enabled so answers are sourced from the live web (Songkick,
Bandsintown, venue pages) rather than hallucinated.

Public API:
  - fetch_tour(artist_name) -> {"artist", "events": [...], "source"} or {}
"""
from __future__ import annotations

import json
import re
import time

_MODEL = "GPT-5"
_REPLY_TIMEOUT_S = 170.0
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _prompt(artist_name: str) -> str:
    return (
        f"Use Web Search to find live concert / tour dates for the musician \"{artist_name}\". "
        "Check sources such as Songkick, Bandsintown, official artist pages and venue listings. "
        "Include upcoming shows (and a few recent past ones if available), ordered by date. "
        "Respond with ONLY a JSON array and nothing else — no prose, no citations, no markdown. "
        "Each array item must be an object with exactly these keys:\n"
        '{"artist": string, "status": "upcoming" | "past", "date": "YYYY-MM-DD", '
        '"time": "HH:MM" or null, "place": "City", '
        '"location": "Venue, City, Country", "venue": string, "country": string, '
        '"price": string (estimate or "TBD"), "info": string (festival/notes or empty), '
        '"url": string (ticket or source link)}\n'
        "If there are no known concerts, return []. Return only the JSON array."
    )


def _extract_json_array(text: str) -> list:
    """Pull the first top-level JSON array out of a possibly-noisy reply."""
    raw = str(text or "")
    start = raw.find("[")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    chunk = raw[start:i + 1]
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        break
        start = raw.find("[", start + 1)
    return []


def _normalize(item: dict, artist_name: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    date = str(item.get("date") or "").strip()
    month = day = ""
    iso = ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date)
    if m:
        iso = m.group(0)
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            month = _MONTHS[mon]
        day = str(int(m.group(3)))
    place = str(item.get("place") or item.get("city") or "").strip()
    location = str(item.get("location") or "").strip()
    venue = str(item.get("venue") or "").strip()
    if not venue and location:
        venue = location.split(",")[0].strip()
    time_val = item.get("time")
    time_str = "" if time_val in (None, "null", "TBD") else str(time_val).strip()
    if not place and not location and not iso:
        return None
    return {
        "artist": str(item.get("artist") or artist_name or "").strip() or artist_name,
        "status": str(item.get("status") or "").strip().lower() or "upcoming",
        "date": iso or date,
        "month": month,
        "day": day,
        "time": time_str,
        "place": place or (location.split(",")[0].strip() if location else ""),
        "city": place,
        "location": location,
        "venue": venue,
        "country": str(item.get("country") or "").strip(),
        "price": str(item.get("price") or "").strip(),
        "info": str(item.get("info") or "").strip(),
        "url": str(item.get("url") or "").strip(),
    }


def _sort_key(ev: dict):
    # Upcoming first (ascending date), then past (descending date).
    iso = ev.get("date") or ""
    is_upcoming = ev.get("status") != "past"
    return (0 if is_upcoming else 1, iso if is_upcoming else _invert_date(iso))


def _invert_date(iso: str) -> str:
    # Cheap descending sort for past events without parsing.
    try:
        y, m, d = iso.split("-")
        return f"{9999 - int(y):04d}-{99 - int(m):02d}-{99 - int(d):02d}"
    except Exception:
        return iso


def fetch_tour(artist_name: str) -> dict:
    artist_name = str(artist_name or "").strip()
    if not artist_name:
        return {}
    try:
        import duck_proxy
    except Exception:
        return {}

    status = duck_proxy.fetch_status()
    if not status.get("vqd_hash_1"):
        return {"artist": artist_name, "events": [], "source": "", "error": status.get("error", "advisor unavailable")}

    messages = [{"role": "user", "content": _prompt(artist_name)}]
    started = time.time()
    res = duck_proxy.send_chat(
        token=status.get("vqd_hash_1", ""),
        messages=messages,
        model="gpt-5",
        ensure_model=_MODEL,
        web_search=True,
        reply_timeout=_REPLY_TIMEOUT_S,
    )
    if not res.get("ok"):
        return {"artist": artist_name, "events": [], "source": "", "error": res.get("error", "no reply")}

    raw = res.get("text", "") or ""
    events = []
    for item in _extract_json_array(raw):
        normalized = _normalize(item, artist_name)
        if normalized:
            events.append(normalized)
    events.sort(key=_sort_key)

    return {
        "artist": artist_name,
        "events": events,
        "source": "Duck.ai · GPT-5 Web Search",
        "elapsed": round(time.time() - started, 1),
    }
