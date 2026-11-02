"""
Unit and integration tests for LRC Synchronized Lyrics functionality.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import VideoItem, DownloadSettings, DownloadMode
from downloader.lyrics_manager import LyricsManager


class TestLyricsManager(unittest.TestCase):
    def test_01_clean_query_basic(self):
        title = "Axel Lee 李雨壕 - 【车站 Farewell Station】 歌词版 Lyrics MV"
        cleaned = LyricsManager.clean_query(title, "Axel Lee")
        self.assertIn("车站", cleaned)
        self.assertNotIn("MV", cleaned)
        self.assertNotIn("歌词版", cleaned)
        self.assertNotIn("【", cleaned)
        self.assertNotIn("】", cleaned)

    def test_02_clean_query_official_video(self):
        title = "Adele - Hello (Official Music Video)"
        cleaned = LyricsManager.clean_query(title, "Adele")
        self.assertIn("Hello", cleaned)
        self.assertNotIn("Official", cleaned)
        self.assertNotIn("Video", cleaned)

    def test_03_format_supported(self):
        for fmt in ["mp3", "MP3", "M4A", "m4a", "FLAC", "flac", "OPUS", "opus"]:
            self.assertTrue(LyricsManager.is_format_supported(fmt), f"Expected {fmt} to be supported")
        for fmt in ["wav", "WAV", "aac", "AAC", "ogg", "OGG"]:
            self.assertFalse(LyricsManager.is_format_supported(fmt), f"Expected {fmt} to be unsupported")

    def test_04_format_lrc_headers(self):
        raw = "[00:12.34]First line\n[00:15.67]Second line"
        res = LyricsManager.format_lrc(raw, title="Test Song", artist="Test Singer")
        self.assertIn("[ti:Test Song]", res)
        self.assertIn("[ar:Test Singer]", res)
        self.assertIn("[by:ChannelHarvest]", res)
        self.assertIn("[00:12.34]First line", res)

    def test_05_download_lyrics(self, tmp_path_factory=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir)
            video = VideoItem(
                index=1,
                video_id="xyz123",
                title="Song Title",
                duration="03:45",
                channel_title="Artist Name",
            )
            settings = DownloadSettings(
                download_folder=tmp_dir,
                download_lrc_lyrics=True,
                skip_existing=False,
            )

            # Mock fetch_lyrics
            sample_lrc = "[00:01.00]Hello world\n[00:05.00]End"
            with patch.object(LyricsManager, "fetch_lyrics", return_value=sample_lrc):
                res = LyricsManager.download_lyrics(video, settings, target_dir)
                self.assertTrue(res["success"])
                dest_file = res["saved_file"]
                self.assertTrue(dest_file.is_file())
                content = dest_file.read_text(encoding="utf-8")
                self.assertIn("Hello world", content)
                self.assertIn("[by:ChannelHarvest]", content)

                # Test skip_existing
                settings.skip_existing = True
                res2 = LyricsManager.download_lyrics(video, settings, target_dir)
                self.assertTrue(res2["success"])
                self.assertTrue(res2.get("skipped", False))

    def test_06_embed_lyrics_unsupported_wav(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_file = Path(tmp_dir) / "test.wav"
            wav_file.write_bytes(b"RIFF dummy wav data")
            succ = LyricsManager.embed_lyrics(wav_file, "[00:01.00]Lyrics")
            self.assertFalse(succ)


class TestLyricsUIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_07_checkbox_placement_and_initialization(self):
        from gui.main_window import MainWindow
        win = MainWindow()

        # Check Download LRC Lyrics is in Additional Assets
        self.assertTrue(hasattr(win, "download_lrc_cb"))
        # Check parent layout: should be in info_container inside Additional Assets
        self.assertIsNotNone(win.download_lrc_cb.parent())

        # Check Embed Lyrics into Audio Tag is in File Organization
        self.assertTrue(hasattr(win, "embed_lyrics_cb"))
        self.assertIsNotNone(win.embed_lyrics_cb.parent())

        # Verify initial states reflect settings manager
        self.assertEqual(win.download_lrc_cb.isChecked(), win.settings_manager.get("download_lrc_lyrics", False))
        self.assertEqual(win.embed_lyrics_cb.isChecked(), win.settings_manager.get("embed_lyrics", False))
        win.close()

    def test_08_audio_format_gating(self):
        from gui.main_window import MainWindow
        win = MainWindow()

        # Switch mode to Audio Only
        idx = win.mode_combo.findData(DownloadMode.AUDIO_ONLY)
        if idx >= 0:
            win.mode_combo.setCurrentIndex(idx)

        # 1. MP3 -> Embed Lyrics should be enabled
        mp3_idx = win.audio_format_combo.findData("MP3")
        if mp3_idx >= 0:
            win.audio_format_combo.setCurrentIndex(mp3_idx)
        win._update_cover_art_ui()
        self.assertTrue(win.embed_lyrics_cb.isEnabled())

        # Check embed lyrics
        win.embed_lyrics_cb.setChecked(True)
        self.assertTrue(win.embed_lyrics_cb.isChecked())

        # 2. Switch to WAV -> Embed Lyrics must be unchecked and disabled
        wav_idx = win.audio_format_combo.findData("WAV")
        if wav_idx >= 0:
            win.audio_format_combo.setCurrentIndex(wav_idx)
        win._update_cover_art_ui()
        self.assertFalse(win.embed_lyrics_cb.isChecked())
        self.assertFalse(win.embed_lyrics_cb.isEnabled())

        # 3. Switch back to MP3 -> Embed Lyrics should be re-enabled
        if mp3_idx >= 0:
            win.audio_format_combo.setCurrentIndex(mp3_idx)
        win._update_cover_art_ui()
        self.assertTrue(win.embed_lyrics_cb.isEnabled())

        win.close()

    def test_09_download_settings_construction(self):
        from gui.main_window import MainWindow
        win = MainWindow()

        # Check checkboxes
        win.download_lrc_cb.setChecked(True)
        win.embed_lyrics_cb.setEnabled(True)
        win.embed_lyrics_cb.setChecked(True)

        settings = win._build_settings_from_ui()
        self.assertTrue(settings.download_lrc_lyrics)
        self.assertTrue(settings.embed_lyrics)

        # Uncheck
        win.download_lrc_cb.setChecked(False)
        win.embed_lyrics_cb.setChecked(False)
        settings2 = win._build_settings_from_ui()
        self.assertFalse(settings2.download_lrc_lyrics)
        self.assertFalse(settings2.embed_lyrics)

        win.close()

    def test_10_stage_weights_computation(self):
        from downloader.download_manager import DownloadManager
        # Standard media + lyrics
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=False,
            has_thumb=False,
            has_meta=False,
            has_cover=False,
            has_lyrics=True,
        )
        self.assertIn("media", ranges)
        self.assertIn("lyrics", ranges)
        m_start, m_end = ranges["media"]
        l_start, l_end = ranges["lyrics"]
        self.assertEqual(m_start, 0.0)
        self.assertEqual(m_end, l_start)
        self.assertEqual(l_end, 100.0)

        # Assets only mode
        ranges_assets = DownloadManager._compute_stage_weights(
            has_media=False,
            has_sub=True,
            has_thumb=True,
            has_meta=True,
            has_cover=True,
            has_lyrics=True,
        )
        self.assertIn("lyrics", ranges_assets)
        self.assertEqual(len(ranges_assets), 5)
        self.assertEqual(ranges_assets["subtitles"][0], 0.0)
        self.assertEqual(ranges_assets["metadata"][1], 100.0)

    def test_11_retranslate_ui(self):
        from gui.main_window import MainWindow
        from core.i18n import I18nManager
        win = MainWindow()

        # EN
        I18nManager.set_language("en")
        win.retranslate_ui()
        self.assertEqual(win.download_lrc_cb.text(), "Download LRC Lyrics")
        self.assertEqual(win.embed_lyrics_cb.text(), "Embed Lyrics into Audio Tag")

        # zh_CN
        I18nManager.set_language("zh_CN")
        win.retranslate_ui()
        self.assertEqual(win.download_lrc_cb.text(), "下载 LRC 同步歌词")
        self.assertEqual(win.embed_lyrics_cb.text(), "将歌词嵌入音频 Tag")

        # zh_TW
        I18nManager.set_language("zh_TW")
        win.retranslate_ui()
        self.assertEqual(win.download_lrc_cb.text(), "下載 LRC 同步歌詞")
        self.assertEqual(win.embed_lyrics_cb.text(), "將歌詞嵌入音訊 Tag")

        # Restore
        I18nManager.set_language("en")
        win.retranslate_ui()
        win.close()

    def test_12_fetch_lyrics_lrclib_fallback(self):
        sample = "[00:01.00]Direct LRCLIB result\n[00:04.00]End"
        with patch.object(LyricsManager, "_fetch_lrclib_search", return_value=sample):
            res = LyricsManager.fetch_lyrics("Test Song", "Test Artist")
            self.assertIsNotNone(res)
            self.assertIn("Direct LRCLIB result", res)

    def test_14_artist_candidate_expansion(self):
        cands = LyricsManager.expand_artist_candidates("GEM鄧紫棋")
        self.assertIn("G.E.M.", cands)
        self.assertIn("邓紫棋", cands)
        self.assertIn("鄧紫棋", cands)

        jay_cands = LyricsManager.expand_artist_candidates("周杰伦 Jay Chou")
        self.assertIn("周杰伦", jay_cands)
        self.assertIn("Jay Chou", jay_cands)

    def test_15_title_candidate_extraction(self):
        cands = LyricsManager.extract_title_candidates("01_THE SKY", ["G.E.M."])
        self.assertIn("THE SKY", cands)

        cands2 = LyricsManager.extract_title_candidates(
            "Axel Lee 李雨壕 - 【车站 Farewell Station】 歌词版 Lyrics MV",
            ["Axel Lee 李雨壕"]
        )
        self.assertIn("车站", cands2)
        for c in cands2:
            self.assertNotIn("MV", c)
            self.assertNotIn("歌词版", c)

    def test_16_validate_lyrics_rejection(self):
        slayr_lrc = """[00:00.000] 作词 : Evan McDonald
[00:01.000] 作曲 : slayr
[00:02.211][Intro]
Now a nigga want to move a thousand miles away
"""
        gem_cands = ["G.E.M.", "邓紫棋", "鄧紫棋", "GEM"]
        self.assertFalse(LyricsManager.validate_lyrics(slayr_lrc, gem_cands))

        correct_lrc = """[00:14.91] 当我好奇地乱敲着黑白的琴键
[00:18.46] 当我躲在房间乐极忘形地表演
"""
        self.assertTrue(LyricsManager.validate_lyrics(correct_lrc, gem_cands))

    def test_17_gem_the_sky_real_match(self):
        # End-to-end test with live LRCLIB API for G.E.M. THE SKY
        lrc = LyricsManager.fetch_lyrics(
            title="01_THE SKY",
            artist="G.E.M.",
            album="REVELATION",
            duration=279,
            channel_title="GEM鄧紫棋",
        )
        self.assertIsNotNone(lrc)
        self.assertTrue("天空" in lrc)
        self.assertNotIn("slayr", lrc)
        self.assertNotIn("Evan McDonald", lrc)


if __name__ == "__main__":
    unittest.main()
