# Channel Harvest

<p align="center">
  <img src="Channel Harvest__Logo.png" alt="Channel Harvest Logo" width="120"/>
</p>

<p align="center">
  <strong>YouTube, TikTok & Bilibili media and creator downloader</strong><br/>
  Harvest channels and creator profiles. Keep every video — with full media, subtitles, thumbnails, and metadata archival.<br/>
  Built with Python, PySide6 (Qt for Python), yt-dlp, Deno, and FFmpeg.
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-1.4.0-6C63FF?style=flat-square"/>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue?style=flat-square"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square"/>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-F59E0B?style=flat-square"/>
</p>

---

## 🌟 Key Features

### 🌐 Multi-Platform Support (YouTube, TikTok & Bilibili)
* **Dedicated Platform Selector**: Easily switch between supported platforms (YouTube, TikTok, and Bilibili) right from the top navigation bar with adaptive URL placeholder cues.
* **TikTok Video & Creator Archival**:
  * Full support for TikTok video URLs (`tiktok.com/@user/video/...`, `vt.tiktok.com/...`, `vm.tiktok.com/...`) and creator profile URLs (`tiktok.com/@username`).
  * High-speed profile batch scanning and metadata retrieval without UI freezes.
  * High-definition, watermark-free video downloads (MP4, MOV).
  * Standalone audio extraction (WAV, MP3, M4A, FLAC, AAC, OPUS).
  * Complete asset archival: native covers/thumbnails (`.jpg`, `.png`, `.webp`), raw descriptions (`.description`), and structured metadata records (`.metadata.txt`).
* **Bilibili Video, Multi-Part & Space Archival (哔哩哔哩)**:
  * Full support for Bilibili video URLs (`bilibili.com/video/BV...` / `av...`), multi-part (分P) episodes with clean part preservation, creator Space URLs (`space.bilibili.com/{mid}`), user video submissions, and media lists/series.
  * Real-time metadata scanning displaying the actual video title returned by Bilibili instead of generic fallback identifiers.
  * Anti-crawler & Wbi request signing protection with platform-scoped custom Cookie file (`cookies.txt`) authentication to prevent server rejection (Error 352).
  * High-definition video downloads (MP4, MKV) up to 1080P/4K 60fps (when authenticated with VIP/member cookies).
  * Standalone audio extraction (WAV, MP3, M4A, FLAC, AAC, OPUS).
  * Complete asset archival: native high-resolution covers (`.jpg`, `.png`, `.webp`), raw descriptions (`.description`), and dedicated Bilibili structured metadata records (`.metadata.txt`).
* **Extensible Multi-Platform Architecture (`core/platform/`)**: Modular platform adapters with isolated capability flags, URL auto-detection, and strictly scoped authentication configurations.

### ⚡ EJS & Deno JavaScript Challenge Solver
* **Modern Challenge Solver**: Bundles a dedicated modern JavaScript runtime engine (`deno.exe`) directly in `runtime/` to solve YouTube's latest client-side signature decryption (`n-sig` challenge) and Embedded JavaScript (`EJS`) player routines without requiring external Node.js or Deno installations.
* **Zero Throttling & 403 Recovery**: Completely resolves YouTube download throttling, signature calculation failures, and HTTP 403 Forbidden errors.

### 🎛️ Flexible Download Modes
* **Video + Audio**: High-definition video with crystal-clear merged audio (MOV, MP4, MKV, WEBM).
* **Video Only**: Standalone high-resolution video streams.
* **Audio Only**: Pristine standalone audio extracted into WAV, MP3, M4A, FLAC, AAC, or OPUS with customizable bitrates.
* **Assets Only**: Standalone subtitle, thumbnail/cover, and metadata asset extraction in seconds without downloading media streams.

### 📝 Comprehensive Subtitles, Thumbnails & Metadata Archival
* **Intelligent Subtitle & Caption Extraction**:
  * Automatically detects official manual subtitles and auto-generated captions across multiple languages (Chinese, English, Malay, Japanese, Korean, or All).
  * Automatically converts tracks to standard SubRip (`.srt`) format via bundled FFmpeg with clean player-friendly filename matching.
* **Thumbnail & Cover Archival**: Download video thumbnails and TikTok covers as separate image files in JPG, PNG, WEBP, or native source format matching media filenames without container embedding.
* **Raw Descriptions**: Exports raw video descriptions to clean `.description` text files preserving line breaks and links.
* **Structured Metadata**: Converts complete video metadata into a structured, human-readable `.metadata.txt` record (statistics, tags, uploader info).
* **Chapter Extraction**: Extracts timestamped chapter navigation markers into clean `.chapters.txt` files (YouTube).

### 🏷️ Customizable File Naming & Organization
* **Clean Filenames by Default**: Media, subtitles, thumbnails, and metadata default to clean video titles rather than forcing video IDs.
* **Optional Video ID in Filename**: Enable `Include Video ID in filename` under **Download Option → File Organization** to append `[<id>]`.
* **Automatic Collision Protection**: Detects duplicate titles and protects against accidental overwrites by safely appending `[<id>]` only when necessary.
* **Individual Video Folder Organization**: Optionally organizes each video and all its related assets into its own dedicated subfolder.

### 🔒 Platform-Scoped Authentication & Cookie Management
* **Platform Isolation**: Authentication credentials and profiles are strictly scoped per platform to prevent credential leakage across platforms.
* **Custom Cookie File Support**: Supports Netscape format `cookies.txt` files with automated syntax validation, expiration warnings, and security sanitization.
* **Direct Browser Cookie Extraction**: Direct extraction support with Windows DPAPI safety diagnostics.
* **Live Authentication Verification**: Test login and premium status before starting batch downloads.
* **Unrestricted Content Access**: Unlocks age-restricted videos, private playlists, members-only uploads, and unlisted high-definition streams.

### ⚙️ Centralized Runtime Manager & Diagnostics
* **Component Health Dashboard**: Real-time visual status dashboard integrated into Settings to inspect operational readiness, paths, and versions of all core components.
* **In-App Updater**: Asynchronous background updater for `yt-dlp` requiring zero administrator privileges, backed by multi-level version caching for instantaneous dialog response.
* **One-Click System Diagnostics**: Collects hardware architecture, Windows OS build, Python runtime, component versions, network connectivity, and cookie configuration for rapid debugging.
* **Dedicated Sanitized Error Logging**: Unhandled exceptions and background failures are recorded in `channel_harvest_error.log` with automatic privacy scrubbing, paired with an intelligent error classifier.

### 🖥️ Polished Windows Desktop UI & Resiliency
* **Windows Taskbar Progress**: Real-time download progress tracking rendered directly on the Windows taskbar application icon with dynamic color status (green for active, yellow for paused, red for errors).
* **Bilingual Language Support**: Switch dynamically between English, Traditional Chinese and Simplified Chinese directly from Settings, updating all labels, dialogs, and controls in real time without restart.
* **Polished Desktop Experience**: Desktop-first design featuring native Dark and Light theme switching, balanced settings layout, ergonomic vector action buttons, and fast UI responsiveness.
* **Queue & Resiliency Management**: Full control to pause, resume, or cancel active downloads, backed by automatic 3x retries on transient network failures.

---

## 📥 Download & Installation

Visit the [GitHub Releases](https://github.com/jjsiew2014-art/ChannelHarvest/releases) page to download the latest release for **Windows 10 / 11 (64-bit)**:

| Package | File | Description |
| :--- | :--- | :--- |
| **Windows Installer** (Recommended) | `ChannelHarvest-Setup-v1.3.0.exe` | Standard setup wizard (Inno Setup) with desktop shortcuts and uninstaller |
| **Standalone Portable ZIP** | `ChannelHarvest-Portable-v1.3.0.zip` | Zero installation — extract anywhere and run `ChannelHarvest.exe` |

Both packages are fully self-contained with bundled `runtime/` binaries (`ffmpeg.exe`, `ffprobe.exe`, `deno.exe`, `yt-dlp.exe`).

---

## 🛡️ Windows SmartScreen Notice

Because Channel Harvest is an open-source tool and not signed with an expensive commercial Code Signing Certificate:

1. Windows Defender SmartScreen may display: **"Windows protected your PC"**.
2. Click **"More info"**.
3. Click **"Run anyway"**.

You can verify the SHA-256 integrity hash of your downloaded file against `SHA256SUMS.txt` published on the GitHub Releases page:

```powershell
Get-FileHash ChannelHarvest-Setup-v1.4.0.exe -Algorithm SHA256
Get-FileHash ChannelHarvest-Portable-v1.4.0.zip -Algorithm SHA256
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
├── core/                          # Data Models, Paths, Diagnostics & Settings
│   ├── __init__.py
│   ├── diagnostics.py             # System & runtime diagnostic report generator
│   ├── error_classifier.py        # Intelligent error categorization & action advice
│   ├── i18n.py                    # Bilingual internationalization (English / 简体中文)
│   ├── models.py                  # VideoItem, DownloadSettings, VideoStatus
│   ├── paths.py                   # AppData & runtime path resolution
│   ├── settings.py                # Persistent JSON SettingsManager
│   ├── version.py                 # Central version & branding constants
│   └── platform/                  # Extensible Multi-Platform Architecture
│       ├── __init__.py
│       ├── auth.py                # Platform-specific auth configuration & models
│       ├── base.py                # BasePlatformAdapter contract
│       ├── capabilities.py        # Platform capability definitions & flags
│       ├── detector.py            # Automatic URL-to-platform detection
│       ├── douyin.py              # Douyin platform adapter (experimental/frozen)
│       ├── tiktok.py              # TikTok platform adapter
│       └── youtube.py             # YouTube platform adapter
│
├── downloader/                    # Download & Extraction Engine
│   ├── __init__.py
│   ├── auth_checker.py            # Browser cookie extractor & Netscape format validator
│   ├── deno_checker.py            # Deno & JavaScript engine environment detection
│   ├── download_manager.py        # Background QThread queue dispatcher
│   ├── ffmpeg_checker.py          # Runtime & system FFmpeg/FFprobe detection
│   ├── format_selector.py         # Dynamic format spec builder
│   ├── info_manager.py            # Description, metadata & chapters extraction engine
│   ├── runtime_manager.py         # Live component tracking, version cache & updates
│   ├── subtitle_manager.py        # Intelligent subtitle detection, conversion & normalization
│   ├── thumbnail_manager.py       # YouTube thumbnail & TikTok cover downloader
│   ├── updater.py                 # Standalone yt-dlp updater (binary & wheel)
│   └── ytdlp_engine.py            # Direct yt-dlp Python API integration
│
├── gui/                           # Desktop User Interface (PySide6)
│   ├── __init__.py
│   ├── auth_result_dialog.py      # Authentication test results dialog
│   ├── error_details_dialog.py    # Formatted error details & actionable solutions dialog
│   ├── main_window.py             # Main application window with platform switcher
│   ├── settings_dialog.py         # Settings, Runtime Manager & Diagnostics dialog
│   ├── styles.py                  # Dark/Light Windows theme engine
│   ├── summary_dialog.py          # Download completion summary dialog
│   ├── taskbar_progress.py        # Windows taskbar ITaskbarList3 dynamic progress bar
│   └── video_table.py             # Video queue table with live progress badges
│
├── installer/                     # Inno Setup Windows Installer
│   └── ChannelHarvest.iss         # Inno Setup 6 compiler configuration
│
└── runtime/                       # Bundled External Executables
    ├── deno.exe                   # Deno JavaScript runtime for YouTube EJS challenges
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
1. Verify runtime binaries (`deno.exe`, `ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`).
2. Generate multi-resolution icons and PE metadata.
3. Clean and freeze the application using PyInstaller.
4. Deploy the `runtime/` folder into `dist/ChannelHarvest/`.
5. Package `release/ChannelHarvest-Portable-v1.3.0.zip`.
6. Compile `release/ChannelHarvest-Setup-v1.3.0.exe` using Inno Setup.
7. Generate cryptographic SHA-256 hashes in `release/SHA256SUMS.txt`.

---

## 📜 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 jjsiew2014-art.
