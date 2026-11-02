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


class _VideoTableInternal(QTableWidget):
    """Subclass of QTableWidget that prevents spacebar toggling of non-checkable items."""
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            row = self.currentRow()
            if row >= 0:
                item = self.item(row, VideoTableWidget.COL_SELECT)
                if item and not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    event.accept()
                    return
        super().keyPressEvent(event)


class _DurationTableWidgetItem(QTableWidgetItem):
    """Custom QTableWidgetItem for duration that sorts by numeric seconds."""
    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            v1 = self.data(Qt.ItemDataRole.UserRole)
            v2 = other.data(Qt.ItemDataRole.UserRole)
            if v1 is not None and v2 is not None:
                try:
                    return float(v1) < float(v2)
                except Exception:
                    pass
        return super().__lt__(other)

class VideoTableWidget(QWidget):
    """
    Table widget displaying scanned videos with selection checkboxes,
    index numbers, titles, durations, and download status.

    Signals:
        selection_changed (int, int): Emitted when selection count changes (selected_count, total_count).
    """

    selection_changed = Signal(int, int)
    table_cleared = Signal()

    # Column index constants
    COL_SELECT = 0
    COL_INDEX = 1
    COL_TITLE = 2
    COL_TYPE = 3
    COL_DURATION = 4
    COL_SUBTITLE = 5
    COL_VIDEO_ID = 6  # Kept in table data for internal lookups, hidden from default view
    COL_STATUS = 7


    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._videos: List[VideoItem] = []
        self._current_platform: str = "youtube"
        self._image_only_mode: bool = False
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
        self.found_label = QLabel("0 media found")
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

        self.empty_title = QLabel("No media available")
        self.empty_title.setObjectName("emptyStateTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_subtitle = QLabel("Scan a YouTube channel or playlist to load videos.")
        self.empty_subtitle.setObjectName("emptyStateSubtitle")
        self.empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_subtitle)

        # Table Widget configuration
        self.table = _VideoTableInternal()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["", "#", tr("header_media_title"), tr("header_media_type"), tr("header_duration"), tr("header_subtitles"), tr("header_media_id"), tr("header_status")])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)

        # Hide developer-level Media ID column by default
        self.table.setColumnHidden(self.COL_VIDEO_ID, True)

        # Column sizing behavior
        header = self.table.horizontalHeader()

        # Selection Checkbox
        header.setSectionResizeMode(self.COL_SELECT, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_SELECT, 36)

        # Index (#) - comfortably accommodates up to 4-digit numbers (e.g. 9999)
        header.setSectionResizeMode(self.COL_INDEX, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_INDEX, 58)

        # Media Title (stretches to fill remaining space)
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)

        # Media Type (Photo / Video / Reel / Unknown)
        header.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_TYPE, 90)

        # Duration
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_DURATION, 80)

        # Subtitle (comfortable width for multi-language tags)
        header.setSectionResizeMode(self.COL_SUBTITLE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_SUBTITLE, 150)

        # Media ID (hidden, 0 width)
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

    def set_platform(self, platform_id: str) -> None:
        """
        Configures table column visibility and layout based on active platform capabilities.
        Hides the Subtitle column on TikTok and stretches Video Title horizontally across reclaimed space.
        """
        self._current_platform = platform_id
        is_tiktok = (platform_id == "tiktok")
        is_douyin = (platform_id == "douyin")
        is_facebook = (platform_id == "facebook")
        is_instagram = (platform_id == "instagram")
        is_x = (platform_id == "x")
        self.set_subtitle_column_visible(not (is_tiktok or is_douyin or is_facebook or is_instagram or is_x))
        if hasattr(self, "empty_subtitle"):
            if is_douyin:
                self.empty_subtitle.setText(tr("empty_subtitle_douyin"))
            elif is_tiktok:
                self.empty_subtitle.setText(tr("empty_subtitle_tiktok"))
            elif is_facebook:
                self.empty_subtitle.setText(tr("empty_subtitle_facebook"))
            elif is_instagram:
                self.empty_subtitle.setText(tr("empty_subtitle_instagram"))
            elif is_x:
                self.empty_subtitle.setText(tr("empty_subtitle_x"))
            else:
                self.empty_subtitle.setText(tr("empty_subtitle"))

    @staticmethod
    def _apply_media_type_styling(item: QTableWidgetItem, media_type: str) -> None:
        """Applies clean semantic badges/colors to media types."""
        font = item.font()
        if font.pointSize() <= 0:
            font.setPointSize(9)
        m = (media_type or "").lower()
        if "photo" in m or "image" in m or "图片" in m or "相片" in m or "照片" in m:
            item.setForeground(QColor("#0284c7"))  # Sky blue
            font.setBold(True)
        elif "reel" in m:
            item.setForeground(QColor("#8b5cf6"))  # Violet / Purple
            font.setBold(True)
        elif "video" in m or "视频" in m or "影片" in m:
            item.setForeground(QColor("#0d9488"))  # Teal / Emerald
            font.setBold(True)
        else:
            item.setForeground(QColor("#64748b"))  # Slate
            font.setBold(False)
        item.setFont(font)

    @property
    def videos(self) -> List[VideoItem]:
        """Returns the current list of VideoItem instances."""
        return self._videos

    def get_selection_summary(self):
        """Computes centralized selection summary of the currently loaded and checked media items."""
        from core.models import SelectionSummary, MediaType
        selected = self.get_selected_videos()
        photo_c = sum(1 for v in selected if getattr(v, "media_type", MediaType.VIDEO) == MediaType.PHOTO)
        reel_c = sum(1 for v in selected if getattr(v, "media_type", MediaType.VIDEO) == MediaType.REEL)
        video_c = sum(1 for v in selected if getattr(v, "media_type", MediaType.VIDEO) == MediaType.VIDEO)
        unknown_c = len(selected) - (photo_c + reel_c + video_c)
        return SelectionSummary(
            total_count=len(self._videos),
            selected_count=len(selected),
            photo_count=photo_c,
            video_count=video_c,
            reel_count=reel_c,
            unknown_count=unknown_c,
        )

    def set_subtitle_column_visible(self, visible: bool) -> None:
        """
        Shows or hides the Subtitle column.
        When hidden (e.g. TikTok), Video Title automatically stretches across the reclaimed horizontal space.
        When shown (e.g. YouTube), Subtitle column is restored with fixed 150px width.
        """
        self.table.setColumnHidden(self.COL_SUBTITLE, not visible)
        header = self.table.horizontalHeader()
        if visible:
            header.setSectionResizeMode(self.COL_SUBTITLE, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(self.COL_SUBTITLE, 150)
        # Ensure Title column always stretches to fill all available horizontal space
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.ResizeMode.Stretch)

    def load_videos(self, videos: List[VideoItem]) -> None:
        """Populates the table with scanned VideoItem objects."""
        self.table.blockSignals(True)
        self._videos = list(videos)
        self.table.setRowCount(len(videos))

        mono_font = QFont("Consolas", 10)
        disabled_color = QColor("#888888")

        for row, video in enumerate(videos):
            is_inacc = video.is_inaccessible
            reason_text = ""
            if is_inacc:
                reason_text = (
                    video.availability.get_localized_message()
                    if getattr(video, "availability", None)
                    else (video.error_reason or tr("status_inaccessible"))
                )

            from core.models import MediaType
            m_type = getattr(video, "media_type", MediaType.VIDEO)
            is_photo = (m_type == MediaType.PHOTO)

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            if is_inacc:
                chk_item.setFlags(Qt.ItemFlag.NoItemFlags)
                chk_item.setCheckState(Qt.CheckState.Unchecked)
                chk_item.setToolTip(tr("avail_tooltip_disabled", reason=reason_text))
            elif self._image_only_mode and not is_photo:
                chk_item.setFlags(Qt.ItemFlag.NoItemFlags)
                chk_item.setCheckState(Qt.CheckState.Unchecked)
                chk_item.setToolTip(tr("tooltip_disabled_in_image_only_mode"))
                video.selected = False
            else:
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                video.selected = True
                chk_item.setCheckState(Qt.CheckState.Checked)
            chk_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_item.setData(Qt.ItemDataRole.UserRole, video.video_id)
            self.table.setItem(row, self.COL_SELECT, chk_item)

            # Col 1: Index (#)
            idx_item = QTableWidgetItem(str(video.index))
            idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_inacc:
                idx_item.setForeground(disabled_color)
            self.table.setItem(row, self.COL_INDEX, idx_item)

            # Col 2: Media Title
            title_item = QTableWidgetItem(video.title)
            title_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            if is_inacc:
                title_item.setForeground(disabled_color)
                title_item.setToolTip(f"{video.title}\n{tr('avail_tooltip_disabled', reason=reason_text)}\n{tr('video_id_prefix', id=video.video_id)}\n{tr('url_prefix', url=video.url)}")
            else:
                title_item.setToolTip(f"{video.title}\n{tr('video_id_prefix', id=video.video_id)}\n{tr('url_prefix', url=video.url)}")
            self.table.setItem(row, self.COL_TITLE, title_item)

            # Col 3: Media Type
            from core.models import MediaType
            m_type = getattr(video, "media_type", MediaType.VIDEO)
            type_label = I18nManager.get_media_type_label(m_type)
            type_item = QTableWidgetItem(type_label)
            type_item.setData(Qt.ItemDataRole.UserRole, m_type)
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_inacc:
                type_item.setForeground(disabled_color)
            else:
                self._apply_media_type_styling(type_item, m_type)
            self.table.setItem(row, self.COL_TYPE, type_item)

            # Col 4: Duration (formatted string or '-', numeric value in UserRole for sorting)
            dur_str = video.formatted_duration
            dur_numeric = video.duration_seconds if (video.duration_seconds is not None and m_type != MediaType.PHOTO) else -1
            dur_item = _DurationTableWidgetItem(dur_str)
            dur_item.setData(Qt.ItemDataRole.UserRole, dur_numeric)
            dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_inacc:
                dur_item.setForeground(disabled_color)
            self.table.setItem(row, self.COL_DURATION, dur_item)

            # Col 4: Subtitle
            sub_raw = getattr(video, "subtitle_status", tr("subtitle_checking")) or tr("subtitle_checking")
            sub_item = QTableWidgetItem(self._localize_sub_status(sub_raw))
            sub_item.setData(Qt.ItemDataRole.UserRole, sub_raw)
            sub_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_inacc:
                sub_item.setForeground(disabled_color)
            else:
                self._apply_subtitle_styling(sub_item, sub_raw)
            self.table.setItem(row, self.COL_SUBTITLE, sub_item)

            # Col 5: Video ID (stored internally, column is hidden)
            id_item = QTableWidgetItem(video.video_id)
            id_item.setFont(mono_font)
            id_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setToolTip(tr("youtube_id_prefix", id=video.video_id))
            self.table.setItem(row, self.COL_VIDEO_ID, id_item)

            # Col 6: Status
            status_text = I18nManager.get_status_label(video.status)
            if is_inacc:
                if getattr(video, "availability", None):
                    status_text = I18nManager.get_status_label(video.availability.status.value)
                elif video.error_reason:
                    status_text = I18nManager.get_status_label(video.error_reason)
            status_item = QTableWidgetItem(status_text)
            status_item.setData(Qt.ItemDataRole.UserRole, video.status)
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if not is_inacc else Qt.ItemFlag.ItemIsSelectable)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_inacc:
                status_item.setForeground(disabled_color)
                status_item.setToolTip(f"{tr('avail_tooltip_disabled', reason=reason_text)}")
            else:
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
            if item and item.checkState() == Qt.CheckState.Checked and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                video_id = item.data(Qt.ItemDataRole.UserRole)
                selected_ids.add(video_id)

        selected_videos = []
        for vid in self._videos:
            if vid.video_id in selected_ids and not vid.is_inaccessible:
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

    def set_image_only_mode(self, enabled: bool) -> None:
        """
        In Image Only mode, all non-photo items (videos, reels) are unchecked and disabled.
        When exiting Image Only mode, non-inaccessible items become checkable again.
        """
        if getattr(self, "_image_only_mode", None) == enabled:
            return
        self._image_only_mode = enabled
        self.table.blockSignals(True)
        from core.models import MediaType
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, self.COL_SELECT)
            if not chk_item:
                continue
            vid_id = chk_item.data(Qt.ItemDataRole.UserRole)
            vid = next((v for v in self._videos if v.video_id == vid_id), None)
            if not vid:
                continue

            m_type = getattr(vid, "media_type", MediaType.VIDEO)
            is_photo = (m_type == MediaType.PHOTO)

            if enabled:
                if not is_photo:
                    vid.selected = False
                    chk_item.setCheckState(Qt.CheckState.Unchecked)
                    chk_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    chk_item.setToolTip(tr("tooltip_disabled_in_image_only_mode"))
                else:
                    if not vid.is_inaccessible:
                        chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            else:
                if not vid.is_inaccessible:
                    chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                    chk_item.setToolTip(f"{vid.title}\n{tr('video_id_prefix', id=vid.video_id)}\n{tr('url_prefix', url=vid.url)}")
        self.table.blockSignals(False)
        self._update_counts()

    def select_all(self, checked: bool) -> None:
        """Selects or deselects all video rows (or visible filtered rows if search active)."""
        self.table.blockSignals(True)
        target_state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            # If search filter is active, only toggle visible rows
            if not self.table.isRowHidden(row):
                item = self.table.item(row, self.COL_SELECT)
                if item:
                    vid_id = item.data(Qt.ItemDataRole.UserRole)
                    vid = next((v for v in self._videos if v.video_id == vid_id), None)
                    if vid and vid.is_inaccessible:
                        item.setCheckState(Qt.CheckState.Unchecked)
                        vid.selected = False
                    elif not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                        item.setCheckState(Qt.CheckState.Unchecked)
                        if vid:
                            vid.selected = False
                    else:
                        item.setCheckState(target_state)
                        if vid:
                            vid.selected = checked
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
        self.table_cleared.emit()

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
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            vid = next((v for v in self._videos if v.video_id == vid_id), None)
            if vid and vid.is_inaccessible and item.checkState() == Qt.CheckState.Checked:
                self.table.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.table.blockSignals(False)
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
            url = vid_match.url or f"https://www.youtube.com/watch?v={video_id}"
        else:
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
                platform=getattr(video, "platform", "youtube"),
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
                platform=getattr(video, "platform", "youtube"),
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
        vid_match = next((v for v in self._videos if v.video_id == video_id), None)
        if vid_match and vid_match.url:
            video_url = vid_match.url
        elif (getattr(vid_match, "platform", None) == "facebook" or getattr(self, "_current_platform", "") == "facebook") and video_id:
            video_url = f"https://www.facebook.com/watch/?v={video_id}"
        elif (getattr(vid_match, "platform", None) == "instagram" or getattr(self, "_current_platform", "") == "instagram") and video_id:
            video_url = f"https://www.instagram.com/p/{video_id}/"
        elif (getattr(vid_match, "platform", None) == "x" or getattr(self, "_current_platform", "") == "x") and video_id:
            raw_id = video_id.split("_")[0] if "_" in video_id else video_id
            video_url = f"https://x.com/i/status/{raw_id}"
        elif (getattr(vid_match, "platform", None) == "bilibili" or getattr(self, "_current_platform", "") == "bilibili") and video_id:
            video_url = f"https://www.bilibili.com/video/{video_id}"
        elif (getattr(vid_match, "platform", None) == "youtubemusic" or getattr(self, "_current_platform", "") == "youtubemusic") and video_id:
            video_url = f"https://music.youtube.com/watch?v={video_id}"
        elif (getattr(vid_match, "platform", None) == "tiktok" or getattr(self, "_current_platform", "") == "tiktok") and video_id:
            video_url = f"https://www.tiktok.com/@video/video/{video_id}"
        else:
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
            tr("header_media_title"),
            tr("header_media_type"),
            tr("header_duration"),
            tr("header_subtitle"),
            tr("header_media_id"),
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
        curr_plat = getattr(self, "_current_platform", "youtube")
        if curr_plat == "douyin":
            self.empty_subtitle.setText(tr("empty_subtitle_douyin"))
        elif curr_plat == "tiktok":
            self.empty_subtitle.setText(tr("empty_subtitle_tiktok"))
        elif curr_plat == "facebook":
            self.empty_subtitle.setText(tr("empty_subtitle_facebook"))
        elif curr_plat == "instagram":
            self.empty_subtitle.setText(tr("empty_subtitle_instagram"))
        elif curr_plat == "x":
            self.empty_subtitle.setText(tr("empty_subtitle_x"))
        else:
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
                chk_item = self.table.item(row, self.COL_SELECT)
                vid_id = chk_item.data(Qt.ItemDataRole.UserRole) if chk_item else None
                vid = next((v for v in self._videos if v.video_id == vid_id), None)
                if vid and vid.is_inaccessible:
                    if getattr(vid, "availability", None):
                        status_text = I18nManager.get_status_label(vid.availability.status.value)
                    elif vid.error_reason:
                        status_text = I18nManager.get_status_label(vid.error_reason)
                    else:
                        status_text = tr("status_inaccessible")
                    status_item.setText(status_text)
                    reason_text = vid.availability.get_localized_message() if getattr(vid, "availability", None) else (vid.error_reason or tr("status_inaccessible"))
                    status_item.setToolTip(tr("avail_tooltip_disabled", reason=reason_text))
                    if chk_item:
                        chk_item.setToolTip(tr("avail_tooltip_disabled", reason=reason_text))
                else:
                    raw_status = status_item.data(Qt.ItemDataRole.UserRole) or status_item.text()
                    status_item.setText(I18nManager.get_status_label(raw_status))

    @staticmethod
    def _apply_status_styling(item: QTableWidgetItem, status: str) -> None:
        """Applies clean semantic colors to different status states."""
        font = item.font()
        if font.pointSize() <= 0:
            font.setPointSize(9)
        st_lower = (status or "").lower()
        if status == VideoStatus.DOWNLOADING or "downloading" in st_lower or "下载中" in status:
            item.setForeground(QColor("#0284c7"))  # Sky blue
            font.setBold(True)
        elif status == VideoStatus.PROCESSING or "processing" in st_lower or "saving" in st_lower or "处理中" in status or "保存中" in status or "儲存中" in status:
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
        font = item.font()
        if font.pointSize() <= 0:
            font.setPointSize(9)
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

