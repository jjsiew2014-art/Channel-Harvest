# -*- coding: utf-8 -*-

"""

test_traditional_chinese_ui.py

Comprehensive test suite verifying Traditional Chinese (Taiwan) localization

and compliance with all 15 acceptance criteria in Channel Harvest.

"""



import sys

import os

import unittest

import tempfile

import json

import re

from pathlib import Path



# Ensure application modules can be imported

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))



from PySide6.QtWidgets import QApplication

from core.i18n import I18nManager, tr

from core.settings import SettingsManager

from core.models import (

    DownloadMode,

    SubtitleSource,

    SubtitleLanguage,

    ThumbnailFormat,

    VideoStatus,

    VideoItem,

)

from core.error_classifier import DownloadError, ErrorCategory

from gui.styles import ThemeManager, ThemeMode, get_font_family



# Initialize headless QApplication if not running

app = QApplication.instance() or QApplication(sys.argv)





class TestLanguageDropdownAndSettings(unittest.TestCase):

    """Verifies acceptance criteria 1, 2, 3, 4: dropdown choices, switching, persistence."""



    def setUp(self):

        self.orig_lang = I18nManager.get_language()

        self.temp_dir = tempfile.TemporaryDirectory()

        self.settings_file = Path(self.temp_dir.name) / "settings.json"



    def tearDown(self):

        I18nManager.set_language(self.orig_lang)

        self.temp_dir.cleanup()



    def test_languages_constant_contains_zh_tw(self):

        """Criterion 1: Language options contain English, Simplified Chinese, and Traditional Chinese."""

        expected = [

            ("English", "en"),

            ("简体中文", "zh_CN"),

            ("繁體中文", "zh_TW"),

        ]

        self.assertEqual(I18nManager.LANGUAGES, expected)



    def test_settings_dialog_dropdown_items(self):

        """Criterion 1 & 2: Settings dialog dropdown displays correct labels and codes."""

        from gui.settings_dialog import SettingsDialog



        sm = SettingsManager(settings_path=self.settings_file)

        dlg = SettingsDialog(None, settings_manager=sm)



        items = [dlg.lang_combo.itemText(i) for i in range(dlg.lang_combo.count())]

        codes = [dlg.lang_combo.itemData(i) for i in range(dlg.lang_combo.count())]



        self.assertEqual(items, ["English", "简体中文", "繁體中文"])

        self.assertEqual(codes, ["en", "zh_CN", "zh_TW"])



        # Switch to zh_TW via dropdown

        dlg.lang_combo.setCurrentIndex(2)

        self.assertEqual(I18nManager.get_language(), "zh_TW")

        self.assertEqual(sm.get("language"), "zh_TW")

        self.assertEqual(dlg.lang_lbl.text(), "語言")



        # Criterion 4: Switching back to Simplified Chinese and English still works

        dlg.lang_combo.setCurrentIndex(1)

        self.assertEqual(I18nManager.get_language(), "zh_CN")

        self.assertEqual(sm.get("language"), "zh_CN")

        self.assertEqual(dlg.lang_lbl.text(), "语言")



        dlg.lang_combo.setCurrentIndex(0)

        self.assertEqual(I18nManager.get_language(), "en")

        self.assertEqual(sm.get("language"), "en")

        self.assertEqual(dlg.lang_lbl.text(), "Language")



        dlg.close()



    def test_language_persistence_across_restarts(self):

        """Criterion 3: Selected language persists after restarting the application."""

        # Save zh_TW in settings manager

        sm1 = SettingsManager(settings_path=self.settings_file)

        sm1.set("language", "zh_TW")

        sm1.save()



        # Simulate restart with fresh SettingsManager instance loading the saved settings file

        I18nManager.set_language("en")  # Reset memory state

        self.assertEqual(I18nManager.get_language(), "en")



        sm2 = SettingsManager(settings_path=self.settings_file)

        self.assertEqual(sm2.get("language"), "zh_TW")

        self.assertEqual(I18nManager.get_language(), "zh_TW")





class TestTranslationCoverageAndPlaceholders(unittest.TestCase):

    """Verifies acceptance criteria 6, 7, 8: complete key coverage, placeholder parity, terminology."""



    def test_no_missing_keys_in_strings(self):

        """Criterion 7: Translation dictionaries contain all required keys with automated check."""

        missing = []

        for key, lang_map in I18nManager._STRINGS.items():

            if "zh_TW" not in lang_map or (key != "header_select" and not lang_map["zh_TW"].strip()):

                missing.append(key)



        self.assertEqual(

            missing, [],

            f"Found {len(missing)} keys missing Traditional Chinese translations: {missing}"

        )

        self.assertGreaterEqual(len(I18nManager._STRINGS), 350)
        self.assertEqual(len(I18nManager._STRINGS), 496)



    def test_all_label_dictionaries_have_zh_tw(self):

        """Verify all enum/label helper dictionaries include zh_TW translations."""

        dict_checks = [

            ("MODE_LABELS", I18nManager._MODE_LABELS),

            ("SUB_SOURCE_LABELS", I18nManager._SUB_SOURCE_LABELS),

            ("SUB_LANG_LABELS", I18nManager._SUB_LANG_LABELS),

            ("THUMB_FORMAT_LABELS", I18nManager._THUMB_FORMAT_LABELS),

            ("THEME_LABELS", I18nManager._THEME_LABELS),

            ("STATUS_LABELS", I18nManager._STATUS_LABELS),

            ("QUALITY_LABELS", I18nManager._QUALITY_LABELS),

            ("VIDEO_BITRATE_LABELS", I18nManager._VIDEO_BITRATE_LABELS),

            ("AUDIO_BITRATE_LABELS", I18nManager._AUDIO_BITRATE_LABELS),

        ]



        for name, d in dict_checks:

            for k, val_map in d.items():

                self.assertIn(

                    "zh_TW", val_map,

                    f"Label dict {name} entry '{k}' missing 'zh_TW' translation!"

                )

                self.assertTrue(len(val_map["zh_TW"]) > 0)



    def test_placeholder_parity_between_en_and_zh_tw(self):

        """Criterion 8: Format placeholders ({var}) match exactly between en and zh_TW."""

        placeholder_pattern = re.compile(r"\{([a-zA-Z0-9_]+)\}")

        mismatches = []



        for key, lang_map in I18nManager._STRINGS.items():

            en_text = lang_map.get("en", "")

            tw_text = lang_map.get("zh_TW", "")

            en_tokens = set(placeholder_pattern.findall(en_text))

            tw_tokens = set(placeholder_pattern.findall(tw_text))

            if en_tokens != tw_tokens:

                mismatches.append((key, en_tokens, tw_tokens))



        self.assertEqual(

            mismatches, [],

            f"Found placeholder token mismatches in {len(mismatches)} keys: {mismatches}"

        )



    def test_taiwan_standard_terminology(self):

        """Verify compliance with Taiwan software terminology standards (no Mainland terms in zh_TW)."""

        forbidden_terms = [

            "视频", "音频", "文件夹", "磁盘", "网络", "分辨率", "码率",

            "组件", "登录", "默认", "帮助", "缩略图", "缓存", "运行时",

            "链接", "跳过", "支持", "信息", "用户", "会话"

        ]



        violations = []

        for key, lang_map in I18nManager._STRINGS.items():

            tw_text = lang_map.get("zh_TW", "")

            for term in forbidden_terms:

                if term in tw_text:

                    violations.append((key, term, tw_text))



        self.assertEqual(

            violations, [],

            f"Found forbidden Simplified/Mainland terms in zh_TW: {violations}"

        )





class TestMainWindowAndComponentsTraditionalChinese(unittest.TestCase):

    """Verifies acceptance criteria 5, 8, 9: main window sections, tables, progress, dialogs."""



    def setUp(self):

        self.orig_lang = I18nManager.get_language()

        I18nManager.set_language("zh_TW")



    def tearDown(self):

        I18nManager.set_language(self.orig_lang)



    def test_enum_label_translations_in_zh_tw(self):

        """Verify helper getters return natural Taiwan Traditional Chinese."""

        self.assertEqual(I18nManager.get_mode_label(DownloadMode.VIDEO_AND_AUDIO), "影片 + 音訊")

        self.assertEqual(I18nManager.get_mode_label(DownloadMode.VIDEO_ONLY), "僅影片")

        self.assertEqual(I18nManager.get_mode_label(DownloadMode.AUDIO_ONLY), "僅音訊")

        self.assertEqual(I18nManager.get_mode_label(DownloadMode.ASSETS_ONLY), "僅附加內容")



        self.assertEqual(I18nManager.get_sub_source_label(SubtitleSource.AUTO_GENERATED), "自動產生字幕")

        self.assertEqual(I18nManager.get_sub_lang_label(SubtitleLanguage.CHINESE), "中文")

        self.assertEqual(I18nManager.get_sub_lang_label(SubtitleLanguage.ALL), "所有語言")



        self.assertEqual(I18nManager.get_theme_label("Dark"), "深色模式")

        self.assertEqual(I18nManager.get_theme_label("Light"), "淺色模式")

        self.assertEqual(I18nManager.get_theme_label("System"), "跟隨系統")



        self.assertEqual(I18nManager.get_quality_label("Best Available"), "最高解析度")

        self.assertEqual(I18nManager.get_video_bitrate_label("Best Available"), "最高畫質")

        self.assertEqual(I18nManager.get_audio_bitrate_label("Best Available"), "最高音質")



        self.assertEqual(I18nManager.get_status_label(VideoStatus.DOWNLOADING), "下載中")

        self.assertEqual(I18nManager.get_status_label(VideoStatus.SKIPPED), "已略過")

        self.assertEqual(I18nManager.get_status_label(VideoStatus.COMPLETED), "已完成")

        self.assertEqual(I18nManager.get_status_label("Failed — HTTP 403"), "失敗 — HTTP 403")

        self.assertEqual(I18nManager.get_status_label("Failed — Custom"), "失敗 — Custom")



    def test_main_window_labels_zh_tw(self):

        """Criterion 5: All major application sections display Traditional Chinese correctly."""

        from gui.main_window import MainWindow



        win = MainWindow()

        try:

            # Switch to zh_TW dynamically

            I18nManager.set_language("zh_TW")
            win.platform_combo.setCurrentIndex(win.platform_combo.findData("youtube"))



            self.assertEqual(win.scan_btn.text(), "掃描頻道")

            self.assertEqual(win.download_btn.text(), "開始下載")

            self.assertEqual(win.pause_btn.text(), "暫停")

            self.assertEqual(win.cancel_btn.text(), "取消")

            self.assertEqual(win.open_folder_btn.text(), "開啟資料夾")



            # Check table headers

            tbl = win.video_table.table

            headers = [tbl.horizontalHeaderItem(col).text() for col in range(tbl.columnCount())]

            self.assertTrue("媒體標題" in headers or "影片標題" in headers)

            self.assertIn("時長", headers)

            self.assertIn("字幕", headers)

            self.assertIn("狀態", headers)



            # Check source title row

            self.assertEqual(win.source_title_badge.text(), "來源名稱")

            self.assertEqual(win.source_title_value.text(), "未載入來源")

        finally:

            win.close()



    def test_summary_dialog_zh_tw(self):

        """Verify completion summary dialog uses natural Taiwan Traditional Chinese."""

        from gui.summary_dialog import SummaryDialog



        dlg = SummaryDialog(

            completed=5,

            skipped=2,

            failed=1,

            total=8,

            download_folder="C:/ChannelHarvest/Test",

            skipped_private=1,

            skipped_unavailable=1,

            skipped_existing=0,

        )

        try:

            self.assertEqual(dlg.windowTitle(), "下載佇列完成")

            self.assertEqual(dlg.open_folder_btn.text(), "📁 開啟下載資料夾")

            self.assertEqual(dlg.close_btn.text(), "關閉")

        finally:

            dlg.close()



    def test_error_classifier_localization_zh_tw(self):

        """Verify error classification and suggested actions localize into Traditional Chinese."""

        err = DownloadError(

            title="Video download failed",

            category=ErrorCategory.HTTP_403,

            user_message="YouTube server rejected stream request.",

            suggested_action="Wait a bit and retry.",

            technical_details="HTTP 403 Forbidden",

            platform="youtube",

        )



        self.assertEqual(err.get_localized_title(), "影片下載失敗")

        self.assertIn("YouTube 伺服器暫時拒絕了視訊與音訊串流的擷取請求", err.get_localized_user_message())

        self.assertIn("避免同時並行下載大量影片", err.get_localized_suggested_action())





class TestThemeAndLanguageIndependence(unittest.TestCase):

    """Verifies acceptance criteria 10, 11, 12: Light/Dark mode rendering, independence."""



    def setUp(self):

        self.orig_lang = I18nManager.get_language()

        self.orig_theme = ThemeManager.current_preference()



    def tearDown(self):

        I18nManager.set_language(self.orig_lang)

        ThemeManager.apply_theme(self.orig_theme)



    def test_font_family_selection(self):

        """Verify Taiwan Traditional Chinese font stack includes Microsoft JhengHei UI."""

        I18nManager.set_language("zh_TW")

        font_tw = get_font_family()

        self.assertIn("Microsoft JhengHei", font_tw)



        I18nManager.set_language("zh_CN")

        font_cn = get_font_family()

        self.assertIn("Noto Sans SC", font_cn)



        I18nManager.set_language("en")

        font_en = get_font_family()

        self.assertIn("Segoe UI", font_en)



    def test_theme_and_language_are_independent(self):

        """Criterion 11 & 12: Switching languages does not alter theme; switching themes does not alter language."""

        ThemeManager.apply_theme(ThemeMode.DARK)

        self.assertTrue(ThemeManager.is_dark())



        # Switch language to zh_TW -> theme must remain DARK

        I18nManager.set_language("zh_TW")

        self.assertTrue(ThemeManager.is_dark())

        self.assertEqual(I18nManager.get_language(), "zh_TW")



        # Switch theme to LIGHT -> language must remain zh_TW

        ThemeManager.apply_theme(ThemeMode.LIGHT)

        self.assertFalse(ThemeManager.is_dark())

        self.assertEqual(I18nManager.get_language(), "zh_TW")



        # Switch language to en -> theme must remain LIGHT

        I18nManager.set_language("en")

        self.assertFalse(ThemeManager.is_dark())

        self.assertEqual(I18nManager.get_language(), "en")





class TestVideoModelAndPlatformBehavior(unittest.TestCase):

    """Verifies acceptance criteria 13, 14: inaccessible video detection, platform compatibility."""



    def test_inaccessible_video_traditional_chinese_strings(self):

        """Verify VideoItem correctly classifies private and unavailable videos with zh_TW strings."""

        # Private video in Traditional Chinese

        item_priv = VideoItem(

            index=1,

            video_id="priv1",

            title="[私人影片]",

            duration="02:00",

            status="私人影片",

        )

        self.assertTrue(item_priv.is_private)

        self.assertFalse(item_priv.is_unavailable)

        self.assertTrue(item_priv.is_inaccessible)



        # Unavailable video in Traditional Chinese

        item_unavail = VideoItem(

            index=2,

            video_id="unavail1",

            title="[無法播放影片]",

            duration="00:00",

            status="影片無法播放",

        )

        self.assertFalse(item_unavail.is_private)

        self.assertTrue(item_unavail.is_unavailable)

        self.assertTrue(item_unavail.is_inaccessible)



    def test_douyin_disabled_state_localization(self):

        """Criterion 14: Douyin disabled behavior remains intact with proper Traditional Chinese message."""
        orig = I18nManager.get_language()
        try:
            I18nManager.set_language("zh_TW")

            self.assertEqual(tr("platform_douyin"), "抖音")

            self.assertEqual(tr("platform_douyin_unavailable_tooltip"), "暫時無法使用 — 等待 yt-dlp 上游修復。")

            self.assertEqual(tr("platform_temporarily_unavailable_title"), "平台暫時無法使用")

            self.assertIn("ArgusSecurityPlugin", tr("platform_douyin_unavailable_msg"))
        finally:
            I18nManager.set_language(orig)





if __name__ == "__main__":

    unittest.main()

