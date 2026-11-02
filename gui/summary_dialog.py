"""
summary_dialog.py
Completion summary modal dialog for Channel Harvest.

Displays overall batch statistics (Total, Completed, Skipped, Failed)
and provides a one-click button to open the download folder in Windows Explorer.
"""

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QMessageBox,
    QFrame,
)
from core.paths import get_logo_file
from core.i18n import I18nManager, tr


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
        skipped_private: int = 0,
        skipped_unavailable: int = 0,
        skipped_existing: int = 0,
        skipped_media: Optional[int] = None,
        cancelled: int = 0,
        is_cancelled: bool = False,
        lyrics_not_found: int = 0,
        lyrics_enabled: bool = False,
        download_lrc_enabled: bool = False,
        embed_lyrics_enabled: bool = False,
        parent: Optional[QDialog] = None,
    ):
        super().__init__(parent)
        try:
            self.completed = int(completed)
        except Exception:
            self.completed = 0
        try:
            self.skipped = int(skipped)
        except Exception:
            self.skipped = 0
        try:
            self.failed = int(failed)
        except Exception:
            self.failed = 0
        try:
            self.total = int(total)
        except Exception:
            self.total = 0
        self.download_folder = (download_folder or "").strip(" \"'")
        try:
            self.skipped_private = int(skipped_private)
        except Exception:
            self.skipped_private = 0
        try:
            self.skipped_unavailable = int(skipped_unavailable)
        except Exception:
            self.skipped_unavailable = 0
        try:
            self.skipped_existing = int(skipped_existing)
        except Exception:
            self.skipped_existing = 0
        try:
            self.skipped_media = int((self.skipped_private + self.skipped_unavailable) if skipped_media is None else skipped_media)
        except Exception:
            self.skipped_media = self.skipped_private + self.skipped_unavailable
        try:
            self.cancelled = int(cancelled)
        except Exception:
            self.cancelled = 0
        self.is_cancelled = bool(is_cancelled) or (self.cancelled > 0)
        try:
            self.lyrics_not_found = int(lyrics_not_found)
        except Exception:
            self.lyrics_not_found = 0
        self.lyrics_enabled = bool(lyrics_enabled)
        self.download_lrc_enabled = bool(download_lrc_enabled)
        self.embed_lyrics_enabled = bool(embed_lyrics_enabled)

        window_title = tr("summary_window_title_cancelled") if self.is_cancelled else tr("summary_window_title")
        self.setWindowTitle(window_title)
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

        # Header Title (Main Heading Format & Size)
        header_text = tr("summary_header_title_cancelled") if self.is_cancelled else tr("summary_header_title")
        title_label = QLabel(header_text)
        title_label.setObjectName("summaryTitleLabel")
        title_font = title_label.font()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Statistics Card
        stats_group = QGroupBox(tr("summary_batch_results"))
        grid = QGridLayout(stats_group)
        grid.setContentsMargins(16, 16, 16, 14)
        grid.setSpacing(10)

        row = 0
        # Total
        grid.addWidget(QLabel(tr("summary_total")), row, 0)
        total_val = QLabel(str(self.total))
        total_val.setObjectName("summaryTotalVal")
        grid.addWidget(total_val, row, 1)
        row += 1

        # Downloaded
        grid.addWidget(QLabel(tr("summary_completed")), row, 0)
        comp_val = QLabel(str(self.completed))
        comp_val.setObjectName("summaryCompletedVal")
        grid.addWidget(comp_val, row, 1)
        row += 1

        # Skipped Media (consolidating Private & Unavailable Video)
        grid.addWidget(QLabel(tr("summary_skipped_media")), row, 0)
        skip_media_val = QLabel(str(self.skipped_media))
        skip_media_val.setObjectName("summarySkippedVal")
        grid.addWidget(skip_media_val, row, 1)
        row += 1

        # Skipped (Already Exists) — if any existing/other skipped
        other_skipped = self.skipped_existing
        if other_skipped == 0 and self.skipped > self.skipped_media:
            other_skipped = self.skipped - self.skipped_media
        if other_skipped > 0:
            grid.addWidget(QLabel(tr("summary_skipped")), row, 0)
            other_skip_val = QLabel(str(other_skipped))
            other_skip_val.setObjectName("summarySkippedVal")
            grid.addWidget(other_skip_val, row, 1)
            row += 1

        # Failed
        grid.addWidget(QLabel(tr("summary_failed")), row, 0)
        fail_val = QLabel(str(self.failed))
        fail_val.setObjectName("summaryFailedVal" if self.failed > 0 else "summarySkippedVal")
        grid.addWidget(fail_val, row, 1)
        row += 1

        # Cancelled
        if self.cancelled > 0 or self.is_cancelled:
            grid.addWidget(QLabel(tr("summary_cancelled")), row, 0)
            canc_val = QLabel(str(self.cancelled))
            canc_val.setObjectName("summaryFailedVal" if self.cancelled > 0 else "summarySkippedVal")
            grid.addWidget(canc_val, row, 1)
            row += 1

        # Lyrics Not Found (when lyrics options were enabled and lyrics were missing)
        if self.lyrics_enabled and self.lyrics_not_found > 0:
            grid.addWidget(QLabel(tr("summary_lyrics_not_found")), row, 0)
            lyrics_val = QLabel(str(self.lyrics_not_found))
            lyrics_val.setObjectName("summaryLyricsVal")
            grid.addWidget(lyrics_val, row, 1)
            row += 1

        layout.addWidget(stats_group)

        # Notice box if lyrics options were selected but lyrics could not be found
        if self.lyrics_enabled and self.lyrics_not_found > 0:
            self.lyrics_notice_box = QFrame()
            self.lyrics_notice_box.setObjectName("summaryLyricsNoticeBox")
            notice_layout = QHBoxLayout(self.lyrics_notice_box)
            notice_layout.setContentsMargins(12, 10, 12, 10)
            notice_layout.setSpacing(10)

            icon_lbl = QLabel()
            svg = """<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="8" x2="12" y2="12"></line>
              <line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>"""
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            pix = QPixmap(20, 20)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            icon_lbl.setPixmap(pix)
            icon_lbl.setFixedSize(20, 20)
            notice_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignTop)

            if self.download_lrc_enabled and self.embed_lyrics_enabled:
                msg_key = "summary_lyrics_not_found_both"
            elif self.download_lrc_enabled:
                msg_key = "summary_lyrics_not_found_download"
            else:
                msg_key = "summary_lyrics_not_found_embed"

            self.lyrics_notice_lbl = QLabel(tr(msg_key, count=self.lyrics_not_found))
            self.lyrics_notice_lbl.setObjectName("summaryLyricsNoticeText")
            self.lyrics_notice_lbl.setWordWrap(True)
            notice_layout.addWidget(self.lyrics_notice_lbl, 1)

            layout.addWidget(self.lyrics_notice_box)

        # Destination Folder Info
        folder_info = QLabel(f"<b>{tr('summary_destination')}</b><br>{self.download_folder}")
        folder_info.setWordWrap(True)
        folder_info.setObjectName("summaryFolderInfo")
        layout.addWidget(folder_info)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.open_folder_btn = QPushButton(tr("summary_open_folder"))
        self.open_folder_btn.setObjectName("primaryButton")
        self.open_folder_btn.setMinimumHeight(34)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_layout.addWidget(self.open_folder_btn)

        self.close_btn = QPushButton(tr("close"))
        self.close_btn.setObjectName("secondaryButton")
        self.close_btn.setMinimumHeight(34)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _on_open_folder(self) -> None:
        """Opens the download destination in Windows File Explorer."""
        raw_path = (self.download_folder or "").strip(' "\'')
        folder_path = Path(raw_path) if raw_path else (Path.home() / "Downloads")

        if not folder_path.exists():
            # Defensive check: if the subfolder does not exist, fall back to its parent directory
            if folder_path.parent and folder_path.parent.exists():
                folder_path = folder_path.parent
            else:
                QMessageBox.warning(
                    self,
                    tr("dialog_folder_not_found_title"),
                    tr("dialog_folder_not_found_msg", folder=str(folder_path)),
                )
                return

        try:
            os.startfile(str(folder_path.resolve()))
        except Exception as e:
            QMessageBox.warning(
                self,
                tr("error"),
                tr("could_not_open_dir_fmt", error=str(e)),
            )
