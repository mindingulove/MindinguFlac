# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [('static', 'static')]
binaries = []
hiddenimports = ['bluetooth_scan']

tmp_ret = collect_all('SpotiFLAC')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

try:
    tmp_ret = collect_all('bleak')
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]
    hiddenimports += collect_submodules('bleak')
except Exception:
    pass

for package_name in ('PIL', 'git'):
    try:
        tmp_ret = collect_all(package_name)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
        hiddenimports += collect_submodules(package_name)
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
    [],
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
