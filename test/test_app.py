import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app


class SpotifyPlaylistImportTests(unittest.TestCase):
    def test_import_uses_public_playlist_client_and_preserves_track_ids(self):
        track = SimpleNamespace(
            id="track-id",
            title="Song",
            artists="Artist",
            album="Album",
            cover_url="/cover",
            external_url="https://open.spotify.com/track/track-id",
            duration_ms=123000,
            isrc="ISRC123",
        )
        client = SimpleNamespace(get_playlist_tracks=lambda playlist_id: (
            {
                "name": "Imported Playlist",
                "cover_url": "/playlist-cover",
                "description": "Description",
                "owner": "Owner",
                "followers": 14,
            },
            [track],
            "/fallback-cover",
        ))

        with patch("backend.providers.spotify_metadata.SpotifyMetadataClient", return_value=client):
            imported = app._spotify_import_playlist("https://open.spotify.com/playlist/playlist-id?si=test")

        self.assertEqual(imported["name"], "Imported Playlist")
        self.assertEqual(imported["artwork_url"], "/playlist-cover")
        self.assertEqual(imported["tracks"][0]["spotify_id"], "track-id")
        self.assertEqual(imported["tracks"][0]["artist"], "Artist")

    def test_import_accepts_spotify_playlist_uri(self):
        client = SimpleNamespace(get_playlist_tracks=lambda playlist_id: ({"name": playlist_id}, [], ""))

        with patch("backend.providers.spotify_metadata.SpotifyMetadataClient", return_value=client):
            imported = app._spotify_import_playlist("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")

        self.assertEqual(imported["name"], "37i9dQZF1DXcBWIGoYBM5M")

    def test_download_enrichment_persists_track_identifiers_in_saved_playlist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playlist_path = Path(tmpdir) / "playlists.json"
            playlist_path.write_text(
                '[{"id":"playlist","tracks":[{"type":"track","title":"Shout","spotify_id":"spotify-id"}]}]',
                "utf-8",
            )
            enriched = {
                "type": "track",
                "title": "Shout",
                "artist": "Tears For Fears",
                "spotify_id": "spotify-id",
                "isrc": "ISRC",
                "deezer_id": "deezer-id",
            }
            with patch.object(app, "PLAYLISTS_PATH", playlist_path):
                with patch.object(app, "enrich_track_identifiers", return_value=enriched):
                    payload = app.enrich_download_payload({"track": {"spotify_id": "spotify-id"}})
                stored = app.load_playlists()[0]["tracks"][0]

        self.assertEqual(payload["isrc"], "ISRC")
        self.assertEqual(stored["deezer_id"], "deezer-id")

    def test_download_enrichment_recovers_spotify_id_from_track_key(self):
        enriched = {
            "type": "track",
            "title": "Mentre dormi amor fomenti",
            "artist": "Antonio Vivaldi",
            "spotify_id": "7DZb1nzqvKMVcN8KEfu6kk",
            "genre": "Classical",
        }
        with patch.object(app, "enrich_track_identifiers", return_value=enriched) as enrich:
            payload = app.enrich_download_payload({
                "track": {
                    "track_key": "spotify_id:7DZb1nzqvKMVcN8KEfu6kk",
                    "title": "Mentre dormi amor fomenti",
                    "artist": "Antonio Vivaldi",
                }
            })

        enrich.assert_called_once()
        self.assertEqual(enrich.call_args.args[0]["spotify_id"], "7DZb1nzqvKMVcN8KEfu6kk")
        self.assertEqual(payload["spotify_id"], "7DZb1nzqvKMVcN8KEfu6kk")
        self.assertEqual(payload["metadata"]["genre"], "Classical")

    def test_playlist_identifier_enrichment_updates_imported_tracks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playlist_path = Path(tmpdir) / "playlists.json"
            playlist_path.write_text(
                '[{"id":"playlist","tracks":[{"type":"track","title":"Shout","spotify_id":"spotify-id","isrc":""}]}]',
                "utf-8",
            )
            enriched = {
                "type": "track",
                "title": "Shout",
                "spotify_id": "spotify-id",
                "isrc": "GBF088490125",
                "tidal_id": "tidal-id",
            }
            with patch.object(app, "PLAYLISTS_PATH", playlist_path):
                with patch.object(app, "enrich_track_identifiers", return_value=enriched):
                    app.enrich_saved_playlist_tracks("playlist")
                stored = app.load_playlists()[0]["tracks"][0]

        self.assertEqual(stored["isrc"], "GBF088490125")
        self.assertEqual(stored["tidal_id"], "tidal-id")

    def test_identifier_enrichment_updates_saved_track_without_spotify_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playlist_path = Path(tmpdir) / "playlists.json"
            playlist_path.write_text(
                '[{"id":"playlist","tracks":[{"type":"track","title":"Song","artist":"Artist","isrc":""}]}]',
                "utf-8",
            )
            enriched = {
                "type": "track",
                "title": "Song",
                "artist": "Artist",
                "spotify_id": "found-spotify-id",
                "isrc": "ISRC-FALLBACK",
            }
            with patch.object(app, "PLAYLISTS_PATH", playlist_path):
                with patch.object(app, "enrich_track_identifiers", return_value=enriched):
                    app.enrich_and_persist_track({"type": "track", "title": "Song", "artist": "Artist"})
                stored = app.load_playlists()[0]["tracks"][0]

        self.assertEqual(stored["isrc"], "ISRC-FALLBACK")
        self.assertEqual(stored["spotify_id"], "found-spotify-id")

    def test_playlist_isrc_backfill_uses_resolver_and_saves_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            playlist_path = Path(tmpdir) / "playlists.json"
            playlist_path.write_text(
                '[{"id":"playlist","tracks":[{"title":"Song","artist":"Artist","spotify_id":"id","isrc":""}]}]',
                "utf-8",
            )
            with patch.object(app, "PLAYLISTS_PATH", playlist_path):
                with patch("isrc_resolver.resolve_isrc", return_value="ISRC-BACKFILLED") as resolver:
                    result = app.backfill_playlist_isrcs("playlist", max_workers=1)
                stored = app.load_playlists()[0]["tracks"][0]

        resolver.assert_called_once_with("Song", "Artist", spotify_id="id")
        self.assertEqual(result, {"missing": 1, "filled": 1, "remaining": 0})
        self.assertEqual(stored["isrc"], "ISRC-BACKFILLED")

    def test_backfill_library_sidecars_adds_identifiers_without_erasing_saved_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            album_dir = Path(tmpdir) / "Artist" / "Album"
            album_dir.mkdir(parents=True)
            info_path = album_dir / "metadata.json"
            info_path.write_text(
                '{"album_info":{"album":"Album"},"tracks":{"Song":{"title":"Song","spotify_id":"spotify-id","isrc":"","artwork_url":"saved-cover"}}}',
                "utf-8",
            )
            enriched = {
                "title": "Song",
                "spotify_id": "spotify-id",
                "isrc": "",
                "deezer_id": "deezer-id",
                "tidal_id": "tidal-id",
                "artwork_url": "",
            }

            with patch.object(app, "enrich_track_identifiers", return_value=enriched):
                result = app.backfill_library_sidecars(Path(tmpdir))
            stored = __import__("json").loads(info_path.read_text("utf-8"))["tracks"]["Song"]

        self.assertEqual(result["sidecars_updated"], 1)
        self.assertEqual(result["tracks_updated"], 1)
        self.assertEqual(stored["artwork_url"], "saved-cover")
        self.assertEqual(stored["deezer_id"], "deezer-id")
        self.assertEqual(stored["tidal_id"], "tidal-id")
        self.assertEqual(stored["isrc"], "")


if __name__ == "__main__":
    unittest.main()
