import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_reranker


class TestAiReranker(unittest.TestCase):
    def test_duck_provider_is_default_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(ai_reranker.is_enabled())

    def test_explicit_duck_provider_enables_available_client(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_AI_RERANK_PROVIDER": "duck_chat"}, clear=True):
            self.assertTrue(ai_reranker.is_enabled())

    def test_rank_candidates_uses_valid_provider_ids_only(self):
        candidates = [
            {"id": 1, "title": "Artist - Song.flac", "source": "youtube", "seeders": 1, "score": 100, "url": "https://www.youtube.com/watch?v=one"},
            {"id": 2, "title": "Artist - Album - Song.flac", "source": "youtube", "seeders": 0, "score": 90, "url": "https://www.youtube.com/watch?v=two"},
        ]

        with patch.dict(os.environ, {"MINDINGUFLAC_AI_RERANK_PROVIDER": "duck_chat"}):
            with patch("ai_reranker._request", return_value={"ranked_ids": [2, "1", 99, "bad", 2], "ranked_urls": ["https://www.youtube.com/watch?v=two", "https://www.youtube.com/watch?v=one"]}):
                ranked = ai_reranker.rank_candidates(
                    {"artist": "Artist", "title": "Song", "album": "Album"},
                    candidates,
                    include_urls=True,
                )

        self.assertEqual(ranked["ranked_ids"], [2, 1])
        self.assertEqual(ranked["ranked_urls"], ["https://www.youtube.com/watch?v=two", "https://www.youtube.com/watch?v=one"])

    def test_rank_candidates_youtube_falls_back_to_ids_when_urls_missing(self):
        candidates = [
            {"id": 1, "title": "Artist - Song", "source": "youtube", "seeders": 0, "score": 100, "url": "https://www.youtube.com/watch?v=one"},
            {"id": 2, "title": "Artist - Song", "source": "youtube", "seeders": 0, "score": 90, "url": "https://www.youtube.com/watch?v=two"},
        ]

        with patch.dict(os.environ, {"MINDINGUFLAC_AI_RERANK_PROVIDER": "duck_chat"}):
            with patch("ai_reranker._request", return_value={"ranked_ids": [2, 1]}):
                ranked = ai_reranker.rank_candidates(
                    {"artist": "Artist", "title": "Song", "album": "Album"},
                    candidates,
                    include_urls=True,
                )

        self.assertEqual(ranked["ranked_ids"], [2, 1])
        self.assertEqual(ranked["ranked_urls"], ["https://www.youtube.com/watch?v=two", "https://www.youtube.com/watch?v=one"])

    def test_selected_provider_prefers_setting_over_env(self):
        with patch.dict(os.environ, {"MINDINGUFLAC_AI_RERANK_PROVIDER": "duckai"}, clear=True):
            self.assertEqual(ai_reranker._selected_provider("gemini"), "gemini")

    def test_codex_provider_requires_cached_authentication(self):
        with patch("codex_proxy.fetch_status", return_value={"authenticated": True}):
            self.assertTrue(ai_reranker.is_enabled("codex"))
        with patch("codex_proxy.fetch_status", return_value={"authenticated": False}):
            self.assertFalse(ai_reranker.is_enabled("codex"))

    def test_provider_settings_are_normalized_for_all_backends(self):
        config = SimpleNamespace(duck_model=2, ai_provider="codex", gemini_model="pro")
        self.assertEqual(
            ai_reranker.provider_settings(config),
            ("2", "codex", "pro"),
        )

    def test_selected_provider_does_not_silently_send_to_another_service(self):
        with patch("ai_reranker._duck_request", return_value={}) as duck_request:
            with patch("ai_reranker._gemini_request") as gemini_request:
                self.assertEqual(ai_reranker._request("prompt", ai_provider="duckai"), {})
        duck_request.assert_called_once()
        gemini_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
