"""
core/platform package
Provides platform adapter abstractions, capability queries, and registry for Channel Harvest.
"""

from core.platform.capabilities import PlatformCapabilities
from core.platform.auth import PlatformAuthConfig
from core.platform.base import PlatformAdapter
from core.platform.detector import PlatformDetector, PlatformRegistry
from core.platform.youtube import YouTubeAdapter
from core.platform.tiktok import TikTokAdapter
from core.platform.douyin import DouyinAdapter

# Auto-register default platform adapters
PlatformRegistry.register(YouTubeAdapter())
PlatformRegistry.register(TikTokAdapter())
PlatformRegistry.register(DouyinAdapter())

__all__ = [
    "PlatformCapabilities",
    "PlatformAuthConfig",
    "PlatformAdapter",
    "PlatformDetector",
    "PlatformRegistry",
    "YouTubeAdapter",
    "TikTokAdapter",
    "DouyinAdapter",
]
