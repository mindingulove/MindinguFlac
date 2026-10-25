from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "build" / "desktop-jre"
MODULES = "java.base,java.logging,java.management,java.naming,java.net.http,java.prefs,java.security.sasl,java.xml,jdk.unsupported"


def build_runtime() -> Path:
    home = os.environ.get("JAVA_HOME")
    if home:
        jlink = Path(home) / "bin" / ("jlink.exe" if os.name == "nt" else "jlink")
    else:
        found = shutil.which("jlink")
        if not found and os.name != "nt":
            for candidate in (
                Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin/jlink"),
                Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin/jlink"),
            ):
                if candidate.is_file():
                    found = str(candidate)
                    break
        jlink = Path(found or "jlink")
    if not jlink.is_file() and not shutil.which(str(jlink)):
        raise RuntimeError("Building the desktop torrent engine requires a Java 17+ JDK with jlink")
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(jlink), "--add-modules", MODULES, "--strip-debug", "--no-header-files",
        "--no-man-pages", "--compress=2", "--output", str(OUTPUT),
    ], check=True)
    return OUTPUT


def build_runtime_archive() -> Path:
    runtime = build_runtime()
    archive = ROOT / "build" / "desktop-jre.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in runtime.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(runtime).as_posix())
    return archive


if __name__ == "__main__":
    print(build_runtime_archive())
