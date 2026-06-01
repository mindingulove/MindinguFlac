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
            out.append({
                "title": name,
                "magnet": _magnet(info_hash, name),
                "size": str(item.get("size") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("leechers") or 0),
                "source": "apibay",
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
            out.append({
                "title": title,
                "magnet": magnet,
                "size": str(item.get("bytes") or ""),
                "seeders": int(item.get("seeders") or 0),
                "leechers": int(item.get("peers") or 0),
                "source": "knaben:" + str(item.get("tracker") or "agg"),
            })
    except Exception:
        pass
    return out


def search_extra(query: str, timeout: int = 12) -> list[dict]:
    """Query all extra sources in parallel and return the merged results."""
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(search_apibay, query, timeout),
            executor.submit(search_knaben, query, timeout),
        ]
        for future in futures:
            try:
                results += future.result() or []
            except Exception:
                pass
    return results
