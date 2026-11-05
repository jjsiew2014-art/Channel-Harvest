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
    api_token: Optional[str] = None  # Platform API token (e.g. Meta Graph API token)
    description: str = "None"

    @classmethod
    def none(cls) -> "PlatformAuthConfig":
        """Returns a non-active authentication configuration."""
        return cls(auth_method="none", description="None", api_token=None)

    @property
    def is_active(self) -> bool:
        """Returns True if this configuration contains active authentication credentials."""
        return self.auth_method in ("browser", "custom_file") or bool(self.api_token)

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


def resolve_effective_cookie_file(
    platform_id: str,
    platform_auth_method: str,
    platform_cookie_file: str,
    settings: Optional[Any] = None,
) -> tuple[str, str, str]:
    """
    Resolves effective auth_method, cookie_file, and source description suffix.
    If the platform's own auth_method is 'none' or missing a valid cookie file,
    falls back to the global 'all' platform configuration if active.

    Returns:
        (effective_auth_method, effective_cookie_file, source_desc)
    """
    if platform_auth_method == "custom_file" and platform_cookie_file:
        p = Path(platform_cookie_file)
        if p.is_file():
            return "custom_file", str(p.resolve()), ""

    # Check fallback to 'all'
    all_method = "none"
    all_file = ""
    if settings is not None:
        if hasattr(settings, "get") and callable(settings.get):
            all_method = settings.get("all_auth_method", "none") or "none"
            all_file = settings.get("all_custom_cookie_file", "") or ""
        elif hasattr(settings, "all_auth_method"):
            all_method = getattr(settings, "all_auth_method", "none") or "none"
            all_file = getattr(settings, "all_custom_cookie_file", "") or ""
        elif isinstance(settings, dict):
            all_method = settings.get("all_auth_method", "none") or "none"
            all_file = settings.get("all_custom_cookie_file", "") or ""
    else:
        try:
            from core.settings import SettingsManager
            sm = SettingsManager()
            all_method = sm.get("all_auth_method", "none") or "none"
            all_file = sm.get("all_custom_cookie_file", "") or ""
        except Exception:
            pass

    if all_method == "custom_file" and all_file:
        ap = Path(all_file)
        if ap.is_file():
            return "custom_file", str(ap.resolve()), " (All Platforms)"

    return platform_auth_method, platform_cookie_file, ""

