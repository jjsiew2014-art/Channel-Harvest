"""
summary_dialog.py
Completion summary modal dialog for Channel Harvest.

Displays overall batch statistics (Total, Completed, Skipped, Failed)
and provides a one-click button to open the download folder in Windows Explorer.
"""

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QMessageBox,
)
from core.paths import get_logo_file


class SummaryDialog(QDialog):
    """
    Modal dialog displayed when the download queue finishes.
    """

    def __init__(
        self,
        completed: int,
        skipped: int,
        failed: int,
        total: int,
        download_folder: str,
        parent: Optional[QDialog] = None,
    ):
        super().__init__(parent)
        self.completed = completed
        self.skipped = skipped
        self.failed = failed
        self.total = total
        self.download_folder = download_folder

        self.setWindowTitle("Download Queue Complete")
        self.setMinimumWidth(440)
        self.setModal(True)

        logo_file = get_logo_file()
        if logo_file.exists():
            self.setWindowIcon(QIcon(str(logo_file)))

        self._init_ui()

    def _init_ui(self) -> None:
        """Sets up the summary presentation layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header Title
        title_label = QLabel("🎉 Downloads Finished")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #0f172a;")
        layout.addWidget(title_label)

        # Statistics Card
        stats_group = QGroupBox("Batch Results")
        grid = QGridLayout(stats_group)
        grid.setContentsMargins(16, 16, 16, 14)
        grid.setSpacing(10)

        # Total
        grid.addWidget(QLabel("Total Videos in Queue:"), 0, 0)
        total_val = QLabel(str(self.total))
        total_val.setStyleSheet("font-weight: bold; color: #1e293b;")
        grid.addWidget(total_val, 0, 1)

        # Completed
        grid.addWidget(QLabel("Successfully Downloaded:"), 1, 0)
        comp_val = QLabel(str(self.completed))
        comp_val.setStyleSheet("font-weight: bold; color: #16a34a;")
        grid.addWidget(comp_val, 1, 1)

        # Skipped
        grid.addWidget(QLabel("Skipped (Already Exists):"), 2, 0)
        skip_val = QLabel(str(self.skipped))
        skip_val.setStyleSheet("font-weight: bold; color: #64748b;")
        grid.addWidget(skip_val, 2, 1)

        # Failed
        grid.addWidget(QLabel("Failed:"), 3, 0)
        fail_val = QLabel(str(self.failed))
        fail_val.setStyleSheet("font-weight: bold; color: #dc2626;" if self.failed > 0 else "color: #64748b;")
        grid.addWidget(fail_val, 3, 1)

        layout.addWidget(stats_group)

        # Destination Folder Info
        folder_info = QLabel(f"<b>Destination:</b><br>{self.download_folder}")
        folder_info.setWordWrap(True)
        folder_info.setStyleSheet("color: #475569; font-size: 12px; padding: 4px;")
        layout.addWidget(folder_info)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.open_folder_btn = QPushButton("📁 Open Download Folder")
        self.open_folder_btn.setObjectName("primaryButton")
        self.open_folder_btn.setMinimumHeight(34)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_layout.addWidget(self.open_folder_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("secondaryButton")
        self.close_btn.setMinimumHeight(34)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _on_open_folder(self) -> None:
        """Opens the download destination in Windows File Explorer."""
        folder_path = Path(self.download_folder)
        if not folder_path.exists():
            QMessageBox.warning(
                self,
                "Folder Not Found",
                f"The directory does not exist yet:\n{self.download_folder}",
            )
            return

        try:
            os.startfile(str(folder_path))
        except Exception as e:
            QMessageBox.warning(
                self,
                "Error",
                f"Could not open directory:\n{str(e)}",
            )
