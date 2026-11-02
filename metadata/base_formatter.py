"""
base_formatter.py
Abstract base class and shared utilities for platform-specific metadata TXT formatters.
Channel Harvest - Multi-Platform Architecture.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
import re


class BaseMetadataFormatter(ABC):
    """
    Abstract base formatter defining the contract for platform-specific metadata TXT generation.
    Provides standard sanitization, numeric formatting, date parsing, and visual layout helpers.
    """

    SEPARATOR_CHAR = "="
    SEPARATOR_WIDTH = 40

    @property
    @abstractmethod
    def platform_id(self) -> str:
        """Unique platform identifier (e.g. 'youtube', 'tiktok', 'bilibili')."""
        pass

    @property
    @abstractmethod
    def platform_display_name(self) -> str:
        """Human-readable platform name (e.g. 'YouTube', 'TikTok', 'Bilibili')."""
        pass

    @abstractmethod
    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        """
        Formats raw yt-dlp metadata and VideoItem into a platform-appropriate TXT document.

        Args:
            info: Raw or normalized dictionary returned by yt-dlp.
            video: Optional VideoItem model containing application-level metadata.

        Returns:
            Clean, structured, human-readable UTF-8 string.
        """
        pass

    # -------------------------------------------------------------------------
    # Shared Layout & Section Builders
    # -------------------------------------------------------------------------

    @classmethod
    def make_header(cls, title: str) -> str:
        """Constructs a standardized top document banner."""
        sep = cls.SEPARATOR_CHAR * cls.SEPARATOR_WIDTH
        return f"{sep}\n{title.upper()}\n{sep}\n\n"

    @classmethod
    def make_section(cls, title: str, lines_or_text: Union[List[str], str]) -> str:
        """
        Builds a visually separated section block.
        Accepts either a list of pre-formatted lines or a multiline text block.
        """
        sep = cls.SEPARATOR_CHAR * cls.SEPARATOR_WIDTH
        if isinstance(lines_or_text, list):
            content = "\n".join(line for line in lines_or_text if line is not None).strip()
        else:
            content = str(lines_or_text or "").strip()

        if not content:
            content = "None"

        return f"{sep}\n{title.upper()}\n{sep}\n\n{content}\n\n"

    # -------------------------------------------------------------------------
    # Value Formatting Helpers
    # -------------------------------------------------------------------------

    @classmethod
    def format_number(cls, val: Any) -> str:
        """Formats integer/float with comma thousands grouping, or returns 'N/A'."""
        if val is None or val == "":
            return "N/A"
        try:
            return f"{int(val):,}"
        except (ValueError, TypeError):
            return str(val)

    @classmethod
    def format_date(cls, val: Any) -> str:
        """
        Formats YYYYMMDD string or timestamp into YYYY-MM-DD.
        Returns 'N/A' if missing or unparseable.
        """
        if not val:
            return "N/A"
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        # If passed as integer Unix timestamp
        if isinstance(val, (int, float)) and val > 100000000:
            import datetime
            try:
                dt = datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        return s

    @classmethod
    def format_timestamp(cls, seconds: Optional[float]) -> str:
        """Formats seconds into standardized HH:MM:SS timestamp."""
        if seconds is None:
            return "00:00:00"
        try:
            s = int(seconds)
            if s < 0:
                return "00:00:00"
            hours = s // 3600
            minutes = (s % 3600) // 60
            secs = s % 60
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "00:00:00"

    @classmethod
    def format_duration(cls, seconds: Optional[float]) -> str:
        """Formats seconds into human-readable duration string (MM:SS or HH:MM:SS)."""
        if seconds is None:
            return "N/A"
        try:
            s = int(seconds)
            if s < 0:
                return "N/A"
            hours = s // 3600
            minutes = (s % 3600) // 60
            secs = s % 60
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "N/A"

    @classmethod
    def format_file_size(cls, bytes_val: Optional[Union[int, float]]) -> str:
        """Formats bytes into human-readable size string (MB, GB)."""
        if bytes_val is None or bytes_val <= 0:
            return "N/A"
        try:
            b = float(bytes_val)
            for unit in ["B", "KB", "MB", "GB", "TB"]:
                if b < 1024.0:
                    return f"{b:.2f} {unit}"
                b /= 1024.0
            return f"{b:.2f} PB"
        except Exception:
            return "N/A"

    @classmethod
    def sanitize_field(cls, val: Any, fallback: str = "N/A") -> str:
        """
        Safely stringifies any field, stripping leading/trailing whitespace.
        Never leaks private objects, dicts, or None.
        """
        if val is None or val == "":
            return fallback
        if isinstance(val, (dict, list, set, tuple)):
            # Avoid dumping internal data structures
            return fallback
        s = str(val).strip()
        return s if s else fallback
