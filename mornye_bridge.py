"""Versioned REST first, with a narrow SDK adapter for uncovered metadata."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from types import SimpleNamespace
import threading

import mornye_runtime as runtime

logger = logging.getLogger(__name__)


def _track(row):
    # Keep our legacy metadata-normalisation layer independent of Pydantic.
    return SimpleNamespace(**row)


class SpotifyMetadataClient:
    def __init__(self):
        runtime.configure()
        self._sdk_instance = None
        self._sdk_lock = threading.Lock()
        self._details = OrderedDict()
        self._details_lock = threading.Lock()

    def _remember(self, tracks):
        with self._details_lock:
            for track in tracks:
                key = str(getattr(track, "id", ""))
                if key:
                    self._details[key] = track
                    self._details.move_to_end(key)
            while len(self._details) > 256:
                self._details.popitem(last=False)

    def _with_identity(self, row, detail=None):
        if detail is None:
            with self._details_lock:
                detail = self._details.get(str(row.get("id", "")))
        enriched = dict(row)
        if detail is not None:
            # v1 TrackOut omits album/artist IDs. Preserve those uncovered
            # fields without substituting a different edition by title.
            for key in ("album_id", "album_url", "artist_id", "artists_data", "album_artist_names", "plays", "preview_url"):
                value = getattr(detail, key, None)
                if value:
                    enriched[key] = value
        return _track(enriched)

    def _sdk(self):
        # Artist discography, album/artist search and home/preview/play-count
        # data are not yet covered by Mornye's versioned TrackOut schema.
        with self._sdk_lock:
            if self._sdk_instance is None:
                from mornye.core.spotify_metadata import SpotifyMetadataClient as Client
                self._sdk_instance = Client()
        return self._sdk_instance

    @property
    def web_client(self):
        return self._sdk().web_client

    async def get_track_async(self, track_id):
        data = await asyncio.to_thread(runtime.request, "POST", "/resolve",
            payload={"url": f"spotify:track:{track_id}"})
        tracks = data.get("tracks") or []
        if not tracks:
            raise RuntimeError("Mornye could not resolve this track")
        with self._details_lock:
            detail = self._details.get(str(track_id))
        if detail is None:
            try:
                detail = await self._sdk().get_track_async(track_id)
                self._remember([detail])
            except Exception:
                logger.exception("Mornye track album identity could not be loaded")
        return self._with_identity(tracks[0], detail)

    async def get_album_tracks_async(self, album_id):
        data = await asyncio.to_thread(runtime.request, "POST", "/resolve",
            payload={"url": f"spotify:album:{album_id}"})
        tracks = [_track({**row, "album_id": album_id, "album_url": f"https://open.spotify.com/album/{album_id}"}) for row in data.get("tracks", [])]
        first = tracks[0] if tracks else SimpleNamespace()
        return {"name": data.get("name", ""), "cover_url": getattr(first, "cover_url", ""),
                "release_date": getattr(first, "release_date", ""), "artist": getattr(first, "album_artist", "")}, tracks

    async def get_playlist_tracks_async(self, playlist_id):
        data = await asyncio.to_thread(runtime.request, "POST", "/resolve",
            payload={"url": f"spotify:playlist:{playlist_id}"})
        tracks = [_track(row) for row in data.get("tracks", [])]
        cover = getattr(tracks[0], "cover_url", "") if tracks else ""
        return {"name": data.get("name", ""), "cover_url": cover}, tracks, cover

    async def search_tracks_async(self, query, limit=20):
        data = await asyncio.to_thread(runtime.request, "GET", "/search", params={"q": query, "limit": max(1, min(50, int(limit)))})
        return [_track(row) for row in data.get("tracks", [])]

    async def search_async(self, query, limit=20):
        failure = None
        try:
            tracks = await self.search_tracks_async(query, limit)
        except Exception as exc:
            logger.exception("Mornye REST search failed")
            failure, tracks = exc, []
        # v1 search is tracks-only. Preserve the app's album and artist search
        # with the SDK rather than silently losing those UI sections.
        try:
            extra = await self._sdk().search_async(query, limit=limit)
        except Exception as exc:
            logger.exception("Mornye album/artist search failed")
            failure, extra = exc, {}
        result = {"tracks": tracks}
        for kind in ("albums", "artists", "playlists"):
            result[kind] = extra.get(kind, [])
        if failure is not None and not any(result.values()):
            raise failure
        self._remember(extra.get("tracks", []))
        result["tracks"] = [self._with_identity(vars(track)) for track in tracks]
        return result

    def search(self, query, limit=20):
        from spotiflac_compat import run_async_blocking
        return run_async_blocking(self.search_async(query, limit))

    async def get_track_playcount_async(self, track_id):
        # TrackOut intentionally omits play counts; keep this one uncovered
        # field at the SDK boundary rather than returning a misleading zero.
        track = await self._sdk().get_track_async(track_id)
        return getattr(track, "plays", 0)

    async def get_artist_profile_async(self, artist_id):
        try:
            fetch = self._sdk().get_artist_profile_async
        except AttributeError:
            from local_metadata.artist_profile import fetch_artist_profile
            return await fetch_artist_profile(artist_id, self.web_client)
        return await fetch(artist_id)

    def __getattr__(self, name):
        # Retain only public uncovered SDK methods. No downloader hooks.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._sdk(), name)
