"""
ytdlp_engine.py
Downloader engine module encapsulating yt-dlp's Python API and background threading.

Key Features:
- Direct integration with yt-dlp via its Python API (yt_dlp.YoutubeDL).
- Fast channel and playlist metadata extraction without downloading videos.
- Single video downloading with FFmpeg audio/video merging.
- Real-time progress hook parsing (percentage, downloaded/total size, speed, ETA).
- Instantaneous cancellation support via hook exception raising.
- Windows-safe filename output template preserving Unicode and Chinese characters.
- Background scanning and downloading workers using QThread.
"""

import os
import re
import time
import socket
from pathlib import Path
from urllib.error import URLError
from typing import List, Optional, Tuple, Callable, Dict, Any
from urllib.parse import urlparse
from collections import deque

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError, YoutubeDLError
from yt_dlp.postprocessor import PostProcessor

from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode, ScanResult
from core.availability import AvailabilityDetectorRegistry, AvailabilityStatus
from core.paths import get_deno_executable, sanitize_filename, resolve_video_outtmpl, get_temp_dir, validate_output_path, calculate_safe_stem_length
from core.error_classifier import ErrorCategory
from core.diagnostics import PrivacySanitizer
from downloader.format_selector import FormatSelector
from downloader.ffmpeg_checker import FFmpegChecker


# =============================================================================
# Custom Exceptions for Clear Error Reporting
# =============================================================================

class DownloaderError(Exception):
    """Base exception for downloader errors with stage, raw error, and technical details tracking."""
    def __init__(self, message: str, stage: str = "video", raw_error: str = "", technical_details: str = ""):
        super().__init__(message)
        self.stage = stage
        self.raw_error = raw_error or message
        self.technical_details = technical_details or ""


class InvalidURLError(DownloaderError):
    """Raised when a provided URL is malformed or not a YouTube URL."""
    pass


class NetworkError(DownloaderError):
    """Raised when network connectivity fails during extraction or download."""
    pass


class EmptyChannelError(DownloaderError):
    """Raised when a scanned channel or playlist contains no public videos."""
    pass


class ExtractionError(DownloaderError):
    """Raised when yt-dlp fails to extract metadata from the target."""
    pass


class DownloadCancelledException(DownloaderError):
    """Raised inside progress hooks to cleanly abort an active download immediately."""
    pass


# =============================================================================
# Windows File-Locking Helpers
# =============================================================================

RENAME_ERROR_PATTERN = re.compile(
    r"(?:Unable to rename file:.*?)?(?:\[WinError\s*32\]|being used by another process).*?['\"]([^'\"]+)['\"]\s*->\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)


def parse_locked_rename_paths(error_msg: str) -> Optional[Tuple[Path, Path]]:
    """
    Extracts source and destination paths from a Windows file-locking rename error message.
    """
    msg = str(error_msg or "")
    m = RENAME_ERROR_PATTERN.search(msg)
    if m:
        try:
            src = Path(m.group(1).strip())
            dst = Path(m.group(2).strip())
            return src, dst
        except Exception:
            return None
    return None


def is_final_output_file(dst_path: Path, video_id: str = "", title: str = "") -> bool:
    """
    Determines if a destination path represents the final merged/output media file
    or an intermediate format stream (e.g. .f137.mp4, .f140.m4a, .f1139573745394401v.mp4, .temp.mp4).
    """
    name = dst_path.name
    if video_id:
        has_id = (f"[{video_id}]" in name) or (video_id in name)
        clean_title = sanitize_filename(title) if title else ""
        has_title = bool(clean_title and (clean_title in name or name.startswith(clean_title) or clean_title.startswith(dst_path.stem.split(" [")[0])))
        if not (has_id or has_title):
            return False
    if name.endswith(".part") or name.endswith(".ytdl") or ".temp." in name:
        return False
    # Matches numeric format IDs (YouTube/Bilibili/TikTok) as well as Facebook format IDs ending in 'v' or 'a'
    if re.search(r"\.f[a-zA-Z0-9_-]+\.[a-zA-Z0-9]+$", name):
        return False
    return True


def is_http_416_error(error_msg: str) -> bool:
    """
    Detects if an error message indicates an HTTP 416 Requested Range Not Satisfiable
    or invalid resume state.
    """
    low = str(error_msg or "").lower()
    return (
        "http error 416" in low
        or "http 416" in low
        or ("416" in low and ("range not satisfiable" in low or "range" in low))
        or "requested range not satisfiable" in low
    )


def is_http_403_error(error_msg: str) -> bool:
    """
    Detects if an error message indicates an HTTP 403 Forbidden rejection.
    """
    low = str(error_msg or "").lower()
    return (
        "http error 403" in low
        or "http 403" in low
        or ("403" in low and ("forbidden" in low or "unable to download video data" in low))
    )


def is_http_500_error(error_msg: str) -> bool:
    """
    Detects if an error message indicates an HTTP 500/502/503 server error.
    """
    low = str(error_msg or "").lower()
    return bool(
        "http error 500" in low
        or "http 500" in low
        or "500: internal server error" in low
        or "500 internal server error" in low
        or "500 server error" in low
        or "http error 502" in low
        or "http 502" in low
        or "502: bad gateway" in low
        or "502 bad gateway" in low
        or "http error 503" in low
        or "http 503" in low
        or "503: service unavailable" in low
        or "503 service unavailable" in low
        or (("500" in low or "502" in low or "503" in low) and ("server error" in low or "bad gateway" in low or "service unavailable" in low or "got error:" in low))
    )


def is_transient_retryable_error(error_msg: str) -> bool:
    """
    Detects if an error is a transient server or network error where
    partial download data should be preserved for safe resume.
    """
    low = str(error_msg or "").lower()
    return (
        is_http_500_error(low)
        or any(t in low for t in (
            "connection reset",
            "connection refused",
            "connection aborted",
            "remotedisconnected",
            "incompleteread",
            "timed out",
            "timeout",
            "network is unreachable",
            "temporary failure in name resolution",
            "broken pipe",
        ))
    )


def find_video_partial_files(target_dir: Path, video_id: str, title: str = "") -> List[Path]:
    """
    Identifies all partial (.part) or download state (.ytdl) files in target_dir
    that belong strictly to video_id.
    Guarantees no files belonging to other videos are touched.
    """
    if not target_dir.is_dir() or not video_id:
        return []

    partial_files = []
    id_bracket = f"[{video_id}]"
    clean_title = sanitize_filename(title) if title else ""

    try:
        for entry in target_dir.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if name.endswith(".part") or name.endswith(".ytdl"):
                # Strict ownership check: must match video ID or video title
                if id_bracket in name or video_id in name:
                    partial_files.append(entry)
                elif clean_title and (clean_title in name or name.startswith(clean_title) or clean_title.startswith(name.split(".")[0])):
                    partial_files.append(entry)
    except Exception:
        pass

    return partial_files


def find_completed_final_file(target_dir: Path, video_id: str, title: str = "") -> Optional[Path]:
    """
    Checks if a valid, complete final output media file already exists for video_id.
    """
    if not target_dir.is_dir() or not video_id:
        return None

    try:
        for entry in target_dir.iterdir():
            if entry.is_file() and is_final_output_file(entry, video_id, title=title):
                if entry.stat().st_size > 0:
                    return entry
    except Exception:
        pass

    return None


# =============================================================================
# yt-dlp Custom Logger Bridge
# =============================================================================

ANSI_ESCAPE_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


class YtDlpLogger:
    """
    Custom logger that routes internal yt-dlp messages into our Qt application log.
    This avoids stdout clutter and allows users to see real-time progress.
    Sanitizes terminal ANSI color and control codes before emitting to the GUI.
    Maintains an in-memory buffer of debug messages, FFmpeg command lines, and FFmpeg
    stderr output to provide comprehensive technical diagnostics on failure.
    Checks cancellation on every message to ensure immediate responsiveness.
    """

    def __init__(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self._callback = log_callback
        self._cancel_check = cancel_check
        self._recent_logs: deque = deque(maxlen=100)
        self._ffmpeg_command: str = ""
        self._ffmpeg_stderr_lines: deque = deque(maxlen=50)

    @staticmethod
    def _sanitize(msg: str) -> str:
        clean = ANSI_ESCAPE_RE.sub("", msg)
        return PrivacySanitizer.sanitize_message(clean)

    def _check_cancellation(self) -> None:
        if self._cancel_check and self._cancel_check():
            raise DownloadCancelledException("Download cancelled by user.")

    def debug(self, msg: str) -> None:
        """Called by yt-dlp for debug and step messages."""
        self._check_cancellation()
        sanitized = self._sanitize(msg)
        self._recent_logs.append(sanitized)

        # 1. Capture FFmpeg command line if present
        if "ffmpeg command line:" in sanitized:
            parts = sanitized.split("ffmpeg command line:", 1)
            self._ffmpeg_command = parts[1].strip()

        # 2. Capture FFmpeg stderr / conversion output
        if any(term in sanitized for term in (
            "Conversion failed",
            "only supported in",
            "Could not write header",
            "Stream mapping:",
            "incorrect codec parameters",
            "[mov @",
            "[mp4 @",
            "[matroska @",
            "Invalid argument",
            "Error opening input",
        )):
            self._ffmpeg_stderr_lines.append(sanitized)

        # 3. Route user-facing operational lines to GUI callback
        if any(msg.startswith(prefix) for prefix in (
            "[youtube",
            "[facebook",
            "[tiktok",
            "[bilibili",
            "[instagram",
            "[twitter",
            "[x",
            "[Extracting",
            "[info]",
            "[download]",
            "[Merger]",
            "[Fixup",
            "[ExtractAudio",
            "[VideoConvertor",
        )):
            if self._callback:
                self._callback(f"[yt-dlp] {sanitized}")

    def info(self, msg: str) -> None:
        """Called by yt-dlp for informational messages."""
        self._check_cancellation()
        sanitized = self._sanitize(msg)
        self._recent_logs.append(sanitized)
        if self._callback:
            self._callback(f"[yt-dlp] {sanitized}")

    def warning(self, msg: str) -> None:
        """Called by yt-dlp when a non-fatal warning occurs."""
        self._check_cancellation()
        sanitized = self._sanitize(msg)
        self._recent_logs.append(f"[WARNING] {sanitized}")
        if self._callback:
            self._callback(f"[yt-dlp WARNING] {sanitized}")

    def error(self, msg: str) -> None:
        """Called by yt-dlp when an error occurs."""
        self._check_cancellation()
        sanitized = self._sanitize(msg)
        self._recent_logs.append(f"[ERROR] {sanitized}")
        self._ffmpeg_stderr_lines.append(sanitized)
        if self._callback:
            self._callback(f"[yt-dlp ERROR] {sanitized}")

    def get_ffmpeg_command(self) -> str:
        """Returns the last captured sanitized FFmpeg command line."""
        return self._ffmpeg_command

    def get_ffmpeg_stderr(self) -> str:
        """Returns the captured sanitized FFmpeg stderr output lines."""
        return "\n".join(self._ffmpeg_stderr_lines)

    def get_ffmpeg_diagnostics(self) -> Dict[str, Any]:
        """Returns a consolidated dictionary of FFmpeg runtime diagnostics."""
        is_avail, ffmpeg_path, version_str, _ = FFmpegChecker.detect()
        return {
            "ffmpeg_path": ffmpeg_path or "Unknown",
            "ffmpeg_version": version_str or "Unknown",
            "ffmpeg_command": self.get_ffmpeg_command(),
            "ffmpeg_stderr": self.get_ffmpeg_stderr(),
            "recent_logs": list(self._recent_logs)[-20:],
        }


# =============================================================================
# Container Compatibility PostProcessor (MOV / Single-Pass Remux & Transcode)
# =============================================================================

class TitleSanitizerPP(PostProcessor):
    """
    Pre-process postprocessor that sanitizes and bounds video titles in yt-dlp's info_dict
    before downloading format streams or creating temporary and final files on Windows.

    Ensures:
    - No single component exceeds MAX_COMPONENT_LENGTH (255 characters), even when
      yt-dlp appends format suffixes (e.g. .f1139573745394401v), .part, and extensions.
    - Windows-illegal characters (< > : " / \\ | ? *) and control characters are sanitized.
    - Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) are de-reserved.
    - Meaningful Unicode (Chinese, Japanese, Korean, Malay, emojis, accents) is preserved.
    - The resulting filename matches resolve_media_filename exactly.
    """
    def __init__(
        self,
        downloader=None,
        target_dir: Optional[Path] = None,
        include_video_id: bool = False,
        suffix: str = "",
        target_title: Optional[str] = None,
        platform: Optional[str] = None,
        number_prefix: str = "",
    ):
        super().__init__(downloader)
        self.target_dir = target_dir
        self.include_video_id = include_video_id
        self.suffix = suffix
        self.target_title = target_title
        self.platform = (platform or "").lower()
        self.number_prefix = number_prefix or ""

    def run(self, info: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
        raw_title = info.get("title") or ""
        v_id = info.get("id", "")
        ext_key = str(info.get("extractor_key") or info.get("extractor") or "").lower()
        is_instagram = (self.platform == "instagram") or ("instagram" in ext_key)
        is_facebook = (self.platform == "facebook") or ("facebook" in ext_key)
        is_x = (self.platform in ("x", "twitter")) or ("twitter" in ext_key) or ("x" in ext_key)

        # 1. If target_title is provided (from VideoItem.title), prioritize it
        if self.target_title and self.target_title.strip():
            candidate = self.target_title.strip()
            # If target_title itself was generic ("Video by ..."), check if we can improve it via caption
            if is_instagram and candidate.lower().startswith(("video by ", "post by ")):
                from core.platform.instagram import clean_instagram_title
                caption = info.get("description") or ""
                candidate = clean_instagram_title(
                    candidate,
                    caption=caption,
                    fallback=f"Instagram Video {v_id}" if v_id else candidate,
                )
            raw_title = candidate
        else:
            # 2. No target_title provided; apply platform-specific cleaning to extractor's raw_title
            if is_facebook or "facebook" in ext_key:
                from core.platform.facebook import clean_facebook_title
                raw_title = clean_facebook_title(raw_title, fallback=f"Facebook Video {v_id}" if v_id else "Untitled")
            elif is_instagram or raw_title.lower().startswith(("video by ", "post by ")):
                from core.platform.instagram import clean_instagram_title
                caption = info.get("description") or ""
                raw_title = clean_instagram_title(
                    raw_title,
                    caption=caption,
                    fallback=f"Instagram Video {v_id}" if v_id else "Untitled",
                )
            elif is_x or "twitter" in ext_key:
                from core.platform.x import clean_x_title
                caption = info.get("description") or ""
                raw_title = clean_x_title(
                    raw_title,
                    caption=caption,
                    fallback=f"X Video {v_id}" if v_id else "Untitled",
                )

        if is_facebook:
            from core.platform.facebook import clean_facebook_title
            if clean_facebook_title(raw_title) != raw_title:
                raw_title = clean_facebook_title(raw_title, fallback=f"Facebook Video {v_id}" if v_id else "Untitled")

        reserve_extra = (len(f" [{v_id}]") if self.include_video_id else 0) + len(self.number_prefix)
        safe_len = calculate_safe_stem_length(
            target_dir=self.target_dir,
            suffix=self.suffix,
            reserve_extra=reserve_extra,
        )
        info["title"] = sanitize_filename(raw_title, max_length=safe_len)
        return [], info


class MovCompatibilityPP(PostProcessor):
    """
    Ensures media streams merged into the QuickTime MOV container (.mov)
    are strictly compatible with QuickTime and FFmpeg MOV muxer specifications.

    MOV muxer natively accepts H.264 (avc1/h264), HEVC (hev1/hvc1), ProRes, and MJPEG video,
    and AAC, ALAC, PCM, MP3 audio with stream copy (-c copy).
    Incompatible modern video codecs (AV1/av01, VP9/vp09, VP8) and audio codecs (Opus, Vorbis)
    cannot be remuxed with -c copy and must be transcoded to H.264 / AAC.

    This postprocessor runs at the 'video' stage (pre-download/merge):
    - Inspects requested_formats for video and audio codecs.
    - Preserves stream copy (-c copy) when streams are already compatible (e.g. native H.264 / AAC).
    - Injects '-c:v libx264' and/or '-c:a aac' into postprocessor_args['merger'] only when
      incompatible codecs are detected, achieving valid MOV output in a single merge pass.
    """
    def __init__(self, downloader=None, target_format: str = "mov"):
        super().__init__(downloader)
        self.target_format = (target_format or "").lower().strip()

    def run(self, info: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
        if self.target_format != "mov":
            return [], info

        req_formats = info.get("requested_formats") or [info]
        video_codec = ""
        audio_codec = ""
        for f in req_formats:
            v_c = (f.get("vcodec") or "").lower()
            a_c = (f.get("acodec") or "").lower()
            if v_c and v_c != "none":
                video_codec = v_c
            if a_c and a_c != "none":
                audio_codec = a_c

        extra_merger_args = []
        # MOV rejects AV1 and VP9/VP8 in -c copy mode
        is_video_incompat = any(x in video_codec for x in ("av01", "av1", "vp9", "vp09", "vp8"))
        if is_video_incompat:
            extra_merger_args.extend(["-c:v", "libx264"])
            if self._downloader and hasattr(self._downloader, "to_screen"):
                self._downloader.to_screen(
                    f"[Merger] Transcoding incompatible video codec ({video_codec}) to H.264 for MOV container compatibility"
                )

        # MOV rejects Opus and Vorbis in -c copy mode
        is_audio_incompat = any(x in audio_codec for x in ("opus", "vorbis"))
        if is_audio_incompat:
            extra_merger_args.extend(["-c:a", "aac"])
            if self._downloader and hasattr(self._downloader, "to_screen"):
                self._downloader.to_screen(
                    f"[Merger] Transcoding incompatible audio codec ({audio_codec}) to AAC for MOV container compatibility"
                )

        if extra_merger_args and self._downloader:
            pp_args = self._downloader.params.get("postprocessor_args")
            if pp_args is None:
                self._downloader.params["postprocessor_args"] = {}
            if isinstance(self._downloader.params["postprocessor_args"], dict):
                # Note: yt-dlp requires lowercase key 'merger'
                m_args = list(self._downloader.params["postprocessor_args"].get("merger", []))
                for a in extra_merger_args:
                    if a not in m_args:
                        m_args.append(a)
                self._downloader.params["postprocessor_args"]["merger"] = m_args
            elif isinstance(self._downloader.params["postprocessor_args"], list):
                self._downloader.params["postprocessor_args"].extend(extra_merger_args)

        return [], info


def format_ffmpeg_technical_details(
    raw_error: str,
    logger: Optional[Any] = None,
    target_format: str = "",
    info_dict: Optional[Dict[str, Any]] = None,
) -> str:
    """Formats technical diagnostic details for FFmpeg failures."""
    details = []
    if logger and hasattr(logger, "get_ffmpeg_diagnostics"):
        diag = logger.get_ffmpeg_diagnostics()
        if diag.get("ffmpeg_path"):
            details.append(f"FFmpeg Path: {diag['ffmpeg_path']}")
        if diag.get("ffmpeg_version"):
            details.append(f"FFmpeg Version: {diag['ffmpeg_version']}")
        if target_format:
            details.append(f"Target Container: {target_format.upper()}")
        if diag.get("ffmpeg_command"):
            details.append(f"FFmpeg Command: {diag['ffmpeg_command']}")
        if diag.get("ffmpeg_stderr"):
            details.append(f"FFmpeg Stderr:\n{diag['ffmpeg_stderr']}")

    if info_dict:
        req = info_dict.get("requested_formats") or [info_dict]
        stream_info = []
        for i, fmt in enumerate(req):
            vc = fmt.get("vcodec", "none")
            ac = fmt.get("acodec", "none")
            ext = fmt.get("ext", "")
            res = fmt.get("resolution") or f"{fmt.get('width', '?')}x{fmt.get('height', '?')}"
            stream_info.append(f"Stream #{i}: ext={ext}, vcodec={vc}, acodec={ac}, res={res}")
        if stream_info:
            details.append("Input Streams:\n  " + "\n  ".join(stream_info))

    if not details:
        details.append(raw_error)
    return "\n".join(details)


# =============================================================================
# Helper Formatting Functions
# =============================================================================

def format_bytes(bytes_count: Optional[float]) -> str:
    """Formats raw byte counts into human-readable strings (KB, MB, GB)."""
    if bytes_count is None or bytes_count <= 0:
        return "-- MB"
    try:
        b = float(bytes_count)
        if b >= 1024 ** 3:
            return f"{b / (1024 ** 3):.2f} GB"
        elif b >= 1024 ** 2:
            return f"{b / (1024 ** 2):.1f} MB"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB"
        else:
            return f"{b:.0f} B"
    except (ValueError, TypeError):
        return "-- MB"


def format_speed(bytes_per_sec: Optional[float]) -> str:
    """Formats download speed into human-readable MB/s or KB/s."""
    if bytes_per_sec is None or bytes_per_sec <= 0:
        return "-- MB/s"
    try:
        speed = float(bytes_per_sec)
        if speed >= 1024 ** 2:
            return f"{speed / (1024 ** 2):.1f} MB/s"
        elif speed >= 1024:
            return f"{speed / 1024:.0f} KB/s"
        else:
            return f"{speed:.0f} B/s"
    except (ValueError, TypeError):
        return "-- MB/s"


def format_eta(seconds: Optional[float]) -> str:
    """Formats estimated seconds into MM:SS or HH:MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    try:
        s = int(seconds)
        hours = s // 3600
        minutes = (s % 3600) // 60
        secs = s % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"
    except (ValueError, TypeError):
        return "--:--"


# =============================================================================
# Main yt-dlp Engine Interface
# =============================================================================

class YtDlpEngine:
    """
    High-level engine providing YouTube metadata extraction and video downloading.
    """

    @staticmethod
    def validate_url(url: str) -> Tuple[bool, str]:
        """
        Validates whether the provided string is a valid YouTube URL.

        Returns:
            Tuple of (is_valid: bool, error_reason: str)
        """
        cleaned = url.strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a YouTube channel or playlist URL."

        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = parsed.netloc.lower()
            if not any(netloc == host or netloc.endswith("." + host) for host in ("youtube.com", "youtu.be")):
                return False, f"Domain '{parsed.netloc}' is not a valid YouTube domain."

            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific channel, playlist, or video path."

            return True, ""

        except Exception as e:
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            return False, f"Malformed URL: {str(e)}"

    @staticmethod
    def normalize_channel_url(url: str) -> str:
        """
        Ensures a channel handle points to its /videos tab for optimal extraction.
        """
        cleaned = url.strip()
        if re.match(r"^https?://(www\.)?youtube\.com/@[^/]+/?$", cleaned, re.IGNORECASE):
            cleaned = cleaned.rstrip("/") + "/videos"
        return cleaned

    @staticmethod
    def format_duration(seconds: Optional[float]) -> str:
        """Converts seconds into a human-readable duration string."""
        if seconds is None:
            return "Unknown"
        try:
            total_seconds = int(seconds)
            if total_seconds < 0:
                return "Unknown"
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            secs = total_seconds % 60
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "Unknown"

    @staticmethod
    def build_base_ydl_opts(
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        quiet: bool = True,
        no_warnings: bool = True,
        platform: str = "youtube",
        auth_config: Optional[Any] = None,
        settings: Optional[Any] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Builds standard yt-dlp option dictionary configured with:
        1. Bundled Deno JavaScript runtime via js_runtimes for YouTube challenges (if YouTube).
        2. Platform-scoped authentication resolved via active platform adapter.
        3. Application logger routing to GUI activity log with cancellation checking.
        4. Safe writable per-user temporary directory.
        """
        opts: Dict[str, Any] = {
            "quiet": quiet,
            "no_warnings": no_warnings,
            "verbose": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "file_access_retries": 3,
            "extractor_retries": 3,
            "paths": {
                "temp": str(get_temp_dir()),
            },
        }
        opts["logger"] = YtDlpLogger(log_callback, cancel_check=cancel_check)

        platform_str = str(platform).lower().strip() if platform else "youtube"
        is_youtube = platform_str in ("youtube", "youtubemusic")

        # 1. Attach Deno runtime and EJS solver only for YouTube
        if is_youtube:
            deno_exe = get_deno_executable()
            if deno_exe and deno_exe.is_file():
                opts["js_runtimes"] = {
                    "deno": {"path": str(deno_exe.resolve())}
                }
            # Enable official remote components fallback for challenge solver
            opts["remote_components"] = ["ejs:github"]

        # 2. Resolve platform-scoped authentication
        resolved_auth = auth_config
        platform_name = platform_str.capitalize()

        if resolved_auth is None:
            try:
                from core.platform import PlatformRegistry
                adapter = PlatformRegistry.get_adapter(platform_str)
                if adapter:
                    platform_name = adapter.display_name
                    if settings is not None:
                        resolved_auth = adapter.get_auth_config(settings=settings)
                    elif is_youtube and (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file):
                        resolved_auth = adapter.get_auth_config(settings={"browser_cookies": browser_cookies} if browser_cookies else None)
                    else:
                        resolved_auth = adapter.get_auth_config()
            except Exception:
                pass

        if resolved_auth is None:
            if is_youtube:
                try:
                    from core.platform.youtube import YouTubeAdapter
                    resolved_auth = YouTubeAdapter().get_auth_config(settings={"browser_cookies": browser_cookies} if browser_cookies else None)
                except Exception:
                    from core.platform.auth import PlatformAuthConfig
                    resolved_auth = PlatformAuthConfig.none()
            else:
                from core.platform.auth import PlatformAuthConfig
                resolved_auth = PlatformAuthConfig.none()

        # Log platform authentication state without leaking credentials or paths
        if log_callback and resolved_auth:
            log_callback(f"[AUTH] Platform: {platform_name} | Authentication: {resolved_auth.description}")

        # Apply authentication parameters to yt-dlp options (if active and supported by platform capabilities)
        if resolved_auth and resolved_auth.is_active:
            from core.platform import PlatformRegistry
            plat_adapter = PlatformRegistry.get_adapter(platform_str)
            can_apply = True
            if plat_adapter:
                caps = plat_adapter.capabilities
                if resolved_auth.auth_method == "browser" and not caps.supports_browser_cookies:
                    can_apply = False
                elif resolved_auth.auth_method == "custom_file" and not caps.supports_cookie_file:
                    can_apply = False
            if can_apply:
                resolved_auth.apply_to_ydl_opts(opts)

        return opts

    def extract_channel_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        """
        Extracts video entries from a channel or playlist URL using yt-dlp.
        Delegates to scan_channel_entries and returns the video list.
        """
        scan_res = self.scan_channel_entries(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
        )
        return scan_res.videos

    def scan_channel_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> ScanResult:
        """
        Scans a channel or playlist URL and returns a normalized ScanResult.
        Runs fast flat extraction without downloading any media.
        """
        """
        Extracts video entries from a channel or playlist URL using yt-dlp.
        Runs fast flat extraction without downloading any media.
        """
        is_valid, reason = self.validate_url(url)
        if not is_valid:
            raise InvalidURLError(reason)

        normalized_url = self.normalize_channel_url(url)
        if log_callback:
            log_callback(f"[INFO] Connecting to: {normalized_url}")

        ydl_opts = self.build_base_ydl_opts(
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            quiet=True,
            no_warnings=True,
            platform="youtube",
            auth_config=auth_config,
        )
        if auth_config is None and custom_cookie_file and Path(custom_cookie_file).is_file():
            ydl_opts["cookiefile"] = str(Path(custom_cookie_file).resolve())

        ydl_opts.update({
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": True,
        })

        MAX_METADATA_RETRIES = 2
        info = None
        for scan_attempt in range(1, MAX_METADATA_RETRIES + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if log_callback:
                        log_callback("[INFO] Fetching metadata from YouTube...")
                    info = ydl.extract_info(normalized_url, download=False)
                break

            except UnsupportedError as e:
                raise InvalidURLError(f"URL is not supported by yt-dlp: {str(e)}") from e

            except (URLError, socket.gaierror, socket.timeout, ConnectionError) as e:
                if scan_attempt < MAX_METADATA_RETRIES:
                    if log_callback:
                        log_callback(f"[RETRY] Network issue during metadata extraction. Retrying in 1.5s ({scan_attempt}/{MAX_METADATA_RETRIES})...")
                    time.sleep(1.5)
                    continue
                raise NetworkError(f"Network error while connecting to YouTube: {str(e)}") from e

            except DownloadError as e:
                err_msg = str(e)
                if scan_attempt < MAX_METADATA_RETRIES and is_http_500_error(err_msg):
                    if log_callback:
                        log_callback(f"[RETRY] Server error (HTTP 500) during metadata extraction. Retrying in 1.5s ({scan_attempt}/{MAX_METADATA_RETRIES})...")
                    time.sleep(1.5)
                    continue
                if any(net_term in err_msg.lower() for net_term in ("unable to download", "timed out", "nodename", "connection")):
                    raise NetworkError(f"Network connection failed: {err_msg}") from e
                raise ExtractionError(f"Failed to extract channel data: {err_msg}") from e

            except ExtractorError as e:
                raise ExtractionError(f"YouTube extractor failed: {str(e)}") from e

            except Exception as e:
                raise ExtractionError(f"Unexpected error during extraction: {str(e)}") from e

        if not info:
            raise EmptyChannelError("No information could be retrieved for this channel or playlist.")

        raw_entries = info.get("entries")
        entries_list = []

        if raw_entries is not None:
            entries_list = list(raw_entries)
        elif info.get("id"):
            entries_list = [info]

        is_playlist = (
            "list=" in normalized_url.lower()
            or "/playlist" in normalized_url.lower()
            or "/browse/mpreb_" in normalized_url.lower()
            or "/album/" in normalized_url.lower()
            or info.get("_type") == "playlist"
        )
        is_single_video = raw_entries is None and bool(info.get("id")) and not is_playlist

        extracted_playlist_id = None
        if is_playlist or (info.get("id") and any(k in str(info.get("id")) for k in ("OLAK", "MPREb_", "PL", "RD"))):
            extracted_playlist_id = info.get("id")
        if not extracted_playlist_id:
            m_list = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", normalized_url)
            if m_list:
                extracted_playlist_id = m_list.group(1)
            else:
                m_browse = re.search(r"/(?:browse|album|playlist)/([a-zA-Z0-9_-]+)", normalized_url)
                if m_browse:
                    extracted_playlist_id = m_browse.group(1)

        if is_playlist:
            source_type = "playlist"
            source_title = info.get("playlist_title") or info.get("title") or info.get("channel") or info.get("uploader") or "Playlist"
        elif is_single_video:
            source_type = "video"
            source_title = info.get("channel") or info.get("uploader") or info.get("title") or "YouTube Video"
        else:
            source_type = "channel"
            source_title = info.get("channel") or info.get("uploader") or info.get("title") or "YouTube Channel"

        channel_title = source_title
        if log_callback:
            log_callback(f"[INFO] Scanned target: {channel_title}")

        if not entries_list:
            raise EmptyChannelError(
                f"No public videos found for '{channel_title}'. "
                "The channel may be empty, or contains only members-only/private content."
            )

        video_items: List[VideoItem] = []
        index_counter = 1
        detector = AvailabilityDetectorRegistry.get_detector("youtube")
        auth_active = bool(auth_config and getattr(auth_config, "is_active", False))

        for entry in entries_list:
            if not entry:
                continue

            video_id = entry.get("id") or ""
            raw_title = entry.get("title") or "Untitled Video"
            raw_duration = entry.get("duration")
            duration_str = self.format_duration(raw_duration)

            video_url = entry.get("url") or entry.get("webpage_url") or ""
            if not video_url and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

            avail = detector.detect_entry(
                entry=entry,
                video_id=video_id,
                title=raw_title,
                url=video_url,
                auth_active=auth_active,
            )

            extra_meta = {}
            if avail.is_definitively_inaccessible():
                selected = False
                if avail.status == AvailabilityStatus.PRIVATE:
                    status = "Private Video"
                    error_reason = "Private Video"
                    extra_meta["inaccessibility"] = ErrorCategory.PRIVATE_VIDEO
                else:
                    status = "Unavailable Video"
                    error_reason = "Unavailable Video"
                    extra_meta["inaccessibility"] = ErrorCategory.VIDEO_UNAVAILABLE
            else:
                selected = True
                status = VideoStatus.READY
                error_reason = ""

            if extracted_playlist_id:
                extra_meta["playlist_id"] = extracted_playlist_id

            album_cand = entry.get("album") or info.get("album")
            if not album_cand and extracted_playlist_id and any(extracted_playlist_id.startswith(p) for p in ("OLAK", "MPREb_")):
                album_cand = info.get("playlist_title") or info.get("title")
                if album_cand and str(album_cand).lower().startswith("album - "):
                    album_cand = str(album_cand)[8:].strip()
            if album_cand:
                extra_meta["album"] = str(album_cand).strip()

            item = VideoItem(
                index=index_counter,
                video_id=video_id,
                title=raw_title,
                duration=duration_str,
                duration_seconds=int(raw_duration) if isinstance(raw_duration, (int, float)) else None,
                status=status,
                url=video_url,
                selected=selected,
                channel_title=channel_title,
                error_reason=error_reason,
                platform="youtube",
                extra_metadata=extra_meta,
                availability=avail,
            )
            video_items.append(item)
            index_counter += 1

        if not video_items:
            raise EmptyChannelError("All videos found in this channel are private or unavailable.")

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} video(s).")

        scan_extra_meta = {}
        if extracted_playlist_id:
            scan_extra_meta["playlist_id"] = extracted_playlist_id
        if info.get("thumbnails"):
            scan_extra_meta["playlist_thumbnails"] = info.get("thumbnails")

        return ScanResult(
            videos=video_items,
            source_title=source_title,
            source_type=source_type,
            platform="youtube",
            url=url,
            extra_metadata=scan_extra_meta,
        )
    @staticmethod
    def _create_progress_hook(
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        cancel_check: Optional[Callable[[], bool]],
        scale_start: float = 0.0,
        scale_factor: float = 1.0,
        step_label: str = "",
    ) -> Callable[[Dict[str, Any]], None]:
        def ytdlp_progress_hook(d: Dict[str, Any]) -> None:
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")

            status = d.get("status")
            if status == "downloading":
                downloaded_bytes = d.get("downloaded_bytes") or 0
                total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

                raw_percent = 0.0
                if total_bytes > 0:
                    raw_percent = min(100.0, (downloaded_bytes / total_bytes) * 100.0)

                # Scale download up to 90% of current slice so post-processing has dedicated progress headroom
                scaled_percent = scale_start + (raw_percent * 0.90 * scale_factor)

                speed_str = format_speed(d.get("speed"))
                eta_str = format_eta(d.get("eta"))
                downloaded_str = format_bytes(downloaded_bytes)
                total_str = format_bytes(total_bytes) if total_bytes > 0 else "-- MB"

                if progress_callback:
                    progress_callback({
                        "status": "downloading",
                        "percent": scaled_percent,
                        "downloaded_str": downloaded_str,
                        "total_str": total_str,
                        "speed": speed_str,
                        "eta": eta_str,
                        "step": step_label,
                    })

            elif status == "finished":
                if progress_callback:
                    progress_callback({
                        "status": "processing",
                        "percent": scale_start + (92.0 * scale_factor),
                        "downloaded_str": format_bytes(d.get("downloaded_bytes")),
                        "total_str": format_bytes(d.get("total_bytes")),
                        "speed": "-- MB/s",
                        "eta": "00:00",
                        "step": step_label,
                    })

        return ytdlp_progress_hook

    @staticmethod
    def _create_postprocessor_hook(
        cancel_check: Optional[Callable[[], bool]],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        scale_start: float = 0.0,
        scale_factor: float = 1.0,
        step_label: str = "",
    ) -> Callable[[Dict[str, Any]], None]:
        def ytdlp_postprocessor_hook(d: Dict[str, Any]) -> None:
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")
            status = d.get("status")
            if not progress_callback:
                return

            pp_name = d.get("postprocessor", "")
            op_map = {
                "Merger": "Merging streams",
                "VideoConvertor": "Converting video",
                "ExtractAudio": "Extracting audio",
                "FFmpegMetadata": "Writing metadata",
                "FixupM3u8": "Fixing stream container",
                "FixupMP4": "Fixing MP4 container",
                "MoveFiles": "Finalizing file",
            }
            op_label = op_map.get(pp_name, pp_name or "Processing")

            if status == "started":
                progress_callback({
                    "status": "processing",
                    "percent": scale_start + (92.0 * scale_factor),
                    "downloaded_str": "-- MB",
                    "total_str": "-- MB",
                    "speed": f"FFmpeg ({op_label})",
                    "eta": "--:--",
                    "step": step_label or "Processing",
                    "postprocessor": pp_name,
                    "operation": op_label,
                })
            elif status == "finished":
                progress_callback({
                    "status": "processing",
                    "percent": scale_start + (98.0 * scale_factor),
                    "downloaded_str": "-- MB",
                    "total_str": "-- MB",
                    "speed": f"FFmpeg ({op_label})",
                    "eta": "00:00",
                    "step": step_label or "Processing",
                    "postprocessor": pp_name,
                    "operation": op_label,
                })
        return ytdlp_postprocessor_hook

    @staticmethod
    def safe_finalize_rename(
        src_path: Path,
        dst_path: Path,
        raw_error: str = "",
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Safely attempts to finalize/rename a downloaded file that was temporarily locked
        by Windows (WinError 32 / sharing violation).

        Applies bounded exponential backoff:
        Attempt 1: ~1s
        Attempt 2: ~2s
        Attempt 3: ~4s
        Attempt 4: ~8s
        Attempt 5: ~10s
        Max 5 attempts. No infinite loops.
        """
        delays = [1.0, 2.0, 4.0, 8.0, 10.0]

        # 1. If destination already exists, is complete (>0 bytes), and src is gone or equal/larger, already finalized!
        try:
            if dst_path.is_file() and dst_path.stat().st_size > 0:
                if not src_path.exists():
                    if log_callback:
                        log_callback("[File Finalization] File rename successful after retry.")
                    return True
                elif dst_path.stat().st_size >= src_path.stat().st_size:
                    try:
                        src_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if log_callback:
                        log_callback("[File Finalization] File rename successful after retry.")
                    return True
        except Exception:
            pass

        # 2. Verify source file exists
        if not src_path.is_file():
            return False

        # 3. Verify file size is stable (>0 and not actively changing)
        try:
            size_1 = src_path.stat().st_size
            if size_1 <= 0:
                return False
            time.sleep(0.1)
            size_2 = src_path.stat().st_size
            if size_1 != size_2:
                # Still actively being written by another process; abort rename to prevent corruption
                return False
        except Exception:
            return False

        # 4. Perform bounded backoff retries (1 to 5)
        for attempt, delay in enumerate(delays, start=1):
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")

            delay_unit = "second" if delay == 1.0 else "seconds"
            delay_num = int(delay) if delay.is_integer() else delay

            if log_callback:
                log_callback(f"[File Finalization] Windows file lock detected. Retrying rename in {delay_num} {delay_unit}...")
                log_callback(f"[File Finalization] Retry {attempt}/5...")

            # Responsive cancellable sleep
            elapsed = 0.0
            while elapsed < delay:
                if cancel_check and cancel_check():
                    raise DownloadCancelledException("Download cancelled by user.")
                sleep_slice = min(0.1, delay - elapsed)
                time.sleep(sleep_slice)
                elapsed += sleep_slice

            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")

            # Check if destination exists and is valid
            try:
                if dst_path.is_file() and dst_path.stat().st_size >= src_path.stat().st_size and dst_path.stat().st_size > 0:
                    try:
                        src_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if log_callback:
                        log_callback("[File Finalization] File rename successful after retry.")
                    return True
            except Exception:
                pass

            # Try renaming with os.replace
            try:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src_path, dst_path)
                if dst_path.is_file() and dst_path.stat().st_size > 0:
                    if log_callback:
                        log_callback("[File Finalization] File rename successful after retry.")
                    return True
            except OSError:
                # Still locked by Windows process, continue to next backoff attempt
                pass

        # If all 5 attempts exhausted:
        if log_callback:
            log_callback("[File Finalization] Unable to finalize file after 5 attempts. Error Category: FILE_LOCKED")
        return False

    @classmethod
    def recover_from_range_error(
        cls,
        video: VideoItem,
        target_dir: Path,
        recovery_attempt: int,
        max_recovery_attempts: int = 2,
        format_spec: str = "",
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Any:
        """
        Safely handles HTTP 416 (Requested Range Not Satisfiable) recovery:
        1. Logs concise detection messages.
        2. Checks whether a valid completed final file already exists (preserves it if so).
        3. Waits briefly to confirm subprocess/file handle release.
        4. Identifies and removes ONLY the partial .part / .ytdl files belonging to this video.
        5. Logs diagnostic information (without exposing sensitive tokens or URLs).
        6. Prepares for a genuinely fresh download without resume (continuedl=False).

        Returns:
            True if partial state was safely reset and a fresh download should proceed.
            'ALREADY_COMPLETE' if a valid final file exists and no download is needed.
            False if recovery cannot be performed.
        """
        if cancel_check and cancel_check():
            raise DownloadCancelledException("Download cancelled by user.")

        if log_callback:
            log_callback(f"[Download] HTTP 416 detected for video {video.video_id}")
            log_callback("[Download] Partial resume state appears invalid")

        # 1. Check whether a valid completed final file already exists
        completed_file = find_completed_final_file(target_dir, video.video_id, title=video.title)
        if completed_file:
            if log_callback:
                log_callback(f"[Download] Valid completed final file already exists: {completed_file.name}. Preserving file.")
            # Clean up any leftover stale .part files
            for p in find_video_partial_files(target_dir, video.video_id, title=video.title):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
            return "ALREADY_COMPLETE"

        if log_callback:
            log_callback("[Download] Waiting for download process to terminate")

        # 2. Brief grace period to ensure previous subprocess/handles are fully flushed
        time.sleep(0.2)

        if cancel_check and cancel_check():
            raise DownloadCancelledException("Download cancelled by user.")

        # 3. Locate partial files belonging strictly to this video
        part_files = find_video_partial_files(target_dir, video.video_id, title=video.title)

        # 4. Record sanitized diagnostic information
        part_exists_str = "yes" if part_files else "no"
        part_sizes_str = ", ".join(f"{p.name}: {p.stat().st_size} bytes" for p in part_files if p.is_file()) if part_files else "N/A"
        if log_callback:
            log_callback(
                f"[Download Diagnostics] .part exists: {part_exists_str} ({part_sizes_str}) | "
                f"final file exists: no | video ID: {video.video_id} | "
                f"format: {format_spec or 'default'} | output: {target_dir.name}"
            )

        # 5. Safely reset the partial files
        for p in part_files:
            try:
                # Ensure the path is within the target directory
                if not p.resolve().is_relative_to(target_dir.resolve()):
                    continue
                # Ensure file is accessible and not actively locked
                if p.is_file():
                    try:
                        with open(p, "r+b"):
                            pass
                    except OSError:
                        time.sleep(0.3)
                    p.unlink(missing_ok=True)
                    if log_callback:
                        log_callback(f"[Download] Removing stale partial file: {p.name}")
            except Exception as ex:
                if log_callback:
                    log_callback(f"[Download] Warning: Could not remove {p.name}: {ex}")

        if log_callback:
            log_callback("[Download] Starting fresh download without resume")
            log_callback(f"[Download] HTTP 416 recovery attempt {recovery_attempt}/{max_recovery_attempts}")

        return True

    @classmethod
    def safe_cleanup_partial_files(cls, target_dir: Path, video_id: str, title: str = "") -> None:
        """
        Safely removes any partial (.part, .ytdl) files strictly belonging to video_id in target_dir.
        Never touches completed final output files or files of other videos.
        """
        if not target_dir.is_dir() or not video_id:
            return
        partial_files = find_video_partial_files(target_dir, video_id, title=title)
        for pf in partial_files:
            try:
                if not pf.resolve().is_relative_to(target_dir.resolve()):
                    continue
                if pf.is_file():
                    pf.unlink(missing_ok=True)
            except Exception:
                pass

    @classmethod
    def recover_from_http_403(
        cls,
        video: VideoItem,
        target_dir: Path,
        recovery_attempt: int,
        max_recovery_attempts: int = 1,
        format_spec: str = "",
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Any:
        """
        Safely attempts recovery from an HTTP 403 (Forbidden) stream rejection:
        1. Checks whether a valid completed final file already exists (preserves it if so).
        2. Safely removes any stale partial .part or .ytdl files belonging to this video only.
        3. Logs diagnostic message without exposing tokens or signed URLs.
        4. Authorizes a bounded single fresh retry without resume and without cached tokens.
        """
        if cancel_check and cancel_check():
            raise DownloadCancelledException("Download cancelled by user.")

        if log_callback:
            log_callback(f"[Download] HTTP 403 Forbidden detected for video {video.video_id}")

        completed_file = find_completed_final_file(target_dir, video.video_id, title=video.title)
        if completed_file:
            if log_callback:
                log_callback(f"[Download] Valid completed final file already exists: {completed_file.name}. Preserving file.")
            cls.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
            return "ALREADY_COMPLETE"

        # Safely clean up partial files for this video
        cls.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)

        if recovery_attempt > max_recovery_attempts:
            if log_callback:
                log_callback(
                    f"[Download] HTTP 403 recovery limit reached ({recovery_attempt}/{max_recovery_attempts}). "
                    "Error Category: HTTP_403"
                )
            return False

        if log_callback:
            log_callback(f"[Download] Refreshing stream URLs and attempting safe recovery ({recovery_attempt}/{max_recovery_attempts})...")

        return True

    def download_single_video(
        self,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        archive_file: Optional[Path] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Downloads a single video or audio file using yt-dlp's Python API according to settings.download_mode:
        - Video Only: Downloads complete playable video file with merged audio (1 file).
        - Audio Only: Downloads standalone audio track (1 file).
        - Video + Audio: Downloads both complete video file and standalone audio track (2 files).

        Returns:
            Dict with {'success': bool, 'skipped': bool}
        """
        # 0. Immediate cancellation check
        if cancel_check and cancel_check():
            raise DownloadCancelledException("Download cancelled by user.")

        # 1. Check download archive if skip_existing is enabled
        platform_prefix = getattr(video, "platform", "youtube").lower()
        if settings.skip_existing and archive_file and archive_file.exists():
            try:
                with open(archive_file, "r", encoding="utf-8") as f:
                    archive_content = f.read()
                    if f"{platform_prefix} {video.video_id}" in archive_content or f"youtube {video.video_id}" in archive_content or video.video_id in archive_content:
                        if log_callback:
                            log_callback(f"[ARCHIVE] Video {video.video_id} already in archive. Skipping download.")
                        return {"success": True, "skipped": True}
            except Exception as e:
                if log_callback:
                    log_callback(f"[WARNING] Could not read download archive: {e}")

        if video.url:
            video_url = video.url
        elif platform_prefix == "tiktok":
            video_url = f"https://www.tiktok.com/@tiktok/video/{video.video_id}"
        elif platform_prefix == "bilibili":
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter("bilibili")
            video_url = adapter.build_video_url(video.video_id) if adapter else f"https://www.bilibili.com/video/{video.video_id}"
        elif platform_prefix == "facebook":
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter("facebook")
            video_url = adapter.build_video_url(video.video_id) if adapter else f"https://www.facebook.com/watch/?v={video.video_id}"
        elif platform_prefix == "instagram":
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter("instagram")
            video_url = adapter.build_video_url(video.video_id) if adapter else f"https://www.instagram.com/p/{video.video_id}/"
        elif platform_prefix in ("x", "twitter"):
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter("x")
            video_url = adapter.build_video_url(video.video_id, original_url=video.url) if adapter else (video.url or f"https://x.com/i/status/{video.video_id}")
        else:
            video_url = f"https://www.youtube.com/watch?v={video.video_id}"
        # Pre-download path validation
        is_valid, val_err = validate_output_path(target_dir)
        if not is_valid:
            if log_callback:
                log_callback(f"[ERROR] Pre-download path validation failed: {val_err}")
            raise DownloaderError(
                f"Path validation failed: {val_err}",
                stage="path_validation",
                raw_error=val_err or "Invalid output path",
            )

        mode = settings.download_mode or DownloadMode.VIDEO_ONLY

        # 2. Mode: Video Only (complete video with audio merged)
        num_prefix = getattr(settings, "number_prefix", "")
        if mode == DownloadMode.VIDEO_ONLY:
            format_spec, merge_ext = FormatSelector.build_video_format_spec(settings)
            outtmpl_pattern = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, number_prefix=num_prefix)
            hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="",
            )

            pp_hook = self._create_postprocessor_hook(
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="Video",
            )
            ydl_opts: Dict[str, Any] = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
                platform=platform_prefix,
                settings=settings,
                cancel_check=cancel_check,
            )
            ydl_opts.pop("paths", None)
            ydl_opts.update({
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [hook],
                "postprocessor_hooks": [pp_hook],
            })
            pp_args = FormatSelector.get_audio_postprocessor_args(settings)
            if pp_args:
                if "postprocessor_args" in ydl_opts and isinstance(ydl_opts["postprocessor_args"], dict):
                    ydl_opts["postprocessor_args"].update(pp_args)
                else:
                    ydl_opts["postprocessor_args"] = pp_args
            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location
            if settings.skip_existing and archive_file:
                ydl_opts["download_archive"] = str(archive_file)

            if log_callback:
                log_callback(f"[ENGINE] Video Only: Downloading {video.title} -> container .{merge_ext}")

            finalization_retries = 0
            MAX_FINALIZATION_RECOVERIES = 3
            range_416_recoveries = 0
            MAX_416_RECOVERIES = 2
            http_403_recoveries = 0
            MAX_403_RECOVERIES = 1

            while True:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.add_post_processor(
                            TitleSanitizerPP(
                                downloader=ydl,
                                target_dir=target_dir,
                                include_video_id=settings.include_video_id_in_filename,
                                target_title=video.title,
                                platform=platform_prefix,
                                number_prefix=num_prefix,
                            ),
                            when="pre_process",
                        )
                        if merge_ext == "mov":
                            ydl.add_post_processor(MovCompatibilityPP(downloader=ydl, target_format="mov"), when="video")
                        info_dict = ydl.extract_info(video_url, download=True)
                    return {"success": True, "skipped": False, "info_dict": info_dict}
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
                    if cancel_check and cancel_check():
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_msg = str(e)
                    if "already been recorded in the archive" in err_msg:
                        return {"success": True, "skipped": True, "info_dict": None}
                    paths = parse_locked_rename_paths(err_msg)
                    if paths and finalization_retries < MAX_FINALIZATION_RECOVERIES:
                        src_path, dst_path = paths
                        finalization_retries += 1
                        rename_ok = self.safe_finalize_rename(
                            src_path=src_path,
                            dst_path=dst_path,
                            raw_error=err_msg,
                            log_callback=log_callback,
                            cancel_check=cancel_check,
                        )
                        if rename_ok:
                            if is_final_output_file(dst_path, video.video_id, title=video.title):
                                if log_callback:
                                    log_callback(f"[SUCCESS] Download completed and finalized: {dst_path.name}")
                                if settings.skip_existing and archive_file:
                                    try:
                                        archive_file.parent.mkdir(parents=True, exist_ok=True)
                                        with open(archive_file, "a", encoding="utf-8") as f:
                                            f.write(f"{platform_prefix} {video.video_id}\n")
                                    except Exception:
                                        pass
                                return {"success": True, "skipped": False, "info_dict": None}
                            continue

                    if is_http_416_error(err_msg):
                        if range_416_recoveries < MAX_416_RECOVERIES:
                            range_416_recoveries += 1
                            rec_status = self.recover_from_range_error(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=range_416_recoveries,
                                max_recovery_attempts=MAX_416_RECOVERIES,
                                format_spec=format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                return {"success": True, "skipped": True, "info_dict": None}
                            elif rec_status:
                                ydl_opts["continuedl"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 416 recovery limit reached ({range_416_recoveries}/{MAX_416_RECOVERIES}). "
                                "Error Category: RANGE_NOT_SATISFIABLE"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp video download failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    if is_http_403_error(err_msg):
                        if http_403_recoveries < MAX_403_RECOVERIES:
                            http_403_recoveries += 1
                            rec_status = self.recover_from_http_403(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=http_403_recoveries,
                                max_recovery_attempts=MAX_403_RECOVERIES,
                                format_spec=format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                return {"success": True, "skipped": True, "info_dict": None}
                            elif rec_status:
                                ydl_opts["continuedl"] = False
                                ydl_opts["cachedir"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 403 recovery limit reached ({http_403_recoveries}/{MAX_403_RECOVERIES}). "
                                "Error Category: HTTP_403"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp video download failed: {err_msg}",
                            stage="video",
                            raw_error=err_msg,
                        ) from e

                    if is_transient_retryable_error(err_msg):
                        stage = "video"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_msg}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp video download failed: {err_msg}", stage=stage, raw_error=err_msg) from e

                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    is_ffmpeg_fail = any(t in err_msg.lower() for t in ("postprocessing:", "conversion failed", "ffmpeg", "muxing"))
                    if is_ffmpeg_fail:
                        stage = "conversion"
                        tech_details = format_ffmpeg_technical_details(err_msg, logger=ydl_opts.get("logger"), target_format=merge_ext)
                    else:
                        stage = "File Finalization" if paths else "video"
                        tech_details = err_msg
                    raise DownloaderError(f"yt-dlp video download failed: {err_msg}", stage=stage, raw_error=err_msg, technical_details=tech_details) from e
                except Exception as e:
                    if (cancel_check and cancel_check()) or isinstance(e, DownloadCancelledException):
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_str = str(e)
                    if is_transient_retryable_error(err_str):
                        stage = "video"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_str}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp video download failed: {err_str}", stage=stage, raw_error=err_str) from e
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    is_ffmpeg_fail = ("ffmpeg" in err_str.lower() or "postprocessing" in err_str.lower() or "conversion" in err_str.lower())
                    stage = "conversion" if is_ffmpeg_fail else "video"
                    tech_details = format_ffmpeg_technical_details(err_str, logger=ydl_opts.get("logger"), target_format=merge_ext) if is_ffmpeg_fail else err_str
                    raise DownloaderError(f"Unexpected video download error: {str(e)}", stage=stage, raw_error=str(e), technical_details=tech_details) from e

        # 3. Mode: Audio Only (standalone audio track)
        elif mode == DownloadMode.AUDIO_ONLY:
            format_spec, audio_ext, postprocessors = FormatSelector.build_audio_format_spec(settings)
            outtmpl_pattern = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, number_prefix=num_prefix)
            hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="",
            )

            pp_hook = self._create_postprocessor_hook(
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="Audio",
            )
            ydl_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
                platform=platform_prefix,
                settings=settings,
                cancel_check=cancel_check,
            )
            ydl_opts.pop("paths", None)
            ydl_opts.update({
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "postprocessors": postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [hook],
                "postprocessor_hooks": [pp_hook],
            })
            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location
            if settings.skip_existing and archive_file:
                ydl_opts["download_archive"] = str(archive_file)

            pp_args = FormatSelector.get_audio_postprocessor_args(settings)
            if pp_args:
                if "postprocessor_args" in ydl_opts and isinstance(ydl_opts["postprocessor_args"], dict):
                    ydl_opts["postprocessor_args"].update(pp_args)
                else:
                    ydl_opts["postprocessor_args"] = pp_args

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if (settings.audio_format or "").upper() == "MP3" and (not settings.audio_bitrate or settings.audio_bitrate == "Best Available"):
                bitrate_info = " (Best Available - 320 kbps)"
            if log_callback:
                log_callback(f"[ENGINE] Audio Only: Extracting {video.title} -> {settings.audio_format}{bitrate_info}")

            finalization_retries = 0
            MAX_FINALIZATION_RECOVERIES = 3
            range_416_recoveries = 0
            MAX_416_RECOVERIES = 2
            http_403_recoveries = 0
            MAX_403_RECOVERIES = 1

            while True:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.add_post_processor(
                            TitleSanitizerPP(
                                downloader=ydl,
                                target_dir=target_dir,
                                include_video_id=settings.include_video_id_in_filename,
                                target_title=video.title,
                                platform=platform_prefix,
                                number_prefix=num_prefix,
                            ),
                            when="pre_process",
                        )
                        info_dict = ydl.extract_info(video_url, download=True)
                    return {"success": True, "skipped": False, "info_dict": info_dict}
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
                    if cancel_check and cancel_check():
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_msg = str(e)
                    if "already been recorded in the archive" in err_msg:
                        return {"success": True, "skipped": True, "info_dict": None}
                    paths = parse_locked_rename_paths(err_msg)
                    if paths and finalization_retries < MAX_FINALIZATION_RECOVERIES:
                        src_path, dst_path = paths
                        finalization_retries += 1
                        rename_ok = self.safe_finalize_rename(
                            src_path=src_path,
                            dst_path=dst_path,
                            raw_error=err_msg,
                            log_callback=log_callback,
                            cancel_check=cancel_check,
                        )
                        if rename_ok:
                            if is_final_output_file(dst_path, video.video_id, title=video.title):
                                if log_callback:
                                    log_callback(f"[SUCCESS] Audio download completed and finalized: {dst_path.name}")
                                if settings.skip_existing and archive_file:
                                    try:
                                        archive_file.parent.mkdir(parents=True, exist_ok=True)
                                        with open(archive_file, "a", encoding="utf-8") as f:
                                            f.write(f"{platform_prefix} {video.video_id}\n")
                                    except Exception:
                                        pass
                                return {"success": True, "skipped": False, "info_dict": None}
                            continue

                    if is_http_416_error(err_msg):
                        if range_416_recoveries < MAX_416_RECOVERIES:
                            range_416_recoveries += 1
                            rec_status = self.recover_from_range_error(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=range_416_recoveries,
                                max_recovery_attempts=MAX_416_RECOVERIES,
                                format_spec=format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                return {"success": True, "skipped": True, "info_dict": None}
                            elif rec_status:
                                ydl_opts["continuedl"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 416 recovery limit reached ({range_416_recoveries}/{MAX_416_RECOVERIES}). "
                                "Error Category: RANGE_NOT_SATISFIABLE"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp audio download failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    if is_http_403_error(err_msg):
                        if http_403_recoveries < MAX_403_RECOVERIES:
                            http_403_recoveries += 1
                            rec_status = self.recover_from_http_403(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=http_403_recoveries,
                                max_recovery_attempts=MAX_403_RECOVERIES,
                                format_spec=format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                return {"success": True, "skipped": True, "info_dict": None}
                            elif rec_status:
                                ydl_opts["continuedl"] = False
                                ydl_opts["cachedir"] = False
                                if "format_id!=251" not in ydl_opts.get("format", ""):
                                    ydl_opts["format"] = "ba[ext=m4a]/ba[format_id!=251]/ba/b"
                                    if log_callback:
                                        log_callback("[Download] Retrying with alternative audio stream format")
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 403 recovery limit reached ({http_403_recoveries}/{MAX_403_RECOVERIES}). "
                                "Error Category: HTTP_403"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp audio download failed: {err_msg}",
                            stage="audio",
                            raw_error=err_msg,
                        ) from e

                    if is_transient_retryable_error(err_msg):
                        stage = "audio"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_msg}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp audio download failed: {err_msg}", stage=stage, raw_error=err_msg) from e

                    stage = "File Finalization" if paths else "audio"
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    raise DownloaderError(f"yt-dlp audio download failed: {err_msg}", stage=stage, raw_error=err_msg) from e
                except Exception as e:
                    if (cancel_check and cancel_check()) or isinstance(e, DownloadCancelledException):
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_str = str(e)
                    if is_transient_retryable_error(err_str):
                        stage = "audio"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_str}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp audio download failed: {err_str}", stage=stage, raw_error=err_str) from e
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    stage = "conversion" if ("ffmpeg" in str(e).lower() or "postprocessing" in str(e).lower()) else "audio"
                    raise DownloaderError(f"Unexpected audio download error: {str(e)}", stage=stage, raw_error=str(e)) from e

        # 4. Mode: Video + Audio (both files downloaded for each item)
        else:
            v_format_spec, merge_ext = FormatSelector.build_video_format_spec(settings)
            a_format_spec, audio_ext, a_postprocessors = FormatSelector.build_audio_format_spec(settings)

            # Prevent file overwrite collision if video and audio share the same extension
            if merge_ext.lower() == audio_ext.lower():
                v_suffix = "_video"
                a_suffix = "_audio"
                v_outtmpl = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, suffix=v_suffix, number_prefix=num_prefix)
                a_outtmpl = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, suffix=a_suffix, number_prefix=num_prefix)
            else:
                v_suffix = ""
                a_suffix = ""
                v_outtmpl = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, number_prefix=num_prefix)
                a_outtmpl = resolve_video_outtmpl(target_dir, include_video_id=settings.include_video_id_in_filename, number_prefix=num_prefix)

            # Step 1: Video download
            v_hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=0.5,
                step_label="Video",
            )
            v_pp_hook = self._create_postprocessor_hook(
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                scale_start=0.0,
                scale_factor=0.5,
                step_label="Video",
            )
            v_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
                platform=platform_prefix,
                settings=settings,
                cancel_check=cancel_check,
            )
            v_opts.pop("paths", None)
            v_opts.update({
                "format": v_format_spec,
                "outtmpl": v_outtmpl,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [v_hook],
                "postprocessor_hooks": [v_pp_hook],
            })
            if ffmpeg_location:
                v_opts["ffmpeg_location"] = ffmpeg_location

            if log_callback:
                log_callback(f"[ENGINE] Video + Audio [1/2]: Downloading video for {video.title} (.{merge_ext})")

            info_dict = None
            v_finalization_retries = 0
            MAX_FINALIZATION_RECOVERIES = 3
            v_range_416_recoveries = 0
            MAX_416_RECOVERIES = 2
            v_http_403_recoveries = 0
            MAX_403_RECOVERIES = 1

            while True:
                try:
                    with yt_dlp.YoutubeDL(v_opts) as ydl:
                        ydl.add_post_processor(
                            TitleSanitizerPP(
                                downloader=ydl,
                                target_dir=target_dir,
                                include_video_id=settings.include_video_id_in_filename,
                                suffix=v_suffix,
                                target_title=video.title,
                                platform=platform_prefix,
                                number_prefix=num_prefix,
                            ),
                            when="pre_process",
                        )
                        if merge_ext == "mov":
                            ydl.add_post_processor(MovCompatibilityPP(downloader=ydl, target_format="mov"), when="video")
                        info_dict = ydl.extract_info(video_url, download=True)
                    break
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
                    if cancel_check and cancel_check():
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_msg = str(e)
                    if "already been recorded in the archive" in err_msg:
                        return {"success": True, "skipped": True, "info_dict": None}
                    paths = parse_locked_rename_paths(err_msg)
                    if paths and v_finalization_retries < MAX_FINALIZATION_RECOVERIES:
                        src_path, dst_path = paths
                        v_finalization_retries += 1
                        rename_ok = self.safe_finalize_rename(
                            src_path=src_path,
                            dst_path=dst_path,
                            raw_error=err_msg,
                            log_callback=log_callback,
                            cancel_check=cancel_check,
                        )
                        if rename_ok:
                            if is_final_output_file(dst_path, video.video_id, title=video.title):
                                break
                            continue

                    if is_http_416_error(err_msg):
                        if v_range_416_recoveries < MAX_416_RECOVERIES:
                            v_range_416_recoveries += 1
                            rec_status = self.recover_from_range_error(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=v_range_416_recoveries,
                                max_recovery_attempts=MAX_416_RECOVERIES,
                                format_spec=v_format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                break
                            elif rec_status:
                                v_opts["continuedl"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 416 recovery limit reached ({v_range_416_recoveries}/{MAX_416_RECOVERIES}). "
                                "Error Category: RANGE_NOT_SATISFIABLE"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp video pass failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    if is_http_403_error(err_msg):
                        if v_http_403_recoveries < MAX_403_RECOVERIES:
                            v_http_403_recoveries += 1
                            rec_status = self.recover_from_http_403(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=v_http_403_recoveries,
                                max_recovery_attempts=MAX_403_RECOVERIES,
                                format_spec=v_format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                break
                            elif rec_status:
                                v_opts["continuedl"] = False
                                v_opts["cachedir"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 403 recovery limit reached ({v_http_403_recoveries}/{MAX_403_RECOVERIES}). "
                                "Error Category: HTTP_403"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp video pass failed: {err_msg}",
                            stage="video",
                            raw_error=err_msg,
                        ) from e

                    if is_transient_retryable_error(err_msg):
                        stage = "video"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_msg}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp video pass failed: {err_msg}", stage=stage, raw_error=err_msg) from e

                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    is_ffmpeg_fail = any(t in err_msg.lower() for t in ("postprocessing:", "conversion failed", "ffmpeg", "muxing"))
                    if is_ffmpeg_fail:
                        stage = "conversion"
                        tech_details = format_ffmpeg_technical_details(err_msg, logger=v_opts.get("logger"), target_format=merge_ext)
                    else:
                        stage = "File Finalization" if paths else "video"
                        tech_details = err_msg
                    raise DownloaderError(f"yt-dlp video pass failed: {err_msg}", stage=stage, raw_error=err_msg, technical_details=tech_details) from e
                except Exception as e:
                    if (cancel_check and cancel_check()) or isinstance(e, DownloadCancelledException):
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_str = str(e)
                    if is_transient_retryable_error(err_str):
                        stage = "video"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_str}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp video pass failed: {err_str}", stage=stage, raw_error=err_str) from e
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    is_ffmpeg_fail = ("ffmpeg" in err_str.lower() or "postprocessing" in err_str.lower() or "conversion" in err_str.lower())
                    stage = "conversion" if is_ffmpeg_fail else "video"
                    tech_details = format_ffmpeg_technical_details(err_str, logger=v_opts.get("logger"), target_format=merge_ext) if is_ffmpeg_fail else err_str
                    raise DownloaderError(f"Unexpected error in video pass: {err_str}", stage=stage, raw_error=err_str, technical_details=tech_details) from e

            # Cancellation check between passes
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")

            # Step 2: Audio extraction (reuses info_dict to avoid duplicate YouTube extraction)
            a_hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=50.0,
                scale_factor=0.5,
                step_label="Audio",
            )
            a_pp_hook = self._create_postprocessor_hook(
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                scale_start=50.0,
                scale_factor=0.5,
                step_label="Audio",
            )
            a_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
                platform=platform_prefix,
                settings=settings,
                cancel_check=cancel_check,
            )
            a_opts.pop("paths", None)
            a_opts.update({
                "format": a_format_spec,
                "outtmpl": a_outtmpl,
                "postprocessors": a_postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [a_hook],
                "postprocessor_hooks": [a_pp_hook],
            })
            a_pp_args = FormatSelector.get_audio_postprocessor_args(settings)
            if a_pp_args:
                if "postprocessor_args" in a_opts and isinstance(a_opts["postprocessor_args"], dict):
                    a_opts["postprocessor_args"].update(a_pp_args)
                else:
                    a_opts["postprocessor_args"] = a_pp_args
            if ffmpeg_location:
                a_opts["ffmpeg_location"] = ffmpeg_location

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if audio_ext.lower() == "mp3" and (not settings.audio_bitrate or settings.audio_bitrate == "Best Available"):
                bitrate_info = " (Best Available - 320 kbps)"
            if log_callback:
                log_callback(f"[ENGINE] Video + Audio [2/2]: Extracting audio for {video.title} (.{audio_ext}{bitrate_info})")

            a_finalization_retries = 0
            a_range_416_recoveries = 0
            a_http_403_recoveries = 0
            while True:
                try:
                    with yt_dlp.YoutubeDL(a_opts) as ydl:
                        ydl.add_post_processor(
                            TitleSanitizerPP(
                                downloader=ydl,
                                target_dir=target_dir,
                                include_video_id=settings.include_video_id_in_filename,
                                suffix=a_suffix,
                                target_title=video.title,
                                platform=platform_prefix,
                                number_prefix=num_prefix,
                            ),
                            when="pre_process",
                        )
                        ydl.download([video_url])
                    break
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
                    if cancel_check and cancel_check():
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_msg = str(e)
                    paths = parse_locked_rename_paths(err_msg)
                    if paths and a_finalization_retries < MAX_FINALIZATION_RECOVERIES:
                        src_path, dst_path = paths
                        a_finalization_retries += 1
                        rename_ok = self.safe_finalize_rename(
                            src_path=src_path,
                            dst_path=dst_path,
                            raw_error=err_msg,
                            log_callback=log_callback,
                            cancel_check=cancel_check,
                        )
                        if rename_ok:
                            if is_final_output_file(dst_path, video.video_id, title=video.title):
                                break
                            continue

                    if is_http_416_error(err_msg):
                        if a_range_416_recoveries < MAX_416_RECOVERIES:
                            a_range_416_recoveries += 1
                            rec_status = self.recover_from_range_error(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=a_range_416_recoveries,
                                max_recovery_attempts=MAX_416_RECOVERIES,
                                format_spec=a_format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                break
                            elif rec_status:
                                a_opts["continuedl"] = False
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 416 recovery limit reached ({a_range_416_recoveries}/{MAX_416_RECOVERIES}). "
                                "Error Category: RANGE_NOT_SATISFIABLE"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp audio pass failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    if is_http_403_error(err_msg):
                        if a_http_403_recoveries < MAX_403_RECOVERIES:
                            a_http_403_recoveries += 1
                            rec_status = self.recover_from_http_403(
                                video=video,
                                target_dir=target_dir,
                                recovery_attempt=a_http_403_recoveries,
                                max_recovery_attempts=MAX_403_RECOVERIES,
                                format_spec=a_format_spec,
                                log_callback=log_callback,
                                cancel_check=cancel_check,
                            )
                            if rec_status == "ALREADY_COMPLETE":
                                break
                            elif rec_status:
                                a_opts["continuedl"] = False
                                a_opts["cachedir"] = False
                                if "format_id!=251" not in a_opts.get("format", ""):
                                    a_opts["format"] = "ba[ext=m4a]/ba[format_id!=251]/ba/b"
                                    if log_callback:
                                        log_callback("[Download] Retrying with alternative audio stream format")
                                continue
                        if log_callback:
                            log_callback(
                                f"[Download] HTTP 403 recovery limit reached ({a_http_403_recoveries}/{MAX_403_RECOVERIES}). "
                                "Error Category: HTTP_403"
                            )
                        self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                        raise DownloaderError(
                            f"yt-dlp audio pass failed: {err_msg}",
                            stage="audio",
                            raw_error=err_msg,
                        ) from e

                    if is_transient_retryable_error(err_msg):
                        stage = "audio"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_msg}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp audio pass failed: {err_msg}", stage=stage, raw_error=err_msg) from e

                    stage = "File Finalization" if paths else "audio"
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    raise DownloaderError(f"yt-dlp audio pass failed: {err_msg}", stage=stage, raw_error=err_msg) from e
                except Exception as e:
                    if (cancel_check and cancel_check()) or isinstance(e, DownloadCancelledException):
                        raise DownloadCancelledException("Download cancelled by user.") from e
                    err_str = str(e)
                    if is_transient_retryable_error(err_str):
                        stage = "audio"
                        if log_callback:
                            log_callback(f"[Download] Transient error ({err_str}). Preserving partial download for resume.")
                        raise DownloaderError(f"yt-dlp audio pass failed: {err_str}", stage=stage, raw_error=err_str) from e
                    self.safe_cleanup_partial_files(target_dir, video.video_id, title=video.title)
                    stage = "conversion" if ("ffmpeg" in str(e).lower() or "postprocessing" in str(e).lower()) else "audio"
                    raise DownloaderError(f"Unexpected error in audio pass: {str(e)}", stage=stage, raw_error=str(e)) from e

            # Both passes succeeded: record to archive if enabled
            if settings.skip_existing and archive_file:
                try:
                    archive_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(archive_file, "a", encoding="utf-8") as f:
                        f.write(f"{platform_prefix} {video.video_id}\n")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[WARNING] Could not append to archive: {e}")

            return {"success": True, "skipped": False, "info_dict": info_dict}


# =============================================================================
# QThread Worker for Responsive Background Scanning
# =============================================================================

class ChannelScanWorker(QThread):
    """
    Worker thread that runs yt-dlp extraction in the background so that
    the PySide6 GUI never freezes or displays "(Not Responding)".
    """

    scan_started = Signal()
    log_message = Signal(str)
    channel_info = Signal(str, int)
    scan_completed = Signal(object)
    scan_error = Signal(str)
    scan_finished = Signal()

    def __init__(
        self,
        url: str,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        platform_id: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.url = url
        self.browser_cookies = browser_cookies
        self.custom_cookie_file = custom_cookie_file
        self.auth_config = auth_config
        self.platform_id = platform_id
        self.scan_id = 0
        self._is_cancelled = False
        self.engine = YtDlpEngine()

    def cancel(self) -> None:
        """Flags the worker as cancelled and terminates underlying scanning subprocesses."""
        self._is_cancelled = True
        try:
            from downloader.download_manager import kill_child_processes
            kill_child_processes()
        except Exception:
            pass
        try:
            from downloader.gallerydl_engine import GalleryDlEngine
            GalleryDlEngine.terminate_all_processes()
        except Exception:
            pass

    def run(self) -> None:
        """Runs extraction off the main thread using platform adapter."""
        self.scan_started.emit()
        self.log_message.emit(f"[INFO] Starting background scan for: {self.url}")

        try:
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter_for_url(self.url)
            if not adapter and self.platform_id:
                adapter = PlatformRegistry.get_adapter(self.platform_id)

            if adapter and not PlatformRegistry.is_available(adapter.platform_id):
                from core.error_classifier import ErrorClassifier
                err = ErrorClassifier.for_unavailable_platform(adapter.platform_id)
                self.log_message.emit(f"[BLOCKED] {err.title}: {err.user_message}")
                self.scan_error.emit(f"[PLATFORM_TEMPORARILY_UNAVAILABLE] {err.user_message}")
                return

            if adapter:
                cookies_to_pass = self.browser_cookies if (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file) else None
                if getattr(adapter.capabilities, "supports_profile_media_archive", False):
                    from downloader.gallerydl_engine import GalleryDlEngine
                    is_archive_url = False
                    if adapter.platform_id == "instagram":
                        m_prof = getattr(adapter, "_PROFILE_PATTERN", None)
                        if m_prof and m_prof.search(self.url):
                            is_archive_url = True
                    elif adapter.platform_id == "facebook":
                        low_url = self.url.lower()
                        if "photo" in low_url or "set=a." in low_url or "/photos" in low_url or "/media/set" in low_url:
                            is_archive_url = True
                        elif not any(k in low_url for k in ("/watch", "/reel", "/videos/", "video.php", "fb.watch", "/share/v", "/share/r")):
                            is_archive_url = True

                    if is_archive_url and GalleryDlEngine.is_available():
                        from downloader.profile_scan_manager import ProfileScanManager
                        manager = ProfileScanManager()
                        scan_res = manager.scan_profile(
                            url=self.url,
                            platform=adapter.platform_id,
                            custom_cookie_file=self.custom_cookie_file,
                            auth_config=self.auth_config,
                            log_callback=self.log_message.emit,
                            is_cancelled=lambda: getattr(self, "_is_cancelled", False),
                        )
                    else:
                        scan_res = adapter.scan(
                            url=self.url,
                            log_callback=self.log_message.emit,
                            browser_cookies=cookies_to_pass,
                            custom_cookie_file=self.custom_cookie_file,
                            auth_config=self.auth_config,
                        )
                else:
                    scan_res = adapter.scan(
                        url=self.url,
                        log_callback=self.log_message.emit,
                        browser_cookies=cookies_to_pass,
                        custom_cookie_file=self.custom_cookie_file,
                        auth_config=self.auth_config,
                    )
            else:
                scan_res = self.engine.scan_channel_entries(
                    url=self.url,
                    log_callback=self.log_message.emit,
                    browser_cookies=self.browser_cookies,
                    custom_cookie_file=self.custom_cookie_file,
                    auth_config=self.auth_config,
                )
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            self.channel_info.emit(scan_res.source_title, len(scan_res.videos))
            self.scan_completed.emit(scan_res)

        except InvalidURLError as e:
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            self.log_message.emit(f"[ERROR] Invalid URL: {str(e)}")
            self.scan_error.emit(f"Invalid URL:\n{str(e)}")

        except NetworkError as e:
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            self.log_message.emit(f"[ERROR] Network failure: {str(e)}")
            self.scan_error.emit(
                f"Network Error:\nCould not connect to service. Please check your internet connection.\n{str(e)}"
            )

        except EmptyChannelError as e:
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            self.log_message.emit(f"[WARNING] {str(e)}")
            self.scan_error.emit(f"Empty Channel / User:\n{str(e)}")

        except ExtractionError as e:
            if self._is_cancelled:
                self.log_message.emit("[INFO] Scan cancelled by user.")
                return
            self.log_message.emit(f"[ERROR] Extraction failed: {str(e)}")
            self.scan_error.emit(f"Extraction Error:\n{str(e)}")

        except Exception as e:
            self.log_message.emit(f"[ERROR] Unexpected error: {str(e)}")
            self.scan_error.emit(f"An unexpected error occurred:\n{str(e)}")

        finally:
            self.scan_finished.emit()