"""
settings_dialog.py
Settings and About dialog for Channel Harvest.

Sections:
1. Header & Application Branding (Name, Logo, Version Badge, Subtitle)
2. Appearance (Theme: System, Light, Dark)
3. System Components:
   - FFmpeg (Status, Version, Path, Copy Path)
   - yt-dlp (Status, Version, Check for Updates, Safe Update Installation)
4. Data Directory (Path, Open Data Folder)
5. Footer (Copyright, Developer, Close button)
"""

import os
import time
from pathlib import Path
from typing import Optional

import yt_dlp
from PySide6.QtCore import Qt, QByteArray, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QGuiApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QComboBox,
    QCheckBox,
    QMessageBox,
)

from core.paths import get_logo_file, get_app_data_dir
from core.settings import SettingsManager
from core.version import __version__, __developer__, __copyright__
from downloader.ffmpeg_checker import FFmpegChecker
from downloader.updater import YtDlpUpdater, CheckUpdateWorker, InstallUpdateWorker
from gui.styles import ThemeMode, ThemeManager


def get_settings_icon(color: Optional[str] = None) -> QIcon:
    """Returns a crisp SVG gear icon for the settings button."""
    if color is None:
        color = "#94a3b8" if ThemeManager.is_dark() else "#475569"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"></circle>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
    </svg>"""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


class SettingsDialog(QDialog):
    """
    Settings and About modal dialog for Channel Harvest.
    Modern, clean, commercial-grade Windows utility dialog.
    """

    APP_VERSION = f"v{__version__}"
    DEVELOPER = __developer__
    COPYRIGHT = __copyright__

    def __init__(self, parent: Optional[QWidget] = None, settings_manager: Optional[SettingsManager] = None):
        super().__init__(parent)
        self.setWindowTitle("Settings - Channel Harvest")
        self.setFixedWidth(490)
        self.setModal(True)

        self.settings_manager = settings_manager or SettingsManager()

        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        self._ffmpeg_path: str = ""
        self._copy_btn: Optional[QPushButton] = None
        self._ver_badge: Optional[QLabel] = None

        # Updater state
        self._current_ytdlp_ver: str = YtDlpUpdater.get_installed_version()
        self._latest_ytdlp_ver: str = ""
        self._check_worker: Optional[CheckUpdateWorker] = None
        self._install_worker: Optional[InstallUpdateWorker] = None

        self._init_ui()

        # Listen for theme updates
        ThemeManager.register_listener(self._on_theme_updated)

    def closeEvent(self, event):
        ThemeManager.unregister_listener(self._on_theme_updated)
        super().closeEvent(event)

    def _create_divider(self) -> QFrame:
        """Creates a subtle 1px horizontal rule styled by the active theme."""
        sep = QFrame()
        sep.setObjectName("divider")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        return sep

    def _init_ui(self) -> None:
        """Builds the clean, modern visual layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(13)

        # ---------------------------------------------------------------------
        # 1. HEADER / BRANDING (Only place application name & version appear)
        # ---------------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setSpacing(14)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        logo_file = get_logo_file()
        if logo_file.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_file))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    44,
                    44,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_label.setPixmap(scaled)
                logo_label.setFixedSize(44, 44)
                header_layout.addWidget(logo_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        app_name_lbl = QLabel("Channel Harvest")
        app_name_lbl.setObjectName("appTitleLabel")
        name_row.addWidget(app_name_lbl)

        self._ver_badge = QLabel(self.APP_VERSION)
        self._update_badge_style()
        name_row.addWidget(self._ver_badge)
        name_row.addStretch()
        title_col.addLayout(name_row)

        subtitle_lbl = QLabel("Harvest your channel. Keep every video.")
        subtitle_lbl.setObjectName("appSubtitleLabel")
        title_col.addWidget(subtitle_lbl)

        header_layout.addLayout(title_col, stretch=1)
        layout.addLayout(header_layout)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 2. APPEARANCE SECTION
        # ---------------------------------------------------------------------
        appear_title = QLabel("APPEARANCE")
        appear_title.setObjectName("sectionHeader")
        layout.addWidget(appear_title)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_row.setContentsMargins(4, 0, 4, 0)

        theme_lbl = QLabel("Theme")
        theme_lbl.setStyleSheet("font-size: 13px; font-weight: 500;")
        theme_row.addWidget(theme_lbl)

        theme_row.addStretch()

        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(140)
        self.theme_combo.addItem("System", ThemeMode.SYSTEM)
        self.theme_combo.addItem("Light", ThemeMode.LIGHT)
        self.theme_combo.addItem("Dark", ThemeMode.DARK)

        current_theme = self.settings_manager.get("theme", ThemeMode.SYSTEM)
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        theme_row.addWidget(self.theme_combo)

        layout.addLayout(theme_row)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 3. SYSTEM COMPONENTS SECTION
        # ---------------------------------------------------------------------
        sys_title = QLabel("SYSTEM COMPONENTS")
        sys_title.setObjectName("sectionHeader")
        layout.addWidget(sys_title)

        sys_box = QVBoxLayout()
        sys_box.setSpacing(10)
        sys_box.setContentsMargins(0, 0, 0, 0)

        # 3a. FFmpeg Card
        ffmpeg_card = QFrame()
        ffmpeg_card.setObjectName("componentCard")
        ffmpeg_card_layout = QVBoxLayout(ffmpeg_card)
        ffmpeg_card_layout.setContentsMargins(12, 10, 12, 10)
        ffmpeg_card_layout.setSpacing(6)

        is_ffmpeg_ok, ffmpeg_path, ffmpeg_ver, _ = FFmpegChecker.detect()
        self._ffmpeg_path = str(ffmpeg_path) if ffmpeg_path else ""

        ffmpeg_top = QHBoxLayout()
        ffmpeg_top.setSpacing(8)

        ffmpeg_name = QLabel("FFmpeg")
        ffmpeg_name.setStyleSheet("font-size: 13px; font-weight: 600;")
        ffmpeg_top.addWidget(ffmpeg_name)

        if is_ffmpeg_ok:
            ffmpeg_status = QLabel("<span style='color: #16a34a; font-weight: 600;'>● Installed</span>")
            ffmpeg_status.setStyleSheet("font-size: 12px;")
            ffmpeg_top.addWidget(ffmpeg_status)
            ffmpeg_top.addStretch()

            ffmpeg_ver_lbl = QLabel(f"v{ffmpeg_ver}")
            ffmpeg_ver_lbl.setStyleSheet("font-size: 12px;")
            ffmpeg_top.addWidget(ffmpeg_ver_lbl)
        else:
            ffmpeg_status = QLabel("<span style='color: #dc2626; font-weight: 600;'>● Not Found</span>")
            ffmpeg_status.setStyleSheet("font-size: 12px;")
            ffmpeg_top.addWidget(ffmpeg_status)
            ffmpeg_top.addStretch()

        ffmpeg_card_layout.addLayout(ffmpeg_top)

        if is_ffmpeg_ok and self._ffmpeg_path:
            path_row = QHBoxLayout()
            path_row.setSpacing(8)

            elided_path = self._elide_path(self._ffmpeg_path)
            path_lbl = QLabel(f"Path: {elided_path}")
            path_lbl.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
            path_lbl.setToolTip(self._ffmpeg_path)
            path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            path_row.addWidget(path_lbl, stretch=1)

            self._copy_btn = QPushButton("Copy Path")
            self._copy_btn.setObjectName("compactButton")
            self._copy_btn.setToolTip("Copy executable path to clipboard")
            self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._copy_btn.clicked.connect(self._on_copy_path_clicked)
            path_row.addWidget(self._copy_btn)

            ffmpeg_card_layout.addLayout(path_row)
        elif not is_ffmpeg_ok:
            missing_hint = QLabel("Required for merging video and audio streams into MP4/MKV.")
            missing_hint.setStyleSheet("color: #dc2626; font-size: 11px;")
            ffmpeg_card_layout.addWidget(missing_hint)

        sys_box.addWidget(ffmpeg_card)

        # 3b. yt-dlp Card with Updater
        ytdlp_card = QFrame()
        ytdlp_card.setObjectName("componentCard")
        self._ytdlp_card_layout = QVBoxLayout(ytdlp_card)
        self._ytdlp_card_layout.setContentsMargins(12, 10, 12, 10)
        self._ytdlp_card_layout.setSpacing(6)

        # Top row: Name + Status Badge + Version / Action Button
        self._ytdlp_top = QHBoxLayout()
        self._ytdlp_top.setSpacing(8)

        ytdlp_name = QLabel("yt-dlp")
        ytdlp_name.setStyleSheet("font-size: 13px; font-weight: 600;")
        self._ytdlp_top.addWidget(ytdlp_name)

        self._ytdlp_status_lbl = QLabel("<span style='color: #16a34a; font-weight: 600;'>● Installed</span>")
        self._ytdlp_status_lbl.setStyleSheet("font-size: 12px;")
        self._ytdlp_top.addWidget(self._ytdlp_status_lbl)

        self._ytdlp_top.addStretch()

        self._ytdlp_ver_lbl = QLabel(f"v{self._current_ytdlp_ver}")
        self._ytdlp_ver_lbl.setStyleSheet("font-size: 12px;")
        self._ytdlp_top.addWidget(self._ytdlp_ver_lbl)

        self._check_update_btn = QPushButton("Check for Updates")
        self._check_update_btn.setObjectName("compactButton")
        self._check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_update_btn.clicked.connect(self._on_check_updates_clicked)
        self._ytdlp_top.addWidget(self._check_update_btn)

        self._ytdlp_card_layout.addLayout(self._ytdlp_top)

        # Update Available Row (hidden initially)
        self._update_info_row = QHBoxLayout()
        self._update_info_row.setSpacing(8)

        self._update_info_lbl = QLabel("")
        self._update_info_lbl.setStyleSheet("font-size: 11px;")
        self._update_info_row.addWidget(self._update_info_lbl, stretch=1)

        self._update_install_btn = QPushButton("Update yt-dlp")
        self._update_install_btn.setObjectName("compactButton")
        self._update_install_btn.setStyleSheet("background-color: #0066cc; color: #ffffff; font-weight: 600;")
        self._update_install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_install_btn.clicked.connect(self._on_install_update_clicked)
        self._update_install_btn.setVisible(False)
        self._update_info_row.addWidget(self._update_install_btn)

        self._ytdlp_card_layout.addLayout(self._update_info_row)

        # Auto-check checkbox
        auto_check_val = self.settings_manager.get("auto_check_ytdlp_updates", True)
        self.auto_check_cb = QCheckBox("Automatically check for yt-dlp updates")
        self.auto_check_cb.setStyleSheet("font-size: 11px;")
        self.auto_check_cb.setChecked(bool(auto_check_val))
        self.auto_check_cb.toggled.connect(self._on_auto_check_toggled)
        self._ytdlp_card_layout.addWidget(self.auto_check_cb)

        sys_box.addWidget(ytdlp_card)
        layout.addLayout(sys_box)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 4. DATA DIRECTORY SECTION
        # ---------------------------------------------------------------------
        data_title = QLabel("DATA DIRECTORY")
        data_title.setObjectName("sectionHeader")
        layout.addWidget(data_title)

        data_box = QVBoxLayout()
        data_box.setSpacing(3)
        data_box.setContentsMargins(4, 0, 4, 0)

        data_desc = QLabel("Application data & download archive:")
        data_desc.setStyleSheet("font-size: 12px;")
        data_box.addWidget(data_desc)

        data_row = QHBoxLayout()
        data_row.setSpacing(8)

        app_data_path = str(get_app_data_dir())
        data_path_lbl = QLabel(app_data_path)
        data_path_lbl.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
        data_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data_path_lbl.setToolTip(app_data_path)
        data_row.addWidget(data_path_lbl, stretch=1)

        open_folder_btn = QPushButton("Open Data Folder")
        open_folder_btn.setObjectName("compactButton")
        open_folder_btn.setToolTip("Open %APPDATA%\\ChannelHarvest in Windows File Explorer")
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._on_open_data_folder)
        data_row.addWidget(open_folder_btn)

        data_box.addLayout(data_row)
        layout.addLayout(data_box)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 5. FOOTER (Understated Developer Info + Clean Close Button)
        # ---------------------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)
        footer_layout.setContentsMargins(0, 4, 0, 0)

        dev_col = QVBoxLayout()
        dev_col.setSpacing(1)

        copyright_lbl = QLabel("Channel Harvest © 2026")
        copyright_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        dev_col.addWidget(copyright_lbl)

        dev_lbl = QLabel(f"Developed by {self.DEVELOPER}")
        dev_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        dev_col.addWidget(dev_lbl)

        footer_layout.addLayout(dev_col)
        footer_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.setMinimumHeight(32)
        close_btn.setMinimumWidth(80)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)

        layout.addLayout(footer_layout)

    def _update_badge_style(self) -> None:
        """Applies theme-appropriate styling to the version pill badge."""
        if not self._ver_badge:
            return
        if ThemeManager.is_dark():
            self._ver_badge.setStyleSheet(
                "background-color: #1e3a5f; color: #38bdf8; font-size: 11px; "
                "font-weight: 600; padding: 2px 8px; border-radius: 9px;"
            )
        else:
            self._ver_badge.setStyleSheet(
                "background-color: #e0f2fe; color: #0284c7; font-size: 11px; "
                "font-weight: 600; padding: 2px 8px; border-radius: 9px;"
            )

    def _on_theme_updated(self, effective_theme: str, is_dark: bool) -> None:
        """Listener invoked when application theme changes dynamically."""
        self._update_badge_style()

    def _on_theme_combo_changed(self, index: int) -> None:
        """Handles user selecting a new theme from the Appearance dropdown."""
        theme_pref = self.theme_combo.currentData()
        self.settings_manager.set("theme", theme_pref)
        ThemeManager.apply_theme(theme_pref)

    def _on_auto_check_toggled(self, checked: bool) -> None:
        """Persists the automatic update check preference."""
        self.settings_manager.set("auto_check_ytdlp_updates", checked)

    def _on_check_updates_clicked(self) -> None:
        """Initiates non-blocking background check for yt-dlp updates."""
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText("Checking...")
        self._ytdlp_status_lbl.setText("<span style='color: #0284c7; font-weight: 500;'>Checking...</span>")
        self._update_info_lbl.setText("")
        self._update_install_btn.setVisible(False)

        self._check_worker = CheckUpdateWorker(self)
        self._check_worker.check_completed.connect(self._on_check_completed)
        self._check_worker.start()

    def _on_check_completed(self, has_update: bool, current_ver: str, latest_ver: str, error_msg: str) -> None:
        """Handles result of the yt-dlp update check."""
        self._check_update_btn.setEnabled(True)
        self._current_ytdlp_ver = current_ver
        self._latest_ytdlp_ver = latest_ver
        self.settings_manager.set("last_ytdlp_update_check", time.time())

        if error_msg:
            self._check_update_btn.setText("Retry")
            self._ytdlp_status_lbl.setText("<span style='color: #dc2626; font-weight: 500;'>Check Failed</span>")
            self._update_info_lbl.setText(f"<span style='color: #dc2626;'>{error_msg}</span>")
            self._update_install_btn.setVisible(False)
        elif has_update:
            self._check_update_btn.setText("Check Again")
            self._ytdlp_status_lbl.setText("<span style='color: #f59e0b; font-weight: 600;'>● Update available</span>")
            self._update_info_lbl.setText(
                f"Current: <b>v{current_ver}</b> &nbsp;|&nbsp; Latest: <b style='color: #16a34a;'>v{latest_ver}</b>"
            )
            self._update_install_btn.setVisible(True)
        else:
            self._check_update_btn.setText("Check Again")
            self._ytdlp_status_lbl.setText("<span style='color: #16a34a; font-weight: 600;'>✓ Up to date</span>")
            self._update_info_lbl.setText(f"<span style='color: #16a34a;'>v{current_ver} is the latest version.</span>")
            self._update_install_btn.setVisible(False)

    def _on_install_update_clicked(self) -> None:
        """Safely coordinates yt-dlp update installation."""
        # 1. Guard against updating while download is active
        is_busy = False
        parent_win = self.parent()
        if parent_win and hasattr(parent_win, "is_download_active"):
            is_busy = parent_win.is_download_active()

        if is_busy:
            QMessageBox.information(
                self,
                "Download in Progress",
                "yt-dlp cannot be updated while a download is running.\n\n"
                "Please finish or cancel the current download first.",
            )
            return

        # 2. Ask user for confirmation
        reply = QMessageBox.question(
            self,
            "Update yt-dlp",
            f"A new yt-dlp version is available.\n\n"
            f"Current version: v{self._current_ytdlp_ver}\n"
            f"Latest version: v{self._latest_ytdlp_ver}\n\n"
            f"Would you like to update?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 3. Launch background install worker
        self._update_install_btn.setEnabled(False)
        self._update_install_btn.setText("Updating...")
        self._check_update_btn.setEnabled(False)
        self._update_info_lbl.setText("Downloading and installing update...")

        self._install_worker = InstallUpdateWorker(self)
        self._install_worker.install_completed.connect(self._on_install_completed)
        self._install_worker.start()

    def _on_install_completed(self, success: bool, new_ver: str, error_msg: str) -> None:
        """Handles completion of the update installation."""
        self._update_install_btn.setEnabled(True)
        self._check_update_btn.setEnabled(True)

        if success:
            self._current_ytdlp_ver = new_ver
            self._ytdlp_ver_lbl.setText(f"v{new_ver}")
            self._ytdlp_status_lbl.setText("<span style='color: #16a34a; font-weight: 600;'>✓ Up to date</span>")
            self._update_info_lbl.setText(f"<span style='color: #16a34a;'>Successfully updated to v{new_ver}!</span>")
            self._update_install_btn.setVisible(False)
            self._check_update_btn.setText("Check Again")

            QMessageBox.information(
                self,
                "Update Complete",
                f"yt-dlp has been updated to v{new_ver} successfully.",
            )
        else:
            self._update_install_btn.setText("Retry Update")
            self._update_info_lbl.setText(f"<span style='color: #dc2626;'>{error_msg}</span>")
            QMessageBox.warning(
                self,
                "Update Failed",
                f"Could not update yt-dlp:\n{error_msg}\n\n"
                "Your existing yt-dlp installation was preserved.",
            )

    def _elide_path(self, path_str: str, max_chars: int = 40) -> str:
        """Elides path cleanly in the middle so basename and drive remain visible."""
        if len(path_str) <= max_chars:
            return path_str
        try:
            p = Path(path_str)
            parts = p.parts
            if len(parts) >= 3:
                drive = parts[0]
                tail = f"{parts[-2]}\\{parts[-1]}" if len(parts) >= 4 else parts[-1]
                return f"{drive}...\\{tail}"
        except Exception:
            pass
        return path_str[:14] + "..." + path_str[-18:]

    def _on_copy_path_clicked(self) -> None:
        """Copies FFmpeg executable path to clipboard and shows brief feedback."""
        if not self._ffmpeg_path:
            return
        QGuiApplication.clipboard().setText(self._ffmpeg_path)
        if self._copy_btn:
            self._copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self._copy_btn.setText("Copy Path") if self._copy_btn else None)

    def _on_open_data_folder(self) -> None:
        """Opens the %APPDATA%/ChannelHarvest directory in File Explorer."""
        path = get_app_data_dir()
        if path.exists():
            try:
                os.startfile(str(path))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not open directory:\n{e}")
