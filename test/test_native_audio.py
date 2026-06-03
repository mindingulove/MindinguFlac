
import unittest
import sys
from unittest.mock import MagicMock
from native_audio import NativeAudioManager

# Mock NSSound for macOS tests
class MockSound:
    def __init__(self, duration=100.0):
        self._playing = False
        self._position = 0.0
        self._duration = duration
        self._volume = 1.0

    def isPlaying(self):
        return self._playing

    def duration(self):
        return self._duration

    def currentTime(self):
        return self._position

    def volume(self):
        return self._volume

    def play(self):
        self._playing = True
        return True

    def pause(self):
        self._playing = False
        return True

    def resume(self):
        self._playing = True
        return True

    def setCurrentTime_(self, pos):
        self._position = pos

class TestNativeAudioMacOS(unittest.TestCase):
    def setUp(self):
        self.am = NativeAudioManager()
        # Mock dependencies
        self.am._lock = MagicMock()
        self.am._lock.__enter__ = MagicMock()
        self.am._lock.__exit__ = MagicMock()

    @unittest.skipIf(sys.platform != "darwin", "macOS only")
    def test_status_robustness_against_slow_start(self):
        self.am._sound = MockSound(duration=10.0)
        self.am._playing = True
        self.am._has_played = False
        self.am._paused = False
        self.am._ended = False
        
        # Slow start (raw_playing is False, position is 0)
        self.am._sound._playing = False
        self.am._sound._position = 0.0
        
        s = self.am.status()
        self.assertTrue(s["playing"])
        self.assertFalse(s["ended"])
        self.assertFalse(self.am._has_played)

    @unittest.skipIf(sys.platform != "darwin", "macOS only")
    def test_status_robustness_against_fluctuation(self):
        self.am._sound = MockSound(duration=10.0)
        self.am._playing = True
        self.am._has_played = True # Already observed movement
        self.am._paused = False
        self.am._ended = False
        
        # Fluctuation (raw_playing drops to False momentarily in the middle)
        self.am._sound._playing = False
        self.am._sound._position = 5.0
        
        s = self.am.status()
        self.assertTrue(s["playing"])
        self.assertFalse(s["ended"])

    @unittest.skipIf(sys.platform != "darwin", "macOS only")
    def test_status_finish_detection(self):
        self.am._sound = MockSound(duration=10.0)
        self.am._playing = True
        self.am._has_played = True
        self.am._paused = False
        self.am._ended = False
        
        # Sound finished (raw_playing is False, position is 0)
        self.am._sound._playing = False
        self.am._sound._position = 0.0
        
        s = self.am.status()
        self.assertFalse(s["playing"])
        self.assertTrue(s["ended"])

    @unittest.skipIf(sys.platform != "darwin", "macOS only")
    def test_resume_preserves_position_if_resume_fails(self):
        self.am._sound = MockSound(duration=10.0)
        self.am._sound._position = 5.0
        self.am._sound._playing = False
        self.am._paused = True
        
        # Mock resume failure
        self.am._sound.resume = MagicMock(return_value=False)
        self.am._sound.play = MagicMock(return_value=True)
        self.am._sound.setCurrentTime_ = MagicMock()
        
        self.am.resume()
        
        self.am._sound.setCurrentTime_.assert_called_with(5.0)
        self.am._sound.play.assert_called()

if __name__ == "__main__":
    unittest.main()
