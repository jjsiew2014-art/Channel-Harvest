"""
download_manager.py
Multi-threaded download manager and queue coordinator for Channel Harvest.

Coordinates sequential video downloads in a dedicated QThread:
- Maintains download queue states (Waiting, Downloading, Processing, Completed, Skipped, Failed, Cancelled)
- Automatic retries (up to 3 attempts with status 'Retry X/3')
- Immediate non-blocking cancellation and pause/resume coordination
- FFmpeg detection and archive integration to prevent duplicate downloads
- Real-time progress signals (speed, ETA, downloaded size, percentage, overall queue)
"""

import re
import time
import threading
from pathlib import Path
from dataclasses import replace
from typing import List, Optional, Dict, Any

from PySide6.QtCore import QThread, Signal, QObject

from collections import Counter
from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode, SubtitleSource, MediaType
from core.paths import (
    get_archive_file,
    resolve_video_output_dir,
    resolve_media_filename,
    format_number_prefix,
    sanitize_filename,
    sanitize_path_component,
    should_include_video_id,
    ensure_safe_environment,
    cleanup_temp_dir,
)
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
)
from downloader.ffmpeg_checker import FFmpegChecker
from downloader.subtitle_manager import SubtitleManager
from downloader.thumbnail_manager import ThumbnailManager
from downloader.info_manager import InfoManager
from core.diagnostics import ErrorTracker
from core.error_classifier import ErrorClassifier, ErrorCategory, DownloadError
from core.platform import PlatformRegistry
from core.inventory import ProfileMediaInventory, MediaDownloadStatus
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlError, GalleryDlCancelledException
from downloader.engine_router import DownloadEngineRouter, EngineType
from downloader.cover_art_manager import (
    CoverArtManager,
    SUPPORTED_COVER_ART_AUDIO_EXTENSIONS,
)
from downloader.lyrics_manager import LyricsManager


def kill_child_processes() -> None:
    """Terminates any child processes (deno, ffmpeg, ffprobe, yt-dlp) spawned by the current process on Windows."""
    try:
        import sys
        if sys.platform != "win32":
            return
        import os
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_TERMINATE = 0x0001

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('cntUsage', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', wintypes.DWORD),
                ('cntThreads', wintypes.DWORD),
                ('th32ParentProcessID', wintypes.DWORD),
                ('pcPriClassBase', wintypes.LONG),
                ('dwFlags', wintypes.DWORD),
                ('szExeFile', ctypes.c_char * 260)
            ]

        current_pid = os.getpid()
        kernel32 = ctypes.windll.kernel32
        h_snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snapshot == -1:
            return

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

        procs = []
        if kernel32.Process32First(h_snapshot, ctypes.byref(entry)):
            while True:
                child_pid = entry.th32ProcessID
                parent_pid = entry.th32ParentProcessID
                exe_name = entry.szExeFile.decode('utf-8', errors='ignore').lower()
                procs.append((child_pid, parent_pid, exe_name))
                if not kernel32.Process32Next(h_snapshot, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(h_snapshot)

        # Collect all descendant PIDs
        descendants = set()
        to_check = {current_pid}
        while to_check:
            next_check = set()
            for pid, ppid, _ in procs:
                if ppid in to_check and pid not in descendants and pid != current_pid:
                    descendants.add(pid)
                    next_check.add(pid)
            to_check = next_check

        for pid, _, exe_name in procs:
            if pid in descendants and any(target in exe_name for target in ('deno', 'ffmpeg', 'ffprobe', 'yt-dlp', 'gallery-dl', 'conhost')):
                h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h_proc:
                    kernel32.TerminateProcess(h_proc, 1)
                    kernel32.CloseHandle(h_proc)
    except Exception:
        pass


class DownloadManager(QThread):
    """
    Background worker thread managing sequential video downloads.

    Signals:
        queue_started (int): Emitted when batch starts with total selected video count.
        video_started (str, str, int, int): (video_id, title, current_index, total_count).
        video_progress (str, float, str, str, str, str):
            (video_id, percent, downloaded_size, total_size, speed, eta).
        video_status_changed (str, str, str): (video_id, new_status, error_reason).
        video_subtitle_status (str, str): (video_id, subtitle_status_text).
        overall_progress (int, int, int, int, float):
            (completed_count, skipped_count, failed_count, remaining_count, overall_percent).
        queue_finished (int, int, int, int):
            (completed_count, skipped_count, failed_count, total_count).
        log_message (str): Timestamped status message for the GUI console.
        error_occurred (str, str): (title, user_friendly_message).
    """

    queue_started = Signal(int)
    video_started = Signal(str, str, int, int)
    video_progress = Signal(str, float, str, str, str, str)
    video_status_changed = Signal(str, str, str)
    video_subtitle_status = Signal(str, str)
    overall_progress = Signal(int, int, int, int, float)
    queue_finished = Signal(int, int, int, int)
    log_message = Signal(str)
    error_occurred = Signal(str, str)


    MAX_RETRIES = 3

    def __init__(
        self,
        videos: List[VideoItem],
        settings: DownloadSettings,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.videos = list(videos)  # Clone list
        self.settings = settings
        self.engine = YtDlpEngine()
        self.gallerydl_engine = GalleryDlEngine()
        self.router = DownloadEngineRouter(gallerydl_engine=self.gallerydl_engine)
        self.inventory = ProfileMediaInventory()

        # Thread synchronization and control flags
        self._is_cancelled = False
        self._is_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Initially unpaused
        self._terminal_video_ids: set[str] = set()
        self._resolved_target_dir: Optional[Path] = None
        self._last_video_target_dir: Optional[Path] = None
        self._downloaded_cover_arts: set = set()

    @staticmethod
    def _compute_stage_weights(
        has_media: bool,
        has_sub: bool,
        has_thumb: bool,
        has_meta: bool,
        has_cover: bool = False,
        has_lyrics: bool = False,
        has_embed: bool = False,
    ) -> Dict[str, Tuple[float, float]]:
        """
        Computes non-overlapping, contiguous progress percentage ranges [start, end]
        for each active download/saving stage of a video item so that:
        - The sum of stage progress ranges is always exactly 100.0%.
        - The media download (if present) receives the primary progress allocation.
        - Subsequent asset stages (subtitles, thumbnail, cover art, lyrics, tag embedding, metadata) receive distinct slices.
        - The progress bar never prematurely reaches 100% while stages remain pending.
        """
        stages: List[str] = []
        if has_media:
            stages.append("media")
        if has_sub:
            stages.append("subtitles")
        if has_thumb:
            stages.append("thumbnail")
        if has_cover:
            stages.append("cover_art")
        if has_lyrics:
            stages.append("lyrics")
        if has_embed:
            stages.append("embed")
        if has_meta:
            stages.append("metadata")

        if not stages:
            return {}

        ranges: Dict[str, Tuple[float, float]] = {}

        if has_media:
            extra_stages = [s for s in stages if s != "media"]
            k = len(extra_stages)
            if k == 0:
                ranges["media"] = (0.0, 100.0)
            elif k == 1:
                ranges["media"] = (0.0, 85.0)
                ranges[extra_stages[0]] = (85.0, 100.0)
            elif k == 2:
                ranges["media"] = (0.0, 80.0)
                ranges[extra_stages[0]] = (80.0, 90.0)
                ranges[extra_stages[1]] = (90.0, 100.0)
            elif k == 3:
                ranges["media"] = (0.0, 70.0)
                ranges[extra_stages[0]] = (70.0, 80.0)
                ranges[extra_stages[1]] = (80.0, 90.0)
                ranges[extra_stages[2]] = (90.0, 100.0)
            elif k == 4:
                ranges["media"] = (0.0, 68.0)
                ranges[extra_stages[0]] = (68.0, 76.0)
                ranges[extra_stages[1]] = (76.0, 84.0)
                ranges[extra_stages[2]] = (84.0, 92.0)
                ranges[extra_stages[3]] = (92.0, 100.0)
            else:
                media_slice = 65.0
                ranges["media"] = (0.0, media_slice)
                rem = 100.0 - media_slice
                step = rem / k
                for idx, stg in enumerate(extra_stages):
                    ranges[stg] = (media_slice + idx * step, media_slice + (idx + 1) * step)
        else:
            # ASSETS ONLY mode
            m = len(stages)
            if m == 1:
                ranges[stages[0]] = (0.0, 100.0)
            elif m == 2:
                ranges[stages[0]] = (0.0, 50.0)
                ranges[stages[1]] = (50.0, 100.0)
            elif m == 3:
                ranges[stages[0]] = (0.0, 34.0)
                ranges[stages[1]] = (34.0, 67.0)
                ranges[stages[2]] = (67.0, 100.0)
            elif m >= 4:
                step = 100.0 / m
                for idx, stg in enumerate(stages):
                    ranges[stg] = (idx * step, (idx + 1) * step)

        return ranges

    def cancel(self) -> None:
        """Flags the download queue for cancellation and terminates child worker processes."""
        self._is_cancelled = True
        self._is_paused = False
        self._pause_event.set()  # Unblock if paused so thread can exit cleanly
        kill_child_processes()
        GalleryDlEngine.terminate_all_processes()
        self.log_message.emit("[CANCEL] Cancellation requested. Stopping download and child processes...")
        self.log_message.emit("[QUEUE] Download cancelled by user.")

    def pause(self) -> None:
        """Pauses queue dispatch between videos."""
        self._is_paused = True
        self._pause_event.clear()
        self.log_message.emit("[PAUSE] Queue paused. Current activity will pause; click 'Resume' to continue.")

    def resume(self) -> None:
        """Resumes queue dispatch."""
        self._is_paused = False
        self._pause_event.set()
        self.log_message.emit("[RESUME] Queue resumed.")

    def is_cancelled(self) -> bool:
        """Returns whether cancellation was requested."""
        return self._is_cancelled

    def is_paused(self) -> bool:
        """Returns whether the queue is currently paused."""
        return self._is_paused

    @staticmethod
    def classify_error(err_msg: str, platform: Optional[str] = None) -> str:
        """
        Classifies downloader error into standard category using ErrorClassifier.
        """
        return ErrorClassifier.classify(err_msg, platform=platform).category

    def _cancelable_sleep(self, seconds: float) -> bool:
        """
        Sleeps for `seconds` in 100ms intervals, checking self._is_cancelled.
        Returns True if cancelled, False if sleep completed normally.
        """
        steps = int(max(1, seconds * 10))
        for _ in range(steps):
            if self._is_cancelled:
                return True
            self.msleep(100)
        return self._is_cancelled

    def _process_image_conversions(self, downloaded_files: List[str]) -> List[str]:
        """Converts downloaded images according to user settings using Pillow."""
        target_fmt = getattr(self.settings, "image_format", "Keep Original")
        if not target_fmt or target_fmt in ("Keep Original", "Original"):
            return downloaded_files

        target_ext = "." + target_fmt.lower().replace("jpeg", "jpg")
        pil_format = "JPEG" if target_ext in (".jpg", ".jpeg") else target_fmt.upper()

        quality_str = getattr(self.settings, "image_quality", "90%")
        try:
            quality = int(str(quality_str).replace("%", "").strip())
            quality = max(1, min(100, quality))
        except Exception:
            quality = 90

        preserve_orig = getattr(self.settings, "preserve_original_images", True)

        try:
            from PIL import Image
        except ImportError:
            self.log_message.emit("[WARNING] Pillow is not installed; skipping image format conversion.")
            return downloaded_files

        converted_list = []
        for file_path_str in downloaded_files:
            file_path = Path(file_path_str)
            if not file_path.exists():
                converted_list.append(file_path_str)
                continue

            orig_ext = file_path.suffix.lower()
            if orig_ext == target_ext or (target_ext in (".jpg", ".jpeg") and orig_ext in (".jpg", ".jpeg")):
                converted_list.append(file_path_str)
                continue

            out_path = file_path.with_suffix(target_ext)
            try:
                with Image.open(file_path) as im:
                    save_kwargs = {}
                    if pil_format == "JPEG":
                        if im.mode in ("RGBA", "LA", "P"):
                            im = im.convert("RGB")
                        save_kwargs["quality"] = quality
                    elif pil_format == "WEBP":
                        save_kwargs["quality"] = quality
                    elif pil_format == "PNG":
                        pass

                    im.save(out_path, format=pil_format, **save_kwargs)

                self.log_message.emit(f"[IMAGE CONVERT] Converted {file_path.name} -> {out_path.name} ({target_fmt})")

                if not preserve_orig and out_path != file_path:
                    try:
                        file_path.unlink(missing_ok=True)
                    except Exception as e:
                        self.log_message.emit(f"[WARNING] Could not delete original image {file_path.name}: {e}")

                converted_list.append(str(out_path))
            except Exception as exc:
                self.log_message.emit(f"[IMAGE CONVERT WARNING] Failed to convert {file_path.name} to {target_fmt}: {exc}. Retaining original file.")
                converted_list.append(file_path_str)

        return converted_list

    def run(self) -> None:
        """Main worker thread loop executing sequential downloads."""
        total_videos = len(self.videos)
        if total_videos == 0:
            self.queue_finished.emit(0, 0, 0, 0)
            return

        self._downloaded_cover_arts = set()

        self.queue_started.emit(total_videos)
        self.log_message.emit("=" * 65)
        self.log_message.emit(f"[INFO] Download Queue Started: {total_videos} video(s)")
        cwd, safe_temp = ensure_safe_environment()
        self.log_message.emit(f"[INFO] Working Directory: {cwd}")
        self.log_message.emit(f"[INFO] Temporary Directory: {safe_temp}")
        mode_val = self.settings.download_mode or DownloadMode.VIDEO_ONLY
        self.log_message.emit(f"[CONFIG] Download Mode : {mode_val}")
        if mode_val in (DownloadMode.VIDEO_ONLY, DownloadMode.VIDEO_AND_AUDIO):
            self.log_message.emit(f"[CONFIG] Video Format  : {self.settings.format} ({self.settings.quality}, {self.settings.bitrate})")
        # Log subtitle configuration if active
        if self.settings.download_subtitles:
            self.log_message.emit(f"[CONFIG] Subtitle      : {self.settings.subtitle_language} ({self.settings.subtitle_source}, {self.settings.subtitle_format})")
        # Log thumbnail configuration if active
        if self.settings.download_thumbnail:
            self.log_message.emit(f"[CONFIG] Thumbnail     : Yes ({self.settings.thumbnail_format})")
        if getattr(self.settings, "download_cover_art", False):
            self.log_message.emit("[CONFIG] Cover Art     : Yes (1:1 Original)")
        if getattr(self.settings, "embed_cover_art", False):
            self.log_message.emit("[CONFIG] Embed Cover   : Yes (ID3/Metadata Tag)")
        if getattr(self.settings, "embed_metadata", False):
            self.log_message.emit("[CONFIG] Embed Metadata: Yes (Audio Tag)")
        if getattr(self.settings, "download_lrc_lyrics", False):
            self.log_message.emit("[CONFIG] LRC Lyrics    : Yes (.lrc)")
        if getattr(self.settings, "embed_lyrics", False):
            self.log_message.emit("[CONFIG] Embed Lyrics  : Yes (Audio Tag)")
        # Log metadata / description / chapters if active
        if self.settings.save_description:
            self.log_message.emit("[CONFIG] Description   : Yes (.description)")
        if self.settings.save_metadata:
            self.log_message.emit("[CONFIG] Metadata      : Yes (.metadata.txt)")
        if self.settings.save_chapters:
            self.log_message.emit("[CONFIG] Chapters      : Yes (.chapters.txt)")
        custom_folder = (
            getattr(self.settings, "unique_filename_folder", "")
            or getattr(self.settings, "unique_folder_name", "")
            or getattr(self.settings, "custom_folder_name", "")
        )
        is_custom_folder = (
            getattr(self.settings, "create_unique_filename", False)
            or getattr(self.settings, "create_unique_folder", False)
        ) and bool(custom_folder and custom_folder.strip())

        if is_custom_folder:
            self.log_message.emit(f"[CONFIG] Custom Folder  : Yes ({custom_folder.strip()})")
        else:
            self.log_message.emit(f"[CONFIG] Channel Folder : {'Yes' if self.settings.create_channel_folder else 'No'}")
        self.log_message.emit(f"[CONFIG] Video Folders  : {'Yes' if self.settings.create_individual_video_folders else 'No'}")
        self.log_message.emit(f"[CONFIG] Video ID in File: {'Yes' if self.settings.include_video_id_in_filename else 'No'}")
        self.log_message.emit(f"[CONFIG] Number Prefix: {'Yes' if getattr(self.settings, 'add_number_to_filename', False) else 'No'}")
        self.log_message.emit(f"[CONFIG] Skip Existing : {'Yes' if self.settings.skip_existing else 'No'}")

        # 1. Resolve Target Directory & Create Channel Subfolder or Custom Folder if enabled
        base_dir = Path(self.settings.download_folder)
        if is_custom_folder:
            clean_custom = sanitize_path_component(custom_folder.strip(), max_length=120, fallback="custom_folder")
            target_dir = base_dir / clean_custom
        elif self.settings.create_channel_folder and self.settings.channel_title:
            clean_channel = sanitize_path_component(self.settings.channel_title, max_length=80, fallback="channel")
            target_dir = base_dir / clean_channel
        else:
            target_dir = base_dir

        self._resolved_target_dir = target_dir

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            self.log_message.emit(f"[CONFIG] Destination   : {target_dir}")
        except Exception as e:
            self.log_message.emit(f"[ERROR] Could not create destination folder: {e}")
            self.error_occurred.emit("Folder Error", f"Could not create folder:\n{target_dir}\n\nError: {e}")
            self.queue_finished.emit(0, 0, total_videos, total_videos)
            return

        # 2. Check FFmpeg availability
        is_ffmpeg_ok, ffmpeg_path, ffmpeg_ver, _ = FFmpegChecker.detect()
        ffmpeg_dir = FFmpegChecker.get_ffmpeg_directory() if is_ffmpeg_ok else None

        if is_ffmpeg_ok:
            self.log_message.emit(f"[INFO] FFmpeg Detected : v{ffmpeg_ver}")
        else:
            self.log_message.emit("[WARNING] FFmpeg not found. Media stream merging and subtitle conversion may be limited.")

        # 3. Resolve Download Archive path
        # In Assets Only mode, we do NOT use or write to the video download archive
        is_sub_only = (mode_val in (DownloadMode.ASSETS_ONLY, "Subtitle Only"))
        archive_file = get_archive_file() if (self.settings.skip_existing and not is_sub_only) else None
        if archive_file:
            self.log_message.emit(f"[INFO] Archive File    : {archive_file}")

        self.log_message.emit("=" * 65)

        # 4. Counters
        completed_count = 0
        skipped_count = 0
        failed_count = 0

        # Mark all selected items as 'Waiting' initially
        for vid in self.videos:
            self.video_status_changed.emit(vid.video_id, VideoStatus.WAITING, "")
            if self.settings.download_subtitles:
                self.video_subtitle_status.emit(vid.video_id, "Waiting")

        # Identify duplicate titles in queue for deterministic folder collision isolation
        title_counts = Counter(v.title for v in self.videos)
        duplicate_titles = {title for title, count in title_counts.items() if count > 1}

        # 5. Sequential Download Loop
        for index, video in enumerate(self.videos, start=1):
            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index - 1:])
                break

            if self._is_paused:
                self.log_message.emit(f"[PAUSED] Waiting to resume before starting #{index}: {video.title}")
                self._pause_event.wait()
                if self._is_cancelled:
                    self._mark_remaining_cancelled(self.videos[index - 1:])
                    break

            # 5.0 Pre-download inaccessibility check
            is_known_private = video.is_private or (video.extra_metadata.get("inaccessibility") == ErrorCategory.PRIVATE_VIDEO)
            is_known_unavailable = (not is_known_private) and (video.is_unavailable or (video.extra_metadata.get("inaccessibility") == ErrorCategory.VIDEO_UNAVAILABLE))

            if is_known_private or is_known_unavailable or video.is_inaccessible:
                reason_label = "Private Video" if is_known_private else "Unavailable Video"
                inaccess_cat = ErrorCategory.PRIVATE_VIDEO if is_known_private else ErrorCategory.VIDEO_UNAVAILABLE

                video.status = VideoStatus.SKIPPED
                video.error_reason = reason_label
                video.extra_metadata["inaccessibility"] = inaccess_cat
                self._terminal_video_ids.add(video.video_id)
                skipped_count += 1
                self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, reason_label)
                self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", f"Skipped ({reason_label})", "00:00")
                if is_known_private:
                    self.log_message.emit(f"[QUEUE] Skipping private video: {video.title or video.video_id}")
                else:
                    self.log_message.emit(f"[QUEUE] Skipping unavailable video ({reason_label}): {video.title or video.video_id}")
                self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} skipped. Continuing to the next item...")
                rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
                ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
                self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)
                continue

            remaining_count = total_videos - (completed_count + skipped_count + failed_count)
            overall_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
            self.overall_progress.emit(completed_count, skipped_count, failed_count, remaining_count, overall_pct)

            self.video_started.emit(video.video_id, video.title, index, total_videos)
            self.log_message.emit(f"\n[DOWNLOAD] ({index}/{total_videos}) Starting: {video.title}")

            # Resolve effective number prefix if add_number_to_filename is enabled
            num_prefix = ""
            if getattr(self.settings, "add_number_to_filename", False) or getattr(self.settings, "add_number_prefix", False):
                max_idx = getattr(self.settings, "max_scan_index", None)
                if not max_idx:
                    max_idx = max((v.index for v in self.videos if getattr(v, "index", None)), default=total_videos)
                scan_idx = video.index if (getattr(video, "index", None) and video.index > 0) else index
                num_prefix = format_number_prefix(scan_idx, max_index=max_idx)

            # Resolve the output directory for this video
            video_target_dir = resolve_video_output_dir(
                base_download_dir=base_dir,
                channel_title=self.settings.channel_title,
                create_channel_folder=self.settings.create_channel_folder,
                video_title=video.title,
                video_id=video.video_id,
                create_individual_video_folders=self.settings.create_individual_video_folders,
                duplicate_titles_in_queue=duplicate_titles,
                number_prefix=num_prefix,
                custom_folder_name=custom_folder.strip() if is_custom_folder else None,
            )
            self._last_video_target_dir = video_target_dir

            # Resolve effective video ID filename setting with collision protection
            eff_include_id = should_include_video_id(
                video_title=video.title,
                video_id=video.video_id,
                include_video_id_setting=self.settings.include_video_id_in_filename,
                create_individual_video_folders=self.settings.create_individual_video_folders,
                duplicate_titles_in_queue=duplicate_titles,
                target_dir=video_target_dir,
            )
            video_settings = replace(
                self.settings,
                include_video_id_in_filename=eff_include_id,
                include_media_id_in_filename=eff_include_id,
                number_prefix=num_prefix,
            )
            video_platform = getattr(video, "platform", "youtube")
            if not PlatformRegistry.is_available(video_platform):
                err = ErrorClassifier.for_unavailable_platform(video_platform, video_id=video.video_id, video_title=video.title)
                self.log_message.emit(f"[BLOCKED] {err.title}: {err.user_message}")
                failed_count += 1
                video.status = VideoStatus.FAILED
                video.error_reason = err.user_message
                self._terminal_video_ids.add(video.video_id)
                self.video_status_changed.emit(video.video_id, VideoStatus.FAILED, err.user_message)
                self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", "Failed", "00:00")
                rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
                ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
                self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)
                if index < total_videos and not self._is_cancelled:
                    self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} failed. Continuing to next item in queue...")
                continue

            adapter = PlatformRegistry.get_adapter(video_platform)
            supports_cookies = (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file) if adapter else (video_platform.lower() == "youtube")
            if not supports_cookies:
                video_settings = replace(video_settings, browser_cookies="none")

            try:
                video_target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.log_message.emit(f"[ERROR] Could not create folder for {video.title}: {e}")
                self._terminal_video_ids.add(video.video_id)
                failed_count += 1
                video.status = VideoStatus.FAILED
                video.error_reason = f"Folder error: {e}"
                self.video_status_changed.emit(video.video_id, VideoStatus.FAILED, f"Folder error: {e}")
                self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", "Failed", "00:00")
                rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
                ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
                self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)
                if index < total_videos and not self._is_cancelled:
                    self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} failed. Continuing to next item in queue...")
                continue

            if self.settings.create_individual_video_folders:
                self.log_message.emit(f"[FOLDER] Video folder: {video_target_dir}")

            last_logged_processing_step = None

            is_sub_only = (self.settings.download_mode == DownloadMode.ASSETS_ONLY)
            has_sub = bool(self.settings.download_subtitles)
            adapter = PlatformRegistry.get_adapter(getattr(video, "platform", "youtube"))
            if adapter and not adapter.capabilities.supports_subtitles:
                has_sub = False
            has_thumb = bool(self.settings.download_thumbnail)
            has_info = bool(self.settings.save_description or self.settings.save_metadata or self.settings.save_chapters)

            has_cover = bool(getattr(self.settings, "download_cover_art", False))
            has_lyrics = bool(getattr(self.settings, "download_lrc_lyrics", False))
            has_embed = bool(
                getattr(self.settings, "embed_cover_art", False)
                or getattr(self.settings, "embed_metadata", False)
                or getattr(self.settings, "embed_lyrics", False)
            ) and not is_sub_only
            stage_ranges = self._compute_stage_weights(
                has_media=not is_sub_only,
                has_sub=has_sub,
                has_thumb=has_thumb,
                has_meta=has_info,
                has_cover=has_cover,
                has_lyrics=has_lyrics,
                has_embed=has_embed,
            )
            media_start, media_end = stage_ranges.get("media", (0.0, 100.0))
            last_media_downloaded_str = "-- MB"
            last_media_total_str = "-- MB"

            # Define progress callback for this video
            def handle_video_progress(data: Dict[str, Any]) -> None:
                nonlocal last_logged_processing_step, last_media_downloaded_str, last_media_total_str
                status_val = data.get("status")
                step_val = data.get("step", "")
                raw_pct = float(data.get("percent", 0.0))
                scaled_pct = media_start + (raw_pct / 100.0) * (media_end - media_start)
                scaled_pct = min(media_end, max(media_start, scaled_pct))

                dl_str = data.get("downloaded_str")
                if dl_str and dl_str != "-- MB":
                    last_media_downloaded_str = dl_str
                tot_str = data.get("total_str")
                if tot_str and tot_str != "-- MB":
                    last_media_total_str = tot_str

                if status_val == "downloading":
                    status_text = VideoStatus.DOWNLOADING if not step_val else f"Downloading ({step_val})"
                    self.video_status_changed.emit(video.video_id, status_text, "")
                    self.video_progress.emit(
                        video.video_id,
                        scaled_pct,
                        last_media_downloaded_str,
                        last_media_total_str,
                        data.get("speed", "-- MB/s"),
                        data.get("eta", "--:--"),
                    )
                elif status_val == "processing":
                    op_label = data.get("operation") or "Processing"
                    proc_text = VideoStatus.PROCESSING if not step_val else f"{op_label} ({step_val})"
                    self.video_status_changed.emit(video.video_id, proc_text, "")
                    self.video_progress.emit(
                        video.video_id,
                        scaled_pct,
                        last_media_downloaded_str,
                        last_media_total_str,
                        f"FFmpeg ({op_label})",
                        "00:00",
                    )
                    current_step_key = f"{step_val}:{data.get('postprocessor', op_label)}"
                    if current_step_key != last_logged_processing_step:
                        last_logged_processing_step = current_step_key
                        self.log_message.emit(f"[PROCESSING] FFmpeg {op_label.lower()} ({step_val or 'media'}): {video.title}")

            # -------------------------------------------------------------
            # Branch A: ASSETS ONLY MODE
            # -------------------------------------------------------------
            if is_sub_only:
                sub_res = None
                thumb_res = None
                info_res = None

                # 1. Subtitles (only if explicitly enabled)
                if has_sub and not self._is_cancelled:
                    sub_start, sub_end = stage_ranges.get("subtitles", (0.0, 100.0))
                    self.video_status_changed.emit(video.video_id, "Downloading (Subtitles)", "")
                    self.video_progress.emit(video.video_id, sub_start, "-- KB", "-- KB", "Subtitles", "--:--")
                    self.video_subtitle_status.emit(video.video_id, "Downloading...")
                    sub_res = SubtitleManager.download_subtitles(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )
                    self.video_subtitle_status.emit(video.video_id, sub_res.get("status_text", "No Subs"))
                    self.video_progress.emit(video.video_id, sub_end, "-- KB", "-- KB", "Subtitles", "00:00")

                if self._is_cancelled:
                    self._mark_remaining_cancelled(self.videos[index - 1:])
                    break

                # 2. Thumbnail
                if has_thumb and not self._is_cancelled:
                    thumb_start, thumb_end = stage_ranges.get("thumbnail", (0.0, 100.0))
                    self.video_status_changed.emit(video.video_id, "Downloading (Thumbnail)", "")
                    self.video_progress.emit(video.video_id, thumb_start, "-- KB", "-- KB", "Thumbnail", "--:--")
                    thumb_res = ThumbnailManager.download_thumbnail(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )
                    self.video_progress.emit(video.video_id, thumb_end, "-- KB", "-- KB", "Thumbnail", "00:00")

                # 2.5 Cover Art (Assets Only)
                has_cover = bool(getattr(self.settings, "download_cover_art", False))
                cover_res = None
                ao_artist = video.extra_metadata.get("artist") or video.channel_title
                ao_album = video.extra_metadata.get("album") or ""
                if has_cover and not self._is_cancelled:
                    cov_start, cov_end = stage_ranges.get("cover_art", (0.0, 100.0))
                    self.video_status_changed.emit(video.video_id, "Downloading (Cover Art)", "")
                    self.video_progress.emit(video.video_id, cov_start, "-- KB", "-- KB", "Cover Art", "--:--")
                    cover_res = CoverArtManager.download_cover_art(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        album=ao_album,
                        downloaded_covers=self._downloaded_cover_arts,
                    )
                    self.video_progress.emit(video.video_id, cov_end, "-- KB", "-- KB", "Cover Art", "00:00")

                # 2.6 Lyrics (Assets Only)
                has_lyrics = bool(getattr(self.settings, "download_lrc_lyrics", False))
                lyrics_res = None
                if has_lyrics and not self._is_cancelled:
                    lyr_start, lyr_end = stage_ranges.get("lyrics", (0.0, 100.0))
                    self.video_status_changed.emit(video.video_id, "Downloading (Lyrics)", "")
                    self.video_progress.emit(video.video_id, lyr_start, "-- KB", "-- KB", "Lyrics", "--:--")
                    lyrics_res = LyricsManager.download_lyrics(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        artist=ao_artist,
                        title=video.title,
                        album=ao_album,
                        duration=video.duration_seconds,
                    )
                    video._lrc_found = bool(lyrics_res and lyrics_res.get("success"))
                    self.video_progress.emit(video.video_id, lyr_end, "-- KB", "-- KB", "Lyrics", "00:00")

                if self._is_cancelled:
                    self._mark_remaining_cancelled(self.videos[index - 1:])
                    break

                # 3. Description / Metadata / Chapters
                if has_info and not self._is_cancelled:
                    meta_start, meta_end = stage_ranges.get("metadata", (0.0, 100.0))
                    self.video_status_changed.emit(video.video_id, "Saving (Metadata)", "")
                    self.video_progress.emit(video.video_id, meta_start, "-- KB", "-- KB", "Metadata", "--:--")
                    info_res = InfoManager.save_video_info(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )
                    self.video_progress.emit(video.video_id, meta_end, "-- KB", "-- KB", "Metadata", "00:00")

                # Collect results
                results = []
                if has_sub and sub_res:
                    results.append(("subtitle", sub_res))
                if has_thumb and thumb_res:
                    results.append(("thumbnail", thumb_res))
                if has_cover and cover_res:
                    results.append(("cover_art", cover_res))
                if has_lyrics and lyrics_res:
                    results.append(("lyrics", lyrics_res))
                if has_info and info_res:
                    results.append(("metadata", info_res))

                hard_failures = []
                any_success = False
                all_skipped = bool(results)

                for rtype, rdict in results:
                    succ = rdict.get("success", False)
                    skip = rdict.get("skipped", False)
                    err = rdict.get("error", "")

                    if succ:
                        if not skip:
                            any_success = True
                            all_skipped = False
                    else:
                        # For subtitles, missing subs is non-fatal notice
                        if rtype == "subtitle" and ("No subtitles" in err or "not available" in err or "No Sub" in rdict.get("status_text", "") or rdict.get("status_text", "").startswith("—")):
                            pass
                        else:
                            all_skipped = False
                            hard_failures.append((rtype, err))

                if hard_failures:
                    first_fail_type, first_err = hard_failures[0]
                    sub_dl_err = ErrorClassifier.classify(
                        raw_error=first_err,
                        component="yt-dlp",
                        stage=first_fail_type,
                        video_id=video.video_id,
                        video_title=video.title,
                        platform=getattr(video, "platform", "youtube"),
                    )
                    video.error_details = sub_dl_err
                    ErrorTracker.record_error(sub_dl_err)

                    is_priv = (sub_dl_err.category == ErrorCategory.PRIVATE_VIDEO) or ErrorClassifier.is_private_video(first_err)
                    is_unavail = (not is_priv) and ((sub_dl_err.category == ErrorCategory.VIDEO_UNAVAILABLE) or ErrorClassifier.is_unavailable_video(first_err))

                    if is_priv or is_unavail:
                        reason_label = "Private Video" if is_priv else "Unavailable Video"
                        inaccess_cat = ErrorCategory.PRIVATE_VIDEO if is_priv else ErrorCategory.VIDEO_UNAVAILABLE
                        video.status = VideoStatus.SKIPPED
                        video.error_reason = reason_label
                        video.extra_metadata["inaccessibility"] = inaccess_cat
                        self._terminal_video_ids.add(video.video_id)
                        skipped_count += 1
                        self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, reason_label)
                        self.video_progress.emit(video.video_id, 0.0, "-- KB", "-- KB", f"Skipped ({reason_label})", "00:00")
                        if is_priv:
                            self.log_message.emit(f"[QUEUE] Skipping private video: {video.title or video.video_id}")
                        else:
                            self.log_message.emit(f"[QUEUE] Skipping unavailable video: {video.title or video.video_id}")
                        self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} skipped. Continuing to the next item...")
                    else:
                        failed_count += 1
                        video.status = VideoStatus.FAILED
                        video.error_reason = sub_dl_err.user_message
                        self._terminal_video_ids.add(video.video_id)
                        self.video_status_changed.emit(video.video_id, sub_dl_err.concise_status, sub_dl_err.user_message)
                        self.video_progress.emit(video.video_id, 0.0, "-- KB", "-- KB", "Failed", "00:00")
                        self.log_message.emit(f"[FAILED] Asset download failed for {video.title}: {sub_dl_err.user_message}")
                        if index < total_videos and not self._is_cancelled:
                            self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} failed. Continuing to next item in queue...")
                elif any_success:
                    completed_count += 1
                    video.status = VideoStatus.COMPLETED
                    video.error_reason = ""
                    self._terminal_video_ids.add(video.video_id)
                    self.video_status_changed.emit(video.video_id, VideoStatus.COMPLETED, "")
                    self.video_progress.emit(video.video_id, 100.0, "-- KB", "-- KB", "Finished", "00:00")
                    self.log_message.emit(f"[COMPLETED] Assets downloaded: {video.title}")
                elif all_skipped:
                    skipped_count += 1
                    video.status = VideoStatus.SKIPPED
                    video.error_reason = "Assets already exist on disk"
                    self._terminal_video_ids.add(video.video_id)
                    self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, "Assets already exist on disk")
                    self.video_progress.emit(video.video_id, 100.0, "-- KB", "-- KB", "Finished", "00:00")
                    self.log_message.emit(f"[SKIPPED] Assets already exist: {video.title}")
                else:
                    skipped_count += 1
                    video.status = VideoStatus.SKIPPED
                    video.error_reason = "No subtitles available"
                    self._terminal_video_ids.add(video.video_id)
                    self.video_status_changed.emit(video.video_id, "No Subtitle", sub_res.get("error", "") if sub_res else "")
                    self.video_progress.emit(video.video_id, 100.0, "-- KB", "-- KB", "Finished", "00:00")
                    self.log_message.emit(f"[SUBTITLE NOTICE] {video.title}: No subtitles available")

                rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
                ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
                self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)
                continue

            # -------------------------------------------------------------
            # Branch B: VIDEO / AUDIO / VIDEO + AUDIO MODES
            # -------------------------------------------------------------
            success = False
            is_skipped = False
            is_inaccessible_skipped = False
            inaccessible_reason = ""
            inaccessible_cat = None
            last_error_msg = ""
            download_error: Optional[DownloadError] = None

            for attempt in range(1, self.MAX_RETRIES + 1):
                if self._is_cancelled:
                    break

                if attempt > 1:
                    retry_label = f"Retry {attempt}/{self.MAX_RETRIES}"
                    if download_error and download_error.category == ErrorCategory.RATE_LIMITED:
                        retry_label = f"Rate Limit Retry {attempt}/{self.MAX_RETRIES}"
                    elif download_error and download_error.category in (ErrorCategory.NETWORK_ERROR, ErrorCategory.TIMEOUT):
                        retry_label = f"Network Retry {attempt}/{self.MAX_RETRIES}"
                    elif download_error and download_error.category in (ErrorCategory.HTTP_500, ErrorCategory.HTTP_502, ErrorCategory.HTTP_503):
                        retry_label = f"Server Error Retry {attempt}/{self.MAX_RETRIES}"
                    self.video_status_changed.emit(video.video_id, retry_label, last_error_msg)
                    self.log_message.emit(f"[RETRY] Attempt {attempt}/{self.MAX_RETRIES} for: {video.title}")

                try:
                    route_decision = self.router.route_media_item(video, platform=video_platform)
                    if route_decision.engine == EngineType.GALLERY_DL:
                        custom_cookie = ""
                        if video_platform == "facebook":
                            custom_cookie = getattr(self.settings, "facebook_custom_cookie_file", "")
                        elif video_platform == "instagram":
                            custom_cookie = getattr(self.settings, "instagram_custom_cookie_file", "")
                        elif video_platform == "x":
                            custom_cookie = getattr(self.settings, "x_custom_cookie_file", "")

                        g_stem = resolve_media_filename(video.title, video.video_id, include_video_id=eff_include_id, target_dir=video_target_dir, number_prefix=num_prefix)
                        g_res = self.gallerydl_engine.download_media(
                            url=video.url,
                            target_dir=video_target_dir,
                            filename_stem=g_stem,
                            custom_cookie_file=custom_cookie,
                            progress_callback=handle_video_progress,
                            log_callback=self.log_message.emit,
                            cancel_check=self.is_cancelled,
                        )
                        success = g_res.get("success", False)
                        is_skipped = g_res.get("skipped", False)
                        dl_files = g_res.get("downloaded_files", [])
                        if success and not is_skipped and dl_files:
                            dl_files = self._process_image_conversions(dl_files)
                        info_dict = {
                            "id": video.video_id,
                            "title": video.title,
                            "webpage_url": video.url,
                            "ext": Path(dl_files[0]).suffix.lstrip(".") if dl_files else "jpg",
                            "filesize": Path(dl_files[0]).stat().st_size if dl_files and Path(dl_files[0]).exists() else 0,
                            "media_type": route_decision.media_type,
                            "engine": "gallery-dl",
                        }
                        if not success and g_res.get("error"):
                            raise DownloaderError(g_res.get("error"), raw_error=g_res.get("error"))
                    elif route_decision.engine == EngineType.UNSUPPORTED:
                        raise DownloaderError(f"Unsupported media task: {route_decision.rationale}")
                    else:
                        res = self.engine.download_single_video(
                            video=video,
                            settings=video_settings,
                            target_dir=video_target_dir,
                            ffmpeg_location=ffmpeg_dir,
                            archive_file=archive_file,
                            progress_callback=handle_video_progress,
                            log_callback=self.log_message.emit,
                            cancel_check=self.is_cancelled,
                        )
                        success = res.get("success", False)
                        is_skipped = res.get("skipped", False)
                        info_dict = res.get("info_dict")
                    break

                except DownloadCancelledException:
                    self._is_cancelled = True
                    video.status = VideoStatus.CANCELLED
                    video.error_reason = "Cancelled by user"
                    self._terminal_video_ids.add(video.video_id)
                    self.video_status_changed.emit(video.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                    self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", "Cancelled", "00:00")
                    self.log_message.emit(f"[CANCELLED] Download cancelled: {video.title}")
                    break

                except Exception as e:
                    if self._is_cancelled or isinstance(e, DownloadCancelledException) or (self.is_cancelled() and "cancelled" in str(e).lower()):
                        self._is_cancelled = True
                        video.status = VideoStatus.CANCELLED
                        video.error_reason = "Cancelled by user"
                        self._terminal_video_ids.add(video.video_id)
                        self.video_status_changed.emit(video.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                        self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", "Cancelled", "00:00")
                        self.log_message.emit(f"[CANCELLED] Download cancelled: {video.title}")
                        break

                    last_error_msg = str(e)
                    stage = getattr(e, "stage", None)
                    raw_err = getattr(e, "raw_error", last_error_msg)
                    tech_details = getattr(e, "technical_details", "")
                    download_error = ErrorClassifier.classify(
                        raw_error=raw_err,
                        component="yt-dlp",
                        stage=stage,
                        video_id=video.video_id,
                        video_title=video.title,
                        platform=getattr(video, "platform", "youtube"),
                        technical_details=tech_details,
                    )
                    ErrorTracker.record_error(download_error)
                    video.error_details = download_error
                    self.log_message.emit(f"[WARNING] Attempt {attempt} failed: {last_error_msg}")

                    # Check if this error establishes that the video is private or unavailable
                    from core.availability import AvailabilityDetectorRegistry, AvailabilityStatus
                    detector = AvailabilityDetectorRegistry.get_detector(getattr(video, "platform", "youtube"))
                    avail_from_err = detector.detect_error(
                        last_error_msg,
                        video_id=video.video_id,
                        title=video.title,
                        url=video.url,
                    )
                    is_inacc_detector = avail_from_err.is_definitively_inaccessible()

                    is_priv = (download_error.category == ErrorCategory.PRIVATE_VIDEO) or ErrorClassifier.is_private_video(last_error_msg) or (avail_from_err.status == AvailabilityStatus.PRIVATE)
                    is_unavail = (not is_priv) and (
                        (download_error.category == ErrorCategory.VIDEO_UNAVAILABLE)
                        or ErrorClassifier.is_unavailable_video(last_error_msg)
                        or is_inacc_detector
                    )

                    if is_priv or is_unavail:
                        is_inaccessible_skipped = True
                        inaccessible_reason = "Private Video" if is_priv else "Unavailable Video"
                        inaccessible_cat = ErrorCategory.PRIVATE_VIDEO if is_priv else ErrorCategory.VIDEO_UNAVAILABLE
                        video.availability = avail_from_err
                        break  # Immediately stop retries for confirmed inaccessible videos

                    # If not retryable: immediately halt retries to prevent account/IP throttling or useless loops
                    if not download_error.retryable:
                        self.log_message.emit("=" * 65)
                        self.log_message.emit(f"[ERROR] {download_error.title}: '{video.title}'")
                        self.log_message.emit(f"[ERROR] Reason: {download_error.user_message}")
                        self.log_message.emit(f"[ERROR] Category: {download_error.category} | Component: {download_error.component} | Video ID: {video.video_id}")
                        self.log_message.emit("[ERROR] Suggested Action:")
                        for act_line in download_error.suggested_action.splitlines():
                            self.log_message.emit(f"  {act_line}")
                        self.log_message.emit(f"[ERROR] Technical Details: {download_error.technical_details}")
                        self.log_message.emit("=" * 65)
                        break

                    # If retryable and further retries remain:
                    if attempt < self.MAX_RETRIES:
                        if download_error.category == ErrorCategory.RATE_LIMITED:
                            backoff_seconds = 5.0 if attempt == 1 else 15.0
                            self.video_status_changed.emit(
                                video.video_id,
                                f"Rate Limited (Wait {int(backoff_seconds)}s)",
                                download_error.user_message,
                            )
                            self.log_message.emit(
                                f"[RATE LIMIT] {download_error.user_message}. Waiting {int(backoff_seconds)}s with exponential backoff before retry {attempt + 1}/{self.MAX_RETRIES}..."
                            )
                            if self._cancelable_sleep(backoff_seconds):
                                break
                        elif download_error.category in (ErrorCategory.NETWORK_ERROR, ErrorCategory.TIMEOUT):
                            backoff_seconds = 3.0 * attempt
                            self.video_status_changed.emit(
                                video.video_id,
                                f"Network Wait ({int(backoff_seconds)}s)",
                                download_error.user_message,
                            )
                            self.log_message.emit(
                                f"[NETWORK] {download_error.user_message}. Waiting {int(backoff_seconds)}s before retry {attempt + 1}/{self.MAX_RETRIES}..."
                            )
                            if self._cancelable_sleep(backoff_seconds):
                                break
                        elif download_error.category in (ErrorCategory.HTTP_500, ErrorCategory.HTTP_502, ErrorCategory.HTTP_503):
                            backoff_seconds = 2.0 * attempt
                            self.video_status_changed.emit(
                                video.video_id,
                                f"Server Wait ({int(backoff_seconds)}s)",
                                download_error.user_message,
                            )
                            self.log_message.emit(
                                f"[SERVER ERROR] {download_error.user_message}. Waiting {int(backoff_seconds)}s before retry {attempt + 1}/{self.MAX_RETRIES}..."
                            )
                            if self._cancelable_sleep(backoff_seconds):
                                break
                        else:
                            # Standard transient backoff: 2.0s
                            backoff_seconds = 2.0 * attempt
                            self.video_status_changed.emit(
                                video.video_id,
                                f"Wait ({int(backoff_seconds)}s)",
                                download_error.user_message,
                            )
                            if self._cancelable_sleep(backoff_seconds):
                                break

            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index - 1:])
                break

            if is_inaccessible_skipped:
                video.status = VideoStatus.SKIPPED
                video.error_reason = inaccessible_reason
                video.extra_metadata["inaccessibility"] = inaccessible_cat
                self._terminal_video_ids.add(video.video_id)
                skipped_count += 1
                self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, inaccessible_reason)
                self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", f"Skipped ({inaccessible_reason})", "00:00")
                if inaccessible_cat == ErrorCategory.PRIVATE_VIDEO:
                    self.log_message.emit(f"[QUEUE] Skipping private video: {video.title or video.video_id}")
                else:
                    self.log_message.emit(f"[QUEUE] Skipping unavailable video: {video.title or video.video_id}")
                self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} skipped. Continuing to the next item...")
                self.engine.safe_cleanup_partial_files(video_target_dir, video.video_id, title=video.title)
                rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
                ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
                self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)
                continue

            # If subtitles are also enabled for media downloads:
            # Gating: disable subtitles and thumbnails for photo items
            is_photo_item = (
                getattr(video, "media_type", "") in (MediaType.PHOTO, "Photo")
                or (locals().get("route_decision") and route_decision.engine == EngineType.GALLERY_DL)
            )
            if is_photo_item:
                has_sub = False
                has_thumb = False

            # If subtitles are also enabled for media downloads:
            if has_sub and (success or is_skipped) and not self._is_cancelled:
                sub_start, sub_end = stage_ranges.get("subtitles", (media_end, media_end))
                try:
                    self.video_status_changed.emit(video.video_id, "Downloading (Subtitles)", "")
                    self.video_progress.emit(
                        video.video_id,
                        sub_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Subtitles",
                        "--:--",
                    )
                    self.video_subtitle_status.emit(video.video_id, "Downloading...")
                    sub_res = SubtitleManager.download_subtitles(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )
                    self.video_subtitle_status.emit(video.video_id, sub_res.get("status_text", "No Subs"))
                except Exception as sub_err:
                    self.log_message.emit(f"[WARNING] Subtitle download error for {video.title}: {sub_err}")
                    self.video_subtitle_status.emit(video.video_id, "Failed")
                finally:
                    self.video_progress.emit(
                        video.video_id,
                        sub_end,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Subtitles",
                        "00:00",
                    )

            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index - 1:])
                break

            # If thumbnail is enabled:
            if has_thumb and not self._is_cancelled and (success or is_skipped):
                thumb_start, thumb_end = stage_ranges.get("thumbnail", (media_end, media_end))
                try:
                    self.video_status_changed.emit(video.video_id, "Downloading (Thumbnail)", "")
                    self.video_progress.emit(
                        video.video_id,
                        thumb_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Thumbnail",
                        "--:--",
                    )
                    ThumbnailManager.download_thumbnail(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        info_dict=info_dict,
                    )
                except Exception as thumb_err:
                    self.log_message.emit(f"[WARNING] Thumbnail download error for {video.title}: {thumb_err}")
                finally:
                    self.video_progress.emit(
                        video.video_id,
                        thumb_end,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Thumbnail",
                        "00:00",
                    )

            # Resolve common metadata fields early so Cover Art, Lyrics, and Embedding can use them
            title_val = (info_dict.get("track") if info_dict else None) or (info_dict.get("title") if info_dict else None) or video.title
            artist_val = (info_dict.get("artist") if info_dict else None) or (info_dict.get("creator") if info_dict else None) or (info_dict.get("uploader") if info_dict else None) or video.channel_title
            clean_artist = ""
            if artist_val:
                clean_artist = str(artist_val).strip()
                if clean_artist.endswith(" - Topic"):
                    clean_artist = clean_artist[:-8].strip()
            album_val = (info_dict.get("album") if info_dict else None) or video.extra_metadata.get("album")
            dur_val = (info_dict.get("duration") if info_dict else None) or video.duration_seconds
            if album_val and hasattr(video, "extra_metadata") and not video.extra_metadata.get("album"):
                video.extra_metadata["album"] = album_val

            # If Cover Art download is enabled:
            if getattr(self.settings, "download_cover_art", False) and not self._is_cancelled and (success or is_skipped):
                cov_start, cov_end = stage_ranges.get("cover_art", (media_end, media_end))
                try:
                    self.video_status_changed.emit(video.video_id, "Downloading (Cover Art)", "")
                    self.video_progress.emit(
                        video.video_id,
                        cov_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Cover Art",
                        "--:--",
                    )
                    CoverArtManager.download_cover_art(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        album=album_val,
                        info_dict=info_dict,
                        downloaded_covers=self._downloaded_cover_arts,
                    )
                except Exception as cover_err:
                    self.log_message.emit(f"[WARNING] Cover Art download error for {video.title}: {cover_err}")
                finally:
                    self.video_progress.emit(
                        video.video_id,
                        cov_end,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Cover Art",
                        "00:00",
                    )

            # If LRC Lyrics download is enabled:
            if getattr(self.settings, "download_lrc_lyrics", False) and not self._is_cancelled and (success or is_skipped):
                lyr_start, lyr_end = stage_ranges.get("lyrics", (media_end, media_end))
                try:
                    self.video_status_changed.emit(video.video_id, "Downloading (Lyrics)", "")
                    self.video_progress.emit(
                        video.video_id,
                        lyr_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Lyrics",
                        "--:--",
                    )
                    lyr_res = LyricsManager.download_lyrics(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        info_dict=info_dict,
                        artist=clean_artist,
                        title=title_val,
                        album=album_val,
                        duration=dur_val,
                    )
                    video._lrc_found = bool(lyr_res and lyr_res.get("success"))
                except Exception as lyr_err:
                    video._lrc_found = False
                    self.log_message.emit(f"[WARNING] LRC Lyrics download error for {video.title}: {lyr_err}")
                finally:
                    self.video_progress.emit(
                        video.video_id,
                        lyr_end,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Lyrics",
                        "00:00",
                    )

            # Embedding Cover Art / Metadata / Lyrics into Audio Tags
            should_embed_cover = bool(getattr(self.settings, "embed_cover_art", False))
            should_embed_meta = bool(getattr(self.settings, "embed_metadata", False))
            should_embed_lyrics = bool(getattr(self.settings, "embed_lyrics", False))

            if (should_embed_cover or should_embed_meta or should_embed_lyrics) and not self._is_cancelled and (success or is_skipped):
                embed_start, embed_end = stage_ranges.get("embed", (media_end, media_end))
                embed_parts = []
                if should_embed_cover:
                    embed_parts.append("Cover")
                if should_embed_meta:
                    embed_parts.append("Metadata")
                if should_embed_lyrics:
                    embed_parts.append("Lyrics")
                status_text = f"Embedding {' & '.join(embed_parts)}"
                try:
                    self.video_status_changed.emit(video.video_id, status_text, "")
                    self.video_progress.emit(
                        video.video_id,
                        embed_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        status_text,
                        "--:--",
                    )
                    from downloader.ytdlp_engine import is_final_output_file

                    VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov"}
                    stem = resolve_media_filename(
                        video.title,
                        video.video_id,
                        include_video_id=eff_include_id,
                        target_dir=video_target_dir,
                        number_prefix=num_prefix,
                    )

                    matching_audio_files = []
                    matching_video_files = []
                    if video_target_dir.is_dir():
                        for mf in video_target_dir.iterdir():
                            if not mf.is_file():
                                continue
                            ext = mf.suffix.lower()
                            if ext in SUPPORTED_COVER_ART_AUDIO_EXTENSIONS:
                                if mf.stem == stem or mf.stem.startswith(stem) or is_final_output_file(mf, video.video_id, title=video.title):
                                    matching_audio_files.append(mf)
                            elif ext in VIDEO_EXTS:
                                if mf.stem == stem or mf.stem.startswith(stem) or is_final_output_file(mf, video.video_id, title=video.title):
                                    matching_video_files.append(mf)

                    target_files = matching_audio_files + matching_video_files
                    if target_files:
                        mid_pct = embed_start + 0.45 * (embed_end - embed_start)
                        self.video_progress.emit(
                            video.video_id,
                            mid_pct,
                            last_media_downloaded_str,
                            last_media_total_str,
                            status_text,
                            "--:--",
                        )
                        meta = {}
                        if should_embed_meta:
                            if title_val:
                                meta["title"] = title_val
                            if clean_artist:
                                meta["artist"] = clean_artist
                            if album_val:
                                meta["album"] = album_val
                            album_artist_val = (info_dict.get("album_artist") if info_dict else None) or meta.get("artist")
                            if album_artist_val:
                                meta["album_artist"] = album_artist_val
                            date_val = (info_dict.get("release_date") if info_dict else None) or (info_dict.get("release_year") if info_dict else None)
                            if not date_val and info_dict and info_dict.get("upload_date"):
                                date_val = str(info_dict["upload_date"])[:4]
                            if date_val:
                                meta["date"] = str(date_val)
                            track_val = info_dict.get("track_number") if info_dict else None
                            if track_val is not None:
                                meta["track"] = str(track_val)
                            genre_val = (info_dict.get("genre") if info_dict else None) or video.extra_metadata.get("genre")
                            if genre_val:
                                meta["genre"] = str(genre_val)
                            isrc_val = info_dict.get("isrc") if info_dict else None
                            if isrc_val:
                                meta["isrc"] = str(isrc_val)

                        if should_embed_lyrics:
                            lrc_text = getattr(video, "_lrc_text", None)
                            if not lrc_text:
                                lrc_file = video_target_dir / f"{stem}.lrc"
                                if lrc_file.is_file():
                                    try:
                                        with open(lrc_file, "r", encoding="utf-8") as f:
                                            lrc_text = f.read()
                                    except Exception:
                                        pass
                            if not lrc_text:
                                lrc_text = LyricsManager.fetch_lyrics(
                                    title=title_val,
                                    artist=clean_artist or video.channel_title,
                                    album=album_val or "",
                                    duration=dur_val,
                                    channel_title=video.channel_title,
                                    video_id=video.video_id,
                                    log_callback=self.log_message.emit,
                                )
                                if lrc_text:
                                    video._lrc_text = lrc_text
                            if lrc_text:
                                video._lrc_found = True
                                meta["lyrics"] = lrc_text
                                meta["LYRICS"] = lrc_text
                                meta["unsyncedlyrics"] = lrc_text
                            else:
                                if not getattr(video, "_lrc_found", False):
                                    video._lrc_found = False

                        cover_embedded = False
                        if should_embed_cover:
                            cover_embedded = CoverArtManager.embed_cover_art_for_media_files(
                                video=video,
                                media_paths=target_files,
                                settings=video_settings,
                                target_dir=video_target_dir,
                                ffmpeg_location=ffmpeg_dir,
                                log_callback=self.log_message.emit,
                                cancel_check=self.is_cancelled,
                                metadata=meta if meta else None,
                            )

                        if (should_embed_meta or should_embed_lyrics) and not cover_embedded and meta:
                            CoverArtManager.embed_metadata_for_media_files(
                                media_paths=target_files,
                                metadata=meta,
                                ffmpeg_location=ffmpeg_dir,
                                log_callback=self.log_message.emit,
                                cancel_check=self.is_cancelled,
                            )
                    else:
                        self.log_message.emit(f"[Tag Embed] No supported output audio files found to embed tags for {video.title}")
                except Exception as embed_err:
                    self.log_message.emit(f"[WARNING] Tag embed error for {video.title}: {embed_err}")
                finally:
                    embed_finish_pct = min(99.0, embed_end) if not has_info else embed_end
                    self.video_progress.emit(
                        video.video_id,
                        embed_finish_pct,
                        last_media_downloaded_str,
                        last_media_total_str,
                        status_text,
                        "00:00",
                    )

            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index - 1:])
                break

            # If description / metadata / chapters are enabled:
            if has_info and not self._is_cancelled and (success or is_skipped):
                meta_start, meta_end = stage_ranges.get("metadata", (media_end, media_end))
                try:
                    self.video_status_changed.emit(video.video_id, "Saving (Metadata)", "")
                    self.video_progress.emit(
                        video.video_id,
                        meta_start,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Metadata",
                        "--:--",
                    )
                    InfoManager.save_video_info(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                        info_dict=info_dict,
                    )
                except Exception as info_err:
                    self.log_message.emit(f"[WARNING] Metadata save error for {video.title}: {info_err}")
                finally:
                    meta_finish_pct = min(99.0, meta_end)
                    self.video_progress.emit(
                        video.video_id,
                        meta_finish_pct,
                        last_media_downloaded_str,
                        last_media_total_str,
                        "Metadata",
                        "00:00",
                    )

            # Update Item Completion State
            if success:
                try:
                    self.inventory.update_media_download_status(
                        platform=video_platform,
                        media_id=video.video_id,
                        status=MediaDownloadStatus.COMPLETED,
                        output_path=str(video_target_dir),
                        selected_engine=route_decision.engine if 'route_decision' in locals() else 'yt-dlp',
                    )
                except Exception:
                    pass
                self._terminal_video_ids.add(video.video_id)
                if is_skipped:
                    video.status = VideoStatus.SKIPPED
                    video.error_reason = "Already in download archive"
                    skipped_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, "Already in download archive")
                    self.video_progress.emit(video.video_id, 100.0, last_media_downloaded_str, last_media_total_str, "Finished", "00:00")
                    self.log_message.emit(f"[SKIPPED] Video already exists: {video.title}")
                else:
                    video.status = VideoStatus.COMPLETED
                    video.error_reason = ""
                    completed_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.COMPLETED, "")
                    self.video_progress.emit(video.video_id, 100.0, last_media_downloaded_str, last_media_total_str, "Finished", "00:00")
                    self.log_message.emit(f"[COMPLETED] Successfully finished: {video.title}")
            else:
                self._terminal_video_ids.add(video.video_id)
                video.status = VideoStatus.FAILED
                failed_count += 1
                if download_error:
                    video.error_details = download_error
                    video.error_reason = download_error.user_message
                    if download_error.category in (ErrorCategory.HTTP_500, ErrorCategory.HTTP_502, ErrorCategory.HTTP_503):
                        user_msg = f"HTTP {download_error.http_status or 500} — Server temporarily unavailable after retries"
                        status_text = f"Failed — HTTP {download_error.http_status or 500}"
                        err_tooltip = f"{user_msg}\n\nSuggested action:\n{download_error.suggested_action}"
                        self.video_status_changed.emit(video.video_id, status_text, err_tooltip)
                        self.log_message.emit(f"[FAILED] {status_text} for '{video.title}': {user_msg}")
                    else:
                        status_text = download_error.concise_status
                        err_tooltip = f"{download_error.user_message}\n\nSuggested action:\n{download_error.suggested_action}"
                        self.video_status_changed.emit(video.video_id, status_text, err_tooltip)
                        self.log_message.emit(f"[FAILED] {status_text} for '{video.title}': {download_error.user_message}")
                else:
                    video.error_reason = last_error_msg
                    status_text = VideoStatus.FAILED
                    self.video_status_changed.emit(video.video_id, status_text, last_error_msg)
                    self.log_message.emit(f"[FAILED] {status_text} for '{video.title}': {last_error_msg}")
                # All retries have permanently failed: safely clean up partial files strictly for this video
                self.engine.safe_cleanup_partial_files(video_target_dir, video.video_id, title=video.title)
                self.video_progress.emit(video.video_id, 0.0, "-- MB", "-- MB", "Failed", "00:00")
                if index < total_videos and not self._is_cancelled:
                    self.log_message.emit(f"[QUEUE] Item {index}/{total_videos} failed. Continuing to next item in queue...")

            rem_c = max(0, total_videos - (completed_count + skipped_count + failed_count))
            ov_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
            self.overall_progress.emit(completed_count, skipped_count, failed_count, rem_c, ov_pct)

        # 8. Final Queue Wrap-up
        # Failsafe: Ensure every single video in self.videos reached a terminal state
        for vid in self.videos:
            if vid.video_id not in self._terminal_video_ids:
                self._terminal_video_ids.add(vid.video_id)
                if self._is_cancelled:
                    vid.status = VideoStatus.CANCELLED
                    vid.error_reason = "Cancelled by user"
                else:
                    vid.status = VideoStatus.FAILED
                    vid.error_reason = "Queue ended before processing"

        stats = self.get_queue_statistics()
        completed_count = stats["completed"]
        skipped_count = stats["skipped"]
        failed_count = stats["failed"]
        cancelled_count = stats["cancelled"]

        remaining_count = max(0, total_videos - (completed_count + skipped_count + failed_count + cancelled_count))
        final_pct = 100.0 if not self._is_cancelled else ((completed_count + skipped_count) / total_videos) * 100.0
        self.overall_progress.emit(completed_count, skipped_count, failed_count, remaining_count, final_pct)

        self.log_message.emit("=" * 65)
        self.log_message.emit(
            f"[SUMMARY] Finished: {completed_count} Completed | {skipped_count} Skipped "
            f"({stats['skipped_private']} Private, {stats['skipped_unavailable']} Unavailable, {stats['skipped_existing']} Existing) | "
            f"{failed_count} Failed" + (f" | {cancelled_count} Cancelled" if cancelled_count > 0 else "")
        )
        self.log_message.emit("=" * 65)
        try:
            self.inventory.close()
        except Exception:
            pass

        cleanup_temp_dir()
        self.queue_finished.emit(completed_count, skipped_count, failed_count, total_videos)

    def _mark_remaining_cancelled(self, remaining_videos: List[VideoItem]) -> None:
        """Marks any pending items as Cancelled when the user aborts."""
        for vid in remaining_videos:
            if vid.video_id not in self._terminal_video_ids:
                self._terminal_video_ids.add(vid.video_id)
                vid.status = VideoStatus.CANCELLED
                vid.error_reason = "Cancelled by user"
                self.video_status_changed.emit(vid.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                self.video_progress.emit(vid.video_id, 0.0, "-- MB", "-- MB", "Cancelled", "00:00")
                self.log_message.emit(f"[CANCELLED] Queue cancelled: {vid.title}")

    def get_queue_statistics(self) -> Dict[str, int]:
        """
        Derives authoritative, mutually exclusive counts for all videos in the queue:
        - total: Total videos selected in this queue run
        - completed / downloaded: Successfully downloaded items
        - skipped_private: Confirmed private videos skipped
        - skipped_unavailable: Confirmed unavailable videos skipped
        - skipped_existing: Videos skipped because already present in download archive
        - skipped: Total skipped items (private + unavailable + existing)
        - failed: Items failed due to other reasons
        - cancelled: Items cancelled by the user
        Every video is counted in exactly one category.
        """
        stats = {
            "total": len(self.videos),
            "completed": 0,
            "downloaded": 0,
            "skipped": 0,
            "skipped_private": 0,
            "skipped_unavailable": 0,
            "skipped_existing": 0,
            "failed": 0,
            "cancelled": 0,
        }

        for vid in self.videos:
            st = vid.status
            # 1. Cancelled
            if st == VideoStatus.CANCELLED or "cancel" in (vid.status or "").lower() or "cancel" in (vid.error_reason or "").lower():
                stats["cancelled"] += 1
            # 2. Completed / Downloaded
            elif st == VideoStatus.COMPLETED or st == "Completed":
                stats["completed"] += 1
                stats["downloaded"] += 1
            # 3. Skipped
            elif st == VideoStatus.SKIPPED or st == "Skipped" or vid.is_inaccessible:
                if vid.is_private or vid.extra_metadata.get("inaccessibility") == ErrorCategory.PRIVATE_VIDEO:
                    stats["skipped_private"] += 1
                    stats["skipped"] += 1
                elif vid.is_unavailable or vid.extra_metadata.get("inaccessibility") == ErrorCategory.VIDEO_UNAVAILABLE:
                    stats["skipped_unavailable"] += 1
                    stats["skipped"] += 1
                else:
                    stats["skipped_existing"] += 1
                    stats["skipped"] += 1
            # 4. Failed
            elif st == VideoStatus.FAILED or st == "Failed":
                if vid.is_private or (vid.error_details and getattr(vid.error_details, "category", None) == ErrorCategory.PRIVATE_VIDEO):
                    stats["skipped_private"] += 1
                    stats["skipped"] += 1
                elif vid.is_unavailable or (vid.error_details and getattr(vid.error_details, "category", None) == ErrorCategory.VIDEO_UNAVAILABLE):
                    stats["skipped_unavailable"] += 1
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
            # 5. Fallback for un-finalized items
            else:
                if self._is_cancelled:
                    stats["cancelled"] += 1
                else:
                    stats["failed"] += 1

        download_lrc = bool(getattr(self.settings, "download_lrc_lyrics", False))
        embed_lyrics = bool(getattr(self.settings, "embed_lyrics", False))
        lyrics_enabled = download_lrc or embed_lyrics
        lyrics_not_found = 0

        if lyrics_enabled:
            for vid in self.videos:
                if vid.status in (VideoStatus.COMPLETED, VideoStatus.SKIPPED):
                    if vid.is_private or vid.is_unavailable:
                        continue
                    has_lrc = getattr(vid, "_lrc_found", None)
                    if has_lrc is False or (has_lrc is None and not getattr(vid, "_lrc_text", None)):
                        lyrics_not_found += 1

        stats["lyrics_enabled"] = lyrics_enabled
        stats["download_lrc_enabled"] = download_lrc
        stats["embed_lyrics_enabled"] = embed_lyrics
        stats["lyrics_not_found"] = lyrics_not_found

        return stats

    def get_destination_folder(self) -> Path:
        """
        Returns the resolved on-disk destination folder for the downloaded files.
        Prioritizes the channel subfolder or video directory that actually exists on disk.
        """
        if self._resolved_target_dir and self._resolved_target_dir.exists():
            return self._resolved_target_dir
        if self._last_video_target_dir and self._last_video_target_dir.exists():
            return self._last_video_target_dir
        base = Path(self.settings.download_folder)
        if base.exists():
            return base
        return self._resolved_target_dir or base
