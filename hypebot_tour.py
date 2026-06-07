from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request

from rapidfuzz import fuzz

_BASE_URL = "https://concerts.hypebot.com"
_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15"
)


def _fetch_text(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _absolute_url(url: str) -> str:
    return urllib.parse.urljoin(_BASE_URL, html.unescape(url or ""))


def _artist_letter(name: str, fallback: str = "a") -> str:
    for ch in (name or "").casefold():
        if "a" <= ch <= "z":
            return ch
        if ch.isdigit():
            return "%23"
    return fallback


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _artist_match_score(wanted: str, candidate: str) -> int:
    wanted_norm = _norm(wanted)
    candidate_norm = _norm(candidate)
    if not wanted_norm or not candidate_norm:
        return 0
    if wanted_norm == candidate_norm:
        return 100
    return int(max(
        fuzz.ratio(wanted_norm, candidate_norm),
        fuzz.token_sort_ratio(wanted, candidate),
    ))


def _extract_json_ld(html_text: str) -> list:
    blocks = re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parsed: list = []
    for block in blocks:
        raw = html.unescape(block).strip()
        if not raw:
            continue
        try:
            parsed.append(json.loads(raw))
        except Exception:
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
            try:
                parsed.append(json.loads(cleaned))
            except Exception:
                continue
    return parsed


def _iter_json_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_nodes(item)
    elif isinstance(value, dict):
        yield value
        for child_key in ("@graph", "mainEntity", "itemListElement"):
            child = value.get(child_key)
            if isinstance(child, list):
                for item in child:
                    yield from _iter_json_nodes(item)
            elif isinstance(child, dict):
                yield from _iter_json_nodes(child)
        answer = value.get("acceptedAnswer")
        if isinstance(answer, list):
            for item in answer:
                yield from _iter_json_nodes(item)
        elif isinstance(answer, dict):
            yield from _iter_json_nodes(answer)


def _first_text(*values) -> str:
    for value in values:
        if value is None:
            continue
        text = html.unescape(str(value)).strip()
        if text:
            return text
    return ""


def _date_parts(start_date: str) -> tuple[str, str, str]:
    date = (start_date or "").split("T", 1)[0]
    month = day = ""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", date)
    if match:
        month_index = int(match.group(2))
        if 1 <= month_index <= 12:
            month = _MONTHS[month_index]
        day = str(int(match.group(3)))
    return date, month, day


def _time_part(start_date: str) -> str:
    match = re.match(r"\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})", start_date or "")
    return match.group(1) if match else ""


def _normalize_event(event: dict, artist_name: str) -> dict | None:
    if not isinstance(event, dict) or event.get("@type") != "MusicEvent":
        return None
    start_date = _first_text(event.get("startDate"))
    date, month, day = _date_parts(start_date)
    location = event.get("location") if isinstance(event.get("location"), dict) else {}
    address = location.get("address") if isinstance(location.get("address"), dict) else {}
    geo = location.get("geo") if isinstance(location.get("geo"), dict) else {}
    offers = event.get("offers") if isinstance(event.get("offers"), dict) else {}
    performer = event.get("performer") if isinstance(event.get("performer"), dict) else {}

    venue = _first_text(location.get("name"))
    city = _first_text(address.get("addressLocality"))
    region = _first_text(address.get("addressRegion"))
    country = _first_text(address.get("addressCountry"))
    street = _first_text(address.get("streetAddress"))
    postal_code = _first_text(address.get("postalCode"))
    location_text = ", ".join(part for part in (venue, city, region or country) if part)
    price = _first_text(offers.get("price"))
    currency = _first_text(offers.get("priceCurrency"))
    if price and currency:
        price = f"{price} {currency}"

    if not date and not venue and not city:
        return None
    return {
        "artist": _first_text(performer.get("name"), artist_name),
        "name": _first_text(event.get("name")) or venue or "Concert",
        "status": "upcoming",
        "date": date,
        "datetime": start_date,
        "month": month,
        "day": day,
        "time": _time_part(start_date),
        "city": city,
        "place": city,
        "state": region,
        "region": region,
        "country": country,
        "venue": venue,
        "street": street,
        "postal_code": postal_code,
        "location": location_text,
        "latitude": _first_text(geo.get("latitude")),
        "longitude": _first_text(geo.get("longitude")),
        "price": price,
        "info": _first_text(event.get("description")),
        "image": _first_text(event.get("image")),
        "url": _first_text(offers.get("url"), event.get("url")),
        "source": "Hypebot/Bandsintown",
    }


def _extract_tour_message(html_text: str, artist_name: str) -> str:
    wanted_question = f"is {artist_name}".casefold() if artist_name else "is "
    for node in _iter_json_nodes(_extract_json_ld(html_text)):
        if node.get("@type") != "Question":
            continue
        question = _first_text(node.get("name"))
        if "on tour" not in question.casefold() or wanted_question not in question.casefold():
            continue
        answer = node.get("acceptedAnswer") if isinstance(node.get("acceptedAnswer"), dict) else {}
        text = _first_text(answer.get("text"))
        if text:
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return ""


def parse_artist_page(html_text: str, page_url: str = "") -> dict:
    artist_name = ""
    for node in _iter_json_nodes(_extract_json_ld(html_text)):
        if node.get("@type") == "MusicGroup":
            artist_name = _first_text(node.get("name"))
            break
    if not artist_name:
        title_match = re.search(r"<h1[^>]*>\s*([^<]+?)\s*<span", html_text or "", re.I | re.S)
        artist_name = _first_text(title_match.group(1) if title_match else "")

    events = []
    for node in _iter_json_nodes(_extract_json_ld(html_text)):
        event = _normalize_event(node, artist_name)
        if event:
            events.append(event)
    events.sort(key=lambda item: item.get("date") or "")
    return {
        "artist": artist_name,
        "events": events,
        "message": _extract_tour_message(html_text, artist_name),
        "source": "Hypebot/Bandsintown",
        "url": page_url,
    }


def parse_artist_links(html_text: str, artist: str = "", limit: int = 10, exact_artist: bool = False) -> list[dict]:
    seen: set[str] = set()
    links: list[dict] = []
    pattern = re.compile(r'<a\b[^>]*href=["\']([^"\']*/artist/[^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    for match in pattern.finditer(html_text or ""):
        url = _absolute_url(match.group(1))
        if url in seen:
            continue
        seen.add(url)
        text = re.sub(r"<[^>]+>", " ", match.group(2))
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        slug_name = urllib.parse.unquote(url.rstrip("/").split("/")[-1])
        slug_name = re.sub(r"^\d+-", "", slug_name).replace("-", " ").strip()
        name = text or slug_name.title()
        links.append({"name": name, "url": url})

    if artist:
        exact = [item for item in links if _artist_match_score(artist, item.get("name", "")) == 100]
        if exact_artist:
            if exact:
                return exact[: max(1, int(limit or 1))]
            fuzzy_matches = [
                {**item, "_match_score": _artist_match_score(artist, item.get("name", ""))}
                for item in links
            ]
            fuzzy_matches = [item for item in fuzzy_matches if item["_match_score"] >= 86]
            fuzzy_matches.sort(key=lambda item: (-item["_match_score"], item.get("name", "")))
            return [
                {key: value for key, value in item.items() if key != "_match_score"}
                for item in fuzzy_matches[: max(1, int(limit or 1))]
            ]
        links.sort(key=lambda item: (-_artist_match_score(artist, item.get("name", "")), item.get("name", "")))
    return links[: max(1, int(limit or 1))]


def search_artist_pages(artist: str = "", letter: str = "", limit: int = 10, timeout: float = 15) -> list[dict]:
    letter = (letter or _artist_letter(artist)).strip().lower()
    if letter in {"#", "%23"}:
        letter = "%23"
    if not re.fullmatch(r"[a-z]|%23", letter):
        letter = _artist_letter(artist)
    url = f"{_BASE_URL}/search/artists/{letter}"
    print(f"[hypebot_tour] Searching artist index {url} for {artist!r}")
    text = _fetch_text(url, timeout=timeout)
    links = parse_artist_links(text, artist=artist, limit=limit, exact_artist=bool(artist))
    if artist:
        if links:
            score = _artist_match_score(artist, links[0].get("name", ""))
            match_type = "exact" if score == 100 else "fuzzy"
            print(f"[hypebot_tour] {match_type} artist match: {artist!r} -> {links[0].get('name')!r} ({score})")
        else:
            print(f"[hypebot_tour] No artist match found for {artist!r} on letter {letter!r}")
    return links


def fetch_artist_concerts(artist: str = "", letter: str = "", url: str = "", limit: int = 1, timeout: float = 15) -> dict:
    started = time.time()
    pages = [{"name": artist, "url": _absolute_url(url)}] if url else search_artist_pages(artist, letter, limit, timeout)
    results = []
    for page in pages[: max(1, int(limit or 1))]:
        page_url = page.get("url", "")
        print(f"[hypebot_tour] Fetching artist page {page_url}")
        text = _fetch_text(page_url, timeout=timeout)
        parsed = parse_artist_page(text, page_url=page_url)
        if not parsed.get("artist"):
            parsed["artist"] = page.get("name", "")
        print(f"[hypebot_tour] Extracted {len(parsed.get('events') or [])} events for {parsed.get('artist')!r}")
        results.append(parsed)

    events = []
    message = ""
    for item in results:
        events.extend(item.get("events") or [])
        if not message and item.get("message"):
            message = item.get("message")
    events.sort(key=lambda item: item.get("date") or "")
    return {
        "ok": True,
        "artist": artist,
        "pages": results,
        "events": events,
        "message": message,
        "source": "Hypebot/Bandsintown",
        "elapsed": round(time.time() - started, 2),
    }
