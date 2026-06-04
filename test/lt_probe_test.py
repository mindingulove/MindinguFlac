"""Standalone libtorrent probe test.

Pulls REAL magnets (with seeder counts) from the same providers the app uses,
then drives them through the EXACT optimized session from backend_torrent.py,
reporting DHT bootstrap, metadata acquisition, and live peers over time.

Goal: decide whether "unresponsive during metadata probe" is dead torrents or a
broken pipeline / blocked BitTorrent connectivity in this environment.
"""
from __future__ import annotations

import sys
import time
import urllib.parse

import libtorrent as lt

import torrent_sources
from backend_torrent import _create_optimized_session, _get_best_trackers

PIPELINE_TRACKERS = _get_best_trackers()

QUERY = sys.argv[1] if len(sys.argv) > 1 else "Pink Floyd Dark Side of the Moon FLAC"
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 6
PROBE_SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 40


def fetch_magnets(query: str) -> list[dict]:
    out: list[dict] = []
    for name, fn in [("apibay", torrent_sources.search_apibay),
                     ("knaben", torrent_sources.search_knaben),
                     ("torrentdownloads", torrent_sources.search_torrentdownloads)]:
        try:
            rows = fn(query) or []
            print(f"  provider {name}: {len(rows)} results")
            for r in rows:
                if r.get("magnet"):
                    out.append(r)
        except Exception as exc:
            print(f"  provider {name}: ERROR {exc}")
    # de-dupe by infohash-ish, prefer seeders
    seen = set()
    uniq = []
    for r in sorted(out, key=lambda x: int(x.get("seeders") or 0), reverse=True):
        m = r.get("magnet", "")
        key = m.split("&", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq


def main() -> None:
    print(f"Query: {QUERY!r}  top_n={TOP_N}  probe={PROBE_SECONDS}s")
    print("== Fetching real magnets from providers ==")
    mags = fetch_magnets(QUERY)
    if not mags:
        print("No magnets returned by any provider (indexer network blocked?). Aborting.")
        return
    mags = mags[:TOP_N]
    print(f"Probing top {len(mags)} by seeders:")
    for r in mags:
        print(f"  - {int(r.get('seeders') or 0):>5}s  {str(r.get('title'))[:70]}")

    print("\n== Building pipeline's optimized session ==")
    ses = _create_optimized_session()

    handles = []
    for r in mags:
        m = r["magnet"]
        for tr in PIPELINE_TRACKERS:
            if "&tr=" not in m or urllib.parse.quote(tr) not in m:
                m += f"&tr={urllib.parse.quote(tr)}"
        h = lt.add_magnet_uri(ses, m, {"save_path": "/tmp/lt_probe", "storage_mode": lt.storage_mode_t(2)})
        for tr in PIPELINE_TRACKERS:
            try:
                h.add_tracker(lt.announce_entry(tr))
            except Exception:
                pass
        h.force_reannounce()
        handles.append((r, h))

    print(f"\n== Probing for {PROBE_SECONDS}s (metadata + peers + DHT) ==")
    start = time.time()
    got_meta = set()
    while time.time() - start < PROBE_SECONDS:
        st = ses.status()
        dht_nodes = getattr(st, "dht_nodes", 0)
        elapsed = int(time.time() - start)
        line_meta = 0
        line_peers = 0
        for r, h in handles:
            try:
                if h.has_metadata():
                    line_meta += 1
                    got_meta.add(id(h))
                line_peers += int(h.status().num_peers or 0)
            except Exception:
                pass
        print(f"  t={elapsed:>3}s  dht_nodes={dht_nodes:<5}  meta={line_meta}/{len(handles)}  total_peers={line_peers}")
        if line_meta == len(handles):
            print("  -> all torrents resolved metadata; stopping early")
            break
        time.sleep(2.0)

    print("\n== Per-torrent final state ==")
    for r, h in handles:
        try:
            s = h.status()
            print(f"  meta={h.has_metadata()!s:<5} peers={int(s.num_peers or 0):<3} "
                  f"dl={int(s.download_rate or 0)//1024:>4}KB/s seeders_idx={int(r.get('seeders') or 0):<5} "
                  f"{str(r.get('title'))[:55]}")
        except Exception as exc:
            print(f"  ERROR {exc}")

    final = ses.status()
    print(f"\n== Verdict ==")
    print(f"DHT nodes bootstrapped: {getattr(final, 'dht_nodes', 0)}")
    print(f"Torrents that got metadata: {len(got_meta)}/{len(handles)}")
    if getattr(final, "dht_nodes", 0) == 0:
        print(">> DHT never bootstrapped — UDP/DHT likely blocked in this environment.")
    if len(got_meta) == 0:
        print(">> ZERO metadata fetched even for high-seeder torrents => connectivity/config issue, NOT dead torrents.")
    elif len(got_meta) < len(handles):
        print(">> Partial: some resolved => network works; the rest are genuinely slow/dead.")
    else:
        print(">> All resolved => libtorrent + session are healthy; pipeline timeouts/logic are the suspect.")


if __name__ == "__main__":
    main()
