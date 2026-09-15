"""
downloader_stub.py
Downloader service stub and interface for Phase 1.

ARCHITECTURE NOTE:
In Phase 1, this class provides mock data and simulated progress so that
the desktop GUI can be thoroughly tested without downloading actual videos.
In Phase 2, this class will be connected to a QThread worker that invokes
yt-dlp to perform real extraction, metadata fetching, and video downloads.
"""

from typing import List, Optional
from PySide6.QtCore import QObject, Signal, QTimer
from core.models import VideoItem, DownloadSettings


class DownloaderService(QObject):
    """
    Service responsible for scanning YouTube channels and downloading videos.
    
    Signals:
        channel_scanned (list): Emitted when channel scanning is complete with VideoItem objects.
        progress_updated (str, int, str, str): Emitted during download with
            (video_title, progress_percentage, speed_str, eta_str).
        video_status_changed (str, str): Emitted when a video's status changes (video_id, status).
        download_started (int): Emitted when batch download begins with total video count.
        download_finished (int): Emitted when batch download ends with completed count.
        log_message (str): Emitted to send activity logs to the GUI log panel.
    """

    channel_scanned = Signal(list)
    progress_updated = Signal(str, int, str, str)
    video_status_changed = Signal(str, str)
    download_started = Signal(int)
    download_finished = Signal(int)
    log_message = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._is_downloading = False
        self._queue: List[VideoItem] = []
        self._current_index = 0
        self._current_percent = 0

        # Timer to simulate download progress in Phase 1 without blocking the UI
        self._mock_timer = QTimer(self)
        self._mock_timer.setInterval(120)  # Update every 120ms
        self._mock_timer.timeout.connect(self._simulation_tick)

    def scan_channel(self, channel_url: str) -> None:
        """
        Scans a YouTube channel URL to retrieve the list of available videos.
        In Phase 1, this validates the URL format and provides mock videos.
        """
        cleaned_url = channel_url.strip()
        if not cleaned_url:
            self.log_message.emit("[WARNING] Please enter a valid YouTube channel URL before scanning.")
            return

        self.log_message.emit(f"[INFO] Scanning channel: {cleaned_url}")
        self.log_message.emit("[INFO] Contacting YouTube (Phase 1 mock scan)...")

        # Mock videos representing realistic YouTube channel content
        mock_videos = [
            VideoItem(
                video_id="vid_001",
                title="Python Full Course for Beginners [2026 Edition]",
                duration="04:15:20",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
            VideoItem(
                video_id="vid_002",
                title="Building Modern Desktop GUIs with PySide6 & Qt",
                duration="00:28:45",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
            VideoItem(
                video_id="vid_003",
                title="Mastering Asynchronous Programming in Python",
                duration="00:19:12",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
            VideoItem(
                video_id="vid_004",
                title="Clean Architecture for Python Desktop Applications",
                duration="00:34:05",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
            VideoItem(
                video_id="vid_005",
                title="Packaging Python Apps into Standalone Windows .EXE with PyInstaller",
                duration="00:16:30",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
            VideoItem(
                video_id="vid_006",
                title="How yt-dlp Works Under the Hood: Streams, Codecs & Formats",
                duration="00:22:18",
                status="Ready",
                url=f"{cleaned_url}/videos",
                selected=True,
            ),
        ]

        self.channel_scanned.emit(mock_videos)
        self.log_message.emit(f"[SUCCESS] Scan completed. Found {len(mock_videos)} videos in channel.")

    def start_download(self, videos: List[VideoItem], settings: DownloadSettings) -> None:
        """
        Starts downloading the selected videos.
        In Phase 1, this runs a simulated progress loop to demonstrate the UI responsiveness.
        """
        if self._is_downloading:
            self.log_message.emit("[WARNING] A download process is already in progress.")
            return

        if not videos:
            self.log_message.emit("[WARNING] No videos selected. Please check at least one video to download.")
            return

        self._queue = [v for v in videos if v.selected]
        if not self._queue:
            self.log_message.emit("[WARNING] All selected videos are unchecked. Check at least one video.")
            return

        self._is_downloading = True
        self._current_index = 0
        self._current_percent = 0

        self.log_message.emit("=" * 60)
        self.log_message.emit(f"[INFO] Download started for {len(self._queue)} video(s).")
        self.log_message.emit(f"[CONFIG] Target Folder : {settings.download_folder}")
        self.log_message.emit(f"[CONFIG] Target Format : {settings.format}")
        self.log_message.emit(f"[CONFIG] Target Quality: {settings.quality}")
        self.log_message.emit(f"[CONFIG] Target Bitrate: {settings.bitrate}")
        self.log_message.emit("[INFO] Note: Phase 1 is a GUI prototype. yt-dlp engine will be connected in Phase 2.")
        self.log_message.emit("=" * 60)

        self.download_started.emit(len(self._queue))

        # Mark first video as "Downloading"
        current_vid = self._queue[self._current_index]
        self.video_status_changed.emit(current_vid.video_id, "Downloading")
        self.log_message.emit(f"[DOWNLOADING] ({self._current_index + 1}/{len(self._queue)}) {current_vid.title}")

        # Start timer simulation
        self._mock_timer.start()

    def cancel_download(self) -> None:
        """Cancels an ongoing download process."""
        if not self._is_downloading:
            return

        self._mock_timer.stop()
        self._is_downloading = False

        if self._current_index < len(self._queue):
            current_vid = self._queue[self._current_index]
            self.video_status_changed.emit(current_vid.video_id, "Cancelled")

        self.log_message.emit("[INFO] Download operation cancelled by user.")
        self.progress_updated.emit("Download cancelled", 0, "-- MB/s", "--:--")
        self.download_finished.emit(self._current_index)

    def _simulation_tick(self) -> None:
        """
        Internal timer callback simulating download increments, speed, and ETA.
        """
        if not self._is_downloading or self._current_index >= len(self._queue):
            self._finish_all_downloads()
            return

        current_vid = self._queue[self._current_index]
        self._current_percent += 10

        # Simulated dynamic speed and ETA calculations
        simulated_speed = f"{14.5 + (self._current_percent % 5) * 1.2:.1f} MB/s"
        remaining_seconds = max(0, int((100 - self._current_percent) * 0.15))
        simulated_eta = f"00:{remaining_seconds:02d}"

        self.progress_updated.emit(
            current_vid.title,
            min(100, self._current_percent),
            simulated_speed,
            simulated_eta,
        )

        if self._current_percent >= 100:
            # Mark video as completed
            self.video_status_changed.emit(current_vid.video_id, "Completed")
            self.log_message.emit(f"[COMPLETED] Finished: {current_vid.title}")

            # Move to next video
            self._current_index += 1
            self._current_percent = 0

            if self._current_index < len(self._queue):
                next_vid = self._queue[self._current_index]
                self.video_status_changed.emit(next_vid.video_id, "Downloading")
                self.log_message.emit(f"[DOWNLOADING] ({self._current_index + 1}/{len(self._queue)}) {next_vid.title}")
            else:
                self._finish_all_downloads()

    def _finish_all_downloads(self) -> None:
        """Finalizes the simulated download queue."""
        self._mock_timer.stop()
        self._is_downloading = False
        self.progress_updated.emit("All selected downloads finished!", 100, "0.0 MB/s", "00:00")
        self.log_message.emit(f"[SUCCESS] All {len(self._queue)} video(s) processed successfully!")
        self.download_finished.emit(len(self._queue))
