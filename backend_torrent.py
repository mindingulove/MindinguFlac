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
from typing import Callable
from urllib.parse import parse_qs, urlparse
import urllib.request
try:
    import torrfetch
except ImportError:
    torrfetch = None

_IS_ANDROID = os.environ.get("MINDINGUFLAC_ANDROID") == "1"
try:
    if _IS_ANDROID:
        lt = None
    else:
        import libtorrent as lt
except (ImportError, OSError) as _lt_exc:
    # On Windows the win_amd64 libtorrent wheel needs the x64 VC++ runtime,
    # which is absent on a fresh Windows-on-ARM box. Try to install it, then
    # retry the import; if that's not possible this raises an actionable,
    # link-bearing error that the cache-job UI surfaces to the user.
    if _IS_ANDROID:
        lt = None
    else:
        from vcredist import ensure_vc_redist_for_libtorrent
        ensure_vc_redist_for_libtorrent(_lt_exc)
        import libtorrent as lt
# RapidFuzz's pure-Python source distribution is bundled in the APK, so the
# deterministic fuzzy matching below runs on Android too; only the native
# libtorrent wheel is desktop-only.
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


def _search_all_tracker_providers(
    query: str,
    metadata: dict,
    timeout: int = 6,
    artist: str = "",
    album: str = "",
    include_1337x: bool = True,
) -> dict[str, list[dict]]:
    """Fetch every configured torrent provider concurrently for one query."""
    import torrent_sources

    category = torrent_sources.torrentdownloads_category_from_metadata(metadata)
    calls = {
        "torlock": lambda: torrent_sources.search_torlock(query, timeout=timeout),
        "torrentdownloads": lambda: torrent_sources.search_torrentdownloads(query, category, timeout=timeout),
        "limetorrents": lambda: torrent_sources.search_limetorrents(query, timeout=timeout),
        "kickass": lambda: torrent_sources.search_kickass(query, timeout=timeout),
        "solidtorrents": lambda: torrent_sources.search_solid(query, timeout=timeout),
        "knaben": lambda: torrent_sources.search_knaben(query, timeout=timeout),
        "apibay": lambda: torrent_sources.search_apibay(query, timeout=timeout),
        "piratebay": lambda: torrfetch.search_torrents(query, only=["piratebay"]) or [],
        "yts": lambda: torrfetch.search_torrents(query, only=["yts"]) or [],
    }
    if include_1337x:
        calls["1337x"] = lambda: torrent_sources.search_1337x(
            query, timeout=timeout, artist=artist, album=album,
            desktop_compact=True,
        )
    found = {name: [] for name in calls}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(call): name for name, call in calls.items()}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=30):
                name = futures[future]
                try:
                    found[name] = future.result() or []
                except Exception:
                    found[name] = []
        except concurrent.futures.TimeoutError:
            pass
    return found


def _filter_and_rank_provider_results(
    provider_results: dict[str, list[dict]],
    relevance: Callable[[dict], float],
) -> list[dict]:
    """Fuzzy-filter and swarm-rank each provider before merging its results."""
    merged = []
    for provider_rows in provider_results.values():
        ranked = []
        for row in provider_rows:
            try:
                if int(row.get("seeders") or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            try:
                score = relevance(row)
            except Exception:
                continue
            if score <= 50:
                continue
            candidate = dict(row)
            candidate["_score"] = score
            ranked.append(candidate)
        ranked.sort(
            key=lambda item: (
                int(item.get("seeders") or 0),
                int(item.get("seeders") or 0) / max(1, int(item.get("leechers") or item.get("peers") or 0)),
                int(item.get("seeders") or 0) + int(item.get("leechers") or item.get("peers") or 0),
                int(item.get("_score") or 0),
            ),
            reverse=True,
        )
        merged.extend(ranked)
    return merged

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
_WARM_ALBUM_LEASES = {}

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

_GLOBAL_SES = None if _IS_ANDROID else _create_optimized_session()

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


def _torrent_race_slots(config=None, prefetch=False) -> int:
    name = "torrent_prefetch_candidates" if prefetch else "torrent_playback_candidates"
    default = 2 if prefetch else 3
    try:
        value = getattr(config, name, os.environ.get("MINDINGUFLAC_TORRENT_RACE_SLOTS", default))
        return max(1, min(8, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def _torrent_metadata_timeout_seconds(config=None) -> int:
    try:
        return max(10, min(180, int(getattr(config, "torrent_metadata_timeout_seconds", 60))))
    except (ValueError, TypeError, OverflowError):
        return 60


def _album_similarity_without_track_words(album: str, candidate_title: str, track_title: str) -> int:
    """Compare an album to a release title after removing the requested track words.

    Torrent result titles often contain both the album and track name. Removing
    the track tokens keeps feature credits and other track-specific words from
    distorting the album comparison, while token-set matching tolerates release
    descriptors such as format and edition labels.
    """
    def tokens(value: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", (value or "").casefold())

    track_tokens = set(tokens(track_title))
    candidate_tokens = [token for token in tokens(candidate_title) if token not in track_tokens]
    candidate_without_track = " ".join(candidate_tokens)
    return rapidfuzz.fuzz.token_set_ratio(" ".join(tokens(album)), candidate_without_track)


def _rolling_torrent_race(next_candidate, start, poll, cleanup, cancelled,
                          *, slots=3, sleep=time.sleep):
    """Keep independent probes alive; yield byte-producing candidates.

    poll returns None while pending, False on failure, or a positive byte delta.
    Yielded candidates belong to the caller; pending candidates remain alive if
    a winner later stalls. Closing the iterator releases all pending probes.
    """
    active = []
    try:
        while True:
            if cancelled():
                raise RuntimeError("Cancelled")
            while len(active) < (slots() if callable(slots) else slots):
                candidate = next_candidate()
                if candidate is None:
                    break
                state = start(candidate)
                if state is not None:
                    active.append(state)
            if not active:
                return
            ready = []
            failed = False
            for state in list(active):
                progress = poll(state)
                if progress is False:
                    active.remove(state)
                    cleanup(state)
                    failed = True
                elif progress is not None and progress > 0:
                    ready.append((progress, state))
            if ready:
                _, winner = max(ready, key=lambda item: item[0])
                active.remove(winner)
                yield winner
            elif not failed:
                sleep(0.5)
            # Failed slots refill immediately, without waiting for their peers.
    finally:
        for state in active:
            cleanup(state)


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


def _torrent_contiguous_ready(handle, info, file_index: int) -> int:
    """Only verified pieces from the file's start are safe to stream."""
    request = info.map_file(file_index, 0, 0)
    piece_size = int(info.piece_length())
    size = int(info.file_at(file_index).size)
    piece = int(request.piece)
    ready = -int(request.start)
    while ready < size and handle.have_piece(piece):
        ready += piece_size
        piece += 1
    return max(0, min(size, ready))


def _remember_torrent_source(job, magnet, manager):
    if getattr(manager, "config", None) is None:
        return
    import db
    key = job.get("track_key") or f"{str(job.get('artist') or '').lower()}||{str(job.get('title') or '').lower()}"
    db.save_resolved_source(
        track_key=key, engine="torrent", service=job.get("service") or "all",
        quality=job.get("quality") or "LOSSLESS", resolved_url=magnet,
    )
    artist = str(job.get("artist") or "").lower()
    album = str(job.get("album") or "").lower()
    if album and album != "unknown":
        db.save_album_source(album_key=f"{artist}||{album}", engine="torrent", resolved_url=magnet)


def _keep_torrent_warm(magnet):
    key = _torrent_key(magnet)
    lease = f"warm:{time.monotonic_ns()}"
    def expire():
        with _SESSIONS_LOCK:
            current = _WARM_ALBUM_LEASES.get(key)
            if current and current[0] == lease:
                _WARM_ALBUM_LEASES.pop(key, None)
        _unregister_job_from_torrent(magnet, lease)
    timer = threading.Timer(180, expire)
    timer.daemon = True
    with _SESSIONS_LOCK:
        entry = _ACTIVE_SESSIONS.get(key)
        if not entry:
            return
        entry["refs"].add(lease)
        old = _WARM_ALBUM_LEASES.get(key)
        if old:
            old[1].cancel()
            entry["refs"].discard(old[0])
        _WARM_ALBUM_LEASES[key] = (lease, timer)
    timer.start()

def _register_job_to_torrent(magnet: str, job_id: str, output_dir: Path, manager, torrent_url: str = "") -> tuple:
    key = _torrent_key(magnet)
    # HTTP metadata fetching must not hold the session lock: otherwise one slow
    # provider serializes every candidate (and every other track's registration).
    with _SESSIONS_LOCK:
        entry = _ACTIVE_SESSIONS.get(key)
        reuse = entry is not None and entry["handle"].is_valid()
    torrent_info = _torrent_info_from_url(torrent_url) if torrent_url and not reuse else None
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
            'storage_mode': lt.storage_mode_t(2),
            'flags': lt.add_torrent_params().flags | lt.torrent_flags.default_dont_download,
        }
        if torrent_info:
            add_params = lt.add_torrent_params()
            add_params.save_path = str(output_dir)
            add_params.storage_mode = lt.storage_mode_t(2)
            add_params.ti = torrent_info
            add_params.file_priorities = [0] * _torrent_num_files(torrent_info)
            add_params.flags |= lt.torrent_flags.default_dont_download
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
    if _IS_ANDROID:
        try:
            from android_runtime.torrent_backend import cancel
            cancel(job_id)
        except Exception:
            pass
        return

    with _SESSIONS_LOCK:
        to_unregister = []
        for key, entry in list(_ACTIVE_SESSIONS.items()):
            if job_id in entry.get("refs", set()):
                if delete_files:
                    warm = _WARM_ALBUM_LEASES.pop(key, None)
                    if warm:
                        warm[1].cancel()
                        entry["refs"].discard(warm[0])
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
    if str(job.get("quality") or "").strip().lower() in {"video", "mp4-video", "music_video"}:
        import backend_ytpdl
        manager._append_cache_event(job, "provider", "Video request routed to YouTube; torrent engine is reserved for music")
        backend_ytpdl.run(output_dir, job, manager)
        return
    if _IS_ANDROID:
        from android_runtime.torrent_backend import run as run_android_torrent
        run_android_torrent(output_dir, job, manager)
        return

    # 0. Setup
    job_id = job["id"]
    playback_started_at = time.monotonic()
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
    lossless_required = quality_str in {"LOSSLESS", "FLAC", "ALAC", "WAV", "AIFF", "APE", "WV", "DSD"}
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

        lossless_suffixes = {
            ".flac", ".alac", ".wav", ".wave", ".aiff", ".aif", ".aifc",
            ".ape", ".wv", ".dsf", ".dff", ".dsd", ".shn", ".tta", ".tak",
        }

        def allowed_torrent_audio(path: Path) -> bool:
            suffix = path.suffix.lower()
            return suffix in AUDIO_SUFFIXES and (not lossless_required or suffix in lossless_suffixes)

        def audio_file_indexes(torrent_info) -> list[int]:
            indexes = []
            for i in range(_torrent_num_files(torrent_info)):
                f_path = Path(torrent_info.file_at(i).path)
                if allowed_torrent_audio(f_path):
                    indexes.append(i)
            return indexes

        def find_best_audio_file(torrent_info, is_artist_verified: bool = True) -> tuple[int, int]:
            best_f_idx = -1
            best_f_score = -1
            track_pats = [f"{track_num.zfill(2)}.", f" {track_num.zfill(2)} ", f"- {track_num.zfill(2)} "] if track_num else []
            
            # Words that MUST appear for the match to be considered valid.
            # We filter out common noise that might be in Spotify title but not filename.
            noise_words = {"live", "edit", "version", "mono", "stereo", "mix", "remix", "single", "digitally", "beginning", "part", "ost", "edition", "lossless", "feat", "featuring", "bit", "bits", "khz", "hz", "kbps", "web", "rip"}
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
                if allowed_torrent_audio(f_path):
                    f_name_lower = f_path.name.lower()
                    annotations = [part for pair in re.findall(r"\(([^)]*)\)|\[([^]]*)\]", f_path.stem) for part in pair if part]
                    annotation_tokens = {
                        token.lower() for annotation in annotations
                        for token in re.findall(r"[a-z]+", annotation.lower())
                    }
                    if annotation_tokens - meaningful_tokens - noise_words:
                        continue
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
                        album_score = max(
                            album_score,
                            _album_similarity_without_track_words(
                                target_album_clean, candidate, raw_title
                            ),
                        )

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
        # Prefer the proven album-wide swarm for every track on that album,
        # even if this queued track carries an older track-specific URL.
        album_source = db.get_album_source(album_key)
        if album_source and album_source.get("engine") == "torrent" and str(album_source.get("resolved_url") or "").startswith("magnet:"):
            cached_magnet = album_source.get("resolved_url")
        elif not cached_magnet or not str(cached_magnet).startswith("magnet:"):
            cached_magnet = catalog.get(album_key)
        
        handle = None
        torrent_save_path = output_dir
        # The cached-magnet fast path is attempted later, once stream_to_completion
        # is defined (see "INSTANT CACHE attempt" below).

        # 2. DISCOVERY ENGINE
        if not handle:
            # `target_album` is assigned later while iterating broad search
            # phases, so it is a local in this enclosing function and cannot
            # be referenced here before that loop runs. Use the track's
            # resolved album as the default for the initial discovery queries.
            def do_search_safe(q, svc, search_album=album_clean, include_1337x=True):
                results = []
                import torrent_sources
                try:
                    torrentdownloads_category = torrent_sources.torrentdownloads_category_from_metadata(metadata)
                    if svc == "all":
                        provider_results = _search_all_tracker_providers(
                            q, metadata, artist=primary_artist, album=search_album,
                            include_1337x=include_1337x,
                        )
                        results = _filter_and_rank_provider_results(
                            provider_results,
                            lambda row: score_torrent_result(
                                row, primary_artist, title_clean, search_album,
                                allow_album_miss=allow_album_miss,
                            ),
                        )
                    elif svc == "torrentdownloads":
                        results = torrent_sources.search_torrentdownloads(q, torrentdownloads_category, timeout=4)
                    elif svc == "limetorrents":
                        results = torrent_sources.search_limetorrents(q, timeout=4)
                    elif svc == "torlock":
                        results = torrent_sources.search_torlock(q, timeout=4)
                    elif svc == "1337x":
                        results = torrent_sources.search_1337x(q, timeout=4, artist=primary_artist, album=search_album)
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
                    "beginning", "part", "ost", "soundtrack",
                    "original", "motion", "picture", "limited", "edition",
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

                if is_classical_search:
                    for query in candidate_track_queries():
                        add(query, "")
                    if album_clean:
                        for query in candidate_queries_for_album(album_clean):
                            add(query, album_clean)
                    if album_looks_like_primary_artist_release():
                        for query in candidate_inventory_queries():
                            add(query, album_clean or "complete")
                elif album_clean:
                    # Keep the first pass focused. Every selected tracker runs
                    # for each query, and 1337x itself searches the album/query
                    # variants and resolves detail pages. Sending the full
                    # track + album + six-query artist inventory here caused
                    # the same provider work to be multiplied across ten
                    # simultaneous queries; Android's three-query pass found
                    # healthy album swarms that desktop then missed to timeouts.
                    for artist in artist_variations:
                        add(f"{artist} {album_clean} FLAC", album_clean)
                        add(f"{artist} {raw_title} FLAC", "")
                        add(f"{artist} {album_clean} lossless", album_clean)
                else:
                    for artist in artist_variations:
                        add(f"{artist} {raw_title} FLAC", "")
                        add(f"{raw_title} FLAC", "")
                        add(f"{artist} {raw_title} lossless", "")
                return queries

            def stream_to_completion(handle, magnet, save_path: Path | None = None, is_artist_verified: bool = True) -> bool | None:
                # Download the best matching file to completion. Returns True on
                # success (file placed in output_dir), False on hard source
                # failure, or None on a soft stall so the rolling race resumes.
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
                    if not job.get("active_audio_is_youtube_fallback"):
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
                        job["active_audio_is_youtube_fallback"] = False
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
                while True:
                    if job_id in manager._cancel_flags: raise RuntimeError("Cancelled")
                    if not handle.is_valid():
                        if finalize_selected_file():
                            return True
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
                        with manager._lock:
                            if job.get("torrent_first_byte_at") is None:
                                job["torrent_first_byte_at"] = time.monotonic()
                        # Reset re-announce flag so we can wake the swarm again if it stalls later
                        reannounced_once = False

                    update_shared_priorities()
                    prog = (done / total) * 100 if total > 0 else 0
                    with manager._lock:
                        job["progress"] = int(prog)
                        job["last_status"] = f"Streaming: {int(prog)}% ({s.download_rate/1024:.1f}kB/s, {s.num_peers}p)"
                        if not job.get("active_audio_is_youtube_fallback"):
                            job["active_audio_path"] = str(target_abs)
                            job["active_audio_size"] = total
                            job["active_audio_ready_bytes"] = _torrent_contiguous_ready(handle, torrent_info, best_f_idx)
                    if done >= total and total > 0:
                        return finalize_selected_file()
                    # Stall handling. Reported seed counts are often stale; a
                    # selected torrent with zero connected peers and zero bytes
                    # should not hold the player for a long stall window.
                    since_progress = time.time() - last_progress_time
                    reannounce_after = 12
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

                    if since_progress >= (90 if last_done > 0 else 24):
                        manager._append_cache_event(job, "trying", f"Selected track stalled for {int(since_progress)}s; continuing parallel candidates...")
                        return None
                    if time.time() - start_time > 1800: return False
                    time.sleep(2)

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
                if phase_label == "First pass" and cached_magnet and not db.is_blacklisted(cached_magnet):
                    phase_results.append({
                        "magnet": cached_magnet, "title": album or title_clean,
                        "source": "cached album", "_score": 10000,
                        "_artist_verified": True, "_album_verified": True,
                        "_search_album": album_clean, "seeders": 0,
                    })
                cached_source_pending = bool(
                    phase_label == "First pass" and cached_magnet
                    and not db.is_blacklisted(cached_magnet)
                )

                def cached_source_failed(reason: str) -> None:
                    nonlocal cached_source_pending
                    if not cached_source_pending:
                        return
                    cached_source_pending = False
                    try:
                        saved = db.get_album_source(album_key) or {}
                        if _torrent_key(str(saved.get("resolved_url") or "")) == _torrent_key(cached_magnet):
                            db.delete_album_source(album_key)
                            phase_status(f"Saved album torrent failed ({reason}); removed it and searching replacements")
                    except Exception:
                        pass
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
                            # Live indexed candidates without reported seeders
                            # cannot enter the race. A proven cached album
                            # magnet is handled separately above and remains
                            # eligible even without a refreshed swarm count.
                            try:
                                if int(r.get("seeders") or 0) <= 0:
                                    continue
                            except (TypeError, ValueError):
                                continue
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
                    duck_model, ai_provider, gemini_model = ai_reranker.provider_settings(config)
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

                    def swarm_order(item: dict) -> tuple[int, float, int, int, int, int]:
                        try:
                            seeds = int(item.get("seeders") or 0)
                        except (TypeError, ValueError):
                            seeds = 0
                        try:
                            peers = int(item.get("leechers") or item.get("peers") or 0)
                        except (TypeError, ValueError):
                            peers = 0
                        key = _torrent_key(str(item.get("magnet") or ""))
                        return (
                            seeds,
                            seeds / max(peers, 1),
                            seeds + peers,
                            peers,
                            int(item.get("_score") or 0),
                            -ai_positions.get(key, 10_000),
                        )

                    ordered = sorted(
                        _dedupe_results(phase_results),
                        key=swarm_order,
                        reverse=True,
                    )
                    if cached_source_pending:
                        cached_key = _torrent_key(cached_magnet)
                        ordered.sort(key=lambda row: _torrent_key(str(row.get("magnet") or "")) != cached_key)
                    out = []
                    for result in ordered:
                        m_link = result.get("magnet") or ""
                        if m_link and _torrent_key(m_link) not in attempted_keys and _torrent_key(m_link) not in dead_race_keys:
                            out.append(result)
                    return out[:max_sources]

                try:
                    if query_specs:
                        if _normalize_service(job.get("service") or "all") == "all":
                            phase_status(
                                f"{phase_label}: all tracker providers in parallel: "
                                "TorLock, TorrentDownloads, LimeTorrents, The Pirate Bay, "
                                "1337x, KickassTorrents, YTS, SolidTorrents, Knaben, APIBay"
                            )
                        search_executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(query_specs)))
                        pending_search_futures = {
                            search_executor.submit(
                                do_search_safe, q, service, query_album,
                                query_index == 0,
                            ): (q, query_album)
                            for query_index, (q, query_album) in enumerate(query_specs)
                        }

                    search_deadline = time.time() + (55 if phase_label in {"First pass", "Track fallback"} else 40)
                    # Let provider results join the same list before opening
                    # slots, including when a cached magnet is available. This
                    # gives live swarm counts from every indexer a chance to
                    # outrank a stale cached source.
                    # Don't launch low-swarm candidates from a partial provider
                    # pool. Each query's provider fan-out is bounded above, so
                    # this gathers the completed results before swarm ranking.
                    # A saved album magnet is a proven source. Probe it
                    # immediately and exclusively; provider results can be
                    # collected in the background and opened as a race only
                    # if the saved source fails.
                    collect_search_results(0.1 if cached_source_pending else 30)
                    start_ai_advisor_if_ready()

                    while True:
                        collect_search_results(0.1)
                        start_ai_advisor_if_ready()
                        if ai_thread and not ai_first_batch_waited and not attempted_keys and not cached_magnet:
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
                            peers = int(result.get("leechers") or result.get("peers") or 0)
                            ratio = seeders / max(peers, 1)
                            preview_items.append(f"{idx}. {title} ({seeders}s/{peers}p, {ratio:.2f} S/L, {source})")
                        if preview_items:
                            phase_status(f"{phase_label}: unified top candidates after provider fuzzy/swarm ranking: {'; '.join(preview_items)}")

                        def next_candidate():
                            collect_search_results(0.001)
                            for result in ordered_untried_results():
                                magnet = result.get("magnet")
                                key = _torrent_key(magnet)
                                attempted_keys.add(key)
                                if not db.is_blacklisted(magnet):
                                    return result
                            return None

                        def start_candidate(result):
                            magnet = result["magnet"]
                            import urllib.parse
                            if "&tr=" not in magnet:
                                for tracker in trackers:
                                    magnet += f"&tr={urllib.parse.quote(tracker)}"
                            source_name = str(result.get("source") or "unknown")
                            seed_count = int(result.get("seeders") or 0)
                            peer_count = int(result.get("leechers") or result.get("peers") or 0)
                            if source_name == "cached album":
                                phase_status(f"{phase_label}: testing saved album magnet first (live swarm count not refreshed): {result.get('title', '')[:60]}")
                            else:
                                phase_status(f"{phase_label}: starting parallel candidate ({source_name}, {seed_count}s/{peer_count}p): {result.get('title', '')[:60]}")
                            return {
                                "magnet": magnet,
                                "result": result,
                                "save_path": race_save_path(magnet),
                                "future": registration_executor.submit(
                                    _register_job_to_torrent, magnet, job_id,
                                    race_save_path(magnet), manager,
                                    str(result.get("torrent_url") or ""),
                                ),
                                "started": time.monotonic(),
                                "reannounced": False,
                            }

                        def release_candidate(state):
                            # Registration may still be finishing during cancellation.
                            # Collect it before unregistering so it cannot leak a ref.
                            try:
                                if "handle" not in state:
                                    h, path = state["future"].result()
                                    state["handle"], state["save_path"] = h, path
                            except Exception:
                                pass
                            cleanup_candidate(state["magnet"], state["save_path"], delete_files=True)
                            with manager._lock:
                                job.get("race_audio_progress", {}).pop(state.get("file_path"), None)

                        def poll_candidate(state):
                            nonlocal zero_byte_race_failures
                            now = time.monotonic()
                            try:
                                if "handle" not in state:
                                    if not state["future"].done():
                                        return None
                                    h, path = state["future"].result()
                                    state["handle"], state["save_path"] = h, path
                                    for tracker in trackers:
                                        try: h.add_tracker(lt.announce_entry(tracker))
                                        except Exception: pass
                                    h.force_reannounce()
                                h = state["handle"]
                                if not h.is_valid():
                                    cached_source_failed("torrent handle became invalid")
                                    return False
                                elapsed = now - state["started"]
                                if "meta" not in state:
                                    if not h.has_metadata():
                                        if elapsed < _torrent_metadata_timeout_seconds(manager.config):
                                            return None
                                        phase_status("Candidate metadata timed out; replacing this slot...")
                                        dead_race_keys.add(_torrent_key(state["magnet"]))
                                        cached_source_failed("metadata timed out")
                                        return False
                                    info = h.get_torrent_info()
                                    meta, reason = score_metadata_candidate(
                                        info, state["result"],
                                        state["result"].get("_search_album") or target_album,
                                        require_track_list=require_track_list,
                                        live_peers=h.status().num_peers,
                                    )
                                    if not meta:
                                        phase_status(f"Candidate rejected: {reason}; replacing this slot...")
                                        cached_source_failed(reason)
                                        return False
                                    state["meta"] = meta
                                    file_idx = int(meta["file_index"])
                                    priorities = [0] * _torrent_num_files(info)
                                    priorities[file_idx] = 7
                                    h.set_sequential_download(True)
                                    h.prioritize_files(priorities)
                                    state["file_idx"] = file_idx
                                    state["file_path"] = str(state["save_path"] / info.file_at(file_idx).path)
                                    state["file_size"] = int(info.file_at(file_idx).size)
                                    state["start_done"] = int(h.file_progress()[file_idx])
                                    state["probe_started"] = now
                                    peer_status = h.status()
                                    phase_status(
                                        f"Candidate matched; testing track bytes ({peer_status.num_peers} peers, "
                                        f"{getattr(peer_status, 'num_seeds', 0)} seeds): {state['result'].get('title', '')[:60]}"
                                    )
                                done = int(h.file_progress()[state["file_idx"]])
                                state["last_done"] = done
                                delta = max(0, done - state["start_done"])
                                age = now - state["probe_started"]
                                with manager._lock:
                                    job.setdefault("race_audio_progress", {})[state["file_path"]] = {
                                        "ready": done, "total": state["file_size"],
                                    }
                                if done >= state["file_size"] > 0:
                                    return max(1, delta)
                                prefix = _torrent_contiguous_ready(h, h.get_torrent_info(), state["file_idx"])
                                if prefix > 0 and (delta >= 16 * 1024 or (delta > 0 and age >= 4)):
                                    return min(delta, prefix)
                                no_byte_grace = max(60, _torrent_metadata_timeout_seconds(manager.config))
                                if age >= no_byte_grace:
                                    zero_byte_race_failures += 1
                                    dead_race_keys.add(_torrent_key(state["magnet"]))
                                    peer_status = h.status()
                                    phase_status(
                                        f"Candidate has no track byte progress after {no_byte_grace}s "
                                        f"({peer_status.num_peers} peers, {getattr(peer_status, 'num_seeds', 0)} seeds, "
                                        f"{peer_status.download_rate} B/s): {state['result'].get('title', '')[:60]}; "
                                        "replacing this slot..."
                                    )
                                    cached_source_failed("no track byte progress")
                                    ensure_yt_fallback_started("Torrent candidate stalled; starting YouTube fallback in parallel...")
                                    return False
                                if age >= 8 and not state["reannounced"]:
                                    h.force_reannounce()
                                    state["reannounced"] = True
                                return None
                            except Exception as exc:
                                phase_status(f"Candidate failed: {exc}; replacing this slot...")
                                cached_source_failed(str(exc))
                                return False

                        def slots():
                            if cached_source_pending:
                                return 1
                            return _torrent_race_slots(manager.config, job.get("prefetch", False))
                        phase_status(f"{phase_label}: testing up to {slots()} torrents in independent parallel slots...")
                        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as registration_executor:
                            race = _rolling_torrent_race(
                                next_candidate, start_candidate, poll_candidate,
                                release_candidate, lambda: job_id in manager._cancel_flags,
                                slots=slots,
                            )
                            try:
                                for winner in race:
                                    m = winner["magnet"]
                                    h = winner["handle"]
                                    save_path = winner["save_path"]
                                    selected_result = winner["result"]
                                    current_magnet = m
                                    _remember_torrent_source(job, m, manager)
                                    phase_status(f"Race winner (real track bytes): {selected_result.get('title', '')[:60]}")
                                    completed = False
                                    try:
                                        completed = stream_to_completion(
                                            h, m, save_path,
                                            is_artist_verified=selected_result.get("_artist_verified", True),
                                        )
                                        if completed:
                                            _keep_torrent_warm(m)
                                            if apply_search_album:
                                                resolved_album_from_search = selected_result.get("_search_album") or target_album
                                            return h
                                        cached_source_failed("track download stalled")
                                        dead_race_keys.add(_torrent_key(m))
                                        ensure_yt_fallback_started("Torrent winner stalled; continuing independent candidates and fallback...")
                                    finally:
                                        cleanup_candidate(m, save_path, delete_files=bool(completed))
                                        current_magnet = None
                            finally:
                                race.close()
                                with manager._lock:
                                    job["race_audio_progress"] = {}

                        if pending_search_futures and time.time() < search_deadline:
                            phase_status(f"{phase_label}: checking late provider results...")
                            collect_search_results(5)
                            continue
                        return None
                finally:
                    if search_executor:
                        search_executor.shutdown(wait=False, cancel_futures=True)

            yt_fallback_thread = None
            yt_fallback_done = threading.Event()
            yt_fallback_produced = False
            yt_fallback_path = None
            yt_fallback_lock = threading.Lock()

            def run_yt_fallback():
                nonlocal yt_fallback_produced, yt_fallback_path
                try:
                    import backend_ytpdl
                    from service_downloader import _find_audio_files
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
                    produced = _find_audio_files(output_dir)
                    if produced:
                        with yt_fallback_lock:
                            yt_fallback_path = max(produced, key=lambda p: p.stat().st_mtime)
                            yt_fallback_produced = True
                except Exception as e:
                    manager._append_cache_event(job, "trying", f"YouTube fallback failed: {e}")
                finally:
                    yt_fallback_done.set()

            def ensure_yt_fallback_started(reason: str) -> None:
                nonlocal yt_fallback_thread
                if yt_fallback_thread or str(job.get("quality") or "").strip().lower() not in {"video", "mp4-video", "music_video"}:
                    return
                manager._append_cache_event(job, "trying", reason)
                yt_fallback_thread = threading.Thread(target=run_yt_fallback, daemon=True, name=f"yt-fallback-{job_id}")
                yt_fallback_thread.start()
                threading.Thread(target=publish_ready_youtube_fallback, daemon=True,
                                 name=f"yt-fallback-publish-{job_id}").start()

            def publish_ready_youtube_fallback() -> None:
                deadline = playback_started_at + _torrent_metadata_timeout_seconds(manager.config)
                while job_id not in manager._cancel_flags:
                    now = time.monotonic()
                    with yt_fallback_lock:
                        fallback_path = yt_fallback_path
                    first_byte = job.get("torrent_first_byte_at")
                    if (fallback_path and fallback_path.is_file() and now >= deadline
                            and (first_byte is None or first_byte > deadline)
                            and not job.get("prefetch")):
                        try:
                            size = fallback_path.stat().st_size
                        except OSError:
                            size = 0
                        if size > 0:
                            with manager._lock:
                                if not job.get("active_audio_is_youtube_fallback"):
                                    job["active_audio_path"] = str(fallback_path)
                                    job["active_audio_size"] = size
                                    job["active_audio_ready_bytes"] = size
                                    job["active_audio_is_youtube_fallback"] = True
                                    job["last_status"] = "Playing YouTube temporarily while FLAC torrent continues"
                            manager._append_cache_event(job, "provider", "Using the completed YouTube copy temporarily; FLAC candidates continue in parallel")
                        return
                    if yt_fallback_done.is_set() and not fallback_path:
                        return
                    time.sleep(0.5)

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
            ensure_yt_fallback_started("Starting YouTube fallback alongside parallel FLAC torrent search...")
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

        # A race winner is downloaded to completion inside stream_to_completion;
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
        _unregister_all_for_job(job_id, delete_files=job_id in manager._cancel_flags)
