import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

        with patch("SpotiFLAC.providers.spotify_metadata.SpotifyMetadataClient", return_value=client):
            imported = app._spotify_import_playlist("https://open.spotify.com/playlist/playlist-id?si=test")

        self.assertEqual(imported["name"], "Imported Playlist")
        self.assertEqual(imported["artwork_url"], "/playlist-cover")
        self.assertEqual(imported["tracks"][0]["spotify_id"], "track-id")
        self.assertEqual(imported["tracks"][0]["artist"], "Artist")

    def test_import_accepts_spotify_playlist_uri(self):
        client = SimpleNamespace(get_playlist_tracks=lambda playlist_id: ({"name": playlist_id}, [], ""))

        with patch("SpotiFLAC.providers.spotify_metadata.SpotifyMetadataClient", return_value=client):
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

    def test_fetch_lyrics_includes_lrclib_provider(self):
        captured = {}

        async def fake_fetch_lyrics_async(**kwargs):
            captured.update(kwargs)
            return "[00:01.00]Line", "lrclib"

        identity = {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_s": 123,
            "spotify_id": "spotify-id",
            "isrc": "ISRC",
        }

        with patch.object(app, "_read_cached_lyrics", return_value=None):
            with patch.object(app, "_write_cached_lyrics") as write_cache:
                with patch("SpotiFLAC.core.lyrics.fetch_lyrics_async", side_effect=fake_fetch_lyrics_async):
                    result = app._fetch_lyrics(identity)

        self.assertEqual(captured["providers"], ["spotify", "apple", "musixmatch", "lrclib", "amazon"])
        self.assertTrue(result["found"])
        self.assertTrue(result["synced"])
        self.assertEqual(result["provider"], "lrclib")
        write_cache.assert_called_once_with(identity, "[00:01.00]Line", "lrclib")

    def test_video_start_offset_uses_database_override_for_selected_video(self):
        with patch.object(app.db, "get_youtube_video_override", return_value={"start_offset_s": 252}) as lookup:
            offset = app._music_video_start_offset(
                {"webpage_url": "https://www.youtube.com/watch?v=sOnqjkJTMaA"},
                {"spotify_id": "spotify-track-id", "title": "Thriller", "artist": "Michael Jackson"},
            )

        self.assertEqual(offset, 252)
        lookup.assert_called_once()

    def test_video_cache_key_uses_stable_track_identifiers(self):
        first = app._video_cache_key({
            "spotify_id": "spotify-track-id",
            "isrc": "USSM18200005",
            "title": "Thriller",
            "artist": "Michael Jackson",
            "album": "Thriller",
        })
        second = app._video_cache_key({
            "spotify_id": "spotify-track-id",
            "isrc": "USSM18200005",
            "title": "Thriller - Remastered",
            "artist": "Michael Jackson",
            "album": "Number Ones",
        })

        self.assertEqual(first, second)

    def test_video_candidate_rejects_movie_length_side_video(self):
        self.assertTrue(app._video_candidate_rejected(
            {
                "title": "Jimi Hendrix Voodoo Chile Full Movie",
                "uploader": "Movie Channel",
                "duration": 5400,
                "webpage_url": "https://www.youtube.com/watch?v=movie",
            },
            {
                "artist": "Jimi Hendrix",
                "title": "Voodoo Chile",
                "duration_s": 313,
            },
        ))

    def test_side_video_votify_fetch_copies_video_to_cache_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            cache_path = output_dir / "cache.mp4"

            def fake_run(args, **kwargs):
                produced_dir = output_dir / "cache.votify"
                produced_dir.mkdir(parents=True, exist_ok=True)
                (produced_dir / "video.mp4").write_bytes(b"ftyp" + b"\0" * (128 * 1024))
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch.object(app, "VIDEO_FILES_DIR", output_dir):
                with patch("backend_ytpdl._votify_command", return_value=["votify"]):
                    with patch("subprocess.run", side_effect=fake_run):
                        ok = app._try_votify_video_fetch({"spotify_id": "7J1uxwnxfQLu4APicE5Rnj"}, cache_path)

            self.assertTrue(ok)
            self.assertTrue(cache_path.exists())


if __name__ == "__main__":
    unittest.main()
