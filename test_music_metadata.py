import unittest
from dataclasses import dataclass
from unittest.mock import patch

import music_metadata


@dataclass
class FakeTrack:
    id: str = "track-id"
    title: str = "Beat It"
    artists: str = "Michael Jackson"
    album: str = "Thriller"
    cover_url: str = "https://images.example/cover.jpg"
    external_url: str = "https://open.spotify.com/track/track-id"
    isrc: str = "USSM19902990"
    duration_ms: int = 258000
    plays: str = "950000"


class FakePublicSpotifyClient:
    def search(self, query, limit=20):
        return {
            "tracks": [FakeTrack()],
            "albums": [{
                "id": "album-id",
                "name": "Thriller",
                "artists": "Michael Jackson",
                "cover_url": "https://images.example/album.jpg",
            }],
            "artists": [{
                "id": "artist-id",
                "name": "Michael Jackson",
                "cover_url": "https://images.example/artist.jpg",
            }],
        }

    def get_playlist_tracks(self, playlist_id):
        return {}, [FakeTrack()], ""

    def get_artist_profile(self, artist_id):
        return {"profile": {"name": "Michael Jackson"}}

    def search_tracks(self, query, limit=20):
        return [FakeTrack()]


class FakeRawSearchClient(FakePublicSpotifyClient):
    def __init__(self):
        self.web_client = self

    def search(self, query, limit=20):
        return {"tracks": [FakeTrack()], "albums": [], "artists": []}

    def _search_payload(self, query, limit):
        return {}

    def query(self, payload):
        return {"data": {"searchV2": {
            "albumsV2": {"items": [{"data": {
                "uri": "spotify:album:album-id", "name": "Thriller",
                "artists": {"items": [{"profile": {"name": "Michael Jackson"}}]},
                "coverArt": {"sources": [{"url": "https://images.example/album.jpg", "width": 640}]},
            }}]},
            "artists": {"items": [{"data": {
                "uri": "spotify:artist:artist-id", "profile": {"name": "Michael Jackson"},
                "visualIdentity": {"squareCoverImage": {"sources": [{"url": "https://images.example/artist.jpg", "width": 640}]}},
            }}, {"data": {
                "uri": "spotify:artist:no-cover-id", "profile": {"name": "No Cover Artist"},
                "visualIdentity": None,
            }}]},
        }}}


class FakeDiscographyClient(FakePublicSpotifyClient):
    def __init__(self):
        self.web_client = self

    def get_artist_discography(self, artist_id):
        return [
            {"releases": {"items": [{
                "uri": "spotify:album:album-one",
                "name": "First Album",
                "type": "ALBUM",
                "date": {"isoString": "1973-03-01"},
                "coverArt": {"sources": [{"url": "https://images.example/first.jpg", "width": 640}]},
            }]}},
            {"releases": {"items": [{
                "uri": "spotify:album:album-two",
                "name": "Second Album",
                "type": "ALBUM",
                "date": {"isoString": "1975-09-12"},
                "coverArt": {"sources": [{"url": "https://images.example/second.jpg", "width": 640}]},
            }]}},
            {"releases": {"items": [{
                "uri": "spotify:album:album-one",
                "name": "Duplicate Edition",
                "type": "ALBUM",
            }]}},
            {"releases": {"items": [{
                "uri": "spotify:album:guest-release",
                "name": "Guest Release",
                "type": "APPEARS_ON",
            }]}},
        ]


class SpotifyPublicClientCompatibilityTests(unittest.TestCase):
    def setUp(self):
        music_metadata.spotify_search_track.cache_clear()
        music_metadata.spotify_artist_artwork.cache_clear()
        music_metadata.spotify_artist_id.cache_clear()
        music_metadata.spotify_artist_top_tracks.cache_clear()

    def test_public_client_search_is_exposed_to_search_and_artwork_helpers(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakePublicSpotifyClient()):
            results = music_metadata.SpotifyIndexer().search("Michael Jackson")
            artwork = music_metadata.spotify_artist_artwork("Michael Jackson")

        self.assertEqual(results[0]["title"], "Beat It")
        self.assertEqual(results[0]["artwork_url"], "/api/image?url=https%3A%2F%2Fimages.example%2Fcover.jpg")
        self.assertEqual(artwork, "/api/image?url=https%3A%2F%2Fimages.example%2Fartist.jpg")

    def test_spotify_proxy_repairs_prefixed_full_image_ids(self):
        malformed = "https://i.scdn.co/image/ab67616d000082c1ab6742d3000052b7e15ca24c1b0ea8e2bf439b27"

        artwork = music_metadata.proxy_artwork_url(malformed)

        self.assertEqual(artwork, "/api/image?url=https%3A%2F%2Fi.scdn.co%2Fimage%2Fab6742d3000052b7e15ca24c1b0ea8e2bf439b27")

    def test_public_client_playlist_supports_top_tracks(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakePublicSpotifyClient()):
            tracks = music_metadata.SpotifyIndexer().top_tracks(1)
            albums = music_metadata.SpotifyIndexer().new_releases(1)

        self.assertEqual(tracks[0]["title"], "Beat It")
        self.assertTrue(tracks[0]["artwork_url"])
        self.assertEqual(albums[0]["title"], "Thriller")

    def test_new_raw_search_shapes_restore_artist_and_album_categories(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakeRawSearchClient()):
            results = music_metadata.SpotifyIndexer().search("Michael Jackson")

        self.assertEqual([item["type"] for item in results], ["track", "album", "artist", "artist"])
        self.assertEqual(results[1]["title"], "Thriller")
        self.assertEqual(results[2]["artist"], "Michael Jackson")
        self.assertEqual(results[3]["artist"], "No Cover Artist")
        self.assertEqual(results[3]["artwork_url"], "")

    def test_public_client_artist_page_can_load_tracks(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakePublicSpotifyClient()):
            tracks = music_metadata.spotify_artist_top_tracks("Michael Jackson", artist_id="artist-id")

        self.assertEqual(tracks[0]["title"], "Beat It")

    def test_artist_page_fills_missing_track_art_from_album(self):
        class MissingArtworkClient(FakePublicSpotifyClient):
            def search_tracks(self, query, limit=20):
                return [FakeTrack(cover_url="")]

        with patch.object(music_metadata, "_spotify_client_cache", MissingArtworkClient()):
            with patch.object(music_metadata, "spotify_album_artwork", return_value="/api/image?url=fallback") as artwork:
                tracks = music_metadata.spotify_artist_top_tracks("Michael Jackson", artist_id="artist-id")

        self.assertEqual(tracks[0]["artwork_url"], "/api/image?url=fallback")
        artwork.assert_called_once_with("Michael Jackson", "Thriller")

    def test_artist_page_resolves_invalid_card_id_and_uses_discography(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakeDiscographyClient()):
            parts = list(music_metadata.artist_page(None, "Michael Jackson", artist_id="track-id"))

        albums = parts[-1]["albums"]
        self.assertEqual(parts[0]["artist_id"], "artist-id")
        self.assertEqual(len(parts[1]["tracks"]), 1)
        self.assertEqual([item["title"] for item in albums], ["First Album", "Second Album"])
        self.assertEqual(albums[0]["spotify_id"], "album-one")
        self.assertTrue(albums[0]["artwork_url"])


if __name__ == "__main__":
    unittest.main()
