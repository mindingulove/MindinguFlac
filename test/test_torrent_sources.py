import unittest
from unittest.mock import patch
from urllib.error import HTTPError

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


class X1337Tests(unittest.TestCase):
    def test_cloudflare_primary_falls_back_to_mirror_and_keeps_result_after_row_12(self):
        wanted = "The Jimi Hendrix Experience - Electric Ladyland (50th Anniversary Deluxe Edition) (2018) [3CD] FLAC"
        rows = []
        titles = [
            "The Electric State 2025 1080p WEB-DL FLAC",
            "Jimi Hendrix - Are You Experienced FLAC",
        ] + [f"Jimi Hendrix unrelated release {index} FLAC" for index in range(3, 15)]
        titles.append(wanted)
        for index, title in enumerate(titles, start=1):
            rows.append(
                f'<tr><td><a href="/torrent/{index}/release-{index}/">{title}</a></td>'
                f'<td class="coll-2 seeds">{1200 if index == 1 else 800 if index == 2 else 114 if title == wanted else 2}</td>'
                f'<td class="coll-3 leeches">{20 if title == wanted else 1}</td>'
                '<td class="coll-4 size">1.2 GB</td></tr>'
            )
        listing = "<table>" + "".join(rows) + "</table>"

        requested = []
        def fake_http(url, **_kwargs):
            requested.append(url)
            if "1337x.st" in url:
                raise HTTPError(url, 403, "Cloudflare challenge", {}, None)
            if "/search/" in url:
                return listing
            return 'href="magnet:?xt=urn:btih:' + f"{int(url.split('/torrent/')[1].split('/')[0]):040X}" + '"'

        with patch.object(torrent_sources, "_http", side_effect=fake_http):
            results = torrent_sources.search_1337x(
                "Jimi Hendrix Electric Ladyland FLAC", timeout=1,
                artist="Jimi Hendrix", album="Electric Ladyland",
                desktop_compact=True,
            )

        match = next(row for row in results if row["title"] == wanted)
        self.assertEqual((match["seeders"], match["leechers"]), (114, 20))
        self.assertTrue(match["magnet"].startswith("magnet:?xt=urn:btih:"))
        self.assertEqual(match["source"], "1337x")
        detail_requests = [url for url in requested if "/torrent/" in url]
        self.assertEqual(len(detail_requests), 1)
        self.assertIn("/torrent/15/", detail_requests[0])
        search_requests = [url for url in requested if "/search/" in url]
        self.assertEqual(len(search_requests), 1)  # one query on the accessible .la mirror
        self.assertIn("/search/Jimi%20Hendrix/1/", search_requests[0])

    def test_android_default_keeps_album_first_search_sequence(self):
        listing = (
            '<tr><td><a href="/torrent/1/release/">Jimi Hendrix - Electric Ladyland FLAC</a></td>'
            '<td class="coll-2 seeds">10</td><td class="coll-3 leeches">2</td>'
            '<td class="coll-4 size">1 GB</td></tr>'
        )
        requested = []

        def fake_http(url, **_kwargs):
            requested.append(url)
            if "/search/" in url:
                return listing
            return 'href="magnet:?xt=urn:btih:' + "1" * 40 + '"'

        with patch.object(torrent_sources, "_http", side_effect=fake_http):
            torrent_sources.search_1337x(
                "Jimi Hendrix Electric Ladyland FLAC", timeout=1,
                artist="Jimi Hendrix", album="Electric Ladyland",
            )

        first_search = next(url for url in requested if "/search/" in url)
        self.assertIn("/search/Electric%20Ladyland/1/", first_search)


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
