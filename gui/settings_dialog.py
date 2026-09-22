"""
settings_dialog.py
Settings, Runtime Manager, and Diagnostic Report dialog for Channel Harvest.

Sections:
1. Header & Application Branding (Name, Logo, Version Badge, Subtitle)
2. Appearance (Theme: System, Light, Dark | Language: English, 简体中文)
3. Runtime Manager (Coordinated yt-dlp, EJS, Deno, and FFmpeg version status & updates)
4. YouTube Authentication (Browser cookies selector + local verification test)
5. Diagnostic Report (Privacy-safe troubleshooting report + clipboard copy & log folder)
6. Data Directory (AppData location + Open Data Folder button)
7. Footer (Copyright, Developer credit, Close button)
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, QByteArray, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QGuiApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QScrollArea,
    QApplication,
    QLineEdit,
    QFileDialog,
    QRadioButton,
    QButtonGroup,
)

from core.paths import get_logo_file, get_app_data_dir, get_logs_dir
from core.settings import SettingsManager
from core.version import __version__, __developer__, __copyright__
from core.i18n import I18nManager, tr
from core.diagnostics import DiagnosticReporter, ErrorTracker
from downloader.runtime_manager import (
    RuntimeManager,
    ComponentInfo,
    CheckRuntimeWorker,
    InstallRuntimeWorker,
)
from downloader.updater import YtDlpUpdater, CheckUpdateWorker, InstallUpdateWorker
from downloader.auth_checker import (
    AuthChecker,
    AuthStatusCode,
    AuthTestResult,
    get_browser_profiles,
    validate_cookie_file,
)
from gui.auth_result_dialog import AuthResultDialog
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


class AuthTestWorker(QThread):
    """Background worker for asynchronous stage-aware authentication testing."""
    finished = Signal(object)

    def __init__(self, browser_or_file: str, custom_cookie_path: Optional[str] = None, profile: Optional[str] = None):
        super().__init__()
        self.browser_or_file = browser_or_file
        self.custom_cookie_path = custom_cookie_path
        self.profile = profile

    def run(self):
        from downloader.auth_checker import AuthChecker
        result = AuthChecker.test_authentication(
            self.browser_or_file,
            custom_cookie_path=self.custom_cookie_path,
            profile=self.profile,
        )
        self.finished.emit(result)


class SettingsDialog(QDialog):
    """
    Settings, Runtime Manager, and Diagnostic modal dialog for Channel Harvest.
    Modern, clean, commercial-grade Windows utility dialog.
    """

    APP_VERSION = f"v{__version__}"
    DEVELOPER = __developer__
    COPYRIGHT = __copyright__

    def __init__(self, parent: Optional[QWidget] = None, settings_manager: Optional[SettingsManager] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_window_title"))
        self.setFixedWidth(580)
        self.resize(580, 840)
        self.setMinimumHeight(600)
        self.setModal(True)

        self.settings_manager = settings_manager or SettingsManager()

        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        self._ver_badge: Optional[QLabel] = None

        # Live runtime state
        self._runtime_components: Dict[str, ComponentInfo] = RuntimeManager.get_installed_versions()
        self._check_worker: Optional[CheckRuntimeWorker] = None
        self._install_worker: Optional[InstallRuntimeWorker] = None

        # Backward compatibility aliases for legacy updater worker
        self._current_ytdlp_ver = self._runtime_components.get("ytdlp", ComponentInfo("ytdlp", "yt-dlp")).current_version
        self._latest_ytdlp_ver = ""
        self._last_auth_result: Optional[Any] = None

        self._init_ui()

        # Listen for theme and language updates
        ThemeManager.register_listener(self._on_theme_updated)
        I18nManager.register_listener(self._on_language_updated)

    def closeEvent(self, event):
        ThemeManager.unregister_listener(self._on_theme_updated)
        I18nManager.unregister_listener(self._on_language_updated)
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
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 16, 20, 14)
        root_layout.setSpacing(10)

        # ---------------------------------------------------------------------
        # 1. HEADER / BRANDING
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
                    42,
                    42,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo_label.setPixmap(scaled)
                logo_label.setFixedSize(42, 42)
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

        self.subtitle_lbl = QLabel(tr("app_subtitle"))
        self.subtitle_lbl.setObjectName("appSubtitleLabel")
        title_col.addWidget(self.subtitle_lbl)

        header_layout.addLayout(title_col, stretch=1)
        root_layout.addLayout(header_layout)

        root_layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # CENTRAL SCROLL AREA (Ensures clean fit on all laptop resolutions)
        # ---------------------------------------------------------------------
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(4, 2, 8, 2)
        layout.setSpacing(9)

        # ---------------------------------------------------------------------
        # 2. APPEARANCE SECTION
        # ---------------------------------------------------------------------
        self.appear_title = QLabel(tr("settings_appearance"))
        self.appear_title.setObjectName("sectionHeader")
        layout.addWidget(self.appear_title)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_row.setContentsMargins(4, 0, 4, 0)

        self.theme_lbl = QLabel(tr("settings_theme"))
        self.theme_lbl.setStyleSheet("font-size: 13px; font-weight: 500;")
        theme_row.addWidget(self.theme_lbl)
        theme_row.addStretch()

        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(140)
        self.theme_combo.addItem(I18nManager.get_theme_label("System"), ThemeMode.SYSTEM)
        self.theme_combo.addItem(I18nManager.get_theme_label("Light"), ThemeMode.LIGHT)
        self.theme_combo.addItem(I18nManager.get_theme_label("Dark"), ThemeMode.DARK)

        current_theme = self.settings_manager.get("theme", ThemeMode.SYSTEM)
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)

        # Language row
        lang_row = QHBoxLayout()
        lang_row.setSpacing(12)
        lang_row.setContentsMargins(4, 0, 4, 0)

        self.lang_lbl = QLabel(tr("settings_language"))
        self.lang_lbl.setStyleSheet("font-size: 13px; font-weight: 500;")
        lang_row.addWidget(self.lang_lbl)
        lang_row.addStretch()

        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(140)
        for label, code in I18nManager.LANGUAGES:
            self.lang_combo.addItem(label, code)

        current_lang = self.settings_manager.get("language", I18nManager.LANG_EN)
        l_idx = self.lang_combo.findData(current_lang)
        if l_idx >= 0:
            self.lang_combo.setCurrentIndex(l_idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        lang_row.addWidget(self.lang_combo)
        layout.addLayout(lang_row)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 3. RUNTIME MANAGER SECTION
        # ---------------------------------------------------------------------
        self.runtime_title = QLabel(tr("runtime_manager_title"))
        self.runtime_title.setObjectName("sectionHeader")
        layout.addWidget(self.runtime_title)

        # Runtime Card
        runtime_card = QFrame()
        runtime_card.setObjectName("componentCard")
        runtime_card_layout = QVBoxLayout(runtime_card)
        runtime_card_layout.setContentsMargins(16, 14, 16, 14)
        runtime_card_layout.setSpacing(10)

        # Table Grid
        self._table_grid = QGridLayout()
        self._table_grid.setHorizontalSpacing(16)
        self._table_grid.setVerticalSpacing(8)
        self._table_grid.setColumnStretch(0, 0)
        self._table_grid.setColumnMinimumWidth(0, 110)
        self._table_grid.setColumnStretch(1, 0)
        self._table_grid.setColumnMinimumWidth(1, 140)
        self._table_grid.setColumnStretch(2, 1)

        # Table Headers
        self.th_comp = QLabel(tr("th_component"))
        self.th_comp.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748b;")
        self.th_ver = QLabel(tr("th_current_version"))
        self.th_ver.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748b;")
        self.th_stat = QLabel(tr("th_status"))
        self.th_stat.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748b;")

        self._table_grid.addWidget(self.th_comp, 0, 0)
        self._table_grid.addWidget(self.th_ver, 0, 1)
        self._table_grid.addWidget(self.th_stat, 0, 2)

        # Component row widgets dictionary
        self._comp_widgets: Dict[str, Dict[str, QLabel]] = {}
        row_idx = 1
        for comp_key in RuntimeManager.ALL_COMPONENTS:
            info = self._runtime_components.get(comp_key, ComponentInfo(comp_key, comp_key))
            
            name_lbl = QLabel(info.display_name)
            name_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
            
            ver_lbl = QLabel(f"v{info.current_version}" if not info.current_version.startswith("v") else info.current_version)
            ver_lbl.setStyleSheet("font-size: 12px; font-family: Consolas, monospace;")
            
            status_lbl = QLabel(self._format_status_html(info.status))
            status_lbl.setStyleSheet("font-size: 12px;")

            self._table_grid.addWidget(name_lbl, row_idx, 0)
            self._table_grid.addWidget(ver_lbl, row_idx, 1)
            self._table_grid.addWidget(status_lbl, row_idx, 2)

            self._comp_widgets[comp_key] = {
                "name": name_lbl,
                "version": ver_lbl,
                "status": status_lbl,
            }
            row_idx += 1

        runtime_card_layout.addLayout(self._table_grid)

        # Action Buttons Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self._check_runtime_btn = QPushButton(tr("check_runtime_updates"))
        self._check_runtime_btn.setObjectName("compactButton")
        self._check_runtime_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_runtime_btn.clicked.connect(self._on_check_runtime_clicked)
        actions_row.addWidget(self._check_runtime_btn)

        self._update_runtime_btn = QPushButton(tr("update_available_components"))
        self._update_runtime_btn.setObjectName("compactButton")
        self._update_runtime_btn.setStyleSheet("background-color: #0066cc; color: #ffffff; font-weight: 600;")
        self._update_runtime_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_runtime_btn.clicked.connect(self._on_update_components_clicked)
        self._update_runtime_btn.setVisible(False)
        actions_row.addWidget(self._update_runtime_btn)

        actions_row.addStretch()
        runtime_card_layout.addLayout(actions_row)

        # Auto-check Checkbox
        auto_check_val = self.settings_manager.get("auto_check_runtime_updates", True)
        self.auto_check_runtime_cb = QCheckBox(tr("auto_check_runtime"))
        self.auto_check_runtime_cb.setStyleSheet("font-size: 11px;")
        self.auto_check_runtime_cb.setChecked(bool(auto_check_val))
        self.auto_check_runtime_cb.toggled.connect(self._on_auto_check_runtime_toggled)
        runtime_card_layout.addWidget(self.auto_check_runtime_cb)

        layout.addWidget(runtime_card)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 4. YOUTUBE AUTHENTICATION SECTION
        # ---------------------------------------------------------------------
        self.auth_title = QLabel(tr("settings_auth"))
        self.auth_title.setObjectName("sectionHeader")
        layout.addWidget(self.auth_title)

        auth_box = QVBoxLayout()
        auth_box.setSpacing(8)
        auth_box.setContentsMargins(4, 0, 4, 0)

        # 4.1 Authentication Method Radio Selector
        method_row = QHBoxLayout()
        method_row.setSpacing(14)

        self.auth_method_lbl = QLabel(tr("auth_method_label"))
        self.auth_method_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        method_row.addWidget(self.auth_method_lbl)

        self.auth_method_group = QButtonGroup(self)
        self.auth_none_rb = QRadioButton(tr("auth_method_none"))
        self.auth_browser_rb = QRadioButton(tr("auth_method_browser"))
        self.auth_file_rb = QRadioButton(tr("auth_method_custom_file_radio"))

        self.auth_none_rb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auth_browser_rb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auth_file_rb.setCursor(Qt.CursorShape.PointingHandCursor)

        self.auth_method_group.addButton(self.auth_none_rb, 0)
        self.auth_method_group.addButton(self.auth_browser_rb, 1)
        self.auth_method_group.addButton(self.auth_file_rb, 2)
        self.auth_method_group.idClicked.connect(self._on_auth_method_button_clicked)

        method_row.addWidget(self.auth_none_rb)
        method_row.addWidget(self.auth_browser_rb)
        method_row.addWidget(self.auth_file_rb)
        method_row.addStretch()
        auth_box.addLayout(method_row)

        # 4.2 Panel 1: None (Authentication Disabled)
        self.auth_none_panel = QWidget()
        none_layout = QVBoxLayout(self.auth_none_panel)
        none_layout.setContentsMargins(0, 4, 0, 4)
        none_layout.setSpacing(4)

        self.none_status_lbl = QLabel(f"<b>{tr('auth_status_label')}</b> {tr('status_not_configured')}")
        self.none_status_lbl.setStyleSheet("font-size: 12px; color: #64748b;")
        none_layout.addWidget(self.none_status_lbl)

        self.none_hint_lbl = QLabel(tr("auth_none_hint"))
        self.none_hint_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
        self.none_hint_lbl.setWordWrap(True)
        none_layout.addWidget(self.none_hint_lbl)
        auth_box.addWidget(self.auth_none_panel)

        # 4.3 Panel 2: Browser Cookies
        self.auth_browser_panel = QWidget()
        browser_layout = QVBoxLayout(self.auth_browser_panel)
        browser_layout.setContentsMargins(0, 4, 0, 4)
        browser_layout.setSpacing(6)

        pickers_row = QHBoxLayout()
        pickers_row.setSpacing(10)

        self.browser_lbl = QLabel(tr("auth_browser_label"))
        self.browser_lbl.setStyleSheet("font-size: 12px; font-weight: 500;")
        pickers_row.addWidget(self.browser_lbl)

        self.browser_combo = QComboBox()
        self.browser_combo.setFixedWidth(160)
        self.browser_combo.addItem(tr("cookies_chrome"), "chrome")
        self.browser_combo.addItem(tr("cookies_edge"), "edge")
        self.browser_combo.addItem(tr("cookies_firefox"), "firefox")
        self.browser_combo.addItem(tr("cookies_brave"), "brave")
        self.browser_combo.addItem(tr("cookies_opera"), "opera")
        self.browser_combo.addItem(tr("cookies_vivaldi"), "vivaldi")
        self.browser_combo.currentIndexChanged.connect(self._on_browser_changed)
        pickers_row.addWidget(self.browser_combo)

        self.profile_lbl = QLabel(tr("auth_profile_label"))
        self.profile_lbl.setStyleSheet("font-size: 12px; font-weight: 500;")
        pickers_row.addWidget(self.profile_lbl)

        self.profile_combo = QComboBox()
        self.profile_combo.setFixedWidth(140)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        pickers_row.addWidget(self.profile_combo)

        pickers_row.addStretch()
        browser_layout.addLayout(pickers_row)

        browser_action_row = QHBoxLayout()
        browser_action_row.setSpacing(10)

        self.browser_status_lbl = QLabel(f"<b>{tr('auth_status_label')}</b> {tr('status_not_tested')}")
        self.browser_status_lbl.setStyleSheet("font-size: 12px;")
        browser_action_row.addWidget(self.browser_status_lbl)
        browser_action_row.addStretch()

        self._test_browser_btn = QPushButton(tr("auth_test_btn"))
        self._test_browser_btn.setObjectName("compactButton")
        self._test_browser_btn.setToolTip(tr("auth_test_tooltip"))
        self._test_browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_browser_btn.clicked.connect(self._on_test_browser_auth_clicked)
        browser_action_row.addWidget(self._test_browser_btn)

        browser_layout.addLayout(browser_action_row)

        # Inline recommendation if ABE/decryption fails
        self.browser_abe_widget = QWidget()
        abe_layout = QHBoxLayout(self.browser_abe_widget)
        abe_layout.setContentsMargins(0, 2, 0, 2)
        abe_layout.setSpacing(8)

        self.browser_abe_lbl = QLabel()
        self.browser_abe_lbl.setStyleSheet("font-size: 11px; color: #d97706;")
        self.browser_abe_lbl.setWordWrap(True)
        abe_layout.addWidget(self.browser_abe_lbl, stretch=1)

        self.browser_switch_btn = QPushButton(tr("auth_switch_to_cookie_file"))
        self.browser_switch_btn.setObjectName("compactButton")
        self.browser_switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_switch_btn.clicked.connect(self._on_switch_to_custom_file_clicked)
        abe_layout.addWidget(self.browser_switch_btn)

        self.browser_abe_widget.setVisible(False)
        browser_layout.addWidget(self.browser_abe_widget)

        self.browser_hint_lbl = QLabel(tr("settings_cookies_hint"))
        self.browser_hint_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
        self.browser_hint_lbl.setWordWrap(True)
        browser_layout.addWidget(self.browser_hint_lbl)

        auth_box.addWidget(self.auth_browser_panel)

        # 4.4 Panel 3: Custom Cookie File
        self.auth_file_panel = QWidget()
        file_layout = QVBoxLayout(self.auth_file_panel)
        file_layout.setContentsMargins(0, 4, 0, 4)
        file_layout.setSpacing(6)

        cfile_row = QHBoxLayout()
        cfile_row.setSpacing(8)

        self.cookie_file_lbl = QLabel(tr("auth_cookie_file_label"))
        self.cookie_file_lbl.setStyleSheet("font-size: 12px; font-weight: 500;")
        cfile_row.addWidget(self.cookie_file_lbl)

        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText(tr("auth_cookie_file_placeholder"))
        self.cookie_file_edit.setText(self.settings_manager.get("custom_cookie_file", ""))
        self.cookie_file_edit.textChanged.connect(self._on_cookie_file_changed)
        cfile_row.addWidget(self.cookie_file_edit, stretch=1)

        self.cookie_browse_btn = QPushButton(tr("browse"))
        self.cookie_browse_btn.setObjectName("compactButton")
        self.cookie_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cookie_browse_btn.clicked.connect(self._on_browse_cookie_file_clicked)
        cfile_row.addWidget(self.cookie_browse_btn)

        self._clear_file_btn = QPushButton(tr("auth_clear_cookie_file"))
        self._clear_file_btn.setObjectName("compactButton")
        self._clear_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_file_btn.clicked.connect(self._on_clear_cookie_file_clicked)
        cfile_row.addWidget(self._clear_file_btn)

        file_layout.addLayout(cfile_row)

        file_action_row = QHBoxLayout()
        file_action_row.setSpacing(10)

        self.cookie_file_status_lbl = QLabel(f"<b>{tr('auth_status_label')}</b> {tr('status_not_tested')}")
        self.cookie_file_status_lbl.setStyleSheet("font-size: 12px;")
        self.cookie_file_status_lbl.setWordWrap(True)
        file_action_row.addWidget(self.cookie_file_status_lbl, stretch=1)

        self._test_file_btn = QPushButton(tr("auth_test_btn"))
        self._test_file_btn.setObjectName("compactButton")
        self._test_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_file_btn.clicked.connect(self._on_test_file_auth_clicked)
        file_action_row.addWidget(self._test_file_btn)

        file_layout.addLayout(file_action_row)

        self.cookie_privacy_lbl = QLabel(f"🔒 <i>{tr('auth_cookie_file_privacy_notice')}</i>")
        self.cookie_privacy_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.cookie_privacy_lbl.setWordWrap(True)
        file_layout.addWidget(self.cookie_privacy_lbl)

        auth_box.addWidget(self.auth_file_panel)

        # 4.5 Diagnostics Sub-Section
        diag_sub_box = QHBoxLayout()
        diag_sub_box.setSpacing(12)
        last_s = self.settings_manager.get("last_auth_status", "NOT_CONFIGURED")
        self.auth_last_test_lbl = QLabel(f"<b>{tr('auth_last_test')}</b> {last_s}")
        self.auth_last_test_lbl.setStyleSheet("font-size: 11px; color: #64748b;")
        diag_sub_box.addWidget(self.auth_last_test_lbl)
        diag_sub_box.addStretch()

        self.view_auth_diag_btn = QPushButton(tr("auth_view_diagnostic_details"))
        self.view_auth_diag_btn.setObjectName("compactButton")
        self.view_auth_diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_auth_diag_btn.clicked.connect(self._on_view_auth_diagnostic_clicked)
        diag_sub_box.addWidget(self.view_auth_diag_btn)

        auth_box.addLayout(diag_sub_box)

        # Backward compatibility aliases
        self.cookies_combo = self.browser_combo
        self._test_auth_btn = self._test_browser_btn
        self.cookies_lbl = self.browser_lbl
        self.cookies_hint_lbl = self.browser_hint_lbl
        self.cookie_file_row = self.auth_file_panel

        layout.addLayout(auth_box)

        # Sync state from settings
        self._sync_auth_ui_from_settings()

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 5. DIAGNOSTIC REPORT SECTION
        # ---------------------------------------------------------------------
        self.diag_title = QLabel(tr("diagnostic_report_title"))
        self.diag_title.setObjectName("sectionHeader")
        layout.addWidget(self.diag_title)

        diag_box = QVBoxLayout()
        diag_box.setSpacing(6)
        diag_box.setContentsMargins(4, 0, 4, 0)

        self.diag_desc = QLabel(tr("diagnostic_report_desc"))
        self.diag_desc.setStyleSheet("font-size: 12px; color: #64748b;")
        self.diag_desc.setWordWrap(True)
        diag_box.addWidget(self.diag_desc)

        diag_btns_row = QHBoxLayout()
        diag_btns_row.setSpacing(10)

        self._copy_diag_btn = QPushButton(tr("copy_diagnostic_info"))
        self._copy_diag_btn.setObjectName("compactButton")
        self._copy_diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_diag_btn.clicked.connect(self._on_copy_diagnostic_clicked)
        diag_btns_row.addWidget(self._copy_diag_btn)

        self._open_logs_btn = QPushButton(tr("open_log_folder"))
        self._open_logs_btn.setObjectName("compactButton")
        self._open_logs_btn.setToolTip(tr("open_log_folder_tooltip"))
        self._open_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_logs_btn.clicked.connect(self._on_open_log_folder_clicked)
        diag_btns_row.addWidget(self._open_logs_btn)

        diag_btns_row.addStretch()
        diag_box.addLayout(diag_btns_row)

        self._diag_status_lbl = QLabel("")
        self._diag_status_lbl.setStyleSheet("font-size: 11px; color: #16a34a; font-weight: 500;")
        diag_box.addWidget(self._diag_status_lbl)

        layout.addLayout(diag_box)

        layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 6. DATA DIRECTORY SECTION
        # ---------------------------------------------------------------------
        self.data_title = QLabel(tr("settings_data_dir"))
        self.data_title.setObjectName("sectionHeader")
        layout.addWidget(self.data_title)

        data_box = QVBoxLayout()
        data_box.setSpacing(3)
        data_box.setContentsMargins(4, 0, 4, 0)

        self.data_desc = QLabel(tr("data_dir_desc"))
        self.data_desc.setStyleSheet("font-size: 12px;")
        data_box.addWidget(self.data_desc)

        data_row = QHBoxLayout()
        data_row.setSpacing(8)

        app_data_path = str(get_app_data_dir())
        data_path_lbl = QLabel(app_data_path)
        data_path_lbl.setStyleSheet("font-size: 11px; font-family: Consolas, monospace;")
        data_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data_path_lbl.setToolTip(app_data_path)
        data_row.addWidget(data_path_lbl, stretch=1)

        self.open_folder_btn = QPushButton(tr("open_data_folder"))
        self.open_folder_btn.setObjectName("compactButton")
        self.open_folder_btn.setToolTip(tr("open_data_folder_tooltip"))
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.clicked.connect(self._on_open_data_folder)
        data_row.addWidget(self.open_folder_btn)

        data_box.addLayout(data_row)
        layout.addLayout(data_box)

        scroll_area.setWidget(content_widget)
        root_layout.addWidget(scroll_area, stretch=1)

        root_layout.addWidget(self._create_divider())

        # ---------------------------------------------------------------------
        # 7. FOOTER SECTION
        # ---------------------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)
        footer_layout.setContentsMargins(0, 2, 0, 0)

        dev_col = QVBoxLayout()
        dev_col.setSpacing(1)

        copyright_lbl = QLabel("Channel Harvest © 2026")
        copyright_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        dev_col.addWidget(copyright_lbl)

        self.dev_lbl = QLabel(f"Developed by {self.DEVELOPER}")
        self.dev_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        dev_col.addWidget(self.dev_lbl)

        footer_layout.addLayout(dev_col)
        footer_layout.addStretch()

        self.close_btn = QPushButton(tr("close"))
        self.close_btn.setObjectName("primaryButton")
        self.close_btn.setMinimumHeight(32)
        self.close_btn.setMinimumWidth(80)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(self.close_btn)

        root_layout.addLayout(footer_layout)

        # Apply current language
        self.retranslate_ui()

    # -------------------------------------------------------------------------
    # Styling and Theme Listeners
    # -------------------------------------------------------------------------

    def _format_status_html(self, status: str, latest_ver: str = "") -> str:
        """Formats the status string with clean theme-aware colors."""
        low = status.lower()
        if "update available" in low:
            tag = f" (v{latest_ver})" if latest_ver else ""
            return f"<span style='color: #f59e0b; font-weight: 600;'>● {tr('status_update_available')}{tag}</span>"
        elif "up to date" in low:
            return f"<span style='color: #16a34a; font-weight: 600;'>● {tr('status_up_to_date')}</span>"
        elif "checking" in low:
            return f"<span style='color: #0284c7; font-weight: 500;'>● {tr('status_checking')}</span>"
        elif "not installed" in low:
            return f"<span style='color: #dc2626; font-weight: 600;'>● {tr('status_not_installed')}</span>"
        elif "not found" in low:
            return f"<span style='color: #dc2626; font-weight: 600;'>● {tr('status_not_found')}</span>"
        elif "error" in low:
            return f"<span style='color: #dc2626; font-weight: 500;'>● {tr('status_error')}</span>"
        return f"<span>{status}</span>"

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

    def _on_lang_combo_changed(self, index: int) -> None:
        """Handles user selecting a new language from the Appearance dropdown."""
        lang_pref = self.lang_combo.currentData()
        self.settings_manager.set("language", lang_pref)
        I18nManager.set_language(lang_pref)

    def _on_language_updated(self, lang_code: str) -> None:
        """Listener invoked when language changes dynamically."""
        self.retranslate_ui()

    def _on_auto_check_runtime_toggled(self, checked: bool) -> None:
        """Persists the automatic runtime update check preference."""
        self.settings_manager.set("auto_check_runtime_updates", checked)
        self.settings_manager.set("auto_check_ytdlp_updates", checked)

    def _format_status_badge(self, status: str) -> str:
        """Formats an authentication status code into a styled user-facing badge."""
        if status in ("NOT_CONFIGURED", "none"):
            return f"<span style='color: #64748b;'>{tr('status_not_configured')}</span>"
        elif status in (
            AuthStatusCode.YOUTUBE_SESSION_AUTHENTICATED,
            getattr(AuthStatusCode, "SUCCESS", "SUCCESS"),
        ):
            return f"<span style='color: #16a34a; font-weight: 600;'>✓ {tr('status_session_detected')}</span>"
        elif status in (
            AuthStatusCode.COOKIE_FILE_VALID,
            AuthStatusCode.BROWSER_COOKIE_EXTRACTION_SUCCESS,
        ):
            return f"<span style='color: #16a34a; font-weight: 500;'>{tr('status_cookie_file_detected')}</span>"
        elif status == AuthStatusCode.COOKIE_DECRYPTION_FAILED:
            return f"<span style='color: #d97706; font-weight: 600;'>⚠️ {tr('status_decryption_failed')}</span>"
        elif status == AuthStatusCode.COOKIE_FILE_INVALID:
            return f"<span style='color: #dc2626; font-weight: 500;'>❌ {tr('status_invalid_cookie_file')}</span>"
        else:
            return f"<span style='color: #64748b;'>{status}</span>"

    def _sync_auth_ui_from_settings(self) -> None:
        """Synchronizes UI controls with persistent authentication settings."""
        auth_method = self.settings_manager.get("auth_method", "none")
        if auth_method == "none":
            b_cookie = self.settings_manager.get("browser_cookies", "none")
            if b_cookie == "custom_file":
                auth_method = "custom_file"
            elif b_cookie not in ("none", ""):
                auth_method = "browser"

        browser_choice = self.settings_manager.get("browser_cookies", "chrome")
        if browser_choice in ("none", "custom_file"):
            browser_choice = "chrome"

        profile_choice = self.settings_manager.get("browser_profile", "Default")
        custom_file = self.settings_manager.get("custom_cookie_file", "")
        last_status = self.settings_manager.get("last_auth_status", "NOT_CONFIGURED")

        # Update Radio Group
        self.auth_method_group.blockSignals(True)
        if auth_method == "none":
            self.auth_none_rb.setChecked(True)
        elif auth_method == "browser":
            self.auth_browser_rb.setChecked(True)
        elif auth_method == "custom_file":
            self.auth_file_rb.setChecked(True)
        self.auth_method_group.blockSignals(False)

        # Show/Hide panels
        self.auth_none_panel.setVisible(auth_method == "none")
        self.auth_browser_panel.setVisible(auth_method == "browser")
        self.auth_file_panel.setVisible(auth_method == "custom_file")

        # Browser dropdown
        self.browser_combo.blockSignals(True)
        b_idx = self.browser_combo.findData(browser_choice)
        if b_idx >= 0:
            self.browser_combo.setCurrentIndex(b_idx)
        else:
            self.browser_combo.setCurrentIndex(0)
        self.browser_combo.blockSignals(False)

        # Profiles dropdown
        cur_browser = self.browser_combo.currentData() or "chrome"
        self._populate_profiles_for_browser(cur_browser, selected_profile=profile_choice)

        # Custom cookie file
        self.cookie_file_edit.blockSignals(True)
        self.cookie_file_edit.setText(custom_file)
        self.cookie_file_edit.blockSignals(False)
        self._update_cookie_file_validation(custom_file)

        # Diagnostics & Last Test
        self.auth_last_test_lbl.setText(f"<b>{tr('auth_last_test')}</b> {self._format_status_badge(last_status)}")

    def _populate_profiles_for_browser(self, browser_name: str, selected_profile: Optional[str] = None) -> None:
        """Populates the profile combo box for the chosen browser."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = get_browser_profiles(browser_name)
        if not profiles:
            profiles = ["Default"]
        for p in profiles:
            self.profile_combo.addItem(p, p)

        target = selected_profile or self.settings_manager.get("browser_profile", "Default")
        idx = self.profile_combo.findText(target)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        else:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

    def _on_auth_method_button_clicked(self, id_: int) -> None:
        """Handles switching between None (0), Browser Cookies (1), and Custom Cookie File (2)."""
        method_map = {0: "none", 1: "browser", 2: "custom_file"}
        method = method_map.get(id_, "none")
        self.settings_manager.set("auth_method", method)

        if method == "none":
            self.settings_manager.set("browser_cookies", "none")
        elif method == "browser":
            b_choice = self.browser_combo.currentData() or "chrome"
            self.settings_manager.set("browser_cookies", b_choice)
            p_choice = self.profile_combo.currentText() or "Default"
            self.settings_manager.set("browser_profile", p_choice)
        elif method == "custom_file":
            self.settings_manager.set("browser_cookies", "custom_file")

        self.auth_none_panel.setVisible(method == "none")
        self.auth_browser_panel.setVisible(method == "browser")
        self.auth_file_panel.setVisible(method == "custom_file")

        if method == "browser":
            cur_b = self.browser_combo.currentData() or "chrome"
            self._populate_profiles_for_browser(cur_b)
        elif method == "custom_file":
            self._update_cookie_file_validation(self.cookie_file_edit.text().strip())

    def _on_browser_changed(self, index: int) -> None:
        """Persists the selected browser cookies authentication setting."""
        browser_choice = self.browser_combo.currentData() or "chrome"
        if self.settings_manager.get("auth_method") == "browser":
            self.settings_manager.set("browser_cookies", browser_choice)
        self._populate_profiles_for_browser(browser_choice)
        self.browser_abe_widget.setVisible(False)
        self.browser_status_lbl.setText(f"<b>{tr('auth_status_label')}</b> {tr('status_not_tested')}")

    def _on_profile_changed(self, index: int) -> None:
        """Persists the selected browser profile."""
        profile_choice = self.profile_combo.currentText() or "Default"
        self.settings_manager.set("browser_profile", profile_choice)
        self.browser_status_lbl.setText(f"<b>{tr('auth_status_label')}</b> {tr('status_not_tested')}")

    def _update_cookie_file_validation(self, path_str: str) -> None:
        """Performs immediate synchronous non-destructive validation of cookie file."""
        if not path_str:
            self.cookie_file_status_lbl.setText(
                f"<b>{tr('auth_status_label')}</b> <span style='color: #64748b;'>{tr('status_not_configured')}</span>"
            )
            return

        validation = validate_cookie_file(path_str)
        if not validation.get("is_valid", False):
            msg = validation.get("message", tr("status_invalid_cookie_file"))
            self.cookie_file_status_lbl.setText(
                f"<b>{tr('auth_status_label')}</b> <span style='color: #dc2626;'>{tr('status_invalid_cookie_file')}</span> "
                f"<span style='font-size: 11px; color: #94a3b8;'>({msg})</span>"
            )
        else:
            cookie_cnt = validation.get("cookie_count", 0)
            yt_cnt = validation.get("youtube_cookie_count", 0)
            has_session = validation.get("has_session", False)
            if has_session:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_cookie_file_detected')}</span> "
                    f"<span style='font-size: 11px; color: #16a34a;'>{tr('cookie_yt_session_count_fmt', count=yt_cnt)}</span>"
                )
            elif yt_cnt > 0:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_cookie_file_detected')}</span> "
                    f"<span style='font-size: 11px; color: #64748b;'>{tr('cookie_yt_count_no_session_fmt', count=yt_cnt)}</span>"
                )
            else:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #d97706;'>{tr('status_cookie_file_detected')}</span> "
                    f"<span style='font-size: 11px; color: #d97706;'>{tr('cookie_count_no_yt_fmt', count=cookie_cnt)}</span>"
                )

    def _on_cookie_file_changed(self, text: str) -> None:
        """Persists the custom cookie file path and updates validation."""
        path = text.strip()
        self.settings_manager.set("custom_cookie_file", path)
        self._update_cookie_file_validation(path)

    def _on_browse_cookie_file_clicked(self) -> None:
        """Opens a file dialog to select an exported Netscape cookies.txt file."""
        current_dir = ""
        if hasattr(self, "cookie_file_edit"):
            val = self.cookie_file_edit.text().strip()
            if val and Path(val).parent.is_dir():
                current_dir = str(Path(val).parent)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("auth_select_cookie_file"),
            current_dir,
            tr("cookie_file_filter"),
        )
        if file_path:
            norm_path = str(Path(file_path).resolve())
            if hasattr(self, "cookie_file_edit"):
                self.cookie_file_edit.setText(norm_path)
            self.settings_manager.set("custom_cookie_file", norm_path)
            self._update_cookie_file_validation(norm_path)

    def _on_clear_cookie_file_clicked(self) -> None:
        """Clears the cookie file path setting without deleting the file on disk."""
        if hasattr(self, "cookie_file_edit"):
            self.cookie_file_edit.setText("")
        self.settings_manager.set("custom_cookie_file", "")
        self.cookie_file_status_lbl.setText(
            f"<b>{tr('auth_status_label')}</b> <span style='color: #64748b;'>{tr('auth_cookie_file_cleared')}</span>"
        )

    def _on_switch_to_custom_file_clicked(self) -> None:
        """Switches the active auth mode to Custom Cookie File."""
        self.auth_file_rb.setChecked(True)
        self._on_auth_method_button_clicked(2)
        if hasattr(self, "cookie_file_edit") and not self.cookie_file_edit.text().strip():
            self._on_browse_cookie_file_clicked()

    def _on_cookies_combo_changed(self, index: int) -> None:
        """Backward compatibility handler for cookies combo."""
        self._on_browser_changed(index)

    # -------------------------------------------------------------------------
    # Runtime Manager Actions
    # -------------------------------------------------------------------------

    def _on_check_runtime_clicked(self) -> None:
        """Initiates background checking of all 4 runtime components."""
        self._check_runtime_btn.setEnabled(False)
        self._check_runtime_btn.setText(tr("status_checking"))
        self._update_runtime_btn.setVisible(False)

        for comp_key, widgets in self._comp_widgets.items():
            widgets["status"].setText(self._format_status_html("Checking..."))

        self._check_worker = CheckRuntimeWorker(self)
        self._check_worker.check_completed.connect(self._on_runtime_check_completed)
        self._check_worker.start()

    def _on_runtime_check_completed(self, results: Dict[str, ComponentInfo]) -> None:
        """Handles completion of the coordinated runtime update check."""
        self._check_runtime_btn.setEnabled(True)
        self._check_runtime_btn.setText(tr("check_again"))
        self._runtime_components = results
        self.settings_manager.set("last_runtime_update_check", time.time())

        has_any_update = False
        outdated_names = []

        for comp_key, info in results.items():
            widgets = self._comp_widgets.get(comp_key)
            if not widgets:
                continue

            ver_display = f"v{info.current_version}" if not info.current_version.startswith("v") else info.current_version
            widgets["version"].setText(ver_display)
            widgets["status"].setText(self._format_status_html(info.status, latest_ver=info.latest_version))

            if info.has_update:
                has_any_update = True
                outdated_names.append(info.display_name)

        if has_any_update:
            self._update_runtime_btn.setVisible(True)
            self._update_runtime_btn.setText(tr("update_available_components"))
        else:
            self._update_runtime_btn.setVisible(False)

    def _on_update_components_clicked(self) -> None:
        """Safely coordinates updating all components that have updates available."""
        # 1. Guard against active downloads
        is_busy = False
        parent_win = self.parent()
        if parent_win and hasattr(parent_win, "is_download_active"):
            is_busy = parent_win.is_download_active()

        if is_busy:
            QMessageBox.information(
                self,
                tr("runtime_busy_title"),
                tr("runtime_busy_msg"),
            )
            return

        # 2. Identify outdated components
        outdated_keys = [k for k, info in self._runtime_components.items() if info.has_update]
        if not outdated_keys:
            return

        names_str = "\n".join(f"• {self._runtime_components[k].display_name}: v{self._runtime_components[k].current_version} → v{self._runtime_components[k].latest_version}" for k in outdated_keys)

        reply = QMessageBox.question(
            self,
            tr("runtime_update_confirm_title"),
            tr("runtime_update_confirm_msg", components=names_str),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 3. Launch background updater worker
        self._update_runtime_btn.setEnabled(False)
        self._update_runtime_btn.setText(tr("updating"))
        self._check_runtime_btn.setEnabled(False)

        for k in outdated_keys:
            if k in self._comp_widgets:
                self._comp_widgets[k]["status"].setText(f"<span style='color: #0284c7; font-weight: 500;'>{tr('updating')}</span>")

        self._install_worker = InstallRuntimeWorker(outdated_keys, is_download_active=False, parent=self)
        self._install_worker.component_finished.connect(self._on_component_update_finished)
        self._install_worker.all_finished.connect(self._on_all_runtime_updates_finished)
        self._install_worker.start()

    def _on_component_update_finished(self, comp_key: str, success: bool, new_ver: str, error_msg: str) -> None:
        """Handles completion of an individual component update."""
        widgets = self._comp_widgets.get(comp_key)
        if not widgets:
            return

        if success:
            ver_display = f"v{new_ver}" if not new_ver.startswith("v") else new_ver
            widgets["version"].setText(ver_display)
            widgets["status"].setText(self._format_status_html("Up to date"))
            if comp_key in self._runtime_components:
                self._runtime_components[comp_key].current_version = new_ver
                self._runtime_components[comp_key].has_update = False
                self._runtime_components[comp_key].status = "Up to date"
        else:
            widgets["status"].setText(f"<span style='color: #dc2626; font-weight: 500;'>● {tr('status_error')}</span>")

    def _on_all_runtime_updates_finished(self, success_count: int, fail_count: int) -> None:
        """Handles completion of the batch update run."""
        self._update_runtime_btn.setEnabled(True)
        self._update_runtime_btn.setText(tr("update_available_components"))
        self._check_runtime_btn.setEnabled(True)

        remaining_updates = any(info.has_update for info in self._runtime_components.values())
        self._update_runtime_btn.setVisible(remaining_updates)

        if success_count > 0:
            reply = QMessageBox.question(
                self,
                tr("runtime_update_complete_title"),
                tr("runtime_update_complete_msg", success=success_count, failed=fail_count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._restart_application()

    def _restart_application(self) -> None:
        """Safely restarts Channel Harvest to load freshly replaced runtime files."""
        try:
            import subprocess
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable])
            else:
                subprocess.Popen([sys.executable] + sys.argv)
            QApplication.quit()
        except Exception as e:
            QMessageBox.warning(self, tr("error"), tr("could_not_restart_fmt", error=e))

    # -------------------------------------------------------------------------
    # Diagnostic Report Actions
    # -------------------------------------------------------------------------

    def _on_copy_diagnostic_clicked(self) -> None:
        """Compiles clean diagnostic text and copies directly to Windows clipboard."""
        # Map statuses
        statuses = {}
        for k, info in self._runtime_components.items():
            name = info.display_name.lower()
            statuses[name] = info.status
            statuses[k] = info.status

        report = DiagnosticReporter.generate_report(
            settings_manager=self.settings_manager,
            runtime_statuses=statuses,
        )

        QGuiApplication.clipboard().setText(report)
        self._diag_status_lbl.setText(f"✓ {tr('copied_diagnostic_info')}")
        QTimer.singleShot(2500, lambda: self._diag_status_lbl.setText("") if hasattr(self, "_diag_status_lbl") else None)

    def _on_open_log_folder_clicked(self) -> None:
        """Opens the %APPDATA%/ChannelHarvest/logs directory in Windows File Explorer."""
        logs_dir = get_logs_dir()
        if logs_dir.exists():
            try:
                os.startfile(str(logs_dir))
            except Exception as e:
                QMessageBox.warning(self, tr("error"), tr("could_not_open_logs_fmt", error=e))

    # -------------------------------------------------------------------------
    # YouTube Auth & Data Folder
    # -------------------------------------------------------------------------

    def _on_test_browser_auth_clicked(self) -> None:
        """Safely verifies browser cookie access for YouTube."""
        browser_choice = self.browser_combo.currentData() or "chrome"
        profile_choice = self.profile_combo.currentText() or "Default"

        self._test_browser_btn.setEnabled(False)
        self._test_browser_btn.setText(tr("status_testing"))

        self._auth_worker = AuthTestWorker(
            browser_choice,
            profile=profile_choice,
        )
        self._auth_worker.finished.connect(self._on_auth_test_finished)
        self._auth_worker.start()

    def _on_test_file_auth_clicked(self) -> None:
        """Safely verifies custom cookie file access for YouTube."""
        custom_path = self.cookie_file_edit.text().strip()
        if not custom_path:
            QMessageBox.information(
                self,
                tr("auth_test_title"),
                tr("auth_cookie_file_placeholder"),
            )
            return

        self._test_file_btn.setEnabled(False)
        self._test_file_btn.setText(tr("status_testing"))

        self._auth_worker = AuthTestWorker(
            "custom_file",
            custom_cookie_path=custom_path,
        )
        self._auth_worker.finished.connect(self._on_auth_test_finished)
        self._auth_worker.start()

    def _on_test_auth_clicked(self) -> None:
        """Backward compatible delegate for testing auth."""
        auth_method = self.settings_manager.get("auth_method", "none")
        if auth_method == "custom_file":
            self._on_test_file_auth_clicked()
        elif auth_method == "browser":
            self._on_test_browser_auth_clicked()
        else:
            QMessageBox.information(
                self,
                tr("auth_test_title"),
                tr("auth_disabled_msg"),
            )

    def _on_auth_test_finished(self, result: Any) -> None:
        """Handles completion of the background authentication verification."""
        if hasattr(self, "_test_browser_btn"):
            self._test_browser_btn.setEnabled(True)
            self._test_browser_btn.setText(tr("auth_test_btn"))
        if hasattr(self, "_test_file_btn"):
            self._test_file_btn.setEnabled(True)
            self._test_file_btn.setText(tr("auth_test_btn"))

        self._last_auth_result = result
        code_name = result.status_code.name if hasattr(result.status_code, "name") else str(result.status_code)
        self.settings_manager.set("last_auth_status", code_name)

        # Update last test label in diagnostics subsection
        if hasattr(self, "auth_last_test_lbl"):
            self.auth_last_test_lbl.setText(f"<b>{tr('auth_last_test')}</b> {self._format_status_badge(code_name)}")

        # Update panel-specific status labels
        if result.auth_method == "Custom Cookie File":
            if result.success or result.has_session:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_session_detected')}</span>"
                )
            elif result.status_code == AuthStatusCode.COOKIE_FILE_VALID:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_cookie_file_detected')}</span>"
                )
            elif result.status_code == AuthStatusCode.COOKIE_FILE_INVALID:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #dc2626;'>{tr('status_invalid_cookie_file')}</span>"
                )
            else:
                self.cookie_file_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #dc2626;'>{code_name}</span>"
                )
        else:
            # Browser Cookies
            if result.status_code == AuthStatusCode.COOKIE_DECRYPTION_FAILED:
                self.browser_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #d97706;'>{tr('status_decryption_failed')}</span>"
                )
                b_name = result.browser_name.title() if result.browser_name else "Browser"
                reason_text = tr("auth_abe_reason", browser=b_name)
                self.browser_abe_lbl.setText(f"⚠️ {reason_text}")
                self.browser_abe_widget.setVisible(True)
            elif result.success or result.has_session:
                self.browser_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_session_detected')}</span>"
                )
                self.browser_abe_widget.setVisible(False)
            elif result.status_code == AuthStatusCode.BROWSER_COOKIE_EXTRACTION_SUCCESS:
                self.browser_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #16a34a;'>{tr('status_cookie_file_detected')}</span>"
                )
                self.browser_abe_widget.setVisible(False)
            else:
                self.browser_status_lbl.setText(
                    f"<b>{tr('auth_status_label')}</b> <span style='color: #dc2626;'>{code_name}</span>"
                )
                self.browser_abe_widget.setVisible(False)

        dlg = AuthResultDialog(result, parent=self)
        dlg.exec()

    def _on_view_auth_diagnostic_clicked(self) -> None:
        """Displays the diagnostic details dialog for the last test or current status."""
        if self._last_auth_result is not None:
            dlg = AuthResultDialog(self._last_auth_result, parent=self)
            dlg.exec()
        else:
            auth_method = self.settings_manager.get("auth_method", "none")
            last_status = self.settings_manager.get("last_auth_status", "NOT_CONFIGURED")
            b_choice = self.settings_manager.get("browser_cookies", "chrome")
            p_choice = self.settings_manager.get("browser_profile", "Default")
            c_file = self.settings_manager.get("custom_cookie_file", "")

            from downloader.auth_checker import AuthStage
            if auth_method == "none":
                res = AuthTestResult(
                    success=False,
                    stage=AuthStage.BROWSER_DETECTION,
                    status_code=AuthStatusCode.NOT_CONFIGURED,
                    browser_name="None",
                    auth_method="None",
                    reason=tr("auth_none_hint"),
                    suggested_action=tr("auth_optional_hint"),
                )
            elif auth_method == "custom_file":
                v = validate_cookie_file(c_file)
                res = AuthTestResult(
                    success=v.get("has_session", False),
                    stage=AuthStage.COOKIE_EXTRACTION,
                    status_code=v.get("status_code", AuthStatusCode.COOKIE_FILE_INVALID),
                    browser_name="Custom Cookie File",
                    auth_method="Custom Cookie File",
                    cookie_count=v.get("cookie_count", 0),
                    youtube_cookie_count=v.get("youtube_cookie_count", 0),
                    has_session=v.get("has_session", False),
                    reason=v.get("message", ""),
                    suggested_action=tr("auth_click_test_hint"),
                )
            else:
                res = AuthTestResult(
                    success=False,
                    stage=AuthStage.BROWSER_DETECTION,
                    status_code=last_status,
                    browser_name=b_choice,
                    auth_method="Browser Cookies",
                    profile_name=p_choice,
                    reason=tr("auth_no_test_yet"),
                    suggested_action=tr("auth_click_test_verify_hint"),
                )
            dlg = AuthResultDialog(res, parent=self)
            dlg.exec()

    def _on_open_data_folder(self) -> None:
        """Opens %APPDATA%/ChannelHarvest in File Explorer."""
        path = get_app_data_dir()
        if path.exists():
            try:
                os.startfile(str(path))
            except Exception as e:
                QMessageBox.warning(self, tr("error"), tr("could_not_open_dir_fmt", error=e))

    # -------------------------------------------------------------------------
    # Dynamic Retranslation
    # -------------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Dynamically retranslates all text elements in the settings dialog."""
        self.setWindowTitle(tr("settings_window_title"))
        if hasattr(self, "subtitle_lbl"):
            self.subtitle_lbl.setText(tr("app_subtitle"))
        if hasattr(self, "appear_title"):
            self.appear_title.setText(tr("settings_appearance"))
        if hasattr(self, "theme_lbl"):
            self.theme_lbl.setText(tr("settings_theme"))
        if hasattr(self, "lang_lbl"):
            self.lang_lbl.setText(tr("settings_language"))
        if hasattr(self, "theme_combo"):
            for i in range(self.theme_combo.count()):
                val = self.theme_combo.itemData(i)
                self.theme_combo.setItemText(i, I18nManager.get_theme_label(val))
        if hasattr(self, "lang_combo"):
            cur_lang = I18nManager.get_language()
            idx = self.lang_combo.findData(cur_lang)
            if idx >= 0 and self.lang_combo.currentIndex() != idx:
                self.lang_combo.blockSignals(True)
                self.lang_combo.setCurrentIndex(idx)
                self.lang_combo.blockSignals(False)

        # Runtime Manager translations
        if hasattr(self, "runtime_title"):
            self.runtime_title.setText(tr("runtime_manager_title"))
        if hasattr(self, "th_comp"):
            self.th_comp.setText(tr("th_component"))
        if hasattr(self, "th_ver"):
            self.th_ver.setText(tr("th_current_version"))
        if hasattr(self, "th_stat"):
            self.th_stat.setText(tr("th_status"))

        if hasattr(self, "_comp_widgets"):
            for comp_key, widgets in self._comp_widgets.items():
                info = self._runtime_components.get(comp_key)
                if info:
                    widgets["status"].setText(self._format_status_html(info.status, latest_ver=info.latest_version))

        if hasattr(self, "_check_runtime_btn") and self._check_runtime_btn.isEnabled():
            has_checked = self.settings_manager.get("last_runtime_update_check", 0.0) > 0
            self._check_runtime_btn.setText(tr("check_again") if has_checked else tr("check_runtime_updates"))
        if hasattr(self, "_update_runtime_btn"):
            self._update_runtime_btn.setText(tr("update_available_components"))
        if hasattr(self, "auto_check_runtime_cb"):
            self.auto_check_runtime_cb.setText(tr("auto_check_runtime"))

        # Auth Section Retranslation
        if hasattr(self, "auth_title"):
            self.auth_title.setText(tr("settings_auth"))
        if hasattr(self, "auth_method_lbl"):
            self.auth_method_lbl.setText(tr("auth_method_label"))
        if hasattr(self, "auth_none_rb"):
            self.auth_none_rb.setText(tr("auth_method_none"))
        if hasattr(self, "auth_browser_rb"):
            self.auth_browser_rb.setText(tr("auth_method_browser"))
        if hasattr(self, "auth_file_rb"):
            self.auth_file_rb.setText(tr("auth_method_custom_file_radio"))

        # None panel
        if hasattr(self, "none_status_lbl"):
            self.none_status_lbl.setText(f"<b>{tr('auth_status_label')}</b> {tr('status_not_configured')}")
        if hasattr(self, "none_hint_lbl"):
            self.none_hint_lbl.setText(tr("auth_none_hint"))

        # Browser panel
        if hasattr(self, "browser_lbl"):
            self.browser_lbl.setText(tr("auth_browser_label"))
        if hasattr(self, "profile_lbl"):
            self.profile_lbl.setText(tr("auth_profile_label"))
        if hasattr(self, "browser_combo"):
            for i in range(self.browser_combo.count()):
                data_val = self.browser_combo.itemData(i)
                if data_val == "chrome":
                    self.browser_combo.setItemText(i, tr("cookies_chrome"))
                elif data_val == "edge":
                    self.browser_combo.setItemText(i, tr("cookies_edge"))
                elif data_val == "firefox":
                    self.browser_combo.setItemText(i, tr("cookies_firefox"))
                elif data_val == "brave":
                    self.browser_combo.setItemText(i, tr("cookies_brave"))
                elif data_val == "opera":
                    self.browser_combo.setItemText(i, tr("cookies_opera"))
                elif data_val == "vivaldi":
                    self.browser_combo.setItemText(i, tr("cookies_vivaldi"))
        if hasattr(self, "_test_browser_btn") and self._test_browser_btn.isEnabled():
            self._test_browser_btn.setText(tr("auth_test_btn"))
            self._test_browser_btn.setToolTip(tr("auth_test_tooltip"))
        if hasattr(self, "browser_switch_btn"):
            self.browser_switch_btn.setText(tr("auth_switch_to_cookie_file"))
        if hasattr(self, "browser_hint_lbl"):
            self.browser_hint_lbl.setText(tr("settings_cookies_hint"))

        # Custom Cookie File panel
        if hasattr(self, "cookie_file_lbl"):
            self.cookie_file_lbl.setText(tr("auth_cookie_file_label"))
        if hasattr(self, "cookie_file_edit"):
            self.cookie_file_edit.setPlaceholderText(tr("auth_cookie_file_placeholder"))
            if hasattr(self, "_update_cookie_file_validation"):
                self._update_cookie_file_validation(self.cookie_file_edit.text().strip())
        if hasattr(self, "cookie_browse_btn"):
            self.cookie_browse_btn.setText(tr("browse"))
        if hasattr(self, "_test_file_btn") and self._test_file_btn.isEnabled():
            self._test_file_btn.setText(tr("auth_test_btn"))
        if hasattr(self, "_clear_file_btn"):
            self._clear_file_btn.setText(tr("auth_clear_cookie_file"))
        if hasattr(self, "cookie_privacy_lbl"):
            self.cookie_privacy_lbl.setText(f"🔒 <i>{tr('auth_cookie_file_privacy_notice')}</i>")

        # Diagnostics subsection
        if hasattr(self, "view_auth_diag_btn"):
            self.view_auth_diag_btn.setText(tr("auth_view_diagnostic_details"))
        if hasattr(self, "auth_last_test_lbl"):
            last_s = self.settings_manager.get("last_auth_status", "NOT_CONFIGURED")
            self.auth_last_test_lbl.setText(f"<b>{tr('auth_last_test')}</b> {self._format_status_badge(last_s)}")

        # Diagnostics
        if hasattr(self, "diag_title"):
            self.diag_title.setText(tr("diagnostic_report_title"))
        if hasattr(self, "diag_desc"):
            self.diag_desc.setText(tr("diagnostic_report_desc"))
        if hasattr(self, "_copy_diag_btn"):
            self._copy_diag_btn.setText(tr("copy_diagnostic_info"))
        if hasattr(self, "_open_logs_btn"):
            self._open_logs_btn.setText(tr("open_log_folder"))
            self._open_logs_btn.setToolTip(tr("open_log_folder_tooltip"))

        # Data directory & footer
        if hasattr(self, "data_title"):
            self.data_title.setText(tr("settings_data_dir"))
        if hasattr(self, "data_desc"):
            self.data_desc.setText(tr("data_dir_desc"))
        if hasattr(self, "open_folder_btn"):
            self.open_folder_btn.setText(tr("open_data_folder"))
            self.open_folder_btn.setToolTip(tr("open_data_folder_tooltip"))
        if hasattr(self, "dev_lbl"):
            self.dev_lbl.setText(f"Developed by {self.DEVELOPER}")
        if hasattr(self, "close_btn"):
            self.close_btn.setText(tr("close"))
