"""
test_chinese_ui.py
Unit tests verifying Chinese UI translations, completeness, and natural modern phrasing.
"""

import unittest
from core.i18n import I18nManager, tr
from core.error_classifier import ErrorCategory, ErrorClassifier, DownloadError
from core.version import __developer__


class TestChineseUITranslations(unittest.TestCase):
    """Tests comprehensive Chinese UI translations and behavior."""

    def setUp(self):
        self._orig_lang = I18nManager.get_language()

    def tearDown(self):
        I18nManager.set_language(self._orig_lang)

    def test_theme_system_translation(self):
        """Verify 'System' theme translates to '跟随系统' in Chinese."""
        I18nManager.set_language("en")
        self.assertEqual(I18nManager.get_theme_label("System"), "System")

        I18nManager.set_language("zh_CN")
        self.assertEqual(I18nManager.get_theme_label("System"), "跟随系统")
        self.assertEqual(I18nManager.get_theme_label("Light"), "浅色模式")
        self.assertEqual(I18nManager.get_theme_label("Dark"), "深色模式")

    def test_all_new_strings_have_valid_translations(self):
        """Verify that all strings in _STRINGS have non-empty translations for en and zh_CN."""
        for key, trans in I18nManager._STRINGS.items():
            self.assertIn("en", trans, f"Key '{key}' missing 'en'")
            self.assertIn("zh_CN", trans, f"Key '{key}' missing 'zh_CN'")
            self.assertTrue(len(trans["en"].strip()) > 0 or key == "header_select", f"Key '{key}' has empty 'en'")
            self.assertTrue(len(trans["zh_CN"].strip()) > 0 or key == "header_select", f"Key '{key}' has empty 'zh_CN'")

    def test_developer_label_kept_in_english(self):
        """Verify developer credit text remains in English per user specification."""
        from gui.settings_dialog import SettingsDialog
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        I18nManager.set_language("zh_CN")
        dlg = SettingsDialog()
        # Per user request: 694 版权文字 和 698 开发者标签 无需有对应的中文
        self.assertEqual(dlg.dev_lbl.text(), f"Developed by {__developer__}")
        dlg.retranslate_ui()
        self.assertEqual(dlg.dev_lbl.text(), f"Developed by {__developer__}")
        dlg.close()

    def test_all_error_categories_localized_in_chinese(self):
        """Verify that all 24 canonical error categories have localized user messages and actions."""
        I18nManager.set_language("zh_CN")

        categories = [
            ErrorCategory.CANCELLED,
            ErrorCategory.FILE_LOCKED,
            ErrorCategory.DISK_SPACE_ERROR,
            ErrorCategory.PERMISSION_ERROR,
            ErrorCategory.FILE_SYSTEM_ERROR,
            ErrorCategory.JS_RUNTIME_ERROR,
            ErrorCategory.EJS_ERROR,
            ErrorCategory.PO_TOKEN_ERROR,
            ErrorCategory.BOT_VERIFICATION,
            ErrorCategory.AGE_RESTRICTED,
            ErrorCategory.LOGIN_REQUIRED,
            ErrorCategory.PRIVATE_VIDEO,
            ErrorCategory.VIDEO_UNAVAILABLE,
            ErrorCategory.REGION_RESTRICTED,
            ErrorCategory.FORMAT_ERROR,
            ErrorCategory.FFMPEG_ERROR,
            ErrorCategory.RANGE_NOT_SATISFIABLE,
            ErrorCategory.RATE_LIMITED,
            ErrorCategory.HTTP_403,
            ErrorCategory.HTTP_404,
            ErrorCategory.HTTP_500,
            ErrorCategory.HTTP_502,
            ErrorCategory.HTTP_503,
            ErrorCategory.TIMEOUT,
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.UNKNOWN_ERROR,
        ]

        for cat in categories:
            err = DownloadError(
                category=cat,
                title="Test Title",
                user_message="English message",
                suggested_action="English action",
                technical_details="tech",
            )
            zh_msg = err.get_localized_user_message()
            zh_act = err.get_localized_suggested_action()
            self.assertNotEqual(zh_msg, "English message", f"Category {cat} has unlocalized user_message")
            self.assertNotEqual(zh_act, "English action", f"Category {cat} has unlocalized suggested_action")
            # Verify contains Chinese characters
            self.assertTrue(any('\u4e00' <= char <= '\u9fff' for char in zh_msg), f"Category {cat} user_message not Chinese")
            self.assertTrue(any('\u4e00' <= char <= '\u9fff' for char in zh_act), f"Category {cat} suggested_action not Chinese")


    def test_refined_chinese_wording_and_colons(self):
        """Verify that refined Chinese terminology and full-width colons match the specifications."""
        I18nManager.set_language("zh_CN")
        self.assertEqual(tr("save_to"), "保存到：")
        self.assertEqual(tr("subsection_media"), "视频与音频")
        self.assertEqual(tr("label_mode"), "下载内容")
        self.assertEqual(tr("label_resolution"), "视频分辨率")
        self.assertEqual(tr("label_audio_bitrate"), "音频质量")
        self.assertEqual(tr("subsection_assets"), "附加内容")
        self.assertEqual(tr("label_thumb_format"), "封面格式")
        self.assertEqual(tr("subgroup_info_files"), "视频信息")
        self.assertEqual(tr("cb_save_meta"), "保存元数据")
        self.assertEqual(tr("cb_save_chapters"), "保存章节")
        self.assertEqual(tr("cb_channel_folder"), "按频道分类存放")
        self.assertEqual(tr("cb_individual_folder"), "每个视频单独建文件夹")
        self.assertEqual(tr("current_video_none"), "当前视频：无")
        self.assertEqual(tr("speed_fmt", speed="1 MB/s"), "下载速度：1 MB/s")
        self.assertEqual(tr("eta_fmt", eta="00:01"), "预计剩余时间：00:01")
        self.assertEqual(tr("runtime_manager_title"), "下载组件")
        self.assertEqual(tr("settings_auth"), "YOUTUBE 登录")
        self.assertEqual(tr("auth_method_label"), "登录方式")
        self.assertEqual(tr("auth_method_none"), "不使用")
        self.assertEqual(tr("auth_method_custom_file_radio"), "Cookie 文件")
        self.assertEqual(tr("auth_test_btn"), "测试登录")

        # Dropdowns
        self.assertEqual(I18nManager.get_mode_label("Assets Only"), "仅附加内容")
        self.assertEqual(I18nManager.get_mode_label("Subtitle Only"), "仅附加内容")
        self.assertEqual(I18nManager.get_quality_label("Best Available"), "最高分辨率")
        self.assertEqual(I18nManager.get_video_bitrate_label("Best Available"), "最高画质")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Best Available"), "最高音质")
        self.assertEqual(I18nManager.get_bitrate_label("Best Available"), "最高画质")

        I18nManager.set_language("en")
        self.assertEqual(I18nManager.get_mode_label("Assets Only"), "Assets Only")
        self.assertEqual(I18nManager.get_mode_label("Subtitle Only"), "Assets Only")
        I18nManager.set_language("zh_CN")

    def test_font_family_switching(self):
        """Verify dynamic font switching uses Noto Sans SC for Chinese and Segoe UI for English."""
        from gui.styles import get_font_family
        zh_fonts = get_font_family("zh_CN")
        en_fonts = get_font_family("en")
        self.assertTrue(zh_fonts.startswith('"Noto Sans SC"'), f"Chinese font stack does not prioritize Noto Sans SC: {zh_fonts}")
        self.assertTrue(en_fonts.startswith('"Segoe UI"'), f"English font stack does not prioritize Segoe UI: {en_fonts}")

    def test_no_ascii_colons_in_chinese_labels(self):
        """Verify that UI labels ending with colon in English use full-width colon in Chinese."""
        I18nManager.set_language("zh_CN")
        # Check label keys that represent field titles
        colon_keys = [
            "save_to", "current_video_none", "current_video_fmt",
            "overall_progress_fmt", "speed_fmt", "eta_fmt",
            "summary_total", "summary_completed", "summary_skipped",
            "summary_failed", "summary_destination", "error_dialog_video_label",
            "tooltip_reason_label", "tooltip_action_label", "video_id_prefix",
            "url_prefix", "youtube_id_prefix", "auth_browser_label",
            "auth_profile_label", "auth_cookie_file_label", "auth_status_label",
            "auth_last_test", "data_dir_desc"
        ]
        for key in colon_keys:
            raw_zh = I18nManager._STRINGS[key]["zh_CN"]
            self.assertIn("：", raw_zh, f"Key '{key}' Chinese string '{raw_zh}' should contain full-width colon '：'")
            # Also ensure it does not end with ASCII colon
            self.assertFalse(raw_zh.endswith(":"), f"Key '{key}' Chinese string ends with ASCII colon: '{raw_zh}'")


if __name__ == "__main__":
    unittest.main()
