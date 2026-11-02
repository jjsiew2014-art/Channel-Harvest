# -*- coding: utf-8 -*-
"""
tests/test_progress_bars_and_summary_folder.py

Unit test suite verifying:
1. Current video progress bar and overall progress bar operate independently:
   - Current video progress bar tracks active video download (0% -> 100%).
   - Overall progress bar tracks queue completion (items completed / total items).
   - In single-video downloads, overall progress bar does not clone current video ticks.
   - In multi-video downloads, overall progress advances when items finish.
2. Open download folder in SummaryDialog / queue completion:
   - Destination folder is properly sanitized and resolved from DownloadManager / sanitize_path_component.
   - Channel titles with invalid Windows characters (e.g. colons, pipes) resolve to the existing folder.
   - SummaryDialog gracefully strips quotes/whitespace and falls back to parent directory when needed.
   - No spurious 'Folder Not Found' warning is shown when download succeeded.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from core.models import VideoItem, VideoStatus, DownloadSettings, DownloadMode
from core.paths import sanitize_path_component
from downloader.download_manager import DownloadManager
from gui.main_window import MainWindow
from gui.summary_dialog import SummaryDialog

app = QApplication.instance() or QApplication(sys.argv)


class TestProgressBarIndependence(unittest.TestCase):
    """Verifies that current video and overall progress bars function independently."""

    def setUp(self):
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()

    def test_single_video_progress_bars_are_independent(self):
        """In a 1-video queue, current video progress does not duplicate overall progress."""
        self.win._on_queue_started(total=1)
        self.assertEqual(self.win.current_progress_bar.value(), 0)
        self.assertEqual(self.win.overall_progress_bar.value(), 0)

        # Video progress ticks to 35%
        self.win._on_video_progress(
            video_id="vid_1",
            percent=35.0,
            downloaded_str="15 MB",
            total_str="50 MB",
            speed="5 MB/s",
            eta="00:07",
        )
        # Current video is at 35%
        self.assertEqual(self.win.current_progress_bar.value(), 35)
        # Overall progress remains 0% because 0/1 items are finished in the queue
        self.assertEqual(self.win.overall_progress_bar.value(), 0)

        # Video progress ticks to 75%
        self.win._on_video_progress(
            video_id="vid_1",
            percent=75.0,
            downloaded_str="37.5 MB",
            total_str="50 MB",
            speed="5 MB/s",
            eta="00:02",
        )
        self.assertEqual(self.win.current_progress_bar.value(), 75)
        self.assertEqual(self.win.overall_progress_bar.value(), 0)

        # Video finishes and overall progress emits 100%
        self.win._on_overall_progress(completed=1, skipped=0, failed=0, remaining=0, overall_pct=100.0)
        self.assertEqual(self.win.overall_progress_bar.value(), 100)

    def test_multi_video_progress_bars_are_independent(self):
        """In a multi-video queue, current video resets per item while overall progress advances monotonically."""
        self.win._on_queue_started(total=3)
        self.assertEqual(self.win.overall_progress_bar.value(), 0)

        # Video 1 downloading (50%)
        self.win._on_video_started("v1", "Video 1", 1, 3)
        self.win._on_video_progress("v1", 50.0, "10 MB", "20 MB", "2 MB/s", "00:05")
        self.assertEqual(self.win.current_progress_bar.value(), 50)
        self.assertEqual(self.win.overall_progress_bar.value(), 0)

        # Video 1 completes (1/3 done = 33%)
        self.win._on_overall_progress(completed=1, skipped=0, failed=0, remaining=2, overall_pct=33.3)
        self.assertEqual(self.win.overall_progress_bar.value(), 33)

        # Video 2 starts (current progress bar resets to 0)
        self.win._on_video_started("v2", "Video 2", 2, 3)
        self.assertEqual(self.win.current_progress_bar.value(), 0)
        self.assertEqual(self.win.overall_progress_bar.value(), 33)

        # Video 2 downloading (60%)
        self.win._on_video_progress("v2", 60.0, "12 MB", "20 MB", "2 MB/s", "00:04")
        self.assertEqual(self.win.current_progress_bar.value(), 60)
        self.assertEqual(self.win.overall_progress_bar.value(), 33)

        # Video 2 completes (2/3 done = 66%)
        self.win._on_overall_progress(completed=2, skipped=0, failed=0, remaining=1, overall_pct=66.6)
        self.assertEqual(self.win.overall_progress_bar.value(), 66)

        # Video 3 completes (3/3 done = 100%)
        self.win._on_overall_progress(completed=3, skipped=0, failed=0, remaining=0, overall_pct=100.0)
        self.assertEqual(self.win.overall_progress_bar.value(), 100)


class TestSummaryDialogDownloadFolder(unittest.TestCase):
    """Verifies that Open Download Folder correctly resolves destination paths without false errors."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_open_folder_existing_directory_calls_startfile(self):
        """When the folder exists, _on_open_folder calls os.startfile with the folder path."""
        target = self.base_dir / "Channel_Folder"
        target.mkdir(parents=True, exist_ok=True)

        dlg = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder=str(target),
        )

        with patch("os.startfile") as mock_startfile, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_open_folder()
            mock_startfile.assert_called_once_with(str(target.resolve()))
            mock_warn.assert_not_called()
        dlg.close()

    def test_open_folder_strips_quotes_and_whitespace(self):
        """Surrounding quotes and whitespace are safely stripped and resolved."""
        target = self.base_dir / "Subfolder"
        target.mkdir(parents=True, exist_ok=True)

        dlg = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder=f'  "{target}"  ',
        )

        with patch("os.startfile") as mock_startfile, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_open_folder()
            mock_startfile.assert_called_once_with(str(target.resolve()))
            mock_warn.assert_not_called()
        dlg.close()

    def test_open_folder_fallback_to_parent_when_subfolder_missing(self):
        """If a specific subfolder is missing but parent exists, opens parent instead of showing error."""
        missing_subfolder = self.base_dir / "Nonexistent_Video_Folder"
        self.assertFalse(missing_subfolder.exists())
        self.assertTrue(self.base_dir.exists())

        dlg = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder=str(missing_subfolder),
        )

        with patch("os.startfile") as mock_startfile, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_open_folder()
            mock_startfile.assert_called_once_with(str(self.base_dir.resolve()))
            mock_warn.assert_not_called()
        dlg.close()

    def test_open_folder_shows_warning_only_if_entire_path_and_parent_missing(self):
        """Shows warning only when neither the folder nor its parent exists."""
        nonexistent_root = Path("Z:/nonexistent_drive_12345/nonexistent_subfolder")

        dlg = SummaryDialog(
            completed=0,
            skipped=0,
            failed=1,
            total=1,
            download_folder=str(nonexistent_root),
        )

        with patch("os.startfile") as mock_startfile, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            dlg._on_open_folder()
            mock_startfile.assert_not_called()
            mock_warn.assert_called_once()
        dlg.close()

    def test_download_manager_get_destination_folder_channel_with_illegal_characters(self):
        """DownloadManager resolves channel title with colons/pipes to sanitized folder on disk."""
        channel_title = "Veritasium: An element of truth | 4K"
        sanitized_name = sanitize_path_component(channel_title, max_length=80, fallback="channel")

        settings = DownloadSettings(
            download_folder=str(self.base_dir),
            create_channel_folder=True,
            channel_title=channel_title,
        )

        dm = DownloadManager(videos=[], settings=settings)
        # Create directory on disk as DownloadManager.run() does
        channel_dir = self.base_dir / sanitized_name
        channel_dir.mkdir(parents=True, exist_ok=True)
        dm._resolved_target_dir = channel_dir

        dest = dm.get_destination_folder()
        self.assertTrue(dest.exists())
        self.assertEqual(dest, channel_dir)


if __name__ == "__main__":
    unittest.main()
