"""
styles.py
Centralized Channel Harvest Design System & Theme Engine.

Supports:
- Light Mode (modern crisp Windows aesthetic)
- Dark Mode (intentional dark navy/charcoal, slate surfaces, high readability)
- System Mode (auto-detects Windows light/dark system setting)
- Dynamic theme switching across all open windows, dialogs, and popups
"""

import sys
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

_arrow_down_light_path = (Path(__file__).resolve().parent / "arrow_down.png").as_posix()
_arrow_down_dark_path = (Path(__file__).resolve().parent / "arrow_down_dark.png").as_posix()
_checkmark_path = (Path(__file__).resolve().parent / "checkmark.png").as_posix()


class ThemeMode:
    SYSTEM = "System"
    LIGHT = "Light"
    DARK = "Dark"


def detect_windows_theme() -> str:
    """
    Detects whether Windows is currently using Light or Dark mode.
    First inspects Windows registry (AppsUseLightTheme), then falls back to Qt styleHints.
    """
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            if val == 0:
                return ThemeMode.DARK
            return ThemeMode.LIGHT
        except Exception:
            pass

    # Qt 6.5+ ColorScheme fallback
    try:
        hints = QGuiApplication.styleHints()
        if hints and hasattr(hints, "colorScheme"):
            if hints.colorScheme() == Qt.ColorScheme.Dark:
                return ThemeMode.DARK
    except Exception:
        pass

    return ThemeMode.LIGHT


# =============================================================================
# LIGHT THEME DEFINITIONS
# =============================================================================

_LIGHT_BASE = """
/* Global Light Application Style */
QWidget {
    font-family: __FONT_FAMILY__;
    font-size: 13px;
    color: #0f172a;
    background-color: #f8fafc;
}

/* Window & Central Panels */
QMainWindow {
    background-color: #f1f5f9;
}

QDialog {
    background-color: #ffffff;
    color: #0f172a;
}

QLabel {
    background-color: transparent;
}

/* Application Header Titles */
QLabel#appTitleLabel,
QLabel#summaryTitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
    background-color: transparent;
}

/* Summary Dialog Elements */
QLabel#summaryTotalVal {
    font-weight: 700;
    color: #1e293b;
}

QLabel#summaryCompletedVal {
    font-weight: 700;
    color: #16a34a;
}

QLabel#summarySkippedVal {
    font-weight: 700;
    color: #64748b;
}

QLabel#summaryFailedVal {
    font-weight: 700;
    color: #dc2626;
}

QLabel#summaryFolderInfo {
    color: #475569;
    font-size: 12px;
    padding: 4px;
}

/* Error Details Dialog Elements */
QLabel#errorDialogTitle {
    font-size: 18px;
    font-weight: 700;
    color: #dc2626;
    background-color: transparent;
}

QLabel#errorVideoInfoLabel {
    font-size: 13px;
    color: #1e293b;
}

QLabel#errorReasonLabel {
    font-size: 13px;
    color: #0f172a;
}

QLabel#errorActionLabel {
    font-size: 13px;
    color: #334155;
}

QLabel#errorTechMetaLabel {
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
}

QTextEdit#errorTechTextEdit {
    background-color: #f1f5f9;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 11px;
    padding: 6px;
}

QLabel#appSubtitleLabel {
    font-size: 12px;
    font-weight: 400;
    color: #64748b;
    background-color: transparent;
}

/* Section Group Boxes / Cards */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    margin-top: 20px;
    padding: 12px 14px 10px 14px;
    font-weight: 700;
    font-size: 14px;
    color: #0f172a;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 2px 10px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.5px;
}

/* Coordinated Blue Tonal Progression - Light Theme */
QGroupBox#urlGroupBox {
    border: 1px solid #cbd5e1;
    border-left: 4px solid #3b82f6;
}
QGroupBox#urlGroupBox::title {
    color: #1e40af;
    background-color: #f1f5f9;
}

QGroupBox#videosGroupBox {
    border: 1px solid #93c5fd;
    border-left: 4px solid #0066cc;
}
QGroupBox#videosGroupBox::title {
    color: #0052a3;
    background-color: #eff6ff;
}

QGroupBox#downloadGroupBox {
    border: 1px solid #cbd5e1;
    border-left: 4px solid #2563eb;
}
QGroupBox#downloadGroupBox::title {
    color: #1d4ed8;
    background-color: #f0f7ff;
}

QGroupBox#progressGroupBox {
    border: 1px solid #bae6fd;
    border-left: 4px solid #0284c7;
}
QGroupBox#progressGroupBox::title {
    color: #0369a1;
    background-color: #f0f9ff;
}

QGroupBox#logGroupBox {
    border: 1px solid #e2e8f0;
    border-left: 4px solid #64748b;
}
QGroupBox#logGroupBox::title {
    color: #475569;
    background-color: #f8fafc;
}

/* Sub-Section Cards inside DOWNLOAD OPTION */
QFrame#subSectionCard {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
}

QLabel#subSectionTitle {
    color: #1e3a8a;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    background: transparent;
}

QLabel#formLabel {
    font-size: 11px;
    font-weight: 600;
    color: #475569;
    background: transparent;
}

QLabel#subGroupTitle {
    font-size: 10px;
    font-weight: 700;
    color: #64748b;
    letter-spacing: 0.5px;
    background: transparent;
    padding-top: 4px;
}

/* Empty State Widget in Available Videos */
QWidget#emptyStateWidget {
    background-color: #ffffff;
    border: 1px dashed #cbd5e1;
    border-radius: 6px;
}

QLabel#emptyStateTitle {
    font-size: 14px;
    font-weight: 600;
    color: #475569;
    background: transparent;
}

QLabel#emptyStateSubtitle {
    font-size: 12px;
    font-weight: 400;
    color: #94a3b8;
    background: transparent;
}

/* Section Header Labels */
QLabel#sectionHeader {
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    background: transparent;
}

/* Text Input Fields */
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: #0f172a;
    selection-background-color: #0066cc;
    selection-color: #ffffff;
    min-height: 20px;
}

QLineEdit:hover {
    border-color: #94a3b8;
}

QLineEdit:focus {
    border: 2px solid #0066cc;
    background-color: #ffffff;
}

QLineEdit:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}

/* Search Box */
QLineEdit#searchBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    color: #0f172a;
    min-width: 180px;
    max-width: 260px;
}

QLineEdit#searchBox:focus {
    border: 2px solid #0066cc;
}

/* Combo Boxes */
QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: #0f172a;
    min-height: 22px;
}

QComboBox:hover {
    border-color: #94a3b8;
}

QComboBox:focus {
    border: 2px solid #0066cc;
}

QComboBox:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #e2e8f0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #f8fafc;
}

QComboBox::down-arrow {
    image: url("__ARROW_DOWN_PATH__");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #0f172a;
    selection-background-color: #0066cc;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

QComboBox QAbstractItemView::item:disabled {
    color: #94a3b8;
    background-color: transparent;
}

/* Push Buttons (Default Base) */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    font-size: 13px;
    color: #1e293b;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}

/* Primary Buttons */
QPushButton#primaryButton, QPushButton#scanButton {
    background-color: #0066cc;
    border: 1px solid #005bb5;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 18px;
}

QPushButton#primaryButton:hover, QPushButton#scanButton:hover {
    background-color: #005bb5;
    border-color: #004c99;
}

QPushButton#primaryButton:pressed, QPushButton#scanButton:pressed {
    background-color: #004c99;
}

QPushButton#primaryButton:disabled, QPushButton#scanButton:disabled {
    background-color: #93c5fd;
    border-color: #93c5fd;
    color: #ffffff;
}

/* Main Start Download Button (Primary Blue) */
QPushButton#downloadButton {
    background-color: #0066cc;
    border: 1px solid #0052a3;
    border-radius: 6px;
    color: #ffffff;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 14px;
}

QPushButton#downloadButton:hover {
    background-color: #0052a3;
    border-color: #003d7a;
}

QPushButton#downloadButton:pressed {
    background-color: #003d7a;
}

QPushButton#downloadButton:disabled {
    background-color: #bfdbfe;
    border-color: #bfdbfe;
    color: #ffffff;
}

/* Pause Button (Warm Amber Warning Tone) */
QPushButton#pauseButton {
    background-color: #fffbeb;
    border: 1px solid #fcd34d;
    border-radius: 6px;
    color: #92400e;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#pauseButton:hover {
    background-color: #fef3c7;
    border-color: #f59e0b;
    color: #78350f;
}

QPushButton#pauseButton:pressed {
    background-color: #fde68a;
    border-color: #d97706;
}

QPushButton#pauseButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Resume Button (Green Success Tone) */
QPushButton#resumeButton {
    background-color: #f0fdf4;
    border: 1px solid #86efac;
    border-radius: 6px;
    color: #166534;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#resumeButton:hover {
    background-color: #dcfce7;
    border-color: #4ade80;
    color: #14532d;
}

QPushButton#resumeButton:pressed {
    background-color: #bbf7d0;
    border-color: #22c55e;
}

QPushButton#resumeButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Cancel Button (Destructive Red Tone) */
QPushButton#cancelButton {
    background-color: #fef2f2;
    border: 1px solid #fca5a5;
    border-radius: 6px;
    color: #991b1b;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#cancelButton:hover {
    background-color: #fee2e2;
    border-color: #f87171;
    color: #7f1d1d;
}

QPushButton#cancelButton:pressed {
    background-color: #fecaca;
    border-color: #ef4444;
}

QPushButton#cancelButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Open Folder & Secondary Buttons (Neutral Slate Utility Tone) */
QPushButton#openFolderButton, QPushButton#secondaryButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #334155;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 14px;
}

QPushButton#openFolderButton:hover, QPushButton#secondaryButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}

QPushButton#openFolderButton:pressed, QPushButton#secondaryButton:pressed {
    background-color: #e2e8f0;
}

QPushButton#openFolderButton:disabled, QPushButton#secondaryButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Settings Button (Top-Right Header) */
QPushButton#settingsButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}

QPushButton#settingsButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}

QPushButton#settingsButton:pressed {
    background-color: #e2e8f0;
}

/* Compact Buttons (e.g. Copy Path, Check Updates) */
QPushButton#compactButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 500;
    color: #475569;
    min-height: 22px;
    max-height: 24px;
}

QPushButton#compactButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}

QPushButton#compactButton:pressed {
    background-color: #e2e8f0;
}

QPushButton#compactButton:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}

/* Component Cards (Settings Dialog & Panels) */
QFrame#componentCard {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
}

QFrame#componentCard QLabel {
    background-color: transparent;
    border: none;
}

/* Divider lines */
QFrame#divider {
    background-color: #e2e8f0;
    border: none;
    max-height: 1px;
}

/* Control Buttons (Pause, Resume, Cancel) */
QPushButton#pauseButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #334155;
    font-weight: 500;
}

QPushButton#pauseButton:hover {
    background-color: #fef3c7;
    border-color: #f59e0b;
    color: #92400e;
}

QPushButton#pauseButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

QPushButton#resumeButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #334155;
    font-weight: 500;
}

QPushButton#resumeButton:hover {
    background-color: #dcfce7;
    border-color: #10b981;
    color: #065f46;
}

QPushButton#resumeButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

QPushButton#cancelButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #475569;
    font-weight: 500;
}

QPushButton#cancelButton:hover {
    background-color: #fee2e2;
    border-color: #ef4444;
    color: #b91c1c;
}

QPushButton#cancelButton:disabled {
    background-color: #f8fafc;
    border-color: #e2e8f0;
    color: #94a3b8;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    font-size: 13px;
    color: #334155;
    background: transparent;
}

QCheckBox:disabled {
    color: #94a3b8;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}

QCheckBox::indicator:hover {
    border-color: #0066cc;
}

QCheckBox::indicator:disabled {
    background-color: #f1f5f9;
    border-color: #e2e8f0;
}

QCheckBox::indicator:checked {
    background-color: #0066cc;
    border-color: #0066cc;
    image: url("__CHECKMARK_PATH__");
}

/* Radio Buttons */
QRadioButton {
    spacing: 8px;
    font-size: 13px;
    color: #1e293b;
    background: transparent;
}

QRadioButton:hover {
    color: #0066cc;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #94a3b8;
    border-radius: 9px;
    background-color: #ffffff;
}

QRadioButton::indicator:hover {
    border-color: #0066cc;
}

QRadioButton::indicator:checked {
    border: 2px solid #0066cc;
    background-color: qradialgradient(
        cx: 0.5, cy: 0.5, radius: 0.5,
        fx: 0.5, fy: 0.5,
        stop: 0 #0066cc,
        stop: 0.48 #0066cc,
        stop: 0.54 #ffffff,
        stop: 1 #ffffff
    );
}

QRadioButton::indicator:disabled {
    border-color: #cbd5e1;
    background-color: #f1f5f9;
}

QTableView::indicator,
QTableWidget::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}

QTableView::indicator:hover,
QTableWidget::indicator:hover {
    border-color: #0066cc;
}

QTableView::indicator:checked,
QTableWidget::indicator:checked {
    background-color: #0066cc;
    border-color: #0066cc;
    image: url("__CHECKMARK_PATH__");
}

/* Table Widget */
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #fbfcfd;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    gridline-color: #f1f5f9;
    selection-background-color: #e0f2fe;
    selection-color: #0369a1;
    font-size: 13px;
    outline: none;
}

QTableWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #f1f5f9;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    font-weight: 600;
    font-size: 12px;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid #cbd5e1;
    border-right: 1px solid #e2e8f0;
}

QHeaderView::section:last {
    border-right: none;
}

/* Progress Bar */
QProgressBar {
    background-color: #e2e8f0;
    border-radius: 4px;
    text-align: center;
    font-weight: 600;
    font-size: 11px;
    color: #0f172a;
    min-height: 14px;
}

QProgressBar::chunk {
    background-color: #0066cc;
    border-radius: 4px;
}

/* Activity Log Panel */
QPlainTextEdit#logOutput {
    background-color: #0f172a;
    color: #38bdf8;
    font-family: "Consolas", "Cascadia Code", "Courier New", monospace;
    font-size: 12px;
    line-height: 1.4;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: #334155;
    selection-color: #f8fafc;
}

/* Scroll Bars */
QScrollBar:vertical {
    background-color: #f8fafc;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #cbd5e1;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #f8fafc;
    border-top: 1px solid #e2e8f0;
    color: #64748b;
    font-size: 12px;
    padding: 2px 10px;
}

/* Context Menus */
QMenu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
    color: #1e293b;
    font-size: 12px;
}

QMenu::item:selected {
    background-color: #0066cc;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #e2e8f0;
    margin: 4px 8px;
}
"""

# =============================================================================
# DARK THEME DEFINITIONS
# =============================================================================

_DARK_BASE = """
/* Global Dark Application Style */
QWidget {
    font-family: __FONT_FAMILY__;
    font-size: 13px;
    color: #f8fafc;
    background-color: #0f172a;
}

/* Window & Central Panels */
QMainWindow {
    background-color: #0f172a;
}

QDialog {
    background-color: #0f172a;
    color: #f8fafc;
}

QLabel {
    background-color: transparent;
}

/* Application Header Titles */
QLabel#appTitleLabel,
QLabel#summaryTitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #f8fafc;
    background-color: transparent;
}

/* Summary Dialog Elements */
QLabel#summaryTotalVal {
    font-weight: 700;
    color: #f1f5f9;
}

QLabel#summaryCompletedVal {
    font-weight: 700;
    color: #22c55e;
}

QLabel#summarySkippedVal {
    font-weight: 700;
    color: #94a3b8;
}

QLabel#summaryFailedVal {
    font-weight: 700;
    color: #ef4444;
}

QLabel#summaryFolderInfo {
    color: #94a3b8;
    font-size: 12px;
    padding: 4px;
}

/* Error Details Dialog Elements */
QLabel#errorDialogTitle {
    font-size: 18px;
    font-weight: 700;
    color: #f87171;
    background-color: transparent;
}

QLabel#errorVideoInfoLabel {
    font-size: 13px;
    color: #f1f5f9;
}

QLabel#errorReasonLabel {
    font-size: 13px;
    color: #f8fafc;
}

QLabel#errorActionLabel {
    font-size: 13px;
    color: #cbd5e1;
}

QLabel#errorTechMetaLabel {
    font-size: 11px;
    font-weight: 600;
    color: #94a3b8;
}

QTextEdit#errorTechTextEdit {
    background-color: #0b1120;
    color: #94a3b8;
    border: 1px solid #334155;
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 11px;
    padding: 6px;
}

QLabel#appSubtitleLabel {
    font-size: 12px;
    font-weight: 400;
    color: #94a3b8;
    background-color: transparent;
}

/* Section Group Boxes / Cards */
QGroupBox {
    background-color: #131c2c;
    border: 1px solid #223249;
    border-radius: 8px;
    margin-top: 20px;
    padding: 12px 14px 10px 14px;
    font-weight: 700;
    font-size: 14px;
    color: #f8fafc;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 2px 10px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.5px;
}

/* Coordinated Blue Tonal Progression - Dark Theme */
QGroupBox#urlGroupBox {
    border: 1px solid #223249;
    border-left: 4px solid #3b82f6;
}
QGroupBox#urlGroupBox::title {
    color: #60a5fa;
    background-color: #182438;
}

QGroupBox#videosGroupBox {
    border: 1px solid #1d4ed8;
    border-left: 4px solid #38bdf8;
}
QGroupBox#videosGroupBox::title {
    color: #38bdf8;
    background-color: #1a2942;
}

QGroupBox#downloadGroupBox {
    border: 1px solid #1e3a5f;
    border-left: 4px solid #2563eb;
}
QGroupBox#downloadGroupBox::title {
    color: #60a5fa;
    background-color: #172438;
}

QGroupBox#progressGroupBox {
    border: 1px solid #075985;
    border-left: 4px solid #0ea5e9;
}
QGroupBox#progressGroupBox::title {
    color: #7dd3fc;
    background-color: #132a42;
}

QGroupBox#logGroupBox {
    border: 1px solid #1e293b;
    border-left: 4px solid #475569;
}
QGroupBox#logGroupBox::title {
    color: #94a3b8;
    background-color: #162032;
}

/* Sub-Section Cards inside DOWNLOAD OPTION */
QFrame#subSectionCard {
    background-color: #0d1522;
    border: 1px solid #1c2a3d;
    border-radius: 6px;
    padding: 10px 12px;
}

QLabel#subSectionTitle {
    color: #93c5fd;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    background: transparent;
}

QLabel#formLabel {
    font-size: 11px;
    font-weight: 600;
    color: #94a3b8;
    background: transparent;
}

QLabel#subGroupTitle {
    font-size: 10px;
    font-weight: 700;
    color: #94a3b8;
    letter-spacing: 0.5px;
    background: transparent;
    padding-top: 4px;
}

/* Empty State Widget in Available Videos */
QWidget#emptyStateWidget {
    background-color: #172033;
    border: 1px dashed #334155;
    border-radius: 6px;
}

QLabel#emptyStateTitle {
    font-size: 14px;
    font-weight: 600;
    color: #cbd5e1;
    background: transparent;
}

QLabel#emptyStateSubtitle {
    font-size: 12px;
    font-weight: 400;
    color: #64748b;
    background: transparent;
}

/* Section Header Labels */
QLabel#sectionHeader {
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    background: transparent;
}

/* Text Input Fields */
QLineEdit {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: #f8fafc;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    min-height: 20px;
}

QLineEdit:hover {
    border-color: #475569;
}

QLineEdit:focus {
    border: 2px solid #0284c7;
    background-color: #1e293b;
}

QLineEdit:disabled {
    background-color: #0f172a;
    color: #64748b;
    border-color: #334155;
}

/* Search Box */
QLineEdit#searchBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    color: #f8fafc;
    min-width: 180px;
    max-width: 260px;
}

QLineEdit#searchBox:focus {
    border: 2px solid #0284c7;
}

/* Combo Boxes */
QComboBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 13px;
    color: #f8fafc;
    min-height: 22px;
}

QComboBox:hover {
    border-color: #475569;
}

QComboBox:focus {
    border: 2px solid #0284c7;
}

QComboBox:disabled {
    background-color: #0f172a;
    color: #64748b;
    border-color: #334155;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #334155;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #172033;
}

QComboBox::down-arrow {
    image: url("__ARROW_DOWN_PATH__");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #f8fafc;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

QComboBox QAbstractItemView::item:disabled {
    color: #64748b;
    background-color: transparent;
}

/* Push Buttons (Default Base) */
QPushButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    font-size: 13px;
    color: #f1f5f9;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #273549;
}

QPushButton:disabled {
    background-color: #0f172a;
    color: #64748b;
    border-color: #334155;
}

/* Primary Buttons */
QPushButton#primaryButton, QPushButton#scanButton {
    background-color: #0284c7;
    border: 1px solid #0369a1;
    color: #ffffff;
    font-weight: 600;
    padding: 6px 18px;
}

QPushButton#primaryButton:hover, QPushButton#scanButton:hover {
    background-color: #0369a1;
    border-color: #075985;
}

QPushButton#primaryButton:pressed, QPushButton#scanButton:pressed {
    background-color: #075985;
}

QPushButton#primaryButton:disabled, QPushButton#scanButton:disabled {
    background-color: #1e3a5f;
    border-color: #1e3a5f;
    color: #64748b;
}

/* Main Start Download Button (Primary Blue) */
QPushButton#downloadButton {
    background-color: #0284c7;
    border: 1px solid #0369a1;
    border-radius: 6px;
    color: #ffffff;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 14px;
}

QPushButton#downloadButton:hover {
    background-color: #0369a1;
    border-color: #075985;
}

QPushButton#downloadButton:pressed {
    background-color: #075985;
}

QPushButton#downloadButton:disabled {
    background-color: #1e3a5f;
    border-color: #1e3a5f;
    color: #64748b;
}

/* Pause Button (Warm Amber Warning Tone) */
QPushButton#pauseButton {
    background-color: #451a03;
    border: 1px solid #b45309;
    border-radius: 6px;
    color: #fde68a;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#pauseButton:hover {
    background-color: #78350f;
    border-color: #d97706;
    color: #fef3c7;
}

QPushButton#pauseButton:pressed {
    background-color: #92400e;
}

QPushButton#pauseButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

/* Resume Button (Green Success Tone) */
QPushButton#resumeButton {
    background-color: #14532d;
    border: 1px solid #15803d;
    border-radius: 6px;
    color: #86efac;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#resumeButton:hover {
    background-color: #166534;
    border-color: #22c55e;
    color: #bbf7d0;
}

QPushButton#resumeButton:pressed {
    background-color: #15803d;
}

QPushButton#resumeButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

/* Cancel Button (Destructive Red Tone) */
QPushButton#cancelButton {
    background-color: #7f1d1d;
    border: 1px solid #b91c1c;
    border-radius: 6px;
    color: #fca5a5;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}

QPushButton#cancelButton:hover {
    background-color: #991b1b;
    border-color: #dc2626;
    color: #fecaca;
}

QPushButton#cancelButton:pressed {
    background-color: #b91c1c;
}

QPushButton#cancelButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

/* Open Folder & Secondary Buttons (Neutral Slate Utility Tone) */
QPushButton#openFolderButton, QPushButton#secondaryButton {
    background-color: #1e293b;
    border: 1px solid #475569;
    border-radius: 6px;
    color: #f1f5f9;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 14px;
}

QPushButton#openFolderButton:hover, QPushButton#secondaryButton:hover {
    background-color: #334155;
    border-color: #64748b;
    color: #ffffff;
}

QPushButton#openFolderButton:pressed, QPushButton#secondaryButton:pressed {
    background-color: #273549;
}

QPushButton#openFolderButton:disabled, QPushButton#secondaryButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

/* Settings Button (Top-Right Header) */
QPushButton#settingsButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}

QPushButton#settingsButton:hover {
    background-color: #334155;
    border-color: #475569;
}

QPushButton#settingsButton:pressed {
    background-color: #273549;
}

/* Compact Buttons (e.g. Copy Path, Check Updates) */
QPushButton#compactButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 500;
    color: #94a3b8;
    min-height: 22px;
    max-height: 24px;
}

QPushButton#compactButton:hover {
    background-color: #334155;
    border-color: #475569;
    color: #f8fafc;
}

QPushButton#compactButton:pressed {
    background-color: #273549;
}

QPushButton#compactButton:disabled {
    background-color: #0f172a;
    color: #64748b;
    border-color: #334155;
}

/* Component Cards (Settings Dialog & Panels) */
QFrame#componentCard {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
}

QFrame#componentCard QLabel {
    background-color: transparent;
    border: none;
}

/* Divider lines */
QFrame#divider {
    background-color: #334155;
    border: none;
    max-height: 1px;
}

/* Control Buttons (Pause, Resume, Cancel) */
QPushButton#pauseButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    color: #f1f5f9;
    font-weight: 500;
}

QPushButton#pauseButton:hover {
    background-color: #451a03;
    border-color: #b45309;
    color: #fde68a;
}

QPushButton#pauseButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

QPushButton#resumeButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    color: #f1f5f9;
    font-weight: 500;
}

QPushButton#resumeButton:hover {
    background-color: #064e3b;
    border-color: #059669;
    color: #a7f3d0;
}

QPushButton#resumeButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

QPushButton#cancelButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    color: #94a3b8;
    font-weight: 500;
}

QPushButton#cancelButton:hover {
    background-color: #450a0a;
    border-color: #dc2626;
    color: #fca5a5;
}

QPushButton#cancelButton:disabled {
    background-color: #0f172a;
    border-color: #334155;
    color: #64748b;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    font-size: 13px;
    color: #e2e8f0;
    background: transparent;
}

QCheckBox:disabled {
    color: #64748b;
}

QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #1e293b;
}

QCheckBox::indicator:hover {
    border-color: #0284c7;
}

QCheckBox::indicator:disabled {
    background-color: #0f172a;
    border-color: #334155;
}

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #0284c7;
    image: url("__CHECKMARK_PATH__");
}

/* Radio Buttons */
QRadioButton {
    spacing: 8px;
    font-size: 13px;
    color: #f1f5f9;
    background: transparent;
}

QRadioButton:hover {
    color: #38bdf8;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #64748b;
    border-radius: 9px;
    background-color: #1e293b;
}

QRadioButton::indicator:hover {
    border-color: #38bdf8;
}

QRadioButton::indicator:checked {
    border: 2px solid #38bdf8;
    background-color: qradialgradient(
        cx: 0.5, cy: 0.5, radius: 0.5,
        fx: 0.5, fy: 0.5,
        stop: 0 #38bdf8,
        stop: 0.48 #38bdf8,
        stop: 0.54 #1e293b,
        stop: 1 #1e293b
    );
}

QRadioButton::indicator:disabled {
    border-color: #334155;
    background-color: #0f172a;
}

QTableView::indicator,
QTableWidget::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #1e293b;
}

QTableView::indicator:hover,
QTableWidget::indicator:hover {
    border-color: #0284c7;
}

QTableView::indicator:checked,
QTableWidget::indicator:checked {
    background-color: #0284c7;
    border-color: #0284c7;
    image: url("__CHECKMARK_PATH__");
}

/* Table Widget */
QTableWidget {
    background-color: #1e293b;
    alternate-background-color: #172033;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #253347;
    selection-background-color: #0369a1;
    selection-color: #ffffff;
    font-size: 13px;
    color: #f8fafc;
    outline: none;
}

QTableWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #253347;
    color: #f8fafc;
}

QHeaderView::section {
    background-color: #0f172a;
    color: #94a3b8;
    font-weight: 600;
    font-size: 12px;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid #334155;
    border-right: 1px solid #334155;
}

QHeaderView::section:last {
    border-right: none;
}

/* Progress Bar */
QProgressBar {
    background-color: #334155;
    border-radius: 4px;
    text-align: center;
    font-weight: 600;
    font-size: 11px;
    color: #f8fafc;
    min-height: 14px;
}

QProgressBar::chunk {
    background-color: #0284c7;
    border-radius: 4px;
}

/* Activity Log Panel */
QPlainTextEdit#logOutput {
    background-color: #080c14;
    color: #38bdf8;
    font-family: "Consolas", "Cascadia Code", "Courier New", monospace;
    font-size: 12px;
    line-height: 1.4;
    border: 1px solid #1e293b;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: #1e3a5f;
    selection-color: #f8fafc;
}

/* Scroll Bars */
QScrollBar:vertical {
    background-color: #0f172a;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #0f172a;
    border-top: 1px solid #334155;
    color: #94a3b8;
    font-size: 12px;
    padding: 2px 10px;
}

/* Context Menus */
QMenu {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
    color: #f1f5f9;
    font-size: 12px;
}

QMenu::item:selected {
    background-color: #0284c7;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #334155;
    margin: 4px 8px;
}
"""


def get_font_family(lang: Optional[str] = None) -> str:
    """Returns the typography font stack based on the active application language or specified lang code."""
    try:
        from core.i18n import I18nManager
        is_zh = (lang == I18nManager.LANG_ZH) if lang is not None else I18nManager.is_chinese()
        if is_zh:
            return '"Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Segoe UI Variable", -apple-system, BlinkMacSystemFont, Roboto, sans-serif'
    except Exception:
        pass
    return '"Segoe UI", "Segoe UI Variable", -apple-system, BlinkMacSystemFont, Roboto, sans-serif'


def get_theme_stylesheet(effective_theme: str) -> str:
    """Returns the compiled stylesheet for the specified effective theme (Light or Dark)."""
    font_stack = get_font_family()
    if effective_theme == ThemeMode.DARK:
        return (
            _DARK_BASE
            .replace("__FONT_FAMILY__", font_stack)
            .replace("__ARROW_DOWN_PATH__", _arrow_down_dark_path)
            .replace("__CHECKMARK_PATH__", _checkmark_path)
        )
    return (
        _LIGHT_BASE
        .replace("__FONT_FAMILY__", font_stack)
        .replace("__ARROW_DOWN_PATH__", _arrow_down_light_path)
        .replace("__CHECKMARK_PATH__", _checkmark_path)
    )


# Backwards compatibility
MODERN_STYLE_SHEET = get_theme_stylesheet(ThemeMode.LIGHT)


class ThemeManager:
    """
    Application-wide manager for Theme preference and runtime switching.
    """

    _current_preference: str = ThemeMode.SYSTEM
    _effective_theme: str = ThemeMode.LIGHT
    _listeners: List[Callable[[str, bool], None]] = []

    @classmethod
    def current_preference(cls) -> str:
        """Returns the user's selected preference ('System', 'Light', or 'Dark')."""
        return cls._current_preference

    @classmethod
    def effective_theme(cls) -> str:
        """Returns the resolved active theme ('Light' or 'Dark')."""
        return cls._effective_theme

    @classmethod
    def is_dark(cls) -> bool:
        """Returns True if the effective theme is Dark."""
        return cls._effective_theme == ThemeMode.DARK

    @classmethod
    def resolve_effective_theme(cls, preference: str) -> str:
        """Resolves preference into either 'Light' or 'Dark'."""
        if preference == ThemeMode.SYSTEM:
            return detect_windows_theme()
        if preference == ThemeMode.DARK:
            return ThemeMode.DARK
        return ThemeMode.LIGHT

    @classmethod
    def register_listener(cls, callback: Callable[[str, bool], None]) -> None:
        """Registers a callback to be invoked when the effective theme changes: callback(effective_theme, is_dark)."""
        if callback not in cls._listeners:
            cls._listeners.append(callback)

    @classmethod
    def unregister_listener(cls, callback: Callable[[str, bool], None]) -> None:
        """Unregisters a previously registered listener callback."""
        if callback in cls._listeners:
            cls._listeners.remove(callback)

    @classmethod
    def _on_language_changed(cls, lang: str) -> None:
        """Automatically updates typography font family and stylesheets when UI language changes."""
        cls.apply_theme(cls._current_preference)

    @classmethod
    def apply_theme(cls, preference: str, app: Optional[QApplication] = None) -> str:
        """
        Applies the selected theme preference globally to the QApplication.

        Returns:
            The resolved effective theme string ('Light' or 'Dark').
        """
        cls._current_preference = preference
        effective = cls.resolve_effective_theme(preference)
        cls._effective_theme = effective
        is_dark = (effective == ThemeMode.DARK)

        qapp = app or QApplication.instance()
        if qapp:
            stylesheet = get_theme_stylesheet(effective)
            qapp.setStyleSheet(stylesheet)
            from PySide6.QtGui import QFont
            try:
                from core.i18n import I18nManager
                font_family = "Noto Sans SC" if I18nManager.is_chinese() else "Segoe UI"
                base_font = QFont(font_family, 9)
                if base_font.pointSize() <= 0:
                    base_font.setPointSize(9)
                qapp.setFont(base_font)
            except Exception:
                pass

        # Notify registered listeners
        for listener in list(cls._listeners):
            try:
                listener(effective, is_dark)
            except Exception:
                pass

        return effective


# Automatically listen for language changes to swap font family seamlessly
try:
    from core.i18n import I18nManager
    I18nManager.register_listener(ThemeManager._on_language_changed)
except Exception:
    pass

