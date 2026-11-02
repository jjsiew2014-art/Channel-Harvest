"""
test_window_scaling_and_progress_layout.py
Unit and integration tests verifying that window scaling, resizing, and responsive layouts
remain stable and uncompromised when downloading starts, even with long video titles,
special characters, emojis, and platform metadata.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSize

from gui.main_window import MainWindow, ElidedLabel


class TestWindowScalingAndProgressLayout(unittest.TestCase):
    """Verifies ElidedLabel and MainWindow progress section layout behavior under extreme titles."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        from core.i18n import I18nManager
        cls.orig_lang = I18nManager.get_language()
        I18nManager.set_language("en")
        cls._silent_patcher = patch.object(MainWindow, "_check_ytdlp_updates_silent", lambda self: None)
        cls._silent_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._silent_patcher.stop()
        from core.i18n import I18nManager
        I18nManager.set_language(cls.orig_lang)

    def setUp(self):
        self._sub_worker_patcher = patch("gui.main_window.SubtitleDetectionWorker")
        self.mock_sub_worker = self._sub_worker_patcher.start()
        mock_instance = MagicMock()
        mock_instance.isRunning.return_value = False
        self.mock_sub_worker.return_value = mock_instance

        self.window = MainWindow()

    def tearDown(self):
        self._sub_worker_patcher.stop()
        self.window._download_manager = None
        if hasattr(self.window, "_silent_update_worker") and self.window._silent_update_worker and self.window._silent_update_worker.isRunning():
            self.window._silent_update_worker.terminate()
            self.window._silent_update_worker.wait(500)
        if self.window._scan_worker and self.window._scan_worker.isRunning():
            self.window._scan_worker.terminate()
            self.window._scan_worker.wait(500)
        self.window.close()

    def test_01_elided_label_minimum_size_hint_does_not_inflate(self):
        """ElidedLabel must return a small minimum width regardless of text length."""
        short_label = ElidedLabel("Short")
        long_text = "🔥 [4K 超高清] 这是一个非常长、包含大量中文字符、特殊符号与标签的视频标题 " * 10
        long_label = ElidedLabel(long_text)

        # Both must have minimumSizeHint width <= 50, preventing layout lock
        self.assertLessEqual(short_label.minimumSizeHint().width(), 50)
        self.assertLessEqual(long_label.minimumSizeHint().width(), 50)

        # sizeHint width is capped
        self.assertLessEqual(long_label.sizeHint().width(), 300)

        # Full text and tooltip must preserve complete original string
        self.assertEqual(long_label.fullText(), long_text)
        self.assertEqual(long_label.toolTip(), long_text)

    def test_02_current_video_label_is_elided_label(self):
        """MainWindow.current_video_label must be an instance of ElidedLabel."""
        self.assertIsInstance(self.window.current_video_label, ElidedLabel)

    def test_03_download_start_with_long_title_preserves_layout_stability(self):
        """
        When downloading starts with an extremely long video title,
        the progress group and central widget minimum width must not inflate.
        """
        scroll_area = self.window.centralWidget()
        central_widget = scroll_area.widget()

        initial_pg_min_w = self.window.progress_group.minimumSizeHint().width()
        initial_cw_min_w = central_widget.minimumSizeHint().width()

        # Simulate download starting for a video with a massive 500+ character title
        massive_title = "🔥【震撼重磅】这是一个超长视频标题用于测试UI缩放与自适应布局稳定性 " * 10
        self.window._on_video_started("test_id_999", massive_title, 1, 20)
        self.app.processEvents()

        # Check current_video_label
        self.assertEqual(self.window.current_video_label.fullText(), f"Current Media: (1/20) {massive_title}")
        self.assertEqual(self.window.current_video_label.toolTip(), f"Current Media: (1/20) {massive_title}")
        self.assertLessEqual(self.window.current_video_label.minimumSizeHint().width(), 50)

        # Progress group and central widget minimum width must NOT have exploded
        after_pg_min_w = self.window.progress_group.minimumSizeHint().width()
        after_cw_min_w = central_widget.minimumSizeHint().width()

        self.assertEqual(after_pg_min_w, initial_pg_min_w)
        self.assertEqual(after_cw_min_w, initial_cw_min_w)

    def test_04_window_resizing_and_scroll_area_responsiveness(self):
        """
        Window can be resized smoothly down to minimum size (660x460) and restored
        without blowing out the central widget.
        """
        self.window.show()
        self.app.processEvents()

        massive_title = "A" * 600
        self.window._on_video_started("test_id_888", massive_title, 2, 10)
        self.app.processEvents()

        # Resize to standard 1200x960
        self.window.resize(1200, 960)
        self.app.processEvents()
        self.assertFalse(self.window.centralWidget().horizontalScrollBar().isVisible())

        # Resize to minimum size 660x460
        self.window.resize(660, 460)
        self.app.processEvents()
        # Verify current_video_label elided properly for narrow width
        self.assertTrue(len(self.window.current_video_label.text()) < len(massive_title))

    def test_05_status_bar_message_length_bounded(self):
        """Status bar message must truncate extremely long titles to prevent status bar layout overflow."""
        long_title = "X" * 300
        self.window._on_video_started("vid_short", long_title, 3, 5)
        status_msg = self.window.status_bar.currentMessage()
        self.assertLess(len(status_msg), 150)
        self.assertTrue("..." in status_msg or "…" in status_msg)


if __name__ == "__main__":
    unittest.main()
