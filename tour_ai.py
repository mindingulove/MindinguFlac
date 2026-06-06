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
import os
import re
import time

_MODEL = "GPT-5"
_REPLY_TIMEOUT_S = 100.0
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _selected_provider(ai_provider: str) -> str:
    return (ai_provider or os.environ.get("MINDINGUFLAC_AI_RERANK_PROVIDER", "duckai")).strip().lower()


def _prompt(artist_name: str) -> str:
    return (
        f"Search for live concert / tour dates for \"{artist_name}\" in 2026. "
        "Check Songkick, Bandsintown, and venue listings. "
        "Respond with ONLY a JSON array and nothing else. "
        "If no dates are found, return []. "
        "Format each entry as: "
        '{"artist": string, "status": "upcoming" | "past", "date": "YYYY-MM-DD", '
        '"time": "HH:MM", "place": "City", "location": "Venue, City, Country", '
        '"venue": string, "country": string, "price": "TBD", "info": "", "url": "link"}.'
    )

def _extract_json_array(text: str) -> list:
    """Pull JSON array or attempt to parse prose into array-like structure."""
    raw = str(text or "").strip()
    
    # 1. Try to find JSON inside markdown blocks
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    # 2. Try strict bracket finding
    start = raw.find("[")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == "[": depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw[start:i + 1])
                        if isinstance(parsed, list): return parsed
                    except Exception: break
        start = raw.find("[", start + 1)

    # 2b. Accept a JSON object that carries an events/results payload.
    start = raw.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw[start:i + 1])
                        if isinstance(parsed, dict):
                            for key in ("events", "results", "data"):
                                value = parsed.get(key)
                                if isinstance(value, list):
                                    return value
                    except Exception:
                        break
        start = raw.find("{", start + 1)

    # 3. LAZY PARSER: If Gemini gave us a list of dates in prose
    # Matches patterns like "Aug 14: Dinard, France (Parvis de Port-Breton)"
    # or "2026-08-14 - Dinard"
    lazy_events = []
    # Simplified regex for dates + city + venue
    lines = raw.split("\n")
    current_year = "2026" # Default from prompt
    
    date_pattern = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", re.I)
    iso_pattern = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        found_date = ""
        # Try ISO
        im = iso_pattern.search(line)
        if im:
            found_date = im.group(0)
        else:
            # Try Month Day
            dm = date_pattern.search(line)
            if dm:
                month_str = dm.group(1).capitalize()[:3]
                try:
                    month_idx = _MONTHS.index(month_str)
                    day = int(dm.group(2))
                    found_date = f"{current_year}-{month_idx:02d}-{day:02d}"
                except Exception: pass
        
        if found_date:
            # Try to extract city/venue: "Date: City, Country (Venue)" or "Date - City - Venue"
            content = line.split(found_date)[-1].strip(": -–—")
            # Heuristic: split by commas or parentheses
            parts = re.split(r"[,()]", content)
            city = parts[0].strip() if len(parts) > 0 else ""
            venue = parts[-1].strip(" )") if len(parts) > 1 else ""
            if city or venue:
                parts = [p.strip() for p in re.split(r"[,()]", content) if p.strip()]
                lazy_events.append({
                    "date": found_date,
                    "place": city,
                    "venue": venue or city,
                    "location": content.strip(),
                    "state": parts[1] if len(parts) >= 3 else "",
                    "country": parts[-1] if len(parts) >= 2 else "",
                    "status": "upcoming",
                    "artist": "", # will be filled by caller
                })
    
    return lazy_events


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
    state = str(item.get("state") or item.get("region") or "").strip()
    country = str(item.get("country") or "").strip()
    if not venue and location:
        venue = location.split(",")[0].strip()
    if not place and location:
        parts = [p.strip() for p in location.split(",") if p.strip()]
        venueish = re.compile(r"(arena|stadium|theatre|theater|park|hall|club|center|centre|dome|auditorium|festival|pavilion|ground|amphitheater|amphitheatre)", re.I)
        if len(parts) >= 3:
            place = parts[1] if venueish.search(parts[0]) else parts[0]
        elif len(parts) == 2:
            place = parts[1] if venueish.search(parts[0]) else parts[0]
        elif len(parts) == 1:
            place = parts[0]
    if not state and location:
        parts = [p.strip() for p in location.split(",") if p.strip()]
        if len(parts) >= 3:
            state = parts[1]
        elif len(parts) == 2:
            state = ""
            
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
        "state": state,
        "region": state,
        "location": location,
        "venue": venue,
        "country": country or (location.split(",")[-1].strip() if location and "," in location else ""),
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


def fetch_tour(artist_name: str, ai_provider: str = "duckai", gemini_model: str = "gemini-1.5-flash") -> dict:
    artist_name = str(artist_name or "").strip()
    if not artist_name:
        return {}
        
    # Prefer the saved/app-selected provider. Environment override is only a fallback.
    provider = _selected_provider(ai_provider)
    
    def try_duck():
        try:
            import duck_proxy
            status = duck_proxy.fetch_status()
            if not status.get("vqd_hash_1"):
                return {"error": status.get("error", "advisor unavailable")}

            messages = [{"role": "user", "content": _prompt(artist_name)}]
            res = duck_proxy.send_chat(
                token=status.get("vqd_hash_1", ""),
                messages=messages,
                model="gpt-5",
                ensure_model=_MODEL,
                web_search=True,
                reply_timeout=_REPLY_TIMEOUT_S,
            )
            return res
        except Exception as e:
            return {"error": str(e)}

    def try_gemini():
        try:
            import gemini_proxy
            # Gemini always uses web search by default if needed, or we can prepend instructions
            prompt = _prompt(artist_name)
            # Add explicit instruction for Gemini to use its search capabilities
            full_prompt = f"Use your Google Search capabilities to find live concert dates.\n\n{prompt}"
            return gemini_proxy.send_chat(prompt=full_prompt, ensure_model=gemini_model, timeout_s=_REPLY_TIMEOUT_S)
        except Exception as e:
            return {"error": str(e)}

    started = time.time()
    res = {"ok": False}
    source_name = ""

    if provider in {"duck", "duck_chat", "duckai"}:
        res = try_duck()
        source_name = "Duck.ai · GPT-5 Web Search"
        # Fallback if Duck.ai fails or rate limited
        if not res.get("ok") or res.get("rate_limited"):
            print("[tour_ai] Duck.ai limit reached or failed, falling back to Gemini")
            res = try_gemini()
            source_name = f"Gemini ({gemini_model}) · Google Search"
    elif provider == "gemini":
        res = try_gemini()
        source_name = f"Gemini ({gemini_model}) · Google Search"

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
        "source": source_name,
        "elapsed": round(time.time() - started, 1),
    }
