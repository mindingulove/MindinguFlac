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

_SERVICE_ALIASES = {
    "thepiratebay": "piratebay",
    "tpb": "piratebay",
}


def _normalize_service(value: str) -> str:
    service = (value or "all").strip().lower()
    return _SERVICE_ALIASES.get(service, service)

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
    # Use random port to bypass ISP blocks on 6881
    import random
    port = random.randint(49152, 65534)
    
    settings = {
        'listen_interfaces': f'0.0.0.0:{port},[::]:{port}',
        'enable_dht': True,
        'enable_upnp': True,
        'enable_natpmp': True,
        'enable_lsd': True,
        'active_downloads': 20,
        'active_seeds': 5,
        'active_limit': 30,
        'inactivity_timeout': 30,
        'peer_connect_timeout': 10,
        # Aggressive peer discovery
        'dht_announce_interval': 60,
        'out_enc_policy': 1, # enabled
        'in_enc_policy': 1,  # enabled
        'allowed_enc_level': 2, # both
    }
    s.apply_settings(settings)
    
    # Extra routers for faster bootstrapping
    routers = [
        ("router.bittorrent.com", 6881),
        ("router.utorrent.com", 6881),
        ("dht.transmissionbt.com", 6881),
        ("dht.libtorrent.org", 25401),
        ("router.silence.is", 6881),
    ]
    for r_host, r_port in routers:
        s.add_dht_router(r_host, r_port)
    return s

_GLOBAL_SES = _create_optimized_session()

def _register_job_to_torrent(magnet: str, job_id: str, output_dir: Path, manager) -> tuple:
    with _SESSIONS_LOCK:
        if magnet in _ACTIVE_SESSIONS:
            entry = _ACTIVE_SESSIONS[magnet]
            entry["refs"].add(job_id)
            handle = entry["handle"]
            if handle.is_valid():
                handle.resume()
                return handle, Path(entry["save_path"])
        output_dir.mkdir(parents=True, exist_ok=True)
        params = {
            'save_path': str(output_dir),
            'storage_mode': lt.storage_mode_t(2)
        }
        handle = lt.add_magnet_uri(_GLOBAL_SES, magnet, params)
        _ACTIVE_SESSIONS[magnet] = {"handle": handle, "refs": {job_id}, "save_path": str(output_dir)}
        return handle, output_dir

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

def _dedupe_results(results: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for result in results:
        key = result.get("magnet") or result.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped

def run(output_dir: Path, job: dict, manager) -> None:
    # 0. Setup
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
    # Strip remaster/edition/single suffixes that aren't part of the real album
    # name (e.g. "Empire - Remastered 2003", "... - Single", "... - Deluxe").
    album_clean = re.sub(
        r'\s*[-–]\s*(remaster|remastered|single|ep|deluxe|expanded|anniversary|edition|version|mono|stereo|re-?master).*$',
        '', album_clean, flags=re.IGNORECASE,
    ).strip()
    # When the "album" is really just the track title (a single release), Spotify
    # gave us no real album. Drop it so the MusicBrainz hierarchy below resolves
    # the track's actual album (e.g. "Silent Lucidity" -> "Empire").
    if album_clean and title_clean and album_clean.lower() == title_clean.lower():
        album_clean = ""

    quality_str = str(job.get("quality") or "LOSSLESS").upper()
    service = _normalize_service(job.get("service") or "all")
    track_num = str(job.get("metadata", {}).get("track_number") or job.get("track_number") or "")
    disc_num = str(job.get("metadata", {}).get("disc_number") or job.get("disc_number") or "1")
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}

    def album_looks_like_primary_artist_release() -> bool:
        album_artist = (
            metadata.get("album_artist")
            or metadata.get("albumartist")
            or metadata.get("albumArtist")
            or metadata.get("artist_credit")
            or ""
        )
        if album_artist:
            album_artist_norm = re.sub(r"[^a-z0-9]+", " ", str(album_artist).lower()).strip()
            primary_artist_norm = re.sub(r"[^a-z0-9]+", " ", primary_artist.lower()).strip()
            if "various artists" in album_artist_norm or album_artist_norm == "various":
                return False
            if primary_artist_norm and rapidfuzz.fuzz.token_set_ratio(primary_artist_norm, album_artist_norm) < 80:
                return False

        album_norm = re.sub(r"[^a-z0-9]+", " ", album_clean.lower()).strip()
        compilation_markers = {
            "various artists", "top 40", "top hits", "essential hits", "ultimate hits",
            "now thats what i call", "soundtrack", "motion picture", "original soundtrack",
            "hits 80s", "hits 90s", "hits 00s", "hits 2000s", "anthems",
        }
        return not any(marker in album_norm for marker in compilation_markers)

    discovery_timeout = 60 if is_prefetch else 120
    current_magnet = None
    blacklist: set[str] = set()  # magnets that stalled mid-download

    def _apply_resolved_album(new_album: str) -> None:
        # When the track is found on a different album than Spotify reported
        # (resolved via MusicBrainz), tag/sidecar the saved file with that real
        # album instead of the Spotify single/remaster name.
        if not new_album or new_album.lower() == (album_clean or "").lower():
            return
        with manager._lock:
            job["album"] = new_album
            meta = job.get("metadata")
            if isinstance(meta, dict):
                meta["album"] = new_album
        manager._append_cache_event(job, "provider", f"Using MusicBrainz album: {new_album}")

    try:
        from service_downloader import AUDIO_SUFFIXES

        def audio_file_indexes(torrent_info) -> list[int]:
            indexes = []
            for i in range(torrent_info.num_files()):
                f_path = Path(torrent_info.file_at(i).path)
                if f_path.suffix.lower() in AUDIO_SUFFIXES:
                    indexes.append(i)
            return indexes

        def find_best_audio_file(torrent_info) -> tuple[int, int]:
            best_f_idx = -1
            best_f_score = -1
            track_pats = [f"{track_num.zfill(2)}.", f" {track_num.zfill(2)} ", f"- {track_num.zfill(2)} "] if track_num else []
            for i in range(torrent_info.num_files()):
                f_path = Path(torrent_info.file_at(i).path)
                if f_path.suffix.lower() in AUDIO_SUFFIXES:
                    score = max(
                        rapidfuzz.fuzz.token_set_ratio(raw_title, f_path.name),
                        rapidfuzz.fuzz.token_set_ratio(title_clean, f_path.stem),
                    )
                    if any(p in f_path.name for p in track_pats): score += 40
                    if f"cd{disc_num}" in str(f_path).lower(): score += 20
                    for kw in ["live", "demo", "remix", "mix", "edit"]:
                        if kw in f_path.name.lower() and kw not in raw_title.lower(): score -= 50
                    if score > best_f_score:
                        best_f_score = score
                        best_f_idx = i
            return best_f_idx, best_f_score

        # 1. INSTANT CACHE
        catalog = _load_catalog(manager)
        album_key = f"{primary_artist.lower()}||{album.lower()}"
        cached_magnet = catalog.get(album_key)
        
        handle = None
        torrent_save_path = output_dir
        # The cached-magnet fast path is attempted later, once stream_to_completion
        # is defined (see "INSTANT CACHE attempt" below).

        # 2. DISCOVERY ENGINE
        if not handle:
            def do_search_safe(q, svc):
                results = []
                try:
                    if svc == "all":
                        results = torrfetch.search_torrents(q, mode="parallel") or []
                    else:
                        try: results = torrfetch.search_torrents(q, only=[svc]) or []
                        except: results = torrfetch.search_torrents(q, mode="parallel") or []
                except Exception:
                    results = []
                # Augment torrfetch (TPB-only for music) with extra indexers:
                # apibay (reliable TPB JSON) + knaben aggregator (many trackers).
                try:
                    import torrent_sources
                    results = list(results) + torrent_sources.search_extra(q)
                except Exception:
                    pass
                return results

            def score_torrent_result(r, target_artist, target_title, target_album, allow_album_miss=False):
                torrent_title = r.get("title", "").lower()
                if any(k in torrent_title for k in ["s01","s02","movie","1080p","x264"]): return -1
                category = str(r.get("category") or "").lower()
                if category and category != "unknown" and not any(k in category for k in ["audio", "music"]):
                    return -1
                
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
                target_album = clean_term(target_album).lower()
                if target_album and target_album != "unknown":
                    if rapidfuzz.fuzz.token_set_ratio(target_album.lower(), torrent_title) > 85: album_verified = True
                
                title_score = rapidfuzz.fuzz.token_set_ratio(target_title.lower(), torrent_title)
                if target_album:
                    if not artist_verified and not album_verified:
                        return -1
                    if allow_album_miss and not album_verified and not artist_verified:
                        return -1
                    if not allow_album_miss and not album_verified:
                        return -1
                elif not artist_verified or title_score < 55:
                    return -1
                
                score = title_score
                score += 40 if artist_verified else 0
                score += 60 if album_verified else 20
                if any(k in torrent_title for k in ["discography", "complete", "collection", "albums"]): score += 30
                
                # Audiophile boosts
                if any(k in torrent_title for k in ["24-bit", "96khz", "vinyl", "lp", "eac"]): score += 30
                if "flac" in torrent_title or "lossless" in torrent_title:
                    score += 25
                
                health = int(r.get("seeders") or 0)
                if health > 0:
                    import math
                    score += math.log10(health) * 15
                else:
                    score -= 25
                return score

            trackers = _get_best_trackers()

            def candidate_queries_for_album(album_name: str) -> list[str]:
                album_name = clean_term(album_name)
                if not album_name:
                    return []
                return [f"{art_var} {album_name}" for art_var in artist_variations]

            def candidate_inventory_queries() -> list[str]:
                queries = []
                suffixes = ["", "albums", "collection", "discography", "FLAC", "lossless"]
                for art_var in artist_variations:
                    for suffix in suffixes:
                        queries.append(f"{art_var} {suffix}".strip())
                return list(dict.fromkeys(queries))

            def stream_to_completion(handle, magnet) -> bool:
                # Download the best matching file to completion. Returns True on
                # success (file placed in output_dir), False if the swarm stalls
                # so the caller can fall back to the next candidate torrent.
                torrent_info = handle.get_torrent_info()
                best_f_idx, best_f_score = find_best_audio_file(torrent_info)
                if best_f_idx == -1 or best_f_score < 40:
                    return False

                handle.set_sequential_download(True)
                priorities = [0] * torrent_info.num_files(); priorities[best_f_idx] = 7
                handle.prioritize_files(priorities)
                # Do NOT rename_file: the torrent session can be shared across
                # jobs (swarm reuse); renaming would move the file out from under
                # another job streaming the same torrent. Copy on completion.
                target_abs = torrent_save_path / torrent_info.file_at(best_f_idx).path
                target_size = torrent_info.file_at(best_f_idx).size
                with manager._lock:
                    job["active_audio_path"] = str(target_abs)
                    job["active_audio_size"] = target_size
                    job["active_audio_ready_bytes"] = 0
                manager._append_cache_event(job, "trying", f"Streaming: {target_abs.name}")

                start_time = time.time(); last_progress_time = time.time(); last_done = 0
                while True:
                    if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                    s = handle.status()
                    done = handle.file_progress()[best_f_idx]
                    total = torrent_info.file_at(best_f_idx).size
                    if done > last_done:
                        last_done = done; last_progress_time = time.time()
                    prog = (done / total) * 100 if total > 0 else 0
                    with manager._lock:
                        job["progress"] = int(prog)
                        job["last_status"] = f"Streaming: {int(prog)}% ({s.download_rate/1024:.1f}kB/s, {s.num_peers}p)"
                        job["active_audio_path"] = str(target_abs)
                        job["active_audio_size"] = total
                        job["active_audio_ready_bytes"] = done
                    if done >= total and total > 0:
                        # Copy the single requested file (flattened) into this
                        # job's own output_dir so _find_audio_files locates it
                        # regardless of any torrent subdirectory or shared
                        # session save_path.
                        output_dir.mkdir(parents=True, exist_ok=True)
                        final_dest = output_dir / target_abs.name
                        if target_abs.resolve() != final_dest.resolve():
                            # Only replace a same-named file; never wipe the dir,
                            # which for download mode is the shared album folder.
                            if final_dest.exists():
                                try: final_dest.unlink()
                                except Exception: pass
                            shutil.copy2(target_abs, final_dest)
                        manager._append_cache_event(job, "provider", f"Torrent engine produced {final_dest.name}")
                        if album != "Unknown":
                            catalog[f"{primary_artist.lower()}||{album.lower()}"] = magnet
                            _save_catalog(manager, catalog)
                        return True
                    # Stall detection (only when NOT making progress):
                    #   - no progress at all for 120s, or
                    #   - peers dropped to 0 and no progress for 60s.
                    # As long as bytes keep arriving, last_progress_time updates
                    # and we never abandon an actively-downloading source.
                    since_progress = time.time() - last_progress_time
                    stalled = since_progress > 120
                    if not stalled and s.num_peers == 0 and since_progress > 60:
                        stalled = True
                    if stalled: return False
                    if time.time() - start_time > 1800: return False
                    time.sleep(2)

            def try_result_source(r: dict, r_idx: int, phase_label: str, require_track_list: bool):
                nonlocal current_magnet, torrent_save_path
                m_link = r.get("magnet")
                if not m_link:
                    return None
                if m_link in blacklist:
                    return None
                import urllib.parse
                if "&tr=" not in m_link:
                    for tr in trackers:
                        m_link += f"&tr={urllib.parse.quote(tr)}"

                manager._append_cache_event(
                    job,
                    "trying",
                    f"{phase_label} source #{r_idx+1} (Score: {int(r.get('_score',0))}): {r.get('title','')[:35]}...",
                )
                candidate_handle, torrent_save_path = _register_job_to_torrent(m_link, job_id, output_dir, manager)
                current_magnet = m_link
                for tr in trackers:
                    try: candidate_handle.add_tracker(lt.announce_entry(tr))
                    except: pass
                candidate_handle.force_reannounce()

                meta_start = time.time()
                got_meta = False
                max_seen = 0
                while True:
                    if job_id in manager._cancel_flags:
                        raise RuntimeError("Cancelled")
                    s = candidate_handle.status()
                    num_p = s.num_peers
                    if num_p > max_seen:
                        max_seen = num_p
                    if candidate_handle.has_metadata():
                        got_meta = True
                        break

                    elapsed = time.time() - meta_start
                    # Scale metadata patience to swarm health. A source that
                    # can't deliver its file list quickly with few peers is
                    # almost certainly dead, so cycle to the next candidate fast.
                    # (Active downloads, which already have metadata, get far
                    # more patience in the streaming loop.)
                    if max_seen == 0:
                        meta_budget = 15 if _GLOBAL_SES.status().dht_nodes > 100 else discovery_timeout
                    elif max_seen <= 1:
                        meta_budget = 25   # single weak peer
                    elif max_seen <= 4:
                        meta_budget = 45
                    else:
                        meta_budget = 60
                    if elapsed > meta_budget:
                        break
                    if elapsed % 15 < 1.5:
                        candidate_handle.force_reannounce()

                    with manager._lock:
                        job["progress"] = 1
                        job["last_status"] = f"Swarm: {num_p}p ({max_seen} max), Nodes: {_GLOBAL_SES.status().dht_nodes}"
                    time.sleep(1.2)

                if not got_meta:
                    manager._append_cache_event(job, "trying", f"Source unresponsive ({max_seen} real peers seen), trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    current_magnet = None
                    return None

                torrent_info = candidate_handle.get_torrent_info()
                audio_indexes = audio_file_indexes(torrent_info)
                if require_track_list and len(audio_indexes) < 2:
                    manager._append_cache_event(job, "trying", "Source has a single album audio file, trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    current_magnet = None
                    return None

                best_f_idx, best_f_score = find_best_audio_file(torrent_info)
                if best_f_idx == -1 or best_f_score < 40:
                    manager._append_cache_event(job, "trying", "Track not in source, trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    current_magnet = None
                    return None
                # Actually download it now. If the swarm stalls mid-download,
                # blacklist this magnet and let the phase loop try the next one.
                if stream_to_completion(candidate_handle, current_magnet):
                    return candidate_handle
                manager._append_cache_event(job, "trying", "Source stalled mid-download, trying next...")
                blacklist.add(current_magnet)
                _unregister_job_from_torrent(current_magnet, job_id)
                current_magnet = None
                return None

            def run_search_phase(
                phase_label: str,
                target_album: str,
                queries: list[str],
                max_sources: int = 40,
                allow_album_miss: bool = False,
                require_track_list: bool = True,
            ):
                manager._append_cache_event(job, "trying", f"{phase_label}: searching {len(queries)} artist-qualified query(s)")
                phase_results = []
                if queries:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(queries))) as exec:
                        futures = {exec.submit(do_search_safe, q, service): q for q in queries}
                        for future in concurrent.futures.as_completed(futures):
                            for r in future.result() or []:
                                score = score_torrent_result(
                                    r,
                                    primary_artist,
                                    title_clean,
                                    target_album,
                                    allow_album_miss=allow_album_miss,
                                )
                                if score > 50:
                                    item = dict(r)
                                    item["_score"] = score
                                    item["_search_album"] = target_album
                                    item["_query"] = futures[future]
                                    phase_results.append(item)

                phase_results = _dedupe_results(phase_results)
                if not phase_results:
                    manager._append_cache_event(job, "trying", f"{phase_label}: no matching torrents")
                    return None

                ordered_results = sorted(
                    phase_results,
                    key=lambda x: (int(x.get("seeders") or 0) > 0, x.get("_score", 0), int(x.get("seeders") or 0)),
                    reverse=True,
                )
                for r_idx, result in enumerate(ordered_results[:max_sources]):
                    winner = try_result_source(result, r_idx, phase_label, require_track_list=require_track_list)
                    if winner:
                        return winner
                return None

            # INSTANT CACHE attempt: reuse the known-good magnet for this album.
            if cached_magnet and cached_magnet not in blacklist:
                handle, torrent_save_path = _register_job_to_torrent(cached_magnet, job_id, output_dir, manager)
                current_magnet = cached_magnet
                time.sleep(0.5)
                if handle.status().num_peers > 0:
                    manager._append_cache_event(job, "trying", f"Step 0: Reusing swarm for: {album}")
                    if stream_to_completion(handle, current_magnet):
                        return
                blacklist.add(cached_magnet)
                _unregister_job_from_torrent(current_magnet, job_id)
                handle = None
                current_magnet = None

            # 1. Search the clicked album DIRECTLY first. This is the album the
            #    user saw when pressing play, with correct metadata + cover. If
            #    it's found here we keep the Spotify metadata and never touch
            #    MusicBrainz or the broad discography sweep.
            if album_clean:
                handle = run_search_phase(
                    "Clicked album",
                    album_clean,
                    candidate_queries_for_album(album_clean),
                )

            # 2. Clicked album failed (or was a single with no real album):
            #    resolve the track's real album(s) via MusicBrainz and search
            #    each one, applying that album's metadata when a match is found.
            if not handle:
                manager._append_cache_event(job, "trying", "Clicked album failed; checking MusicBrainz album hierarchy...")
                try:
                    from music_metadata import get_alternative_albums_hierarchical
                    alternative_albums = get_alternative_albums_hierarchical(primary_artist, title_clean)
                except Exception:
                    alternative_albums = []
                seen_albums = {clean_term(album_clean).lower()}
                for alt_album in alternative_albums:
                    alt_clean = clean_term(alt_album)
                    if not alt_clean or alt_clean.lower() in seen_albums:
                        continue
                    seen_albums.add(alt_clean.lower())
                    handle = run_search_phase(
                        f"MusicBrainz album: {alt_clean}",
                        alt_clean,
                        candidate_queries_for_album(alt_clean),
                    )
                    if handle:
                        _apply_resolved_album(alt_clean)
                        break

            # 3. Last resort: broad artist-inventory sweep (any release that may
            #    contain the track). Demoted below targeted searches and capped
            #    so it can't grind through the whole discography.
            if not handle and album_clean and album_looks_like_primary_artist_release():
                handle = run_search_phase(
                    "Artist inventory (broad fallback)",
                    album_clean,
                    candidate_inventory_queries(),
                    max_sources=20,
                    allow_album_miss=True,
                )

            if not handle:
                broad_phases = [
                    ("Artist albums", "album", ["discography"]),
                    ("Artist compilations", "compilation", ["compilation", "greatest hits", "best of", "collection"]),
                    ("Artist live releases", "live", ["live"]),
                ]
                for phase_label, target_album, suffixes in broad_phases:
                    queries = [f"{art_var} {suffix}" for art_var in artist_variations for suffix in suffixes]
                    handle = run_search_phase(phase_label, target_album, queries)
                    if handle:
                        break

            if not handle:
                queries = [f"{art_var} {title_clean}" for art_var in artist_variations if title_clean]
                handle = run_search_phase("Track fallback", "", queries, max_sources=60, require_track_list=False)

        # Each candidate is downloaded to completion inside try_result_source;
        # a truthy handle here means the file was already produced. A falsy
        # handle means every candidate failed or stalled.
        if not handle:
            raise RuntimeError("All sources failed or stalled.")
    finally:
        if current_magnet: _unregister_job_from_torrent(current_magnet, job_id)
