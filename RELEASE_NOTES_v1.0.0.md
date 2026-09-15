# Channel Harvest v1.0.0 - Official Release

> **Harvest your channel. Keep every video.**

We are excited to announce the official release of **Channel Harvest (v1.0.0)** for Windows 10 and Windows 11 (64-bit).

Channel Harvest is a modern, high-performance desktop application designed to archive entire YouTube channels and playlists with ease, reliability, and precision.

---

## 🚀 Key Features

* **High-Speed Channel & Playlist Scanning**: Fast metadata extraction without UI freezes or unneeded downloads.
* **Flexible Download Modes**:
  * **Video Only**: High-definition video with crystal-clear merged audio (1 file per item).
  * **Audio Only**: Standalone music or podcast audio extracted into MP3, M4A, FLAC, WAV, AAC, or OPUS (with configurable bitrate).
  * **Video + Audio**: Concurrently saves both the video file and standalone audio track.
* **100% Self-Contained**: Includes verified, bundled `ffmpeg.exe`, `ffprobe.exe`, and `yt-dlp.exe` in the `runtime/` folder. No prior installation of Python, FFmpeg, or command-line tools is needed!
* **Non-Admin In-App yt-dlp Updates**: Check and update `yt-dlp` directly from official GitHub releases into user AppData without requiring administrator privileges or `pip`.
* **Smart Duplicate Prevention**: Persistent download archive (`%APPDATA%/ChannelHarvest/download_archive.txt`) automatically skips already saved videos.
* **Queue & Retry Management**: Pause, resume, and cancel queues with automatic 3x retries on transient network failures.
* **Modern Windows UI**: Clean Segoe UI typography, native dark and light theme switching, crisp SVG icons, and live status badges.
* **Clean User Data Separation**: Settings, archives, and logs are kept in `%APPDATA%\ChannelHarvest\`, leaving application directories completely pristine.

---

## 📦 Downloads & Checksums

| Asset | Size | Description |
|---|---|---|
| **`ChannelHarvest-Setup-v1.0.0.exe`** | ~151 MB (158,840,864 bytes) | **Recommended**. Standard Windows installer targeting `Program Files` or User profile, Start Menu & Desktop shortcuts, and Windows uninstaller. |
| **`ChannelHarvest-Portable-v1.0.0.zip`** | ~224 MB (234,855,593 bytes) | Standalone portable archive. Unpack and run `ChannelHarvest.exe` anywhere (no installation needed). |
| **`SHA256SUMS.txt`** | 201 B | Cryptographic checksums for release verification. |

### SHA-256 Checksums
```text
9d0c56e8b931c43218f46f2e4bbd072e5a7afbc31c23efdf5f22919acd23983a  ChannelHarvest-Portable-v1.0.0.zip
af960e6d861bd6bbd5283b9ad8d915bf905839fc61d2be65ed33e87348763539  ChannelHarvest-Setup-v1.0.0.exe
```

---


## 🛡️ Windows SmartScreen Notice

Because this is an independent open-source release without a paid commercial EV Code Signing Certificate, Windows Defender SmartScreen may display:

> **"Windows protected your PC"**

To install/run:
1. Click **"More info"**.
2. Click **"Run anyway"**.

You can verify the SHA-256 checksum of your download in PowerShell:
```powershell
Get-FileHash ChannelHarvest-Setup-v1.0.0.exe -Algorithm SHA256
```

---

## 📋 System Requirements

* **Operating System**: Windows 10 (64-bit) or Windows 11 (64-bit)
* **Processor**: 64-bit Intel / AMD processor
* **Memory**: 4 GB RAM minimum
* **Disk Space**: ~600 MB free disk space for application and bundled runtime
