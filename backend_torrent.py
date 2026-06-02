from __future__ import annotations

import logging
import os
import time
import threading
import shutil
import re
import concurrent.futures
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import torrfetch
try:
    import libtorrent as lt
except (ImportError, OSError) as _lt_exc:
    # On Windows the win_amd64 libtorrent wheel needs the x64 VC++ runtime,
    # which is absent on a fresh Windows-on-ARM box. Try to install it, then
    # retry the import; if that's not possible this raises an actionable,
    # link-bearing error that the cache-job UI surfaces to the user.
    from vcredist import ensure_vc_redist_for_libtorrent
    ensure_vc_redist_for_libtorrent(_lt_exc)
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
        # Aggressive connection limits
        'active_downloads': 30,
        'active_seeds': 5,
        'active_limit': 50,
        'connections_limit': 400,
        'peer_connect_timeout': 5,
        'connection_speed': 100,
        'inactivity_timeout': 45,
        # High throughput & caching optimizations
        'disk_io_write_mode': 2, # disable_os_cache
        'disk_io_read_mode': 2,  # disable_os_cache
        'max_queued_disk_bytes': 10 * 1024 * 1024,
        'cache_size': 512, # 512 * 16KB = 8MB cache
        'send_buffer_watermark': 3 * 1024 * 1024,
        'recv_socket_buffer_size': 2 * 1024 * 1024,
        'send_socket_buffer_size': 2 * 1024 * 1024,
        'mixed_mode_algorithm': 1, # prefer_tcp
        # Aggressive peer discovery & requesting
        'dht_announce_interval': 30,
        'min_announce_interval': 60,
        'choking_algorithm': 1, # rate_based_choker
        'seed_choking_algorithm': 1, # fastest_upload
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

def _torrent_key(magnet: str) -> str:
    try:
        parsed = urlparse(magnet)
        xt_values = parse_qs(parsed.query).get("xt") or []
        for xt in xt_values:
            lower_xt = xt.lower()
            if lower_xt.startswith("urn:btih:"):
                return lower_xt
    except Exception:
        pass
    return magnet

def _register_job_to_torrent(magnet: str, job_id: str, output_dir: Path, manager) -> tuple:
    key = _torrent_key(magnet)
    with _SESSIONS_LOCK:
        if key in _ACTIVE_SESSIONS:
            entry = _ACTIVE_SESSIONS[key]
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
        _ACTIVE_SESSIONS[key] = {"handle": handle, "refs": {job_id}, "save_path": str(output_dir)}
        return handle, output_dir

def _unregister_job_from_torrent(magnet: str, job_id: str):
    key = _torrent_key(magnet)
    with _SESSIONS_LOCK:
        if key not in _ACTIVE_SESSIONS: return
        entry = _ACTIVE_SESSIONS[key]
        entry["refs"].discard(job_id)
        if not entry["refs"]:
            handle = entry["handle"]
            if handle.is_valid():
                _GLOBAL_SES.remove_torrent(handle)
            del _ACTIVE_SESSIONS[key]

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

    discovery_timeout = 120
    current_magnet = None
    blacklist: set[str] = set()  # magnets that are dead/wrong; never retry
    # magnets that stalled but had real progress on the correct file: counted
    # so they get a bounded number of resume attempts before being blacklisted.
    stall_retry_counts: dict[str, int] = {}

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
            
            # Words that MUST appear for the match to be considered valid
            title_tokens = set(re.findall(r'\w+', title_clean.lower()))
            meaningful_tokens = {t for t in title_tokens if len(t) > 2 and t not in {"the", "and", "feat", "with"}}
            if not meaningful_tokens: meaningful_tokens = title_tokens

            for i in range(torrent_info.num_files()):
                f_path = Path(torrent_info.file_at(i).path)
                if f_path.suffix.lower() in AUDIO_SUFFIXES:
                    f_name_lower = f_path.name.lower()
                    title_score = max(
                        rapidfuzz.fuzz.token_set_ratio(raw_title, f_path.name),
                        rapidfuzz.fuzz.token_set_ratio(title_clean, f_path.stem),
                    )
                    # Significant word check: a majority of meaningful words from target MUST exist in the filename.
                    # We check the filename stem specifically to avoid "Sirius" matching "Eye in the Sky"
                    # just because it's inside a folder named "Eye in the Sky".
                    filename_tokens = set(re.findall(r'\w+', f_path.stem.lower()))
                    match_count = sum(1 for t in meaningful_tokens if t in filename_tokens)
                    match_ratio = match_count / len(meaningful_tokens) if meaningful_tokens else 1.0
                    
                    if match_ratio < 0.7:
                        # Fallback: if the filename is very short (e.g. "01.flac"), check the immediate parent folder too
                        parent_tokens = set(re.findall(r'\w+', f_path.parent.name.lower())) if f_path.parent.name else set()
                        combined_tokens = filename_tokens.union(parent_tokens)
                        match_count = sum(1 for t in meaningful_tokens if t in combined_tokens)
                        match_ratio = match_count / len(meaningful_tokens) if meaningful_tokens else 1.0
                        if match_ratio < 0.7:
                            continue

                    if title_score < 62:
                    
                    score = title_score
                    if any(p in f_path.name for p in track_pats): score += 40
                    if f"cd{disc_num}" in str(f_path).lower(): score += 20
                    for kw in ["live", "demo", "remix", "mix", "edit"]:
                        if kw in f_name_lower and kw not in raw_title.lower(): score -= 50
                    
                    if score > best_f_score:
                        best_f_score = score
                        best_f_idx = i
            return best_f_idx, best_f_score

        def score_metadata_candidate(torrent_info, result: dict, target_album: str, require_track_list: bool):
            audio_indexes = audio_file_indexes(torrent_info)
            if require_track_list and len(audio_indexes) < 2:
                return None, "Single-file album"

            best_f_idx, best_f_score = find_best_audio_file(torrent_info)
            if best_f_idx == -1 or best_f_score < 60:
                return None, "Track not found"

            target_album_clean = clean_term(target_album).lower()
            generic_targets = {"", "unknown", "album", "complete", "discography", "compilation", "live", "other"}
            album_is_specific = target_album_clean not in generic_targets and len(target_album_clean) >= 4
            album_score = 0

            if target_album_clean:
                album_candidates = [str(result.get("title") or "")]
                try:
                    album_candidates.append(str(torrent_info.name()))
                except Exception:
                    pass
                for idx in audio_indexes:
                    f_path = Path(torrent_info.file_at(idx).path)
                    album_candidates.extend(str(part) for part in f_path.parts[:-1])
                    if f_path.parent and str(f_path.parent) != ".":
                        album_candidates.append(str(f_path.parent))

                for candidate in album_candidates:
                    candidate = candidate.lower()
                    if candidate:
                        album_score = max(album_score, rapidfuzz.fuzz.token_set_ratio(target_album_clean, candidate))

            if album_is_specific and album_score < 55 and best_f_score < 90:
                return None, f"Album mismatch ({int(album_score)}%)"

            score = (best_f_score * 2) + (album_score * 2) + (float(result.get("_score") or 0) * 0.25)
            if album_is_specific:
                if album_score >= 80:
                    score += 220
                elif album_score >= 65:
                    score += 120
                elif album_score < 55:
                    score -= 100
            if int(result.get("seeders") or 0) > 0:
                score += min(int(result.get("seeders") or 0), 50)

            return {
                "score": score,
                "file_index": best_f_idx,
                "file_score": best_f_score,
                "album_score": album_score,
            }, None

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
                import torrent_sources
                try:
                    if svc == "all":
                        results = torrfetch.search_torrents(q, mode="parallel") or []
                        # Augment torrfetch with extra indexers
                        results = list(results) + torrent_sources.search_extra(q)
                    elif svc == "1337x":
                        results = torrent_sources.search_1337x(q)
                    elif svc == "kickass":
                        results = torrent_sources.search_kickass(q)
                    else:
                        try: results = torrfetch.search_torrents(q, only=[svc]) or []
                        except: results = torrfetch.search_torrents(q, mode="parallel") or []
                        # Still add extra sources as fallback/augmentation even for specific TPB/YTS
                        results = list(results) + torrent_sources.search_extra(q)
                except Exception:
                    pass
                return results

            def score_torrent_result(r, target_artist, target_title, target_album, allow_album_miss=False):
                torrent_title = r.get("title", "").lower()
                if any(k in torrent_title for k in ["s01","s02","movie","1080p","x264","h264","mp4","mkv","dvdrip","brrip","videograffitti"]): return -1
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
                
                # Massive Audiophile boost
                if any(k in torrent_title for k in ["flac", "lossless", "24-bit", "96khz", "alac", "eac"]):
                    score += 250
                
                # Penalty for video keywords
                if any(k in torrent_title for k in ["1080p", "720p", "x264", "h264", "brrip", "dvdrip", "videograffitti"]):
                    score -= 500

                health = int(r.get("seeders") or 0)
                if health > 0:
                    import math
                    score += math.log10(health) * 20
                else:
                    score -= 100
                return score

            trackers = _get_best_trackers()

            def candidate_queries_for_album(album_name: str) -> list[str]:
                album_name = clean_term(album_name)
                if not album_name:
                    return []
                # Lead with "<artist> <album>" so a short/generic artist name
                # (e.g. "Skank") doesn't pull unrelated junk; keep the bare
                # album as a fallback for releases credited to another artist.
                queries = [f"{art} {album_name}".strip() for art in artist_variations if art]
                queries.append(album_name)
                return list(dict.fromkeys(queries))

            def candidate_inventory_queries() -> list[str]:
                queries = []
                suffixes = ["", "albums", "collection", "discography", "FLAC", "lossless"]
                for art_var in artist_variations:
                    for suffix in suffixes:
                        queries.append(f"{art_var} {suffix}".strip())
                return list(dict.fromkeys(queries))

            def stream_to_completion(handle, magnet, save_path: Path | None = None) -> bool:
                # Download the best matching file to completion. Returns True on
                # success (file placed in output_dir), False if the swarm stalls
                # so the caller can fall back to the next candidate torrent.
                if not handle.is_valid():
                    manager._append_cache_event(job, "trying", "Source handle expired before streaming, trying next...")
                    return False
                save_path = save_path or torrent_save_path
                try:
                    torrent_info = handle.get_torrent_info()
                except Exception as exc:
                    manager._append_cache_event(job, "trying", f"Source metadata became unavailable, trying next: {exc}")
                    return False
                best_f_idx, best_f_score = find_best_audio_file(torrent_info)
                if best_f_idx == -1 or best_f_score < 60:
                    return False

                try:
                    handle.set_sequential_download(True)
                    priorities = [0] * torrent_info.num_files(); priorities[best_f_idx] = 7
                    handle.prioritize_files(priorities)
                except Exception as exc:
                    manager._append_cache_event(job, "trying", f"Source could not be prioritized, trying next: {exc}")
                    return False
                # Do NOT rename_file: the torrent session can be shared across
                # jobs (swarm reuse); renaming would move the file out from under
                # another job streaming the same torrent. Copy on completion.
                target_abs = save_path / torrent_info.file_at(best_f_idx).path
                target_size = torrent_info.file_at(best_f_idx).size
                with manager._lock:
                    job["active_audio_path"] = str(target_abs)
                    job["active_audio_size"] = target_size
                    job["active_audio_ready_bytes"] = 0
                manager._append_cache_event(job, "trying", f"Streaming: {target_abs.name}")

                def finalize_selected_file() -> bool:
                    if not target_abs.exists():
                        return False
                    # Completeness MUST be judged by bytes actually downloaded,
                    # not file size: sparse storage (storage_mode_t(2)) allocates
                    # the full size up front, so st_size == target_size even when
                    # pieces are still missing. Without this, a handle that dies
                    # mid-download would "finalize" a sparse, hole-riddled file
                    # (no FLAC header, unplayable) into the library.
                    if last_done < target_size:
                        return False
                    try:
                        if target_abs.stat().st_size < target_size:
                            return False
                        # Defense-in-depth: a finished audio file never begins
                        # with a run of zero bytes. A zero head means the first
                        # piece is a sparse hole, i.e. the download is incomplete.
                        with open(target_abs, "rb") as fh:
                            head = fh.read(16)
                        if not head or head == b"\x00" * len(head):
                            return False
                    except OSError:
                        return False
                    output_dir.mkdir(parents=True, exist_ok=True)
                    final_dest = output_dir / target_abs.name
                    if target_abs.resolve() != final_dest.resolve():
                        if final_dest.exists():
                            try: final_dest.unlink()
                            except Exception: pass
                        shutil.copy2(target_abs, final_dest)
                    manager._append_cache_event(job, "provider", f"Torrent engine produced {final_dest.name}")
                    if album != "Unknown":
                        catalog[f"{primary_artist.lower()}||{album.lower()}"] = magnet
                        _save_catalog(manager, catalog)
                    return True

                start_time = time.time(); last_progress_time = time.time(); last_done = 0
                reannounced_once = False
                reacquire_attempts = 0
                while True:
                    if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                    if not handle.is_valid():
                        if finalize_selected_file():
                            return True
                        # A libtorrent handle can go invalid mid-stream from
                        # session churn (GEMINI.md: treat as retryable, not
                        # fatal). Re-add the SAME magnet and resume from the
                        # partial data already on disk before abandoning a
                        # confirmed high-quality match for worse candidates.
                        if reacquire_attempts < 3:
                            reacquire_attempts += 1
                            manager._append_cache_event(job, "trying", f"Source handle expired; re-acquiring same source (attempt {reacquire_attempts}/3)...")
                            handle, _ = _register_job_to_torrent(magnet, job_id, output_dir, manager)
                            meta_wait = time.time()
                            while time.time() - meta_wait < 20:
                                if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                                if handle.is_valid() and handle.has_metadata():
                                    break
                                time.sleep(0.5)
                            if handle.is_valid() and handle.has_metadata():
                                try:
                                    torrent_info = handle.get_torrent_info()
                                    handle.set_sequential_download(True)
                                    priorities = [0] * torrent_info.num_files(); priorities[best_f_idx] = 7
                                    handle.prioritize_files(priorities)
                                    last_progress_time = time.time()
                                    continue
                                except Exception:
                                    pass
                        manager._append_cache_event(job, "trying", "Source handle expired during streaming, trying next...")
                        return False
                    try:
                        s = handle.status()
                        done = handle.file_progress()[best_f_idx]
                    except Exception as exc:
                        if finalize_selected_file():
                            return True
                        manager._append_cache_event(job, "trying", f"Source became unavailable during streaming, trying next: {exc}")
                        return False
                    total = torrent_info.file_at(best_f_idx).size
                    if done > last_done:
                        last_done = done; last_progress_time = time.time()
                    elif s.download_payload_rate > 0 or s.download_rate > 0:
                        last_progress_time = time.time()
                    prog = (done / total) * 100 if total > 0 else 0
                    with manager._lock:
                        job["progress"] = int(prog)
                        job["last_status"] = f"Streaming: {int(prog)}% ({s.download_rate/1024:.1f}kB/s, {s.num_peers}p)"
                        job["active_audio_path"] = str(target_abs)
                        job["active_audio_size"] = total
                        job["active_audio_ready_bytes"] = done
                    if done >= total and total > 0:
                        return finalize_selected_file()
                    # Stall handling. Don't abandon a source the instant bytes
                    # pause: first re-announce to wake a quiet swarm, and stay
                    # patient. Only give up after the extended budget.
                    since_progress = time.time() - last_progress_time
                    if since_progress > 30 and not reannounced_once:
                        try:
                            for tr in trackers:
                                handle.add_tracker(lt.announce_entry(tr))
                        except Exception:
                            pass
                        try:
                            handle.force_reannounce()
                        except Exception:
                            pass
                        reannounced_once = True
                        manager._append_cache_event(job, "trying", f"Streaming stalled {int(since_progress)}s ({s.num_peers}p); re-announcing once to wake swarm...")
                    max_stall = 120
                    no_peer_stall = 60
                    stalled = since_progress > max_stall
                    if not stalled and s.num_peers == 0 and since_progress > no_peer_stall:
                        stalled = True
                    if stalled:
                        if last_done > 0:
                            key = _torrent_key(magnet)
                            stall_retry_counts[key] = stall_retry_counts.get(key, 0) + 1
                            limit = 1
                            if stall_retry_counts[key] <= limit:
                                manager._append_cache_event(job, "trying", "Source stalled but had progress; keeping it as a fallback to resume later...")
                                return None
                        manager._append_cache_event(job, "trying", f"Source stalled after {int(since_progress)}s; moving to next candidate.")
                        return False
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
                    # Scale metadata patience to swarm health.
                    if max_seen == 0:
                        meta_budget = 15 if _GLOBAL_SES.status().dht_nodes > 100 else discovery_timeout
                    elif max_seen <= 2:
                        # Give small swarms more time
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
                if best_f_idx == -1 or best_f_score < 60:
                    manager._append_cache_event(job, "trying", "Track not in source, trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    current_magnet = None
                    return None
                # Actually download it now. False = dead/wrong -> blacklist;
                # None = stalled with real progress -> keep retryable (resume).
                _scr = stream_to_completion(candidate_handle, current_magnet, torrent_save_path)
                if _scr:
                    return candidate_handle
                if _scr is False:
                    blacklist.add(current_magnet)
                    manager._append_cache_event(job, "trying", "Source stalled mid-download, trying next...")
                else:
                    manager._append_cache_event(job, "trying", "Source stalled but kept as fallback, trying next...")
                _unregister_job_from_torrent(current_magnet, job_id)
                current_magnet = None
                return None

            resolved_album_from_search = None

            def run_search_phase(
                phase_label: str,
                target_album: str,
                queries: list,
                max_sources: int = 40,
                allow_album_miss: bool = False,
                require_track_list: bool = True,
                apply_search_album: bool = False,
            ):
                nonlocal current_magnet, resolved_album_from_search
                query_specs = []
                for query_entry in queries:
                    if isinstance(query_entry, dict):
                        query_text = str(query_entry.get("query") or "").strip()
                        query_album = clean_term(query_entry.get("album") or target_album)
                    elif isinstance(query_entry, (tuple, list)) and len(query_entry) >= 2:
                        query_text = str(query_entry[0] or "").strip()
                        query_album = clean_term(query_entry[1] or target_album)
                    else:
                        query_text = str(query_entry or "").strip()
                        query_album = target_album
                    if query_text:
                        query_specs.append((query_text, query_album))

                manager._append_cache_event(job, "trying", f"{phase_label}: searching {len(query_specs)} torrent query(s)")
                phase_results = []
                if query_specs:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(query_specs))) as exec:
                        futures = {exec.submit(do_search_safe, q, service): (q, query_album) for q, query_album in query_specs}
                        for future in concurrent.futures.as_completed(futures):
                            query_text, query_album = futures[future]
                            for r in future.result() or []:
                                score = score_torrent_result(
                                    r,
                                    primary_artist,
                                    title_clean,
                                    query_album,
                                    allow_album_miss=allow_album_miss,
                                )
                                if score > 50:
                                    item = dict(r)
                                    item["_score"] = score
                                    item["_search_album"] = query_album
                                    item["_query"] = query_text
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
                
                # --- WINDOWED PARALLEL DISCOVERY ---
                # Probe a batch of candidates in parallel, then choose the best
                # metadata match by album + track instead of taking the first
                # torrent that responds.
                window_size = 8
                results_to_try = ordered_results[:max_sources]
                
                for i in range(0, len(results_to_try), window_size):
                    window = results_to_try[i : i + window_size]
                    manager._append_cache_event(job, "trying", f"{phase_label}: probing batch of {len(window)} torrents...")
                    
                    # 1. Register all magnets in the current window
                    active_window_handles = []
                    active_window_keys = set()
                    for r_idx, r in enumerate(window):
                        m_link = r.get("magnet")
                        if not m_link or m_link in blacklist: continue
                        
                        # Add trackers if missing
                        import urllib.parse
                        if "&tr=" not in m_link:
                            for tr in trackers: m_link += f"&tr={urllib.parse.quote(tr)}"

                        m_key = _torrent_key(m_link)
                        if m_key in active_window_keys:
                            continue
                        active_window_keys.add(m_key)
                        
                        h, save_path = _register_job_to_torrent(m_link, job_id, output_dir, manager)
                        for tr in trackers: 
                            try: h.add_tracker(lt.announce_entry(tr))
                            except: pass
                        h.force_reannounce()
                        active_window_handles.append((h, m_link, r, i + r_idx, save_path))

                    # 2. Collect metadata from the batch, then choose the best
                    # album+track match. The first torrent to expose metadata is
                    # often not the right album.
                    start_wait = time.time()
                    metadata_candidates = []
                    scored_magnets = set()
                    # Budget is shorter for parallel probing to keep the UI snappy
                    probe_budget = 25 
                    
                    while time.time() - start_wait < probe_budget:
                        if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                        
                        for h, m, r, r_idx, save_path in active_window_handles:
                            try:
                                if not h.is_valid():
                                    continue
                                if not h.has_metadata():
                                    continue
                                if m in scored_magnets:
                                    continue

                                # Found metadata!
                                torrent_info = h.get_torrent_info()
                                candidate_score, skip_reason = score_metadata_candidate(
                                    torrent_info,
                                    r,
                                    r.get("_search_album") or target_album,
                                    require_track_list=require_track_list,
                                )
                                scored_magnets.add(m)

                                if candidate_score:
                                    metadata_candidates.append((candidate_score["score"], h, m, r, r_idx, save_path, candidate_score))
                                    manager._append_cache_event(
                                        job,
                                        "trying",
                                        f"Source #{r_idx+1} scored {int(candidate_score['score'])}: album {int(candidate_score['album_score'])}%, file {int(candidate_score['file_score'])}%...",
                                    )
                                else:
                                    # Metadata was found but it's the wrong torrent/contents.
                                    # Kill it immediately so libtorrent focuses on others.
                                    manager._append_cache_event(job, "trying", f"Source #{r_idx+1} rejected: {skip_reason}")
                                    _unregister_job_from_torrent(m, job_id)
                                    active_window_handles = [x for x in active_window_handles if x[1] != m]
                                    break # back to the while loop
                            except Exception as exc:
                                manager._append_cache_event(job, "trying", f"Source #{r_idx+1} probe failed: {exc}")
                                _unregister_job_from_torrent(m, job_id)
                                active_window_handles = [x for x in active_window_handles if x[1] != m]
                                break
                        
                        if metadata_candidates and len(scored_magnets) >= len(active_window_handles):
                            break
                        if not active_window_handles: break
                        time.sleep(1.0)

                    if metadata_candidates:
                        metadata_candidates.sort(key=lambda item: item[0], reverse=True)
                        _score, h, m, selected_result, selected_idx, save_path, selected_meta = metadata_candidates[0]
                        manager._append_cache_event(
                            job,
                            "trying",
                            f"Selected source #{selected_idx+1}: {selected_result.get('title','')[:45]} (album {int(selected_meta['album_score'])}%, file {int(selected_meta['file_score'])}%)",
                        )
                        selected_key = _torrent_key(m)
                        for _h_other, m_other, _r_other, _r_idx_other, _save_path_other in active_window_handles:
                            if _torrent_key(m_other) != selected_key:
                                _unregister_job_from_torrent(m_other, job_id)

                        current_magnet = m
                        torrent_save_path = save_path
                        _scr = stream_to_completion(h, m, save_path)
                        if _scr:
                            if apply_search_album:
                                resolved_album_from_search = selected_result.get("_search_album") or target_album
                            return h

                        if _scr is False:
                            blacklist.add(m)
                        _unregister_job_from_torrent(m, job_id)
                        current_magnet = None
                        active_window_handles = [x for x in active_window_handles if x[1] != m]
                        continue
                    
                    # Window timeout - clean up anything remaining
                    for h, m, r, r_idx, save_path in active_window_handles:
                        _unregister_job_from_torrent(m, job_id)

                return None

            # INSTANT CACHE attempt: reuse the known-good magnet for this album.
            if cached_magnet and cached_magnet not in blacklist:
                handle, torrent_save_path = _register_job_to_torrent(cached_magnet, job_id, output_dir, manager)
                current_magnet = cached_magnet
                time.sleep(0.5)
                if handle.status().num_peers > 0:
                    manager._append_cache_event(job, "trying", f"Step 0: Reusing swarm for: {album}")
                    _scr = stream_to_completion(handle, current_magnet, torrent_save_path)
                    if _scr:
                        return
                    # Only blacklist on a hard failure; a stalled-with-progress
                    # cache magnet (None) stays retryable so a later phase resumes.
                    if _scr is False:
                        blacklist.add(cached_magnet)
                else:
                    blacklist.add(cached_magnet)
                _unregister_job_from_torrent(current_magnet, job_id)
                handle = None
                current_magnet = None

            # 1. Search the selected artist's inventory first, then fuzzy-match
            #    the requested album + track inside that artist-owned result set.
            #    This avoids taking a wrong first responder from a direct album
            #    query, and it handles cases like Bonnie Tyler where the right
            #    album appears inside a discography/collection result.
            if album_looks_like_primary_artist_release():
                handle = run_search_phase(
                    "Artist inventory",
                    album_clean or "complete",
                    candidate_inventory_queries(),
                    max_sources=40,
                    allow_album_miss=True,
                )

            # 2. If inventory did not expose a usable album/track match, try the
            #    clicked album directly.
            if not handle and album_clean:
                handle = run_search_phase(
                    "Clicked album",
                    album_clean,
                    candidate_queries_for_album(album_clean),
                )

            # 3. Artist inventory and clicked-album search failed: resolve the
            #    track's real album(s) via
            #    MusicBrainz and search each one, applying that album's metadata
            #    when a match is found.
            if not handle:
                manager._append_cache_event(job, "trying", "Artist inventory/clicked album failed; checking MusicBrainz album hierarchy...")
                try:
                    from music_metadata import get_alternative_albums_hierarchical
                    alternative_albums = get_alternative_albums_hierarchical(primary_artist, title_clean)
                except Exception:
                    alternative_albums = []
                seen_albums = {clean_term(album_clean).lower()}
                musicbrainz_queries = []
                for alt_album in alternative_albums:
                    alt_clean = clean_term(alt_album)
                    if not alt_clean or alt_clean.lower() in seen_albums:
                        continue
                    seen_albums.add(alt_clean.lower())
                    for query in candidate_queries_for_album(alt_clean):
                        musicbrainz_queries.append({"query": query, "album": alt_clean})
                if musicbrainz_queries:
                    handle = run_search_phase(
                        "MusicBrainz albums",
                        "",
                        musicbrainz_queries,
                        max_sources=80,
                        apply_search_album=True,
                    )
                    if handle and resolved_album_from_search:
                        _apply_resolved_album(resolved_album_from_search)

            if not handle:
                broad_phases = [
                    ("Artist Discography", "complete", ["discography", "complete", "all albums", "flac"]),
                    ("Artist Compilations", "compilation", ["compilation", "greatest hits", "best of", "collection"]),
                    ("Artist Live Releases", "live", ["live"]),
                ]
                for phase_label, target_album, suffixes in broad_phases:
                    queries = [f"{art_var} {suffix}" for art_var in artist_variations for suffix in suffixes]
                    handle = run_search_phase(
                        phase_label, 
                        target_album, 
                        queries, 
                        max_sources=50, 
                        allow_album_miss=True # Very important: allow finding the track in a 'Discography' pack
                    )
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
