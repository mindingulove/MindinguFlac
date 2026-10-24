"""Real upstream REST contract plus the narrowly retained metadata fallback."""
import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests

import backend_mornye
import mornye_bridge
import mornye_runtime
from local_metadata import lyrics


class MornyeRoutingTests(unittest.TestCase):
    def test_track_results_survive_uncovered_category_failure_and_api_limit_is_valid(self):
        client = mornye_bridge.SpotifyMetadataClient()
        client._sdk_instance = SimpleNamespace(search_async=AsyncMock(side_effect=RuntimeError("category unavailable")))
        with patch.object(mornye_runtime, "request", return_value={"tracks": [{"id": "123", "title": "Song"}]}) as request:
            result = asyncio.run(client.search_async("pink floyd", limit=100))
        self.assertEqual(result["tracks"][0].id, "123")
        self.assertEqual(result["artists"], [])
        self.assertEqual(request.call_args.kwargs["params"]["limit"], 50)

    def test_existing_extensions_are_copied_once_without_overwriting(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            old = home / ".spotiflac/extensions/tidal-web"
            old.mkdir(parents=True)
            (old / "manifest.json").write_text(json.dumps({"name": "tidal-web"}))
            (old / "index.js").write_text("existing installed provider")
            root = Path(tmp) / "app"
            root.mkdir()
            with patch.object(Path, "home", return_value=home):
                mornye_runtime._adopt_installed_extensions(root)
                destination = root / "extensions/tidal-web/index.js"
                self.assertEqual(destination.read_text(), "existing installed provider")
                destination.write_text("newer app copy")
                mornye_runtime._adopt_installed_extensions(root)
                self.assertEqual(destination.read_text(), "newer app copy")
                self.assertEqual((old / "index.js").read_text(), "existing installed provider")

    def test_existing_artist_endpoint_prefers_mornye_profile_fields(self):
        import music_metadata
        client = SimpleNamespace(get_artist_profile_async=AsyncMock(return_value={
            "profile": {"name": "Duran Duran", "biography": "Mornye biography"},
            "stats": {"listeners": 1234}, "avatar": "https://artist-image",
        }))
        with patch.object(music_metadata, "_get_spotify_client", return_value=client):
            result = music_metadata._load_artist_about("artist")
        self.assertEqual(result["biography"], "Mornye biography")
        self.assertEqual(result["monthly_listeners"], 1234)
        client.get_artist_profile_async.assert_awaited_once_with("artist")

    def test_artist_uses_mornye_when_function_exists(self):
        client = mornye_bridge.SpotifyMetadataClient()
        client._sdk_instance = SimpleNamespace(get_artist_profile_async=AsyncMock(return_value={"id": "artist"}))
        with patch("local_metadata.artist_profile.fetch_artist_profile", new_callable=AsyncMock) as fallback:
            self.assertEqual(asyncio.run(client.get_artist_profile_async("artist")), {"id": "artist"})
        client._sdk_instance.get_artist_profile_async.assert_awaited_once_with("artist")
        fallback.assert_not_called()

    def test_missing_artist_function_uses_retained_profile_parser(self):
        client = mornye_bridge.SpotifyMetadataClient()
        query = Mock(return_value={"data": {"artistUnion": {"profile": {"name": "Duran Duran", "biography": {"text": "<b>Band</b>"}},
                     "stats": {"monthlyListeners": 123}, "visuals": {"avatarImage": {"sources": [{"url": "https://image"}]}}}}})
        client._sdk_instance = SimpleNamespace(web_client=SimpleNamespace(query=query))
        result = asyncio.run(client.get_artist_profile_async("artist"))
        self.assertEqual(result["profile"]["name"], "Duran Duran")
        self.assertEqual(result["profile"]["biography"], "Band")
        self.assertEqual(result["stats"]["listeners"], 123)
        self.assertEqual(result["avatar"], "https://image")

    def test_lyrics_use_mornye_when_function_exists(self):
        with patch("mornye.core.lyrics.fetch_lyrics_async", new_callable=AsyncMock, return_value=("[00:01]Words", "lrclib")) as upstream, \
                patch.object(lyrics, "_fetch_lyrics_async", new_callable=AsyncMock) as fallback:
            result = asyncio.run(lyrics.fetch_lyrics_async(track_name="Song", artist_name="Artist"))
        self.assertEqual(result, ("[00:01]Words", "lrclib"))
        upstream.assert_awaited_once_with(track_name="Song", artist_name="Artist")
        fallback.assert_not_called()

    def test_missing_lyrics_function_uses_local_port(self):
        with patch("mornye.core.lyrics.fetch_lyrics_async", None), \
                patch.object(lyrics, "_fetch_lyrics_async", new_callable=AsyncMock, return_value=("Words", "lrclib")) as fallback:
            self.assertEqual(asyncio.run(lyrics.fetch_lyrics_async(track_name="Song", artist_name="Artist")), ("Words", "lrclib"))
        fallback.assert_awaited_once()

    def test_track_metadata_uses_resolve_api_and_preserves_isrc(self):
        with patch.object(mornye_runtime, "request", return_value={"tracks": [{"id": "123", "title": "Song", "isrc": "ISRC123"}]}) as request:
            result = asyncio.run(mornye_bridge.SpotifyMetadataClient().get_track_async("123"))
        self.assertEqual(result.isrc, "ISRC123")
        request.assert_called_once_with("POST", "/resolve", payload={"url": "spotify:track:123"})

    def test_provider_job_uses_rest_output_directory_and_polls(self):
        manager = SimpleNamespace(_lock=threading.Lock(), _cancel_flags=set(), _append_cache_event=Mock())
        job = {"id": "local", "service": "tidal", "quality": "LOSSLESS"}
        responses = [{"providers": [{"provider": "ext:qobuz-py", "installed": True}, {"provider": "ext:tidal-py", "installed": True}]},
                     {"id": "remote"}, {"status": "done"}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(backend_mornye, "request", side_effect=responses) as request:
            backend_mornye.run("spotify:track:123", Path(tmp), job, manager)
            payload = request.call_args_list[1].kwargs["payload"]
            self.assertEqual(payload["output_dir"], str(Path(tmp).resolve()))
            self.assertEqual(payload["services"][0], "ext:tidal-py")
        self.assertEqual(job["mornye_job_id"], "remote")

    def test_cancel_is_forwarded_to_upstream_job(self):
        manager = SimpleNamespace(_lock=threading.Lock(), _cancel_flags={"local"}, _append_cache_event=Mock())
        job = {"id": "local", "service": "tidal"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(backend_mornye, "request", side_effect=[
            {"providers": [{"provider": "ext:tidal-py", "installed": True}]}, {"id": "remote"}, {"status": "cancelled"},
        ]) as request:
            backend_mornye.run("spotify:track:123", Path(tmp), job, manager)
        self.assertEqual(request.call_args_list[-1].args, ("POST", "/downloads/remote/cancel"))


class EmbeddedMornyeContractTests(unittest.TestCase):
    def test_api_starts_with_native_file_logging_without_terminal_methods(self):
        class FileWriter:
            def write(self, text):
                pass
            def flush(self):
                pass
        mornye_runtime.stop()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MINDINGUFLAC_DATA_DIR": tmp}), \
                patch("sys.stdout", FileWriter()), patch("sys.stderr", FileWriter()):
            try:
                self.assertEqual(mornye_runtime.request("GET", "/info")["name"], "Mornye")
            finally:
                mornye_runtime.stop()

    def test_real_api_health_auth_resolve_shutdown_and_restart(self):
        from mornye.core.spotify_metadata import SpotifyMetadataClient
        track = SimpleNamespace(id="123", title="Song", artists="Artist", album="Album", isrc="ISRC123", duration_ms=120000)
        mornye_runtime.stop()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MINDINGUFLAC_DATA_DIR": tmp}), \
                patch.object(SpotifyMetadataClient, "get_url_async", new_callable=AsyncMock, return_value=("Song", [track], "", {})):
            try:
                info = mornye_runtime.request("GET", "/info")
                self.assertEqual(info["api_version"], "v1")
                self.assertTrue(info["authenticated"])
                base = mornye_runtime.start()
                self.assertTrue(base.startswith("http://127.0.0.1:"))
                self.assertEqual(requests.get(base + "/info", timeout=2).status_code, 401)
                result = mornye_runtime.request("POST", "/resolve", payload={"url": "spotify:track:123"})
                self.assertEqual(result["tracks"][0]["isrc"], "ISRC123")
                self.assertEqual(result["tracks"][0]["duration_ms"], 120000)
                mornye_runtime.stop()
                self.assertIsNone(mornye_runtime._server)
                self.assertEqual(mornye_runtime.request("GET", "/info")["name"], "Mornye")
            finally:
                mornye_runtime.stop()
