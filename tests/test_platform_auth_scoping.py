"""
test_platform_auth_scoping.py
Comprehensive unit tests verifying platform-scoped authentication in Channel Harvest.

Covers:
1. YouTube + Authentication = None
2. YouTube + Browser Cookies
3. YouTube + Custom Cookie File
4. TikTok + YouTube Authentication = None
5. TikTok + YouTube Browser Cookies configured
6. TikTok + YouTube Custom Cookie File configured
7. Verification that TikTok profile scanning, single video extraction, and download
   never pass YouTube cookiefile or browser-cookie arguments.
8. Privacy compliance and logging verification.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
from unittest.mock import patch, MagicMock

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.platform.auth import PlatformAuthConfig
from core.platform import PlatformRegistry, YouTubeAdapter, TikTokAdapter
from core.settings import SettingsManager
from downloader.ytdlp_engine import YtDlpEngine
from downloader.info_manager import InfoManager
from downloader.thumbnail_manager import ThumbnailManager


class TestPlatformAuthScoping(unittest.TestCase):
    """Verifies that authentication settings are strictly scoped per platform."""

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.settings_manager = SettingsManager(settings_path=self.settings_path)

        # Create a real dummy cookie file
        self.cookie_file = Path(self.tmp_dir.name) / "cookies.txt"
        self.cookie_file.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\ttest_token\n", encoding="utf-8")

        # Instantiate adapters
        self.yt_adapter = PlatformRegistry.get_adapter("youtube")
        self.tt_adapter = PlatformRegistry.get_adapter("tiktok")
        self.engine = YtDlpEngine()

    def tearDown(self):
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Core Adapter Auth Resolution Tests (Cases 1 - 6)
    # -------------------------------------------------------------------------

    def test_case_1_youtube_auth_none(self):
        """Case 1: YouTube with Authentication = None returns active=False."""
        self.settings_manager.set("auth_method", "none")
        self.settings_manager.set("browser_cookies", "none")
        self.settings_manager.set("custom_cookie_file", "")

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            auth = self.yt_adapter.get_auth_config()
            self.assertFalse(auth.is_active)
            self.assertEqual(auth.auth_method, "none")
            self.assertEqual(auth.description, "None")

            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                platform="youtube",
            )
            self.assertNotIn("cookiefile", opts)
            self.assertNotIn("cookiesfrombrowser", opts)
            self.assertTrue(any("[AUTH] Platform: YouTube | Authentication: None" in l for l in logs))

    def test_case_2_youtube_browser_cookies(self):
        """Case 2: YouTube with Browser Cookies (Chrome) returns browser config."""
        self.settings_manager.set("auth_method", "browser")
        self.settings_manager.set("browser_cookies", "chrome")
        self.settings_manager.set("browser_profile", "Default")

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            auth = self.yt_adapter.get_auth_config()
            self.assertTrue(auth.is_active)
            self.assertEqual(auth.auth_method, "browser")
            self.assertEqual(auth.browser_name, "chrome")
            self.assertIn("Browser Cookies", auth.description)

            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                platform="youtube",
            )
            self.assertIn("cookiesfrombrowser", opts)
            self.assertEqual(opts["cookiesfrombrowser"][0], "chrome")
            self.assertNotIn("cookiefile", opts)
            self.assertTrue(any("[AUTH] Platform: YouTube | Authentication: Browser Cookies (Chrome)" in l for l in logs))

    def test_case_3_youtube_custom_cookie_file(self):
        """Case 3: YouTube with Custom Cookie File returns cookie_file config."""
        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("browser_cookies", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            auth = self.yt_adapter.get_auth_config()
            self.assertTrue(auth.is_active)
            self.assertEqual(auth.auth_method, "custom_file")
            self.assertEqual(auth.cookie_file, str(self.cookie_file.resolve()))
            self.assertEqual(auth.description, "Custom Cookie File")

            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                platform="youtube",
            )
            self.assertIn("cookiefile", opts)
            self.assertEqual(opts["cookiefile"], str(self.cookie_file.resolve()))
            self.assertNotIn("cookiesfrombrowser", opts)
            self.assertTrue(any("[AUTH] Platform: YouTube | Authentication: Custom Cookie File" in l for l in logs))

    def test_case_4_tiktok_with_youtube_auth_none(self):
        """Case 4: TikTok with YouTube Auth = None returns None for TikTok."""
        self.settings_manager.set("auth_method", "none")
        self.settings_manager.set("browser_cookies", "none")

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            auth = self.tt_adapter.get_auth_config()
            self.assertFalse(auth.is_active)
            self.assertEqual(auth.auth_method, "none")

            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                platform="tiktok",
            )
            self.assertNotIn("cookiefile", opts)
            self.assertNotIn("cookiesfrombrowser", opts)
            self.assertTrue(any("[AUTH] Platform: TikTok | Authentication: None" in l for l in logs))

    def test_case_5_tiktok_with_youtube_browser_cookies(self):
        """Case 5: TikTok ignores configured YouTube Browser Cookies."""
        self.settings_manager.set("auth_method", "browser")
        self.settings_manager.set("browser_cookies", "chrome")

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            # TikTok adapter explicitly returns None
            auth = self.tt_adapter.get_auth_config()
            self.assertFalse(auth.is_active)
            self.assertEqual(auth.description, "None")

            # build_base_ydl_opts for tiktok must NEVER attach chrome cookies
            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                browser_cookies="chrome",
                platform="tiktok",
            )
            self.assertNotIn("cookiefile", opts)
            self.assertNotIn("cookiesfrombrowser", opts)
            self.assertTrue(any("[AUTH] Platform: TikTok | Authentication: None" in l for l in logs))

    def test_case_6_tiktok_with_youtube_custom_cookie_file(self):
        """Case 6: TikTok ignores configured YouTube Custom Cookie File."""
        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("browser_cookies", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            # TikTok adapter explicitly returns None
            auth = self.tt_adapter.get_auth_config()
            self.assertFalse(auth.is_active)
            self.assertEqual(auth.description, "None")

            # build_base_ydl_opts for tiktok must NEVER attach cookiefile
            # and must NEVER treat 'custom_file' as a browser name
            logs = []
            opts = self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                browser_cookies="custom_file",
                platform="tiktok",
            )
            self.assertNotIn("cookiefile", opts)
            self.assertNotIn("cookiesfrombrowser", opts)
            self.assertTrue(any("[AUTH] Platform: TikTok | Authentication: None" in l for l in logs))

    # -------------------------------------------------------------------------
    # TikTok Operations Verification (Scanning, Single Video, Download)
    # -------------------------------------------------------------------------

    @patch("yt_dlp.YoutubeDL")
    def test_tiktok_profile_scanning_ignores_youtube_cookies(self, mock_ydl_cls):
        """Verify TikTok profile scanning never passes cookiefile or browser cookies."""
        # Configure YouTube to have Custom Cookie File
        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("browser_cookies", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))

        mock_ydl_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "uploader": "test_creator",
            "entries": [
                {
                    "id": "7106594312292453678",
                    "title": "TikTok Dance Clip",
                    "duration": 15,
                    "webpage_url": "https://www.tiktok.com/@test_creator/video/7106594312292453678",
                }
            ],
        }

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            logs = []
            items = self.tt_adapter.extract_entries(
                url="https://www.tiktok.com/@test_creator",
                log_callback=logs.append,
                browser_cookies="custom_file",
                custom_cookie_file=str(self.cookie_file.resolve()),
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].video_id, "7106594312292453678")
            self.assertEqual(items[0].platform, "tiktok")

            # Check YoutubeDL init options passed by TikTokAdapter
            ydl_call_opts = mock_ydl_cls.call_args[0][0]
            self.assertNotIn("cookiefile", ydl_call_opts)
            self.assertNotIn("cookiesfrombrowser", ydl_call_opts)
            # Verify auth log was emitted cleanly
            self.assertTrue(any("[AUTH] Platform: TikTok | Authentication: None" in l for l in logs))

    @patch("yt_dlp.YoutubeDL")
    def test_tiktok_single_video_extraction_ignores_youtube_browser_cookies(self, mock_ydl_cls):
        """Verify TikTok single-video extraction never passes browser cookies."""
        # Configure YouTube with Chrome cookies
        self.settings_manager.set("auth_method", "browser")
        self.settings_manager.set("browser_cookies", "chrome")

        mock_ydl_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "id": "7106594312292453678",
            "uploader": "funny_creator",
            "title": "Single TikTok Video",
            "duration": 30,
            "webpage_url": "https://www.tiktok.com/@funny_creator/video/7106594312292453678",
        }

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            logs = []
            items = self.tt_adapter.extract_entries(
                url="https://www.tiktok.com/@funny_creator/video/7106594312292453678",
                log_callback=logs.append,
                browser_cookies="chrome",
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].video_id, "7106594312292453678")

            ydl_call_opts = mock_ydl_cls.call_args[0][0]
            self.assertNotIn("cookiefile", ydl_call_opts)
            self.assertNotIn("cookiesfrombrowser", ydl_call_opts)

    @patch("yt_dlp.YoutubeDL")
    def test_tiktok_video_download_ignores_youtube_cookies(self, mock_ydl_cls):
        """Verify TikTok video download via YtDlpEngine ignores YouTube custom cookie file."""
        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("browser_cookies", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))

        mock_ydl_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "id": "7106594312292453678",
            "title": "Downloaded TikTok",
        }

        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="Downloaded TikTok",
            duration="00:30",
            status=VideoStatus.READY,
            url="https://www.tiktok.com/@creator/video/7106594312292453678",
            platform="tiktok",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            format="MP4",
            quality="Best",
            browser_cookies="custom_file",  # Legacy setting passed in
        )

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            logs = []
            target_dir = Path(self.tmp_dir.name) / "output"
            target_dir.mkdir(parents=True, exist_ok=True)

            res = self.engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=target_dir,
                log_callback=logs.append,
            )

            self.assertTrue(res["success"])
            ydl_call_opts = mock_ydl_cls.call_args[0][0]
            self.assertNotIn("cookiefile", ydl_call_opts)
            self.assertNotIn("cookiesfrombrowser", ydl_call_opts)
            self.assertTrue(any("[AUTH] Platform: TikTok | Authentication: None" in l for l in logs))

    @patch("yt_dlp.YoutubeDL")
    def test_tiktok_metadata_and_thumbnail_extraction_ignores_cookies(self, mock_ydl_cls):
        """Verify InfoManager and ThumbnailManager for TikTok video ignore YouTube cookies."""
        mock_ydl_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "id": "7106594312292453678",
            "title": "TikTok Meta",
            "description": "Caption text",
        }

        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="TikTok Meta",
            duration="00:15",
            status=VideoStatus.READY,
            url="https://www.tiktok.com/@creator/video/7106594312292453678",
            platform="tiktok",
        )
        settings = DownloadSettings(
            save_metadata=True,
            save_description=True,
            download_thumbnail=True,
            browser_cookies="chrome",
        )

        target_dir = Path(self.tmp_dir.name) / "meta_output"
        target_dir.mkdir(parents=True, exist_ok=True)

        logs = []
        # Info extraction
        InfoManager.save_video_info(
            video=video,
            settings=settings,
            target_dir=target_dir,
            log_callback=logs.append,
        )
        ydl_call_opts = mock_ydl_cls.call_args[0][0]
        self.assertNotIn("cookiefile", ydl_call_opts)
        self.assertNotIn("cookiesfrombrowser", ydl_call_opts)

        # Thumbnail extraction
        ThumbnailManager.download_thumbnail(
            video=video,
            settings=settings,
            target_dir=target_dir,
            log_callback=logs.append,
        )
        ydl_thumb_opts = mock_ydl_cls.call_args[0][0]
        self.assertNotIn("cookiefile", ydl_thumb_opts)
        self.assertNotIn("cookiesfrombrowser", ydl_thumb_opts)

    # -------------------------------------------------------------------------
    # Logging and Privacy Compliance
    # -------------------------------------------------------------------------

    def test_logging_does_not_leak_sensitive_cookie_info(self):
        """Ensure auth logs never print cookie file paths, cookie contents, or tokens."""
        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            logs = []
            self.engine.build_base_ydl_opts(
                log_callback=logs.append,
                platform="youtube",
            )

            for l in logs:
                # Should not leak secret token from dummy cookie file
                self.assertNotIn("test_token", l)
                # Should not leak absolute path to cookie file in the auth log description
                self.assertNotIn(str(self.cookie_file.resolve()), l)
                self.assertIn("Custom Cookie File", l)

    def test_gui_on_scan_clicked_no_unbound_local_error(self):
        """Verify MainWindow._on_scan_clicked executes without UnboundLocalError for both YouTube and TikTok."""
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        try:
            with patch("gui.main_window.ChannelScanWorker") as mock_worker:
                mock_worker_instance = MagicMock()
                mock_worker_instance.isRunning.return_value = False
                mock_worker.return_value = mock_worker_instance

                # Test YouTube URL scan
                window.url_input.setText("https://www.youtube.com/@Veritasium")
                window._on_scan_clicked()
                self.assertTrue(mock_worker.called)

                # Test TikTok URL scan
                mock_worker.reset_mock()
                window.url_input.setText("https://www.tiktok.com/@creator")
                window._on_scan_clicked()
                self.assertTrue(mock_worker.called)

                # Test Douyin URL scan (temporarily enabled to verify adapter lookup without UnboundLocalError)
                mock_worker.reset_mock()
                PlatformRegistry.set_platform_available("douyin", True)
                try:
                    window.url_input.setText("https://www.douyin.com/video/7106594312292453678")
                    window._on_scan_clicked()
                    self.assertTrue(mock_worker.called)
                finally:
                    PlatformRegistry.reset_availability_overrides()
        finally:
            window._download_manager = None
            window.close()

    def test_case_douyin_auth_browser_scoping(self):
        """Douyin browser cookies scoping: Douyin uses Edge while YouTube uses Chrome."""
        self.settings_manager.set("auth_method", "browser")
        self.settings_manager.set("browser_cookies", "chrome")
        self.settings_manager.set("douyin_auth_method", "browser")
        self.settings_manager.set("douyin_browser_cookies", "edge")

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            # Douyin opts: must use Edge, NOT Chrome
            opts_dy = self.engine.build_base_ydl_opts(
                platform="douyin",
            )
            self.assertIn("cookiesfrombrowser", opts_dy)
            self.assertEqual(opts_dy["cookiesfrombrowser"][0], "edge")

            # YouTube opts: must use Chrome, NOT Edge
            opts_yt = self.engine.build_base_ydl_opts(
                platform="youtube",
            )
            self.assertIn("cookiesfrombrowser", opts_yt)
            self.assertEqual(opts_yt["cookiesfrombrowser"][0], "chrome")

            # TikTok opts: has NONE
            opts_tt = self.engine.build_base_ydl_opts(
                platform="tiktok",
            )
            self.assertNotIn("cookiesfrombrowser", opts_tt)

    def test_case_douyin_custom_cookie_file_scoping(self):
        """Douyin custom cookie file scoping: Douyin uses dy_cookies while YouTube uses yt_cookies."""
        dy_cookie = Path(self.tmp_dir.name) / "douyin_cookies.txt"
        dy_cookie.write_text("# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t0\ts_v_web_id\ttest_dy\n", encoding="utf-8")

        self.settings_manager.set("auth_method", "custom_file")
        self.settings_manager.set("custom_cookie_file", str(self.cookie_file.resolve()))
        self.settings_manager.set("douyin_auth_method", "custom_file")
        self.settings_manager.set("douyin_custom_cookie_file", str(dy_cookie.resolve()))

        with patch("core.settings.SettingsManager", return_value=self.settings_manager):
            # Douyin opts
            opts_dy = self.engine.build_base_ydl_opts(
                platform="douyin",
            )
            self.assertIn("cookiefile", opts_dy)
            self.assertEqual(opts_dy["cookiefile"], str(dy_cookie.resolve()))

            # YouTube opts
            opts_yt = self.engine.build_base_ydl_opts(
                platform="youtube",
            )
            self.assertIn("cookiefile", opts_yt)
            self.assertEqual(opts_yt["cookiefile"], str(self.cookie_file.resolve()))

            # TikTok opts: has NONE
            opts_tt = self.engine.build_base_ydl_opts(
                platform="tiktok",
            )
            self.assertNotIn("cookiefile", opts_tt)


if __name__ == "__main__":
    unittest.main()
