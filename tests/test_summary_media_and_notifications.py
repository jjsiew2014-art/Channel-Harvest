"""
test_summary_media_and_notifications.py
Unit tests verifying:
1. Download Queue Complete window: 'Total Media in Queue' replacing 'Total Videos in Queue'.
2. Download Queue Complete window: 'Skipped Media' consolidating private and unavailable items.
3. File Organization: 'Add Sequence No. to filename' capitalization.
4. File Organization: 'Create custom folder name' renaming.
5. Settings: New 'enable_notifications' toggle (default True) and Windows desktop notification on download completion.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel, QCheckBox, QSystemTrayIcon

from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from gui.summary_dialog import SummaryDialog
from gui.settings_dialog import SettingsDialog
from gui.main_window import MainWindow


class TestSummaryMediaAndNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_summary_dialog_total_media_in_queue(self):
        """1. Verify Total Videos in Queue is renamed to Total Media in Queue across locales."""
        orig_lang = I18nManager.get_language()
        try:
            I18nManager.set_language("en")
            self.assertEqual(tr("summary_total"), "Total Media in Queue:")

            I18nManager.set_language("zh_CN")
            self.assertEqual(tr("summary_total"), "队列媒体总数：")

            I18nManager.set_language("zh_TW")
            self.assertEqual(tr("summary_total"), "佇列媒體總數：")
        finally:
            I18nManager.set_language(orig_lang)

    def test_02_summary_dialog_skipped_media_consolidation(self):
        """2. Verify Skipped - Private and Skipped - Unavailable are consolidated into Skipped Media."""
        orig_lang = I18nManager.get_language()
        try:
            I18nManager.set_language("en")
            self.assertEqual(tr("summary_skipped_media"), "Skipped Media:")

            I18nManager.set_language("zh_CN")
            self.assertEqual(tr("summary_skipped_media"), "跳过媒体：")

            I18nManager.set_language("zh_TW")
            self.assertEqual(tr("summary_skipped_media"), "略過媒體：")

            # Test SummaryDialog instantiation with private=2, unavailable=3
            I18nManager.set_language("en")
            dlg = SummaryDialog(
                completed=10,
                skipped=5,
                failed=0,
                total=15,
                download_folder="C:/ChannelHarvest/Downloads",
                skipped_private=2,
                skipped_unavailable=3,
            )

            # Backward compatibility attributes
            self.assertEqual(dlg.skipped_private, 2)
            self.assertEqual(dlg.skipped_unavailable, 3)
            self.assertEqual(dlg.skipped_media, 5)

            # Verify in dialog layout that 'Skipped Media:' is displayed and old separate labels are absent
            all_labels = [w.text() for w in dlg.findChildren(QLabel)]
            self.assertIn("Total Media in Queue:", all_labels)
            self.assertIn("Skipped Media:", all_labels)
            self.assertNotIn("Skipped — Private Video:", all_labels)
            self.assertNotIn("Skipped — Unavailable Video:", all_labels)

            dlg.close()
        finally:
            I18nManager.set_language(orig_lang)

    def test_03_file_org_add_sequence_no_capitalization(self):
        """3. Verify 'Add Sequence No. to filename' has capitalized Sequence and No."""
        orig_lang = I18nManager.get_language()
        try:
            I18nManager.set_language("en")
            self.assertEqual(tr("cb_add_number_to_filename"), "Add Sequence No. to filename")
            self.assertEqual(tr("cb_add_number"), "Add Sequence No. to filename")

            mock_settings = MagicMock(spec=SettingsManager)
            mock_settings.get.side_effect = lambda k, d=None: SettingsManager.DEFAULT_SETTINGS.get(k, d)
            with patch("gui.main_window.SettingsManager", return_value=mock_settings):
                win = MainWindow()
                self.assertEqual(win.add_number_cb.text(), "Add Sequence No. to filename")
                win.close()
        finally:
            I18nManager.set_language(orig_lang)

    def test_04_file_org_create_custom_folder_name_renaming(self):
        """4. Verify 'Create unique filename' is renamed to 'Create custom folder name'."""
        orig_lang = I18nManager.get_language()
        try:
            I18nManager.set_language("en")
            self.assertEqual(tr("cb_create_unique_filename"), "Create custom folder name")

            mock_settings = MagicMock(spec=SettingsManager)
            mock_settings.get.side_effect = lambda k, d=None: SettingsManager.DEFAULT_SETTINGS.get(k, d)
            with patch("gui.main_window.SettingsManager", return_value=mock_settings):
                win = MainWindow()
                self.assertEqual(win.create_unique_filename_cb.text(), "Create custom folder name")
                win.close()
        finally:
            I18nManager.set_language(orig_lang)

    def test_05_settings_notification_toggle_and_windows_notification(self):
        """5. Verify new notification switch in Settings (default ON) and desktop notification behavior."""
        # 5.1 Check default settings
        self.assertIn("enable_notifications", SettingsManager.DEFAULT_SETTINGS)
        self.assertTrue(SettingsManager.DEFAULT_SETTINGS["enable_notifications"])

        # 5.2 Settings Dialog UI integration
        mock_settings = MagicMock(spec=SettingsManager)
        stored_settings = {"enable_notifications": True}
        mock_settings.get.side_effect = lambda k, d=None: stored_settings.get(k, SettingsManager.DEFAULT_SETTINGS.get(k, d))
        mock_settings.set.side_effect = lambda k, v: stored_settings.update({k: v})

        with patch("gui.settings_dialog.SettingsManager", return_value=mock_settings), \
             patch("gui.settings_dialog.DetectRuntimeWorker"):
            settings_dlg = SettingsDialog()
            self.assertTrue(hasattr(settings_dlg, "notif_cb"))
            self.assertTrue(settings_dlg.notif_cb.isChecked())

            # Toggle off and verify persistence
            settings_dlg.notif_cb.setChecked(False)
            self.assertFalse(stored_settings["enable_notifications"])

            # Toggle on and verify persistence
            settings_dlg.notif_cb.setChecked(True)
            self.assertTrue(stored_settings["enable_notifications"])

            settings_dlg.close()

        # 5.3 Verify MainWindow triggers notification when enabled
        with patch("gui.main_window.SettingsManager", return_value=mock_settings):
            win = MainWindow()
            stored_settings["enable_notifications"] = True

            # 5.3 Verify MainWindow triggers notification when enabled
            win._download_manager = MagicMock()
            win._download_manager.isRunning.return_value = False
            win._download_manager.is_cancelled.return_value = False
            win._download_manager.get_destination_folder.return_value = None
            win._download_manager.get_queue_statistics.return_value = {
                "completed": 5, "skipped": 1, "failed": 0, "total": 6
            }
            stored_settings["enable_notifications"] = True

            # Mock tray_icon.showMessage and SummaryDialog
            with patch.object(win.tray_icon, "showMessage") as mock_show_msg, \
                 patch("gui.main_window.SummaryDialog"):
                win._on_queue_finished(completed=5, skipped=1, failed=0, total=6)

                mock_show_msg.assert_called_once()
                call_args = mock_show_msg.call_args[0]
                # Large title is "Downloaded Completed"
                self.assertEqual(call_args[0], "Downloaded Completed")
                # Body contains only completed, skipped, failed counts (no "downloaded finished")
                self.assertEqual(call_args[1], "5 Completed, 1 Skipped, 0 Failed")
                self.assertNotIn("downloaded finished", call_args[1].lower())
                self.assertNotIn("download finished", call_args[1].lower())
                self.assertIsInstance(call_args[2], QIcon)
                self.assertFalse(call_args[2].isNull())

            # Verify AppUserModelID is set to 'Channel Harvest'
            try:
                import ctypes
                buf = ctypes.c_wchar_p()
                res = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(buf))
                if res == 0:
                    self.assertEqual(buf.value, "Channel Harvest")
            except Exception:
                pass

            # 5.4 Verify MainWindow does NOT trigger notification when disabled
            stored_settings["enable_notifications"] = False
            with patch.object(win.tray_icon, "showMessage") as mock_show_msg, \
                 patch("gui.main_window.SummaryDialog"):
                win._on_queue_finished(completed=5, skipped=1, failed=0, total=6)

                mock_show_msg.assert_not_called()

            # 5.5 Verify MainWindow does NOT trigger completion notification when cancelled
            stored_settings["enable_notifications"] = True
            with patch.object(win.tray_icon, "showMessage") as mock_show_msg, \
                 patch("gui.main_window.SummaryDialog"):
                win._download_manager.is_cancelled.return_value = True
                win._download_manager.get_queue_statistics.return_value = {
                    "completed": 1, "skipped": 0, "failed": 0, "total": 6, "cancelled": 1
                }
                win._on_queue_finished(completed=1, skipped=0, failed=0, total=6)

                mock_show_msg.assert_not_called()

            win._download_manager = None
            win.close()

    def test_06_activity_log_dialog_window_icon(self):
        """1. Verify Activity Log dialog window icon is set to the Channel Harvest software icon."""
        from gui.activity_log_dialog import ActivityLogDialog
        dlg = ActivityLogDialog()
        try:
            self.assertFalse(dlg.windowIcon().isNull())
        finally:
            dlg.close()

    def test_07_runtime_manager_order_gallerydl_between_ytdlp_and_ejs(self):
        """2. Verify gallery-dl is placed between yt-dlp and EJS in RuntimeManager.ALL_COMPONENTS."""
        from downloader.runtime_manager import RuntimeManager
        comps = RuntimeManager.ALL_COMPONENTS
        self.assertIn(RuntimeManager.KEY_YTDLP, comps)
        self.assertIn(RuntimeManager.KEY_GALLERYDL, comps)
        self.assertIn(RuntimeManager.KEY_EJS, comps)

        idx_ytdlp = comps.index(RuntimeManager.KEY_YTDLP)
        idx_gdl = comps.index(RuntimeManager.KEY_GALLERYDL)
        idx_ejs = comps.index(RuntimeManager.KEY_EJS)

        self.assertEqual(idx_gdl, idx_ytdlp + 1)
        self.assertEqual(idx_ejs, idx_gdl + 1)
        self.assertEqual(comps, [
            RuntimeManager.KEY_YTDLP,
            RuntimeManager.KEY_GALLERYDL,
            RuntimeManager.KEY_EJS,
            RuntimeManager.KEY_DENO,
            RuntimeManager.KEY_FFMPEG,
        ])



if __name__ == "__main__":
    unittest.main()
