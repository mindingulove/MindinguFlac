import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from native_audio import NativeAudioManager

import numpy as np

from config import AppConfig
from volume_normalizer import VolumeNormalizer


class TestVolumeNormalization(unittest.TestCase):
    def render(self, amplitude, volume=1.0, channels=2):
        rate = 48000
        phase = np.arange(rate * 5) / rate
        signal = np.repeat((amplitude * np.sin(2 * np.pi * 440 * phase))[:, None], channels, axis=1).astype('float32')
        normalizer = VolumeNormalizer()
        output = np.concatenate([normalizer.process(signal[i:i+1024], rate, True) * volume
                                 for i in range(0, len(signal), 1024)])
        return output, normalizer

    def test_matches_quiet_and_loud_songs(self):
        quiet, _ = self.render(0.05)
        loud, _ = self.render(0.7)
        quiet_rms = np.sqrt(np.mean(quiet[-48000:] ** 2))
        loud_rms = np.sqrt(np.mean(loud[-48000:] ** 2))
        self.assertLess(abs(20 * np.log10(quiet_rms / loud_rms)), 0.1)
        self.assertAlmostEqual(20 * np.log10(loud_rms), -18, delta=0.1)

    def test_volume_and_channel_count_do_not_change_matching(self):
        full, _ = self.render(0.3)
        quiet, _ = self.render(0.3, volume=0.25, channels=1)
        self.assertTrue(np.allclose(full[:, :1] * 0.25, quiet))

    def test_silence_is_gated_boost_is_bounded_and_peaks_do_not_clip(self):
        normalizer = VolumeNormalizer()
        silence = np.zeros((48000, 2), dtype='float32')
        self.assertFalse(np.any(normalizer.process(silence, 48000, True)))
        self.assertEqual(normalizer.target, 1)
        pcm = np.full((48000, 2), 0.004, dtype='float32')
        normalizer.process(pcm, 48000, True)
        self.assertLessEqual(normalizer.target, 10 ** (12 / 20))
        transient = np.array([[1.0, -0.7], [0.1, -1.0]], dtype='float32')
        self.assertLessEqual(float(np.max(np.abs(normalizer.process(transient, 48000, True)))), 0.980001)

    def test_disabled_is_exact_bypass_and_resets_track(self):
        normalizer = VolumeNormalizer()
        pcm = np.full((48000, 2), 0.5, dtype='float32')
        normalizer.process(pcm, 48000, True)
        self.assertIs(normalizer.process(pcm, 48000, False), pcm)
        self.assertEqual(normalizer.frames, 0)
        self.assertEqual(normalizer.gain, 1)

    def test_preference_round_trip_and_default(self):
        self.assertFalse(AppConfig.from_public_dict({}).normalize_volume)
        config = AppConfig.from_public_dict({'normalize_volume': True})
        self.assertTrue(AppConfig.from_public_dict(config.public_dict()).normalize_volume)


class TestNativeNormalization(unittest.TestCase):
    def test_normalized_macos_file_uses_pcm_and_preserves_metadata(self):
        manager = NativeAudioManager()
        manager._normalize_volume = True
        with patch('native_audio.sys.platform', 'darwin'), patch.object(manager, 'available', return_value=True), \
                patch('native_audio._on_android', return_value=False), patch('pathlib.Path.is_file', return_value=True), \
                patch.object(manager, '_play_windows', return_value={'ok': True}) as pcm:
            manager.play('/test/song.flac', 'output', .4, 22, {'title': 'song'})
        self.assertEqual(pcm.call_args.args[1:4], ('output', .4, 22))
        self.assertEqual(manager._metadata, {'title': 'song'})

    def test_enabling_on_paused_macos_file_preserves_position_and_pause(self):
        manager = NativeAudioManager()
        manager._sound = MagicMock()
        manager._sound.currentTime.return_value = 23
        manager._path = '/test/song.flac'
        manager._device_uid = 'output'
        manager._volume = .3
        manager._paused = True
        with patch('native_audio._on_android', return_value=False), \
                patch.object(manager, 'play', return_value={'ok': True}) as play, \
                patch.object(manager, 'pause') as pause:
            manager.set_normalization(True)
        play.assert_called_once_with('/test/song.flac', 'output', .3, 23, {})
        pause.assert_called_once()

    def test_macos_pcm_file_pause_resume_and_status(self):
        manager = NativeAudioManager()
        manager._thread = MagicMock()
        manager._position = 17
        manager._duration = 200
        with patch('native_audio.sys.platform', 'darwin'), patch('native_audio._on_android', return_value=False), \
                patch.object(manager, 'available', return_value=True):
            self.assertFalse(manager.pause()['playing'])
            self.assertTrue(manager._pause_event.is_set())
            self.assertTrue(manager.resume()['playing'])
            self.assertFalse(manager._pause_event.is_set())
            self.assertEqual(manager.status()['position'], 17)

    def test_native_pcm_worker_matches_level_and_reaches_end(self):
        import soundfile as sf
        rate = 48000
        signal = (0.6 * np.sin(2 * np.pi * 440 * np.arange(rate * 5) / rate)).astype('float32')
        output = []
        sd = MagicMock()
        sd.OutputStream.return_value.__enter__.return_value.write.side_effect = lambda block: output.append(block.copy())
        manager = NativeAudioManager()
        manager._normalize_volume = True
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'song.wav'
            sf.write(source, signal, rate, subtype='FLOAT')
            with patch('native_audio.sys.platform', 'darwin'), patch('native_audio._on_android', return_value=False), \
                    patch.object(manager, 'available', return_value=True), patch.dict('sys.modules', {'sounddevice': sd}):
                self.assertTrue(manager.play(str(source), volume=.25)['ok'])
                manager._thread.join(timeout=3)
                status = manager.status()
        self.assertTrue(status['ended'])
        self.assertFalse(status['playing'])
        self.assertAlmostEqual(status['position'], 5)
        rms = np.sqrt(np.mean(np.concatenate(output)[-rate:] ** 2))
        self.assertAlmostEqual(20 * np.log10(rms), -18 + 20 * np.log10(.25), delta=.1)
