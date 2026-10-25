import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import service_downloader


class TorrentResumeTests(unittest.TestCase):
    def test_retry_reuses_retained_job_and_directory_without_starting_a_new_search(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / 'partial.flac'
            partial.write_bytes(b'fLaC' + bytes(1024))
            manager = service_downloader.ServiceDownloadManager.__new__(service_downloader.ServiceDownloadManager)
            manager.config = SimpleNamespace(default_quality='LOSSLESS')
            manager._start_lock = threading.Lock()
            manager._lock = threading.Lock()
            manager._cancel_flags = set()
            job = {'id':'same-id', 'engine':'torrent','mode':'stream','status':'error',
                   'error':'Interrupted by server restart','artist':'Artist','title':'Song',
                   'quality':'LOSSLESS','active_audio_path':str(partial),
                   'resolved_url':'magnet:?xt=urn:btih:known', 'created_at':1}
            manager.jobs = {'same-id':job}
            with patch.object(manager,'_find_cache_entry',return_value=None), \
                    patch.object(manager,'_find_active_cache_job',return_value=None), \
                    patch.object(manager,'_requested_engine',return_value=('torrent','all','LOSSLESS')), \
                    patch.object(manager,'_create_job',side_effect=AssertionError('must reuse partial')), \
                    patch.object(service_downloader.threading,'Thread') as thread:
                result = manager.start_job({'artist':'Artist','title':'Song','quality':'LOSSLESS'})
            self.assertEqual(result['id'],'same-id')
            self.assertEqual(result['status'],'starting')
            self.assertTrue(thread.call_args.kwargs['args'][1]['_resume_torrent'])
            self.assertTrue(partial.exists())

    def test_preallocated_race_files_are_not_finished_cache_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            private = cache / 'job' / '_race' / 'candidate' / 'song.flac'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'fLaC' + bytes(1024 * 1024))
            complete = cache / 'job' / 'complete.flac'
            complete.write_bytes(b'fLaC' + b'A' * (1024 * 1024))
            self.assertEqual(service_downloader._find_audio_files(cache), [complete])
            manager = service_downloader.ServiceDownloadManager.__new__(service_downloader.ServiceDownloadManager)
            manager.config = SimpleNamespace(cache_dir=cache)
            manager._lock = threading.Lock()
            manager.jobs = {'job': {'id':'job','mode':'stream','status':'running','output_dir':str(cache/'job')}}
            resolved, unresolved = manager._find_cache_files_on_disk()
            self.assertEqual((resolved, unresolved), ([], []))
