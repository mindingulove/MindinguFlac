from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import threading
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _ffmpeg_location() -> str:
    """Return a path yt-dlp can use to find ffmpeg.

    yt-dlp's postprocessors (FFmpegMetadata, FFmpegExtractAudio) require an
    ffmpeg binary. Rather than expecting the user to install one, ship it via
    the ``imageio-ffmpeg`` pip package, which bundles a static ffmpeg binary
    per platform. Fall back to a frozen-bundle binary (``sys._MEIPASS``) or a
    PATH ffmpeg if the package is unavailable."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), name)
        if os.path.exists(bundled):
            return bundled
    return shutil.which(name) or shutil.which("ffmpeg") or ""


def _get_yt_dlp():
    import importlib

    try:
        return importlib.import_module("yt_dlp")
    except ModuleNotFoundError as exc:
        raise RuntimeError("yt-dlp is not installed in this environment") from exc


def _quality_mode(quality: str) -> str:
    value = str(quality or "").strip().lower()
    if value in {"mp3", "m4a"}:
        return value
    return "best"


def _quality_to_codec(quality: str) -> str:
    mode = _quality_mode(quality)
    if mode == "mp3":
        return "mp3"
    if mode == "m4a":
        return "m4a"
    return ""


def _format_selector(quality: str) -> str:
    mode = _quality_mode(quality)
    if mode == "m4a":
        return "bestaudio[ext=m4a][has_drm!=true]/bestaudio[acodec^=mp4a][has_drm!=true]/bestaudio[has_drm!=true]/best[has_drm!=true]"
    if mode == "mp3":
        return "bestaudio[has_drm!=true]/best[has_drm!=true]"
    return "bestaudio[has_drm!=true]/best[has_drm!=true]"


def _is_youtube_url(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        host = (urlparse(value).netloc or "").lower()
    except Exception:
        return False
    return "youtube.com" in host or "youtu.be" in host or "music.youtube.com" in host


def _safe_outtmpl(output_dir: Path) -> str:
    return str(output_dir / "%(title).200B - %(uploader).100B.%(ext)s")


def _job_metadata(job: dict) -> dict:
    track = job.get("track") if isinstance(job.get("track"), dict) else {}
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    return {**metadata, **track}


def _parse_duration_seconds(value: object) -> int:
    if value in ("", None):
        return 0
    if isinstance(value, (int, float)):
        number = int(value)
        return number // 1000 if number > 10000 else number
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        number = int(text)
        return number // 1000 if number > 10000 else number
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _expected_track(job: dict) -> dict:
    merged = _job_metadata(job)
    return {
        "artist": str(merged.get("artist") or job.get("artist") or "").strip(),
        "title": str(merged.get("title") or merged.get("name") or job.get("title") or "").strip(),
        "album": str(merged.get("album") or job.get("album") or "").strip(),
        "duration": (
            _parse_duration_seconds(merged.get("duration_ms"))
            or _parse_duration_seconds(merged.get("length"))
            or _parse_duration_seconds(merged.get("duration"))
        ),
    }


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove text in parentheses or brackets like (Remastered 2010) or [Official Video]
    text = re.sub(r"\s*[\(\[].*?[\)\]]", "", text)
    # Strip common suffixes that follow a dash or space
    text = re.sub(
        r"\s*[-–]\s*(remaster|remastered|single|ep|deluxe|expanded|anniversary|edition|version|mono|stereo|re-?master).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _extract_catalog_ids(value: object) -> set[str]:
    text = str(value or "").casefold()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    ids: set[str] = set()
    # Keep this intentionally conservative. These catalogue numbers are strong
    # classical identifiers; looser forms like "op. 3" are too common for
    # YouTube matching and can make pop searches less strict.
    for prefix, number in re.findall(r"\b(rv|bwv|hwv|kv|k)\s*\.?\s*(\d{1,5}[a-z]?)\b", text, flags=re.IGNORECASE):
        ids.add(f"{prefix.casefold()}{number.casefold()}")
    for number in re.findall(r"\bhob\s*\.?\s*(?:[ivxlcdm]+:)?\s*(\d{1,4}[a-z]?)\b", text, flags=re.IGNORECASE):
        ids.add(f"hob{number.casefold()}")
    return ids


def _classical_search_terms(title: str) -> str:
    catalog_ids = _extract_catalog_ids(title)
    if not catalog_ids:
        return ""
    tokens = _tokens(title)
    ignored = {
        "vivaldi", "bach", "handel", "haendel", "mozart", "haydn",
        "beethoven", "schubert", "chopin", "liszt", "verdi", "puccini",
        "concerto", "symphony", "sonata", "opera", "aria", "major", "minor",
        "op", "no", "nr", "act", "scene", "i", "ii", "iii", "iv", "v",
        "vi", "vii", "viii", "ix", "x",
    }
    catalog_tokens = set()
    for catalog_id in catalog_ids:
        match = re.match(r"([a-z]+)(\d.*)", catalog_id)
        if match:
            catalog_tokens.update(match.groups())
    distinctive = [
        token for token in tokens
        if token not in ignored and token not in catalog_tokens and len(token) > 1
    ]
    return " ".join([*sorted(catalog_tokens), *distinctive[:6]]).strip()


_CLASSICAL_GENRE_TERMS = {
    "classical",
    "baroque",
    "opera",
    "oratorio",
    "chamber music",
    "concerto",
    "symphony",
}


def _metadata_values_for_keys(data: dict, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = data.get(key)
        if isinstance(raw, str):
            values.extend(part.strip() for part in re.split(r"[,/;|]", raw) if part.strip())
        elif isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, str):
                    values.extend(part.strip() for part in re.split(r"[,/;|]", item) if part.strip())
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("genre") or item.get("title")
                    if name:
                        values.append(str(name).strip())
    return [value for value in values if value]


def _ytpdl_search_profile(job: dict) -> str:
    merged = _job_metadata(job)
    genre_values = _metadata_values_for_keys(
        merged,
        ("genre", "genres", "primary_genre", "secondary_genres", "style", "styles"),
    )
    genre_text = _norm_text(" ".join(genre_values))
    if any(term in genre_text for term in _CLASSICAL_GENRE_TERMS):
        return "classical"
    return "default"


def _classical_youtube_search_query(job: dict, clean: bool = False) -> str:
    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = _clean_text(wanted["title"]) if clean else wanted["title"]
    terms = _classical_search_terms(title)
    if not terms:
        return ""
    parts = [artist, terms] if artist else [terms]
    if not clean and wanted["album"]:
        album_terms = _classical_search_terms(wanted["album"])
        if album_terms:
            parts.append(album_terms)
    return "ytsearch15:" + " ".join(part for part in parts if part)


def _youtube_search_query(job: dict, clean: bool = False) -> str:
    if _ytpdl_search_profile(job) == "classical":
        query = _classical_youtube_search_query(job, clean=clean)
        if query:
            return query

    wanted = _expected_track(job)
    artist = wanted["artist"]
    title = wanted["title"]
    album = wanted["album"]
    
    if clean:
        title = _clean_text(title)
        album = "" # Don't include album in clean search
    
    if artist and title:
        query_parts = [artist, title]
        if not clean and album and album.lower() not in {"unknown album", "unknown"}:
            query_parts.append(album)
        query_parts.extend(["official", "audio"])
        return "ytsearch15:" + " ".join(query_parts)
    return ""


def _resolved_youtube_url(job: dict) -> str:
    merged = _job_metadata(job)

    direct = (
        job.get("resolved_url")
        or merged.get("youtube_url")
        or merged.get("youtube")
        or merged.get("external_url")
        or ""
    )
    if _is_youtube_url(direct):
        return direct

    # Fall back to any direct YouTube-ish URL present in metadata.
    for value in (merged.get("url"), merged.get("source_url")):
        if _is_youtube_url(value):
            return value

    return _youtube_search_query(job)


def _current_track_youtube_url(job: dict) -> str:
    """Return an explicit YouTube URL already attached to the selected track.

    This is different from _resolved_youtube_url(): it never falls back to a
    search query. The AI race should see this user/current-track URL as the
    first candidate when present, but search still supplies alternatives.
    """
    merged = _job_metadata(job)
    for key in ("youtube_url", "youtube", "url", "source_url", "external_url"):
        value = merged.get(key)
        if _is_youtube_url(value):
            return str(value)
    return ""


def _prepend_current_youtube_candidate(
    candidates: list[tuple[str, dict]],
    job: dict,
) -> list[tuple[str, dict]]:
    current_url = _current_track_youtube_url(job)
    if not current_url:
        return candidates
    if any(url == current_url for url, _details in candidates):
        return candidates
    wanted = _expected_track(job)
    details = {
        "title": f"{wanted.get('artist', '')} - {wanted.get('title', '')}".strip(" -"),
        "uploader": "Current track YouTube link",
        "duration": wanted.get("duration") or 0,
        "score": 100,
        "url": current_url,
        "source": "current_youtube_link",
    }
    return [(current_url, details), *candidates]


def _norm_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_BAD_MATCH_TERMS = {
    "background music",
    "compilation",
    "cover",
    "full album",
    "gaming",
    "karaoke",
    "mix",
    "no copyright",
    "playlist",
    "royalty free",
    "sound effect",
    "sound effects",
    "sound fx",
    "tribute",
    "drm",
    "instrumental",
    "protected",
    "tutorial",
    "reaction",
    "remix",
    "sped up",
    "slowed",
    "nightcore",
    "loop",
    "1 hour",
    "10 hours",
    "archive",
    "extended",
}


def _tokens(value: str) -> list[str]:
    ignored = {"a", "an", "and", "feat", "ft", "official", "audio", "video", "lyrics", "the"}
    return [token for token in _norm_text(value).split() if token and token not in ignored]


def _token_coverage(needles: list[str], haystack: str) -> int:
    if not needles:
        return 0
    hay_tokens = set(_tokens(haystack))
    if not hay_tokens:
        return 0
    matched = sum(1 for token in needles if token in hay_tokens)
    return int((matched / len(needles)) * 100)


def _classical_match_adjustment(wanted: dict, raw_title: str, raw_uploader: str) -> tuple[int, dict]:
    wanted_text = f"{wanted.get('artist', '')} {wanted.get('title', '')} {wanted.get('album', '')}"
    candidate_text = f"{raw_title} {raw_uploader}"
    wanted_catalog = _extract_catalog_ids(wanted_text)
    if not wanted_catalog:
        return 0, {}
    candidate_catalog = _extract_catalog_ids(candidate_text)
    if not candidate_catalog:
        return 0, {"classical_catalog": "missing"}
    if wanted_catalog.isdisjoint(candidate_catalog):
        return -90, {"classical_catalog": "mismatch"}

    wanted_terms = _classical_search_terms(str(wanted.get("title") or ""))
    candidate_norm = _norm_text(candidate_text)
    wanted_tokens = [
        token for token in _tokens(wanted_terms)
        if not token.isdigit() and not re.fullmatch(r"[a-z]{1,4}", token)
    ]
    term_coverage = _token_coverage(wanted_tokens, candidate_norm)
    if term_coverage < 60:
        return -45, {"classical_catalog": "matched", "classical_term_coverage": term_coverage}
    return 28, {"classical_catalog": "matched", "classical_term_coverage": term_coverage}


def _candidate_url(entry: dict) -> str:
    return str(entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or "")

def _candidate_has_drm(entry: dict) -> bool:
    drm_fields = (
        entry.get("has_drm"),
        entry.get("is_drm"),
        entry.get("drm"),
        entry.get("drm_family"),
        entry.get("license_url"),
    )
    if any(value not in ("", None, False) for value in drm_fields):
        return True

    return False


def _candidate_requires_auth(entry: dict) -> bool:
    """Return True if the candidate likely requires age verification or
    authentication (e.g. age-restricted or premium-only content)."""
    if int(entry.get("age_limit") or 0) > 0:
        return True
    # 'needs_auth' usually means age verification or sign-in required.
    # 'premium_only' means YouTube Premium required.
    if entry.get("availability") in ("needs_auth", "premium_only"):
        return True
    return False

    formats = entry.get("formats")
    if not isinstance(formats, list) or not formats:
        return False
    playable = 0
    drm = 0
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        if fmt.get("has_drm") is True or fmt.get("drm_family") or fmt.get("license_url"):
            drm += 1
        else:
            playable += 1
    return drm > 0 and playable == 0


def _source_score(wanted_artist: str, uploader: str, candidate_title: str) -> int:
    from rapidfuzz import fuzz

    artist_tokens = _tokens(wanted_artist)
    uploader_norm = _norm_text(uploader)
    title_norm = _norm_text(candidate_title)
    if not artist_tokens:
        return 0

    # Official releases are frequently hosted on label/aggregator channels whose
    # name does not contain the artist (so uploader_coverage is 0). Treat the
    # title itself as a trust signal when it is clearly an official release that
    # names the artist, e.g. "CeCe Peniston - Finally (Official Music Video)".
    title_artist_coverage = _token_coverage(artist_tokens, title_norm)
    official_release = "official" in title_norm and any(
        marker in title_norm for marker in (" video", " audio")
    )
    official_titled_by_artist = official_release and title_artist_coverage >= 70

    uploader_coverage = _token_coverage(artist_tokens, uploader_norm)
    source = max(
        uploader_coverage,
        fuzz.token_set_ratio(_norm_text(wanted_artist), uploader_norm),
    )
    if uploader_coverage == 0:
        # Stay skeptical of unrelated channels, but don't reject an official
        # video just because the label channel name omits the artist.
        source = max(source, 70) if official_titled_by_artist else min(source, 30)

    if uploader_coverage == 100:
        source = max(source, 95)
    if uploader_norm.endswith(" topic") and uploader_coverage >= 80:
        source = 100
    if "vevo" in uploader_norm and uploader_coverage >= 70:
        source = 100
    if "official" in uploader_norm and uploader_coverage >= 70:
        source = max(source, 95)
    if "official" in title_norm and uploader_coverage >= 70:
        source = max(source, 90)
    return int(min(100, source))


def _score_youtube_candidate(entry: dict, job: dict) -> tuple[int, dict]:
    from rapidfuzz import fuzz

    wanted = _expected_track(job)
    wanted_artist = _norm_text(wanted["artist"])
    wanted_title = _norm_text(wanted["title"])
    wanted_full = _norm_text(f"{wanted['artist']} {wanted['title']}")
    raw_title = str(entry.get("title") or "")
    raw_uploader = str(entry.get("uploader") or entry.get("channel") or entry.get("creator") or "")
    candidate_title = _norm_text(raw_title)
    uploader = _norm_text(raw_uploader)
    combined = _norm_text(f"{candidate_title} {uploader}")

    if not wanted_artist or not wanted_title or not candidate_title:
        return 0, {"reason": "missing title metadata"}
    if _candidate_has_drm(entry) or _candidate_requires_auth(entry):
        reason = "drm" if _candidate_has_drm(entry) else "auth_required"
        return -999, {
            "title": raw_title,
            "uploader": raw_uploader,
            "url": _candidate_url(entry),
            "title_score": 0,
            "artist_score": 0,
            "source_score": 0,
            "title_coverage": 0,
            "artist_coverage": 0,
            "duration_score": 0,
            "score": -999,
            "drm": reason == "drm",
            "auth": reason == "auth_required",
        }

    wanted_title_tokens = _tokens(wanted_title)
    wanted_artist_tokens = _tokens(wanted_artist)
    title_coverage = _token_coverage(wanted_title_tokens, candidate_title)
    artist_coverage = _token_coverage(wanted_artist_tokens, combined)
    source_score = _source_score(wanted_artist, uploader, candidate_title)

    title_score = max(
        fuzz.WRatio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_title, candidate_title),
        fuzz.token_set_ratio(wanted_full, candidate_title),
    )
    
    # Use token_set_ratio for artist to handle variations like "Artist - Topic" or "ArtistVEVO"
    artist_score = max(artist_coverage, fuzz.token_set_ratio(wanted_artist, combined))

    expected_duration = int(wanted.get("duration") or 0)
    candidate_duration = _parse_duration_seconds(entry.get("duration"))
    duration_score = 50
    duration_penalty = 0
    if expected_duration and candidate_duration:
        diff = abs(expected_duration - candidate_duration)
        if diff <= 5:
            duration_score = 100
        elif diff <= 15:
            duration_score = 80
        elif diff <= 30:
            duration_score = 45
        else:
            duration_score = 0
            duration_penalty = min(80, diff)

    penalty = 0
    candidate_text = f" {combined} "
    requested_tokens = f" {wanted_title} "
    for term in _BAD_MATCH_TERMS:
        if f" {term} " in candidate_text and f" {term} " not in requested_tokens:
            penalty += 35
    if "archive" in uploader and "official" not in candidate_text:
        penalty += 45

    if title_coverage < 70:
        penalty += 35
    if artist_coverage < 70:
        penalty += 40
    if source_score < 45 and any(term in candidate_text for term in (" background music ", " compilation ", " gaming ", " sound fx ")):
        penalty += 60

    classical_adjustment = 0
    classical_details = {}
    if _ytpdl_search_profile(job) == "classical":
        classical_adjustment, classical_details = _classical_match_adjustment(wanted, raw_title, raw_uploader)

    score = int(
        (title_score * 0.42)
        + (artist_score * 0.18)
        + (source_score * 0.22)
        + (duration_score * 0.12)
        + (title_coverage * 0.06)
        + classical_adjustment
        - penalty
        - duration_penalty
    )
    details = {
        "title": raw_title,
        "uploader": raw_uploader,
        "url": _candidate_url(entry),
        "title_score": int(title_score),
        "artist_score": int(artist_score),
        "source_score": int(source_score),
        "title_coverage": int(title_coverage),
        "artist_coverage": int(artist_coverage),
        "duration_score": int(duration_score),
        "score": score,
        "drm": False,
        **classical_details,
    }
    return score, details


def _scored_youtube_candidates(search_info: dict, job: dict) -> list[tuple[int, dict, str]]:
    entries = [entry for entry in (search_info.get("entries") or []) if isinstance(entry, dict)]
    scored = []
    for entry in entries:
        url = _candidate_url(entry)
        if not url:
            continue
        score, details = _score_youtube_candidate(entry, job)
        scored.append((score, details, url))

    if not scored:
        raise RuntimeError("ytp-dl search returned no downloadable YouTube candidates")

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _candidate_is_confident(score: int, details: dict) -> bool:
    return not (
        score < 55
        or details.get("title_score", 0) < 55
        or details.get("artist_score", 0) < 50
        or (details.get("source_score", 0) < 25 and score < 70)
    )


def _best_youtube_search_match(search_info: dict, job: dict) -> tuple[str, dict]:
    scored = _scored_youtube_candidates(search_info, job)
    best_score, best_details, best_url = scored[0]
    if not _candidate_is_confident(best_score, best_details):
        title = best_details.get("title") or "unknown result"
        raise RuntimeError(f"ytp-dl could not find a confident YouTube match; best was {best_score}%: {title}")
    return best_url, best_details


def _ranked_youtube_matches(search_info: dict, job: dict) -> list[tuple[str, dict]]:
    """Return candidates sorted by score so the caller can fall back to the
    next match if a chosen video turns out to be unavailable. If no highly
    confident matches exist, we still try the top somewhat-plausible matches."""
    scored = _scored_youtube_candidates(search_info, job)
    
    # We prefer 'confident' matches
    confident = [(url, details) for score, details, url in scored if _candidate_is_confident(score, details)]
    if confident:
        return confident

    # If no matches are 'confident', we still try anything with a decent score (>40%)
    # rather than failing immediately. This handles cases where metadata is slightly off.
    plausible = [(url, details) for score, details, url in scored if score > 40]
    if plausible:
        return plausible

    # If everything is <40%, it's likely total junk/unrelated.
    best_score, best_details, _ = scored[0]
    title = best_details.get("title") or "unknown result"
    raise RuntimeError(f"ytp-dl could not find any plausible YouTube match; best was {best_score}%: {title}")


def _youtube_ai_race_timeout() -> float:
    try:
        return max(0.0, min(5.0, float(os.environ.get("MINDINGUFLAC_YOUTUBE_AI_RACE_TIMEOUT", "1.25"))))
    except Exception:
        return 1.25


def _ranked_youtube_matches_with_ai(
    candidates: list[tuple[str, dict]],
    job: dict,
    manager,
) -> list[tuple[str, dict]]:
    candidates = _prepend_current_youtube_candidate(candidates, job)
    if len(candidates) < 3:
        return candidates
    try:
        import ai_reranker
        config = getattr(manager, "config", None)
        ai_provider = getattr(config, "ai_provider", "duckai")
        if not ai_reranker.is_enabled(ai_provider):
            return candidates
    except Exception as exc:
        manager._append_cache_event(job, "trying", f"YouTube AI advisor unavailable ({exc})")
        return candidates
    ai_timeout = _youtube_ai_race_timeout()
    if ai_timeout <= 0:
        return candidates

    done = threading.Event()
    result: dict[str, object] = {}
    id_to_candidate: dict[int, tuple[str, dict]] = {}
    target = _expected_track(job)
    ai_candidates = []
    for idx, (url, details) in enumerate(candidates[:20], start=1):
        details = details or {}
        id_to_candidate[idx] = (url, details)
        ai_candidates.append({
            "id": idx,
            "title": details.get("title") or url,
            "source": details.get("uploader") or "YouTube",
            "seeders": 0,
            "score": details.get("score") or 0,
            "query": "youtube",
        })

    def run_ai_advisor() -> None:
        try:
            import ai_reranker
            config = getattr(manager, "config", None)
            duck_model = getattr(config, "duck_model", "1")
            ai_provider = getattr(config, "ai_provider", "duckai")
            gemini_model = getattr(config, "gemini_model", "gemini-1.5-flash")
            ranked_ids = ai_reranker.rank_candidates(target, ai_candidates, duck_model, ai_provider, gemini_model)
            if ranked_ids:
                result["ranked_ids"] = ranked_ids
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            done.set()

    threading.Thread(target=run_ai_advisor, daemon=True, name=f"youtube-ai-rerank-{job.get('id', '')}").start()
    manager._append_cache_event(job, "trying", "YouTube AI advisor running in parallel")

    if not done.wait(ai_timeout):
        manager._append_cache_event(job, "trying", "YouTube local selector won before AI advisor responded")
        return candidates
    if result.get("error"):
        manager._append_cache_event(job, "trying", f"YouTube AI advisor unavailable ({result['error']})")
        return candidates

    ranked_ids = result.get("ranked_ids")
    if not isinstance(ranked_ids, list):
        return candidates

    ordered: list[tuple[str, dict]] = []
    seen_urls: set[str] = set()
    for value in ranked_ids:
        try:
            item = id_to_candidate.get(int(value))
        except Exception:
            item = None
        if not item:
            continue
        url = item[0]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ordered.append(item)
    for item in candidates:
        if item[0] not in seen_urls:
            ordered.append(item)

    if ordered:
        manager._append_cache_event(job, "trying", f"YouTube AI advisor ranked {len(ordered)} candidates first")
        return ordered
    return candidates


def run(output_dir: Path, job: dict, manager) -> None:
    from service_downloader import _find_audio_files

    if job["id"] in manager._cancel_flags:
        return

    import db
    url = _resolved_youtube_url(job)
    if not url:
        raise RuntimeError("ytp-dl could not build a YouTube URL or search query from the selected track metadata")

    quality = job.get("quality") or "best"
    codec = _quality_to_codec(quality)
    format_selector = _format_selector(quality)
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress_cb(payload: dict) -> None:
        status = str(payload.get("status") or "")
        if status == "downloading":
            downloaded = int(payload.get("downloaded_bytes") or 0)
            total = int(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
            if total > 0:
                percent = int((downloaded / total) * 100)
                with manager._lock:
                    job["progress"] = percent
                    job["last_status"] = f"Downloading from YouTube... {percent}%"
        elif status == "finished":
            with manager._lock:
                job["last_status"] = "Finalizing YouTube download..."

    postprocessors = [{"key": "FFmpegMetadata"}]
    if codec:
        postprocessors.insert(0, {"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": "0"})

    ydl_opts = {
        "format": format_selector,
        "outtmpl": "%(title)s.%(ext)s",
        "paths": {"home": str(output_dir)},
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": True,
        "cachedir": str(output_dir / ".cache"),
        "allow_unplayable_formats": False,
        "progress_hooks": [progress_cb],

        "writethumbnail": True,
        "addmetadata": True,
        "postprocessors": postprocessors,
    }

    ffmpeg_path = _ffmpeg_location()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    with manager._lock:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["resolved_url"] = url
        job["last_status"] = "Searching YouTube..." if url.startswith("ytsearch") else "Downloading from YouTube..."
        job["active_provider"] = "ytp-dl"
    label = codec.upper() if codec else "best native audio"
    manager._append_cache_event(job, "trying", f"Downloading via ytp-dl ({label})...")

    try:
        yt_dlp = _get_yt_dlp()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            def _try_download(target_url: str) -> str | None:
                if target_url.startswith("ytsearch"):
                    try:
                        search_info = ydl.extract_info(target_url, download=False)
                        if not isinstance(search_info, dict):
                            return None
                        candidates = _ranked_youtube_matches(search_info, job)
                        candidates = _prepend_current_youtube_candidate(candidates, job)
                        candidates = _ranked_youtube_matches_with_ai(candidates, job, manager)
                    except Exception as exc:
                        manager._append_cache_event(job, "trying", f"YouTube search failed: {exc}")
                        return None
                else:
                    candidates = [(target_url, None)]

                # Try up to 8 candidates in order of score
                attempts = [(u, s) for u, s in candidates if not db.is_blacklisted(u)][:8]
                if not attempts:
                    return None

                for index, (download_url, selected) in enumerate(attempts):
                    if job["id"] in manager._cancel_flags:
                        return None
                    if selected:
                        with manager._lock:
                            job["resolved_url"] = download_url
                            job["ytpdl_match"] = selected
                            job["last_status"] = f"Downloading YouTube match: {selected.get('title', '')[:80]}"
                        verb = "Trying next YouTube match" if index else "Selected YouTube match"
                        manager._append_cache_event(
                            job,
                            "trying",
                            f"{verb} ({selected.get('score', 0)}%): {selected.get('title', '')[:80]}",
                        )
                    try:
                        result_code = ydl.download([download_url])
                        
                        # Verify that a file was actually produced. 
                        # With ignoreerrors: True, ydl.download might return success-ish codes even if it skipped.
                        if result_code == 0 or _find_audio_files(output_dir):
                            return download_url
                        
                        # If we get here, it failed to produce a file
                        db.add_to_blacklist(download_url, "ytp-dl produced no file (likely restricted or unplayable)")
                        if index + 1 < len(attempts):
                            manager._append_cache_event(
                                job, "trying", f"YouTube candidate failed to download, blacklisting and trying another..."
                            )
                        continue
                    except Exception as exc:
                        db.add_to_blacklist(download_url, f"ytp-dl error: {exc}")
                        if index + 1 < len(attempts):
                            manager._append_cache_event(
                                job, "trying", f"YouTube candidate unavailable: {exc}"
                            )
                        else:
                            manager._append_cache_event(job, "trying", f"YouTube candidate failed: {exc}")
                return None

            worked_url = None
            if url:
                worked_url = _try_download(url)
            
            if not worked_url:
                if url and not url.startswith("ytsearch"):
                    db.add_to_blacklist(url, "direct url failed")
                
                # Phase 2: Full Search (Artist + Title + Album)
                search_query = _youtube_search_query(job, clean=False)
                if search_query and search_query != url:
                    manager._append_cache_event(job, "trying", "Falling back to full YouTube search...")
                    worked_url = _try_download(search_query)
            
            if not worked_url:
                # Phase 3: Clean Search (Artist + Base Title, stripping Remastered/Deluxe/etc.)
                clean_query = _youtube_search_query(job, clean=True)
                if clean_query and clean_query != url:
                    manager._append_cache_event(job, "trying", "Falling back to clean YouTube search (stripping version suffixes)...")
                    worked_url = _try_download(clean_query)

            if not worked_url:
                raise RuntimeError("All YouTube download attempts failed")

    except Exception as exc:
        raise RuntimeError(f"ytp-dl failed: {exc}") from exc

    audio_files = _find_audio_files(output_dir)
    if not audio_files:
        raise RuntimeError("ytp-dl reported success but no playable audio file was found")

    final = audio_files[0]
    
    # Persistence: save the successful URL
    if worked_url:
        track_key = job.get("track_key") or f"{job.get('artist','').lower()}||{job.get('title','').lower()}"
        existing = db.get_resolved_source(track_key)
        if not (job.get("engine") == "torrent" and existing and existing.get("engine") == "torrent"):
            db.save_resolved_source(
                track_key=track_key,
                engine="ytp-dl",
                service="youtube",
                quality=job.get("quality") or "best",
                resolved_url=worked_url
            )

    with manager._lock:
        job["library_path"] = str(final)
        job["provider_used"] = "ytp-dl"
        job["progress"] = 100
        job["last_status"] = "YouTube download complete"
    manager._append_cache_event(job, "provider", f"ytp-dl produced {final.name}")
