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

    def test_classical_profile_uses_existing_genre_metadata_only(self):
        classical_job = {
            "artist": "Antonio Vivaldi",
            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti",
            "metadata": {"genres": ["Classical", "Baroque"]},
        }
        unclassified_job = {
            "artist": "Antonio Vivaldi",
            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti",
            "metadata": {},
        }

        self.assertEqual(backend_ytpdl._ytpdl_search_profile(classical_job), "classical")
        self.assertEqual(backend_ytpdl._ytpdl_search_profile(unclassified_job), "default")

    def test_classical_youtube_query_uses_catalog_and_distinctive_terms(self):
        job = {
            "artist": "Antonio Vivaldi",
            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti (Licida)",
            "album": "Vivaldi: L'Olimpiade, RV 725",
            "metadata": {"genre": "Classical"},
        }

        self.assertEqual(
            backend_ytpdl._youtube_search_query(job),
            "ytsearch15:Antonio Vivaldi 725 rv olimpiade mentre dormi amor fomenti licida 725 rv olimpiade",
        )

    def test_default_youtube_query_unchanged_for_unclassified_catalog_title(self):
        job = {
            "artist": "Antonio Vivaldi",
            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti (Licida)",
            "album": "Vivaldi: L'Olimpiade, RV 725",
            "metadata": {},
        }

        self.assertEqual(
            backend_ytpdl._youtube_search_query(job),
            "ytsearch15:Antonio Vivaldi L'Olimpiade, RV 725: Mentre dormi amor fomenti (Licida) Vivaldi: L'Olimpiade, RV 725 official audio",
        )

    def test_youtube_query_falls_back_to_title_when_artist_is_missing(self):
        self.assertEqual(
            backend_ytpdl._youtube_search_query({
                "artist": "",
                "title": "Lamento della ninfa, SV 163 Amor, amor",
                "metadata": {},
            }),
            "ytsearch15:Lamento della ninfa, SV 163 Amor, amor official audio",
        )
        self.assertEqual(
            backend_ytpdl._youtube_search_query({
                "artist": "",
                "title": "Ciaccona (Antonio Falconiero ca. 1585-1656)",
                "metadata": {},
            }, clean=True),
            "ytsearch15:Ciaccona official audio",
        )

    def test_video_youtube_query_prefers_official_video(self):
        self.assertEqual(
            backend_ytpdl._youtube_search_query({
                "artist": "Simply Red",
                "title": "For Your Babies",
                "album": "Stars",
                "quality": "video",
                "metadata": {},
            }),
            "ytsearch15:Simply Red For Your Babies official video",
        )

    def test_broad_youtube_query_drops_official_audio_constraint(self):
        self.assertEqual(
            backend_ytpdl._broad_youtube_search_query({
                "artist": "Claudio Monteverdi",
                "title": "Oblivion",
                "metadata": {},
            }),
            "ytsearch15:Claudio Monteverdi Oblivion",
        )

    def test_title_only_scoring_does_not_reject_missing_artist_metadata(self):
        job = {
            "artist": "",
            "title": "Lamento della ninfa, SV 163 Amor, amor",
            "metadata": {"duration_ms": 250000},
        }
        score, details = backend_ytpdl._score_youtube_candidate({
            "title": "Lamento della ninfa, SV 163: Amor, amor",
            "uploader": "Early Music Channel",
            "duration": 250,
            "webpage_url": "https://www.youtube.com/watch?v=match",
        }, job)

        self.assertGreaterEqual(score, 55)
        self.assertGreaterEqual(details["artist_score"], 50)
        self.assertEqual(details["artist_coverage"], 100)

    def test_classical_scoring_rejects_wrong_catalog_number(self):
        job = {
            "artist": "Antonio Vivaldi",
            "title": "L'Olimpiade, RV 725: Mentre dormi amor fomenti (Licida)",
            "metadata": {"genre": "Classical"},
        }
        search_info = {
            "entries": [
                {
                    "title": "La verità in cimento, RV 739: Mi vuoi tradir, lo so. Melindo, aria.",
                    "uploader": "Classical Archive",
                    "duration": 220,
                    "webpage_url": "https://www.youtube.com/watch?v=wrong",
                },
            ]
        }

        with self.assertRaisesRegex(RuntimeError, "confident YouTube match"):
            backend_ytpdl._best_youtube_search_match(search_info, job)

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

    def test_video_scoring_prefers_official_video_over_auto_generated_audio(self):
        job = {
            "artist": "Simply Red",
            "title": "For Your Babies",
            "quality": "video",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "For Your Babies",
                    "uploader": "Simply Red",
                    "description": "Provided to YouTube by Rhino\n\nFor Your Babies · Simply Red\n\nSong Book 1985-2010\n\nAuto-generated by YouTube.",
                    "duration": 257,
                    "channel_is_verified": True,
                    "webpage_url": "https://www.youtube.com/watch?v=nBJvUF5cNtk",
                },
                {
                    "title": "Simply Red - For Your Babies (Official Video)",
                    "uploader": "Simply Red",
                    "description": "Simply Red official music video for For Your Babies.",
                    "duration": 259,
                    "channel_is_verified": True,
                    "webpage_url": "https://www.youtube.com/watch?v=xv4HOh9uwLc",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=xv4HOh9uwLc")
        self.assertIn("official_video_title", details["video_match_reasons"])
        self.assertGreater(details["score"], 80)

    def test_video_scoring_rejects_static_official_audio_when_video_exists(self):
        job = {
            "artist": "Michael Jackson",
            "title": "P.Y.T. (Pretty Young Thing)",
            "quality": "video",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "Michael Jackson - P.Y.T. (Pretty Young Thing) (Official Audio)",
                    "uploader": "Michael Jackson",
                    "description": "Official Audio for P.Y.T. (Pretty Young Thing) by Michael Jackson",
                    "duration": 241,
                    "channel_is_verified": True,
                    "webpage_url": "https://www.youtube.com/watch?v=audio",
                },
                {
                    "title": "Michael Jackson P Y T Pretty Young Thing MUSIC VIDEO HD",
                    "uploader": "Quincy Lopez (Quin)",
                    "duration": 239,
                    "webpage_url": "https://www.youtube.com/watch?v=video",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)
        audio_score, audio_details = backend_ytpdl._score_youtube_candidate(search_info["entries"][0], job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=video")
        self.assertFalse(backend_ytpdl._candidate_is_confident(audio_score, audio_details))
        self.assertTrue(audio_details["video_static_audio"])

    def test_video_scoring_rejects_ai_or_fanmade_recreations(self):
        job = {
            "artist": "Michael Jackson",
            "title": "P.Y.T. (Pretty Young Thing)",
            "quality": "video",
            "metadata": {},
        }
        score, details = backend_ytpdl._score_youtube_candidate({
            "title": "Michael Jackson - P.Y.T. (Pretty Young Thing) (AI Music Video)",
            "uploader": "Michael Jackson The Music",
            "description": "Michael Jackson fans made video.",
            "duration": 241,
            "channel_is_verified": False,
            "webpage_url": "https://www.youtube.com/watch?v=ai",
        }, job)

        self.assertFalse(backend_ytpdl._candidate_is_confident(score, details))
        self.assertTrue(details["video_unofficial_recreation"])
        self.assertIn("unofficial_recreation", details["video_match_reasons"])

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

    def test_best_youtube_search_match_uses_description_artist_signal_for_vevo(self):
        job = {
            "artist": "CeCe Peniston",
            "title": "Finally",
            "metadata": {},
        }
        search_info = {
            "entries": [
                {
                    "title": "Finally",
                    "uploader": "MusicVEVO",
                    "description": "Music video by CeCe Peniston performing Finally. (C) 1991 A&M Records",
                    "duration": 250,
                    "webpage_url": "https://www.youtube.com/watch?v=vevo",
                },
                {
                    "title": "Finally",
                    "uploader": "Random Music",
                    "duration": 250,
                    "webpage_url": "https://www.youtube.com/watch?v=random",
                },
            ]
        }

        url, details = backend_ytpdl._best_youtube_search_match(search_info, job)

        self.assertEqual(url, "https://www.youtube.com/watch?v=vevo")
        self.assertGreaterEqual(details["description_artist_coverage"], 100)
        self.assertGreaterEqual(details["source_score"], 80)

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

    @patch("ai_reranker.rank_candidates", return_value={
        "ranked_ids": [2, 1],
        "ranked_urls": [
            "https://www.youtube.com/watch?v=ai",
            "https://www.youtube.com/watch?v=local",
        ],
    })
    @patch("ai_reranker.is_enabled", return_value=True)
    @patch("backend_ytpdl._youtube_ai_race_timeout", return_value=1)
    def test_youtube_ai_advisor_uses_returned_urls(self, race_timeout, is_enabled, rank_candidates):
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
    @patch("backend_ytpdl._resolved_youtube_url", return_value="https://www.youtube.com/watch?v=8KWf_-ofYgI&list=PLFAcddgaFN8zqIJrTakvM9qWnR7iIrXnj")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.webm")])
    @patch("db.add_to_blacklist")
    def test_run_rejects_mismatched_direct_youtube_url_and_searches(self, add_to_blacklist, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {
            "id": "job-1",
            "quality": "best",
            "artist": "Michael Jackson",
            "title": "Thriller",
            "metadata": {},
            "track": {
                "youtube_url": "https://www.youtube.com/watch?v=8KWf_-ofYgI&list=PLFAcddgaFN8zqIJrTakvM9qWnR7iIrXnj",
            },
        }
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()

        def extract_info(target, download=False):
            if target.startswith("https://www.youtube.com/watch?v=8KWf_-ofYgI"):
                return {
                    "title": "Wanna Be Startin' Somethin'",
                    "uploader": "Michael Jackson",
                    "description": "Provided to YouTube by Epic\n\nWanna Be Startin' Somethin' · Michael Jackson\n\nThriller\n\nAuto-generated by YouTube.",
                    "duration": 363,
                    "webpage_url": "https://www.youtube.com/watch?v=8KWf_-ofYgI",
                }
            self.assertTrue(target.startswith("ytsearch15:Michael Jackson Thriller"))
            return {
                "entries": [
                    {
                        "title": "Michael Jackson - Thriller (Official 4K Video)",
                        "uploader": "Michael Jackson",
                        "description": "Michael Jackson's official 4K music video for Thriller",
                        "duration": 822,
                        "webpage_url": "https://www.youtube.com/watch?v=sOnqjkJTMaA",
                    },
                ]
            }

        yt_dlp_instance.extract_info.side_effect = extract_info
        yt_dlp_instance.download.return_value = 0
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        yt_dlp_instance.download.assert_called_once_with(["https://www.youtube.com/watch?v=sOnqjkJTMaA"])
        self.assertEqual(job["resolved_url"], "https://www.youtube.com/watch?v=sOnqjkJTMaA")
        self.assertEqual(job["ytpdl_match"]["title"], "Michael Jackson - Thriller (Official 4K Video)")
        add_to_blacklist.assert_not_called()

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="ytsearch15:Pink Floyd See Emily Play official audio")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.webm")])
    @patch("db.add_to_blacklist")
    @patch("db.is_blacklisted", return_value=False)
    def test_run_falls_back_when_first_candidate_unavailable(self, is_blacklisted, add_to_blacklist, find_audio_files, resolved_url, get_yt_dlp):
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

    @patch("backend_ytpdl._get_yt_dlp")
    @patch("backend_ytpdl._resolved_youtube_url", return_value="ytsearch15:Claudio Monteverdi Oblivion official audio")
    @patch("service_downloader._find_audio_files", return_value=[Path("/tmp/out/song.webm")])
    def test_run_uses_broad_search_when_official_queries_return_no_candidates(self, find_audio_files, resolved_url, get_yt_dlp):
        manager = MagicMock()
        manager._cancel_flags = set()
        manager._append_cache_event = MagicMock()

        job = {
            "id": "job-1",
            "quality": "best",
            "artist": "Claudio Monteverdi",
            "title": "Oblivion",
            "metadata": {},
        }
        output_dir = Path("/tmp/out")

        yt_dlp_module = MagicMock()
        yt_dlp_instance = MagicMock()

        def extract_info(query, download=False):
            if "official audio" in query:
                return {"entries": []}
            return {
                "entries": [
                    {
                        "title": "Claudio Monteverdi - Oblivion",
                        "uploader": "Early Music Channel",
                        "duration": 180,
                        "webpage_url": "https://www.youtube.com/watch?v=broad",
                    }
                ]
            }

        yt_dlp_instance.extract_info.side_effect = extract_info
        yt_dlp_instance.download.return_value = 0
        yt_dlp_module.YoutubeDL.return_value.__enter__.return_value = yt_dlp_instance
        get_yt_dlp.return_value = yt_dlp_module

        backend_ytpdl.run(output_dir, job, manager)

        self.assertEqual(
            yt_dlp_instance.extract_info.call_args_list[-1].args[0],
            "ytsearch15:Claudio Monteverdi Oblivion",
        )
        yt_dlp_instance.download.assert_called_once_with(["https://www.youtube.com/watch?v=broad"])
        self.assertEqual(job["resolved_url"], "https://www.youtube.com/watch?v=broad")
        self.assertEqual(job["provider_used"], "ytp-dl")


if __name__ == "__main__":
    unittest.main()
