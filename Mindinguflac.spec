# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

# Ensure project root is in path for analysis
sys.path.insert(0, os.path.abspath('.'))

datas = [('static', 'static')]
binaries = []
hiddenimports = [
    'bluetooth_scan', 
    'IOBluetooth', 
    'AVFoundation', 
    'CoreAudio', 
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
    'backend_ytpdl',
    'catalog',
    'service_downloader',
    'ai_reranker',
    'duck_proxy',
    'ddg_browser',
    'tour_ai', 'hypebot_tour', 'gemini_proxy', 'gemini_browser',
    'db'
]
# SpotiFLAC — all imports now use 'SpotiFLAC.*' (updated from old 'backend.*' API).
try:
    tmp_ret = collect_all('SpotiFLAC')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    hiddenimports += collect_submodules('SpotiFLAC')
except Exception:
    pass

# rapidfuzz has C extensions and is imported at module level across multiple files.
try:
    tmp_ret = collect_all('rapidfuzz')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

# pydantic-core is a Rust extension — PyInstaller needs it explicitly collected.
for _pkg in ('pydantic', 'pydantic_core'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

# httpx with http2 pulls in h2/hpack/hyperframe which may not be traced statically.
for _pkg in ('httpx', 'httpcore', 'h2', 'hpack', 'hyperframe'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

# countrystatecity_countries is imported inside a try block (dynamic-ish).
try:
    tmp_ret = collect_all('countrystatecity_countries')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

# mutagen, cryptography, pywebview bundled for completeness.
for _pkg in ('mutagen', 'cryptography', 'pywebview'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass

try:
    tmp_ret = collect_all('torrfetch')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    hiddenimports += collect_submodules('torrfetch')
except Exception:
    pass

# libtorrent ships as a compiled extension — collect_all ensures its .so and
# any data files are bundled alongside the hiddenimport entry.
try:
    tmp_ret = collect_all('libtorrent')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

# imageio-ffmpeg bundles a static ffmpeg binary used by the ytp-dl YouTube
# postprocessors. Collect its binaries folder so get_ffmpeg_exe() resolves in
# the frozen app.
try:
    tmp_ret = collect_all('imageio_ffmpeg')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

# yt-dlp is imported dynamically so PyInstaller won't detect it automatically.
try:
    tmp_ret = collect_all('yt_dlp')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    hiddenimports += collect_submodules('yt_dlp')
except Exception:
    pass

# Playwright (Duck.ai AI-reranker browser worker). collect_all bundles the node
# driver + package data; playwright_stealth bundles its JS evasion files. NOTE:
# the actual Chromium browser is NOT bundled — it lives in the per-user
# ms-playwright cache, so the app still needs a one-time
# `python -m playwright install chromium`. The reranker degrades gracefully if
# the browser is unavailable.
for _pkg in ('playwright', 'playwright_stealth'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass


helper = Path('build/macos/MindinguflacNowPlayingHelper')
if helper.is_file():
    binaries.append((str(helper), '.'))

import shutil
_ffmpeg = shutil.which('ffmpeg')
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
    excludes=['MediaLibrary', 'Photos', 'Contacts', 'EventKit', 'CoreLocation'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Mindinguflac',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['build/icons/mindinguflac.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Mindinguflac',
)
app = BUNDLE(
    coll,
    name='Mindinguflac.app',
    icon='build/icons/mindinguflac.icns',
    bundle_identifier='com.mindinguflac.app',
    info_plist={
        'CFBundleShortVersionString': '1.1.1',
        'CFBundleVersion': '1.1.1',
        'NSHumanReadableCopyright': 'Copyright © 2026 Mindingulove. All rights reserved.',
        'NSBluetoothAlwaysUsageDescription': 'Mindinguflac needs Bluetooth access to discover and connect audio devices.',
        'NSBluetoothPeripheralUsageDescription': 'Mindinguflac needs Bluetooth access to discover and connect audio devices.',
        'NSMicrophoneUsageDescription': 'Mindinguflac needs microphone access to correctly identify some audio output devices.',
    },
)
