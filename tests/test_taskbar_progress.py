"""
tests/test_taskbar_progress.py
Unit tests for TaskbarProgressManager and Windows Taskbar progress integration.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from gui.taskbar_progress import TaskbarProgressManager


# Ensure a QApplication exists for widget testing
app = QApplication.instance() or QApplication([])


class TestTaskbarProgressManager(unittest.TestCase):
    """Test suite for TaskbarProgressManager functionality and safety."""

    def setUp(self):
        self.widget = QWidget()

    def tearDown(self):
        self.widget.deleteLater()

    def test_manager_initialization_real_or_fallback(self):
        manager = TaskbarProgressManager(self.widget)
        # On Windows, is_available should reflect COM availability; on non-Windows it is False
        if sys.platform == "win32":
            self.assertTrue(manager.is_available)
        else:
            self.assertFalse(manager.is_available)

    def test_clamping_and_zero_safety(self):
        manager = TaskbarProgressManager(self.widget)
        # Mock underlying COM functions to inspect arguments
        mock_val = MagicMock()
        mock_state = MagicMock()
        manager._is_available = True
        manager._taskbar = 12345
        manager._set_value_fn = mock_val
        manager._set_state_fn = mock_state
        manager._get_hwnd = MagicMock(return_value=99999)

        # Test normal value
        manager.set_progress(50, 100)
        mock_val.assert_called_with(12345, 99999, 50, 100)
        mock_state.assert_called_with(12345, 99999, TaskbarProgressManager.TBPF_NORMAL)

        # Test negative value clamped to 0
        manager.set_progress(-10, 100)
        mock_val.assert_called_with(12345, 99999, 0, 100)

        # Test value exceeding total clamped to total
        manager.set_progress(150, 100)
        mock_val.assert_called_with(12345, 99999, 100, 100)

        # Test total <= 0 clamped to max(1, total) without ZeroDivisionError
        manager.set_progress(5, 0)
        mock_val.assert_called_with(12345, 99999, 1, 1)

    def test_pause_resume_clear_transitions(self):
        manager = TaskbarProgressManager(self.widget)
        mock_val = MagicMock()
        mock_state = MagicMock()
        manager._is_available = True
        manager._taskbar = 12345
        manager._set_value_fn = mock_val
        manager._set_state_fn = mock_state
        manager._get_hwnd = MagicMock(return_value=99999)

        # Set progress first
        manager.set_progress(30, 100)
        self.assertEqual(manager._current_state, TaskbarProgressManager.TBPF_NORMAL)

        # Pause
        manager.pause()
        self.assertEqual(manager._current_state, TaskbarProgressManager.TBPF_PAUSED)
        mock_state.assert_called_with(12345, 99999, TaskbarProgressManager.TBPF_PAUSED)

        # Resume
        manager.resume()
        self.assertEqual(manager._current_state, TaskbarProgressManager.TBPF_NORMAL)
        mock_state.assert_called_with(12345, 99999, TaskbarProgressManager.TBPF_NORMAL)

        # Clear
        manager.clear()
        self.assertEqual(manager._current_state, TaskbarProgressManager.TBPF_NOPROGRESS)
        mock_state.assert_called_with(12345, 99999, TaskbarProgressManager.TBPF_NOPROGRESS)

    def test_graceful_no_op_when_unavailable_or_no_hwnd(self):
        manager = TaskbarProgressManager(None)
        manager._is_available = False

        # Should never raise exceptions even when called without window or COM
        manager.set_progress(50, 100)
        manager.pause()
        manager.resume()
        manager.clear()


class TestMainWindowTaskbarIntegration(unittest.TestCase):
    """Test suite verifying MainWindow interaction with TaskbarProgressManager during queue events."""

    @patch("gui.main_window.QMessageBox.question")
    @patch("gui.main_window.SummaryDialog")
    @patch("gui.main_window.SettingsManager")
    def test_main_window_lifecycle_updates_taskbar(self, mock_settings_cls, mock_summary_cls, mock_msg_box):
        mock_settings = mock_settings_cls.return_value
        mock_settings.get.side_effect = lambda key, default=None: default
        mock_settings.get_all.return_value = {}

        from gui.main_window import MainWindow

        win = MainWindow()
        mock_tb = MagicMock()
        win.taskbar_progress = mock_tb

        # 1. Queue starts
        win._on_queue_started(total=10)
        mock_tb.set_progress.assert_called_with(0, 100)
        self.assertEqual(win._queue_total, 10)

        # 2. Video progress updates smooth overall progress
        # 0 completed items + video at 50% = 0.5 / 10 = 5% overall
        win._on_video_progress("vid1", 50.0, "5 MB", "10 MB", "1 MB/s", "00:05")
        mock_tb.set_progress.assert_called_with(50, 1000)

        # 3. Overall progress emits
        win._on_overall_progress(completed=1, skipped=0, failed=0, remaining=9, overall_pct=10.0)
        mock_tb.set_progress.assert_called_with(100, 1000)

        # 4. Pause clicked
        win._download_manager = MagicMock()
        win._download_manager.isRunning.return_value = True
        win._on_pause_clicked()
        mock_tb.pause.assert_called_once()

        # 5. Resume clicked
        win._on_resume_clicked()
        mock_tb.resume.assert_called_once()

        # 6. Queue finished
        win._on_queue_finished(completed=10, skipped=0, failed=0, total=10)
        mock_tb.clear.assert_called_once()

        # Clean up manager state before closing window
        win._download_manager = None
        win.close()
        win.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
