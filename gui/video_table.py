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
    QStackedWidget,
)
from core.models import VideoItem, VideoStatus
from core.i18n import I18nManager, tr


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
    COL_SUBTITLE = 4
    COL_VIDEO_ID = 5  # Kept in table data for internal lookups, hidden from default view
    COL_STATUS = 6


    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._videos: List[VideoItem] = []
        self._init_ui()
        I18nManager.register_listener(self._on_language_updated)

    def _init_ui(self) -> None:
        """Sets up the layout, search bar, and table components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Unified High-Efficiency Action Toolbar (Single Horizontal Row)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 0, 2, 2)
        toolbar.setSpacing(8)

        # Counter: "0 videos found • 0 selected"
        self.found_label = QLabel("0 videos found")
        self.found_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        toolbar.addWidget(self.found_label)

        sep_dot = QLabel("•")
        sep_dot.setStyleSheet("color: #64748b; font-size: 12px; font-weight: bold;")
        toolbar.addWidget(sep_dot)

        self.selected_label = QLabel("0 selected")
        self.selected_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #0284c7;")
        toolbar.addWidget(self.selected_label)

        toolbar.addSpacing(10)

        # Action Buttons
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setObjectName("secondaryButton")
        self.select_all_btn.setMinimumHeight(28)
        self.select_all_btn.setStyleSheet("font-size: 12px; padding: 3px 10px;")
        self.select_all_btn.clicked.connect(lambda: self.select_all(True))
        toolbar.addWidget(self.select_all_btn)

        self.deselect_btn = QPushButton("Deselect All")
        self.deselect_btn.setObjectName("secondaryButton")
        self.deselect_btn.setMinimumHeight(28)
        self.deselect_btn.setStyleSheet("font-size: 12px; padding: 3px 10px;")
        self.deselect_btn.clicked.connect(lambda: self.select_all(False))
        toolbar.addWidget(self.deselect_btn)

        self.clear_btn = QPushButton("Clear List")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.setMinimumHeight(28)
        self.clear_btn.setStyleSheet("font-size: 12px; padding: 3px 10px;")
        self.clear_btn.setToolTip("Clear all videos from the table")
        self.clear_btn.clicked.connect(self.clear_table)
        toolbar.addWidget(self.clear_btn)

        toolbar.addStretch(1)

        # Real-time search filter field on the right
        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchBox")
        self.search_input.setPlaceholderText("🔍 Search videos...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(28)
        self.search_input.setMinimumWidth(220)
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_input)

        layout.addLayout(toolbar)

        # 2. View Stack: Empty State vs. Table Widget
        self.view_stack = QStackedWidget()

        # Empty State
        self.empty_widget = QWidget()
        self.empty_widget.setObjectName("emptyStateWidget")
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(6)
        empty_layout.setContentsMargins(20, 16, 20, 16)

        self.empty_title = QLabel("No videos available")
        self.empty_title.setObjectName("emptyStateTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_subtitle = QLabel("Scan a YouTube channel or playlist to load videos.")
        self.empty_subtitle.setObjectName("emptyStateSubtitle")
        self.empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_subtitle)

        # Table Widget configuration
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["", "#", "Video Title", "Duration", "Subtitle", "Video ID", "Status"])
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

        # Index (#) - comfortably accommodates up to 4-digit numbers (e.g. 9999)
        header.setSectionResizeMode(self.COL_INDEX, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_INDEX, 58)

        # Video Title (stretches to fill remaining space)
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)

        # Duration
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_DURATION, 80)

        # Subtitle (comfortable width for multi-language tags)
        header.setSectionResizeMode(self.COL_SUBTITLE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_SUBTITLE, 150)

        # Video ID (hidden, 0 width)
        header.setSectionResizeMode(self.COL_VIDEO_ID, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_VIDEO_ID, 0)

        # Status
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_STATUS, 180)

        # Flexible minimum height for primary workspace (allows compact startup, expands with window)
        self.table.setMinimumHeight(150)

        # Context Menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # Prevent accidental actions on double click
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.table.itemChanged.connect(self._on_item_changed)

        self.view_stack.addWidget(self.empty_widget)
        self.view_stack.addWidget(self.table)
        self.view_stack.setCurrentWidget(self.empty_widget)

        layout.addWidget(self.view_stack)

        self.retranslate_ui()

    def load_videos(self, videos: List[VideoItem]) -> None:
        """Populates the table with scanned VideoItem objects."""
        self.table.blockSignals(True)
        self._videos = list(videos)
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
            title_item.setToolTip(f"{video.title}\n{tr('video_id_prefix', id=video.video_id)}\n{tr('url_prefix', url=video.url)}")
            self.table.setItem(row, self.COL_TITLE, title_item)

            # Col 3: Duration
            dur_item = QTableWidgetItem(video.duration)
            dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, self.COL_DURATION, dur_item)

            # Col 4: Subtitle
            sub_raw = getattr(video, "subtitle_status", tr("subtitle_checking")) or tr("subtitle_checking")
            sub_item = QTableWidgetItem(self._localize_sub_status(sub_raw))
            sub_item.setData(Qt.ItemDataRole.UserRole, sub_raw)
            sub_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_subtitle_styling(sub_item, sub_raw)
            self.table.setItem(row, self.COL_SUBTITLE, sub_item)

            # Col 5: Video ID (stored internally, column is hidden)
            id_item = QTableWidgetItem(video.video_id)
            id_item.setFont(mono_font)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setToolTip(tr("youtube_id_prefix", id=video.video_id))
            self.table.setItem(row, self.COL_VIDEO_ID, id_item)

            # Col 6: Status
            status_item = QTableWidgetItem(I18nManager.get_status_label(video.status))
            status_item.setData(Qt.ItemDataRole.UserRole, video.status)
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._apply_status_styling(status_item, video.status)
            self.table.setItem(row, self.COL_STATUS, status_item)

        self.table.blockSignals(False)

        if videos:
            self.view_stack.setCurrentWidget(self.table)
        else:
            self.view_stack.setCurrentWidget(self.empty_widget)

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

    def update_video_status(self, video_id: str, new_status: str, error_msg: str = "", error_details: Optional[Any] = None) -> None:
        """Updates the status column and tooltip for a specific video row."""
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if chk_item and chk_item.data(Qt.ItemDataRole.UserRole) == video_id:
                # Find matching video model
                matched_vid = None
                for vid in self._videos:
                    if vid.video_id == video_id:
                        vid.status = new_status
                        if error_msg:
                            vid.error_reason = error_msg
                        if error_details is not None:
                            vid.error_details = error_details
                        matched_vid = vid
                        break

                status_item = self.table.item(row, self.COL_STATUS)
                if status_item:
                    status_item.setData(Qt.ItemDataRole.UserRole, new_status)
                    status_item.setText(I18nManager.get_status_label(new_status))

                    err_det = (matched_vid.error_details if matched_vid else None) or error_details
                    if err_det:
                        reason_hdr = tr("tooltip_reason_label")
                        action_hdr = tr("tooltip_action_label")
                        hint = tr("tooltip_details_hint")
                        tooltip = f"{err_det.title}\n\n{reason_hdr}\n{err_det.get_localized_user_message()}\n\n{action_hdr}\n{err_det.get_localized_suggested_action()}\n\n{hint}"
                        status_item.setToolTip(tooltip)
                    elif error_msg:
                        status_item.setToolTip(f"{tr('tooltip_reason_label')} {error_msg}")
                    else:
                        status_item.setToolTip("")

                    self._apply_status_styling(status_item, new_status)
                break

    def update_video_subtitle_status(self, video_id: str, new_subtitle_status: str, tooltip: str = "") -> None:
        """Updates the subtitle column and styling for a specific video row."""
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if chk_item and chk_item.data(Qt.ItemDataRole.UserRole) == video_id:
                sub_item = self.table.item(row, self.COL_SUBTITLE)
                if sub_item:
                    sub_item.setData(Qt.ItemDataRole.UserRole, new_subtitle_status)
                    sub_item.setText(self._localize_sub_status(new_subtitle_status))
                    if tooltip:
                        sub_item.setToolTip(tooltip)
                    self._apply_subtitle_styling(sub_item, new_subtitle_status)
                for vid in self._videos:
                    if vid.video_id == video_id:
                        vid.subtitle_status = new_subtitle_status
                break

    def set_queue_waiting(self, video_ids: List[str]) -> None:
        """Marks selected videos as Waiting prior to queue start."""
        id_set = set(video_ids)
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if chk_item and chk_item.data(Qt.ItemDataRole.UserRole) in id_set:
                status_item = self.table.item(row, self.COL_STATUS)
                if status_item:
                    status_item.setData(Qt.ItemDataRole.UserRole, VideoStatus.WAITING)
                    status_item.setText(I18nManager.get_status_label(VideoStatus.WAITING))
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
        self.view_stack.setCurrentWidget(self.empty_widget)

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
        """Safely handles double-click: opens error details dialog if failed; otherwise copies URL."""
        chk_item = self.table.item(row, self.COL_SELECT)
        if not chk_item:
            return
        video_id = chk_item.data(Qt.ItemDataRole.UserRole)
        vid_match = next((v for v in self._videos if v.video_id == video_id), None)
        if vid_match:
            is_failed = (
                vid_match.error_details is not None
                or "fail" in (vid_match.status or "").lower()
                or "失败" in (vid_match.status or "")
                or "error" in (vid_match.status or "").lower()
            )
            if is_failed:
                self._open_error_details_for_video(vid_match)
                return

        url = f"https://www.youtube.com/watch?v={video_id}"
        QGuiApplication.clipboard().setText(url)

    def _open_error_details_for_video(self, video: VideoItem) -> None:
        """Opens the rich error details modal dialog for the given video."""
        from gui.error_details_dialog import ErrorDetailsDialog
        from core.error_classifier import ErrorClassifier

        err = video.error_details
        if err is None:
            err = ErrorClassifier.classify(
                raw_error=video.error_reason or tr("download_failed_fallback"),
                video_id=video.video_id,
                video_title=video.title,
            )
        dialog = ErrorDetailsDialog(error=err, parent=self.window())
        dialog.exec()

    def _copy_error_details_for_video(self, video: VideoItem) -> None:
        """Copies the sanitized error report for the given video to the clipboard."""
        from core.error_classifier import ErrorClassifier

        err = video.error_details
        if err is None:
            err = ErrorClassifier.classify(
                raw_error=video.error_reason or tr("download_failed_fallback"),
                video_id=video.video_id,
                video_title=video.title,
            )
        runtime_info = {}
        try:
            from downloader.updater import YtDlpUpdater
            runtime_info["yt-dlp"] = YtDlpUpdater.get_installed_version()
        except Exception:
            pass
        try:
            import yt_dlp_ejs
            runtime_info["ejs"] = getattr(yt_dlp_ejs, "__version__", getattr(yt_dlp_ejs, "version", "Installed"))
        except Exception:
            pass
        try:
            from downloader.deno_checker import DenoChecker
            is_ok, _, ver, _ = DenoChecker.detect()
            if is_ok:
                runtime_info["deno"] = ver
        except Exception:
            pass
        try:
            from downloader.ffmpeg_checker import FFmpegChecker
            is_ok, _, ver, _ = FFmpegChecker.detect()
            if is_ok:
                runtime_info["ffmpeg"] = ver
        except Exception:
            pass

        report_text = err.to_report(runtime_info=runtime_info)
        QGuiApplication.clipboard().setText(report_text)

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

        copy_title_act = QAction(tr("ctx_copy_title"), self)
        copy_title_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_title))
        menu.addAction(copy_title_act)

        copy_url_act = QAction(tr("ctx_copy_url"), self)
        copy_url_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_url))
        menu.addAction(copy_url_act)

        copy_id_act = QAction(tr("ctx_copy_id"), self)
        copy_id_act.triggered.connect(lambda: QGuiApplication.clipboard().setText(video_id))
        menu.addAction(copy_id_act)

        menu.addSeparator()

        open_browser_act = QAction(tr("ctx_open_browser"), self)
        open_browser_act.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(video_url)))
        menu.addAction(open_browser_act)

        vid_match = next((v for v in self._videos if v.video_id == video_id), None)
        if vid_match:
            is_failed = (
                vid_match.error_details is not None
                or "fail" in (vid_match.status or "").lower()
                or "失败" in (vid_match.status or "")
                or "error" in (vid_match.status or "").lower()
            )
            if is_failed:
                menu.addSeparator()
                view_err_act = QAction(tr("ctx_view_error_details"), self)
                view_err_act.triggered.connect(lambda: self._open_error_details_for_video(vid_match))
                menu.addAction(view_err_act)

                copy_err_act = QAction(tr("ctx_copy_error_details"), self)
                copy_err_act.triggered.connect(lambda: self._copy_error_details_for_video(vid_match))
                menu.addAction(copy_err_act)

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
            self.found_label.setText(tr("videos_found_filter_fmt", visible=f"{visible:,}", total=f"{total:,}"))
        elif total == 1:
            self.found_label.setText(tr("one_video_found"))
        else:
            self.found_label.setText(tr("videos_found_fmt", found=f"{total:,}"))

        self.selected_label.setText(tr("videos_selected_fmt", selected=f"{selected:,}"))
        self.selection_changed.emit(selected, total)

    @staticmethod
    def _localize_sub_status(raw_status: str) -> str:
        """Translates basic subtitle status strings for localized display."""
        if raw_status == "Yes":
            return tr("subtitle_yes")
        elif raw_status == "No":
            return tr("subtitle_no")
        elif raw_status == "Checking...":
            return tr("subtitle_checking")
        return raw_status

    def _on_language_updated(self, lang_code: str) -> None:
        """Listener invoked when application language changes dynamically."""
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Retranslates all text elements in the video table widget."""
        # Headers
        self.table.setHorizontalHeaderLabels([
            tr("header_select"),
            tr("header_index"),
            tr("header_title"),
            tr("header_duration"),
            tr("header_subtitle"),
            tr("header_video_id"),
            tr("header_status"),
        ])

        # Action Buttons & placeholders
        self.select_all_btn.setText(tr("select_all"))
        self.deselect_btn.setText(tr("deselect_all"))
        self.clear_btn.setText(tr("clear_list"))
        self.clear_btn.setToolTip(tr("clear_list_tooltip"))
        self.search_input.setPlaceholderText(tr("search_placeholder"))

        # Empty state
        self.empty_title.setText(tr("empty_title"))
        self.empty_subtitle.setText(tr("empty_subtitle"))

        # Counts
        self._update_counts()

        # Existing table items
        for row in range(self.table.rowCount()):
            # Subtitle
            sub_item = self.table.item(row, self.COL_SUBTITLE)
            if sub_item:
                raw_sub = sub_item.data(Qt.ItemDataRole.UserRole) or sub_item.text()
                sub_item.setText(self._localize_sub_status(raw_sub))

            # Status
            status_item = self.table.item(row, self.COL_STATUS)
            if status_item:
                raw_status = status_item.data(Qt.ItemDataRole.UserRole) or status_item.text()
                status_item.setText(I18nManager.get_status_label(raw_status))

    @staticmethod
    def _apply_status_styling(item: QTableWidgetItem, status: str) -> None:
        """Applies clean semantic colors to different status states."""
        font = QFont()
        st_lower = (status or "").lower()
        if status == VideoStatus.DOWNLOADING or "downloading" in st_lower or "下载中" in status:
            item.setForeground(QColor("#0284c7"))  # Sky blue
            font.setBold(True)
        elif status == VideoStatus.PROCESSING or "processing" in st_lower or "处理中" in status:
            item.setForeground(QColor("#6366f1"))  # Indigo
            font.setBold(True)
        elif status == VideoStatus.COMPLETED or "complete" in st_lower or "已完成" in status:
            item.setForeground(QColor("#16a34a"))  # Green
            font.setBold(True)
        elif status == VideoStatus.SKIPPED or "skip" in st_lower or "已跳过" in status:
            item.setForeground(QColor("#64748b"))  # Muted slate
            font.setItalic(True)
        elif status == VideoStatus.WAITING or "wait" in st_lower or "等待中" in status:
            item.setForeground(QColor("#94a3b8"))  # Light slate
            font.setBold(False)
        elif status == VideoStatus.CANCELLED or "cancel" in st_lower or "已取消" in status:
            item.setForeground(QColor("#9ca3af"))  # Muted gray
            font.setItalic(True)
        elif "retry" in st_lower or "rate limit" in st_lower or "重试" in status or "限流" in status:
            item.setForeground(QColor("#d97706"))  # Amber
            font.setItalic(True)
        elif "fail" in st_lower or "失败" in status or status == VideoStatus.FAILED or "error" in st_lower:
            item.setForeground(QColor("#dc2626"))  # Red
            font.setBold(True)
        elif "private" in st_lower or "unavailable" in st_lower or "私享" in status or "不可用" in status:
            item.setForeground(QColor("#94a3b8"))
            font.setItalic(True)
        else:
            item.setForeground(QColor("#475569"))
            font.setBold(False)
        item.setFont(font)

    @staticmethod
    def _apply_subtitle_styling(item: QTableWidgetItem, status: str) -> None:
        """Applies clean semantic colors to subtitle status states."""
        font = QFont()
        st = status.lower() if status else ""
        if "complete" in st or "downloaded" in st or "saved" in st or "official" in st or "✓" in st:
            item.setForeground(QColor("#16a34a"))  # Green
            font.setBold(True)
        elif "auto" in st:
            item.setForeground(QColor("#6366f1"))  # Indigo
            font.setBold(True)
        elif "downloading" in st or "fetching" in st or "checking" in st or "detecting" in st:
            item.setForeground(QColor("#0284c7"))  # Sky blue
            font.setBold(True)
        elif "skip" in st:
            item.setForeground(QColor("#64748b"))  # Slate
            font.setItalic(True)
        elif "no sub" in st or "none" in st or "n/a" in st or st in ("-", "—"):
            item.setForeground(QColor("#94a3b8"))  # Light slate
            font.setItalic(True)
        elif "fail" in st or "error" in st:
            item.setForeground(QColor("#dc2626"))  # Red
            font.setBold(True)
        else:
            item.setForeground(QColor("#475569"))
            font.setBold(False)
        item.setFont(font)

