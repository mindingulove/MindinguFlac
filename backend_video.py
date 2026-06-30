"""backend_video.py — Music video clip downloader with its own libtorrent session.

Completely separate from backend_torrent.py so music downloads are unaffected.

Strategy (in order):
  1. Torrent clip search (apibay cat 203, knaben video, solid video) — runs in parallel
     with YouTube lookup; whichever wins is used.
  2. YouTube music video fallback if no torrent clip found.

Entry point used by app.py:
  fetch_clip_to_path(identity, output_mp4_path) -> bool
"""
from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── libtorrent (optional) ────────────────────────────────────────────────────

try:
    import libtorrent as _lt
except Exception:
    _lt = None  # type: ignore

_SESSION_LOCK = threading.Lock()
_VIDEO_SESSION = None  # lazy-init so import is free if lt unavailable


def _get_session():
    global _VIDEO_SESSION
    if _lt is None:
        return None
    with _SESSION_LOCK:
        if _VIDEO_SESSION is None:
            s = _lt.session()
            s.apply_settings({
                "active_downloads": 4,
                "active_seeds": 0,
                "active_limit": 4,
                "enable_dht": True,
                "enable_lsd": True,
                "enable_upnp": True,
                "enable_natpmp": True,
                "alert_mask": 0,
            })
            _VIDEO_SESSION = s
        return _VIDEO_SESSION


# ── Constants ────────────────────────────────────────────────────────────────

_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v"})
_CLIP_MAX_BYTES = 700 * 1024 * 1024   # 700 MB — filters out concerts/multi-video dumps at search time
_META_WAIT_S = 30                      # seconds to wait for torrent metadata
_DOWNLOAD_TIMEOUT_S = 150              # 2.5 minutes max per clip download


# ── Torrent clip search ──────────────────────────────────────────────────────

def _parse_bytes(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _looks_like_clip(title: str) -> bool:
    """True when the torrent name looks like a music video clip, not junk/TV/software."""
    import re as _re
    low = (title or "").lower()
    # Hard rejects: concerts, full albums, video formats that signal multi-episode packs
    if any(w in low for w in (
        "concert", "live at", "full album", "discography",
        "dvdrip", "blu-ray", "bluray", "bdrip",
        "season", "episode",
    )):
        return False
    # Audio-only releases (music files, not video clips)
    if _re.search(r"\b(320[\s_]?kbps|flac|mp3|aac|wav|lossless|24[\s-]?bit)\b", low):
        return False
    # Doujinshi / anime CG sets: (同人CG集), (COMIC1☆28), [無修正] etc.
    if _re.search(r"^\(", title or "") and _re.search(r"[　-鿿＀-￯]", title or ""):
        return False
    # Manga/comic digital releases: (Digital), chapter ranges 001-005, volume markers v28
    if _re.search(r"\(Digital\)", title or "", _re.IGNORECASE):
        return False
    if _re.search(r"\b\d{3}-\d{3}\b", title or ""):  # chapter range like 001-005
        return False
    # TV episode pattern: S01E01 / S01E01-E03 etc.
    if _re.search(r"\bS\d{1,3}E\d{1,3}\b", title or "", _re.IGNORECASE):
        return False
    # Software/crack torrents: version numbers + crack indicators
    if _re.search(r"\b(crack(s|ed)?|keygen|serial|portable|repack|nulled|patch)\b", low):
        return False
    if _re.search(r"\bv\d+\.\d+[\.\d]*\b", low) and any(w in low for w in ("fix", "pro", "setup", "installer", "activat")):
        return False
    if _re.search(r"\{[A-Za-z]+\}", title or ""):  # {CracksHash}, {TeamOS} etc.
        return False
    # TV/anime release group prefix: [GroupName] — supports ASCII and non-ASCII group names
    if _re.search(r"^\[.{2,30}\]", title or ""):
        return False
    # Bracketed broadcast network or codec markers
    if _re.search(r"\b(nhkg?|nhk world|tbs|fuji tv|abc tv|nbc|cbs tv|bbc one|bbc two|hevc|x265)\b", low):
        return False
    # Reject titles that are predominantly non-Latin (Chinese, Japanese, Korean, Arabic, etc.)
    # A music video for an English-language track should have mostly ASCII in the title.
    latin_chars = len(_re.findall(r"[A-Za-z0-9\s\-_.,!?'\"()]", title or ""))
    total_chars = max(len((title or "").replace(" ", "")), 1)
    if latin_chars / total_chars < 0.4:
        return False
    return True


def _search_apibay_video(query: str, timeout: int) -> list[dict]:
    """Pirate Bay official API — category 203 (Music Videos), fallback 200 (All Video)."""
    import json
    import urllib.parse
    out: list[dict] = []
    try:
        from torrent_sources import _http, _DEAD_HASH, _magnet
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
                    "size_bytes": _parse_bytes(item.get("size")),
                    "seeders": int(item.get("seeders") or 0),
                    "source": f"apibay:{cat}",
                })
            if out:
                break
    except Exception:
        pass
    return out


def _search_knaben_video(query: str, timeout: int) -> list[dict]:
    """Knaben aggregator — video category."""
    import json
    out: list[dict] = []
    try:
        from torrent_sources import _http, _magnet
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
                "size_bytes": _parse_bytes(item.get("bytes")),
                "seeders": int(item.get("seeders") or 0),
                "source": "knaben_video:" + str(item.get("tracker") or "agg"),
            })
    except Exception:
        pass
    return out


def _search_solid_video(query: str, timeout: int) -> list[dict]:
    """SolidTorrents — Video category (aggregates 1337x, KAT, etc.)."""
    import json
    import urllib.parse
    out: list[dict] = []
    try:
        from torrent_sources import _http
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
                "size_bytes": _parse_bytes(item.get("size")),
                "seeders": int(item.get("seeders") or 0),
                "source": "solid_video",
            })
    except Exception:
        pass
    return out


def _clip_relevance_score(r: dict, artist: str, title: str) -> float:
    """Score 0–1: how well the torrent title matches the artist+track we want.

    Uses rapidfuzz token_set_ratio so word order, punctuation, and extra tokens
    (year, [HQ], 'Official') don't penalise a correct match. Seeder log-bonus
    breaks ties so a 50-seed exact match beats a 2-seed exact match.
    """
    import math as _math
    from rapidfuzz import fuzz as _fuzz
    t = (r.get("title") or "").lower()
    a_low = artist.lower()
    ti_low = title.lower()

    # token_set_ratio: tokenises both strings, takes the set intersection approach.
    # "Michael Jackson Bad Music Video" vs "Bad [HQ] - Michael Jackson - Music Video" → ~100
    artist_score  = _fuzz.token_set_ratio(a_low, t) / 100.0   # 0–1
    title_score   = _fuzz.token_set_ratio(ti_low, t) / 100.0  # 0–1
    combined_score = _fuzz.token_set_ratio(f"{a_low} {ti_low}", t) / 100.0

    # Weighted: track title match matters most, then combined, then artist alone
    fuzzy = title_score * 0.45 + combined_score * 0.35 + artist_score * 0.20

    # Small seeder log-bonus (caps at ~0.15 for very high seed counts)
    seed_bonus = min(0.15, _math.log1p(int(r.get("seeders") or 0)) / 40)

    return min(1.0, fuzzy + seed_bonus)


def search_clip_torrents(artist: str, title: str, timeout: int = 15) -> list[dict]:
    """Search all video sources in parallel; return filtered candidates ranked by relevance."""
    query = f"{artist} {title} music video"
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [
            ex.submit(_search_apibay_video, query, timeout),
            ex.submit(_search_knaben_video, query, timeout),
            ex.submit(_search_solid_video, query, timeout),
        ]
        for fut in as_completed(futures):
            try:
                results += fut.result() or []
            except Exception:
                pass

    try:
        import db as _db
        _adult_terms = _db.get_adult_filter_terms()
    except Exception:
        _adult_terms = set()

    def _passes(r: dict) -> bool:
        t = (r.get("title") or "").lower()
        if not _looks_like_clip(r.get("title") or ""):
            return False
        if _adult_terms and any(term in t for term in _adult_terms):
            return False
        if _CLIP_MAX_BYTES > 0 and _parse_bytes(r.get("size_bytes")) > _CLIP_MAX_BYTES:
            return False
        return True

    filtered = [r for r in results if _passes(r)]
    # Score by relevance first; seeders already factored in via log-bonus
    for r in filtered:
        r["_relevance"] = _clip_relevance_score(r, artist, title)
    filtered.sort(key=lambda r: r["_relevance"], reverse=True)
    return filtered


# ── Torrent clip download ────────────────────────────────────────────────────

def _ffmpeg_exe() -> str:
    """Return path to bundled ffmpeg (via imageio-ffmpeg) or fall back to PATH."""
    try:
        from backend_ytpdl import _ffmpeg_location
        return _ffmpeg_location()
    except Exception:
        pass
    import shutil, os
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return shutil.which(name) or "ffmpeg"


def _ffprobe_exe() -> str:
    """Return path to ffprobe alongside the bundled ffmpeg, or fall back to PATH."""
    import os, shutil
    ffmpeg = _ffmpeg_exe()
    if ffmpeg and ffmpeg != "ffmpeg":
        # imageio-ffmpeg ships ffprobe next to ffmpeg
        probe = str(Path(ffmpeg).with_name("ffprobe" + (".exe" if os.name == "nt" else "")))
        if Path(probe).exists():
            return probe
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    return shutil.which(name) or "ffprobe"


def _video_duration_s(path: Path) -> float:
    """Return video duration in seconds via ffprobe, or 0 on failure."""
    try:
        import subprocess, json as _json
        result = subprocess.run(
            [_ffprobe_exe(), "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return float(_json.loads(result.stdout).get("format", {}).get("duration") or 0)
    except Exception:
        pass
    return 0.0


_WEB_SAFE_AUDIO = frozenset({"aac", "mp3", "opus", "vorbis", "mp4a"})

def _ensure_web_safe_audio(path: Path) -> bool:
    """If the video has AC3/DTS/unsupported audio, re-encode the audio track to AAC in-place.

    Video stream is copied (no quality loss, fast). Returns True when the file is
    ready to play in WKWebView, False if ffmpeg fails and the file should be discarded.
    """
    import subprocess, json as _json
    try:
        r = subprocess.run(
            [_ffprobe_exe(), "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return True  # can't probe — pass through, let player decide
        streams = _json.loads(r.stdout).get("streams", [])
        audio_codecs = [
            (s.get("codec_name") or "").lower()
            for s in streams if s.get("codec_type") == "audio"
        ]
        needs_remux = any(c and c not in _WEB_SAFE_AUDIO for c in audio_codecs)
        if not needs_remux:
            return True
        print(f"[VideoBackend] re-encoding audio {audio_codecs} → AAC for WebKit compatibility")
        tmp = path.with_suffix(".reencode.mp4")
        res = subprocess.run(
            [_ffmpeg_exe(), "-y", "-i", str(path),
             "-c:v", "copy",        # video: no re-encode
             "-c:a", "aac", "-b:a", "192k",  # audio: AC3/DTS → AAC
             "-c:s", "mov_text",    # subtitle passthrough (or drop if unsupported)
             "-map", "0:v:0", "-map", "0:a:0",  # keep first video + first audio track only
             str(tmp)],
            capture_output=True, text=True, timeout=600,
        )
        if res.returncode == 0 and tmp.exists() and tmp.stat().st_size > 65536:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
        print(f"[VideoBackend] audio re-encode failed: {res.stderr[-200:]}")
        return False
    except Exception as exc:
        print(f"[VideoBackend] _ensure_web_safe_audio error: {exc}")
        return True  # don't reject on unexpected errors


def _clip_duration_ok(path: Path, expected_s: float) -> bool:
    """Return False when the downloaded video is absurdly longer than the track.

    Tolerance: allow up to max(3× expected, expected + 600 s, 900 s).
    This lets the Thriller short film (13:43 for a 5:57 track) through,
    but rejects concert recordings and multi-video dumps.
    When expected_s is unknown (0), fall back to a 30-minute hard cap.
    """
    actual = _video_duration_s(path)
    if actual <= 0:
        return True  # can't probe — accept and let playback decide
    # Dynamic ceiling: track length + 50% padding (max +10 min), floor 15 min.
    # Examples: 3-min pop → 15 min cap | 5:57 Thriller → 15 min | 15-min Voodoo Chile → 22.5 min
    if expected_s > 0:
        ceiling = max(expected_s + min(expected_s * 0.5, 600), 900)
    else:
        ceiling = 900  # 15-min default when duration unknown
    ok = actual <= ceiling
    if not ok:
        print(f"[VideoBackend] duration {actual:.0f}s > ceiling {ceiling:.0f}s — rejected")
    return ok


def _download_torrent_clip(magnet: str, output_path: Path, expected_s: float = 0, timeout: int = _DOWNLOAD_TIMEOUT_S) -> bool:
    """Download the largest video file from `magnet` into `output_path`.

    Uses the module-local libtorrent session — never touches backend_torrent's session.
    Returns True on success.
    """
    ses = _get_session()
    if ses is None:
        return False

    save_dir = output_path.parent / f".vtmp_{output_path.stem}"
    save_dir.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        params = {
            "save_path": str(save_dir),
            "storage_mode": _lt.storage_mode_t(2),
        }
        handle = _lt.add_magnet_uri(ses, magnet, params)

        # Wait for torrent metadata
        deadline = time.monotonic() + _META_WAIT_S
        while not handle.has_metadata():
            if time.monotonic() > deadline:
                return False
            time.sleep(1)

        ti = handle.get_torrent_info()
        files = ti.files()

        # Pick the largest video file in the torrent
        best_idx, best_size = -1, 0
        for i in range(ti.num_files()):
            ext = Path(files.file_path(i)).suffix.lower()
            sz = files.file_size(i)
            if ext in _VIDEO_EXTS and sz > best_size:
                best_idx, best_size = i, sz

        if best_idx == -1:
            return False  # no video file

        # Pre-download size guard: reject files that are clearly too large.
        # A music video at 480p averages ~1 MB/min. Cap at 2 GB (still generous
        # for a 13-minute extended MV like Thriller).
        if best_size > _CLIP_MAX_BYTES:
            print(f"[VideoBackend] torrent file too large ({best_size // 1024**2} MB), skipping")
            return False

        # Disable every file except the chosen one
        priorities = [0] * ti.num_files()
        priorities[best_idx] = 7
        handle.prioritize_files(priorities)

        # Wait for download to complete
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            fp = handle.file_progress()
            if fp and len(fp) > best_idx:
                if files.file_size(best_idx) > 0 and fp[best_idx] >= files.file_size(best_idx):
                    break
            st = handle.status()
            if st.state in (_lt.torrent_status.seeding, _lt.torrent_status.finished):
                break
            time.sleep(2)
        else:
            return False

        src = save_dir / files.file_path(best_idx)
        if not src.exists() or src.stat().st_size < 65536:
            return False

        if not _clip_duration_ok(src, expected_s):
            return False
        if not _ensure_web_safe_audio(src):
            return False

        tmp = output_path.with_suffix(".vtmp" + output_path.suffix)
        shutil.copy2(src, tmp)
        tmp.replace(output_path)
        return True

    except Exception as exc:
        print(f"[VideoBackend] torrent download failed: {exc}")
        return False
    finally:
        try:
            if handle is not None and handle.is_valid():
                ses.remove_torrent(handle)
        except Exception:
            pass
        try:
            shutil.rmtree(save_dir, ignore_errors=True)
        except Exception:
            pass


# ── YouTube fallback download ────────────────────────────────────────────────

def _download_youtube_clip(url: str, start_offset: int, output_path: Path) -> bool:
    """Download a YouTube music video at 480p H.264/AAC into output_path."""
    try:
        import yt_dlp
        from backend_ytpdl import _ffmpeg_location
    except Exception:
        return False

    tmp = output_path.with_suffix(".ytmp.mp4")
    tmp.unlink(missing_ok=True)
    opts: dict = {
        "format": (
            "bestvideo[vcodec^=avc][height<=480]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc][height<=480]+bestaudio/"
            "bestvideo[vcodec^=avc]+bestaudio[ext=m4a]/"
            "bestvideo[vcodec^=avc]+bestaudio/"
            "bestvideo[height<=480]+bestaudio[ext=m4a]/"
            "bestvideo[height<=480]+bestaudio/"
            "bestvideo+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[height<=480]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(tmp),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "http_chunk_size": 10 * 1024 * 1024,
    }
    if start_offset > 0:
        from yt_dlp.utils import download_range_func
        opts["download_ranges"] = download_range_func(None, [(start_offset, None)])
        opts["force_keyframes_at_cuts"] = True
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg

    for browser in ("safari", "chrome", "firefox", None):
        try:
            attempt = dict(opts)
            if browser:
                attempt["cookiesfrombrowser"] = (browser,)
            tmp.unlink(missing_ok=True)
            with yt_dlp.YoutubeDL(attempt) as ydl:
                ydl.download([url])
            if tmp.exists() and tmp.stat().st_size > 65536:
                tmp.replace(output_path)
                return True
        except Exception:
            tmp.unlink(missing_ok=True)
    return False


# ── Main entry point ─────────────────────────────────────────────────────────

def fetch_clip_to_path(identity: dict, output_path: Path, log_cb=None) -> bool:
    """Find and download the best music video clip for `identity` into `output_path`.

    Races torrent search against YouTube lookup; whichever produces a valid file wins.
    YouTube is the fallback if torrents come up empty.
    Returns True when a file is written to output_path, False otherwise.

    log_cb(msg): optional callable for live-cache log output; defaults to print.
    """
    _log = log_cb if callable(log_cb) else print

    artist = str(identity.get("artist") or "").strip()
    title = str(identity.get("title") or "").strip()
    if not artist or not title:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    expected_s = float(identity.get("duration_s") or 0)
    if not expected_s:
        try:
            expected_s = float(identity.get("duration_ms") or 0) / 1000
        except Exception:
            expected_s = 0.0

    # --- Phase 1: race torrent search vs YouTube lookup -------------------
    torrent_candidates: list[dict] = []
    youtube_result: dict = {}
    youtube_start_offset: int = 0

    _log(f"Searching video clip for: {artist} – {title}")

    def _do_torrent_search():
        nonlocal torrent_candidates
        try:
            torrent_candidates = search_clip_torrents(artist, title, timeout=15)
        except Exception:
            torrent_candidates = []

    def _do_youtube_lookup():
        nonlocal youtube_result, youtube_start_offset
        try:
            from app import _lookup_youtube_video
            res = _lookup_youtube_video(identity)
            if res.get("found") and res.get("webpage_url"):
                youtube_result = res
                youtube_start_offset = int(res.get("video_start_offset") or 0)
        except Exception:
            pass

    import threading as _threading

    track_key = str(identity.get("track_key") or "").strip()

    # --- Phase 0: try DB-persisted source from a previous successful fetch ---
    if track_key:
        try:
            import db as _db
            saved = _db.get_video_source(track_key)
            if saved:
                video_bl = _db.get_video_blacklist()
                if saved.get("magnet") and saved["magnet"] not in video_bl:
                    _log(f"Video: reusing saved torrent — {saved.get('torrent_title', '')[:60]}")
                    if _download_torrent_clip(saved["magnet"], output_path, expected_s=expected_s):
                        _log(f"Video: clip from saved torrent → {output_path.name}")
                        return True
                    _db.add_video_blacklist(saved["magnet"], reason="stalled or no peers on reuse")
                if saved.get("youtube_url") and saved["youtube_url"] not in video_bl:
                    _log(f"Video: reusing saved YouTube URL — {saved['youtube_url'][:80]}")
                    if _download_youtube_clip(saved["youtube_url"], 0, output_path):
                        if _clip_duration_ok(output_path, expected_s):
                            _log(f"Video: clip from saved YouTube → {output_path.name}")
                            return True
                        output_path.unlink(missing_ok=True)
                    _db.add_video_blacklist(saved["youtube_url"], reason="failed on reuse")
        except Exception:
            pass

    # --- Phase 1: race torrent search vs YouTube lookup ---
    with ThreadPoolExecutor(max_workers=2) as ex:
        ft = ex.submit(_do_torrent_search)
        fy = ex.submit(_do_youtube_lookup)
        ft.result()
        fy.result()

    # Filter any DB-blacklisted magnets from candidates
    try:
        import db as _db
        _vbl = _db.get_video_blacklist()
        torrent_candidates = [c for c in torrent_candidates if c.get("magnet") not in _vbl]
    except Exception:
        _vbl = set()

    if torrent_candidates:
        _log(f"Video: {len(torrent_candidates)} torrent clip(s) found, trying best matches...")
    else:
        _log("Video: no torrent clips found, trying YouTube...")

    # --- Phase 1b: AI advisor in parallel (reorders candidates while first download starts) ---
    ai_ranked_ids: list[int] = []
    ai_done = _threading.Event()

    def _run_ai_advisor():
        try:
            import ai_reranker, config as _cfg
            ai_provider = getattr(_cfg, "ai_provider", "duckai")
            if not ai_reranker.is_enabled(ai_provider):
                return
            ai_candidates = [
                {"id": i, "title": r.get("title", ""), "seeders": r.get("seeders", 0),
                 "magnet": r.get("magnet", ""), "score": int(r.get("_relevance", 0) * 100)}
                for i, r in enumerate(torrent_candidates[:10])
            ]
            duck_model = getattr(_cfg, "duck_model", "1")
            gemini_model = getattr(_cfg, "gemini_model", "gemini-1.5-flash")
            ranked = ai_reranker.rank_candidates(
                {"artist": artist, "title": title},
                ai_candidates, duck_model, ai_provider, gemini_model,
                video_clip_mode=True,
            )
            if isinstance(ranked, list) and ranked:
                ai_ranked_ids[:] = ranked
        except Exception:
            pass
        finally:
            ai_done.set()

    if torrent_candidates:
        _threading.Thread(target=_run_ai_advisor, daemon=True, name="ai-video-rerank").start()
        _log("Video: AI advisor running in parallel...")
        ai_done.wait(timeout=6.0)
        if ai_ranked_ids:
            id_map = {i: r for i, r in enumerate(torrent_candidates[:10])}
            ai_ordered = [id_map[i] for i in ai_ranked_ids if i in id_map]
            remaining = [r for i, r in id_map.items() if i not in set(ai_ranked_ids)]
            torrent_candidates = ai_ordered + remaining + torrent_candidates[10:]
            _log(f"Video: AI advisor reordered top {len(ai_ranked_ids)} candidates")
        else:
            _log("Video: AI advisor timed out, using local ranking")

    # --- Phase 2: try torrent first (up to 10 ranked candidates), then YouTube ---
    _MIN_RELEVANCE = 0.15
    # If we already have a YouTube result and the top candidates all have 0 seeders,
    # skip torrents — they'll stall for 30s each and YouTube is already waiting.
    top = [c for c in torrent_candidates[:10] if c.get("_relevance", 0) >= _MIN_RELEVANCE]
    if youtube_result and top and all(int(c.get("seeders") or 0) == 0 for c in top[:3]):
        _log("Video: all top torrent candidates have 0 seeders — skipping to YouTube fallback")
        torrent_candidates = []

    for candidate in torrent_candidates[:10]:
        magnet = candidate.get("magnet") or ""
        if not magnet:
            continue
        rel = candidate.get("_relevance", 0)
        if rel < _MIN_RELEVANCE:
            _log(f"Video: skipping low-relevance ({rel:.2f}) — {candidate.get('title', '')[:50]}")
            continue
        _log(f"Video: trying torrent clip (relevance={rel:.2f}) — {candidate.get('title', '')[:60]} "
             f"({candidate.get('seeders', 0)} seeds)")
        if _download_torrent_clip(magnet, output_path, expected_s=expected_s):
            _log(f"Video: clip saved from torrent → {output_path.name}")
            if track_key:
                try:
                    _db.save_video_source(track_key, magnet=magnet,
                                          torrent_title=candidate.get("title", ""))
                except Exception:
                    pass
            return True
        # Don't blacklist stalled magnets — seeder shortage is temporary

    if youtube_result:
        url = youtube_result["webpage_url"]
        _log(f"Video: downloading YouTube clip — {url[:80]}")
        if _download_youtube_clip(url, youtube_start_offset, output_path):
            if _clip_duration_ok(output_path, expected_s):
                _log(f"Video: clip saved from YouTube → {output_path.name}")
                if track_key:
                    try:
                        _db.save_video_source(track_key, youtube_url=url)
                    except Exception:
                        pass
                return True
            output_path.unlink(missing_ok=True)
            _log("Video: YouTube clip rejected (duration out of range)")
            try:
                _db.add_video_blacklist(url, reason="duration out of range")
            except Exception:
                pass

    _log("Video: no clip found")
    return False
