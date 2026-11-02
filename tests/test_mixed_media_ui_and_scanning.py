"""
test_mixed_media_ui_and_scanning.py
Comprehensive unit and integration tests for:
1. Dual-Engine profile scanning (gallery-dl for photos + yt-dlp for videos/reels).
2. SelectionSummary model and selection-aware UI state in MainWindow.
3. VideoTableWidget 8 columns, headers, type badges, and numeric duration sorting.
4. VideoItem media model invariants (duration normalization for photos vs videos).
5. Settings migration and bidirectional alias synchronization.
6. Pillow image conversion pipeline in DownloadManager.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.models import (
    MediaType,
    SelectionSummary,
    VideoItem,
    VideoStatus,
    DownloadMode,
    DownloadSettings,
    ScanResult,
)
from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from downloader.profile_scan_manager import ProfileScanManager, ScanCompleteness
from downloader.engine_router import DownloadEngineRouter, EngineType
from downloader.download_manager import DownloadManager
from gui.video_table import VideoTableWidget
from gui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestMixedMediaUIAndScanning(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.settings_file = self.test_dir / "settings.json"
        self.settings = SettingsManager(settings_path=self.settings_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Media Model & Duration Invariants
    # -------------------------------------------------------------------------

    def test_video_item_duration_invariants_for_photos(self):
        """Photos must never store 'Photo' in duration; duration='-' and duration_seconds=None."""
        item = VideoItem(
            index=1,
            video_id="photo_123",
            title="A Beautiful Sunset",
            duration="Photo",  # User or extractor passed "Photo" string
            duration_seconds=120,  # Erroneous duration seconds
            url="https://facebook.com/photo/123",
            media_type=MediaType.PHOTO,
        )
        self.assertEqual(item.duration, "-")
        self.assertIsNone(item.duration_seconds)
        self.assertEqual(item.formatted_duration, "-")
        self.assertEqual(item.media_type, MediaType.PHOTO)

    def test_video_item_duration_for_videos_and_reels(self):
        """Videos and Reels must format duration in MM:SS or HH:MM:SS."""
        vid = VideoItem(
            index=2,
            video_id="vid_456",
            title="Cooking Tutorial",
            duration="03:45",
            duration_seconds=225,
            url="https://facebook.com/reel/456",
            media_type=MediaType.REEL,
        )
        self.assertEqual(vid.formatted_duration, "03:45")
        self.assertEqual(vid.duration_seconds, 225)
        self.assertEqual(vid.media_type, MediaType.REEL)

    # -------------------------------------------------------------------------
    # 2. SelectionSummary Model
    # -------------------------------------------------------------------------

    def test_selection_summary_states(self):
        """SelectionSummary accurately represents empty, photo-only, video-only, and mixed selections."""
        # Empty
        s_empty = SelectionSummary(total_count=5, selected_count=0)
        self.assertFalse(s_empty.has_selection)
        self.assertFalse(s_empty.is_photo_only)
        self.assertFalse(s_empty.is_video_only)
        self.assertFalse(s_empty.is_mixed)

        # Photo-only
        s_photo = SelectionSummary(total_count=3, selected_count=3, photo_count=3, video_count=0, reel_count=0)
        self.assertTrue(s_photo.has_selection)
        self.assertTrue(s_photo.is_photo_only)
        self.assertFalse(s_photo.is_video_only)
        self.assertFalse(s_photo.is_mixed)

        # Video-only (videos + reels)
        s_video = SelectionSummary(total_count=3, selected_count=3, photo_count=0, video_count=2, reel_count=1)
        self.assertTrue(s_video.has_selection)
        self.assertFalse(s_video.is_photo_only)
        self.assertTrue(s_video.is_video_only)
        self.assertFalse(s_video.is_mixed)

        # Mixed
        s_mixed = SelectionSummary(total_count=4, selected_count=4, photo_count=2, video_count=1, reel_count=1)
        self.assertTrue(s_mixed.has_selection)
        self.assertFalse(s_mixed.is_photo_only)
        self.assertFalse(s_mixed.is_video_only)
        self.assertTrue(s_mixed.is_mixed)

    # -------------------------------------------------------------------------
    # 3. VideoTableWidget: 8 Columns, Headers, Badges, Numeric Duration Sorting
    # -------------------------------------------------------------------------

    def test_video_table_columns_and_headers(self):
        """VideoTableWidget must expose 8 columns with Media Title, Media Type, Duration, Media ID headers."""
        table = VideoTableWidget()
        try:
            self.assertEqual(table.table.columnCount(), 8)
            self.assertEqual(table.COL_SELECT, 0)
            self.assertEqual(table.COL_INDEX, 1)
            self.assertEqual(table.COL_TITLE, 2)
            self.assertEqual(table.COL_TYPE, 3)
            self.assertEqual(table.COL_DURATION, 4)
            self.assertEqual(table.COL_SUBTITLE, 5)
            self.assertEqual(table.COL_VIDEO_ID, 6)
            self.assertEqual(table.COL_STATUS, 7)

            headers = [table.table.horizontalHeaderItem(i).text() for i in range(8)]
            self.assertIn("Media Title", headers[2])
            self.assertIn("Media Type", headers[3])
            self.assertIn("Duration", headers[4])
            self.assertIn("Media ID", headers[6])
        finally:
            table.close()

    def test_video_table_numeric_duration_sorting(self):
        """Duration column must sort numerically using UserRole seconds rather than alphabetical string."""
        table = VideoTableWidget()
        try:
            p1 = VideoItem(index=1, video_id="p1", title="Photo 1", duration="-", url="http://x/1", media_type=MediaType.PHOTO)
            v1 = VideoItem(index=2, video_id="v1", title="Short Video", duration="00:15", duration_seconds=15, url="http://x/2", media_type=MediaType.VIDEO)
            v2 = VideoItem(index=3, video_id="v2", title="Long Video", duration="02:00", duration_seconds=120, url="http://x/3", media_type=MediaType.VIDEO)

            table.load_videos([p1, v1, v2])

            # Item in row 0 duration widget
            item_p1 = table.table.item(0, table.COL_DURATION)
            item_v1 = table.table.item(1, table.COL_DURATION)
            item_v2 = table.table.item(2, table.COL_DURATION)

            # Photos sort as -1
            self.assertEqual(item_p1.data(Qt.ItemDataRole.UserRole), -1)
            self.assertEqual(item_v1.data(Qt.ItemDataRole.UserRole), 15)
            self.assertEqual(item_v2.data(Qt.ItemDataRole.UserRole), 120)

            # Verification of < operator for _DurationTableWidgetItem
            self.assertTrue(item_p1 < item_v1)
            self.assertTrue(item_v1 < item_v2)
        finally:
            table.close()

    def test_video_table_selection_summary_calculation(self):
        """VideoTableWidget.get_selection_summary accurately reports counts and states."""
        table = VideoTableWidget()
        try:
            p1 = VideoItem(index=1, video_id="p1", title="Photo 1", duration="-", url="http://x/1", media_type=MediaType.PHOTO)
            v1 = VideoItem(index=2, video_id="v1", title="Video 1", duration="01:00", duration_seconds=60, url="http://x/2", media_type=MediaType.VIDEO)
            r1 = VideoItem(index=3, video_id="r1", title="Reel 1", duration="00:30", duration_seconds=30, url="http://x/3", media_type=MediaType.REEL)

            table.load_videos([p1, v1, r1])

            # Select none
            table.select_all(False)
            s0 = table.get_selection_summary()
            self.assertFalse(s0.has_selection)

            # Select only photo
            table.select_all(True)
            table.table.item(1, table.COL_SELECT).setCheckState(Qt.CheckState.Unchecked)
            table.table.item(2, table.COL_SELECT).setCheckState(Qt.CheckState.Unchecked)
            s_photo = table.get_selection_summary()
            self.assertTrue(s_photo.has_selection)
            self.assertTrue(s_photo.is_photo_only)
            self.assertEqual(s_photo.photo_count, 1)

            # Select only videos
            table.table.item(0, table.COL_SELECT).setCheckState(Qt.CheckState.Unchecked)
            table.table.item(1, table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            table.table.item(2, table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            s_video = table.get_selection_summary()
            self.assertTrue(s_video.has_selection)
            self.assertTrue(s_video.is_video_only)
            self.assertEqual(s_video.video_count, 1)
            self.assertEqual(s_video.reel_count, 1)

            # Select all (mixed)
            table.select_all(True)
            s_mixed = table.get_selection_summary()
            self.assertTrue(s_mixed.is_mixed)
            self.assertEqual(s_mixed.total_count, 3)
        finally:
            table.close()

    # -------------------------------------------------------------------------
    # 4. MainWindow Selection-Aware Control Behavior
    # -------------------------------------------------------------------------

    def test_main_window_selection_aware_gating(self):
        """MainWindow enables/disables Video Options, Image Options, and Assets based on selection."""
        win = MainWindow(settings_manager=self.settings)
        try:
            win.resize(1200, 960)
            app.processEvents()

            # 1. No selection state
            win.video_table.select_all(False)
            win._update_selection_aware_controls()
            self.assertFalse(win.download_btn.isEnabled())
            # In idle state with no selection, configurations are both accessible
            self.assertTrue(win.mode_combo.isEnabled())
            self.assertTrue(win.image_format_combo.isEnabled())

            # 2. Populate table with mixed media
            p1 = VideoItem(index=1, video_id="p1", title="Photo 1", duration="-", url="http://x/1", media_type=MediaType.PHOTO)
            v1 = VideoItem(index=2, video_id="v1", title="Video 1", duration="01:00", duration_seconds=60, url="http://x/2", media_type=MediaType.VIDEO)
            win.video_table.load_videos([p1, v1])

            # Select photo only
            win.video_table.table.item(0, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            win.video_table.table.item(1, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Unchecked)
            win._update_selection_aware_controls()

            self.assertTrue(win.download_btn.isEnabled())
            # Video controls disabled
            self.assertFalse(win.mode_combo.isEnabled())
            self.assertFalse(win.format_combo.isEnabled())
            self.assertFalse(win.quality_combo.isEnabled())
            # Video-only assets disabled
            self.assertFalse(win.subtitles_cb.isEnabled())
            self.assertFalse(win.thumbnail_cb.isEnabled())
            self.assertFalse(win.save_chapters_cb.isEnabled())
            # Meta & Image controls enabled
            self.assertTrue(win.save_desc_cb.isEnabled())
            self.assertTrue(win.save_meta_cb.isEnabled())
            self.assertTrue(win.image_card.isEnabled())
            self.assertTrue(win.image_format_combo.isEnabled())

            # Select video only
            win.video_table.table.item(0, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Unchecked)
            win.video_table.table.item(1, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            win._update_selection_aware_controls()

            self.assertTrue(win.download_btn.isEnabled())
            # Video controls enabled
            self.assertTrue(win.mode_combo.isEnabled())
            self.assertTrue(win.thumbnail_cb.isEnabled())
            # Image card disabled
            self.assertFalse(win.image_format_combo.isEnabled())
            self.assertFalse(win.preserve_original_images_cb.isEnabled())

            # Select mixed (both)
            win.video_table.table.item(0, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            win.video_table.table.item(1, win.video_table.COL_SELECT).setCheckState(Qt.CheckState.Checked)
            win._update_selection_aware_controls()

            self.assertTrue(win.download_btn.isEnabled())
            self.assertTrue(win.mode_combo.isEnabled())
            self.assertTrue(win.image_format_combo.isEnabled())
            self.assertTrue(win.thumbnail_cb.isEnabled())
        finally:
            win.close()

    def test_image_format_combo_controls_quality_enabled(self):
        """Changing image format enables quality for JPG/WEBP and disables for Keep Original/PNG."""
        win = MainWindow(settings_manager=self.settings)
        try:
            # Ensure an image-permitting mode is active (Image Only)
            win.mode_combo.setCurrentIndex(win.mode_combo.findData(DownloadMode.IMAGE_ONLY))

            # Set to Keep Original -> Quality disabled
            idx_orig = win.image_format_combo.findData("Keep Original")
            win.image_format_combo.setCurrentIndex(idx_orig)
            win._on_image_format_changed()
            self.assertFalse(win.image_quality_combo.isEnabled())

            # Set to JPG -> Quality enabled
            idx_jpg = win.image_format_combo.findData("JPG")
            win.image_format_combo.setCurrentIndex(idx_jpg)
            win._on_image_format_changed()
            self.assertTrue(win.image_quality_combo.isEnabled())

            # Set to PNG -> Quality disabled
            idx_png = win.image_format_combo.findData("PNG")
            win.image_format_combo.setCurrentIndex(idx_png)
            win._on_image_format_changed()
            self.assertFalse(win.image_quality_combo.isEnabled())

            # Set to WEBP -> Quality enabled
            idx_webp = win.image_format_combo.findData("WEBP")
            win.image_format_combo.setCurrentIndex(idx_webp)
            win._on_image_format_changed()
            self.assertTrue(win.image_quality_combo.isEnabled())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 5. Dual-Engine Scanning & Outcome Tracking
    # -------------------------------------------------------------------------

    def test_dual_engine_profile_scanning(self):
        """ProfileScanManager invokes both gallery-dl and yt-dlp discovery paths and merges outcomes."""
        mock_gdl = MagicMock()
        mock_gdl.is_available.return_value = True
        mock_gdl.extract_metadata.return_value = [
            {
                "id": "photo_item_1",
                "title": "Facebook Photo 1",
                "url": "https://facebook.com/photo?fbid=1",
                "post_url": "https://facebook.com/photo?fbid=1",
                "media_url": "https://facebook.com/photo?fbid=1",
                "caption": "Facebook Photo 1",
                "media_type": "IMAGE",
            }
        ]

        scanner = ProfileScanManager(gallerydl_engine=mock_gdl)

        # Mock adapter scan for video discovery
        mock_adapter = MagicMock()
        mock_adapter.scan.return_value = ScanResult(
            videos=[
                VideoItem(
                    index=1,
                    video_id="video_item_1",
                    title="Facebook Reel 1",
                    duration="00:45",
                    duration_seconds=45,
                    url="https://facebook.com/reel/100",
                    media_type=MediaType.REEL,
                )
            ],
            source_title="Test Facebook Page",
        )

        with patch("core.platform.PlatformRegistry.get_adapter", return_value=mock_adapter):
            result = scanner.scan_profile(
                url="https://www.facebook.com/TestPage",
                platform="facebook",
                custom_cookie_file="",
            )

        self.assertEqual(len(result.videos), 2)
        # Check Task 1 and Task 2 outcomes
        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.COMPLETE)
        self.assertEqual(result.extra_metadata["gallerydl_status"], "SUCCESS")
        self.assertEqual(result.extra_metadata["ytdlp_status"], "SUCCESS")

        # Verify items and types
        types = {v.media_type for v in result.videos}
        self.assertIn(MediaType.PHOTO, types)
        self.assertIn(MediaType.REEL, types)

    # -------------------------------------------------------------------------
    # 6. Pillow Image Conversion in DownloadManager
    # -------------------------------------------------------------------------

    def test_image_conversion_pipeline_with_pillow(self):
        """DownloadManager converts images to requested format with quality settings and preserves or deletes originals."""
        from PIL import Image

        dm = DownloadManager(videos=[], settings=DownloadSettings())

        # Create dummy PNG file
        png_path = self.test_dir / "sample_img.png"
        img = Image.new("RGBA", (80, 80), color=(100, 200, 50, 255))
        img.save(png_path)
        self.assertTrue(png_path.exists())

        # 1. Convert to JPG with preserve_original_images = True
        dm.settings.image_format = "JPG"
        dm.settings.image_quality = "80%"
        dm.settings.preserve_original_images = True

        converted = dm._process_image_conversions([str(png_path)])
        self.assertEqual(len(converted), 1)
        jpg_path = Path(converted[0])
        self.assertEqual(jpg_path.suffix.lower(), ".jpg")
        self.assertTrue(jpg_path.exists())
        self.assertTrue(png_path.exists())  # Original preserved

        # 2. Convert to WEBP with preserve_original_images = False
        png_path_2 = self.test_dir / "sample_img_2.png"
        img.save(png_path_2)
        self.assertTrue(png_path_2.exists())

        dm.settings.image_format = "WEBP"
        dm.settings.image_quality = "70%"
        dm.settings.preserve_original_images = False

        converted_webp = dm._process_image_conversions([str(png_path_2)])
        self.assertEqual(len(converted_webp), 1)
        webp_path = Path(converted_webp[0])
        self.assertEqual(webp_path.suffix.lower(), ".webp")
        self.assertTrue(webp_path.exists())
        self.assertFalse(png_path_2.exists())  # Original unlinked per settings

    # -------------------------------------------------------------------------
    # 7. Backward Compatibility & Settings Migration
    # -------------------------------------------------------------------------

    def test_settings_bidirectional_migration(self):
        """SettingsManager migrates old keys to generalized media keys and synchronizes updates."""
        settings_file = self.test_dir / "migration_test.json"
        legacy_json = {
            "skip_existing": True,
            "create_individual_video_folders": True,
            "include_video_id_in_filename": True,
        }
        import json
        settings_file.write_text(json.dumps(legacy_json), encoding="utf-8")

        sm = SettingsManager(settings_path=settings_file)

        # Generalized media keys must be populated from legacy keys
        self.assertTrue(sm.get("skip_downloaded_media"))
        self.assertTrue(sm.get("create_individual_media_folders"))
        self.assertTrue(sm.get("include_media_id_in_filename"))

        # Updating new key synchronizes old key
        sm.set("skip_downloaded_media", False)
        self.assertFalse(sm.get("skip_existing"))
        self.assertFalse(sm.get("skip_downloaded_media"))


if __name__ == "__main__":
    unittest.main()
