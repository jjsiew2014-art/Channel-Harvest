"""
test_gallerydl_runtime_and_activity_log_dialog.py
Unit tests verifying:
1. RuntimeManager support for gallery-dl version detection and update checking.
2. Download action buttons order (Open Folder, Pause, Resume, Cancel, Start Download).
3. Removal of Activity Log from main window and giving vertical space to Available Video.
4. Activity Log button left of Settings and opening dedicated ActivityLogDialog.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

from downloader.runtime_manager import RuntimeManager
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlInfo
from gui.activity_log_dialog import ActivityLogDialog
from gui.main_window import MainWindow
from core.settings import SettingsManager


class TestGalleryDlRuntimeAndActivityLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def test_01_gallerydl_in_runtime_manager_components(self):
        """1. Verify gallerydl is in RuntimeManager components and detected."""
        self.assertIn(RuntimeManager.KEY_GALLERYDL, RuntimeManager.ALL_COMPONENTS)
        placeholders = RuntimeManager.get_placeholder_versions()
        self.assertIn(RuntimeManager.KEY_GALLERYDL, placeholders)
        self.assertEqual(placeholders[RuntimeManager.KEY_GALLERYDL].display_name, "gallery-dl")

        # Mock GalleryDlEngine.detect_runtime
        with patch.object(
            GalleryDlEngine,
            "detect_runtime",
            return_value=GalleryDlInfo(available=True, version="1.32.18", executable_path="C:/fake/gallery-dl.exe"),
        ):
            versions = RuntimeManager.get_installed_versions(force_refresh=True)
            self.assertIn(RuntimeManager.KEY_GALLERYDL, versions)
            gdl_info = versions[RuntimeManager.KEY_GALLERYDL]
            self.assertEqual(gdl_info.current_version, "1.32.18")
            self.assertEqual(gdl_info.status, "Up to date")
            self.assertEqual(gdl_info.path, "C:/fake/gallery-dl.exe")

    def test_02_gallerydl_check_update(self):
        """1. Verify check_component_update detects newer gallery-dl version."""
        with patch.object(
            GalleryDlEngine,
            "detect_runtime",
            return_value=GalleryDlInfo(available=True, version="1.32.17", executable_path="C:/fake/gallery-dl.exe"),
        ):
            RuntimeManager.get_installed_versions(force_refresh=True)

            mock_pypi_resp = MagicMock()
            mock_pypi_resp.status = 200
            mock_pypi_resp.read.return_value = b'{"info": {"version": "1.32.18"}}'
            mock_pypi_resp.__enter__.return_value = mock_pypi_resp

            with patch("urllib.request.urlopen", return_value=mock_pypi_resp):
                info = RuntimeManager.check_component_update(RuntimeManager.KEY_GALLERYDL)
                self.assertEqual(info.current_version, "1.32.17")
                self.assertEqual(info.latest_version, "1.32.18")
                self.assertTrue(info.has_update)
                self.assertEqual(info.status, "Update available")

    def test_03_download_action_buttons_order(self):
        """2. Verify download option buttons order: Open Folder, Pause, Resume, Cancel, Start Download."""
        mock_settings = MagicMock(spec=SettingsManager)
        mock_settings.get.side_effect = lambda k, d=None: SettingsManager.DEFAULT_SETTINGS.get(k, d)

        with patch("gui.main_window.SettingsManager", return_value=mock_settings):
            window = MainWindow()

            # Find action layout
            action_layout = None
            for i in range(window.download_group.layout().count()):
                item = window.download_group.layout().itemAt(i)
                if item and item.layout():
                    sub = item.layout()
                    if sub.indexOf(window.download_btn) >= 0:
                        action_layout = sub
                        break

            self.assertIsNotNone(action_layout)
            idx_open = action_layout.indexOf(window.open_folder_btn)
            idx_pause = action_layout.indexOf(window.pause_btn)
            idx_resume = action_layout.indexOf(window.resume_btn)
            idx_cancel = action_layout.indexOf(window.cancel_btn)
            idx_download = action_layout.indexOf(window.download_btn)

            # Order must be strictly: Open Folder -> Pause -> Resume -> Cancel -> Start Download
            self.assertEqual(
                [idx_open, idx_pause, idx_resume, idx_cancel, idx_download],
                sorted([idx_open, idx_pause, idx_resume, idx_cancel, idx_download]),
            )
            self.assertLess(idx_open, idx_pause)
            self.assertLess(idx_pause, idx_resume)
            self.assertLess(idx_resume, idx_cancel)
            self.assertLess(idx_cancel, idx_download)
            window.close()

    def test_04_activity_log_removed_from_main_window_and_video_table_expands(self):
        """3. Verify Activity Log is removed from main window and Available Video takes stretch."""
        mock_settings = MagicMock(spec=SettingsManager)
        mock_settings.get.side_effect = lambda k, d=None: SettingsManager.DEFAULT_SETTINGS.get(k, d)

        with patch("gui.main_window.SettingsManager", return_value=mock_settings):
            window = MainWindow()
            main_layout = window.video_group.parentWidget().layout()
            self.assertIsNotNone(main_layout)

            # Verify log_group is NOT in main_layout
            for i in range(main_layout.count()):
                item = main_layout.itemAt(i)
                w = item.widget()
                if w:
                    self.assertNotEqual(w.objectName(), "logGroupBox")

            # Verify video_group is in main_layout with positive stretch
            vid_idx = main_layout.indexOf(window.video_group)
            self.assertGreaterEqual(vid_idx, 0)
            self.assertGreater(main_layout.stretch(vid_idx), 0)
            window.close()

    def test_05_activity_log_button_and_dialog(self):
        """4. Verify Activity Log button is to the left of Settings and opens ActivityLogDialog."""
        mock_settings = MagicMock(spec=SettingsManager)
        mock_settings.get.side_effect = lambda k, d=None: SettingsManager.DEFAULT_SETTINGS.get(k, d)

        with patch("gui.main_window.SettingsManager", return_value=mock_settings):
            window = MainWindow()

            # Find header layout
            main_layout = window.video_group.parentWidget().layout()
            header_layout = main_layout.itemAt(0).layout()
            self.assertIsNotNone(header_layout)

            idx_log_btn = header_layout.indexOf(window.activity_log_btn)
            idx_settings_btn = header_layout.indexOf(window.settings_btn)

            # Activity Log button must be immediately to the left of Settings button
            self.assertGreaterEqual(idx_log_btn, 0)
            self.assertGreaterEqual(idx_settings_btn, 0)
            self.assertLess(idx_log_btn, idx_settings_btn)

            # Click Activity Log button opens ActivityLogDialog
            window.log("Test log entry 12345")
            window._on_activity_log_clicked()

            self.assertIsNotNone(window._activity_log_dialog)
            self.assertIsInstance(window._activity_log_dialog, ActivityLogDialog)
            self.assertIn("Test log entry 12345", window._activity_log_dialog.log_output.toPlainText())

            # Real-time streaming to open dialog
            window.log("Live incoming message 67890")
            self.assertIn("Live incoming message 67890", window._activity_log_dialog.log_output.toPlainText())

            # Test Copy All and Clear
            window._activity_log_dialog.clear_log()
            self.assertEqual(window._activity_log_dialog.log_output.toPlainText(), "")

            if window._activity_log_dialog:
                window._activity_log_dialog.close()
            window.close()


if __name__ == "__main__":
    unittest.main()
