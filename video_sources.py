"""Curated music-video lookups, tried before the YouTube search.

Order (first hit wins):
  1. MusicBrainz  - the song's audio recording links to a "music video"
                    recording, which carries the YouTube link. If the audio
                    recording has no such link, search MusicBrainz's video
                    recordings for an official music video of the same song.
  2. Wikidata     - song items keyed by ISRC or MusicBrainz recording ID with
                    a "YouTube video ID" (P1651).
  3. Odesli       - Spotify URI -> YouTube link. Its public API now needs a
                    key (MINDINGUFLAC_ODESLI_API_KEY or config odesli_api_key);
                    skipped without one. Its YouTube link is often the
                    auto-generated "Artist - Topic" audio, so those are refused.

All of these are human-curated or platform mappings, so a hit is far more
likely to be the official clip than a ranked search result.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request

USER_AGENT = "Mindinguflac/1.3 (self-hosted music player; https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)"
_YOUTUBE_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_NOT_THE_CLIP = ("live", "lyric", "visualizer", "visualiser", "behind the scenes", "making of",
                 "teaser", "trailer", "karaoke", "performance", "acoustic", "rehearsal", "interview")

def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _get_json(url: str, *, headers: dict | None = None, data: bytes | None = None, timeout: int = 12) -> dict:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                               **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _musicbrainz(path: str, params: dict) -> dict:
    """MusicBrainz allows one request per second per client; share the gate
    with metadata enrichment so the two together never burst."""
    from music_metadata import musicbrainz_throttle
    musicbrainz_throttle()
    return _get_json(f"https://musicbrainz.org/ws/2/{path}?" + urllib.parse.urlencode({**params, "fmt": "json"}))


def youtube_id(url: str) -> str:
    match = _YOUTUBE_ID.search(url or "")
    return match.group(1) if match else ""


def _hit(source: str, video_id: str, title: str = "", duration_s: float = 0) -> dict:
    return {"source": source, "video_id": video_id, "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title, "duration": duration_s}


# ---------------------------------------------------------------- MusicBrainz

def _youtube_link_of(recording_id: str) -> str:
    data = _musicbrainz(f"recording/{recording_id}", {"inc": "url-rels"})
    for relation in data.get("relations") or []:
        if relation.get("type") in ("free streaming", "streaming"):
            video_id = youtube_id((relation.get("url") or {}).get("resource", ""))
            if video_id:
                return video_id
    return ""


def _is_the_clip(recording: dict) -> bool:
    note = _norm(recording.get("disambiguation"))
    if "official music video" in note or note in ("", "music video", "video", "official video"):
        return not any(word in note for word in _NOT_THE_CLIP)
    return False


def _audio_recording_id(identity: dict) -> str:
    recording_id = str(identity.get("musicbrainz_recording_id") or "").strip()
    if recording_id:
        return recording_id
    try:
        import music_metadata
        duration_ms = int(float(identity.get("duration_s") or 0) * 1000)
        found = {}
        if identity.get("isrc"):
            found = music_metadata.musicbrainz_recording_identifiers_by_isrc(
                identity["isrc"], identity.get("title") or "", identity.get("artist") or "", duration_ms)
        if not found:
            found = music_metadata.musicbrainz_recording_identifiers(
                identity.get("artist") or "", identity.get("title") or "", identity.get("album") or "", duration_ms)
        return str(found.get("musicbrainz_recording_id") or "")
    except Exception:
        return ""


def musicbrainz_music_video(identity: dict) -> tuple[dict | None, list[str]]:
    """(hit, recording ids seen). The ids also feed the Wikidata lookup."""
    title, artist = identity.get("title") or "", identity.get("artist") or ""
    seen: list[str] = []
    audio_id = _audio_recording_id(identity)
    video_candidates: list[dict] = []
    if audio_id:
        seen.append(audio_id)
        data = _musicbrainz(f"recording/{audio_id}", {"inc": "recording-rels"})
        for relation in data.get("relations") or []:
            target = relation.get("recording") or {}
            if relation.get("type") == "music video" and target.get("id"):
                video_candidates.append(target)
    if not video_candidates and title and artist:
        # The enriched recording is often one of many album pressings; the
        # music-video link may hang off another. Ask for the video directly.
        query = f'recording:"{title}" AND artist:"{artist}" AND video:true'
        rows = _musicbrainz("recording/", {"query": query, "limit": "15"}).get("recordings") or []
        exact = [row for row in rows
                 if _norm(row.get("title")) == _norm(title)
                 and any(_norm(credit.get("name")) == _norm(artist) for credit in row.get("artist-credit") or [])
                 and _is_the_clip(row)]
        # "official music video" first, then plain entries.
        exact.sort(key=lambda row: 0 if "official music video" in _norm(row.get("disambiguation")) else 1)
        video_candidates = exact
    for recording in video_candidates[:3]:
        if not _is_the_clip(recording) and recording.get("disambiguation"):
            continue
        seen.append(recording["id"])
        video_id = _youtube_link_of(recording["id"])
        if video_id:
            length = float(recording.get("length") or 0) / 1000
            return _hit("musicbrainz", video_id, recording.get("title") or title, length), seen
    return None, seen


# ------------------------------------------------------------------- Wikidata

def wikidata_music_video(identity: dict, recording_ids: list[str]) -> dict | None:
    isrc = re.sub(r"[^A-Z0-9]", "", str(identity.get("isrc") or "").upper())
    ids = [rid for rid in recording_ids if re.fullmatch(r"[0-9a-f-]{36}", rid)]
    clauses = []
    if isrc:
        clauses.append(f'{{ ?item wdt:P1243 "{isrc}" }}')
    clauses += [f'{{ ?item wdt:P4404 "{rid}" }}' for rid in ids]
    if not clauses:
        return None
    query = f"SELECT ?yt WHERE {{ {' UNION '.join(clauses)} . ?item wdt:P1651 ?yt }} LIMIT 5"
    data = _get_json("https://query.wikidata.org/sparql",
                     headers={"Accept": "application/sparql-results+json",
                              "Content-Type": "application/x-www-form-urlencoded"},
                     data=urllib.parse.urlencode({"query": query}).encode())
    for binding in (data.get("results") or {}).get("bindings") or []:
        video_id = str((binding.get("yt") or {}).get("value") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return _hit("wikidata", video_id, identity.get("title") or "")
    return None


# --------------------------------------------------------------------- Odesli

def odesli_music_video(identity: dict, api_key: str = "") -> dict | None:
    spotify_id = str(identity.get("spotify_id") or "").strip()
    key = (api_key or os.environ.get("MINDINGUFLAC_ODESLI_API_KEY", "")).strip()
    if not spotify_id or not key:
        return None
    data = _get_json("https://api.song.link/v1-alpha.1/links?" + urllib.parse.urlencode(
        {"url": f"spotify:track:{spotify_id}", "key": key}))
    links = data.get("linksByPlatform") or {}
    entity_id = (links.get("youtube") or {}).get("entityUniqueId", "")
    entity = (data.get("entitiesByUniqueId") or {}).get(entity_id) or {}
    channel = str(entity.get("artistName") or "")
    title = _norm(entity.get("title"))
    # "Artist - Topic" channels hold auto-generated audio-only uploads.
    if channel.endswith(" - Topic") or any(word in title for word in ("audio", "lyric", "visualizer")):
        return None
    video_id = youtube_id((links.get("youtube") or {}).get("url", ""))
    return _hit("odesli", video_id, entity.get("title") or "") if video_id else None


# -------------------------------------------------------------------- chained

def curated_music_video(identity: dict, odesli_api_key: str = "") -> dict | None:
    """First curated hit, or None to fall back to the YouTube search."""
    recording_ids: list[str] = []
    try:
        hit, recording_ids = musicbrainz_music_video(identity)
        if hit:
            return hit
    except Exception as exc:
        print(f"[VideoLookup] MusicBrainz: {exc}")
    for lookup in (lambda: wikidata_music_video(identity, recording_ids), lambda: odesli_music_video(identity, odesli_api_key)):
        try:
            hit = lookup()
            if hit:
                return hit
        except Exception as exc:
            print(f"[VideoLookup] {exc}")
    return None
