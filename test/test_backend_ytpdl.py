import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import backend_ytpdl


class TestBackendYtpDl(unittest.TestCase):
    def test_quality_to_codec(self):
        self.assertEqual(backend_ytpdl._quality_to_codec("mp3"), "mp3")
        self.assertEqual(backend_ytpdl._quality_to_codec("m4a"), "m4a")
        self.assertEqual(backend_ytpdl._quality_to_codec("best"), "")
        self.assertEqual(backend_ytpdl._quality_to_codec(""), "")
        self.assertIn("has_drm!=true", backend_ytpdl._format_selector("best"))
        self.assertIn("has_drm!=true", backend_ytpdl._format_selector("m4a"))

    def test_resolved_youtube_url_builds_search_from_track_metadata(self):
        job = {
            "artist": "Pink Floyd",
            "title": "See Emily Play",
            "album": "Relics",
            "metadata": {},
        }

        self.assertEqual(
            backend_ytpdl._resolved_youtube_url(job),
            "ytsearch15:Pink Floyd See Emily Play Relics official audio",
        )

    def test_best_youtube_search_match_scores_candidates(self):
        job = {
            "artist": "Pink Floyd",
            "title": "See Emily Play",
            "metadata": {"duration_ms": 176000},
        }
        search_info = {
            "entries": [
                {
                    "title": "Random psych rock mix with See Emily Play",
                    "uploader": "Compilation Channel",
                    "duration": 3600,
                    "webpage_url": "https://www.youtube.com/watch?v=weak",
                },
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=strong",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=strong")
        self.assertGreater(details["score"], 80)
        self.assertGreater(details["source_score"], 80)

    def test_best_youtube_search_match_accepts_official_video_on_label_channel(self):
        # The official music video is the correct song but lives on a label
        # channel whose name does not contain the artist. It must still pass.
        job = {
            "artist": "CeCe Peniston",
            "title": "Finally",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "CeCe Peniston - Finally (Official Music Video)",
                    "uploader": "A&M Records",
                    "duration": 250,
                    "webpage_url": "https://www.youtube.com/watch?v=official",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=official")
        self.assertGreaterEqual(details["source_score"], 35)

    def test_best_youtube_search_match_rejects_title_only_background_upload(self):
        job = {
            "artist": "Kevin MacLeod",
            "title": "Sneaky Snitch",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "Sneaky Snitch (Kevin MacLeod) - Background Music (HD)",
                    "uploader": "Gaming Sound FX",
                    "duration": 190,
                    "webpage_url": "https://www.youtube.com/watch?v=weak",
                },
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "confident YouTube match"):
            backend_ytpdl._best_youtube_search_match(search_info, job)

    def test_best_youtube_search_match_rejects_untrusted_archive_upload(self):
        job = {
            "artist": "Kevin MacLeod",
            "title": "Sneaky Snitch",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "Kevin MacLeod ~ Sneaky Snitch",
                    "uploader": "EricArchive",
                    "duration": 190,
                    "webpage_url": "https://www.youtube.com/watch?v=archive",
                },
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "confident YouTube match"):
            backend_ytpdl._best_youtube_search_match(search_info, job)

    def test_best_youtube_search_match_avoids_drm_candidate(self):
        job = {
            "artist": "Pink Floyd",
            "title": "See Emily Play",
            "metadata": {"duration_ms": 176000},
        }
        search_info = {
            "entries": [
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=drm",
                    "has_drm": True,
                },
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=clear",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=clear")
        self.assertFalse(details["drm"])

    @patch("ai_reranker.rank_candidates", return_value=[2, 1])
    @patch("ai_reranker.is_enabled", return_value=True)
    @patch("backend_ytpdl._youtube_ai_race_timeout", return_value=1)
    def test_youtube_ai_advisor_reorders_when_it_wins(self, race_timeout, is_enabled, rank_candidates):
        manager = MagicMock()
        manager.config.duck_model = "1"
        manager._append_cache_event = MagicMock()
        job = {"id": "job-1", "artist": "Artist", "title": "Song", "album": "Album"}
        candidates = [
            ("https://www.youtube.com/watch?v=local", {"title": "Artist - Song", "uploader": "Artist", "score": 90}),
            ("https://www.youtube.com/watch?v=ai", {"title": "Artist - Song Official Audio", "uploader": "Artist", "score": 80}),
            ("https://www.youtube.com/watch?v=third", {"title": "Artist - Song live", "uploader": "Artist", "score": 70}),
        ]

        ordered = backend_ytpdl._ranked_youtube_matches_with_ai(candidates, job, manager)

        self.assertEqual(ordered[0][0], "https://www.youtube.com/watch?v=ai")
        self.assertEqual(ordered[1][0], "https://www.youtube.com/watch?v=local")

    @patch("ai_reranker.rank_candidates", return_value=[2, 1])
    @patch("ai_reranker.is_enabled", return_value=True)
    @patch("backend_ytpdl._youtube_ai_race_timeout", return_value=0)
    def test_youtube_local_selector_wins_when_ai_is_late(self, race_timeout, is_enabled, rank_candidates):
        manager = MagicMock()
        manager.config.duck_model = "1"
        manager._append_cache_event = MagicMock()
        job = {"id": "job-1", "artist": "Artist", "title": "Song", "album": "Album"}
        candidates = [
            ("https://www.youtube.com/watch?v=local", {"title": "Artist - Song", "uploader": "Artist", "score": 90}),
            ("https://www.youtube.com/watch?v=ai", {"title": "Artist - Song Official Audio", "uploader": "Artist", "score": 80}),
            ("https://www.youtube.com/watch?v=third", {"title": "Artist - Song live", "uploader": "Artist", "score": 70}),
        ]

        ordered = backend_ytpdl._ranked_youtube_matches_with_ai(candidates, job, manager)

        self.assertEqual(ordered, candidates)

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.m4a")])
    def test_run_uses_youtube_resolution_and_records_output(self, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {"id": "job-1", "quality": "best", "track": {}, "metadata": {}}
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        yt_dlp_instance.download.assert_called_once()
        ydl_opts = yt_dlp_module.YoutubeDL.call_args.args[0]
        self.assertEqual(ydl_opts["format"], "bestaudio[has_drm!=true]/best[has_drm!=true]")
        self.assertNotIn("FFmpegExtractAudio", [item["key"] for item in ydl_opts["postprocessors"]])
        self.assertEqual(job["provider_used"], "ytp-dl")
        self.assertEqual(job["library_path"], "/tmp/out/song.m4a")

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="ytsearch15:Pink Floyd See Emily Play official audio")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.webm")])
    def test_run_resolves_search_to_best_scored_candidate(self, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {
            "id": "job-1",
            "quality": "best",
            "artist": "Pink Floyd",
            "title": "See Emily Play",
            "metadata": {"duration_ms": 176000},
        }
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()
        yt_dlp_instance.extract_info.return_value = {
            "entries": [
                {
                    "title": "Pink Floyd See Emily Play cover",
                    "uploader": "Some Cover Band",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=cover",
                },
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=official",
                },
            ]
        }
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        yt_dlp_instance.extract_info.assert_called_once_with(
            "ytsearch15:Pink Floyd See Emily Play official audio",
            download=False,
        )
        yt_dlp_instance.download.assert_called_once_with(["https://www.youtube.com/watch?v=official"])
        self.assertEqual(job["resolved_url"], "https://www.youtube.com/watch?v=official")
        self.assertEqual(job["ytpdl_match"]["title"], "Pink Floyd - See Emily Play (Official Audio)")

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="ytsearch15:Pink Floyd See Emily Play official audio")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.webm")])
    def test_run_falls_back_when_first_candidate_unavailable(self, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {
            "id": "job-1",
            "quality": "best",
            "artist": "Pink Floyd",
            "title": "See Emily Play",
            "metadata": {"duration_ms": 176000},
        }
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()
        yt_dlp_instance.extract_info.return_value = {
            "entries": [
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=unavailable",
                },
                {
                    "title": "Pink Floyd - See Emily Play (Official Audio)",
                    "uploader": "Pink Floyd - Topic",
                    "duration": 176,
                    "webpage_url": "https://www.youtube.com/watch?v=playable",
                },
            ]
        }
        yt_dlp_instance.download.side_effect = [
            Exception("This video is not available"),
            None,
        ]
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        self.assertEqual(yt_dlp_instance.download.call_count, 2)
        self.assertEqual(
            yt_dlp_instance.download.call_args_list[0].args[0],
            ["https://www.youtube.com/watch?v=unavailable"],
        )
        self.assertEqual(
            yt_dlp_instance.download.call_args_list[1].args[0],
            ["https://www.youtube.com/watch?v=playable"],
        )
        self.assertEqual(job["resolved_url"], "https://www.youtube.com/watch?v=playable")
        self.assertEqual(job["provider_used"], "ytp-dl")


if __name__ == "__main__":
    unittest.main()
