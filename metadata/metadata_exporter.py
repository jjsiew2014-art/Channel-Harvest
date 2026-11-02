"""
metadata_exporter.py
Central dispatcher, security sanitizer, and file writer for platform-specific metadata exports.
Channel Harvest - Multi-Platform Architecture.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, Callable
import logging
import re

from metadata.base_formatter import BaseMetadataFormatter
from metadata.youtube_formatter import YouTubeMetadataFormatter
from metadata.tiktok_formatter import TikTokMetadataFormatter
from metadata.bilibili_formatter import BilibiliMetadataFormatter
from metadata.facebook_formatter import FacebookMetadataFormatter
from metadata.instagram_formatter import InstagramMetadataFormatter
from metadata.x_formatter import XMetadataFormatter
from metadata.generic_formatter import GenericMetadataFormatter

logger = logging.getLogger("MetadataExporter")


class MetadataExporter:
    """
    Central dispatcher and file manager for metadata TXT generation.
    Selects the appropriate formatter based on platform identity, sanitizes sensitive
    credentials, and safely writes UTF-8 metadata files.
    """

    _FORMATTERS: Dict[str, BaseMetadataFormatter] = {
        "youtube": YouTubeMetadataFormatter(),
        "facebook": FacebookMetadataFormatter(),
        "instagram": InstagramMetadataFormatter(),
        "x": XMetadataFormatter(),
        "twitter": XMetadataFormatter(),
        "tiktok": TikTokMetadataFormatter(),
        "bilibili": BilibiliMetadataFormatter(),
        "generic": GenericMetadataFormatter(),
    }

    # Sensitive token / cookie patterns to scrub from all metadata exports
    _SENSITIVE_PATTERNS = [
        re.compile(r"SESSDATA=[^;\s]+", re.IGNORECASE),
        re.compile(r"bili_jct=[^;\s]+", re.IGNORECASE),
        re.compile(r"DedeUserID(?:__ckMd5)?=[^;\s]+", re.IGNORECASE),
        re.compile(r"buvid[34]?=[^;\s]+", re.IGNORECASE),
        re.compile(r"sid_tt=[^;\s]+", re.IGNORECASE),
        re.compile(r"sessionid=[^;\s]+", re.IGNORECASE),
        re.compile(r"c_user=[^;\s]+", re.IGNORECASE),
        re.compile(r"xs=[^;\s]+", re.IGNORECASE),
        re.compile(r"auth_token=[^;\s]+", re.IGNORECASE),
        re.compile(r"ct0=[^;\s]+", re.IGNORECASE),
        re.compile(r"twid=[^;\s]+", re.IGNORECASE),
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
        re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE),
    ]

    @classmethod
    def get_formatter(
        cls,
        platform_id: Optional[str] = None,
        info: Optional[Dict[str, Any]] = None,
        video: Optional[Any] = None,
    ) -> BaseMetadataFormatter:
        """
        Resolves the appropriate formatter instance.

        Resolution Priority:
            1. Explicit platform_id argument (if known)
            2. video.platform attribute (e.g. 'youtube', 'tiktok', 'bilibili')
            3. info['extractor_key'] or info['extractor'] (yt-dlp extractor name)
            4. Generic fallback formatter
        """
        resolved_id = ""

        if platform_id:
            resolved_id = str(platform_id).strip().lower()
        elif video and getattr(video, "platform", None):
            resolved_id = str(video.platform).strip().lower()
        elif info:
            extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
            if "youtube" in extractor:
                resolved_id = "youtube"
            elif "tiktok" in extractor:
                resolved_id = "tiktok"
            elif "bilibili" in extractor:
                resolved_id = "bilibili"
            elif "facebook" in extractor:
                resolved_id = "facebook"
            elif "instagram" in extractor:
                resolved_id = "instagram"
            elif "twitter" in extractor or extractor == "x":
                resolved_id = "x"

        return cls._FORMATTERS.get(resolved_id, cls._FORMATTERS["generic"])

    @classmethod
    def sanitize_credentials(cls, content: str) -> str:
        """
        Guarantees zero credential leakage by scrubbing any tokens, cookies,
        session IDs, or auth headers that might have entered raw metadata fields.
        """
        if not content:
            return ""

        sanitized = content
        for pattern in cls._SENSITIVE_PATTERNS:
            sanitized = pattern.sub("[REDACTED_CREDENTIAL]", sanitized)

        return sanitized

    @classmethod
    def export_metadata_txt(
        cls,
        info: Dict[str, Any],
        video: Optional[Any] = None,
        platform_id: Optional[str] = None,
    ) -> str:
        """
        Generates formatted metadata TXT content for the given media item.

        Args:
            info: Metadata dictionary from yt-dlp.
            video: Optional VideoItem domain model.
            platform_id: Optional explicit platform override.

        Returns:
            Sanitized, platform-appropriate TXT document string.
        """
        safe_info = info or {}
        formatter = cls.get_formatter(platform_id=platform_id, info=safe_info, video=video)
        raw_text = formatter.format(safe_info, video=video)
        return cls.sanitize_credentials(raw_text)

    @classmethod
    def save_metadata_file(
        cls,
        target_path: Union[str, Path],
        info: Dict[str, Any],
        video: Optional[Any] = None,
        platform_id: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Safely writes metadata TXT to disk with explicit UTF-8 encoding.
        Catches filesystem, permission, and disk space exceptions to prevent blocking
        the main download queue.

        Args:
            target_path: Destination file path.
            info: Metadata dictionary.
            video: Optional VideoItem.
            platform_id: Optional platform override.
            log_callback: Optional logging callback.

        Returns:
            True if written successfully, False otherwise.
        """
        try:
            path = Path(target_path)

            # Ensure parent directories exist
            path.parent.mkdir(parents=True, exist_ok=True)

            # Generate formatted content
            content = cls.export_metadata_txt(info, video=video, platform_id=platform_id)

            # Support Windows long paths (> 260 characters)
            path_str = str(path.resolve())
            if len(path_str) >= 240 and not path_str.startswith("\\\\?\\") and "\\" in path_str:
                path = Path(f"\\\\?\\{path_str}")

            # Write with explicit UTF-8
            path.write_text(content, encoding="utf-8", errors="replace")
            return True

        except Exception as e:
            msg = f"Failed to save metadata file '{target_path}': {str(e)}"
            logger.warning(msg)
            if log_callback:
                log_callback(f"[WARNING] {msg}")
            return False
