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


class SpotifyPublicClientCompatibilityTests(unittest.TestCase):
    def setUp(self):
        music_metadata.spotify_search_track.cache_clear()
        music_metadata.spotify_artist_artwork.cache_clear()
        music_metadata.spotify_artist_top_tracks.cache_clear()

    def test_public_client_search_is_exposed_to_search_and_artwork_helpers(self):
        with patch.object(music_metadata, "_spotify_client_cache", FakePublicSpotifyClient()):
            results = music_metadata.SpotifyIndexer().search("Michael Jackson")
            artwork = music_metadata.spotify_artist_artwork("Michael Jackson")

        self.assertEqual(results[0]["title"], "Beat It")
        self.assertEqual(results[0]["artwork_url"], "/api/image?url=https%3A%2F%2Fimages.example%2Fcover.jpg")
        self.assertEqual(artwork, "/api/image?url=https%3A%2F%2Fimages.example%2Fartist.jpg")

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


if __name__ == "__main__":
    unittest.main()
