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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.stealth.si:80/announce",
]

_DEAD_HASH = "0" * 40


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
