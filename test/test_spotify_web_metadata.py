import json
import unittest
from unittest.mock import patch

import spotify_web_metadata


class SpotifyWebMetadataTests(unittest.TestCase):
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
            with patch.object(spotify_web_metadata, "_query_contract", return_value=("hash", b"secret", "61")):
                with patch.object(spotify_web_metadata, "_anonymous_token", return_value="token"):
                    with patch.object(spotify_web_metadata, "_request_text", return_value=json.dumps(response)):
                        playcounts = spotify_web_metadata._load_album_playcounts("album-id")

        self.assertEqual(playcounts, {"track-id": 308747990})


if __name__ == "__main__":
    unittest.main()
