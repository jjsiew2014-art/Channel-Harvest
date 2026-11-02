"""
base.py
Abstract base class and interface definition for Channel Harvest platform adapters.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Callable, Dict, Any

from core.models import VideoItem, DownloadSettings, ScanResult
from core.platform.capabilities import PlatformCapabilities


class PlatformAdapter(ABC):
    """
    Abstract interface for platform-specific adapters.
    Encapsulates URL parsing, metadata extraction, format resolution,
    and platform-specific constraints.
    """

    @property
    @abstractmethod
    def platform_id(self) -> str:
        """Unique identifier (e.g. 'youtube', 'tiktok', 'douyin')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable display name (e.g. 'YouTube', 'TikTok', 'Douyin')."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> PlatformCapabilities:
        """Returns the capability flags for this platform."""
        pass

    @property
    def is_available(self) -> bool:
        """
        Whether this platform is currently available for scanning and downloading.
        Returns True by default. Subclasses may override if a platform is temporarily frozen.
        """
        return True

    @property
    def unavailable_reason(self) -> Optional[str]:
        """Returns localized explanation key or text if the platform is unavailable."""
        return None

    @abstractmethod
    def matches_url(self, url: str) -> bool:
        """Returns True if the URL belongs to this platform."""
        pass

    @abstractmethod
    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates whether the URL is supported and ready for scanning.
        Returns: (is_valid: bool, error_reason: str)
        """
        pass

    @abstractmethod
    def normalize_url(self, url: str) -> str:
        """Normalizes URL for scanning (e.g., handles trailing slashes, /videos suffix)."""
        pass

    @abstractmethod
    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        """Scans the channel, user page, playlist, or single video and returns VideoItems."""
        pass

    def scan(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> ScanResult:
        """
        Scans the source URL and returns a normalized ScanResult containing the videos
        and the human-readable source title (channel, creator, playlist).
        Default implementation delegates to extract_entries and derives
        source_title from the first entry's channel_title if available.
        """
        videos = self.extract_entries(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
        )
        source_title = ""
        if videos:
            source_title = videos[0].channel_title or ""
        return ScanResult(
            videos=videos,
            source_title=source_title,
            source_type="channel",
            platform=self.platform_id,
            url=url,
        )

    @abstractmethod
    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """Constructs a canonical playback URL from a video/item ID."""
        pass

    @abstractmethod
    def get_archive_tag(self, video: VideoItem) -> str:
        """Returns the entry format for download_archive.txt (e.g. 'youtube {id}')."""
        pass

    def get_auth_config(self, settings: Optional[Any] = None) -> "PlatformAuthConfig":
        """
        Resolves authentication configuration for this platform.
        Defaults to PlatformAuthConfig.none() for platforms without explicit authentication support.
        """
        from core.platform.auth import PlatformAuthConfig
        return PlatformAuthConfig.none()
