"""
test_facebook_adapter.py
Comprehensive unit tests for the Facebook platform adapter, including URL detection,
URL validation, capabilities, short link / redirect handling, metadata extraction,
authentication isolation, error classification, metadata TXT formatting, and cancellation handling.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.error_classifier import ErrorCategory, ErrorClassifier
from core.models import DownloadSettings, VideoItem, VideoStatus
from core.platform import (
    PlatformCapabilities,
    PlatformDetector,
    PlatformRegistry,
)
from core.platform.auth import PlatformAuthConfig
from core.platform.facebook import FacebookAdapter
from downloader.auth_checker import AuthChecker, AuthStatusCode
from metadata import MetadataExporter
from metadata.facebook_formatter import FacebookMetadataFormatter


class TestFacebookAdapter(unittest.TestCase):
    """Verifies Facebook platform adapter integration and contract compliance."""

    def setUp(self):
        self.adapter = FacebookAdapter()

    def test_registration_and_lookup(self):
        """Verify FacebookAdapter is registered in PlatformRegistry and retrievable."""
        reg_adapter = PlatformRegistry.get_adapter("facebook")
        self.assertIsNotNone(reg_adapter)
        self.assertEqual(reg_adapter.platform_id, "facebook")
        self.assertEqual(reg_adapter.display_name, "Facebook")
        self.assertTrue(PlatformRegistry.is_available("facebook"))

        # Lookup by URL
        matched_watch = PlatformRegistry.get_adapter_for_url("https://www.facebook.com/watch/?v=123456789")
        self.assertIs(matched_watch, reg_adapter)

        matched_reel = PlatformRegistry.get_adapter_for_url("https://www.facebook.com/reel/987654321")
        self.assertIs(matched_reel, reg_adapter)

        matched_fbwatch = PlatformRegistry.get_adapter_for_url("https://fb.watch/abcdef123/")
        self.assertIs(matched_fbwatch, reg_adapter)

    def test_platform_detector(self):
        """Verify PlatformDetector identifies various Facebook URL formats."""
        test_cases = [
            ("https://www.facebook.com/watch/?v=10158292837492817", "facebook"),
            ("https://facebook.com/watch?v=10158292837492817", "facebook"),
            ("https://www.facebook.com/reel/123456789012345", "facebook"),
            ("https://facebook.com/reel/123456789012345/?s=fb_shorts_tab", "facebook"),
            ("https://www.facebook.com/username/videos/123456789012345/", "facebook"),
            ("https://www.facebook.com/page.name/videos/10158292837492817", "facebook"),
            ("https://m.facebook.com/watch/?v=10158292837492817", "facebook"),
            ("https://m.facebook.com/story.php?story_fbid=123&id=456", "facebook"),
            ("https://fb.watch/abcdef123/", "facebook"),
            ("https://fb.me/xyz987", "facebook"),
            ("https://www.facebook.com/share/v/123456789/", "facebook"),
            ("https://www.facebook.com/share/r/987654321/", "facebook"),
        ]
        for url, expected in test_cases:
            self.assertEqual(
                PlatformDetector.identify_platform_id(url),
                expected,
                f"Failed for {url}",
            )

    def test_capabilities(self):
        """Verify Facebook platform capabilities matrix."""
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertFalse(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_chapters)
        self.assertFalse(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_cookie_file)
        self.assertFalse(caps.supports_browser_cookies)
        self.assertEqual(caps.archive_prefix, "facebook")

    def test_validate_url(self):
        """Verify Facebook URL validation for supported and invalid formats."""
        valid_urls = [
            "https://www.facebook.com/watch/?v=10158292837492817",
            "https://facebook.com/watch?v=10158292837492817",
            "https://www.facebook.com/reel/123456789012345",
            "https://www.facebook.com/user/videos/123456789012345/",
            "https://m.facebook.com/watch/?v=10158292837492817",
            "https://fb.watch/abcdef123/",
            "https://fb.me/xyz987",
            "https://www.facebook.com/share/v/123456789/",
            "https://www.facebook.com/share/r/987654321/",
        ]
        for u in valid_urls:
            is_valid, reason = self.adapter.validate_url(u)
            self.assertTrue(is_valid, f"Expected {u} to be valid, got reason: {reason}")

        invalid_urls = [
            "",
            "   ",
            "not a url",
            "https://www.youtube.com/watch?v=123",
            "https://www.tiktok.com/@user/video/123",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.facebook.com/",
            "https://www.facebook.com/home.php",
            "https://www.facebook.com/messages/t/123",
            "ftp://www.facebook.com/watch/?v=123",
        ]
        for u in invalid_urls:
            is_valid, _ = self.adapter.validate_url(u)
            self.assertFalse(is_valid, f"Expected {u} to be invalid")

    def test_clean_url_parameters(self):
        """Verify tracking parameters are removed while essential video IDs are preserved."""
        # watch url with tracking
        url_watch = "https://www.facebook.com/watch/?v=10158292837492817&fbclid=IwAR12345&ref=sharing&mibextid=2dXqE3"
        cleaned_watch = self.adapter.clean_url(url_watch)
        self.assertIn("v=10158292837492817", cleaned_watch)
        self.assertNotIn("fbclid", cleaned_watch)
        self.assertNotIn("mibextid", cleaned_watch)
        self.assertNotIn("ref=sharing", cleaned_watch)

        # reel url with tracking
        url_reel = "https://www.facebook.com/reel/123456789012345?s=fb_shorts_tab&stack_idx=0&rdid=xyz"
        cleaned_reel = self.adapter.clean_url(url_reel)
        self.assertEqual(cleaned_reel, "https://www.facebook.com/reel/123456789012345")

        # video url with tracking
        url_video = "https://www.facebook.com/creator/videos/987654321098765/?notif_id=123&notif_t=feedback_reaction_generic"
        cleaned_video = self.adapter.clean_url(url_video)
        self.assertEqual(cleaned_video, "https://www.facebook.com/creator/videos/987654321098765/")

    def test_archive_tag_generation(self):
        """Verify archive tags follow established '{archive_prefix} {video_id}' convention."""
        self.assertEqual(self.adapter.generate_archive_tag("10158292837492817"), "facebook 10158292837492817")
        item = VideoItem(index=1, video_id="987654321", title="Facebook Test", duration="01:30")
        self.assertEqual(self.adapter.get_archive_tag(item), "facebook 987654321")

    def test_canonical_url_builder(self):
        """Verify get_canonical_url builds standard Facebook watch URL."""
        self.assertEqual(
            self.adapter.get_canonical_url("10158292837492817"),
            "https://www.facebook.com/watch/?v=10158292837492817",
        )

    def test_single_video_extraction(self):
        """Verify standard Facebook video extraction produces normalized VideoItem."""
        mock_info = {
            "id": "10158292837492817",
            "title": "Inspiring Nature Timelapse 4K",
            "uploader": "National Geographic",
            "uploader_id": "natgeo",
            "duration": 185,
            "webpage_url": "https://www.facebook.com/watch/?v=10158292837492817",
            "thumbnail": "https://scontent.xx.fbcdn.net/v/t15.5256-10/test.jpg",
            "upload_date": "20240315",
            "description": "Breathtaking views from around the globe.\n#nature #timelapse",
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.facebook.com/watch/?v=10158292837492817")
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "10158292837492817")
            self.assertEqual(item.title, "Inspiring Nature Timelapse 4K")
            self.assertEqual(item.channel_title, "National Geographic")
            self.assertEqual(item.duration, "03:05")
            self.assertEqual(item.platform, "facebook")
            self.assertEqual(item.url, "https://www.facebook.com/watch/?v=10158292837492817")

    def test_reel_extraction_with_unicode_and_emojis(self):
        """Verify Reel extraction preserves Unicode, CJK characters, emojis, and hashtags."""
        reel_title = "🌟 Amazing Street Food in Tokyo! 🍜 日本の美味しいラーメン #travel #shorts"
        mock_info = {
            "id": "123456789012345",
            "title": reel_title,
            "uploader": "Tokyo Foodie",
            "uploader_id": "tokyo.foodie",
            "duration": 58,
            "webpage_url": "https://www.facebook.com/reel/123456789012345",
            "thumbnail": "https://scontent.xx.fbcdn.net/reel_thumb.jpg",
            "upload_date": "20240401",
            "description": reel_title,
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.facebook.com/reel/123456789012345")
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "123456789012345")
            self.assertEqual(item.title, reel_title)
            self.assertEqual(item.duration, "00:58")
            self.assertEqual(item.platform, "facebook")

    def test_title_fallback_when_title_missing(self):
        """Verify title fallback uses first non-empty description line or generic Facebook Video {id}."""
        # Case A: title missing, description present
        mock_info_desc = {
            "id": "5555555555",
            "title": None,
            "description": "First line of caption\nSecond line details",
            "uploader": "Test Page",
            "duration": 30,
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info_desc
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.facebook.com/watch/?v=5555555555")
            self.assertEqual(items[0].title, "First line of caption")

        # Case B: title and description both missing
        mock_info_none = {
            "id": "7777777777",
            "title": "",
            "description": "",
            "uploader": "",
            "duration": 45,
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info_none
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.facebook.com/watch/?v=7777777777")
            self.assertEqual(items[0].title, "Facebook Video 7777777777")

    def test_short_link_redirect_resolution(self):
        """Verify short link redirect resolution resolves fb.watch or share URLs."""
        with patch("urllib.request.build_opener") as mock_build_opener:
            mock_opener = MagicMock()
            mock_resp = MagicMock()
            mock_resp.geturl.return_value = "https://www.facebook.com/watch/?v=10158292837492817"
            mock_opener.open.return_value.__enter__.return_value = mock_resp
            mock_build_opener.return_value = mock_opener

            resolved = self.adapter.resolve_short_link("https://fb.watch/abcdef123/")
            self.assertEqual(resolved, "https://www.facebook.com/watch/?v=10158292837492817")

    def test_cancellation_during_extraction(self):
        """Verify extract_entries halts when is_cancelled returns True."""
        cancelled_flag = [True]

        def check_cancelled():
            return cancelled_flag[0]

        items = self.adapter.extract_entries(
            "https://www.facebook.com/watch/?v=10158292837492817",
            is_cancelled=check_cancelled,
        )
        self.assertEqual(items, [])

    def test_auth_isolation_none_mode(self):
        """Verify unauthenticated request contains no cookiefile and no browser cookies."""
        unauth_config = PlatformAuthConfig(auth_method="none")
        ydl_opts = self.adapter.build_ydl_options(unauth_config)
        self.assertNotIn("cookiefile", ydl_opts)
        self.assertNotIn("cookiesfrombrowser", ydl_opts)

    def test_auth_isolation_custom_file_mode(self):
        """Verify custom cookie file mode propagates valid cookie file path to ydl_opts."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t10001\n")
            temp_path = tf.name

        try:
            auth_config = PlatformAuthConfig(
                auth_method="custom_file",
                cookie_file=temp_path,
            )
            ydl_opts = self.adapter.build_ydl_options(auth_config)
            self.assertEqual(ydl_opts.get("cookiefile"), str(Path(temp_path).resolve()))
            self.assertNotIn("cookiesfrombrowser", ydl_opts)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_auth_isolation_rejects_browser_cookies(self):
        """Verify Facebook adapter strictly rejects browser cookies configuration."""
        browser_config = PlatformAuthConfig(
            auth_method="browser",
            browser_name="chrome",
            cookie_file="",
        )
        ydl_opts = self.adapter.build_ydl_options(browser_config)
        self.assertNotIn("cookiesfrombrowser", ydl_opts)
        self.assertNotIn("cookiefile", ydl_opts)

    def test_get_auth_config_with_settings_manager_duck_typing(self):
        """Verify get_auth_config retrieves custom cookie file via SettingsManager (.get())."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t10001\n")
            temp_path = tf.name

        try:
            mock_sm = MagicMock()
            mock_sm.get.side_effect = lambda key, default=None: {
                "facebook_auth_method": "custom_file",
                "facebook_custom_cookie_file": temp_path,
            }.get(key, default)

            auth_config = self.adapter.get_auth_config(mock_sm)
            self.assertEqual(auth_config.auth_method, "custom_file")
            self.assertTrue(auth_config.is_active)
            self.assertEqual(auth_config.cookie_file, str(Path(temp_path).resolve()))
            self.assertEqual(auth_config.description, "Custom Cookie File")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_get_auth_config_missing_file_diagnostics(self):
        """Verify get_auth_config reports accurate diagnostics when file is missing or unconfigured."""
        # Case A: empty path
        mock_sm_empty = MagicMock()
        mock_sm_empty.get.side_effect = lambda key, default=None: {
            "facebook_auth_method": "custom_file",
            "facebook_custom_cookie_file": "",
        }.get(key, default)
        cfg_empty = self.adapter.get_auth_config(mock_sm_empty)
        self.assertFalse(cfg_empty.is_active)
        self.assertIn("No file path configured", cfg_empty.description)

        # Case B: non-existent file
        non_existent = r"C:\fake_dir\non_existent_facebook_cookies.txt"
        mock_sm_missing = MagicMock()
        mock_sm_missing.get.side_effect = lambda key, default=None: {
            "facebook_auth_method": "custom_file",
            "facebook_custom_cookie_file": non_existent,
        }.get(key, default)
        cfg_missing = self.adapter.get_auth_config(mock_sm_missing)
        self.assertFalse(cfg_missing.is_active)
        self.assertIn("File not found on disk", cfg_missing.description)

    def test_get_auth_config_dataclass_and_dict(self):
        """Verify get_auth_config works with DownloadSettings dataclass and dictionary."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n")
            temp_path = tf.name

        try:
            # Dataclass
            ds = DownloadSettings(
                facebook_auth_method="custom_file",
                facebook_custom_cookie_file=temp_path,
            )
            cfg_ds = self.adapter.get_auth_config(ds)
            self.assertEqual(cfg_ds.auth_method, "custom_file")
            self.assertTrue(cfg_ds.is_active)

            # Dictionary
            d = {
                "facebook_auth_method": "custom_file",
                "facebook_custom_cookie_file": temp_path,
            }
            cfg_d = self.adapter.get_auth_config(d)
            self.assertEqual(cfg_d.auth_method, "custom_file")
            self.assertTrue(cfg_d.is_active)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_scan_propagates_cookie_file_to_ytdlp(self):
        """Verify scan() passes cookiefile option to YoutubeDL when cookie auth is configured."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t10001\n")
            temp_path = tf.name

        try:
            auth_config = PlatformAuthConfig(
                auth_method="custom_file",
                cookie_file=temp_path,
                description="Custom Cookie File",
            )
            mock_info = {
                "id": "10158292837492817",
                "title": "Facebook Video Scan Test",
                "uploader": "Test Page",
                "duration": 120,
            }

            captured_opts = {}

            def fake_ydl_init(opts):
                captured_opts.update(opts)
                mock_instance = MagicMock()
                mock_instance.__enter__.return_value = mock_instance
                mock_instance.extract_info.return_value = mock_info
                return mock_instance

            with patch("yt_dlp.YoutubeDL", side_effect=fake_ydl_init):
                result = self.adapter.scan(
                    "https://www.facebook.com/watch/?v=10158292837492817",
                    auth_config=auth_config,
                )
                self.assertEqual(len(result.videos), 1)
                self.assertIn("cookiefile", captured_opts)
                self.assertEqual(captured_opts["cookiefile"], str(Path(temp_path).resolve()))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestFacebookErrorClassification(unittest.TestCase):
    """Verifies Facebook-specific error classification, localization, and retryability."""

    def test_video_unavailable_classification(self):
        """Verify removed or unavailable Facebook video is classified as VIDEO_UNAVAILABLE."""
        err_msg = "ERROR: [facebook] 10158292837492817: This video may have been removed or is no longer available"
        classified = ErrorClassifier.classify(err_msg, platform="facebook")
        self.assertEqual(classified.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertTrue(classified.is_facebook)
        self.assertEqual(classified.platform, "facebook")

    def test_login_required_classification(self):
        """Verify login required Facebook message is classified as LOGIN_REQUIRED."""
        err_msg = "ERROR: [facebook] 10158292837492817: Log in to Facebook to watch this video"
        classified = ErrorClassifier.classify(err_msg, platform="facebook")
        self.assertEqual(classified.category, ErrorCategory.LOGIN_REQUIRED)
        self.assertTrue(classified.is_facebook)

        # Check localized guidance mentions cookies
        action_en = classified.get_localized_suggested_action("en")
        self.assertIn("cookie", action_en.lower())
        action_zh_cn = classified.get_localized_suggested_action("zh_CN")
        self.assertIn("Cookie", action_zh_cn)
        action_zh_tw = classified.get_localized_suggested_action("zh_TW")
        self.assertIn("Cookie", action_zh_tw)

    def test_private_video_classification(self):
        """Verify private or permissions restricted video is classified as PRIVATE_VIDEO."""
        err_msg = "ERROR: [facebook] 10158292837492817: This video is private or restricted"
        classified = ErrorClassifier.classify(err_msg, platform="facebook")
        self.assertEqual(classified.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertTrue(classified.is_facebook)


class TestFacebookAuthChecker(unittest.TestCase):
    """Verifies Facebook cookie file inspection and authentication diagnostics."""

    def test_valid_facebook_cookies_authenticated(self):
        """Verify cookie file containing facebook.com with c_user and xs returns authenticated status."""
        content = (
            "# Netscape HTTP Cookie File\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1893456000\tc_user\t1000123456789\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1893456000\txs\t34%3Atest_session_token%3A2%3A1710000000\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1893456000\tdatr\tabc123xyz\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tf:
            tf.write(content)
            temp_path = tf.name

        try:
            res = AuthChecker.test_authentication("custom_file", custom_cookie_path=temp_path, platform="facebook")
            self.assertEqual(res.status_code, AuthStatusCode.FACEBOOK_SESSION_AUTHENTICATED)
            self.assertTrue(res.has_session)
            self.assertIn("Facebook cookies found", res.reason)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_missing_facebook_cookies_warning(self):
        """Verify cookie file lacking facebook.com cookies returns warning status."""
        content = (
            "# Netscape HTTP Cookie File\n"
            ".google.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc123\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as tf:
            tf.write(content)
            temp_path = tf.name

        try:
            res = AuthChecker.test_authentication("custom_file", custom_cookie_path=temp_path, platform="facebook")
            self.assertEqual(res.status_code, AuthStatusCode.NO_FACEBOOK_COOKIES)
            self.assertIn("facebook.com", res.reason)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_missing_cookie_file_not_found(self):
        """Verify non-existent cookie file returns not found diagnostics."""
        non_existent = r"C:\fake\dir\no_cookies_here.txt"
        res = AuthChecker.test_authentication("custom_file", custom_cookie_path=non_existent, platform="facebook")
        self.assertFalse(res.success)
        self.assertEqual(res.status_code, AuthStatusCode.BROWSER_NOT_FOUND)
        self.assertIn("does not exist", res.reason.lower())


class TestFacebookMetadataTXT(unittest.TestCase):
    """Verifies dedicated Facebook metadata TXT formatting, sanitization, and UTF-8 output."""

    def test_formatter_registration(self):
        """Verify FacebookMetadataFormatter is registered for platform 'facebook'."""
        formatter = MetadataExporter.get_formatter(platform_id="facebook")
        self.assertIsInstance(formatter, FacebookMetadataFormatter)

    def test_metadata_txt_structure_and_fields(self):
        """Verify all mandatory sections and fields in formatted Facebook metadata TXT."""
        video_item = VideoItem(
            index=1,
            video_id="10158292837492817",
            title="Magnificent Sunset Over the Ocean",
            duration="02:15",
            channel_title="Ocean Wonders Page",
            platform="facebook",
            url="https://www.facebook.com/watch/?v=10158292837492817",
            status=VideoStatus.COMPLETED,
        )

        ext_info = {
            "id": "10158292837492817",
            "title": "Magnificent Sunset Over the Ocean",
            "description": "Watch the sunset in golden hour.\n#ocean #sunset #nature",
            "uploader": "Ocean Wonders Page",
            "uploader_id": "ocean.wonders",
            "uploader_url": "https://www.facebook.com/ocean.wonders",
            "channel": "Ocean Wonders Page",
            "channel_id": "1000987654321",
            "channel_url": "https://www.facebook.com/ocean.wonders",
            "duration": 135,
            "upload_date": "20240320",
            "timestamp": 1710936000,
            "webpage_url": "https://www.facebook.com/watch/?v=10158292837492817",
            "view_count": 154200,
            "like_count": 8900,
            "comment_count": 450,
            "repost_count": 120,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "vcodec": "h264",
            "acodec": "aac",
            "format_id": "hd",
            "ext": "mp4",
            "filesize": 45123456,
            "thumbnail": "https://scontent.xx.fbcdn.net/sunset.jpg",
            "tags": ["ocean", "sunset", "nature"],
        }

        formatter = FacebookMetadataFormatter()
        txt = formatter.format(ext_info, video_item)

        # Basic Information
        self.assertIn("BASIC INFORMATION", txt)
        self.assertIn("Magnificent Sunset Over the Ocean", txt)
        self.assertIn("10158292837492817", txt)
        self.assertIn("https://www.facebook.com/watch/?v=10158292837492817", txt)
        self.assertIn("Standard Video", txt)
        self.assertIn("02:15", txt)
        self.assertIn("2024-03-20", txt)

        # Publisher Information
        self.assertIn("PUBLISHER INFORMATION", txt)
        self.assertIn("Ocean Wonders Page", txt)
        self.assertIn("ocean.wonders", txt)
        self.assertIn("1000987654321", txt)

        # Engagement Statistics
        self.assertIn("ENGAGEMENT STATISTICS", txt)
        self.assertIn("154,200", txt)
        self.assertIn("8,900", txt)
        self.assertIn("450", txt)
        self.assertIn("120", txt)

        # Description / Caption
        self.assertIn("DESCRIPTION / CAPTION", txt)
        self.assertIn("Watch the sunset in golden hour.", txt)

        # Media Technical Information
        self.assertIn("MEDIA INFORMATION", txt)
        self.assertIn("1920", txt)
        self.assertIn("1080", txt)
        self.assertIn("30", txt)
        self.assertIn("h264", txt)
        self.assertIn("aac", txt)
        self.assertIn("hd", txt)
        self.assertIn("mp4", txt)

        # Additional Information
        self.assertIn("ADDITIONAL INFORMATION", txt)
        self.assertIn("https://scontent.xx.fbcdn.net/sunset.jpg", txt)
        self.assertIn("ocean, sunset, nature", txt)

    def test_reel_metadata_type_detection(self):
        """Verify Reel URL is recognized as Video Type: Reel."""
        video_item = VideoItem(
            index=1,
            video_id="987654321",
            title="Short Reel",
            duration="00:30",
            platform="facebook",
            url="https://www.facebook.com/reel/987654321",
        )
        ext_info = {
            "id": "987654321",
            "title": "Short Reel",
            "webpage_url": "https://www.facebook.com/reel/987654321",
        }
        formatter = FacebookMetadataFormatter()
        txt = formatter.format(ext_info, video_item)
        self.assertIn("Facebook Reel", txt)

    def test_credential_sanitization_in_metadata_export(self):
        """Verify session tokens (c_user, xs, etc.) are never leaked in exported metadata."""
        video_item = VideoItem(
            index=1,
            video_id="10158292837492817",
            title="Test Video",
            duration="01:00",
            platform="facebook",
            url="https://www.facebook.com/watch/?v=10158292837492817",
        )
        # Attempt to inject credentials into description or extra info
        ext_info = {
            "id": "10158292837492817",
            "title": "Test Video",
            "description": "Cookie dump: c_user=100012345; xs=34%3Atesttoken%3A2; datr=xyz",
        }
        formatter = FacebookMetadataFormatter()
        raw_txt = formatter.format(ext_info, video_item)
        sanitized_txt = MetadataExporter.sanitize_credentials(raw_txt)

        self.assertNotIn("c_user=100012345", sanitized_txt)
        self.assertNotIn("34%3Atesttoken%3A2", sanitized_txt)
        self.assertIn("[REDACTED_CREDENTIAL]", sanitized_txt)

    def test_save_metadata_file_utf8_encoding(self):
        """Verify MetadataExporter saves Facebook metadata TXT in UTF-8 encoding."""
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td)
            dest_file = output_dir / "Tokyo_Night.metadata.txt"
            video_item = VideoItem(
                index=1,
                video_id="10158292837492817",
                title="✨ 東京夜景 4K Timelapse 🗼",
                duration="02:15",
                platform="facebook",
                url="https://www.facebook.com/watch/?v=10158292837492817",
            )
            ext_info = {
                "id": "10158292837492817",
                "title": "✨ 東京夜景 4K Timelapse 🗼",
                "uploader": "東京チャンネル",
                "description": "美しい夜景です。\n#tokyo #japan",
            }
            success = MetadataExporter.save_metadata_file(
                dest_file,
                ext_info,
                video=video_item,
                platform_id="facebook",
            )
            self.assertTrue(success)
            self.assertTrue(dest_file.exists())

            # Verify UTF-8 readability
            with open(dest_file, "r", encoding="utf-8") as f:
                saved_content = f.read()

            self.assertIn("✨ 東京夜景 4K Timelapse 🗼", saved_content)
            self.assertIn("東京チャンネル", saved_content)
            self.assertIn("BASIC INFORMATION", saved_content)


class TestCrossPlatformIsolation(unittest.TestCase):
    """Verifies that Facebook settings never leak to or collide with other platforms."""

    def test_facebook_settings_do_not_affect_youtube_or_tiktok(self):
        """Verify YouTube and TikTok adapters never pick up Facebook cookie file."""
        from core.platform.youtube import YouTubeAdapter
        from core.platform.tiktok import TikTokAdapter
        from core.platform.bilibili import BilibiliAdapter

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.facebook.com\tTRUE\t/\tTRUE\t0\tc_user\t10001\n")
            fb_cookie_path = tf.name

        try:
            # Settings with ONLY Facebook custom cookie configured
            settings = {
                "youtube_auth_method": "none",
                "youtube_custom_cookie_file": "",
                "tiktok_auth_method": "none",
                "tiktok_custom_cookie_file": "",
                "bilibili_auth_method": "none",
                "bilibili_custom_cookie_file": "",
                "facebook_auth_method": "custom_file",
                "facebook_custom_cookie_file": fb_cookie_path,
            }

            yt_adapter = YouTubeAdapter()
            tt_adapter = TikTokAdapter()
            bili_adapter = BilibiliAdapter()
            fb_adapter = FacebookAdapter()

            yt_auth = yt_adapter.get_auth_config(settings)
            tt_auth = tt_adapter.get_auth_config(settings)
            bili_auth = bili_adapter.get_auth_config(settings)
            fb_auth = fb_adapter.get_auth_config(settings)

            self.assertEqual(yt_auth.auth_method, "none")
            self.assertFalse(yt_auth.is_active)
            self.assertEqual(tt_auth.auth_method, "none")
            self.assertFalse(tt_auth.is_active)
            self.assertEqual(bili_auth.auth_method, "none")
            self.assertFalse(bili_auth.is_active)

            self.assertEqual(fb_auth.auth_method, "custom_file")
            self.assertTrue(fb_auth.is_active)
            self.assertEqual(fb_auth.cookie_file, str(Path(fb_cookie_path).resolve()))
        finally:
            if os.path.exists(fb_cookie_path):
                os.remove(fb_cookie_path)



    def test_clean_facebook_title_function(self):
        """Verify clean_facebook_title strips leading views and reactions across languages and formats."""
        from core.platform.facebook import clean_facebook_title

        # Standard English Reel with stats and pipe
        raw1 = "9.7K views · 352 reactions | My Awesome Reel | Beast Camp Training"
        self.assertEqual(clean_facebook_title(raw1), "My Awesome Reel | Beast Camp Training")

        # Reactions and shares
        raw2 = "119 reactions · 1.4K shares | Asif Nawab Butt on Reels"
        self.assertEqual(clean_facebook_title(raw2), "Asif Nawab Butt on Reels")

        # 3 stats
        raw3 = "1.2M views · 45K reactions · 3.2K shares | My Amazing Video Title"
        self.assertEqual(clean_facebook_title(raw3), "My Amazing Video Title")

        # Single stat: views only
        raw4 = "500 views | Single Stat Title"
        self.assertEqual(clean_facebook_title(raw4), "Single Stat Title")

        # Single stat: reactions only
        raw5 = "42 reactions | Reactions Only Title"
        self.assertEqual(clean_facebook_title(raw5), "Reactions Only Title")

        # Chinese Simplified
        raw6 = "1.5万次观看 · 352次点赞 | 简体中文标题"
        self.assertEqual(clean_facebook_title(raw6), "简体中文标题")

        # Chinese Traditional
        raw7 = "1.5萬次觀看 · 352個心情 · 100次分享 | 繁體中文影片標題"
        self.assertEqual(clean_facebook_title(raw7), "繁體中文影片標題")

        # Multiline: stats on line 1, title on line 2
        raw8 = "9.7K views · 352 reactions\nMultiline Real Video Title"
        self.assertEqual(clean_facebook_title(raw8), "Multiline Real Video Title")

        # Quoted title
        raw9 = '"9.7K views · 352 reactions | Quoted Title"'
        self.assertEqual(clean_facebook_title(raw9), "Quoted Title")

        # Stats only without real title -> returns fallback
        raw10 = "9.7K views · 352 reactions"
        self.assertEqual(clean_facebook_title(raw10, fallback="FALLBACK"), "FALLBACK")

        # Regular title that contains 'views' in sentence -> preserved untouched
        raw11 = "10 views on life and philosophy | My Lecture"
        self.assertEqual(clean_facebook_title(raw11), "10 views on life and philosophy | My Lecture")

    def test_scan_strips_views_and_reactions_from_source_title_and_video_item(self):
        """Verify scan() strips views and reactions from both ScanResult.source_title and VideoItem.title."""
        mock_info = {
            "id": "1195289147628387",
            "title": "9.7K views · 352 reactions | Amazing Slapathon Reel | Beast Camp",
            "uploader": "Beast Camp",
            "uploader_id": "100040874179269",
            "duration": 15,
            "webpage_url": "https://www.facebook.com/reel/1195289147628387",
            "thumbnail": "https://scontent.xx.fbcdn.net/thumb.jpg",
            "upload_date": "20240410",
            "description": "Original caption text",
            "extractor_key": "FacebookReel",
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            adapter = FacebookAdapter()
            scan_result = adapter.scan("https://www.facebook.com/reel/1195289147628387")
            # source_title must be stripped of views and reactions
            self.assertEqual(scan_result.source_title, "Amazing Slapathon Reel | Beast Camp")
            self.assertEqual(len(scan_result.videos), 1)

            # Available video item title in table must be stripped of views and reactions
            item = scan_result.videos[0]
            self.assertEqual(item.title, "Amazing Slapathon Reel | Beast Camp")
            self.assertNotIn("9.7K views", item.title)
            self.assertNotIn("352 reactions", item.title)

    def test_download_title_sanitizer_strips_views_and_reactions_for_filename(self):
        """Verify TitleSanitizerPP strips views/reactions so yt-dlp outputs clean filename."""
        from downloader.ytdlp_engine import TitleSanitizerPP
        from core.paths import resolve_media_filename

        raw_fb_title = "9.7K views · 352 reactions | Sunset Timelapse | Nature Channel"
        info = {
            "id": "999888777",
            "title": raw_fb_title,
            "extractor_key": "FacebookReel",
        }

        pp = TitleSanitizerPP(include_video_id=False)
        _, cleaned_info = pp.run(info)

        # Downloaded filename title stem in info must not contain stats
        self.assertEqual(cleaned_info["title"], "Sunset Timelapse _ Nature Channel")
        self.assertNotIn("views", cleaned_info["title"])
        self.assertNotIn("reactions", cleaned_info["title"])

        # Sidecar filenames generated with clean title match
        sidecar_meta = resolve_media_filename("Sunset Timelapse | Nature Channel", "999888777", ext="metadata.txt")
        self.assertEqual(sidecar_meta, "Sunset Timelapse _ Nature Channel.metadata.txt")

    def test_metadata_formatter_strips_views_and_reactions(self):
        """Verify FacebookMetadataFormatter excludes views/reactions from the Video Title field."""
        from metadata.facebook_formatter import FacebookMetadataFormatter

        raw_title = "119 reactions · 1.4K shares | Asif Nawab Butt on Reels"
        info = {
            "id": "274175099429670",
            "title": raw_title,
            "uploader": "Asif Nawab Butt",
            "webpage_url": "https://www.facebook.com/reel/274175099429670",
        }

        formatter = FacebookMetadataFormatter()
        output = formatter.format(info=info)

        self.assertIn("Video Title:\nAsif Nawab Butt on Reels", output)
        self.assertNotIn("119 reactions", output)
        self.assertNotIn("1.4K shares", output)

if __name__ == "__main__":
    unittest.main()
