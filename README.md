# Channel Harvest

> **Harvest your channel. Keep every video.**

A modern, clean, commercial-grade Windows desktop application for archiving and downloading entire YouTube channels and playlists. Built with **Python**, **PySide6** (Qt for Python), **yt-dlp**, and **FFmpeg**.

Distributed as a **100% self-contained Windows application**—no Python, command-line tools, or extra software required.

---

## 🌟 Key Features

* **High-Speed Channel & Playlist Scanning**: Fast metadata extraction without UI freezes or unneeded downloads.
* **Flexible Download Modes**:
  * **Video Only**: High-definition video with crystal-clear merged audio (1 file per item).
  * **Audio Only**: Standalone music or podcast audio extracted into MP3, M4A, FLAC, WAV, AAC, or OPUS (with configurable bitrate).
  * **Video + Audio**: Concurrently saves both the video file and standalone audio track.
* **Self-Contained Bundled Binaries**: Bundles official, verified `ffmpeg.exe`, `ffprobe.exe`, and `yt-dlp.exe` in the `runtime/` folder.
* **Non-Admin In-App yt-dlp Updates**: Directly checks and downloads official yt-dlp updates from GitHub releases into user AppData without needing `pip` or administrator rights.
* **Duplicate Prevention**: Persistent download archive (`%APPDATA%/ChannelHarvest/download_archive.txt`) automatically skips already saved videos.
* **Queue & Retry Management**: Pause, resume, and cancel queues with automatic 3x retries on transient network failures.
* **Modern Windows UI**: Clean Segoe UI typography, native dark and light theme switching, crisp SVG icons, and live status badges.
* **Clean User Data Separation**: Settings, archives, and logs are kept in `%APPDATA%\ChannelHarvest\`, leaving application directories completely pristine.

---

## 📥 Download & Installation

Visit the [GitHub Releases](https://github.com/jjsiew2014-art/ChannelHarvest/releases) page to download the latest release for **Windows 10 / 11 (64-bit)**:

### 1. Windows Installer (Recommended)
* **File**: `ChannelHarvest-Setup-v1.0.0.exe`
* **Features**:
  * Clean standard Windows installer (built with Inno Setup).
  * Installs into `Program Files\Channel Harvest` (or user profile for non-admin).
  * Creates Start Menu and optional Desktop shortcuts.
  * Registers in Windows *Settings > Installed apps* with a clean uninstaller.

### 2. Standalone Portable ZIP
* **File**: `ChannelHarvest-Portable-v1.0.0.zip`
* **Features**:
  * Zero installation required.
  * Extract anywhere (e.g. `C:\Tools\ChannelHarvest` or a USB drive) and double-click `ChannelHarvest.exe`.
  * Fully self-contained with bundled `runtime/` binaries.

---

## 🛡️ Windows SmartScreen Notice

Because Channel Harvest is an open-source tool and not signed with an expensive commercial Code Signing Certificate:

1. Windows Defender SmartScreen may display: **"Windows protected your PC"**.
2. Click **"More info"**.
3. Click **"Run anyway"**.

You can verify the SHA-256 integrity hash of your downloaded file against `SHA256SUMS.txt` published on the GitHub Releases page:
```powershell
Get-FileHash ChannelHarvest-Setup-v1.0.0.exe -Algorithm SHA256
```


---

## 📁 Project Architecture

```
Channel Harvest/
│
├── app.py                         # Application entry point
├── build.py                       # Automated 1-click build & release pipeline
├── build_release.bat              # Windows batch file to run build.py
├── ChannelHarvest.spec            # PyInstaller onedir freeze specification
├── version_info.txt               # Windows PE executable version resource metadata
├── ChannelHarvest.ico             # Multi-resolution application icon (16x16 to 256x256)
├── Channel Harvest__Logo.png      # High-resolution branding logo
├── requirements.txt               # Runtime Python dependencies
├── requirements-build.txt         # Build-time dependencies (PyInstaller, Pillow)
├── LICENSE                        # MIT License
├── README.md                      # Documentation
│
├── core/                          # Data Models, Paths & Settings
│   ├── __init__.py
│   ├── models.py                  # VideoItem, DownloadSettings, VideoStatus
│   ├── paths.py                   # AppData & runtime path resolution
│   ├── settings.py                # Persistent JSON SettingsManager
│   └── version.py                 # Central version & branding constants
│
├── downloader/                    # Download & Extraction Engine
│   ├── __init__.py
│   ├── download_manager.py        # Background QThread queue dispatcher
│   ├── ffmpeg_checker.py          # Runtime & system FFmpeg/FFprobe detection
│   ├── format_selector.py         # Dynamic format spec builder
│   ├── updater.py                 # Standalone yt-dlp updater (binary & wheel)
│   └── ytdlp_engine.py            # Direct yt-dlp Python API integration
│
├── gui/                           # Desktop User Interface (PySide6)
│   ├── __init__.py
│   ├── main_window.py             # Main application window
│   ├── settings_dialog.py         # Settings & About dialog
│   ├── summary_dialog.py          # Download completion summary dialog
│   ├── video_table.py             # Video queue table with live progress badges
│   └── styles.py                  # Dark/Light Windows theme engine
│
├── installer/                     # Inno Setup Windows Installer
│   └── ChannelHarvest.iss         # Inno Setup 6 compiler configuration
│
└── runtime/                       # Bundled External Executables
    ├── ffmpeg.exe                 # FFmpeg media converter
    ├── ffprobe.exe                # FFprobe media stream analyzer
    └── yt-dlp.exe                 # yt-dlp standalone engine
```

---

## 🔨 Building From Source

### Prerequisites
* Windows 10 or 11 (64-bit)
* Python 3.10+ (tested with Python 3.14 64-bit)
* [Inno Setup 6](https://jrsoftware.org/isdl.php) (for compiling installer EXE)

### 1. Clone & Setup Environment
```powershell
git clone https://github.com/jjsiew2014-art/ChannelHarvest.git
cd "ChannelHarvest"
pip install -r requirements-build.txt
```

### 2. Run from Source (Development)
```powershell
python app.py
```

### 3. Build Release Packages (Automated)
Run the automated build script:
```powershell
python build.py
```
*(Or double-click `build_release.bat`)*

The script will automatically:
1. Verify runtime binaries (`ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`).
2. Generate multi-resolution icons and PE metadata.
3. Clean and freeze the application using PyInstaller.
4. Deploy the `runtime/` folder into `dist/ChannelHarvest/`.
5. Package `release/ChannelHarvest-Portable-v1.0.0.zip`.
6. Compile `release/ChannelHarvest-Setup-v1.0.0.exe` using Inno Setup.
7. Generate cryptographic SHA-256 hashes in `release/SHA256SUMS.txt`.


---

## 📜 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 jjsiew2014-art.
