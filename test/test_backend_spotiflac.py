import asyncio
import unittest
from pathlib import Path

import backend_spotiflac


class SpotiFLACProviderSelectionTests(unittest.TestCase):
    def test_amazon_setting_is_first_lossless_provider(self):
        self.assertEqual(
            backend_spotiflac.spotiflac_fallback_services("amazon", "LOSSLESS"),
            ["amazon", "qobuz", "deezer", "apple", "tidal"],
        )

    def test_tidal_lossless_fallback_includes_apple_before_returning_to_tidal(self):
        self.assertEqual(
            backend_spotiflac.spotiflac_fallback_services("tidal", "LOSSLESS"),
            ["tidal", "qobuz", "deezer", "amazon", "apple"],
        )
        self.assertEqual(backend_spotiflac.spotiflac_provider_quality("LOSSLESS", "apple"), "ALAC")

    def test_download_options_do_not_enable_internal_provider_fallback(self):
        options = backend_spotiflac.spotiflac_download_options(
            Path("/tmp/cache"),
            {
                "title": "Shout",
                "artist": "Tears For Fears",
                "resolved_url": "https://open.spotify.com/track/spotify-id",
                "quality": "LOSSLESS",
            },
            1,
            ["amazon", "qobuz", "deezer", "apple", "tidal"],
        )

        self.assertEqual(options["services"][0], "amazon")
        self.assertFalse(options["allow_fallback"])


if __name__ == "__main__":
    unittest.main()
