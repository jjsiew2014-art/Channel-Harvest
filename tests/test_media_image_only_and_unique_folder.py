"""
tests/test_media_image_only_and_unique_folder.py
Comprehensive test suite verifying the 5 user-requested features:
1. Card layout: Image Options card removed, Image Format and Quality moved under MEDIA card,
   File Organization restored to original position (3-column layout).
2. Mode dropdown: Image Only added.
   - Selecting Image Only automatically unchecks all videos and disables their checkability.
   - When scan results contain only photos, Media Mode automatically selects Image Only,
     and other modes become disabled.
3. In Image Only mode, Subtitle, Download Thumbnail, and Save Chapter in Additional Assets become disabled.
4. "Add number to filename" renamed to "Add sequence no. to filename".
5. "Create Unique filename" feature:
   - Checkbox with text input underneath.
   - When checked, input is enabled, and "Create channel subfolder" becomes disabled.
   - Media downloads into the custom user-specified directory.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.models import VideoItem, MediaType, DownloadMode, DownloadSettings, VideoStatus
from core.paths import resolve_video_output_dir
from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from gui.main_window import MainWindow
from downloader.download_manager import DownloadManager
from downloader.engine_router import DownloadEngineRouter
from downloader.gallerydl_engine import GalleryDlEngine


class TestMediaImageOnlyAndUniqueFolder(unittest.TestCase):
    """Verifies all 5 requirements for Image Only mode and Unique Folder feature."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)
        I18nManager.set_language("en")
        try:
            SettingsManager().set("download_mode", DownloadMode.VIDEO_AND_AUDIO)
        except Exception:
            pass

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass
        I18nManager.set_language("en")

    # -------------------------------------------------------------------------
    # 1. Card Layout Verification
    # -------------------------------------------------------------------------
    def test_01_card_layout_media_and_org_restoration(self):
        """Verify Image Option card is removed, Image Format/Quality moved into Media, File Org in Col 3."""
        win = MainWindow()
        try:
            # Check Image Format & Quality are children of Media card
            self.assertTrue(hasattr(win, "image_format_combo"))
            self.assertTrue(hasattr(win, "image_quality_combo"))
            self.assertTrue(hasattr(win, "preserve_original_images_cb"))

            # Image Format & Quality are located inside media_card's layout
            self.assertIn("Keep Original", [win.image_format_combo.itemText(i) for i in range(win.image_format_combo.count())])

            # File Organization card restored to column 3
            # Columns layout should have exactly 3 top-level cards: Media (0), Additional Assets (1), File Org (2)
            self.assertTrue(hasattr(win, "channel_folder_cb"))
            self.assertTrue(hasattr(win, "create_unique_filename_cb"))
            self.assertTrue(hasattr(win, "unique_folder_input"))
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 2. Mode Dropdown: Image Only option exists
    # -------------------------------------------------------------------------
    def test_02_mode_dropdown_has_image_only(self):
        """Verify Image Only mode is present in mode_combo."""
        win = MainWindow()
        try:
            modes = [win.mode_combo.itemData(i) for i in range(win.mode_combo.count())]
            self.assertIn(DownloadMode.IMAGE_ONLY, modes)
            idx = win.mode_combo.findData(DownloadMode.IMAGE_ONLY)
            self.assertGreaterEqual(idx, 0)
            self.assertEqual(win.mode_combo.itemText(idx), "Image Only")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 3. Selecting Image Only disables video rows in Available Media
    # -------------------------------------------------------------------------
    def test_03_selecting_image_only_disables_videos(self):
        """Verify selecting Image Only unchecks and disables all video rows while keeping photos checkable."""
        win = MainWindow()
        try:
            items = [
                VideoItem(index=1, video_id="vid_1", title="Video One", duration="05:00", media_type=MediaType.VIDEO, selected=True),
                VideoItem(index=2, video_id="photo_1", title="Photo One", duration="-", media_type=MediaType.PHOTO, selected=True),
                VideoItem(index=3, video_id="vid_2", title="Video Two", duration="02:30", media_type=MediaType.REEL, selected=True),
            ]
            win.video_table.load_videos(items)

            # Initially in Video Only mode, all 3 are checked
            self.assertEqual(len(win.video_table.get_selected_videos()), 3)

            # Switch mode to Image Only
            idx = win.mode_combo.findData(DownloadMode.IMAGE_ONLY)
            win.mode_combo.setCurrentIndex(idx)

            # Only photo should remain selected; videos are unchecked and non-checkable
            selected = win.video_table.get_selected_videos()
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].video_id, "photo_1")

            # Check flags: video row checkboxes cannot be checked
            tbl = win.video_table.table
            vid_chk_0 = tbl.item(0, win.video_table.COL_SELECT)
            self.assertFalse(vid_chk_0.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            self.assertEqual(vid_chk_0.checkState(), Qt.CheckState.Unchecked)

            photo_chk_1 = tbl.item(1, win.video_table.COL_SELECT)
            self.assertTrue(photo_chk_1.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            self.assertEqual(photo_chk_1.checkState(), Qt.CheckState.Checked)

            # Switch back to Video Only: videos become checkable again
            idx_vo = win.mode_combo.findData(DownloadMode.VIDEO_ONLY)
            win.mode_combo.setCurrentIndex(idx_vo)
            self.assertTrue(vid_chk_0.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 4. Scan with only photos automatically selects Image Only and disables others
    # -------------------------------------------------------------------------
    def test_04_scan_with_only_photos_auto_selects_image_only(self):
        """When scan results contain ONLY photos, mode switches to Image Only and other modes disabled."""
        win = MainWindow()
        try:
            photo_items = [
                VideoItem(index=1, video_id="p1", title="Photo 1", duration="-", media_type=MediaType.PHOTO),
                VideoItem(index=2, video_id="p2", title="Photo 2", duration="-", media_type=MediaType.PHOTO),
            ]

            # Simulate scan completion with photo-only result
            from core.models import ScanResult
            res = ScanResult(videos=photo_items, source_title="Hong Yong Music")
            win._on_scan_completed(res)

            # Mode should automatically be Image Only
            current_mode = win.mode_combo.currentData()
            self.assertEqual(current_mode, DownloadMode.IMAGE_ONLY)

            # Other modes must be disabled in the combo dropdown
            combo_model = win.mode_combo.model()
            for i in range(win.mode_combo.count()):
                d = win.mode_combo.itemData(i)
                item = combo_model.item(i)
                if d == DownloadMode.IMAGE_ONLY:
                    self.assertTrue(item.isEnabled())
                else:
                    self.assertFalse(item.isEnabled())

            # Clearing table restores all mode options
            win.video_table.clear_table()
            for i in range(win.mode_combo.count()):
                item = combo_model.item(i)
                self.assertTrue(item.isEnabled())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 5. Image Only disables Subtitle, Download Thumbnail, and Save Chapters
    # -------------------------------------------------------------------------
    def test_05_image_only_disables_additional_assets(self):
        """Verify in Image Only mode, Subtitles, Download Thumbnail, and Save Chapter are disabled."""
        win = MainWindow()
        try:
            # Baseline: Video Only mode
            win.mode_combo.setCurrentIndex(win.mode_combo.findData(DownloadMode.VIDEO_ONLY))
            self.assertTrue(win.thumbnail_cb.isEnabled())
            self.assertTrue(win.save_chapters_cb.isEnabled())

            # Switch to Image Only
            win.mode_combo.setCurrentIndex(win.mode_combo.findData(DownloadMode.IMAGE_ONLY))

            # Additional assets gating
            self.assertFalse(win.subtitles_cb.isEnabled())
            self.assertFalse(win.thumbnail_cb.isEnabled())
            self.assertFalse(win.save_chapters_cb.isEnabled())
            self.assertFalse(win.sub_source_combo.isEnabled())
            self.assertFalse(win.thumb_format_combo.isEnabled())

            # Switch back to Video + Audio
            win.mode_combo.setCurrentIndex(win.mode_combo.findData(DownloadMode.VIDEO_AND_AUDIO))
            self.assertTrue(win.thumbnail_cb.isEnabled())
            self.assertTrue(win.save_chapters_cb.isEnabled())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 6. File Organization: "Add sequence no. to filename" renaming
    # -------------------------------------------------------------------------
    def test_06_add_sequence_no_renaming(self):
        """Verify File Organization has 'Add sequence no. to filename' label."""
        win = MainWindow()
        try:
            I18nManager.set_language("en")
            win.retranslate_ui()
            self.assertEqual(win.add_number_cb.text(), "Add Sequence No. to filename")

            # Simplified Chinese
            I18nManager.set_language("zh_CN")
            win.retranslate_ui()
            self.assertIn("序号", win.add_number_cb.text())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 7. Create Unique filename / Custom Folder feature
    # -------------------------------------------------------------------------
    def test_07_create_unique_filename_ui_interaction(self):
        """Verify checking Create Unique filename enables custom folder input and disables channel subfolder."""
        win = MainWindow()
        try:
            win.settings_manager.set("create_unique_filename", False)
            win.create_unique_filename_cb.setChecked(False)

            self.assertFalse(win.unique_folder_input.isEnabled())
            self.assertTrue(win.channel_folder_cb.isEnabled())

            # Check Create Unique filename
            win.create_unique_filename_cb.setChecked(True)
            self.assertTrue(win.unique_folder_input.isEnabled())
            self.assertFalse(win.channel_folder_cb.isEnabled())

            # Fill in folder name
            win.unique_folder_input.setText("Hong Yong Archive 2026")
            self.assertEqual(win.settings_manager.get("unique_filename_folder"), "Hong Yong Archive 2026")

            # Uncheck
            win.create_unique_filename_cb.setChecked(False)
            self.assertFalse(win.unique_folder_input.isEnabled())
            self.assertTrue(win.channel_folder_cb.isEnabled())
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 8. Path resolution with Custom Folder Name
    # -------------------------------------------------------------------------
    def test_08_resolve_output_dir_with_custom_folder(self):
        """Verify resolve_video_output_dir routes into custom_folder_name when provided."""
        base_dir = self.target_dir / "Downloads"

        # Case 1: Custom folder name overrides channel folder
        out_dir = resolve_video_output_dir(
            base_download_dir=base_dir,
            channel_title="HongYongMusic",
            create_channel_folder=True,
            video_title="Song Title",
            video_id="abc123",
            create_individual_video_folders=False,
            custom_folder_name="My Custom Channel Archive",
        )
        self.assertEqual(out_dir, base_dir / "My Custom Channel Archive")

        # Case 2: Custom folder name with individual video folders
        out_dir_indiv = resolve_video_output_dir(
            base_download_dir=base_dir,
            channel_title="HongYongMusic",
            create_channel_folder=True,
            video_title="Song Title",
            video_id="abc123",
            create_individual_video_folders=True,
            custom_folder_name="My Custom Channel Archive",
            number_prefix="01_",
        )
        self.assertEqual(out_dir_indiv, base_dir / "My Custom Channel Archive" / "01_Song Title")

    # -------------------------------------------------------------------------
    # 9. DownloadManager downloads into Custom Unique Folder
    # -------------------------------------------------------------------------
    def test_09_download_manager_custom_unique_folder(self):
        """Verify DownloadManager creates and targets user-defined custom unique folder."""
        video = VideoItem(
            index=1,
            video_id="vid_001",
            title="Special Performance",
            duration="03:00",
            url="https://example.com/v1",
        )
        settings = DownloadSettings(
            download_folder=str(self.target_dir),
            create_channel_folder=True,
            create_unique_filename=True,
            unique_filename_folder="CustomConcertFolder",
            create_individual_video_folders=False,
        )

        dm = DownloadManager(videos=[video], settings=settings)

        captured_target_dirs = []
        def mock_download(video, settings, target_dir, **kwargs):
            captured_target_dirs.append(target_dir)
            return {"success": True, "skipped": False, "info_dict": {"title": video.title, "ext": "mp4"}}

        dm.engine.download_single_video = mock_download
        dm.run()

        expected_dir = self.target_dir / "CustomConcertFolder"
        self.assertEqual(len(captured_target_dirs), 1)
        self.assertEqual(captured_target_dirs[0], expected_dir)
        self.assertTrue(expected_dir.is_dir())


    # -------------------------------------------------------------------------
    # 10. Requirement 1: "XXX media found" counter label
    # -------------------------------------------------------------------------
    def test_10_counter_shows_media_found(self):
        """Verify counter label shows 'media found' for 0, 1, and N items."""
        win = MainWindow()
        try:
            # Empty / Initial
            self.assertEqual(win.video_table.found_label.text(), "0 media found")

            # 1 item
            items1 = [VideoItem(index=1, video_id="v1", title="Single Video", duration="01:00")]
            win.video_table.load_videos(items1)
            self.assertEqual(win.video_table.found_label.text(), "1 media found")

            # 3 items
            items3 = [
                VideoItem(index=1, video_id="v1", title="Video 1", duration="01:00"),
                VideoItem(index=2, video_id="p1", title="Photo 1", duration="-", media_type=MediaType.PHOTO),
                VideoItem(index=3, video_id="v2", title="Video 2", duration="02:00"),
            ]
            win.video_table.load_videos(items3)
            self.assertEqual(win.video_table.found_label.text(), "3 media found")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 11. Requirement 8: "No media available" placeholder before scan
    # -------------------------------------------------------------------------
    def test_11_empty_state_shows_no_media_available(self):
        """Verify empty state title displays 'No media available' before scanning."""
        win = MainWindow()
        try:
            self.assertEqual(win.video_table.empty_title.text(), "No media available")
            I18nManager.set_language("zh_CN")
            win.video_table.retranslate_ui()
            self.assertIn("暂无媒体", win.video_table.empty_title.text())
            I18nManager.set_language("en")
            win.video_table.retranslate_ui()
            self.assertEqual(win.video_table.empty_title.text(), "No media available")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 12. Requirement 3: Mode Video Only, Audio Only, Assets Only disables Image Format/Quality
    # -------------------------------------------------------------------------
    def test_12_mode_video_audio_assets_disables_image_options(self):
        """Selecting Video Only, Audio Only, or Assets Only automatically disables Image Format & Quality."""
        win = MainWindow()
        try:
            for mode in (DownloadMode.VIDEO_ONLY, DownloadMode.AUDIO_ONLY, DownloadMode.ASSETS_ONLY):
                idx = win.mode_combo.findData(mode)
                win.mode_combo.setCurrentIndex(idx)
                self.assertFalse(win.image_format_combo.isEnabled(), f"Expected image_format_combo disabled in {mode}")
                self.assertFalse(win.image_quality_combo.isEnabled(), f"Expected image_quality_combo disabled in {mode}")
                self.assertFalse(win.preserve_original_images_cb.isEnabled(), f"Expected preserve_original_images_cb disabled in {mode}")

            # Enabled in Image Only and Video + Audio
            for mode in (DownloadMode.IMAGE_ONLY, DownloadMode.VIDEO_AND_AUDIO):
                idx = win.mode_combo.findData(mode)
                win.mode_combo.setCurrentIndex(idx)
                self.assertTrue(win.image_format_combo.isEnabled(), f"Expected image_format_combo enabled in {mode}")
                self.assertTrue(win.preserve_original_images_cb.isEnabled(), f"Expected preserve_original_images_cb enabled in {mode}")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 13. Requirement 4: Checking Create unique filename unchecks & disables Create channel subfolder
    # -------------------------------------------------------------------------
    def test_13_create_unique_filename_unchecks_and_disables_channel_subfolder(self):
        """When Create unique filename is checked, Create channel subfolder is unchecked and disabled."""
        win = MainWindow()
        try:
            win.channel_folder_cb.setChecked(True)
            self.assertTrue(win.channel_folder_cb.isChecked())
            self.assertTrue(win.channel_folder_cb.isEnabled())

            # Check unique filename
            win.create_unique_filename_cb.setChecked(True)
            self.assertFalse(win.channel_folder_cb.isChecked(), "Create channel subfolder must be automatically unchecked")
            self.assertFalse(win.channel_folder_cb.isEnabled(), "Create channel subfolder must be disabled")

            # Uncheck unique filename restores channel subfolder enable state
            win.create_unique_filename_cb.setChecked(False)
            self.assertTrue(win.channel_folder_cb.isEnabled(), "Create channel subfolder must be enabled when unique filename is unchecked")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 14. Requirement 5: File Organization controls ordering
    # -------------------------------------------------------------------------
    def test_14_file_organization_controls_ordering(self):
        """Verify exact top-to-bottom layout ordering in File Organization group."""
        win = MainWindow()
        try:
            # Inspect widgets in org_layout
            layout = win.add_number_cb.parentWidget().layout()
            widgets = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget()
                if w is not None:
                    widgets.append(w)

            # Expected order in File Organization (Skip Downloaded Media and Include Media ID moved to Settings General):
            # 0: Section title (FILE ORGANIZATION)
            # 1: Add sequence no. to filename
            # 2: Embed Cover Art into Audio Tag
            # 3: Embed Media Metadata into Audio Tag
            # 4: Embed Lyrics into Audio Tag
            # 5: Create individual media folders
            # 6: Create channel subfolder
            # 7: Create unique filename
            # 8: unique_folder_input
            self.assertEqual(widgets[0], win.org_title)
            self.assertEqual(widgets[1], win.add_number_cb)
            self.assertEqual(widgets[2], win.embed_cover_art_cb)
            self.assertEqual(widgets[3], win.embed_metadata_cb)
            self.assertEqual(widgets[4], win.embed_lyrics_cb)
            self.assertEqual(widgets[5], win.individual_media_folder_cb)
            self.assertEqual(widgets[6], win.channel_folder_cb)
            self.assertEqual(widgets[7], win.create_unique_filename_cb)
            self.assertEqual(widgets[8], win.unique_folder_input)

            # Verify Include Media ID and Skip Downloaded Media are in SettingsDialog under GENERAL
            from gui.settings_dialog import SettingsDialog
            dlg = SettingsDialog(win, settings_manager=win.settings_manager)
            self.assertTrue(hasattr(dlg, "include_media_id_cb"))
            self.assertEqual(dlg.include_media_id_cb.isChecked(), False)
            self.assertTrue(hasattr(dlg, "skip_downloaded_media_cb"))
            self.assertEqual(dlg.skip_downloaded_media_cb.isChecked(), False)
            dlg.close()
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 15. Requirement 6: "Create unique filename" renaming (lowercase 'u')
    # -------------------------------------------------------------------------
    def test_15_create_unique_filename_lowercase_u(self):
        """Verify 'Create unique filename' has lowercase 'u'."""
        win = MainWindow()
        try:
            I18nManager.set_language("en")
            win.retranslate_ui()
            self.assertEqual(win.create_unique_filename_cb.text(), "Create custom folder name")
            self.assertEqual(tr("cb_create_unique_filename"), "Create custom folder name")
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 16. Requirement 7: Scan media results are all automatically checked
    # -------------------------------------------------------------------------
    def test_16_all_media_checked_after_scan(self):
        """Verify all displayed available media are automatically in the ALL CHECKED state after scanning."""
        win = MainWindow()
        try:
            from core.models import ScanResult
            scanned = [
                VideoItem(index=1, video_id="v1", title="Video One", duration="03:00", media_type=MediaType.VIDEO, selected=False),
                VideoItem(index=2, video_id="p1", title="Photo One", duration="-", media_type=MediaType.PHOTO, selected=False),
                VideoItem(index=3, video_id="v2", title="Video Two", duration="04:00", media_type=MediaType.VIDEO, selected=False),
            ]
            res = ScanResult(videos=scanned, source_title="Test Channel")
            win._on_scan_completed(res)

            selected_videos = win.video_table.get_selected_videos()
            self.assertEqual(len(selected_videos), 3, "All 3 scanned media items must be selected after scan")

            # Check individual checkboxes in table
            tbl = win.video_table.table
            for row in range(3):
                chk = tbl.item(row, win.video_table.COL_SELECT)
                self.assertEqual(chk.checkState(), Qt.CheckState.Checked)
        finally:
            win.close()

    # -------------------------------------------------------------------------
    # 17. Requirement 2: Sequence Number Naming in default VIDEO_AND_AUDIO and AUDIO_ONLY
    # -------------------------------------------------------------------------
    def test_17_sequence_number_naming_video_and_audio(self):
        """Verify number_prefix is propagated and injected in default Video + Audio and Audio Only modes."""
        from core.paths import resolve_video_outtmpl
        # Target dir
        out_dir = Path("C:/Downloads/Channel")

        # In VIDEO_AND_AUDIO mode:
        v_out = resolve_video_outtmpl(out_dir, include_video_id=False, number_prefix="01_")
        self.assertIn("01_%(title)s.%(ext)s", v_out)

        # In AUDIO_ONLY mode:
        a_out = resolve_video_outtmpl(out_dir, include_video_id=True, number_prefix="02_")
        self.assertIn("02_%(title)s [%(id)s].%(ext)s", a_out)

        # 6-digit prefix support
        max_out = resolve_video_outtmpl(out_dir, include_video_id=False, number_prefix="000042_")
        self.assertIn("000042_%(title)s.%(ext)s", max_out)


if __name__ == "__main__":
    unittest.main()
