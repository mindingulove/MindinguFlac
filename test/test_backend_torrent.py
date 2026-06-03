import unittest

import backend_torrent


class TestBackendTorrentHelpers(unittest.TestCase):
    def test_torrent_num_files_handles_missing_metadata(self):
        self.assertEqual(backend_torrent._torrent_num_files(None), 0)

    def test_torrent_num_files_handles_bad_objects(self):
        class BrokenInfo:
            def num_files(self):
                raise RuntimeError("boom")

        self.assertEqual(backend_torrent._torrent_num_files(BrokenInfo()), 0)


if __name__ == "__main__":
    unittest.main()
