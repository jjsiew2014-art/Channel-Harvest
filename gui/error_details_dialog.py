"""
error_details_dialog.py
User-facing error details modal dialog for Channel Harvest.

Displays a clear diagnostic hierarchy:
1. Dialog Title / Stage Header
2. Video Information
3. Reason: human-readable explanation
4. What you can do: actionable suggested steps
5. Technical Details: component, error category, sanitized technical output
6. Actions: [ Copy Error Details ] and [ Close ]
"""

from pathlib import Path
from typing import Optional, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QTextEdit,
    QWidget,
)

from core.paths import get_logo_file
from core.i18n import tr
from core.error_classifier import DownloadError


class ErrorDetailsDialog(QDialog):
    """
    Modal presentation dialog explaining a video download failure
    with clear causes, actionable guidance, and sanitized technical details.
    """

    def __init__(
        self,
        error: DownloadError,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.error = error

        self.setWindowTitle(tr("error_dialog_title"))
        self.setMinimumWidth(500)
        self.setModal(True)

        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        self._init_ui()

    def _init_ui(self) -> None:
        """Constructs the hierarchical presentation layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Main Header Title
        title_text = self.error.get_localized_title() if hasattr(self.error, "get_localized_title") else (self.error.title or tr("error"))
        title_label = QLabel(f"⚠️ {title_text}")
        title_label.setObjectName("errorDialogTitle")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 2. Target Video Info
        if self.error.video_title or self.error.video_id:
            info_group = QGroupBox(tr("error_dialog_video_label"))
            info_layout = QVBoxLayout(info_group)
            info_layout.setContentsMargins(14, 12, 14, 12)
            info_layout.setSpacing(4)

            title_str = self.error.video_title or tr("unknown_title")
            id_str = f" [ID: {self.error.video_id}]" if self.error.video_id else ""
            vid_lbl = QLabel(f"<b>{title_str}</b>{id_str}")
            vid_lbl.setWordWrap(True)
            vid_lbl.setObjectName("errorVideoInfoLabel")
            info_layout.addWidget(vid_lbl)
            layout.addWidget(info_group)

        # 3. Reason Section
        reason_group = QGroupBox(tr("error_dialog_reason_heading"))
        reason_layout = QVBoxLayout(reason_group)
        reason_layout.setContentsMargins(14, 12, 14, 12)
        reason_lbl = QLabel(self.error.get_localized_user_message())
        reason_lbl.setWordWrap(True)
        reason_lbl.setObjectName("errorReasonLabel")
        reason_layout.addWidget(reason_lbl)
        layout.addWidget(reason_group)

        # 4. What you can do Section
        action_group = QGroupBox(tr("error_dialog_action_heading"))
        action_layout = QVBoxLayout(action_group)
        action_layout.setContentsMargins(14, 12, 14, 12)
        action_lbl = QLabel(self.error.get_localized_suggested_action())
        action_lbl.setWordWrap(True)
        action_lbl.setObjectName("errorActionLabel")
        action_layout.addWidget(action_lbl)
        layout.addWidget(action_group)

        # 5. Technical Details Section
        tech_group = QGroupBox(tr("error_dialog_tech_heading"))
        tech_layout = QVBoxLayout(tech_group)
        tech_layout.setContentsMargins(14, 12, 14, 12)
        tech_layout.setSpacing(6)

        header_details = (
            f"{tr('tech_category_label')}: {self.error.category}  |  "
            f"{tr('tech_component_label')}: {self.error.component}  |  "
            f"{tr('tech_stage_label')}: {self.error.stage.capitalize()}"
        )
        if self.error.http_status:
            header_details += f"  |  {tr('tech_http_status_label')}: {self.error.http_status}"

        meta_lbl = QLabel(header_details)
        meta_lbl.setObjectName("errorTechMetaLabel")
        tech_layout.addWidget(meta_lbl)

        self.tech_edit = QTextEdit()
        self.tech_edit.setObjectName("errorTechTextEdit")
        self.tech_edit.setReadOnly(True)
        self.tech_edit.setMaximumHeight(90)
        self.tech_edit.setPlainText(self.error.technical_details or self.error.raw_error or tr("no_tech_details"))
        tech_layout.addWidget(self.tech_edit)
        layout.addWidget(tech_group)

        # 6. Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.copy_btn = QPushButton(tr("error_dialog_copy_btn"))
        self.copy_btn.setObjectName("primaryButton")
        self.copy_btn.setMinimumHeight(34)
        self.copy_btn.clicked.connect(self._on_copy_report)
        btn_layout.addWidget(self.copy_btn)

        self.close_btn = QPushButton(tr("close"))
        self.close_btn.setObjectName("secondaryButton")
        self.close_btn.setMinimumHeight(34)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _get_runtime_info(self) -> Dict[str, str]:
        """Collects current runtime version information."""
        info = {
            "yt-dlp": "Unknown",
            "ejs": "Not Installed",
            "deno": "Not Found",
            "ffmpeg": "Not Found",
        }
        try:
            from downloader.updater import YtDlpUpdater
            info["yt-dlp"] = YtDlpUpdater.get_installed_version()
        except Exception:
            pass

        try:
            import yt_dlp_ejs
            info["ejs"] = getattr(yt_dlp_ejs, "__version__", getattr(yt_dlp_ejs, "version", "Installed"))
        except Exception:
            pass

        try:
            from downloader.deno_checker import DenoChecker
            is_ok, _, ver, _ = DenoChecker.detect()
            if is_ok:
                info["deno"] = ver
        except Exception:
            pass

        try:
            from downloader.ffmpeg_checker import FFmpegChecker
            is_ok, _, ver, _ = FFmpegChecker.detect()
            if is_ok:
                info["ffmpeg"] = ver
        except Exception:
            pass

        return info

    def _on_copy_report(self) -> None:
        """Copies the sanitized troubleshooting report to the system clipboard."""
        runtime_info = self._get_runtime_info()
        report_text = self.error.to_report(runtime_info=runtime_info)
        QGuiApplication.clipboard().setText(report_text)

        # Visual button feedback
        self.copy_btn.setText(tr("error_dialog_copied"))
        self.copy_btn.setEnabled(False)
        QTimer.singleShot(2000, self._reset_copy_btn)

    def _reset_copy_btn(self) -> None:
        """Restores the copy button text."""
        self.copy_btn.setText(tr("error_dialog_copy_btn"))
        self.copy_btn.setEnabled(True)
