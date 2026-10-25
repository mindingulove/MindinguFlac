"""Load the shared jlibtorrent 2 JNI engine from the desktop app."""
from __future__ import annotations

import glob
import os
import platform
import shutil
import sys
import threading
import zipfile
from pathlib import Path


_LOCK = threading.Lock()
_ENGINE = None
_JRE_HOME = None


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates = (base, base.parent / "Resources", Path(sys.executable).parent.parent / "Resources")
        return next((path for path in candidates if (path / "desktop_torrent").is_dir()), base)
    return Path(__file__).resolve().parent


def _platform_jar() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
        return f"jlibtorrent-macosx-{arch}-2.0.12.9.jar"
    if system == "windows":
        if machine not in {"amd64", "x86_64"}:
            raise RuntimeError("Desktop jlibtorrent currently supports Windows x64")
        return "jlibtorrent-windows-2.0.12.9.jar"
    raise RuntimeError(f"Unsupported desktop jlibtorrent platform: {system}/{machine}")


def _bundled_jre(root: Path) -> Path | None:
    global _JRE_HOME
    if _JRE_HOME is not None and (_JRE_HOME / "release").is_file():
        return _JRE_HOME
    for candidate in (root / "jre", root / "build/desktop-jre"):
        if (candidate / "release").is_file():
            _JRE_HOME = candidate
            return candidate
    archive = root / "desktop-jre.zip"
    if not archive.is_file():
        return None
    if platform.system() == "Darwin":
        runtime_base = Path.home() / "Library/Application Support/Mindinguflac/runtime"
    elif platform.system() == "Windows":
        runtime_base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Mindinguflac/runtime"
    else:
        runtime_base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "Mindinguflac/runtime"
    destination = runtime_base / "jre-17"
    if not (destination / "release").is_file():
        runtime_base.mkdir(parents=True, exist_ok=True)
        staging = runtime_base / "jre-17.installing"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
        if not (staging / "release").is_file():
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError("Bundled Java runtime archive is incomplete")
        shutil.rmtree(destination, ignore_errors=True)
        staging.replace(destination)
    _JRE_HOME = destination
    return destination


def _jvm_path() -> str:
    candidates = []
    if os.environ.get("JAVA_HOME"):
        home = Path(os.environ["JAVA_HOME"])
        candidates.extend((home / "lib/server/libjvm.dylib", home / "lib/server/libjvm.so",
                           home / "bin/server/jvm.dll"))
    root = _resource_root()
    bundled = _bundled_jre(root)
    if bundled is not None:
        candidates.extend((bundled / "lib/server/libjvm.dylib",
                           bundled / "lib/server/libjvm.so",
                           bundled / "bin/server/jvm.dll"))
    if platform.system() == "Darwin":
        candidates.extend(Path(p) for p in glob.glob(
            "/Library/Java/JavaVirtualMachines/*/Contents/Home/lib/server/libjvm.dylib"))
        for prefix in ("/opt/homebrew", "/usr/local"):
            candidates.extend(Path(prefix, f"opt/openjdk@{version}/libexec/openjdk.jdk/Contents/Home/lib/server/libjvm.dylib")
                              for version in ("17", "21", "") if version)
    elif platform.system() == "Windows":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.extend(Path(p) for p in glob.glob(str(Path(base) / "Java/*/bin/server/jvm.dll")))
    java = shutil.which("java")
    if java:
        candidates.append(Path(java).resolve().parent.parent / "lib/server/libjvm.so")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("jlibtorrent 2 needs the bundled Java runtime or Java 17+ installed")


def engine_class():
    """Return the singleton Java engine class, starting its JVM on first use."""
    global _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        try:
            import jpype
        except ImportError as exc:
            raise RuntimeError("Desktop jlibtorrent bridge is missing JPype1") from exc
        root = _resource_root()
        jars = root / "desktop_torrent" / "jars"
        classes = root / "desktop_torrent" / "classes"
        classpath = [str(classes), str(jars / "jlibtorrent-2.0.12.9.jar"),
                     str(jars / _platform_jar()), str(jars / "json-20240303.jar")]
        missing = [path for path in classpath if not Path(path).exists()]
        if missing:
            raise RuntimeError("Desktop jlibtorrent files are missing: " + ", ".join(missing))
        if not jpype.isJVMStarted():
            jpype.startJVM(_jvm_path(), classpath=classpath, convertStrings=True)
        _ENGINE = jpype.JClass("com.mindinguflac.desktop.DesktopTorrentEngine")
        return _ENGINE
