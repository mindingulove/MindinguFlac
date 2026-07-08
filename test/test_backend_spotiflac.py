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

    def test_spotiflac_clients_request_identity_encoding(self):
        client = backend_spotiflac._get_sf_client(None)
        async_client = backend_spotiflac._get_sf_async_client(None)

        self.assertEqual(client.headers.get("accept-encoding"), "identity")
        self.assertEqual(async_client.headers.get("accept-encoding"), "identity")

    def test_detects_provider_decompression_error(self):
        exc = RuntimeError("Error -3 while decompressing data: incorrect header check")

        self.assertTrue(backend_spotiflac._is_decompression_error(exc))


if __name__ == "__main__":
    unittest.main()
