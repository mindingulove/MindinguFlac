"""Confirm queue-starvation: load the shared optimized session like the pipeline
does under 5-track prefetch, and measure metadata acquisition for auto-managed
(default) vs auto_managed=False. If auto-managed starves and the override fixes
it, the pipeline bug is confirmed.
"""
from __future__ import annotations

import sys
import time
import urllib.parse

import libtorrent as lt

import torrent_sources
from backend_torrent import _create_optimized_session, _get_best_trackers

TRACKERS = _get_best_trackers()
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
PROBE = int(sys.argv[2]) if len(sys.argv) > 2 else 25


def get_magnets(n: int) -> list[str]:
    rows = []
    for q in ["FLAC 2024", "FLAC album", "discography FLAC", "lossless music", "greatest hits FLAC"]:
        try:
            rows += torrent_sources.search_apibay(q) or []
        except Exception:
            pass
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: int(x.get("seeders") or 0), reverse=True):
        m = r.get("magnet", "")
        k = m.split("&", 1)[0]
        if m and k not in seen and int(r.get("seeders") or 0) > 0:
            seen.add(k)
            out.append(m)
        if len(out) >= n:
            break
    return out


def add(ses, magnet, auto_managed):
    m = magnet
    for tr in TRACKERS:
        if urllib.parse.quote(tr) not in m:
            m += f"&tr={urllib.parse.quote(tr)}"
    p = lt.add_torrent_params()
    p.url = m
    p.save_path = "/tmp/lt_load"
    p.storage_mode = lt.storage_mode_t(2)
    if auto_managed:
        p.flags |= lt.torrent_flags.auto_managed
    else:
        p.flags &= ~lt.torrent_flags.auto_managed
        p.flags &= ~lt.torrent_flags.paused
    h = ses.add_torrent(p)
    for tr in TRACKERS:
        try:
            h.add_tracker(lt.announce_entry(tr))
        except Exception:
            pass
    h.force_reannounce()
    return h


def run(auto_managed: bool, magnets: list[str]) -> int:
    label = "auto_managed=True (pipeline default)" if auto_managed else "auto_managed=False (fix)"
    print(f"\n== {label}: adding {len(magnets)} torrents to one shared session ==")
    ses = _create_optimized_session()
    handles = [add(ses, m, auto_managed) for m in magnets]
    start = time.time()
    while time.time() - start < PROBE:
        meta = sum(1 for h in handles if h.has_metadata())
        if int(time.time() - start) % 5 == 0:
            print(f"  t={int(time.time()-start):>3}s  meta={meta}/{len(handles)}")
        if meta == len(handles):
            break
        time.sleep(1.0)
    meta = sum(1 for h in handles if h.has_metadata())
    print(f"  FINAL: {meta}/{len(handles)} got metadata in {PROBE}s")
    return meta


def main() -> None:
    print(f"Fetching {N} live magnets...")
    magnets = get_magnets(N)
    print(f"Got {len(magnets)} magnets with >0 seeders")
    if len(magnets) < 10:
        print("Not enough magnets to test load. Aborting.")
        return
    a = run(True, magnets)
    b = run(False, magnets)
    print("\n== Verdict ==")
    print(f"auto_managed (default): {a}/{len(magnets)}   auto_managed=False: {b}/{len(magnets)}")
    if b > a:
        print(">> CONFIRMED: queue limits starve auto-managed torrents under load. "
              "Pipeline floods the shared session; excess torrents never fetch metadata.")
    else:
        print(">> No clear starvation difference at this load level.")


if __name__ == "__main__":
    main()
