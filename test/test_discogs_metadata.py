import unittest
from unittest.mock import patch

from discogs_metadata import DiscogsClient


class DiscogsMetadataTests(unittest.TestCase):
    def test_vinyl_release_images_are_returned_from_best_matching_release(self):
        search_response = {
            "results": [
                {"id": 1, "title": "Various - Thriller Tribute", "format": ["Vinyl"], "year": "1983"},
                {"id": 2, "title": "Michael Jackson - Thriller", "format": ["Vinyl"], "year": "1982"},
            ]
        }
        release_response = {
            "id": 2,
            "title": "Thriller",
            "uri": "https://www.discogs.com/release/2",
            "images": [
                {"type": "primary", "uri": "https://i.discogs.com/front.jpg", "uri150": "front-small.jpg", "width": 1200, "height": 1200},
                {"type": "secondary", "uri": "https://i.discogs.com/insert.jpg", "uri150": "insert-small.jpg", "width": 900, "height": 900},
            ],
        }

        with patch.object(DiscogsClient, "_json", side_effect=[search_response, release_response]) as get_json:
            gallery = DiscogsClient("token").album_release_images("Michael Jackson", "Thriller", "1982")

        self.assertEqual(gallery["release_id"], "2")
        self.assertEqual([image["url"] for image in gallery["images"]], [
            "https://i.discogs.com/front.jpg",
            "https://i.discogs.com/insert.jpg",
        ])
        self.assertEqual(gallery["images"][1]["full_url"], "https://i.discogs.com/insert.jpg")
        self.assertEqual(gallery["images"][1]["width"], 900)
        self.assertEqual(get_json.call_args_list[1].args, ("releases/2",))


if __name__ == "__main__":
    unittest.main()
