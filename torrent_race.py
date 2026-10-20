from __future__ import annotations

import concurrent.futures
import json
import hashlib
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_BAD_MARKERS = {
    "1080p", "2160p", "720p", "bdrip", "bluray", "dvdrip", "h264",
    "h265", "hevc", "movie", "webrip", "x264", "x265", "xvid",
}


def _engine():
    import os
    if os.environ.get("MINDINGUFLAC_ANDROID") == "1":
        from java import jclass  # type: ignore
        return jclass("com.mindinguflac.android.AndroidTorrentEngine")
    from desktop_jlibtorrent import engine_class
    return engine_class()


def _key(magnet: str) -> str:
    try:
        values = parse_qs(urlparse(magnet).query).get("xt") or []
        return next((value.lower() for value in values if value.lower().startswith("urn:btih:")), magnet)
    except Exception:
        return magnet


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
        if len(token) > 1 and token not in {"the", "and", "feat", "with"}
    }


def _coverage(wanted: set[str], actual: set[str]) -> float:
    return len(wanted & actual) / len(wanted) if wanted else 0.0


def _score(
    item: dict, artist: str, title: str, album: str, album_year: str = "",
    quality: str = "LOSSLESS",
) -> float:
    from rapidfuzz import fuzz

    candidate_title = str(item.get("title") or "")
    lowered = candidate_title.casefold()
    if any(marker in lowered for marker in _BAD_MARKERS):
        return -1.0
    category = str(item.get("category") or "").casefold()
    if category and category != "unknown" and not any(word in category for word in ("audio", "music")):
        return -1.0
    actual = _tokens(candidate_title)
    artist_cov = _coverage(_tokens(artist), actual)
    title_cov = _coverage(_tokens(title), actual)
    album_cov = _coverage(_tokens(album), actual)
    if artist_cov < 0.45 or max(title_cov, album_cov) < 0.35:
        return -1.0
    fuzzy = fuzz.token_set_ratio(f"{artist} {album}", candidate_title) / 100.0
    # A year is especially useful for one-word album titles (e.g. "Bad") and
    # is taken from the release metadata, not from a remaster suffix in title.
    year_bonus = 24 if album_year and album_year in actual else 0
    wants_mp3 = str(quality or "LOSSLESS").upper() in {"MP3", "LOSSY"}
    format_bonus = (
        90 if "mp3" in lowered else 0
    ) if wants_mp3 else (
        90 if any(word in lowered for word in ("flac", "lossless", "24bit", "24-bit")) else 0
    )
    seeders = min(80, max(0, int(item.get("seeders") or 0)))
    return (artist_cov * 110) + (title_cov * 80) + (album_cov * 90) + (fuzzy * 50) + year_bonus + format_bonus + seeders


def _album_search_year(job: dict, metadata: dict | None = None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    for value in (
        metadata.get("album_year"), metadata.get("release_year"),
        metadata.get("year"), metadata.get("release_date"), metadata.get("date"),
        job.get("album_year"), job.get("year"),
    ):
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return ""


def _first_pass_queries(job: dict) -> list[str]:
    artist = str(job.get("artist") or "").strip()
    title = str(job.get("title") or "").strip()
    album = str(job.get("album") or "").strip()
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    quality = str(job.get("quality") or "LOSSLESS").upper()
    format_term = "MP3" if quality in {"MP3", "LOSSY"} else "FLAC"
    # Search the useful combinations up front. Every query fans out to every
    # selected tracker, and results are deduplicated/ranked together below.
    # Keep this list bounded so an "all trackers" pass remains practical.
    queries = [
        f"{artist} {album} {title} {format_term}",
        f"{artist} {album} {format_term}",
        f"{artist} {title} {format_term}",
        f"{album} {title} {format_term}",
        f"{artist} {album} {('lossy' if format_term == 'MP3' else 'lossless')}",
    ]
    album_tokens = _tokens(album)
    year = _album_search_year(job, metadata)
    if len(album_tokens) == 1 and year:
        queries.append(f"{artist} {album} {year} {format_term}")
    cleaned = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in cleaned:
            cleaned.append(query)
    return cleaned


def _require_lossless(job: dict) -> bool:
    return str(job.get("quality") or "LOSSLESS").upper() not in {"MP3", "LOSSY"}


def _search(
    query: str,
    service: str,
    metadata: dict,
    artist: str = "",
    title: str = "",
    album: str = "",
) -> list[dict]:
    import torrent_sources

    def torrfetch_search(provider: str) -> list[dict]:
        try:
            import torrfetch
            return torrfetch.search_torrents(query, only=[provider]) or []
        except Exception:
            return []

    category = torrent_sources.torrentdownloads_category_from_metadata(metadata)

    def live_seeded(rows):
        return [row for row in (rows or []) if int(row.get("seeders") or 0) > 0]

    calls = {
        "torlock": lambda: torrent_sources.search_torlock(query, timeout=6),
        "torrentdownloads": lambda: torrent_sources.search_torrentdownloads(query, category, timeout=6),
        "limetorrents": lambda: torrent_sources.search_limetorrents(query, timeout=6),
        "1337x": lambda: torrent_sources.search_1337x(query, timeout=6, artist=artist, album=album),
        "kickass": lambda: torrent_sources.search_kickass(query, timeout=6),
        "solidtorrents": lambda: torrent_sources.search_solid(query, timeout=6),
        "knaben": lambda: torrent_sources.search_knaben(query, timeout=6),
        "apibay": lambda: torrent_sources.search_apibay(query, timeout=6),
        "piratebay": lambda: torrfetch_search("piratebay"),
        "yts": lambda: torrfetch_search("yts"),
    }
    if service != "all" and service in calls:
        try:
            return live_seeded(calls[service]())
        except Exception:
            return []
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(call): provider for provider, call in calls.items()}
        for future in concurrent.futures.as_completed(futures):
            try:
                provider_rows = []
                for row in future.result() or []:
                    if int(row.get("seeders") or 0) <= 0:
                        continue
                    relevance = _score(row, artist, title, album, _album_search_year({}, metadata)) if artist and title else 0
                    if artist and title and relevance < 0:
                        continue
                    candidate = dict(row)
                    candidate["_score"] = relevance
                    provider_rows.append(candidate)
                provider_rows.sort(
                    key=lambda item: (
                        int(item.get("seeders") or 0),
                        int(item.get("seeders") or 0)
                        / max(1, int(item.get("leechers") or item.get("peers") or 0)),
                        int(item.get("seeders") or 0)
                        + int(item.get("leechers") or item.get("peers") or 0),
                        float(item.get("_score") or 0),
                    ),
                    reverse=True,
                )
                results.extend(provider_rows)
            except Exception:
                pass
    return results


def _ordered_candidates(job: dict, manager) -> list[dict]:
    artist = str(job.get("artist") or "")
    title = str(job.get("title") or "")
    album = str(job.get("album") or "")
    service = str(job.get("service") or "all").lower()
    quality_label = "FLAC" if _require_lossless(job) else "MP3"
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    album_year = _album_search_year(job, metadata)
    queries = _first_pass_queries(job)

    if service == "all":
        manager._append_cache_event(
            job, "searching",
            "All Trackers first pass: TorLock, TorrentDownloads, LimeTorrents, The Pirate Bay, "
            "1337x, KickassTorrents, YTS, SolidTorrents, Knaben, and APIBay in parallel",
        )
    else:
        manager._append_cache_event(job, "searching", f"Searching {quality_label} torrent sources")
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(_search, query, service, metadata, artist, title, album) for query in queries]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.extend(future.result() or [])
            except Exception:
                pass

    deduped: dict[str, dict] = {}
    for item in results:
        magnet = str(item.get("magnet") or "")
        if not magnet.startswith("magnet:?"):
            continue
        if int(item.get("seeders") or 0) <= 0:
            continue
        score = _score(item, artist, title, album, album_year, job.get("quality") or "LOSSLESS")
        if score < 0:
            continue
        candidate = dict(item)
        candidate["_score"] = score
        key = _key(magnet)
        previous = deduped.get(key)
        if previous is None:
            deduped[key] = candidate
        else:
            candidate_seeds = int(candidate.get("seeders") or 0)
            previous_seeds = int(previous.get("seeders") or 0)
            candidate_peers = int(candidate.get("leechers") or candidate.get("peers") or 0)
            previous_peers = int(previous.get("leechers") or previous.get("peers") or 0)
            preferred = candidate if score > float(previous.get("_score") or 0) else previous
            preferred = dict(preferred)
            preferred["seeders"] = max(candidate_seeds, previous_seeds)
            preferred["leechers"] = max(candidate_peers, previous_peers)
            deduped[key] = preferred
    ordered = sorted(deduped.values(), key=lambda item: float(item.get("_score") or 0), reverse=True)
    ai_positions: dict[str, int] = {}

    if len(ordered) >= 2:
        try:
            import ai_reranker

            config = getattr(manager, "config", None)
            duck_model, ai_provider, gemini_model = ai_reranker.provider_settings(config)
            packed = [
                {
                    "id": index,
                    "title": item.get("title") or "",
                    "source": item.get("source") or "",
                    "seeders": item.get("seeders") or 0,
                    "score": item.get("_score") or 0,
                    "magnet": item.get("magnet") or "",
                }
                for index, item in enumerate(ordered[:20], start=1)
            ]
            ranked_ids = ai_reranker.rank_candidates(
                {"artist": artist, "title": title, "album": album},
                packed,
                duck_model,
                ai_provider,
                gemini_model,
            )
            rows_by_id = {entry["id"]: entry for entry in packed}
            ai_positions = {
                _key(str(rows_by_id[candidate_id].get("magnet") or "")): index
                for index, candidate_id in enumerate(ranked_ids)
                if candidate_id in rows_by_id
            }
            if ranked_ids:
                manager._append_cache_event(job, "trying", f"AI advisor ranked {('MP3' if str(job.get('quality') or '').upper() == 'MP3' else 'FLAC')} candidates; swarm health controls launch order")
        except Exception as exc:
            manager._append_cache_event(job, "trying", f"Using deterministic torrent ranking ({exc})")
    def swarm_order(item: dict) -> tuple[int, float, int, int, float]:
        try:
            seeds = int(item.get("seeders") or 0)
        except (TypeError, ValueError):
            seeds = 0
        try:
            peers = int(item.get("leechers") or item.get("peers") or 0)
        except (TypeError, ValueError):
            peers = 0
        return (
            seeds,
            seeds / max(peers, 1),
            seeds + peers,
            peers,
            -ai_positions.get(_key(str(item.get("magnet") or "")), 10_000),
            float(item.get("_score") or 0),
        )

    ordered.sort(key=swarm_order, reverse=True)
    if ordered:
        preview = []
        for item in ordered[:10]:
            seeds = int(item.get("seeders") or 0)
            peers = int(item.get("leechers") or item.get("peers") or 0)
            ratio = seeds / max(peers, 1)
            preview.append(
                f"{str(item.get('title') or '')[:58]} ({seeds}s/{peers}p, {ratio:.2f} S/L, "
                f"{item.get('source') or 'unknown'})"
            )
        manager._append_cache_event(
            job, "trying", "Unified top torrent candidates: " + "; ".join(preview)
        )
    return ordered


def run(output_dir: Path, job: dict, manager) -> None:
    # Both platforms use this race and the same jlibtorrent 2 JNI bridge API.
    from backend_torrent import (
        _album_source_keys, _torrent_metadata_timeout_seconds,
        _torrent_race_slots, _remember_torrent_source,
    )

    engine = _engine()
    job_id = str(job["id"])
    run_token = time.monotonic_ns()
    known = ""
    album_key, legacy_album_key = _album_source_keys(
        str(job.get("artist") or ""), str(job.get("album") or ""),
    )
    known_album_source = False
    if getattr(manager, "config", None) is not None:
        import db
        saved = db.get_album_source(album_key) or db.get_album_source(legacy_album_key) or {}
        if saved.get("engine") == "torrent" and str(saved.get("resolved_url") or "").startswith("magnet:"):
            known = str(saved.get("resolved_url") or "")
            known_album_source = bool(known)
    if not known:
        known = str(job.get("resolved_url") or "")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    search = None if known.startswith("magnet:") else executor.submit(_ordered_candidates, job, manager)
    ordered = []
    seen = set()
    if known.startswith("magnet:"):
        ordered.append({
            "magnet": known, "title": job.get("album") or job.get("title"),
            "source": "saved album" if known_album_source else "saved track", "_score": 10000,
        })
        seen.add(_key(known))
        manager._append_cache_event(job, "trying", "Trying the saved album torrent first; other candidates wait until it fails")
    candidate_index = 0
    search_collected = False
    known_pending = known.startswith("magnet:")

    def start_replacement_search():
        nonlocal search
        if search is None:
            manager._append_cache_event(
                job, "trying",
                "Saved album magnet failed for this track; starting replacement search",
            )
            search = executor.submit(_ordered_candidates, job, manager)

    def invalidate_known_album_source(candidate, reason):
        nonlocal known_pending
        if _key(str(candidate.get("magnet") or "")) != _key(known):
            return
        known_pending = False
        if known_album_source:
            try:
                import db
                saved = db.get_album_source(album_key) or db.get_album_source(legacy_album_key) or {}
                if _key(str(saved.get("resolved_url") or "")) == _key(known):
                    db.delete_album_source(str(saved.get("album_key") or album_key))
                    manager._append_cache_event(
                        job, "trying",
                        f"Removed failed saved album torrent ({reason}); searching replacements",
                    )
            except Exception:
                pass
        manager._append_cache_event(job, "trying", f"Saved torrent failed ({reason}); starting replacement search")
        start_replacement_search()

    def next_candidate():
        nonlocal candidate_index, search_collected
        if not search_collected and search is None and not known_pending:
            start_replacement_search()
        if not search_collected and search is not None and search.done():
            search_collected = True
            try:
                results = search.result()
            except Exception as exc:
                manager._append_cache_event(job, "trying", f"Alternative search failed; keeping known album source: {exc}")
                results = []
            for row in results:
                key = _key(str(row.get("magnet") or ""))
                if key not in seen:
                    ordered.append(row)
                    seen.add(key)
        if candidate_index >= len(ordered):
            return None
        candidate_index += 1
        return candidate_index, ordered[candidate_index - 1]
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    track_number = str(metadata.get("track_number") or job.get("track_number") or "")
    quality_label = "FLAC" if _require_lossless(job) else "MP3"
    last_error = f"No usable {quality_label} torrent source"

    def slots():
        if known_pending:
            return 1
        return _torrent_race_slots(manager.config, job.get("prefetch", False))

    metadata_timeout = _torrent_metadata_timeout_seconds(manager.config)

    # Keep YouTube warm alongside current-playback torrent discovery. If the
    # swarm has not delivered its first track byte by the configured deadline,
    # expose the completed YouTube file temporarily while the FLAC race keeps
    # running. Prefetch jobs remain torrent-only to avoid duplicate downloads.
    playback_started = time.monotonic()
    youtube_state = {"path": None, "done": False, "error": ""}
    youtube_done = threading.Event()
    youtube_lock = threading.Lock()
    if str(job.get("quality") or "").strip().lower() in {"video", "mp4-video", "music_video"}:
        def download_youtube_fallback():
            try:
                import backend_ytpdl
                class ShadowManager:
                    _lock = manager._lock
                    _cancel_flags = manager._cancel_flags
                    def __getattr__(self, name): return getattr(manager, name)
                    def _append_cache_event(self, _job, event_type, message):
                        manager._append_cache_event(job, event_type, f"[YouTube fallback] {message}")
                shadow_job = dict(job)
                shadow_job["progress"] = 0
                shadow_job["last_status"] = "YouTube fallback downloading in parallel"
                if job.get("fallback_resolved_url"):
                    shadow_job["resolved_url"] = job["fallback_resolved_url"]
                backend_ytpdl.run(output_dir, shadow_job, ShadowManager())
                from service_downloader import _find_audio_files
                candidates = _find_audio_files(output_dir)
                if candidates:
                    with youtube_lock:
                        youtube_state["path"] = candidates[0]
            except Exception as exc:
                with youtube_lock:
                    youtube_state["error"] = str(exc)
                manager._append_cache_event(job, "trying", f"Parallel YouTube fallback failed: {exc}")
            finally:
                with youtube_lock:
                    youtube_state["done"] = True
                youtube_done.set()

        def publish_youtube_fallback():
            deadline = playback_started + metadata_timeout
            while job_id not in manager._cancel_flags:
                now = time.monotonic()
                with youtube_lock:
                    fallback_path = youtube_state["path"]
                first_byte = job.get("torrent_first_byte_at")
                if (fallback_path and fallback_path.is_file() and now >= deadline
                        and (first_byte is None or first_byte > deadline)
                        and not job.get("prefetch")):
                    try:
                        fallback_size = fallback_path.stat().st_size
                    except OSError:
                        fallback_size = 0
                    if fallback_size > 0:
                        with manager._lock:
                            if not job.get("active_audio_is_youtube_fallback"):
                                job["active_audio_path"] = str(fallback_path)
                                job["active_audio_size"] = fallback_size
                                job["active_audio_ready_bytes"] = fallback_size
                                job["active_audio_is_youtube_fallback"] = True
                                job["last_status"] = "Playing YouTube temporarily while FLAC torrent continues"
                        manager._append_cache_event(job, "provider", "Using the completed YouTube copy temporarily; FLAC candidates continue in parallel")
                    return
                with youtube_lock:
                    finished = youtube_state["done"]
                if finished and fallback_path is None:
                    return
                time.sleep(0.5)

        threading.Thread(target=download_youtube_fallback, daemon=True,
                         name=f"android-yt-fallback-{job_id}").start()
        threading.Thread(target=publish_youtube_fallback, daemon=True,
                         name=f"android-yt-publish-{job_id}").start()
    else:
        youtube_done.set()

    def finish_with_youtube_or_raise(error: str) -> None:
        if not youtube_done.is_set():
            manager._append_cache_event(job, "trying", "Torrent sources exhausted; waiting for the parallel YouTube copy...")
            youtube_done.wait(timeout=300)
        with youtube_lock:
            fallback_path = youtube_state.get("path")
        if fallback_path and fallback_path.is_file():
            size = fallback_path.stat().st_size
            with manager._lock:
                job["active_audio_path"] = str(fallback_path)
                job["active_audio_size"] = size
                job["active_audio_ready_bytes"] = size
                job["active_audio_is_youtube_fallback"] = True
            manager._append_cache_event(job, "provider", "Torrent sources were unavailable; using the completed YouTube copy")
            return
        raise RuntimeError(error)

    if not known.startswith("magnet:"):
        assert search is not None
        ordered.extend(search.result())
        seen.update(_key(str(row.get("magnet") or "")) for row in ordered)
        search_collected = True
        if not ordered:
            executor.shutdown(wait=False)
            finish_with_youtube_or_raise(f"No matching {quality_label} torrent sources were found")
            return

    def start(item):
        index, candidate = item
        native_id = f"{job_id}::torrent::{run_token}::{index}"
        magnet = str(candidate.get("magnet") or "")
        save_path = output_dir / "_race" / hashlib.sha1(_key(magnet).encode()).hexdigest()[:12]
        if magnet == known and job.get("active_audio_path"):
            previous = Path(job["active_audio_path"])
            if previous.is_file():
                saved_root = job.get("torrent_save_path")
                if saved_root:
                    save_path = Path(saved_root)
                elif previous.is_relative_to(output_dir):
                    parts = previous.relative_to(output_dir).parts
                    save_path = output_dir.joinpath(*parts[:2]) if parts[0] == "_race" else output_dir
        manager._append_cache_event(
            job,
            "trying",
            (f"Trying {candidate.get('source')} magnet first (swarm count not refreshed): "
             if str(candidate.get("source") or "").startswith("saved ") else
             f"Parallel {quality_label} candidate {index} ({candidate.get('source') or 'unknown'}, "
             f"{candidate.get('seeders') or 0} seeds/{candidate.get('leechers') or candidate.get('peers') or 0} peers): ") +
            f"{str(candidate.get('title') or '')[:70]}",
        )
        return {
            "native_id": native_id, "candidate": candidate,
            "save_path": save_path,
            "future": executor.submit(
                engine.startDownload, native_id, str(candidate.get("magnet") or ""),
                str(save_path),
                str(job.get("artist") or ""), str(job.get("title") or ""),
                str(job.get("album") or ""), track_number, _require_lossless(job),
                metadata_timeout,
            ),
        }

    def release(state):
        state["future"].cancel()
        if state.get("status", {}).get("finished"):
            engine.release(state["native_id"])
        else:
            engine.cancel(state["native_id"])
        # Also release a result arriving after cancellation. Java tracks pending
        # starts too, so it cannot publish a late orphan handle.
        state["future"].add_done_callback(lambda _future: engine.release(state["native_id"]))
        with manager._lock:
            job.get("race_audio_progress", {}).pop(str(state.get("path", "")), None)

    def read_status(state):
        nonlocal last_error
        if hasattr(engine, "setPrefetch"):
            engine.setPrefetch(state["native_id"], bool(job.get("prefetch")))
        status = json.loads(str(engine.status(state["native_id"])))
        if not status.get("ok"):
            last_error = str(status.get("error") or "jlibtorrent download failed")
            return None
        ready = int(status.get("ready") or 0)
        if ready > 0 and job.get("torrent_first_byte_at") is None:
            with manager._lock:
                job.setdefault("torrent_first_byte_at", time.monotonic())
        if ready > state["ready"]:
            state["ready"] = ready
        state["status"] = status
        return status

    def poll(state):
        nonlocal last_error
        if "path" not in state:
            if not state["future"].done():
                return None
            try:
                started = json.loads(str(state["future"].result()))
            except Exception as exc:
                last_error = str(exc)
                invalidate_known_album_source(state["candidate"], last_error)
                return False
            if not started.get("ok"):
                last_error = str(started.get("error") or last_error)
                message = "Candidate metadata timed out; replacing this slot..." if "metadata timed out" in last_error.lower() else f"Candidate failed ({last_error}); replacing this slot..."
                manager._append_cache_event(job, "trying", message)
                invalidate_known_album_source(state["candidate"], last_error)
                return False
            state["path"] = Path(str(started.get("path") or ""))
            state["save_path"] = Path(started.get("save_path") or state["save_path"])
            state["size"] = int(started.get("size") or 0)
            state["ready"] = 0
            state["last_contiguous"] = 0
            state["last_progress"] = state["probe_started"] = time.monotonic()
        status = read_status(state)
        if status is None:
            invalidate_known_album_source(state["candidate"], last_error)
            return False
        ready = state["ready"]
        with manager._lock:
            job.setdefault("race_audio_progress", {})[str(state["path"])] = {"ready": ready, "total": state["size"]}
        if status.get("finished") and ready >= state["size"] > 0:
            return max(1, ready)
        age = time.monotonic() - state["probe_started"]
        prefix = int(status.get("contiguous", ready))
        # Only progress in the contiguous prefix makes the selected track
        # streamable. Later pieces can keep `ready` increasing while playback
        # remains pinned at the beginning of the file; do not let those pieces
        # keep a dead/slow saved-album source in its exclusive slot forever.
        if prefix > int(state.get("last_contiguous") or 0):
            state["last_contiguous"] = prefix
            state["last_progress"] = time.monotonic()
        stall_limit = 90 if prefix >= 2 * 1024 * 1024 else max(60, metadata_timeout)
        if time.monotonic() - state["last_progress"] >= stall_limit:
            last_error = f"{quality_label} candidate has no track byte progress for {stall_limit} seconds"
            manager._append_cache_event(job, "trying", f"{last_error}; replacing this slot and keeping partial data...")
            invalidate_known_album_source(state["candidate"], last_error)
            return False
        if prefix > 0 and (ready >= 16 * 1024 or (ready > 0 and age >= 4)):
            return min(ready, prefix)
        return None

    # Monitor every slot on every tick, including after selecting a source.
    # A generator suspended at its first winner left the other probes unpolled.
    active = []
    selected = None
    manager._append_cache_event(job, "trying", f"Testing up to {slots()} torrents in independent parallel slots")
    try:
        while True:
            if job_id in manager._cancel_flags:
                raise RuntimeError("Cancelled")
            while len(active) < slots():
                candidate = next_candidate()
                if candidate is None:
                    break
                active.append(start(candidate))
            ready_sources = []
            for state in list(active):
                progress = poll(state)
                if progress is False:
                    active.remove(state)
                    release(state)
                    if selected is state:
                        selected = None
                elif progress is not None and progress > 0:
                    ready_sources.append((progress, state))
            if ready_sources:
                _, best = max(ready_sources, key=lambda item: (bool(item[1]["status"].get("finished")), item[0]))
                # Keep downloading the selected source while alternatives race.
                # Switch only to a completed source or a substantially larger
                # verified prefix, avoiding source churn for tiny differences.
                current_prefix = int((selected or {}).get("status", {}).get("contiguous", (selected or {}).get("ready", 0)))
                best_prefix = int(best["status"].get("contiguous", best["ready"]))
                if selected is None or best is selected or best["status"].get("finished") or best_prefix >= current_prefix + 1024 * 1024:
                    if selected is not best:
                        selected = best
                        _remember_torrent_source(job, best["candidate"]["magnet"], manager)
                        manager._append_cache_event(job, "downloading", f"Parallel source selected: {best['path'].name}; other slots continue testing")
            if selected is not None:
                status = selected["status"]
                ready = selected["ready"]
                total = int(status.get("size") or selected["size"])
                with manager._lock:
                    job["resolved_url"] = selected["candidate"]["magnet"]
                    job["torrent_save_path"] = str(selected["save_path"])
                    if not job.get("active_audio_is_youtube_fallback"):
                        job["active_audio_path"] = str(selected["path"])
                        job["active_audio_ready_bytes"] = int(status.get("contiguous", ready))
                    job["downloaded_bytes"] = ready
                    if not job.get("active_audio_is_youtube_fallback"):
                        job["active_audio_size"] = total
                    job["estimated_total_bytes"] = total
                    job["progress"] = min(99.0, ready / total * 100.0 if total else 0.0)
                    job["last_status"] = f"{quality_label} {job['progress']:.1f}% · {int(status.get('peers') or 0)} peers · {len(active)} parallel candidates"
                if status.get("finished") and total > 0 and ready >= total:
                    if not selected["path"].is_file():
                        raise RuntimeError(f"jlibtorrent finished but the selected {quality_label} file is missing")
                    final_path = output_dir / selected["path"].name
                    if final_path.resolve() != selected["path"].resolve():
                        shutil.copy2(selected["path"], final_path)
                    with manager._lock:
                        job["active_audio_path"] = str(final_path)
                        job["active_audio_size"] = total
                        job["active_audio_ready_bytes"] = total
                        job["active_audio_is_youtube_fallback"] = False
                    return
            if not active and search_collected:
                # next_candidate may have more results after failed slots.
                candidate = next_candidate()
                if candidate is None:
                    finish_with_youtube_or_raise(last_error)
                    return
                active.append(start(candidate))
            time.sleep(0.5)
    finally:
        for state in active:
            release(state)
        executor.shutdown(wait=False, cancel_futures=True)
        with manager._lock:
            job["race_audio_progress"] = {}


def cancel(job_id: str) -> None:
    try:
        _engine().cancelGroup(str(job_id))
    except Exception:
        pass


def runtime_status() -> dict:
    try:
        return json.loads(str(_engine().runtimeStatus()))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
