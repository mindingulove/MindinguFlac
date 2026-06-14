import unittest

from taste_profile import (
    calculate_score_delta,
    derive_status,
    extract_genres_from_metadata,
    normalize_artist_key,
    normalize_genre_key,
)


class TasteProfileTests(unittest.TestCase):
    def test_normalize_keys(self):
        self.assertEqual(normalize_artist_key("  Miles  Davis "), "miles davis")
        self.assertEqual(normalize_genre_key("R&B / Soul"), "r&b / soul")

    def test_score_thresholds(self):
        self.assertEqual(calculate_score_delta("play", 4), -5.0)
        self.assertEqual(calculate_score_delta("play", 10), -2.0)
        self.assertEqual(calculate_score_delta("play", 50), 1.0)
        self.assertEqual(calculate_score_delta("play", 80), 4.0)
        self.assertEqual(calculate_score_delta("complete", 98), 6.0)

    def test_status_thresholds(self):
        self.assertEqual(derive_status(20), "liked")
        self.assertEqual(derive_status(-20), "soft_blacklisted")
        self.assertEqual(derive_status(0), "neutral")
        self.assertEqual(derive_status(0, hard_blacklisted=True), "hard_blacklisted")

    def test_extract_genres(self):
        genres = extract_genres_from_metadata({
            "genres": ["Rock", "Classic Rock"],
            "album": {"genres": ["Rock"]},
        })
        self.assertIn("Rock", genres)
        self.assertIn("Classic Rock", genres)


if __name__ == "__main__":
    unittest.main()
