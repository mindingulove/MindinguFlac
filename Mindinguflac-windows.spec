# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

datas = [('static', 'static')]
binaries = []
hiddenimports = [
    'bluetooth_scan',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'webview.platforms.mshtml',
    'clr',
    'torrfetch',
    'libtorrent',
    'torrent_sources',
    'music_metadata',
    'isrc_resolver',
    'discogs_metadata',
    'backend_torrent',
    'backend_spotiflac',
    'backend_tidal_hifi',
    'backend_monochrome',
    'backend_video',
    'vcredist',
    'backend_ytpdl',
    'catalog',
    'service_downloader',
    'ai_reranker',
    'duck_proxy',
    'ddg_browser',
    'tour_ai', 'gemini_proxy', 'gemini_browser',
    'native_audio',
    'db',
]

def _collect_package(package_name, include_submodules=False):
    try:
        tmp_ret = collect_all(package_name)
        datas.extend(tmp_ret[0])
        binaries.extend(tmp_ret[1])
        hiddenimports.extend(tmp_ret[2])
        if include_submodules:
            hiddenimports.extend(collect_submodules(package_name))
    except Exception:
        pass


for _pkg in (
    'SpotiFLAC',
    'torrfetch',
    'yt_dlp',
    'rapidfuzz',
    'pydantic', 'pydantic_core',
    'httpx', 'httpcore', 'h2', 'hpack', 'hyperframe',
    'mutagen', 'cryptography',
    'countrystatecity_countries',
):
    _collect_package(_pkg)

datas += collect_data_files('webview')
hiddenimports += collect_submodules('webview')

_collect_package('bleak')

# libtorrent must be collected, not just hidden-imported: its win_amd64 wheel
# ships dependent native DLLs (OpenSSL etc.) next to libtorrent.pyd. Without
# collect_all those DLLs are missing from the bundle and the packaged app fails
# with "DLL load failed while importing libtorrent: The specified module could
# not be found."
for package_name in ('libtorrent', 'PIL', 'git', 'pythonnet', 'clr_loader', 'sounddevice', 'soundfile', 'numpy', 'imageio_ffmpeg', 'playwright', 'playwright_stealth'):
    _collect_package(package_name)

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _playwright:
        _chromium_executable = Path(_playwright.chromium.executable_path)
    _chromium_root = str(_chromium_executable.parent.parent)
    if _chromium_executable.exists():
        datas.append((_chromium_root, f"ms-playwright/{_chromium_executable.parent.parent.name}"))
except Exception:
    pass

for module_name in (
    'winrt',
    'winrt.windows.devices.bluetooth',
    'winrt.windows.devices.bluetooth.advertisement',
    'winrt.windows.devices.enumeration',
    'winrt.windows.foundation',
):
    try:
        hiddenimports += collect_submodules(module_name)
    except Exception:
        pass

import shutil
_ffmpeg = shutil.which('ffmpeg.exe') or shutil.which('ffmpeg')
if _ffmpeg:
    binaries.append((_ffmpeg, '.'))

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['AppKit', 'Foundation', 'IOBluetooth', 'objc', 'MediaLibrary', 'Photos', 'Contacts', 'EventKit', 'CoreLocation'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    exclude_binaries=False,
    name='Mindinguflac',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    # Extracts to %LOCALAPPDATA%\Mindinguflac\runtime\_MEI<build_hash> on first
    # run; reuses that folder on subsequent runs; re-extracts only when the
    # build hash changes (i.e. a new release).
    runtime_tmpdir=r'%LOCALAPPDATA%\Mindinguflac\runtime',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['build/icons/mindinguflac.ico'],
)
