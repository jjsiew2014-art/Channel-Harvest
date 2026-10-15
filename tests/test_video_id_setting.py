"""
test_video_id_setting.py
Unit tests verifying the 'Include Video ID in filename' setting in Channel Harvest v1.2.2:
- Test Matrix A-P
- Centralized path resolution in core/paths.py
- SubtitleManager, ThumbnailManager, and InfoManager naming
- Safe duplicate collision protection
- Backward compatibility and persistence in settings.json
- Bilingual translations (English and Chinese)
- UI Checkbox integration
"""

import sys
import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from core.version import __version__
from core.models import VideoItem, DownloadSettings, DownloadMode, ThumbnailFormat, SubtitleLanguage
from core.settings import SettingsManager
from core.i18n import I18nManager, tr
from core.paths import (
    sanitize_filename,
    resolve_media_filename,
    resolve_video_outtmpl,
    resolve_video_output_dir,
    should_include_video_id,
)
from downloader.subtitle_manager import SubtitleManager
from downloader.thumbnail_manager import ThumbnailManager
from downloader.info_manager import InfoManager
from downloader.ytdlp_engine import YtDlpEngine
from gui.main_window import MainWindow


class TestVideoIdSetting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_dir = Path(self.temp_dir)
        self.video = VideoItem(
            index=1,
            video_id="dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            duration="03:33",
            channel_title="Rick Astley",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Version & Model & Default Settings Tests
    # -------------------------------------------------------------------------

    def test_version_bump(self):
        """Verify version is exactly 1.3.0."""
        self.assertEqual(__version__, "1.3.0")

    def test_model_default_setting(self):
        """Verify DownloadSettings defaults include_video_id_in_filename to False."""
        settings = DownloadSettings()
        self.assertFalse(settings.include_video_id_in_filename)

    def test_default_settings_dict(self):
        """Verify DEFAULT_SETTINGS contains include_video_id_in_filename=False."""
        self.assertIn("include_video_id_in_filename", SettingsManager.DEFAULT_SETTINGS)
        self.assertFalse(SettingsManager.DEFAULT_SETTINGS["include_video_id_in_filename"])

    def test_settings_persistence_and_backwards_compatibility(self):
        """Verify Test Matrix P: Persistence and backwards compatibility when key is absent."""
        settings_file = self.target_dir / "settings.json"

        # 1. Backwards compatibility: Existing JSON without the new key
        legacy_data = {
            "format": "MOV",
            "quality": "1080p",
            "create_channel_folder": True,
        }
        settings_file.write_text(json.dumps(legacy_data), encoding="utf-8")

        sm = SettingsManager(settings_path=settings_file)
        # Should gracefully default to False
        self.assertFalse(sm.get("include_video_id_in_filename"))

        # 2. Modify and persist
        sm.set("include_video_id_in_filename", True)
        self.assertTrue(sm.get("include_video_id_in_filename"))

        # Reload from disk
        sm_reloaded = SettingsManager(settings_path=settings_file)
        self.assertTrue(sm_reloaded.get("include_video_id_in_filename"))

    # -------------------------------------------------------------------------
    # 2. Bilingual Translations Tests
    # -------------------------------------------------------------------------

    def test_i18n_strings(self):
        """Verify exact English and Chinese strings per user specification."""
        orig_lang = I18nManager.get_language()
        try:
            I18nManager.set_language("en")
            self.assertEqual(tr("cb_include_video_id"), "Include Video ID in filename")

            I18nManager.set_language("zh_CN")
            # Must be exactly '文件名包含 Video ID' with 'Video ID' untranslated
            self.assertEqual(tr("cb_include_video_id"), "文件名包含 Video ID")
        finally:
            I18nManager.set_language(orig_lang)

    # -------------------------------------------------------------------------
    # 3. Path Resolution Helpers Tests
    # -------------------------------------------------------------------------

    def test_resolve_media_filename(self):
        """Verify filename resolution with and without Video ID."""
        title = "My Test Video"
        vid_id = "abc123XYZ00"

        # With include_video_id=False
        stem_no_id = resolve_media_filename(title, vid_id, include_video_id=False)
        self.assertEqual(stem_no_id, "My Test Video")

        file_no_id = resolve_media_filename(title, vid_id, ext="mov", include_video_id=False)
        self.assertEqual(file_no_id, "My Test Video.mov")

        # With include_video_id=True
        stem_with_id = resolve_media_filename(title, vid_id, include_video_id=True)
        self.assertEqual(stem_with_id, "My Test Video [abc123XYZ00]")

        file_with_id = resolve_media_filename(title, vid_id, ext="mov", include_video_id=True)
        self.assertEqual(file_with_id, "My Test Video [abc123XYZ00].mov")

    def test_resolve_video_outtmpl(self):
        """Verify yt-dlp outtmpl pattern generator."""
        tmpl_no_id = resolve_video_outtmpl(self.target_dir, include_video_id=False)
        self.assertIn("%(title)s.%(ext)s", tmpl_no_id)
        self.assertNotIn("%(id)s", tmpl_no_id)

        tmpl_with_id = resolve_video_outtmpl(self.target_dir, include_video_id=True)
        self.assertIn("%(title)s [%(id)s].%(ext)s", tmpl_with_id)

    # -------------------------------------------------------------------------
    # 4. Safe Collision Detection (Test Matrix O)
    # -------------------------------------------------------------------------

    def test_safe_duplicate_collision_protection(self):
        """Verify Test Matrix O: Safe collision fallback when individual folders are OFF."""
        # 1. User set include_video_id=True: always True
        self.assertTrue(should_include_video_id(self.video.title, self.video.video_id, True))

        # 2. User set include_video_id=False and individual folders=True: returns False (folder provides isolation)
        self.assertFalse(should_include_video_id(self.video.title, self.video.video_id, False, create_individual_video_folders=True))

        # 3. User set include_video_id=False, individual folders=False, NO duplicates: returns False
        self.assertFalse(should_include_video_id(self.video.title, self.video.video_id, False, create_individual_video_folders=False))

        # 4. Duplicate title exists in queue: safely falls back to True
        dup_queue = {"Never Gonna Give You Up"}
        self.assertTrue(should_include_video_id(
            self.video.title, self.video.video_id, False,
            create_individual_video_folders=False,
            duplicate_titles_in_queue=dup_queue,
        ))

        # 5. Collision on disk: a file with the same title from another video ID already exists
        collision_file = self.target_dir / "Never Gonna Give You Up [OTHER_ID_123].mov"
        collision_file.write_text("dummy", encoding="utf-8")
        self.assertTrue(should_include_video_id(
            self.video.title, self.video.video_id, False,
            create_individual_video_folders=False,
            target_dir=self.target_dir,
        ))

    # -------------------------------------------------------------------------
    # 5. Test Matrix A-F: Video Only, Audio Only, Video + Audio Modes
    # -------------------------------------------------------------------------

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_a_video_only_without_id(self, mock_ydl):
        """Test Matrix A: Video Only mode + include_video_id=False."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            format="MOV",
            quality="1080p",
            include_video_id_in_filename=False,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        ydl_opts = mock_ydl.call_args[0][0]
        self.assertIn("outtmpl", ydl_opts)
        self.assertIn("%(title)s.%(ext)s", ydl_opts["outtmpl"])
        self.assertNotIn("%(id)s", ydl_opts["outtmpl"])

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_b_video_only_with_id(self, mock_ydl):
        """Test Matrix B: Video Only mode + include_video_id=True."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            format="MOV",
            quality="1080p",
            include_video_id_in_filename=True,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        ydl_opts = mock_ydl.call_args[0][0]
        self.assertIn("outtmpl", ydl_opts)
        self.assertIn("%(title)s [%(id)s].%(ext)s", ydl_opts["outtmpl"])

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_c_audio_only_without_id(self, mock_ydl):
        """Test Matrix C: Audio Only mode + include_video_id=False."""
        settings = DownloadSettings(
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
            include_video_id_in_filename=False,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        ydl_opts = mock_ydl.call_args[0][0]
        self.assertIn("outtmpl", ydl_opts)
        self.assertIn("%(title)s.%(ext)s", ydl_opts["outtmpl"])
        self.assertNotIn("%(id)s", ydl_opts["outtmpl"])

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_d_audio_only_with_id(self, mock_ydl):
        """Test Matrix D: Audio Only mode + include_video_id=True."""
        settings = DownloadSettings(
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
            include_video_id_in_filename=True,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        ydl_opts = mock_ydl.call_args[0][0]
        self.assertIn("outtmpl", ydl_opts)
        self.assertIn("%(title)s [%(id)s].%(ext)s", ydl_opts["outtmpl"])

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_e_video_and_audio_without_id(self, mock_ydl):
        """Test Matrix E: Video + Audio mode + include_video_id=False."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            format="MOV",
            quality="1080p",
            audio_format="WAV",
            include_video_id_in_filename=False,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        # Check all YoutubeDL calls made during download
        for call_item in mock_ydl.call_args_list:
            opts = call_item[0][0]
            self.assertIn("%(title)s", opts["outtmpl"])
            self.assertNotIn("%(id)s", opts["outtmpl"])

    @patch("yt_dlp.YoutubeDL")
    def test_matrix_f_video_and_audio_with_id(self, mock_ydl):
        """Test Matrix F: Video + Audio mode + include_video_id=True."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            format="MOV",
            quality="1080p",
            audio_format="WAV",
            include_video_id_in_filename=True,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)
        self.assertTrue(mock_ydl.called)
        for call_item in mock_ydl.call_args_list:
            opts = call_item[0][0]
            self.assertIn("%(title)s [%(id)s]", opts["outtmpl"])

    # -------------------------------------------------------------------------
    # 6. Test Matrix G-H: Subtitle Downloading
    # -------------------------------------------------------------------------

    def test_matrix_g_subtitles_without_id(self):
        """Test Matrix G: Subtitles + include_video_id=False."""
        srt_path = SubtitleManager.get_target_srt_path(self.video, self.target_dir, include_video_id=False)
        self.assertEqual(srt_path.name, "Never Gonna Give You Up.srt")

        settings = DownloadSettings(
            download_subtitles=True,
            include_video_id_in_filename=False,
        )
        # Verify skip existing detection when file exists without video ID
        srt_path.write_text("1\n00:00:00 --> 00:00:01\nTest", encoding="utf-8")
        self.assertTrue(SubtitleManager.is_subtitle_downloaded(self.video, settings, self.target_dir))

    def test_matrix_h_subtitles_with_id(self):
        """Test Matrix H: Subtitles + include_video_id=True."""
        srt_path = SubtitleManager.get_target_srt_path(self.video, self.target_dir, include_video_id=True)
        self.assertEqual(srt_path.name, "Never Gonna Give You Up [dQw4w9WgXcQ].srt")

        settings = DownloadSettings(
            download_subtitles=True,
            include_video_id_in_filename=True,
        )
        srt_path.write_text("1\n00:00:00 --> 00:00:01\nTest", encoding="utf-8")
        self.assertTrue(SubtitleManager.is_subtitle_downloaded(self.video, settings, self.target_dir))

    # -------------------------------------------------------------------------
    # 7. Test Matrix I-J: Thumbnail Downloading
    # -------------------------------------------------------------------------

    def test_matrix_i_thumbnails_without_id(self):
        """Test Matrix I: Thumbnail + include_video_id=False."""
        settings = DownloadSettings(
            download_thumbnail=True,
            thumbnail_format=ThumbnailFormat.JPG,
            include_video_id_in_filename=False,
        )
        # Create thumbnail without video ID
        thumb_file = self.target_dir / "Never Gonna Give You Up.jpg"
        thumb_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        exists, found_path = ThumbnailManager.is_thumbnail_downloaded(self.video, settings, self.target_dir)
        self.assertTrue(exists)
        self.assertEqual(found_path, thumb_file)

    def test_matrix_j_thumbnails_with_id(self):
        """Test Matrix J: Thumbnail + include_video_id=True."""
        settings = DownloadSettings(
            download_thumbnail=True,
            thumbnail_format=ThumbnailFormat.JPG,
            include_video_id_in_filename=True,
        )
        thumb_file = self.target_dir / "Never Gonna Give You Up [dQw4w9WgXcQ].jpg"
        thumb_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        exists, found_path = ThumbnailManager.is_thumbnail_downloaded(self.video, settings, self.target_dir)
        self.assertTrue(exists)
        self.assertEqual(found_path, thumb_file)

    # -------------------------------------------------------------------------
    # 8. Test Matrix K-L: Description / Metadata / Chapters
    # -------------------------------------------------------------------------

    def test_matrix_k_info_files_without_id(self):
        """Test Matrix K: Description / Metadata / Chapters + include_video_id=False."""
        desc_p = InfoManager.get_description_path(self.video, self.target_dir, include_video_id=False)
        meta_p = InfoManager.get_metadata_path(self.video, self.target_dir, include_video_id=False)
        chap_p = InfoManager.get_chapters_path(self.video, self.target_dir, include_video_id=False)

        self.assertEqual(desc_p.name, "Never Gonna Give You Up.description")
        self.assertEqual(meta_p.name, "Never Gonna Give You Up.metadata.txt")
        self.assertEqual(chap_p.name, "Never Gonna Give You Up.chapters.txt")

        desc_p.write_text("Great song description", encoding="utf-8")
        meta_p.write_text("Metadata content", encoding="utf-8")
        chap_p.write_text("00:00 Intro", encoding="utf-8")

        settings = DownloadSettings(
            save_description=True,
            save_metadata=True,
            save_chapters=True,
            include_video_id_in_filename=False,
        )
        all_complete, needed = InfoManager.is_info_complete(self.video, settings, self.target_dir)
        self.assertTrue(all_complete)

    def test_matrix_l_info_files_with_id(self):
        """Test Matrix L: Description / Metadata / Chapters + include_video_id=True."""
        desc_p = InfoManager.get_description_path(self.video, self.target_dir, include_video_id=True)
        meta_p = InfoManager.get_metadata_path(self.video, self.target_dir, include_video_id=True)
        chap_p = InfoManager.get_chapters_path(self.video, self.target_dir, include_video_id=True)

        self.assertEqual(desc_p.name, "Never Gonna Give You Up [dQw4w9WgXcQ].description")
        self.assertEqual(meta_p.name, "Never Gonna Give You Up [dQw4w9WgXcQ].metadata.txt")
        self.assertEqual(chap_p.name, "Never Gonna Give You Up [dQw4w9WgXcQ].chapters.txt")

        desc_p.write_text("Great song description", encoding="utf-8")
        meta_p.write_text("Metadata content", encoding="utf-8")
        chap_p.write_text("00:00 Intro", encoding="utf-8")

        settings = DownloadSettings(
            save_description=True,
            save_metadata=True,
            save_chapters=True,
            include_video_id_in_filename=True,
        )
        all_complete, needed = InfoManager.is_info_complete(self.video, settings, self.target_dir)
        self.assertTrue(all_complete)

    # -------------------------------------------------------------------------
    # 9. Test Matrix M-N: Channel & Individual Folder Structures
    # -------------------------------------------------------------------------

    def test_matrix_m_channel_subfolder_without_id(self):
        """Test Matrix M: Channel Subfolder enabled + include_video_id=False."""
        out_dir = resolve_video_output_dir(
            base_download_dir=self.target_dir,
            channel_title="Rick Astley",
            create_channel_folder=True,
            video_title="Never Gonna Give You Up",
            video_id="dQw4w9WgXcQ",
            create_individual_video_folders=False,
        )
        expected_dir = self.target_dir / "Rick Astley"
        self.assertEqual(out_dir, expected_dir)

        # File generated inside channel subfolder without ID
        filename = resolve_media_filename("Never Gonna Give You Up", "dQw4w9WgXcQ", ext="mov", include_video_id=False)
        self.assertEqual(filename, "Never Gonna Give You Up.mov")
        full_path = out_dir / filename
        self.assertEqual(full_path, self.target_dir / "Rick Astley" / "Never Gonna Give You Up.mov")

    def test_matrix_n_individual_video_folders_without_id(self):
        """Test Matrix N: Individual Video Folders enabled + include_video_id=False."""
        out_dir = resolve_video_output_dir(
            base_download_dir=self.target_dir,
            channel_title="Rick Astley",
            create_channel_folder=True,
            video_title="Never Gonna Give You Up",
            video_id="dQw4w9WgXcQ",
            create_individual_video_folders=True,
        )
        expected_dir = self.target_dir / "Rick Astley" / "Never Gonna Give You Up"
        self.assertEqual(out_dir, expected_dir)

        filename = resolve_media_filename("Never Gonna Give You Up", "dQw4w9WgXcQ", ext="mov", include_video_id=False)
        self.assertEqual(filename, "Never Gonna Give You Up.mov")
        full_path = out_dir / filename
        self.assertEqual(full_path, expected_dir / "Never Gonna Give You Up.mov")

    # -------------------------------------------------------------------------
    # 10. UI Checkbox & Retranslate Tests
    # -------------------------------------------------------------------------

    def test_ui_checkbox_and_bilingual_retranslate(self):
        """Verify UI Checkbox creation under FILE ORGANIZATION and dynamic translation."""
        win = MainWindow()
        try:
            self.assertTrue(hasattr(win, "include_video_id_cb"))
            cb = win.include_video_id_cb

            # Default state should match settings (False)
            self.assertFalse(cb.isChecked())

            # Test English translation
            I18nManager.set_language("en")
            win.retranslate_ui()
            self.assertEqual(cb.text(), "Include Video ID in filename")

            # Test Chinese translation
            I18nManager.set_language("zh_CN")
            win.retranslate_ui()
            self.assertEqual(cb.text(), "文件名包含 Video ID")

            # Test settings round-trip via UI
            cb.setChecked(True)
            self.assertTrue(win.settings_manager.get("include_video_id_in_filename"))

            cb.setChecked(False)
            self.assertFalse(win.settings_manager.get("include_video_id_in_filename"))
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
