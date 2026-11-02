"""
core/platform package
Provides platform adapter abstractions, capability queries, and registry for Channel Harvest.
"""

from core.platform.capabilities import PlatformCapabilities
from core.platform.auth import PlatformAuthConfig
from core.platform.base import PlatformAdapter
from core.platform.detector import PlatformDetector, PlatformRegistry
from core.platform.youtube import YouTubeAdapter
from core.platform.youtubemusic import YouTubeMusicAdapter
from core.platform.tiktok import TikTokAdapter
from core.platform.douyin import DouyinAdapter
from core.platform.bilibili import BilibiliAdapter
from core.platform.facebook import FacebookAdapter
from core.platform.instagram import InstagramAdapter
from core.platform.x import XAdapter

# Auto-register default platform adapters
PlatformRegistry.register(YouTubeAdapter())
PlatformRegistry.register(YouTubeMusicAdapter())
PlatformRegistry.register(FacebookAdapter())
PlatformRegistry.register(InstagramAdapter())
PlatformRegistry.register(XAdapter())
PlatformRegistry.register(BilibiliAdapter())
PlatformRegistry.register(TikTokAdapter())
PlatformRegistry.register(DouyinAdapter())

__all__ = [
    "PlatformCapabilities",
    "PlatformAuthConfig",
    "PlatformAdapter",
    "PlatformDetector",
    "PlatformRegistry",
    "YouTubeAdapter",
    "YouTubeMusicAdapter",
    "FacebookAdapter",
    "InstagramAdapter",
    "XAdapter",
    "BilibiliAdapter",
    "TikTokAdapter",
    "DouyinAdapter",
]
