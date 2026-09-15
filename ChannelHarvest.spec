# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

datas = [
    ('Channel Harvest__Logo.png', '.'),
    ('ChannelHarvest.ico', '.'),
    ('gui/arrow_down.png', 'gui'),
    ('gui/arrow_down_dark.png', 'gui'),
    ('gui/checkmark.png', 'gui'),
]

hidden_imports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'yt_dlp',
    'yt_dlp.version',
    'yt_dlp.extractor',
    'yt_dlp.postprocessor',
    'core',
    'core.models',
    'core.paths',
    'core.settings',
    'core.version',
    'downloader',
    'downloader.download_manager',
    'downloader.ffmpeg_checker',
    'downloader.format_selector',
    'downloader.updater',
    'downloader.ytdlp_engine',
    'gui',
    'gui.main_window',
    'gui.settings_dialog',
    'gui.styles',
    'gui.summary_dialog',
    'gui.video_table',
]

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'distutils'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ChannelHarvest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ChannelHarvest.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ChannelHarvest',
)
