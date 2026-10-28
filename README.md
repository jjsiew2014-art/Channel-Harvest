# Channel Harvest

<p align="center">
  <img src="Channel Harvest__Logo.png" alt="Channel Harvest Logo" width="120"/>
</p>

<p align="center">
  <strong>YouTube, TikTok, Bilibili, Facebook, Instagram & X (Twitter) media and creator downloader</strong><br/>
  Harvest channels, creator profiles, spaces, pages, and accounts. Keep every video — with full media, subtitles, thumbnails, and metadata archival.<br/>
  Built with Python, PySide6 (Qt for Python), yt-dlp, Deno, and FFmpeg.
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-1.3.5-6C63FF?style=flat-square"/>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue?style=flat-square"/>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square"/>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-F59E0B?style=flat-square"/>
</p>

---

## 🌟 Key Features

### 🌐 Multi-Platform Support (YouTube, TikTok, Bilibili, Facebook, Instagram & X)
Easily switch between platforms directly from the top navigation bar with adaptive URL placeholder cues:
* **YouTube Video, Shorts, Playlist & Channel Archival**:
  * Full support for single videos, Shorts, playlists, and entire channel archives (`/channel/`, `/@handle`, `/c/`).
  * Bundled **EJS & Deno JavaScript challenge solver** directly in `runtime/` to resolve client-side `n-sig` player challenge decryption, eliminating download throttling and HTTP 403 Forbidden errors.
  * Multi-lingual subtitle detection & auto-conversion to standard SubRip (`.srt`) format, timestamped chapter navigation markers (`.chapters.txt`), and structured metadata.
* **X (Twitter) Video Post & Multi-Media Archival**:
  * Direct support for single video and GIF posts (`x.com/<user>/status/<id>`, `twitter.com/<user>/status/<id>`, `mobile.twitter.com`, `x.com/i/status/<id>`).
  * Intelligent multi-video tweet extraction: unpacks and enumerates individual video streams (`/video/1`, `/video/2`) with parent post caption and metadata preservation.
  * Adaptive title cleaning (`clean_x_title`): strips redundant `User on X: "..."` wrappers, removes trailing `t.co` media links, and enforces safe filename length limits while preserving Unicode characters, CJK scripts, and emojis.
  * Dedicated Netscape `cookies.txt` authentication support (`auth_token`, `ct0`, `twid`) with session validation and sensitive credential scrubbing for protected accounts and login-gated content.
* **Instagram Reels, Video Posts, Carousels & Profile Archival**:
  * Full support for single Reels (`/reel/`, `/reels/`), standard video posts (`/p/`), IGTV (`/tv/`), and public creator profiles (`/<username>/`).
* **Facebook Video, Watch & Reels Archival**:
  * Full support for Facebook Watch (`/watch/?v=...`), page/creator videos (`/{user}/videos/...`), and Facebook Reels (`/reel/`, `fb.watch`).
* **TikTok Video & Creator Archival**:
  * High-speed batch scanning and watermark-free video downloads for video links (`/video/...`, `vt.tiktok.com`, `vm.tiktok.com`) and creator profiles (`/@username`).
* **Bilibili Video, Multi-Part & Space Archival (哔哩哔哩)**:
  * Full support for videos (`BV...`/`av...`), multi-part (分P) episodes with clean part preservation, and creator Space archives (`space.bilibili.com/{mid}`) with anti-crawler Wbi request protection.

### 🎛️ Flexible Download & Archival Modes
* **Video + Audio**: High-definition video with merged audio streams (MP4, MOV, MKV).
* **Audio Only**: Pristine standalone audio extraction (WAV, MP3, M4A, FLAC, AAC, OPUS) with customizable bitrates.
* **Assets Only**: Rapidly extracts subtitles (`.srt`), covers/thumbnails (`.jpg`, `.png`), descriptions (`.description`), chapters, and metadata records in seconds without re-downloading media streams.
* **Platform-Dedicated Structured Metadata**: Modular exporter (`metadata/`) generating platform-tailored UTF-8 `.metadata.txt` records capturing uploader info, metrics, timestamps, and canonical source URLs.

### 🛡️ Smart Availability Detection & Safe File Organization
* **Automatic Availability Detection & Skip**: Defensively detects private, deleted, copyright-restricted, or region-blocked videos during scanning; disables inaccessible checkboxes with informative tooltips and skips them cleanly in the queue.
* **Windows Path Budgeting & Sanitization**: Centralized engine (`core/paths.py`) strips Windows-illegal characters and reserved device names (`CON`, `PRN`, `AUX`), with dynamic `MAX_PATH` budgeting for deep directory paths.
* **Customizable Organization**: Option to append video IDs (`[<id>]`) and organize each video and its companion assets into dedicated subfolders.

### 🔒 Platform-Scoped Authentication
* **Isolated Credentials**: Dedicated Netscape `cookies.txt` support per platform, ensuring zero cross-platform credential leakage.
* **Session Verification**: Built-in validation for YouTube, Instagram (`sessionid`), Bilibili (`SESSDATA`), and Facebook cookies to access private, members-only, or login-required content safely.

### 🖥️ Modern Desktop Experience & Diagnostics
* **Responsive PySide6 UI**: Native Dark and Light themes, Windows taskbar dynamic progress bar (`ITaskbarList3`), and non-blocking background scanning/download queues.
* **Trilingual Localization**: Instant dynamic switching between English, 简体中文, and 繁體中文 directly from Settings without application restart.
* **Component Dashboard & Diagnostics**: Live health inspection of core binaries, one-click system diagnostics, and background in-app updater for `yt-dlp`.

---

## 📥 Download & Installation

Visit the [GitHub Releases](https://github.com/jjsiew2014-art/ChannelHarvest/releases) page to download the latest release for **Windows 10 / 11 (64-bit)**:

| Package | File | Description |
| :--- | :--- | :--- |
| **Windows Installer** (Recommended) | `ChannelHarvest-Setup-v1.3.5.exe` | Standard setup wizard (Inno Setup) with desktop shortcuts and uninstaller |
| **Standalone Portable ZIP** | `ChannelHarvest-Portable-v1.3.5.zip` | Zero installation — extract anywhere and run `ChannelHarvest.exe` |

Both packages are fully self-contained with bundled `runtime/` binaries (`ffmpeg.exe`, `ffprobe.exe`, `deno.exe`, `yt-dlp.exe`).

---

## 🛡️ Windows SmartScreen Notice

Because Channel Harvest is an open-source tool and not signed with an expensive commercial Code Signing Certificate:

1. Windows Defender SmartScreen may display: **"Windows protected your PC"**.
2. Click **"More info"**.
3. Click **"Run anyway"**.

You can verify the SHA-256 integrity hash of your downloaded file against `SHA256SUMS.txt` published on the GitHub Releases page:

```powershell
Get-FileHash ChannelHarvest-Setup-v1.3.5.exe -Algorithm SHA256
Get-FileHash ChannelHarvest-Portable-v1.3.5.zip -Algorithm SHA256
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
│   ├── availability.py            # Platform-aware video accessibility & skip detection
│   ├── diagnostics.py             # System & runtime diagnostic report generator
│   ├── error_classifier.py        # Intelligent error categorization & action advice
│   ├── i18n.py                    # Tri-lingual internationalization (English / 简体中文 / 繁體中文)
│   ├── models.py                  # VideoItem, DownloadSettings, VideoStatus, ScanResult
│   ├── paths.py                   # AppData & runtime path resolution and Windows sanitization
│   ├── settings.py                # Persistent JSON SettingsManager
│   ├── version.py                 # Central version & branding constants
│   └── platform/                  # Extensible Multi-Platform Architecture
│       ├── __init__.py
│       ├── auth.py                # Platform-specific auth configuration & models
│       ├── base.py                # BasePlatformAdapter contract
│       ├── capabilities.py        # Platform capability definitions & flags
│       ├── detector.py            # Automatic URL-to-platform detection
│       ├── youtube.py             # YouTube platform adapter
│       ├── tiktok.py              # TikTok platform adapter
│       ├── bilibili.py            # Bilibili platform adapter
│       ├── facebook.py            # Facebook platform adapter
│       ├── instagram.py           # Instagram platform adapter
│       ├── x.py                   # X (Twitter) platform adapter
│       └── douyin.py              # Douyin platform adapter (frozen)
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
│   ├── thumbnail_manager.py       # Cover & thumbnail downloader
│   ├── updater.py                 # Standalone yt-dlp updater (binary & wheel)
│   └── ytdlp_engine.py            # Direct yt-dlp Python API integration
│
├── metadata/                      # Platform-Dedicated Structured Metadata Exporters
│   ├── __init__.py
│   ├── base_formatter.py          # Abstract metadata TXT formatter
│   ├── metadata_exporter.py       # Exporter dispatching to platform formatters
│   ├── youtube_formatter.py       # YouTube .metadata.txt record formatter
│   ├── tiktok_formatter.py        # TikTok .metadata.txt record formatter
│   ├── bilibili_formatter.py      # Bilibili .metadata.txt record formatter
│   ├── facebook_formatter.py      # Facebook .metadata.txt record formatter
│   ├── instagram_formatter.py     # Instagram .metadata.txt record formatter
│   ├── x_formatter.py             # X (Twitter) .metadata.txt record formatter
│   └── generic_formatter.py       # Universal fallback metadata formatter
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
5. Package `release/ChannelHarvest-Portable-v1.3.5.zip`.
6. Compile `release/ChannelHarvest-Setup-v1.3.5.exe` using Inno Setup.
7. Generate cryptographic SHA-256 hashes in `release/SHA256SUMS.txt`.

---

## 📜 License

Distributed under the [MIT License](LICENSE). Copyright (c) 2026 jjsiew2014-art.
