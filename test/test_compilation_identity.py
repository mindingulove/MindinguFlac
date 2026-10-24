"""Recording editions do not share an artist/title-only metadata cache."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import music_metadata as metadata


class CompilationIdentityTests(unittest.TestCase):
    def test_original_and_compilation_tracks_keep_separate_metadata_and_isrc(self):
        edition = {
            '4xCvkEWkK08p00riIBu1QO': {'album': 'Hits Of The 90s', 'album_artist': 'Various Artists',
                'album_spotify_id': 'compilation', 'isrc': 'USPR39507368', 'duration_ms': 256320},
            'O' * 22: {'album': 'Relish', 'album_artist': 'Joan Osborne',
                'album_spotify_id': 'original', 'isrc': 'USPR39500200', 'duration_ms': 320133},
        }
        cache = {'joan osborne||one of us': {'spotify_id': 'old-wrong-id', 'isrc': 'wrong'}}
        with ExitStack() as stack:
            stack.enter_context(patch('db.get_track_metadata', side_effect=cache.get))
            stack.enter_context(patch('db.save_track_metadata', side_effect=cache.__setitem__))
            stack.enter_context(patch('db.resolve_track_identity'))
            stack.enter_context(patch.object(metadata, 'spotify_track_metadata', side_effect=edition.get))
            for name in ('odesli_lookup', 'musicbrainz_recording_identifiers_by_isrc', 'musicbrainz_recording_identifiers'):
                stack.enter_context(patch.object(metadata, name, return_value={}))
            for key in edition:
                track = metadata.enrich_track_identifiers({'spotify_id': key, 'artist': 'Joan Osborne', 'title': 'One Of Us', 'genres': ['rock']})
                self.assertEqual(track['isrc'], edition[key]['isrc'])
                self.assertEqual(track['album_spotify_id'], edition[key]['album_spotify_id'])
        self.assertEqual(cache['spotify_track:4xCvkEWkK08p00riIBu1QO']['isrc'], 'USPR39507368')
        self.assertEqual(cache['spotify_track:' + 'O' * 22]['isrc'], 'USPR39500200')

    def test_explicit_deluxe_album_context_survives_reused_track_id(self):
        with ExitStack() as stack:
            stack.enter_context(patch('db.get_track_metadata', return_value=None))
            stack.enter_context(patch('db.save_track_metadata'))
            stack.enter_context(patch('db.resolve_track_identity'))
            stack.enter_context(patch.object(metadata, 'spotify_track_metadata', return_value={
                'album': 'Original', 'album_spotify_id': 'O' * 22, 'isrc': 'XX1234567890'}))
            for name in ('odesli_lookup', 'musicbrainz_recording_identifiers_by_isrc', 'musicbrainz_recording_identifiers'):
                stack.enter_context(patch.object(metadata, name, return_value={}))
            track = metadata.enrich_track_identifiers({'spotify_id': 'T' * 22, 'title': 'Song', 'artist': 'Artist',
                'genres': ['rock'], 'album_context': {'spotify_id': 'D' * 22, 'album': 'Album (Deluxe)', 'album_artist': 'Artist'}})
        self.assertEqual(track['album_spotify_id'], 'D' * 22)
        self.assertEqual(track['album'], 'Album (Deluxe)')
        self.assertEqual(track['catalog_album_spotify_id'], 'O' * 22)
        self.assertEqual(track['isrc'], 'XX1234567890')
