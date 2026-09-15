"""
main_window.py
Primary application window for Channel Harvest.

Integrates:
- Channel URL input & validation
- Non-blocking background scanning with ChannelScanWorker (QThread)
- Sequential download queue with DownloadManager (QThread)
- Intelligent stream selection and FFmpeg merging (FormatSelector)
- Real-time progress hooks (speed, ETA, downloaded size, percentage)
- Pause, Resume, and Cancellation controls
- Skip already downloaded videos via persistent download archive
- Persistent settings in %APPDATA%/ChannelHarvest/settings.json
- Summary report modal on completion
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import yt_dlp
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QProgressBar,
    QPlainTextEdit,
    QGroupBox,
    QCheckBox,
    QFileDialog,
    QStatusBar,
    QMessageBox,
    QScrollArea,
    QFrame,
)

from core.models import DownloadSettings, VideoItem, VideoStatus, DownloadMode
from core.settings import SettingsManager
from core.paths import get_archive_file, get_logo_file
from downloader.ytdlp_engine import ChannelScanWorker, YtDlpEngine
from downloader.download_manager import DownloadManager
from downloader.ffmpeg_checker import FFmpegChecker
from gui.video_table import VideoTableWidget
from gui.summary_dialog import SummaryDialog
from gui.settings_dialog import SettingsDialog, get_settings_icon
from gui.styles import ThemeManager


class MainWindow(QMainWindow):
    """
    Main application window managing UI layout, background workers,
    and user interactions.
    """

    def __init__(self):
        super().__init__()

        # 1. Initialize settings manager and load saved configuration
        self.settings_manager = SettingsManager()
        self._current_channel_title: str = ""

        # References to active background workers
        self._scan_worker: Optional[ChannelScanWorker] = None
        self._download_manager: Optional[DownloadManager] = None
        self._silent_update_worker = None

        # Register theme listener to dynamically update icons on theme switch
        ThemeManager.register_listener(self._on_theme_changed)

        # Window configuration
        self.setWindowTitle("Channel Harvest")
        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        saved_w = self.settings_manager.get("window_width", 1000)
        saved_h = self.settings_manager.get("window_height", 780)

        # Ensure window doesn't exceed current monitor available geometry
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            saved_w = min(saved_w, avail.width() - 40)
            saved_h = min(saved_h, avail.height() - 60)

        self.resize(saved_w, saved_h)
        # Flexible minimum size allowing free resizing on any display (including 1366x768 or 1080p @ 125% DPI)
        self.setMinimumSize(660, 460)

        # 2. Build GUI sections
        self._init_ui()

        # 3. Apply saved settings to controls
        self._load_saved_settings()

        # 4. Check environment (FFmpeg and yt-dlp versions)
        self._check_environment_status()

        # 5. Set initial button states
        self._set_ui_state("idle")

        # Initial Welcome Logs
        self.log("[READY] Channel Harvest initialized.")
        archive_path = get_archive_file()
        self.log(f"[INFO] Download archive active: {archive_path.name}")

        # Check for yt-dlp updates in background if enabled and > 24h since last check
        self._check_ytdlp_updates_silent()

    def _init_ui(self) -> None:
        """Initializes and arranges all UI sections in responsive layouts."""
        # Scroll area allows the window to shrink smoothly on any screen resolution
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(scroll_area)

        central_widget = QWidget()
        scroll_area.setWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 10, 14, 8)
        main_layout.setSpacing(6)

        # 1. Header Banner with Environment Status
        header_layout = self._create_header_section()
        main_layout.addLayout(header_layout)

        # 2. Channel URL Input Section
        url_group = self._create_url_section()
        main_layout.addWidget(url_group)

        # 3. Video List Table Section (expands most when window is resized)
        video_group = self._create_video_list_section()
        main_layout.addWidget(video_group, stretch=1)

        # 4. Download Settings Section
        settings_group = self._create_settings_section()
        main_layout.addWidget(settings_group)

        # 5. Action Controls (Download, Pause, Resume, Cancel, Open Folder)
        controls_layout = self._create_controls_section()
        main_layout.addLayout(controls_layout)

        # 6. Download Progress Section (Current item + Overall queue)
        progress_group = self._create_progress_section()
        main_layout.addWidget(progress_group)

        # 7. Activity Log Panel Section (flexible expansion)
        log_group = self._create_log_section()
        main_layout.addWidget(log_group, stretch=0)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready • Paste a YouTube channel URL and click 'Scan Channel'")

    def _create_header_section(self) -> QHBoxLayout:
        """Creates the top header title with application logo, title, subtitle, and badges."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(14)

        # Brand Container (Logo on left + Titles)
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(12)
        brand_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 1. Application Logo Icon
        logo_file = get_logo_file()
        if logo_file.exists():
            self.logo_label = QLabel()
            pixmap = QPixmap(str(logo_file))
            if not pixmap.isNull():
                scaled_pix = pixmap.scaled(
                    38,
                    38,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.logo_label.setPixmap(scaled_pix)
                self.logo_label.setFixedSize(38, 38)
                brand_layout.addWidget(self.logo_label)

        # 2. Prominent Main Title & Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_label = QLabel("Channel Harvest")
        title_label.setObjectName("appTitleLabel")
        title_box.addWidget(title_label)

        subtitle_label = QLabel("Harvest your channel. Keep every video.")
        subtitle_label.setObjectName("appSubtitleLabel")
        title_box.addWidget(subtitle_label)

        brand_layout.addLayout(title_box)
        layout.addLayout(brand_layout, stretch=1)

        # 3. Settings Icon Button (Top-Right)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setIcon(get_settings_icon())
        self.settings_btn.setIconSize(QSize(16, 16))
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        layout.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return layout

    def _create_url_section(self) -> QGroupBox:
        """Creates the channel URL input field and 'Scan Channel' button."""
        group = QGroupBox("CHANNEL")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        label = QLabel("Channel URL:")
        label.setStyleSheet("font-weight: 600;")
        layout.addWidget(label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/@channel or playlist URL")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.setMinimumHeight(34)
        self.url_input.returnPressed.connect(self._on_scan_clicked)
        layout.addWidget(self.url_input, stretch=1)

        self.scan_btn = QPushButton("Scan Channel")
        self.scan_btn.setObjectName("scanButton")
        self.scan_btn.setMinimumHeight(34)
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        layout.addWidget(self.scan_btn)

        return group

    def _create_video_list_section(self) -> QGroupBox:
        """Creates the video list table with Select All, Deselect All, and counters."""
        group = QGroupBox("VIDEOS")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)

        self.video_table = VideoTableWidget()
        self.video_table.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self.video_table)

        return group

    def _create_settings_section(self) -> QGroupBox:
        """Creates mode, format, quality, bitrate, folder, and download options."""
        group = QGroupBox("DOWNLOAD")
        main_layout = QVBoxLayout(group)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # Grid for settings
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        # Col 0, Row 0: Mode
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)
        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-weight: 600;")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            DownloadMode.VIDEO_AND_AUDIO,
            DownloadMode.VIDEO_ONLY,
            DownloadMode.AUDIO_ONLY,
        ])
        self.mode_combo.setMinimumHeight(30)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self.mode_combo.currentTextChanged.connect(self._on_setting_changed)
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo, stretch=1)
        grid.addLayout(mode_layout, 0, 0)

        # Col 1, Row 0: Save to folder
        folder_layout = QHBoxLayout()
        folder_layout.setSpacing(8)
        folder_label = QLabel("Save to:")
        folder_label.setStyleSheet("font-weight: 600;")
        self.folder_input = QLineEdit()
        self.folder_input.setMinimumHeight(30)
        self.folder_input.textChanged.connect(self._on_setting_changed)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setObjectName("secondaryButton")
        self.browse_btn.setMinimumHeight(30)
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input, stretch=1)
        folder_layout.addWidget(self.browse_btn)
        grid.addLayout(folder_layout, 0, 1)

        # Col 0, Row 1: Video Controls (Format, Quality, Bitrate)
        v_layout = QHBoxLayout()
        v_layout.setSpacing(8)

        self.video_format_label = QLabel("Format:")
        self.video_format_label.setStyleSheet("font-weight: 500;")
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP4", "MKV", "WEBM", "MOV"])
        self.format_combo.setMinimumHeight(30)
        self.format_combo.currentTextChanged.connect(self._on_setting_changed)

        self.quality_label = QLabel("Quality:")
        self.quality_label.setStyleSheet("font-weight: 500;")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Best Available",
            "2160p",
            "1440p",
            "1080p",
            "720p",
            "480p",
            "360p",
        ])
        self.quality_combo.setMinimumHeight(30)
        self.quality_combo.currentTextChanged.connect(self._on_setting_changed)

        self.video_bitrate_label = QLabel("Bitrate:")
        self.video_bitrate_label.setStyleSheet("font-weight: 500;")
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems([
            "Best Available",
            "8000 kbps",
            "5000 kbps",
            "3000 kbps",
            "2000 kbps",
            "1000 kbps",
        ])
        self.bitrate_combo.setMinimumHeight(30)
        self.bitrate_combo.currentTextChanged.connect(self._on_setting_changed)

        v_layout.addWidget(self.video_format_label)
        v_layout.addWidget(self.format_combo)
        v_layout.addWidget(self.quality_label)
        v_layout.addWidget(self.quality_combo)
        v_layout.addWidget(self.video_bitrate_label)
        v_layout.addWidget(self.bitrate_combo)
        grid.addLayout(v_layout, 1, 0)

        # Col 1, Row 1: Audio Controls (Audio Format, Bitrate)
        a_layout = QHBoxLayout()
        a_layout.setSpacing(8)

        self.audio_format_label = QLabel("Audio Format:")
        self.audio_format_label.setStyleSheet("font-weight: 500;")
        self.audio_format_combo = QComboBox()
        self.audio_format_combo.addItems(["MP3", "M4A", "WAV", "AAC", "FLAC", "OPUS"])
        self.audio_format_combo.setMinimumHeight(30)
        self.audio_format_combo.currentTextChanged.connect(self._on_setting_changed)

        self.audio_bitrate_label = QLabel("Bitrate:")
        self.audio_bitrate_label.setStyleSheet("font-weight: 500;")
        self.audio_bitrate_combo = QComboBox()
        self.audio_bitrate_combo.addItems([
            "Best Available",
            "320 kbps",
            "256 kbps",
            "192 kbps",
            "128 kbps",
            "96 kbps",
            "64 kbps",
        ])
        self.audio_bitrate_combo.setMinimumHeight(30)
        self.audio_bitrate_combo.currentTextChanged.connect(self._on_setting_changed)

        a_layout.addWidget(self.audio_format_label)
        a_layout.addWidget(self.audio_format_combo)
        a_layout.addWidget(self.audio_bitrate_label)
        a_layout.addWidget(self.audio_bitrate_combo)
        a_layout.addStretch()
        grid.addLayout(a_layout, 1, 1)

        main_layout.addLayout(grid)

        # Row 2: Checkboxes
        opt_layout = QHBoxLayout()
        opt_layout.setSpacing(20)

        self.skip_existing_cb = QCheckBox("Skip already downloaded videos")
        self.skip_existing_cb.setChecked(True)
        self.skip_existing_cb.stateChanged.connect(self._on_setting_changed)
        opt_layout.addWidget(self.skip_existing_cb)

        self.channel_folder_cb = QCheckBox("Create channel subfolder")
        self.channel_folder_cb.setChecked(False)
        self.channel_folder_cb.stateChanged.connect(self._on_setting_changed)
        opt_layout.addWidget(self.channel_folder_cb)

        opt_layout.addStretch()
        main_layout.addLayout(opt_layout)

        return group

    def _create_controls_section(self) -> QHBoxLayout:
        """Creates the main action buttons: Download, Pause, Resume, Cancel, Open Folder."""
        layout = QHBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(0, 4, 0, 4)

        # Main Download Button (Dominant Blue, 36px)
        self.download_btn = QPushButton("▶ Start Download")
        self.download_btn.setObjectName("downloadButton")
        self.download_btn.setMinimumHeight(36)
        self.download_btn.clicked.connect(self._on_download_clicked)
        layout.addWidget(self.download_btn, stretch=3)

        # Pause Button
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("pauseButton")
        self.pause_btn.setMinimumHeight(36)
        self.pause_btn.setToolTip("Pause queue after current video finishes")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self.pause_btn, stretch=1)

        # Resume Button
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.setObjectName("resumeButton")
        self.resume_btn.setMinimumHeight(36)
        self.resume_btn.setToolTip("Resume paused download queue")
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        layout.addWidget(self.resume_btn, stretch=1)

        # Cancel Button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setToolTip("Cancel active download and stop queue")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self.cancel_btn, stretch=1)

        # Open Download Folder Button
        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setObjectName("secondaryButton")
        self.open_folder_btn.setMinimumHeight(36)
        self.open_folder_btn.setToolTip("Open destination directory in Windows Explorer")
        self.open_folder_btn.clicked.connect(self._on_open_folder_clicked)
        layout.addWidget(self.open_folder_btn, stretch=1)

        return layout

    def _create_progress_section(self) -> QGroupBox:
        """Creates current video and overall queue progress indicators in a clean hierarchy."""
        group = QGroupBox("DOWNLOAD PROGRESS")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # 1. Current Video Info Line
        top_row = QHBoxLayout()
        self.current_video_label = QLabel("Current Video: None")
        self.current_video_label.setStyleSheet("font-weight: 600; font-size: 12px;")
        top_row.addWidget(self.current_video_label, stretch=1)

        self.item_stats_label = QLabel("0 MB / 0 MB")
        self.item_stats_label.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
        top_row.addWidget(self.item_stats_label)
        layout.addLayout(top_row)

        # 2. Current Video Progress Bar (16px high rounded)
        self.current_progress_bar = QProgressBar()
        self.current_progress_bar.setFixedHeight(16)
        self.current_progress_bar.setRange(0, 100)
        self.current_progress_bar.setValue(0)
        self.current_progress_bar.setFormat("%p%")
        layout.addWidget(self.current_progress_bar)

        # 3. Overall Progress Label + Speed & ETA & Queue Counters
        queue_row = QHBoxLayout()
        self.queue_label = QLabel("Overall Progress: 0 / 0 completed")
        self.queue_label.setStyleSheet("font-weight: 600; font-size: 11px;")
        queue_row.addWidget(self.queue_label)

        self.speed_label = QLabel("Speed: -- MB/s")
        self.speed_label.setStyleSheet("font-size: 11px; margin-left: 10px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.speed_label)

        self.eta_label = QLabel("ETA: --:--")
        self.eta_label.setStyleSheet("font-size: 11px; margin-left: 10px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.eta_label)

        queue_row.addStretch()

        self.queue_stats_label = QLabel("Completed: 0 | Skipped: 0 | Failed: 0 | Remaining: 0")
        self.queue_stats_label.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.queue_stats_label)
        layout.addLayout(queue_row)

        # 4. Overall Progress Bar (12px high rounded)
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setFixedHeight(12)
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFormat("%p%")
        layout.addWidget(self.overall_progress_bar)

        return group

    def _create_log_section(self) -> QGroupBox:
        """Creates the Activity Log panel with collapsible toggle to save space."""
        group = QGroupBox("ACTIVITY LOG")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(1000)
        self.log_output.setFixedHeight(110)
        self.log_output.setVisible(False)  # Collapsed by default
        layout.addWidget(self.log_output)

        log_bottom = QHBoxLayout()
        log_hint = QLabel("Real-time extraction and download output")
        log_hint.setStyleSheet("font-size: 11px;")
        log_bottom.addWidget(log_hint)

        log_bottom.addStretch()

        self.toggle_log_btn = QPushButton("Show Log ▾")
        self.toggle_log_btn.setObjectName("secondaryButton")
        self.toggle_log_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.toggle_log_btn.clicked.connect(self._on_toggle_log)
        log_bottom.addWidget(self.toggle_log_btn)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setObjectName("secondaryButton")
        clear_log_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        clear_log_btn.clicked.connect(self.log_output.clear)
        log_bottom.addWidget(clear_log_btn)

        layout.addLayout(log_bottom)
        return group

    # -------------------------------------------------------------------------
    # Settings & Environment Setup
    # -------------------------------------------------------------------------

    def _load_saved_settings(self) -> None:
        """Populates UI controls with saved settings from SettingsManager."""
        self.url_input.setText(self.settings_manager.get("last_channel_url", "https://www.youtube.com/@PythonSimplified"))
        self.folder_input.setText(self.settings_manager.get("download_folder", str(Path.home() / "Downloads" / "Channel Harvest")))

        # Mode
        saved_mode = self.settings_manager.get("download_mode", DownloadMode.VIDEO_AND_AUDIO)
        mode_idx = self.mode_combo.findText(saved_mode)
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)

        # Video dropdowns
        saved_fmt = self.settings_manager.get("format", "MP4")
        fmt_idx = self.format_combo.findText(saved_fmt)
        if fmt_idx >= 0:
            self.format_combo.setCurrentIndex(fmt_idx)

        saved_quality = self.settings_manager.get("quality", "1080p")
        q_idx = self.quality_combo.findText(saved_quality)
        if q_idx >= 0:
            self.quality_combo.setCurrentIndex(q_idx)

        saved_bitrate = self.settings_manager.get("bitrate", "Best Available")
        b_idx = self.bitrate_combo.findText(saved_bitrate)
        if b_idx >= 0:
            self.bitrate_combo.setCurrentIndex(b_idx)

        # Audio dropdowns
        saved_afmt = self.settings_manager.get("audio_format", "MP3")
        afmt_idx = self.audio_format_combo.findText(saved_afmt)
        if afmt_idx >= 0:
            self.audio_format_combo.setCurrentIndex(afmt_idx)

        saved_abitrate = self.settings_manager.get("audio_bitrate", "Best Available")
        ab_idx = self.audio_bitrate_combo.findText(saved_abitrate)
        if ab_idx >= 0:
            self.audio_bitrate_combo.setCurrentIndex(ab_idx)

        self.skip_existing_cb.setChecked(self.settings_manager.get("skip_existing", True))
        self.channel_folder_cb.setChecked(self.settings_manager.get("create_channel_folder", False))

        # Synchronize enabled/disabled states based on restored mode
        self._on_mode_changed()

    def _on_mode_changed(self, mode_text: Optional[str] = None) -> None:
        """Dynamically enables or disables Video/Audio controls based on mode."""
        if mode_text is None or not isinstance(mode_text, str):
            mode_text = self.mode_combo.currentText()

        enable_video = mode_text in (DownloadMode.VIDEO_ONLY, DownloadMode.VIDEO_AND_AUDIO)
        enable_audio = mode_text in (DownloadMode.AUDIO_ONLY, DownloadMode.VIDEO_AND_AUDIO)

        # Video controls
        self.video_format_label.setEnabled(enable_video)
        self.format_combo.setEnabled(enable_video)
        self.quality_label.setEnabled(enable_video)
        self.quality_combo.setEnabled(enable_video)
        self.video_bitrate_label.setEnabled(enable_video)
        self.bitrate_combo.setEnabled(enable_video)

        # Audio controls
        self.audio_format_label.setEnabled(enable_audio)
        self.audio_format_combo.setEnabled(enable_audio)
        self.audio_bitrate_label.setEnabled(enable_audio)
        self.audio_bitrate_combo.setEnabled(enable_audio)

    def _on_setting_changed(self) -> None:
        """Saves current settings when changed by the user."""
        self.settings_manager.set("download_mode", self.mode_combo.currentText())
        self.settings_manager.set("format", self.format_combo.currentText())
        self.settings_manager.set("quality", self.quality_combo.currentText())
        self.settings_manager.set("bitrate", self.bitrate_combo.currentText())
        self.settings_manager.set("audio_format", self.audio_format_combo.currentText())
        self.settings_manager.set("audio_bitrate", self.audio_bitrate_combo.currentText())
        self.settings_manager.set("download_folder", self.folder_input.text().strip())
        self.settings_manager.set("skip_existing", self.skip_existing_cb.isChecked())
        self.settings_manager.set("create_channel_folder", self.channel_folder_cb.isChecked())
        self.settings_manager.set("last_channel_url", self.url_input.text().strip())

    def _check_environment_status(self) -> None:
        """Detects FFmpeg availability on startup."""
        is_ffmpeg_ok, ffmpeg_path, version_str, _ = FFmpegChecker.detect()
        if not is_ffmpeg_ok:
            self.log("[WARNING] FFmpeg was not detected on this system. Audio and video stream merging requires FFmpeg.")

    def _set_ui_state(self, state: str) -> None:
        """
        State machine managing enabled/disabled button states.
        States: 'idle', 'scanning', 'downloading', 'paused'
        """
        has_selected = len(self.video_table.get_selected_videos()) > 0

        if state == "idle":
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("Scan Channel")
            self.download_btn.setEnabled(has_selected)
            self.download_btn.setText("▶ Start Download")
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.open_folder_btn.setEnabled(True)

        elif state == "scanning":
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText("Scanning...")
            self.download_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.open_folder_btn.setEnabled(False)

        elif state == "downloading":
            self.scan_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)

        elif state == "paused":
            self.scan_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.open_folder_btn.setEnabled(True)

    # -------------------------------------------------------------------------
    # Channel Scanning (Worker Thread)
    # -------------------------------------------------------------------------

    def _on_scan_clicked(self) -> None:
        """Validates URL and spawns ChannelScanWorker on a background QThread."""
        raw_url = self.url_input.text().strip()

        is_valid, error_reason = YtDlpEngine.validate_url(raw_url)
        if not is_valid:
            self.log(f"[ERROR] URL Validation Failed: {error_reason}")
            QMessageBox.warning(
                self,
                "Invalid YouTube URL",
                f"{error_reason}\n\nExample of a valid channel URL:\nhttps://www.youtube.com/@ChannelName",
            )
            return

        if self._scan_worker is not None and self._scan_worker.isRunning():
            return

        self._set_ui_state("scanning")
        self.status_bar.showMessage("Connecting to YouTube and extracting channel metadata...")

        self._scan_worker = ChannelScanWorker(url=raw_url, parent=self)
        self._scan_worker.log_message.connect(self.log)
        self._scan_worker.scan_completed.connect(self._on_scan_completed)
        self._scan_worker.scan_error.connect(self._on_scan_error)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_completed(self, videos: list) -> None:
        """Populates the table with extracted videos."""
        self.video_table.load_videos(videos)
        if videos:
            self._current_channel_title = videos[0].channel_title
        self.status_bar.showMessage(f"Scan complete: Found {len(videos)} video(s).")
        self.log(f"[SUCCESS] Channel scan finished. {len(videos)} video(s) retrieved.")

    def _on_scan_error(self, error_message: str) -> None:
        """Alerts the user when scanning fails."""
        self.status_bar.showMessage("Channel scan stopped due to an error.")
        QMessageBox.warning(self, "Channel Scan Issue", error_message)

    def _on_scan_finished(self) -> None:
        """Resets UI state after scan worker finishes."""
        self._scan_worker = None
        self._set_ui_state("idle")

    def _on_selection_changed(self, selected_count: int, total_count: int) -> None:
        """Updates download button enabled state and status bar."""
        self.status_bar.showMessage(f"{selected_count} of {total_count} video(s) selected.")
        if self._download_manager is None or not self._download_manager.isRunning():
            self.download_btn.setEnabled(selected_count > 0)

    # -------------------------------------------------------------------------
    # Download Queue Management
    # -------------------------------------------------------------------------

    def _on_download_clicked(self) -> None:
        """Initiates the sequential download queue in a background QThread."""
        selected_videos = self.video_table.get_selected_videos()

        if not selected_videos:
            QMessageBox.information(
                self,
                "No Videos Selected",
                "Please scan a channel first and select at least one video to download.",
            )
            return

        folder_str = self.folder_input.text().strip()
        if not folder_str:
            QMessageBox.warning(self, "Missing Destination", "Please choose a download destination folder.")
            return

        # Prepare settings
        settings = DownloadSettings(
            download_mode=self.mode_combo.currentText(),
            format=self.format_combo.currentText(),
            quality=self.quality_combo.currentText(),
            bitrate=self.bitrate_combo.currentText(),
            audio_format=self.audio_format_combo.currentText(),
            audio_bitrate=self.audio_bitrate_combo.currentText(),
            download_folder=folder_str,
            create_channel_folder=self.channel_folder_cb.isChecked(),
            skip_existing=self.skip_existing_cb.isChecked(),
            channel_title=self._current_channel_title,
        )

        # Check FFmpeg requirement warning
        is_ffmpeg_ok, _, _, _ = FFmpegChecker.detect()
        if not is_ffmpeg_ok:
            needs_ffmpeg = (
                settings.download_mode != DownloadMode.AUDIO_ONLY
                or settings.audio_format in ("MP3", "WAV", "AAC", "FLAC", "OPUS")
            )
            if needs_ffmpeg:
                reply = QMessageBox.question(
                    self,
                    "FFmpeg Recommended",
                    "FFmpeg is not detected on your system. Merging video/audio streams or extracting audio "
                    "requires FFmpeg.\n\n"
                    "Would you like to continue anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return

        # Prevent duplicate entries in queue
        seen_ids = set()
        unique_videos: List[VideoItem] = []
        for v in selected_videos:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                unique_videos.append(v)

        # Mark selected videos as 'Waiting' in table
        self.video_table.set_queue_waiting([v.video_id for v in unique_videos])

        # Instantiate DownloadManager
        self._download_manager = DownloadManager(videos=unique_videos, settings=settings, parent=self)

        # Connect signals
        self._download_manager.queue_started.connect(self._on_queue_started)
        self._download_manager.video_started.connect(self._on_video_started)
        self._download_manager.video_progress.connect(self._on_video_progress)
        self._download_manager.video_status_changed.connect(self._on_video_status_changed)
        self._download_manager.overall_progress.connect(self._on_overall_progress)
        self._download_manager.queue_finished.connect(self._on_queue_finished)
        self._download_manager.log_message.connect(self.log)
        self._download_manager.error_occurred.connect(self._on_download_error)

        self._set_ui_state("downloading")
        self._download_manager.start()

    def _on_pause_clicked(self) -> None:
        """Pauses queue between video downloads."""
        if self._download_manager and self._download_manager.isRunning():
            self._download_manager.pause()
            self._set_ui_state("paused")
            self.status_bar.showMessage("Download queue paused.")

    def _on_resume_clicked(self) -> None:
        """Resumes paused download queue."""
        if self._download_manager and self._download_manager.isRunning():
            self._download_manager.resume()
            self._set_ui_state("downloading")
            self.status_bar.showMessage("Download queue resumed.")

    def _on_cancel_clicked(self) -> None:
        """Cancels active download and stops remaining queue."""
        if self._download_manager and self._download_manager.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Downloads",
                "Are you sure you want to cancel the remaining download queue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.cancel_btn.setEnabled(False)
                self.status_bar.showMessage("Cancelling downloads, please wait...")
                self._download_manager.cancel()

    def _on_queue_started(self, total: int) -> None:
        """Updates UI when queue starts."""
        self.current_progress_bar.setValue(0)
        self.overall_progress_bar.setValue(0)
        self.queue_label.setText(f"Overall Progress: 0 / {total} completed")
        self.queue_stats_label.setText(f"Completed: 0 | Skipped: 0 | Failed: 0 | Remaining: {total}")
        self.status_bar.showMessage(f"Downloading queue ({total} items)...")

    def _on_video_started(self, video_id: str, title: str, index: int, total: int) -> None:
        """Updates UI for the newly active video."""
        self.current_video_label.setText(f"Downloading: ({index}/{total}) {title}")
        self.current_progress_bar.setValue(0)
        self.status_bar.showMessage(f"Downloading #{index} of {total}: {title}")

    def _on_video_progress(
        self,
        video_id: str,
        percent: float,
        downloaded_str: str,
        total_str: str,
        speed: str,
        eta: str,
    ) -> None:
        """Updates real-time progress widgets."""
        self.current_progress_bar.setValue(int(percent))
        self.item_stats_label.setText(f"{downloaded_str} / {total_str}")
        self.speed_label.setText(f"Speed: {speed}")
        self.eta_label.setText(f"ETA: {eta}")

    def _on_video_status_changed(self, video_id: str, status: str, error_msg: str) -> None:
        """Updates the status column in the video table."""
        self.video_table.update_video_status(video_id, status, error_msg)

    def _on_overall_progress(
        self,
        completed: int,
        skipped: int,
        failed: int,
        remaining: int,
        overall_pct: float,
    ) -> None:
        """Updates queue-level progress bar and counters."""
        total = completed + skipped + failed + remaining
        self.overall_progress_bar.setValue(int(overall_pct))
        self.queue_label.setText(f"Overall Progress: {completed + skipped} / {total} finished ({overall_pct:.0f}%)")
        self.queue_stats_label.setText(
            f"Completed: {completed} | Skipped: {skipped} | Failed: {failed} | Remaining: {remaining}"
        )

    def _on_queue_finished(self, completed: int, skipped: int, failed: int, total: int) -> None:
        """Displays completion summary dialog and restores UI state."""
        self._set_ui_state("idle")
        self.status_bar.showMessage(f"Queue complete: {completed} downloaded, {skipped} skipped, {failed} failed.")

        # Resolve final folder path for dialog
        folder = self.folder_input.text().strip()
        if self.channel_folder_cb.isChecked() and self._current_channel_title:
            folder = str(Path(folder) / self._current_channel_title)

        # Show summary modal
        dialog = SummaryDialog(
            completed=completed,
            skipped=skipped,
            failed=failed,
            total=total,
            download_folder=folder,
            parent=self,
        )
        dialog.exec()

    def _on_download_error(self, title: str, message: str) -> None:
        """Displays an error dialog from the download manager."""
        QMessageBox.warning(self, title, message)

    # -------------------------------------------------------------------------
    # Folder & Log Helpers
    # -------------------------------------------------------------------------

    def _on_browse_clicked(self) -> None:
        """Opens native Windows folder picker."""
        current_dir = self.folder_input.text().strip() or str(Path.home() / "Downloads")
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Download Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected_dir:
            self.folder_input.setText(selected_dir)
            self._on_setting_changed()
            self.log(f"[CONFIG] Download destination set to: {selected_dir}")

    def _on_open_folder_clicked(self) -> None:
        """Opens the download destination folder in Windows File Explorer."""
        folder_str = self.folder_input.text().strip()
        if not folder_str:
            return

        folder_path = Path(folder_str)
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)

        try:
            os.startfile(str(folder_path))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open directory:\n{e}")

    def is_download_active(self) -> bool:
        """Returns True if a video download queue is currently running."""
        return self._download_manager is not None and self._download_manager.isRunning()

    def _on_theme_changed(self, effective_theme: str, is_dark: bool) -> None:
        """Updates main window dynamic elements (e.g. settings icon) when theme switches."""
        if hasattr(self, "settings_btn"):
            self.settings_btn.setIcon(get_settings_icon())

    def _check_ytdlp_updates_silent(self) -> None:
        """Checks for yt-dlp updates in a silent background thread if enabled and interval elapsed."""
        auto_check = self.settings_manager.get("auto_check_ytdlp_updates", True)
        if not auto_check:
            return
        last_check = self.settings_manager.get("last_ytdlp_update_check", 0.0)
        # Check at most once every 24 hours (86400 seconds)
        if time.time() - float(last_check) < 86400:
            return

        from downloader.updater import CheckUpdateWorker
        self._silent_update_worker = CheckUpdateWorker(self)
        self._silent_update_worker.check_completed.connect(self._on_silent_check_completed)
        self._silent_update_worker.start()

    def _on_silent_check_completed(self, has_update: bool, current_ver: str, latest_ver: str, error_msg: str) -> None:
        """Handles silent update check result."""
        if has_update:
            self.settings_manager.set("last_ytdlp_update_check", time.time())
            self.log(f"[UPDATE] A new yt-dlp version is available: v{latest_ver} (current: v{current_ver}). Check Settings to update.")
        elif not error_msg:
            self.settings_manager.set("last_ytdlp_update_check", time.time())

    def _on_settings_clicked(self) -> None:
        """Opens the Settings modal dialog."""
        dialog = SettingsDialog(self, settings_manager=self.settings_manager)
        dialog.exec()

    def _on_toggle_log(self) -> None:
        """Toggles visibility of the activity log to maximize vertical space."""
        if self.log_output.isVisible():
            self.log_output.setVisible(False)
            self.toggle_log_btn.setText("Show Log ▾")
        else:
            self.log_output.setVisible(True)
            self.toggle_log_btn.setText("Hide Log ▴")

    def log(self, message: str) -> None:
        """Appends a timestamped message to the activity log panel."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handles graceful application shutdown and settings persistence."""
        ThemeManager.unregister_listener(self._on_theme_changed)

        # Check if downloads are actively running
        if self._download_manager is not None and self._download_manager.isRunning():
            reply = QMessageBox.question(
                self,
                "Download in Progress",
                "Downloads are currently running. Do you want to cancel downloads and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_manager.cancel()
                self._download_manager.wait(3000)  # Wait up to 3 seconds for clean exit
            else:
                event.ignore()
                return

        # Save window geometry
        self.settings_manager.set("window_width", self.width())
        self.settings_manager.set("window_height", self.height())
        self._on_setting_changed()
        event.accept()
