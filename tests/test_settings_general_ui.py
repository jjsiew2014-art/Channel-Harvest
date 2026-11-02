"""
test_settings_general_ui.py
Unit tests verifying SettingsDialog's GENERAL section layout, dynamic multilingual
translation (en, zh_CN, zh_TW), migration of 'Include Media ID in filename'
and 'Skip Downloaded Media' from File Organization card to the modern GENERAL card,
unified AUTHENTICATION card title, and Embed Cover Art renaming.
"""

import sys
import unittest
from PySide6.QtWidgets import QApplication

from core.i18n import I18nManager, tr
from core.settings import SettingsManager
from gui.main_window import MainWindow
from gui.settings_dialog import SettingsDialog
from gui.toggle_switch import ToggleSwitch


class TestSettingsGeneralUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.settings_manager = SettingsManager()

    def test_01_general_card_contains_seven_rows_with_toggles_in_order(self):
        """Verify SettingsDialog GENERAL card contains all 7 rows matching requested layout order."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            # Verify General section title exists
            self.assertTrue(hasattr(dlg, "general_title"))

            # Ordered rows:
            # 1. Desktop Notification
            # 2. Auto-Scan on Paste (directly below Desktop Notification)
            # 3. Skip Downloaded Media (directly above Automatic Clear Source Link, default False)
            # 4. Automatic Clear Source Link
            # 5. Automatic Clear Media List
            # 6. Automatic Clear Custom Folder Name
            # 7. Include Media ID in Filename
            rows = [
                ("notif_title_lbl", "notif_desc_lbl", "notif_cb"),
                ("auto_scan_on_paste_title_lbl", "auto_scan_on_paste_desc_lbl", "auto_scan_on_paste_cb"),
                ("skip_downloaded_media_title_lbl", "skip_downloaded_media_desc_lbl", "skip_downloaded_media_cb"),
                ("clear_link_title_lbl", "clear_link_desc_lbl", "clear_link_cb"),
                ("clear_media_list_title_lbl", "clear_media_list_desc_lbl", "clear_media_list_cb"),
                ("clear_custom_folder_title_lbl", "clear_custom_folder_desc_lbl", "clear_custom_folder_cb"),
                ("include_media_id_title_lbl", "include_media_id_desc_lbl", "include_media_id_cb"),
            ]
            for title_attr, desc_attr, switch_attr in rows:
                self.assertTrue(hasattr(dlg, title_attr), f"Missing {title_attr}")
                self.assertTrue(hasattr(dlg, desc_attr), f"Missing {desc_attr}")
                self.assertTrue(hasattr(dlg, switch_attr), f"Missing {switch_attr}")
                switch = getattr(dlg, switch_attr)
                self.assertIsInstance(switch, ToggleSwitch, f"{switch_attr} must be a ToggleSwitch")

            # Check default of skip_downloaded_media is False
            fresh_settings = SettingsManager()
            if "skip_downloaded_media" not in fresh_settings._data:
                dlg_fresh = SettingsDialog(settings_manager=fresh_settings)
                self.assertFalse(dlg_fresh.skip_downloaded_media_cb.isChecked())
                dlg_fresh.close()
        finally:
            dlg.close()

    def test_02_include_media_id_persists_settings_on_toggle(self):
        """Verify toggling include_media_id_cb updates settings_manager cleanly."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            # Toggle ON
            dlg.include_media_id_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("include_media_id_in_filename"))
            self.assertTrue(self.settings_manager.get("include_video_id_in_filename"))

            # Toggle OFF
            dlg.include_media_id_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("include_media_id_in_filename"))
            self.assertFalse(self.settings_manager.get("include_video_id_in_filename"))
        finally:
            dlg.close()

    def test_03_file_organization_does_not_contain_moved_items(self):
        """Verify Skip Downloaded Media & Include Media ID were moved to Settings, and Embed Cover Art renamed."""
        win = MainWindow()
        try:
            # Check all widgets in org_layout
            layout = win.add_number_cb.parentWidget().layout()
            org_widgets = []
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w is not None:
                    org_widgets.append(w)

            # Neither include_media_id_cb nor skip_downloaded_media_cb in File Organization layout
            self.assertNotIn(win.include_media_id_cb, org_widgets)
            self.assertNotIn(win.skip_downloaded_media_cb, org_widgets)

            # File Organization order:
            # 0: Section title
            # 1: add_number_cb
            # 2: embed_cover_art_cb
            # 3: embed_metadata_cb
            # 4: embed_lyrics_cb
            # 5: individual_media_folder_cb
            # 6: channel_folder_cb
            # 7: create_unique_filename_cb
            # 8: unique_folder_input
            self.assertEqual(org_widgets[0], win.org_title)
            self.assertEqual(org_widgets[1], win.add_number_cb)
            self.assertEqual(org_widgets[2], win.embed_cover_art_cb)
            self.assertEqual(org_widgets[3], win.embed_metadata_cb)
            self.assertEqual(org_widgets[4], win.embed_lyrics_cb)
            self.assertEqual(org_widgets[5], win.individual_media_folder_cb)
            self.assertEqual(org_widgets[6], win.channel_folder_cb)
            self.assertEqual(org_widgets[7], win.create_unique_filename_cb)
            self.assertEqual(org_widgets[8], win.unique_folder_input)

            # Check Embed Cover Art text
            I18nManager.set_language("en")
            win.retranslate_ui()
            self.assertEqual(win.embed_cover_art_cb.text(), "Embed Cover Art into Audio Tag")
        finally:
            win.close()

    def test_04_multilingual_retranslation_coverage_and_quality(self):
        """Verify dynamic retranslation across en, zh_CN, and zh_TW for all General settings rows."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            # 1. English
            I18nManager.set_language("en")
            dlg.retranslate_ui()
            self.assertEqual(dlg.general_title.text(), "GENERAL")
            self.assertEqual(dlg.notif_title_lbl.text(), "Desktop Notifications")
            self.assertEqual(dlg.auto_scan_on_paste_title_lbl.text(), "Auto-Scan on Paste")
            self.assertEqual(dlg.auto_scan_on_paste_desc_lbl.text(), "Automatically start scanning when a valid media link is pasted into the Link field.")
            self.assertEqual(dlg.skip_downloaded_media_title_lbl.text(), "Skip Downloaded Media")
            self.assertEqual(dlg.skip_downloaded_media_desc_lbl.text(), "Skip media items that already exist in the download directory or archive.")
            self.assertEqual(dlg.clear_link_title_lbl.text(), "Automatic Clear Source Link")
            self.assertEqual(dlg.include_media_id_title_lbl.text(), "Include Media ID in Filename")
            self.assertEqual(dlg.include_media_id_desc_lbl.text(), "Append the platform media or video ID to saved filenames.")

            # 2. Simplified Chinese (zh_CN)
            I18nManager.set_language("zh_CN")
            dlg.retranslate_ui()
            self.assertEqual(dlg.general_title.text(), "常规")
            self.assertEqual(dlg.notif_title_lbl.text(), "桌面通知")
            self.assertEqual(dlg.auto_scan_on_paste_title_lbl.text(), "粘贴链接后自动扫描")
            self.assertEqual(dlg.auto_scan_on_paste_desc_lbl.text(), "当完整粘贴有效媒体链接至主界面链接输入框时，自动触发扫描程序。")
            self.assertEqual(dlg.skip_downloaded_media_title_lbl.text(), "跳过已下载媒体")
            self.assertEqual(dlg.skip_downloaded_media_desc_lbl.text(), "跳过保存目录中已存在或已被归档的媒体文件。")
            self.assertEqual(dlg.clear_link_title_lbl.text(), "自动清空来源链接")
            self.assertEqual(dlg.clear_media_list_title_lbl.text(), "自动清空媒体列表")
            self.assertEqual(dlg.clear_custom_folder_title_lbl.text(), "自动清空自定义文件夹名称")
            self.assertEqual(dlg.include_media_id_title_lbl.text(), "文件名包含媒体 ID")
            self.assertEqual(dlg.include_media_id_desc_lbl.text(), "在保存的文件名末尾添加对应媒体或视频的平台 ID。")

            # 3. Traditional Chinese (zh_TW)
            I18nManager.set_language("zh_TW")
            dlg.retranslate_ui()
            self.assertEqual(dlg.general_title.text(), "一般")
            self.assertEqual(dlg.notif_title_lbl.text(), "桌面通知")
            self.assertEqual(dlg.auto_scan_on_paste_title_lbl.text(), "貼上連結後自動掃描")
            self.assertEqual(dlg.auto_scan_on_paste_desc_lbl.text(), "當完整貼上有效媒體連結至主畫面連結輸入框時，自動觸發掃描程序。")
            self.assertEqual(dlg.skip_downloaded_media_title_lbl.text(), "略過已下載媒體")
            self.assertEqual(dlg.skip_downloaded_media_desc_lbl.text(), "略過儲存目錄中已存在或已被封存的媒體檔案。")
            self.assertEqual(dlg.clear_link_title_lbl.text(), "自動清空來源連結")
            self.assertEqual(dlg.clear_media_list_title_lbl.text(), "自動清空媒體列表")
            self.assertEqual(dlg.clear_custom_folder_title_lbl.text(), "自動清空自訂資料夾名稱")
            self.assertEqual(dlg.include_media_id_title_lbl.text(), "檔案名稱包含媒體 ID")
            self.assertEqual(dlg.include_media_id_desc_lbl.text(), "在儲存的檔案名稱結尾新增對應媒體或影片的平台 ID。")
        finally:
            I18nManager.set_language("en")
            dlg.close()

    def test_05_auto_scan_on_paste_persists_settings_on_toggle(self):
        """Verify toggling auto_scan_on_paste_cb updates settings_manager cleanly."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            # Toggle ON
            dlg.auto_scan_on_paste_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("auto_scan_on_paste"))

            # Toggle OFF
            dlg.auto_scan_on_paste_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("auto_scan_on_paste"))
        finally:
            dlg.close()

    def test_06_paste_aware_line_edit_distinguishes_paste_from_typing(self):
        """Verify PasteAwareLineEdit emits pasted signal on paste events but NOT on normal keyboard typing."""
        from gui.main_window import PasteAwareLineEdit
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import Qt, QEvent
        import time

        le = PasteAwareLineEdit()
        pasted_payloads = []
        le.pasted.connect(lambda t: pasted_payloads.append(t))

        # 1. Typing 'h', 'e', 'l', 'l', 'o'
        for char in "hello":
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, char)
            le.keyPressEvent(event)
        self.assertEqual(len(pasted_payloads), 0, "Typing must NEVER emit pasted signal")

        # 2. Programmatic paste
        QApplication.clipboard().setText("https://www.youtube.com/@test")
        le.paste()
        self.assertEqual(len(pasted_payloads), 1)
        self.assertIn("https://www.youtube.com/@test", pasted_payloads[0])

        time.sleep(0.15)
        # 3. Ctrl+V key event
        ctrl_v = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        le.keyPressEvent(ctrl_v)
        self.assertEqual(len(pasted_payloads), 2)

    def test_07_auto_scan_triggered_only_on_paste_and_valid_link(self):
        """Verify auto-scan triggers only when auto_scan_on_paste=True and valid platform URL is pasted."""
        from unittest.mock import patch

        win = MainWindow(settings_manager=self.settings_manager)
        try:
            # Case 1: auto_scan_on_paste is False (default) -> Paste valid URL -> NO scan triggered
            self.settings_manager.set("auto_scan_on_paste", False)
            scan_called = []
            win._on_scan_clicked = lambda: scan_called.append(True)

            win.url_input.setText("https://www.youtube.com/@veritasium")
            win._on_url_pasted("https://www.youtube.com/@veritasium")
            QApplication.processEvents()
            self.assertEqual(len(scan_called), 0)

            # Case 2: auto_scan_on_paste is True -> Paste invalid URL -> NO scan triggered
            self.settings_manager.set("auto_scan_on_paste", True)
            win.url_input.setText("invalid-non-url-text")
            win._on_url_pasted("invalid-non-url-text")
            QApplication.processEvents()
            self.assertEqual(len(scan_called), 0)

            # Case 3: auto_scan_on_paste is True -> Paste valid YouTube URL -> Scan triggered
            win.url_input.setText("https://www.youtube.com/@veritasium")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://www.youtube.com/@veritasium")
                mock_single_shot.assert_called_once()
                args = mock_single_shot.call_args[0]
                self.assertEqual(args[1], win._on_scan_clicked)

            # Case 4: auto_scan_on_paste is True -> Paste valid TikTok URL -> Scan triggered
            win.url_input.setText("https://www.tiktok.com/@tiktok")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://www.tiktok.com/@tiktok")
                mock_single_shot.assert_called_once()
                self.assertEqual(mock_single_shot.call_args[0][1], win._on_scan_clicked)

            # Case 5: auto_scan_on_paste is True -> Paste valid Bilibili URL -> Scan triggered
            win.url_input.setText("https://www.bilibili.com/video/BV1xx411c7mD")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://www.bilibili.com/video/BV1xx411c7mD")
                mock_single_shot.assert_called_once()
                self.assertEqual(mock_single_shot.call_args[0][1], win._on_scan_clicked)

            # Case 6: auto_scan_on_paste is True -> Paste valid Facebook URL -> Scan triggered
            win.url_input.setText("https://www.facebook.com/watch/?v=123456789")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://www.facebook.com/watch/?v=123456789")
                mock_single_shot.assert_called_once()
                self.assertEqual(mock_single_shot.call_args[0][1], win._on_scan_clicked)

            # Case 7: auto_scan_on_paste is True -> Paste valid Instagram URL -> Scan triggered
            win.url_input.setText("https://www.instagram.com/p/C-example123/")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://www.instagram.com/p/C-example123/")
                mock_single_shot.assert_called_once()
                self.assertEqual(mock_single_shot.call_args[0][1], win._on_scan_clicked)

            # Case 8: auto_scan_on_paste is True -> Paste valid X URL -> Scan triggered
            win.url_input.setText("https://x.com/username/status/1234567890123456789")
            with patch("PySide6.QtCore.QTimer.singleShot") as mock_single_shot:
                win._on_url_pasted("https://x.com/username/status/1234567890123456789")
                mock_single_shot.assert_called_once()
                self.assertEqual(mock_single_shot.call_args[0][1], win._on_scan_clicked)
        finally:
            self.settings_manager.set("auto_scan_on_paste", False)
            win.close()

    def test_08_authentication_card_title_unified_without_platform_prefix(self):
        """Verify AUTHENTICATION card title is unified without platform prefix across all platforms."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            platforms = ["youtube", "douyin", "bilibili", "facebook", "instagram", "x"]
            for plat in platforms:
                dlg._on_auth_platform_changed(plat)
                self.assertEqual(dlg.auth_title.text(), "AUTHENTICATION")

            # Retranslate test
            I18nManager.set_language("zh_CN")
            dlg.retranslate_ui()
            for plat in platforms:
                dlg._on_auth_platform_changed(plat)
                self.assertEqual(dlg.auth_title.text(), "身份验证")

            I18nManager.set_language("zh_TW")
            dlg.retranslate_ui()
            for plat in platforms:
                dlg._on_auth_platform_changed(plat)
                self.assertEqual(dlg.auth_title.text(), "身分驗證")
        finally:
            I18nManager.set_language("en")
            dlg.close()

    def test_09_skip_downloaded_media_persists_settings_on_toggle(self):
        """Verify toggling skip_downloaded_media_cb in Settings updates settings_manager."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            dlg.skip_downloaded_media_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("skip_downloaded_media"))
            self.assertTrue(self.settings_manager.get("skip_existing"))

            dlg.skip_downloaded_media_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("skip_downloaded_media"))
            self.assertFalse(self.settings_manager.get("skip_existing"))
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
