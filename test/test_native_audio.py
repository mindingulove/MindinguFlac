
import unittest
from pathlib import Path
import ctypes
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from native_audio import NativeAudioManager, _macos_unmute_device, _metadata_duration_ms


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


class TestNativeAudioLifecycle(unittest.TestCase):
    def test_pause_and_resume_keep_live_stream_worker_and_identity(self):
        manager = NativeAudioManager()
        manager._stream_url = "https://tracks.monochrome.st/track/test"
        manager._stream_id = 7
        manager._thread = threading.current_thread()
        manager._playing = True
        manager._stream_pause_ack.set()

        paused = manager.pause()
        self.assertTrue(paused["ok"])
        self.assertIs(manager._thread, threading.current_thread())
        self.assertEqual(manager._stream_id, 7)
        self.assertFalse(manager._stop_event.is_set())

        resumed = manager.resume()
        self.assertTrue(resumed["ok"])
        self.assertIs(manager._thread, threading.current_thread())
        self.assertEqual(manager._stream_id, 7)
        self.assertFalse(manager._stop_event.is_set())

    def test_live_stream_output_switch_keeps_same_stream_and_pause_state(self):
        manager = NativeAudioManager()
        manager._stream_url = "https://tracks.monochrome.st/track/test"
        manager._stream_id = 12
        manager._thread = threading.current_thread()
        manager._pause_event.set()
        manager._paused = True
        manager._stream_output = MagicMock()
        fake_sounddevice = SimpleNamespace(
            query_devices=lambda *args: (
                {"max_output_channels": 2, "name": "Default"}
                if args else [{"max_output_channels": 2, "name": "EDIFIER S351DB"}]
            ),
            default=SimpleNamespace(device=(0, 0)),
        )

        def acknowledge_route_change():
            deadline = time.monotonic() + 1.0
            while manager._stream_output_revision < 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            with manager._stream_output_condition:
                manager._stream_output_applied_revision = manager._stream_output_revision
                manager._stream_output_condition.notify_all()

        acknowledger = threading.Thread(target=acknowledge_route_change, daemon=True)
        acknowledger.start()

        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), \
                patch("native_audio._macos_output_device_name", return_value="EDIFIER S351DB"):
            result = manager.set_stream_output("device-uid", "EDIFIER S351DB")

        self.assertTrue(result["ok"])
        self.assertEqual(result["output_revision"], 1)
        self.assertEqual(result["output_applied_revision"], 1)
        self.assertEqual(manager._stream_id, 12)
        self.assertEqual(manager._stream_url, "https://tracks.monochrome.st/track/test")
        self.assertTrue(manager._pause_event.is_set())
        self.assertEqual(manager._device_uid, "device-uid")
        manager._stream_output.abort.assert_not_called()

    def test_unavailable_route_does_not_mutate_current_stream_route(self):
        manager = NativeAudioManager()
        manager._stream_url = "https://tracks.monochrome.st/track/test"
        manager._stream_id = 12
        manager._thread = threading.current_thread()
        manager._device_uid = "existing-uid"
        manager._stream_device_name = "Existing output"
        manager._stream_output_revision = 4
        fake_sounddevice = SimpleNamespace(
            query_devices=lambda *args: (
                {"max_output_channels": 2, "name": "Default"}
                if args else [{"max_output_channels": 2, "name": "Existing output"}]
            ),
            default=SimpleNamespace(device=(0, 0)),
        )
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), \
                patch("native_audio._macos_output_device_name", return_value=""):
            result = manager.set_stream_output("missing-uid", "EDIFIER S351DB")
        self.assertFalse(result["ok"])
        self.assertEqual(manager._device_uid, "existing-uid")
        self.assertEqual(manager._stream_device_name, "Existing output")
        self.assertEqual(manager._stream_output_revision, 4)
        self.assertEqual(manager._stream_id, 12)

    def test_stop_waits_for_stream_worker_without_holding_state_lock(self):
        manager = NativeAudioManager()
        finished = threading.Event()

        def worker():
            while not manager._stop_event.is_set():
                time.sleep(0.005)
            # The real stream worker takes the state lock while unwinding.
            with manager._lock:
                pass
            finished.set()

        manager._thread = threading.Thread(target=worker, daemon=True)
        manager._thread.start()

        result = manager.stop()

        self.assertTrue(finished.is_set())
        self.assertTrue(result["ok"])
        self.assertIsNone(manager._thread)
        self.assertFalse(manager._stop_event.is_set())

class _FakeOutputStream:
    def __init__(self, backend, device, **kwargs):
        if device in backend.failing:
            raise RuntimeError(f"PortAudio could not open device {device}")
        self.backend = backend
        self.device = device
        self.closed = False
        self.writes = 0
        backend.opened.append(self)

    def start(self):
        pass

    def write(self, pcm):
        if self.device in self.backend.write_failing:
            raise RuntimeError("Device disconnected")
        self.writes += 1
        time.sleep(0.001)

    def stop(self):
        pass

    def abort(self):
        pass

    def close(self):
        self.closed = True


class _FakePortAudio:
    """sounddevice stand-in whose device list only changes on re-initialise."""

    def __init__(self, devices, live_devices=None):
        self.devices = list(devices)
        self.live_devices = list(live_devices if live_devices is not None else devices)
        self.failing = set()
        self.write_failing = set()
        self.opened = []
        self.refreshes = 0
        self.default = SimpleNamespace(device=(None, 0))

    def query_devices(self, *args):
        if args:
            return self.devices[args[0]]
        return list(self.devices)

    def OutputStream(self, samplerate, channels, dtype, device, latency, extra_settings=None):
        return _FakeOutputStream(self, device)

    def _terminate(self):
        for stream in self.opened:
            stream.closed = True

    def _initialize(self):
        self.refreshes += 1
        self.devices = list(self.live_devices)


class _FakeFetch:
    """Offline stand-in for _MonochromeFetch: never touches the network."""

    def __init__(self, error="", http_status=0, size=4000000):
        self.error = error
        self.http_status = http_status
        self.size = size

    def read_into(self, write, stop):
        sent = 0
        while sent < self.size and not stop() and not self.error:
            write(bytes(min(65536, self.size - sent)))
            sent += 65536


@unittest.skipUnless(sys.platform != "win32", "POSIX shell fake ffmpeg")
class TestNativeStreamWorkerRouting(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _fake_ffmpeg(self, body):
        import os
        path = os.path.join(self.tmp.name, "ffmpeg")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def _start(self, sd, ffmpeg, uid="", name="", live_names=None, fetch=None):
        manager = NativeAudioManager()
        live_names = live_names or {}
        patches = [
            patch("native_audio._monochrome_fetch", return_value=fetch or _FakeFetch()),
            patch.dict(sys.modules, {"sounddevice": sd}),
            patch("native_audio._macos_output_device_name", side_effect=lambda u="": live_names.get(u, "" if u else None)),
            patch("native_audio._NATIVE_STREAM_PREBUFFER_SECONDS", 0.01),
            patch.object(NativeAudioManager, "available", return_value=True),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        manager._stream_url = "https://tracks.monochrome.st/track/1"
        manager._device_uid = uid
        manager._stream_device_name = name
        manager._stream_output_revision = 1
        manager._thread = threading.Thread(target=manager._stream_worker, args=(ffmpeg,), daemon=True)
        manager._thread.start()
        self.addCleanup(manager._stop)
        return manager

    def _wait(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_switch_back_to_bluetooth_missing_from_stale_portaudio_list_refreshes(self):
        speakers = {"name": "MacBook Pro Speakers", "max_output_channels": 2}
        edifier = {"name": "EDIFIER S351DB", "max_output_channels": 2}
        # PortAudio launched while the Edifier was disconnected.
        sd = _FakePortAudio([speakers], live_devices=[speakers, edifier])
        ffmpeg = self._fake_ffmpeg("head -c 4000000 /dev/zero")
        manager = self._start(sd, ffmpeg, live_names={"edifier-uid": "EDIFIER S351DB"})
        self.assertTrue(self._wait(lambda: manager._stream_output_applied_revision == 1))

        result = manager.set_stream_output("edifier-uid", "EDIFIER S351DB")

        self.assertTrue(result["ok"], result)
        self.assertEqual(sd.refreshes, 1)
        self.assertEqual(manager._stream_output.device, 1)
        self.assertEqual(manager._device_uid, "edifier-uid")

    def test_failed_switch_restores_previous_output_after_refresh(self):
        speakers = {"name": "MacBook Pro Speakers", "max_output_channels": 2}
        edifier = {"name": "EDIFIER S351DB", "max_output_channels": 2}
        sd = _FakePortAudio([speakers, edifier])
        sd.failing.add(0)
        ffmpeg = self._fake_ffmpeg("head -c 4000000 /dev/zero")
        manager = self._start(sd, ffmpeg, uid="edifier-uid", name="EDIFIER S351DB",
                              live_names={"edifier-uid": "EDIFIER S351DB", "": "MacBook Pro Speakers"})
        self.assertTrue(self._wait(lambda: manager._stream_output_applied_revision == 1))

        result = manager.set_stream_output("", "")

        self.assertFalse(result["ok"])
        self.assertTrue(manager._thread.is_alive())
        self.assertEqual(manager._device_uid, "edifier-uid")
        self.assertEqual(manager._stream_output.device, 1)
        self.assertFalse(manager._stream_output.closed)

    def test_output_write_failure_moves_stream_to_default_output(self):
        speakers = {"name": "MacBook Pro Speakers", "max_output_channels": 2}
        edifier = {"name": "EDIFIER S351DB", "max_output_channels": 2}
        sd = _FakePortAudio([speakers, edifier])
        sd.write_failing.add(1)
        ffmpeg = self._fake_ffmpeg("head -c 4000000 /dev/zero")
        manager = self._start(sd, ffmpeg, uid="edifier-uid", name="EDIFIER S351DB",
                              live_names={"edifier-uid": "EDIFIER S351DB", "": "MacBook Pro Speakers"})

        self.assertTrue(self._wait(lambda: manager._stream_output is not None and manager._stream_output.device == 0))
        status = manager.status()
        self.assertEqual(status["error"], "")
        self.assertEqual(status["device_uid"], "")
        self.assertIn("This computer", status["output_notice"])

    def test_download_rejection_is_reported_instead_of_decoder_error(self):
        sd = _FakePortAudio([{"name": "MacBook Pro Speakers", "max_output_channels": 2}])
        ffmpeg = self._fake_ffmpeg('cat >/dev/null; echo "pipe:0: Invalid data found" >&2; exit 1')
        fetch = _FakeFetch(error="Monochrome refused the stream (HTTP 403 access denied)", http_status=403)
        manager = self._start(sd, ffmpeg, live_names={"": "MacBook Pro Speakers"}, fetch=fetch)
        self.assertTrue(self._wait(lambda: manager._error != ""))
        status = manager.status()
        self.assertEqual(status["stream_http_status"], 403)
        self.assertEqual(status["error"], "Monochrome refused the stream (HTTP 403 access denied)")


class TestWindowsOutputResolution(unittest.TestCase):
    def _sd(self, devices):
        hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
        return SimpleNamespace(
            query_devices=lambda *args: devices[args[0]] if args else list(devices),
            query_hostapis=lambda index: hostapis[index],
            default=SimpleNamespace(device=(None, 0)),
            WasapiSettings=lambda **kwargs: ("wasapi", kwargs),
        )

    def test_stale_index_resolves_by_name_and_prefers_wasapi(self):
        import native_audio
        devices = [
            {"name": "Speakers (Realtek)", "max_output_channels": 2, "hostapi": 0},
            {"name": "EDIFIER S351DB", "max_output_channels": 2, "hostapi": 0},
            {"name": "EDIFIER S351DB", "max_output_channels": 2, "hostapi": 1},
        ]
        sd = self._sd(devices)
        with patch.object(native_audio.sys, "platform", "win32"):
            # Index 0 now belongs to another device after a re-enumeration.
            self.assertEqual(native_audio._portaudio_output_index(sd, "sounddevice:0", "EDIFIER S351DB"), 2)
            self.assertEqual(native_audio._portaudio_output_index(sd, "sounddevice:1", "EDIFIER S351DB"), 1)
            self.assertEqual(native_audio._output_extra_settings(sd, 2), ("wasapi", {"auto_convert": True}))
            self.assertIsNone(native_audio._output_extra_settings(sd, 1))


class TestWindowsLiveDevices(unittest.TestCase):
    def test_endpoint_uid_resolves_after_refresh(self):
        import native_audio
        edifier = {"name": "Headphones (EDIFIER S351DB)", "max_output_channels": 2, "hostapi": 1}
        speakers = {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 1}
        sd = _FakePortAudio([speakers], live_devices=[speakers, edifier])
        sd.query_hostapis = lambda index: {"name": "Windows WASAPI"}
        with patch.object(native_audio.sys, "platform", "win32"):
            uid = "endpoint:Headphones (EDIFIER S351DB)"
            self.assertIsNone(native_audio._portaudio_output_index(sd, uid))
            native_audio._refresh_portaudio(sd)
            self.assertEqual(native_audio._portaudio_output_index(sd, uid), 1)

    def test_windows_file_playback_reenumerates_missing_device(self):
        import native_audio
        import tempfile, wave
        speakers = {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 0}
        edifier = {"name": "Headphones (EDIFIER S351DB)", "max_output_channels": 2, "hostapi": 0}
        sd = _FakePortAudio([speakers], live_devices=[speakers, edifier])
        sd.query_hostapis = lambda index: {"name": "Windows WASAPI"}
        manager = NativeAudioManager()
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/t.wav"
            with wave.open(path, "wb") as handle:
                handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(44100)
                handle.writeframes(bytes(44100 * 4))
            fake_sf = SimpleNamespace(SoundFile=lambda p: _FakeSoundFile())
            with patch.dict(sys.modules, {"sounddevice": sd, "soundfile": fake_sf}), \
                    patch.object(native_audio.sys, "platform", "win32"), \
                    patch.object(NativeAudioManager, "_windows_worker", lambda self: None):
                result = manager._play_windows(Path(path), "endpoint:Headphones (EDIFIER S351DB)", 1.0, 0.0)
                missing = manager._play_windows(Path(path), "sounddevice:9", 1.0, 0.0, "Gone Device")
        self.assertTrue(result["ok"], result)
        self.assertEqual(sd.refreshes, 2)
        self.assertFalse(missing["ok"])
        self.assertIn("not connected", missing["error"])


class _FakeSoundFile:
    samplerate = 44100

    def __len__(self):
        return 44100

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestWindowsDeviceList(unittest.TestCase):
    def _lister(self, live):
        source = Path("app.py").read_text()
        start = source.index("def _list_audio_output_devices_windows(")
        end = source.index("ROOT = Path(__file__)")
        namespace = {"os": SimpleNamespace(name="posix"), "_windows_live_render_endpoints": lambda: live}
        exec(source[start:end], namespace)
        return namespace["_list_audio_output_devices_windows"]

    def test_live_endpoints_drop_gone_devices_and_add_new_ones(self):
        devices = [
            {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 0},
            {"name": "Speakers (Realtek(R) Audio)", "max_output_channels": 2, "hostapi": 1},
            {"name": "Headphones (Old BT)", "max_output_channels": 2, "hostapi": 1},
        ]
        sd = SimpleNamespace(query_devices=lambda: devices,
                             query_hostapis=lambda i: {"name": ["MME", "Windows WASAPI"][i]})
        with patch.dict(sys.modules, {"sounddevice": sd}):
            listed = self._lister(["Speakers (Realtek(R) Audio)", "Headphones (EDIFIER S351DB)"])()
            unchanged = self._lister(None)()
        self.assertEqual([d["uid"] for d in listed], ["sounddevice:1", "endpoint:Headphones (EDIFIER S351DB)"])
        self.assertEqual([d["name"] for d in unchanged], ["Speakers (Realtek(R) Audio)", "Headphones (Old BT)"])


class _FakeAndroidPlayer:
    """Stand-in for NativeAudioPlayer.java (reached through Chaquopy's jclass)."""

    def __init__(self):
        import json
        self.json = json
        self.calls = []
        self.snapshot = {"stream_id": 1, "device_id": 7, "error": "", "http_status": 0, "notice": "",
                         "ended": False, "playing": True, "position": 12.5, "duration": 244.6,
                         "buffered": 30.0, "elapsed": 3.0, "active": True}
        self.devices = [{"id": 7, "name": "EDIFIER S351DB", "type": "bluetooth"}]

    def available(self):
        return True

    def play(self, source, headers, device_id, device_name, volume, position):
        self.calls.append(("play", source, headers, device_id, device_name, volume, position))
        return self.json.dumps({"ok": True, "stream_id": 1})

    def setOutput(self, device_id, device_name):
        self.calls.append(("setOutput", device_id, device_name))
        ok = any(d["id"] == device_id for d in self.devices) or device_id < 0
        return self.json.dumps({"ok": ok, "error": "" if ok else "Selected output is not connected"})

    def status(self):
        return self.json.dumps(self.snapshot)

    def listOutputs(self):
        return self.json.dumps(self.devices)

    def pause(self):
        self.calls.append(("pause",))

    def resume(self):
        self.calls.append(("resume",))


class TestAndroidNativePlayback(unittest.TestCase):
    def setUp(self):
        import native_audio
        self.player = _FakeAndroidPlayer()
        for item in (patch.object(native_audio, "_on_android", return_value=True),
                     patch.object(native_audio, "_android_player", return_value=self.player)):
            item.start()
            self.addCleanup(item.stop)

    def test_monochrome_stream_plays_on_chosen_device_with_browser_headers(self):
        import backend_monochrome, json
        manager = NativeAudioManager()
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            result = manager.play_stream("https://tracks.monochrome.st/track/1", "android:7", "EDIFIER S351DB",
                                         0.8, 3.0, {"title": "Adia"})
        self.assertTrue(result["ok"], result)
        _, source, headers, device_id, name, volume, position = self.player.calls[0]
        self.assertEqual((device_id, name, position), (7, "EDIFIER S351DB", 3.0))
        self.assertEqual(json.loads(headers)["Sec-Fetch-Dest"], "audio")
        self.assertEqual(result["stream_phase"], "playing")
        self.assertEqual(result["position"], 12.5)
        self.assertEqual(result["device_uid"], "android:7")

    def test_http_429_reports_clearly_and_starts_cooldown(self):
        import backend_monochrome
        manager = NativeAudioManager()
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            manager.play_stream("https://tracks.monochrome.st/track/1", "android:7", "EDIFIER S351DB")
            self.player.snapshot |= {"error": "Server returned 429", "http_status": 429, "playing": False}
            status = manager.status()
            self.assertIn("429", backend_monochrome.stream_block_reason())
        self.assertEqual(status["stream_http_status"], 429)
        self.assertIn("rate-limiting", status["error"])

    def test_disconnected_output_is_followed_to_this_phone(self):
        manager = NativeAudioManager()
        with patch("pathlib.Path.is_file", return_value=True):
            manager.play("/data/song.flac", "android:7", 1.0, 0.0, {"title": "x"}, device_name="EDIFIER S351DB")
        self.player.snapshot |= {"device_id": -1, "notice": "Audio output disconnected (EDIFIER S351DB); playing on This phone"}
        status = manager.status()
        self.assertEqual(status["device_uid"], "")
        self.assertIn("This phone", status["output_notice"])
        self.assertEqual(status["path"], "/data/song.flac")

    def test_output_switch_and_device_list(self):
        import native_audio
        manager = NativeAudioManager()
        self.assertTrue(manager.set_stream_output("android:7", "EDIFIER S351DB")["ok"])
        self.assertFalse(manager.set_stream_output("android:99", "Gone")["ok"])
        self.assertEqual(manager._device_uid, "android:7")
        self.assertEqual(native_audio.android_output_devices(),
                         [{"name": "EDIFIER S351DB", "uid": "android:7", "driver": "bluetooth"}])


class _FakeResponse:
    def __init__(self, status_code, chunks=(), headers=None):
        self.status_code = status_code
        self.chunks = chunks
        self.headers = headers or {}

    def iter_content(self, chunk_size=65536):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestMonochromeFetch(unittest.TestCase):
    def _fetch(self, responses):
        import native_audio
        calls = []

        class Session:
            def get(self, url, headers, stream, timeout):
                calls.append(dict(headers))
                return responses.pop(0)

            def close(self):
                pass

        with patch.object(native_audio._MonochromeFetch, "_session", lambda self: Session()):
            fetch = native_audio._MonochromeFetch("https://tracks.monochrome.st/track/test-fetch")
            fetch.thread.join(timeout=5)
        self.addCleanup(fetch.cancel)
        return fetch, calls

    def test_429_starts_cooldown_without_retrying(self):
        import backend_monochrome
        with patch.object(backend_monochrome, "_stream_blocked_until", 0.0):
            fetch, calls = self._fetch([_FakeResponse(429, headers={"Retry-After": "300"})])
            self.assertIn("429", backend_monochrome.stream_block_reason())
        self.assertEqual(fetch.http_status, 429)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["Sec-Fetch-Dest"], "audio")

    def test_download_is_shared_by_readers_and_seeks(self):
        fetch, calls = self._fetch([_FakeResponse(206, chunks=[b"abc", b"def"])])
        self.assertTrue(fetch.done)
        for _ in range(2):  # e.g. initial play, then a seek restart
            received = bytearray()
            fetch.read_into(received.extend, lambda: False)
            self.assertEqual(bytes(received), b"abcdef")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["Range"], "bytes=0-")


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

    def test_stream_metadata_duration_can_be_nested(self):
        self.assertEqual(
            743760,
            _metadata_duration_ms({"metadata": {"duration_ms": 743760}}),
        )
        self.assertEqual(
            743760,
            _metadata_duration_ms({"duration": {"totalMilliseconds": 743760}}),
        )

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
