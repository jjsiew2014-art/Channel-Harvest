"""
video_table.py
Video list table widget for displaying channel videos with:
- Checkbox selection
- Index (#)
- Video title
- Duration
- Real-time download status (Waiting, Downloading, Processing, Completed, Skipped, Failed, Cancelled)
- Real-time search filter by title or video ID
- Right-click context menu (Copy Title, Copy URL, Copy ID, Open in Browser)
"""

from typing import List, Optional
from PySide6.QtCore import Qt, Signal, QUrl, QPoint
from PySide6.QtGui import QColor, QFont, QAction, QGuiApplication, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QLabel,
    QPushButton,
    QLineEdit,
    QMenu,
)
from core.models import VideoItem, VideoStatus


class VideoTableWidget(QWidget):
    """
    Table widget displaying scanned videos with selection checkboxes,
    index numbers, titles, durations, and download status.

    Signals:
        selection_changed (int, int): Emitted when selection count changes (selected_count, total_count).
    """

    selection_changed = Signal(int, int)

    # Column index constants
    COL_SELECT = 0
    COL_INDEX = 1
    COL_TITLE = 2
    COL_DURATION = 3
    COL_VIDEO_ID = 4  # Kept in table data for internal lookups, hidden from default view
    COL_STATUS = 5

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._videos: List[VideoItem] = []
        self._init_ui()

    def _init_ui(self) -> None:
        """Sets up the layout, search bar, and table components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. Top Metadata Bar: Left "X videos found" | Right "Y selected"
        meta_bar = QHBoxLayout()
        meta_bar.setContentsMargins(2, 0, 2, 0)
        meta_bar.setSpacing(8)

        self.found_label = QLabel("0 videos found")
        self.found_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        meta_bar.addWidget(self.found_label)

        meta_bar.addStretch()

        self.selected_label = QLabel("0 selected")
        self.selected_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        meta_bar.addWidget(self.selected_label)

        layout.addLayout(meta_bar)

        # 2. Action Control Bar: [Select All] [Deselect All] [Clear List] ... [Search videos]
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(2, 0, 2, 0)
        action_bar.setSpacing(8)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setObjectName("secondaryButton")
        self.select_all_btn.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        self.select_all_btn.clicked.connect(lambda: self.select_all(True))
        action_bar.addWidget(self.select_all_btn)

        self.deselect_btn = QPushButton("Deselect All")
        self.deselect_btn.setObjectName("secondaryButton")
        self.deselect_btn.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        self.deselect_btn.clicked.connect(lambda: self.select_all(False))
        action_bar.addWidget(self.deselect_btn)

        self.clear_btn = QPushButton("Clear List")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.setStyleSheet("font-size: 11px; padding: 4px 10px;")
        self.clear_btn.setToolTip("Clear all videos from the table")
        self.clear_btn.clicked.connect(self.clear_table)
        action_bar.addWidget(self.clear_btn)

        action_bar.addStretch()

        # Real-time search filter field
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchBox")
        self.search_input.setPlaceholderText("🔍 Search videos...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        action_bar.addWidget(self.search_input)

        layout.addLayout(action_bar)

        # 3. Table Widget configuration
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "#", "Video Title", "Duration", "Video ID", "Status"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)

        # Hide developer-level Video ID column by default
        self.table.setColumnHidden(self.COL_VIDEO_ID, True)

        # Column sizing behavior
        header = self.table.horizontalHeader()

        # Selection Checkbox
        header.setSectionResizeMode(self.COL_SELECT, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_SELECT, 36)

        # Index (#)
        header.setSectionResizeMode(self.COL_INDEX, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_INDEX, 44)

        # Video Title (stretches to fill remaining space)
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)

        # Duration
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_DURATION, 75)

        # Video ID (hidden, 0 width)
        header.setSectionResizeMode(self.COL_VIDEO_ID, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_VIDEO_ID, 0)

        # Status
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_STATUS, 120)

        # Flexible minimum height for smooth resizing
        self.table.setMinimumHeight(120)

        # Context Menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # Prevent accidental actions on double click
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

    def load_videos(self, videos: List[VideoItem]) -> None:
        """Populates the table with scanned VideoItem objects."""
        self.table.blockSignals(True)
        self._videos = videos
        self.table.setRowCount(len(videos))

        mono_font = QFont("Consolas", 10)

        for row, video in enumerate(videos):
            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked if video.selected else Qt.CheckState.Unchecked)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_item.setData(Qt.ItemDataRole.UserRole, video.video_id)
            self.table.setItem(row, self.COL_SELECT, chk_item)

            # Col 1: Index (#)
            idx_item = QTableWidgetItem(str(video.index))
            idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, self.COL_INDEX, idx_item)

            # Col 2: Video Title
            title_item = QTableWidgetItem(video.title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            title_item.setToolTip(f"{video.title}\nID: {video.video_id}\nURL: {video.url}")
            self.table.setItem(row, self.COL_TITLE, title_item)

            # Col 3: Duration
            dur_item = QTableWidgetItem(video.duration)
            dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, self.COL_DURATION, dur_item)

            # Col 4: Video ID (stored internally, column is hidden)
            id_item = QTableWidgetItem(video.video_id)
            id_item.setFont(mono_font)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setToolTip(f"YouTube ID: {video.video_id}")
            self.table.setItem(row, self.COL_VIDEO_ID, id_item)

            # Col 5: Status
            status_item = QTableWidgetItem(video.status)
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_status_styling(status_item, video.status)
            self.table.setItem(row, self.COL_STATUS, status_item)

        self.table.blockSignals(False)

        # Apply active search query if any
        if self.search_input.text().strip():
            self._on_search_changed(self.search_input.text())
        else:
            self._update_counts()

    def get_selected_videos(self) -> List[VideoItem]:
        """Returns the list of VideoItem instances that are currently checked."""
        selected_ids = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_SELECT)
            if item and item.checkState() == Qt.CheckState.Checked:
                video_id = item.data(Qt.ItemDataRole.UserRole)
                selected_ids.add(video_id)

        selected_videos = []
        for vid in self._videos:
            if vid.video_id in selected_ids:
                vid.selected = True
                selected_videos.append(vid)
            else:
                vid.selected = False

        return selected_videos

    def update_video_status(self, video_id: str, new_status: str, error_msg: str = "") -> None:
        """Updates the status column and tooltip for a specific video row."""
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if chk_item and chk_item.data(Qt.ItemDataRole.UserRole) == video_id:
                status_item = self.table.item(row, self.COL_STATUS)
                if status_item:
                    status_item.setText(new_status)
                    if error_msg:
                        status_item.setToolTip(f"Reason: {error_msg}")
                    self._apply_status_styling(status_item, new_status)
                for vid in self._videos:
                    if vid.video_id == video_id:
                        vid.status = new_status
                        vid.error_reason = error_msg
                break

    def set_queue_waiting(self, video_ids: List[str]) -> None:
        """Marks selected videos as Waiting prior to queue start."""
        id_set = set(video_ids)
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if chk_item and chk_item.data(Qt.ItemDataRole.UserRole) in id_set:
                status_item = self.table.item(row, self.COL_STATUS)
                if status_item:
                    status_item.setText(VideoStatus.WAITING)
                    self._apply_status_styling(status_item, VideoStatus.WAITING)

    def select_all(self, checked: bool) -> None:
        """Selects or deselects all video rows (or visible filtered rows if search active)."""
        self.table.blockSignals(True)
        target_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            # If search filter is active, only toggle visible rows
            if not self.table.isRowHidden(row):
                item = self.table.item(row, self.COL_SELECT)
                if item:
                    item.setCheckState(target_state)
        self.table.blockSignals(False)
        self._update_counts()

    def clear_table(self) -> None:
        """Clears all video rows from the table."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._videos.clear()
        self.search_input.clear()
        self.table.blockSignals(False)
        self._update_counts()

    def _on_search_changed(self, text: str) -> None:
        """Filters table rows in real-time by video title or video ID."""
        query = text.strip().lower()
        visible_count = 0
        total_rows = self.table.rowCount()

        for row in range(total_rows):
            title_item = self.table.item(row, self.COL_TITLE)
            id_item = self.table.item(row, self.COL_VIDEO_ID)
            title = title_item.text().lower() if title_item else ""
            vid_id = id_item.text().lower() if id_item else ""

            if not query or query in title or query in vid_id:
                self.table.setRowHidden(row, False)
                visible_count += 1
            else:
                self.table.setRowHidden(row, True)

        self._update_counts()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Triggered when an individual item/checkbox state is toggled."""
        if item.column() == self.COL_SELECT:
            self._update_counts()

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        """Safely handles double-click to prevent triggering accidental downloads."""
        # Double-clicking safely copies the video URL to clipboard
        chk_item = self.table.item(row, self.COL_SELECT)
        if chk_item:
            video_id = chk_item.data(Qt.ItemDataRole.UserRole)
            url = f"https://www.youtube.com/watch?v={video_id}"
            QGuiApplication.clipboard().setText(url)

    def _show_context_menu(self, pos: QPoint) -> None:
        """Displays right-click context menu for selected video row."""
        item = self.table.itemAt(pos)
        if not item:
            return

        row = item.row()
        title_item = self.table.item(row, self.COL_TITLE)
        id_item = self.table.item(row, self.COL_VIDEO_ID)
        video_title = title_item.text() if title_item else ""
        video_id = id_item.text() if id_item else ""
        video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

        menu = QMenu(self)

        copy_title_act = QAction("Copy Video Title", self)
        copy_title_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_title))
        menu.addAction(copy_title_act)

        copy_url_act = QAction("Copy Video URL", self)
        copy_url_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_url))
        menu.addAction(copy_url_act)

        copy_id_act = QAction("Copy Video ID", self)
        copy_id_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_id))
        menu.addAction(copy_id_act)

        menu.addSeparator()

        open_browser_act = QAction("Open in Browser", self)
        open_browser_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(video_url)))
        menu.addAction(open_browser_act)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _update_counts(self) -> None:
        """Recalculates selected vs total counts and updates display labels."""
        total = len(self._videos)
        selected = 0
        visible = 0

        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                visible += 1
            item = self.table.item(row, self.COL_SELECT)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected += 1

        query = self.search_input.text().strip()
        if query and total > 0:
            self.found_label.setText(f"{visible:,} of {total:,} videos found")
        elif total == 1:
            self.found_label.setText("1 video found")
        else:
            self.found_label.setText(f"{total:,} videos found")

        self.selected_label.setText(f"{selected:,} selected")
        self.selection_changed.emit(selected, total)

    @staticmethod
    def _apply_status_styling(item: QTableWidgetItem, status: str) -> None:
        """Applies clean semantic colors to different status states."""
        font = QFont()
        if status == VideoStatus.DOWNLOADING:
            item.setForeground(QColor("#0284c7"))  # Sky blue
            font.setBold(True)
        elif status == VideoStatus.PROCESSING:
            item.setForeground(QColor("#6366f1"))  # Indigo
            font.setBold(True)
        elif status == VideoStatus.COMPLETED:
            item.setForeground(QColor("#16a34a"))  # Green
            font.setBold(True)
        elif status == VideoStatus.SKIPPED:
            item.setForeground(QColor("#64748b"))  # Muted slate
            font.setItalic(True)
        elif status == VideoStatus.WAITING:
            item.setForeground(QColor("#94a3b8"))  # Light slate
            font.setBold(False)
        elif status == VideoStatus.CANCELLED:
            item.setForeground(QColor("#9ca3af"))  # Muted gray
            font.setItalic(True)
        elif "Retry" in status:
            item.setForeground(QColor("#d97706"))  # Amber
            font.setItalic(True)
        elif status in (VideoStatus.FAILED, "Error"):
            item.setForeground(QColor("#dc2626"))  # Red
            font.setBold(True)
        elif "Private" in status or "Unavailable" in status:
            item.setForeground(QColor("#94a3b8"))
            font.setItalic(True)
        else:
            item.setForeground(QColor("#475569"))
            font.setBold(False)
        item.setFont(font)

