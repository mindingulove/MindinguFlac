import unittest

import numpy as np

import video_sync as vs

SR = vs.SAMPLE_RATE


def _song(seconds, seed, period=None):
    """Synthetic 'music': pitched notes with irregular onsets (or a strict loop)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SR), dtype=np.float32)
    t = 0.0
    pattern = None
    if period:
        pattern = _song(period, seed + 1)
    while t < seconds:
        if pattern is not None:
            start = int(t * SR)
            out[start:start + pattern.size] = pattern[:max(0, out.size - start)]
            t += period
            continue
        length = rng.uniform(0.08, 0.6)
        freq = rng.uniform(110, 1800)
        n = int(length * SR)
        start = int(t * SR)
        note = np.sin(2 * np.pi * freq * np.arange(n) / SR) * np.exp(-np.arange(n) / (0.25 * SR))
        end = min(out.size, start + n)
        out[start:end] += (rng.uniform(0.2, 1.0) * note[:end - start]).astype(np.float32)
        t += rng.uniform(0.1, 0.7)
    return out


def _master(samples, gain=0.6):
    """A different 'master': level change, tilt EQ and a little noise."""
    tilted = np.convolve(samples, [0.6, 0.4], mode="same")
    noise = np.random.default_rng(99).normal(0, 0.01, samples.size)
    return (gain * tilted + noise).astype(np.float32)


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


class VideoSyncMatchTests(unittest.TestCase):
    def _match(self, audio, video):
        return vs.match_features(vs.features(audio), vs.features(video))

    def test_finds_video_intro_offset_across_different_masters(self):
        song = _song(150, seed=1)
        intro = _song(12.4, seed=7)
        video = np.concatenate([intro, song])[: int(160 * SR)]
        result = self._match(_master(song[: int(90 * SR)]), video)
        self.assertTrue(result["matched"], result)
        self.assertAlmostEqual(result["offset"], 12.4, delta=0.05)

    def test_finds_video_that_starts_later_in_the_song(self):
        song = _song(150, seed=2)
        result = self._match(_master(song[: int(90 * SR)]), song[int(8 * SR):])
        self.assertTrue(result["matched"], result)
        self.assertAlmostEqual(result["offset"], -8.0, delta=0.05)

    def test_video_can_omit_a_long_album_intro(self):
        song = _song(200, seed=25)
        result = self._match(_master(song[: int(120 * SR)]), song[int(62 * SR):])
        self.assertTrue(result["matched"], result)
        self.assertAlmostEqual(result["offset"], -62.0, delta=0.05)

    def test_unrelated_song_is_not_matched(self):
        result = self._match(_song(90, seed=3), _song(160, seed=4))
        self.assertFalse(result["matched"], result)

    def test_exactly_repeating_loop_is_refused_rather_than_guessed(self):
        loop = _song(160, seed=5, period=2.0)
        result = self._match(_master(loop[int(10 * SR): int(100 * SR)]), loop)
        self.assertFalse(result["matched"], result)


class AndroidDecodeTests(unittest.TestCase):
    """On the phone, audio comes from AudioPcmDecoder.java (MediaCodec), not ffmpeg."""

    def _fake_java(self, samples, calls):
        import sys
        from types import SimpleNamespace

        class Decoder:
            @staticmethod
            def decodeMono(path, seconds, rate):
                calls.append((path, seconds, rate))
                return bytearray(samples.astype("<f4").tobytes())

        classes = {"com.mindinguflac.android.AudioPcmDecoder": Decoder}
        return {"java": SimpleNamespace(jclass=lambda name: classes[name])}

    def test_android_decodes_through_mediacodec_bridge(self):
        import sys
        from unittest.mock import patch
        samples = _song(5, seed=9)
        calls = []
        with patch.dict(sys.modules, self._fake_java(samples, calls)), \
                patch.dict("os.environ", {"MINDINGUFLAC_ANDROID": "1"}):
            self.assertTrue(vs.decoder_available())
            decoded = vs.decode_mono("/sdcard/Music/song.flac", 90)
        np.testing.assert_allclose(decoded, samples, rtol=0, atol=1e-6)
        self.assertEqual(calls, [("/sdcard/Music/song.flac", 90.0, vs.SAMPLE_RATE)])

    def test_android_match_end_to_end_with_bridge_audio(self):
        import sys
        from unittest.mock import patch
        song = _song(150, seed=11)
        video = np.concatenate([_song(9.5, seed=12), song])[: int(160 * SR)]
        album = _master(song[: int(90 * SR)])

        class Decoder:
            @staticmethod
            def decodeMono(path, seconds, rate):
                data = album if "album" in path else video
                return bytearray(data[: int(seconds * rate)].astype("<f4").tobytes())

        fake = {"java": __import__("types").SimpleNamespace(jclass=lambda name: Decoder)}
        with patch.dict(sys.modules, fake), patch.dict("os.environ", {"MINDINGUFLAC_ANDROID": "1"}):
            result = vs.compute_offset("/cache/stream-head/album.audio", "/files/video_files/v.mp4")
        self.assertTrue(result["matched"], result)
        self.assertAlmostEqual(result["offset"], 9.5, delta=0.05)

    def test_android_without_the_bridge_reports_unavailable(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        def missing(name):
            raise LookupError(name)

        with patch.dict(sys.modules, {"java": SimpleNamespace(jclass=missing)}), \
                patch.dict("os.environ", {"MINDINGUFLAC_ANDROID": "1"}):
            self.assertFalse(vs.decoder_available())


if __name__ == "__main__":
    unittest.main()
