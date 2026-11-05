"""
models.py
Data structures representing videos, download settings, and queue states.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
from core.availability import AvailabilityStatus, AvailabilityReasonCode, VideoAvailability


# =============================================================================
# Download Queue Status Constants
# =============================================================================
class MediaType:
    """Standardized media classification types for Channel Harvest."""
    PHOTO = "Photo"
    VIDEO = "Video"
    REEL = "Reel"
    UNKNOWN = "Unknown"


@dataclass
class SelectionSummary:
    """Summary of user selection in Available Media table."""
    total_count: int = 0
    selected_count: int = 0
    photo_count: int = 0
    video_count: int = 0
    reel_count: int = 0
    unknown_count: int = 0

    @property
    def has_selection(self) -> bool:
        return self.selected_count > 0

    @property
    def has_photos(self) -> bool:
        return self.photo_count > 0

    @property
    def has_videos(self) -> bool:
        return (self.video_count + self.reel_count) > 0

    @property
    def is_photo_only(self) -> bool:
        return self.has_photos and not self.has_videos

    @property
    def is_video_only(self) -> bool:
        return self.has_videos and not self.has_photos

    @property
    def is_mixed(self) -> bool:
        return self.has_photos and self.has_videos


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
    IMAGE_ONLY = "Image Only"
    ASSETS_ONLY = "Assets Only"
    SUBTITLE_ONLY = ASSETS_ONLY


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
    Represents an individual video scanned from a platform channel, playlist, or creator.

    Attributes:
        index: 1-based order in the scanned channel list.
        video_id: Unique video ID (e.g., 'dQw4w9WgXcQ' or 'BV1xx411c7mD').
        title: Title of the video.
        duration: Human-readable duration string (e.g. '12:34' or '01:15:20').
        duration_seconds: Raw duration in integer seconds (None if live/unknown).
        status: Current state from VideoStatus.
        subtitle_status: Subtitle availability or status (e.g. '✓ Chinese', '—').
        url: Full URL to watch the video on the platform.
        selected: Whether this video is currently checked for download.
        channel_title: Name of the channel/creator this video belongs to.
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
    platform: str = "youtube"
    media_type: str = "Video"
    cover_art_url: Optional[str] = None
    cover_art_width: Optional[int] = None
    cover_art_height: Optional[int] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)
    availability: Optional[VideoAvailability] = None

    def __post_init__(self):
        # Normalize media type and duration for photos and reels
        raw_mtype = str(self.extra_metadata.get("media_type") or "").upper()
        if self.duration == "Photo":
            self.media_type = MediaType.PHOTO
            self.duration_seconds = None
            self.duration = "-"
        elif self.media_type in (MediaType.PHOTO, "Photo", "IMAGE") or raw_mtype in ("IMAGE", "PHOTO"):
            self.media_type = MediaType.PHOTO
            self.duration_seconds = None
            if not self.duration or self.duration == "Photo":
                self.duration = "-"
        elif self.media_type in (MediaType.REEL, "Reel") or raw_mtype == "REEL" or "/reel/" in (self.url or "").lower():
            self.media_type = MediaType.REEL

    @property
    def formatted_duration(self) -> str:
        """Returns formatted duration string (e.g. '03:25', '1:02:15') or '-' for photo/unknown."""
        if self.media_type == MediaType.PHOTO:
            return "-"
        if self.duration_seconds is not None and isinstance(self.duration_seconds, (int, float)):
            sec = int(self.duration_seconds)
            if sec <= 0:
                return "-"
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            if h > 0:
                return f"{h}:{m:02d}:{s:02d}"
            return f"{m:02d}:{s:02d}"
        if self.duration and self.duration not in ("-", "Photo", "Media", "Unknown"):
            return self.duration
        return "-"

    @property
    def media_id(self) -> str:
        """Generalized alias for video_id."""
        return self.video_id

    @property
    def media_url(self) -> str:
        """Generalized alias for url."""
        return self.url

    @property
    def webpage_url(self) -> str:
        return self.extra_metadata.get("webpage_url") or self.url

    @property
    def source_profile_url(self) -> str:
        return self.extra_metadata.get("source_profile_url") or self.url

    @property
    def source_profile_name(self) -> str:
        return self.channel_title

    @property
    def is_private(self) -> bool:
        """Returns True if the video is confirmed to be private."""
        if self.availability is not None and self.availability.is_confirmed:
            if self.availability.status == AvailabilityStatus.PRIVATE:
                return True
            if self.availability.status in (AvailabilityStatus.UNLISTED, AvailabilityStatus.AVAILABLE, AvailabilityStatus.DELETED, AvailabilityStatus.UNAVAILABLE):
                return False

        if self.extra_metadata.get("inaccessibility") == "PRIVATE_VIDEO":
            return True
        if self.error_details is not None:
            cat = getattr(self.error_details, "category", None)
            if cat is not None:
                return cat == "PRIVATE_VIDEO"
        t = (self.title or "").strip().lower()
        r = (self.error_reason or "").strip().lower()
        s = (self.status or "").strip().lower()
        return (
            t in ("[private video]", "[私享视频]", "[私密视频]", "[私人影片]", "[私密影片]")
            or "private video" in t
            or "私享视频" in t
            or "私密视频" in t
            or "私人影片" in t
            or "私密影片" in t
            or s in ("private video", "私享视频", "私人影片", "私密影片")
            or r in ("private video", "私享视频", "私人影片", "私密影片")
            or "video is private" in r
            or "private video" in r
            or "this video is private" in r
            or "sign in if you've been granted access" in r
        )

    @property
    def is_unavailable(self) -> bool:
        """Returns True if the video is confirmed to be deleted or unavailable (non-private)."""
        if self.is_private:
            return False
        if self.availability is not None and self.availability.is_confirmed:
            if self.availability.is_definitively_inaccessible() and self.availability.status != AvailabilityStatus.PRIVATE:
                return True
            if self.availability.status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.UNLISTED):
                return False

        if self.extra_metadata.get("inaccessibility") == "VIDEO_UNAVAILABLE":
            return True
        if self.error_details is not None:
            cat = getattr(self.error_details, "category", None)
            if cat is not None:
                return cat == "VIDEO_UNAVAILABLE"
        t = (self.title or "").strip().lower()
        r = (self.error_reason or "").strip().lower()
        s = (self.status or "").strip().lower()
        return (
            t in ("[deleted video]", "[unavailable video]", "[已删除视频]", "[不可用视频]", "[已刪除影片]", "[無法播放影片]", "[無法存取影片]")
            or "deleted video" in t
            or "unavailable video" in t
            or "已删除视频" in t
            or "已刪除影片" in t
            or "無法播放影片" in t
            or "無法存取影片" in t
            or s in ("unavailable video", "deleted video", "不可用视频", "已刪除影片", "無法播放影片", "無法存取影片")
            or r in ("unavailable video", "deleted video", "不可用视频", "已刪除影片", "無法播放影片", "無法存取影片")
            or "video unavailable" in r
            or "video is unavailable" in r
            or "this video is unavailable" in r
            or "video has been deleted" in r
            or "video has been removed" in r
            or "removed by the uploader" in r
            or "removed by the user" in r
            or "no longer available" in r
            or "video is not available" in r
            or "视频已被删除" in r
            or "视频已删除" in r
            or "视频不可用" in r
            or "影片已被刪除" in r
            or "影片已刪除" in r
            or "影片無法播放" in r
            or "影片無法存取" in r
        )

    @property
    def is_inaccessible(self) -> bool:
        """Returns True if the video is confirmed inaccessible (private or unavailable)."""
        if self.availability is not None:
            return self.availability.is_definitively_inaccessible()
        return self.is_private or self.is_unavailable


@dataclass
class ScanResult:
    """
    Normalized result of scanning a platform channel, playlist, creator, or URL.

    Attributes:
        videos: List of VideoItem instances discovered during the scan.
        source_title: Human-readable display title for the channel, creator, or playlist.
        source_type: Classification (e.g. 'channel', 'playlist', 'creator', 'video', 'collection').
        platform: Platform identifier ('youtube', 'tiktok', 'douyin', 'bilibili', etc.).
        url: Original URL that was scanned.
        extra_metadata: Optional dictionary of raw or platform-specific metadata.
    """
    videos: list = field(default_factory=list)
    source_title: str = ""
    source_type: str = "channel"
    platform: str = "youtube"
    url: str = ""
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        """Allows iterating directly over videos: for video in scan_result: ..."""
        return iter(self.videos)

    def __len__(self) -> int:
        """Returns number of videos."""
        return len(self.videos)

    def __getitem__(self, index):
        """Allows indexing into videos: scan_result[0]."""
        return self.videos[index]

    def __bool__(self) -> bool:
        """Evaluates to True if there are videos, or if a source title exists."""
        return bool(self.videos) or bool(self.source_title)


@dataclass
class DownloadSettings:
    """
    User-configurable download options selected in the GUI.

    Attributes:
        download_mode: Target mode (Video Only, Audio Only, Video + Audio, Assets Only).
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
        include_video_id_in_filename: If True, appends YouTube video ID to generated filenames.
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
    download_cover_art: bool = False
    embed_cover_art: bool = False
    embed_metadata: bool = False
    download_lrc_lyrics: bool = False
    embed_lyrics: bool = False
    save_description: bool = False
    save_metadata: bool = False
    save_chapters: bool = False
    download_folder: str = str(Path.home() / "Downloads" / "Channel Harvest")
    create_channel_folder: bool = True
    create_individual_video_folders: bool = False
    include_video_id_in_filename: bool = False
    skip_existing: bool = False
    image_format: str = "Keep Original"
    image_quality: str = "100% (Best)"
    preserve_original_images: bool = True
    skip_downloaded_media: bool = False
    create_individual_media_folders: bool = False
    include_media_id_in_filename: bool = False
    add_number_to_filename: bool = False
    add_number_prefix: bool = False
    create_unique_filename: bool = False
    create_unique_folder: bool = False
    unique_filename_folder: str = ""
    unique_folder_name: str = ""
    custom_folder_name: str = ""
    max_scan_index: Optional[int] = None
    number_prefix: str = ""
    channel_title: str = ""
    auth_method: str = "none"
    browser_cookies: str = "none"
    browser_profile: str = "Default"
    custom_cookie_file: str = ""
    douyin_auth_method: str = "none"
    douyin_browser_cookies: str = "none"
    douyin_browser_profile: str = "Default"
    douyin_custom_cookie_file: str = ""
    bilibili_auth_method: str = "none"
    bilibili_custom_cookie_file: str = ""
    facebook_auth_method: str = "none"
    facebook_custom_cookie_file: str = ""
    instagram_auth_method: str = "none"
    instagram_custom_cookie_file: str = ""
    x_auth_method: str = "none"
    x_custom_cookie_file: str = ""
    tiktok_auth_method: str = "none"
    tiktok_custom_cookie_file: str = ""
    all_auth_method: str = "none"
    all_custom_cookie_file: str = ""

    def __post_init__(self):
        if self.add_number_prefix and not self.add_number_to_filename:
            self.add_number_to_filename = True
        elif self.add_number_to_filename and not self.add_number_prefix:
            self.add_number_prefix = True

        if self.create_unique_filename or self.create_unique_folder:
            self.create_unique_filename = True
            self.create_unique_folder = True
        eff_folder = self.unique_filename_folder or self.unique_folder_name or self.custom_folder_name
        if eff_folder:
            self.unique_filename_folder = eff_folder
            self.unique_folder_name = eff_folder
            self.custom_folder_name = eff_folder
