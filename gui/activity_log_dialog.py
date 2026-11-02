"""
activity_log_dialog.py
Standalone Activity Log Window for Channel Harvest.
Provides dedicated modeless dialog with real-time log streaming, copy, and clear functionality.
"""

from typing import Optional, List
from PySide6.QtCore import Qt, QSize, QByteArray, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QApplication,
    QWidget,
)

from core.paths import get_logo_file, get_app_icon_file
from core.i18n import I18nManager, tr
from gui.styles import ThemeManager


def get_activity_log_icon(color: Optional[str] = None) -> QIcon:
    """Returns a crisp SVG terminal / code log icon for the activity log button."""
    if color is None:
        color = "#94a3b8" if ThemeManager.is_dark() else "#475569"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="4 17 10 11 4 5"></polyline>
      <line x1="12" y1="19" x2="20" y2="19"></line>
    </svg>"""

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class ActivityLogDialog(QDialog):
    """
    Dedicated Activity Log window displayed when clicking the Activity Log button.
    Allows monitoring scanning, extraction, and download processes in real time.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog_activity_log_title"))
        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))
        else:
            app_icon = get_app_icon_file()
            if app_icon.exists():
                self.setWindowIcon(QIcon(str(app_icon)))
        self.resize(800, 520)
        self.setMinimumSize(520, 340)

        # Allow non-modal behavior so user can work while viewing logs
        self.setModal(False)

        self._init_ui()
        ThemeManager.register_listener(self._on_theme_changed)
        I18nManager.register_listener(self._on_language_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Top Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.title_label = QLabel(tr("section_activity_log"))
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        top_bar.addWidget(self.title_label)

        top_bar.addStretch(1)

        self.copy_btn = QPushButton(tr("btn_copy_log"))
        self.copy_btn.setObjectName("secondaryButton")
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet("font-size: 12px; padding: 2px 12px;")
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        top_bar.addWidget(self.copy_btn)

        self.clear_btn = QPushButton(tr("clear_log"))
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.setFixedHeight(28)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("font-size: 12px; padding: 2px 12px;")
        self.clear_btn.clicked.connect(self.clear_log)
        top_bar.addWidget(self.clear_btn)

        layout.addLayout(top_bar)

        # Center: Log output text edit
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("dialogLogOutput")
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_output.setFont(font)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._apply_text_edit_style()

        layout.addWidget(self.log_output, stretch=1)

        # Bottom Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)

        self.status_hint = QLabel("")
        self.status_hint.setStyleSheet("font-size: 11px; color: #64748b;")
        bottom_bar.addWidget(self.status_hint)

        bottom_bar.addStretch(1)

        self.close_btn = QPushButton(tr("btn_close"))
        self.close_btn.setObjectName("secondaryButton")
        self.close_btn.setFixedHeight(30)
        self.close_btn.setMinimumWidth(80)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        bottom_bar.addWidget(self.close_btn)

        layout.addLayout(bottom_bar)

    def _apply_text_edit_style(self) -> None:
        """Applies clean dark or light monospace styling to the log text area."""
        if ThemeManager.is_dark():
            self.log_output.setStyleSheet("""
                QPlainTextEdit#dialogLogOutput {
                    background-color: #090d16;
                    color: #e2e8f0;
                    border: 1px solid #1e293b;
                    border-radius: 6px;
                    padding: 8px;
                    font-family: Consolas, 'Cascadia Code', monospace;
                    font-size: 12px;
                    line-height: 1.4;
                }
            """)
        else:
            self.log_output.setStyleSheet("""
                QPlainTextEdit#dialogLogOutput {
                    background-color: #f8fafc;
                    color: #0f172a;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    padding: 8px;
                    font-family: Consolas, 'Cascadia Code', monospace;
                    font-size: 12px;
                    line-height: 1.4;
                }
            """)

    def set_logs(self, logs: List[str]) -> None:
        """Sets full log text from an existing list of log messages."""
        self.log_output.clear()
        if logs:
            self.log_output.setPlainText("\n".join(logs))
            self._scroll_to_bottom()

    def append_log(self, formatted_message: str) -> None:
        """Appends a new formatted log message and auto-scrolls to the bottom."""
        self.log_output.appendPlainText(formatted_message)
        self._scroll_to_bottom()

    def clear_log(self) -> None:
        """Clears the displayed log output."""
        self.log_output.clear()
        self.status_hint.setText(tr("log_cleared"))
        QTimer.singleShot(2000, self._safe_clear_status_hint)

    def _safe_clear_status_hint(self) -> None:
        try:
            self.status_hint.setText("")
        except (RuntimeError, AttributeError):
            pass

    def _safe_reset_copy_btn(self, orig_text: str) -> None:
        try:
            self.copy_btn.setText(orig_text)
        except (RuntimeError, AttributeError):
            pass

    def _on_copy_clicked(self) -> None:
        """Copies all log contents to the system clipboard."""
        text = self.log_output.toPlainText()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        orig_text = self.copy_btn.text()
        self.copy_btn.setText(tr("btn_copied"))
        self.status_hint.setText(tr("log_copied_hint"))
        QTimer.singleShot(1800, lambda: self._safe_reset_copy_btn(orig_text))
        QTimer.singleShot(2500, self._safe_clear_status_hint)

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.log_output.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _on_theme_changed(self, theme_name: str) -> None:
        self._apply_text_edit_style()

    def _on_language_changed(self, lang: str) -> None:
        self.setWindowTitle(tr("dialog_activity_log_title"))
        self.title_label.setText(tr("section_activity_log"))
        self.copy_btn.setText(tr("btn_copy_log"))
        self.clear_btn.setText(tr("clear_log"))
        self.close_btn.setText(tr("btn_close"))

    def closeEvent(self, event) -> None:
        # Hide instead of destroy to preserve contents smoothly
        super().closeEvent(event)
