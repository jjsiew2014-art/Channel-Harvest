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
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

ANSI_ESCAPE_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

import yt_dlp
from PySide6.QtCore import Qt, QSize, QByteArray, QTimer
from PySide6.QtGui import QFont, QCloseEvent, QIcon, QPixmap, QPainter, QBrush, QColor
from PySide6.QtSvg import QSvgRenderer
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
    QSizePolicy,
)

from core.models import (
    DownloadSettings,
    VideoItem,
    VideoStatus,
    DownloadMode,
    SubtitleSource,
    SubtitleLanguage,
    ThumbnailFormat,
)
from core.settings import SettingsManager
from core.paths import get_archive_file, get_logo_file
from core.i18n import I18nManager, tr
from core.platform import PlatformDetector, PlatformRegistry
from downloader.ytdlp_engine import ChannelScanWorker, YtDlpEngine
from downloader.download_manager import DownloadManager
from downloader.subtitle_manager import SubtitleDetectionWorker
from downloader.ffmpeg_checker import FFmpegChecker
from downloader.runtime_manager import RuntimeManager
from gui.video_table import VideoTableWidget
from gui.summary_dialog import SummaryDialog
from gui.settings_dialog import SettingsDialog, get_settings_icon
from gui.styles import ThemeManager
from gui.taskbar_progress import TaskbarProgressManager
from core.diagnostics import ErrorTracker


def get_action_icon(action: str, color: Optional[str] = None) -> QIcon:
    """Generates crisp vector SVG icons for download action bar buttons."""
    is_dark = ThemeManager.is_dark()
    if color is None:
        if action == "download":
            color = "#ffffff"
        elif action == "pause":
            color = "#fde68a" if is_dark else "#92400e"
        elif action == "resume":
            color = "#86efac" if is_dark else "#166534"
        elif action == "cancel":
            color = "#fca5a5" if is_dark else "#991b1b"
        elif action in ("folder", "open_folder"):
            color = "#f1f5f9" if is_dark else "#334155"
        else:
            color = "#ffffff"

    svgs = {
        "download": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
        "pause": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>',
        "resume": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 19 12 6 20 6 4"/></svg>',
        "cancel": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
        "folder": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
        "open_folder": f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    }
    svg = svgs.get(action, svgs["download"])
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


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
        self._current_ui_state: str = "idle"

        # References to active background workers
        self._scan_worker: Optional[ChannelScanWorker] = None
        self._download_manager: Optional[DownloadManager] = None
        self._sub_detect_worker: Optional[SubtitleDetectionWorker] = None
        self._silent_update_worker = None
        self._settings_dialog: Optional[SettingsDialog] = None

        # Queue progress tracking and Windows taskbar progress manager
        self._queue_total: int = 0
        self._queue_completed: int = 0
        self._queue_skipped: int = 0
        self._queue_failed: int = 0
        self._current_video_pct: float = 0.0
        self.taskbar_progress = TaskbarProgressManager(self)

        # Register theme listener to dynamically update icons on theme switch
        ThemeManager.register_listener(self._on_theme_changed)
        I18nManager.register_listener(self._on_language_changed)

        # Window configuration
        self.setWindowTitle("Channel Harvest")
        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        default_w = 1200
        default_h = 960

        saved_w = self.settings_manager.get("window_width", default_w)
        saved_h = self.settings_manager.get("window_height", default_h)

        # If previous saved dimensions are smaller than optimal defaults, upgrade them
        # so all content is fully visible on startup without scrolling
        if saved_w < default_w:
            saved_w = default_w
        if saved_h < default_h:
            saved_h = default_h

        # Ensure window doesn't exceed current monitor available geometry
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            saved_w = min(saved_w, avail.width() - 40)
            saved_h = min(saved_h, avail.height() - 60)
            # Center window on screen for a balanced desktop presentation
            x = avail.x() + (avail.width() - saved_w) // 2
            y = avail.y() + (avail.height() - saved_h) // 2
            self.setGeometry(x, y, saved_w, saved_h)
        else:
            self.resize(saved_w, saved_h)
        # Flexible minimum size allowing free resizing on any display (including 1366x768 or 1080p @ 125% DPI)
        self.setMinimumSize(660, 460)

        # 2. Build GUI sections
        self._loading_settings = True
        self._init_ui()

        # 3. Apply saved settings to controls
        self._load_saved_settings()
        self._loading_settings = False

        # 4. Check environment (FFmpeg and yt-dlp versions)
        self._check_environment_status()

        # 5. Set initial button states
        self._set_ui_state("idle")

        # 6. Apply initial translations
        self.retranslate_ui()

        # Initial Welcome Logs
        self.log(tr("log_ready"))
        archive_path = get_archive_file()
        self.log(tr("log_archive_active_fmt", name=archive_path.name))

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
        main_layout.setContentsMargins(16, 8, 16, 8)
        main_layout.setSpacing(8)

        # 1. Header Banner with Environment Status
        header_layout = self._create_header_section()
        main_layout.addLayout(header_layout)

        # 2. Channel URL Input Section
        url_group = self._create_url_section()
        main_layout.addWidget(url_group)

        # 3. Video List Table Section (expands most when window is resized)
        video_group = self._create_video_list_section()
        main_layout.addWidget(video_group, stretch=3)

        # 4. Download Settings Section (Hosts Destination, 3 sub-panels, and Action Bar)
        settings_group = self._create_settings_section()
        main_layout.addWidget(settings_group, stretch=0)

        # 5. Download Progress Section (Current item + Overall queue)
        progress_group = self._create_progress_section()
        main_layout.addWidget(progress_group, stretch=0)

        # 7. Activity Log Panel Section (flexible expansion)
        log_group = self._create_log_section()
        main_layout.addWidget(log_group, stretch=0)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(tr("status_ready"))

    def _create_header_section(self) -> QHBoxLayout:
        """Creates the clean application header with branding, subtitle, and settings button."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Branding container (Logo + Title + Subtitle)
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(10)
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

        self.subtitle_label = QLabel("Harvest your channel. Keep every video.")
        self.subtitle_label.setObjectName("appSubtitleLabel")
        title_box.addWidget(self.subtitle_label)

        brand_layout.addLayout(title_box)
        layout.addLayout(brand_layout, stretch=1)

        # 3. Settings Icon Button (Top-Right)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setIcon(get_settings_icon())
        self.settings_btn.setIconSize(QSize(16, 16))
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setFixedSize(34, 34)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        layout.addWidget(self.settings_btn)

        return layout

    def _create_url_section(self) -> QGroupBox:
        """Creates the media link input and platform selection section."""
        self.url_group = QGroupBox("YOUTUBE LINK")
        self.url_group.setObjectName("urlGroupBox")
        layout = QVBoxLayout(self.url_group)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.url_label = QLabel("YouTube Channel / Playlist URL")
        self.url_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        header_layout.addWidget(self.url_label, stretch=1)

        platform_layout = QHBoxLayout()
        platform_layout.setSpacing(6)

        self.platform_label = QLabel(tr("platform_label"))
        self.platform_label.setStyleSheet("font-weight: 600; font-size: 12px; color: #888888;")
        platform_layout.addWidget(self.platform_label)

        self.platform_combo = QComboBox()
        self.platform_combo.setObjectName("platformCombo")
        self.platform_combo.setMinimumHeight(28)
        self.platform_combo.setMinimumWidth(110)
        self.platform_combo.addItem(tr("platform_youtube"), "youtube")
        self.platform_combo.addItem(tr("platform_tiktok"), "tiktok")
        self.platform_combo.addItem(tr("platform_douyin"), "douyin")
        self._update_platform_combo_availability()
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        platform_layout.addWidget(self.platform_combo)

        header_layout.addLayout(platform_layout)
        layout.addLayout(header_layout)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/@channel or playlist URL")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.setMinimumHeight(34)
        self.url_input.returnPressed.connect(self._on_scan_clicked)
        self.url_input.textChanged.connect(self._on_url_text_changed)
        input_layout.addWidget(self.url_input, stretch=1)

        self.scan_btn = QPushButton("Scan Channel")
        self.scan_btn.setObjectName("scanButton")
        self.scan_btn.setMinimumHeight(34)
        self.scan_btn.setMinimumWidth(120)
        self.scan_btn.clicked.connect(self._on_scan_clicked)
        input_layout.addWidget(self.scan_btn)

        layout.addLayout(input_layout)
        return self.url_group

    def _create_video_list_section(self) -> QGroupBox:
        """Creates the available videos list table (primary workspace)."""
        self.video_group = QGroupBox("AVAILABLE VIDEOS")
        self.video_group.setObjectName("videosGroupBox")
        layout = QVBoxLayout(self.video_group)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.video_table = VideoTableWidget()
        self.video_table.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self.video_table)

        return self.video_group

    def _create_settings_section(self) -> QGroupBox:
        """Creates mode, format, quality, bitrate, folder, and download options with internal action bar."""
        self.download_group = QGroupBox("DOWNLOAD OPTION")
        self.download_group.setObjectName("downloadGroupBox")
        main_layout = QVBoxLayout(self.download_group)
        main_layout.setContentsMargins(14, 8, 14, 8)
        main_layout.setSpacing(6)

        # -----------------------------------------------------------------
        # 1. Destination Bar (Save to: [ Path ] [ Browse... ])
        # -----------------------------------------------------------------
        dest_layout = QHBoxLayout()
        dest_layout.setSpacing(8)

        self.folder_prefix = QLabel("Save to:")
        self.folder_prefix.setStyleSheet("font-weight: 600; font-size: 12px;")
        self.folder_input = QLineEdit()
        self.folder_input.setMinimumHeight(32)
        self.folder_input.textChanged.connect(self._on_setting_changed)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setObjectName("secondaryButton")
        self.browse_btn.setMinimumHeight(32)
        self.browse_btn.setFixedWidth(90)
        self.browse_btn.clicked.connect(self._on_browse_clicked)

        dest_layout.addWidget(self.folder_prefix)
        dest_layout.addWidget(self.folder_input, stretch=1)
        dest_layout.addWidget(self.browse_btn)
        main_layout.addLayout(dest_layout)

        # -----------------------------------------------------------------
        # 2. 3-Column Sub-Panels (MEDIA | ADDITIONAL ASSETS | FILE ORGANIZATION)
        # -----------------------------------------------------------------
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(10)

        # Column 1: MEDIA
        media_card = QFrame()
        media_card.setObjectName("subSectionCard")
        media_layout = QVBoxLayout(media_card)
        media_layout.setContentsMargins(12, 8, 12, 8)
        media_layout.setSpacing(4)

        self.media_title = QLabel("MEDIA")
        self.media_title.setObjectName("subSectionTitle")
        media_layout.addWidget(self.media_title)

        media_grid = QGridLayout()
        media_grid.setHorizontalSpacing(10)
        media_grid.setVerticalSpacing(3)

        # Row 0 & 1: Mode & Quality
        self.mode_label = QLabel("Mode")
        self.mode_label.setObjectName("formLabel")
        self.mode_combo = QComboBox()
        for mode in [
            DownloadMode.VIDEO_AND_AUDIO,
            DownloadMode.VIDEO_ONLY,
            DownloadMode.AUDIO_ONLY,
            DownloadMode.ASSETS_ONLY,
        ]:
            self.mode_combo.addItem(I18nManager.get_mode_label(mode), mode)
        idx_vo = self.mode_combo.findData(DownloadMode.VIDEO_ONLY)
        if idx_vo >= 0:
            self.mode_combo.setCurrentIndex(idx_vo)
        self.mode_combo.setMinimumHeight(28)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_setting_changed)

        self.quality_label = QLabel("Video Resolution")
        self.quality_label.setObjectName("formLabel")
        self.quality_combo = QComboBox()
        for q in [
            "Best Available",
            "2160p",
            "1440p",
            "1080p",
            "720p",
            "480p",
            "360p",
        ]:
            self.quality_combo.addItem(I18nManager.get_quality_label(q), q)
        self.quality_combo.setMinimumHeight(28)
        self.quality_combo.currentIndexChanged.connect(self._on_setting_changed)

        media_grid.addWidget(self.mode_label, 0, 0)
        media_grid.addWidget(self.quality_label, 0, 1)
        media_grid.addWidget(self.mode_combo, 1, 0)
        media_grid.addWidget(self.quality_combo, 1, 1)

        # Row 2 & 3: Video Format & Video Bitrate
        self.video_format_label = QLabel("Video Format")
        self.video_format_label.setObjectName("formLabel")
        self.format_combo = QComboBox()
        for fmt in ["MOV", "MP4", "MKV", "WEBM"]:
            self.format_combo.addItem(fmt, fmt)
        self.format_combo.setMinimumHeight(28)
        self.format_combo.currentIndexChanged.connect(self._on_setting_changed)

        self.video_bitrate_label = QLabel("Video Bitrate")
        self.video_bitrate_label.setObjectName("formLabel")
        self.bitrate_combo = QComboBox()
        for b in [
            "Best Available",
            "8000 kbps",
            "5000 kbps",
            "3000 kbps",
            "2000 kbps",
            "1000 kbps",
        ]:
            self.bitrate_combo.addItem(I18nManager.get_video_bitrate_label(b), b)
        self.bitrate_combo.setMinimumHeight(28)
        self.bitrate_combo.currentIndexChanged.connect(self._on_setting_changed)

        media_grid.addWidget(self.video_format_label, 2, 0)
        media_grid.addWidget(self.video_bitrate_label, 2, 1)
        media_grid.addWidget(self.format_combo, 3, 0)
        media_grid.addWidget(self.bitrate_combo, 3, 1)

        # Row 4 & 5: Audio Format & Audio Bitrate
        self.audio_format_label = QLabel("Audio Format")
        self.audio_format_label.setObjectName("formLabel")
        self.audio_format_combo = QComboBox()
        for afmt in ["WAV", "MP3", "M4A", "AAC", "FLAC", "OPUS"]:
            self.audio_format_combo.addItem(afmt, afmt)
        self.audio_format_combo.setMinimumHeight(28)
        self.audio_format_combo.currentIndexChanged.connect(self._on_setting_changed)

        self.audio_bitrate_label = QLabel("Audio Bitrate")
        self.audio_bitrate_label.setObjectName("formLabel")
        self.audio_bitrate_combo = QComboBox()
        for ab in [
            "Best Available",
            "320 kbps",
            "256 kbps",
            "192 kbps",
            "128 kbps",
            "96 kbps",
            "64 kbps",
        ]:
            self.audio_bitrate_combo.addItem(I18nManager.get_audio_bitrate_label(ab), ab)
        self.audio_bitrate_combo.setMinimumHeight(28)
        self.audio_bitrate_combo.currentIndexChanged.connect(self._on_setting_changed)

        media_grid.addWidget(self.audio_format_label, 4, 0)
        media_grid.addWidget(self.audio_bitrate_label, 4, 1)
        media_grid.addWidget(self.audio_format_combo, 5, 0)
        media_grid.addWidget(self.audio_bitrate_combo, 5, 1)

        media_grid.setColumnStretch(0, 1)
        media_grid.setColumnStretch(1, 1)

        media_layout.addLayout(media_grid)
        media_layout.addStretch(1)
        columns_layout.addWidget(media_card, stretch=8)

        # Column 2: ADDITIONAL ASSETS
        assets_card = QFrame()
        assets_card.setObjectName("subSectionCard")
        assets_layout = QVBoxLayout(assets_card)
        assets_layout.setContentsMargins(12, 8, 12, 8)
        assets_layout.setSpacing(4)

        self.assets_title = QLabel("ADDITIONAL ASSETS")
        self.assets_title.setObjectName("subSectionTitle")
        assets_layout.addWidget(self.assets_title)

        assets_grid = QGridLayout()
        assets_grid.setHorizontalSpacing(10)
        assets_grid.setVerticalSpacing(3)

        # Row 0: Checkbox Headers (Subtitles & Thumbnail)
        self.subtitles_cb = QCheckBox("Subtitles")
        self.subtitles_cb.setStyleSheet("font-weight: 600;")
        self.subtitles_cb.setChecked(False)
        self.subtitles_cb.toggled.connect(self._on_subtitles_toggled)
        assets_grid.addWidget(self.subtitles_cb, 0, 0)

        self.thumbnail_cb = QCheckBox("Download thumbnail")
        self.thumbnail_cb.setStyleSheet("font-weight: 600;")
        self.thumbnail_cb.setChecked(False)
        self.thumbnail_cb.setToolTip("Download the video's YouTube thumbnail as a separate image file.")
        self.thumbnail_cb.toggled.connect(self._on_thumbnail_toggled)
        assets_grid.addWidget(self.thumbnail_cb, 0, 1)

        # Row 1 & 2: Subtitle Source & Thumbnail Format
        self.sub_source_label = QLabel("Source")
        self.sub_source_label.setObjectName("formLabel")
        self.sub_source_combo = QComboBox()
        for src in [
            SubtitleSource.BEST_AVAILABLE,
            SubtitleSource.OFFICIAL,
            SubtitleSource.AUTO,
        ]:
            self.sub_source_combo.addItem(I18nManager.get_sub_source_label(src), src)
        self.sub_source_combo.setMinimumHeight(28)
        self.sub_source_combo.currentIndexChanged.connect(self._on_setting_changed)
        assets_grid.addWidget(self.sub_source_label, 1, 0)
        assets_grid.addWidget(self.sub_source_combo, 2, 0)

        self.thumb_format_label = QLabel("Thumbnail Format")
        self.thumb_format_label.setObjectName("formLabel")
        self.thumb_format_combo = QComboBox()
        for tfmt in [
            ThumbnailFormat.JPG,
            ThumbnailFormat.PNG,
            ThumbnailFormat.WEBP,
            ThumbnailFormat.ORIGINAL,
        ]:
            self.thumb_format_combo.addItem(I18nManager.get_thumb_format_label(tfmt), tfmt)
        self.thumb_format_combo.setMinimumHeight(28)
        self.thumb_format_combo.setEnabled(False)
        self.thumb_format_combo.setToolTip("Format for saved thumbnail image.")
        self.thumb_format_combo.currentIndexChanged.connect(self._on_setting_changed)
        assets_grid.addWidget(self.thumb_format_label, 1, 1)
        assets_grid.addWidget(self.thumb_format_combo, 2, 1)

        # Row 3 & 4: Subtitle Language & Information Files Title
        self.sub_lang_label = QLabel("Language")
        self.sub_lang_label.setObjectName("formLabel")
        self.sub_lang_combo = QComboBox()
        for slang in [
            SubtitleLanguage.CHINESE,
            SubtitleLanguage.ENGLISH,
            SubtitleLanguage.MALAY,
            SubtitleLanguage.JAPANESE,
            SubtitleLanguage.KOREAN,
            SubtitleLanguage.ALL,
        ]:
            self.sub_lang_combo.addItem(I18nManager.get_sub_lang_label(slang), slang)
        self.sub_lang_combo.setMinimumHeight(28)
        self.sub_lang_combo.currentIndexChanged.connect(self._on_setting_changed)
        assets_grid.addWidget(self.sub_lang_label, 3, 0)
        assets_grid.addWidget(self.sub_lang_combo, 4, 0)

        # Row 5 & 6: Subtitle Format & Information Files Checkboxes
        self.sub_format_label = QLabel("Subtitle Format")
        self.sub_format_label.setObjectName("formLabel")
        self.sub_format_combo = QComboBox()
        self.sub_format_combo.addItem("SRT", "SRT")
        self.sub_format_combo.setMinimumHeight(28)
        self.sub_format_combo.currentIndexChanged.connect(self._on_setting_changed)
        assets_grid.addWidget(self.sub_format_label, 5, 0)
        assets_grid.addWidget(self.sub_format_combo, 6, 0)

        # Right side: Information files grouped container
        info_container = QVBoxLayout()
        info_container.setSpacing(5)
        info_container.setContentsMargins(0, 4, 0, 0)

        self.info_header = QLabel("INFORMATION FILES")
        self.info_header.setObjectName("subGroupTitle")
        info_container.addWidget(self.info_header)

        self.save_desc_cb = QCheckBox("Save description")
        self.save_desc_cb.setChecked(False)
        self.save_desc_cb.setToolTip("Save original YouTube video description to a .description text file.")
        self.save_desc_cb.stateChanged.connect(self._on_setting_changed)
        info_container.addWidget(self.save_desc_cb)

        self.save_meta_cb = QCheckBox("Save metadata")
        self.save_meta_cb.setChecked(False)
        self.save_meta_cb.setToolTip("Save clean, organized video metadata to a .metadata.txt file.")
        self.save_meta_cb.stateChanged.connect(self._on_setting_changed)
        info_container.addWidget(self.save_meta_cb)

        self.save_chapters_cb = QCheckBox("Save chapters")
        self.save_chapters_cb.setChecked(False)
        self.save_chapters_cb.setToolTip("Save video chapter markers to a .chapters.txt file.")
        self.save_chapters_cb.stateChanged.connect(self._on_setting_changed)
        info_container.addWidget(self.save_chapters_cb)
        info_container.addStretch(1)

        assets_grid.addLayout(info_container, 3, 1, 4, 1)

        assets_grid.setColumnStretch(0, 1)
        assets_grid.setColumnStretch(1, 1)

        assets_layout.addLayout(assets_grid)
        assets_layout.addStretch(1)
        columns_layout.addWidget(assets_card, stretch=8)

        # Column 3: FILE ORGANIZATION
        org_card = QFrame()
        org_card.setObjectName("subSectionCard")
        org_layout = QVBoxLayout(org_card)
        org_layout.setContentsMargins(12, 8, 12, 8)
        org_layout.setSpacing(8)

        self.org_title = QLabel("FILE ORGANIZATION")
        self.org_title.setObjectName("subSectionTitle")
        org_layout.addWidget(self.org_title)

        self.skip_existing_cb = QCheckBox("Skip downloaded videos")
        self.skip_existing_cb.setChecked(False)
        self.skip_existing_cb.setToolTip("Skip downloading files that already exist in the target folder.")
        self.skip_existing_cb.stateChanged.connect(self._on_setting_changed)
        org_layout.addWidget(self.skip_existing_cb)

        self.channel_folder_cb = QCheckBox("Create channel subfolder")
        self.channel_folder_cb.setChecked(True)
        self.channel_folder_cb.setToolTip("Store videos inside a folder named after the channel.")
        self.channel_folder_cb.stateChanged.connect(self._on_setting_changed)
        org_layout.addWidget(self.channel_folder_cb)

        self.individual_folder_cb = QCheckBox("Create individual video folders")
        self.individual_folder_cb.setChecked(False)
        self.individual_folder_cb.setToolTip("Store each video's files in its own folder.")
        self.individual_folder_cb.stateChanged.connect(self._on_setting_changed)
        org_layout.addWidget(self.individual_folder_cb)

        self.include_video_id_cb = QCheckBox("Include Video ID in filename")
        self.include_video_id_cb.setChecked(False)
        self.include_video_id_cb.setToolTip("Include YouTube Video ID in downloaded filenames.")
        self.include_video_id_cb.stateChanged.connect(self._on_setting_changed)
        org_layout.addWidget(self.include_video_id_cb)

        org_layout.addStretch(1)
        columns_layout.addWidget(org_card, stretch=6)

        main_layout.addLayout(columns_layout)

        # -----------------------------------------------------------------
        # 3. Full-Width Download Action Bar (INSIDE DOWNLOAD OPTION)
        # -----------------------------------------------------------------
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        action_layout.setContentsMargins(0, 2, 0, 0)

        # 1. Primary Action Button: Start Download
        self.download_btn = QPushButton("Start Download")
        self.download_btn.setObjectName("downloadButton")
        self.download_btn.setIcon(get_action_icon("download"))
        self.download_btn.setIconSize(QSize(18, 18))
        self.download_btn.setFixedHeight(40)
        self.download_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.download_btn.clicked.connect(self._on_download_clicked)
        action_layout.addWidget(self.download_btn, stretch=20)

        # 2. Secondary Action Controls
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("pauseButton")
        self.pause_btn.setIcon(get_action_icon("pause"))
        self.pause_btn.setIconSize(QSize(16, 16))
        self.pause_btn.setFixedHeight(40)
        self.pause_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.pause_btn.setToolTip("Pause queue after current video finishes")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        action_layout.addWidget(self.pause_btn, stretch=10)

        self.resume_btn = QPushButton("Resume")
        self.resume_btn.setObjectName("resumeButton")
        self.resume_btn.setIcon(get_action_icon("resume"))
        self.resume_btn.setIconSize(QSize(16, 16))
        self.resume_btn.setFixedHeight(40)
        self.resume_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.resume_btn.setToolTip("Resume paused download queue")
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        action_layout.addWidget(self.resume_btn, stretch=10)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setIcon(get_action_icon("cancel"))
        self.cancel_btn.setIconSize(QSize(16, 16))
        self.cancel_btn.setFixedHeight(40)
        self.cancel_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cancel_btn.setToolTip("Cancel active download and stop queue")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        action_layout.addWidget(self.cancel_btn, stretch=10)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setObjectName("openFolderButton")
        self.open_folder_btn.setIcon(get_action_icon("folder"))
        self.open_folder_btn.setIconSize(QSize(16, 16))
        self.open_folder_btn.setFixedHeight(40)
        self.open_folder_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.open_folder_btn.setToolTip("Open destination directory in Windows Explorer")
        self.open_folder_btn.clicked.connect(self._on_open_folder_clicked)
        action_layout.addWidget(self.open_folder_btn, stretch=13)

        main_layout.addLayout(action_layout)
        return self.download_group

    def _create_progress_section(self) -> QGroupBox:
        """Creates current video and overall queue progress indicators in a clean hierarchy."""
        self.progress_group = QGroupBox("DOWNLOAD PROGRESS")
        self.progress_group.setObjectName("progressGroupBox")
        layout = QVBoxLayout(self.progress_group)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)

        # 1. Current Video Info Line
        top_row = QHBoxLayout()
        self.current_video_label = QLabel("Current Video: None")
        self.current_video_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_row.addWidget(self.current_video_label, stretch=1)

        self.item_stats_label = QLabel("0 MB / 0 MB")
        self.item_stats_label.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
        top_row.addWidget(self.item_stats_label)
        layout.addLayout(top_row)

        # 2. Current Video Progress Bar (14px high rounded)
        self.current_progress_bar = QProgressBar()
        self.current_progress_bar.setFixedHeight(14)
        self.current_progress_bar.setRange(0, 100)
        self.current_progress_bar.setValue(0)
        self.current_progress_bar.setFormat("%p%")
        layout.addWidget(self.current_progress_bar)

        # 3. Overall Progress Label + Speed & ETA & Queue Counters
        queue_row = QHBoxLayout()
        self.queue_label = QLabel("Overall Progress: 0 / 0 completed")
        self.queue_label.setStyleSheet("font-weight: 600; font-size: 12px;")
        queue_row.addWidget(self.queue_label)

        self.speed_label = QLabel("Speed: -- MB/s")
        self.speed_label.setStyleSheet("font-size: 11px; margin-left: 10px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.speed_label)

        self.eta_label = QLabel("ETA: --:--")
        self.eta_label.setStyleSheet("font-size: 11px; margin-left: 10px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.eta_label)

        queue_row.addStretch()

        self.queue_stats_label = QLabel("Completed: 0 | Skipped: 0 | Failed: 0 | Remaining: 0")
        self.queue_stats_label.setStyleSheet("font-size: 12px; font-family: Consolas, monospace;")
        queue_row.addWidget(self.queue_stats_label)
        layout.addLayout(queue_row)

        # 4. Overall Progress Bar (10px high rounded)
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setFixedHeight(10)
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_bar.setFormat("%p%")
        layout.addWidget(self.overall_progress_bar)

        return self.progress_group

    def _create_log_section(self) -> QGroupBox:
        """Creates the Activity Log panel with collapsible toggle in a compact header."""
        self.log_group = QGroupBox("ACTIVITY LOG")
        self.log_group.setObjectName("logGroupBox")
        layout = QVBoxLayout(self.log_group)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(1000)
        self.log_output.setFixedHeight(110)
        self.log_output.setVisible(False)  # Collapsed by default

        top_row = QHBoxLayout()
        self.log_hint = QLabel("Real-time extraction and download output")
        self.log_hint.setStyleSheet("font-size: 12px; font-weight: 500;")
        top_row.addWidget(self.log_hint)
        top_row.addStretch(1)

        self.toggle_log_btn = QPushButton("Show Log ▾")
        self.toggle_log_btn.setObjectName("secondaryButton")
        self.toggle_log_btn.setFixedHeight(28)
        self.toggle_log_btn.setStyleSheet("font-size: 12px; padding: 2px 10px;")
        self.toggle_log_btn.clicked.connect(self._on_toggle_log)
        top_row.addWidget(self.toggle_log_btn)

        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setObjectName("secondaryButton")
        self.clear_log_btn.setFixedHeight(28)
        self.clear_log_btn.setStyleSheet("font-size: 12px; padding: 2px 10px;")
        self.clear_log_btn.clicked.connect(self.log_output.clear)
        top_row.addWidget(self.clear_log_btn)

        layout.addLayout(top_row)
        layout.addWidget(self.log_output)

        return self.log_group

    # -------------------------------------------------------------------------
    # Settings & Environment Setup
    # -------------------------------------------------------------------------

    def _update_platform_combo_availability(self) -> None:
        """
        Applies enabled/disabled state, styling, and tooltips to platform selector items.
        Keeps YouTube and TikTok enabled. Greys out and disables Douyin while temporarily frozen.
        """
        if not hasattr(self, "platform_combo"):
            return
        model = self.platform_combo.model()
        for i in range(self.platform_combo.count()):
            plat_id = self.platform_combo.itemData(i)
            item = model.item(i) if hasattr(model, "item") else None
            if item is None:
                continue
            is_avail = PlatformRegistry.is_available(plat_id)
            if is_avail:
                item.setEnabled(True)
                item.setSelectable(True)
                item.setToolTip("")
                item.setData(None, Qt.ItemDataRole.ForegroundRole)
            else:
                item.setEnabled(False)
                item.setSelectable(False)
                tooltip = tr("platform_douyin_unavailable_tooltip") if plat_id == "douyin" else tr(f"platform_{plat_id}_unavailable_tooltip")
                item.setToolTip(tooltip)
                # Subtle greyed-out appearance consistent with current UI and both light/dark themes
                item.setForeground(QBrush(QColor("#94a3b8")))

    def _on_url_text_changed(self, text: str) -> None:
        """Auto-detects platform when URL is pasted or typed, seamlessly updating platform selector."""
        if getattr(self, "_switching_platform", False) or getattr(self, "_loading_settings", False):
            return
        cleaned = text.strip()
        if not cleaned:
            return
        detected = PlatformDetector.identify_platform_id(cleaned)
        if detected in ("youtube", "tiktok", "douyin"):
            if not PlatformRegistry.is_available(detected):
                # Do NOT auto-switch to a temporarily frozen platform
                return
            current = self.platform_combo.currentData() or "youtube"
            if detected != current:
                self._switching_platform = True
                idx = self.platform_combo.findData(detected)
                if idx >= 0:
                    self.platform_combo.setCurrentIndex(idx)
                self._active_platform = detected
                self._apply_platform_ui(detected)
                self.settings_manager.set("selected_platform", detected)
                self._switching_platform = False

    def _on_platform_changed(self) -> None:
        """Triggered when platform selector dropdown value is changed by the user."""
        if getattr(self, "_loading_settings", False) or getattr(self, "_switching_platform", False):
            return
        platform_id = self.platform_combo.currentData() or "youtube"
        if not PlatformRegistry.is_available(platform_id):
            fallback = getattr(self, "_active_platform", "youtube")
            if not PlatformRegistry.is_available(fallback):
                fallback = "youtube"
            self.log(f"[WARNING] Platform '{platform_id}' is temporarily unavailable.")
            self.status_bar.showMessage(tr("platform_douyin_unavailable_tooltip"), 4000)
            self._switching_platform = True
            idx = self.platform_combo.findData(fallback)
            if idx >= 0:
                self.platform_combo.setCurrentIndex(idx)
            self._switching_platform = False
            return

        self._active_platform = platform_id
        self._apply_platform_ui(platform_id)
        self._on_setting_changed()

    def _apply_platform_ui(self, platform_id: str) -> None:
        """Updates UI labels, placeholders, and capability constraints based on active platform."""
        if not PlatformRegistry.is_available(platform_id):
            platform_id = "youtube"
        prev_switching = getattr(self, "_switching_platform", False)
        self._switching_platform = True
        try:
            self._active_platform = platform_id
            is_douyin = (platform_id == "douyin")
            is_tiktok = (platform_id == "tiktok")

            if is_douyin:
                if hasattr(self, "url_group"):
                    self.url_group.setTitle(tr("section_douyin_link"))
                if hasattr(self, "url_label"):
                    self.url_label.setText(tr("douyin_url_label"))
                if hasattr(self, "url_input"):
                    self.url_input.setPlaceholderText(tr("douyin_url_placeholder"))
                if hasattr(self, "scan_btn") and getattr(self, "_current_ui_state", "idle") == "idle":
                    self.scan_btn.setText(tr("scan_douyin"))
            elif is_tiktok:
                if hasattr(self, "url_group"):
                    self.url_group.setTitle(tr("section_tiktok_link"))
                if hasattr(self, "url_label"):
                    self.url_label.setText(tr("tiktok_url_label"))
                if hasattr(self, "url_input"):
                    self.url_input.setPlaceholderText(tr("tiktok_url_placeholder"))
                if hasattr(self, "scan_btn") and getattr(self, "_current_ui_state", "idle") == "idle":
                    self.scan_btn.setText(tr("scan_tiktok"))
            else:
                if hasattr(self, "url_group"):
                    self.url_group.setTitle(tr("section_youtube_link"))
                if hasattr(self, "url_label"):
                    self.url_label.setText(tr("channel_url_label"))
                if hasattr(self, "url_input"):
                    self.url_input.setPlaceholderText(tr("channel_url_placeholder"))
                if hasattr(self, "scan_btn") and getattr(self, "_current_ui_state", "idle") == "idle":
                    self.scan_btn.setText(tr("scan_channel"))

            if hasattr(self, "platform_combo"):
                idx = self.platform_combo.findData(platform_id)
                if idx >= 0 and self.platform_combo.currentIndex() != idx:
                    self.platform_combo.blockSignals(True)
                    self.platform_combo.setCurrentIndex(idx)
                    self.platform_combo.blockSignals(False)

            # Update table columns for active platform (hide subtitle column on TikTok, extend Title horizontal space)
            if hasattr(self, "video_table"):
                self.video_table.set_platform(platform_id)

            if hasattr(self, "mode_combo"):
                self._on_mode_changed()
        finally:
            self._switching_platform = prev_switching

    def _load_saved_settings(self) -> None:
        """Populates UI controls with saved settings from SettingsManager."""
        self.url_input.setText(self.settings_manager.get("last_channel_url", "https://www.youtube.com/@PythonSimplified"))
        self.folder_input.setText(self.settings_manager.get("download_folder", str(Path.home() / "Downloads" / "Channel Harvest")))

        def _set_combo(combo: QComboBox, val: str):
            idx = combo.findData(val)
            if idx < 0:
                idx = combo.findText(val)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        # Platform selector
        saved_platform = self.settings_manager.get("selected_platform", "youtube")
        if not PlatformRegistry.is_available(saved_platform):
            saved_platform = "youtube"
            self.settings_manager.set("selected_platform", "youtube")
        self._active_platform = saved_platform
        _set_combo(self.platform_combo, saved_platform)
        self._apply_platform_ui(saved_platform)
        self._update_platform_combo_availability()

        # Mode
        saved_mode = self.settings_manager.get("download_mode", DownloadMode.VIDEO_ONLY)
        if saved_mode == "Subtitle Only":
            saved_mode = DownloadMode.ASSETS_ONLY
        _set_combo(self.mode_combo, saved_mode)

        # Video dropdowns
        _set_combo(self.format_combo, self.settings_manager.get("format", "MOV"))
        _set_combo(self.quality_combo, self.settings_manager.get("quality", "1080p"))
        _set_combo(self.bitrate_combo, self.settings_manager.get("bitrate", "Best Available"))

        # Audio dropdowns
        _set_combo(self.audio_format_combo, self.settings_manager.get("audio_format", "WAV"))
        _set_combo(self.audio_bitrate_combo, self.settings_manager.get("audio_bitrate", "Best Available"))

        # Subtitle controls
        self.subtitles_cb.setChecked(self.settings_manager.get("download_subtitles", False))
        _set_combo(self.sub_source_combo, self.settings_manager.get("subtitle_source", SubtitleSource.BEST_AVAILABLE))
        _set_combo(self.sub_lang_combo, self.settings_manager.get("subtitle_language", SubtitleLanguage.CHINESE))
        _set_combo(self.sub_format_combo, self.settings_manager.get("subtitle_format", "SRT"))

        # Thumbnail controls
        self.thumbnail_cb.setChecked(self.settings_manager.get("download_thumbnail", False))
        _set_combo(self.thumb_format_combo, self.settings_manager.get("thumbnail_format", ThumbnailFormat.JPG))

        self._on_thumbnail_toggled(self.thumbnail_cb.isChecked())

        # Archive info controls
        self.save_desc_cb.setChecked(self.settings_manager.get("save_description", False))
        self.save_meta_cb.setChecked(self.settings_manager.get("save_metadata", False))
        self.save_chapters_cb.setChecked(self.settings_manager.get("save_chapters", False))

        self.skip_existing_cb.setChecked(self.settings_manager.get("skip_existing", False))
        self.channel_folder_cb.setChecked(self.settings_manager.get("create_channel_folder", True))
        self.individual_folder_cb.setChecked(self.settings_manager.get("create_individual_video_folders", False))
        self.include_video_id_cb.setChecked(self.settings_manager.get("include_video_id_in_filename", False))

        # Synchronize enabled/disabled states based on restored mode and platform capabilities
        self._on_mode_changed()

    def _on_mode_changed(self, mode_text: Optional[str] = None) -> None:
        """Dynamically enables or disables Video/Audio/Subtitle controls based on mode and platform capabilities."""
        canonical_mode = self.mode_combo.currentData() or self.mode_combo.currentText()
        if mode_text is not None and isinstance(mode_text, str):
            if mode_text in (
                DownloadMode.VIDEO_ONLY,
                DownloadMode.AUDIO_ONLY,
                DownloadMode.VIDEO_AND_AUDIO,
                DownloadMode.ASSETS_ONLY,
                "Subtitle Only",
            ):
                canonical_mode = mode_text

        enable_video = canonical_mode in (DownloadMode.VIDEO_ONLY, DownloadMode.VIDEO_AND_AUDIO)
        enable_audio = canonical_mode in (DownloadMode.AUDIO_ONLY, DownloadMode.VIDEO_AND_AUDIO)
        is_assets_only = canonical_mode in (DownloadMode.ASSETS_ONLY, "Subtitle Only")

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

        # Platform capability gating
        current_platform = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
        adapter = PlatformRegistry.get_adapter(current_platform)
        supports_subs = adapter.capabilities.supports_subtitles if adapter else True
        supports_chapters = adapter.capabilities.supports_chapters if adapter else True

        if not supports_chapters:
            self.save_chapters_cb.setEnabled(False)
            if current_platform == "douyin":
                self.save_chapters_cb.setToolTip(tr("tooltip_douyin_no_chapters"))
            else:
                self.save_chapters_cb.setToolTip(tr("tooltip_tiktok_no_chapters"))
        else:
            self.save_chapters_cb.setEnabled(True)
            self.save_chapters_cb.setToolTip(tr("cb_save_chapters_tooltip"))

        # Subtitle controls in Additional Assets
        if not supports_subs:
            self.subtitles_cb.blockSignals(True)
            self.subtitles_cb.setChecked(False)
            self.subtitles_cb.setEnabled(False)
            self.subtitles_cb.blockSignals(False)
            if current_platform == "douyin":
                self.subtitles_cb.setToolTip(tr("tooltip_douyin_no_subs"))
            else:
                self.subtitles_cb.setToolTip(tr("tooltip_tiktok_no_subs"))
        else:
            self.subtitles_cb.setEnabled(True)
            self.subtitles_cb.setToolTip("")
            saved_sub = self.settings_manager.get("download_subtitles", False)
            self.subtitles_cb.blockSignals(True)
            self.subtitles_cb.setChecked(saved_sub)
            self.subtitles_cb.blockSignals(False)

        self._on_subtitles_toggled()

    def _on_subtitles_toggled(self) -> None:
        """Enables or disables subtitle configuration dropdowns based on checkbox state and platform capabilities."""
        current_platform = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
        adapter = PlatformRegistry.get_adapter(current_platform)
        supports_subs = adapter.capabilities.supports_subtitles if adapter else True

        if not supports_subs:
            enable_subs = False
        else:
            enable_subs = self.subtitles_cb.isChecked()

        self.sub_source_label.setEnabled(enable_subs)
        self.sub_source_combo.setEnabled(enable_subs)
        self.sub_lang_label.setEnabled(enable_subs)
        self.sub_lang_combo.setEnabled(enable_subs)
        self.sub_format_label.setEnabled(enable_subs)
        self.sub_format_combo.setEnabled(enable_subs)

        self._on_setting_changed()

    def _on_thumbnail_toggled(self, checked: bool) -> None:
        """Enables or disables thumbnail format dropdown based on checkbox state."""
        self.thumb_format_label.setEnabled(checked)
        self.thumb_format_combo.setEnabled(checked)
        self._on_setting_changed()

    def _on_setting_changed(self) -> None:
        """Saves current settings when changed by the user."""
        if getattr(self, "_loading_settings", False) or getattr(self, "_switching_platform", False):
            return
        current_platform = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
        self.settings_manager.set("download_mode", self.mode_combo.currentData() or self.mode_combo.currentText())
        self.settings_manager.set("format", self.format_combo.currentData() or self.format_combo.currentText())
        self.settings_manager.set("quality", self.quality_combo.currentData() or self.quality_combo.currentText())
        self.settings_manager.set("bitrate", self.bitrate_combo.currentData() or self.bitrate_combo.currentText())
        self.settings_manager.set("audio_format", self.audio_format_combo.currentData() or self.audio_format_combo.currentText())
        self.settings_manager.set("audio_bitrate", self.audio_bitrate_combo.currentData() or self.audio_bitrate_combo.currentText())
        if current_platform == "youtube":
            self.settings_manager.set("download_subtitles", self.subtitles_cb.isChecked())
        self.settings_manager.set("subtitle_source", self.sub_source_combo.currentData() or self.sub_source_combo.currentText())
        self.settings_manager.set("subtitle_language", self.sub_lang_combo.currentData() or self.sub_lang_combo.currentText())
        self.settings_manager.set("subtitle_format", self.sub_format_combo.currentData() or self.sub_format_combo.currentText())
        self.settings_manager.set("download_thumbnail", self.thumbnail_cb.isChecked())
        self.settings_manager.set("thumbnail_format", self.thumb_format_combo.currentData() or self.thumb_format_combo.currentText())
        self.settings_manager.set("save_description", self.save_desc_cb.isChecked())
        self.settings_manager.set("save_metadata", self.save_meta_cb.isChecked())
        self.settings_manager.set("save_chapters", self.save_chapters_cb.isChecked())
        self.settings_manager.set("download_folder", self.folder_input.text().strip())
        self.settings_manager.set("skip_existing", self.skip_existing_cb.isChecked())
        self.settings_manager.set("create_channel_folder", self.channel_folder_cb.isChecked())
        self.settings_manager.set("create_individual_video_folders", self.individual_folder_cb.isChecked())
        self.settings_manager.set("include_video_id_in_filename", self.include_video_id_cb.isChecked())
        self.settings_manager.set("selected_platform", self.platform_combo.currentData() or "youtube")
        self.settings_manager.set("last_channel_url", self.url_input.text().strip())

    def _check_environment_status(self) -> None:
        """Detects FFmpeg availability on startup and preheats runtime version cache."""
        is_ffmpeg_ok, ffmpeg_path, version_str, _ = FFmpegChecker.detect()
        if not is_ffmpeg_ok:
            self.log(tr("log_ffmpeg_warning"))

        # Asynchronously preheat runtime manager version cache so opening Settings is instant
        import threading
        threading.Thread(target=RuntimeManager.get_installed_versions, daemon=True).start()

        # Pre-construct SettingsDialog during idle time for instantaneous (<1 ms) display
        QTimer.singleShot(250, self._preheat_settings_dialog)

    def _preheat_settings_dialog(self) -> None:
        """Pre-constructs SettingsDialog in idle time so clicking Settings opens instantly."""
        if self._settings_dialog is None:
            try:
                self._settings_dialog = SettingsDialog(self, settings_manager=self.settings_manager)
            except Exception:
                pass

    def _set_ui_state(self, state: str) -> None:
        """
        State machine managing enabled/disabled button states.
        States: 'idle', 'scanning', 'downloading', 'paused'
        """
        self._current_ui_state = state
        has_selected = len(self.video_table.get_selected_videos()) > 0

        if state == "idle":
            self.scan_btn.setEnabled(True)
            platform_id = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
            if platform_id == "douyin":
                self.scan_btn.setText(tr("scan_douyin"))
            elif platform_id == "tiktok":
                self.scan_btn.setText(tr("scan_tiktok"))
            else:
                self.scan_btn.setText(tr("scan_channel"))
            self.download_btn.setEnabled(has_selected)
            self.download_btn.setText(tr("btn_start_download"))
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.open_folder_btn.setEnabled(True)

        elif state == "scanning":
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText(tr("scanning"))
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
        platform_id = self.platform_combo.currentData() or "youtube"

        # Auto-detect if user entered a URL belonging to another platform
        detected = PlatformDetector.identify_platform_id(raw_url)
        if detected != "unknown" and not PlatformRegistry.is_available(detected):
            from core.error_classifier import ErrorClassifier
            classified = ErrorClassifier.for_unavailable_platform(detected)
            self.log(f"[BLOCKED] {classified.title}: {classified.user_message}")
            QMessageBox.warning(
                self,
                classified.get_localized_title(),
                f"{classified.get_localized_user_message()}\n\n{classified.get_localized_suggested_action()}",
            )
            return

        if not PlatformRegistry.is_available(platform_id):
            from core.error_classifier import ErrorClassifier
            classified = ErrorClassifier.for_unavailable_platform(platform_id)
            self.log(f"[BLOCKED] {classified.title}: {classified.user_message}")
            QMessageBox.warning(
                self,
                classified.get_localized_title(),
                f"{classified.get_localized_user_message()}\n\n{classified.get_localized_suggested_action()}",
            )
            return

        if detected in ("youtube", "tiktok", "douyin") and detected != platform_id and PlatformRegistry.is_available(detected):
            platform_id = detected
            self._switching_platform = True
            idx = self.platform_combo.findData(detected)
            if idx >= 0:
                self.platform_combo.setCurrentIndex(idx)
            self._active_platform = detected
            self._apply_platform_ui(detected)
            self.settings_manager.set("selected_platform", detected)
            self._switching_platform = False

        adapter = PlatformRegistry.get_adapter(platform_id)
        if adapter:
            is_valid, error_reason = adapter.validate_url(raw_url)
        else:
            is_valid, error_reason = YtDlpEngine.validate_url(raw_url)

        if not is_valid:
            self.log(f"[ERROR] URL Validation Failed: {error_reason}")
            if platform_id == "douyin":
                QMessageBox.warning(
                    self,
                    tr("dialog_invalid_douyin_url_title"),
                    tr("dialog_invalid_douyin_url_msg"),
                )
            elif platform_id == "tiktok":
                QMessageBox.warning(
                    self,
                    tr("dialog_invalid_tiktok_url_title"),
                    tr("dialog_invalid_tiktok_url_msg"),
                )
            else:
                localized_reason = error_reason
                if I18nManager.is_chinese():
                    if "cannot be empty" in error_reason:
                        localized_reason = "链接不能为空。请输入 YouTube 频道或播放列表链接。"
                    elif "must begin with" in error_reason:
                        localized_reason = "链接必须以 http:// 或 https:// 开头。"
                    elif "not a valid YouTube domain" in error_reason:
                        localized_reason = error_reason.replace("Domain", "域名").replace("is not a valid YouTube domain.", "不是有效的 YouTube 域名。")
                    elif "specific channel, playlist, or video path" in error_reason:
                        localized_reason = "请输入具体的频道、播放列表或视频路径。"
                    elif "Malformed URL" in error_reason:
                        localized_reason = error_reason.replace("Malformed URL:", "链接格式错误:")
                QMessageBox.warning(
                    self,
                    tr("dialog_invalid_url_title"),
                    f"{localized_reason}\n\n{tr('dialog_invalid_url_msg')}\nhttps://www.youtube.com/@ChannelName",
                )
            return

        if self._scan_worker is not None and self._scan_worker.isRunning():
            return

        if self._sub_detect_worker is not None and self._sub_detect_worker.isRunning():
            self._sub_detect_worker.cancel()
            self._sub_detect_worker.wait(500)

        self._set_ui_state("scanning")
        self.status_bar.showMessage(tr("status_scanning"))

        supports_cookies = (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file) if adapter else (platform_id == "youtube")
        pfx = f"{platform_id}_" if platform_id != "youtube" else ""
        browser_cookies = self.settings_manager.get(f"{pfx}browser_cookies", "none") if supports_cookies else "none"
        custom_cookie_file = self.settings_manager.get(f"{pfx}custom_cookie_file", "") if supports_cookies else ""
        auth_config = adapter.get_auth_config(self.settings_manager) if adapter else None

        self._scan_worker = ChannelScanWorker(
            url=raw_url,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            platform_id=platform_id,
            parent=self,
        )
        self._scan_worker.log_message.connect(self.log)
        self._scan_worker.scan_completed.connect(self._on_scan_completed)
        self._scan_worker.scan_error.connect(self._on_scan_error)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_completed(self, videos: list) -> None:
        """Populates the table with extracted videos and triggers background subtitle detection."""
        platform_id = self.platform_combo.currentData() or "youtube"
        adapter = PlatformRegistry.get_adapter(platform_id)
        supports_subs = adapter.capabilities.supports_subtitles if adapter else True

        for v in videos:
            v.subtitle_status = "Checking..." if supports_subs else "—"
        self.video_table.load_videos(videos)
        if videos:
            self._current_channel_title = videos[0].channel_title
        self.status_bar.showMessage(tr("status_scan_complete_fmt", count=len(videos)))
        self.log(tr("log_scan_finished_fmt", count=len(videos)))

        # Concurrently detect subtitle availability in background ONLY if platform supports it
        if not supports_subs:
            return

        if self._sub_detect_worker is not None and self._sub_detect_worker.isRunning():
            self._sub_detect_worker.cancel()
            self._sub_detect_worker.wait(500)

        self._sub_detect_worker = SubtitleDetectionWorker(videos=videos, parent=self)
        self._sub_detect_worker.video_subtitle_detected.connect(self._on_video_subtitle_detected)
        self._sub_detect_worker.detection_finished.connect(self._on_subtitle_detection_finished)
        self._sub_detect_worker.start()

    def _on_video_subtitle_detected(self, video_id: str, status_text: str, tooltip: str) -> None:
        """Slot called in real-time as each video's subtitle availability is determined."""
        self.video_table.update_video_subtitle_status(video_id, status_text, tooltip)

    def _on_subtitle_detection_finished(self) -> None:
        """Called when all videos in the table have been checked for subtitles."""
        self.status_bar.showMessage(tr("status_ready"))
        self.log(tr("log_subtitle_detection_done"))

    def _on_scan_error(self, error_message: str) -> None:
        """Alerts the user when scanning fails with actionable localized guidance."""
        self.status_bar.showMessage(tr("status_scan_failed"))
        platform_id = self.platform_combo.currentData() or "youtube"
        try:
            from core.error_classifier import ErrorClassifier
            from core.i18n import I18nManager
            err = ErrorClassifier.classify(
                raw_error=error_message,
                stage="scan",
                platform=platform_id,
            )
            is_zh = I18nManager.is_chinese()
            lang = "zh_CN" if is_zh else "en"
            title = err.get_localized_title(lang) or tr("error")
            user_msg = err.get_localized_user_message(lang)
            action = err.get_localized_suggested_action(lang)
            if user_msg and action:
                display_msg = f"{user_msg}\n\n{action}"
            elif user_msg:
                display_msg = user_msg
            else:
                display_msg = error_message
            QMessageBox.warning(self, title, display_msg)
        except Exception:
            QMessageBox.warning(self, tr("error"), error_message)

    def _on_scan_finished(self) -> None:
        """Resets UI state after scan worker finishes."""
        self._scan_worker = None
        self._set_ui_state("idle")

    def _on_selection_changed(self, selected_count: int, total_count: int) -> None:
        """Updates download button enabled state and status bar."""
        self.status_bar.showMessage(tr("videos_selected_fmt", selected=selected_count))
        if self._download_manager is None or not self._download_manager.isRunning():
            self.download_btn.setEnabled(selected_count > 0)

    # -------------------------------------------------------------------------
    # Download Queue Management
    # -------------------------------------------------------------------------

    def _on_download_clicked(self) -> None:
        """Initiates the sequential download queue in a background QThread."""
        # Stop background subtitle detection if still running
        if self._sub_detect_worker is not None and self._sub_detect_worker.isRunning():
            self._sub_detect_worker.cancel()

        selected_videos = self.video_table.get_selected_videos()

        if not selected_videos:
            QMessageBox.information(
                self,
                tr("dialog_no_selection_title"),
                tr("dialog_no_selection_msg"),
            )
            return

        folder_str = self.folder_input.text().strip()
        if not folder_str:
            QMessageBox.warning(self, tr("dialog_missing_dest_title"), tr("dialog_missing_dest_msg"))
            return

        # Prepare settings
        mode_val = self.mode_combo.currentData() or self.mode_combo.currentText()
        is_assets_only = mode_val in (DownloadMode.ASSETS_ONLY, "Subtitle Only")

        if is_assets_only:
            has_any_asset = (
                self.subtitles_cb.isChecked()
                or self.thumbnail_cb.isChecked()
                or self.save_desc_cb.isChecked()
                or self.save_meta_cb.isChecked()
                or self.save_chapters_cb.isChecked()
            )
            if not has_any_asset:
                QMessageBox.warning(
                    self,
                    tr("dialog_no_assets_selected_title"),
                    tr("dialog_no_assets_selected_msg"),
                )
                return

        platform_id = self.platform_combo.currentData() or "youtube"
        if not PlatformRegistry.is_available(platform_id):
            from core.error_classifier import ErrorClassifier
            classified = ErrorClassifier.for_unavailable_platform(platform_id)
            self.log(f"[BLOCKED] {classified.title}: {classified.user_message}")
            QMessageBox.warning(
                self,
                classified.get_localized_title(),
                f"{classified.get_localized_user_message()}\n\n{classified.get_localized_suggested_action()}",
            )
            return

        adapter = PlatformRegistry.get_adapter(platform_id)
        supports_cookies = (adapter.capabilities.supports_browser_cookies or adapter.capabilities.supports_cookie_file) if adapter else (platform_id == "youtube")
        if platform_id == "douyin":
            active_cookies = self.settings_manager.get("douyin_browser_cookies", "none") if supports_cookies else "none"
            active_file = self.settings_manager.get("douyin_custom_cookie_file", "") if supports_cookies else ""
        elif platform_id == "youtube":
            active_cookies = self.settings_manager.get("browser_cookies", "none") if supports_cookies else "none"
            active_file = self.settings_manager.get("custom_cookie_file", "") if supports_cookies else ""
        else:
            active_cookies = "none"
            active_file = ""

        settings = DownloadSettings(
            download_mode=mode_val,
            format=self.format_combo.currentData() or self.format_combo.currentText(),
            quality=self.quality_combo.currentData() or self.quality_combo.currentText(),
            bitrate=self.bitrate_combo.currentData() or self.bitrate_combo.currentText(),
            audio_format=self.audio_format_combo.currentData() or self.audio_format_combo.currentText(),
            audio_bitrate=self.audio_bitrate_combo.currentData() or self.audio_bitrate_combo.currentText(),
            download_folder=folder_str,
            create_channel_folder=self.channel_folder_cb.isChecked(),
            create_individual_video_folders=self.individual_folder_cb.isChecked(),
            include_video_id_in_filename=self.include_video_id_cb.isChecked(),
            skip_existing=self.skip_existing_cb.isChecked(),
            channel_title=self._current_channel_title,
            download_subtitles=self.subtitles_cb.isChecked(),
            subtitle_source=self.sub_source_combo.currentData() or self.sub_source_combo.currentText(),
            subtitle_language=self.sub_lang_combo.currentData() or self.sub_lang_combo.currentText(),
            subtitle_format=self.sub_format_combo.currentData() or self.sub_format_combo.currentText(),
            download_thumbnail=self.thumbnail_cb.isChecked(),
            thumbnail_format=self.thumb_format_combo.currentData() or self.thumb_format_combo.currentText(),
            save_description=self.save_desc_cb.isChecked(),
            save_metadata=self.save_meta_cb.isChecked(),
            save_chapters=self.save_chapters_cb.isChecked(),
            browser_cookies=active_cookies,
            custom_cookie_file=active_file,
            douyin_auth_method=self.settings_manager.get("douyin_auth_method", "none"),
            douyin_browser_cookies=self.settings_manager.get("douyin_browser_cookies", "none"),
            douyin_browser_profile=self.settings_manager.get("douyin_browser_profile", "Default"),
            douyin_custom_cookie_file=self.settings_manager.get("douyin_custom_cookie_file", ""),
        )

        # Check FFmpeg requirement warning
        is_ffmpeg_ok, _, _, _ = FFmpegChecker.detect()
        if not is_ffmpeg_ok:
            needs_ffmpeg = (
                (settings.download_mode != DownloadMode.AUDIO_ONLY and not is_assets_only)
                or settings.audio_format in ("MP3", "WAV", "AAC", "FLAC", "OPUS")
                or settings.download_subtitles
                or (settings.download_thumbnail and settings.thumbnail_format != ThumbnailFormat.ORIGINAL)
            )
            if needs_ffmpeg:
                reply = QMessageBox.question(
                    self,
                    tr("dialog_ffmpeg_warning_title"),
                    tr("dialog_ffmpeg_warning_msg"),
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
        self._download_manager.video_subtitle_status.connect(self.video_table.update_video_subtitle_status)
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
            self.taskbar_progress.pause()
            self.status_bar.showMessage(tr("status_paused"))

    def _on_resume_clicked(self) -> None:
        """Resumes paused download queue."""
        if self._download_manager and self._download_manager.isRunning():
            self._download_manager.resume()
            self._set_ui_state("downloading")
            self.taskbar_progress.resume()
            self.status_bar.showMessage(tr("status_resumed"))

    def _on_cancel_clicked(self) -> None:
        """Cancels active download and stops remaining queue."""
        if self._download_manager and self._download_manager.isRunning():
            reply = QMessageBox.question(
                self,
                tr("dialog_confirm_cancel_title"),
                tr("dialog_confirm_cancel_msg"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.cancel_btn.setEnabled(False)
                self.taskbar_progress.clear()
                self.status_bar.showMessage(tr("status_cancelled"))
                self._download_manager.cancel()

    def _on_queue_started(self, total: int) -> None:
        """Updates UI when queue starts."""
        self._queue_total = total
        self._queue_completed = 0
        self._queue_skipped = 0
        self._queue_failed = 0
        self._current_video_pct = 0.0
        self.current_progress_bar.setValue(0)
        self.overall_progress_bar.setValue(0)
        self.taskbar_progress.set_progress(0, 100)
        self.queue_label.setText(tr("overall_progress_fmt", completed=0, total=total))
        self.queue_stats_label.setText(tr("queue_stats_fmt", completed=0, skipped=0, failed=0, remaining=total))
        self.status_bar.showMessage(tr("status_downloading_fmt", index=1, total=total, title="..."))

    def _on_video_started(self, video_id: str, title: str, index: int, total: int) -> None:
        """Updates UI for the newly active video."""
        self._current_video_pct = 0.0
        self.current_video_label.setText(tr("current_video_fmt", title=f"({index}/{total}) {title}"))
        self.current_progress_bar.setValue(0)
        self.status_bar.showMessage(tr("status_downloading_fmt", index=index, total=total, title=title))

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
        self._current_video_pct = percent
        self.current_progress_bar.setValue(int(percent))
        self.item_stats_label.setText(f"{downloaded_str} / {total_str}")
        self.speed_label.setText(tr("speed_fmt", speed=speed))
        self.eta_label.setText(tr("eta_fmt", eta=eta))

        # Real-time sub-item overall progress for smooth UI & taskbar feedback
        if hasattr(self, "_queue_total") and self._queue_total > 0:
            finished = self._queue_completed + self._queue_skipped + self._queue_failed
            smooth_overall_pct = min(100.0, max(0.0, ((finished + (percent / 100.0)) / self._queue_total) * 100.0))
            self.overall_progress_bar.setValue(int(smooth_overall_pct))
            self.taskbar_progress.set_progress(int(smooth_overall_pct * 10), 1000)

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
        self._queue_completed = completed
        self._queue_skipped = skipped
        self._queue_failed = failed
        total = completed + skipped + failed + remaining
        self._queue_total = total
        self.overall_progress_bar.setValue(int(overall_pct))
        self.taskbar_progress.set_progress(int(overall_pct * 10), 1000)
        self.queue_label.setText(f"{tr('overall_progress_fmt', completed=completed + skipped, total=total)} ({overall_pct:.0f}%)")
        self.queue_stats_label.setText(
            tr("queue_stats_fmt", completed=completed, skipped=skipped, failed=failed, remaining=remaining)
        )

    def _on_queue_finished(self, completed: int, skipped: int, failed: int, total: int) -> None:
        """Displays completion summary dialog and restores UI state."""
        self.taskbar_progress.clear()
        self._set_ui_state("idle")
        self.status_bar.showMessage(tr("status_finished_fmt", completed=completed, skipped=skipped, failed=failed))

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

    def is_download_active(self) -> bool:
        """Returns whether the download queue is actively running."""
        return bool(self._download_manager and self._download_manager.isRunning())

    def _on_download_error(self, title: str, message: str) -> None:
        """Displays an error dialog from the download manager and records diagnostics."""
        ErrorTracker.record_error(message)
        QMessageBox.warning(self, title, message)

    # -------------------------------------------------------------------------
    # Folder & Log Helpers
    # -------------------------------------------------------------------------

    def _on_browse_clicked(self) -> None:
        """Opens native Windows folder picker."""
        current_dir = self.folder_input.text().strip() or str(Path.home() / "Downloads")
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            tr("select_folder_title"),
            current_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected_dir:
            self.folder_input.setText(selected_dir)
            self._on_setting_changed()
            self.log(tr("log_dest_set_fmt", path=selected_dir))

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
            QMessageBox.warning(self, tr("error"), tr("could_not_open_dir_fmt", error=e))

    def is_download_active(self) -> bool:
        """Returns True if a video download queue is currently running."""
        return self._download_manager is not None and self._download_manager.isRunning()

    def _on_theme_changed(self, effective_theme: str, is_dark: bool) -> None:
        """Updates main window dynamic elements (e.g. settings icon and action icons) when theme switches."""
        if hasattr(self, "settings_btn"):
            self.settings_btn.setIcon(get_settings_icon())
        if hasattr(self, "download_btn"):
            self.download_btn.setIcon(get_action_icon("download"))
        if hasattr(self, "pause_btn"):
            self.pause_btn.setIcon(get_action_icon("pause"))
        if hasattr(self, "resume_btn"):
            self.resume_btn.setIcon(get_action_icon("resume"))
        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setIcon(get_action_icon("cancel"))
        if hasattr(self, "open_folder_btn"):
            self.open_folder_btn.setIcon(get_action_icon("folder"))

    def _on_language_changed(self, lang: str) -> None:
        """Triggered when language changes in settings."""
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Dynamically retranslates all labels, placeholders, buttons, and combo texts."""
        self.setWindowTitle(tr("app_title"))
        if hasattr(self, "subtitle_label"):
            self.subtitle_label.setText(tr("app_subtitle"))
        if hasattr(self, "settings_btn"):
            self.settings_btn.setToolTip(tr("settings_tooltip"))

        # Platform & URL Section
        if hasattr(self, "platform_label"):
            self.platform_label.setText(tr("platform_label"))
        if hasattr(self, "platform_combo"):
            current_id = self.platform_combo.currentData() or "youtube"
            for i in range(self.platform_combo.count()):
                d = self.platform_combo.itemData(i)
                if d == "youtube":
                    self.platform_combo.setItemText(i, tr("platform_youtube"))
                elif d == "tiktok":
                    self.platform_combo.setItemText(i, tr("platform_tiktok"))
                elif d == "douyin":
                    self.platform_combo.setItemText(i, tr("platform_douyin"))
            self._update_platform_combo_availability()
            self._apply_platform_ui(current_id)
        else:
            if hasattr(self, "url_group"):
                self.url_group.setTitle(tr("section_youtube_link"))
            if hasattr(self, "url_label"):
                self.url_label.setText(tr("channel_url_label"))
            if hasattr(self, "url_input"):
                self.url_input.setPlaceholderText(tr("channel_url_placeholder"))

        # Video List Section
        if hasattr(self, "video_group"):
            self.video_group.setTitle(tr("section_available_videos"))

        # Settings Section
        if hasattr(self, "download_group"):
            self.download_group.setTitle(tr("section_download_option"))
        if hasattr(self, "folder_prefix"):
            self.folder_prefix.setText(tr("save_to"))
        if hasattr(self, "browse_btn"):
            self.browse_btn.setText(tr("browse"))

        # MEDIA
        if hasattr(self, "media_title"):
            self.media_title.setText(tr("subsection_media"))
        if hasattr(self, "mode_label"):
            self.mode_label.setText(tr("label_mode"))
        if hasattr(self, "quality_label"):
            self.quality_label.setText(tr("label_resolution"))
        if hasattr(self, "video_format_label"):
            self.video_format_label.setText(tr("label_video_format"))
        if hasattr(self, "video_bitrate_label"):
            self.video_bitrate_label.setText(tr("label_video_bitrate"))
        if hasattr(self, "audio_format_label"):
            self.audio_format_label.setText(tr("label_audio_format"))
        if hasattr(self, "audio_bitrate_label"):
            self.audio_bitrate_label.setText(tr("label_audio_bitrate"))

        # Dropdowns in MEDIA
        if hasattr(self, "mode_combo"):
            for i in range(self.mode_combo.count()):
                data = self.mode_combo.itemData(i)
                if data:
                    self.mode_combo.setItemText(i, I18nManager.get_mode_label(data))
        if hasattr(self, "quality_combo"):
            for i in range(self.quality_combo.count()):
                data = self.quality_combo.itemData(i)
                if data:
                    self.quality_combo.setItemText(i, I18nManager.get_quality_label(data))
        if hasattr(self, "bitrate_combo"):
            for i in range(self.bitrate_combo.count()):
                data = self.bitrate_combo.itemData(i)
                if data:
                    self.bitrate_combo.setItemText(i, I18nManager.get_video_bitrate_label(data))
        if hasattr(self, "audio_bitrate_combo"):
            for i in range(self.audio_bitrate_combo.count()):
                data = self.audio_bitrate_combo.itemData(i)
                if data:
                    self.audio_bitrate_combo.setItemText(i, I18nManager.get_audio_bitrate_label(data))

        # ADDITIONAL ASSETS
        if hasattr(self, "assets_title"):
            self.assets_title.setText(tr("subsection_assets"))
        if hasattr(self, "subtitles_cb"):
            self.subtitles_cb.setText(tr("cb_subtitles"))
            current_platform = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
            adapter = PlatformRegistry.get_adapter(current_platform)
            supports_subs = adapter.capabilities.supports_subtitles if adapter else True
            if not supports_subs:
                if current_platform == "douyin":
                    self.subtitles_cb.setToolTip(tr("tooltip_douyin_no_subs"))
                else:
                    self.subtitles_cb.setToolTip(tr("tooltip_tiktok_no_subs"))
            else:
                self.subtitles_cb.setToolTip("")
        if hasattr(self, "thumbnail_cb"):
            self.thumbnail_cb.setText(tr("cb_thumbnail"))
            self.thumbnail_cb.setToolTip(tr("cb_thumbnail_tooltip"))
        if hasattr(self, "sub_source_label"):
            self.sub_source_label.setText(tr("label_sub_source"))
        if hasattr(self, "thumb_format_label"):
            self.thumb_format_label.setText(tr("label_thumb_format"))
        if hasattr(self, "thumb_format_combo"):
            self.thumb_format_combo.setToolTip(tr("label_thumb_format_tooltip"))
            for i in range(self.thumb_format_combo.count()):
                data = self.thumb_format_combo.itemData(i)
                if data:
                    self.thumb_format_combo.setItemText(i, I18nManager.get_thumb_format_label(data))
        if hasattr(self, "sub_source_combo"):
            for i in range(self.sub_source_combo.count()):
                data = self.sub_source_combo.itemData(i)
                if data:
                    self.sub_source_combo.setItemText(i, I18nManager.get_sub_source_label(data))
        if hasattr(self, "sub_lang_label"):
            self.sub_lang_label.setText(tr("label_sub_lang"))
        if hasattr(self, "sub_lang_combo"):
            for i in range(self.sub_lang_combo.count()):
                data = self.sub_lang_combo.itemData(i)
                if data:
                    self.sub_lang_combo.setItemText(i, I18nManager.get_sub_lang_label(data))
        if hasattr(self, "sub_format_label"):
            self.sub_format_label.setText(tr("label_sub_format"))

        # INFORMATION FILES
        if hasattr(self, "info_header"):
            self.info_header.setText(tr("subgroup_info_files"))
        if hasattr(self, "save_desc_cb"):
            self.save_desc_cb.setText(tr("cb_save_desc"))
            self.save_desc_cb.setToolTip(tr("cb_save_desc_tooltip"))
        if hasattr(self, "save_meta_cb"):
            self.save_meta_cb.setText(tr("cb_save_meta"))
            self.save_meta_cb.setToolTip(tr("cb_save_meta_tooltip"))
        if hasattr(self, "save_chapters_cb"):
            self.save_chapters_cb.setText(tr("cb_save_chapters"))
            current_platform = self.platform_combo.currentData() if hasattr(self, "platform_combo") else "youtube"
            adapter = PlatformRegistry.get_adapter(current_platform)
            supports_chapters = adapter.capabilities.supports_chapters if adapter else True
            if not supports_chapters:
                if current_platform == "douyin":
                    self.save_chapters_cb.setToolTip(tr("tooltip_douyin_no_chapters"))
                else:
                    self.save_chapters_cb.setToolTip(tr("tooltip_tiktok_no_chapters"))
            else:
                self.save_chapters_cb.setToolTip(tr("cb_save_chapters_tooltip"))

        # FILE ORGANIZATION
        if hasattr(self, "org_title"):
            self.org_title.setText(tr("subsection_org"))
        if hasattr(self, "skip_existing_cb"):
            self.skip_existing_cb.setText(tr("cb_skip_existing"))
            self.skip_existing_cb.setToolTip(tr("cb_skip_existing_tooltip"))
        if hasattr(self, "channel_folder_cb"):
            self.channel_folder_cb.setText(tr("cb_channel_folder"))
            self.channel_folder_cb.setToolTip(tr("cb_channel_folder_tooltip"))
        if hasattr(self, "individual_folder_cb"):
            self.individual_folder_cb.setText(tr("cb_individual_folder"))
            self.individual_folder_cb.setToolTip(tr("cb_individual_folder_tooltip"))
        if hasattr(self, "include_video_id_cb"):
            self.include_video_id_cb.setText(tr("cb_include_video_id"))
            self.include_video_id_cb.setToolTip(tr("cb_include_video_id_tooltip"))

        # Action Buttons
        if hasattr(self, "pause_btn"):
            self.pause_btn.setText(tr("btn_pause"))
            self.pause_btn.setToolTip(tr("btn_pause_tooltip"))
        if hasattr(self, "resume_btn"):
            self.resume_btn.setText(tr("btn_resume"))
            self.resume_btn.setToolTip(tr("btn_resume_tooltip"))
        if hasattr(self, "cancel_btn"):
            self.cancel_btn.setText(tr("btn_cancel"))
            self.cancel_btn.setToolTip(tr("btn_cancel_tooltip"))
        if hasattr(self, "open_folder_btn"):
            self.open_folder_btn.setText(tr("btn_open_folder"))
            self.open_folder_btn.setToolTip(tr("btn_open_folder_tooltip"))

        # Reapply current state texts to scan_btn and download_btn
        self._set_ui_state(getattr(self, "_current_ui_state", "idle"))

        # Progress Section
        if hasattr(self, "progress_group"):
            self.progress_group.setTitle(tr("section_download_progress"))
        if hasattr(self, "current_video_label") and (self._download_manager is None or not self._download_manager.isRunning()):
            self.current_video_label.setText(tr("current_video_none"))
        if hasattr(self, "queue_label") and (self._download_manager is None or not self._download_manager.isRunning()):
            self.queue_label.setText(tr("overall_progress_fmt", completed=0, total=0))
        if hasattr(self, "speed_label") and (self._download_manager is None or not self._download_manager.isRunning()):
            self.speed_label.setText(tr("speed_fmt", speed="-- MB/s"))
        if hasattr(self, "eta_label") and (self._download_manager is None or not self._download_manager.isRunning()):
            self.eta_label.setText(tr("eta_fmt", eta="--:--"))
        if hasattr(self, "queue_stats_label") and (self._download_manager is None or not self._download_manager.isRunning()):
            self.queue_stats_label.setText(tr("queue_stats_fmt", completed=0, skipped=0, failed=0, remaining=0))

        # Log Section
        if hasattr(self, "log_group"):
            self.log_group.setTitle(tr("section_activity_log"))
        if hasattr(self, "log_hint"):
            self.log_hint.setText(tr("log_hint"))
        if hasattr(self, "toggle_log_btn"):
            if hasattr(self, "log_output") and self.log_output.isVisible():
                self.toggle_log_btn.setText(tr("hide_log"))
            else:
                self.toggle_log_btn.setText(tr("show_log"))
        if hasattr(self, "clear_log_btn"):
            self.clear_log_btn.setText(tr("clear_log"))

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
            self.log(tr("log_update_available_fmt", latest=latest_ver, current=current_ver))
        elif not error_msg:
            self.settings_manager.set("last_ytdlp_update_check", time.time())

    def _on_settings_clicked(self) -> None:
        """Opens the Settings modal dialog."""
        if self._settings_dialog is not None:
            dialog = self._settings_dialog
            self._settings_dialog = None
            try:
                dialog._sync_auth_ui_from_settings()
            except Exception:
                pass
            dialog.exec()
            # Pre-construct next instance in idle time
            QTimer.singleShot(500, self._preheat_settings_dialog)
        else:
            dialog = SettingsDialog(self, settings_manager=self.settings_manager)
            dialog.exec()

    def _on_toggle_log(self) -> None:
        """Toggles visibility of the activity log to maximize vertical space."""
        if self.log_output.isVisible():
            self.log_output.setVisible(False)
            self.toggle_log_btn.setText(tr("show_log"))
        else:
            self.log_output.setVisible(True)
            self.toggle_log_btn.setText(tr("hide_log"))

    def log(self, message: str) -> None:
        """Appends a timestamped message to the activity log panel with ANSI escapes stripped."""
        clean_msg = ANSI_ESCAPE_RE.sub("", message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {clean_msg}")
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handles graceful application shutdown and settings persistence."""
        if getattr(self, "_settings_dialog", None) is not None:
            try:
                self._settings_dialog.close()
            except Exception:
                pass
            self._settings_dialog = None

        ThemeManager.unregister_listener(self._on_theme_changed)
        I18nManager.unregister_listener(self._on_language_changed)

        # Check if downloads are actively running
        if self._download_manager is not None and self._download_manager.isRunning():
            reply = QMessageBox.question(
                self,
                tr("ytdlp_busy_title"),
                tr("dialog_confirm_cancel_msg"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_manager.cancel()
                self._download_manager.wait(3000)  # Wait up to 3 seconds for clean exit
            else:
                event.ignore()
                return

        # Clean up taskbar progress
        self.taskbar_progress.clear()

        # Save window geometry
        self.settings_manager.set("window_width", self.width())
        self.settings_manager.set("window_height", self.height())
        self._on_setting_changed()
        event.accept()
