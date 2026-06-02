"""Ensure the x64 Visual C++ runtime is present on Windows.

libtorrent's ``win_amd64`` wheel depends on the x64 VC++ 2015-2022 runtime
(``VCRUNTIME140.dll`` / ``VCRUNTIME140_1.dll`` / ``MSVCP140.dll``). On a fresh
Windows-on-ARM box (e.g. Parallels) only the ARM64 runtime ships, so the
x64-emulated app fails to import libtorrent with:

    DLL load failed while importing libtorrent: The specified module could not be found.

This module:
  1. detects whether the x64 runtime is installed,
  2. tries to install it automatically (downloads the official redistributable
     and runs it; the installer self-elevates via UAC), and
  3. otherwise hands back the official download link so the UI can tell the user
     to install it.

Everything is a no-op on non-Windows platforms.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import urllib.request

logger = logging.getLogger(__name__)

# Official Microsoft "latest supported" x64 VC++ 2015-2022 redistributable.
VC_REDIST_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def vc_redist_x64_installed() -> bool:
    """Return True if the x64 VC++ runtime appears to be installed.

    Non-Windows always returns True (nothing to install). The redistributable
    records its presence in the registry regardless of host architecture, which
    is the most reliable signal on Windows-on-ARM; DLL presence is a fallback.
    """
    if not _is_windows():
        return True

    try:
        import winreg

        for hive, path in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
        ):
            try:
                with winreg.OpenKey(hive, path) as key:
                    installed, _ = winreg.QueryValueEx(key, "Installed")
                    if int(installed) == 1:
                        return True
            except OSError:
                continue
    except Exception:
        pass

    windir = os.environ.get("WINDIR", r"C:\Windows")
    for dll in ("VCRUNTIME140_1.dll", "MSVCP140.dll", "VCRUNTIME140.dll"):
        if os.path.exists(os.path.join(windir, "System32", dll)):
            return True
    return False


def install_vc_redist_x64(timeout: int = 600) -> tuple[bool, str]:
    """Download and silently install the x64 VC++ runtime.

    Returns ``(ok, message)``. ``ok`` is True on success (or when already
    installed). On failure ``message`` carries the download link and a short
    instruction for the user. The installer self-elevates (UAC prompt).
    """
    if not _is_windows():
        return True, ""
    if vc_redist_x64_installed():
        return True, ""

    installer = os.path.join(tempfile.gettempdir(), "vc_redist.x64.exe")
    try:
        logger.info("Downloading x64 VC++ runtime from %s", VC_REDIST_X64_URL)
        urllib.request.urlretrieve(VC_REDIST_X64_URL, installer)
    except Exception as exc:
        logger.warning("Could not download VC++ runtime: %s", exc)
        return False, _manual_install_message()

    try:
        logger.info("Installing x64 VC++ runtime (a UAC prompt may appear)...")
        # /install /passive shows a progress bar and lets the bundle self-elevate;
        # 0 = success, 3010 = success but reboot recommended, 1638 = newer present.
        proc = subprocess.run(
            [installer, "/install", "/passive", "/norestart"],
            timeout=timeout,
        )
        if proc.returncode in (0, 3010, 1638):
            return True, ""
        logger.warning("VC++ runtime installer exited with code %s", proc.returncode)
        return False, _manual_install_message()
    except Exception as exc:
        logger.warning("Could not run VC++ runtime installer: %s", exc)
        return False, _manual_install_message()


def _manual_install_message() -> str:
    return (
        "The x64 Microsoft Visual C++ runtime is required for the torrent engine "
        "(libtorrent) but could not be installed automatically. Please download "
        f"and install it manually from:\n    {VC_REDIST_X64_URL}\n"
        "(install the x64 build — not arm64 — then restart Mindinguflac)."
    )


def ensure_vc_redist_for_libtorrent(original_error: BaseException) -> None:
    """Best-effort recovery for a failed ``import libtorrent`` on Windows.

    If the x64 VC++ runtime is missing, tries to install it so a subsequent
    ``import libtorrent`` can succeed. Raises ``RuntimeError`` with an
    actionable, link-bearing message when automatic recovery is not possible.
    On non-Windows it simply re-raises the original import error.
    """
    if not _is_windows():
        raise original_error

    if vc_redist_x64_installed():
        # Runtime is present, so the import failure is something else; surface it.
        raise original_error

    ok, message = install_vc_redist_x64()
    if ok:
        return  # caller retries `import libtorrent`
    raise RuntimeError(message) from original_error
