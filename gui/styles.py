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
    font-family: "Segoe UI", "Segoe UI Variable", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
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
QLabel#appTitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
    background-color: transparent;
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
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 12px 8px 12px;
    font-weight: 700;
    font-size: 11px;
    color: #475569;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 4px;
    background-color: #ffffff;
    color: #475569;
    letter-spacing: 0.5px;
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

/* Main Start Download Button */
QPushButton#downloadButton {
    background-color: #0066cc;
    border: 1px solid #005bb5;
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 8px 24px;
    border-radius: 6px;
}

QPushButton#downloadButton:hover {
    background-color: #005bb5;
    border-color: #004c99;
}

QPushButton#downloadButton:pressed {
    background-color: #004c99;
}

QPushButton#downloadButton:disabled {
    background-color: #bfdbfe;
    border-color: #bfdbfe;
    color: #ffffff;
}

/* Secondary Buttons */
QPushButton#secondaryButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #334155;
    font-weight: 500;
}

QPushButton#secondaryButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
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

QCheckBox::indicator:checked {
    background-color: #0066cc;
    border-color: #0066cc;
    image: url("__CHECKMARK_PATH__");
}

QTableWidget::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}

QTableWidget::indicator:hover {
    border-color: #0066cc;
}

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
    font-family: "Segoe UI", "Segoe UI Variable", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
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
QLabel#appTitleLabel {
    font-size: 20px;
    font-weight: 700;
    color: #f8fafc;
    background-color: transparent;
}

QLabel#appSubtitleLabel {
    font-size: 12px;
    font-weight: 400;
    color: #94a3b8;
    background-color: transparent;
}

/* Section Group Boxes / Cards */
QGroupBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 12px 8px 12px;
    font-weight: 700;
    font-size: 11px;
    color: #94a3b8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0 4px;
    background-color: #1e293b;
    color: #94a3b8;
    letter-spacing: 0.5px;
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

/* Main Start Download Button */
QPushButton#downloadButton {
    background-color: #0284c7;
    border: 1px solid #0369a1;
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 8px 24px;
    border-radius: 6px;
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

/* Secondary Buttons */
QPushButton#secondaryButton {
    background-color: #1e293b;
    border: 1px solid #334155;
    color: #f1f5f9;
    font-weight: 500;
}

QPushButton#secondaryButton:hover {
    background-color: #334155;
    border-color: #475569;
    color: #ffffff;
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

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #0284c7;
    image: url("__CHECKMARK_PATH__");
}

QTableWidget::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #475569;
    border-radius: 4px;
    background-color: #1e293b;
}

QTableWidget::indicator:hover {
    border-color: #0284c7;
}

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


def get_theme_stylesheet(effective_theme: str) -> str:
    """Returns the compiled stylesheet for the specified effective theme (Light or Dark)."""
    if effective_theme == ThemeMode.DARK:
        return (
            _DARK_BASE
            .replace("__ARROW_DOWN_PATH__", _arrow_down_dark_path)
            .replace("__CHECKMARK_PATH__", _checkmark_path)
        )
    return (
        _LIGHT_BASE
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

        # Notify registered listeners
        for listener in list(cls._listeners):
            try:
                listener(effective, is_dark)
            except Exception:
                pass

        return effective
