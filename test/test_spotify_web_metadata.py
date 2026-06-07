import json
import socket
import unittest
from unittest.mock import patch
import urllib.error

import spotify_web_metadata


class SpotifyWebMetadataTests(unittest.TestCase):
    def setUp(self):
        spotify_web_metadata._artist_about_cache.clear()

    def test_album_playcounts_extract_track_id_from_web_player_uri(self):
        response = {
            "data": {
                "albumUnion": {
                    "tracksV2": {
                        "items": [
                            {"track": {"uri": "spotify:track:track-id", "playcount": "308747990"}},
                        ],
                    },
                },
            },
        }
        with patch.object(spotify_web_metadata, "_web_player_config", return_value=(0, "web-player.js")):
            with patch.object(spotify_web_metadata, "_query_contract", return_value={"album": "hash", "secret": b"secret", "token_version": "61"}):
                with patch.object(spotify_web_metadata, "_anonymous_token", return_value="token"):
                    with patch.object(spotify_web_metadata, "_request_text", return_value=json.dumps(response)):
                        playcounts = spotify_web_metadata._load_album_playcounts("album-id")

        self.assertEqual(playcounts, {"track-id": 308747990})

    def test_request_text_retries_timeout(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"ok"

        calls = {"count": 0}

        def fake_urlopen(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise urllib.error.URLError(socket.timeout("timed out"))
            return FakeResponse()

        with patch.object(spotify_web_metadata.urllib.request, "urlopen", side_effect=fake_urlopen):
            with patch.object(spotify_web_metadata.time, "sleep", return_value=None):
                text = spotify_web_metadata._request_text("https://open.spotify.com/artist/id", retries=2)

        self.assertEqual(text, "ok")
        self.assertEqual(calls["count"], 2)

    def test_artist_about_timeout_returns_stale_cache(self):
        spotify_web_metadata._artist_about_cache["artist-id"] = (
            0,
            {"name": "Cached Artist", "followers": 10},
        )

        with patch.object(spotify_web_metadata, "_load_artist_about", side_effect=TimeoutError("timed out")):
            result = spotify_web_metadata.spotify_artist_about("artist-id")

        self.assertEqual(result["name"], "Cached Artist")


if __name__ == "__main__":
    unittest.main()
