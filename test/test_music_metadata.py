import unittest
from dataclasses import dataclass
from unittest.mock import patch

import music_metadata
from config import AppConfig


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

    def test_album_gallery_preserves_spotify_cover_before_discogs_images(self):
        spotify_album = {
            "name": "Thriller",
            "images": [{"url": "https://images.example/spotify-cover.jpg"}],
            "release_date": "1982-11-30",
            "tracks": {"items": []},
        }
        discogs = {
            "release_url": "https://www.discogs.com/release/2",
            "images": [{"url": "https://i.discogs.com/insert.jpg", "full_url": "https://i.discogs.com/insert-full.jpg"}],
        }
        with patch.object(music_metadata, "_sp", return_value=spotify_album):
            with patch.object(music_metadata, "spotify_artist_artwork", return_value=""):
                with patch.object(music_metadata, "spotify_album_playcounts", return_value={}):
                    with patch.object(music_metadata, "discogs_album_images", return_value=discogs):
                        result = music_metadata.album_tracks(
                            AppConfig(discogs_token="token"), "Michael Jackson", "Thriller", spotify_id="album-id"
                        )

        self.assertEqual(result["gallery_images"][0]["source"], "Spotify")
        self.assertEqual(result["gallery_images"][1]["source"], "Discogs")
        self.assertEqual(result["gallery_images"][1]["full_url"], "/api/image?url=https%3A%2F%2Fi.discogs.com%2Finsert-full.jpg")
        self.assertEqual(result["discogs_release_url"], "https://www.discogs.com/release/2")

    def test_album_tracks_includes_spotify_web_player_playcounts(self):
        spotify_album = {
            "name": "Thriller",
            "images": [{"url": "https://images.example/spotify-cover.jpg"}],
            "release_date": "1982-11-30",
            "tracks": {"items": [{"id": "track-id", "name": "Beat It", "duration_ms": 258000}]},
        }
        with patch.object(music_metadata, "_sp", return_value=spotify_album):
            with patch.object(music_metadata, "spotify_album_playcounts", return_value={"track-id": 1832455943}):
                with patch.object(music_metadata, "spotify_artist_artwork", return_value=""):
                    with patch.object(music_metadata, "discogs_album_images", return_value={}):
                        result = music_metadata.album_tracks(AppConfig(), "Michael Jackson", "Thriller", spotify_id="album-id")

        self.assertEqual(result["tracks"][0]["plays"], 1832455943)

    def test_identifier_enrichment_persists_cross_service_and_matching_musicbrainz_ids(self):
        track = {
            "type": "track",
            "title": "Shout",
            "artist": "Tears For Fears",
            "album": "Songs From The Big Chair (Deluxe)",
            "spotify_id": "spotify-id",
            "duration_ms": 392675,
        }
        with patch.object(music_metadata, "odesli_lookup", return_value={"deezer_id": "deezer-id", "tidal_id": "tidal-id"}):
            with patch.object(music_metadata, "deezer_track_identifiers", return_value={"isrc": "ISRC-ID"}):
                with patch.object(music_metadata, "musicbrainz_recording_identifiers", return_value={"musicbrainz_recording_id": "mbid"}):
                    enriched = music_metadata.enrich_track_identifiers(track)

        self.assertEqual(enriched["spotify_url"], "https://open.spotify.com/track/spotify-id")
        self.assertEqual(enriched["deezer_id"], "deezer-id")
        self.assertEqual(enriched["tidal_id"], "tidal-id")
        self.assertEqual(enriched["isrc"], "ISRC-ID")
        self.assertEqual(enriched["musicbrainz_recording_id"], "mbid")

    def test_identifier_enrichment_adds_spotify_id_when_missing(self):
        track = {"type": "track", "title": "Shout", "artist": "Tears For Fears"}
        spotify_result = {
            "spotify_id": "found-spotify-id",
            "spotify_url": "https://open.spotify.com/track/found-spotify-id",
            "isrc": "GBF088490125",
        }
        with patch.object(music_metadata, "spotify_search_track", return_value=spotify_result):
            with patch.object(music_metadata, "odesli_lookup", return_value={}):
                with patch.object(music_metadata, "deezer_track_identifiers", return_value={}):
                    with patch.object(music_metadata, "musicbrainz_recording_identifiers", return_value={}):
                        enriched = music_metadata.enrich_track_identifiers(track)

        self.assertEqual(enriched["spotify_id"], "found-spotify-id")
        self.assertEqual(enriched["isrc"], "GBF088490125")

    def test_deezer_identifier_lookup_accepts_matching_track_isrc(self):
        data = {
            "title": "Shout",
            "duration": 391,
            "isrc": "GBF088490125",
            "artist": {"id": 1192, "name": "Tears for Fears"},
            "album": {"id": 8980363},
        }
        music_metadata.deezer_track_identifiers.cache_clear()
        with patch.object(music_metadata, "get_json", return_value=data):
            identifiers = music_metadata.deezer_track_identifiers(
                "88845907", "Tears For Fears", "Shout", 392675
            )

        self.assertEqual(identifiers["isrc"], "GBF088490125")
        self.assertEqual(identifiers["deezer_album_id"], 8980363)

    def test_musicbrainz_identifier_match_rejects_different_track_duration(self):
        recording = {
            "id": "short-version",
            "title": "Shout",
            "length": 350266,
            "isrcs": ["ISRC-SHORT"],
            "artist-credit": [{"name": "Tears For Fears", "artist": {"id": "artist-id", "sort-name": "Tears For Fears"}}],
        }
        music_metadata.musicbrainz_recording_identifiers.cache_clear()
        with patch.object(music_metadata, "get_json", return_value={"recordings": [recording]}):
            identifiers = music_metadata.musicbrainz_recording_identifiers(
                "Tears For Fears", "Shout", "Songs From The Big Chair", 392675
            )

        self.assertEqual(identifiers, {})

    def test_musicbrainz_identifier_match_retries_album_without_edition_suffix(self):
        matching = {
            "id": "matched-version",
            "title": "Shout",
            "length": 392672,
            "isrcs": [],
            "artist-credit": [{"name": "Tears For Fears", "artist": {"id": "artist-id", "sort-name": "Tears For Fears"}}],
        }
        music_metadata.musicbrainz_recording_identifiers.cache_clear()
        with patch.object(music_metadata, "get_json", side_effect=[{"recordings": []}, {"recordings": [matching]}]) as lookup:
            identifiers = music_metadata.musicbrainz_recording_identifiers(
                "Tears For Fears", "Shout", "Songs From The Big Chair (Deluxe)", 392675
            )

        self.assertEqual(identifiers["musicbrainz_recording_id"], "matched-version")
        self.assertEqual(lookup.call_count, 2)


if __name__ == "__main__":
    unittest.main()
