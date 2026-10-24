import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backend_monochrome


# test_android_runtime starts the real Android bootstrap in-process, which sets
# MINDINGUFLAC_ANDROID=1 for the rest of the run. These are desktop tests
# (Android cases opt in explicitly), so run them without it.
_saved_android_flag = None


def setUpModule():
    global _saved_android_flag
    import os
    _saved_android_flag = os.environ.pop("MINDINGUFLAC_ANDROID", None)


def tearDownModule():
    import os
    if _saved_android_flag is not None:
        os.environ["MINDINGUFLAC_ANDROID"] = _saved_android_flag


class _Response:
    def __init__(self, payload=None, chunks=(), headers=None, status_code=200):
        self.payload = payload or {}
        self.chunks = chunks
        self.headers = headers or {"Content-Length": str(sum(map(len, chunks)))}
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=65536):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Manager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_flags = set()
        self.events = []

    def _append_cache_event(self, job, kind, message):
        self.events.append((kind, message))


class _FetchSession:
    """Fake HTTP/2 session for native_audio._MonochromeFetch (no network)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, stream=False, timeout=None):
        self.calls.append((url, dict(headers or {})))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        pass


def _patched_fetch(responses):
    """Route library downloads through a fake fetch session; returns (session, patchers)."""
    import native_audio

    session = _FetchSession(responses)
    for fetch in list(native_audio._monochrome_fetches.values()):
        fetch.cancel()  # also deletes its temp file
    native_audio._monochrome_fetches.clear()
    return session, [patch.object(native_audio._MonochromeFetch, "_session", lambda self: session),
                     patch.object(native_audio.time, "sleep")]


class MonochromeBackendTests(unittest.TestCase):
    def test_compilation_edit_maps_to_verified_studio_album_without_changing_album(self):
        row = {'id': '173847391828508672', 'title': 'One Of Us', 'artistNames': ['Joan Osborne'],
               'isrc': 'USPR39500200', 'duration': 320466}
        records = {
            'USPR39507368': [{'id': 'edit', 'title': 'One of Us (edit)', 'length': 256453, 'artist-credit': [{'name': 'Joan Osborne'}]}],
            'USPR39500200': [{'id': 'album-take', 'title': 'One of Us', 'length': 320133, 'artist-credit': [{'name': 'Joan Osborne'}]}],
        }
        details = {
            'edit': {'relations': [{'type': 'performance', 'work': {'id': 'same-work'}}]},
            'album-take': {'relations': [{'type': 'performance', 'work': {'id': 'same-work'}}],
                          'releases': [{'title': 'Relish', 'release-group': {'primary-type': 'Album', 'secondary-types': []}}]},
        }
        job = {'id': 'job', 'title': 'One Of Us', 'artist': 'Joan Osborne', 'album': 'Hits Of The 90s',
               'isrc': 'USPR39507368', 'mode': 'stream', 'metadata': {'duration_ms': 256320,
               'is_compilation': True, 'album_artist': 'Various Artists', 'album_spotify_id': 'compilation-id'}}
        manager = _Manager()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, '_search_items', return_value=[row]), \
                patch.object(backend_monochrome, '_musicbrainz_isrc_title', return_value='One of Us (edit)'), \
                patch.object(backend_monochrome, '_musicbrainz_isrc_recordings', side_effect=lambda code: records.get(code, [])), \
                patch.object(backend_monochrome, '_recording_details', side_effect=lambda key: details.get(key, {})):
            backend_monochrome.run(Path(tmp), job, manager)
            self.assertEqual(job['status'], 'finished')
            self.assertEqual(job['isrc'], 'USPR39500200')
            self.assertEqual(job['metadata']['requested_isrc'], 'USPR39507368')
            self.assertEqual(job['metadata']['album_spotify_id'], 'compilation-id')
            self.assertEqual(job['metadata']['source_album'], 'Relish')
            self.assertEqual(job['album'], 'Hits Of The 90s')
            # A title/artist match alone, or only a compilation release, is
            # insufficient even though the provider row has a plausible length.
            details['album-take']['relations'][0]['work']['id'] = 'other-work'
            self.assertIsNone(backend_monochrome._select_compilation_album_item([row], 'One Of Us', 'Joan Osborne', 'USPR39507368', 256320))
            details['album-take']['relations'][0]['work']['id'] = 'same-work'
            details['album-take']['releases'][0]['release-group']['secondary-types'] = ['Compilation']
            self.assertIsNone(backend_monochrome._select_compilation_album_item([row], 'One Of Us', 'Joan Osborne', 'USPR39507368', 256320))

    def test_alternate_catalog_isrc_uses_shared_recording_identity(self):
        candidate = {'id': '123', 'title': 'Save Tonight', 'artists': [{'name': 'Eagle-Eye Cherry'}],
                     'isrc': 'USSM10027246', 'duration': 239226}
        same = {'id': 'shared-recording', 'title': 'Save Tonight', 'length': 236000,
                'artist-credit': [{'name': 'Eagle‐Eye Cherry'}]}
        records = {'GBAKW0201563': [same], 'USSM10027246': [same]}
        with patch.object(backend_monochrome, '_musicbrainz_isrc_recordings', side_effect=lambda code: records.get(code, [])):
            match = backend_monochrome._select_equivalent_recording_item([candidate], 'Save Tonight - 7" Mix',
                        'Eagle-Eye Cherry', 'GBAKW0201563', 230520)
            self.assertIsNotNone(match)
            self.assertEqual(match['_recording_match_kind'], 'same_recording')
            records['USSM10027246'] = [{**same, 'id': 'different-remix'}]
            self.assertIsNone(backend_monochrome._select_equivalent_recording_item([candidate], 'Save Tonight - 7" Mix',
                        'Eagle-Eye Cherry', 'GBAKW0201563', 230520))
            records['USSM10027246'] = [same]
            candidate['artists'] = [{'name': 'Cover Band'}]
            self.assertIsNone(backend_monochrome._select_equivalent_recording_item([candidate], 'Save Tonight - 7" Mix',
                        'Eagle-Eye Cherry', 'GBAKW0201563', 230520))

    def tearDown(self):
        import native_audio
        for fetch in list(native_audio._monochrome_fetches.values()):
            fetch.cancel()
        native_audio._monochrome_fetches.clear()

    def _fetch_with(self, responses):
        import native_audio
        session, patchers = _patched_fetch(responses)
        with patchers[0], patchers[1]:
            fetch = native_audio._monochrome_fetch("https://tracks.monochrome.st/track/resume-test")
            fetch.thread.join(timeout=5)
        return fetch, session

    def test_resume_that_restarts_at_byte_zero_skips_the_overlap(self):
        body = bytes(range(256)) * 400  # 102400 distinct-ish bytes
        cut = 60000

        class Dropped(_Response):
            def iter_content(self, chunk_size=65536):
                yield body[:cut]
                raise ConnectionError("HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR")

        fetch, session = self._fetch_with([
            Dropped(headers={"Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}"}, status_code=206),
            # The server ignores the requested offset and starts again at 0.
            _Response(chunks=[body], headers={"Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}"}, status_code=206),
        ])
        self.assertTrue(fetch.done, fetch.error)
        self.assertEqual(fetch.path.read_bytes(), body)
        self.assertEqual(session.calls[1][1]["Range"], f"bytes={cut}-")

    def test_resume_that_starts_after_the_offset_is_not_spliced(self):
        body = b"x" * 100000

        class Dropped(_Response):
            def iter_content(self, chunk_size=65536):
                yield body[:40000]
                raise ConnectionError("reset")

        gap = _Response(chunks=[body[50000:]], headers={"Content-Range": f"bytes 50000-99999/{len(body)}"}, status_code=206)
        fetch, _session = self._fetch_with([
            Dropped(headers={"Content-Range": f"bytes 0-99999/{len(body)}"}, status_code=206),
            gap, gap, gap,
        ])
        self.assertFalse(fetch.done)
        self.assertTrue(fetch.error)
        self.assertEqual(fetch.size, 40000)  # nothing from the wrong offset was written

    def test_early_clean_close_is_resumed_not_marked_done(self):
        body = b"y" * 90000
        fetch, session = self._fetch_with([
            _Response(chunks=[body[:30000]], headers={"Content-Range": f"bytes 0-89999/{len(body)}"}, status_code=206),
            _Response(chunks=[body[30000:]], headers={"Content-Range": f"bytes 30000-89999/{len(body)}"}, status_code=206),
        ])
        self.assertTrue(fetch.done)
        self.assertEqual(fetch.path.read_bytes(), body)
        self.assertEqual(len(session.calls), 2)

    def test_full_decode_rejects_a_spliced_flac(self):
        import subprocess
        from native_audio import _ffmpeg_exe
        ffmpeg = _ffmpeg_exe()
        if not ffmpeg:
            self.skipTest("ffmpeg not available")
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.flac"
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=20:a=0.3", "-ac", "2",
                            "-ar", "44100", str(good)], check=True)
            self.assertEqual(backend_monochrome._decode_error(good), "")
            data = good.read_bytes()
            spliced = Path(tmp) / "spliced.flac"
            # Same size, but the second half is bytes from the start: the
            # damage a mis-positioned resume produces.
            half = len(data) // 2
            spliced.write_bytes(data[:half] + data[1000:1000 + len(data) - half])
            self.assertTrue(backend_monochrome._decode_error(spliced))

    _MISSING_ROWS = [  # real Monochrome search rows for "Missing Everything But The Girl"
        {"id": "1", "title": "Missing", "artistNames": ["Everything But The Girl"], "isrc": "GBAHT9400251", "duration": 247200},
        {"id": "2", "title": "Missing - Todd Terry Club Mix", "artistNames": ["Everything But The Girl", "Todd Terry"], "isrc": "GBAHT0109010", "duration": 296560},
        {"id": "3", "title": "Missing - Todd Terry Remix", "artistNames": ["Everything But The Girl", "Todd Terry"], "isrc": "UKLT91300051", "duration": 236293},
        {"id": "4", "title": "Missing - 2013 Remaster", "artistNames": ["Everything But The Girl"], "isrc": "UKLT91300041", "duration": 247200},
        {"id": "5", "title": "Missing - Todd Terry Club Mix / US Radio Edit", "artistNames": ["Everything But The Girl", "Todd Terry"], "isrc": "GBAHT1300332", "duration": 249533},
    ]

    def test_unnamed_spotify_remix_matches_the_version_musicbrainz_names(self):
        rows = self._MISSING_ROWS
        self.assertIsNone(backend_monochrome._select_matching_item(
            rows, "Missing", "Everything But The Girl", "GBAHT9601125", 234600))
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title",
                          return_value="Missing (Todd Terry club mix, Ben Watt\u2019s \u2018Blanco\u2013Eternal\u2019 radio edit)"):
            selected = backend_monochrome._select_named_version(
                rows, "Missing", "Everything But The Girl", "GBAHT9601125", 234600)
        self.assertEqual(selected["id"], "3")

    def test_named_version_needs_musicbrainz_to_name_a_version(self):
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title", return_value="Missing"):
            self.assertIsNone(backend_monochrome._select_named_version(
                self._MISSING_ROWS, "Missing", "Everything But The Girl", "GBAHT9601125", 234600))

    def test_named_version_never_picks_a_different_remixer_on_length_alone(self):
        rows = [{"id": "k", "title": "Missing - Kenny Dope Remix", "artistNames": ["Everything But The Girl"],
                 "isrc": "X", "duration": 234900}]
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title",
                          return_value="Missing (Todd Terry club mix, radio edit)"):
            self.assertIsNone(backend_monochrome._select_named_version(
                rows, "Missing", "Everything But The Girl", "GBAHT9601125", 234600))

    def test_split_version_ignores_generic_words(self):
        self.assertEqual(backend_monochrome._split_version("Missing - Todd Terry Remix"), ("missing", {"todd", "terry"}))
        self.assertEqual(backend_monochrome._split_version("Missing - 2013 Remaster"), ("missing", set()))
        self.assertEqual(backend_monochrome._split_version("Song (25th Anniversary Remastered Edition)")[1], set())

    def _resolve(self, rows, mb_title, duration_ms, isrc="GBAHT9601125"):
        match = backend_monochrome._select_matching_item(rows, "Missing", "Everything But The Girl", isrc, duration_ms)
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title", return_value=mb_title) as lookup:
            result = backend_monochrome._resolve_version(rows, match, "Missing", "Everything But The Girl", isrc, duration_ms)
        return result, lookup

    def test_remix_present_and_musicbrainz_names_it_plays_the_remix_not_the_original(self):
        # Same-length original exists, but the ISRC is the Todd Terry edit.
        rows = [dict(self._MISSING_ROWS[0], duration=234600)] + self._MISSING_ROWS[1:]
        (selected, reason), _ = self._resolve(rows, "Missing (Todd Terry club mix, radio edit)", 234600)
        self.assertEqual(selected["id"], "3")

    def test_remix_present_but_musicbrainz_names_the_plain_song_keeps_the_original(self):
        rows = [dict(self._MISSING_ROWS[0], duration=247000)] + self._MISSING_ROWS[1:]
        (selected, reason), lookup = self._resolve(rows, "Missing", 247000)
        self.assertEqual(selected["id"], "1")
        lookup.assert_called_once()

    def test_version_named_by_musicbrainz_but_missing_on_monochrome_is_refused(self):
        rows = [dict(self._MISSING_ROWS[0], duration=234600), self._MISSING_ROWS[3]]
        rows.append({"id": "k", "title": "Missing - Kenny Dope Remix", "artistNames": ["Everything But The Girl"],
                     "isrc": "Y", "duration": 300000})
        (selected, reason), _ = self._resolve(rows, "Missing (Todd Terry club mix, radio edit)", 234600)
        self.assertIsNone(selected)
        self.assertIn("not on Monochrome", reason)

    def test_exact_isrc_hit_skips_the_musicbrainz_check(self):
        rows = self._MISSING_ROWS
        (selected, reason), lookup = self._resolve(rows, "Missing (whatever)", 247200, isrc="GBAHT9400251")
        self.assertEqual(selected["id"], "1")
        lookup.assert_not_called()

    def test_no_remix_in_results_needs_no_musicbrainz_check(self):
        rows = [self._MISSING_ROWS[0]]
        match = backend_monochrome._select_matching_item(rows, "Missing", "Everything But The Girl", "", 247200)
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title") as lookup:
            selected, _ = backend_monochrome._resolve_version(rows, match, "Missing", "Everything But The Girl", "", 247200)
        self.assertEqual(selected["id"], "1")
        lookup.assert_not_called()

    _SO_FAR_AWAY = [  # real Monochrome search rows
        {"id": "161", "title": "So Far Away", "artistNames": ["Dire Straits"], "isrc": "GBF088500673", "duration": 312133},
    ]

    def test_remaster_label_matches_the_plain_title_without_an_isrc(self):
        # Android sent no ISRC: only the title can match, and Spotify's says
        # "So Far Away - Remastered 1996" while Monochrome's says "So Far Away".
        selected = backend_monochrome._select_matching_item(
            self._SO_FAR_AWAY, "So Far Away - Remastered 1996", "Dire Straits", "", 306373)
        self.assertEqual(selected["id"], "161")

    def test_so_far_away_remaster_matches_catalog_isrc_with_duration_offset(self):
        # Spotify's regional remaster has a different ISRC and reports 5.76 s
        # less than Monochrome's full-version entry for the same recording.
        rows = [{"id": "161", "title": "So Far Away", "artistNames": ["Dire Straits"],
                 "isrc": "GBF088500673", "duration": 312133}]
        selected = backend_monochrome._select_matching_item(
            rows, "So Far Away - Remastered 1996", "Dire Straits", "GBUM72102498", 306373)
        self.assertEqual(selected["id"], "161")

    def test_live_edit_and_remix_labels_are_still_different_songs(self):
        for label in ("Live", "Radio Edit", "Todd Terry Remix", "Live at Wembley 1985", "Acoustic"):
            self.assertIsNone(backend_monochrome._select_matching_item(
                self._SO_FAR_AWAY, f"So Far Away - {label}", "Dire Straits", "", 306373), label)

    def test_remastered_versions_in_results_do_not_trigger_a_refusal(self):
        rows = self._SO_FAR_AWAY + [{"id": "r", "title": "So Far Away - 2011 Remaster", "artistNames": ["Dire Straits"],
                                     "isrc": "OTHER", "duration": 306000}]
        match = backend_monochrome._select_matching_item(rows, "So Far Away", "Dire Straits", "SPOTIFYISRC", 306373)
        with patch.object(backend_monochrome, "_musicbrainz_isrc_title", return_value="So Far Away (remastered 1996)"):
            selected, reason = backend_monochrome._resolve_version(rows, match, "So Far Away", "Dire Straits", "SPOTIFYISRC", 306373)
        self.assertIsNotNone(selected, reason)

    def test_search_uses_current_monochrome_tracks_api(self):
        response = _Response({"tracks": [{"id": "12345678901234567", "title": "Time"}]})
        get = unittest.mock.Mock(return_value=response)
        request = SimpleNamespace(get=get)

        rows = backend_monochrome._search_items(request, "Pink Floyd Time")

        self.assertEqual(rows[0]["title"], "Time")
        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://tracks.monochrome.st/search/tracks")
        self.assertEqual(kwargs["params"], {"q": "Pink Floyd Time", "limit": 50})
        self.assertEqual(kwargs["headers"]["Origin"], "https://monochrome.st")

    def test_matching_requires_exact_artist_and_title(self):
        rows = [
            {"id": "1", "title": "Time", "artistNames": ["Pink Floyd Tribute"]},
            {"id": "2", "title": "Time (Live)", "artistNames": ["Pink Floyd"]},
            {"id": "3", "title": "Time", "artistNames": ["Pink Floyd"]},
        ]
        selected = backend_monochrome._select_matching_item(rows, "Time", "Pink Floyd", "")
        self.assertEqual(selected["id"], "3")

    def test_isrc_match_wins_and_wrong_recordings_are_rejected(self):
        rows = [
            {"id": "1", "title": "Time", "artistNames": ["Pink Floyd"], "isrc": "WRONG"},
            {"id": "2", "title": "Time (Live)", "artistNames": ["Pink Floyd Tribute"],
             "isrc": "GBN9Y1100079"},
        ]
        selected = backend_monochrome._select_matching_item(rows, "Time", "Pink Floyd", "GBN9Y1100079")
        self.assertEqual(selected["id"], "2")
        self.assertIsNone(backend_monochrome._select_matching_item(rows[:1], "Time", "Pink Floyd", "GBN9Y1100079"))

    def test_reissue_with_new_isrc_matches_when_length_is_the_same(self):
        # Real search rows: Spotify has the 2005 remaster ISRC, Monochrome
        # the 1982 release; same title, artist and length.
        rows = [
            {"id": "1", "title": "Eye In The Sky", "artistNames": ["The Alan Parsons Project"],
             "isrc": "USAR18200010", "duration": 276400},
            {"id": "2", "title": "Eye In The Sky", "artistNames": ["The Alan Parsons Project"],
             "isrc": "USAR18200010", "duration": 276280},
            {"id": "3", "title": "Eye in the Sky - Single Edit", "artistNames": ["The Alan Parsons Project"],
             "isrc": "USQX91701694", "duration": 236520},
        ]
        selected = backend_monochrome._select_matching_item(
            rows, "Eye In The Sky", "The Alan Parsons Project", "USAR10500379", 276280)
        self.assertEqual(selected["id"], "2")

    def test_same_title_with_new_isrc_and_different_length_is_rejected(self):
        live = [{"id": "1", "title": "Time", "artistNames": ["Pink Floyd"], "isrc": "LIVE0001", "duration": 470000}]
        self.assertIsNone(backend_monochrome._select_matching_item(live, "Time", "Pink Floyd", "GBN9Y1100079", 413000))

    def test_compilation_can_use_a_verified_original_album_recording(self):
        rows = [{"id": "155103623456493568", "title": "Hungry Like the Wolf - 2009 Remaster",
                 "artistNames": ["Duran Duran"], "isrc": "GBAYE0901090", "duration": 220626},
                {"id": "2", "title": "Hungry Like the Wolf - Night Version; 2009 Remaster",
                 "artistNames": ["Duran Duran"], "isrc": "GBAYE0901101", "duration": 311613}]
        recordings = {
            "GBAYE8200051": [{"title": "Hungry Like the Wolf", "length": 209546, "artist-credit": [{"name": "Duran Duran"}]}],
            "GBAYE0901090": [{"id": "original-album", "title": "Hungry Like the Wolf", "length": 220626,
                "disambiguation": "original album version", "artist-credit": [{"name": "Duran Duran"}]}],
        }
        self.assertIsNone(backend_monochrome._select_matching_item(rows, "Hungry Like the Wolf", "Duran Duran", "GBAYE8200051", 209546))
        with patch.object(backend_monochrome, "_musicbrainz_isrc_recordings", side_effect=lambda isrc: recordings.get(isrc, [])):
            selected = backend_monochrome._select_original_album_item(rows, "Hungry Like the Wolf", "Duran Duran", "GBAYE8200051", 209546)
        self.assertEqual(selected["isrc"], "GBAYE0901090")
        self.assertEqual(selected["_original_recording_id"], "original-album")

    def test_original_album_stream_preserves_requested_edition_and_actual_isrc(self):
        selected = {"id": "155103623456493568", "title": "Hungry Like the Wolf - 2009 Remaster",
                    "artistNames": ["Duran Duran"], "isrc": "GBAYE0901090", "duration": 220626,
                    "_original_recording_id": "original-album"}
        job = {"id": "job", "title": "Hungry Like the Wolf", "artist": "Duran Duran", "album": "Greatest",
               "mode": "stream", "isrc": "GBAYE8200051", "metadata": {"isrc": "GBAYE8200051", "duration_ms": 209546}}
        manager = _Manager()
        with tempfile.TemporaryDirectory() as tmp, \
                patch("requests.get", return_value=_Response({"tracks": [selected]})), \
                patch.object(backend_monochrome, "_resolve_version", return_value=(None, "")), \
                patch.object(backend_monochrome, "_select_original_album_item", return_value=selected):
            backend_monochrome.run(Path(tmp), job, manager)
        self.assertEqual(job["status"], "finished")
        self.assertTrue(job["direct_stream"])
        self.assertEqual(job["metadata"]["requested_isrc"], "GBAYE8200051")
        self.assertEqual(job["metadata"]["isrc"], "GBAYE0901090")
        self.assertEqual(job["metadata"]["duration_ms"], 220626)
        self.assertEqual(job["album"], "Greatest")

    def test_original_album_fallback_needs_evidence_and_rejects_named_versions(self):
        rows = [{"id": "1", "title": "Song", "artistNames": ["Artist"], "isrc": "OTHER", "duration": 220000}]
        with patch.object(backend_monochrome, "_musicbrainz_isrc_recordings", return_value=[]):
            self.assertIsNone(backend_monochrome._select_original_album_item(rows, "Song", "Artist", "REQUESTED", 209000))
            self.assertIsNone(backend_monochrome._select_original_album_item(rows, "Song - Radio Edit", "Artist", "REQUESTED", 209000))
            self.assertIsNone(backend_monochrome._select_original_album_item(rows, "Song (Live)", "Artist", "REQUESTED", 209000))

    def test_monochrome_download_enriches_missing_isrc_even_with_genres(self):
        import service_downloader

        metadata = {"genres": ["rock"]}
        with patch("music_metadata.enrich_track_identifiers",
                   return_value={"isrc": "GBN9Y1100079"}) as enrich:
            result = service_downloader._enrich_download_metadata_for_search(
                {"artist": "Pink Floyd", "title": "Time", "metadata": metadata},
                "monochrome", metadata)
        self.assertEqual(result["isrc"], "GBN9Y1100079")
        enrich.assert_called_once()

    def test_run_downloads_matched_track_from_monochrome_track_endpoint(self):
        selected = {
            "id": "154140608489852928", "trackId": "154140608489852928",
            "title": "Time", "artistNames": ["Pink Floyd"], "isrc": "GBN9Y1100079",
        }
        api_response = _Response({"tracks": [selected]})
        flac = b"fLaC" + b"test audio bytes"
        session, patchers = _patched_fetch([_Response(chunks=[flac], status_code=206,
                                                      headers={"Content-Range": f"bytes 0-{len(flac) - 1}/{len(flac)}"})])
        manager = _Manager()
        job = {"id": "job", "title": "Time", "artist": "Pink Floyd", "mode": "download", "quality": "LOSSLESS"}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", (("https://tracks.monochrome.st", "https://monochrome.st"),)), \
                patch("requests.get", side_effect=[api_response]) as get, \
                patch("service_downloader.is_valid_audio_file", return_value=True), \
                patch.object(backend_monochrome, "_decode_error", return_value=""), \
                patchers[0], patchers[1]:
            backend_monochrome.run(Path(tmp), job, manager)
            output = Path(tmp) / "Time - Pink Floyd.flac"
            self.assertEqual(output.read_bytes(), flac)
            self.assertEqual(job["progress"], 100)
            self.assertEqual(job["active_audio_path"], str(output))
            self.assertEqual(job["active_audio_ready_bytes"], len(flac))
            self.assertEqual(job["active_audio_size"], len(flac))
            self.assertTrue(job["resolved_url"].endswith("/track/154140608489852928"))

        self.assertEqual(get.call_args_list[0].args[0], "https://tracks.monochrome.st/search/tracks")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["q"], "Time Pink Floyd")
        url, headers = session.calls[0]
        self.assertEqual(url, "https://tracks.monochrome.st/track/154140608489852928")
        self.assertEqual(headers["Range"], "bytes=0-")
        self.assertEqual(headers["Sec-Fetch-Dest"], "audio")
        self.assertTrue(headers["X-Playback-Session-Id"])
        self.assertEqual(len(session.calls), 1)

    def test_run_resumes_interrupted_monochrome_download_with_range(self):
        selected = {"id": "154140608489852928", "title": "Time", "artistNames": ["Pink Floyd"]}
        first_chunk = b"fLaC" + b"a" * 120_000
        second_chunk = b"b" * 80_000

        class InterruptedResponse(_Response):
            def iter_content(self, chunk_size=65536):
                yield first_chunk
                raise ConnectionError("incomplete response")

        session, patchers = _patched_fetch([
            InterruptedResponse(chunks=(), headers={"Content-Range": "bytes 0-200003/200004"}, status_code=206),
            _Response(chunks=[second_chunk], headers={"Content-Range": "bytes 120004-200003/200004"}, status_code=206),
        ])
        manager = _Manager()
        job = {"id": "job", "title": "Time", "artist": "Pink Floyd", "mode": "download"}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", (("https://tracks.monochrome.st", "https://monochrome.st"),)), \
                patch("requests.get", side_effect=[_Response({"tracks": [selected]})]), \
                patch("service_downloader.is_valid_audio_file", return_value=True), \
                patch.object(backend_monochrome, "_decode_error", return_value=""), \
                patchers[0], patchers[1]:
            backend_monochrome.run(Path(tmp), job, manager)
            output = Path(tmp) / "Time - Pink Floyd.flac"
            self.assertEqual(output.read_bytes(), first_chunk + second_chunk)
            self.assertEqual(job["active_audio_ready_bytes"], output.stat().st_size)

        self.assertEqual([headers["Range"] for _, headers in session.calls],
                         ["bytes=0-", f"bytes={len(first_chunk)}-"])

    def test_run_fails_over_to_next_official_instance(self):
        selected = {"id": "12345678901234567", "title": "Time", "artistNames": ["Pink Floyd"]}
        unavailable = RuntimeError("primary unavailable")
        api_response = _Response({"tracks": [selected]})
        session, patchers = _patched_fetch([_Response(chunks=[b"fLaCtest audio bytes"], status_code=200,
                                                      headers={"Content-Length": "20"})])
        manager = _Manager()
        job = {"id": "job", "title": "Time", "artist": "Pink Floyd", "mode": "download"}
        instances = (("https://primary.example", "https://monochrome.st"),
                     ("https://backup.example", "https://monochrome.st"))

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", instances), \
                patch("requests.get", side_effect=[unavailable, api_response]) as get, \
                patch("service_downloader.is_valid_audio_file", return_value=True), \
                patch.object(backend_monochrome, "_decode_error", return_value=""), \
                patchers[0], patchers[1]:
            backend_monochrome.run(Path(tmp), job, manager)
            self.assertTrue((Path(tmp) / "Time - Pink Floyd.flac").exists())

        self.assertEqual(get.call_args_list[0].args[0], "https://primary.example/search/tracks")
        self.assertEqual(get.call_args_list[1].args[0], "https://backup.example/search/tracks")
        self.assertEqual(session.calls[0][0], "https://backup.example/track/12345678901234567")

    def test_stream_mode_resolves_direct_url_without_downloading_audio(self):
        selected = {"id": "154140608489852928", "title": "Time", "artistNames": ["Pink Floyd"]}
        api_response = _Response({"tracks": [selected]})
        manager = _Manager()
        job = {"id": "job", "title": "Time", "artist": "Pink Floyd", "mode": "stream"}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", (("https://tracks.monochrome.st", "https://monochrome.st"),)), \
                patch("requests.get", return_value=api_response) as get:
            backend_monochrome.run(Path(tmp), job, manager)

        self.assertTrue(job["direct_stream"])
        self.assertEqual(job["status"], "finished")
        self.assertEqual(job["resolved_url"], "https://tracks.monochrome.st/track/154140608489852928")
        self.assertEqual(get.call_count, 1)
        self.assertIn("streaming directly", manager.events[-1][1])

    def test_stream_search_tries_isrc_before_title_and_artist(self):
        selected = {
            "id": "154140608489852928", "title": "Welcome to the Machine (Remastered)",
            "artistNames": ["Pink Floyd"], "isrc": "GBN9Y1100079",
        }
        api_response = _Response({"tracks": [selected]})
        manager = _Manager()
        job = {
            "id": "job", "title": "Welcome to the Machine", "artist": "Pink Floyd",
            "isrc": "GBN9Y1100079", "mode": "stream",
        }

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", (("https://tracks.monochrome.st", "https://monochrome.st"),)), \
                patch("requests.get", return_value=api_response) as get:
            backend_monochrome.run(Path(tmp), job, manager)

        self.assertEqual(get.call_args.kwargs["params"]["q"], "GBN9Y1100079")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(job["status"], "finished")

    def test_stream_rejection_cooldown_and_stream_headers(self):
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            self.assertEqual(backend_monochrome.stream_block_reason(), "")
            backend_monochrome.note_stream_rejected(500)
            self.assertEqual(backend_monochrome.stream_block_reason(), "")
            backend_monochrome.note_stream_rejected(403)
            self.assertIn("HTTP 403", backend_monochrome.stream_block_reason())
        headers = backend_monochrome.stream_request_headers()
        self.assertEqual(headers["Origin"], "https://monochrome.st")
        self.assertEqual(headers["Sec-Fetch-Dest"], "audio")
        self.assertIn("X-Playback-Session-Id", headers)
        self.assertNotIn("Connection", headers)

    def test_repeated_browser_stream_failures_start_cooldown(self):
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            backend_monochrome.note_stream_failing()
            reason = backend_monochrome.stream_block_reason()
        self.assertIn("kept failing", reason)
        self.assertNotIn("HTTP", reason)

    def test_requested_engine_falls_back_to_youtube_while_blocked(self):
        from service_downloader import ServiceDownloadManager

        manager = ServiceDownloadManager.__new__(ServiceDownloadManager)
        manager.config = SimpleNamespace(download_engine="monochrome", download_service="tidal", default_quality="LOSSLESS")
        payload = {"engine": "monochrome", "service": "tidal", "quality": "LOSSLESS"}
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            self.assertEqual(manager._requested_engine(payload)[0], "monochrome")
            backend_monochrome.note_stream_rejected(429)
            self.assertEqual(manager._requested_engine(payload), ("ytp-dl", "youtube", "best"))

    def test_download_403_fails_without_retrying(self):
        selected = {"id": "154140608489852928", "title": "Song", "artistNames": ["Artist"]}
        manager = _Manager()
        job = {"id": "job", "title": "Song", "artist": "Artist", "mode": "download"}
        session, patchers = _patched_fetch([_Response(status_code=403, headers={})])
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_stream_blocked_until", 0.0), \
                patch("requests.get", side_effect=[_Response({"tracks": [selected]})]), \
                patchers[0], patchers[1]:
            with self.assertRaises(RuntimeError) as raised:
                backend_monochrome.run(Path(tmp), job, manager)
            self.assertIn("HTTP 403", backend_monochrome.stream_block_reason())
        self.assertIn("HTTP 403", str(raised.exception))
        self.assertEqual(len(session.calls), 1)

    def test_download_reuses_the_track_already_being_streamed(self):
        import native_audio
        selected = {"id": "154140608489852928", "title": "Song", "artistNames": ["Artist"]}
        flac = b"fLaC" + b"x" * 1000
        session, patchers = _patched_fetch([_Response(chunks=[flac], status_code=206,
                                                      headers={"Content-Range": f"bytes 0-{len(flac) - 1}/{len(flac)}"})])
        url = "https://tracks.monochrome.st/track/154140608489852928"
        manager = _Manager()
        job = {"id": "job", "title": "Song", "artist": "Artist", "mode": "download"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_monochrome, "_INSTANCES", (("https://tracks.monochrome.st", "https://monochrome.st"),)), \
                patch("requests.get", side_effect=[_Response({"tracks": [selected]})]), \
                patch("service_downloader.is_valid_audio_file", return_value=True), \
                patch.object(backend_monochrome, "_decode_error", return_value=""), \
                patchers[0], patchers[1]:
            streaming = native_audio._monochrome_fetch(url)  # the native player is playing it
            streaming.thread.join(timeout=5)
            backend_monochrome.run(Path(tmp), job, manager)
            self.assertEqual((Path(tmp) / "Song - Artist.flac").read_bytes(), flac)
        self.assertEqual(len(session.calls), 1)  # one request for play + save

if __name__ == "__main__":
    unittest.main()
