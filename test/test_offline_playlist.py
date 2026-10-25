import base64
import http.client
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mutagen.id3 import APIC, TALB, TIT2, TPE1
from mutagen.wave import WAVE

import app
from offline_playlist import OFFLINE_PLAYLIST_ID, build_offline_playlist, read_artwork
from service_downloader import ServiceDownloadManager

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=")


class OfflinePlaylistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(music_dir=self.root / "music", cache_dir=self.root / "cache")
        with patch("service_downloader.JOBS_PATH", self.root / "jobs.json"):
            self.manager = ServiceDownloadManager(self.config)

    def audio(self, title="Song", artist="Artist", album="Album", root=None):
        path = (root or self.config.music_dir) / artist / album / f"{title}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 44100)
        tagged = WAVE(path)
        tagged.add_tags()
        tagged.tags.add(TIT2(encoding=3, text=title))
        tagged.tags.add(TPE1(encoding=3, text=artist))
        tagged.tags.add(TALB(encoding=3, text=album))
        tagged.save()
        return path

    def test_appears_for_real_files_and_disappears_after_last_removal(self):
        self.assertIsNone(build_offline_playlist(self.manager))
        path = self.audio()
        playlist = build_offline_playlist(self.manager)
        self.assertEqual(playlist["id"], OFFLINE_PLAYLIST_ID)
        self.assertTrue(playlist["read_only"])
        self.assertEqual(playlist["tracks"][0]["library_path"], str(path.resolve()))
        self.assertEqual(playlist["tracks"][0]["duration_ms"], 1000)
        path.unlink()
        self.assertIsNone(build_offline_playlist(self.manager))

    def test_complete_inventory_ignores_cache_invalid_files_and_unfinished_downloads(self):
        path = self.audio()
        self.audio("Streamed", root=self.config.cache_dir)
        pending = self.audio("Still downloading")
        path.with_name("broken.mp3").write_bytes(b"not audio")
        path.with_name("partial.wav.part").write_bytes(path.read_bytes())
        self.manager.jobs = {
            "a": {"mode": "download", "status": "finished", "library_path": str(path)},
            "duplicate": {"mode": "download", "status": "finished", "library_path": str(path)},
            "pending": {"mode": "download", "status": "running", "output_dir": str(pending.parent), "title": "Still downloading", "artist": "Artist"},
        }
        playlist = build_offline_playlist(self.manager)
        self.assertEqual([t["title"] for t in playlist["tracks"]], ["Song"])

    def test_metadata_and_four_distinct_local_album_covers(self):
        for n in range(5):
            path = self.audio(f"Song {n}", album=f"Album {n}")
            path.parent.joinpath("cover.png").write_bytes(PNG)
            path.parent.joinpath("metadata.json").write_text(json.dumps({
                "album_info": {"artist": "Artist", "album": f"Album {n}"},
                "tracks": {f"Song {n}": {"isrc": f"TEST{n}", "spotify_id": f"spotify{n}"}},
            }))
        playlist = build_offline_playlist(self.manager)
        self.assertEqual(len(playlist["tracks"]), 5)
        self.assertEqual(len(playlist["artwork_urls"]), 4)
        self.assertEqual(len(set(playlist["artwork_urls"])), 4)
        for track in playlist["tracks"]:
            self.assertTrue(track["artwork_url"].startswith("/api/library/artwork?"))
            self.assertTrue(track["isrc"].startswith("TEST"))
            self.assertTrue(track["spotify_id"].startswith("spotify"))
            self.assertEqual(read_artwork(Path(track["library_path"]), self.config.music_dir), (PNG, "image/png"))

    def test_embedded_art_and_small_valid_audio_are_available_offline(self):
        path = self.audio()
        tagged = WAVE(path)
        tagged.tags.add(APIC(encoding=3, mime="image/png", type=3, data=PNG))
        tagged.save()
        self.assertLess(path.stat().st_size, 100 * 1024)
        playlist = build_offline_playlist(self.manager)
        self.assertEqual(len(playlist["artwork_urls"]), 1)
        self.assertEqual(read_artwork(path, self.config.music_dir), (PNG, "image/png"))

    def test_artwork_and_inventory_reject_paths_outside_music_root(self):
        outside = self.audio(root=self.root / "outside")
        outside.parent.joinpath("cover.png").write_bytes(PNG)
        self.config.music_dir.mkdir()
        (self.config.music_dir / "escape.wav").symlink_to(outside)
        self.assertIsNone(read_artwork(outside, self.config.music_dir))
        self.assertIsNone(build_offline_playlist(self.manager))

    def test_known_offline_file_does_not_wait_for_online_metadata_enrichment(self):
        path = self.audio()
        track = build_offline_playlist(self.manager)["tracks"][0]
        with patch.object(app, "app_config", self.config), patch.object(app, "enrich_and_persist_track", side_effect=AssertionError("Online metadata must not be needed")):
            payload = app.enrich_download_payload({"track": track, "mode": "download"})
        self.assertEqual(payload["track"]["library_path"], str(path.resolve()))

    def test_live_api_is_automatic_immutable_and_plays_local_audio_on_both_platforms(self):
        playlists_path = self.root / "playlists.json"
        saved = [{"id": "mine", "name": "My playlist", "tracks": []}]
        playlists_path.write_text(json.dumps(saved))
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def request(method, path, body=None, headers=None):
            client = http.client.HTTPConnection(*server.server_address, timeout=5)
            all_headers = {"X-Mindinguflac-Token": "android-test", **(headers or {})}
            client.request(method, path, json.dumps(body) if body is not None else None, all_headers)
            response = client.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            client.close()
            return result
        with patch.object(app, "service_downloader", self.manager), patch.object(app, "app_config", self.config), patch.object(app, "PLAYLISTS_PATH", playlists_path):
            for platform_token in ("", "android-test"):
                with self.subTest(platform="Android" if platform_token else "desktop"), patch.object(app, "API_TOKEN", platform_token):
                    self.assertEqual(json.loads(request("GET", "/api/playlists")[2]), saved)
                    path = self.audio()
                    path.parent.joinpath("cover.png").write_bytes(PNG)
                    playlists = json.loads(request("GET", "/api/playlists")[2])
                    self.assertEqual([p["id"] for p in playlists], [OFFLINE_PLAYLIST_ID, "mine"])
                    art = request("GET", playlists[0]["tracks"][0]["artwork_url"])
                    self.assertEqual((art[0], art[1]["Content-Type"], art[2]), (200, "image/png", PNG))
                    for route, body in [
                        ("/api/playlists/tracks", {"playlist_id": OFFLINE_PLAYLIST_ID, "track": {}}),
                        ("/api/playlists/tracks/add", {"id": OFFLINE_PLAYLIST_ID, "tracks": [{}]}),
                        ("/api/playlists/refresh", {"id": OFFLINE_PLAYLIST_ID}),
                        (f"/api/playlists/{OFFLINE_PLAYLIST_ID}/tracks", {"track": {}}),
                    ]:
                        self.assertEqual(request("POST", route, body)[0], 403)
                    self.assertEqual(request("DELETE", "/api/playlists", {"id": OFFLINE_PLAYLIST_ID})[0], 403)
                    self.assertEqual(json.loads(playlists_path.read_text()), saved)
                    self.assertTrue(path.exists())
                    from urllib.parse import urlencode
                    streamed = request("GET", "/api/library/stream?" + urlencode({"path": str(path)}), headers={"Range": "bytes=0-15"})
                    self.assertEqual(streamed[0], 206)
                    self.assertEqual(streamed[2], path.read_bytes()[:16])
                    path.unlink()
                    self.assertEqual(json.loads(request("GET", "/api/playlists")[2]), saved)


if __name__ == "__main__":
    unittest.main()
