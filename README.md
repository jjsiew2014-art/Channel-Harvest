# Channel Harvest

<p align="center">
  <img src="Channel Harvest__Logo.png" alt="Channel Harvest Logo" width="120"/>
</p>

<p align="center">
  <strong>A modern, high-performance YouTube channel & playlist downloader</strong><br/>
  Harvest your channel. Keep every video — with full media, subtitles, thumbnails, and metadata archival.
  Built with **Python**, **PySide6** (Qt for Python), **yt-dlp**, and **FFmpeg**.
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-1.1.0-6C63FF?style=flat-square"/>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue?style=flat-square"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square"/>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-F59E0B?style=flat-square"/>
</p>


---

## 🌟 Key Features

* **High-Speed Channel & Playlist Scanning**: Fast metadata extraction without UI freezes, featuring real-time title search and multi-select queue controls.
* **Flexible Download Modes**:
  * **Video + Audio**: High-definition video with crystal-clear merged audio (MOV, MP4, MKV, WEBM).
  * **Video Only**: Standalone high-resolution video streams.
  * **Audio Only**: Pristine standalone audio extracted into WAV, MP3, M4A, FLAC, AAC, or OPUS with customizable bitrates.
  * **Subtitle Only**: Standalone subtitle and caption extraction in seconds without downloading media streams.
* **Intelligent Subtitle & Caption Extraction**:
  * Automatically detects official manual subtitles and auto-generated captions across multiple languages (Chinese, English, Malay, Japanese, Korean, or All).
  * Automatically converts tracks to standard SubRip (`.srt`) format via bundled FFmpeg with clean player-friendly filename matching.
* **YouTube Thumbnail Archival**: Download video thumbnails as separate image files in JPG, PNG, WEBP, or native source format matching media filenames without container embedding.
* **Comprehensive Metadata, Description & Chapters Archival**:
  * **Save Description**: Exports raw video descriptions to clean `.description` text files preserving line breaks and links.
  * **Save Metadata**: Converts complete video metadata into a structured, human-readable `.metadata.txt` record (statistics, tags, uploader info).
  * **Save Chapters**: Extracts timestamped chapter navigation markers into clean `.chapters.txt` files.
* **Individual Video Folder Organization**: Optionally organizes each video and all its related assets (media, `.srt`, thumbnail, `.description`, `.metadata.txt`, `.chapters.txt`) into its own dedicated subfolder with automatic duplicate title collision protection.
* **Independent Skip Verification**: Intelligently skips already-downloaded files, allowing you to fetch missing subtitles, thumbnails, or metadata for existing local archives without re-downloading media streams.
* **Polished Modern Windows UI**: Desktop-first design featuring native Dark and Light theme switching, balanced settings layout, ergonomic vector action buttons, and zero-scroll startup display.
* **Self-Contained & In-App Updates**: Bundles official FFmpeg and yt-dlp binaries in `runtime/`, with a 1-click in-app yt-dlp updater that requires zero administrator rights.
* **Queue & Resiliency Management**: Full control to pause, resume, or cancel active downloads, backed by automatic 3x retries on transient network failures.

---

## 📥 Download & Installation

Visit the [GitHub Releases](https://github.com/jjsiew2014-art/ChannelHarvest/releases) page to download the latest release for **Windows 10 / 11 (64-bit)**:

### 1. Windows Installer (Recommended)
* **File**: `ChannelHarvest-Setup-v1.1.0.exe`
* **Features**:
  * Clean standard Windows installer (built with Inno Setup).
  * Installs into `Program Files\Channel Harvest` (or user profile for non-admin).
  * Creates Start Menu and optional Desktop shortcuts.
  * Registers in Windows *Settings > Installed apps* with a clean uninstaller.

### 2. Standalone Portable ZIP
* **File**: `ChannelHarvest-Portable-v1.1.0.zip`
* **Features**:
  * Zero installation required.
  * Extract anywhere and double-click `ChannelHarvest.exe`.
  * Fully self-contained with bundled `runtime/` binaries.

---

## 🛡️ Windows SmartScreen Notice

Because Channel Harvest is an open-source tool and not signed with an expensive commercial Code Signing Certificate:

1. Windows Defender SmartScreen may display: **"Windows protected your PC"**.
2. Click **"More info"**.
3. Click **"Run anyway"**.

You can verify the SHA-256 integrity hash of your downloaded file against `SHA256SUMS.txt` published on the GitHub Releases page:
```powershell
Get-FileHash ChannelHarvest-Setup-v1.1.0.exe -Algorithm SHA256
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
│   ├── info_manager.py            # Description, metadata & chapters extraction engine
│   ├── subtitle_manager.py        # Intelligent subtitle detection, conversion & normalization
│   ├── thumbnail_manager.py       # YouTube thumbnail downloader and converter
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
5. Package `release/ChannelHarvest-Portable-v1.1.0.zip`.
6. Compile `release/ChannelHarvest-Setup-v1.1.0.exe` using Inno Setup.
7. Generate cryptographic SHA-256 hashes in `release/SHA256SUMS.txt`.


---

## 📜 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 jjsiew2014-art.
