"""
test_douyin_adapter.py
Comprehensive unit tests for the Douyin platform adapter, URL detection, capabilities,
error handling, file organization, platform isolation, and localization in Channel Harvest.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.platform.douyin import DouyinAdapter
from core.platform.detector import PlatformDetector, PlatformRegistry
from core.error_classifier import ErrorClassifier, ErrorCategory
from core.paths import resolve_video_output_dir, should_include_video_id, resolve_media_filename, sanitize_filename
from core.settings import SettingsManager
from core.i18n import I18nManager, tr


class TestDouyinAdapter(unittest.TestCase):
    """Tests for the DouyinAdapter implementation."""

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        self.adapter = DouyinAdapter()
        PlatformRegistry.set_platform_available("douyin", True)

    def tearDown(self):
        PlatformRegistry.reset_availability_overrides()
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    def test_properties(self):
        self.assertEqual(self.adapter.platform_id, "douyin")
        self.assertEqual(self.adapter.display_name, "Douyin")
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_subtitles)
        self.assertFalse(caps.supports_chapters)
        self.assertFalse(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_browser_cookies)
        self.assertTrue(caps.supports_cookie_file)
        self.assertEqual(caps.archive_prefix, "douyin")

    def test_matches_url(self):
        # Valid Douyin URLs
        valid_urls = [
            "https://www.douyin.com/video/7106594312292453678",
            "http://douyin.com/video/7106594312292453678",
            "https://www.douyin.com/note/7106594312292453678",
            "https://v.douyin.com/iABCxyz/",
            "https://www.iesdouyin.com/share/video/7106594312292453678/",
            "https://douyin.com/user/MS4wLjABAAAA...",
            "7.88 复制打开抖音，看看【小明的作品】 https://v.douyin.com/iABCxyz/ 01/22 b@h.rc",
        ]
        for url in valid_urls:
            self.assertTrue(self.adapter.matches_url(url), f"Should match Douyin: {url}")

        # Invalid or non-Douyin URLs
        invalid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.tiktok.com/@tiktok/video/7106594312292453678",
            "https://vm.tiktok.com/ZM8example/",
            "https://www.instagram.com/reel/C123456/",
            "https://example.com/douyin",
            "",
            None,
        ]
        for url in invalid_urls:
            self.assertFalse(self.adapter.matches_url(url), f"Should not match Douyin: {url}")

    def test_validate_url(self):
        # Valid URLs
        valid_urls = [
            "https://www.douyin.com/video/7106594312292453678",
            "https://v.douyin.com/iABCxyz/",
            "https://www.iesdouyin.com/share/video/7106594312292453678/",
            "7.88 复制打开抖音，看看【作品】 https://v.douyin.com/iABCxyz/",
        ]
        for url in valid_urls:
            is_valid, err = self.adapter.validate_url(url)
            self.assertTrue(is_valid, f"Should be valid: {url}, got error: {err}")
            self.assertEqual(err, "")

        # Empty
        is_valid, err = self.adapter.validate_url("")
        self.assertFalse(is_valid)
        self.assertIn("cannot be empty", err)

        # No scheme
        is_valid, err = self.adapter.validate_url("ftp://douyin.com/video/123")
        self.assertFalse(is_valid)
        self.assertIn("http:// or https://", err)

        # Non-Douyin domain
        is_valid, err = self.adapter.validate_url("https://www.tiktok.com/@creator/video/123")
        self.assertFalse(is_valid)
        self.assertIn("not a valid Douyin domain", err)

        # Bare domain with no path
        is_valid, err = self.adapter.validate_url("https://www.douyin.com/")
        self.assertFalse(is_valid)
        self.assertIn("creator profile link", err)

    def test_normalize_url_direct(self):
        url = "https://www.douyin.com/video/7106594312292453678?mode=1&from_tab=feed"
        normalized = self.adapter.normalize_url(url)
        self.assertEqual(normalized, "https://www.douyin.com/video/7106594312292453678")

        ies_url = "https://www.iesdouyin.com/share/video/7106594312292453678/?timestamp=123"
        normalized_ies = self.adapter.normalize_url(ies_url)
        self.assertEqual(normalized_ies, "https://www.douyin.com/video/7106594312292453678")

        note_url = "https://www.douyin.com/note/7106594312292453678"
        normalized_note = self.adapter.normalize_url(note_url)
        self.assertEqual(normalized_note, "https://www.douyin.com/video/7106594312292453678")

    def test_normalize_profile_urls(self):
        """Profile URLs must normalize to https://www.douyin.com/user/<sec_uid> and never iesdouyin."""
        sec_uid = "MS4wLjABAAAAj8CXcr_EyHRD-rw5EcQcPECcUhwZdy5A7O9JmaSVeZQ"
        ies_profile = f"https://www.iesdouyin.com/share/user/{sec_uid}?with_sec_did=1&sec_uid={sec_uid}"
        normalized = self.adapter.normalize_url(ies_profile)
        self.assertEqual(normalized, f"https://www.douyin.com/user/{sec_uid}")

        direct_profile = f"https://www.douyin.com/user/{sec_uid}?extra=param"
        normalized_direct = self.adapter.normalize_url(direct_profile)
        self.assertEqual(normalized_direct, f"https://www.douyin.com/user/{sec_uid}")

    @patch("core.platform.douyin.DouyinAdapter.resolve_short_url")
    def test_normalize_url_with_short_link(self, mock_resolve):
        mock_resolve.return_value = "https://www.douyin.com/video/7412345678901234567?previous_page=app_code"
        raw_share = "8.12 复制打开抖音，看看【测试视频】 https://v.douyin.com/iGoodLink/ 01/22"
        normalized = self.adapter.normalize_url(raw_share)
        self.assertEqual(normalized, "https://www.douyin.com/video/7412345678901234567")
        mock_resolve.assert_called_once_with("https://v.douyin.com/iGoodLink/")

    @patch("core.platform.douyin.DouyinAdapter.resolve_short_url")
    def test_normalize_short_profile_url(self, mock_resolve):
        sec_uid = "MS4wLjABAAAAj8CXcr_EyHRD-rw5EcQcPECcUhwZdy5A7O9JmaSVeZQ"
        mock_resolve.return_value = f"https://www.iesdouyin.com/share/user/{sec_uid}?with_sec_did=1"
        normalized = self.adapter.normalize_url("https://v.douyin.com/lh_6q3qWC-U/")
        self.assertEqual(normalized, f"https://www.douyin.com/user/{sec_uid}")
        mock_resolve.assert_called_once_with("https://v.douyin.com/lh_6q3qWC-U/")

    def test_auth_resolution_and_isolation(self):
        """Douyin resolves its own auth configuration and ignores YouTube's."""
        # 1. Default -> None
        auth_config = self.adapter.get_auth_config()
        self.assertFalse(auth_config.is_active)
        self.assertEqual(auth_config.auth_method, "none")
        self.assertEqual(auth_config.description, "None")

        # 2. Browser auth configured for Douyin
        mock_sm = MagicMock()
        mock_sm.get.side_effect = lambda k, d=None: {
            "douyin_auth_method": "browser",
            "douyin_browser_cookies": "edge",
            "douyin_browser_profile": "Profile 1",
            "browser_cookies": "chrome",  # YouTube's setting
        }.get(k, d)

        auth_edge = self.adapter.get_auth_config(mock_sm)
        self.assertTrue(auth_edge.is_active)
        self.assertEqual(auth_edge.auth_method, "browser")
        self.assertEqual(auth_edge.browser_name, "edge")
        self.assertEqual(auth_edge.browser_profile, "Profile 1")
        self.assertNotEqual(auth_edge.browser_name, "chrome")

    def test_archive_tag_and_url_builder(self):
        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="Douyin Video",
            duration="00:15",
            status=VideoStatus.READY,
            platform="douyin",
        )
        self.assertEqual(self.adapter.get_archive_tag(video), "douyin 7106594312292453678")
        self.assertEqual(
            self.adapter.build_video_url("7106594312292453678"),
            "https://www.douyin.com/video/7106594312292453678",
        )

    def test_profile_scan_requires_cookies_guidance(self):
        """Profile scanning without cookies must raise informative ExtractionError directing to Settings."""
        from downloader.ytdlp_engine import ExtractionError
        profile_url = "https://www.douyin.com/user/MS4wLjABAAAAabcdefg123456"
        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.extract_entries(profile_url)
        err_msg = str(ctx.exception)
        self.assertIn("Douyin requires fresh session cookies", err_msg)
        self.assertIn("Settings", err_msg)


class TestPlatformDetectorDouyin(unittest.TestCase):
    """Tests for platform detection and registry resolution for Douyin."""

    def test_identify_platform_id(self):
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.douyin.com/video/7106594312292453678"), "douyin")
        self.assertEqual(PlatformDetector.identify_platform_id("https://v.douyin.com/iABCxyz/"), "douyin")
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.iesdouyin.com/share/video/123"), "douyin")
        self.assertEqual(PlatformDetector.identify_platform_id("https://douyin.com/video/123"), "douyin")
        self.assertEqual(PlatformDetector.identify_platform_id("7.88 复制打开抖音... https://v.douyin.com/iABC/"), "douyin")

        # Isolation against YouTube and TikTok
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.tiktok.com/@user/video/123"), "tiktok")
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.youtube.com/watch?v=123"), "youtube")

    def test_extract_url(self):
        text = "4.56 复制打开抖音，看看【小明的作品】 https://v.douyin.com/iGoodUrl/ 长按复制此条消息"
        extracted = PlatformDetector.extract_url(text)
        self.assertEqual(extracted, "https://v.douyin.com/iGoodUrl/")

    def test_registry_resolution(self):
        dy_adapter = PlatformRegistry.get_adapter("douyin")
        self.assertIsNotNone(dy_adapter)
        self.assertEqual(dy_adapter.platform_id, "douyin")

        adapter_by_url = PlatformRegistry.get_adapter_for_url("https://www.douyin.com/video/7106594312292453678")
        self.assertIsNotNone(adapter_by_url)
        self.assertEqual(adapter_by_url.platform_id, "douyin")


class TestDouyinErrorClassification(unittest.TestCase):
    """Tests error classification for Douyin-specific error messages."""

    def test_argus_fresh_cookies_classification(self):
        raw = "ERROR: [Douyin] Fresh cookies (not necessarily logged in) are needed to retrieve video details: ArgusSecurityPlugin challenge"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Extraction", video_id="7106594312292453678", platform="douyin")
        self.assertEqual(err.category, ErrorCategory.DOUYIN_API_BLOCKED)
        self.assertFalse(err.retryable)
        self.assertIn("Douyin", err.user_message)
        self.assertNotIn("YouTube", err.user_message)
        self.assertNotIn("Google", err.user_message)

    def test_douyin_http_403(self):
        raw = "ERROR: [Douyin] 7106594312292453678: HTTP Error 403: Forbidden"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Extraction", video_id="7106594312292453678", platform="douyin")
        self.assertEqual(err.category, ErrorCategory.HTTP_403)
        self.assertIn("Douyin", err.user_message)
        self.assertNotIn("YouTube", err.user_message)

    def test_douyin_video_unavailable(self):
        raw = "ERROR: [Douyin] 7106594312292453678: Video unavailable or has been deleted"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Extraction", video_id="7106594312292453678", platform="douyin")
        self.assertEqual(err.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertIn("Douyin", err.user_message)
        self.assertNotIn("YouTube", err.user_message)

    def test_douyin_private_video(self):
        raw = "ERROR: [Douyin] 7106594312292453678: This video is private and only visible to friends"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Extraction", video_id="7106594312292453678", platform="douyin")
        self.assertEqual(err.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertIn("Douyin", err.user_message)
        self.assertNotIn("YouTube", err.user_message)

    def test_localized_douyin_error_messages(self):
        raw = "ERROR: [Douyin] 7106594312292453678: HTTP Error 403: Forbidden"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Extraction", video_id="7106594312292453678", platform="douyin")

        # English
        I18nManager.set_language("en")
        msg_en = err.get_localized_user_message("en")
        self.assertIn("Douyin", msg_en)
        self.assertNotIn("YouTube", msg_en)

        # Chinese
        I18nManager.set_language("zh_CN")
        msg_zh = err.get_localized_user_message("zh_CN")
        self.assertIn("抖音", msg_zh)
        self.assertNotIn("YouTube", msg_zh)
        I18nManager.set_language("en")


class TestDouyinPathsAndFilenames(unittest.TestCase):
    """Tests file organization and output paths for Douyin downloads."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.base_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_douyin_19_digit_id_detection(self):
        """Douyin IDs are 19 digits long. should_include_video_id must correctly recognize them."""
        vid_id_1 = "7106594312292453678"
        vid_id_2 = "7106594312292453679"
        title = "Douyin Dance Video"

        # Explicit setting enabled
        self.assertTrue(should_include_video_id(title, vid_id_1, include_video_id_setting=True))

        # Explicit setting disabled, no collision
        self.assertFalse(should_include_video_id(title, vid_id_1, include_video_id_setting=False))

        # Explicit setting disabled, duplicate title in queue -> collision detected
        self.assertTrue(
            should_include_video_id(
                title,
                vid_id_1,
                include_video_id_setting=False,
                duplicate_titles_in_queue={title},
            )
        )

        # On-disk collision with another 19-digit Douyin ID
        target_dir = self.base_dir / "test_channel"
        target_dir.mkdir(parents=True)
        collision_file = target_dir / f"{title} [{vid_id_2}].mp4"
        collision_file.touch()

        self.assertTrue(
            should_include_video_id(
                title,
                vid_id_1,
                include_video_id_setting=False,
                target_dir=target_dir,
            )
        )

    def test_douyin_folder_structure(self):
        vid_id = "7106594312292453678"
        title = "Dance Performance"
        channel_title = "Douyin Dancer"

        # Base channel folder without individual video folder
        out_dir = resolve_video_output_dir(
            base_download_dir=self.base_dir,
            channel_title=channel_title,
            create_channel_folder=True,
            video_title=title,
            video_id=vid_id,
            create_individual_video_folders=False,
        )
        self.assertEqual(out_dir, self.base_dir / "@Douyin Dancer" if False else self.base_dir / "Douyin Dancer")

        # Individual video folder
        out_dir_indiv = resolve_video_output_dir(
            base_download_dir=self.base_dir,
            channel_title=channel_title,
            create_channel_folder=True,
            video_title=title,
            video_id=vid_id,
            create_individual_video_folders=True,
        )
        self.assertEqual(out_dir_indiv, self.base_dir / "Douyin Dancer" / title)


class TestDouyinLocalization(unittest.TestCase):
    """Tests bilingual localization strings for Douyin."""

    def test_translations_en(self):
        I18nManager.set_language("en")
        self.assertEqual(I18nManager.tr("platform_douyin"), "Douyin")
        self.assertIn("Douyin", I18nManager.tr("scan_douyin"))
        self.assertIn("douyin.com", I18nManager.tr("douyin_url_placeholder"))
        self.assertIn("Douyin", I18nManager.tr("tooltip_douyin_no_subs"))
        self.assertIn("Douyin", I18nManager.tr("tooltip_douyin_no_chapters"))

    def test_translations_zh(self):
        I18nManager.set_language("zh_CN")
        self.assertEqual(I18nManager.tr("platform_douyin"), "抖音")
        self.assertEqual(I18nManager.tr("scan_douyin"), "解析视频")
        self.assertIn("douyin.com", I18nManager.tr("douyin_url_placeholder"))
        self.assertIn("抖音", I18nManager.tr("tooltip_douyin_no_subs"))
        self.assertIn("抖音", I18nManager.tr("tooltip_douyin_no_chapters"))
        I18nManager.set_language("en")

class TestDouyinExtraction(unittest.TestCase):
    """Tests metadata extraction and authentication isolation in download engine."""

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        self.adapter = DouyinAdapter()
        PlatformRegistry.set_platform_available("douyin", True)

    def tearDown(self):
        PlatformRegistry.reset_availability_overrides()
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    @patch("yt_dlp.YoutubeDL")
    def test_mock_single_video_extraction(self, mock_ydl_cls):
        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.return_value = {
            "id": "7106594312292453678",
            "title": "Douyin Viral Dance Video",
            "duration": 30.0,
            "uploader": "CoolDancer",
            "uploader_id": "MS4wLjABAAAA...",
            "like_count": 99999,
            "comment_count": 8888,
            "webpage_url": "https://www.douyin.com/video/7106594312292453678",
        }

        logs = []
        items = self.adapter.extract_entries(
            "https://www.douyin.com/video/7106594312292453678",
            log_callback=logs.append,
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.video_id, "7106594312292453678")
        self.assertEqual(item.title, "Douyin Viral Dance Video")
        self.assertEqual(item.duration, "00:30")
        self.assertEqual(item.duration_seconds, 30)
        self.assertEqual(item.channel_title, "CoolDancer")
        self.assertEqual(item.platform, "douyin")
        self.assertEqual(item.status, VideoStatus.READY)
        self.assertEqual(item.extra_metadata["like_count"], 99999)
        self.assertEqual(item.extra_metadata["comment_count"], 8888)

    def test_douyin_engine_auth_isolation(self):
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        logs = []
        opts = engine.build_base_ydl_opts(
            log_callback=logs.append,
            browser_cookies="chrome",
            platform="douyin",
        )
        self.assertNotIn("cookiefile", opts)
        self.assertNotIn("cookiesfrombrowser", opts)
        self.assertNotIn("js_runtimes", opts)
        self.assertTrue(any("[AUTH] Platform: Douyin | Authentication: None" in l for l in logs))

    @patch("urllib.request.build_opener")
    def test_mock_profile_post_api_extraction(self, mock_build_opener):
        import json
        import io
        mock_response = io.BytesIO(json.dumps({
            "status_code": 0,
            "has_more": 0,
            "aweme_list": [
                {
                    "aweme_id": "7106594312292453678",
                    "desc": "Amazing Douyin Dance Performance",
                    "duration": 45000,
                    "author": {
                        "nickname": "DancerStar",
                        "sec_uid": "MS4wLjABAAAA...",
                    },
                    "statistics": {
                        "digg_count": 50000,
                        "comment_count": 1200,
                    },
                    "video": {
                        "cover": {
                            "url_list": ["https://p3.douyinpic.com/cover1.jpg"]
                        }
                    }
                }
            ]
        }).encode("utf-8"))
        mock_opener = MagicMock()
        mock_opener.open.return_value.__enter__.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        # Configure adapter with active mock cookie config
        mock_auth = MagicMock()
        mock_auth.is_active = True
        mock_auth.cookie_file = None
        mock_auth.browser_name = None

        with patch.object(self.adapter, "get_auth_config", return_value=mock_auth):
            items = self.adapter.extract_entries(
                "https://www.douyin.com/user/MS4wLjABAAAA...",
            )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.video_id, "7106594312292453678")
        self.assertEqual(item.title, "Amazing Douyin Dance Performance")
        self.assertEqual(item.channel_title, "DancerStar")
        self.assertEqual(item.platform, "douyin")
        self.assertEqual(item.duration, "00:45")
        self.assertEqual(item.extra_metadata["thumbnail"], "https://p3.douyinpic.com/cover1.jpg")
        self.assertEqual(item.status, VideoStatus.READY)

    @patch("yt_dlp.YoutubeDL")
    def test_fresh_cookies_error_fails_fast(self, mock_ydl_cls):
        from yt_dlp.utils import DownloadError
        from downloader.ytdlp_engine import ExtractionError
        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = DownloadError(
            "ERROR: [Douyin] Fresh cookies (not necessarily logged in) are needed to retrieve video details: ArgusSecurityPlugin challenge"
        )

        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.extract_entries(
                "https://www.douyin.com/video/7106594312292453678",
            )
        err_msg = str(ctx.exception)
        self.assertIn("Douyin", err_msg)
        self.assertIn("Settings", err_msg)


class TestDouyinUIIntegration(unittest.TestCase):
    """Verifies Douyin UI specific behaviors: subtitle column removal and title expansion."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_video_table_subtitle_column_hidden_on_douyin(self):
        from gui.video_table import VideoTableWidget

        vt = VideoTableWidget()
        vt.resize(1000, 500)
        vt.show()
        self.app.processEvents()

        # YouTube platform
        vt.set_platform("youtube")
        self.app.processEvents()
        self.assertFalse(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        yt_title_width = vt.table.columnWidth(vt.COL_TITLE)

        # Douyin platform -> Subtitle hidden, Title horizontal width expanded
        vt.set_platform("douyin")
        self.app.processEvents()
        self.assertTrue(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        douyin_title_width = vt.table.columnWidth(vt.COL_TITLE)
        self.assertGreater(douyin_title_width, yt_title_width)
        self.assertEqual(douyin_title_width - yt_title_width, 150)

        # Switch back to YouTube -> Subtitle restored, Title width restored
        vt.set_platform("youtube")
        self.app.processEvents()
        self.assertFalse(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        self.assertEqual(vt.table.columnWidth(vt.COL_SUBTITLE), 150)
        self.assertEqual(vt.table.columnWidth(vt.COL_TITLE), yt_title_width)

        vt.close()


class TestDouyinAuthenticationIntegration(unittest.TestCase):
    """Verifies Douyin authentication testing, diagnostics, and scan/download cookie attachment."""

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        self.adapter = DouyinAdapter()

        # Create dummy valid Douyin cookie file
        self.dy_cookie_file = Path(self.tmp_dir.name) / "douyin_cookies.txt"
        self.dy_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".douyin.com\tTRUE\t/\tTRUE\t0\tsessionid\ttest_session_123\n"
            ".douyin.com\tTRUE\t/\tTRUE\t0\tttwid\ttest_ttwid_456\n",
            encoding="utf-8"
        )

        # Create cookie file with no Douyin cookies
        self.yt_cookie_file = Path(self.tmp_dir.name) / "youtube_cookies.txt"
        self.yt_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tyt_token\n",
            encoding="utf-8"
        )
        PlatformRegistry.set_platform_available("douyin", True)

    def tearDown(self):
        PlatformRegistry.reset_availability_overrides()
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    def test_douyin_cookie_testing_and_diagnostics(self):
        from downloader.auth_checker import AuthChecker, AuthStatusCode

        # 1. Test Douyin cookie file with valid Douyin session
        result = AuthChecker.test_authentication(
            "custom_file",
            custom_cookie_path=str(self.dy_cookie_file),
            platform="douyin",
        )
        self.assertTrue(result.success)
        self.assertTrue(result.has_session)
        self.assertEqual(result.status_code, AuthStatusCode.DOUYIN_SESSION_AUTHENTICATED)
        self.assertEqual(result.platform, "douyin")
        self.assertEqual(result.youtube_cookie_count, 2)

        report = result.to_diagnostic_report()
        self.assertIn("Channel Harvest Douyin Authentication Diagnostic", report)
        self.assertIn("Platform:               Douyin", report)
        self.assertIn("Douyin Cookies:        2", report)
        self.assertIn("Session Authenticated:  Yes", report)

        # 2. Test cookie file without Douyin cookies
        no_dy_res = AuthChecker.test_authentication(
            "custom_file",
            custom_cookie_path=str(self.yt_cookie_file),
            platform="douyin",
        )
        self.assertFalse(no_dy_res.success)
        self.assertEqual(no_dy_res.status_code, AuthStatusCode.COOKIE_FILE_INVALID)
        self.assertEqual(no_dy_res.stage, "Douyin Cookie Verification")
        self.assertIn("no Douyin cookies", no_dy_res.reason)

    @patch("yt_dlp.YoutubeDL")
    def test_douyin_scan_with_cookie_file_configured(self, mock_ydl_cls):
        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.return_value = {
            "id": "7106594312292453678",
            "title": "Douyin Video with Cookies",
            "duration": 15.0,
            "uploader": "Creator",
            "webpage_url": "https://www.douyin.com/video/7106594312292453678",
        }

        # Save douyin cookie setting in settings manager
        self.isolated_sm.set("douyin_auth_method", "custom_file")
        self.isolated_sm.set("douyin_browser_cookies", "custom_file")
        self.isolated_sm.set("douyin_custom_cookie_file", str(self.dy_cookie_file))

        logs = []
        items = self.adapter.extract_entries(
            "https://www.douyin.com/video/7106594312292453678",
            log_callback=logs.append,
            custom_cookie_file=str(self.dy_cookie_file),
        )
        self.assertEqual(len(items), 1)

        # Verify yt-dlp was invoked with cookiefile
        call_opts = mock_ydl_cls.call_args[0][0]
        self.assertEqual(call_opts.get("cookiefile"), str(self.dy_cookie_file.resolve()))
        self.assertTrue(any("[AUTH] Platform: Douyin | Authentication: Custom Cookie File" in l for l in logs))

    @patch("yt_dlp.YoutubeDL")
    def test_douyin_download_with_cookie_file_configured(self, mock_ydl_cls):
        from downloader.ytdlp_engine import YtDlpEngine

        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.return_value = {"id": "7106594312292453678", "title": "Test Video"}

        engine = YtDlpEngine()
        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="Test Video",
            duration="00:15",
            url="https://www.douyin.com/video/7106594312292453678",
            platform="douyin",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            douyin_auth_method="custom_file",
            douyin_browser_cookies="custom_file",
            douyin_custom_cookie_file=str(self.dy_cookie_file),
            custom_cookie_file=str(self.dy_cookie_file),
        )

        logs = []
        target_dir = Path(self.tmp_dir.name) / "downloads"
        res = engine.download_single_video(
            video=video,
            settings=settings,
            target_dir=target_dir,
            log_callback=logs.append,
        )
        self.assertTrue(res["success"])

        # Verify yt-dlp received cookiefile
        call_opts = mock_ydl_cls.call_args[0][0]
        self.assertEqual(call_opts.get("cookiefile"), str(self.dy_cookie_file.resolve()))
        self.assertTrue(any("[AUTH] Platform: Douyin | Authentication: Custom Cookie File" in l for l in logs))


class TestDouyinMetadataAndErrorClassification(unittest.TestCase):
    """
    Dedicated tests for Douyin cookie validation, metadata extraction diagnostics,
    error classification, and fail-fast behavior.
    """

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        self.adapter = DouyinAdapter()

        # Valid cookie file
        self.valid_cookie_file = Path(self.tmp_dir.name) / "valid_cookies.txt"
        self.valid_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".douyin.com\tTRUE\t/\tTRUE\t0\ts_v_web_id\tverify_test123\n"
            ".douyin.com\tTRUE\t/\tTRUE\t0\tttwid\tttwid_test456\n"
            ".douyin.com\tTRUE\t/\tTRUE\t0\tUIFID_TEMP\tuifid_temp_789\n",
            encoding="utf-8"
        )

        # Empty cookie file
        self.empty_cookie_file = Path(self.tmp_dir.name) / "empty_cookies.txt"
        self.empty_cookie_file.write_text("", encoding="utf-8")

        # Invalid format cookie file
        self.bad_format_file = Path(self.tmp_dir.name) / "bad_format.txt"
        self.bad_format_file.write_text("Hello this is just a random text document.", encoding="utf-8")

        # Non-existent file
        self.missing_file = Path(self.tmp_dir.name) / "does_not_exist.txt"
        PlatformRegistry.set_platform_available("douyin", True)

    def tearDown(self):
        PlatformRegistry.reset_availability_overrides()
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    def test_inspect_cookie_file_safe(self):
        from core.platform.douyin import inspect_cookie_file_safe

        # 1. Valid file
        is_ok, msg, details = inspect_cookie_file_safe(str(self.valid_cookie_file))
        self.assertTrue(is_ok)
        self.assertEqual(details["total_cookies"], 3)
        self.assertEqual(details["douyin_cookies"], 3)
        self.assertTrue(details["has_s_v_web_id"])
        self.assertTrue(details["has_ttwid"])
        self.assertTrue(details["has_uifid_temp"])
        self.assertFalse(details["has_uifid"])

        # 2. Empty file
        is_ok, msg, _ = inspect_cookie_file_safe(str(self.empty_cookie_file))
        self.assertFalse(is_ok)
        self.assertIn("empty", msg.lower())

        # 3. Bad format file
        is_ok, msg, _ = inspect_cookie_file_safe(str(self.bad_format_file))
        self.assertFalse(is_ok)
        self.assertIn("netscape", msg.lower())

        # 4. Missing file
        is_ok, msg, _ = inspect_cookie_file_safe(str(self.missing_file))
        self.assertFalse(is_ok)
        self.assertIn("does not exist", msg.lower())

        # 5. Empty path
        is_ok, msg, _ = inspect_cookie_file_safe("")
        self.assertFalse(is_ok)

    @patch("yt_dlp.YoutubeDL")
    def test_douyin_extraction_with_cookies_fails_fast_with_api_blocked(self, mock_ydl_cls):
        """
        When cookies are configured but Douyin returns 403 / ArgusSecurityPlugin / Fresh cookies needed,
        verify it fails fast, logs safe diagnostics, passes cookiefile to yt-dlp, and raises DOUYIN_API_BLOCKED.
        """
        from yt_dlp.utils import DownloadError
        from downloader.ytdlp_engine import ExtractionError

        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = DownloadError(
            "ERROR: [Douyin] 7106594312292453678: Failed to download web detail JSON: HTTP Error 403: Forbidden\n"
            "ERROR: [Douyin] 7106594312292453678: Fresh cookies (not necessarily logged in) are needed"
        )

        logs = []
        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.extract_entries(
                "https://www.douyin.com/video/7106594312292453678",
                log_callback=logs.append,
                custom_cookie_file=str(self.valid_cookie_file),
            )

        err_msg = str(ctx.exception)
        self.assertIn("DOUYIN_API_BLOCKED", err_msg)
        self.assertIn("ArgusSecurityPlugin", err_msg)

        # Verify yt-dlp received cookiefile
        call_opts = mock_ydl_cls.call_args[0][0]
        self.assertEqual(call_opts.get("cookiefile"), str(self.valid_cookie_file.resolve()))

        # Verify safe diagnostics were logged
        self.assertTrue(any("[AUTH DIAGNOSTIC] Douyin cookie file verified:" in l for l in logs))
        self.assertTrue(any("[AUTH] Passing verified cookie file to yt-dlp extraction engine." in l for l in logs))
        self.assertFalse(any("verify_test123" in l for l in logs))  # Never leak cookie secret values

        # Verify classification
        classified = ErrorClassifier.classify(err_msg, stage="scan", platform="douyin")
        self.assertEqual(classified.category, ErrorCategory.DOUYIN_API_BLOCKED)
        self.assertIn("Argus", classified.title)
        self.assertIn("ArgusSecurityPlugin", classified.get_localized_user_message("zh_CN"))

    @patch("yt_dlp.YoutubeDL")
    def test_douyin_extraction_no_cookies_fails_fast_with_session_required(self, mock_ydl_cls):
        """
        When no cookies are configured and Douyin returns 403 / Fresh cookies needed,
        verify it raises DOUYIN_SESSION_REQUIRED.
        """
        from yt_dlp.utils import DownloadError
        from downloader.ytdlp_engine import ExtractionError

        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = DownloadError(
            "ERROR: [Douyin] 7106594312292453678: Fresh cookies (not necessarily logged in) are needed"
        )

        logs = []
        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.extract_entries(
                "https://www.douyin.com/video/7106594312292453678",
                log_callback=logs.append,
            )

        err_msg = str(ctx.exception)
        self.assertIn("DOUYIN_SESSION_REQUIRED", err_msg)
        self.assertTrue(any("Authentication: None" in l for l in logs))

        # Verify classification
        classified = ErrorClassifier.classify(err_msg, stage="scan", platform="douyin")
        self.assertEqual(classified.category, ErrorCategory.DOUYIN_SESSION_REQUIRED)
        self.assertIn("会话 Cookie", classified.get_localized_title("zh_CN"))

    def test_douyin_extraction_with_invalid_cookie_file_raises_cookie_file_invalid(self):
        """
        When a non-existent or corrupted cookie file is specified, verify it fails fast
        with COOKIE_FILE_INVALID without calling yt-dlp.
        """
        from downloader.ytdlp_engine import ExtractionError

        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.extract_entries(
                "https://www.douyin.com/video/7106594312292453678",
                custom_cookie_file=str(self.missing_file),
            )

        err_msg = str(ctx.exception)
        self.assertIn("COOKIE_FILE_INVALID", err_msg)

        classified = ErrorClassifier.classify(err_msg, stage="scan", platform="douyin")
        self.assertEqual(classified.category, ErrorCategory.COOKIE_FILE_INVALID)
        self.assertIn("Cookie 文件无效", classified.get_localized_title("zh_CN"))

    def test_error_classifier_all_douyin_categories(self):
        """Verifies accurate classification and bilingual localization for all Douyin error categories."""
        test_cases = [
            (
                "COOKIE_FILE_INVALID: Specified Douyin cookie file does not exist",
                ErrorCategory.COOKIE_FILE_INVALID,
                "Cookie file invalid",
                "Cookie 文件无效",
            ),
            (
                "COOKIE_NOT_APPLIED: Cookie authentication not applied to engine",
                ErrorCategory.COOKIE_NOT_APPLIED,
                "Cookie authentication not applied",
                "Cookie 认证未应用",
            ),
            (
                "DOUYIN_SESSION_REQUIRED: Douyin requires fresh session cookies",
                ErrorCategory.DOUYIN_SESSION_REQUIRED,
                "Douyin session required",
                "需要有效的抖音会话 Cookie",
            ),
            (
                "DOUYIN_API_BLOCKED: Blocked by ArgusSecurityPlugin / Uifid Not Found",
                ErrorCategory.DOUYIN_API_BLOCKED,
                "Douyin API security block (ArgusSecurityPlugin)",
                "抖音 API 安全拦截 (ArgusSecurityPlugin)",
            ),
            (
                "DOUYIN_EXTRACTOR_INCOMPATIBLE: Douyin URL not supported or schema mismatch",
                ErrorCategory.DOUYIN_EXTRACTOR_INCOMPATIBLE,
                "Douyin extractor incompatible",
                "抖音提取器兼容性异常",
            ),
            (
                "UNKNOWN_EXTRACTION_ERROR: Unexpected error occurred during extraction",
                ErrorCategory.UNKNOWN_EXTRACTION_ERROR,
                "Douyin extraction failed",
                "抖音视频提取失败",
            ),
        ]

        for raw_err, expected_cat, expected_en_title, expected_zh_title in test_cases:
            classified = ErrorClassifier.classify(raw_err, platform="douyin")
            self.assertEqual(classified.category, expected_cat, f"Failed for {raw_err}")
            self.assertEqual(classified.get_localized_title("en"), expected_en_title)
            self.assertEqual(classified.get_localized_title("zh_CN"), expected_zh_title)
            self.assertTrue(len(classified.get_localized_user_message("zh_CN")) > 10)
            self.assertTrue(len(classified.get_localized_suggested_action("zh_CN")) > 10)

    def test_second_douyin_video_url_handling(self):
        """Verifies URL normalization and building for a second publicly accessible Douyin video."""
        second_url = "https://www.douyin.com/video/6961737553342991651"
        self.assertTrue(self.adapter.matches_url(second_url))
        is_valid, _ = self.adapter.validate_url(second_url)
        self.assertTrue(is_valid)
        norm = self.adapter.normalize_url(second_url)
        self.assertEqual(norm, second_url)

    def test_douyin_and_youtube_tiktok_isolation(self):
        """Verifies authentication scoping: Douyin auth does not leak to YouTube or TikTok."""
        from core.platform.detector import PlatformRegistry

        yt_adapter = PlatformRegistry.get_adapter("youtube")
        tt_adapter = PlatformRegistry.get_adapter("tiktok")
        dy_adapter = PlatformRegistry.get_adapter("douyin")

        # TikTok auth is always none
        tt_auth = tt_adapter.get_auth_config()
        self.assertFalse(tt_auth.is_active)
        self.assertEqual(tt_auth.description, "None")

        # Douyin auth with isolated cookie file
        dy_auth = dy_adapter.get_auth_config(settings={"douyin_custom_cookie_file": str(self.valid_cookie_file)})
        self.assertTrue(dy_auth.is_active)
        self.assertEqual(dy_auth.auth_method, "custom_file")

        # YouTube auth remains independent
        yt_auth = yt_adapter.get_auth_config(settings={"douyin_custom_cookie_file": str(self.valid_cookie_file)})
        self.assertFalse(yt_auth.is_active)


class TestDouyinTemporaryFreeze(unittest.TestCase):
    """
    Dedicated tests verifying the temporary freeze of the Douyin platform:
    1. YouTube remains enabled and selectable.
    2. TikTok remains enabled and selectable.
    3. Douyin is visibly disabled in the platform selector with localized tooltip.
    4. Douyin cannot be selected through normal GUI interaction.
    5. A saved Douyin selection falls back to an enabled platform on startup.
    6. Direct attempts to start a new Douyin scan or download are rejected gracefully with PLATFORM_TEMPORARILY_UNAVAILABLE.
    7. Centralized availability control can be toggled and reversed without deleting or rebuilding Douyin adapter.
    8. Douyin adapter code, auth configuration, error classification, and existing tests remain present.
    9. YouTube and TikTok scan/download behavior remains unchanged.
    10. Reversing the freeze restores Douyin operation cleanly.
    """

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        PlatformRegistry.reset_availability_overrides()

    def tearDown(self):
        PlatformRegistry.reset_availability_overrides()
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    def test_1_platform_availability_defaults(self):
        """Verify YouTube/TikTok are available, and Douyin is frozen by default."""
        self.assertTrue(PlatformRegistry.is_available("youtube"))
        self.assertTrue(PlatformRegistry.is_available("tiktok"))
        self.assertFalse(PlatformRegistry.is_available("douyin"))

        adapter = PlatformRegistry.get_adapter("douyin")
        self.assertIsNotNone(adapter)
        self.assertFalse(adapter.is_available)
        self.assertEqual(adapter.unavailable_reason, "platform_douyin_unavailable_tooltip")

    def test_2_centralized_availability_reversal(self):
        """Verify centralized availability control can be reversed and reset cleanly."""
        self.assertFalse(PlatformRegistry.is_available("douyin"))
        # Unfreeze
        PlatformRegistry.set_platform_available("douyin", True)
        self.assertTrue(PlatformRegistry.is_available("douyin"))
        adapter = PlatformRegistry.get_adapter("douyin")
        self.assertTrue(adapter.is_available)

        # Reset back to frozen
        PlatformRegistry.reset_availability_overrides()
        self.assertFalse(PlatformRegistry.is_available("douyin"))
        self.assertFalse(adapter.is_available)

    def test_3_direct_extraction_attempt_rejected(self):
        """Verify direct calls to DouyinAdapter.extract_entries fail fast with PLATFORM_TEMPORARILY_UNAVAILABLE."""
        adapter = DouyinAdapter()
        logs = []
        with self.assertRaises(RuntimeError) as ctx:
            adapter.extract_entries(
                "https://www.douyin.com/video/7106594312292453678",
                log_callback=logs.append,
            )
        err_msg = str(ctx.exception)
        self.assertIn("PLATFORM_TEMPORARILY_UNAVAILABLE", err_msg)
        self.assertIn("waiting for an upstream yt-dlp fix", err_msg)
        self.assertNotIn("re-export", err_msg.lower())
        self.assertTrue(len(logs) > 0)
        self.assertIn("[BLOCKED]", logs[0])

    def test_4_channel_scan_worker_rejected(self):
        """Verify ChannelScanWorker rejects Douyin URLs when frozen."""
        from downloader.ytdlp_engine import ChannelScanWorker
        scan_errors = []
        worker = ChannelScanWorker(url="https://www.douyin.com/video/7106594312292453678")
        worker.scan_error.connect(scan_errors.append)
        worker.run()
        self.assertEqual(len(scan_errors), 1)
        self.assertIn("PLATFORM_TEMPORARILY_UNAVAILABLE", scan_errors[0])
        self.assertIn("waiting for an upstream yt-dlp fix", scan_errors[0])

    def test_5_download_manager_rejects_douyin_video(self):
        """Verify DownloadManager skips Douyin videos gracefully with FAILED status and [BLOCKED] log."""
        from downloader.download_manager import DownloadManager

        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="Frozen Douyin Video",
            duration="00:30",
            platform="douyin",
            url="https://www.douyin.com/video/7106594312292453678",
        )
        settings = DownloadSettings(
            download_folder=str(self.tmp_dir.name),
        )
        dm = DownloadManager([video], settings)
        status_updates = []
        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.run()

        # Video must be marked FAILED with explanation
        self.assertTrue(any(st == VideoStatus.FAILED for vid, st, msg in status_updates))
        self.assertTrue(any("waiting for an upstream yt-dlp fix" in msg for vid, st, msg in status_updates))

    def test_6_error_classifier_unavailable_platform(self):
        """Verify ErrorClassifier.for_unavailable_platform provides accurate, localized diagnostics."""
        err = ErrorClassifier.for_unavailable_platform("douyin")
        self.assertEqual(err.category, ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE)
        self.assertIn("Douyin temporarily unavailable", err.title)
        self.assertIn("ArgusSecurityPlugin", err.user_message)
        self.assertIn("waiting for an upstream yt-dlp fix", err.user_message)

        # Bilingual localization
        self.assertEqual(err.get_localized_title("zh_CN"), "抖音暂时不可用")
        self.assertIn("等待 yt-dlp 上游修复", err.get_localized_user_message("zh_CN"))
        self.assertIn("ArgusSecurityPlugin", err.get_localized_user_message("zh_CN"))
        self.assertIn("临时冻结状态", err.get_localized_suggested_action("zh_CN"))

        # Classifier classification from raw error string
        classified = ErrorClassifier.classify(
            "[PLATFORM_TEMPORARILY_UNAVAILABLE] Douyin is temporarily unavailable",
            platform="douyin",
        )
        self.assertEqual(classified.category, ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE)

    def test_7_settings_startup_fallback(self):
        """Verify SettingsManager safely falls back to youtube if saved platform is douyin."""
        self.isolated_sm.set("selected_platform", "douyin")
        retrieved = self.isolated_sm.get("selected_platform")
        self.assertEqual(retrieved, "youtube")

    def test_8_gui_platform_selector_disabled_douyin(self):
        """Verify GUI platform combo shows Douyin disabled, unselectable, and reverts attempts."""
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        with patch.object(MainWindow, "_check_ytdlp_updates_silent"):
            win = MainWindow()
            try:
                combo = win.platform_combo
                model = combo.model()

                # Verify YouTube item (index 0)
                yt_item = model.item(0)
                self.assertEqual(combo.itemData(0), "youtube")
                self.assertTrue(yt_item.isEnabled())

                # Verify TikTok item (index 1)
                tt_item = model.item(1)
                self.assertEqual(combo.itemData(1), "tiktok")
                self.assertTrue(tt_item.isEnabled())

                # Verify Douyin item (index 2)
                dy_item = model.item(2)
                self.assertEqual(combo.itemData(2), "douyin")
                self.assertFalse(dy_item.isEnabled())
                self.assertEqual(dy_item.toolTip(), tr("platform_douyin_unavailable_tooltip"))

                # Verify attempting to select Douyin programmatically reverts to YouTube/active
                combo.setCurrentIndex(2)
                self.assertNotEqual(combo.currentData(), "douyin")
                self.assertIn(combo.currentData(), ("youtube", "tiktok"))

                # Verify pasting Douyin URL does not switch combo
                win.url_input.setText("https://www.douyin.com/video/7106594312292453678")
                self.assertNotEqual(combo.currentData(), "douyin")
            finally:
                win._download_manager = None
                win.close()

    def test_9_douyin_preservation_and_auth_integrity(self):
        """Verify Douyin code, capabilities, auth config, and cookie diagnostics remain intact."""
        adapter = PlatformRegistry.get_adapter("douyin")
        self.assertIsNotNone(adapter)
        caps = adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_browser_cookies)
        self.assertTrue(caps.supports_cookie_file)

        auth = adapter.get_auth_config()
        self.assertIsNotNone(auth)

        # Cookie checker import remains functional
        from core.platform.douyin import inspect_cookie_file_safe
        self.assertTrue(callable(inspect_cookie_file_safe))


if __name__ == "__main__":
    unittest.main()
