"""
auth.py
Platform-scoped authentication configuration for Channel Harvest.
Encapsulates credentials and options passed to yt-dlp on a per-platform basis.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass
class PlatformAuthConfig:
    """
    Platform-scoped authentication configuration for yt-dlp operations.
    Determines whether and how authentication options are applied.
    """
    auth_method: str = "none"  # "none", "browser", "custom_file"
    browser_name: Optional[str] = None  # e.g., "chrome", "firefox", "edge"
    browser_profile: Optional[str] = None  # e.g., "Default"
    cookie_file: Optional[str] = None  # Valid path to Netscape cookies file
    description: str = "None"

    @classmethod
    def none(cls) -> "PlatformAuthConfig":
        """Returns a non-active authentication configuration."""
        return cls(auth_method="none", description="None")

    @property
    def is_active(self) -> bool:
        """Returns True if this configuration contains active authentication credentials."""
        return self.auth_method in ("browser", "custom_file")

    def apply_to_ydl_opts(self, opts: Dict[str, Any]) -> None:
        """Applies authentication parameters to yt-dlp options dictionary."""
        if not self.is_active:
            return

        if self.auth_method == "custom_file" and self.cookie_file:
            cookie_path = Path(self.cookie_file)
            if cookie_path.is_file():
                opts["cookiefile"] = str(cookie_path.resolve())
        elif self.auth_method == "browser" and self.browser_name:
            clean_browser = self.browser_name.lower().strip()
            prof = self.browser_profile if self.browser_profile and self.browser_profile.lower() != "default" else None
            opts["cookiesfrombrowser"] = (clean_browser, prof, None, None)
