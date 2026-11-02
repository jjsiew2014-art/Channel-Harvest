"""
test_summary_lyrics_notice.py
Unit tests verifying the Download Queue Complete window (SummaryDialog)
presentation of the lyrics not found notice when the user has enabled
LRC download and/or tag embedding options.
"""

import sys
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from core.i18n import I18nManager, tr
from core.models import VideoItem, VideoStatus, DownloadSettings
from gui.summary_dialog import SummaryDialog
from downloader.download_manager import DownloadManager


class TestSummaryLyricsNotice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_01_no_lyrics_notice_when_not_enabled(self):
        """When user did not enable lyrics options, no notice box is created."""
        dlg = SummaryDialog(
            completed=3,
            skipped=0,
            failed=0,
            total=3,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=False,
            lyrics_not_found=0,
        )
        try:
            self.assertFalse(hasattr(dlg, "lyrics_notice_box"))
        finally:
            dlg.close()

    def test_02_no_lyrics_notice_when_all_lyrics_found(self):
        """When lyrics options were enabled and all lyrics were successfully found (not_found=0), no notice box is created."""
        dlg = SummaryDialog(
            completed=3,
            skipped=0,
            failed=0,
            total=3,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=True,
            embed_lyrics_enabled=True,
            lyrics_not_found=0,
        )
        try:
            self.assertFalse(hasattr(dlg, "lyrics_notice_box"))
        finally:
            dlg.close()

    def test_03_lyrics_notice_displayed_when_both_options_enabled(self):
        """When both Download LRC and Embed Lyrics options were enabled and lyrics were missing, display combined notice."""
        # Test English
        I18nManager.set_language("en")
        dlg_en = SummaryDialog(
            completed=2,
            skipped=0,
            failed=0,
            total=2,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=True,
            embed_lyrics_enabled=True,
            lyrics_not_found=2,
        )
        try:
            self.assertTrue(hasattr(dlg_en, "lyrics_notice_box"))
            self.assertTrue(hasattr(dlg_en, "lyrics_notice_lbl"))
            expected_en = tr("summary_lyrics_not_found_both", count=2)
            self.assertEqual(dlg_en.lyrics_notice_lbl.text(), expected_en)
            self.assertIn("Synchronized LRC lyrics could not be found for 2 song(s)", dlg_en.lyrics_notice_lbl.text())
        finally:
            dlg_en.close()

        # Test Simplified Chinese (zh_CN)
        I18nManager.set_language("zh_CN")
        dlg_zh = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=True,
            embed_lyrics_enabled=True,
            lyrics_not_found=1,
        )
        try:
            self.assertTrue(hasattr(dlg_zh, "lyrics_notice_box"))
            expected_zh = tr("summary_lyrics_not_found_both", count=1)
            self.assertEqual(dlg_zh.lyrics_notice_lbl.text(), expected_zh)
            self.assertIn("提示：未检索到 1 首歌曲的相应同步 LRC 歌词，已跳过歌词文件导出与音频标签嵌入。", dlg_zh.lyrics_notice_lbl.text())
        finally:
            dlg_zh.close()

        # Test Traditional Chinese (zh_TW)
        I18nManager.set_language("zh_TW")
        dlg_tw = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=True,
            embed_lyrics_enabled=True,
            lyrics_not_found=1,
        )
        try:
            self.assertTrue(hasattr(dlg_tw, "lyrics_notice_box"))
            expected_tw = tr("summary_lyrics_not_found_both", count=1)
            self.assertEqual(dlg_tw.lyrics_notice_lbl.text(), expected_tw)
            self.assertIn("提示：未檢索到 1 首歌曲的相應同步 LRC 歌詞，已略過歌詞檔案匯出與音訊標籤嵌入。", dlg_tw.lyrics_notice_lbl.text())
        finally:
            I18nManager.set_language("en")
            dlg_tw.close()

    def test_04_lyrics_notice_when_only_download_lrc_enabled(self):
        """When only Download LRC Lyrics was enabled and lyrics were missing, display export notice."""
        I18nManager.set_language("zh_CN")
        dlg = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=True,
            embed_lyrics_enabled=False,
            lyrics_not_found=1,
        )
        try:
            self.assertTrue(hasattr(dlg, "lyrics_notice_box"))
            self.assertEqual(
                dlg.lyrics_notice_lbl.text(),
                "提示：未检索到 1 首歌曲的相应同步 LRC 歌词，已跳过歌词文件导出。",
            )
        finally:
            I18nManager.set_language("en")
            dlg.close()

    def test_05_lyrics_notice_when_only_embed_lyrics_enabled(self):
        """When only Embed Lyrics was enabled and lyrics were missing, display embedding notice."""
        I18nManager.set_language("zh_CN")
        dlg = SummaryDialog(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
            download_folder="C:/Downloads/Test",
            lyrics_enabled=True,
            download_lrc_enabled=False,
            embed_lyrics_enabled=True,
            lyrics_not_found=1,
        )
        try:
            self.assertTrue(hasattr(dlg, "lyrics_notice_box"))
            self.assertEqual(
                dlg.lyrics_notice_lbl.text(),
                "提示：未检索到 1 首歌曲的相应同步 LRC 歌词，已跳过音频标签嵌入。",
            )
        finally:
            I18nManager.set_language("en")
            dlg.close()

    def test_06_download_manager_get_queue_statistics_tracks_lyrics_not_found(self):
        """Verify DownloadManager.get_queue_statistics accurately calculates lyrics_not_found."""
        settings = DownloadSettings(
            download_folder="C:/Downloads/Test",
            download_lrc_lyrics=True,
            embed_lyrics=True,
        )
        v1 = VideoItem(index=1, video_id="vid1", title="Song 1", duration="3:30", status=VideoStatus.COMPLETED)
        v1._lrc_found = True

        v2 = VideoItem(index=2, video_id="vid2", title="Song 2", duration="4:00", status=VideoStatus.COMPLETED)
        v2._lrc_found = False

        v3 = VideoItem(index=3, video_id="vid3", title="Song 3", duration="2:45", status=VideoStatus.SKIPPED)
        v3._lrc_found = False

        from core.error_classifier import ErrorCategory
        v4 = VideoItem(index=4, video_id="vid4", title="Private Song", duration="0:00", status=VideoStatus.SKIPPED)
        v4.extra_metadata["inaccessibility"] = ErrorCategory.PRIVATE_VIDEO

        dm = DownloadManager(videos=[v1, v2, v3, v4], settings=settings)
        stats = dm.get_queue_statistics()

        self.assertTrue(stats["lyrics_enabled"])
        self.assertTrue(stats["download_lrc_enabled"])
        self.assertTrue(stats["embed_lyrics_enabled"])
        # v2 and v3 had lyrics requested and completed/skipped but _lrc_found=False
        # v1 had _lrc_found=True
        # v4 is private, so skipped from lyrics check
        self.assertEqual(stats["lyrics_not_found"], 2)


if __name__ == "__main__":
    unittest.main()
