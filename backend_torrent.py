from __future__ import annotations

import logging
import os
import time
import threading
import contextlib
import shutil
import re
import hashlib
import concurrent.futures
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request
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

_ADULT_CONTENT_TERMS = {
    "adult",
    "anal",
    "bangbros",
    "bbc",
    "blowjob",
    "brazzers",
    "bukkake",
    "cock",
    "creampie",
    "cum",
    "cumming",
    "deepthroat",
    "dick",
    "facial",
    "fuck",
    "fucking",
    "handjob",
    "hardcore",
    "hentai",
    "hotandmean",
    "incest",
    "jizz",
    "milf",
    "mofos",
    "nude",
    "onlybbc",
    "onlyfans",
    "orgy",
    "porn",
    "pornhub",
    "porno",
    "pussy",
    "realitykings",
    "sex",
    "sexcapade",
    "slut",
    "slutinspection",
    "squirting",
    "stepmom",
    "stepsis",
    "teen",
    "threesome",
    "xhamster",
    "xnxx",
    "xvideos",
    "xxx",
    "youporn",
}

_ADULT_COMPOUND_TERMS = {
    "bangbros",
    "deepthroat",
    "hotandmean",
    "onlybbc",
    "onlyfans",
    "pornhub",
    "realitykings",
    "sexcapade",
    "slutinspection",
    "xhamster",
    "xvideos",
    "youporn",
}

_VIDEO_TORRENT_MARKERS = {
    "1080p",
    "2160p",
    "480p",
    "720p",
    "avi",
    "bdrip",
    "bluray",
    "brrip",
    "dvdrip",
    "h264",
    "h265",
    "hdrip",
    "hevc",
    "mkv",
    "movie",
    "mp4",
    "webdl",
    "webrip",
    "x264",
    "x265",
    "xvid",
}


def _normalize_service(value: str) -> str:
    service = (value or "all").strip().lower()
    return _SERVICE_ALIASES.get(service, service)

def _content_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

def _adult_terms_in_text(text: str, terms: set[str] | None = None) -> set[str]:
    terms = terms or _ADULT_CONTENT_TERMS
    words = _content_words(text)
    compact = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    normalized_terms = {
        re.sub(r"[^a-z0-9]+", " ", str(term).lower()).strip()
        for term in terms
        if str(term).strip()
    }
    found = {term for term in normalized_terms if term in words}
    found.update(
        term for term in normalized_terms
        if term in _ADULT_COMPOUND_TERMS or (" " not in term and len(term) >= 6)
        if term.replace(" ", "") in compact
    )
    return found

def _has_disallowed_adult_content(
    text: str,
    allowed_terms: set[str] | None = None,
    terms: set[str] | None = None,
) -> bool:
    allowed_terms = allowed_terms or set()
    return bool(_adult_terms_in_text(text, terms) - allowed_terms)

def _has_video_torrent_marker(text: str) -> bool:
    words = _content_words(text)
    compact = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    if words.intersection(_VIDEO_TORRENT_MARKERS):
        return True
    if compact and any(marker in compact for marker in ("s01e", "s02e", "s03e", "x264", "x265", "h264", "h265")):
        return True
    return bool(re.search(r"\.(avi|mkv|mp4)\b", (text or "").lower()))

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

# All torrent jobs share one libtorrent session. Keep prefetch bounded to the
# five-track window the player requests, while leaving active playback ungated so
# it can always cut ahead of queued prefetch work.
try:
    _PREFETCH_TORRENT_SLOTS = max(1, int(os.environ.get("MINDINGUFLAC_PREFETCH_TORRENT_SLOTS", "5")))
except Exception:
    _PREFETCH_TORRENT_SLOTS = 5
_PREFETCH_TORRENT_GATE = threading.BoundedSemaphore(_PREFETCH_TORRENT_SLOTS)


@contextlib.contextmanager
def prefetch_torrent_gate(job: dict):
    """Throttle concurrent prefetch torrent jobs against the shared session.
    Active playback jobs pass through untouched.

    A prefetch job can be adopted as the actively-playing track *while it is still
    waiting here* (the frontend reuses the running job and calls promote_job, which
    clears job['prefetch']). We therefore poll the live flag instead of capturing
    it once: a job promoted mid-wait stops waiting and proceeds immediately, so the
    throttle can never strand the track the user is waiting to hear. Degrades to
    running anyway after a long wait so a wedged slot can't permanently block."""
    if not job.get("prefetch"):
        yield
        return
    acquired = False
    deadline = time.time() + 180
    while job.get("prefetch") and time.time() < deadline:
        if _PREFETCH_TORRENT_GATE.acquire(timeout=0.25):
            acquired = True
            break
    try:
        yield
    finally:
        if acquired:
            _PREFETCH_TORRENT_GATE.release()

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


def _torrent_ai_first_batch_grace() -> float:
    try:
        return max(0.0, min(20.0, float(os.environ.get("MINDINGUFLAC_TORRENT_AI_FIRST_BATCH_GRACE", "8"))))
    except Exception:
        return 8.0


def _torrent_info_from_url(url: str, timeout: int = 8):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(5 * 1024 * 1024)
        for payload in (data, bytearray(data)):
            try:
                return lt.torrent_info(payload)
            except Exception:
                pass
        try:
            return lt.torrent_info(lt.bdecode(data))
        except Exception:
            return None
    except Exception:
        return None

def _torrent_num_files(torrent_info) -> int:
    try:
        if torrent_info is None:
            return 0
        return int(torrent_info.num_files())
    except Exception:
        return 0

def _register_job_to_torrent(magnet: str, job_id: str, output_dir: Path, manager, torrent_url: str = "") -> tuple:
    key = _torrent_key(magnet)
    with _SESSIONS_LOCK:
        if key in _ACTIVE_SESSIONS:
            entry = _ACTIVE_SESSIONS[key]
            entry["refs"].add(job_id)
            if "magnet" not in entry:
                entry["magnet"] = magnet
            handle = entry["handle"]
            if handle.is_valid():
                handle.resume()
                return handle, Path(entry["save_path"])
        output_dir.mkdir(parents=True, exist_ok=True)
        params = {
            'save_path': str(output_dir),
            'storage_mode': lt.storage_mode_t(2)
        }
        torrent_info = _torrent_info_from_url(torrent_url) if torrent_url else None
        if torrent_info:
            add_params = lt.add_torrent_params()
            add_params.save_path = str(output_dir)
            add_params.storage_mode = lt.storage_mode_t(2)
            add_params.ti = torrent_info
            handle = _GLOBAL_SES.add_torrent(add_params)
        else:
            handle = lt.add_magnet_uri(_GLOBAL_SES, magnet, params)
        _ACTIVE_SESSIONS[key] = {
            "handle": handle,
            "refs": {job_id},
            "save_path": str(output_dir),
            "magnet": magnet
        }
        return handle, output_dir

def _unregister_job_from_torrent(magnet: str, job_id: str) -> bool:
    """Drop this job's reference to the shared torrent. Returns True only when no
    other job still references it (i.e. the handle was actually removed and the
    on-disk files are now safe to delete). Returns False when other jobs are still
    downloading the same magnet, so the caller must NOT delete the shared files."""
    key = _torrent_key(magnet)
    with _SESSIONS_LOCK:
        if key not in _ACTIVE_SESSIONS: return True
        entry = _ACTIVE_SESSIONS[key]
        entry["refs"].discard(job_id)
        if not entry["refs"]:
            handle = entry["handle"]
            if handle.is_valid():
                _GLOBAL_SES.remove_torrent(handle)
            del _ACTIVE_SESSIONS[key]
            return True
        return False

def _unregister_all_for_job(job_id: str, delete_files: bool = True) -> None:
    """Drop all references this job holds to any active torrent sessions,
    and optionally delete their files if this was the last job referencing them."""
    with _SESSIONS_LOCK:
        to_unregister = []
        for key, entry in list(_ACTIVE_SESSIONS.items()):
            if job_id in entry.get("refs", set()):
                magnet = entry.get("magnet") or ""
                save_path = entry.get("save_path")
                to_unregister.append((magnet, save_path))
    
    for magnet, save_path in to_unregister:
        if not magnet:
            continue
        fully_removed = _unregister_job_from_torrent(magnet, job_id)
        if delete_files and fully_removed and save_path:
            try:
                p_path = Path(save_path).resolve()
                if "_race" in p_path.parts:
                    shutil.rmtree(p_path, ignore_errors=True)
            except Exception:
                pass

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
    import db
    db.seed_adult_filter_terms(_ADULT_CONTENT_TERMS, source="builtin")
    adult_filter_terms = db.get_adult_filter_terms() or set(_ADULT_CONTENT_TERMS)
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
    allowed_adult_terms = _adult_terms_in_text(
        f"{raw_title} {title_clean} {album} {album_clean}",
        adult_filter_terms,
    )

    quality_str = str(job.get("quality") or "LOSSLESS").upper()
    service = _normalize_service(job.get("service") or "all")
    track_num = str(job.get("metadata", {}).get("track_number") or job.get("track_number") or "")
    disc_num = str(job.get("metadata", {}).get("disc_number") or job.get("disc_number") or "1")
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    try:
        from backend_ytpdl import (
            _classical_match_adjustment,
            _classical_search_terms,
            _extract_catalog_ids,
            _norm_text,
            _token_coverage,
            _tokens,
            _ytpdl_search_profile,
        )
    except Exception:
        _classical_match_adjustment = None
        _classical_search_terms = None
        _extract_catalog_ids = None
        _norm_text = None
        _token_coverage = None
        _tokens = None
        _ytpdl_search_profile = None
    is_classical_search = bool(_ytpdl_search_profile and _ytpdl_search_profile(job) == "classical")

    def classical_query_terms(text: str) -> str:
        if not is_classical_search or not _classical_search_terms:
            return ""
        terms = _classical_search_terms(text)
        if terms:
            return terms
        if not _tokens:
            return clean_term(text)
        ignored = {
            "the", "and", "with", "feat", "official", "audio", "video",
            "concerto", "symphony", "sonata", "major", "minor", "op", "no",
            "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
        }
        tokens = [token for token in _tokens(text) if len(token) > 1 and token not in ignored]
        return " ".join(tokens[:8])

    def classical_candidate_adjustment(candidate_text: str) -> tuple[int, str]:
        if not is_classical_search or not _classical_match_adjustment:
            return 0, ""
        wanted = {"artist": primary_artist, "title": raw_title, "album": album_clean or album}
        adjustment, details = _classical_match_adjustment(wanted, candidate_text, "")
        catalog_state = str(details.get("classical_catalog") or "")
        if adjustment < 0:
            return adjustment, catalog_state
        return adjustment * 3, catalog_state

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
        from service_downloader import AUDIO_SUFFIXES, is_download_audio_candidate, is_valid_audio_file

        def audio_file_indexes(torrent_info) -> list[int]:
            indexes = []
            for i in range(_torrent_num_files(torrent_info)):
                f_path = Path(torrent_info.file_at(i).path)
                if f_path.suffix.lower() in AUDIO_SUFFIXES:
                    indexes.append(i)
            return indexes

        def find_best_audio_file(torrent_info, is_artist_verified: bool = True) -> tuple[int, int]:
            best_f_idx = -1
            best_f_score = -1
            track_pats = [f"{track_num.zfill(2)}.", f" {track_num.zfill(2)} ", f"- {track_num.zfill(2)} "] if track_num else []
            
            # Words that MUST appear for the match to be considered valid.
            # We filter out common noise that might be in Spotify title but not filename.
            noise_words = {"remastered", "remaster", "live", "edit", "version", "mono", "stereo", "mix", "remix", "single", "digitally", "trilogy", "beginning", "part", "vol", "volume", "ost"}
            title_for_tokens = classical_query_terms(raw_title) if is_classical_search else title_clean
            title_tokens = set(re.findall(r'\w+', title_for_tokens.lower()))
            meaningful_tokens = {t for t in title_tokens if len(t) > 2 and t not in {"the", "and", "feat", "with"} and t not in noise_words}
            if not meaningful_tokens: meaningful_tokens = title_tokens

            for i in range(_torrent_num_files(torrent_info)):
                f_path = Path(torrent_info.file_at(i).path)
                path_text = str(f_path)
                try:
                    torrent_name = str(torrent_info.name())
                except Exception:
                    torrent_name = ""
                if _has_video_torrent_marker(path_text) or _has_disallowed_adult_content(path_text, allowed_adult_terms, adult_filter_terms):
                    continue
                if f_path.suffix.lower() in AUDIO_SUFFIXES:
                    f_name_lower = f_path.name.lower()
                    classical_adj, classical_catalog_state = classical_candidate_adjustment(f"{torrent_name} {path_text}")
                    if is_classical_search and classical_catalog_state == "mismatch":
                        continue
                    title_score = max(
                        rapidfuzz.fuzz.token_set_ratio(raw_title, f_path.name),
                        rapidfuzz.fuzz.token_set_ratio(title_clean, f_path.stem),
                        rapidfuzz.fuzz.token_set_ratio(title_for_tokens, path_text) if is_classical_search else 0,
                    )
                    
                    # If artist is not verified in the torrent title, we MUST have a strong filename match
                    # and the artist name should ideally appear in the path.
                    if not is_artist_verified:
                        if title_score < 75:
                            continue
                        # Artist check in path
                        path_norm = path_text.lower()
                        artist_found = any(token in path_norm for token in artist_variations[0].lower().split())
                        if not artist_found:
                            # Strict penalty for missing artist in path if torrent title is unverified
                            continue
                    # Significant word check: 
                    # For short titles (1-2 words), we want a high match to avoid "Kill the King" vs "Temple of the King".
                    # For longer titles, we allow some flexibility (65%).
                    # We check the filename stem specifically to avoid "Sirius" matching "Eye in the Sky"
                    # just because it's inside a folder named "Eye in the Sky".
                    filename_tokens = set(re.findall(r'\w+', f_path.stem.lower()))
                    match_count = sum(1 for t in meaningful_tokens if t in filename_tokens)
                    match_ratio = match_count / len(meaningful_tokens) if meaningful_tokens else 1.0
                    
                    required_ratio = 0.50 if is_classical_search and len(meaningful_tokens) > 2 else (0.65 if len(meaningful_tokens) > 2 else 0.85)
                    if match_ratio < required_ratio:
                        # Fallback: if the filename is very short (e.g. "01.flac"), check the immediate parent folder too
                        parent_tokens = set(re.findall(r'\w+', f_path.parent.name.lower())) if f_path.parent.name else set()
                        combined_tokens = filename_tokens.union(parent_tokens)
                        match_count = sum(1 for t in meaningful_tokens if t in combined_tokens)
                        match_ratio = match_count / len(meaningful_tokens) if meaningful_tokens else 1.0
                        if match_ratio < required_ratio:
                            continue

                    if title_score < 58: # Balanced for better inclusivity
                        continue
                    
                    score = title_score
                    score += classical_adj
                    is_track_match = any(p in f_path.name for p in track_pats)
                    if track_num:
                        if is_track_match:
                            score += 40
                        elif re.search(r'\b\d{1,2}\b', f_path.name) and not is_track_match:
                            # If filename has a different track number, penalize it heavily
                            score -= 60

                    if f"cd{disc_num}" in str(f_path).lower(): score += 20
                    
                    # Massive penalty for "Full CD" / "Disc 1" filenames when we want a single track.
                    # This prevents matching "Eye in the Sky CD1.flac" (469MB) as the song "Eye in the Sky".
                    album_indicators = ["cd1", "cd2", "cd3", "disc 1", "disc 2", "full album", "complete album"]
                    if any(ind in f_name_lower for ind in album_indicators):
                        if not any(ind in raw_title.lower() for ind in album_indicators):
                            score -= 100

                    for kw in ["live", "demo", "remix", "mix", "edit"]:
                        if kw in f_name_lower and kw not in raw_title.lower(): score -= 50
                    
                    if score > best_f_score:
                        best_f_score = score
                        best_f_idx = i
            return best_f_idx, best_f_score

        def score_metadata_candidate(torrent_info, result: dict, target_album: str, require_track_list: bool, live_peers: int = 0):
            try:
                torrent_name = str(torrent_info.name())
            except Exception:
                torrent_name = str(result.get("title") or "")
            if _has_video_torrent_marker(torrent_name) or _has_disallowed_adult_content(torrent_name, allowed_adult_terms, adult_filter_terms):
                return None, "Adult/video content"

            audio_indexes = audio_file_indexes(torrent_info)
            if require_track_list and len(audio_indexes) < 2:
                return None, "Single-file album"

            is_artist_verified = result.get("_artist_verified", True)
            best_f_idx, best_f_score = find_best_audio_file(torrent_info, is_artist_verified=is_artist_verified)
            if best_f_idx == -1 or best_f_score < 60:
                return None, "Track not found"

            # Penalty for "Covers", "Tribute", "Reimagined" unless explicitly requested
            torrent_name_lower = torrent_name.lower()
            tribute_terms = {"tribute", "cover", "covers", "reimagined", "karaoke", "instrumental", "remix", "remixed", "acoustic", "rework"}
            requested_text = f"{raw_title} {target_album}".lower()
            has_tribute_in_torrent = any(t in torrent_name_lower for t in tribute_terms)
            has_tribute_in_request = any(t in requested_text for t in tribute_terms)
            if has_tribute_in_torrent and not has_tribute_in_request:
                # If artist is verified and it's an official Hendrix release (e.g. 'Axis: Bold as Love'),
                # don't penalize it just because it says 'remaster' or similar. 
                # But if it says 'tribute', it's almost certainly not him.
                bad_tribute = any(t in torrent_name_lower for t in ["tribute", "karaoke", "instrumental"])
                if bad_tribute:
                    return None, "Tribute/Karaoke content"
                # For 'cover', 'remix', etc. we check if the artist is verified.
                if not is_artist_verified:
                    return None, "Potential cover/remix mismatch"

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
            
            # Live Peer Health bonus
            if live_peers > 0:
                score += min(live_peers * 10, 100) # Up to +100 for healthy connections
            else:
                score -= 50 # Ghost source penalty
            
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
        # RECOVERY attempt: use the persistent source from DB if available
        album_key = f"{primary_artist.lower()}||{album.lower()}"
        cached_magnet = job.get("resolved_url")
        if not cached_magnet or not cached_magnet.startswith("magnet:"):
            # 1. Try track-specific magnet
            # 2. Try album-wide magnet (new SQLite source)
            # 3. Try legacy JSON catalog
            album_source = db.get_album_source(album_key)
            if album_source:
                cached_magnet = album_source.get("resolved_url")
            
            if not cached_magnet:
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
                    torrentdownloads_category = torrent_sources.torrentdownloads_category_from_metadata(metadata)
                    if svc == "all":
                        provider_timeout = 4
                        provider_calls = [
                            ("torlock", lambda: torrent_sources.search_torlock(q, timeout=provider_timeout)),
                            ("torrentdownloads", lambda: torrent_sources.search_torrentdownloads(q, torrentdownloads_category, timeout=provider_timeout)),
                            ("limetorrents", lambda: torrent_sources.search_limetorrents(q, timeout=provider_timeout)),
                            ("torrfetch", lambda: torrfetch.search_torrents(q, mode="parallel") or []),
                            ("extra", lambda: torrent_sources.search_extra(q, timeout=provider_timeout)),
                        ]
                        provider_results = {name: [] for name, _ in provider_calls}
                        exec = concurrent.futures.ThreadPoolExecutor(max_workers=len(provider_calls))
                        try:
                            futures = {exec.submit(call): name for name, call in provider_calls}
                            for future in concurrent.futures.as_completed(futures, timeout=provider_timeout + 2):
                                name = futures[future]
                                try:
                                    provider_results[name] = future.result() or []
                                except Exception:
                                    provider_results[name] = []
                        except Exception:
                            pass
                        finally:
                            exec.shutdown(wait=False, cancel_futures=True)
                        for name, _ in provider_calls:
                            results = list(results) + provider_results.get(name, [])
                    elif svc == "torrentdownloads":
                        results = torrent_sources.search_torrentdownloads(q, torrentdownloads_category, timeout=4)
                    elif svc == "limetorrents":
                        results = torrent_sources.search_limetorrents(q, timeout=4)
                    elif svc == "torlock":
                        results = torrent_sources.search_torlock(q, timeout=4)
                    elif svc == "1337x":
                        results = torrent_sources.search_1337x(q, timeout=4)
                    elif svc == "kickass":
                        results = torrent_sources.search_kickass(q, timeout=4)
                    else:
                        try: results = torrfetch.search_torrents(q, only=[svc]) or []
                        except: results = torrfetch.search_torrents(q, mode="parallel") or []
                        # Still add extra sources as fallback/augmentation even for specific TPB/YTS
                        results = list(results) + torrent_sources.search_extra(q, timeout=4)
                except Exception:
                    pass
                return results

            def score_torrent_result(r, target_artist, target_title, target_album, allow_album_miss=False):
                torrent_title = r.get("title", "").lower()
                if _has_video_torrent_marker(torrent_title) or _has_disallowed_adult_content(torrent_title, allowed_adult_terms, adult_filter_terms):
                    return -1
                
                category = str(r.get("category") or "").lower()
                if category and category != "unknown" and not any(k in category for k in ["audio", "music"]):
                    return -1
                
                classical_adj, classical_catalog_state = classical_candidate_adjustment(str(r.get("title") or ""))
                if is_classical_search and classical_catalog_state == "mismatch":
                    return -1

                artist_tokens = set(re.findall(r'\w+', target_artist.lower()))
                title_tokens = set(re.findall(r'\w+', torrent_title))
                meaningful_artist = {t for t in artist_tokens if len(t) >= 2 and t not in {"the","and","feat","with"}}
                if not meaningful_artist: meaningful_artist = artist_tokens
                
                artist_verified = False
                matches = meaningful_artist.intersection(title_tokens)
                
                # Strict verification: multi-word artists need at least 2 matching tokens (or 70% if very long)
                if len(meaningful_artist) >= 2:
                    if len(matches) >= 2 and len(matches) >= (len(meaningful_artist) * 0.7):
                        artist_verified = True
                elif len(matches) >= len(meaningful_artist):
                    artist_verified = True
                    
                if not artist_verified and target_artist.replace("'", "") in torrent_title: 
                    artist_verified = True

                album_verified = False
                target_album = clean_term(target_album).lower()
                if target_album and target_album != "unknown":
                    if rapidfuzz.fuzz.token_set_ratio(target_album.lower(), torrent_title) > 85: album_verified = True
                
                target_title_for_score = classical_query_terms(target_title) if is_classical_search else target_title
                title_score = max(
                    rapidfuzz.fuzz.token_set_ratio(target_title.lower(), torrent_title),
                    rapidfuzz.fuzz.token_set_ratio(target_title_for_score.lower(), torrent_title) if target_title_for_score else 0,
                )
                album_tokens = set(re.findall(r'\w+', target_album.lower()))
                generic_album_tokens = {
                    "get", "here", "there", "this", "that", "the", "a", "an", "to", "from",
                    "in", "on", "of", "for", "me", "you", "now", "out", "up", "down",
                    "greatest", "hits", "hit", "best", "collection", "collections", "complete",
                    "ultimate", "essential", "singles", "anthology", "platinum", "gold",
                    "trilogy", "beginning", "part", "vol", "volume", "ost", "soundtrack",
                    "original", "motion", "picture", "limited", "deluxe", "edition",
                }
                album_has_distinctive_token = any(
                    len(token) >= 4 and token not in generic_album_tokens
                    for token in album_tokens
                )
                if is_classical_search and classical_catalog_state == "matched":
                    artist_verified = True
                    allow_album_miss = True

                if target_album:
                    # Generic album names (like 'Trilogy') are accepted IF the artist is confirmed.
                    if not artist_verified and not album_verified:
                        return -1
                    # If artist is verified, we can be much more relaxed about generic album names
                    if not artist_verified and not album_has_distinctive_token and rapidfuzz.fuzz.ratio(target_album.lower(), torrent_title) < 95:
                        return -1
                    if allow_album_miss and not album_verified and not artist_verified:
                        return -1
                    if not allow_album_miss and not album_verified:
                        return -1
                    if album_verified and not artist_verified and title_score < 45 and not album_has_distinctive_token:
                        return -1
                elif not artist_verified or title_score < 55:
                    return -1
                
                score = title_score
                score += classical_adj
                score += 40 if artist_verified else 0
                score += 60 if album_verified else 20
                collection_result = any(
                    k in torrent_title
                    for k in ["discography", "complete", "collection", "albums", "greatest hits", "best of"]
                )
                if collection_result:
                    score += 30
                
                # Massive Audiophile boost
                if (
                    any(k in torrent_title for k in ["flac", "lossless", "24-bit", "96khz", "alac", "eac"])
                    and (title_score >= 60 or album_verified or collection_result)
                ):
                    score += 250
                source_name = str(r.get("source") or "")
                if source_name.startswith("torlock"):
                    score += 45
                elif source_name.startswith("torrentdownloads"):
                    score += 35
                elif source_name.startswith("limetorrents"):
                    score += 20
                
                # Penalty for video keywords
                if any(k in torrent_title for k in ["1080p", "720p", "x264", "h264", "brrip", "dvdrip", "videograffitti"]):
                    score -= 500

                health = int(r.get("seeders") or 0)
                if health > 0:
                    import math
                    score += math.log10(health) * 20
                else:
                    score -= 100
                
                # Store verification flags for later file-level selection
                r["_artist_verified"] = artist_verified
                r["_album_verified"] = album_verified
                
                return score

            trackers = _get_best_trackers()

            def race_save_path(magnet: str) -> Path:
                digest = hashlib.sha1(_torrent_key(magnet).encode("utf-8", errors="ignore")).hexdigest()[:12]
                return output_dir / "_race" / digest

            def cleanup_candidate(magnet: str, save_path: Path | None, delete_files: bool = False) -> None:
                fully_removed = _unregister_job_from_torrent(magnet, job_id)
                # When another job (e.g. a same-album prefetch) still shares this
                # magnet, its handle keeps downloading into the same _race dir.
                # Deleting those files here would stall that live download
                # ("no byte progress"/"stalled during streaming"), so only remove
                # them once we were the last reference.
                if not delete_files or not save_path or not fully_removed:
                    return
                try:
                    save_path = Path(save_path)
                    race_root = (output_dir / "_race").resolve()
                    resolved = save_path.resolve()
                    if resolved == race_root or not resolved.is_relative_to(race_root):
                        return
                    shutil.rmtree(resolved, ignore_errors=True)
                except Exception:
                    pass

            def candidate_queries_for_album(album_name: str) -> list[str]:
                album_name = clean_term(album_name)
                if not album_name:
                    return []
                if is_classical_search:
                    album_terms = classical_query_terms(album_name)
                    if album_terms:
                        queries = [f"{art} {album_terms}".strip() for art in artist_variations if art]
                        queries.append(album_terms)
                        return list(dict.fromkeys(queries))
                # Lead with "<artist> <album>" so a short/generic artist name
                # (e.g. "Skank") doesn't pull unrelated junk; keep the bare
                # album as a fallback for releases credited to another artist.
                queries = [f"{art} {album_name}".strip() for art in artist_variations if art]
                queries.append(album_name)
                return list(dict.fromkeys(queries))

            def candidate_inventory_queries() -> list[str]:
                queries = []
                if is_classical_search:
                    # Classical torrents are usually work/recording-specific;
                    # broad discography/collection searches create too much
                    # cross-work noise, so keep inventory narrow.
                    terms = classical_query_terms(raw_title)
                    if terms:
                        for art_var in artist_variations:
                            queries.append(f"{art_var} {terms} lossless".strip())
                            queries.append(f"{art_var} {terms} flac".strip())
                    return list(dict.fromkeys(queries))
                suffixes = ["", "albums", "collection", "discography", "FLAC", "lossless"]
                for art_var in artist_variations:
                    for suffix in suffixes:
                        queries.append(f"{art_var} {suffix}".strip())
                return list(dict.fromkeys(queries))

            def candidate_track_queries() -> list[str]:
                if not title_clean:
                    return []
                if is_classical_search:
                    terms = classical_query_terms(raw_title) or title_clean
                    queries = [f"{art_var} {terms}".strip() for art_var in artist_variations if art_var]
                    queries.append(terms)
                    return list(dict.fromkeys(queries))
                queries = [f"{art_var} {title_clean}".strip() for art_var in artist_variations if art_var]
                queries.append(title_clean)
                return list(dict.fromkeys(queries))

            def candidate_first_pass_queries() -> list[dict]:
                queries = []
                seen = set()

                def add(query_text: str, query_album: str) -> None:
                    query_text = str(query_text or "").strip()
                    query_album = clean_term(query_album)
                    key = (query_text.lower(), query_album.lower())
                    if not query_text or key in seen:
                        return
                    seen.add(key)
                    queries.append({"query": query_text, "album": query_album})

                for query in candidate_track_queries():
                    add(query, "")
                if album_clean:
                    for query in candidate_queries_for_album(album_clean):
                        add(query, album_clean)
                if album_looks_like_primary_artist_release():
                    for query in candidate_inventory_queries():
                        add(query, album_clean or "complete")
                return queries

            def stream_to_completion(handle, magnet, save_path: Path | None = None, is_artist_verified: bool = True, cached_reuse: bool = False) -> bool | None:
                # Download the best matching file to completion. Returns True on
                # success (file placed in output_dir), False on hard source
                # failure, or None on a soft stall so the caller can fall back
                # without blacklisting a cached album source.
                if not handle.is_valid():
                    manager._append_cache_event(job, "trying", "Source handle expired before streaming, trying next...")
                    return False
                save_path = save_path or torrent_save_path
                try:
                    torrent_info = handle.get_torrent_info()
                except Exception as exc:
                    manager._append_cache_event(job, "trying", f"Source metadata became unavailable, trying next: {exc}")
                    return False
                best_f_idx, best_f_score = find_best_audio_file(torrent_info, is_artist_verified=is_artist_verified)
                if best_f_idx == -1 or best_f_score < 60:
                    return False

                def update_shared_priorities():
                    try:
                        file_count = _torrent_num_files(torrent_info)
                        if file_count <= 0:
                            return
                        priorities = [0] * file_count
                        with manager._lock:
                            for other_job in list(manager.jobs.values()):
                                if other_job.get("status") in ("starting", "running"):
                                    other_mag = other_job.get("resolved_url")
                                    if other_mag and _torrent_key(other_mag) == _torrent_key(magnet):
                                        fidx = other_job.get("active_file_idx")
                                        if fidx is not None and 0 <= fidx < file_count:
                                            is_pref = other_job.get("prefetch", False)
                                            priorities[fidx] = 2 if is_pref else 7
                        handle.prioritize_files(priorities)
                    except Exception:
                        pass

                try:
                    handle.set_sequential_download(True)
                    with manager._lock:
                        job["active_file_idx"] = best_f_idx
                        job["resolved_url"] = magnet
                    update_shared_priorities()
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
                    # Prefer libtorrent's file_progress(), but do not get stuck
                    # forever if it underreports a file that is already fully
                    # materialized on disk. Sparse files can have target_size
                    # before pieces are real, so a stale-progress fallback still
                    # requires size + a valid audio header.
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
                        if last_done < target_size and not is_valid_audio_file(target_abs):
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
                    with manager._lock:
                        job["active_audio_path"] = str(final_dest)
                        job["active_audio_size"] = target_size
                        job["active_audio_ready_bytes"] = target_size
                    manager._append_cache_event(job, "provider", f"Torrent engine produced {final_dest.name}")
                    if album != "Unknown":
                        catalog[f"{primary_artist.lower()}||{album.lower()}"] = magnet
                        _save_catalog(manager, catalog)
                        db.save_album_source(
                            album_key=f"{primary_artist.lower()}||{album.lower()}",
                            engine="torrent",
                            resolved_url=magnet
                        )
                    
                    db.save_resolved_source(
                        track_key=job.get("track_key") or f"{primary_artist.lower()}||{title_clean.lower()}",
                        engine="torrent",
                        service=job.get("service") or "all",
                        quality=job.get("quality") or "LOSSLESS",
                        resolved_url=magnet
                    )
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
                            handle, _ = _register_job_to_torrent(magnet, job_id, save_path, manager)
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
                                    file_count = _torrent_num_files(torrent_info)
                                    if file_count <= 0:
                                        raise RuntimeError("torrent metadata unavailable")
                                    priorities = [0] * file_count
                                    priorities[best_f_idx] = 7
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
                        last_done = done
                        last_progress_time = time.time()
                        # Reset re-announce flag so we can wake the swarm again if it stalls later
                        reannounced_once = False
                    elif s.download_payload_rate > 100 * 1024: # > 100 KB/s overall is "healthy enough" to wait
                        last_progress_time = time.time()

                    update_shared_priorities()
                    prog = (done / total) * 100 if total > 0 else 0
                    with manager._lock:
                        job["progress"] = int(prog)
                        job["last_status"] = f"Streaming: {int(prog)}% ({s.download_rate/1024:.1f}kB/s, {s.num_peers}p)"
                        job["active_audio_path"] = str(target_abs)
                        job["active_audio_size"] = total
                        job["active_audio_ready_bytes"] = done
                    if done >= total and total > 0:
                        return finalize_selected_file()
                    # Stall handling. Reported seed counts are often stale; a
                    # selected torrent with zero connected peers and zero bytes
                    # should not hold the player for a long stall window.
                    since_progress = time.time() - last_progress_time
                    reannounce_after = 12 if s.num_peers == 0 and last_done == 0 else 30
                    if since_progress > reannounce_after and not reannounced_once:
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

                    max_stall = 75 if last_done > 0 else 45
                    no_peer_stall = 45 if last_done > 0 else 24
                    stalled = since_progress > max_stall
                    if not stalled and s.num_peers == 0 and since_progress > no_peer_stall:
                        stalled = True
                    if stalled:
                        if last_done > 0:
                            key = _torrent_key(magnet)
                            stall_retry_counts[key] = stall_retry_counts.get(key, 0) + 1
                            limit = 2 if cached_reuse and s.num_peers == 0 else 4
                            if stall_retry_counts[key] <= limit:
                                # A winning source that already produced real bytes is
                                # worth keeping: a slow FLAC swarm delivers in bursts.
                                # Re-announce to wake peers, reset the stall window and
                                # KEEP downloading the same handle from its partial,
                                # instead of returning None — which every caller deletes
                                # (delete_files=True), the reason a winning download
                                # "didn't continue".
                                try:
                                    for tr in trackers:
                                        handle.add_tracker(lt.announce_entry(tr))
                                    handle.force_reannounce()
                                    handle.force_dht_announce()
                                except Exception:
                                    pass
                                last_progress_time = time.time()
                                reannounced_once = False
                                manager._append_cache_event(job, "trying", f"Source stalled at {int(prog)}% but had progress ({s.num_peers}p); re-announcing and resuming ({stall_retry_counts[key]}/{limit})...")
                                time.sleep(2)
                                continue
                        if s.num_peers == 0 and last_done == 0:
                            manager._append_cache_event(job, "trying", f"Source has metadata but no connected peers after {int(since_progress)}s; moving to next candidate.")
                        elif cached_reuse and s.num_peers == 0:
                            manager._append_cache_event(job, "trying", f"Cached album source stalled at {int(prog)}% with no connected peers; trying discovery/fallback instead.")
                            return None
                        else:
                            manager._append_cache_event(job, "trying", f"Source stalled after {int(since_progress)}s; moving to next candidate.")
                        return False
                    if time.time() - start_time > 1800: return False
                    time.sleep(2)

            def try_result_source(r: dict, r_idx: int, phase_label: str, require_track_list: bool):
                nonlocal current_magnet, torrent_save_path
                m_link = r.get("magnet")
                if not m_link:
                    return None
                if db.is_blacklisted(m_link):
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
                candidate_handle, torrent_save_path = _register_job_to_torrent(
                    m_link,
                    job_id,
                    output_dir,
                    manager,
                    str(r.get("torrent_url") or ""),
                )
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

                best_f_idx, best_f_score = find_best_audio_file(torrent_info, is_artist_verified=r.get("_artist_verified", True))
                if best_f_idx == -1 or best_f_score < 60:
                    manager._append_cache_event(job, "trying", "Track not in source, trying next...")
                    _unregister_job_from_torrent(current_magnet, job_id)
                    current_magnet = None
                    return None
                # Actually download it now. False = dead/wrong -> blacklist;
                # None = stalled with real progress -> keep retryable (resume).
                _scr = stream_to_completion(candidate_handle, current_magnet, torrent_save_path, is_artist_verified=r.get("_artist_verified", True))
                if _scr:
                    return candidate_handle
                if _scr is False:
                    db.add_to_blacklist(current_magnet, "stalled or dead")
                    manager._append_cache_event(job, "trying", "Source stalled mid-download, trying next...")
                else:
                    manager._append_cache_event(job, "trying", "Source stalled but kept as fallback, trying next...")
                _unregister_job_from_torrent(current_magnet, job_id)
                current_magnet = None
                return None

            resolved_album_from_search = None
            zero_byte_race_failures = 0
            dead_race_keys = set()

            def run_search_phase(
                phase_label: str,
                target_album: str,
                queries: list,
                max_sources: int = 40,
                allow_album_miss: bool = False,
                require_track_list: bool = True,
                apply_search_album: bool = False,
            ):
                nonlocal current_magnet, resolved_album_from_search, zero_byte_race_failures
                def phase_status(message: str) -> None:
                    with manager._lock:
                        job["last_status"] = message
                    manager._append_cache_event(job, "trying", message)

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

                phase_status(f"{phase_label}: searching {len(query_specs)} torrent query(s)")
                phase_results = []
                attempted_keys = set()
                pending_search_futures = {}
                search_executor = None
                ai_thread = None
                ai_first_batch_waited = False
                ai_ranked_keys: list[str] = []
                ai_lock = threading.Lock()

                def collect_search_results(wait_seconds: float) -> None:
                    if not pending_search_futures:
                        return
                    deadline = time.time() + max(0.0, wait_seconds)
                    while pending_search_futures and time.time() < deadline:
                        try:
                            future = next(concurrent.futures.as_completed(list(pending_search_futures), timeout=max(0.001, deadline - time.time())))
                        except concurrent.futures.TimeoutError:
                            break
                        query_text, query_album = pending_search_futures.pop(future)
                        try:
                            rows = future.result() or []
                        except Exception:
                            rows = []
                        for r in rows:
                            score = score_torrent_result(r, primary_artist, title_clean, query_album, allow_album_miss=allow_album_miss)
                            if score > 50:
                                item = dict(r)
                                item["_score"] = score
                                item["_search_album"] = query_album
                                item["_query"] = query_text
                                phase_results.append(item)

                def start_ai_advisor_if_ready() -> None:
                    nonlocal ai_thread
                    if ai_thread or len(phase_results) < 3:
                        return
                    try:
                        import ai_reranker
                    except Exception:
                        return
                    config = getattr(manager, "config", None)
                    ai_provider = getattr(config, "ai_provider", "duckai")
                    if not ai_reranker.is_enabled(ai_provider):
                        return
                    snapshot = sorted(
                        _dedupe_results(phase_results),
                        key=lambda x: (int(x.get("seeders") or 0) > 0, x.get("_score", 0), int(x.get("seeders") or 0)),
                        reverse=True,
                    )[:20]
                    if len(snapshot) < 3:
                        return
                    def run_ai_advisor():
                        try:
                            import ai_reranker
                            target = {"artist": primary_artist, "title": title_clean, "album": target_album}
                            candidates = []
                            id_to_key = {}
                            for idx, item in enumerate(snapshot, start=1):
                                m_link = str(item.get("magnet") or "")
                                if not m_link:
                                    continue
                                id_to_key[idx] = _torrent_key(m_link)
                                candidates.append({
                                    "id": idx,
                                    "title": item.get("title") or "",
                                    "source": item.get("source") or "",
                                    "seeders": item.get("seeders") or 0,
                                    "score": item.get("_score") or 0,
                                    "query": item.get("_query") or "",
                                    "magnet": m_link,  # lets the reranker read DN + trackers
                                })
                            config = getattr(manager, "config", None)
                            duck_model = getattr(config, "duck_model", "1")
                            ai_provider = getattr(config, "ai_provider", "duckai")
                            gemini_model = getattr(config, "gemini_model", "gemini-1.5-flash")
                            ranked_ids = ai_reranker.rank_candidates(target, candidates, duck_model, ai_provider, gemini_model)
                            ranked_keys = [id_to_key[i] for i in ranked_ids if i in id_to_key]
                            if ranked_keys:
                                with ai_lock:
                                    ai_ranked_keys[:] = ranked_keys
                                manager._append_cache_event(job, "trying", f"{phase_label}: AI advisor ranked {len(ranked_keys)} clean candidates")
                        except Exception as exc:
                            manager._append_cache_event(job, "trying", f"{phase_label}: AI advisor unavailable ({exc})")

                    ai_thread = threading.Thread(target=run_ai_advisor, daemon=True, name=f"ai-rerank-{job_id}")
                    ai_thread.start()
                    manager._append_cache_event(job, "trying", f"{phase_label}: AI advisor running in parallel")

                def ordered_untried_results() -> list[dict]:
                    with ai_lock:
                        ai_positions = {key: pos for pos, key in enumerate(ai_ranked_keys)}
                    ordered = sorted(
                        _dedupe_results(phase_results),
                        key=lambda x: (
                            -ai_positions.get(_torrent_key(str(x.get("magnet") or "")), 10_000),
                            int(x.get("seeders") or 0) > 0,
                            x.get("_score", 0),
                            int(x.get("seeders") or 0),
                        ),
                        reverse=True,
                    )
                    out = []
                    for result in ordered:
                        m_link = result.get("magnet") or ""
                        if m_link and _torrent_key(m_link) not in attempted_keys and _torrent_key(m_link) not in dead_race_keys:
                            out.append(result)
                    return out[:max_sources]

                try:
                    if query_specs:
                        search_executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(query_specs)))
                        pending_search_futures = {
                            search_executor.submit(do_search_safe, q, service): (q, query_album)
                            for q, query_album in query_specs
                        }

                    search_deadline = time.time() + (55 if phase_label in {"First pass", "Track fallback"} else 40)
                    collect_search_results(5 if phase_label == "First pass" else 7)
                    start_ai_advisor_if_ready()

                    while True:
                        collect_search_results(0.1)
                        start_ai_advisor_if_ready()
                        if ai_thread and not ai_first_batch_waited and not attempted_keys:
                            ai_first_batch_waited = True
                            grace = _torrent_ai_first_batch_grace()
                            if grace > 0:
                                ai_thread.join(timeout=grace)
                        results_to_try = ordered_untried_results()
                        if not results_to_try:
                            if pending_search_futures and time.time() < search_deadline:
                                phase_status(f"{phase_label}: waiting for slower providers...")
                                collect_search_results(5)
                                continue
                            if not phase_results:
                                phase_status(f"{phase_label}: no matching torrents")
                            return None

                        preview_items = []
                        for idx, result in enumerate(results_to_try[:5], start=1):
                            title = re.sub(r"\s+", " ", str(result.get("title") or "")).strip()
                            if len(title) > 60:
                                title = title[:57].rstrip() + "..."
                            source = str(result.get("source") or "unknown")
                            seeders = int(result.get("seeders") or 0)
                            preview_items.append(f"{idx}. {title} ({seeders}s, {source})")
                        if preview_items:
                            phase_status(f"{phase_label}: top candidates: {'; '.join(preview_items)}")

                        for i in range(0, len(results_to_try), 8):
                            window = results_to_try[i : i + 8]
                            phase_status(f"{phase_label}: probing batch of {len(window)} torrents...")
                            active_window_handles = []
                            active_window_keys = set()
                            for r_idx, r in enumerate(window):
                                m_link = r.get("magnet")
                                if not m_link or db.is_blacklisted(m_link):
                                    continue
                                import urllib.parse
                                if "&tr=" not in m_link:
                                    for tr in trackers:
                                        m_link += f"&tr={urllib.parse.quote(tr)}"
                                m_key = _torrent_key(m_link)
                                if m_key in active_window_keys or m_key in dead_race_keys:
                                    continue
                                active_window_keys.add(m_key)
                                attempted_keys.add(m_key)
                                save_path = race_save_path(m_link)
                                h, save_path = _register_job_to_torrent(m_link, job_id, save_path, manager, str(r.get("torrent_url") or ""))
                                for tr in trackers:
                                    try: h.add_tracker(lt.announce_entry(tr))
                                    except: pass
                                h.force_reannounce()
                                active_window_handles.append((h, m_link, r, i + r_idx, save_path))

                            start_wait = time.time()
                            metadata_candidates = []
                            scored_magnets = set()
                            probe_budget = 60 if phase_label == "Track fallback" or len(window) <= 2 else 25
                            while time.time() - start_wait < probe_budget:
                                if job_id in manager._cancel_flags:
                                    raise RuntimeError("Cancelled")
                                for h, m, r, r_idx, save_path in active_window_handles:
                                    try:
                                        if not h.is_valid() or not h.has_metadata() or m in scored_magnets:
                                            continue
                                        torrent_info = h.get_torrent_info()
                                        if not torrent_info:
                                            manager._append_cache_event(job, "trying", f"Source #{r_idx+1} metadata unavailable, trying next...")
                                            cleanup_candidate(m, save_path, delete_files=True)
                                            active_window_handles = [x for x in active_window_handles if x[1] != m]
                                            break
                                        s = h.status()
                                        live_peers = s.num_peers
                                        file_count = _torrent_num_files(torrent_info)
                                        candidate_score, skip_reason = score_metadata_candidate(
                                            torrent_info,
                                            r,
                                            r.get("_search_album") or target_album,
                                            require_track_list=require_track_list,
                                            live_peers=live_peers,
                                        )
                                        scored_magnets.add(m)
                                        if candidate_score:
                                            # Keep peers warm by downloading ONLY the matched file during
                                            # the probe, instead of zeroing every file. Telling libtorrent
                                            # it wants zero bytes makes it drop all peers (rate-based choker
                                            # + 45s inactivity timeout), so the later race starts cold at
                                            # 0 peers / 0 bytes ("Race has no byte progress yet (0p)") and a
                                            # perfectly live FLAC never downloads. Verified A/B: zero-then-
                                            # race stalls where an immediate target-priority download works.
                                            try:
                                                fidx = int(candidate_score.get("file_index", -1))
                                                if 0 <= fidx < file_count:
                                                    pr = [0] * file_count
                                                    pr[fidx] = 1
                                                    h.set_sequential_download(True)
                                                    h.prioritize_files(pr)
                                                elif file_count > 0:
                                                    h.prioritize_files([0] * file_count)
                                            except Exception:
                                                pass
                                            candidate_score["live_peers"] = live_peers
                                            metadata_candidates.append((candidate_score["score"], h, m, r, r_idx, save_path, candidate_score))
                                            disp_song = min(100, int(candidate_score["file_score"]))
                                            disp_album = min(100, int(candidate_score["album_score"]))
                                            manager._append_cache_event(job, "trying", f"Source #{r_idx+1} match: {disp_song}% (song), {disp_album}% (album). Swarm: {live_peers}p. Score: {int(candidate_score['score'])}")
                                        else:
                                            manager._append_cache_event(job, "trying", f"Source #{r_idx+1} rejected: {skip_reason}")
                                            cleanup_candidate(m, save_path, delete_files=True)
                                            active_window_handles = [x for x in active_window_handles if x[1] != m]
                                            break
                                    except Exception as exc:
                                        manager._append_cache_event(job, "trying", f"Source #{r_idx+1} probe failed: {exc}")
                                        cleanup_candidate(m, save_path, delete_files=True)
                                        active_window_handles = [x for x in active_window_handles if x[1] != m]
                                        break
                                if metadata_candidates and len(scored_magnets) >= len(active_window_handles):
                                    break
                                if not active_window_handles:
                                    break
                                time.sleep(1.0)

                            if metadata_candidates:
                                # Bias toward healthier swarms: rank by the *measured* live
                                # peer COUNT (not just >0), then score. A 5-peer source should
                                # be raced ahead of a 1-peer one.
                                metadata_candidates.sort(key=lambda item: (int(item[6].get("live_peers", 0) or 0), item[0]), reverse=True)
                                race_limit = 3 if is_prefetch else 5
                                race_candidates = metadata_candidates[:race_limit]
                                race_keys = {_torrent_key(item[2]) for item in race_candidates}
                                for _h_other, m_other, _r_other, _r_idx_other, _save_path_other in active_window_handles:
                                    if _torrent_key(m_other) not in race_keys:
                                        cleanup_candidate(m_other, _save_path_other, delete_files=True)

                                manager._append_cache_event(job, "trying", f"Racing {len(race_candidates)} matched sources; first real byte progress wins...")
                                race_state = []
                                for _score, h, m, selected_result, selected_idx, save_path, selected_meta in race_candidates:
                                    try:
                                        torrent_info = h.get_torrent_info()
                                        file_count = _torrent_num_files(torrent_info)
                                        file_idx = int(selected_meta.get("file_index", -1))
                                        if file_count <= 0 or file_idx < 0 or file_idx >= file_count:
                                            cleanup_candidate(m, save_path, delete_files=True)
                                            continue
                                        h.set_sequential_download(True)
                                        priorities = [0] * file_count
                                        priorities[file_idx] = 7
                                        h.prioritize_files(priorities)
                                        try:
                                            start_done = h.file_progress()[file_idx]
                                        except Exception:
                                            start_done = 0
                                        file_entry = torrent_info.file_at(file_idx)
                                        file_path = save_path / file_entry.path
                                        race_state.append({
                                            "score": _score,
                                            "handle": h,
                                            "magnet": m,
                                            "result": selected_result,
                                            "idx": selected_idx,
                                            "save_path": save_path,
                                            "meta": selected_meta,
                                            "file_idx": file_idx,
                                            "file_path": str(file_path),
                                            "file_size": int(file_entry.size),
                                            "start_done": start_done,
                                        })
                                    except Exception:
                                        cleanup_candidate(m, save_path, delete_files=True)

                                race_winner = None
                                race_start = time.time()
                                race_reannounced = False
                                while race_state and time.time() - race_start < 24:
                                    if job_id in manager._cancel_flags:
                                        raise RuntimeError("Cancelled")
                                    best_state = None
                                    best_delta = 0
                                    total_peers = 0
                                    for state in list(race_state):
                                        h = state["handle"]
                                        if not h.is_valid():
                                            cleanup_candidate(state["magnet"], state["save_path"], delete_files=True)
                                            race_state.remove(state)
                                            continue
                                        try:
                                            status = h.status()
                                            done = h.file_progress()[state["file_idx"]]
                                        except Exception:
                                            cleanup_candidate(state["magnet"], state["save_path"], delete_files=True)
                                            race_state.remove(state)
                                            continue
                                        state["last_done"] = int(done)
                                        delta = max(0, int(done) - int(state["start_done"]))
                                        total_peers += int(getattr(status, "num_peers", 0) or 0)
                                        if delta > best_delta or (delta == best_delta and best_state is None):
                                            best_delta = delta
                                            best_state = state
                                    race_progress = {
                                        str(state["file_path"]): {
                                            "ready": max(0, int(state.get("last_done", state.get("start_done", 0)))),
                                            "total": int(state.get("file_size") or 0),
                                        }
                                        for state in race_state
                                        if state.get("file_path")
                                    }
                                    # Winner = the FASTEST source (most bytes pulled so far),
                                    # not the first in list order. Decide once any source has
                                    # clearly started (16 KB) or after a short grace window so
                                    # the quicker swarm has a chance to pull ahead.
                                    if best_state is not None and (
                                        best_delta >= 16 * 1024
                                        or (best_delta > 0 and time.time() - race_start >= 4)
                                    ):
                                        race_winner = best_state
                                        break
                                    if not race_reannounced and time.time() - race_start > 8:
                                        for state in race_state:
                                            try:
                                                state["handle"].force_reannounce()
                                            except Exception:
                                                pass
                                        race_reannounced = True
                                        manager._append_cache_event(job, "trying", f"Race has no byte progress yet ({total_peers}p); re-announcing candidates...")
                                    with manager._lock:
                                        job["race_audio_progress"] = race_progress
                                        job["last_status"] = f"Racing sources: {best_delta} bytes, {total_peers}p"
                                    time.sleep(1.0)

                                if not race_winner:
                                    zero_byte_race_failures += 1
                                    ensure_yt_fallback_started("Torrent race has no byte progress; starting YouTube fallback in parallel...")
                                    for state in race_state:
                                        dead_race_keys.add(_torrent_key(state["magnet"]))
                                        cleanup_candidate(state["magnet"], state["save_path"], delete_files=True)
                                    manager._append_cache_event(job, "trying", "Race found no downloading source, trying next candidates...")
                                    if zero_byte_race_failures >= 2 and use_ready_fallback(
                                        "Repeated zero-byte torrent races; checking fallback before more torrent candidates...",
                                        wait_seconds=10,
                                    ):
                                        return True
                                    continue

                                h = race_winner["handle"]
                                m = race_winner["magnet"]
                                selected_result = race_winner["result"]
                                selected_idx = race_winner["idx"]
                                save_path = race_winner["save_path"]
                                selected_meta = race_winner["meta"]
                                selected_key = _torrent_key(m)
                                for state in race_state:
                                    if _torrent_key(state["magnet"]) != selected_key:
                                        cleanup_candidate(state["magnet"], state["save_path"], delete_files=True)

                                live_peer_note = f", {int(selected_meta.get('live_peers') or 0)}p"
                                manager._append_cache_event(job, "trying", f"Race winner source #{selected_idx+1}: {selected_result.get('title','')[:45]} (album {min(100, int(selected_meta['album_score']))}%, file {min(100, int(selected_meta['file_score']))}{live_peer_note})")
                                current_magnet = m
                                torrent_save_path = save_path
                                _scr = stream_to_completion(h, m, save_path, is_artist_verified=selected_result.get("_artist_verified", True))

                                if _scr:
                                    # Winner finished! (stream_to_completion already called finalize_selected_file)
                                    if apply_search_album:
                                        resolved_album_from_search = selected_result.get("_search_album") or target_album

                                    # GEMINI: Only delete if this was the last reference; 
                                    # finalization already COPIED the file out of _race.
                                    cleanup_candidate(m, save_path, delete_files=True)
                                    current_magnet = None
                                    return h
                                if _scr is False:
                                    db.add_to_blacklist(m, "stalled during streaming")

                                # If we got here, this specific winner failed or couldn't finalize.
                                cleanup_candidate(m, save_path, delete_files=True)
                                current_magnet = None
                                active_window_handles = [x for x in active_window_handles if x[1] != m]
                                continue
                            for h, m, r, r_idx, save_path in active_window_handles:
                                if m not in scored_magnets:
                                    manager._append_cache_event(job, "trying", f"Source #{r_idx+1} unresponsive during metadata probe, trying next...")
                                cleanup_candidate(m, save_path, delete_files=True)

                        if pending_search_futures and time.time() < search_deadline:
                            phase_status(f"{phase_label}: checking late provider results...")
                            collect_search_results(5)
                            continue
                        return None
                finally:
                    if search_executor:
                        search_executor.shutdown(wait=False, cancel_futures=True)

            # INSTANT CACHE attempt: reuse the known-good magnet for this album.
            if cached_magnet and not db.is_blacklisted(cached_magnet):
                handle, torrent_save_path = _register_job_to_torrent(cached_magnet, job_id, output_dir, manager)
                current_magnet = cached_magnet
                
                # Wait for metadata to resolve (up to 30 seconds).
                # Magnet links need DHT propagation time; 8s is too short for
                # low-peer swarms that still resolve within a normal download window.
                meta_start = time.time()
                has_meta = False
                while time.time() - meta_start < 30.0:
                    if job_id in manager._cancel_flags:
                        raise RuntimeError("Cancelled")
                    if handle.is_valid() and handle.status().has_metadata:
                        has_meta = True
                        break
                    time.sleep(0.5)

                if has_meta:
                    manager._append_cache_event(job, "trying", f"Step 0: Reusing swarm for: {album}")
                    _scr = stream_to_completion(handle, current_magnet, torrent_save_path, is_artist_verified=True, cached_reuse=True)
                    if _scr:
                        return
                    # Only blacklist/delete on a hard failure
                    if _scr is False:
                        db.add_to_blacklist(cached_magnet, "cached source failed")
                        db.delete_resolved_source(job.get("track_key") or "")
                        db.delete_album_source(album_key)
                else:
                    manager._append_cache_event(job, "trying", "Cached source metadata not resolved in 30s; falling back to discovery search...")

                _unregister_job_from_torrent(current_magnet, job_id)
                handle = None
                current_magnet = None

            yt_fallback_thread = None
            yt_fallback_done = threading.Event()
            yt_fallback_produced = False

            def run_yt_fallback():
                nonlocal yt_fallback_produced
                try:
                    import backend_ytpdl
                    # Use a shadow job to avoid clobbering torrent status/progress
                    # while torrent races keep searching.
                    shadow_job = dict(job)
                    shadow_job["progress"] = 0
                    shadow_job["last_status"] = "YouTube Fallback started"
                    if job.get("fallback_resolved_url"):
                        shadow_job["resolved_url"] = job["fallback_resolved_url"]

                    class ShadowManager:
                        def __getattr__(self, name): return getattr(manager, name)
                        def _append_cache_event(self, _j, type, msg):
                            manager._append_cache_event(job, type, f"[YT Fallback] {msg}")

                    backend_ytpdl.run(output_dir, shadow_job, ShadowManager())
                    if any(
                        p for p in output_dir.rglob("*")
                        if p.is_file()
                        and "_race" not in p.relative_to(output_dir).parts
                        and is_download_audio_candidate(p)
                    ):
                        yt_fallback_produced = True
                except Exception as e:
                    manager._append_cache_event(job, "trying", f"YouTube fallback failed: {e}")
                finally:
                    yt_fallback_done.set()

            def ensure_yt_fallback_started(reason: str) -> None:
                nonlocal yt_fallback_thread
                if yt_fallback_thread:
                    return
                manager._append_cache_event(job, "trying", reason)
                yt_fallback_thread = threading.Thread(target=run_yt_fallback, daemon=True, name=f"yt-fallback-{job_id}")
                yt_fallback_thread.start()

            def use_ready_fallback(reason: str, wait_seconds: float = 0) -> bool:
                if not yt_fallback_thread:
                    return False
                if wait_seconds > 0:
                    manager._append_cache_event(job, "trying", reason)
                    yt_fallback_done.wait(timeout=wait_seconds)
                if yt_fallback_done.is_set() and yt_fallback_produced:
                    manager._append_cache_event(job, "provider", "Torrent races stayed at zero bytes, using YouTube fallback")
                    return True
                return False

            # 1. Race direct track, clicked-album, and artist inventory searches.
            first_pass_queries = candidate_first_pass_queries()
            if first_pass_queries:
                handle = run_search_phase(
                    "First pass",
                    album_clean or "",
                    first_pass_queries,
                    max_sources=80,
                    allow_album_miss=True,
                    require_track_list=False,
                )

            if not handle:
                ensure_yt_fallback_started("First pass failed; keeping YouTube fallback running in parallel...")

                # 2. Search the selected artist's inventory first...
                handle = run_search_phase(
                    "Artist inventory",
                    album_clean or "complete",
                    candidate_inventory_queries(),
                    max_sources=40,
                    allow_album_miss=True,
                )
                if not handle and zero_byte_race_failures >= 2 and use_ready_fallback(
                    "Repeated zero-byte torrent races; waiting briefly for YouTube fallback...",
                    wait_seconds=45,
                ):
                    return

            # 3. If inventory did not expose a usable album/track match, try the
            #    clicked album directly.
            if not handle and album_clean:
                handle = run_search_phase(
                    "Clicked album",
                    album_clean,
                    candidate_queries_for_album(album_clean),
                )
                if not handle and yt_fallback_thread and zero_byte_race_failures >= 2 and use_ready_fallback(
                    "Torrent candidates are still not transferring bytes; checking fallback...",
                    wait_seconds=20,
                ):
                    return

            # 4. If the album searches only found wrong albums or dead swarms, try
            #    direct single-track sources before the much wider MusicBrainz
            #    album expansion. This handles sparse catalog tracks where no
            #    healthy full-album torrent exists.
            if not handle and title_clean:
                handle = run_search_phase(
                    "Track fallback",
                    "",
                    candidate_track_queries(),
                    max_sources=60,
                    require_track_list=False,
                )
                if not handle and yt_fallback_thread and zero_byte_race_failures >= 2 and use_ready_fallback(
                    "Track torrent fallback also has no byte progress; checking fallback...",
                    wait_seconds=20,
                ):
                    return

            # 5. Artist inventory, clicked-album, and direct-track search failed:
            #    resolve the track's real album(s) via
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

        # Each candidate is downloaded to completion inside try_result_source;
        # a truthy handle here means the file was already produced. A falsy
        # handle means every candidate failed or stalled.
        if not handle:
            if yt_fallback_thread:
                manager._append_cache_event(job, "trying", "All torrent phases failed; waiting for YouTube fallback to finish...")
                yt_fallback_done.wait(timeout=300) # Wait up to 5 more minutes for YT
                if yt_fallback_produced:
                    manager._append_cache_event(job, "provider", "Torrent failed, but successfully fell back to YouTube")
                    return
            
            raise RuntimeError("All sources failed or stalled.")
    finally:
        _unregister_all_for_job(job_id, delete_files=True)
