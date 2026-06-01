from __future__ import annotations

import logging
import os
import time
import threading
import shutil
import re
import concurrent.futures
from pathlib import Path
import torrfetch
import libtorrent as lt
import rapidfuzz

logger = logging.getLogger(__name__)

_TRACKERS_CACHE: list[str] = []
_TRACKERS_LAST_FETCH: float = 0

_HARDCODED_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.moeking.me:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.com:2810/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://opentracker.i2p.rocks:6969/announce",
    "https://opentracker.i2p.rocks:443/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
]

def _get_best_trackers() -> list[str]:
    global _TRACKERS_CACHE, _TRACKERS_LAST_FETCH
    now = time.time()
    if _TRACKERS_CACHE and (now - _TRACKERS_LAST_FETCH < 86400):
        return _TRACKERS_CACHE
    trackers = list(_HARDCODED_TRACKERS)
    try:
        url = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as resp:
            lines = resp.read().decode("utf-8").splitlines()
            for line in lines:
                t = line.strip()
                if t and t not in trackers: trackers.append(t)
            _TRACKERS_LAST_FETCH = now
    except Exception: pass
    _TRACKERS_CACHE = trackers
    return trackers

_ACTIVE_SESSIONS: dict[str, dict] = {}
_SESSIONS_LOCK = threading.Lock()

def _create_optimized_session():
    s = lt.session()
    settings = {
        'listen_interfaces': '0.0.0.0:6881,[::]:6881',
        'enable_dht': True,
        'enable_upnp': True,
        'enable_natpmp': True,
        'enable_lsd': True,
        'active_downloads': 15,
        'active_seeds': 5,
        'active_limit': 20,
        'inactivity_timeout': 60,
        'peer_connect_timeout': 10,
    }
    s.apply_settings(settings)
    s.add_dht_router("router.bittorrent.com", 6881)
    s.add_dht_router("router.utorrent.com", 6881)
    s.add_dht_router("dht.transmissionbt.com", 6881)
    s.add_dht_router("dht.libtorrent.org", 25401)
    return s

_GLOBAL_SES = _create_optimized_session()

def _register_job_to_torrent(magnet: str, job_id: str, manager) -> lt.torrent_handle:
    with _SESSIONS_LOCK:
        if magnet in _ACTIVE_SESSIONS:
            entry = _ACTIVE_SESSIONS[magnet]
            entry["refs"].add(job_id)
            handle = entry["handle"]
            if handle.is_valid():
                handle.resume()
                return handle
        params = {
            'save_path': str(Path(manager.config.cache_dir) / "torrent_downloads"),
            'storage_mode': lt.storage_mode_t(2)
        }
        handle = lt.add_magnet_uri(_GLOBAL_SES, magnet, params)
        _ACTIVE_SESSIONS[magnet] = {"handle": handle, "refs": {job_id}}
        return handle

def _unregister_job_from_torrent(magnet: str, job_id: str):
    with _SESSIONS_LOCK:
        if magnet not in _ACTIVE_SESSIONS: return
        entry = _ACTIVE_SESSIONS[magnet]
        entry["refs"].discard(job_id)
        if not entry["refs"]:
            handle = entry["handle"]
            if handle.is_valid():
                _GLOBAL_SES.remove_torrent(handle)
            del _ACTIVE_SESSIONS[magnet]

def _get_catalog_path(manager) -> Path:
    return Path(manager.config.cache_dir) / "torrent_catalog.json"

def _load_catalog(manager) -> dict:
    path = _get_catalog_path(manager)
    if not path.exists(): return {}
    try:
        import json
        return json.loads(path.read_text("utf-8"))
    except Exception: return {}

def _save_catalog(manager, catalog: dict) -> None:
    path = _get_catalog_path(manager)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import json
        path.write_text(json.dumps(catalog, indent=2), "utf-8")
    except Exception: pass

def run(output_dir: Path, job: dict, manager) -> None:
    # 0. Query Cleaning
    job_id = job["id"]
    is_prefetch = bool(job.get("prefetch"))
    raw_title = job.get("title") or "Unknown"
    title_clean = re.sub(r'\s*[\(\[].*?[\)\]]', '', raw_title).strip()
    title_clean = title_clean.split(' - ')[0].strip()
    
    artist_list = job.get("artist") or "Unknown"
    primary_artist = artist_list.split(',')[0].strip()
    artist_variations = [primary_artist]
    clean_name = re.sub(r"[^a-zA-Z0-9\s]", "", primary_artist)
    if clean_name != primary_artist: artist_variations.append(clean_name)
    
    album = job.get("album") or "Unknown"
    def clean_term(text):
        if not text or text == "Unknown": return ""
        return re.sub(r'\s*[\(\[].*?[\)\]]', '', text).strip()
    album_clean = clean_term(album)
    title_simple = clean_term(raw_title)

    quality_str = str(job.get("quality") or "LOSSLESS").upper()
    service = job.get("service") or "all"
    meta = job.get("metadata") or {}
    track_num = str(meta.get("track_number") or job.get("track_number") or "")
    disc_num = str(meta.get("disc_number") or job.get("disc_number") or "1")

    discovery_timeout = 25 if is_prefetch else 45
    max_discovery_attempts = 100
    current_magnet = None

    try:
        # 1. STEP 0: INSTANT CACHE
        catalog = _load_catalog(manager)
        album_key = f"{primary_artist.lower()}||{album.lower()}"
        cached_magnet = catalog.get(album_key)
        
        handle = None
        if cached_magnet:
            handle = _register_job_to_torrent(cached_magnet, job_id, manager)
            current_magnet = cached_magnet
            # Fast check health
            time.sleep(0.5)
            s = handle.status()
            if s.num_peers > 0 or not s.active_duration > 15:
                 manager._append_cache_event(job, "trying", f"Step 0: Using cached swarm for: {album}")
            else:
                 manager._append_cache_event(job, "trying", "Step 0: Cached source dead, moving to search...")
                 _unregister_job_from_torrent(current_magnet, job_id)
                 handle = None
                 current_magnet = None

        # 2. DISCOVERY ENGINE
        def do_search_safe(q, svc):
            try:
                if svc == "all": return torrfetch.search_torrents(q, mode="parallel")
                else:
                    try: return torrfetch.search_torrents(q, only=[svc])
                    except: return torrfetch.search_torrents(q, mode="parallel")
            except Exception: return []

        def score_torrent_result(r, target_artist, target_title, target_album):
            torrent_title = r.get("title", "").lower()
            if any(k in torrent_title for k in ["s01","s02","e01","movie","1080p","x264"]): return -1
            
            # Identity Verification
            artist_tokens = set(re.findall(r'\w+', target_artist.lower()))
            title_tokens = set(re.findall(r'\w+', torrent_title))
            meaningful_artist = {t for t in artist_tokens if len(t) >= 2 and t not in {"the","and","feat","with"}}
            if not meaningful_artist: meaningful_artist = artist_tokens
            
            artist_verified = False
            matches = meaningful_artist.intersection(title_tokens)
            if len(meaningful_artist) <= 2:
                if len(matches) >= len(meaningful_artist): artist_verified = True
            elif len(matches) >= (len(meaningful_artist) * 0.7): artist_verified = True
            
            if not artist_verified and target_artist.replace("'", "") in torrent_title: artist_verified = True

            album_verified = False
            if target_album != "unknown":
                if rapidfuzz.fuzz.token_set_ratio(target_album.lower(), torrent_title) > 85: album_verified = True
            
            if not artist_verified and not album_verified: return -1
            
            # Scoring
            score = rapidfuzz.fuzz.token_set_ratio(target_title.lower(), torrent_title)
            score += 40 if artist_verified else 0
            score += 40 if album_verified else 0
            if any(k in torrent_title for k in ["discography", "complete", "collection"]): score += 30
            
            health = int(r.get("seeders") or 0)
            if health > 0:
                import math
                score += math.log10(health) * 15
            return score

        results_pool = []
        if not handle:
            # --- STEP 1: PHASE 1 - TARGETED SEARCH (Clicked Album) ---
            if album != "Unknown":
                manager._append_cache_event(job, "trying", f"Step 1: Searching targeted release: {primary_artist} - {album_clean}")
                p1_queries = [f"{art_var} {album_clean}" for art_var in artist_variations]
                for q in p1_queries:
                    p1_results = do_search_safe(q, service)
                    for r in p1_results:
                        s = score_torrent_result(r, primary_artist, title_clean, album_clean)
                        if s > 50:
                            r["_score"] = s
                            r["_search_album"] = album_clean
                            results_pool.append(r)
                    if results_pool: break
                
                # Check if we have healthy targeted results to skip broad discovery
                if results_pool and any(int(r.get("seeders", 0)) >= 3 for r in results_pool):
                    manager._append_cache_event(job, "trying", "Healthy targeted matches found, skipping broad discovery.")
                else:
                    # --- STEP 2: PHASE 0 - BROAD ARTIST SCAN ---
                    manager._append_cache_event(job, "trying", f"Step 2: Targeted weak, launching broad artist scan for '{primary_artist}'...")
                    for art_var in artist_variations:
                        broad_results = do_search_safe(art_var, service)
                        for r in broad_results:
                            s = score_torrent_result(r, primary_artist, title_clean, album_clean)
                            if s > 65: # High bar for broad
                                r["_score"] = s
                                r["_search_album"] = album_clean
                                results_pool.append(r)

                    # --- STEP 3: PHASE 2 - HIERARCHICAL PARALLEL DISCOVERY ---
                    if not any(int(r.get("seeders", 0)) > 2 for r in results_pool):
                        manager._append_cache_event(job, "trying", "Step 3: Initiating parallel hierarchical discography discovery...")
                        search_candidates = []
                        try:
                            from music_metadata import get_alternative_albums_hierarchical
                            search_candidates.extend(get_alternative_albums_hierarchical(primary_artist, title_clean))
                        except Exception: pass
                        
                        search_candidates = [c for c in search_candidates if c.lower() != album.lower()][:15]
                        search_candidates.append(None) # Track fallback

                        def p2_worker(cand):
                            worker_res = []
                            for art_var in artist_variations:
                                q = f"{art_var} {clean_term(cand)}" if cand else f"{art_var} {title_simple}"
                                res = do_search_safe(q, service)
                                for r in res:
                                    s = score_torrent_result(r, primary_artist, title_clean, cand or album_clean)
                                    if s > 50:
                                        r["_score"] = s
                                        r["_search_album"] = cand or album_clean
                                        worker_res.append(r)
                                if worker_res: break
                            return worker_res

                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as exec:
                            futs = [exec.submit(p2_worker, c) for c in search_candidates]
                            for f in concurrent.futures.as_completed(futs):
                                results_pool.extend(f.result() or [])

            # --- STEP 4: PHASE 3 - HEALTH-WEIGHTED RACE ---
            if not results_pool: raise RuntimeError(f"No valid torrents found for {primary_artist} - {title_clean}.")

            trackers = _get_best_trackers()
            ordered_results = sorted(results_pool, key=lambda x: x.get("_score", 0), reverse=True)

            for r_idx, r in enumerate(ordered_results[:max_discovery_attempts]):
                m_link = r.get("magnet")
                if not m_link: continue
                import urllib.parse
                if "&tr=" not in m_link:
                    for tr in trackers: m_link += f"&tr={urllib.parse.quote(tr)}"
                
                manager._append_cache_event(job, "trying", f"Attaching source #{r_idx+1} (Score: {int(r.get('_score',0))}): {r.get('title')[:35]}...")
                handle = _register_job_to_torrent(m_link, job_id, manager)
                current_magnet = m_link
                for tr in trackers:
                    try: handle.add_tracker(lt.announce_entry(tr))
                    except: pass
                handle.force_reannounce()

                # Health Loop
                meta_start = time.time()
                got_meta = False
                last_log = 0
                while time.time() - meta_start < discovery_timeout:
                    if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                    s = handle.status()
                    r["_live_peers"] = s.num_peers
                    if handle.has_metadata():
                        got_meta = True
                        break
                    if time.time() - last_log > 12:
                        manager._append_cache_event(job, "trying", f"Connecting... ({s.num_peers} peers seen)")
                        last_log = time.time()
                    if time.time() - meta_start > 15 and s.num_peers == 0: break
                    with manager._lock:
                        job["progress"] = 1
                        job["last_status"] = f"Swarm: {s.num_peers} peers, {_GLOBAL_SES.status().dht_nodes} nodes"
                    time.sleep(1.2)
                    
                if not got_meta:
                    manager._append_cache_event(job, "trying", f"Source dead ({r.get('_live_peers', 0)} real peers), trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    handle = None
                    current_magnet = None
                    # RE-SORT based on live peers
                    tried_ids = {ordered_results[i].get("magnet") for i in range(r_idx + 1)}
                    ordered_results.sort(key=lambda x: (x.get("magnet") not in tried_ids, x.get("_live_peers", 0) > 0, x.get("_score", 0)), reverse=True)
                    continue

                # --- STEP 5: PHASE 4 - PRECISION EXTRACTION ---
                torrent_info = handle.get_torrent_info()
                best_f_idx = -1
                best_f_score = -1
                from service_downloader import AUDIO_SUFFIXES
                track_pats = [f"{track_num.zfill(2)}.", f" {track_num.zfill(2)} ", f"- {track_num.zfill(2)} "] if track_num else []
                for i in range(torrent_info.num_files()):
                    f_path = Path(torrent_info.file_at(i).path)
                    if f_path.suffix.lower() in AUDIO_SUFFIXES:
                        score = rapidfuzz.fuzz.token_set_ratio(raw_title, f_path.name)
                        if any(p in f_path.name for p in track_pats): score += 40
                        if f"cd{disc_num}" in str(f_path).lower(): score += 20
                        for kw in ["live", "demo", "remix", "mix", "edit"]:
                            if kw in f_path.name.lower() and kw not in raw_title.lower(): score -= 50
                        if score > best_f_score:
                            best_f_score = score
                            best_f_idx = i

                if best_f_idx == -1 or best_f_score < 40:
                    manager._append_cache_event(job, "trying", "Track missing from source, trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    handle = None
                    current_magnet = None
                    continue
                break

        if not handle: raise RuntimeError("All search attempts failed.")

        # 3. Final Streaming
        torrent_info = handle.get_torrent_info()
        best_f_idx = -1
        best_f_score = -1
        from service_downloader import AUDIO_SUFFIXES
        track_pats = [f"{track_num.zfill(2)}.", f" {track_num.zfill(2)} ", f"- {track_num.zfill(2)} "] if track_num else []
        for i in range(torrent_info.num_files()):
            f_path = Path(torrent_info.file_at(i).path)
            if f_path.suffix.lower() in AUDIO_SUFFIXES:
                score = rapidfuzz.fuzz.token_set_ratio(raw_title, f_path.name)
                if any(p in f_path.name for p in track_pats): score += 40
                if f"cd{disc_num}" in str(f_path).lower(): score += 20
                for kw in ["live", "demo", "remix", "mix", "edit"]:
                    if kw in f_path.name.lower() and kw not in raw_title.lower(): score -= 50
                if score > best_f_score:
                    best_f_score = score
                    best_f_idx = i

        handle.set_sequential_download(True)
        priorities = [0] * torrent_info.num_files()
        priorities[best_f_idx] = 7
        handle.prioritize_files(priorities)
        target_rel = torrent_info.file_at(best_f_idx).path
        target_abs = Path(manager.config.cache_dir) / "torrent_downloads" / target_rel
        manager._append_cache_event(job, "trying", f"Streaming: {Path(target_rel).name}")
        
        start_time = time.time()
        last_progress_time = time.time()
        last_done = 0
        while True:
            if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
            s = handle.status()
            done = handle.file_progress()[best_f_idx]
            total = torrent_info.file_at(best_f_idx).size
            if done > last_done:
                last_done = done
                last_progress_time = time.time()
            prog = (done / total) * 100 if total > 0 else 0
            with manager._lock:
                job["progress"] = int(prog)
                job["last_status"] = f"Streaming: {int(prog)}% ({s.download_rate/1024:.1f}kB/s, {s.num_peers}p)"
            if done >= total and total > 0:
                output_dir.mkdir(parents=True, exist_ok=True)
                final_dest = output_dir / Path(target_rel).name
                for old_file in output_dir.glob("*"):
                    if old_file.is_file(): old_file.unlink()
                shutil.copy2(target_abs, final_dest)
                manager._append_cache_event(job, "provider", f"Torrent engine produced {final_dest.name}")
                if album != "Unknown":
                    catalog[f"{primary_artist.lower()}||{album.lower()}"] = current_magnet
                    _save_catalog(manager, catalog)
                return
            if time.time() - last_progress_time > 65: break
            if time.time() - start_time > 1800: break
            time.sleep(2)
        raise RuntimeError("Stalled.")
    finally:
        if current_magnet: _unregister_job_from_torrent(current_magnet, job_id)
