from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Containers/codecs that neither macOS NSSound nor Windows soundfile can decode
# directly. These are transcoded to WAV (via bundled ffmpeg) before playback so
# native output works with every audio file, including YouTube webm/opus.
_NATIVE_UNSUPPORTED_EXTS = {".webm", ".weba", ".opus", ".ogg", ".oga", ".mkv", ".m4v"}
_NATIVE_STREAM_PREBUFFER_SECONDS = 30.0


def _metadata_duration_ms(metadata: dict | None) -> float:
    """Read track length from flat or nested Spotify track metadata."""
    root = metadata if isinstance(metadata, dict) else {}
    sources = [root]
    for key in ("metadata", "track", "spotify"):
        nested = root.get(key)
        if isinstance(nested, dict):
            sources.append(nested)
    for source in sources:
        for key in ("duration_ms", "durationMillis", "duration_millis"):
            try:
                value = float(source.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        duration = source.get("duration")
        if isinstance(duration, dict):
            duration = duration.get("totalMilliseconds")
        try:
            value = float(duration or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value if value > 1000 else value * 1000
    return 0.0


def _ffmpeg_exe() -> str:
    """Locate an ffmpeg binary, preferring the bundled imageio-ffmpeg one."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), name)
        if os.path.exists(bundled):
            return bundled
    return shutil.which(name) or shutil.which("ffmpeg") or ""


def _transcode_to_wav(src: Path) -> str:
    """Transcode an audio file to a temp 16-bit WAV the native players can read.
    Results are cached by source path so repeated plays don't re-encode."""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return ""
    src_res = str(src.resolve())
    key = hashlib.md5(src_res.encode("utf-8")).hexdigest()
    out = Path(tempfile.gettempdir()) / f"mindinguflac_native_{key}.wav"
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    cmd = [ffmpeg, "-y", "-i", src_res, "-vn", "-c:a", "pcm_s16le", str(out)]
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, timeout=300, creationflags=creationflags
        )
    except Exception:
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass
        return ""
    return str(out) if (out.exists() and out.stat().st_size > 0) else ""


def _native_playable_path(audio_path: Path) -> str:
    """Return a path the native players can decode, transcoding only when the
    source format is unsupported. Falls back to the original on transcode
    failure so the caller can surface a clear error."""
    if audio_path.suffix.lower() not in _NATIVE_UNSUPPORTED_EXTS:
        return str(audio_path.resolve())
    converted = _transcode_to_wav(audio_path)
    return converted or str(audio_path.resolve())


def _macos_unmute_device(device_uid: str) -> None:
    """Best-effort: clear mute and lift zeroed volume on a CoreAudio output."""
    if not device_uid or sys.platform != "darwin":
        return
    try:
        import ctypes

        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        try:
            ahs = ctypes.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
        except Exception:
            ahs = None

        def _fcc(s: str) -> int:
            return int.from_bytes(s.encode(), "big")

        class _PA(ctypes.Structure):
            _fields_ = [("mSel", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mEl", ctypes.c_uint32)]

        kSys, kGlob, kOutp = ctypes.c_uint32(1), _fcc("glob"), _fcc("outp")
        kDev, kUID, kMute = _fcc("dev#"), _fcc("uid "), _fcc("mute")
        kVol, kVMV, kUTF8 = _fcc("volm"), _fcc("vmvc"), 0x08000100

        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        ca.AudioObjectHasProperty.restype = ctypes.c_bool
        ca.AudioObjectSetPropertyData.restype = ctypes.c_int32
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.restype = None
        if ahs is not None:
            try:
                ahs.AudioHardwareServiceHasProperty.restype = ctypes.c_bool
                ahs.AudioHardwareServiceGetPropertyData.restype = ctypes.c_int32
                ahs.AudioHardwareServiceSetPropertyData.restype = ctypes.c_int32
            except Exception:
                ahs = None

        def _data_ptr(value):
            return ctypes.cast(value, ctypes.c_void_p)

        def _get_cfstr(dev: int, selector: int) -> str:
            pa_uid = _PA(selector, kGlob, 0)
            value = ctypes.c_void_p(0)
            size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
            if ca.AudioObjectGetPropertyData(dev, ctypes.byref(pa_uid), 0, None, ctypes.byref(size), ctypes.byref(value)):
                return ""
            if not value.value:
                return ""
            try:
                buf = ctypes.create_string_buffer(512)
                if not cf.CFStringGetCString(value, _data_ptr(buf), len(buf), kUTF8):
                    return ""
                return buf.value.decode("utf-8", "replace")
            finally:
                try:
                    cf.CFRelease(value)
                except Exception:
                    pass

        def _set_uint32(dev: int, selector: int, element: int, value: int) -> None:
            pa = _PA(selector, kOutp, element)
            if ca.AudioObjectHasProperty(dev, ctypes.byref(pa)):
                data = ctypes.c_uint32(value)
                ca.AudioObjectSetPropertyData(
                    dev,
                    ctypes.byref(pa),
                    0,
                    None,
                    ctypes.c_uint32(ctypes.sizeof(data)),
                    ctypes.byref(data),
                )

        def _raise_zero_float(dev: int, selector: int, element: int, use_service: bool = False) -> None:
            pa = _PA(selector, kOutp, element)
            has_prop = ahs.AudioHardwareServiceHasProperty if use_service and ahs is not None else ca.AudioObjectHasProperty
            get_prop = ahs.AudioHardwareServiceGetPropertyData if use_service and ahs is not None else ca.AudioObjectGetPropertyData
            set_prop = ahs.AudioHardwareServiceSetPropertyData if use_service and ahs is not None else ca.AudioObjectSetPropertyData
            if not has_prop(dev, ctypes.byref(pa)):
                return
            current = ctypes.c_float(0.0)
            size = ctypes.c_uint32(ctypes.sizeof(current))
            if get_prop(dev, ctypes.byref(pa), 0, None, ctypes.byref(size), ctypes.byref(current)):
                return
            if current.value > 0.001:
                return
            new_value = ctypes.c_float(0.5)
            set_prop(
                dev,
                ctypes.byref(pa),
                0,
                None,
                ctypes.c_uint32(ctypes.sizeof(new_value)),
                ctypes.byref(new_value),
            )

        # Enumerate output devices and locate the one matching this UID.
        pa = _PA(kDev, kGlob, 0)
        sz = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz)):
            return
        ids = (ctypes.c_uint32 * (sz.value // ctypes.sizeof(ctypes.c_uint32)))()
        if ca.AudioObjectGetPropertyData(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz), ids):
            return

        target = None
        for dev in ids:
            dev_id = int(dev)
            if _get_cfstr(dev_id, kUID) == device_uid:
                target = dev_id
                break
        if target is None:
            return

        # Clear mute on the master + per-channel output elements.
        for el in (0, 1, 2):
            _set_uint32(target, kMute, el, 0)

        # Zero device volume is effectively silent even when the mute flag is off.
        _raise_zero_float(target, kVMV, 0, use_service=True)
        for el in (0, 1, 2):
            _raise_zero_float(target, kVol, el)
    except Exception:
        pass


def _macos_output_device_name(device_uid: str = "") -> str | None:
    """CoreAudio's live name for an output UID, or for the current default output.

    Returns "" when that UID is not connected right now and None when CoreAudio
    cannot be queried, so callers can tell "gone" from "unknown".
    """
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.restype = None

        def _fcc(s: str) -> int:
            return int.from_bytes(s.encode(), "big")

        class _PA(ctypes.Structure):
            _fields_ = [("mSel", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mEl", ctypes.c_uint32)]

        k_sys, k_glob = 1, _fcc("glob")

        def _get_str(dev: int, selector: int) -> str:
            pa = _PA(selector, k_glob, 0)
            value = ctypes.c_void_p(0)
            size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
            if ca.AudioObjectGetPropertyData(dev, ctypes.byref(pa), 0, None, ctypes.byref(size), ctypes.byref(value)):
                return ""
            if not value.value:
                return ""
            try:
                buf = ctypes.create_string_buffer(512)
                if not cf.CFStringGetCString(value, buf, len(buf), 0x08000100):
                    return ""
                return buf.value.decode("utf-8", "replace")
            finally:
                cf.CFRelease(value)

        if not device_uid:
            pa = _PA(_fcc("dOut"), k_glob, 0)
            dev = ctypes.c_uint32(0)
            size = ctypes.c_uint32(ctypes.sizeof(dev))
            if ca.AudioObjectGetPropertyData(k_sys, ctypes.byref(pa), 0, None, ctypes.byref(size), ctypes.byref(dev)):
                return None
            return _get_str(int(dev.value), _fcc("lnam")) or None

        pa = _PA(_fcc("dev#"), k_glob, 0)
        size = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(k_sys, ctypes.byref(pa), 0, None, ctypes.byref(size)):
            return None
        ids = (ctypes.c_uint32 * (size.value // ctypes.sizeof(ctypes.c_uint32)))()
        if ca.AudioObjectGetPropertyData(k_sys, ctypes.byref(pa), 0, None, ctypes.byref(size), ids):
            return None
        for dev in ids:
            if _get_str(int(dev), _fcc("uid ")) == device_uid:
                return _get_str(int(dev), _fcc("lnam"))
        return ""
    except Exception:
        return None


def _hostapi_name(sd, device: dict) -> str:
    try:
        return str(sd.query_hostapis(int(device.get("hostapi", 0))).get("name") or "")
    except Exception:
        return ""


def _portaudio_output_index(sd, device_uid: str = "", device_name: str = "") -> int | None:
    """Map a selected output (UID or system default) to a PortAudio index.

    PortAudio identifies devices only by its own launch-time index. On macOS,
    match on the live CoreAudio name first and fall back to the name the UI
    supplied. Windows UIDs are "sounddevice:<index>" from the device list,
    which go stale after a re-enumeration, so the name is checked too and
    WASAPI is preferred when the same device appears under several host APIs.
    """
    live_name = _macos_output_device_name(device_uid)
    if device_uid and live_name == "":
        return None
    if device_uid.startswith("endpoint:") and not device_name:
        device_name = device_uid.split(":", 1)[1]
    devices = list(sd.query_devices())
    if device_uid.startswith("sounddevice:"):
        try:
            index = int(device_uid.split(":", 1)[1])
        except ValueError:
            index = -1
        if 0 <= index < len(devices) and int(devices[index].get("max_output_channels") or 0) > 0 and (
                not device_name or str(devices[index].get("name") or "").casefold() == device_name.casefold()):
            return index
    wanted = [name.casefold() for name in (live_name, device_name if device_uid else "") if name]
    outputs = [(index, str(item.get("name") or "").casefold()) for index, item in enumerate(devices)
               if int(item.get("max_output_channels") or 0) > 0]
    if sys.platform == "win32":
        outputs.sort(key=lambda entry: "wasapi" not in _hostapi_name(sd, devices[entry[0]]).casefold())
    for name in wanted:
        for index, candidate in outputs:
            if candidate == name:
                return index
    for name in wanted:
        for index, candidate in outputs:
            if name in candidate or candidate in name:
                return index
    if device_uid or wanted:
        return None
    default_output = sd.default.device[1]
    if default_output is not None and int(default_output) >= 0 and any(i == int(default_output) for i, _ in outputs):
        return int(default_output)
    return None


def _output_extra_settings(sd, index: int | None):
    """WASAPI shared mode only accepts the device's mix rate (often 48 kHz);
    let it resample 44.1 kHz tracks instead of failing to open."""
    if sys.platform != "win32" or index is None:
        return None
    try:
        if "wasapi" in _hostapi_name(sd, sd.query_devices(index)).casefold():
            return sd.WasapiSettings(auto_convert=True)
    except Exception:
        pass
    return None


def _refresh_portaudio(sd) -> None:
    """Re-enumerate audio devices. Invalidates every open sounddevice stream."""
    sd._terminate()
    sd._initialize()


def _monochrome_http_error(detail: str) -> tuple[int, str]:
    """Pull the HTTP status out of an ffmpeg open failure for Monochrome."""
    import re

    match = re.search(r"Server returned (\d{3})", detail or "")
    status = int(match.group(1)) if match else 0
    if status == 403:
        return status, "Monochrome refused the stream (HTTP 403 access denied)"
    if status == 429:
        return status, "Monochrome is rate-limiting streams (HTTP 429 too many requests)"
    if status:
        return status, f"Monochrome stream failed (HTTP {status})"
    return 0, ""


def _on_android() -> bool:
    return os.environ.get("MINDINGUFLAC_ANDROID") == "1"


def _android_player():
    """The APK's ExoPlayer bridge (NativeAudioPlayer.java), via Chaquopy."""
    from java import jclass  # type: ignore

    return jclass("com.mindinguflac.android.NativeAudioPlayer")


def _android_device_id(device_uid: str) -> int:
    if device_uid.startswith("android:"):
        try:
            return int(device_uid.split(":", 1)[1])
        except ValueError:
            return -1
    return -1


def android_output_devices() -> list[dict]:
    """Outputs the phone can route to, for the app's output menu."""
    import json

    try:
        devices = json.loads(str(_android_player().listOutputs()))
    except Exception:
        return []
    return [{"name": item["name"], "uid": f"android:{item['id']}", "driver": item.get("type", "")}
            for item in devices if isinstance(item, dict) and "id" in item]


class _MonochromeFetch:
    """Download one Monochrome track once, into a temp file all decoders share.

    ffmpeg's HTTP client is HTTP/1.1-only, and Monochrome's storage proxy
    answers those requests with HTTP 400 (IncompleteBody) or tarpits them.
    curl_cffi speaks HTTP/2 with Safari's TLS fingerprint, like the web
    player. Seeks and decoder restarts re-read this file instead of opening a
    new connection, which keeps each track to a single request against
    Monochrome's tight per-IP rate limit.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        directory = Path(tempfile.gettempdir()) / "mindinguflac-stream"
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (hashlib.sha1(url.encode()).hexdigest() + ".audio")
        self.path.unlink(missing_ok=True)
        self.path.touch()
        self.size = 0
        self.total = 0   # full file size once the server has said (0 = unknown)
        self.pins = 0    # downloads waiting on this fetch; never evicted while > 0
        self.done = False
        self.error = ""
        self.http_status = 0
        self.cancelled = threading.Event()
        self.condition = threading.Condition()
        self.thread = threading.Thread(target=self._run, daemon=True, name="monochrome-fetch")
        self.thread.start()

    def _session(self):
        try:
            from curl_cffi import requests as curl_requests
            return curl_requests.Session(impersonate="safari")
        except Exception:
            import httpx  # HTTP/2 fallback when curl_cffi is unavailable
            return httpx.Client(http2=True, follow_redirects=True, timeout=httpx.Timeout(20.0, read=60.0))

    def _headers(self, offset: int) -> dict:
        try:
            import backend_monochrome
            headers = backend_monochrome.stream_request_headers()
        except Exception:
            headers = {"Origin": "https://monochrome.st", "Referer": "https://monochrome.st/"}
        headers["Range"] = f"bytes={offset}-"
        return headers

    def _fail(self, message: str, http_status: int = 0) -> None:
        with self.condition:
            self.error = message
            self.http_status = http_status
            self.condition.notify_all()

    def _run(self) -> None:
        session = None
        try:
            session = self._session()
            failures_without_progress = 0
            resumes = 0
            while not self.cancelled.is_set():
                offset = self.size
                try:
                    if hasattr(session, "stream"):  # httpx
                        context = session.stream("GET", self.url, headers=self._headers(offset))
                    else:
                        context = session.get(self.url, headers=self._headers(offset), stream=True, timeout=(20, 60))
                    with context as response:
                        status = int(response.status_code)
                        if status not in (200, 206):
                            try:
                                import backend_monochrome
                                retry_after = float(response.headers.get("Retry-After") or 0)
                                backend_monochrome.note_stream_rejected(status, retry_after)
                            except Exception:
                                pass
                            _status, message = _monochrome_http_error(f"Server returned {status}")
                            self._fail(message, status)
                            return
                        if offset and status != 206:
                            raise RuntimeError(f"server ignored the resume range (HTTP {status})")
                        import re
                        content_range = str(response.headers.get("Content-Range") or "")
                        range_match = re.search(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                        if range_match:
                            self.total = int(range_match.group(3))
                        elif status == 200 and response.headers.get("Content-Length"):
                            self.total = int(response.headers.get("Content-Length") or 0)
                        # Never trust a resumed response to start where it was
                        # asked to: appending bytes from the wrong position
                        # silently corrupts the FLAC (it decodes up to the
                        # splice, then fails). Skip any overlap; refuse a gap.
                        start = int(range_match.group(1)) if range_match else (0 if status == 200 else offset)
                        if start > offset:
                            raise RuntimeError(f"server resumed at byte {start}, after the requested {offset}")
                        skip = offset - start
                        chunks = response.iter_bytes() if hasattr(response, "iter_bytes") else response.iter_content(chunk_size=65536)
                        with self.path.open("ab") as handle:
                            for chunk in chunks:
                                if self.cancelled.is_set():
                                    return
                                if not chunk:
                                    continue
                                if skip:
                                    dropped = min(skip, len(chunk))
                                    chunk = chunk[dropped:]
                                    skip -= dropped
                                    if not chunk:
                                        continue
                                handle.write(chunk)
                                handle.flush()
                                with self.condition:
                                    self.size += len(chunk)
                                    self.condition.notify_all()
                    if self.total and self.size < self.total:
                        # The server ended the response early but "cleanly".
                        raise RuntimeError(f"connection closed at {self.size} of {self.total} bytes")
                    with self.condition:
                        self.done = True
                        self.condition.notify_all()
                    return
                except Exception as exc:
                    # A dropped connection (e.g. an HTTP/2 INTERNAL_ERROR reset
                    # near the end of a long transfer) resumes from the bytes
                    # already on disk. Keep resuming while each attempt makes
                    # progress; three attempts in a row with no new bytes means
                    # the server is refusing, so stop rather than hammer it.
                    failures_without_progress = 0 if self.size > offset else failures_without_progress + 1
                    resumes += 1
                    if failures_without_progress >= 3 or resumes > 12 or self.cancelled.is_set():
                        self._fail(f"Monochrome stream download failed: {exc}")
                        return
                    print(f"[Monochrome] resuming at byte {self.size} after: {exc}")
                    time.sleep(1.5 * max(1, failures_without_progress))
        except Exception as exc:
            self._fail(f"Monochrome stream download failed: {exc}")
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def read_into(self, write, stop) -> None:
        """Feed the file to ``write`` as it grows until complete, failed or ``stop()``."""
        offset = 0
        with self.path.open("rb") as handle:
            while not stop():
                with self.condition:
                    while self.size <= offset and not self.done and not self.error and not stop():
                        self.condition.wait(timeout=0.25)
                    available, finished = self.size, self.done or bool(self.error)
                if available > offset:
                    handle.seek(offset)
                    data = handle.read(min(available - offset, 262144))
                    offset += len(data)
                    write(data)
                elif finished:
                    return

    def cancel(self) -> None:
        self.cancelled.set()
        with self.condition:
            self.condition.notify_all()
        self.path.unlink(missing_ok=True)


_monochrome_fetch_lock = threading.Lock()
_monochrome_fetches: dict[str, _MonochromeFetch] = {}


def _monochrome_fetch(url: str, pin: bool = False) -> _MonochromeFetch:
    """Shared download for this URL; restarts one that failed, keeps the last two.

    ``pin=True`` is for a library download that must see the fetch through:
    it is not evicted while pinned. Release it with _release_monochrome_fetch.
    """
    with _monochrome_fetch_lock:
        fetch = _monochrome_fetches.pop(url, None)
        if fetch is not None and (fetch.error or fetch.cancelled.is_set()):
            fetch.cancel()
            fetch = None
        if fetch is None:
            fetch = _MonochromeFetch(url)
        _monochrome_fetches[url] = fetch
        if pin:
            fetch.pins += 1
        unpinned = [key for key, item in _monochrome_fetches.items() if item.pins <= 0 and key != url]
        while len(_monochrome_fetches) > 2 and unpinned:
            _monochrome_fetches.pop(unpinned.pop(0)).cancel()
        return fetch


def _release_monochrome_fetch(fetch: _MonochromeFetch) -> None:
    with _monochrome_fetch_lock:
        fetch.pins = max(0, fetch.pins - 1)


def _macos_set_device_mute(device_uid: str, muted: bool) -> None:
    """Best-effort: toggle the CoreAudio mute flag on the selected output."""
    if not device_uid or sys.platform != "darwin":
        return
    try:
        import ctypes

        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

        def _fcc(s: str) -> int:
            return int.from_bytes(s.encode(), "big")

        class _PA(ctypes.Structure):
            _fields_ = [("mSel", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mEl", ctypes.c_uint32)]

        kSys, kGlob, kOutp = ctypes.c_uint32(1), _fcc("glob"), _fcc("outp")
        kDev, kUID, kMute, kUTF8 = _fcc("dev#"), _fcc("uid "), _fcc("mute"), 0x08000100

        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        ca.AudioObjectHasProperty.restype = ctypes.c_bool
        ca.AudioObjectSetPropertyData.restype = ctypes.c_int32
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.restype = None

        def _data_ptr(value):
            return ctypes.cast(value, ctypes.c_void_p)

        def _get_cfstr(dev: int, selector: int) -> str:
            pa_uid = _PA(selector, kGlob, 0)
            value = ctypes.c_void_p(0)
            size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
            if ca.AudioObjectGetPropertyData(dev, ctypes.byref(pa_uid), 0, None, ctypes.byref(size), ctypes.byref(value)):
                return ""
            if not value.value:
                return ""
            try:
                buf = ctypes.create_string_buffer(512)
                if not cf.CFStringGetCString(value, _data_ptr(buf), len(buf), kUTF8):
                    return ""
                return buf.value.decode("utf-8", "replace")
            finally:
                try:
                    cf.CFRelease(value)
                except Exception:
                    pass

        def _set_uint32(dev: int, selector: int, scope: int, element: int, value: int) -> None:
            pa = _PA(selector, scope, element)
            if not ca.AudioObjectHasProperty(dev, ctypes.byref(pa)):
                return
            data = ctypes.c_uint32(value)
            ca.AudioObjectSetPropertyData(
                dev,
                ctypes.byref(pa),
                0,
                None,
                ctypes.c_uint32(ctypes.sizeof(data)),
                ctypes.byref(data),
            )

        pa = _PA(kDev, kGlob, 0)
        sz = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz)):
            return
        ids = (ctypes.c_uint32 * (sz.value // ctypes.sizeof(ctypes.c_uint32)))()
        if ca.AudioObjectGetPropertyData(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz), ids):
            return

        target = None
        for dev in ids:
            dev_id = int(dev)
            if _get_cfstr(dev_id, kUID) == device_uid:
                target = dev_id
                break
        if target is None:
            return

        mute_value = 1 if muted else 0
        for scope in (kOutp, kGlob):
            for el in (0, 1, 2):
                _set_uint32(target, kMute, scope, el, mute_value)
    except Exception:
        pass


def _macos_set_device_volume(device_uid: str, volume: float) -> None:
    """Best-effort: apply scalar volume to the selected CoreAudio output."""
    if not device_uid or sys.platform != "darwin":
        return
    try:
        import ctypes

        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        try:
            ahs = ctypes.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
        except Exception:
            ahs = None

        def _fcc(s: str) -> int:
            return int.from_bytes(s.encode(), "big")

        class _PA(ctypes.Structure):
            _fields_ = [("mSel", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mEl", ctypes.c_uint32)]

        kSys, kGlob, kOutp = ctypes.c_uint32(1), _fcc("glob"), _fcc("outp")
        kDev, kUID, kVol, kVMV, kUTF8 = _fcc("dev#"), _fcc("uid "), _fcc("volm"), _fcc("vmvc"), 0x08000100

        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        ca.AudioObjectHasProperty.restype = ctypes.c_bool
        ca.AudioObjectSetPropertyData.restype = ctypes.c_int32
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.restype = None
        if ahs is not None:
            try:
                ahs.AudioHardwareServiceHasProperty.restype = ctypes.c_bool
                ahs.AudioHardwareServiceGetPropertyData.restype = ctypes.c_int32
                ahs.AudioHardwareServiceSetPropertyData.restype = ctypes.c_int32
            except Exception:
                ahs = None

        def _data_ptr(value):
            return ctypes.cast(value, ctypes.c_void_p)

        def _get_cfstr(dev: int, selector: int) -> str:
            pa_uid = _PA(selector, kGlob, 0)
            value = ctypes.c_void_p(0)
            size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
            if ca.AudioObjectGetPropertyData(dev, ctypes.byref(pa_uid), 0, None, ctypes.byref(size), ctypes.byref(value)):
                return ""
            if not value.value:
                return ""
            try:
                buf = ctypes.create_string_buffer(512)
                if not cf.CFStringGetCString(value, _data_ptr(buf), len(buf), kUTF8):
                    return ""
                return buf.value.decode("utf-8", "replace")
            finally:
                try:
                    cf.CFRelease(value)
                except Exception:
                    pass

        def _set_float(dev: int, selector: int, element: int, value: float, use_service: bool = False) -> bool:
            pa = _PA(selector, kOutp, element)
            has_prop = ahs.AudioHardwareServiceHasProperty if use_service and ahs is not None else ca.AudioObjectHasProperty
            set_prop = ahs.AudioHardwareServiceSetPropertyData if use_service and ahs is not None else ca.AudioObjectSetPropertyData
            if not has_prop(dev, ctypes.byref(pa)):
                return False
            data = ctypes.c_float(max(0.0, min(1.0, float(value))))
            err = set_prop(
                dev,
                ctypes.byref(pa),
                0,
                None,
                ctypes.c_uint32(ctypes.sizeof(data)),
                ctypes.byref(data),
            )
            return not bool(err)

        pa = _PA(kDev, kGlob, 0)
        sz = ctypes.c_uint32(0)
        if ca.AudioObjectGetPropertyDataSize(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz)):
            return
        ids = (ctypes.c_uint32 * (sz.value // ctypes.sizeof(ctypes.c_uint32)))()
        if ca.AudioObjectGetPropertyData(kSys, ctypes.byref(pa), 0, None, ctypes.byref(sz), ids):
            return

        target = None
        for dev in ids:
            dev_id = int(dev)
            if _get_cfstr(dev_id, kUID) == device_uid:
                target = dev_id
                break
        if target is None:
            return

        if volume <= 0.0001:
            _macos_set_device_mute(device_uid, True)
        else:
            _macos_set_device_mute(device_uid, False)

        applied = _set_float(target, kVMV, 0, volume, use_service=True)
        for el in (1, 2):
            applied = _set_float(target, kVol, el, volume) or applied
        if not applied:
            _set_float(target, kVol, 0, volume)
    except Exception:
        pass


class NativeAudioManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream_output_condition = threading.Condition(self._lock)
        self._sound = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._stream_pause_ack = threading.Event()
        self._path = ""
        self._playback_path = ""  # actual file handed to the player (may be a transcode)
        self._device_uid = ""
        self._error = ""
        self._playing = False
        self._ended = False
        self._position = 0.0
        self._duration = 0.0
        self._volume = 1.0
        self._metadata = {}
        # macOS NSSound finish-detection: currentTime() can reset to 0 when a
        # sound finishes, so "position near duration" is unreliable. Track
        # whether we paused and whether playback was ever observed instead.
        self._paused = False
        self._has_played = False
        self._stream_url = ""
        self._stream_device_name = ""
        self._stream_process = None
        self._stream_output = None
        self._stream_sample_rate = 44100
        self._stream_channels = 2
        self._stream_id = 0
        self._stream_output_revision = 0
        self._stream_output_applied_revision = 0
        self._stream_output_failed_revision = 0
        self._stream_output_error = ""
        self._stream_phase = "idle"
        self._stream_buffered_seconds = 0.0
        self._stream_started_at = 0.0
        self._stream_http_status = 0
        self._windows_output_index: int | None = None
        self._android_active = False
        self._android_noted_stream = 0

    # ------------------------------------------------------------- Android
    # ExoPlayer in NativeAudioPlayer.java does the decoding, buffering, seeking
    # and output routing; these methods only translate the desktop contract.

    def _android_play(self, source: str, device_uid: str, device_name: str, volume: float,
                      position: float, metadata: dict | None, stream: bool) -> dict:
        import json

        headers = ""
        if stream:
            try:
                import backend_monochrome
                headers = json.dumps(backend_monochrome.stream_request_headers())
            except Exception:
                headers = ""
        result = json.loads(str(_android_player().play(
            source, headers, _android_device_id(device_uid), device_name or "",
            max(0.0, min(1.0, float(volume))), max(0.0, float(position or 0)))))
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error") or "Native audio failed"}
        with self._lock:
            self._android_active = True
            self._stream_url = source if stream else ""
            self._path = "" if stream else source
            self._device_uid = device_uid or ""
            self._stream_device_name = device_name or ""
            self._metadata = metadata or {}
            self._volume = max(0.0, min(1.0, float(volume)))
            self._paused = False
            self._error = ""
            self._stream_output_revision += 1
            self._stream_output_applied_revision = self._stream_output_revision
            self._android_noted_stream = 0
        return self.status() | {"ok": True}

    def _android_set_output(self, device_uid: str, device_name: str) -> dict:
        import json

        result = json.loads(str(_android_player().setOutput(_android_device_id(device_uid), device_name or "")))
        with self._lock:
            self._stream_output_revision += 1
            revision = self._stream_output_revision
            if result.get("ok"):
                self._device_uid = device_uid or ""
                self._stream_device_name = device_name or ""
                self._stream_output_applied_revision = revision
        if not result.get("ok"):
            return self.status() | {"ok": False, "error": result.get("error") or "Could not change the audio output",
                                    "output_revision": revision}
        return self.status() | {"ok": True, "output_revision": revision, "output_applied_revision": revision}

    def _android_status(self) -> dict:
        import json

        try:
            snapshot = json.loads(str(_android_player().status()))
        except Exception as exc:
            snapshot = {"active": False, "error": str(exc)}
        with self._lock:
            active = bool(getattr(self, "_android_active", False))
            stream = bool(self._stream_url)
            http_status = int(snapshot.get("http_status") or 0)
            error = str(snapshot.get("error") or "")
            if stream and http_status:
                _status, message = _monochrome_http_error(f"Server returned {http_status}")
                error = message or error
                stream_id = int(snapshot.get("stream_id") or 0)
                if http_status in (403, 429) and getattr(self, "_android_noted_stream", 0) != stream_id:
                    self._android_noted_stream = stream_id
                    try:
                        import backend_monochrome
                        backend_monochrome.note_stream_rejected(http_status)
                    except Exception:
                        pass
            notice = str(snapshot.get("notice") or "")
            if notice and int(snapshot.get("device_id", -1)) < 0 and self._device_uid:
                # The chosen output disconnected; ExoPlayer moved to the phone.
                self._device_uid = ""
                self._stream_device_name = ""
            ended = bool(snapshot.get("ended"))
            playing = bool(snapshot.get("playing")) and not self._paused
            if error:
                phase = "error"
            elif ended:
                phase = "ended"
            elif self._paused:
                phase = "paused"
            elif playing:
                phase = "playing"
            else:
                phase = "buffering"
            result = {
                "available": True, "playing": playing, "ended": ended,
                "buffering": bool(snapshot.get("buffering")) and not self._paused and not error and not ended,
                "position": float(snapshot.get("position") or 0.0),
                "duration": float(snapshot.get("duration") or 0.0) or _metadata_duration_ms(self._metadata) / 1000.0,
                "path": self._path if active else "", "device_uid": self._device_uid, "volume": self._volume,
                "error": error if active else "", "metadata": self._metadata if active else {},
                "output_revision": self._stream_output_revision,
                "output_applied_revision": self._stream_output_applied_revision,
                "output_notice": notice, "output_latency": 0.0,
            }
            if stream and active:
                result |= {
                    "stream_id": int(snapshot.get("stream_id") or 0), "stream_phase": phase,
                    "stream_http_status": http_status,
                    "buffered_seconds": float(snapshot.get("buffered") or 0.0),
                    "prebuffer_target_seconds": 0.0,
                    "stream_elapsed_seconds": float(snapshot.get("elapsed") or 0.0),
                }
            return result

    def _stream_output_latency(self) -> float:
        output = self._stream_output
        try:
            return max(0.0, float(output.latency)) if output is not None else 0.0
        except Exception:
            return 0.0

    def available(self) -> bool:
        if _on_android():
            try:
                return bool(_android_player().available())
            except Exception as exc:
                self._error = str(exc)
                return False
        if sys.platform == "darwin":
            try:
                import AppKit  # noqa: F401
                import AVFoundation  # noqa: F401
                import CoreAudio  # noqa: F401
                import sounddevice  # noqa: F401
                return True
            except Exception as exc:
                self._error = str(exc)
                return False
        if sys.platform == "win32":
            try:
                import sounddevice  # noqa: F401
                import soundfile  # noqa: F401
                return True
            except Exception as exc:
                self._error = str(exc)
                return False
        return False

    def play_stream(self, url: str, device_uid: str = "", device_name: str = "",
                    volume: float = 1.0, position: float = 0.0,
                    metadata: dict | None = None) -> dict:
        """Play a remote audio stream directly to a selected native output.

        ffmpeg decodes the HTTP response into PCM on stdout; no audio file or
        cache/download job is created. Pause keeps the PCM output thread alive
        and resume continues from its current position.
        """
        if sys.platform not in ("darwin", "win32") and not _on_android():
            return {"ok": False, "error": "Direct native streaming is only available on macOS, Windows and Android"}
        if not url or not url.startswith("https://tracks.monochrome.st/track/"):
            return {"ok": False, "error": "Unsupported native stream URL"}
        try:
            import backend_monochrome
            blocked = backend_monochrome.stream_block_reason()
        except Exception:
            blocked = ""
        if blocked:
            return {"ok": False, "error": blocked, "stream_blocked": True}
        if _on_android():
            return self._android_play(url, device_uid, device_name, volume, position, metadata, stream=True)
        if not self.available():
            return {"ok": False, "error": self._error or "Native audio is unavailable"}
        ffmpeg = _ffmpeg_exe()
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg is required for native stream playback"}
        if device_uid:
            _macos_unmute_device(device_uid)
        self._stop()
        with self._lock:
            self._stream_url = url
            self._stream_device_name = device_name
            self._device_uid = device_uid
            self._stream_output_revision += 1
            self._path = ""
            self._playback_path = ""
            self._position = max(0.0, float(position or 0))
            self._duration = max(0.0, _metadata_duration_ms(metadata) / 1000.0)
            self._volume = max(0.0, min(1.0, float(volume)))
            self._metadata = metadata or {}
            self._error = ""
            self._ended = False
            self._paused = False
            self._playing = False
            self._stream_id += 1
            self._stream_phase = "buffering"
            self._stream_buffered_seconds = 0.0
            self._stream_http_status = 0
            self._stream_started_at = time.monotonic()
            self._stop_event.clear()
            self._pause_event.clear()
            self._stream_pause_ack.clear()
            self._thread = threading.Thread(target=self._stream_worker, args=(ffmpeg,),
                                            daemon=True, name="native-audio-stream")
            self._thread.start()
        return self.status() | {"ok": True}

    def set_stream_output(self, device_uid: str = "", device_name: str = "") -> dict:
        """Reroute the active Monochrome decoder without reopening its HTTP stream."""
        if _on_android():
            return self._android_set_output(device_uid, device_name)
        # Check CoreAudio's live list, not PortAudio's launch-time snapshot: a
        # Bluetooth speaker that reconnected since launch is missing from the
        # latter until the worker re-enumerates it.
        if device_uid and _macos_output_device_name(device_uid) == "":
            return {"ok": False, "error": f"Selected output is not connected: {device_name or device_uid}"}
        with self._stream_output_condition:
            if not self._stream_url or self._thread is None or not self._thread.is_alive():
                return {"ok": False, "error": "No active Monochrome stream to reroute"}
            previous_uid = self._device_uid
            previous_name = self._stream_device_name
            self._device_uid = str(device_uid or "")
            self._stream_device_name = str(device_name or "")
            self._stream_output_revision += 1
            self._error = ""
            self._stream_output_error = ""
            if self._pause_event.is_set():
                self._stream_phase = "paused"
            elif self._playing:
                self._stream_phase = "playing"
            else:
                self._stream_phase = "buffering"
            revision = self._stream_output_revision
            self._stream_output_condition.notify_all()
        with self._stream_output_condition:
            deadline = time.monotonic() + 10.0
            while (self._stream_output_applied_revision < revision and
                   self._stream_output_failed_revision < revision):
                if self._error:
                    return self.status() | {"ok": False, "error": self._error,
                                            "output_revision": revision}
                if self._thread is None or not self._thread.is_alive():
                    return self.status() | {"ok": False,
                                            "error": "Monochrome stream ended before the output switch applied",
                                            "output_revision": revision}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self._stream_output_revision == revision:
                        # Roll the requested route back. If a slow device open
                        # eventually completes, the worker will see this newer
                        # revision and discard it while keeping the current
                        # output alive.
                        self._device_uid = previous_uid
                        self._stream_device_name = previous_name
                        self._stream_output_revision += 1
                        self._stream_output_error = "Audio output switch timed out; previous output restored"
                        self._stream_output_condition.notify_all()
                    return self.status() | {"ok": False,
                                            "error": self._stream_output_error or "Audio output switch timed out; previous output restored",
                                            "output_revision": revision,
                                            "output_applied_revision": self._stream_output_applied_revision}
                self._stream_output_condition.wait(timeout=remaining)
            if self._stream_output_failed_revision >= revision:
                return self.status() | {"ok": False,
                                        "error": self._stream_output_error or "Could not open the selected audio output",
                                        "output_revision": revision}
            return self.status() | {"ok": True, "output_revision": revision,
                                    "output_applied_revision": self._stream_output_applied_revision}

    def _stream_worker(self, ffmpeg: str) -> None:
        process = None
        output = None
        try:
            import sounddevice as sd
            start_at = max(0.0, self._position)
            fetch = _monochrome_fetch(self._stream_url)
            command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
            if start_at > 0:
                # Seeking on piped input decodes from the start and trims, which
                # is fast because the bytes come from the shared local file.
                command += ["-ss", f"{start_at:.3f}"]
            command += ["-i", "pipe:0",
                        "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(self._stream_sample_rate),
                        "-ac", str(self._stream_channels), "pipe:1"]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._lock:
                self._stream_process = process
            pcm_read_size = 2048 * self._stream_channels * 4
            if sys.platform == "win32":
                # Windows pipes have no dependable non-blocking read, so a
                # reader thread hands decoded PCM over through a queue.
                import queue
                pcm_queue: queue.Queue = queue.Queue(maxsize=64)
                pcm_eof = threading.Event()

                def pump_pcm() -> None:
                    try:
                        while True:
                            chunk = process.stdout.read(pcm_read_size)
                            if not chunk:
                                break
                            while not self._stop_event.is_set():
                                try:
                                    pcm_queue.put(chunk, timeout=0.25)
                                    break
                                except queue.Full:
                                    continue
                            if self._stop_event.is_set():
                                break
                    except (OSError, ValueError):
                        pass
                    finally:
                        pcm_eof.set()

                threading.Thread(target=pump_pcm, daemon=True, name="native-audio-pcm").start()

                def read_pcm() -> bytes | None:
                    """Next PCM chunk, None when none is ready yet, b"" at EOF."""
                    try:
                        return pcm_queue.get(timeout=0.01)
                    except queue.Empty:
                        return b"" if pcm_eof.is_set() and pcm_queue.empty() else None
            else:
                os.set_blocking(process.stdout.fileno(), False)

                def read_pcm() -> bytes | None:
                    """Next PCM chunk, None when none is ready yet, b"" at EOF."""
                    try:
                        return os.read(process.stdout.fileno(), pcm_read_size)
                    except BlockingIOError:
                        time.sleep(0.01)
                        return None

            def feed_decoder() -> None:
                try:
                    fetch.read_into(process.stdin.write,
                                    lambda: self._stop_event.is_set() or process.poll() is not None)
                except (BrokenPipeError, OSError, ValueError):
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass

            threading.Thread(target=feed_decoder, daemon=True, name="native-audio-feed").start()

            def fetch_failure() -> RuntimeError | None:
                if not fetch.error:
                    return None
                with self._lock:
                    self._stream_http_status = fetch.http_status
                return RuntimeError(fetch.error)

            bytes_per_frame = self._stream_channels * 4
            frames_per_block = 2048
            prebuffer_bytes = int(self._stream_sample_rate * bytes_per_frame * _NATIVE_STREAM_PREBUFFER_SECONDS)
            pending_pcm = bytearray()
            started_output = False
            active_revision = -1
            failed_revision = -1
            active_device_uid = ""
            active_device_name = ""

            def open_route(uid: str, name: str):
                index = _portaudio_output_index(sd, uid, name)
                if index is None:
                    raise LookupError(f"Selected output is unavailable to the native audio driver: {name or uid or 'system default'}")
                stream = sd.OutputStream(samplerate=self._stream_sample_rate, channels=self._stream_channels,
                                         dtype="float32", device=index, latency="low",
                                         extra_settings=_output_extra_settings(sd, index))
                try:
                    stream.start()
                except Exception:
                    stream.close()
                    raise
                return stream

            def close_output() -> None:
                nonlocal output
                if output is None:
                    return
                try:
                    output.abort()
                except Exception:
                    pass
                try:
                    output.close()
                except Exception:
                    pass
                output = None
                with self._lock:
                    self._stream_output = None

            def reopen_after_refresh(uid: str, name: str):
                # PortAudio enumerates devices once. A Bluetooth output that
                # (re)connected since then is invisible or has a dead device id
                # until PortAudio re-initialises, which also invalidates the
                # open stream — so it is closed first and the queued PCM kept.
                close_output()
                _refresh_portaudio(sd)
                return open_route(uid, name)

            def recover_from_write_error(exc: Exception) -> None:
                # The playing output vanished (Bluetooth dropped, device sleep).
                # Keep the decoder and its buffer, move to the system default,
                # and publish that as a new route the UI can follow.
                nonlocal output, active_revision, active_device_uid, active_device_name
                try:
                    replacement = reopen_after_refresh("", "")
                except Exception:
                    raise exc
                output = replacement
                with self._stream_output_condition:
                    self._stream_output_revision += 1
                    active_revision = self._stream_output_revision
                    active_device_uid = active_device_name = ""
                    self._device_uid = ""
                    self._stream_device_name = ""
                    self._stream_output = output
                    self._stream_output_applied_revision = active_revision
                    self._stream_output_error = f"Audio output disconnected ({exc}); playing on This computer"
                    self._stream_output_condition.notify_all()

            def write_block(pcm) -> bool:
                """Write to the device; False means a route change needs the block back."""
                # Device writes can block while CoreAudio drains its hardware
                # buffer. Never hold the manager lock across one: route changes
                # and pause/resume must stay responsive on a slow output.
                try:
                    output.write(pcm)
                    return True
                except Exception as exc:
                    if self._stop_event.is_set():
                        raise
                    with self._lock:
                        route_changed = self._stream_output_revision != active_revision
                    if not route_changed:
                        recover_from_write_error(exc)
                    return False

            while not self._stop_event.is_set():
                with self._lock:
                    revision = self._stream_output_revision
                    device_name = self._stream_device_name
                    device_uid = self._device_uid
                if revision != active_revision and revision != failed_revision:
                    if (output is not None and device_uid == active_device_uid and
                            device_name == active_device_name):
                        active_revision = revision
                        with self._stream_output_condition:
                            self._stream_output_applied_revision = revision
                            self._stream_output_error = ""
                            self._stream_output_condition.notify_all()
                        continue
                    replacement_output = None
                    route_error = ""
                    restored = False
                    try:
                        replacement_output = open_route(device_uid, device_name)
                    except Exception as exc:
                        route_error = str(exc)
                    if replacement_output is None:
                        try:
                            replacement_output = reopen_after_refresh(device_uid, device_name)
                            route_error = ""
                        except Exception as exc:
                            route_error = str(exc) or route_error
                    if replacement_output is None and active_revision != -1:
                        # The refresh closed the old output; put it back so a
                        # failed switch leaves audio exactly where it was.
                        for uid, name in ((active_device_uid, active_device_name), ("", "")):
                            try:
                                output = open_route(uid, name)
                            except Exception:
                                continue
                            active_device_uid, active_device_name = uid, name
                            restored = True
                            with self._lock:
                                self._stream_output = output
                            break
                    if replacement_output is None:
                        failed_revision = revision
                        with self._stream_output_condition:
                            self._device_uid = active_device_uid
                            self._stream_device_name = active_device_name
                            self._stream_output_failed_revision = revision
                            self._stream_output_error = route_error or "Could not open the selected audio output"
                            self._stream_output_condition.notify_all()
                        # Keep the decoder alive on the previous output. A later
                        # user selection can request another route revision.
                        if output is None:
                            raise RuntimeError(route_error or "Could not open any audio output")
                        continue
                    with self._lock:
                        route_is_current = self._stream_output_revision == revision
                    if not route_is_current:
                        if output is None:
                            # The refresh already closed the old route; adopt
                            # this one until the newer request is applied.
                            output = replacement_output
                            active_device_uid, active_device_name = device_uid, device_name
                            with self._lock:
                                self._stream_output = output
                        else:
                            try:
                                replacement_output.abort()
                            except Exception:
                                pass
                            replacement_output.close()
                        continue
                    previous_output = output if not restored else None
                    output = replacement_output
                    active_revision = revision
                    failed_revision = -1
                    active_device_uid = device_uid
                    active_device_name = device_name
                    with self._stream_output_condition:
                        self._stream_output = output
                        self._stream_output_applied_revision = active_revision
                        self._stream_output_error = ""
                        if not self._pause_event.is_set():
                            self._stream_phase = "playing" if self._playing else "buffering"
                        self._stream_output_condition.notify_all()
                    if previous_output is not None and previous_output is not output:
                        try:
                            previous_output.abort()
                        except Exception:
                            pass
                        try:
                            previous_output.close()
                        except Exception:
                            pass
                if self._pause_event.is_set():
                    self._stream_pause_ack.set()
                    time.sleep(0.03)
                    continue
                data = read_pcm()
                if data is None:
                    continue
                if not data:
                    if process.poll() is not None:
                        detail = process.stderr.read().decode("utf-8", "replace")[-1000:]
                        # A download failure ends ffmpeg's input early; report
                        # the HTTP cause instead of a decoder or "ended" state.
                        failure = fetch_failure()
                        if failure is not None:
                            raise failure
                        if process.returncode:
                            raise RuntimeError(detail.strip() or f"ffmpeg exited with {process.returncode}")
                        if pending_pcm:
                            started_output = True
                            while pending_pcm and not self._stop_event.is_set():
                                if self._pause_event.is_set():
                                    break
                                block_bytes = min(len(pending_pcm), frames_per_block * bytes_per_frame)
                                block_bytes -= block_bytes % bytes_per_frame
                                if not block_bytes:
                                    pending_pcm.clear()  # trailing partial frame
                                    break
                                block = bytes(pending_pcm[:block_bytes])
                                del pending_pcm[:block_bytes]
                                frames = block_bytes // bytes_per_frame
                                import numpy as np
                                pcm = np.frombuffer(block, dtype=np.float32).reshape(-1, self._stream_channels)
                                with self._lock:
                                    pcm = pcm * self._volume
                                if not write_block(pcm):
                                    pending_pcm[:0] = block
                                    break
                                with self._lock:
                                    self._position += frames / self._stream_sample_rate
                                    self._playing = not self._pause_event.is_set()
                                    self._stream_phase = "playing" if self._playing else "paused"
                                    self._stream_buffered_seconds = len(pending_pcm) / (self._stream_sample_rate * bytes_per_frame)
                        if self._pause_event.is_set():
                            continue
                        with self._lock:
                            route_changed = self._stream_output_revision != active_revision
                        if route_changed or pending_pcm:
                            continue
                        with self._lock:
                            self._ended = True
                            self._playing = False
                            self._stream_phase = "ended"
                        break
                    continue
                pending_pcm.extend(data)
                with self._lock:
                    self._stream_buffered_seconds = len(pending_pcm) / (self._stream_sample_rate * bytes_per_frame)
                if not started_output and len(pending_pcm) < prebuffer_bytes and process.poll() is None:
                    continue
                started_output = True
                while len(pending_pcm) >= bytes_per_frame and not self._stop_event.is_set():
                    if self._pause_event.is_set():
                        break
                    block_bytes = min(len(pending_pcm), frames_per_block * bytes_per_frame)
                    block_bytes -= block_bytes % bytes_per_frame
                    block = bytes(pending_pcm[:block_bytes])
                    del pending_pcm[:block_bytes]
                    with self._lock:
                        if self._stream_output_revision != active_revision:
                            pending_pcm[:0] = block
                            break
                    frames = block_bytes // bytes_per_frame
                    import numpy as np
                    pcm = np.frombuffer(block, dtype=np.float32).reshape(-1, self._stream_channels)
                    with self._lock:
                        pcm = pcm * self._volume
                    if not write_block(pcm):
                        pending_pcm[:0] = block
                        with self._lock:
                            self._stream_buffered_seconds = len(pending_pcm) / (self._stream_sample_rate * bytes_per_frame)
                        break
                    with self._lock:
                        self._position += frames / self._stream_sample_rate
                        self._playing = not self._pause_event.is_set()
                        self._stream_phase = "playing" if self._playing else "paused"
                        self._stream_buffered_seconds = len(pending_pcm) / (self._stream_sample_rate * bytes_per_frame)
        except Exception as exc:
            with self._stream_output_condition:
                if not self._stop_event.is_set():
                    self._error = str(exc)
                    self._playing = False
                    self._stream_phase = "error"
                self._stream_output_condition.notify_all()
        finally:
            if output is not None:
                with self._lock:
                    if self._stream_output is output:
                        self._stream_output = None
                try:
                    output.stop()
                except Exception:
                    pass
                try:
                    output.close()
                except Exception:
                    pass
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=1)
                except Exception:
                    try: process.kill()
                    except Exception: pass
            with self._stream_output_condition:
                self._stream_process = None
                self._stream_output = None
                self._stream_output_condition.notify_all()

    def play(self, path: str, device_uid: str = "", volume: float = 1.0, position: float = 0.0,
             metadata: dict | None = None, device_name: str = "") -> dict:
        if not self.available():
            return {"ok": False, "error": self._error or "Native audio is unavailable"}
        if _on_android():
            if not Path(path).expanduser().is_file():
                return {"ok": False, "error": "Audio file not found"}
            return self._android_play(str(Path(path).expanduser()), device_uid, device_name,
                                      volume, position, metadata, stream=False)

        audio_path = Path(path).expanduser()
        if not audio_path.is_file():
            return {"ok": False, "error": "Audio file not found"}

        if sys.platform == "win32":
            res = self._play_windows(audio_path, device_uid, volume, position, device_name)
            if res.get("ok"):
                with self._lock:
                    self._metadata = metadata or {}
            return res

        try:
            from AppKit import NSSound
            from Foundation import NSURL

            # NSSound can't decode some formats (notably YouTube webm/opus); use a
            # transcoded WAV when needed so native output works with every file.
            playback_path = _native_playable_path(audio_path)
            url = NSURL.fileURLWithPath_(playback_path)
            sound = NSSound.alloc().initWithContentsOfURL_byReference_(url, True)
            if (not sound or float(sound.duration() or 0) <= 0) and playback_path == str(audio_path.resolve()):
                # Opened to nothing (or refused) on an extension we didn't expect
                # to need transcoding — try converting once more.
                converted = _transcode_to_wav(audio_path)
                if converted:
                    playback_path = converted
                    url = NSURL.fileURLWithPath_(playback_path)
                    sound = NSSound.alloc().initWithContentsOfURL_byReference_(url, True)
            if not sound:
                return {"ok": False, "error": "Unable to open audio file"}

            self._stop()

            if device_uid:
                sound.setPlaybackDeviceIdentifier_(device_uid)
                # Unmute the target device first, so a left-muted output isn't silent.
                _macos_unmute_device(device_uid)
                _macos_set_device_volume(device_uid, volume)
            sound.setVolume_(max(0.0, min(1.0, float(volume))))
            if position > 0:
                sound.setCurrentTime_(max(0.0, float(position)))

            with self._lock:
                self._sound = sound
                self._path = str(audio_path.resolve())
                self._playback_path = playback_path
                self._device_uid = device_uid
                self._error = ""
                self._volume = max(0.0, min(1.0, float(volume)))
                self._metadata = metadata or {}
                self._paused = False
                self._has_played = False
                self._playing = True
                self._ended = False

                if not sound.play():
                    self._sound = None
                    self._playing = False
                    self._error = "Native audio player refused to start"
                    return {"ok": False, "error": self._error}

            return self.status() | {"ok": True}
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
            return {"ok": False, "error": str(exc)}

    def pause(self) -> dict:
        if _on_android():
            with self._lock:
                self._paused = True
            _android_player().pause()
            return self.status() | {"ok": True}
        wait_for_stream = False
        with self._lock:
            self._paused = True
            self._playing = False
            if self._stream_url and self._thread is not None:
                self._pause_event.set()
                wait_for_stream = True
            elif sys.platform == "win32" and self._thread is not None:
                self._pause_event.set()
                self._playing = False
            elif self._sound is not None:
                try:
                    self._sound.pause()
                except Exception:
                    pass
        if wait_for_stream:
            # Never wait for the worker while holding its state lock: the
            # worker may be finishing an output write and needs that lock
            # before it can acknowledge the pause.
            self._stream_pause_ack.wait(timeout=2.0)
            with self._lock:
                self._playing = False
                self._stream_phase = "paused"
        return self.status() | {"ok": True}

    def resume(self) -> dict:
        if _on_android():
            with self._lock:
                self._paused = False
            _android_player().resume()
            return self.status() | {"ok": True}
        with self._lock:
            self._paused = False
            self._ended = False
            if self._stream_url and self._thread is not None:
                self._stream_pause_ack.clear()
                self._pause_event.clear()
                self._playing = False
                self._stream_phase = "buffering"
            elif sys.platform == "win32" and self._thread is not None:
                self._pause_event.clear()
                self._playing = True
            elif self._sound is not None:
                try:
                    # NSSound.isPlaying() keeps returning True even after pause(),
                    # so it can't tell us whether we actually need to resume.
                    # Always attempt to resume; fall back to replaying from the
                    # saved position only if resume() truly fails.
                    if not self._sound.resume():
                        pos = self._sound.currentTime()
                        if pos > 0:
                            self._sound.setCurrentTime_(pos)
                        if not self._sound.play():
                            return self.status() | {"ok": False, "error": "Native audio player refused to resume"}
                    self._playing = True
                except Exception as e:
                    return self.status() | {"ok": False, "error": str(e)}
        return self.status() | {"ok": True}

    def stop(self) -> dict:
        if _on_android():
            _android_player().stop()
            with self._lock:
                self._stream_url = ""
                self._path = ""
                self._android_active = False
            return self.status() | {"ok": True}
        self._stop()
        return self.status() | {"ok": True}

    def seek(self, position: float) -> dict:
        if _on_android():
            _android_player().seek(max(0.0, float(position)))
            return self.status() | {"ok": True}
        stream = None
        windows_restart = None
        with self._lock:
            if self._stream_url and self._thread is not None:
                url, uid, name = self._stream_url, self._device_uid, self._stream_device_name
                volume = self._volume
                metadata = self._metadata
                was_paused = self._paused
                stream = (url, uid, name, volume, metadata, was_paused)
                position = max(0.0, float(position))
            elif sys.platform == "win32" and self._thread is not None:
                windows_restart = (
                    self._path, self._playback_path, self._device_uid,
                    max(0.0, float(position)), self._volume, self._duration,
                )
            elif self._sound is not None:
                duration = float(self._sound.duration() or 0)
                target = max(0.0, min(duration if duration > 0 else float(position), float(position)))
                self._sound.setCurrentTime_(target)
        if stream:
            url, uid, name, volume, metadata, was_paused = stream
            target = max(0.0, float(position))
            self._stop()
            result = self.play_stream(url, uid, name, volume, target, metadata)
            if was_paused and result.get("ok"):
                self.pause()
            return result
        if windows_restart:
            path, playback_path, device_uid, target, volume, duration = windows_restart
            self._stop()
            with self._lock:
                self._path = path
                self._playback_path = playback_path
                self._device_uid = device_uid
                self._position = target
                self._volume = volume
                self._duration = duration
                self._ended = False
                self._playing = True
                self._thread = threading.Thread(target=self._windows_worker, daemon=True, name="native-audio-win")
                self._thread.start()
        return self.status() | {"ok": True}

    def set_volume(self, volume: float) -> dict:
        if _on_android():
            with self._lock:
                self._volume = max(0.0, min(1.0, float(volume)))
            _android_player().setVolume(self._volume)
            return self.status() | {"ok": True}
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))
            if self._sound is not None:
                self._sound.setVolume_(self._volume)
            if self._device_uid and sys.platform == "darwin":
                if self._volume > 0.0001:
                    _macos_unmute_device(self._device_uid)
                _macos_set_device_volume(self._device_uid, self._volume)
        return self.status() | {"ok": True}

    def status(self) -> dict:
        if _on_android():
            return self._android_status()
        with self._lock:
            if self._stream_url:
                return {"available": self.available(), "playing": self._playing and not self._paused,
                        "ended": self._ended, "position": self._position, "duration": self._duration,
                        "path": "", "device_uid": self._device_uid, "volume": self._volume,
                        "error": self._error, "metadata": self._metadata,
                        "stream_id": self._stream_id, "stream_phase": self._stream_phase,
                        "output_revision": self._stream_output_revision,
                        "output_applied_revision": self._stream_output_applied_revision,
                        "output_notice": self._stream_output_error,
                        # Seconds between "written to the device" (position)
                        # and "heard" — ~1s on Bluetooth. Video sync uses it.
                        "output_latency": self._stream_output_latency(),
                        "stream_http_status": self._stream_http_status,
                        "buffered_seconds": self._stream_buffered_seconds,
                        "prebuffer_target_seconds": _NATIVE_STREAM_PREBUFFER_SECONDS,
                        "stream_elapsed_seconds": max(0.0, time.monotonic() - self._stream_started_at) if self._stream_started_at else 0.0}
            if sys.platform == "win32":
                return {
                    "available": self.available(),
                    "playing": self._playing,
                    "ended": self._ended,
                    "position": self._position,
                    "duration": self._duration,
                    "path": self._path,
                    "device_uid": self._device_uid,
                    "volume": self._volume,
                    "error": self._error,
                    "metadata": self._metadata,
                }
            sound = self._sound
            if sound is None:
                return {
                    "available": self.available(),
                    "playing": False,
                    "position": 0,
                    "duration": 0,
                    "path": self._path,
                    "device_uid": self._device_uid,
                    "error": self._error,
                    "metadata": self._metadata,
                }
            duration = float(sound.duration() or 0)
            position = float(sound.currentTime() or 0)
            # NSSound.isPlaying() can incorrectly report True even after pause()
            # is called, so we must explicitly check the _paused flag.
            raw_playing = bool(sound.isPlaying())
            if raw_playing:
                self._playing = True
                if position > 0:
                    self._has_played = True

            # NSSound resets currentTime to 0 on finish, so the position check
            # is unreliable on its own. A sound that was playing (observed movement)
            # and is now stopped (raw_playing=False) without the user pausing it,
            # and is either at 0 or the end, has finished.
            if not raw_playing and self._has_played and not self._paused:
                if position == 0 or (duration > 0 and position >= duration - 0.1):
                    self._playing = False
                    self._ended = True

            playing = bool((raw_playing or self._playing) and not self._paused and not self._ended)
            # NSSound resets currentTime to 0 on finish.
            ended = bool(self._ended or (not raw_playing and self._has_played and not self._paused and (position == 0 or (duration > 0 and position >= duration - 0.1))))
            return {
                "available": True,
                "playing": playing,
                "ended": ended,
                "position": position,
                "duration": duration,
                "path": self._path,
                "device_uid": self._device_uid,
                "volume": float(sound.volume()),
                "error": self._error,
                "metadata": self._metadata,
            }

    def _stop(self) -> None:
        # Signal the worker under the lock, but wait without it. The output
        # worker needs this lock to finish its current PCM block; joining while
        # holding it could time out and let an old stream overlap its replacement.
        with self._lock:
            thread = self._thread
            process = self._stream_process
            sound = self._sound
            self._stop_event.set()
            self._pause_event.clear()
            self._playing = False
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass
        if sound is not None:
            try:
                sound.stop()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive() and process is not None:
                try:
                    process.kill()
                except Exception:
                    pass
                thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError("Previous native audio stream did not stop; refusing to start a duplicate")
        with self._lock:
            if self._thread is thread:
                self._thread = None
            self._stop_event.clear()
            self._pause_event.clear()
            self._playing = False
            self._sound = None
            self._stream_url = ""
            self._stream_device_name = ""
            self._stream_process = None
            self._stream_phase = "idle"
            self._stream_buffered_seconds = 0.0
            self._stream_started_at = 0.0

    def _play_windows(self, audio_path: Path, device_uid: str, volume: float, position: float,
                      device_name: str = "") -> dict:
        # soundfile (libsndfile) can't read m4a/mp3/opus/webm; transcode when needed.
        playback_path = _native_playable_path(audio_path)
        try:
            import soundfile as sf
            try:
                with sf.SoundFile(playback_path) as audio_file:
                    duration = len(audio_file) / float(audio_file.samplerate or 1)
            except Exception:
                converted = _transcode_to_wav(audio_path)
                if not converted:
                    raise
                playback_path = converted
                with sf.SoundFile(playback_path) as audio_file:
                    duration = len(audio_file) / float(audio_file.samplerate or 1)
        except Exception as exc:
            return {"ok": False, "error": f"Unable to open audio file: {exc}"}

        self._stop()
        # Resolve the output now, with no stream open, so a device missing from
        # PortAudio's launch-time list (Bluetooth connected later, or a stale
        # saved index) can be re-enumerated safely — and a device that is truly
        # gone fails here, letting the UI fall back to This computer.
        device_index = None
        if device_uid:
            try:
                import sounddevice as sd
                device_index = _portaudio_output_index(sd, device_uid, device_name)
                if device_index is None:
                    _refresh_portaudio(sd)
                    device_index = _portaudio_output_index(sd, device_uid, device_name)
            except Exception as exc:
                return {"ok": False, "error": f"Could not open the selected output: {exc}"}
            if device_index is None:
                return {"ok": False, "error": f"Selected output is not connected: {device_name or device_uid}"}
        with self._lock:
            self._windows_output_index = device_index
            self._path = str(audio_path.resolve())
            self._playback_path = playback_path
            self._device_uid = device_uid
            self._error = ""
            self._ended = False
            self._playing = True
            self._position = max(0.0, min(float(position or 0), duration))
            self._duration = duration
            self._volume = max(0.0, min(1.0, float(volume)))
            self._thread = threading.Thread(target=self._windows_worker, daemon=True, name="native-audio-win")
            self._thread.start()
        return self.status() | {"ok": True}

    def _windows_device_index(self) -> int | None:
        """PortAudio index resolved by _play_windows (None = system default)."""
        return self._windows_output_index

    def _windows_worker(self) -> None:
        try:
            import sounddevice as sd
            import soundfile as sf

            with sf.SoundFile(self._playback_path or self._path) as audio_file:
                with self._lock:
                    start_frame = int(max(0, self._position) * audio_file.samplerate)
                    device_index = self._windows_device_index()
                audio_file.seek(min(start_frame, len(audio_file)))
                with sd.OutputStream(
                    samplerate=audio_file.samplerate,
                    channels=audio_file.channels,
                    dtype="float32",
                    device=device_index,
                    extra_settings=_output_extra_settings(sd, device_index),
                ) as stream:
                    while not self._stop_event.is_set():
                        if self._pause_event.is_set():
                            time.sleep(0.05)
                            continue
                        data = audio_file.read(2048, dtype="float32", always_2d=True)
                        if len(data) == 0:
                            with self._lock:
                                self._playing = False
                                self._ended = True
                                self._position = self._duration
                            break
                        with self._lock:
                            volume = self._volume
                            self._position = audio_file.tell() / float(audio_file.samplerate or 1)
                            self._playing = True
                        stream.write(data * volume)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._playing = False


native_audio = NativeAudioManager()
