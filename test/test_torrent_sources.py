import unittest

import torrent_sources


class TorrentDownloadsTests(unittest.TestCase):
    def test_torrentdownloads_category_from_metadata_uses_genre(self):
        self.assertEqual(
            torrent_sources.torrentdownloads_category_from_metadata({"genre": "R&B / Soul"}),
            "72",
        )
        self.assertEqual(
            torrent_sources.torrentdownloads_category_from_metadata({"genres": ["Pop", "Dance"]}),
            "70",
        )

    def test_torrentdownloads_listing_parser_reads_music_rows(self):
        page = """
        <div class="grey_bar3">
          <p><img src="/icon.png"><a href="/torrent/123/Example-FLAC"
             title="View torrent info : Example Artist - Example Album [FLAC]">
             Example Artist - Example Album [FLAC]</a></p>
          <span class="health"><img src="/health.jpg"></span><span>36</span><span>95</span><span>352.60&nbsp;MB</span>
        </div>
        """

        rows = torrent_sources._torrentdownloads_parse_listing(page)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Example Artist - Example Album [FLAC]")
        self.assertEqual(rows[0]["seeders"], 36)
        self.assertEqual(rows[0]["leechers"], 95)
        self.assertEqual(rows[0]["size"], "352.60 MB")
        self.assertEqual(rows[0]["category"], "audio")
        self.assertIn("/torrent/123/Example-FLAC", rows[0]["detail_url"])


class LimeTorrentsTests(unittest.TestCase):
    def test_limetorrents_listing_parser_reads_music_rows(self):
        page = """
        <table>
          <tr bgcolor="#F4F4F4"><td class="tdleft"><div class="tt-name">
            <a href="http://itorrents.net/torrent/8CE081FF6E4719A68D0376A8EE3AA7C4F4BB00AF.torrent?title=Example" rel="nofollow"></a>
            <a href="/Example-Artist--Example-Song-torrent-210717.html">Example Artist - Example Song</a>
          </div></td>
          <td class="tdnormal">1 Year+ - in Music</td>
          <td class="tdnormal">14.17 MB</td>
          <td class="tdseed">12</td>
          <td class="tdleech">3</td></tr>
        </table>
        """

        rows = torrent_sources._limetorrents_parse_listing(page)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Example Artist - Example Song")
        self.assertEqual(rows[0]["seeders"], 12)
        self.assertEqual(rows[0]["leechers"], 3)
        self.assertEqual(rows[0]["size"], "14.17 MB")
        self.assertEqual(rows[0]["source"], "limetorrents")
        self.assertEqual(rows[0]["category"], "audio")
        self.assertIn("8CE081FF6E4719A68D0376A8EE3AA7C4F4BB00AF", rows[0]["magnet"])
        self.assertIn("itorrents.net/torrent/8CE081FF6E4719A68D0376A8EE3AA7C4F4BB00AF.torrent", rows[0]["torrent_url"])


class TorLockTests(unittest.TestCase):
    def test_torlock_listing_parser_reads_direct_magnets(self):
        page = """
        <table>
          <tr>
            <td><a href="/torrent/123/example.html">Example Artist - Example Album FLAC</a></td>
            <td>98.5 MB</td><td>21</td><td>4</td>
            <td><a href="magnet:?xt=urn:btih:1111111111111111111111111111111111111111&dn=Example+Artist">Magnet</a></td>
          </tr>
        </table>
        """

        rows = torrent_sources._torlock_parse_listing(page)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Example Artist - Example Album FLAC")
        self.assertEqual(rows[0]["size"], "98.5 MB")
        self.assertEqual(rows[0]["source"], "torlock")
        self.assertEqual(rows[0]["category"], "audio")
        self.assertIn("1111111111111111111111111111111111111111", rows[0]["magnet"])

    def test_torlock_detail_parser_uses_current_mirror(self):
        page = """
        <a href="/torrent/123/example.html">Example Artist - Example Album FLAC</a>
        """

        rows = torrent_sources._torlock_parse_detail_links(page, "https://www.torlock.top")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail_url"], "https://www.torlock.top/torrent/123/example.html")


if __name__ == "__main__":
    unittest.main()
