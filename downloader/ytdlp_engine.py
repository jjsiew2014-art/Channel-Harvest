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

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError, YoutubeDLError

from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.paths import get_deno_executable
from downloader.format_selector import FormatSelector


# =============================================================================
# Custom Exceptions for Clear Error Reporting
# =============================================================================

class DownloaderError(Exception):
    """Base exception for downloader errors with stage and raw error tracking."""
    def __init__(self, message: str, stage: str = "video", raw_error: str = ""):
        super().__init__(message)
        self.stage = stage
        self.raw_error = raw_error or message


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


def is_final_output_file(dst_path: Path, video_id: str = "") -> bool:
    """
    Determines if a destination path represents the final merged/output media file
    or an intermediate format stream (e.g. .f137.mp4, .f140.m4a, .temp.mp4).
    """
    name = dst_path.name
    if video_id and f"[{video_id}]" not in name and video_id not in name:
        return False
    if name.endswith(".part") or name.endswith(".ytdl") or ".temp." in name:
        return False
    if re.search(r"\.f\d+\.[a-zA-Z0-9]+$", name):
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


def find_video_partial_files(target_dir: Path, video_id: str) -> List[Path]:
    """
    Identifies all partial (.part) or download state (.ytdl) files in target_dir
    that belong strictly to video_id.
    Guarantees no files belonging to other videos are touched.
    """
    if not target_dir.is_dir() or not video_id:
        return []

    partial_files = []
    id_bracket = f"[{video_id}]"

    try:
        for entry in target_dir.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if name.endswith(".part") or name.endswith(".ytdl"):
                # Strict ownership check: must match video ID
                if id_bracket in name or video_id in name:
                    partial_files.append(entry)
    except Exception:
        pass

    return partial_files


def find_completed_final_file(target_dir: Path, video_id: str) -> Optional[Path]:
    """
    Checks if a valid, complete final output media file already exists for video_id.
    """
    if not target_dir.is_dir() or not video_id:
        return None

    try:
        for entry in target_dir.iterdir():
            if entry.is_file() and is_final_output_file(entry, video_id):
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
    """

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self._callback = log_callback

    @staticmethod
    def _sanitize(msg: str) -> str:
        return ANSI_ESCAPE_RE.sub("", msg)

    def debug(self, msg: str) -> None:
        """Called by yt-dlp for debug and step messages."""
        if any(msg.startswith(prefix) for prefix in ("[youtube", "[Extracting", "[info]", "[download]", "[Merger]", "[Fixup")):
            if self._callback:
                self._callback(self._sanitize(f"[yt-dlp] {msg}"))

    def info(self, msg: str) -> None:
        """Called by yt-dlp for informational messages."""
        if self._callback:
            self._callback(self._sanitize(f"[yt-dlp] {msg}"))

    def warning(self, msg: str) -> None:
        """Called by yt-dlp when a non-fatal warning occurs."""
        if self._callback:
            self._callback(self._sanitize(f"[yt-dlp WARNING] {msg}"))

    def error(self, msg: str) -> None:
        """Called by yt-dlp when an error occurs."""
        if self._callback:
            self._callback(self._sanitize(f"[yt-dlp ERROR] {msg}"))


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
    ) -> Dict[str, Any]:
        """
        Builds standard yt-dlp option dictionary configured with:
        1. Bundled Deno JavaScript runtime via js_runtimes for solving YouTube challenges.
        2. Optional browser cookie extraction when configured by the user.
        3. Application logger routing to GUI activity log.
        """
        opts: Dict[str, Any] = {
            "quiet": quiet,
            "no_warnings": no_warnings,
        }
        if log_callback:
            opts["logger"] = YtDlpLogger(log_callback)

        # 1. Attach Deno runtime if available
        deno_exe = get_deno_executable()
        if deno_exe and deno_exe.is_file():
            opts["js_runtimes"] = {
                "deno": {"path": str(deno_exe.resolve())}
            }
        # Enable official remote components fallback for challenge solver
        opts["remote_components"] = ["ejs:github"]

        # 2. Attach browser cookies or cookie file if explicitly configured
        cookie_browser = browser_cookies
        auth_method = None
        browser_profile = None
        try:
            from core.settings import SettingsManager
            sm = SettingsManager()
            auth_method = sm.get("auth_method", None)
            browser_profile = sm.get("browser_profile", "Default")
            if not cookie_browser:
                cookie_browser = sm.get("browser_cookies", "none")
        except Exception:
            if not cookie_browser:
                cookie_browser = "none"

        # If auth_method is explicitly "none", never attach cookies
        if auth_method == "none" and (not browser_cookies or browser_cookies == "none"):
            return opts

        if cookie_browser and str(cookie_browser).lower().strip() not in ("none", "", "null", "false"):
            raw_target = str(cookie_browser).strip()
            if raw_target.lower() == "custom_file" or auth_method == "custom_file":
                try:
                    from core.settings import SettingsManager
                    cookie_path_str = SettingsManager().get("custom_cookie_file", "")
                    if cookie_path_str and Path(cookie_path_str).is_file():
                        opts["cookiefile"] = str(Path(cookie_path_str).resolve())
                except Exception:
                    pass
            elif Path(raw_target).is_file():
                opts["cookiefile"] = str(Path(raw_target).resolve())
            else:
                browser_clean = raw_target.lower()
                prof = browser_profile if browser_profile and browser_profile.lower() != "default" else None
                opts["cookiesfrombrowser"] = (browser_clean, prof, None, None)

        return opts

    def extract_channel_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
    ) -> List[VideoItem]:
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
        )
        ydl_opts.update({
            "extract_flat": "in_playlist",
            "skip_download": True,
            "ignoreerrors": True,
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if log_callback:
                    log_callback("[INFO] Fetching metadata from YouTube...")
                info = ydl.extract_info(normalized_url, download=False)

        except UnsupportedError as e:
            raise InvalidURLError(f"URL is not supported by yt-dlp: {str(e)}") from e

        except (URLError, socket.gaierror, socket.timeout, ConnectionError) as e:
            raise NetworkError(f"Network error while connecting to YouTube: {str(e)}") from e

        except DownloadError as e:
            err_msg = str(e)
            if any(net_term in err_msg.lower() for net_term in ("unable to download", "timed out", "nodename", "connection")):
                raise NetworkError(f"Network connection failed: {err_msg}") from e
            raise ExtractionError(f"Failed to extract channel data: {err_msg}") from e

        except ExtractorError as e:
            raise ExtractionError(f"YouTube extractor failed: {str(e)}") from e

        except Exception as e:
            raise ExtractionError(f"Unexpected error during extraction: {str(e)}") from e

        if not info:
            raise EmptyChannelError("No information could be retrieved for this channel or playlist.")

        channel_title = info.get("title") or info.get("channel") or info.get("uploader") or "Channel / Playlist"
        if log_callback:
            log_callback(f"[INFO] Scanned target: {channel_title}")

        raw_entries = info.get("entries")
        entries_list = []

        if raw_entries is not None:
            entries_list = list(raw_entries)
        elif info.get("id"):
            entries_list = [info]

        if not entries_list:
            raise EmptyChannelError(
                f"No public videos found for '{channel_title}'. "
                "The channel may be empty, or contains only members-only/private content."
            )

        video_items: List[VideoItem] = []
        index_counter = 1

        for entry in entries_list:
            if not entry:
                continue

            video_id = entry.get("id") or ""
            raw_title = entry.get("title") or "Untitled Video"

            if raw_title in ("[Private video]", "[Deleted video]"):
                status = "Private / Unavailable"
                selected = False
            else:
                status = VideoStatus.READY
                selected = True

            raw_duration = entry.get("duration")
            duration_str = self.format_duration(raw_duration)

            video_url = entry.get("url") or entry.get("webpage_url") or ""
            if not video_url and video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"

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
            )
            video_items.append(item)
            index_counter += 1

        if not video_items:
            raise EmptyChannelError("All videos found in this channel are private or unavailable.")

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} video(s).")

        return video_items
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

                scaled_percent = scale_start + (raw_percent * scale_factor)

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
                        "percent": scale_start + (100.0 * scale_factor),
                        "downloaded_str": format_bytes(d.get("downloaded_bytes")),
                        "total_str": format_bytes(d.get("total_bytes")),
                        "speed": "-- MB/s",
                        "eta": "00:00",
                        "step": step_label,
                    })

        return ytdlp_progress_hook

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
        completed_file = find_completed_final_file(target_dir, video.video_id)
        if completed_file:
            if log_callback:
                log_callback(f"[Download] Valid completed final file already exists: {completed_file.name}. Preserving file.")
            # Clean up any leftover stale .part files
            for p in find_video_partial_files(target_dir, video.video_id):
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
        part_files = find_video_partial_files(target_dir, video.video_id)

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
        if settings.skip_existing and archive_file and archive_file.exists():
            try:
                with open(archive_file, "r", encoding="utf-8") as f:
                    archive_content = f.read()
                    if f"youtube {video.video_id}" in archive_content or video.video_id in archive_content:
                        if log_callback:
                            log_callback(f"[ARCHIVE] Video {video.video_id} already in archive. Skipping download.")
                        return {"success": True, "skipped": True}
            except Exception as e:
                if log_callback:
                    log_callback(f"[WARNING] Could not read download archive: {e}")

        video_url = video.url if video.url else f"https://www.youtube.com/watch?v={video.video_id}"
        mode = settings.download_mode or DownloadMode.VIDEO_AND_AUDIO

        # 2. Mode: Video Only (complete video with audio merged)
        if mode == DownloadMode.VIDEO_ONLY:
            format_spec, merge_ext = FormatSelector.build_video_format_spec(settings)
            outtmpl_pattern = str(target_dir / "%(title)s [%(id)s].%(ext)s")
            hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="",
            )

            ydl_opts: Dict[str, Any] = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
            )
            ydl_opts.update({
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [hook],
            })
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

            while True:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info_dict = ydl.extract_info(video_url, download=True)
                    return {"success": True, "skipped": False, "info_dict": info_dict}
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
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
                            if is_final_output_file(dst_path, video.video_id):
                                if log_callback:
                                    log_callback(f"[SUCCESS] Download completed and finalized: {dst_path.name}")
                                if settings.skip_existing and archive_file:
                                    try:
                                        archive_file.parent.mkdir(parents=True, exist_ok=True)
                                        with open(archive_file, "a", encoding="utf-8") as f:
                                            f.write(f"youtube {video.video_id}\n")
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
                        raise DownloaderError(
                            f"yt-dlp video download failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    stage = "File Finalization" if paths else "video"
                    raise DownloaderError(f"yt-dlp video download failed: {err_msg}", stage=stage, raw_error=err_msg) from e
                except Exception as e:
                    raise DownloaderError(f"Unexpected video download error: {str(e)}", stage="video", raw_error=str(e)) from e

        # 3. Mode: Audio Only (standalone audio track)
        elif mode == DownloadMode.AUDIO_ONLY:
            format_spec, audio_ext, postprocessors = FormatSelector.build_audio_format_spec(settings)
            outtmpl_pattern = str(target_dir / "%(title)s [%(id)s].%(ext)s")
            hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=1.0,
                step_label="",
            )

            ydl_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
            )
            ydl_opts.update({
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "postprocessors": postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [hook],
            })
            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location
            if settings.skip_existing and archive_file:
                ydl_opts["download_archive"] = str(archive_file)

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if log_callback:
                log_callback(f"[ENGINE] Audio Only: Extracting {video.title} -> {settings.audio_format}{bitrate_info}")

            finalization_retries = 0
            MAX_FINALIZATION_RECOVERIES = 3
            range_416_recoveries = 0
            MAX_416_RECOVERIES = 2

            while True:
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info_dict = ydl.extract_info(video_url, download=True)
                    return {"success": True, "skipped": False, "info_dict": info_dict}
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
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
                            if is_final_output_file(dst_path, video.video_id):
                                if log_callback:
                                    log_callback(f"[SUCCESS] Audio download completed and finalized: {dst_path.name}")
                                if settings.skip_existing and archive_file:
                                    try:
                                        archive_file.parent.mkdir(parents=True, exist_ok=True)
                                        with open(archive_file, "a", encoding="utf-8") as f:
                                            f.write(f"youtube {video.video_id}\n")
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
                        raise DownloaderError(
                            f"yt-dlp audio download failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    stage = "File Finalization" if paths else "audio"
                    raise DownloaderError(f"yt-dlp audio download failed: {err_msg}", stage=stage, raw_error=err_msg) from e
                except Exception as e:
                    raise DownloaderError(f"Unexpected audio download error: {str(e)}", stage="audio", raw_error=str(e)) from e

        # 4. Mode: Video + Audio (both files downloaded for each item)
        else:
            v_format_spec, merge_ext = FormatSelector.build_video_format_spec(settings)
            a_format_spec, audio_ext, a_postprocessors = FormatSelector.build_audio_format_spec(settings)

            # Prevent file overwrite collision if video and audio share the same extension
            if merge_ext.lower() == audio_ext.lower():
                v_outtmpl = str(target_dir / "%(title)s [%(id)s]_video.%(ext)s")
                a_outtmpl = str(target_dir / "%(title)s [%(id)s]_audio.%(ext)s")
            else:
                v_outtmpl = str(target_dir / "%(title)s [%(id)s].%(ext)s")
                a_outtmpl = str(target_dir / "%(title)s [%(id)s].%(ext)s")

            # Step 1: Video download
            v_hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=0.0,
                scale_factor=0.5,
                step_label="Video",
            )
            v_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
            )
            v_opts.update({
                "format": v_format_spec,
                "outtmpl": v_outtmpl,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [v_hook],
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

            while True:
                try:
                    with yt_dlp.YoutubeDL(v_opts) as ydl:
                        info_dict = ydl.extract_info(video_url, download=True)
                    break
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
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
                            if is_final_output_file(dst_path, video.video_id):
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
                        raise DownloaderError(
                            f"yt-dlp video pass failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    stage = "File Finalization" if paths else "video"
                    raise DownloaderError(f"yt-dlp video pass failed: {str(e)}", stage=stage, raw_error=str(e)) from e
                except Exception as e:
                    raise DownloaderError(f"Unexpected error in video pass: {str(e)}", stage="video", raw_error=str(e)) from e

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
            a_opts = self.build_base_ydl_opts(
                log_callback=log_callback,
                browser_cookies=settings.browser_cookies,
            )
            a_opts.update({
                "format": a_format_spec,
                "outtmpl": a_outtmpl,
                "postprocessors": a_postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "progress_hooks": [a_hook],
            })
            if ffmpeg_location:
                a_opts["ffmpeg_location"] = ffmpeg_location

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if log_callback:
                log_callback(f"[ENGINE] Video + Audio [2/2]: Extracting audio for {video.title} (.{audio_ext}{bitrate_info})")

            a_finalization_retries = 0
            a_range_416_recoveries = 0
            while True:
                try:
                    with yt_dlp.YoutubeDL(a_opts) as ydl:
                        ydl.download([video_url])
                    break
                except DownloadCancelledException:
                    raise
                except DownloadError as e:
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
                            if is_final_output_file(dst_path, video.video_id):
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
                        raise DownloaderError(
                            f"yt-dlp audio pass failed: {err_msg}",
                            stage="Video Download / Resume",
                            raw_error=err_msg,
                        ) from e

                    stage = "File Finalization" if paths else "audio"
                    raise DownloaderError(f"yt-dlp audio pass failed: {str(e)}", stage=stage, raw_error=str(e)) from e
                except Exception as e:
                    raise DownloaderError(f"Unexpected error in audio pass: {str(e)}", stage="audio", raw_error=str(e)) from e

            # Both passes succeeded: record to archive if enabled
            if settings.skip_existing and archive_file:
                try:
                    archive_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(archive_file, "a", encoding="utf-8") as f:
                        f.write(f"youtube {video.video_id}\n")
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
    scan_completed = Signal(list)
    scan_error = Signal(str)
    scan_finished = Signal()

    def __init__(self, url: str, browser_cookies: Optional[str] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.url = url
        self.browser_cookies = browser_cookies
        self.engine = YtDlpEngine()

    def run(self) -> None:
        """Runs yt-dlp extraction off the main thread."""
        self.scan_started.emit()
        self.log_message.emit(f"[INFO] Starting background scan for: {self.url}")

        try:
            videos = self.engine.extract_channel_entries(
                url=self.url,
                log_callback=self.log_message.emit,
                browser_cookies=self.browser_cookies,
            )
            self.scan_completed.emit(videos)

        except InvalidURLError as e:
            self.log_message.emit(f"[ERROR] Invalid URL: {str(e)}")
            self.scan_error.emit(f"Invalid URL:\n{str(e)}")

        except NetworkError as e:
            self.log_message.emit(f"[ERROR] Network failure: {str(e)}")
            self.scan_error.emit(
                "Network Error:\nCould not reach YouTube. Please check your internet connection."
            )

        except EmptyChannelError as e:
            self.log_message.emit(f"[WARNING] {str(e)}")
            self.scan_error.emit(f"Empty Channel:\n{str(e)}")

        except ExtractionError as e:
            self.log_message.emit(f"[ERROR] Extraction failed: {str(e)}")
            self.scan_error.emit(f"Extraction Error:\n{str(e)}")

        except Exception as e:
            self.log_message.emit(f"[ERROR] Unexpected error: {str(e)}")
            self.scan_error.emit(f"An unexpected error occurred:\n{str(e)}")

        finally:
            self.scan_finished.emit()
