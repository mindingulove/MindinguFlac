# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from pathlib import Path

datas = [('static', 'static')]
binaries = []
hiddenimports = ['bluetooth_scan', 'IOBluetooth']
tmp_ret = collect_all('SpotiFLAC')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

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
    excludes=['PIL', 'MediaLibrary', 'Photos', 'Contacts', 'EventKit', 'CoreLocation'],
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
    target_arch='universal2',
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
        'NSBluetoothAlwaysUsageDescription': 'Mindinguflac needs Bluetooth access to discover and connect audio devices.',
        'NSBluetoothPeripheralUsageDescription': 'Mindinguflac needs Bluetooth access to discover and connect audio devices.',
    },
)
