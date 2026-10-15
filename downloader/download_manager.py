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
from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode, SubtitleSource
from core.paths import (
    get_archive_file,
    resolve_video_output_dir,
    sanitize_filename,
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

        if kernel32.Process32First(h_snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32ParentProcessID == current_pid:
                    child_pid = entry.th32ProcessID
                    exe_name = entry.szExeFile.decode('utf-8', errors='ignore').lower()
                    if any(target in exe_name for target in ('deno', 'ffmpeg', 'ffprobe', 'yt-dlp')):
                        h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, child_pid)
                        if h_proc:
                            kernel32.TerminateProcess(h_proc, 1)
                            kernel32.CloseHandle(h_proc)
                if not kernel32.Process32Next(h_snapshot, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(h_snapshot)
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

        # Thread synchronization and control flags
        self._is_cancelled = False
        self._is_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Initially unpaused

    def cancel(self) -> None:
        """Flags the download queue for cancellation and terminates child worker processes."""
        self._is_cancelled = True
        self._is_paused = False
        self._pause_event.set()  # Unblock if paused so thread can exit cleanly
        kill_child_processes()
        self.log_message.emit("[CANCEL] Cancellation requested. Stopping download and child processes...")

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

    def run(self) -> None:
        """Main worker thread loop executing sequential downloads."""
        total_videos = len(self.videos)
        if total_videos == 0:
            self.queue_finished.emit(0, 0, 0, 0)
            return

        self.queue_started.emit(total_videos)
        self.log_message.emit("=" * 65)
        self.log_message.emit(f"[INFO] Download Queue Started: {total_videos} video(s)")
        cwd, safe_temp = ensure_safe_environment()
        self.log_message.emit(f"[INFO] Working Directory: {cwd}")
        self.log_message.emit(f"[INFO] Temporary Directory: {safe_temp}")
        mode_val = self.settings.download_mode or DownloadMode.VIDEO_AND_AUDIO
        self.log_message.emit(f"[CONFIG] Download Mode : {mode_val}")
        if mode_val in (DownloadMode.VIDEO_ONLY, DownloadMode.VIDEO_AND_AUDIO):
            self.log_message.emit(f"[CONFIG] Video Format  : {self.settings.format} ({self.settings.quality}, {self.settings.bitrate})")
        # Log subtitle configuration if active
        if self.settings.download_subtitles:
            self.log_message.emit(f"[CONFIG] Subtitle      : {self.settings.subtitle_language} ({self.settings.subtitle_source}, {self.settings.subtitle_format})")
        # Log thumbnail configuration if active
        if self.settings.download_thumbnail:
            self.log_message.emit(f"[CONFIG] Thumbnail     : Yes ({self.settings.thumbnail_format})")
        # Log metadata / description / chapters if active
        if self.settings.save_description:
            self.log_message.emit("[CONFIG] Description   : Yes (.description)")
        if self.settings.save_metadata:
            self.log_message.emit("[CONFIG] Metadata      : Yes (.metadata.txt)")
        if self.settings.save_chapters:
            self.log_message.emit("[CONFIG] Chapters      : Yes (.chapters.txt)")
        self.log_message.emit(f"[CONFIG] Channel Folder : {'Yes' if self.settings.create_channel_folder else 'No'}")
        self.log_message.emit(f"[CONFIG] Video Folders  : {'Yes' if self.settings.create_individual_video_folders else 'No'}")
        self.log_message.emit(f"[CONFIG] Video ID in File: {'Yes' if self.settings.include_video_id_in_filename else 'No'}")
        self.log_message.emit(f"[CONFIG] Skip Existing : {'Yes' if self.settings.skip_existing else 'No'}")

        # 1. Resolve Target Directory & Create Channel Subfolder if enabled
        base_dir = Path(self.settings.download_folder)
        if self.settings.create_channel_folder and self.settings.channel_title:
            clean_channel = re.sub(r'[\\/*?:"<>|]', "_", self.settings.channel_title).strip()
            target_dir = base_dir / clean_channel
        else:
            target_dir = base_dir

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

            remaining_count = total_videos - (completed_count + skipped_count + failed_count)
            overall_pct = ((completed_count + skipped_count + failed_count) / total_videos) * 100.0
            self.overall_progress.emit(completed_count, skipped_count, failed_count, remaining_count, overall_pct)

            self.video_started.emit(video.video_id, video.title, index, total_videos)
            self.log_message.emit(f"\n[DOWNLOAD] ({index}/{total_videos}) Starting: {video.title}")

            # Resolve the output directory for this video
            video_target_dir = resolve_video_output_dir(
                base_download_dir=base_dir,
                channel_title=self.settings.channel_title,
                create_channel_folder=self.settings.create_channel_folder,
                video_title=video.title,
                video_id=video.video_id,
                create_individual_video_folders=self.settings.create_individual_video_folders,
                duplicate_titles_in_queue=duplicate_titles,
            )

            # Resolve effective video ID filename setting with collision protection
            eff_include_id = should_include_video_id(
                video_title=video.title,
                video_id=video.video_id,
                include_video_id_setting=self.settings.include_video_id_in_filename,
                create_individual_video_folders=self.settings.create_individual_video_folders,
                duplicate_titles_in_queue=duplicate_titles,
                target_dir=video_target_dir,
            )
            video_settings = replace(self.settings, include_video_id_in_filename=eff_include_id)
            from core.platform import PlatformRegistry
            video_platform = getattr(video, "platform", "youtube")
            if not PlatformRegistry.is_available(video_platform):
                from core.error_classifier import ErrorClassifier
                err = ErrorClassifier.for_unavailable_platform(video_platform, video_id=video.video_id, video_title=video.title)
                self.log_message.emit(f"[BLOCKED] {err.title}: {err.user_message}")
                failed_count += 1
                self.video_status_changed.emit(video.video_id, VideoStatus.FAILED, err.user_message)
                continue

            adapter = PlatformRegistry.get_adapter(video_platform)
            supports_cookies = (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file) if adapter else (video_platform.lower() == "youtube")
            if not supports_cookies:
                video_settings = replace(video_settings, browser_cookies="none")

            try:
                video_target_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.log_message.emit(f"[ERROR] Could not create folder for {video.title}: {e}")
                failed_count += 1
                self.video_status_changed.emit(video.video_id, VideoStatus.FAILED, f"Folder error: {e}")
                continue

            if self.settings.create_individual_video_folders:
                self.log_message.emit(f"[FOLDER] Video folder: {video_target_dir}")

            # Define progress callback for this video
            def handle_video_progress(data: Dict[str, Any]) -> None:
                status_val = data.get("status")
                step_val = data.get("step", "")
                if status_val == "downloading":
                    status_text = VideoStatus.DOWNLOADING if not step_val else f"Downloading ({step_val})"
                    self.video_status_changed.emit(video.video_id, status_text, "")
                    self.video_progress.emit(
                        video.video_id,
                        data.get("percent", 0.0),
                        data.get("downloaded_str", "-- MB"),
                        data.get("total_str", "-- MB"),
                        data.get("speed", "-- MB/s"),
                        data.get("eta", "--:--"),
                    )
                elif status_val == "processing":
                    proc_text = VideoStatus.PROCESSING if not step_val else f"Processing ({step_val})"
                    self.video_status_changed.emit(video.video_id, proc_text, "")
                    self.video_progress.emit(
                        video.video_id,
                        data.get("percent", 100.0),
                        data.get("downloaded_str", "-- MB"),
                        data.get("total_str", "-- MB"),
                        "FFmpeg Processing",
                        "00:00",
                    )
                    self.log_message.emit(f"[PROCESSING] FFmpeg processing ({step_val or 'media'}): {video.title}")

            # -------------------------------------------------------------
            # Branch A: ASSETS ONLY MODE
            # -------------------------------------------------------------
            if is_sub_only:
                self.video_status_changed.emit(video.video_id, "Downloading Assets", "")
                self.video_progress.emit(video.video_id, 30.0, "-- KB", "-- KB", "Fetching Assets", "--:--")

                has_sub = bool(self.settings.download_subtitles)
                has_thumb = bool(self.settings.download_thumbnail)
                has_info = bool(self.settings.save_description or self.settings.save_metadata or self.settings.save_chapters)

                sub_res = None
                thumb_res = None
                info_res = None

                # 1. Subtitles (only if explicitly enabled)
                if has_sub and not self._is_cancelled:
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

                if self._is_cancelled:
                    self._mark_remaining_cancelled(self.videos[index - 1:])
                    break

                # 2. Thumbnail
                if has_thumb and not self._is_cancelled:
                    thumb_res = ThumbnailManager.download_thumbnail(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )

                if self._is_cancelled:
                    self._mark_remaining_cancelled(self.videos[index - 1:])
                    break

                # 3. Description / Metadata / Chapters
                if has_info and not self._is_cancelled:
                    info_res = InfoManager.save_video_info(
                        video=video,
                        settings=video_settings,
                        target_dir=video_target_dir,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )

                # Collect results
                results = []
                if has_sub and sub_res:
                    results.append(("subtitle", sub_res))
                if has_thumb and thumb_res:
                    results.append(("thumbnail", thumb_res))
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
                    failed_count += 1
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
                    self.video_status_changed.emit(video.video_id, sub_dl_err.concise_status, sub_dl_err.user_message)
                    self.log_message.emit(f"[FAILED] Asset download failed for {video.title}: {sub_dl_err.user_message}")
                elif any_success:
                    completed_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.COMPLETED, "")
                    self.video_progress.emit(video.video_id, 100.0, "-- KB", "-- KB", "Finished", "00:00")
                    self.log_message.emit(f"[COMPLETED] Assets downloaded: {video.title}")
                elif all_skipped:
                    skipped_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, "Assets already exist on disk")
                    self.log_message.emit(f"[SKIPPED] Assets already exist: {video.title}")
                else:
                    skipped_count += 1
                    self.video_status_changed.emit(video.video_id, "No Subtitle", sub_res.get("error", "") if sub_res else "")
                    self.log_message.emit(f"[SUBTITLE NOTICE] {video.title}: No subtitles available")
                continue

            # -------------------------------------------------------------
            # Branch B: VIDEO / AUDIO / VIDEO + AUDIO MODES
            # -------------------------------------------------------------
            success = False
            is_skipped = False
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
                    self.video_status_changed.emit(video.video_id, retry_label, last_error_msg)
                    self.log_message.emit(f"[RETRY] Attempt {attempt}/{self.MAX_RETRIES} for: {video.title}")

                try:
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
                    self.video_status_changed.emit(video.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                    self.log_message.emit(f"[CANCELLED] Download cancelled: {video.title}")
                    break

                except Exception as e:
                    if self._is_cancelled or isinstance(e, DownloadCancelledException) or "cancelled" in str(e).lower() or "returncode: 1" in str(e):
                        self._is_cancelled = True
                        self.video_status_changed.emit(video.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                        self.log_message.emit(f"[CANCELLED] Download cancelled: {video.title}")
                        break

                    last_error_msg = str(e)
                    stage = getattr(e, "stage", None)
                    raw_err = getattr(e, "raw_error", last_error_msg)
                    download_error = ErrorClassifier.classify(
                        raw_error=raw_err,
                        component="yt-dlp",
                        stage=stage,
                        video_id=video.video_id,
                        video_title=video.title,
                        platform=getattr(video, "platform", "youtube"),
                    )
                    ErrorTracker.record_error(download_error)
                    video.error_details = download_error
                    self.log_message.emit(f"[WARNING] Attempt {attempt} failed: {last_error_msg}")

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

            # If subtitles are also enabled for media downloads:
            if self.settings.download_subtitles and (success or is_skipped):
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

            # If thumbnail is enabled:
            if self.settings.download_thumbnail and not self._is_cancelled and (success or is_skipped):
                ThumbnailManager.download_thumbnail(
                    video=video,
                    settings=video_settings,
                    target_dir=video_target_dir,
                    ffmpeg_location=ffmpeg_dir,
                    log_callback=self.log_message.emit,
                    cancel_check=self.is_cancelled,
                    info_dict=info_dict,
                )

            # If description / metadata / chapters are enabled:
            if (self.settings.save_description or self.settings.save_metadata or self.settings.save_chapters) and not self._is_cancelled and (success or is_skipped):
                InfoManager.save_video_info(
                    video=video,
                    settings=video_settings,
                    target_dir=video_target_dir,
                    log_callback=self.log_message.emit,
                    cancel_check=self.is_cancelled,
                    info_dict=info_dict,
                )

            # Update Item Completion State
            if success:
                if is_skipped:
                    skipped_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.SKIPPED, "Already in download archive")
                    self.log_message.emit(f"[SKIPPED] Video already exists: {video.title}")
                else:
                    completed_count += 1
                    self.video_status_changed.emit(video.video_id, VideoStatus.COMPLETED, "")
                    self.log_message.emit(f"[COMPLETED] Successfully finished: {video.title}")
            else:
                failed_count += 1
                if download_error:
                    video.error_details = download_error
                    status_text = download_error.concise_status
                    err_tooltip = f"{download_error.user_message}\n\nSuggested action:\n{download_error.suggested_action}"
                    self.video_status_changed.emit(video.video_id, status_text, err_tooltip)
                    self.log_message.emit(f"[FAILED] {status_text} for '{video.title}': {download_error.user_message}")
                else:
                    status_text = VideoStatus.FAILED
                    self.video_status_changed.emit(video.video_id, status_text, last_error_msg)
                    self.log_message.emit(f"[FAILED] {status_text} for '{video.title}': {last_error_msg}")


        # 8. Final Queue Wrap-up
        remaining_count = max(0, total_videos - (completed_count + skipped_count + failed_count))
        final_pct = 100.0 if not self._is_cancelled else ((completed_count + skipped_count) / total_videos) * 100.0
        self.overall_progress.emit(completed_count, skipped_count, failed_count, remaining_count, final_pct)

        self.log_message.emit("=" * 65)
        self.log_message.emit(f"[SUMMARY] Finished: {completed_count} Completed | {skipped_count} Skipped | {failed_count} Failed")
        self.log_message.emit("=" * 65)

        cleanup_temp_dir()
        self.queue_finished.emit(completed_count, skipped_count, failed_count, total_videos)

    def _mark_remaining_cancelled(self, remaining_videos: List[VideoItem]) -> None:
        """Marks any pending items as Cancelled when the user aborts."""
        for vid in remaining_videos:
            self.video_status_changed.emit(vid.video_id, VideoStatus.CANCELLED, "Cancelled by user")
            self.log_message.emit(f"[CANCELLED] Queue cancelled: {vid.title}")
