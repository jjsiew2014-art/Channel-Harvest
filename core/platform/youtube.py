"""
youtube.py
PlatformAdapter implementation for YouTube in Channel Harvest.
Wraps existing YtDlpEngine extraction logic cleanly.
"""

from typing import List, Tuple, Optional, Callable, Dict, Any

from core.models import VideoItem, DownloadSettings
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector


class YouTubeAdapter(PlatformAdapter):
    """
    Concrete adapter for YouTube. Delegates extraction to YtDlpEngine
    while preserving 100% of existing behavior and options.
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
            archive_prefix="youtube",
        )

    @property
    def platform_id(self) -> str:
        return "youtube"

    @property
    def display_name(self) -> str:
        return "YouTube"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        return PlatformDetector.identify_platform_id(url) == "youtube"

    def validate_url(self, url: str) -> Tuple[bool, str]:
        from downloader.ytdlp_engine import YtDlpEngine
        return YtDlpEngine.validate_url(url)

    def normalize_url(self, url: str) -> str:
        from downloader.ytdlp_engine import YtDlpEngine
        return YtDlpEngine.normalize_channel_url(url)

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
            item.platform = "youtube"
        return entries

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        if original_url and ("youtube.com" in original_url or "youtu.be" in original_url):
            return original_url
        return f"https://www.youtube.com/watch?v={video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        return f"youtube {video.video_id}"

    def get_auth_config(self, settings: Optional[Any] = None) -> "PlatformAuthConfig":
        """
        Resolves YouTube-specific authentication configuration.
        Supports Browser Cookies and Custom Cookie File.
        """
        from pathlib import Path
        from core.settings import SettingsManager
        from core.platform.auth import PlatformAuthConfig

        auth_method = "none"
        browser_cookies = "none"
        browser_profile = "Default"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "browser_cookies"):
                browser_cookies = getattr(settings, "browser_cookies", "none") or "none"
            elif isinstance(settings, dict):
                browser_cookies = settings.get("browser_cookies", "none") or "none"
                auth_method = settings.get("auth_method", "none") or "none"
                browser_profile = settings.get("browser_profile", "Default") or "Default"
                custom_cookie_file = settings.get("custom_cookie_file", "") or ""

        # Read from global SettingsManager if not explicitly set
        try:
            sm = SettingsManager()
            if auth_method == "none":
                auth_method = sm.get("auth_method", "none")
            if browser_cookies == "none":
                browser_cookies = sm.get("browser_cookies", "none")
            if browser_profile == "Default":
                browser_profile = sm.get("browser_profile", "Default")
            if not custom_cookie_file:
                custom_cookie_file = sm.get("custom_cookie_file", "")
        except Exception:
            pass

        # Normalize auth_method if missing but browser_cookies is set
        if auth_method == "none" and browser_cookies not in ("none", "", None):
            if browser_cookies == "custom_file":
                auth_method = "custom_file"
            elif browser_cookies in ("chrome", "firefox", "edge", "brave", "opera", "vivaldi", "chromium", "safari"):
                auth_method = "browser"

        if auth_method == "custom_file" or browser_cookies == "custom_file":
            cookie_path = Path(custom_cookie_file) if custom_cookie_file else None
            if cookie_path and cookie_path.is_file():
                return PlatformAuthConfig(
                    auth_method="custom_file",
                    cookie_file=str(cookie_path.resolve()),
                    description="Custom Cookie File",
                )
            return PlatformAuthConfig.none()

        elif auth_method == "browser" or browser_cookies not in ("none", "", "null", "false", None):
            b_name = browser_cookies if browser_cookies != "custom_file" else "none"
            if b_name and b_name.lower() not in ("none", "", "null", "false"):
                return PlatformAuthConfig(
                    auth_method="browser",
                    browser_name=b_name.lower(),
                    browser_profile=browser_profile,
                    description=f"Browser Cookies ({b_name.capitalize()})",
                )
            return PlatformAuthConfig.none()

        return PlatformAuthConfig.none()
