"""
test_stop_scan_and_circular_progress.py
Unit tests verifying:
1. Empty source link and unique folder name on first launch / default settings.
2. Red Stop Scanning button during active scan with user cancellation support.
3. Circular progress indicator between source link and scan button.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from gui.circular_progress import CircularProgressIndicator
from gui.main_window import MainWindow
from downloader.ytdlp_engine import ChannelScanWorker


class TestStopScanAndCircularProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def setUp(self):
        # Fresh settings with defaults
        self.mock_settings_data = dict(SettingsManager.DEFAULT_SETTINGS)
        self.settings_manager = MagicMock(spec=SettingsManager)
        self.settings_manager.get.side_effect = lambda k, d=None: self.mock_settings_data.get(k, d)
        self.settings_manager.set.side_effect = lambda k, v: self.mock_settings_data.__setitem__(k, v)

    def test_01_first_launch_source_link_and_unique_folder_empty(self):
        """1. Verify that on first launch / default settings, source link and unique folder are empty."""
        self.assertEqual(SettingsManager.DEFAULT_SETTINGS["last_channel_url"], "")
        self.assertEqual(SettingsManager.DEFAULT_SETTINGS["unique_filename_folder"], "")
        self.assertEqual(SettingsManager.DEFAULT_SETTINGS["unique_folder_name"], "")

        with patch("gui.main_window.SettingsManager", return_value=self.settings_manager):
            window = MainWindow()
            # Verify UI inputs are empty
            self.assertEqual(window.url_input.text(), "")
            self.assertEqual(window.unique_folder_input.text(), "")
            window.close()

    def test_02_circular_progress_widget_properties_and_layout(self):
        """3. Verify circular progress indicator properties, methods, and layout position."""
        indicator = CircularProgressIndicator(size=24)
        self.assertFalse(indicator.isVisible())
        self.assertFalse(indicator.is_spinning)

        indicator.start_spinning()
        self.assertTrue(indicator.isVisible())
        self.assertTrue(indicator.is_spinning)

        indicator.stop_spinning()
        self.assertFalse(indicator.isVisible())
        self.assertFalse(indicator.is_spinning)

        with patch("gui.main_window.SettingsManager", return_value=self.settings_manager):
            window = MainWindow()
            self.assertTrue(hasattr(window, "scan_spinner"))
            self.assertIsInstance(window.scan_spinner, CircularProgressIndicator)
            self.assertFalse(window.scan_spinner.isVisible())

            # Verify it sits in the layout between url_input and scan_btn
            url_parent_layout = window.url_input.parentWidget().layout()
            # Check widget order in the input layout
            input_layout = None
            for i in range(window.url_group.layout().count()):
                item = window.url_group.layout().itemAt(i)
                if item and item.layout():
                    sub = item.layout()
                    if sub.indexOf(window.url_input) >= 0:
                        input_layout = sub
                        break

            self.assertIsNotNone(input_layout)
            url_idx = input_layout.indexOf(window.url_input)
            spinner_idx = input_layout.indexOf(window.scan_spinner)
            btn_idx = input_layout.indexOf(window.scan_btn)

            self.assertLess(url_idx, spinner_idx)
            self.assertLess(spinner_idx, btn_idx)
            window.close()

    def test_03_scanning_state_transitions_scan_btn_to_red_stop_button(self):
        """2. Verify that entering scanning state changes scan_btn to red Stop Scanning button."""
        with patch("gui.main_window.SettingsManager", return_value=self.settings_manager):
            window = MainWindow()

            # Initially idle
            self.assertEqual(window.scan_btn.objectName(), "scanButton")
            self.assertTrue(window.scan_btn.isEnabled())
            self.assertEqual(window.scan_btn.text(), "Scan Channel")
            self.assertFalse(window.scan_spinner.isVisible())

            # Transition to scanning
            window._set_ui_state("scanning")
            self.assertEqual(window.scan_btn.objectName(), "stopScanButton")
            self.assertTrue(window.scan_btn.isEnabled())  # Must be enabled so user can stop
            self.assertEqual(window.scan_btn.text(), tr("btn_stop_scanning"))
            self.assertFalse(window.scan_spinner.isHidden())
            self.assertTrue(window.scan_spinner.is_spinning)

            # Revert to idle
            window._set_ui_state("idle")
            self.assertEqual(window.scan_btn.objectName(), "scanButton")
            self.assertTrue(window.scan_btn.isEnabled())
            self.assertEqual(window.scan_btn.text(), "Scan Channel")
            self.assertTrue(window.scan_spinner.isHidden())
            self.assertFalse(window.scan_spinner.is_spinning)
            window.close()

    def test_04_clicking_stop_scanning_stops_worker_and_resets_ui(self):
        """2. Verify clicking scan_btn while scanning terminates worker and resets UI."""
        with patch("gui.main_window.SettingsManager", return_value=self.settings_manager):
            window = MainWindow()

            # Mock worker
            mock_worker = MagicMock(spec=ChannelScanWorker)
            mock_worker.isRunning.return_value = True
            window._scan_worker = mock_worker
            window._set_ui_state("scanning")

            self.assertEqual(window._current_ui_state, "scanning")
            self.assertTrue(window.scan_spinner.is_spinning)

            # Simulate user clicking Stop Scanning
            window._on_scan_clicked()

            # Worker cancel called
            mock_worker.cancel.assert_called_once()
            self.assertIsNone(window._scan_worker)
            self.assertEqual(window._current_ui_state, "idle")
            self.assertEqual(window.scan_btn.objectName(), "scanButton")
            self.assertEqual(window.scan_btn.text(), "Scan Channel")
            self.assertFalse(window.scan_spinner.isVisible())
            window.close()

    def test_05_channel_scan_worker_cancellation(self):
        """2. Verify ChannelScanWorker cancel method sets _is_cancelled and kills child processes."""
        worker = ChannelScanWorker(url="https://www.youtube.com/@test")
        self.assertFalse(worker._is_cancelled)

        with patch("downloader.download_manager.kill_child_processes") as mock_kill, \
             patch("downloader.gallerydl_engine.GalleryDlEngine.terminate_all_processes") as mock_kill_gdl:
            worker.cancel()
            self.assertTrue(worker._is_cancelled)
            mock_kill.assert_called_once()
            mock_kill_gdl.assert_called_once()


if __name__ == "__main__":
    unittest.main()
