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


OPEN_SPOTIFY_ARTIST_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Michael Jackson | Spotify</title>
  <meta property="og:image" content="https://i.scdn.co/image/ab6761610000e5eb997cc9a4aec335d46c9481fd"/>
  <meta property="og:description" content="Artist · 104.7M monthly listeners."/>
</head>
<body>
  <div data-testid="artist-entity-view">
    <div data-testid="monthly-listeners-label">104,725,274 monthly listeners</div>
  </div>
  <div>
    <h2>About</h2>
    <div>104,725,274 monthly listeners</div>
    <div data-testid="expandable-description">
      <div>
        <div>
          <span>Michael Jackson is one of the most influential artists in history.</span>
        </div>
      </div>
    </div>
  </div>
  <div>
    <p>48,876,033</p>
    <p>Followers</p>
  </div>
  <div>
    <h2>Fans also like</h2>
    <div data-testid="carousel-mwp">
      <div data-testid="card-mwp">
        <a href="/artist/0du5cEVh5yTK9QJze8zA0C">
          <img src="https://i.scdn.co/image/bruno"/>
          <span>Bruno Mars</span>
        </a>
      </div>
      <div data-testid="card-mwp">
        <a href="/artist/2iE18Oxc8YSumAU232n4rW">
          <img src="https://i.scdn.co/image/jackson5"/>
          <span>The Jackson 5</span>
        </a>
      </div>
    </div>
  </div>
</body>
</html>
"""

OPEN_SPOTIFY_ARTIST_TOP_TRACKS_HTML = """
<!DOCTYPE html>
<html>
<body>
  <span>Popular</span>
  <div data-testid="track-row" role="group" aria-labelledby="listrow-title-track-spotify:track:7J1uxwnxfQLu4APicE5Rnj-0" aria-label="Billie Jean">
    <img src="https://i.scdn.co/image/ab67616d0000485132a7d87248d1b75463483df5"/>
    <p id="listrow-title-track-spotify:track:7J1uxwnxfQLu4APicE5Rnj-0"><span class="e-10451-line-clamp">Billie Jean</span></p>
    <div><span>3,040,144,939</span></div>
  </div>
  <div data-testid="track-row" role="group" aria-labelledby="listrow-title-track-spotify:track:3BovdzfaX4jb5KFQwoPfAw-1" aria-label="Beat It">
    <img src="https://i.scdn.co/image/ab67616d0000485132a7d87248d1b75463483df5"/>
    <p id="listrow-title-track-spotify:track:3BovdzfaX4jb5KFQwoPfAw-1"><span class="e-10451-line-clamp">Beat It</span></p>
    <div><span>1,996,981,600</span></div>
  </div>
</body>
</html>
"""


class SpotifyPublicClientCompatibilityTests(unittest.TestCase):
    def setUp(self):
        if hasattr(music_metadata, "clear_search_music_cache"):
            music_metadata.clear_search_music_cache()
        if hasattr(music_metadata, "clear_spotify_artist_caches"):
            music_metadata.clear_spotify_artist_caches()
        music_metadata.spotify_search_track.cache_clear()
        if hasattr(music_metadata.spotify_artist_artwork, "cache_clear"):
            music_metadata.spotify_artist_artwork.cache_clear()

    def test_search_music_does_not_cache_empty_results(self):
        class EmptyIndexer:
            def search(self, query):
                return []

        class ResultIndexer:
            def search(self, query):
                return [{"type": "track", "title": "Beat It", "artist": "Michael Jackson", "spotify_id": "track-id"}]

        calls = []

        def fake_build_music_indexers(_config):
            calls.append(1)
            return [EmptyIndexer()] if len(calls) == 1 else [ResultIndexer()]

        with patch.object(music_metadata, "build_music_indexers", side_effect=fake_build_music_indexers):
            first = music_metadata.search_music(AppConfig(), "Michael Jackson")
            second = music_metadata.search_music(AppConfig(), "Michael Jackson")

        self.assertEqual(first, [])
        self.assertEqual(second[0]["title"], "Beat It")

    def test_spotify_indexer_retries_after_transient_client_failure(self):
        class BrokenClient:
            def __init__(self):
                self.web_client = self

            def _search_payload(self, query, limit):
                return {}

            def query(self, payload):
                raise RuntimeError("stale session")

        class WorkingClient(BrokenClient):
            def query(self, payload):
                return {"data": {"searchV2": {"tracksV2": {"items": [{
                    "item": {"data": {
                        "id": "track-id",
                        "name": "Beat It",
                        "albumOfTrack": {"name": "Thriller", "coverArt": {}},
                        "artists": {"items": [{"profile": {"name": "Michael Jackson"}}]},
                    }}
                }]}}}}

        with patch.object(music_metadata, "_get_spotify_client", side_effect=[BrokenClient(), WorkingClient()]):
            results = music_metadata.SpotifyIndexer().search("Michael Jackson")

        self.assertEqual(results[0]["title"], "Beat It")

    def test_spotify_artist_top_tracks_retries_after_transient_client_failure(self):
        class BrokenClient(FakePublicSpotifyClient):
            def search_tracks(self, query, limit=20):
                raise RuntimeError("stale session")

        class WorkingClient(FakePublicSpotifyClient):
            pass

        with patch.object(music_metadata, "_get_spotify_client", side_effect=[BrokenClient(), WorkingClient()]):
            tracks = music_metadata.spotify_artist_top_tracks("Michael Jackson", artist_id="artist-id")

        self.assertEqual(tracks[0]["title"], "Beat It")

    def test_spotify_artist_top_tracks_falls_back_to_search_tracks_when_top_tracks_empty(self):
        class EmptyTopTracksClient(FakePublicSpotifyClient):
            def __init__(self):
                self.web_client = self

            def _get(self, endpoint, params=None):
                return {}

            def search_tracks(self, query, limit=20):
                return [FakeTrack()]

        with patch.object(music_metadata, "_get_spotify_client", return_value=EmptyTopTracksClient()):
            tracks = music_metadata.spotify_artist_top_tracks("Duran Duran", artist_id="3DMO3orHyVwheG0Adbg8Ox")

        self.assertEqual(tracks[0]["title"], "Beat It")

    def test_spotify_artist_top_tracks_supports_async_only_client(self):
        class AsyncOnlyClient:
            def __init__(self):
                self.web_client = self

            def query(self, payload):
                return {"data": {"artistUnion": {"discography": {"topTracks": {"items": []}}}}}

            async def get_artist_profile_async(self, artist_id):
                return {"profile": {"name": "Michael Jackson"}}

            async def search_tracks_async(self, query, limit=20):
                return [FakeTrack()]

        with patch.object(music_metadata, "_get_spotify_client", return_value=AsyncOnlyClient()):
            tracks = music_metadata.spotify_artist_top_tracks("Michael Jackson", artist_id="artist-id")

        self.assertEqual(tracks[0]["title"], "Beat It")

    def test_spotify_artist_top_tracks_filters_fallback_results_to_requested_artist(self):
        class MixedFallbackClient(FakePublicSpotifyClient):
            def __init__(self):
                self.web_client = self

            def query(self, payload):
                return {"data": {"artistUnion": {"discography": {"topTracks": {"items": []}}}}}

            def get_artist_profile(self, artist_id):
                return {"profile": {"name": "Michael Jackson"}}

            def search_tracks(self, query, limit=20):
                return [
                    FakeTrack(title="Wrong Song", artists="Someone Else", id="wrong-track"),
                    FakeTrack(title="Beat It", artists="Michael Jackson", id="beat-it"),
                ]

        with patch.object(music_metadata, "_get_spotify_client", return_value=MixedFallbackClient()):
            tracks = music_metadata.spotify_artist_top_tracks("Michael Jackson", artist_id="artist-id")

        self.assertEqual([track["title"] for track in tracks], ["Beat It"])

    def test_spotify_artist_top_tracks_uses_artist_overview_before_search_fallback(self):
        class ArtistOverviewClient(FakePublicSpotifyClient):
            def __init__(self):
                self.web_client = self

            def query(self, payload):
                return {"data": {"artistUnion": {"discography": {"topTracks": {"items": [{
                    "track": {
                        "id": "ordinary-world-id",
                        "name": "Ordinary World",
                        "uri": "spotify:track:ordinary-world-id",
                        "artists": {"items": [{"profile": {"name": "Duran Duran"}}]},
                        "albumOfTrack": {"coverArt": {"sources": [{"url": "https://images.example/rio.jpg", "width": 640}]}},
                        "duration": {"totalMilliseconds": 340200},
                        "playcount": "570788822",
                    }
                }]}}}}}

            def search_tracks(self, query, limit=20):
                raise AssertionError("artist top tracks should come from the artist ID overview first")

        with patch.object(music_metadata, "_get_spotify_client", return_value=ArtistOverviewClient()):
            tracks = music_metadata.spotify_artist_top_tracks("Duran Duran", artist_id="artist-id")

        self.assertEqual(tracks[0]["title"], "Ordinary World")
        self.assertEqual(tracks[0]["spotify_id"], "ordinary-world-id")
        self.assertEqual(tracks[0]["plays"], 570780000)

    def test_spotify_artist_id_uses_cached_discovery_identity(self):
        with patch("catalog.load_discovery_cache", return_value={
            "artist_identities": {
                "duran duran": {"spotify_id": "3DMO3orHyVwheG0Adbg8Ox", "artwork_url": "/api/image?url=https%3A%2F%2Fi.scdn.co%2Fimage%2Fab6761610000e5eb899b5cf79062868a01429bc7"},
            }
        }):
            artist_id = music_metadata.spotify_artist_id("Duran Duran")

        self.assertEqual(artist_id, "3DMO3orHyVwheG0Adbg8Ox")

    def test_artist_page_retries_album_discography_after_transient_client_failure(self):
        class BrokenClient(FakePublicSpotifyClient):
            def __init__(self):
                self.web_client = self

            def get_artist_discography(self, artist_id):
                raise RuntimeError("stale session")

        class WorkingClient(FakeDiscographyClient):
            pass

        with patch.object(music_metadata, "spotify_artist_artwork", return_value=""):
            with patch.object(music_metadata, "spotify_artist_top_tracks", return_value=[{"title": "Beat It"}]):
                with patch.object(music_metadata, "_get_spotify_client", side_effect=[BrokenClient(), WorkingClient()]):
                    parts = list(music_metadata.artist_page(AppConfig(), "Michael Jackson", artist_id="artist-id"))

        self.assertEqual(parts[1]["tracks"][0]["title"], "Beat It")
        self.assertEqual([item["title"] for item in parts[-2]["albums"]], ["First Album", "Second Album"])

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

    def test_artist_about_returns_wikipedia_bio_without_spotify_stats(self):
        with patch.object(music_metadata, "spotify_artist_about", return_value={}):
            with patch.object(music_metadata, "spotify_artist_id", return_value="artist-id"):
                with patch.object(music_metadata, "spotify_artist_artwork", return_value="/api/image?url=spotify-artist"):
                    with patch.object(music_metadata, "fetch_wikipedia_about", return_value={
                        "text": "Michael Jackson was an American singer.",
                        "html": "<p>Michael Jackson was an American singer.</p>",
                        "image": "https://images.example/wiki.jpg",
                    }):
                        about = music_metadata.artist_about("", "Michael Jackson")

        self.assertEqual(about["bio_source"], "Wikipedia")
        self.assertEqual(about["biography"], "Michael Jackson was an American singer.")
        self.assertEqual(about["hero_image"], "/api/image?url=spotify-artist")
        self.assertEqual(about["monthly_listeners"], 0)
        self.assertEqual(about["followers"], 0)

    def test_artist_about_normalizes_missing_fields(self):
        with patch.object(music_metadata, "spotify_artist_about", return_value={"avatar": "/api/image?url=artist"}):
            about = music_metadata.artist_about("artist-id", "Michael Jackson")

        self.assertEqual(about["hero_image"], "/api/image?url=artist")
        self.assertEqual(about["gallery"], [])
        self.assertEqual(about["top_cities"], [])
        self.assertEqual(about["related_artists"], [])
        self.assertEqual(about["monthly_listeners"], 0)
        self.assertEqual(about["followers"], 0)

    def test_extract_open_spotify_artist_about_parses_stats_bio_and_related_artists(self):
        about = music_metadata._extract_open_spotify_artist_about(OPEN_SPOTIFY_ARTIST_HTML, "artist-id")

        self.assertEqual(about["name"], "Michael Jackson")
        self.assertEqual(about["monthly_listeners"], 104725274)
        self.assertEqual(about["followers"], 48876033)
        self.assertIn("most influential artists in history", about["biography"])
        self.assertEqual(about["avatar"], "/api/image?url=https%3A%2F%2Fi.scdn.co%2Fimage%2Fab6761610000e5eb997cc9a4aec335d46c9481fd")
        self.assertEqual([item["name"] for item in about["related_artists"]], ["Bruno Mars", "The Jackson 5"])

    def test_spotify_artist_about_falls_back_to_open_spotify_artist_page(self):
        with patch.object(music_metadata, "_load_artist_about", return_value={}):
            with patch.object(music_metadata, "_load_artist_about_from_open_page", return_value={
                "name": "Michael Jackson",
                "monthly_listeners": 104725274,
                "followers": 48876033,
                "biography": "Public Spotify bio",
                "bio_source": "Spotify",
                "stats_source": "Spotify",
                "avatar": "/api/image?url=spotify-image",
                "hero_image": "/api/image?url=spotify-image",
                "related_artists": [{"name": "Bruno Mars", "id": "0du5cEVh5yTK9QJze8zA0C", "image": "https://i.scdn.co/image/bruno"}],
            }):
                music_metadata._artist_about_cache.clear()
                about = music_metadata.spotify_artist_about("artist-id")

        self.assertEqual(about["monthly_listeners"], 104725274)
        self.assertEqual(about["followers"], 48876033)
        self.assertEqual(about["biography"], "Public Spotify bio")
        self.assertEqual(about["related_artists"][0]["name"], "Bruno Mars")

    def test_extract_open_spotify_artist_top_tracks_parses_track_ids_and_plays(self):
        tracks = music_metadata._extract_open_spotify_artist_top_tracks(
            OPEN_SPOTIFY_ARTIST_TOP_TRACKS_HTML,
            "Michael Jackson",
            limit=5,
        )

        self.assertEqual([track["id"] for track in tracks], ["7J1uxwnxfQLu4APicE5Rnj", "3BovdzfaX4jb5KFQwoPfAw"])
        self.assertEqual(tracks[0]["name"], "Billie Jean")
        self.assertEqual(tracks[0]["popularity"] * 10000, 3040140000)

    def test_spotify_artist_top_tracks_open_page_fallback_preserves_spotiflac_ids_and_isrc(self):
        with patch.object(music_metadata, "_spotify_search_results", return_value={
            "tracks": [FakeTrack(
                id="3BovdzfaX4jb5KFQwoPfAw",
                title="Beat It",
                artists="Michael Jackson",
                album="Thriller",
                cover_url="https://images.example/thriller.jpg",
                external_url="https://open.spotify.com/track/3BovdzfaX4jb5KFQwoPfAw",
                isrc="USSM19902991",
                duration_ms=258000,
                plays="950000",
            )],
            "albums": [],
            "artists": [],
            "playlists": [],
        }):
            with patch.object(music_metadata, "_get_spotify_client", return_value=None):
                with patch.object(music_metadata, "_load_artist_top_tracks_from_open_page", return_value=[{
                    "id": "3BovdzfaX4jb5KFQwoPfAw",
                    "name": "Beat It",
                    "artists": [{"name": "Michael Jackson"}],
                    "album": {"name": "", "images": []},
                    "duration_ms": 0,
                    "external_urls": {"spotify": "https://open.spotify.com/track/3BovdzfaX4jb5KFQwoPfAw"},
                    "external_ids": {"isrc": ""},
                    "popularity": 199698,
                }]):
                    tracks = music_metadata.spotify_artist_top_tracks(
                        "Michael Jackson",
                        artist_id="artist-id",
                        limit=5,
                    )

        self.assertEqual(tracks[0]["title"], "Beat It")
        self.assertEqual(tracks[0]["album"], "Thriller")
        self.assertEqual(tracks[0]["spotify_id"], "3BovdzfaX4jb5KFQwoPfAw")
        self.assertEqual(tracks[0]["isrc"], "USSM19902991")
        self.assertEqual(tracks[0]["plays"], 1996980000)

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
        with patch.object(music_metadata, "spotify_artist_artwork", return_value=""):
            with patch.object(music_metadata, "_spotify_client_cache", FakeDiscographyClient()):
                parts = list(music_metadata.artist_page(None, "Michael Jackson", artist_id="track-id"))

        albums = next(part["albums"] for part in parts if part.get("type") == "albums")
        self.assertEqual(parts[0]["artist_id"], "artist-id")
        self.assertEqual(len(parts[1]["tracks"]), 1)
        self.assertEqual([item["title"] for item in albums], ["Second Album", "First Album"])
        self.assertEqual(albums[0]["spotify_id"], "album-two")
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

    def test_identifier_enrichment_uses_isrc_musicbrainz_genre_before_download_search(self):
        class FakeDb:
            saved = {}

            @staticmethod
            def get_track_metadata(key):
                return None

            @classmethod
            def save_track_metadata(cls, key, data):
                cls.saved = {"key": key, "data": dict(data)}

        with patch.dict("sys.modules", {"db": FakeDb}):
            with patch.object(music_metadata, "spotify_track_metadata", return_value={
                "spotify_id": "7DZb1nzqvKMVcN8KEfu6kk",
                "title": "Mentre dormi amor fomenti",
                "artist": "Antonio Vivaldi",
                "album": "Vivaldi: L'Olimpiade, RV 725",
                "duration_ms": 254000,
            }):
                with patch.object(music_metadata, "odesli_lookup", return_value={}):
                    with patch.object(music_metadata, "deezer_track_identifiers", return_value={}):
                        with patch("isrc_resolver.resolve_isrc", return_value="FRZ131725070"):
                            with patch.object(music_metadata, "musicbrainz_recording_identifiers_by_isrc", return_value={
                                "isrc": "FRZ131725070",
                                "musicbrainz_recording_id": "mb-recording-id",
                            }) as mb_by_isrc:
                                with patch.object(music_metadata, "musicbrainz_genres_for_recording", return_value=["Classical"]):
                                    enriched = music_metadata.enrich_track_identifiers({
                                        "type": "track",
                                        "spotify_id": "7DZb1nzqvKMVcN8KEfu6kk",
                                    })

        mb_by_isrc.assert_called_once()
        self.assertEqual(enriched["isrc"], "FRZ131725070")
        self.assertEqual(enriched["musicbrainz_recording_id"], "mb-recording-id")
        self.assertEqual(enriched["genre"], "Classical")
        self.assertEqual(enriched["genres"], ["Classical"])
        self.assertEqual(FakeDb.saved["data"]["genre"], "Classical")

    def test_musicbrainz_recording_genres_fall_back_to_tags(self):
        music_metadata._MB_GENRE_RECORDING_CACHE.clear()
        with patch.object(music_metadata, "get_json", return_value={"tags": [{"name": "Classical"}]}):
            self.assertEqual(music_metadata.musicbrainz_genres_for_recording("recording-id"), ["Classical"])


if __name__ == "__main__":
    unittest.main()
