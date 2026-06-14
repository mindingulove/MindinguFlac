import unittest
from unittest.mock import patch

import music_metadata
import playlist_recommender


class MusicTasteRankingTests(unittest.TestCase):
    def test_search_relevance_boosts_tasted_track(self):
        base = {"type": "track", "title": "Song", "artist": "Artist", "track_key": "plain"}
        tasted = {"type": "track", "title": "Song", "artist": "Artist", "track_key": "tasted"}
        with patch.object(music_metadata.db, "get_taste_score_for_track", side_effect=lambda key: 20 if key == "tasted" else 0), \
             patch.object(music_metadata.db, "get_taste_score_for_artist", return_value=0):
            self.assertGreater(
                music_metadata.search_relevance("song", tasted)[0],
                music_metadata.search_relevance("song", base)[0],
            )

    def test_playlist_recommendations_exclude_queue_keys(self):
        playlist = {"id": "pl-1", "name": "Playlist", "tracks": []}
        candidates = [
            {"track_key": "keep", "title": "Keep", "artist": "Artist"},
            {"track_key": "skip", "title": "Skip", "artist": "Artist"},
        ]
        patches = [
            patch.object(playlist_recommender, "_load_playlists", return_value=[playlist]),
            patch.object(playlist_recommender, "_expand_catalog_items", return_value=candidates),
            patch.object(playlist_recommender.db, "save_playlist_recommendation_session"),
            patch.object(playlist_recommender.db, "touch_playlist_recommendation_session"),
            patch.object(playlist_recommender.db, "record_playlist_recommendation_feedback"),
            patch.object(playlist_recommender.db, "save_playlist_recommendation_cache"),
            patch.object(playlist_recommender.db, "get_playlist_recommendation_feedback", return_value=set()),
            patch.object(playlist_recommender.db, "get_playlist_recommendation_session_shown", return_value=set()),
            patch.object(playlist_recommender.db, "is_track_taste_hard_blacklisted", return_value=False),
            patch.object(playlist_recommender.db, "is_blacklisted", return_value=False),
            patch.object(playlist_recommender.db, "get_artist_affinity", return_value=None),
            patch.object(playlist_recommender.db, "get_genre_affinity", return_value=None),
            patch.object(playlist_recommender.db, "get_taste_score_for_track", return_value=0.0),
            patch.object(playlist_recommender.db, "get_taste_score_for_artist", return_value=0.0),
            patch.object(playlist_recommender.db, "is_track_taste_soft_blacklisted", return_value=False),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14]:
            result = playlist_recommender.generate_playlist_recommendations(
                "pl-1",
                limit=10,
                refresh=True,
                queue_track_keys={"skip"},
            )
        self.assertEqual([item["track_key"] for item in result["items"]], ["keep"])


if __name__ == "__main__":
    unittest.main()
