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
from typing import List, Optional, Dict, Any

from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.paths import get_archive_file
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
)
from downloader.ffmpeg_checker import FFmpegChecker


class DownloadManager(QThread):
    """
    Background worker thread managing sequential video downloads.

    Signals:
        queue_started (int): Emitted when batch starts with total selected video count.
        video_started (str, str, int, int): (video_id, title, current_index, total_count).
        video_progress (str, float, str, str, str, str):
            (video_id, percent, downloaded_size, total_size, speed, eta).
        video_status_changed (str, str, str): (video_id, new_status, error_reason).
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
        """Flags the download queue for cancellation."""
        self._is_cancelled = True
        self._is_paused = False
        self._pause_event.set()  # Unblock if paused so thread can exit cleanly
        self.log_message.emit("[CANCEL] Cancellation requested. Stopping download...")

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

    def run(self) -> None:
        """Main worker thread loop executing sequential downloads."""
        total_videos = len(self.videos)
        if total_videos == 0:
            self.queue_finished.emit(0, 0, 0, 0)
            return

        self.queue_started.emit(total_videos)
        self.log_message.emit("=" * 65)
        self.log_message.emit(f"[INFO] Download Queue Started: {total_videos} video(s)")
        mode_val = self.settings.download_mode or DownloadMode.VIDEO_AND_AUDIO
        self.log_message.emit(f"[CONFIG] Download Mode : {mode_val}")
        if mode_val in (DownloadMode.VIDEO_ONLY, DownloadMode.VIDEO_AND_AUDIO):
            self.log_message.emit(f"[CONFIG] Video Format  : {self.settings.format} ({self.settings.quality}, {self.settings.bitrate})")
        if mode_val in (DownloadMode.AUDIO_ONLY, DownloadMode.VIDEO_AND_AUDIO):
            self.log_message.emit(f"[CONFIG] Audio Format  : {self.settings.audio_format} ({self.settings.audio_bitrate})")
        self.log_message.emit(f"[CONFIG] Skip Existing : {'Yes' if self.settings.skip_existing else 'No'}")

        # 1. Resolve Target Directory & Create Channel Subfolder if enabled
        base_dir = Path(self.settings.download_folder)
        if self.settings.create_channel_folder and self.settings.channel_title:
            # Sanitize channel title for folder name
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
            self.log_message.emit("[WARNING] FFmpeg not found. Separate video/audio streams may not merge cleanly.")

        # 3. Resolve Download Archive path
        archive_file = get_archive_file() if self.settings.skip_existing else None
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

        # 5. Sequential Download Loop
        for index, video in enumerate(self.videos, start=1):
            # Check for cancellation before starting item
            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index - 1:])
                break

            # Handle pause state (wait until unpaused or cancelled)
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

            # 6. Retry Loop (Up to MAX_RETRIES)
            success = False
            is_skipped = False
            last_error_msg = ""

            for attempt in range(1, self.MAX_RETRIES + 1):
                if self._is_cancelled:
                    break

                if attempt > 1:
                    retry_status = f"Retry {attempt}/{self.MAX_RETRIES}"
                    self.video_status_changed.emit(video.video_id, retry_status, last_error_msg)
                    self.log_message.emit(f"[RETRY] Attempt {attempt}/{self.MAX_RETRIES} for: {video.title}")
                    time.sleep(2.0)  # Brief delay between retry attempts

                try:
                    res = self.engine.download_single_video(
                        video=video,
                        settings=self.settings,
                        target_dir=target_dir,
                        ffmpeg_location=ffmpeg_dir,
                        archive_file=archive_file,
                        progress_callback=handle_video_progress,
                        log_callback=self.log_message.emit,
                        cancel_check=self.is_cancelled,
                    )
                    success = res.get("success", False)
                    is_skipped = res.get("skipped", False)
                    break

                except DownloadCancelledException:
                    self._is_cancelled = True
                    self.video_status_changed.emit(video.video_id, VideoStatus.CANCELLED, "Cancelled by user")
                    self.log_message.emit(f"[CANCELLED] Download cancelled: {video.title}")
                    break

                except Exception as e:
                    last_error_msg = str(e)
                    self.log_message.emit(f"[WARNING] Attempt {attempt} failed: {last_error_msg}")

            if self._is_cancelled:
                self._mark_remaining_cancelled(self.videos[index:])
                break

            # 7. Update Item Completion State
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
                self.video_status_changed.emit(video.video_id, VideoStatus.FAILED, last_error_msg)
                self.log_message.emit(f"[FAILED] Could not download after {self.MAX_RETRIES} attempts: {video.title}")

        # 8. Final Queue Wrap-up
        remaining_count = max(0, total_videos - (completed_count + skipped_count + failed_count))
        final_pct = 100.0 if not self._is_cancelled else ((completed_count + skipped_count) / total_videos) * 100.0
        self.overall_progress.emit(completed_count, skipped_count, failed_count, remaining_count, final_pct)

        self.log_message.emit("=" * 65)
        self.log_message.emit(f"[SUMMARY] Finished: {completed_count} Completed | {skipped_count} Skipped | {failed_count} Failed")
        self.log_message.emit("=" * 65)

        self.queue_finished.emit(completed_count, skipped_count, failed_count, total_videos)

    def _mark_remaining_cancelled(self, remaining_videos: List[VideoItem]) -> None:
        """Marks any pending items as Cancelled when the user aborts."""
        for vid in remaining_videos:
            self.video_status_changed.emit(vid.video_id, VideoStatus.CANCELLED, "Cancelled by user")
            self.log_message.emit(f"[CANCELLED] Queue cancelled: {vid.title}")
