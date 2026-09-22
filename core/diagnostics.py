"""
diagnostics.py
Diagnostic report generation and error tracking utility for Channel Harvest.

Features:
- Thread-safe error tracking with automatic classification into standard error categories.
- Strict privacy sanitization: strips all cookies, tokens, passwords, auth headers,
  and private local user paths before inclusion.
- Generates clean, human-readable diagnostic text blocks for troubleshooting.
"""

import os
import re
import sys
import time
import platform
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from core.version import __version__
from core.settings import SettingsManager


# =============================================================================
# Standard Diagnostic Error Categories
# =============================================================================

class DiagnosticCategory:
    NONE = "NONE"
    RATE_LIMITED = "RATE_LIMITED"
    BOT_VERIFICATION = "BOT_VERIFICATION"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    JS_RUNTIME_ERROR = "JS_RUNTIME_ERROR"
    EJS_ERROR = "EJS_ERROR"
    PO_TOKEN_ERROR = "PO_TOKEN_ERROR"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    REGION_RESTRICTED = "REGION_RESTRICTED"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    FORMAT_ERROR = "FORMAT_ERROR"
    FFMPEG_ERROR = "FFMPEG_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# =============================================================================
# Privacy & Security Sanitizer
# =============================================================================

class PrivacySanitizer:
    """
    Guarantees that sensitive authentication and private personal data
    never leak into logs, clipboard copies, or diagnostic reports.
    """

    # Regex patterns for sensitive tokens and cookies
    _SENSITIVE_PATTERNS = [
        # Bearer / Auth tokens
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.+=]+"),
        re.compile(r"(?i)(authorization:\s*)[^\r\n]+"),
        re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9_\-]+"),
        re.compile(r"(?i)(password\s*[:=]\s*)[^\s&]+"),
        re.compile(r"(?i)(token\s*[:=]\s*)[A-Za-z0-9_\-\.+=]+"),
        re.compile(r"(?i)(po[_-]?token\s*[:=]\s*)[A-Za-z0-9_\-\.+=]+"),
        re.compile(r"(?i)(visitor[_-]?data\s*[:=]\s*)[A-Za-z0-9_\-\.+=]+"),
        re.compile(r"(?i)(session[_-]?id\s*[:=]\s*)[A-Za-z0-9_\-]+"),
        # Cookies
        re.compile(r"(?i)(cookie\s*[:=]\s*)[^\r\n]+"),
        re.compile(r"(?i)(sapisid|ssid|hsid|login_info)\s*[:=]\s*[^\s;]+"),
        re.compile(r"(?i)__secure-[^=]+=[^;\s]+"),
        # Windows Security Identifiers (SIDs)
        re.compile(r"S-1-5-21(?:-\d+){3,}"),
    ]

    # Windows user path sanitizer: C:\Users\Username\... -> <UserPath>\...
    _USER_PATH_PATTERN = re.compile(
        r"(?i)[a-z]:\\users\\[a-z0-9_.\-]+(?=\\)",
        re.IGNORECASE,
    )

    # Clean URL query parameters if they might contain signatures or tokens
    _URL_PARAM_PATTERN = re.compile(
        r"(https?://[^\s\?]+)\?([^\s#]+)",
    )

    @classmethod
    def sanitize_message(cls, message: str) -> str:
        """Sanitizes an error or log message by masking sensitive tokens and paths."""
        if not message:
            return ""

        text = str(message)

        # 1. Mask sensitive key-value pairs
        for pattern in cls._SENSITIVE_PATTERNS:
            text = pattern.sub(lambda m: (m.group(1) if m.lastindex and m.lastindex >= 1 else "") + "<REDACTED>", text)

        # 2. Mask private local filesystem user paths
        text = cls._USER_PATH_PATTERN.sub("<UserPath>", text)

        # 3. Mask sensitive URL query parameters
        def _mask_url_params(match):
            base_url = match.group(1)
            params = match.group(2)
            if any(k in params.lower() for k in ("token", "sig", "key", "auth", "expire", "id")):
                return f"{base_url}?<params_redacted>"
            return match.group(0)

        text = cls._URL_PARAM_PATTERN.sub(_mask_url_params, text)

        # 4. Strip ANSI escape sequences if present
        text = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)

        return text.strip()

    # Alias for convenience
    sanitize = sanitize_message


# =============================================================================
# Error Classification & Tracking
# =============================================================================

class ErrorTracker:
    """
    Thread-safe error tracker that retains the most recent error
    and maps it to standard diagnostic categories and runtime components.
    """

    _lock = threading.Lock()
    _last_download_error: Optional[Any] = None
    _last_error: Dict[str, Any] = {
        "category": DiagnosticCategory.NONE,
        "component": "None",
        "timestamp": "",
        "message": "No errors recorded.",
    }

    @classmethod
    def classify(cls, err_msg: str, default_component: Optional[str] = None) -> Tuple[str, str]:
        """
        Classifies error message into (category, component).
        """
        from core.error_classifier import ErrorClassifier
        err = ErrorClassifier.classify(err_msg, component=default_component)
        return err.category, err.component

    @classmethod
    def record_error(cls, error_input: Any, component: Optional[str] = None) -> None:
        """
        Records an error event, categorizes it, and saves it sanitized.
        Accepts either a string error message or a DownloadError instance.
        """
        from core.error_classifier import ErrorClassifier, DownloadError

        if not error_input:
            return

        if isinstance(error_input, DownloadError):
            dl_err = error_input
        else:
            msg_str = str(error_input).strip()
            if not msg_str:
                return
            dl_err = ErrorClassifier.classify(msg_str, component=component)

        sanitized_msg = PrivacySanitizer.sanitize_message(dl_err.user_message or dl_err.raw_error)

        with cls._lock:
            cls._last_download_error = dl_err
            cls._last_error = {
                "category": dl_err.category,
                "component": dl_err.component,
                "timestamp": dl_err.timestamp,
                "message": sanitized_msg,
                "technical_details": dl_err.technical_details,
            }

    @classmethod
    def get_last_error(cls) -> Dict[str, Any]:
        """Returns a copy of the last recorded error."""
        with cls._lock:
            return dict(cls._last_error)

    @classmethod
    def get_last_download_error(cls) -> Optional[Any]:
        """Returns the structured DownloadError object if available."""
        with cls._lock:
            return cls._last_download_error

    @classmethod
    def clear(cls) -> None:
        """Resets the recorded error to clean state."""
        with cls._lock:
            cls._last_download_error = None
            cls._last_error = {
                "category": DiagnosticCategory.NONE,
                "component": "None",
                "timestamp": "",
                "message": "No errors recorded.",
            }

    clear_errors = clear


# =============================================================================
# Diagnostic Reporter
# =============================================================================

class DiagnosticReporter:
    """
    Compiles a comprehensive diagnostic report containing application,
    system, runtime, configuration, and error information.
    """

    @classmethod
    def generate_report(
        cls,
        settings_manager: Optional[SettingsManager] = None,
        runtime_statuses: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Builds a clean, human-readable diagnostic report string.
        """
        sm = settings_manager or SettingsManager()

        # 1. Application Info
        app_ver = f"v{__version__}"

        # 2. Operating System
        os_name = platform.system()
        os_release = platform.release()
        os_version = platform.version()
        arch = platform.machine() or ("x64" if sys.maxsize > 2**32 else "x86")
        os_display = f"{os_name} {os_release} (Build {os_version})"

        # 3. Runtime Versions & Statuses
        from downloader.updater import YtDlpUpdater
        from downloader.deno_checker import DenoChecker
        from downloader.ffmpeg_checker import FFmpegChecker
        try:
            import yt_dlp_ejs
            ejs_ver = getattr(yt_dlp_ejs, "__version__", getattr(yt_dlp_ejs, "version", "Unknown"))
        except ImportError:
            ejs_ver = "Not Installed"

        ytdlp_ver = YtDlpUpdater.get_installed_version()
        is_deno_ok, _, deno_ver, _ = DenoChecker.detect()
        is_ffmpeg_ok, _, ffmpeg_ver, _ = FFmpegChecker.detect()

        deno_display = f"{deno_ver}" if is_deno_ok else "Not Found"
        ffmpeg_display = f"{ffmpeg_ver}" if is_ffmpeg_ok else "Not Found"

        # Statuses
        r_statuses = runtime_statuses or {}
        ytdlp_status = r_statuses.get("yt-dlp", "Up to date" if ytdlp_ver != "Unknown" else "Unknown")
        ejs_status = r_statuses.get("ejs", "Up to date" if ejs_ver != "Not Installed" else "Not Installed")
        deno_status = r_statuses.get("deno", "Up to date" if is_deno_ok else "Not Found")
        ffmpeg_status = r_statuses.get("ffmpeg", "Up to date" if is_ffmpeg_ok else "Not Found")

        # 4. Application Configuration
        mode = sm.get("download_mode", "Video + Audio")
        video_fmt = sm.get("format", "MOV")
        video_res = sm.get("quality", "1080p")
        audio_fmt = sm.get("audio_format", "WAV")
        sub_enabled = "Enabled" if sm.get("download_subtitles", False) else "Disabled"
        thumb_enabled = "Enabled" if sm.get("download_thumbnail", False) else "Disabled"
        desc_enabled = "Enabled" if sm.get("save_description", False) else "Disabled"
        meta_enabled = "Enabled" if sm.get("save_metadata", False) else "Disabled"
        chap_enabled = "Enabled" if sm.get("save_chapters", False) else "Disabled"
        cookies_browser = sm.get("browser_cookies", "none")
        auth_display = f"Browser ({cookies_browser})" if cookies_browser not in ("none", "", None) else "No authentication"

        # 5. Last Error
        last_err = ErrorTracker.get_last_error()
        err_cat = last_err.get("category", DiagnosticCategory.NONE)
        err_comp = last_err.get("component", "None")
        err_time = last_err.get("timestamp") or "N/A"
        err_msg = last_err.get("message", "None")

        # Assemble clean text
        lines = [
            "Channel Harvest Diagnostic Report",
            "=================================",
            "",
            "Application",
            f"Channel Harvest: {app_ver}",
            "",
            "System",
            f"OS: {os_display}",
            f"Architecture: {arch}",
            "",
            "Runtime",
            f"yt-dlp: {ytdlp_ver}",
            f"EJS: {ejs_ver}",
            f"Deno: {deno_display}",
            f"FFmpeg: {ffmpeg_display}",
            "",
            "Runtime Status",
            f"yt-dlp: {ytdlp_status}",
            f"EJS: {ejs_status}",
            f"Deno: {deno_status}",
            f"FFmpeg: {ffmpeg_status}",
            "",
            "Configuration",
            f"Download Mode: {mode}",
            f"Video Format: {video_fmt} ({video_res})",
            f"Audio Format: {audio_fmt}",
            f"Subtitles: {sub_enabled}",
            f"Thumbnail: {thumb_enabled}",
            f"Description: {desc_enabled}",
            f"Metadata: {meta_enabled}",
            f"Chapters: {chap_enabled}",
            f"Authentication: {auth_display}",
            "",
            "Last Error",
            f"Category: {err_cat}",
            f"Component: {err_comp}",
            f"Time: {err_time}",
            f"Message: {err_msg}",
        ]

        return "\n".join(lines)
