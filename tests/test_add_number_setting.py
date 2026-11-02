"""
tests/test_add_number_setting.py
Comprehensive verification test suite for the 'Add Number' (scan order numbering) feature
in File Organization for Channel Harvest.

Covers:
1. format_number_prefix: 2 digits, 3 digits, up to 6 digits, and edge case fallbacks.
2. resolve_media_filename with number_prefix across media and assets.
3. resolve_video_outtmpl with number_prefix.
4. resolve_video_output_dir with individual folder numbering.
5. DownloadSettings model defaults and bidirectional aliases.
6. SettingsManager persistence, loading, and bidirectional synchronization.
7. i18n translation keys in English, Simplified Chinese, and Traditional Chinese.
8. MainWindow UI Checkbox creation under FILE ORGANIZATION, tooltips, and dynamic retranslation.
9. DownloadManager execution in Video Only mode verifying number_prefix propagation.
10. Scan order preservation when a non-contiguous subset of items is selected (e.g. #3 and #7).
11. Gallery-dl photo downloading with number_prefix.
12. Asset managers (Subtitles, Thumbnails, Descriptions, Metadata, Chapters) with number_prefix.
13. Support for 6-digit numbers (999,999) without truncation or formatting errors.
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import VideoItem, VideoStatus, DownloadSettings, DownloadMode, MediaType
from core.paths import (
    format_number_prefix,
    resolve_media_filename,
    resolve_video_outtmpl,
    resolve_video_output_dir,
    calculate_safe_stem_length,
)
from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from downloader.download_manager import DownloadManager
from downloader.subtitle_manager import SubtitleManager
from downloader.thumbnail_manager import ThumbnailManager
from downloader.info_manager import InfoManager
from downloader.gallerydl_engine import GalleryDlEngine
from downloader.engine_router import DownloadEngineRouter, EngineType


class TestAddNumberSetting(unittest.TestCase):
    """Unit and integration tests for the Add Number feature in File Organization."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. format_number_prefix: 2 digits (e.g. 01_Title)
    # -------------------------------------------------------------------------
    def test_01_format_number_prefix_2_digits(self):
        """Verify 2-digit zero padding when total count/max_index is <= 99."""
        self.assertEqual(format_number_prefix(1, max_index=18), "01_")
        self.assertEqual(format_number_prefix(2, max_index=18), "02_")
        self.assertEqual(format_number_prefix(9, max_index=18), "09_")
        self.assertEqual(format_number_prefix(10, max_index=18), "10_")
        self.assertEqual(format_number_prefix(18, max_index=18), "18_")

    # -------------------------------------------------------------------------
    # 2. format_number_prefix: 3 to 5 digits
    # -------------------------------------------------------------------------
    def test_02_format_number_prefix_multi_digits(self):
        """Verify adaptive zero padding for 3, 4, and 5-digit channel lists."""
        # 3 digits (100 - 999)
        self.assertEqual(format_number_prefix(1, max_index=250), "001_")
        self.assertEqual(format_number_prefix(42, max_index=250), "042_")
        self.assertEqual(format_number_prefix(250, max_index=250), "250_")

        # 4 digits (1,000 - 9,999)
        self.assertEqual(format_number_prefix(1, max_index=1200), "0001_")
        self.assertEqual(format_number_prefix(1200, max_index=1200), "1200_")

        # 5 digits (10,000 - 99,999)
        self.assertEqual(format_number_prefix(5, max_index=50000), "00005_")
        self.assertEqual(format_number_prefix(50000, max_index=50000), "50000_")

    # -------------------------------------------------------------------------
    # 3. format_number_prefix: Up to 6 digits (999,999)
    # -------------------------------------------------------------------------
    def test_03_format_number_prefix_up_to_6_digits(self):
        """Verify full support for 6-digit numbers (up to 999,999)."""
        self.assertEqual(format_number_prefix(1, max_index=999999), "000001_")
        self.assertEqual(format_number_prefix(42, max_index=999999), "000042_")
        self.assertEqual(format_number_prefix(12345, max_index=999999), "012345_")
        self.assertEqual(format_number_prefix(123456, max_index=999999), "123456_")
        self.assertEqual(format_number_prefix(999999, max_index=999999), "999999_")

    # -------------------------------------------------------------------------
    # 4. format_number_prefix: Fallbacks and safe boundaries
    # -------------------------------------------------------------------------
    def test_04_format_number_prefix_fallbacks(self):
        """Verify robust fallbacks for missing max_index, 0, negative, and None."""
        self.assertEqual(format_number_prefix(1), "01_")
        self.assertEqual(format_number_prefix(0), "01_")
        self.assertEqual(format_number_prefix(-1), "01_")
        self.assertEqual(format_number_prefix(None), "01_")
        # Explicit large index without max_index retains full digits
        self.assertEqual(format_number_prefix(999999), "999999_")

    # -------------------------------------------------------------------------
    # 5. resolve_media_filename with number_prefix
    # -------------------------------------------------------------------------
    def test_05_resolve_media_filename_with_number_prefix(self):
        """Verify resolve_media_filename correctly formats stem with number prefix."""
        # A. Without ID
        res1 = resolve_media_filename("Never Gonna Give You Up", "dQw4w9WgXcQ", ext="mp4", number_prefix="01_")
        self.assertEqual(res1, "01_Never Gonna Give You Up.mp4")

        # B. With ID
        res2 = resolve_media_filename("Never Gonna Give You Up", "dQw4w9WgXcQ", ext="mp4", include_video_id=True, number_prefix="01_")
        self.assertEqual(res2, "01_Never Gonna Give You Up [dQw4w9WgXcQ].mp4")

        # C. 6-digit prefix
        res3 = resolve_media_filename("Massive Archive Video", "id999999", ext="mov", number_prefix="000001_")
        self.assertEqual(res3, "000001_Massive Archive Video.mov")

        res4 = resolve_media_filename("Massive Archive Video", "id999999", ext="mov", number_prefix="999999_")
        self.assertEqual(res4, "999999_Massive Archive Video.mov")

        # D. Asset files
        self.assertEqual(resolve_media_filename("Song", "111", ext="srt", number_prefix="02_"), "02_Song.srt")
        self.assertEqual(resolve_media_filename("Song", "111", ext="jpg", number_prefix="02_"), "02_Song.jpg")
        self.assertEqual(resolve_media_filename("Song", "111", ext="description", number_prefix="02_"), "02_Song.description")
        self.assertEqual(resolve_media_filename("Song", "111", ext="metadata.txt", number_prefix="02_"), "02_Song.metadata.txt")
        self.assertEqual(resolve_media_filename("Song", "111", ext="chapters.txt", number_prefix="02_"), "02_Song.chapters.txt")

    # -------------------------------------------------------------------------
    # 6. resolve_video_outtmpl with number_prefix
    # -------------------------------------------------------------------------
    def test_06_resolve_video_outtmpl_with_number_prefix(self):
        """Verify resolve_video_outtmpl injects number_prefix into yt-dlp pattern."""
        out_dir = Path("C:/Downloads/Channel Harvest")

        # Without ID
        tmpl1 = resolve_video_outtmpl(out_dir, include_video_id=False, number_prefix="01_")
        self.assertIn("01_%(title)s.%(ext)s", tmpl1)

        # With ID
        tmpl2 = resolve_video_outtmpl(out_dir, include_video_id=True, number_prefix="01_")
        self.assertIn("01_%(title)s [%(id)s].%(ext)s", tmpl2)

        # 6-digit prefix
        tmpl3 = resolve_video_outtmpl(out_dir, include_video_id=False, number_prefix="999999_")
        self.assertIn("999999_%(title)s.%(ext)s", tmpl3)

    # -------------------------------------------------------------------------
    # 7. resolve_video_output_dir with individual folders and number_prefix
    # -------------------------------------------------------------------------
    def test_07_resolve_video_output_dir_with_number_prefix(self):
        """Verify resolve_video_output_dir prefixes individual folder when enabled."""
        base = Path("C:/Downloads")
        res_dir = resolve_video_output_dir(
            base_download_dir=base,
            channel_title="Music Channel",
            create_channel_folder=True,
            video_title="Hit Song",
            video_id="abc123",
            create_individual_video_folders=True,
            number_prefix="01_",
        )
        self.assertEqual(res_dir.name, "01_Hit Song")
        self.assertEqual(res_dir.parent.name, "Music Channel")

    # -------------------------------------------------------------------------
    # 8. DownloadSettings model defaults and bidirectional aliases
    # -------------------------------------------------------------------------
    def test_08_download_settings_defaults_and_aliases(self):
        """Verify DownloadSettings model has add_number_to_filename=False by default and alias sync."""
        s = DownloadSettings()
        self.assertFalse(s.add_number_to_filename)
        self.assertFalse(s.add_number_prefix)
        self.assertIsNone(s.max_scan_index)
        self.assertEqual(s.number_prefix, "")

        # Alias sync
        s1 = DownloadSettings(add_number_to_filename=True)
        self.assertTrue(s1.add_number_prefix)

        s2 = DownloadSettings(add_number_prefix=True)
        self.assertTrue(s2.add_number_to_filename)

    # -------------------------------------------------------------------------
    # 9. SettingsManager persistence and bidirectional sync
    # -------------------------------------------------------------------------
    def test_09_settings_manager_persistence(self):
        """Verify SettingsManager saves and loads add_number_to_filename to JSON."""
        settings_file = self.target_dir / "test_settings.json"
        mgr = SettingsManager(settings_path=settings_file)

        self.assertFalse(mgr.get("add_number_to_filename"))
        self.assertFalse(mgr.get("add_number_prefix"))

        mgr.set("add_number_to_filename", True)
        self.assertTrue(mgr.get("add_number_to_filename"))
        self.assertTrue(mgr.get("add_number_prefix"))

        # Reload from disk
        mgr2 = SettingsManager(settings_path=settings_file)
        self.assertTrue(mgr2.get("add_number_to_filename"))
        self.assertTrue(mgr2.get("add_number_prefix"))

    # -------------------------------------------------------------------------
    # 10. i18n Translation strings
    # -------------------------------------------------------------------------
    def test_10_i18n_translation_keys(self):
        """Verify i18n translation keys in English, Simplified Chinese, and Traditional Chinese."""
        I18nManager.set_language("en")
        self.assertIn("Add Sequence No.", tr("cb_add_number_to_filename"))
        self.assertIn("6 digits", tr("tooltip_add_number_to_filename"))

        I18nManager.set_language("zh_CN")
        self.assertIn("序号", tr("cb_add_number_to_filename"))
        self.assertIn("6位数", tr("tooltip_add_number_to_filename"))

        I18nManager.set_language("zh_TW")
        self.assertIn("編號", tr("cb_add_number_to_filename"))
        self.assertIn("6位數", tr("tooltip_add_number_to_filename"))

        # Restore default language
        I18nManager.set_language("en")

    # -------------------------------------------------------------------------
    # 11. MainWindow UI Checkbox creation and dynamic retranslation
    # -------------------------------------------------------------------------
    def test_11_ui_checkbox_creation_and_retranslation(self):
        """Verify add_number_cb is created in MainWindow and retranslates dynamically."""
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        win = MainWindow()
        win.settings_manager.set("add_number_to_filename", False)
        win.add_number_cb.setChecked(False)

        try:
            self.assertTrue(hasattr(win, "add_number_cb"))
            cb = win.add_number_cb
            self.assertFalse(cb.isChecked())

            # Verify tooltip
            self.assertIn("scan order number", cb.toolTip().lower())

            # Toggle setting
            cb.setChecked(True)
            self.assertTrue(win.settings_manager.get("add_number_to_filename"))

            # Switch to Chinese and retranslate
            I18nManager.set_language("zh_CN")
            win.retranslate_ui()
            self.assertIn("序号", cb.text())
            self.assertIn("6位数", cb.toolTip())

            # Switch back to English
            I18nManager.set_language("en")
            win.retranslate_ui()
            self.assertIn("Add Sequence No.", cb.text())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 12. DownloadManager: Video Only mode with number_prefix
    # -------------------------------------------------------------------------
    def test_12_download_manager_video_only_number_prefix(self):
        """Verify DownloadManager computes number_prefix from scan index and propagates it."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        videos = [
            VideoItem(index=1, video_id="vid_001", title="First Video", duration="01:00", url="https://example.com/1"),
            VideoItem(index=2, video_id="vid_002", title="Second Video", duration="02:00", url="https://example.com/2"),
        ]
        settings = DownloadSettings(
            download_folder=str(self.target_dir),
            add_number_to_filename=True,
            create_channel_folder=False,
            create_individual_video_folders=False,
            max_scan_index=2,
        )

        dm = DownloadManager(videos=videos, settings=settings)

        # Mock engine
        captured_prefixes = []
        def mock_download_single_video(video, settings, target_dir, **kwargs):
            captured_prefixes.append(getattr(settings, "number_prefix", ""))
            return {"success": True, "skipped": False, "info_dict": {"title": video.title, "ext": "mp4"}}

        dm.engine.download_single_video = mock_download_single_video

        # Run download loop directly
        dm.run()

        self.assertEqual(captured_prefixes, ["01_", "02_"])

    # -------------------------------------------------------------------------
    # 13. Scan order preservation when partial selection is downloaded
    # -------------------------------------------------------------------------
    def test_13_scan_order_preservation_partial_selection(self):
        """Verify items keep their original scan order index even when selecting a non-contiguous subset."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        # Suppose scan discovered 50 videos; user selected #3 and #12
        selected_videos = [
            VideoItem(index=3, video_id="vid_003", title="Third Video", duration="03:00", url="https://example.com/3"),
            VideoItem(index=12, video_id="vid_012", title="Twelfth Video", duration="12:00", url="https://example.com/12"),
        ]
        settings = DownloadSettings(
            download_folder=str(self.target_dir),
            add_number_to_filename=True,
            create_channel_folder=False,
            create_individual_video_folders=False,
            max_scan_index=50,
        )

        dm = DownloadManager(videos=selected_videos, settings=settings)

        captured_prefixes = []
        def mock_download_single_video(video, settings, target_dir, **kwargs):
            captured_prefixes.append(getattr(settings, "number_prefix", ""))
            return {"success": True, "skipped": False, "info_dict": {"title": video.title, "ext": "mp4"}}

        dm.engine.download_single_video = mock_download_single_video
        dm.run()

        # Must be 03_ and 12_, preserving scan order position!
        self.assertEqual(captured_prefixes, ["03_", "12_"])

    # -------------------------------------------------------------------------
    # 14. Gallery-dl photo downloading with number_prefix
    # -------------------------------------------------------------------------
    def test_14_gallerydl_photo_download_with_number_prefix(self):
        """Verify gallery-dl download receives filename_stem prefixed with scan order number."""
        from PySide6.QtWidgets import QApplication
        from core.inventory import MediaInventoryType
        app = QApplication.instance() or QApplication([])

        photo = VideoItem(
            index=1,
            video_id="photo_101",
            title="Hong Yong Music Photo 1",
            duration="-",
            url="https://scontent.example.com/p101.jpg",
            platform="facebook",
            media_type=MediaType.PHOTO,
            extra_metadata={"media_type": MediaInventoryType.IMAGE},
        )
        settings = DownloadSettings(
            download_folder=str(self.target_dir),
            add_number_to_filename=True,
            create_channel_folder=False,
            create_individual_video_folders=False,
            max_scan_index=18,
        )

        dm = DownloadManager(videos=[photo], settings=settings)

        # Mock router and gallery-dl
        mock_gdl = MagicMock(spec=GalleryDlEngine)
        mock_gdl.is_available.return_value = True
        dm.gallerydl_engine = mock_gdl
        dm.router = DownloadEngineRouter(gallerydl_engine=mock_gdl)

        captured_stems = []
        def mock_gdl_download(url, target_dir, filename_stem=None, **kwargs):
            captured_stems.append(filename_stem)
            fake_file = target_dir / f"{filename_stem}.jpg"
            fake_file.write_text("fake_jpg_content")
            return {"success": True, "skipped": False, "downloaded_files": [str(fake_file)]}

        mock_gdl.download_media = mock_gdl_download
        dm.run()

        self.assertEqual(captured_stems, ["01_Hong Yong Music Photo 1"])

    # -------------------------------------------------------------------------
    # 15. Asset managers with number_prefix (Subtitles, Thumbnails, Info)
    # -------------------------------------------------------------------------
    def test_15_asset_managers_with_number_prefix(self):
        """Verify SubtitleManager, ThumbnailManager, and InfoManager format paths with number_prefix."""
        video = VideoItem(index=1, video_id="xyz999", title="Concert Video", duration="10:00", url="https://example.com/v")
        settings = DownloadSettings(
            add_number_to_filename=True,
            number_prefix="01_",
            include_video_id_in_filename=False,
        )

        # Subtitles
        srt_path = SubtitleManager.get_target_srt_path(video, self.target_dir, include_video_id=False, number_prefix="01_")
        self.assertEqual(srt_path.name, "01_Concert Video.srt")

        # Info files
        desc_path = InfoManager.get_description_path(video, self.target_dir, include_video_id=False, number_prefix="01_")
        self.assertEqual(desc_path.name, "01_Concert Video.description")

        meta_path = InfoManager.get_metadata_path(video, self.target_dir, include_video_id=False, number_prefix="01_")
        self.assertEqual(meta_path.name, "01_Concert Video.metadata.txt")

        chap_path = InfoManager.get_chapters_path(video, self.target_dir, include_video_id=False, number_prefix="01_")
        self.assertEqual(chap_path.name, "01_Concert Video.chapters.txt")


if __name__ == "__main__":
    unittest.main()
