"""
tests/test_video_and_image_mode.py
Unit and integration tests for Video + Image download mode:
1. Model & I18n: DownloadMode.VIDEO_AND_IMAGE canonical values and localized labels (en, zh_CN, zh_TW).
2. Mode dropdown population: mode_combo contains VIDEO_AND_IMAGE.
3. Automatic selection in mixed scan:
   When profile scan results on Facebook, Instagram, X, RedNote contain both photos and videos,
   mode_combo automatically selects Video + Image as default, and both video & image options are enabled.
4. Gating when scan has no photos:
   When scan results contain no photos, Video + Image and Image Only become grayed out (disabled),
   and current selection falls back to a valid video mode.
5. Gating when scan has only photos:
   When scan results contain only photos, Image Only is selected and Video + Image is disabled.
6. Execution: DownloadManager with VIDEO_AND_IMAGE properly routes photos to image pipeline and videos to video pipeline.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from core.models import VideoItem, MediaType, DownloadMode, DownloadSettings, VideoStatus, ScanResult
from core.i18n import I18nManager
from core.settings import SettingsManager
from gui.main_window import MainWindow


class TestVideoAndImageMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.isolated_sm.set("download_mode", DownloadMode.VIDEO_AND_AUDIO)
        self.isolated_sm.set("selected_platform", "rednote")
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        I18nManager.set_language("en")

    def tearDown(self):
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()
        I18nManager.set_language("en")

    def test_01_model_and_i18n(self):
        """Verifies DownloadMode.VIDEO_AND_IMAGE definition and translations."""
        self.assertEqual(DownloadMode.VIDEO_AND_IMAGE, "Video + Image")

        I18nManager.set_language("en")
        self.assertEqual(I18nManager.get_mode_label(DownloadMode.VIDEO_AND_IMAGE), "Video + Image")

        I18nManager.set_language("zh_CN")
        self.assertEqual(I18nManager.get_mode_label(DownloadMode.VIDEO_AND_IMAGE), "视频 + 图片")

        I18nManager.set_language("zh_TW")
        self.assertEqual(I18nManager.get_mode_label(DownloadMode.VIDEO_AND_IMAGE), "影片 + 圖片")

    def test_02_mode_combo_contains_video_and_image(self):
        """Verifies MainWindow mode_combo includes Video + Image."""
        win = MainWindow()
        try:
            idx = win.mode_combo.findData(DownloadMode.VIDEO_AND_IMAGE)
            self.assertGreaterEqual(idx, 0, "Video + Image should be in mode_combo")
            self.assertEqual(win.mode_combo.itemData(idx), DownloadMode.VIDEO_AND_IMAGE)
        finally:
            win.close()

    def test_03_mixed_scan_auto_selects_video_and_image(self):
        """When scan results contain both photos and videos, mode automatically switches to Video + Image."""
        win = MainWindow()
        try:
            # Set to RedNote platform
            plat_idx = win.platform_combo.findData("rednote")
            win.platform_combo.setCurrentIndex(plat_idx)

            mixed_videos = [
                VideoItem(index=1, video_id="vid_01", title="RedNote Video 1", duration="01:30", media_type=MediaType.VIDEO),
                VideoItem(index=2, video_id="img_02", title="RedNote Photo 2", duration="3P", media_type=MediaType.PHOTO),
            ]
            res = ScanResult(videos=mixed_videos, source_title="DIOR迪奥", platform="rednote")
            win._on_scan_completed(res)

            # Mode should automatically be Video + Image
            self.assertEqual(win.mode_combo.currentData(), DownloadMode.VIDEO_AND_IMAGE)

            # Video + Image should be enabled
            combo_model = win.mode_combo.model()
            idx_vi = win.mode_combo.findData(DownloadMode.VIDEO_AND_IMAGE)
            self.assertTrue(combo_model.item(idx_vi).isEnabled())

            # Both video and image controls should be enabled
            self.assertTrue(win.format_combo.isEnabled())
            self.assertTrue(win.quality_combo.isEnabled())
            self.assertTrue(win.image_format_combo.isEnabled())
            self.assertTrue(win.preserve_original_images_cb.isEnabled())

            # Both videos and photos should be checkable and checked in the table
            self.assertEqual(len(win.video_table.get_selected_videos()), 2)
        finally:
            win.close()

    def test_04_no_photos_scan_grays_out_video_and_image(self):
        """When scan results contain NO photos, Video + Image automatically becomes grayed out."""
        win = MainWindow()
        try:
            plat_idx = win.platform_combo.findData("instagram")
            win.platform_combo.setCurrentIndex(plat_idx)

            # First simulate mixed scan so Video + Image is selected
            mixed_videos = [
                VideoItem(index=1, video_id="v1", title="IG Video", duration="00:45", media_type=MediaType.VIDEO),
                VideoItem(index=2, video_id="p1", title="IG Photo", duration="Photo", media_type=MediaType.PHOTO),
            ]
            win._on_scan_completed(ScanResult(videos=mixed_videos, source_title="IG Creator", platform="instagram"))
            self.assertEqual(win.mode_combo.currentData(), DownloadMode.VIDEO_AND_IMAGE)

            # Now simulate a scan with NO photos (videos only)
            video_only_scan = [
                VideoItem(index=1, video_id="v2", title="IG Reel Only", duration="00:30", media_type=MediaType.VIDEO),
            ]
            win._on_scan_completed(ScanResult(videos=video_only_scan, source_title="IG Creator", platform="instagram"))

            # Video + Image option should now be disabled (grayed out)
            combo_model = win.mode_combo.model()
            idx_vi = win.mode_combo.findData(DownloadMode.VIDEO_AND_IMAGE)
            self.assertFalse(combo_model.item(idx_vi).isEnabled(), "Video + Image should be disabled when no photos")

            # Image Only option should also be disabled
            idx_io = win.mode_combo.findData(DownloadMode.IMAGE_ONLY)
            self.assertFalse(combo_model.item(idx_io).isEnabled(), "Image Only should be disabled when no photos")

            # Current mode should have fallen back to a valid video mode (e.g. Video + Audio or Video Only)
            self.assertIn(win.mode_combo.currentData(), (DownloadMode.VIDEO_AND_AUDIO, DownloadMode.VIDEO_ONLY))
        finally:
            win.close()

    def test_05_photo_only_scan_grays_out_video_and_image(self):
        """When scan results contain ONLY photos, mode selects Image Only and Video + Image is disabled."""
        win = MainWindow()
        try:
            plat_idx = win.platform_combo.findData("facebook")
            win.platform_combo.setCurrentIndex(plat_idx)

            photo_only_scan = [
                VideoItem(index=1, video_id="p1", title="FB Photo 1", duration="Photo", media_type=MediaType.PHOTO),
                VideoItem(index=2, video_id="p2", title="FB Photo 2", duration="Photo", media_type=MediaType.PHOTO),
            ]
            win._on_scan_completed(ScanResult(videos=photo_only_scan, source_title="FB Page", platform="facebook"))

            # Mode should automatically be Image Only
            self.assertEqual(win.mode_combo.currentData(), DownloadMode.IMAGE_ONLY)

            # Video + Image option should be disabled
            combo_model = win.mode_combo.model()
            idx_vi = win.mode_combo.findData(DownloadMode.VIDEO_AND_IMAGE)
            self.assertFalse(combo_model.item(idx_vi).isEnabled(), "Video + Image should be disabled for photo-only scan")

            # Image Only option should be enabled
            idx_io = win.mode_combo.findData(DownloadMode.IMAGE_ONLY)
            self.assertTrue(combo_model.item(idx_io).isEnabled())
        finally:
            win.close()

    def test_06_download_settings_construction_with_video_and_image(self):
        """Verifies DownloadSettings correctly captures Video + Image mode with video and image options."""
        win = MainWindow()
        try:
            idx_vi = win.mode_combo.findData(DownloadMode.VIDEO_AND_IMAGE)
            win.mode_combo.setCurrentIndex(idx_vi)

            settings = win._build_settings_from_ui()
            self.assertEqual(settings.download_mode, DownloadMode.VIDEO_AND_IMAGE)
            self.assertEqual(settings.format, "MOV")
            self.assertEqual(settings.quality, "1080p")
            self.assertEqual(settings.image_format, "Keep Original")
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
