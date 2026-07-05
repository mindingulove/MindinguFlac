# -*- mode: python ; coding: utf-8 -*-
# Launcher spec — built AFTER Mindinguflac-windows.spec and after
# dist/bundle.zip + _build_id.txt have been created by the build script.

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('dist/bundle.zip', '.'),
        ('_build_id.txt', '.'),
    ],
    hiddenimports=['tkinter', 'tkinter.ttk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'AppKit', 'Foundation', 'IOBluetooth', 'objc',
        'numpy', 'PIL', 'libtorrent', 'playwright',
    ],
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
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['build/icons/mindinguflac.ico'],
)
