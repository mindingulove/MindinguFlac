from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
JARS = ROOT / "jars"
CLASSES = ROOT / "classes"
SOURCE = ROOT / "src/com/mindinguflac/desktop/DesktopTorrentEngine.java"
ANDROID_SOURCE = REPO / "android-app/app/src/main/java/com/mindinguflac/android/AndroidTorrentEngine.java"
JAVA_HOME = Path(os.environ.get("JAVA_HOME") or "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")


def build_bridge() -> Path:
    javac = JAVA_HOME / "bin/javac"
    if os.name == "nt":
        javac = JAVA_HOME / "bin/javac.exe"
    if not javac.exists():
        javac = Path(shutil.which("javac") or "javac")
    # Generate the desktop bridge from Android's proven JNI implementation so
    # session settings, file selection, warm swarms, and slot behavior cannot drift.
    generated = ROOT / "build/generated-java/com/mindinguflac/desktop/DesktopTorrentEngine.java"
    generated.parent.mkdir(parents=True, exist_ok=True)
    source = ANDROID_SOURCE.read_text(encoding="utf-8")
    source = source.replace("package com.mindinguflac.android;", "package com.mindinguflac.desktop;")
    source = source.replace("AndroidTorrentEngine", "DesktopTorrentEngine")
    source = source.replace("Android-native libtorrent bridge used by the embedded Python backend.",
                            "Desktop jlibtorrent 2 bridge generated from Android's shared engine.")
    source = source.replace('value.put("abi", "arm64-v8a");',
                            'value.put("abi", System.getProperty("os.arch"));')
    source = source.replace('LibTorrent.jlibtorrentVersion() + " arm64"',
                            'LibTorrent.jlibtorrentVersion() + " " + System.getProperty("os.arch")')
    generated.write_text(source, encoding="utf-8")
    CLASSES.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(javac), "-source", "17", "-target", "17", "-cp",
        os.pathsep.join((str(JARS / "jlibtorrent-2.0.12.9.jar"), str(JARS / "json-20240303.jar"))),
        "-d", str(CLASSES), str(generated),
    ], check=True, cwd=REPO)
    return CLASSES


if __name__ == "__main__":
    print(build_bridge())
