"""Monochrome track search and direct lossless streaming provider."""
from __future__ import annotations

import re
import threading
import time
import unicodedata
import urllib.parse
import uuid
from pathlib import Path


# The older .tf / .wtf instance list is stale. The live monochrome.st client
# currently falls back to this working catalog API; its current instance-list
# URL array is empty, so there are no verified official API mirrors to rotate
# through. Keep the retry loop generic for when the project publishes a live
# list again, but never guess at stale mirror hosts.
_INSTANCES = (("https://tracks.monochrome.st", "https://monochrome.st"),)
_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
               "(KHTML, like Gecko) Version/27.0 Safari/605.1.15")

# Monochrome answers abusive-looking clients with 429 and escalates to 403.
# Retrying immediately only extends the block, so a rejected stream pauses the
# engine for a while and new jobs fall back to YTP-DL until it expires.
_STREAM_BLOCK_SECONDS = {403: 600.0, 429: 120.0}
_stream_block_lock = threading.Lock()
_stream_blocked_until = 0.0
_stream_block_status = 0


def note_stream_rejected(http_status: int, retry_after: float | None = None) -> None:
    """Record a 403/429 from the track endpoint and start the cooldown."""
    global _stream_blocked_until, _stream_block_status
    status = int(http_status or 0)
    if status not in _STREAM_BLOCK_SECONDS:
        return
    cooldown = _STREAM_BLOCK_SECONDS[status]
    if retry_after and retry_after > 0:
        cooldown = min(1800.0, max(cooldown, float(retry_after)))
    with _stream_block_lock:
        until = time.time() + cooldown
        if until > _stream_blocked_until:
            _stream_blocked_until = until
            _stream_block_status = status


def note_stream_failing() -> None:
    """Start the cooldown after repeated stream failures whose cause is unknown.

    A browser/WebView <audio> element never exposes the HTTP status, so a
    429/403 there only shows up as a stream that keeps failing to reconnect.
    """
    global _stream_blocked_until, _stream_block_status
    with _stream_block_lock:
        until = time.time() + _STREAM_BLOCK_SECONDS[429]
        if until > _stream_blocked_until:
            _stream_blocked_until = until
            _stream_block_status = -1


def stream_block_reason() -> str:
    """Human-readable reason while Monochrome is cooling down, else ""."""
    with _stream_block_lock:
        remaining = _stream_blocked_until - time.time()
        status = _stream_block_status
    if remaining <= 0:
        return ""
    minutes = max(1, round(remaining / 60))
    if status == -1:
        return f"Monochrome streams kept failing (possibly rate limited); retrying it in {minutes} min"
    label = "403 access denied" if status == 403 else "429 rate limited"
    return f"Monochrome refused streams (HTTP {label}); retrying it in {minutes} min"


def stream_request_headers(site_origin: str = _INSTANCES[0][1]) -> dict[str, str]:
    """Headers Safari's <audio> element sends for a Monochrome track.

    Mirrors a captured healthy 206 response from the web player: audio
    destination, no Referer, and a per-playback session id. Connection is
    omitted because it is illegal in HTTP/2.
    """
    return {
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": site_origin,
        "Sec-Fetch-Dest": "audio",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": _USER_AGENT,
        "X-Playback-Session-Id": str(uuid.uuid4()).upper(),
    }


def _headers(site_origin: str, *, audio: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "*/*" if audio else "application/json, */*",
        "Origin": site_origin,
        "Referer": f"{site_origin}/",
        "User-Agent": _USER_AGENT,
    }
    if audio:
        headers.update({
            "Accept-Encoding": "identity",
            "Connection": "Keep-Alive",
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        })
    return headers


def _decode_error(path: Path) -> str:
    """Decode the whole file once; "" if it is intact (or ffmpeg is absent).

    A file can have a valid header and the right size yet be damaged in the
    middle (bytes spliced in from the wrong offset), which only a full decode
    reveals. A damaged file must not be saved into the library.
    """
    import subprocess

    try:
        from native_audio import _ffmpeg_exe
        ffmpeg = _ffmpeg_exe()
    except Exception:
        ffmpeg = ""
    if not ffmpeg:
        return ""
    try:
        result = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
                                capture_output=True, timeout=300,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return ""
    if result.returncode:
        return (result.stderr.decode("utf-8", "replace").strip().splitlines() or ["decode failed"])[-1][:200]
    return ""


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _artists(item: dict) -> list[str]:
    values = item.get("artistNames") or item.get("artists") or []
    if isinstance(values, str):
        return [values]
    names = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            names.append(str(value))
    for key in ("artist", "performer"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            names.append(str(value))
    return names


def _same_artist(expected: str, actual: list[str]) -> bool:
    wanted = _norm(expected)
    return bool(wanted and any(_norm(name) == wanted for name in actual))


# A re-issue or remaster of the same recording gets a new ISRC but keeps its
# length; a live take or re-recording with the same title almost never does.
# Catalog durations for the same remastered recording can differ by several
# seconds (for example, Spotify's Dire Straits "So Far Away - Remastered 1996"
# versus Monochrome's plain-title entry). Keep this narrow enough to reject
# live/edit versions while allowing provider metadata/trim differences.
_SAME_RECORDING_DURATION_MS = 8000
_REMASTER_DURATION_TOLERANCE_MS = 10000


def _duration_ms(item: dict) -> float:
    try:
        value = float(item.get("duration") or item.get("duration_ms") or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 1000 else value * 1000


def _select_matching_item(items: list[dict], title: str, artist: str, isrc: str,
                          duration_ms: float = 0) -> dict | None:
    wanted_title = _norm(title)
    wanted_isrc = _norm(isrc)
    if wanted_isrc:
        # Search is text-based on the current API, so use ISRC as a verification
        # key over the returned rows rather than sending it as the search term.
        exact_isrc = next((item for item in items if _norm(item.get("isrc")) == wanted_isrc), None)
        if exact_isrc is not None:
            return exact_isrc
    candidates = []
    for item in items:
        if artist and not _same_artist(artist, _artists(item)):
            continue
        if not wanted_title or not _same_song_title(title, item.get("title") or ""):
            continue
        returned_isrc = _norm(item.get("isrc"))
        gap = abs(_duration_ms(item) - duration_ms) if duration_ms and _duration_ms(item) else None
        if wanted_isrc and returned_isrc and returned_isrc != wanted_isrc:
            # Different ISRC: accept only when the length shows it is the same
            # recording. Distinct catalog ISRCs are normal for remasters too;
            # their mastered lengths can differ slightly, so allow a wider
            # gap only when the title matcher confirmed an explicit remaster
            # label (e.g. Spotify's "So Far Away - Remastered 1996" is 5.76 s
            # longer than Monochrome's same-title catalog recording).
            remaster_label = _is_remaster_label(_version_text(title)) or _is_remaster_label(_version_text(item.get("title") or ""))
            max_gap = _REMASTER_DURATION_TOLERANCE_MS if remaster_label else _SAME_RECORDING_DURATION_MS
            if gap is None or gap > max_gap:
                continue
        candidates.append((gap if gap is not None else float("inf"), len(candidates), item))
    if not candidates:
        return None
    # Closest length first; search order breaks ties.
    return min(candidates)[2]


# Words that say what kind of version a track is, not which one. Two version
# labels only describe the same recording when they share a *distinctive*
# word, typically a remixer or editor name ("Todd Terry").
_GENERIC_VERSION_WORDS = {
    "a", "and", "the", "of", "with", "feat", "ft", "featuring", "vs", "x", "s",
    "mix", "remix", "remixed", "edit", "radio", "club", "version", "original",
    "remaster", "remastered", "single", "album", "extended", "short", "long",
    "us", "uk", "mono", "stereo", "inch", "7", "12", "dub", "vocal", "instrumental",
    "live", "demo", "acoustic", "bonus", "track", "explicit", "clean",
}


def _split_version(title: str) -> tuple[str, set[str]]:
    """("Missing", {"todd", "terry"}) for "Missing - Todd Terry Remix" or
    "Missing (Todd Terry club mix, Ben Watt's radio edit)"."""
    text = str(title or "")
    match = re.match(r"^(.*?)\s*(?:\s-\s|\(|\[)(.*)$", text)
    base, version = (match.group(1), match.group(2)) if match else (text, "")
    if _is_remaster_label(version):
        return _norm(base), set()  # a remaster is the same recording, not a version
    words = set(_norm(version).split()) - _GENERIC_VERSION_WORDS - _REMASTER_LABEL_WORDS
    return _norm(base), {word for word in words if len(word) > 1 and not word.isdigit()}


# A remaster label names a new master of the same recording, not a different
# take, so "So Far Away - Remastered 1996" is the song Monochrome lists as
# "So Far Away". Only these words (plus years) may appear in such a label.
_REMASTER_LABEL_WORDS = {"remaster", "remastered", "remasters", "digital", "digitally", "edition",
                         "anniversary", "deluxe", "expanded", "version", "mono", "stereo", "the", "of"}


def _is_remaster_label(version_text: str) -> bool:
    words = _norm(version_text).split()
    return any(word.startswith("remaster") for word in words) and all(
        word.isdigit() or word in _REMASTER_LABEL_WORDS or (word.endswith("th") and word[:-2].isdigit())
        for word in words)


def _version_text(title: str) -> str:
    match = re.match(r"^(.*?)\s*(?:\s-\s|\(|\[)(.*)$", str(title or ""))
    return match.group(2) if match else ""


def _same_song_title(wanted: str, candidate: str) -> bool:
    """Exact title, or the same title where the only difference is a remaster
    label ("X - Remastered 1996" vs "X"). Live takes, edits and remixes stay
    different songs."""
    if _norm(wanted) == _norm(candidate):
        return True
    wanted_base, _ = _split_version(wanted)
    candidate_base, _ = _split_version(candidate)
    if not wanted_base or wanted_base != candidate_base:
        return False
    labels = [text for text in (_version_text(wanted), _version_text(candidate)) if text]
    return bool(labels) and all(_is_remaster_label(text) for text in labels)


def _musicbrainz_isrc_title(isrc: str) -> str:
    try:
        from music_metadata import get_json
        data = get_json(f"https://musicbrainz.org/ws/2/isrc/{urllib.parse.quote(isrc)}?fmt=json")
    except Exception:
        return ""
    recordings = data.get("recordings") or []
    return str(recordings[0].get("title") or "") if recordings else ""


def _select_named_version(items: list[dict], title: str, artist: str, isrc: str,
                          duration_ms: float) -> dict | None:
    """Spotify sometimes drops a version name: its "Missing" on a compilation is
    the Todd Terry remix radio edit (ISRC GBAHT9601125), while Monochrome lists
    "Missing" (the 4:07 original) and "Missing - Todd Terry Remix" (3:56).
    MusicBrainz names the recording behind the ISRC, so a Monochrome version is
    accepted only when its label shares a distinctive word with that name and
    its length agrees; a remix is never picked on length alone.
    """
    if not isrc or not duration_ms:
        return None
    official = _musicbrainz_isrc_title(isrc)
    official_base, official_words = _split_version(official)
    if not official_words or official_base != _split_version(title)[0]:
        return None
    best = None
    for item in items:
        if artist and not _same_artist(artist, _artists(item)):
            continue
        base, words = _split_version(item.get("title") or "")
        if base != official_base or not (words & official_words):
            continue
        gap = abs(_duration_ms(item) - duration_ms) if _duration_ms(item) else None
        if gap is None or gap > _SAME_RECORDING_DURATION_MS:
            continue
        if best is None or gap < best[0]:
            best = (gap, item)
    return best[1] if best else None


def _resolve_version(items: list[dict], match: dict | None, title: str, artist: str,
                     isrc: str, duration_ms: float) -> tuple[dict | None, str]:
    """Final pick when the results include remixes of this song.

    An exact ISRC hit is definitive. Otherwise, if any result is a version of
    the same title (a remix/edit), ask MusicBrainz what the ISRC really is: an
    unlabelled Spotify remix must not play as the original. Returns
    (match, reason-if-refused).
    """
    if match is not None and isrc and _norm(match.get("isrc")) == _norm(isrc):
        return match, ""
    wanted = _split_version(title)[0]
    has_version = any(
        (not artist or _same_artist(artist, _artists(item)))
        and _split_version(item.get("title") or "")[0] == wanted
        and _split_version(item.get("title") or "")[1]
        for item in items
    )
    if not has_version and match is not None:
        return match, ""
    if not isrc:
        return match, ""
    _base, official_words = _split_version(_musicbrainz_isrc_title(isrc))
    if not official_words:
        return match, ""  # MusicBrainz names the plain song: keep the original
    version = _select_named_version(items, title, artist, isrc, duration_ms)
    if version is not None:
        return version, ""
    return None, "the requested version (per MusicBrainz) is not on Monochrome"


def _search_items(requests_module, query: str, limit: int = 50, *, api_base: str | None = None,
                  site_origin: str | None = None) -> list[dict]:
    api_base = api_base or _INSTANCES[0][0]
    site_origin = site_origin or _INSTANCES[0][1]
    response = requests_module.get(
        f"{api_base}/search/tracks",
        params={"q": query, "limit": max(1, min(int(limit), 100))},
        headers=_headers(site_origin),
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    tracks = payload.get("tracks", []) if isinstance(payload, dict) else []
    return [item for item in tracks if isinstance(item, dict)]


def run(output_dir: Path, job: dict, manager) -> None:
    import requests
    from service_downloader import is_valid_audio_file

    title = str(job.get("title") or "Unknown").strip()
    artist = str(job.get("artist") or "Unknown").strip()
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    isrc = str(job.get("isrc") or metadata.get("isrc") or "").strip()
    duration_ms = _duration_ms(metadata)
    # Try the stable recording identifier first. The search endpoint accepts
    # arbitrary text, so querying ISRC can find a recording even when its title
    # or artist spelling differs from Spotify's metadata. Fall back to text for
    # catalogs that do not index ISRCs.
    queries = []
    if isrc:
        queries.append(isrc)
    text_query = f"{title} {artist}".strip()
    if text_query and text_query.casefold() not in {query.casefold() for query in queries}:
        queries.append(text_query)

    if job.get("mode", "stream") == "stream":
        manager._append_cache_event(job, "trying", f"Searching Monochrome for {title} — {artist}…")

    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{title} - {artist}.flac"
    part_path = final_path.with_suffix(final_path.suffix + ".part")
    failures = []
    stream_url = ""
    selected = None
    for api_base, site_origin in _INSTANCES:
        try:
            items = []
            match = None
            search_errors = []
            for query in queries:
                try:
                    found = _search_items(requests, query, api_base=api_base, site_origin=site_origin)
                    items.extend(found)
                    match = _select_matching_item(items, title, artist, isrc, duration_ms)
                    # Stop early only on a definitive ISRC hit; otherwise run
                    # the title search too, which is what surfaces remixes the
                    # version check below must see.
                    if match is not None and (not isrc or _norm(match.get("isrc")) == _norm(isrc)):
                        break
                except Exception as exc:
                    search_errors.append(f"query {query!r}: {exc}")
            refused = ""
            if items:
                match, refused = _resolve_version(items, match, title, artist, isrc, duration_ms)
            if match is None:
                detail = (f"search failed ({'; '.join(search_errors)})" if search_errors
                          else refused or "no exact ISRC or title/artist match")
                failures.append(f"{api_base}: {detail}")
                continue

            track_id = str(match.get("trackId") or match.get("id") or "").strip()
            if not track_id.isdigit():
                failures.append(f"{api_base}: invalid track ID")
                continue
            candidate_url = f"{api_base}/track/{urllib.parse.quote(track_id, safe='')}"
            if job.get("mode", "stream") == "stream":
                manager._append_cache_event(job, "provider",
                    f"Monochrome matched {match.get('title')} — {' / '.join(_artists(match))} at {site_origin}; streaming directly")
                with manager._lock:
                    job["resolved_url"] = candidate_url
                    job["direct_stream"] = True
                    job["active_stream_origin"] = site_origin
                    job["progress"] = 100
                    job["status"] = "finished"
                    job["last_status"] = "Streaming directly from Monochrome"
                return

            # Download through the same shared HTTP/2 fetch the native player
            # streams from (native_audio._MonochromeFetch). Saving a track that
            # is already playing reuses its bytes instead of requesting it
            # again; otherwise it is one request with at most a couple of
            # resumes, never the retry storm that trips the per-IP rate limit.
            import shutil
            import native_audio

            fetch = native_audio._monochrome_fetch(candidate_url, pin=True)
            try:
                while True:
                    if job["id"] in manager._cancel_flags:
                        raise RuntimeError("Download cancelled")
                    with fetch.condition:
                        if not (fetch.done or fetch.error or fetch.cancelled.is_set()):
                            fetch.condition.wait(timeout=0.5)
                        size, total, done, error = fetch.size, fetch.total, fetch.done, fetch.error
                    with manager._lock:
                        job["active_audio_path"] = str(fetch.path)
                        job["active_audio_size"] = total
                        job["active_audio_ready_bytes"] = size
                        if total:
                            job["progress"] = min(95, int(size * 95 / total))
                    if error:
                        raise RuntimeError(error)
                    if fetch.cancelled.is_set():
                        raise RuntimeError("download was interrupted")
                    if done:
                        break
                shutil.copyfile(fetch.path, part_path)
                if not is_valid_audio_file(part_path):
                    raise RuntimeError("response was not a valid FLAC file")
                decode_error = _decode_error(part_path)
                if decode_error:
                    raise RuntimeError(f"downloaded FLAC is damaged ({decode_error})")
                part_path.replace(final_path)
                with manager._lock:
                    job["active_audio_path"] = str(final_path)
                    job["active_audio_size"] = final_path.stat().st_size
                    job["active_audio_ready_bytes"] = final_path.stat().st_size
                selected = match
                stream_url = candidate_url
                break
            except Exception as exc:
                part_path.unlink(missing_ok=True)
                with manager._lock:
                    if job.get("active_audio_path") in (str(part_path), str(fetch.path)):
                        job["active_audio_path"] = ""
                        job["active_audio_ready_bytes"] = 0
                        job["active_audio_size"] = 0
                if str(exc) == "Download cancelled":
                    raise
                failures.append(f"{api_base}: download failed ({exc})")
            finally:
                native_audio._release_monochrome_fetch(fetch)
        except Exception as exc:
            if str(exc) == "Download cancelled":
                raise
            failures.append(f"{api_base}: {exc}")
    if selected is None:
        raise RuntimeError("Monochrome official instances failed: " + "; ".join(failures))

    with manager._lock:
        job["progress"] = 100
        job["resolved_url"] = stream_url
        job["last_status"] = "FLAC downloaded from Monochrome"
    manager._append_cache_event(job, "provider", f"Monochrome download completed: {final_path.name}")
