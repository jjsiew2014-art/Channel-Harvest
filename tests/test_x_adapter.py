"""
test_x_adapter.py
Comprehensive unit and integration test suite for the X (formerly Twitter) platform integration in Channel Harvest.

Covers:
1. Platform Registration and Discovery (PlatformRegistry, PlatformDetector)
2. URL Recognition, Validation, Normalization, and Query Stripping
3. Platform Capabilities Matrix
4. Title Cleaning and Sanitization (clean_x_title: t.co stripping, unicode, length budgets)
5. Single Video Post Extraction and Metadata Normalization
6. Multi-Media Post Extraction (unique IDs, /video/<idx> URLs, parent metadata preservation)
7. Text-Only and Photo-Only Post Honest Handling (no fake video entries)
8. Profile URL Scanning and Scan Completeness Reporting
9. Authentication Scoping and Custom Cookie File Integration (AuthChecker, session verification)
10. Credential Protection and Log/Metadata Redaction
11. Availability Detection (XAvailabilityDetector)
12. Error Classification and Platform Scoping (ErrorClassifier)
13. Metadata TXT Formatting (XMetadataFormatter, UTF-8, no fabricated data)
14. Shared Download Pipeline Integration (MOV, WAV, sanitize_filename, archive tag)
15. Tri-lingual Localization Coverage (en, zh_CN, zh_TW)
16. Platform Regression Verification (YouTube, TikTok, Bilibili, Facebook, Instagram intact; Douyin frozen)
"""

import http.cookiejar
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_dlp.utils import DownloadError, ExtractorError

from core.availability import AvailabilityDetectorRegistry, AvailabilityStatus, XAvailabilityDetector
from core.error_classifier import ErrorCategory, ErrorClassifier
from core.i18n import I18nManager
from core.models import DownloadSettings, VideoItem, VideoStatus, ScanResult, DownloadMode
from core.paths import sanitize_filename, calculate_safe_stem_length
from core.platform import PlatformCapabilities, PlatformDetector, PlatformRegistry
from core.platform.auth import PlatformAuthConfig
from core.platform.douyin import DouyinAdapter
from core.platform.x import XAdapter, clean_x_title
from downloader.auth_checker import AuthChecker, AuthStatusCode, validate_cookie_file
from downloader.format_selector import FormatSelector
from metadata import MetadataExporter
from metadata.x_formatter import XMetadataFormatter


class TestXRegistrationAndDetector(unittest.TestCase):
    """Verifies X (Twitter) registration in PlatformRegistry and URL detection."""

    def setUp(self):
        self.adapter = XAdapter()

    def test_registration_and_lookup(self):
        """Verify XAdapter is registered and retrievable."""
        reg_adapter = PlatformRegistry.get_adapter("x")
        self.assertIsNotNone(reg_adapter)
        self.assertEqual(reg_adapter.platform_id, "x")
        self.assertEqual(reg_adapter.display_name, "X (Twitter)")
        self.assertTrue(PlatformRegistry.is_available("x"))

        # Lookup by URL
        matched_x = PlatformRegistry.get_adapter_for_url("https://x.com/jack/status/20")
        self.assertIs(matched_x, reg_adapter)

        matched_twitter = PlatformRegistry.get_adapter_for_url("https://twitter.com/jack/status/20")
        self.assertIs(matched_twitter, reg_adapter)

        matched_mobile = PlatformRegistry.get_adapter_for_url("https://mobile.twitter.com/jack/status/20")
        self.assertIs(matched_mobile, reg_adapter)

    def test_platform_detector(self):
        """Verify PlatformDetector identifies all supported X/Twitter URL forms."""
        test_cases = [
            ("https://x.com/jack/status/20", "x"),
            ("https://www.x.com/jack/status/20", "x"),
            ("https://twitter.com/jack/status/20", "x"),
            ("https://www.twitter.com/jack/status/20", "x"),
            ("https://mobile.twitter.com/jack/status/20", "x"),
            ("https://m.twitter.com/jack/status/20", "x"),
            ("https://x.com/i/status/123456789", "x"),
            ("https://twitter.com/i/web/status/123456789", "x"),
            ("https://x.com/nasa", "x"),
            ("https://twitter.com/OpenAI", "x"),
            ("https://x.com/jack/status/20?s=20&t=abcdef", "x"),
        ]
        for url, expected in test_cases:
            self.assertEqual(
                PlatformDetector.identify_platform_id(url),
                expected,
                f"Failed detection for {url}",
            )

    def test_detector_negative_matching(self):
        """Verify PlatformDetector rejects non-X URLs."""
        non_x_urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://www.facebook.com/reel/1234567890", "facebook"),
            ("https://www.instagram.com/reel/Chunk8-jurw/", "instagram"),
            ("https://www.tiktok.com/@user/video/123456789", "tiktok"),
            ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
            ("https://notx.com/jack/status/20", "unknown"),
            ("https://example.com/x.com/status/123", "unknown"),
        ]
        for url, expected in non_x_urls:
            self.assertEqual(
                PlatformDetector.identify_platform_id(url),
                expected,
                f"Negative test failed for {url}",
            )


class TestXUrlValidationAndNormalization(unittest.TestCase):
    """Verifies URL validation, normalization, and parameter stripping for X."""

    def setUp(self):
        self.adapter = XAdapter()

    def test_valid_post_urls(self):
        """Valid status URLs pass validation."""
        valid_urls = [
            "https://x.com/username/status/1234567890123456789",
            "https://www.x.com/username/status/1234567890123456789",
            "https://twitter.com/username/status/1234567890123456789",
            "https://www.twitter.com/username/status/1234567890123456789",
            "https://mobile.twitter.com/username/status/1234567890123456789",
            "https://x.com/i/status/1234567890123456789",
            "https://twitter.com/i/web/status/1234567890123456789",
            "https://x.com/username/status/1234567890123456789/video/1",
            "https://x.com/username/status/1234567890123456789?s=20&t=xyz",
        ]
        for url in valid_urls:
            is_valid, reason = self.adapter.validate_url(url)
            self.assertTrue(is_valid, f"Expected valid for {url}, got: {reason}")
            self.assertEqual(reason, "")

    def test_valid_profile_urls(self):
        """Valid profile URLs pass validation."""
        valid_profiles = [
            "https://x.com/nasa",
            "https://twitter.com/OpenAI",
            "https://www.x.com/elonmusk",
            "https://mobile.twitter.com/jack",
            "https://x.com/user_name_123/",
        ]
        for url in valid_profiles:
            is_valid, reason = self.adapter.validate_url(url)
            self.assertTrue(is_valid, f"Expected valid for profile {url}, got: {reason}")
            self.assertEqual(reason, "")

    def test_reserved_paths_rejection(self):
        """Reserved system paths on X cannot be profiles."""
        reserved = [
            "https://x.com/explore",
            "https://twitter.com/settings",
            "https://x.com/login",
            "https://x.com/i",
            "https://twitter.com/home",
            "https://x.com/notifications",
        ]
        for url in reserved:
            is_valid, reason = self.adapter.validate_url(url)
            self.assertFalse(is_valid, f"Expected invalid for reserved path {url}")
            self.assertIn("reserved", reason.lower())

    def test_invalid_urls(self):
        """Malformed or non-X URLs fail validation with clear reasons."""
        invalid_cases = [
            ("", "empty"),
            ("   ", "no valid url"),
            ("not a url", "domain is not a valid x"),
            ("https://www.youtube.com/watch?v=123", "domain is not a valid x"),
            ("https://x.com/", "please enter a specific x"),
        ]
        for url, expected_err in invalid_cases:
            is_valid, reason = self.adapter.validate_url(url)
            self.assertFalse(is_valid, f"Expected invalid for '{url}'")
            self.assertIn(expected_err, reason.lower())

    def test_url_normalization(self):
        """Normalizes domains to x.com, standardizes paths, and strips tracking query parameters."""
        cases = [
            (
                "https://twitter.com/jack/status/20?s=20&t=xyz",
                "https://x.com/jack/status/20",
            ),
            (
                "https://mobile.twitter.com/jack/status/20",
                "https://x.com/jack/status/20",
            ),
            (
                "http://www.twitter.com/jack/status/20",
                "https://x.com/jack/status/20",
            ),
            (
                "https://x.com/i/status/987654321?ref_src=twsrc",
                "https://x.com/i/status/987654321",
            ),
            (
                "https://twitter.com/user/status/123/video/2?s=20",
                "https://x.com/user/status/123/video/2",
            ),
            (
                "https://twitter.com/nasa?lang=en",
                "https://x.com/nasa",
            ),
        ]
        for raw, expected in cases:
            norm = self.adapter.normalize_url(raw)
            self.assertEqual(norm, expected, f"Normalization mismatch for {raw}")

    def test_build_video_url(self):
        """Canonical playback URL construction."""
        self.assertEqual(
            self.adapter.build_video_url("123456789"),
            "https://x.com/i/status/123456789",
        )
        self.assertEqual(
            self.adapter.build_video_url("123456789_2"),
            "https://x.com/i/status/123456789/video/2",
        )
        # Using VideoItem mock
        item = VideoItem(index=1, video_id="555_1", title="Test", duration="00:30", url="https://x.com/author/status/555/video/1")
        self.assertEqual(
            self.adapter.build_video_url(item),
            "https://x.com/author/status/555/video/1",
        )


class TestXCapabilities(unittest.TestCase):
    """Verifies X platform capabilities matrix."""

    def setUp(self):
        self.adapter = XAdapter()

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertTrue(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_chapters)  # X doesn't have chapters
        self.assertTrue(caps.supports_playlists) # Multi-video tweets
        self.assertTrue(caps.supports_channel_scan) # Profile scanning
        self.assertFalse(caps.supports_browser_cookies)
        self.assertTrue(caps.supports_cookie_file) # Custom cookie file
        self.assertEqual(caps.archive_prefix, "x")

    def test_archive_tag(self):
        item = VideoItem(index=1, video_id="1790637589910654976", title="Test Post", duration="00:15")
        self.assertEqual(self.adapter.get_archive_tag(item), "x 1790637589910654976")


class TestXTitleCleaning(unittest.TestCase):
    """Verifies clean_x_title with various X/Twitter text structures."""

    def test_strips_trailing_t_co_url(self):
        raw = "One of the most intense moments in history https://t.co/Zgzhvix8ES"
        clean = clean_x_title(raw)
        self.assertEqual(clean, "One of the most intense moments in history")

    def test_strips_redundant_author_prefix(self):
        raw = "Historic Vids - Incredible footage of natural phenomena https://t.co/abc123"
        clean = clean_x_title(raw)
        self.assertEqual(clean, "Incredible footage of natural phenomena")

    def test_multiline_tweet_takes_first_line(self):
        raw = "First line with important context\n\nSecond line with extra details\n#Hashtag https://t.co/link"
        clean = clean_x_title(raw)
        self.assertEqual(clean, "First line with important context")

    def test_unicode_chinese_emoji_preserved(self):
        raw = "🔥 精彩绝伦的历史时刻！来看这段超高清视频 🎥 https://t.co/abc"
        clean = clean_x_title(raw)
        self.assertEqual(clean, "🔥 精彩绝伦的历史时刻！来看这段超高清视频 🎥")

    def test_fallback_when_empty_or_only_link(self):
        raw = "https://t.co/onlylink123"
        clean = clean_x_title(raw, fallback="Fallback Title")
        self.assertEqual(clean, "Fallback Title")

    def test_length_budget_enforced(self):
        long_text = "This is a very long tweet title that exceeds one hundred and twenty characters in total length so it must be cleanly bounded without breaking arbitrarily in the middle"
        clean = clean_x_title(long_text)
        self.assertLessEqual(len(clean), 120)
        self.assertFalse(clean.endswith(" "))


class TestXSinglePostExtraction(unittest.TestCase):
    """Verifies single video post extraction and normalization."""

    def setUp(self):
        self.adapter = XAdapter()

    @patch("yt_dlp.YoutubeDL")
    def test_single_video_scan(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "id": "1790637589910654976",
            "title": "Historic Vids - One of the most intense moments in history",
            "description": "One of the most intense moments in history https://t.co/Zgzhvix8ES",
            "uploader": "Historic Vids",
            "uploader_id": "historyinmemes",
            "channel_id": "12345",
            "duration": 15.488,
            "timestamp": 1715756260,
            "like_count": 132746,
            "repost_count": 18230,
            "comment_count": 1420,
            "view_count": 5200000,
            "thumbnail": "https://pbs.twimg.com/media/abc.jpg",
            "webpage_url": "https://x.com/historyinmemes/status/1790637589910654976",
            "formats": [{"format_id": "http-1080p", "vcodec": "h264", "acodec": "aac", "width": 1920, "height": 1080}],
        }

        result = self.adapter.scan("https://x.com/historyinmemes/status/1790637589910654976")
        self.assertIsInstance(result, ScanResult)
        self.assertEqual(result.platform, "x")
        self.assertEqual(len(result.videos), 1)

        video = result.videos[0]
        self.assertEqual(video.video_id, "1790637589910654976")
        self.assertEqual(video.title, "One of the most intense moments in history")
        self.assertEqual(video.channel_title, "Historic Vids")
        self.assertEqual(video.duration, "00:15")
        self.assertEqual(video.duration_seconds, 15)
        self.assertEqual(video.status, VideoStatus.READY)
        self.assertTrue(video.selected)
        self.assertEqual(video.extra_metadata["uploader_id"], "historyinmemes")
        self.assertEqual(video.extra_metadata["like_count"], 132746)

    @patch("yt_dlp.YoutubeDL")
    def test_photo_only_post_honest_error(self, mock_ydl_cls):
        """Posts containing only photos/text should raise ExtractionError / EmptyChannelError honestly."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = DownloadError("[twitter] 123456: No video could be found in this tweet")

        from downloader.ytdlp_engine import ExtractionError
        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.scan("https://x.com/username/status/123456")
        self.assertIn("no downloadable video media", str(ctx.exception).lower())


class TestXMultiMediaExtraction(unittest.TestCase):
    """Verifies extraction and item separation for tweets containing multiple videos."""

    def setUp(self):
        self.adapter = XAdapter()

    @patch("yt_dlp.YoutubeDL")
    def test_multi_video_playlist_unpacking(self, mock_ydl_cls):
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "_type": "playlist",
            "id": "1600649710662213632",
            "title": "Jocelyn Laidlaw - Important discussion",
            "description": "How death inspired me to share more about my health https://t.co/link",
            "uploader": "Jocelyn Laidlaw",
            "uploader_id": "CTVJLaidlaw",
            "entries": [
                {
                    "id": "1600649511827038209",
                    "title": "Part 1 Discussion #1",
                    "duration": 113.49,
                    "formats": [{"vcodec": "h264", "acodec": "aac"}],
                    "thumbnail": "https://pbs.twimg.com/thumb1.jpg",
                },
                {
                    "id": "1600649511827013632",
                    "title": "Part 2 Discussion #2",
                    "duration": 102.226,
                    "formats": [{"vcodec": "h264", "acodec": "aac"}],
                    "thumbnail": "https://pbs.twimg.com/thumb2.jpg",
                },
            ],
        }

        result = self.adapter.scan("https://twitter.com/CTVJLaidlaw/status/1600649710662213632")
        self.assertEqual(len(result.videos), 2)

        # Video 1
        v1 = result.videos[0]
        self.assertEqual(v1.index, 1)
        self.assertEqual(v1.video_id, "1600649710662213632_1")
        self.assertIn("(Part 1)", v1.title)
        self.assertEqual(v1.url, "https://x.com/CTVJLaidlaw/status/1600649710662213632/video/1")
        self.assertEqual(v1.duration, "01:53")
        self.assertEqual(v1.extra_metadata["media_index"], 1)
        self.assertEqual(v1.extra_metadata["parent_id"], "1600649710662213632")

        # Video 2
        v2 = result.videos[1]
        self.assertEqual(v2.index, 2)
        self.assertEqual(v2.video_id, "1600649710662213632_2")
        self.assertIn("(Part 2)", v2.title)
        self.assertEqual(v2.url, "https://x.com/CTVJLaidlaw/status/1600649710662213632/video/2")
        self.assertEqual(v2.duration, "01:42")
        self.assertEqual(v2.extra_metadata["media_index"], 2)


class TestXProfileScanning(unittest.TestCase):
    """Verifies profile URL handling, completeness reporting, and limitation transparency."""

    def setUp(self):
        self.adapter = XAdapter()

    @patch("yt_dlp.YoutubeDL")
    def test_profile_extractor_unsupported_reported(self, mock_ydl_cls):
        """When yt-dlp raises Unsupported URL for profile, reports clear message."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = DownloadError("ERROR: Unsupported URL: https://x.com/jack")

        from downloader.ytdlp_engine import ExtractionError
        with self.assertRaises(ExtractionError) as ctx:
            self.adapter.scan("https://x.com/jack")
        self.assertIn("profile timeline extraction is not supported", str(ctx.exception).lower())

    @patch("yt_dlp.YoutubeDL")
    def test_profile_scan_when_entries_returned(self, mock_ydl_cls):
        """If extractor returns profile playlist entries, correctly normalizes and caps them."""
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "_type": "playlist",
            "id": "jack",
            "title": "Jack Dorsey",
            "uploader": "Jack",
            "uploader_id": "jack",
            "entries": [
                {
                    "id": "1001",
                    "title": "Video Post One",
                    "duration": 30,
                    "formats": [{"vcodec": "h264", "acodec": "aac"}],
                    "webpage_url": "https://x.com/jack/status/1001",
                },
                {
                    "id": "1002",
                    "title": "Text Post without video",
                    "formats": [],
                    "duration": None,
                },
                {
                    "id": "1003",
                    "title": "Video Post Three",
                    "duration": 45,
                    "formats": [{"vcodec": "h264", "acodec": "aac"}],
                    "webpage_url": "https://x.com/jack/status/1003",
                },
            ],
        }

        result = self.adapter.scan("https://x.com/jack")
        self.assertEqual(result.source_type, "channel")
        # Text post 1002 skipped honestly
        self.assertEqual(len(result.videos), 2)
        self.assertEqual(result.videos[0].video_id, "1001")
        self.assertEqual(result.videos[1].video_id, "1003")
        self.assertEqual(result.extra_metadata["scan_completeness"], "complete")


class TestXAuthentication(unittest.TestCase):
    """Verifies Custom Cookie File authentication, scoping, and AuthChecker."""

    def setUp(self):
        self.adapter = XAdapter()

    def test_get_auth_config_none(self):
        """Defaults to none when unconfigured."""
        cfg = self.adapter.get_auth_config()
        self.assertEqual(cfg.auth_method, "none")
        self.assertFalse(cfg.is_active)

    def test_get_auth_config_with_valid_file(self):
        """Loads custom_file when file exists."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"# Netscape HTTP Cookie File\n")
            cpath = f.name
        try:
            settings = {
                "x_auth_method": "custom_file",
                "x_custom_cookie_file": cpath,
            }
            cfg = self.adapter.get_auth_config(settings=settings)
            self.assertEqual(cfg.auth_method, "custom_file")
            self.assertTrue(cfg.is_active)
            self.assertEqual(Path(cfg.cookie_file).resolve(), Path(cpath).resolve())

            # Options propagation
            opts = {}
            cfg.apply_to_ydl_opts(opts)
            self.assertEqual(opts.get("cookiefile"), str(Path(cpath).resolve()))
        finally:
            if os.path.exists(cpath):
                os.remove(cpath)

    def test_auth_checker_x_cookies_valid(self):
        """AuthChecker recognizes X cookies and session tokens."""
        content = (
            "# Netscape HTTP Cookie File\n"
            ".x.com\tTRUE\t/\tTRUE\t1999999999\tauth_token\tsecret_token_12345\n"
            ".x.com\tTRUE\t/\tTRUE\t1999999999\tct0\tcsrf_token_67890\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            cpath = f.name
        try:
            val = validate_cookie_file(cpath, platform="x")
            self.assertTrue(val["is_valid"])
            self.assertEqual(val["status_code"], AuthStatusCode.COOKIE_FILE_VALID)
            self.assertTrue(val["has_session"])
            self.assertEqual(val["youtube_cookie_count"], 2)

            res = AuthChecker.test_authentication(cpath, platform="x")
            self.assertTrue(res.success)
            self.assertEqual(res.status_code, AuthStatusCode.X_SESSION_AUTHENTICATED)
            self.assertEqual(res.platform, "x")
            self.assertTrue(res.has_session)
        finally:
            if os.path.exists(cpath):
                os.remove(cpath)

    def test_auth_checker_non_x_cookies(self):
        """AuthChecker rejects cookie files without X cookies when platform is x."""
        content = (
            "# Netscape HTTP Cookie File\n"
            ".bilibili.com\tTRUE\t/\tTRUE\t1999999999\tSESSDATA\tbili_val\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write(content)
            cpath = f.name
        try:
            val = validate_cookie_file(cpath, platform="x")
            self.assertFalse(val["is_valid"])
            self.assertEqual(val["status_code"], AuthStatusCode.NO_X_COOKIES)

            res = AuthChecker.test_authentication(cpath, platform="x")
            self.assertFalse(res.success)
            self.assertEqual(res.status_code, AuthStatusCode.NO_X_COOKIES)
        finally:
            if os.path.exists(cpath):
                os.remove(cpath)


class TestXAvailabilityDetection(unittest.TestCase):
    """Verifies XAvailabilityDetector error and entry classification."""

    def setUp(self):
        self.detector = AvailabilityDetectorRegistry.get_detector("x")

    def test_detector_registered(self):
        self.assertIsInstance(self.detector, XAvailabilityDetector)
        self.assertIs(AvailabilityDetectorRegistry.get_detector("twitter"), self.detector)

    def test_detect_available_entry(self):
        entry = {
            "id": "123",
            "title": "Clean normal video",
            "duration": 30,
            "formats": [{"vcodec": "h264", "acodec": "aac"}],
        }
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.AVAILABLE)
        self.assertFalse(avail.is_definitively_inaccessible())

    def test_detect_deleted_error(self):
        avail = self.detector.detect_error("ERROR: Tweet has been deleted")
        self.assertEqual(avail.status, AvailabilityStatus.DELETED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_detect_protected_account(self):
        avail = self.detector.detect_error("ERROR: This Tweet is from a protected account")
        self.assertEqual(avail.status, AvailabilityStatus.PRIVATE)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_detect_auth_required(self):
        avail = self.detector.detect_error("ERROR: The Tweet requires authentication")
        self.assertEqual(avail.status, AvailabilityStatus.AUTH_REQUIRED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_detect_no_video_format(self):
        avail = self.detector.detect_error("ERROR: No video could be found in this tweet")
        self.assertEqual(avail.status, AvailabilityStatus.NO_SUPPORTED_FORMAT)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_detect_rate_limit_temporary(self):
        avail = self.detector.detect_error("HTTP Error 429: Too Many Requests")
        self.assertEqual(avail.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(avail.is_definitively_inaccessible())


class TestXErrorClassifier(unittest.TestCase):
    """Verifies ErrorClassifier scopes X errors accurately."""

    def test_login_required(self):
        err = ErrorClassifier.classify("ERROR: [twitter] 123: login required to view", platform="x")
        self.assertEqual(err.category, ErrorCategory.LOGIN_REQUIRED)
        self.assertIn("X (Twitter)", err.user_message)
        self.assertTrue(err.is_x)

    def test_protected_account(self):
        err = ErrorClassifier.classify("ERROR: This Tweet is from a protected account", platform="x")
        self.assertEqual(err.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertIn("protected", err.user_message)

    def test_rate_limited(self):
        err = ErrorClassifier.classify("HTTP Error 429: Too Many Requests", platform="x")
        self.assertEqual(err.category, ErrorCategory.RATE_LIMITED)
        self.assertIn("X (Twitter)", err.user_message)
        self.assertTrue(err.retryable)

    def test_deleted_video(self):
        err = ErrorClassifier.classify("ERROR: Tweet has been deleted", platform="x")
        self.assertEqual(err.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertIn("X (Twitter)", err.user_message)


class TestXMetadataFormatter(unittest.TestCase):
    """Verifies XMetadataFormatter and credential scrubbing."""

    def test_formatter_registration(self):
        fmt = MetadataExporter.get_formatter(platform_id="x")
        self.assertIsInstance(fmt, XMetadataFormatter)
        fmt_tw = MetadataExporter.get_formatter(info={"extractor_key": "Twitter"})
        self.assertIsInstance(fmt_tw, XMetadataFormatter)

    def test_formatting_fields(self):
        info = {
            "id": "1790637589910654976",
            "title": "Historic Vids - One of the most intense moments in history",
            "description": "One of the most intense moments in history #History #Epic https://t.co/abc",
            "uploader": "Historic Vids",
            "uploader_id": "historyinmemes",
            "channel_id": "998877",
            "duration": 15,
            "timestamp": 1715756260,
            "like_count": 132746,
            "repost_count": 18230,
            "comment_count": 1420,
            "view_count": 5200000,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "vcodec": "h264",
            "acodec": "aac",
            "ext": "mp4",
            "format_id": "http-1080p",
            "webpage_url": "https://x.com/historyinmemes/status/1790637589910654976",
        }
        text = MetadataExporter.export_metadata_txt(info, platform_id="x")
        self.assertIn("Platform:\nX (Twitter)", text)
        self.assertIn("Post ID:\n1790637589910654976", text)
        self.assertIn("Author Username:\n@historyinmemes", text)
        self.assertIn("Like Count:\n132,746", text)
        self.assertIn("Repost Count (Retweets):\n18,230", text)
        self.assertIn("Resolution:\n1920x1080", text)
        self.assertIn("Video Codec:\nh264", text)

    def test_credential_scrubbing(self):
        """Scrubs any tokens or secrets that might appear in metadata."""
        info = {
            "id": "123",
            "title": "Secret post",
            "description": "Auth header Authorization: Basic dXNlcjpwYXNz with Bearer abcdef12345",
        }
        text = MetadataExporter.export_metadata_txt(info, platform_id="x")
        self.assertNotIn("abcdef12345", text)
        self.assertNotIn("dXNlcjpwYXNz", text)
        self.assertIn("[REDACTED_CREDENTIAL]", text)


class TestXPipelineIntegration(unittest.TestCase):
    """Verifies format selection, filename sanitization, and pipeline integration for X."""

    def test_format_spec_defaults(self):
        """MOV and WAV defaults apply cleanly to X."""
        settings_video = DownloadSettings(download_mode=DownloadMode.VIDEO_ONLY, format="MOV", quality="1080p")
        spec, ext = FormatSelector.build_video_format_spec(settings_video)
        self.assertEqual(ext, "mov")

        settings_audio = DownloadSettings(download_mode=DownloadMode.AUDIO_ONLY, audio_format="WAV")
        spec_a, ext_a, _ = FormatSelector.build_audio_format_spec(settings_audio)
        self.assertEqual(ext_a, "wav")

    def test_filename_sanitization_long_chinese_emoji(self):
        """Centralized sanitizer handles X post titles with emojis, Chinese, and Windows-illegal chars."""
        title = '🔥 [Exclusive] 深度评测：这是史上最震撼的视频！*?:"<>| https://t.co/xyz'
        cleaned = clean_x_title(title)
        stem_len = calculate_safe_stem_length(target_dir=Path("C:/Downloads"), suffix="", reserve_extra=15)
        safe_fname = sanitize_filename(cleaned, max_length=stem_len)
        self.assertTrue(all(c not in safe_fname for c in '<>:"/\\|?*'))
        self.assertIn("深度评测", safe_fname)
        self.assertIn("🔥", safe_fname)


class TestXLocalization(unittest.TestCase):
    """Verifies all required X strings exist across all 3 supported languages."""

    REQUIRED_KEYS = [
        "platform_x",
        "section_x_link",
        "x_url_label",
        "x_url_placeholder",
        "scan_x",
        "dialog_invalid_x_url_title",
        "dialog_invalid_x_url_msg",
        "settings_auth_x",
        "auth_x_none_hint",
        "auth_x_hint",
        "auth_x_privacy_notice",
        "auth_test_x_tooltip",
        "auth_dialog_x_title",
        "auth_click_test_x_hint",
        "status_x_session_detected",
        "tooltip_x_no_chapters",
        "tooltip_x_no_subs",
        "empty_subtitle_x",
    ]

    def test_all_keys_in_all_languages(self):
        for key in self.REQUIRED_KEYS:
            for lang in ("en", "zh_CN", "zh_TW"):
                I18nManager.set_language(lang)
                val = I18nManager.tr(key)
                self.assertIsNotNone(val, f"Missing key {key} for lang {lang}")
                self.assertNotEqual(val, key, f"Untranslated key {key} for lang {lang}")
                self.assertTrue(len(val) > 0, f"Empty translation for {key} in {lang}")


class TestPlatformRegression(unittest.TestCase):
    """Verifies existing platforms remain registered and Douyin remains disabled."""

    def test_platforms_available(self):
        self.assertTrue(PlatformRegistry.is_available("youtube"))
        self.assertTrue(PlatformRegistry.is_available("tiktok"))
        self.assertTrue(PlatformRegistry.is_available("bilibili"))
        self.assertTrue(PlatformRegistry.is_available("facebook"))
        self.assertTrue(PlatformRegistry.is_available("instagram"))
        self.assertTrue(PlatformRegistry.is_available("x"))

    def test_douyin_remains_frozen(self):
        douyin = PlatformRegistry.get_adapter("douyin")
        self.assertIsNotNone(douyin)
        self.assertFalse(douyin.is_available)
        self.assertFalse(PlatformRegistry.is_available("douyin"))


if __name__ == "__main__":
    unittest.main()
