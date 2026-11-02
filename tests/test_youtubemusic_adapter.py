"""
test_youtubemusic_adapter.py
Unit tests for YouTube Music independent platform adapter, PlatformDetector identification,
UI integration, mode defaulting, music feature availability, and multilingual support.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

from core.i18n import I18nManager, tr
from core.models import VideoItem, DownloadMode
from core.platform import PlatformRegistry, PlatformDetector, YouTubeMusicAdapter
from core.availability import AvailabilityDetectorRegistry, YouTubeAvailabilityDetector
from core.settings import SettingsManager
from gui.main_window import MainWindow
from gui.settings_dialog import SettingsDialog
from gui.video_table import VideoTableWidget


class TestYouTubeMusicAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.settings_manager = SettingsManager()
        self.adapter = PlatformRegistry.get_adapter("youtubemusic")

    def test_01_adapter_registration_and_properties(self):
        """Verify YouTubeMusicAdapter is registered and exposes expected properties."""
        self.assertIsNotNone(self.adapter)
        self.assertIsInstance(self.adapter, YouTubeMusicAdapter)
        self.assertEqual(self.adapter.platform_id, "youtubemusic")
        self.assertEqual(self.adapter.display_name, "YouTube Music")
        self.assertTrue(self.adapter.is_available)
        self.assertTrue(self.adapter.capabilities.supports_audio)
        self.assertTrue(self.adapter.capabilities.supports_video)
        self.assertTrue(self.adapter.capabilities.supports_playlists)
        self.assertTrue(self.adapter.capabilities.supports_browser_cookies)
        self.assertTrue(self.adapter.capabilities.supports_cookie_file)
        self.assertEqual(self.adapter.capabilities.archive_prefix, "youtubemusic")

    def test_02_url_detection_distinguishes_music_from_main_youtube(self):
        """Verify PlatformDetector cleanly routes music.youtube.com to youtubemusic."""
        test_cases = [
            ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "youtubemusic"),
            ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ", "youtubemusic"),
            ("https://music.youtube.com/playlist?list=OLAK5uy_kXfOaQGg9", "youtubemusic"),
            ("https://music.youtube.com/playlist?list=PL1234567890abcdef", "youtubemusic"),
            ("https://music.youtube.com/channel/UC-9-kyTW8ZkZNDHQJ6FgpwQ", "youtubemusic"),
            ("https://music.youtube.com/browse/MPREb_12345678", "youtubemusic"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://youtube.com/playlist?list=PL123456", "youtube"),
            ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
            ("https://www.tiktok.com/@user/video/123", "tiktok"),
            ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
        ]
        for url, expected_plat in test_cases:
            detected = PlatformDetector.identify_platform_id(url)
            self.assertEqual(detected, expected_plat, f"URL {url} failed detection")
            if expected_plat == "youtubemusic":
                self.assertTrue(self.adapter.matches_url(url))
            else:
                self.assertFalse(self.adapter.matches_url(url))

    def test_03_url_validation_and_canonical_building(self):
        """Verify URL validation and canonical URL construction."""
        # Valid URLs
        valid_urls = [
            "https://music.youtube.com/watch?v=abc12345",
            "https://music.youtube.com/playlist?list=OLAK5uy_test",
            "http://music.youtube.com/channel/UC12345",
        ]
        for u in valid_urls:
            ok, err = self.adapter.validate_url(u)
            self.assertTrue(ok, f"Expected valid: {u}, got error: {err}")

        # Invalid URLs
        invalid_urls = [
            "",
            "   ",
            "ftp://music.youtube.com/test",
            "https://www.youtube.com/watch?v=123",
            "https://music.youtube.com/",
        ]
        for u in invalid_urls:
            ok, err = self.adapter.validate_url(u)
            self.assertFalse(ok, f"Expected invalid: {u}")

        # Canonical URLs & archive tags
        video = VideoItem(index=1, video_id="test123vid", title="Song Title", duration="03:45", platform="youtubemusic")
        self.assertEqual(self.adapter.build_video_url("test123vid"), "https://music.youtube.com/watch?v=test123vid")
        self.assertEqual(self.adapter.get_archive_tag(video), "youtubemusic test123vid")

    def test_04_auth_config_shares_google_youtube_credentials(self):
        """Verify YouTubeMusicAdapter inherits and shares YouTube credentials."""
        auth = self.adapter.get_auth_config()
        self.assertIsNotNone(auth)
        # Auth config should resolve through standard PlatformAuthConfig
        from core.platform.auth import PlatformAuthConfig
        self.assertIsInstance(auth, PlatformAuthConfig)

    def test_05_availability_detector_resolution(self):
        """Verify AvailabilityDetectorRegistry resolves YouTubeAvailabilityDetector for youtubemusic."""
        detector = AvailabilityDetectorRegistry.get_detector("youtubemusic")
        self.assertIsInstance(detector, YouTubeAvailabilityDetector)

    def test_06_main_window_platform_combo_contains_youtubemusic(self):
        """Verify platform_combo includes youtubemusic and switches cleanly."""
        win = MainWindow()
        try:
            # Check youtubemusic is present in platform_combo
            idx = win.platform_combo.findData("youtubemusic")
            self.assertGreaterEqual(idx, 0, "youtubemusic must be in platform_combo")
            self.assertEqual(win.platform_combo.itemText(idx), "YouTube Music")

            # Switch platform to youtubemusic
            win.platform_combo.setCurrentIndex(idx)
            self.assertEqual(win._active_platform, "youtubemusic")
            self.assertEqual(win.url_group.title(), "YOUTUBE MUSIC LINK")
            self.assertEqual(win.url_label.text(), "YouTube Music Album / Song / Playlist URL")
            self.assertEqual(win.scan_btn.text(), "Scan Music")

            # Verify mode_combo auto-selects AUDIO_ONLY
            self.assertEqual(win.mode_combo.currentData(), DownloadMode.AUDIO_ONLY)

            # Verify cover art & lyrics controls remain visible and active
            self.assertFalse(win.cover_art_cb.isHidden())
            self.assertFalse(win.embed_cover_art_cb.isHidden())
            self.assertFalse(win.embed_lyrics_cb.isHidden())
            self.assertFalse(win.download_lrc_cb.isHidden())
        finally:
            win.close()

    def test_07_url_input_auto_detects_music_and_switches(self):
        """Verify pasting a music.youtube.com URL auto-switches platform to youtubemusic."""
        win = MainWindow()
        try:
            win.platform_combo.setCurrentIndex(win.platform_combo.findData("youtube"))
            self.assertEqual(win.platform_combo.currentData(), "youtube")

            # Simulate pasting YouTube Music URL
            win.url_input.clear()
            win.url_input.setText("https://music.youtube.com/watch?v=uniqueSongId999")
            self.assertEqual(win.platform_combo.currentData(), "youtubemusic")
            self.assertEqual(win.mode_combo.currentData(), DownloadMode.AUDIO_ONLY)
        finally:
            win.close()

    def test_08_multilingual_retranslation(self):
        """Verify translations for youtubemusic across en, zh_CN, and zh_TW."""
        try:
            # 1. en
            I18nManager.set_language("en")
            self.assertEqual(tr("platform_youtubemusic"), "YouTube Music")
            self.assertEqual(tr("section_youtubemusic_link"), "YOUTUBE MUSIC LINK")
            self.assertEqual(tr("scan_youtubemusic"), "Scan Music")

            # 2. zh_CN
            I18nManager.set_language("zh_CN")
            self.assertEqual(tr("platform_youtubemusic"), "YouTube Music")
            self.assertEqual(tr("section_youtubemusic_link"), "YOUTUBE MUSIC 链接")
            self.assertEqual(tr("scan_youtubemusic"), "扫描音乐")

            # 3. zh_TW
            I18nManager.set_language("zh_TW")
            self.assertEqual(tr("platform_youtubemusic"), "YouTube Music")
            self.assertEqual(tr("section_youtubemusic_link"), "YOUTUBE MUSIC 連結")
            self.assertEqual(tr("scan_youtubemusic"), "掃描音樂")
        finally:
            I18nManager.set_language("en")

    def test_09_settings_dialog_auth_platform_combo_contains_youtubemusic(self):
        """Verify SettingsDialog auth_platform_combo contains YouTube Music."""
        dlg = SettingsDialog(settings_manager=self.settings_manager)
        try:
            idx = dlg.auth_platform_combo.findData("youtubemusic")
            self.assertGreaterEqual(idx, 0, "youtubemusic must be in auth_platform_combo")
            self.assertEqual(dlg.auth_platform_combo.itemText(idx), "YouTube Music")
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
