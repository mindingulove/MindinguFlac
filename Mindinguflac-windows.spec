# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

datas = [
    ("local_metadata/LICENSE", "local_metadata"),
    ("local_metadata/PROVENANCE.md", "local_metadata"),
    ('static', 'static'),
]
binaries = []
hiddenimports = [
    'bluetooth_scan',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'webview.platforms.mshtml',
    'clr',
    'torrfetch',
    'torrent_race', 'desktop_jlibtorrent',
    'torrent_sources',
    'music_metadata',
    'isrc_resolver',
    'discogs_metadata',
    'backend_torrent',
    'backend_spotiflac', 'backend_mornye', 'mornye_bridge', 'mornye_runtime',
    'local_metadata.artist_profile', 'local_metadata.lyrics', 'local_metadata.apple_ttml',
    'local_metadata.spotify_totp', 'local_metadata.response_cache', 'local_metadata.apple_music_metadata', 'local_metadata.http',
    'backend_tidal_hifi',
    'backend_monochrome',
    'video_sync',
    'video_sources',
    'backend_video',
    'vcredist',
    'backend_ytpdl',
    'catalog',
    'service_downloader',
    'device_sync',
    'ai_reranker',
    'duck_proxy',
    'codex_proxy',
    'browser_worker_proxy',
    'ddg_browser',
    'tour_ai', 'gemini_proxy', 'gemini_browser',
    'native_audio',
    'db',
]
hiddenimports += collect_submodules('qrcode')

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
    'mornye',
    # Mornye browser-backed session helpers use pydoll.
    'pydoll',
    'torrfetch',
    'yt_dlp',
    'yt_dlp_ejs',
    'rapidfuzz',
    'pydantic', 'pydantic_core',
    'httpx', 'httpcore', 'h2', 'hpack', 'hyperframe',
    'mutagen', 'cryptography', 'browser_cookie3', 'lz4', 'codex_auth', 'openai', 'httpx2', 'httpcore2',
    'countrystatecity_countries',
):
    _collect_package(_pkg)

datas += collect_data_files('webview')
hiddenimports += collect_submodules('webview')

_collect_package('bleak')

for package_name in ('PIL', 'git', 'pythonnet', 'clr_loader', 'sounddevice', 'soundfile', 'numpy', 'imageio_ffmpeg', 'playwright', 'playwright_stealth', 'jpype'):
    _collect_package(package_name)

from desktop_torrent.build_bridge import build_bridge
from desktop_torrent.build_runtime import build_runtime_archive
build_bridge()
_jre = build_runtime_archive()
datas.extend([
    (str(Path('desktop_torrent/classes')), 'desktop_torrent/classes'),
    (str(Path('desktop_torrent/jars')), 'desktop_torrent/jars'),
    (str(_jre), '.'),
])

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

# The lyrics aligner ships its verified model and native CPU bridge.
import subprocess
subprocess.run([sys.executable, 'scripts/prepare_lyrics_alignment.py', '--build-desktop'], check=True)
_lyrics_build = Path('build/lyrics-whisper/windows/Release') if sys.platform == 'win32' else Path('build/lyrics-whisper/macos')
_lyrics_library = _lyrics_build / ('lyrics_whisper.dll' if sys.platform == 'win32' else 'liblyrics_whisper.dylib')
binaries.append((str(_lyrics_library), '.'))
datas.append(('assets/lyrics-alignment', 'assets/lyrics-alignment'))
datas += [(str(Path('native/lyrics_alignment') / name), 'assets/lyrics-alignment') for name in ('assets.json', 'THIRD_PARTY_NOTICES.md')]
hiddenimports.append('lyrics_alignment')

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['SpotiFLAC', 'AppKit', 'Foundation', 'IOBluetooth', 'objc', 'MediaLibrary', 'Photos', 'Contacts', 'EventKit', 'CoreLocation'],
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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['build/icons/mindinguflac.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Mindinguflac',
    contents_directory='.',
)
