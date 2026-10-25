import unittest
from unittest.mock import patch

import video_sources as vs

AUDIO = "5fb524f1-8cc8-4c04-a921-e34c0a911ea7"
VIDEO = "3da16e5f-d50d-43a4-b35f-0e869afa0e01"
SONG = {"artist": "Nirvana", "title": "Smells Like Teen Spirit", "isrc": "USGF19942501",
        "musicbrainz_recording_id": AUDIO, "duration_s": 301, "spotify_id": "5ghIJDpPoe3CfHMGu71E6T"}


def _youtube_rel(video_id):
    return {"type": "free streaming", "url": {"resource": f"https://www.youtube.com/watch?v={video_id}"}}


class MusicBrainzTests(unittest.TestCase):
    def test_follows_the_music_video_relationship_to_its_youtube_link(self):
        responses = {
            f"recording/{AUDIO}": {"relations": [{"type": "music video", "recording": {
                "id": VIDEO, "title": "Smells Like Teen Spirit", "disambiguation": "official music video", "video": True}}]},
            f"recording/{VIDEO}": {"relations": [_youtube_rel("hTWKbfoikeg"),
                                                 {"type": "streaming", "url": {"resource": "https://tidal.com/video/1"}}]},
        }
        with patch.object(vs, "_musicbrainz", side_effect=lambda path, params: responses[path]):
            hit, seen = vs.musicbrainz_music_video(SONG)
        self.assertEqual(hit["video_id"], "hTWKbfoikeg")
        self.assertEqual(hit["source"], "musicbrainz")
        self.assertEqual(seen, [AUDIO, VIDEO])

    def test_searches_video_recordings_and_skips_live_versions(self):
        rows = [
            {"id": "live", "title": "Lovefool", "disambiguation": "live, 1996: Shepherds Bush Empire",
             "artist-credit": [{"name": "The Cardigans"}]},
            {"id": "clip", "title": "Lovefool", "disambiguation": "official music video",
             "artist-credit": [{"name": "The Cardigans"}]},
        ]
        calls = []

        def fake(path, params):
            calls.append(path)
            if path == "recording/":
                self.assertIn("video:true", params["query"])
                return {"recordings": rows}
            if path == "recording/clip":
                return {"relations": [_youtube_rel("nN7QA6pZXeA")]}
            if path == "recording/aud":
                return {"relations": []}
            raise AssertionError(f"unexpected {path}")

        song = {"artist": "The Cardigans", "title": "Lovefool", "musicbrainz_recording_id": "aud"}
        with patch.object(vs, "_musicbrainz", side_effect=fake):
            hit, _seen = vs.musicbrainz_music_video(song)
        self.assertEqual(hit["video_id"], "nN7QA6pZXeA")
        self.assertNotIn("recording/live", calls)

    def test_video_without_a_youtube_link_is_no_hit(self):
        with patch.object(vs, "_musicbrainz", side_effect=lambda path, params: (
                {"recordings": [{"id": "v", "title": "Lovefool", "disambiguation": "",
                                 "artist-credit": [{"name": "The Cardigans"}]}]} if path == "recording/" else {"relations": []})):
            hit, seen = vs.musicbrainz_music_video({"artist": "The Cardigans", "title": "Lovefool",
                                                    "musicbrainz_recording_id": "aud"})
        self.assertIsNone(hit)
        self.assertIn("v", seen)


class WikidataAndOdesliTests(unittest.TestCase):
    def test_wikidata_queries_by_isrc_and_recording_ids(self):
        captured = {}

        def fake(url, headers=None, data=None, timeout=12):
            captured["query"] = data.decode()
            return {"results": {"bindings": [{"yt": {"value": "hTWKbfoikeg"}}]}}

        with patch.object(vs, "_get_json", side_effect=fake):
            hit = vs.wikidata_music_video(SONG, [AUDIO])
        self.assertEqual(hit["video_id"], "hTWKbfoikeg")
        self.assertIn("USGF19942501", captured["query"])
        self.assertIn(AUDIO, captured["query"])

    def _odesli(self, channel, title="Nirvana - Smells Like Teen Spirit (Official Music Video)"):
        payload = {
            "linksByPlatform": {"youtube": {"url": "https://www.youtube.com/watch?v=hTWKbfoikeg", "entityUniqueId": "YOUTUBE_VIDEO::x"}},
            "entitiesByUniqueId": {"YOUTUBE_VIDEO::x": {"artistName": channel, "title": title}},
        }
        with patch.object(vs, "_get_json", return_value=payload):
            return vs.odesli_music_video(SONG, api_key="key")

    def test_odesli_returns_the_official_video(self):
        self.assertEqual(self._odesli("Nirvana")["video_id"], "hTWKbfoikeg")

    def test_odesli_refuses_auto_generated_topic_audio(self):
        self.assertIsNone(self._odesli("Nirvana - Topic", "Smells Like Teen Spirit"))

    def test_odesli_is_skipped_without_an_api_key(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(vs, "_get_json") as get:
            self.assertIsNone(vs.odesli_music_video(SONG))
        get.assert_not_called()


class ChainOrderTests(unittest.TestCase):
    def test_musicbrainz_first_then_wikidata_then_odesli(self):
        order = []
        with patch.object(vs, "musicbrainz_music_video", side_effect=lambda i: (order.append("mb"), (None, ["r"]))[1]), \
                patch.object(vs, "wikidata_music_video", side_effect=lambda i, ids: (order.append(("wd", ids)), None)[1]), \
                patch.object(vs, "odesli_music_video", side_effect=lambda i, k: (order.append("od"), vs._hit("odesli", "abcdefghijk"))[1]):
            hit = vs.curated_music_video(SONG, odesli_api_key="key")
        self.assertEqual(order, ["mb", ("wd", ["r"]), "od"])
        self.assertEqual(hit["source"], "odesli")

    def test_a_failing_source_falls_through_to_the_next(self):
        with patch.object(vs, "musicbrainz_music_video", side_effect=OSError("503")), \
                patch.object(vs, "wikidata_music_video", return_value=vs._hit("wikidata", "hTWKbfoikeg")):
            self.assertEqual(vs.curated_music_video(SONG)["source"], "wikidata")


if __name__ == "__main__":
    unittest.main()
