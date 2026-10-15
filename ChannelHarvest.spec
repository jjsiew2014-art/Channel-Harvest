# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ('Channel Harvest__Logo.png', '.'),
    ('ChannelHarvest.ico', '.'),
    ('gui/arrow_down.png', 'gui'),
    ('gui/arrow_down_dark.png', 'gui'),
    ('gui/checkmark.png', 'gui'),
]
datas += collect_data_files('yt_dlp')
datas += collect_data_files('yt_dlp_ejs')
datas += collect_data_files('curl_cffi')

hidden_imports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'curl_cffi',
    '_cffi_backend',
    'yt_dlp',
    'yt_dlp.version',
    'yt_dlp.extractor',
    'yt_dlp.postprocessor',
    'yt_dlp_ejs',
    'yt_dlp_ejs._version',
    'yt_dlp_ejs.yt',
    'yt_dlp_ejs.yt.solver',
    'core',
    'core.diagnostics',
    'core.error_classifier',
    'core.i18n',
    'core.models',
    'core.paths',
    'core.settings',
    'core.version',
    'core.platform',
    'core.platform.base',
    'core.platform.capabilities',
    'core.platform.detector',
    'core.platform.registry',
    'core.platform.youtube',
    'core.platform.tiktok',
    'core.platform.douyin',
    'downloader',
    'downloader.auth_checker',
    'downloader.deno_checker',
    'downloader.download_manager',
    'downloader.ffmpeg_checker',
    'downloader.format_selector',
    'downloader.runtime_manager',
    'downloader.subtitle_manager',
    'downloader.thumbnail_manager',
    'downloader.info_manager',
    'downloader.updater',
    'downloader.ytdlp_engine',
    'gui',
    'gui.auth_result_dialog',
    'gui.error_details_dialog',
    'gui.main_window',
    'gui.settings_dialog',
    'gui.styles',
    'gui.summary_dialog',
    'gui.video_table',
    'gui.taskbar_progress',
]
hidden_imports += collect_submodules('curl_cffi')

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
