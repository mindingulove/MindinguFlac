
import unittest
import ctypes
import sys
from unittest.mock import MagicMock, patch
from native_audio import NativeAudioManager, _macos_unmute_device

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


class MockCFunction:
    def __init__(self, fn):
        self.fn = fn
        self.restype = None

    def __call__(self, *args):
        return self.fn(*args)


class FakeCoreAudio:
    def __init__(self):
        self.devices = [101, 202]
        self.uid_ptrs = {101: 1001, 202: 1002}
        self.uids = {1001: "wrong-device", 1002: "target-device"}
        self.float_values = {}
        self.set_calls = []
        self.AudioObjectGetPropertyDataSize = MockCFunction(self.get_property_data_size)
        self.AudioObjectGetPropertyData = MockCFunction(self.get_property_data)
        self.AudioObjectHasProperty = MockCFunction(self.has_property)
        self.AudioObjectSetPropertyData = MockCFunction(self.set_property_data)

    @staticmethod
    def fcc(value):
        return int.from_bytes(value.encode(), "big")

    @staticmethod
    def address(pa_ref):
        return pa_ref._obj

    @staticmethod
    def out_value(ref, value):
        ref._obj.value = value

    def get_property_data_size(self, obj_id, pa_ref, _qual_size, _qual_data, size_ref):
        if int(obj_id.value if hasattr(obj_id, "value") else obj_id) == 1:
            if self.address(pa_ref).mSel == self.fcc("dev#"):
                self.out_value(size_ref, len(self.devices) * ctypes.sizeof(ctypes.c_uint32))
                return 0
        return 1

    def get_property_data(self, obj_id, pa_ref, _qual_size, _qual_data, size_ref, out_data):
        obj_id = int(obj_id.value if hasattr(obj_id, "value") else obj_id)
        address = self.address(pa_ref)
        if obj_id == 1 and address.mSel == self.fcc("dev#"):
            for index, dev in enumerate(self.devices):
                out_data[index] = dev
            self.out_value(size_ref, len(self.devices) * ctypes.sizeof(ctypes.c_uint32))
            return 0
        if address.mSel == self.fcc("uid "):
            self.out_value(out_data, self.uid_ptrs.get(obj_id, 0))
            return 0
        if address.mSel == self.fcc("volm"):
            self.out_value(out_data, self.float_values.get((obj_id, address.mEl), 0.0))
            return 0
        return 1

    def has_property(self, obj_id, pa_ref):
        obj_id = int(obj_id.value if hasattr(obj_id, "value") else obj_id)
        address = self.address(pa_ref)
        return obj_id == 202 and address.mSel in (self.fcc("mute"), self.fcc("volm"))

    def set_property_data(self, obj_id, pa_ref, _qual_size, _qual_data, _size, data_ref):
        obj_id = int(obj_id.value if hasattr(obj_id, "value") else obj_id)
        address = self.address(pa_ref)
        self.set_calls.append((obj_id, address.mSel, address.mEl, data_ref._obj.value))
        return 0


class FakeCoreFoundation:
    def __init__(self, uids):
        self.uids = uids
        self.CFStringGetCString = MockCFunction(self.get_c_string)
        self.CFRelease = MockCFunction(lambda _ptr: None)

    def get_c_string(self, ptr, buf_ptr, size, _encoding):
        value = self.uids.get(ptr.value, "")
        data = value.encode("utf-8")[: max(0, int(size) - 1)] + b"\0"
        ctypes.memmove(buf_ptr.value, data, len(data))
        return True


class FakeAudioHardwareService:
    def __init__(self):
        self.set_calls = []
        self.AudioHardwareServiceHasProperty = MockCFunction(self.has_property)
        self.AudioHardwareServiceGetPropertyData = MockCFunction(self.get_property_data)
        self.AudioHardwareServiceSetPropertyData = MockCFunction(self.set_property_data)

    @staticmethod
    def fcc(value):
        return int.from_bytes(value.encode(), "big")

    @staticmethod
    def address(pa_ref):
        return pa_ref._obj

    def has_property(self, obj_id, pa_ref):
        address = self.address(pa_ref)
        return int(obj_id) == 202 and address.mSel == self.fcc("vmvc")

    def get_property_data(self, _obj_id, _pa_ref, _qual_size, _qual_data, _size_ref, out_data):
        out_data._obj.value = 0.0
        return 0

    def set_property_data(self, obj_id, pa_ref, _qual_size, _qual_data, _size, data_ref):
        address = self.address(pa_ref)
        self.set_calls.append((int(obj_id), address.mSel, address.mEl, data_ref._obj.value))
        return 0

class TestNativeAudioMacOS(unittest.TestCase):
    def setUp(self):
        self.am = NativeAudioManager()
        # Mock dependencies
        self.am._lock = MagicMock()
        self.am._lock.__enter__ = MagicMock()
        self.am._lock.__exit__ = MagicMock()

    def test_macos_unmute_device_targets_matching_uid(self):
        core_audio = FakeCoreAudio()
        core_foundation = FakeCoreFoundation(core_audio.uids)
        hardware_service = FakeAudioHardwareService()

        def cdll(path):
            if "CoreAudio.framework" in path:
                return core_audio
            if "CoreFoundation.framework" in path:
                return core_foundation
            if "AudioToolbox.framework" in path:
                return hardware_service
            raise OSError(path)

        with patch("native_audio.sys.platform", "darwin"), patch("ctypes.CDLL", side_effect=cdll):
            _macos_unmute_device("target-device")

        mute_selector = FakeCoreAudio.fcc("mute")
        volume_selector = FakeCoreAudio.fcc("volm")
        virtual_volume_selector = FakeCoreAudio.fcc("vmvc")
        self.assertEqual(
            [(202, mute_selector, element, 0) for element in (0, 1, 2)],
            [call for call in core_audio.set_calls if call[1] == mute_selector],
        )
        self.assertEqual(
            [(202, volume_selector, element, 0.5) for element in (0, 1, 2)],
            [call for call in core_audio.set_calls if call[1] == volume_selector],
        )
        self.assertEqual(
            [(202, virtual_volume_selector, 0, 0.5)],
            hardware_service.set_calls,
        )

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

    @unittest.skipIf(sys.platform != "darwin", "macOS only")
    def test_resume_actually_resumes_when_isplaying_lies(self):
        # Regression guard: NSSound.isPlaying() keeps returning True even after
        # pause(). resume() must NOT short-circuit on that, or the sound stays
        # paused while the UI thinks it's playing — the "pause button locks and
        # won't play again" bug. resume() must actually call sound.resume().
        sound = MockSound(duration=10.0)
        sound._position = 5.0
        sound.isPlaying = MagicMock(return_value=True)  # the quirk
        sound.resume = MagicMock(return_value=True)
        sound.play = MagicMock(return_value=True)
        self.am._sound = sound
        self.am._paused = True

        self.am.resume()

        sound.resume.assert_called_once()
        self.assertFalse(self.am._paused)
        self.assertTrue(self.am._playing)

if __name__ == "__main__":
    unittest.main()
