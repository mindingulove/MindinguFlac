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


class NativeAudioManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sound = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
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

    def available(self) -> bool:
        if sys.platform == "darwin":
            try:
                import AppKit  # noqa: F401
                import AVFoundation  # noqa: F401
                import CoreAudio  # noqa: F401
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

    def play(self, path: str, device_uid: str = "", volume: float = 1.0, position: float = 0.0, metadata: dict | None = None) -> dict:
        if not self.available():
            return {"ok": False, "error": self._error or "Native audio is unavailable"}

        audio_path = Path(path).expanduser()
        if not audio_path.is_file():
            return {"ok": False, "error": "Audio file not found"}

        if sys.platform == "win32":
            res = self._play_windows(audio_path, device_uid, volume, position)
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

            if device_uid:
                sound.setPlaybackDeviceIdentifier_(device_uid)
            sound.setVolume_(max(0.0, min(1.0, float(volume))))
            if position > 0:
                sound.setCurrentTime_(max(0.0, float(position)))

            with self._lock:
                self._stop_locked()
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
        with self._lock:
            self._paused = True
            self._playing = False
            if sys.platform == "win32" and self._thread is not None:
                self._pause_event.set()
                self._playing = False
            elif self._sound is not None:
                try:
                    self._sound.pause()
                except Exception:
                    pass
        return self.status() | {"ok": True}

    def resume(self) -> dict:
        with self._lock:
            self._paused = False
            self._ended = False
            if sys.platform == "win32" and self._thread is not None:
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
        with self._lock:
            self._stop_locked()
        return self.status() | {"ok": True}

    def seek(self, position: float) -> dict:
        with self._lock:
            if sys.platform == "win32" and self._thread is not None:
                self._position = max(0.0, float(position))
                self._restart_windows_locked()
            elif self._sound is not None:
                duration = float(self._sound.duration() or 0)
                target = max(0.0, min(duration if duration > 0 else float(position), float(position)))
                self._sound.setCurrentTime_(target)
        return self.status() | {"ok": True}

    def set_volume(self, volume: float) -> dict:
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))
            if self._sound is not None:
                self._sound.setVolume_(self._volume)
        return self.status() | {"ok": True}

    def status(self) -> dict:
        with self._lock:
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

    def _stop_locked(self) -> None:
        if self._thread is not None:
            self._stop_event.set()
            thread = self._thread
            self._thread = None
            if thread.is_alive():
                try:
                    thread.join(timeout=1)
                except RuntimeError:
                    pass
            self._stop_event.clear()
            self._pause_event.clear()
            self._playing = False
        if self._sound is not None:
            try:
                self._sound.stop()
            except Exception:
                pass
        self._sound = None
        self._playing = False

    def _play_windows(self, audio_path: Path, device_uid: str, volume: float, position: float) -> dict:
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

        with self._lock:
            self._stop_locked()
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
        uid = self._device_uid or ""
        if uid.startswith("sounddevice:"):
            try:
                return int(uid.split(":", 1)[1])
            except ValueError:
                return None
        return None

    def _restart_windows_locked(self) -> None:
        path = self._path
        playback_path = self._playback_path
        device_uid = self._device_uid
        position = self._position
        volume = self._volume
        self._stop_locked()
        self._path = path
        self._playback_path = playback_path
        self._device_uid = device_uid
        self._position = position
        self._volume = volume
        self._ended = False
        self._playing = True
        self._thread = threading.Thread(target=self._windows_worker, daemon=True, name="native-audio-win")
        self._thread.start()

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
