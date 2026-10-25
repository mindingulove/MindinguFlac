"""Album tracks remain available independently of optional metadata services."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import music_metadata as metadata
from config import AppConfig


class AlbumLoadingTests(unittest.TestCase):
    def test_compilation_keeps_album_artist_and_exact_identity_on_every_track(self):
        self.spotify.return_value = {
            'name': 'Hits Of The 90s', 'artists': [{'name': 'Various Artists'}],
            'tracks': {'items': [{'id': 'one-of-us', 'name': 'One Of Us', 'artists': [{'name': 'Joan Osborne'}],
                'duration_ms': 256320, 'external_ids': {'isrc': 'USPR39507368'}}]},
        }
        result = metadata.album_tracks(AppConfig(), 'Joan Osborne', 'Hits Of The 90s', spotify_id='compilation', include_extras=False)
        self.assertEqual(result['artist'], 'Various Artists')
        self.assertEqual(result['spotify_id'], 'compilation')
        self.assertEqual(result['tracks'][0]['artist'], 'Joan Osborne')
        self.assertEqual(result['tracks'][0]['album_artist'], 'Various Artists')
        self.assertEqual(result['tracks'][0]['album_spotify_id'], 'compilation')
        self.assertEqual(result['tracks'][0]['isrc'], 'USPR39507368')

    def test_exact_album_failure_cannot_open_another_release_by_name(self):
        self.spotify.return_value = {}
        result = metadata.album_tracks(AppConfig(), 'Artist', 'Album', spotify_id='selected-album', include_extras=False)
        self.assertEqual(result['tracks'], [])
        self.spotify.assert_called_once_with('albums/selected-album', market='US')

    def test_album_adapter_uses_album_artist_instead_of_first_track_singer(self):
        from types import SimpleNamespace
        client = SimpleNamespace(get_album_tracks=lambda _: ({'name': 'Hits', 'artist': 'Various Artists'}, [
            SimpleNamespace(id='track', title='Song', artists='Joan Osborne', album_artist='Various Artists')]))
        album = metadata._public_client_get(client, 'albums/compilation', {})
        self.assertEqual(album['artists'], [{'name': 'Various Artists'}])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cache = {}
        self.stack.enter_context(patch('db.get_album_metadata', side_effect=self.cache.get))
        self.stack.enter_context(patch('db.save_album_metadata', side_effect=self.cache.__setitem__))
        self.spotify = self.stack.enter_context(patch.object(metadata, '_sp', return_value={
            'name': 'Album', 'release_date': '2017-01-01',
            'artists': [{'name': 'Artist'}], 'images': [],
            'tracks': {'items': [{'id': 'track', 'name': 'Song', 'duration_ms': 1000, 'plays': 42}]},
        }))
        self.optional = {}
        for name, result in [('musicbrainz_album_year', '2017'), ('spotify_album_playcounts', {'track': 99}),
                             ('spotify_album_artwork', 'cover'), ('spotify_artist_artwork', 'portrait'),
                             ('discogs_album_images', {}), ('musicbrainz_genres_for_release', []),
                             ('musicbrainz_genres_for_recording', []), ('caa_artwork', [])]:
            self.optional[name] = self.stack.enter_context(patch.object(metadata, name, return_value=result))

    def test_tracks_without_artwork_do_not_wait_for_optional_services(self):
        result = metadata.album_tracks(AppConfig(), 'Artist', 'Album', spotify_id='album', include_extras=False)
        self.assertEqual(result['track_count'], 1)
        self.assertEqual(result['tracks'][0]['plays'], 42)
        self.assertEqual(result['year'], '2017')
        self.assertFalse(result['_extras_complete'])
        for mocked in self.optional.values():
            mocked.assert_not_called()

    def test_details_reuse_core_tracks_and_preserve_original_payload(self):
        core = metadata.album_tracks(AppConfig(), 'Artist', 'Album', spotify_id='album', include_extras=False)
        self.optional['discogs_album_images'].return_value = {'release_url': 'discogs-url', 'images': []}
        details = metadata.album_tracks(AppConfig(), 'Artist', 'Album', spotify_id='album')
        self.spotify.assert_called_once()
        self.assertEqual(details['tracks'][0]['plays'], 99)
        self.assertTrue(details['_extras_complete'])
        self.assertEqual(details['discogs_release_url'], 'discogs-url')
        self.assertEqual(core['tracks'][0]['plays'], 42)
        self.assertFalse(core['_extras_complete'])

    def test_missing_year_does_not_block_cached_tracks(self):
        self.cache['artist||album'] = {'artist': 'Artist', 'album': 'Album', 'tracks': [{'title': 'Song'}], 'year': ''}
        result = metadata.album_tracks(AppConfig(), 'Artist', 'Album', include_extras=False)
        self.assertEqual(result['tracks'][0]['title'], 'Song')
        self.spotify.assert_not_called()
        self.optional['musicbrainz_album_year'].assert_not_called()

    def test_spotify_adapter_keeps_album_date_and_playcounts(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        client = Mock(spec=['get_album_tracks'])
        client.get_album_tracks.return_value = ({'name': 'Album', 'release_date': '2017-01-01'}, [
            SimpleNamespace(id='track', title='Song', artists='Artist', plays=42)
        ])
        album = metadata._public_client_get(client, 'albums/album', {})
        self.assertEqual(album['release_date'], '2017-01-01')
        self.assertEqual(album['artists'], [{'name': 'Artist'}])
        self.assertEqual(album['tracks']['items'][0]['plays'], 42)


if __name__ == '__main__':
    unittest.main()
