"""Android pieces Mornye's JS providers need: Node.js and a challenge solver.

Node ships in the APK as ``libmindinguflac_node.so`` because Android only lets
an app execute files from its native library directory. Mornye looks ``node``
up on PATH, so a ``node`` symlink to it goes first on PATH.

Mornye's ``core.solver`` drives a desktop Chromium through pydoll and cannot
import here. Signed-session providers call its ``solve_with_callback`` when a
challenge must be passed; the stand-in registered below opens it in a Chrome
Custom Tab (MornyeVerification.java), as Mornye's own Android app does. The
grant comes back through the deep link mornye://session-grant.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

NODE_LIBRARY = "libmindinguflac_node.so"
# Mornye runs these by name to remux, decrypt, convert and validate downloads
# (scripts/build_android_ffmpeg.py).
TOOL_LIBRARIES = {"ffmpeg": "libmindinguflac_ffmpeg.so", "ffprobe": "libmindinguflac_ffprobe.so"}
# vendor/mornye-extensions, packaged by build.gradle.kts.
BUNDLED_EXTENSIONS = Path(__file__).resolve().parent / "mornye_extensions"
# Long enough to notice a notification and pass the check, but inside the
# 170 s the bridge gives session.signedFetch (_bridge.js), itself inside the
# provider's 180 s call timeout. Mornye's app waits 180 s.
_VERIFY_SECONDS = 150
# The Zarz page redirects only to Mornye's or SpotiFLAC's scheme; SpotiFLAC is
# a separate installed app, so the grant comes back as Mornye's deep link,
# caught by MornyeGrantActivity.
_CALLBACK = "mornye://session-grant"


def _application():
    from java import jclass  # type: ignore

    return jclass("com.chaquo.python.Python").getPlatform().getApplication()


def configure_node() -> Path | None:
    """Put the APK's Node (and ffmpeg/ffprobe) first on PATH; None if Node is missing."""
    try:
        library_dir = Path(str(_application().getApplicationInfo().nativeLibraryDir))
    except Exception:
        return None
    library = library_dir / NODE_LIBRARY
    if not library.is_file():
        return None
    # Internal cache, not MINDINGUFLAC_CACHE_DIR: that one is on shared
    # storage, where SELinux refuses to create the symlink.
    cache = Path(str(_application().getCacheDir()))
    folder = cache / "mornye-bin"
    link = folder / "node"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tools = {"node": library}
        tools.update({name: library_dir / file for name, file in TOOL_LIBRARIES.items() if (library_dir / file).is_file()})
        for name, target in tools.items():
            # The library directory changes with every app update.
            entry = folder / name
            if not entry.is_symlink() or os.readlink(entry) != str(target):
                entry.unlink(missing_ok=True)
                entry.symlink_to(target)
        # os.tmpdir() falls back to /tmp, which apps cannot use.
        temporary = cache / "mornye-tmp"
        temporary.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[Mornye] Node.js unavailable: {exc}")
        return None
    current = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item and item != str(folder)]
    os.environ["PATH"] = os.pathsep.join([str(folder), *current])
    os.environ["TMPDIR"] = str(temporary)
    install_solver()
    return link


def _callback_state(challenge_url: str) -> str:
    callback = (parse_qs(urlparse(challenge_url).query).get("cb") or [""])[0]
    return (parse_qs(urlparse(callback).query).get("state") or [""])[0]


def _with_callback(challenge_url: str) -> str:
    """Point the challenge's ``cb`` at the app's deep link.

    Mornye builds ``cb`` with a placeholder loopback address, which the page
    drops (it then has nowhere to send the grant); ``cb_version`` and
    ``state`` are kept.
    """
    parts = urlparse(challenge_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    callback_query = urlparse(query.get("cb") or "").query
    query["cb"] = f"{_CALLBACK}?{callback_query}" if callback_query else _CALLBACK
    return urlunparse(parts._replace(query=urlencode(query)))


def solve_with_callback(sitekey: str, siteurl: str, timeout: int = 45, hold_open_seconds: float = 0.0,
                        cancel_event=None, browser_info=None) -> tuple[str, str | None]:
    from java import jclass  # type: ignore

    verification = jclass("com.mindinguflac.android.MornyeVerification")
    grant = ""
    try:
        print("[Mornye] verification opened")
        if verification.request(_with_callback(siteurl), _callback_state(siteurl)):
            for _ in range(_VERIFY_SECONDS):
                if cancel_event is not None and cancel_event.is_set():
                    break
                grant = str(verification.awaitGrant(1000) or "")
                if grant:
                    break
    finally:
        verification.finish(bool(grant))
        print("[Mornye] verification grant received" if grant else "[Mornye] verification ended without a grant")
    return "", grant or None


def install_solver() -> None:
    """Register the Custom Tab solver as ``mornye.core.solver`` if pydoll's cannot load."""
    if "mornye.core.solver" in sys.modules:
        return
    try:
        import mornye.core.solver  # noqa: F401  (a desktop-style runtime, if ever present)
        return
    except Exception:
        pass
    module = types.ModuleType("mornye.core.solver")
    module.solve_with_callback = solve_with_callback
    module._kill_by_profile_dir = lambda profile_dir: None
    sys.modules["mornye.core.solver"] = module
    import mornye.core as core
    core.solver = module


def _version(folder: Path):
    from packaging.version import InvalidVersion, Version

    try:
        return Version(str(json.loads((folder / "manifest.json").read_text("utf-8")).get("version") or "0"))
    except (OSError, ValueError, InvalidVersion):
        return None


def seed_extensions(target: Path, bundled: Path = BUNDLED_EXTENSIONS) -> list[str]:
    """Install the APK's provider extensions that are missing or older in ``target``.

    A copy the user installed or updated to a newer version is left alone.
    """
    if not bundled.is_dir():
        return []
    target.mkdir(parents=True, exist_ok=True)
    installed = []
    for source in sorted(bundled.iterdir()):
        if not (source / "manifest.json").is_file():
            continue
        destination = target / source.name
        current = _version(destination) if destination.exists() else None
        offered = _version(source)
        if destination.exists() and (offered is None or (current is not None and current >= offered)):
            continue
        temporary = target / (".bundled-" + secrets.token_hex(8))
        retired = target / (".retired-" + secrets.token_hex(8))
        try:
            shutil.copytree(source, temporary)
            if destination.exists():
                destination.rename(retired)
            temporary.rename(destination)
            installed.append(source.name)
        except OSError:
            shutil.rmtree(temporary, ignore_errors=True)
            if retired.exists() and not destination.exists():
                retired.rename(destination)
        finally:
            shutil.rmtree(retired, ignore_errors=True)
    return installed
