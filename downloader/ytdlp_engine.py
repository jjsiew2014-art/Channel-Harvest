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
import socket
from pathlib import Path
from urllib.error import URLError
from typing import List, Optional, Tuple, Callable, Dict, Any
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError, YoutubeDLError

from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from downloader.format_selector import FormatSelector


# =============================================================================
# Custom Exceptions for Clear Error Reporting
# =============================================================================

class DownloaderError(Exception):
    """Base exception for downloader errors."""
    pass


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
# yt-dlp Custom Logger Bridge
# =============================================================================

class YtDlpLogger:
    """
    Custom logger that routes internal yt-dlp messages into our Qt application log.
    This avoids stdout clutter and allows users to see real-time progress.
    """

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self._callback = log_callback

    def debug(self, msg: str) -> None:
        """Called by yt-dlp for debug and step messages."""
        if any(msg.startswith(prefix) for prefix in ("[youtube", "[Extracting", "[info]", "[download]", "[Merger]", "[Fixup")):
            if self._callback:
                self._callback(f"[yt-dlp] {msg}")

    def info(self, msg: str) -> None:
        """Called by yt-dlp for informational messages."""
        if self._callback:
            self._callback(f"[yt-dlp] {msg}")

    def warning(self, msg: str) -> None:
        """Called by yt-dlp when a non-fatal warning occurs."""
        if self._callback:
            self._callback(f"[yt-dlp WARNING] {msg}")

    def error(self, msg: str) -> None:
        """Called by yt-dlp when an error occurs."""
        if self._callback:
            self._callback(f"[yt-dlp ERROR] {msg}")


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

    def extract_channel_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
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

        ydl_opts = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "logger": YtDlpLogger(log_callback),
        }

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

            ydl_opts: Dict[str, Any] = {
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpLogger(log_callback),
                "progress_hooks": [hook],
            }
            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location
            if settings.skip_existing and archive_file:
                ydl_opts["download_archive"] = str(archive_file)

            if log_callback:
                log_callback(f"[ENGINE] Video Only: Downloading {video.title} -> container .{merge_ext}")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                return {"success": True, "skipped": False}
            except DownloadCancelledException:
                raise
            except DownloadError as e:
                err_msg = str(e)
                if "already been recorded in the archive" in err_msg:
                    return {"success": True, "skipped": True}
                raise DownloaderError(f"yt-dlp video download failed: {err_msg}") from e
            except Exception as e:
                raise DownloaderError(f"Unexpected video download error: {str(e)}") from e

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

            ydl_opts = {
                "format": format_spec,
                "outtmpl": outtmpl_pattern,
                "postprocessors": postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpLogger(log_callback),
                "progress_hooks": [hook],
            }
            if ffmpeg_location:
                ydl_opts["ffmpeg_location"] = ffmpeg_location
            if settings.skip_existing and archive_file:
                ydl_opts["download_archive"] = str(archive_file)

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if log_callback:
                log_callback(f"[ENGINE] Audio Only: Extracting {video.title} -> {settings.audio_format}{bitrate_info}")

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                return {"success": True, "skipped": False}
            except DownloadCancelledException:
                raise
            except DownloadError as e:
                err_msg = str(e)
                if "already been recorded in the archive" in err_msg:
                    return {"success": True, "skipped": True}
                raise DownloaderError(f"yt-dlp audio download failed: {err_msg}") from e
            except Exception as e:
                raise DownloaderError(f"Unexpected audio download error: {str(e)}") from e

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
            v_opts = {
                "format": v_format_spec,
                "outtmpl": v_outtmpl,
                "merge_output_format": merge_ext,
                "windowsfilenames": True,
                "continuedl": True,
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpLogger(log_callback),
                "progress_hooks": [v_hook],
            }
            if ffmpeg_location:
                v_opts["ffmpeg_location"] = ffmpeg_location

            if log_callback:
                log_callback(f"[ENGINE] Video + Audio [1/2]: Downloading video for {video.title} (.{merge_ext})")

            try:
                with yt_dlp.YoutubeDL(v_opts) as ydl:
                    ydl.download([video_url])
            except DownloadCancelledException:
                raise
            except DownloadError as e:
                raise DownloaderError(f"yt-dlp video pass failed: {str(e)}") from e
            except Exception as e:
                raise DownloaderError(f"Unexpected error in video pass: {str(e)}") from e

            # Cancellation check between passes
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")

            # Step 2: Audio extraction
            a_hook = self._create_progress_hook(
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                scale_start=50.0,
                scale_factor=0.5,
                step_label="Audio",
            )
            a_opts = {
                "format": a_format_spec,
                "outtmpl": a_outtmpl,
                "postprocessors": a_postprocessors,
                "windowsfilenames": True,
                "continuedl": True,
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpLogger(log_callback),
                "progress_hooks": [a_hook],
            }
            if ffmpeg_location:
                a_opts["ffmpeg_location"] = ffmpeg_location

            bitrate_info = f" ({settings.audio_bitrate})" if settings.audio_bitrate else ""
            if log_callback:
                log_callback(f"[ENGINE] Video + Audio [2/2]: Extracting audio for {video.title} (.{audio_ext}{bitrate_info})")

            try:
                with yt_dlp.YoutubeDL(a_opts) as ydl:
                    ydl.download([video_url])
            except DownloadCancelledException:
                raise
            except DownloadError as e:
                raise DownloaderError(f"yt-dlp audio pass failed: {str(e)}") from e
            except Exception as e:
                raise DownloaderError(f"Unexpected error in audio pass: {str(e)}") from e

            # Both passes succeeded: record to archive if enabled
            if settings.skip_existing and archive_file:
                try:
                    archive_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(archive_file, "a", encoding="utf-8") as f:
                        f.write(f"youtube {video.video_id}\n")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[WARNING] Could not append to archive: {e}")

            return {"success": True, "skipped": False}


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

    def __init__(self, url: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.url = url
        self.engine = YtDlpEngine()

    def run(self) -> None:
        """Runs yt-dlp extraction off the main thread."""
        self.scan_started.emit()
        self.log_message.emit(f"[INFO] Starting background scan for: {self.url}")

        try:
            videos = self.engine.extract_channel_entries(
                url=self.url,
                log_callback=self.log_message.emit,
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
