"""
models.py
Data structures representing videos, download settings, and queue states.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# =============================================================================
# Download Queue Status Constants
# =============================================================================
class VideoStatus:
    """Standardized status values for each video in the queue."""
    READY = "Ready"
    WAITING = "Waiting"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    SKIPPED = "Skipped"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class DownloadMode:
    """Download operational modes supported by Channel Harvest."""
    VIDEO_ONLY = "Video Only"
    AUDIO_ONLY = "Audio Only"
    VIDEO_AND_AUDIO = "Video + Audio"
    SUBTITLE_ONLY = "Subtitle Only"


class SubtitleSource:
    """Subtitle acquisition source modes."""
    BEST_AVAILABLE = "Best Available"
    OFFICIAL = "Official / Uploaded"
    AUTO_GENERATED = "Auto-generated"
    AUTO = AUTO_GENERATED


class SubtitleLanguage:
    """Display labels for supported subtitle languages."""
    CHINESE = "Chinese (中文)"
    ENGLISH = "English"
    MALAY = "Malay (Bahasa Melayu)"
    JAPANESE = "Japanese (日本語)"
    KOREAN = "Korean (한국어)"
    ALL = "All Available Languages"


class ThumbnailFormat:
    """Supported thumbnail image formats."""
    JPG = "JPG"
    PNG = "PNG"
    WEBP = "WEBP"
    ORIGINAL = "Original"


@dataclass
class VideoItem:
    """
    Represents an individual YouTube video scanned from a channel or playlist.

    Attributes:
        index: 1-based order in the scanned channel list.
        video_id: Unique YouTube video ID (e.g., 'dQw4w9WgXcQ').
        title: Title of the video.
        duration: Human-readable duration string (e.g. '12:34' or '01:15:20').
        duration_seconds: Raw duration in integer seconds (None if live/unknown).
        status: Current state from VideoStatus.
        subtitle_status: Subtitle availability or status (e.g. '✓ Chinese', '—').
        url: Full URL to watch the video on YouTube.
        selected: Whether this video is currently checked for download.
        channel_title: Name of the channel this video belongs to.
        error_reason: Explanation if downloading failed.
    """
    index: int
    video_id: str
    title: str
    duration: str
    duration_seconds: Optional[int] = None
    status: str = VideoStatus.READY
    subtitle_status: str = "Checking..."
    url: str = ""
    selected: bool = True
    channel_title: str = ""
    error_reason: str = ""
    error_details: Optional[Any] = None


@dataclass
class DownloadSettings:
    """
    User-configurable download options selected in the GUI.

    Attributes:
        download_mode: Target mode (Video Only, Audio Only, Video + Audio, Subtitle Only).
        format: Selected video container format (MP4, MKV, WEBM, MOV).
        quality: Selected video resolution (Best Available, 1080p, 720p, etc.).
        bitrate: Selected video bitrate preference (Best Available, 5000 kbps, etc.).
        audio_format: Selected audio extraction container (MP3, M4A, WAV, AAC, FLAC, OPUS).
        audio_bitrate: Selected audio bitrate preference (Best Available, 320 kbps, 256 kbps, etc.).
        download_subtitles: Whether subtitle downloading is enabled.
        subtitle_source: Subtitle source mode (Best Available, Official / Uploaded, Auto-generated).
        subtitle_language: Target subtitle language (Chinese (中文), English, etc.).
        subtitle_format: Output subtitle format (SRT).
        download_thumbnail: Whether thumbnail downloading is enabled (default False).
        thumbnail_format: Output thumbnail image format (JPG, PNG, WEBP, Original).
        save_description: Whether to save original video description as a separate file.
        save_metadata: Whether to save formatted video metadata (.metadata.txt).
        save_chapters: Whether to save timestamped chapters (.chapters.txt).
        download_folder: Target destination folder path on Windows.
        create_channel_folder: If True, saves into a subfolder named after the channel.
        create_individual_video_folders: If True, saves each video's files into its own folder.
        skip_existing: If True, uses the download archive to skip already finished videos.
        channel_title: Channel title used for subfolder naming.
        browser_cookies: Browser name for cookie extraction ('none', 'chrome', 'edge', 'firefox', etc.).
        custom_cookie_file: Optional file path to a cookies.txt file when browser_cookies is 'custom_file'.
    """
    download_mode: str = DownloadMode.VIDEO_ONLY
    format: str = "MOV"
    quality: str = "1080p"
    bitrate: str = "Best Available"
    audio_format: str = "WAV"
    audio_bitrate: str = "Best Available"
    download_subtitles: bool = False
    subtitle_source: str = SubtitleSource.BEST_AVAILABLE
    subtitle_language: str = SubtitleLanguage.CHINESE
    subtitle_format: str = "SRT"
    download_thumbnail: bool = False
    thumbnail_format: str = ThumbnailFormat.JPG
    save_description: bool = False
    save_metadata: bool = False
    save_chapters: bool = False
    download_folder: str = str(Path.home() / "Downloads" / "Channel Harvest")
    create_channel_folder: bool = True
    create_individual_video_folders: bool = False
    skip_existing: bool = False
    channel_title: str = ""
    auth_method: str = "none"
    browser_cookies: str = "none"
    browser_profile: str = "Default"
    custom_cookie_file: str = ""

