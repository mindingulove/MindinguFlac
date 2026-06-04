import os
import unittest
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
            {"id": 1, "title": "Artist - Song.flac", "source": "test", "seeders": 1, "score": 100},
            {"id": 2, "title": "Artist - Album - Song.flac", "source": "test", "seeders": 0, "score": 90},
        ]

        with patch.dict(os.environ, {"MINDINGUFLAC_AI_RERANK_PROVIDER": "duck_chat"}):
            with patch("ai_reranker._request", return_value={"ranked_ids": [2, "1", 99, "bad", 2]}):
                ranked = ai_reranker.rank_candidates(
                    {"artist": "Artist", "title": "Song", "album": "Album"},
                    candidates,
                )

        self.assertEqual(ranked, [2, 1])


if __name__ == "__main__":
    unittest.main()
