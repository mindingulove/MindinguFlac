import unittest

import backend_kennyy


class BackendKennyyTests(unittest.TestCase):
    def test_rejects_same_isrc_result_credited_to_another_artist(self):
        items = [
            {
                "id": 350220289,
                "title": "Long Distance Love",
                "isrc": "UK9AV2502498",
                "performer": {"name": "Fink"},
            }
        ]

        selected = backend_kennyy._select_matching_item(
            items,
            "Long Distance Love",
            "Daryl Stuermer",
            "UK9AV2502498",
        )

        self.assertIsNone(selected)

    def test_selects_matching_artist_instead_of_first_search_result(self):
        items = [
            {
                "id": 350220289,
                "title": "Long Distance Love",
                "isrc": "UK9AV2502498",
                "performer": {"name": "Fink"},
            },
            {
                "id": 42,
                "title": "Long Distance Love",
                "isrc": "UK9AV2502498",
                "performer": {"name": "Daryl Stuermer"},
            },
        ]

        selected = backend_kennyy._select_matching_item(
            items,
            "Long Distance Love",
            "Daryl Stuermer",
            "UK9AV2502498",
        )

        self.assertEqual(selected["id"], 42)


if __name__ == "__main__":
    unittest.main()
