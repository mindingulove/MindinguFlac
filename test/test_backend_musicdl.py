import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import backend_musicdl


class FakeMusicClient:
    created = []
    search_results = {"NeteaseMusicClient": ["song"]}
    results_by_keyword = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.search_keyword = ""
        self.download_args = None
        FakeMusicClient.created.append(self)

    def search(self, *, keyword):
        self.search_keyword = keyword
        return self.results_by_keyword.get(keyword, self.search_results)

    def download(self, *, song_infos):
        self.download_args = song_infos


class FakeQianqianProvider:
    MUSIC_QUALITIES = ["3000", "320", "128", "64"]


class FakeKuwoProvider:
    MUSIC_QUALITIES = [(22000, "flac"), (320, "mp3")]

    def _parsewiththirdpartapis(self, **_kwargs):
        return "automatic-lossless-result"


class FakeMiguProvider:
    def __init__(self):
        self.attempts = []

    def _parsewithofficialapiv1(self, search_result, *_args, **_kwargs):
        formats = [item["formatType"] for item in search_result.get("rateFormats", [])]
        self.attempts.append(formats)
        return SimpleNamespace(with_valid_download_url="HQ" in formats)


class BackendMusicdlTests(unittest.TestCase):
    def setUp(self):
        FakeMusicClient.created = []
        FakeMusicClient.search_results = {"NeteaseMusicClient": ["song"]}
        FakeMusicClient.results_by_keyword = {}

    def test_builds_selected_client_using_musicdl_public_api(self):
        output_dir = Path("/tmp/cache-output")

        clients = backend_musicdl._build_working_clients(
            SimpleNamespace(MusicClient=FakeMusicClient),
            output_dir,
            "netease",
        )

        self.assertEqual(set(clients), {"netease"})
        self.assertEqual(
            FakeMusicClient.created[0].kwargs,
            {
                "music_sources": ["NeteaseMusicClient"],
                "init_music_clients_cfg": {
                    "NeteaseMusicClient": {"work_dir": str(output_dir)}
                },
            },
        )

    def test_rejects_ui_sources_not_supported_by_current_musicdl_adapter(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported source"):
            backend_musicdl._build_working_clients(
                SimpleNamespace(MusicClient=FakeMusicClient),
                Path("/tmp/cache-output"),
                "baidu",
            )

    def test_quality_preference_orders_requested_tier_then_restores_default(self):
        provider = FakeQianqianProvider()
        client = SimpleNamespace(music_clients={"QianqianMusicClient": provider})

        with backend_musicdl._quality_preference(
            SimpleNamespace(), client, "qianqian", "320"
        ):
            self.assertEqual(type(provider).MUSIC_QUALITIES, ["320", "3000", "128", "64"])

        self.assertEqual(type(provider).MUSIC_QUALITIES, ["3000", "320", "128", "64"])

    def test_explicit_kuwo_quality_bypasses_automatic_lossless_candidate(self):
        provider = FakeKuwoProvider()
        client = SimpleNamespace(music_clients={"KuwoMusicClient": provider})
        musicdl_module = SimpleNamespace(SongInfo=lambda **kwargs: kwargs["source"])

        with backend_musicdl._quality_preference(musicdl_module, client, "kuwo", "320"):
            self.assertEqual(provider._parsewiththirdpartapis(), "KuwoMusicClient")
            self.assertEqual(type(provider).MUSIC_QUALITIES[0], (320, "mp3"))

        self.assertEqual(provider._parsewiththirdpartapis(), "automatic-lossless-result")
        self.assertEqual(type(provider).MUSIC_QUALITIES[0], (22000, "flac"))

    def test_migu_requested_quality_falls_back_to_original_catalog(self):
        provider = FakeMiguProvider()
        client = SimpleNamespace(music_clients={"MiguMusicClient": provider})
        track = {"rateFormats": [{"formatType": "ZQ24"}, {"formatType": "HQ"}]}

        with backend_musicdl._quality_preference(
            SimpleNamespace(), client, "migu", "hires"
        ):
            result = provider._parsewithofficialapiv1(track)

        self.assertTrue(result.with_valid_download_url)
        self.assertEqual(provider.attempts, [["ZQ24"], ["ZQ24", "HQ"]])

    def test_run_passes_search_and_download_through_unified_client(self):
        manager = SimpleNamespace(_cancel_flags=set(), _append_cache_event=lambda *args: None)
        job = {
            "id": "job-1",
            "service": "netease",
            "title": "Space Cowboy",
            "artist": "Jamiroquai",
            "mode": "cache",
        }

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            import builtins

            original_builtin_import = builtins.__import__

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "musicdl":
                    return SimpleNamespace(musicdl=SimpleNamespace(MusicClient=FakeMusicClient))
                if name == "service_downloader":
                    return SimpleNamespace(_find_audio_files=lambda _directory: [output_dir / "track.flac"])
                return original_builtin_import(name, globals, locals, fromlist, level)

            builtins.__import__ = fake_import
            try:
                backend_musicdl.run(output_dir, job, manager)
            finally:
                builtins.__import__ = original_builtin_import

        client = FakeMusicClient.created[0]
        self.assertEqual(client.search_keyword, "Space Cowboy Jamiroquai")
        self.assertEqual(client.download_args, {"NeteaseMusicClient": ["song"]})

    def test_run_searches_by_title_and_artist_ignoring_isrc(self):
        manager = SimpleNamespace(_cancel_flags=set(), _append_cache_event=lambda *args: None)
        job = {
            "id": "job-isrc",
            "service": "netease",
            "title": "Space Cowboy",
            "artist": "Jamiroquai",
            "isrc": "GBISRC123",
            "mode": "cache",
        }

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            import builtins

            original_builtin_import = builtins.__import__

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "musicdl":
                    return SimpleNamespace(musicdl=SimpleNamespace(MusicClient=FakeMusicClient))
                if name == "service_downloader":
                    return SimpleNamespace(_find_audio_files=lambda _directory: [output_dir / "track.flac"])
                return original_builtin_import(name, globals, locals, fromlist, level)

            builtins.__import__ = fake_import
            try:
                backend_musicdl.run(output_dir, job, manager)
            finally:
                builtins.__import__ = original_builtin_import

        self.assertEqual(FakeMusicClient.created[0].search_keyword, "Space Cowboy Jamiroquai")


if __name__ == "__main__":
    unittest.main()
