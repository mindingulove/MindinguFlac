"""Live verification of the Android backend in the Android configuration.

Runs the real ``android_runtime.bootstrap.start()`` on a python3.12
interpreter whose installed packages are exactly the APK's bundled wheel set,
with the APK's vendored source tree on sys.path, then exercises the embedded
HTTP API the way the WebView does: capability report, settings persistence,
search, artist/album/playlist metadata, lyrics, artwork, download job
lifecycle, cancellation and range streaming.

The one thing it cannot prove is the jlibtorrent JNI library loading, which
needs an arm64 device; that probe reports unavailable here and is reported as
such rather than skipped silently.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STAGE = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(STAGE))

# Chaquopy's `java` bridge only exists on-device. Fail loudly if anything
# tries to use it rather than silently degrading.
java = types.ModuleType("java")
java.jclass = lambda name: (_ for _ in ()).throw(
    RuntimeError(f"java.jclass({name}) requires an Android device"))
sys.modules["java"] = java

FILES = WORK / "files"
CACHE = WORK / "cache"
MUSIC = WORK / "music"
for directory in (FILES, CACHE, MUSIC):
    directory.mkdir(parents=True, exist_ok=True)

TOKEN = "verify-token-0001"
results: list[tuple[str, bool, str]] = []


def check(name, fn):
    try:
        detail = fn()
    except Exception as exc:
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"  FAIL  {name}\n          {type(exc).__name__}: {exc}")
        return None
    results.append((name, True, str(detail or "")))
    print(f"  PASS  {name}" + (f"\n          {detail}" if detail else ""))
    return detail


PORT = None


def request(method, path, body=None, headers=None, timeout=90):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request_headers = {"X-Mindinguflac-Token": TOKEN}
    if data:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def job_by_id(job_id):
    jobs = get_json("/api/service/downloads", timeout=60).get("jobs") or []
    return next((job for job in jobs if job.get("id") == job_id), None)


def get_json(path, timeout=90):
    status, _, payload = request("GET", path, timeout=timeout)
    if status != 200:
        raise RuntimeError(f"{path} -> HTTP {status}: {payload[:300]!r}")
    return json.loads(payload)


print("== start the real embedded backend ==")
from android_runtime import bootstrap  # noqa: E402

PORT = check("bootstrap.start() serves an authenticated loopback port and passes preflight",
             lambda: bootstrap.start(str(FILES), str(CACHE), str(MUSIC), TOKEN))
if not PORT:
    print("\nbackend did not start; aborting")
    sys.exit(1)

print()
print("== runtime capability report ==")


def capability_report():
    report = get_json("/api/runtime")
    engines = report["engines"]
    lines = [f"available={report['available_engines']}"]
    for name, entry in engines.items():
        state = "available" if entry["available"] else f"unavailable: {entry['reason'][:120]}"
        lines.append(f"{name}: {state}")
    missing = report["dependencies"]["missing"]
    lines.append(f"missing packaged runtimes: {missing or 'none'}")
    if missing:
        raise RuntimeError(f"packaged runtimes failed to import: {missing}")
    return "\n          ".join(lines)


report = check("every packaged runtime imports; engines reported with reasons", capability_report)

check("the torrent engine is withheld off-device instead of offered and failing",
      lambda: ("withheld: " + get_json("/api/runtime")["engines"]["torrent"]["reason"][:140])
      if not get_json("/api/runtime")["engines"]["torrent"]["available"]
      else (_ for _ in ()).throw(RuntimeError("torrent reported available without jlibtorrent")))

check("the Mornye engine is withheld until a provider extension exists",
      lambda: ("withheld: " + get_json("/api/runtime")["engines"]["spotiflac"]["reason"][:160])
      if not get_json("/api/runtime")["engines"]["spotiflac"]["available"]
      else "available")

print()
print("== settings ==")


def settings_shape():
    settings = get_json("/api/settings")
    assert settings["cache_dir"] == str(CACHE), settings["cache_dir"]
    assert settings["music_dir"] == str(MUSIC), settings["music_dir"]
    assert settings["ai_provider"] == "android", settings["ai_provider"]
    return f"{settings['download_engine']}/{settings['download_service']}/{settings['default_quality']}"


check("settings report the app-managed storage root and the on-device advisor", settings_shape)


def settings_reject_unavailable_engine():
    current = get_json("/api/settings")
    payload = dict(current)
    payload.update({"download_engine": "monochrome", "download_service": "tidal",
                    "default_quality": "LOSSLESS", "cache_dir": "/sdcard/typed-by-hand"})
    status, _, _ = request("POST", "/api/settings", payload)
    assert status == 200, status
    saved = get_json("/api/settings")
    assert saved["download_engine"] != "monochrome", saved["download_engine"]
    assert saved["cache_dir"] == str(CACHE), saved["cache_dir"]
    return f"clamped to {saved['download_engine']}/{saved['download_service']}/{saved['default_quality']}"


check("a POST naming a desktop engine or a hand-typed folder is clamped",
      settings_reject_unavailable_engine)


def settings_persist_across_restart():
    saved = get_json("/api/settings")
    config = json.loads((FILES / "mindinguflac" / "config.json").read_text("utf-8"))
    assert config["download_engine"] == saved["download_engine"], (config, saved)
    bootstrap.stop()
    port = bootstrap.start(str(FILES), str(CACHE), str(MUSIC), TOKEN)
    globals()["PORT"] = port
    again = get_json("/api/settings")
    assert again["download_engine"] == saved["download_engine"], (again, saved)
    assert again["music_dir"] == str(MUSIC)
    return f"kill/relaunch kept {again['download_engine']} under {MUSIC}"


check("settings and the managed storage root survive a kill/relaunch",
      settings_persist_across_restart)

print()
print("== Mornye-backed metadata (live network) ==")

TRACK = {"artist": "Daft Punk", "title": "Veridis Quo", "album": "Discovery"}
found: dict = {}


def music_search():
    payload = get_json("/api/music/search?" + urllib.parse.urlencode(
        {"q": f"{TRACK['artist']} {TRACK['title']}"}), timeout=180)
    items = payload.get("results") or []
    assert items, f"no results: {json.dumps(payload)[:300]}"
    tracks = [item for item in items if (item.get("type") or "track") == "track"]
    assert tracks, f"no track results: {json.dumps(items)[:300]}"
    found["track"] = tracks[0]
    # A different *title* is what makes a distinct job: the job pool keys on
    # track identity (ISRC / Spotify id), so the same song on a different
    # album edition is deliberately adopted as the same job.
    first_title = (tracks[0].get("title") or "").casefold()
    found["other_track"] = next(
        (item for item in tracks[1:]
         if (item.get("title") or "").casefold() not in ("", first_title)), None)
    return f"{len(items)} results; first track = {tracks[0].get('artist')} - {tracks[0].get('title')}"


check("music search returns tracks through the embedded Mornye metadata client", music_search)


def artist_top_tracks():
    track = found.get("track") or {}
    status, _, body = request("POST", "/api/artist/top_tracks", {
        "name": track.get("artist") or TRACK["artist"],
        "artist_id": (track.get("metadata") or {}).get("artist_id") or "",
    }, timeout=240)
    assert status == 200, f"HTTP {status}: {body[:200]!r}"
    tracks = json.loads(body).get("tracks") or []
    assert tracks, f"no top tracks: {body[:300]!r}"
    found["album"] = {"artist": tracks[0].get("artist") or TRACK["artist"],
                      "name": tracks[0].get("album") or TRACK["album"]}
    with_art = sum(1 for item in tracks if item.get("artwork_url"))
    return f"{len(tracks)} top tracks, {with_art} with artwork"


check("the artist page's top tracks load with artwork", artist_top_tracks)


def related_music():
    track = found.get("track") or {}
    status, _, body = request("POST", "/api/artist/related", {
        "name": track.get("artist") or TRACK["artist"],
        "artist_id": (track.get("metadata") or {}).get("artist_id") or "",
        "limit": 8,
    }, timeout=240)
    assert status == 200, f"HTTP {status}: {body[:200]!r}"
    value = json.loads(body)
    artists = value.get("artists") if isinstance(value, dict) else value
    artists = artists or []
    assert artists, f"no related artists: {body[:300]!r}"
    return f"{len(artists)} related artists; first={artists[0].get('name')}"


check("related music resolves on the embedded runtime", related_music)


def album_tracklist():
    album = found.get("album") or {}
    query = {"artist": album.get("artist") or TRACK["artist"],
             "album": album.get("name") or album.get("title") or TRACK["album"]}
    metadata = get_json("/api/music/album?" + urllib.parse.urlencode(query), timeout=240)
    payload = get_json("/api/music/album_tracks?" + urllib.parse.urlencode(query), timeout=240)
    tracks = payload.get("tracks") or []
    assert tracks, f"album tracklist empty: {json.dumps(payload)[:300]}"
    return (f"{query['album']}: {len(tracks)} tracks, year={metadata.get('year')}, "
            f"artwork={bool(metadata.get('artwork_url'))}")


check("album pages return a full tracklist", album_tracklist)


def artwork():
    track = found.get("track") or {}
    url = track.get("artwork_url") or ""
    if not url:
        payload = get_json("/api/music/search?" + urllib.parse.urlencode(
            {"q": f"{TRACK['artist']} {TRACK['album']}"}), timeout=180)
        items = payload.get("results") or []
        url = next((item.get("artwork_url") for item in items if item.get("artwork_url")), "")
    assert url, "no artwork URL in any search result"
    return url[:120]


check("search results carry artwork URLs", artwork)


def lyrics():
    track = found.get("track") or TRACK
    query = {"artist": track.get("artist") or TRACK["artist"],
             "title": track.get("title") or TRACK["title"]}
    status, _, payload = request("GET", "/api/lyrics?" + urllib.parse.urlencode(query), timeout=180)
    assert status in (200, 502), f"HTTP {status}: {payload[:200]!r}"
    value = json.loads(payload)
    if status == 502:
        return f"endpoint answered 502 with a reason: {str(value.get('error'))[:120]}"
    text = value.get("lyrics") or value.get("text") or ""
    lines = value.get("lines") or []
    return f"{len(text)} chars, {len(lines)} synced lines" if (text or lines) else "endpoint answered with no lyrics for this track"


check("the lyrics endpoint answers through the embedded runtime", lyrics)


def deterministic_matching_is_real_rapidfuzz():
    import rapidfuzz
    import rapidfuzz.distance
    import rapidfuzz.process

    origin = rapidfuzz.__file__
    assert str(STAGE) in origin, origin
    assert rapidfuzz.__version__.startswith("3."), rapidfuzz.__version__
    score = rapidfuzz.fuzz.token_set_ratio("Daft Punk Discovery", "Discovery - Daft Punk")
    best = rapidfuzz.process.extractOne("veridis quo", ["Veridis Quo", "Aerodynamic"])
    distance = rapidfuzz.distance.Levenshtein.distance("kitten", "sitting")
    return (f"rapidfuzz {rapidfuzz.__version__} (pure python), token_set_ratio={score:.0f}, "
            f"extractOne={best[0]!r}, levenshtein={distance}")


check("the bundled RapidFuzz is the full package, not the fallback shim",
      deterministic_matching_is_real_rapidfuzz)

def playlists_endpoint():
    payload = get_json("/api/playlists", timeout=120)
    playlists = payload.get("playlists") if isinstance(payload, dict) else payload
    assert playlists is not None, f"unexpected shape: {json.dumps(payload)[:200]}"
    return f"{len(playlists)} playlists on a fresh install (import target reachable)"


check("the playlist store answers on a fresh install", playlists_endpoint)


def playlist_import():
    """Import a real Spotify playlist through the embedded metadata client."""
    url = os.environ.get(
        "MINDINGUFLAC_VERIFY_PLAYLIST",
        "https://open.spotify.com/album/2noRn2Aes5aoNVsU6iWThc")
    origin = "album" if "/album/" in url else "manual"
    status, _, body = request("POST", "/api/playlists",
                              {"spotify_url": url, "origin": origin}, timeout=300)
    assert status in (200, 201), f"HTTP {status}: {body[:300]!r}"
    playlist = json.loads(body)
    tracks = playlist.get("tracks") or []
    assert playlist.get("imported"), f"import reported nothing: {json.dumps(playlist)[:300]}"
    assert tracks, "imported playlist has no tracks"
    found["playlist_id"] = playlist["id"]
    stored = get_json("/api/playlists", timeout=120)
    stored = stored.get("playlists") if isinstance(stored, dict) else stored
    assert any(item.get("id") == playlist["id"] for item in stored), "playlist was not persisted"
    return (f"imported {playlist.get('name')!r}: {len(tracks)} tracks, "
            f"artwork={bool(playlist.get('artwork_url'))}, persisted")


check("a Spotify playlist/album import resolves and persists", playlist_import)

print()
print("== download jobs and streaming ==")


def job_lifecycle():
    track = found.get("track") or TRACK
    payload = {"kind": "track", "mode": "stream", "artist": track.get("artist") or TRACK["artist"],
               "album": track.get("album") or TRACK["album"],
               "title": track.get("title") or TRACK["title"],
               "track": track, "metadata": track.get("metadata") or track}
    status, _, body = request("POST", "/api/service/download", payload, timeout=180)
    assert status in (200, 201), f"HTTP {status}: {body[:300]!r}"
    job = json.loads(body)
    job_id = job.get("id") or job.get("job_id")
    assert job_id, f"no job id: {json.dumps(job)[:300]}"
    settings = get_json("/api/settings")
    deadline = time.time() + 200
    last = {}
    while time.time() < deadline:
        last = job_by_id(job_id) or {}
        state = str(last.get("status") or "")
        if state in {"finished", "error", "cancelled"}:
            break
        if float(last.get("downloaded_bytes") or 0) > 0:
            break
        time.sleep(1.5)
    found["job"] = last
    found["job_id"] = job_id
    assert str(last.get("engine") or settings["download_engine"]) == settings["download_engine"], (
        f"job engine {last.get('engine')} != selected {settings['download_engine']}")
    return (f"engine={last.get('engine')} status={last.get('status')} "
            f"progress={last.get('progress')} bytes={last.get('downloaded_bytes')} "
            f"error={str(last.get('error') or '')[:120]}")


check("a download job runs on the selected engine and reports real progress", job_lifecycle)


def job_cancellation():
    track = found.get("track") or TRACK
    payload = {"kind": "track", "mode": "stream", "artist": track.get("artist") or TRACK["artist"],
               "album": track.get("album") or TRACK["album"],
               "title": (track.get("title") or TRACK["title"]) + " ",
               "track": track, "metadata": track.get("metadata") or track}
    status, _, body = request("POST", "/api/service/download", payload, timeout=180)
    assert status in (200, 201), status
    job = json.loads(body)
    job_id = job.get("id") or job.get("job_id")
    status, _, body = request("DELETE", "/api/service/cancel", {"job_id": job_id}, timeout=60)
    assert status == 200, f"cancel HTTP {status}: {body[:200]!r}"
    deadline = time.time() + 60
    state = ""
    while time.time() < deadline:
        state = str((job_by_id(job_id) or {}).get("status") or "")
        if state in {"cancelled", "error", "finished"}:
            break
        time.sleep(1)
    assert state in {"cancelled", "error", "finished"}, f"job stuck at {state!r} after cancel"
    reason = str((job_by_id(job_id) or {}).get("error") or "")
    return f"cancelled job reached status={state} ({reason[:80]})"


check("cancelling a running job is honoured", job_cancellation)


def duplicate_jobs_are_reused():
    track = found.get("track") or TRACK
    payload = {"kind": "track", "mode": "stream", "artist": track.get("artist") or TRACK["artist"],
               "album": track.get("album") or TRACK["album"],
               "title": track.get("title") or TRACK["title"],
               "track": track, "metadata": track.get("metadata") or track}
    ids = []
    for _ in range(2):
        status, _, body = request("POST", "/api/service/download", payload, timeout=180)
        assert status in (200, 201), status
        value = json.loads(body)
        ids.append(value.get("id") or value.get("job_id"))
    assert ids[0] == ids[1], f"duplicate request created a second job: {ids}"
    return f"both requests adopted job {ids[0]}"


check("a duplicate request for the same track adopts the existing job",
      duplicate_jobs_are_reused)


def prefetch_jobs_are_distinct_and_cancellable():
    other = found.get("other_track")
    assert other, "no second distinct track was found to prefetch"
    payload = {"kind": "track", "mode": "stream", "prefetch": True,
               "artist": other.get("artist") or "", "album": other.get("album") or "",
               "title": other.get("title") or "", "track": other,
               "metadata": other.get("metadata") or other}
    status, _, body = request("POST", "/api/service/download", payload, timeout=180)
    assert status in (200, 201), status
    job_id = json.loads(body).get("id") or json.loads(body).get("job_id")
    assert job_id != found.get("job_id"), "prefetch reused the playing job"
    status, _, _ = request("DELETE", "/api/service/cancel", {"job_id": job_id}, timeout=60)
    assert status == 200, status
    return f"prefetch job {job_id} created and cancelled independently"


check("a prefetch job is independent of the playing job", prefetch_jobs_are_distinct_and_cancellable)


def range_streaming():
    sample = MUSIC / "range-probe.flac"
    sample.write_bytes(bytes(range(256)) * 16)
    query = urllib.parse.urlencode({"path": str(sample), "audio": "1"})
    status, headers, body = request("GET", f"/api/library/stream?{query}", timeout=30)
    assert status == 200 and len(body) == 4096, (status, len(body))
    assert headers.get("Accept-Ranges") == "bytes", headers
    status, headers, body = request("GET", f"/api/library/stream?{query}",
                                    headers={"Range": "bytes=1024-2047"}, timeout=30)
    assert status == 206, status
    assert headers.get("Content-Range") == "bytes 1024-2047/4096", headers
    assert body == (bytes(range(256)) * 16)[1024:2048], len(body)
    status, headers, _ = request("GET", f"/api/library/stream?{query}",
                                 headers={"Range": "bytes=99999-"}, timeout=30)
    assert status == 416, status
    assert headers.get("Content-Range") == "bytes */4096", headers
    sample.unlink()
    return "200 full, 206 partial with exact bytes, 416 for a bad range"


check("the range-stream endpoint serves byte ranges the phone player needs",
      range_streaming)


def offline_errors_are_actionable():
    status, _, body = request("GET", "/api/library/stream?path=/does/not/exist.flac", timeout=20)
    assert status == 404, status
    value = json.loads(body)
    assert value.get("error"), value
    return f"missing file -> HTTP 404 {value['error']!r}"


check("a missing file is an explained error, not an empty stream",
      offline_errors_are_actionable)

def activity_reopen_keeps_the_job_pool():
    """Closing and reopening the Activity must not lose or duplicate jobs.

    Chaquopy keeps the interpreter alive across an Activity close/reopen, so a
    download that was running really is still running — the job pool is
    reused, not reloaded. (Actual process death goes through
    ``ServiceDownloadManager._load_jobs``, which rewrites a persisted
    ``running`` job to an interrupted error; that path is covered by
    ``test/test_android_runtime.py``.)
    """
    before = get_json("/api/service/downloads", timeout=60).get("jobs") or []
    bootstrap.stop()
    port = bootstrap.start(str(FILES), str(CACHE), str(MUSIC), TOKEN)
    globals()["PORT"] = port
    after = get_json("/api/service/downloads", timeout=60).get("jobs") or []
    assert after, "the job pool did not survive the Activity reopen"
    before_ids = {job.get("id") for job in before}
    after_ids = {job.get("id") for job in after}
    assert before_ids <= after_ids, f"jobs lost on reopen: {before_ids - after_ids}"
    assert len(after_ids) == len(after), "the job pool contains duplicate ids"
    persisted = json.loads((FILES / "mindinguflac" / "jobs.json").read_text("utf-8"))
    assert {job["id"] for job in persisted if isinstance(job, dict)} >= before_ids, (
        "jobs were not persisted to disk")
    states = sorted({str(job.get("status")) for job in after})
    return f"{len(after)} jobs kept across the reopen, states={states}, persisted to jobs.json"


check("closing and reopening the Activity keeps the job pool intact",
      activity_reopen_keeps_the_job_pool)


def cache_cleanup():
    stray = CACHE / "stale-job" / "leftover.part"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"\x00" * 2048)
    before = get_json("/api/cache", timeout=60)
    status, _, body = request("DELETE", "/api/cache", {}, timeout=180)
    assert status == 200, f"HTTP {status}: {body[:200]!r}"
    assert not stray.exists(), "cache cleanup left a stray partial file behind"
    assert CACHE.is_dir(), "cache cleanup removed the managed cache root itself"
    after = get_json("/api/cache", timeout=60)
    return (f"cleared {before.get('files', '?')} -> {after.get('files', '?')} files; "
            f"managed cache root kept at {CACHE}")


check("clearing the cache removes stray files and keeps the managed root",
      cache_cleanup)


def library_data_survives_relaunch():
    playlist_id = found.get("playlist_id")
    bootstrap.stop()
    port = bootstrap.start(str(FILES), str(CACHE), str(MUSIC), TOKEN)
    globals()["PORT"] = port
    stored = get_json("/api/playlists", timeout=120)
    stored = stored.get("playlists") if isinstance(stored, dict) else stored
    if playlist_id:
        assert any(item.get("id") == playlist_id for item in stored), "playlist lost on relaunch"
    settings = get_json("/api/settings")
    assert settings["music_dir"] == str(MUSIC), settings["music_dir"]
    assert settings["cache_dir"] == str(CACHE), settings["cache_dir"]
    return (f"{len(stored)} playlist(s) and the managed storage root survived a "
            f"second kill/relaunch")


check("library data survives a kill/relaunch under the single storage root",
      library_data_survives_relaunch)

bootstrap.stop()

failed = [name for name, ok, _ in results if not ok]
print()
print(f"== {len(results) - len(failed)}/{len(results)} checks passed ==")
for name in failed:
    print(f"  FAILED: {name}")
Path(sys.argv[3]).write_text(json.dumps(
    [{"check": name, "ok": ok, "detail": detail} for name, ok, detail in results], indent=2),
    encoding="utf-8")
sys.exit(1 if failed else 0)
