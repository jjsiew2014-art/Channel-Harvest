"""
capabilities.py
Feature capability matrix for media download platforms in Channel Harvest.
Allows the GUI and download pipeline to query platform feature support dynamically.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformCapabilities:
    """
    Defines capabilities and supported feature set for a platform adapter.
    Prevents assuming all platforms support YouTube-specific features like chapters or subtitles.
    """
    supports_video: bool = True
    supports_audio: bool = True
    supports_subtitles: bool = True
    supports_thumbnails: bool = True
    supports_description: bool = True
    supports_metadata: bool = True
    supports_chapters: bool = True
    supports_playlists: bool = True
    supports_channel_scan: bool = True
    supports_browser_cookies: bool = False
    supports_cookie_file: bool = False
    archive_prefix: str = "youtube"
