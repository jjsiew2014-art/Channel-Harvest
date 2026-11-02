"""
youtubemusic.py
PlatformAdapter implementation for YouTube Music in Channel Harvest.
Specializes in music albums, tracks, playlists, and artist extraction
with full audio extraction, cover art, LRC lyrics, and metadata parity.
"""

from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.parse import urlparse

from core.models import VideoItem, DownloadSettings, ScanResult
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector


class YouTubeMusicAdapter(PlatformAdapter):
    """
    Concrete adapter for YouTube Music (music.youtube.com).
    Integrates music streaming tracks, albums, playlists, and artists
    with full audio/cover art/lyrics feature parity.
    """

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=True,
            supports_thumbnails=True,
            supports_description=True,
            supports_metadata=True,
            supports_chapters=True,
            supports_playlists=True,
            supports_channel_scan=True,
            supports_browser_cookies=True,
            supports_cookie_file=True,
            archive_prefix="youtubemusic",
        )

    @property
    def platform_id(self) -> str:
        return "youtubemusic"

    @property
    def display_name(self) -> str:
        return "YouTube Music"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        return PlatformDetector.identify_platform_id(url) == "youtubemusic"

    def validate_url(self, url: str) -> Tuple[bool, str]:
        cleaned = (url or "").strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a YouTube Music song, album, or playlist URL."
        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"
            netloc = (parsed.netloc or "").lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.YOUTUBE_MUSIC_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid YouTube Music domain."
            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific song, album, playlist, or artist URL."
            return True, ""
        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def normalize_url(self, url: str) -> str:
        return (url or "").strip()

    def scan(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> ScanResult:
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        if auth_config is None:
            settings_dict = {}
            if browser_cookies:
                settings_dict["browser_cookies"] = browser_cookies
            if custom_cookie_file:
                settings_dict["custom_cookie_file"] = custom_cookie_file
            auth_config = self.get_auth_config(settings=settings_dict if settings_dict else None)
        scan_res = engine.scan_channel_entries(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
        )
        scan_res.platform = "youtubemusic"
        for item in scan_res.videos:
            item.platform = "youtubemusic"
        return scan_res

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        if auth_config is None:
            settings_dict = {}
            if browser_cookies:
                settings_dict["browser_cookies"] = browser_cookies
            if custom_cookie_file:
                settings_dict["custom_cookie_file"] = custom_cookie_file
            auth_config = self.get_auth_config(settings=settings_dict if settings_dict else None)
        entries = engine.extract_channel_entries(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
        )
        for item in entries:
            item.platform = "youtubemusic"
        return entries

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        if original_url and "music.youtube.com" in original_url:
            return original_url
        return f"https://music.youtube.com/watch?v={video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        return f"youtubemusic {video.video_id}"

    def get_auth_config(self, settings: Optional[Any] = None) -> "PlatformAuthConfig":
        """
        Resolves YouTube Music authentication configuration.
        Shares Google/YouTube authentication credentials by default
        since YouTube Music operates within the same Google account.
        """
        from core.platform.detector import PlatformRegistry
        yt_adapter = PlatformRegistry.get_adapter("youtube")
        if yt_adapter:
            return yt_adapter.get_auth_config(settings=settings)
        from core.platform.auth import PlatformAuthConfig
        return PlatformAuthConfig.none()
