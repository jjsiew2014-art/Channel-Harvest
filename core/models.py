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
    url: str = ""
    selected: bool = True
    channel_title: str = ""
    error_reason: str = ""


@dataclass
class DownloadSettings:
    """
    User-configurable download options selected in the GUI.

    Attributes:
        download_mode: Target mode (Video Only, Audio Only, Video + Audio).
        format: Selected video container format (MP4, MKV, WEBM, MOV).
        quality: Selected video resolution (Best Available, 1080p, 720p, etc.).
        bitrate: Selected video bitrate preference (Best Available, 5000 kbps, etc.).
        audio_format: Selected audio extraction container (MP3, M4A, WAV, AAC, FLAC, OPUS).
        audio_bitrate: Selected audio bitrate preference (Best Available, 320 kbps, 256 kbps, etc.).
        download_folder: Target destination folder path on Windows.
        create_channel_folder: If True, saves into a subfolder named after the channel.
        skip_existing: If True, uses the download archive to skip already finished videos.
        channel_title: Channel title used for subfolder naming.
    """
    download_mode: str = DownloadMode.VIDEO_AND_AUDIO
    format: str = "MP4"
    quality: str = "1080p"
    bitrate: str = "Best Available"
    audio_format: str = "MP3"
    audio_bitrate: str = "Best Available"
    download_folder: str = str(Path.home() / "Downloads" / "Channel Harvest")
    create_channel_folder: bool = False
    skip_existing: bool = True
    channel_title: str = ""
