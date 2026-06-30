"""Additional torrent search sources beyond torrfetch (piratebay/yts).

torrfetch only ships The Pirate Bay (mirror scraping) and YTS (movies only),
which leaves obscure music albums with almost no coverage. These sources add:
  - apibay:  The Pirate Bay's official JSON API (more reliable than scraping).
  - knaben:  an aggregator that searches many indexers at once.

Each function returns dicts in the same shape torrfetch produces, so results
can be merged directly into the discovery pipeline:
    {title, magnet, size, seeders, leechers, source}
All failures are swallowed and return [] so a dead source never breaks search.
"""
from __future__ import annotations

import json
import html
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
]

_DEAD_HASH = "0" * 40
_TORRENTDOWNLOADS_BASE = "https://www.torrentdownloads.pro"
_TORRENTDOWNLOADS_MUSIC_CATEGORY = "5"
_LIMETORRENTS_BASES = [
    "https://www.limetorrents.info",
    "https://www.limetorrents.pro",
    "https://www.limetorrents.asia",
    "https://www.limetorrents.zone",
    "https://www.limetorrents.co",
    "https://www.limetorrent.ws",
    "https://www.limetorrents.fun",
]
_TORLOCK_BASES = [
    "https://www.torlock.com",
    "https://www.torlock-official.live",
    "https://www.torlock.top",
]
_TORRENTDOWNLOADS_CATEGORY_ALIASES = [
    ("compilation", "515"), ("various artists", "515"), (" va ", "515"),
    ("country western", "59"), ("country", "59"), ("western", "59"),
    ("drum n bass", "60"), ("drum and bass", "60"), ("dnb", "60"),
    ("hardhouse", "78"), ("old school", "78"),
    ("heavy death metal", "306"), ("death metal", "306"),
    ("indie britpop", "511"), ("britpop", "511"), ("indie", "511"),
    ("game music", "62"), ("video game", "62"), ("vgm", "62"),
    ("non english", "522"), ("world", "522"),
    ("now thats what i call music", "507"), ("now that's what i call music", "507"),
    ("music other", "79"),
    ("rock n roll", "527"), ("rock and roll", "527"),
    ("singer songwriter", "514"), ("singer-songwriter", "514"),
    ("soundtrack", "77"), ("soundtracks", "77"),
    ("alternative", "54"), ("anime", "160"), ("asian", "55"), ("blues", "56"),
    ("christian", "57"), ("classical", "58"), ("classic", "58"),
    ("electronic", "61"), ("electronica", "61"), ("dance", "61"), ("house", "61"),
    ("techno", "61"), ("trance", "61"), ("folk", "519"), ("gothic", "233"),
    ("hardcore", "63"), ("hardrock", "512"), ("hard rock", "512"),
    ("hip hop", "64"), ("hip-hop", "64"), ("industrial", "65"), ("jazz", "66"),
    ("karaoke", "67"), ("latin", "521"), ("metal", "68"), ("motown", "526"),
    ("pop", "70"), ("punk", "71"), ("r&b", "72"), ("rnb", "72"),
    ("rap", "73"), ("reggae", "74"), ("rock", "75"), ("ska", "230"), ("soul", "505"),
]


def _magnet(info_hash: str, name: str) -> str:
    trackers = "".join(f"&tr={urllib.parse.quote(t)}" for t in _TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(name or '')}{trackers}"


def _http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 12) -> str:
    hdrs = {"User-Agent": "Mozilla/5.0"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def torrentdownloads_category_from_metadata(metadata: dict | None) -> str:
    """Pick a TorrentDownloads music subcategory from track metadata."""
    if not isinstance(metadata, dict):
        return _TORRENTDOWNLOADS_MUSIC_CATEGORY
    values: list[str] = []
    for key in ("genre", "genres", "style", "styles", "tags"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item)
    album = str(metadata.get("album") or "")
    if "soundtrack" in album.lower():
        values.append("soundtrack")
    for value in values:
        text = " " + re.sub(r"[^a-z0-9&']+", " ", value.lower()).strip() + " "
        for needle, category_id in _TORRENTDOWNLOADS_CATEGORY_ALIASES:
            if f" {needle} " in text or needle in text:
                return category_id
    return _TORRENTDOWNLOADS_MUSIC_CATEGORY


def _torrentdownloads_search_slug(query: str) -> str:
    slug = re.sub(r"\s+", "-", (query or "").strip())
    return urllib.parse.quote(slug, safe="")


def _dash_search_slug(query: str) -> str:
    slug = re.sub(r"[\s_]+", "-", (query or "").strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return urllib.parse.quote(slug, safe="")


def _clean_html_text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).replace("\xa0", " ").strip()


def _int_from_text(value: str) -> int:
    try:
        return int(re.sub(r"[^\d]", "", value or "") or 0)
    except Exception:
        return 0


def _category_from_text(value: str) -> str:
    text = (value or "").lower()
    if any(word in text for word in ("audio", "music", "mp3", "flac")):
        return "audio"
    if any(word in text for word in ("video", "movie", "movies", "tv", "1080p", "720p")):
        return "video"
    return "unknown"


def _torrentdownloads_parse_listing(page: str, limit: int = 30) -> list[dict]:
    rows = re.findall(r'<div class="grey_bar3[^"]*">(.*?)</div>', page or "", flags=re.I | re.S)
    parsed: list[dict] = []
    for row in rows:
        link_match = re.search(
            r'<a\s+href="(?P<href>/torrent/[^"]+)"[^>]*title="View torrent info\s*:\s*(?P<title>[^"]+)"',
            row,
            flags=re.I | re.S,
        )
        if not link_match:
            continue
        spans = re.findall(r"<span[^>]*>(.*?)</span>", row, flags=re.I | re.S)
        numeric_spans = []
        for span in spans:
            cleaned = re.sub(r"<[^>]+>", "", span)
            cleaned = html.unescape(cleaned).replace("\xa0", " ").strip()
            if cleaned:
                numeric_spans.append(cleaned)
        seeds = 0
        leeches = 0
        size = ""
        if len(numeric_spans) >= 3:
            try:
                seeds = int(re.sub(r"[^\d]", "", numeric_spans[-3]) or 0)
            except Exception:
                seeds = 0
            try:
                leeches = int(re.sub(r"[^\d]", "", numeric_spans[-2]) or 0)
            except Exception:
                leeches = 0
            size = numeric_spans[-1]
        title = html.unescape(link_match.group("title")).strip()
        parsed.append({
            "title": title,
            "detail_url": urllib.parse.urljoin(_TORRENTDOWNLOADS_BASE, link_match.group("href")),
            "size": size,
            "seeders": seeds,
            "leechers": leeches,
            "source": "torrentdownloads",
            "category": "audio",
        })
        if len(parsed) >= limit:
            break
    return parsed


def _torrentdownloads_detail_magnet(detail_url: str, title: str, timeout: int = 12) -> str:
    try:
        page = _http(detail_url, timeout=timeout)
    except Exception:
        return ""
    magnet_match = re.search(r'href=["\'](magnet:\?xt=urn:btih:[^"\']+)["\']', page, flags=re.I)
    if magnet_match:
        return html.unescape(magnet_match.group(1))
    hash_match = re.search(r"\b([A-Fa-f0-9]{40})\b", page)
    if hash_match:
        return _magnet(hash_match.group(1), title)
    return ""


def search_torrentdownloads(query: str, category_id: str | int | None = None, timeout: int = 12) -> list[dict]:
    out: list[dict] = []
    query_slug = _torrentdownloads_search_slug(query)
    if not query_slug:
        return out
    category = str(category_id or _TORRENTDOWNLOADS_MUSIC_CATEGORY).strip() or _TORRENTDOWNLOADS_MUSIC_CATEGORY
    urls = [f"{_TORRENTDOWNLOADS_BASE}/search/{category}/{query_slug}/"]
    if category != "all":
        urls.append(f"{_TORRENTDOWNLOADS_BASE}/search/all/{query_slug}/")
    seen_details: set[str] = set()
    candidates: list[dict] = []
    for url in urls:
        try:
            for item in _torrentdownloads_parse_listing(_http(url, timeout=timeout)):
                detail_url = item.get("detail_url") or ""
                if not detail_url or detail_url in seen_details:
                    continue
                seen_details.add(detail_url)
                candidates.append(item)
        except Exception:
            continue
        if candidates:
            break
    if not candidates:
        return out

    with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as executor:
        futures = [
            executor.submit(_torrentdownloads_detail_magnet, item["detail_url"], item["title"], timeout)
            for item in candidates
        ]
        for item, future in zip(candidates, futures):
            try:
                magnet = future.result() or ""
            except Exception:
                magnet = ""
            if not magnet:
                continue
            result = dict(item)
            result["magnet"] = magnet
            result.pop("detail_url", None)
            out.append(result)
    return out


def _limetorrents_parse_listing(page: str, limit: int = 30) -> list[dict]:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", page or "", flags=re.I | re.S)
    parsed: list[dict] = []
    seen_hashes: set[str] = set()
    for row in rows:
        hash_match = re.search(r"itorrents\.net/torrent/([A-Fa-f0-9]{40})\.torrent", row, flags=re.I)
        torrent_url_match = re.search(r'href="(https?://itorrents\.net/torrent/[A-Fa-f0-9]{40}\.torrent[^"]*)"', row, flags=re.I)
        title_match = re.search(
            r'<a\s+href="[^"]*-torrent-\d+\.html"[^>]*>(.*?)</a>',
            row,
            flags=re.I | re.S,
        )
        if not hash_match or not title_match:
            continue
        info_hash = hash_match.group(1).upper()
        if info_hash in seen_hashes:
            continue
        seen_hashes.add(info_hash)
        title = _clean_html_text(title_match.group(1))
        if not title:
            continue

        td_values = [_clean_html_text(value) for value in re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)]
        size = ""
        if len(td_values) >= 3:
            size = td_values[-3]
        seed_match = re.search(r'<td\b[^>]*class="tdseed"[^>]*>(.*?)</td>', row, flags=re.I | re.S)
        leech_match = re.search(r'<td\b[^>]*class="tdleech"[^>]*>(.*?)</td>', row, flags=re.I | re.S)
        parsed.append({
            "title": title,
            "magnet": _magnet(info_hash, title),
            "torrent_url": html.unescape(torrent_url_match.group(1)) if torrent_url_match else "",
            "size": size,
            "seeders": _int_from_text(seed_match.group(1) if seed_match else ""),
            "leechers": _int_from_text(leech_match.group(1) if leech_match else ""),
            "source": "limetorrents",
            "category": "audio",
        })
        if len(parsed) >= limit:
            break
    return parsed


def search_limetorrents(query: str, timeout: int = 12) -> list[dict]:
    """Search LimeTorrents music category."""
    slug = _dash_search_slug(query)
    if not slug:
        return []
    per_mirror_timeout = max(1.0, min(float(timeout), 3.0))

    def fetch_base(base: str) -> list[dict]:
        try:
            return _limetorrents_parse_listing(_http(f"{base}/search/music/{slug}/", timeout=per_mirror_timeout))
        except Exception:
            return []

    executor = ThreadPoolExecutor(max_workers=min(4, len(_LIMETORRENTS_BASES)))
    try:
        futures = [executor.submit(fetch_base, base) for base in _LIMETORRENTS_BASES]
        for future in as_completed(futures, timeout=per_mirror_timeout + 1.0):
            try:
                results = future.result()
            except Exception:
                continue
            if results:
                executor.shutdown(wait=False, cancel_futures=True)
                return results
    except Exception:
        pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return []


def _torlock_parse_listing(page: str, limit: int = 30) -> list[dict]:
    parsed: list[dict] = []
    seen: set[str] = set()
    for magnet_match in re.finditer(r'href=["\'](magnet:\?xt=urn:btih:([^&"\']+)[^"\']*)["\']', page or "", flags=re.I):
        magnet = html.unescape(magnet_match.group(1))
        info_hash = magnet_match.group(2).upper()
        if info_hash in seen:
            continue
        seen.add(info_hash)
        row_start = max(0, (page or "").rfind("<tr", 0, magnet_match.start()))
        row_end = (page or "").find("</tr>", magnet_match.end())
        row = (page or "")[row_start:row_end] if row_start >= 0 and row_end >= 0 else (page or "")[magnet_match.start():magnet_match.end()]
        titles = [_clean_html_text(value) for value in re.findall(r"<a\b[^>]*>(.*?)</a>", row, flags=re.I | re.S)]
        title = next((value for value in titles if value and not value.lower().startswith(("download", "magnet"))), "")
        if not title:
            dn = re.search(r"[?&]dn=([^&]+)", magnet)
            title = urllib.parse.unquote(dn.group(1)) if dn else info_hash
        td_values = [_clean_html_text(value) for value in re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)]
        size = next((value for value in td_values if re.search(r"\b(?:kb|mb|gb|tb)\b", value, flags=re.I)), "")
        numbers = [_int_from_text(value) for value in td_values if _int_from_text(value)]
        parsed.append({
            "title": title,
            "magnet": magnet,
            "size": size,
            "seeders": numbers[-2] if len(numbers) >= 2 else 0,
            "leechers": numbers[-1] if numbers else 0,
            "source": "torlock",
            "category": "audio",
        })
        if len(parsed) >= limit:
            break
    return parsed


def _torlock_detail_magnet(detail_url: str, title: str, timeout: int = 12) -> str:
    try:
        page = _http(detail_url, timeout=timeout)
    except Exception:
        return ""
    magnet_match = re.search(r'href=["\'](magnet:\?xt=urn:btih:[^"\']+)["\']', page, flags=re.I)
    if magnet_match:
        return html.unescape(magnet_match.group(1))
    hash_match = re.search(r"\b([A-Fa-f0-9]{40})\b", page)
    if hash_match:
        return _magnet(hash_match.group(1), title)
    return ""


def _torlock_parse_detail_links(page: str, base: str, limit: int = 12) -> list[dict]:
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    for link_match in re.finditer(r'<a\s+href=["\'](?P<href>/torrent/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>', page or "", flags=re.I | re.S):
        href = link_match.group("href")
        title = _clean_html_text(link_match.group("title"))
        if not href or not title:
            continue
        detail_url = urllib.parse.urljoin(base, href)
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        candidates.append({
            "title": title,
            "detail_url": detail_url,
            "size": "",
            "seeders": 0,
            "leechers": 0,
            "source": "torlock",
            "category": "audio",
        })
        if len(candidates) >= limit:
            break
    return candidates


def search_torlock(query: str, timeout: int = 12) -> list[dict]:
    """Search TorLock music category."""
    slug = _dash_search_slug(query)
    if not slug:
        return []
    per_mirror_timeout = max(1.0, min(float(timeout), 3.0))
    for base in _TORLOCK_BASES:
        try:
            page = _http(f"{base}/music/torrents/{slug}.html", timeout=per_mirror_timeout)
        except Exception:
            continue

        direct = _torlock_parse_listing(page)
        if direct:
            return direct

        candidates = _torlock_parse_detail_links(page, base)
        if not candidates:
            continue
        out: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as executor:
            futures = [
                executor.submit(_torlock_detail_magnet, item["detail_url"], item["title"], timeout)
                for item in candidates
            ]
            for item, future in zip(candidates, futures):
                try:
                    magnet = future.result() or ""
                except Exception:
                    magnet = ""
                if not magnet:
                    continue
                result = dict(item)
                result["magnet"] = magnet
                result.pop("detail_url", None)
                out.append(result)
        if out:
            return out
    return []


def search_apibay(query: str, timeout: int = 12) -> list[dict]:
    out: list[dict] = []
    try:
        url = "https://apibay.org/q.php?" + urllib.parse.urlencode({"q": query, "cat": 0})
        data = json.loads(_http(url, timeout=timeout))
        for item in data:
            info_hash = (item.get("info_hash") or "").strip()
            name = item.get("name")
            if not name or not info_hash or info_hash == _DEAD_HASH:
                continue
            
            # Map TPB categories to generic ones
            cat_id = str(item.get("category") or "0")
            category = "unknown"
            if cat_id.startswith("1"): # Audio
                category = "audio"
            elif cat_id.startswith("2"): # Video
                category = "video"
            
            out.append({
                "title": name,
                "magnet": _magnet(info_hash, name),
                "size": str(item.get("size") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("leechers") or 0),
                "source": "apibay",
                "category": category,
            })
    except Exception:
        pass
    return out


def search_knaben(query: str, timeout: int = 12) -> list[dict]:
    out: list[dict] = []
    try:
        body = json.dumps({
            "query": query,
            "order_by": "seeders",
            "order_direction": "desc",
            "size": 50,
            "hide_unsafe": False,
        }).encode()
        data = json.loads(_http(
            "https://api.knaben.eu/v1",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        ))
        for item in (data.get("hits") or []):
            title = item.get("title")
            magnet = item.get("magnetUrl")
            info_hash = item.get("hash")
            if not magnet and info_hash:
                magnet = _magnet(info_hash, title or "")
            if not title or not magnet:
                continue
            
            cat = str(item.get("category") or "unknown").lower()
            category = "unknown"
            if "audio" in cat or "music" in cat:
                category = "audio"
            elif "video" in cat or "movie" in cat or "show" in cat:
                category = "video"

            out.append({
                "title": title,
                "magnet": magnet,
                "size": str(item.get("bytes") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("peers") or 0),
                "source": "knaben:" + str(item.get("tracker") or "agg"),
                "category": category,
            })
    except Exception:
        pass
    return out


def search_solid(query: str, timeout: int = 12) -> list[dict]:
    """Search SolidTorrents which aggregates 1337x, KAT, etc."""
    out: list[dict] = []
    try:
        # SolidTorrents has a nice JSON API
        url = f"https://solidtorrents.to/api/v1/search?q={urllib.parse.quote(query)}&category=Audio"
        data = json.loads(_http(url, timeout=timeout))
        for item in data.get("results", []):
            title = item.get("title")
            info_hash = item.get("infohash")
            if not title or not info_hash:
                continue
            
            out.append({
                "title": title,
                "magnet": f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}",
                "size": str(item.get("size") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("leechers") or 0),
                "source": "solid",
                "category": "audio",
            })
    except Exception:
        pass
    return out


def search_1337x(query: str, timeout: int = 12) -> list[dict]:
    """1337x search via SolidTorrents and extra query flags."""
    # Since direct 1337x is Cloudflare-protected, we use an aggregator
    # but append the site name to favor those results if the aggregator supports it.
    return search_solid(query + " 1337x", timeout)


def search_kickass(query: str, timeout: int = 12) -> list[dict]:
    """Kickass search via SolidTorrents and extra query flags."""
    return search_solid(query + " kickass", timeout)


def search_extra(query: str, timeout: int = 12) -> list[dict]:
    """Query all extra sources in parallel and return the merged results."""
    results: list[dict] = []
    # Reordered to prioritize 1337x and Kickass results in the execution pool
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(search_1337x, query, timeout),
            executor.submit(search_kickass, query, timeout),
            executor.submit(search_solid, query, timeout),
            executor.submit(search_knaben, query, timeout),
            executor.submit(search_apibay, query, timeout),
        ]
        for future in futures:
            try:
                results += future.result() or []
            except Exception:
                pass
    return results


# ── Music video clip search ──────────────────────────────────────────────────

_VIDEO_CLIP_EXTS = frozenset((".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v"))
_VIDEO_CLIP_MAX_BYTES = 2 * 1024 ** 3  # 2 GB; full concerts are usually larger


def _looks_like_clip(title: str) -> bool:
    """True when the torrent name suggests a music video clip rather than a full concert/album."""
    low = (title or "").lower()
    if any(w in low for w in ("concert", "live at", "full album", "discography", "dvdrip", "blu-ray", "bluray", "bdrip")):
        return False
    if any(w in low for w in ("music video", "official video", "official clip", "video clip", "mv ", " mv", "promo")):
        return True
    return True  # accept by default; size filter handles the rest


def _parse_size_bytes(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _search_apibay_music_video(query: str, timeout: int) -> list[dict]:
    """Apibay search restricted to TPB category 200 (Video) which includes 203 Music Videos."""
    out: list[dict] = []
    try:
        # cat=200 = All Video; cat=203 = Music Videos specifically
        for cat in ("203", "200"):
            url = "https://apibay.org/q.php?" + urllib.parse.urlencode({"q": query, "cat": cat})
            data = json.loads(_http(url, timeout=timeout))
            for item in data:
                info_hash = (item.get("info_hash") or "").strip()
                name = item.get("name")
                if not name or not info_hash or info_hash == _DEAD_HASH:
                    continue
                out.append({
                    "title": name,
                    "magnet": _magnet(info_hash, name),
                    "size": str(item.get("size") or ""),
                    "seeders": int(item.get("seeders") or 0),
                    "leechers": int(item.get("leechers") or 0),
                    "source": f"apibay_video:{cat}",
                    "category": "video",
                })
            if out:
                break
    except Exception:
        pass
    return out


def _search_knaben_music_video(query: str, timeout: int) -> list[dict]:
    out: list[dict] = []
    try:
        body = json.dumps({
            "query": query,
            "order_by": "seeders",
            "order_direction": "desc",
            "size": 30,
            "hide_unsafe": False,
            "categories": ["Video"],
        }).encode()
        data = json.loads(_http(
            "https://api.knaben.eu/v1",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        ))
        for item in (data.get("hits") or []):
            title = item.get("title")
            magnet = item.get("magnetUrl")
            info_hash = item.get("hash")
            if not magnet and info_hash:
                magnet = _magnet(info_hash, title or "")
            if not title or not magnet:
                continue
            out.append({
                "title": title,
                "magnet": magnet,
                "size": str(item.get("bytes") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("peers") or 0),
                "source": "knaben_video:" + str(item.get("tracker") or "agg"),
                "category": "video",
            })
    except Exception:
        pass
    return out


def _search_solid_music_video(query: str, timeout: int) -> list[dict]:
    out: list[dict] = []
    try:
        url = f"https://solidtorrents.to/api/v1/search?q={urllib.parse.quote(query)}&category=Video"
        data = json.loads(_http(url, timeout=timeout))
        for item in data.get("results", []):
            title = item.get("title")
            info_hash = item.get("infohash")
            if not title or not info_hash:
                continue
            out.append({
                "title": title,
                "magnet": f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}",
                "size": str(item.get("size") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("leechers") or 0),
                "source": "solid_video",
                "category": "video",
            })
    except Exception:
        pass
    return out


def search_music_video_clips(artist: str, title: str, timeout: int = 15) -> list[dict]:
    """Search torrent sites for a music video clip for the given track.

    Returns results sorted by seeders desc, filtered to plausible clip size.
    Each result has the standard {title, magnet, size, seeders, source, category} shape.
    """
    query = f"{artist} {title} music video"
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_search_apibay_music_video, query, timeout),
            executor.submit(_search_knaben_music_video, query, timeout),
            executor.submit(_search_solid_music_video, query, timeout),
        ]
        for future in futures:
            try:
                results += future.result() or []
            except Exception:
                pass

    filtered: list[dict] = []
    for r in results:
        if int(r.get("seeders") or 0) < 1:
            continue
        size_bytes = _parse_size_bytes(r.get("size"))
        if size_bytes > _VIDEO_CLIP_MAX_BYTES:
            continue
        if not _looks_like_clip(r.get("title") or ""):
            continue
        filtered.append(r)

    filtered.sort(key=lambda r: int(r.get("seeders") or 0), reverse=True)
    return filtered
