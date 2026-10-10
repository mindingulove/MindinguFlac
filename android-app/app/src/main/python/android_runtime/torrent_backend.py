from __future__ import annotations

import concurrent.futures
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_BAD_MARKERS = {
    "1080p", "2160p", "720p", "bdrip", "bluray", "dvdrip", "h264",
    "h265", "hevc", "movie", "webrip", "x264", "x265", "xvid",
}


def _engine():
    from java import jclass  # type: ignore

    return jclass("com.mindinguflac.android.AndroidTorrentEngine")


def _key(magnet: str) -> str:
    try:
        values = parse_qs(urlparse(magnet).query).get("xt") or []
        return next((value.lower() for value in values if value.lower().startswith("urn:btih:")), magnet)
    except Exception:
        return magnet


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
        if len(token) > 1 and token not in {"the", "and", "feat", "with", "remastered"}
    }


def _coverage(wanted: set[str], actual: set[str]) -> float:
    return len(wanted & actual) / len(wanted) if wanted else 0.0


def _score(item: dict, artist: str, title: str, album: str) -> float:
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
    lossless = 90 if any(word in lowered for word in ("flac", "lossless", "24bit", "24-bit")) else 0
    seeders = min(80, max(0, int(item.get("seeders") or 0)))
    return (artist_cov * 110) + (title_cov * 80) + (album_cov * 90) + (fuzzy * 50) + lossless + seeders


def _search(query: str, service: str, metadata: dict) -> list[dict]:
    import torrent_sources

    category = torrent_sources.torrentdownloads_category_from_metadata(metadata)
    calls = {
        "torlock": lambda: torrent_sources.search_torlock(query, timeout=6),
        "torrentdownloads": lambda: torrent_sources.search_torrentdownloads(query, category, timeout=6),
        "limetorrents": lambda: torrent_sources.search_limetorrents(query, timeout=6),
        "1337x": lambda: torrent_sources.search_1337x(query, timeout=6),
        "kickass": lambda: torrent_sources.search_kickass(query, timeout=6),
        "extra": lambda: torrent_sources.search_extra(query, timeout=6),
    }
    if service != "all" and service in calls:
        try:
            return calls[service]() or []
        except Exception:
            return []
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls.values()]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.extend(future.result() or [])
            except Exception:
                pass
    return results


def _ordered_candidates(job: dict, manager) -> list[dict]:
    artist = str(job.get("artist") or "")
    title = str(job.get("title") or "")
    album = str(job.get("album") or "")
    service = str(job.get("service") or "all").lower()
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    queries = []
    for query in (
        f"{artist} {album} FLAC",
        f"{artist} {title} FLAC",
        f"{artist} {album} lossless",
    ):
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in queries:
            queries.append(query)

    manager._append_cache_event(job, "searching", "Searching lossless torrent sources")
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(_search, query, service, metadata) for query in queries]
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
        score = _score(item, artist, title, album)
        if score < 0:
            continue
        candidate = dict(item)
        candidate["_score"] = score
        key = _key(magnet)
        previous = deduped.get(key)
        if previous is None or score > float(previous.get("_score") or 0):
            deduped[key] = candidate
    ordered = sorted(
        deduped.values(),
        key=lambda item: (float(item.get("_score") or 0), int(item.get("seeders") or 0)),
        reverse=True,
    )[:20]

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
                for index, item in enumerate(ordered, start=1)
            ]
            ranked_ids = ai_reranker.rank_candidates(
                {"artist": artist, "title": title, "album": album},
                packed,
                duck_model,
                ai_provider,
                gemini_model,
            )
            positions = {value: index for index, value in enumerate(ranked_ids)}
            ordered.sort(
                key=lambda item: positions.get(
                    next((entry["id"] for entry in packed if entry["magnet"] == item.get("magnet")), -1),
                    10_000,
                )
            )
            if ranked_ids:
                manager._append_cache_event(job, "trying", "On-device advisor ranked FLAC candidates")
        except Exception as exc:
            manager._append_cache_event(job, "trying", f"Using deterministic FLAC ranking ({exc})")
    return ordered


def run(output_dir: Path, job: dict, manager) -> None:
    engine = _engine()
    job_id = str(job["id"])
    candidates = _ordered_candidates(job, manager)
    if not candidates:
        raise RuntimeError("No matching FLAC torrent sources were found")

    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    track_number = str(metadata.get("track_number") or job.get("track_number") or "")
    last_error = "No usable FLAC torrent source"

    try:
        for index, candidate in enumerate(candidates[:8], start=1):
            if job_id in manager._cancel_flags:
                raise RuntimeError("Cancelled")
            magnet = str(candidate.get("magnet") or "")
            manager._append_cache_event(
                job,
                "trying",
                f"Checking FLAC source {index}: {str(candidate.get('title') or '')[:70]}",
            )
            started = json.loads(str(engine.startDownload(
                job_id,
                magnet,
                str(output_dir),
                str(job.get("artist") or ""),
                str(job.get("title") or ""),
                str(job.get("album") or ""),
                track_number,
                True,
            )))
            if not started.get("ok"):
                last_error = str(started.get("error") or last_error)
                continue

            selected_path = Path(str(started.get("path") or ""))
            selected_size = int(started.get("size") or 0)
            with manager._lock:
                job["resolved_url"] = magnet
                job["active_audio_path"] = str(selected_path)
                job["active_audio_size"] = selected_size
                job["active_audio_ready_bytes"] = 0
                job["last_status"] = "Downloading selected FLAC with Android libtorrent"
            manager._append_cache_event(job, "downloading", f"Selected {selected_path.name}")

            last_ready = 0
            last_progress_at = time.time()
            while True:
                if job_id in manager._cancel_flags:
                    raise RuntimeError("Cancelled")
                status = json.loads(str(engine.status(job_id)))
                if not status.get("ok"):
                    last_error = str(status.get("error") or "libtorrent download failed")
                    break
                ready = int(status.get("ready") or 0)
                total = int(status.get("size") or selected_size or 0)
                if ready > last_ready:
                    last_ready = ready
                    last_progress_at = time.time()
                with manager._lock:
                    job["active_audio_ready_bytes"] = ready
                    job["active_audio_size"] = total
                    job["downloaded_bytes"] = ready
                    job["estimated_total_bytes"] = total
                    job["progress"] = min(99.0, (ready / total * 100.0) if total else 0.0)
                    job["last_status"] = (
                        f"FLAC {job['progress']:.1f}% · {int(status.get('peers') or 0)} peers"
                    )
                if status.get("finished") and total > 0 and ready >= total:
                    if not selected_path.exists():
                        raise RuntimeError("libtorrent finished but the selected FLAC file is missing")
                    return
                if time.time() - last_progress_at > 180:
                    last_error = "FLAC torrent source stalled for 3 minutes"
                    break
                time.sleep(1)

            engine.release(job_id)
            with manager._lock:
                job["active_audio_path"] = ""
                job["active_audio_ready_bytes"] = 0
                job["active_audio_size"] = 0
        raise RuntimeError(last_error)
    finally:
        try:
            engine.release(job_id)
        except Exception:
            pass


def cancel(job_id: str) -> None:
    try:
        _engine().cancel(str(job_id))
    except Exception:
        pass


def runtime_status() -> dict:
    try:
        return json.loads(str(_engine().runtimeStatus()))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
