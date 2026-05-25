import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import catalog
from config import AppConfig


class DiscoveryRefreshTests(unittest.TestCase):
    def test_cache_only_response_does_not_call_remote_indexer(self):
        cache = {
            "top_tracks": [{"type": "track", "title": "Cached", "artist": "Artist", "album": "Album"}],
            "top_artists": [],
            "top_albums": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "discovery_cache.json"
            cache_path.write_text(json.dumps(cache), "utf-8")
            config = AppConfig(music_dir=Path(tmpdir) / "music")
            with patch.object(catalog, "DISCOVERY_CACHE_PATH", cache_path), patch(
                "music_metadata.SpotifyIndexer"
            ) as indexer_cls:
                result = catalog.discover_catalog(config, refresh_global=False)

        indexer_cls.assert_not_called()
        self.assertEqual(result["top_tracks"][0]["title"], "Cached")

    def test_fresh_response_replaces_cached_ranking_and_saves_it(self):
        cache = {
            "top_tracks": [{"type": "track", "title": "Old", "artist": "Artist", "album": "Album"}],
            "top_artists": [],
            "top_albums": [],
        }
        fresh = [{"type": "track", "title": "New Number One", "artist": "Artist", "album": "Album"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "discovery_cache.json"
            cache_path.write_text(json.dumps(cache), "utf-8")
            config = AppConfig(music_dir=Path(tmpdir) / "music")
            with patch.object(catalog, "DISCOVERY_CACHE_PATH", cache_path), patch(
                "music_metadata.SpotifyIndexer"
            ) as indexer_cls:
                indexer_cls.return_value.top_tracks.return_value = fresh
                indexer_cls.return_value.top_artists.return_value = []
                indexer_cls.return_value.new_releases.return_value = []
                result = catalog.discover_catalog(config, refresh_global=True)

            saved = json.loads(cache_path.read_text("utf-8"))

        self.assertEqual(result["top_tracks"][0]["title"], "New Number One")
        self.assertEqual(saved["top_tracks"][0]["title"], "New Number One")

    def test_saved_artist_identity_is_applied_to_cached_top_track_artist(self):
        cache = {
            "top_tracks": [{"type": "track", "title": "Billie Jean", "artist": "Michael Jackson", "album": "Thriller"}],
            "top_artists": [],
            "top_albums": [],
            "artist_identities": {"michael jackson": {"spotify_id": "artist-id", "artwork_url": "/cover"}},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "discovery_cache.json"
            cache_path.write_text(json.dumps(cache), "utf-8")
            with patch.object(catalog, "DISCOVERY_CACHE_PATH", cache_path):
                result = catalog.discover_catalog(SimpleNamespace(music_dir=Path(tmpdir) / "music"), refresh_global=False)

        self.assertEqual(result["artists"][0]["spotify_id"], "artist-id")
        self.assertEqual(result["artists"][0]["artwork_url"], "/cover")


if __name__ == "__main__":
    unittest.main()
