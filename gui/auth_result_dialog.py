# -*- coding: utf-8 -*-
"""
auth_result_dialog.py
User-facing authentication results and diagnostics modal for Channel Harvest.

Displays:
1. Result status banner (Success / Failure)
2. Browser & Profile metadata
3. Exact failed stage
4. Human-readable reason & evidence-based cause
5. Suggested actionable next steps
6. Sanitized technical error details
7. [ Copy Diagnostic Details ] button with clipboard feedback
"""

from typing import Optional

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
from downloader.auth_checker import AuthTestResult, AuthStatusCode


class AuthResultDialog(QDialog):
    """
    Modal presentation dialog showing YouTube authentication test results
    with stage-aware diagnostics and sanitized clipboard export.
    """

    def __init__(
        self,
        result: AuthTestResult,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.result = result

        title = tr("auth_dialog_title") if tr("auth_dialog_title") != "auth_dialog_title" else "YouTube Authentication Test"
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setModal(True)

        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Main Result Header
        is_success = self.result.success
        is_decrypt_fail = (self.result.status_code == AuthStatusCode.COOKIE_DECRYPTION_FAILED)
        is_not_configured = (self.result.status_code == AuthStatusCode.NOT_CONFIGURED)

        if is_decrypt_fail:
            header_text = tr("auth_result_abe_header_fmt", browser=self.result.browser_name)
            header_color = "#d97706"  # Amber
        elif is_not_configured:
            header_text = tr("auth_result_not_configured")
            header_color = "#3b82f6"  # Blue
        elif is_success:
            if self.result.has_session:
                header_text = tr("auth_result_success_fmt", browser=self.result.browser_name)
            else:
                header_text = tr("auth_result_success_no_session_fmt", browser=self.result.browser_name)
            header_color = "#10b981"  # Emerald green
        else:
            header_text = tr("auth_result_failed_fmt", browser=self.result.browser_name)
            header_color = "#ef4444"  # Crimson red

        header_label = QLabel(header_text)
        header_label.setObjectName("authResultHeader")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {header_color}; font-weight: bold; margin-bottom: 4px;")
        layout.addWidget(header_label)

        # 2. Stage & Source Metadata Group
        meta_group = QGroupBox(tr("auth_dialog_stage_heading").replace("&", "&&"))
        meta_layout = QVBoxLayout(meta_group)
        meta_layout.setContentsMargins(14, 10, 14, 10)
        meta_layout.setSpacing(4)

        auth_method_lbl = tr("auth_method_label").rstrip(":：") + ":"
        stage_lbl = tr("auth_dialog_stage").rstrip(":：") + ":"
        source_lbl = tr("auth_dialog_source").rstrip(":：") + ":"
        status_lbl = tr("auth_status_label").rstrip(":：") + ":"

        method_str = f"<b>{auth_method_lbl}</b> {self.result.auth_method}"
        stage_str = f"<b>{stage_lbl}</b> {self.result.stage}"
        source_str = f"<b>{source_lbl}</b> {self.result.browser_name}"
        if self.result.profile_name and self.result.profile_name != "N/A":
            source_str += tr("auth_result_profile_fmt", profile=self.result.profile_name)
        status_str = f"<b>{status_lbl}</b> {self.result.status_code}"

        meta_lbl0 = QLabel(method_str)
        meta_lbl1 = QLabel(stage_str)
        meta_lbl2 = QLabel(source_str)
        meta_lbl3 = QLabel(status_str)
        meta_lbl0.setStyleSheet("font-size: 12px;")
        meta_lbl1.setStyleSheet("font-size: 12px;")
        meta_lbl2.setStyleSheet("font-size: 12px;")
        meta_lbl3.setStyleSheet("font-size: 12px;")
        meta_layout.addWidget(meta_lbl0)
        meta_layout.addWidget(meta_lbl1)
        meta_layout.addWidget(meta_lbl2)
        meta_layout.addWidget(meta_lbl3)
        layout.addWidget(meta_group)

        # 3. Reason Group
        reason_group = QGroupBox(tr("auth_dialog_reason_heading"))
        reason_layout = QVBoxLayout(reason_group)
        reason_layout.setContentsMargins(14, 12, 14, 12)
        reason_lbl = QLabel(self.result.reason)
        reason_lbl.setWordWrap(True)
        reason_lbl.setStyleSheet("font-size: 13px; line-height: 1.4;")
        reason_layout.addWidget(reason_lbl)
        layout.addWidget(reason_group)

        # 4. Suggested Action Group
        if self.result.suggested_action:
            action_group = QGroupBox(tr("auth_dialog_action_heading"))
            action_layout = QVBoxLayout(action_group)
            action_layout.setContentsMargins(14, 12, 14, 12)
            action_lbl = QLabel(self.result.suggested_action)
            action_lbl.setWordWrap(True)
            action_lbl.setStyleSheet("font-size: 13px; line-height: 1.4;")
            action_layout.addWidget(action_lbl)
            layout.addWidget(action_group)

        # 5. Technical Details (if failed)
        if not is_success and (self.result.technical_error or self.result.raw_error):
            tech_group = QGroupBox(tr("auth_dialog_tech_heading"))
            tech_layout = QVBoxLayout(tech_group)
            tech_layout.setContentsMargins(14, 10, 14, 10)

            tech_text = QTextEdit()
            tech_text.setReadOnly(True)
            tech_text.setMaximumHeight(80)
            tech_text.setFontFamily("Consolas, Courier New, monospace")
            tech_text.setFontPointSize(9.5)
            err_content = self.result.technical_error or self.result.raw_error
            tech_text.setPlainText(err_content.strip())
            tech_text.setStyleSheet(
                "background-color: rgba(0,0,0,0.05); border: 1px solid rgba(128,128,128,0.2); border-radius: 4px;"
            )
            tech_layout.addWidget(tech_text)
            layout.addWidget(tech_group)

        # 6. Button Row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 8, 0, 0)
        btn_row.setSpacing(10)

        self.copy_btn = QPushButton(f"📋 {tr('auth_dialog_copy_btn')}")
        self.copy_btn.setObjectName("compactButton")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy_details_clicked)
        btn_row.addWidget(self.copy_btn)

        if is_decrypt_fail:
            self.select_cookie_btn = QPushButton(f"📁 {tr('auth_select_cookie_file_btn')}")
            self.select_cookie_btn.setObjectName("compactButton")
            self.select_cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.select_cookie_btn.clicked.connect(self._on_select_cookie_file_clicked)
            btn_row.addWidget(self.select_cookie_btn)

        btn_row.addStretch()

        close_btn = QPushButton(tr("auth_dialog_close_btn"))
        close_btn.setMinimumWidth(90)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _on_select_cookie_file_clicked(self) -> None:
        """Opens file dialog to select cookies.txt, then updates Settings and closes."""
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("auth_select_cookie_file"),
            "",
            tr("cookie_file_filter"),
        )
        if file_path:
            norm_path = str(Path(file_path).resolve())
            from core.settings import SettingsManager
            sm = SettingsManager()
            sm.set("auth_method", "custom_file")
            sm.set("browser_cookies", "custom_file")
            sm.set("custom_cookie_file", norm_path)
            if self.parent() and hasattr(self.parent(), "_sync_auth_ui_from_settings"):
                self.parent()._sync_auth_ui_from_settings()
            self.accept()

    def _on_copy_details_clicked(self) -> None:
        """Copies sanitized diagnostic details to the system clipboard."""
        report = self.result.to_diagnostic_report()
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(report)

        original_text = self.copy_btn.text()
        self.copy_btn.setText(f"✓ {tr('copied')}")
        self.copy_btn.setEnabled(False)

        def _restore():
            self.copy_btn.setText(original_text)
            self.copy_btn.setEnabled(True)

        QTimer.singleShot(2000, _restore)