"""
detector.py
Platform detection mechanism and adapter registry for Channel Harvest.
"""

from urllib.parse import urlparse
from typing import Dict, List, Optional, Type

from core.platform.base import PlatformAdapter


class PlatformDetector:
    """
    Detects platform from target URL using hostname matching and path inspection.
    Supports YouTube, TikTok, and Douyin without modifying current UI.
    """

    # Domain patterns for known platforms
    YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")
    TIKTOK_DOMAINS = ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")
    DOUYIN_DOMAINS = ("douyin.com", "iesdouyin.com")

    @classmethod
    def extract_url(cls, text: str) -> str:
        """
        Extracts first valid http/https URL from raw text (e.g. mobile app share snippets).
        Returns clean URL or stripped original text.
        """
        if not text or not isinstance(text, str):
            return ""
        import re
        m = re.search(r"https?://[^\s]+", text)
        if m:
            clean = m.group(0).rstrip("，。！？；、“”‘’'\"")
            return clean
        return text.strip()

    @classmethod
    def identify_platform_id(cls, url: str) -> str:
        """
        Returns platform ID: 'youtube', 'tiktok', 'douyin', or 'unknown'.
        """
        if not url or not isinstance(url, str):
            return "unknown"

        url_clean = cls.extract_url(url)
        if not url_clean:
            return "unknown"

        if not (url_clean.startswith("http://") or url_clean.startswith("https://")):
            url_clean = "https://" + url_clean

        try:
            parsed = urlparse(url_clean)
            netloc = (parsed.netloc or "").lower().split(":")[0]
            if not netloc:
                return "unknown"

            # Check YouTube
            if any(netloc == host or netloc.endswith("." + host) for host in cls.YOUTUBE_DOMAINS):
                return "youtube"

            # Check TikTok
            if any(netloc == host or netloc.endswith("." + host) for host in cls.TIKTOK_DOMAINS):
                return "tiktok"

            # Check Douyin
            if any(netloc == host or netloc.endswith("." + host) for host in cls.DOUYIN_DOMAINS):
                return "douyin"

        except Exception:
            return "unknown"

        return "unknown"


class PlatformRegistry:
    """
    Central registry managing registered PlatformAdapter instances and their availability.
    """
    _adapters: Dict[str, PlatformAdapter] = {}
    _availability_overrides: Dict[str, bool] = {}

    @classmethod
    def register(cls, adapter: PlatformAdapter) -> None:
        """Registers a platform adapter."""
        cls._adapters[adapter.platform_id] = adapter

    @classmethod
    def get_adapter(cls, platform_id: str) -> Optional[PlatformAdapter]:
        """Retrieves adapter by platform identifier."""
        return cls._adapters.get(platform_id)

    @classmethod
    def get_adapter_for_url(cls, url: str) -> Optional[PlatformAdapter]:
        """Detects platform and returns the matching adapter if registered."""
        # 1. First check registered adapters directly
        for adapter in cls._adapters.values():
            if adapter.matches_url(url):
                return adapter

        # 2. Check platform ID via detector
        platform_id = PlatformDetector.identify_platform_id(url)
        return cls._adapters.get(platform_id)

    @classmethod
    def all_adapters(cls) -> List[PlatformAdapter]:
        """Returns list of all registered platform adapters."""
        return list(cls._adapters.values())

    @classmethod
    def is_available(cls, platform_id: str) -> bool:
        """
        Centralized platform availability check.
        Returns True if the platform is enabled and ready for scanning/downloading.
        Consults runtime availability overrides before delegating to the adapter's is_available property.
        """
        if platform_id in cls._availability_overrides:
            return cls._availability_overrides[platform_id]
        adapter = cls.get_adapter(platform_id)
        if adapter is not None:
            return adapter.is_available
        return False

    @classmethod
    def set_platform_available(cls, platform_id: str, available: bool) -> None:
        """
        Centralized control to toggle platform availability dynamically.
        Enables freezing or re-enabling Douyin or any other platform without
        deleting or rebuilding adapter implementations.
        """
        cls._availability_overrides[platform_id] = available

    @classmethod
    def get_availability_override(cls, platform_id: str) -> Optional[bool]:
        """Returns runtime availability override if set, else None."""
        return cls._availability_overrides.get(platform_id)

    @classmethod
    def reset_availability_overrides(cls) -> None:
        """Resets all runtime availability overrides to adapter defaults."""
        cls._availability_overrides.clear()

    @classmethod
    def get_enabled_adapters(cls) -> List[PlatformAdapter]:
        """Returns list of all registered platform adapters that are currently available."""
        return [ad for ad in cls._adapters.values() if cls.is_available(ad.platform_id)]
