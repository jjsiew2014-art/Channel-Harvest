"""
test_instagram_adapter.py
Comprehensive unit and integration test suite for the Instagram platform adapter in Channel Harvest.

Covers:
1. Platform Registration and Discovery (PlatformRegistry, PlatformDetector)
2. URL Recognition, Validation, Normalization, and Query Stripping
3. Platform Capabilities Matrix
4. Platform Authentication Scoping and Isolation (Custom Cookie File, session verification)
5. Single Reel Extraction and Metadata Normalization
6. Standard Video Post Extraction
7. Photo-Only Post Honest Handling (no fake video items)
8. Carousel Multi-Item Normalization (unique IDs, duplicate prevention, photo filtering)
9. Public Profile Scanning (deduplication, max_videos, pagination, error handling, scan completeness)
10. Availability Detection (InstagramAvailabilityDetector)
11. Metadata TXT Formatting and Credential Protection (InstagramMetadataFormatter)
12. Error Classification and Localization
13. Tri-lingual Localization Coverage (en, zh_CN, zh_TW)
14. Douyin Platform Frozen / Disabled Verification
"""

import http.cookiejar
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from yt_dlp.utils import DownloadError, ExtractorError

from core.availability import AvailabilityDetectorRegistry, AvailabilityStatus, InstagramAvailabilityDetector
from core.error_classifier import ErrorCategory, ErrorClassifier
from core.i18n import I18nManager
from core.models import DownloadSettings, VideoItem, VideoStatus, ScanResult
from core.platform import PlatformCapabilities, PlatformDetector, PlatformRegistry
from core.platform.auth import PlatformAuthConfig
from core.platform.douyin import DouyinAdapter
from core.platform.instagram import InstagramAdapter, clean_instagram_title
from downloader.auth_checker import AuthChecker, AuthStatusCode, validate_cookie_file
from metadata import MetadataExporter
from metadata.instagram_formatter import InstagramMetadataFormatter


class TestInstagramRegistrationAndDetector(unittest.TestCase):
    """Verifies Instagram registration in PlatformRegistry and URL detection."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_registration_and_lookup(self):
        """Verify InstagramAdapter is registered and retrievable."""
        reg_adapter = PlatformRegistry.get_adapter("instagram")
        self.assertIsNotNone(reg_adapter)
        self.assertEqual(reg_adapter.platform_id, "instagram")
        self.assertEqual(reg_adapter.display_name, "Instagram")
        self.assertTrue(PlatformRegistry.is_available("instagram"))

        # Lookup by URL
        matched_reel = PlatformRegistry.get_adapter_for_url("https://www.instagram.com/reel/Chunk8-jurw/")
        self.assertIs(matched_reel, reg_adapter)

        matched_post = PlatformRegistry.get_adapter_for_url("https://www.instagram.com/p/Chunk8-jurw/")
        self.assertIs(matched_post, reg_adapter)

        matched_profile = PlatformRegistry.get_adapter_for_url("https://www.instagram.com/nasa/")
        self.assertIs(matched_profile, reg_adapter)

    def test_platform_detector(self):
        """Verify PlatformDetector identifies all supported Instagram URL forms."""
        test_cases = [
            ("https://www.instagram.com/reel/Chunk8-jurw/", "instagram"),
            ("https://instagram.com/reel/Chunk8-jurw", "instagram"),
            ("https://www.instagram.com/reels/Chunk8-jurw/", "instagram"),
            ("https://www.instagram.com/p/Chunk8-jurw/", "instagram"),
            ("https://instagram.com/p/Chunk8-jurw", "instagram"),
            ("https://www.instagram.com/tv/Chunk8-jurw/", "instagram"),
            ("https://m.instagram.com/reel/Chunk8-jurw/?igsh=abc123xyz", "instagram"),
            ("https://www.instagram.com/nasa/", "instagram"),
            ("https://instagram.com/natgeo", "instagram"),
            ("https://www.instagram.com/creator.name/", "instagram"),
        ]
        for url, expected in test_cases:
            self.assertEqual(
                PlatformDetector.identify_platform_id(url),
                expected,
                f"Failed for {url}",
            )

    def test_detector_negative_matching(self):
        """Verify PlatformDetector rejects non-Instagram URLs."""
        non_instagram_urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://www.facebook.com/reel/1234567890", "facebook"),
            ("https://www.tiktok.com/@user/video/123456789", "tiktok"),
            ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
            ("https://notinstagram.com/reel/123456", "unknown"),
            ("https://example.com/instagram.com/reel/123", "unknown"),
        ]
        for url, expected in non_instagram_urls:
            self.assertEqual(
                PlatformDetector.identify_platform_id(url),
                expected,
                f"Should not detect as instagram: {url}",
            )


class TestInstagramAdapterCapabilities(unittest.TestCase):
    """Verifies Instagram platform capabilities matrix."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertFalse(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_chapters)
        self.assertTrue(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_cookie_file)
        self.assertFalse(caps.supports_browser_cookies)
        self.assertEqual(caps.archive_prefix, "instagram")


class TestInstagramUrlHandling(unittest.TestCase):
    """Verifies Instagram URL matching, validation, normalization, and query stripping."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_matches_url(self):
        self.assertTrue(self.adapter.matches_url("https://www.instagram.com/reel/Chunk8-jurw/"))
        self.assertTrue(self.adapter.matches_url("https://instagram.com/p/BQ0eAlwhDrw/"))
        self.assertTrue(self.adapter.matches_url("https://www.instagram.com/tv/B_123456789/"))
        self.assertTrue(self.adapter.matches_url("https://www.instagram.com/natgeo/"))
        self.assertFalse(self.adapter.matches_url("https://www.youtube.com/watch?v=123"))

    def test_validate_url(self):
        ok, msg = self.adapter.validate_url("https://www.instagram.com/reel/Chunk8-jurw/")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

        ok_prof, msg_prof = self.adapter.validate_url("https://www.instagram.com/natgeo/")
        self.assertTrue(ok_prof)
        self.assertEqual(msg_prof, "")

        bad_ok, bad_msg = self.adapter.validate_url("https://www.instagram.com/explore/")
        self.assertFalse(bad_ok)
        self.assertIn("reserved", bad_msg.lower())

    def test_normalize_url(self):
        raw = "https://m.instagram.com/reel/Chunk8-jurw/?igsh=NTc4MTIwNjQ2YQ%3D%3D&utm_source=ig_web_copy_link"
        normalized = self.adapter.normalize_url(raw)
        self.assertEqual(normalized, "https://www.instagram.com/reel/Chunk8-jurw/")

        post_raw = "https://instagram.com/p/BQ0eAlwhDrw?utm_medium=copy_link"
        self.assertEqual(self.adapter.normalize_url(post_raw), "https://www.instagram.com/p/BQ0eAlwhDrw/")

        prof_raw = "https://instagram.com/nasa/?hl=en"
        self.assertEqual(self.adapter.normalize_url(prof_raw), "https://www.instagram.com/nasa/")

    def test_build_video_url_and_archive_tag(self):
        item = VideoItem(
            index=1,
            video_id="Chunk8-jurw",
            title="Test Reel",
            duration="00:30",
            url="https://www.instagram.com/reel/Chunk8-jurw/",
            platform="instagram",
        )
        self.assertEqual(self.adapter.build_video_url(item), "https://www.instagram.com/reel/Chunk8-jurw/")
        self.assertEqual(self.adapter.get_archive_tag(item), "instagram Chunk8-jurw")


class TestInstagramAuthentication(unittest.TestCase):
    """Verifies Instagram platform-scoped authentication and Custom Cookie File handling."""

    def setUp(self):
        self.adapter = InstagramAdapter()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cookie_file = Path(self.temp_dir.name) / "instagram_cookies.txt"
        self.cookie_file_content = (
            "# Netscape HTTP Cookie File\n"
            "# https://curl.se/docs/http-cookies.html\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\t12345%3Aabcdef%3A19\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tds_user_id\t123456789\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tcsrftoken\ttokenxyz987\n"
        )
        self.cookie_file.write_text(self.cookie_file_content, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_auth_config_propagation(self):
        # Default settings: no auth
        settings = DownloadSettings()
        cfg = self.adapter.get_auth_config(settings)
        self.assertEqual(cfg.auth_method, "none")
        self.assertFalse(cfg.is_active)
        opts_none = {}
        cfg.apply_to_ydl_opts(opts_none)
        self.assertNotIn("cookiefile", opts_none)

        # Custom cookie file configured
        settings.instagram_auth_method = "custom_file"
        settings.instagram_custom_cookie_file = str(self.cookie_file)
        cfg_custom = self.adapter.get_auth_config(settings)
        self.assertEqual(cfg_custom.auth_method, "custom_file")
        self.assertTrue(cfg_custom.is_active)
        opts_custom = {}
        cfg_custom.apply_to_ydl_opts(opts_custom)
        self.assertEqual(opts_custom.get("cookiefile"), str(self.cookie_file.resolve()))

    def test_auth_scoping_isolation(self):
        """Verify that Instagram cookie settings do not bleed into YouTube or Facebook."""
        settings = DownloadSettings()
        settings.instagram_auth_method = "custom_file"
        settings.instagram_custom_cookie_file = str(self.cookie_file)

        # YouTube and Facebook adapters should not pick up Instagram cookie file
        from core.platform.youtube import YouTubeAdapter
        from core.platform.facebook import FacebookAdapter
        yt = YouTubeAdapter()
        fb = FacebookAdapter()

        yt_cfg = yt.get_auth_config(settings)
        fb_cfg = fb.get_auth_config(settings)

        self.assertEqual(yt_cfg.auth_method, "none")
        self.assertEqual(fb_cfg.auth_method, "none")
        self.assertFalse(yt_cfg.is_active)
        self.assertFalse(fb_cfg.is_active)

    def test_cookie_file_validation_success(self):
        """Verify AuthChecker validates an Instagram cookie file containing session tokens."""
        val = validate_cookie_file(str(self.cookie_file), platform="instagram")
        self.assertTrue(val["is_valid"])
        self.assertEqual(val["youtube_cookie_count"], 3)
        self.assertTrue(val["has_session"])
        self.assertEqual(val["status_code"], AuthStatusCode.COOKIE_FILE_VALID)

        # Full test_authentication
        res = AuthChecker.test_authentication(
            "custom_file",
            custom_cookie_path=str(self.cookie_file),
            platform="instagram",
        )
        self.assertTrue(res.success)
        self.assertTrue(res.has_session)
        self.assertEqual(res.status_code, AuthStatusCode.INSTAGRAM_SESSION_AUTHENTICATED)

    def test_cookie_file_validation_missing_cookies(self):
        """Verify AuthChecker rejects cookie files with no Instagram cookies."""
        empty_cookie_file = Path(self.temp_dir.name) / "youtube_only.txt"
        empty_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\ttoken123\n",
            encoding="utf-8",
        )
        val = validate_cookie_file(str(empty_cookie_file), platform="instagram")
        self.assertFalse(val["is_valid"])
        self.assertEqual(val["status_code"], AuthStatusCode.NO_INSTAGRAM_COOKIES)

        res = AuthChecker.test_authentication(
            "custom_file",
            custom_cookie_path=str(empty_cookie_file),
            platform="instagram",
        )
        self.assertFalse(res.success)
        self.assertEqual(res.status_code, AuthStatusCode.NO_INSTAGRAM_COOKIES)


class TestInstagramSingleReelExtraction(unittest.TestCase):
    """Verifies extraction and normalization of single Instagram Reels."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_extract_single_reel(self):
        mock_info = {
            "id": "Chunk8-jurw",
            "title": "A captivating reel about space exploration",
            "description": "A captivating reel about space exploration #nasa #space",
            "uploader": "nasa",
            "uploader_id": "nasa",
            "duration": 42.5,
            "webpage_url": "https://www.instagram.com/reel/Chunk8-jurw/",
            "thumbnail": "https://instagram.com/thumb.jpg",
            "formats": [
                {"format_id": "1", "url": "https://instagram.com/video.mp4", "vcodec": "h264", "acodec": "aac", "width": 1080, "height": 1920}
            ],
            "like_count": 15000,
            "comment_count": 350,
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.instagram.com/reel/Chunk8-jurw/", DownloadSettings())
            self.assertEqual(len(res.videos), 1)
            video = res.videos[0]
            self.assertEqual(video.video_id, "Chunk8-jurw")
            self.assertEqual(video.platform, "instagram")
            self.assertEqual(video.status, VideoStatus.READY)
            self.assertEqual(video.channel_title, "nasa")
            self.assertEqual(video.duration_seconds, 42)
            self.assertEqual(video.url, "https://www.instagram.com/reel/Chunk8-jurw/")
            self.assertIn("captivating reel", video.title)
            self.assertEqual(res.extra_metadata.get("scan_completeness"), "complete")


class TestInstagramStandardVideoPostExtraction(unittest.TestCase):
    """Verifies extraction of standard /p/ video posts."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_extract_video_post(self):
        mock_info = {
            "id": "BQ0eAlwhDrw",
            "title": "Post Title Video",
            "description": "Standard Instagram video post caption",
            "uploader": "natgeo",
            "duration": 58,
            "webpage_url": "https://www.instagram.com/p/BQ0eAlwhDrw/",
            "thumbnail": "https://instagram.com/p_thumb.jpg",
            "formats": [
                {"format_id": "0", "url": "https://instagram.com/v.mp4", "vcodec": "avc1", "acodec": "mp4a", "width": 720, "height": 720}
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.instagram.com/p/BQ0eAlwhDrw/", DownloadSettings())
            self.assertEqual(len(res.videos), 1)
            v = res.videos[0]
            self.assertEqual(v.video_id, "BQ0eAlwhDrw")
            self.assertEqual(v.platform, "instagram")
            self.assertEqual(v.status, VideoStatus.READY)
            self.assertEqual(v.channel_title, "natgeo")


class TestInstagramPhotoOnlyPostHonestHandling(unittest.TestCase):
    """Verifies that photo-only posts produce zero fake video items."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_photo_only_post_not_treated_as_video(self):
        from downloader.ytdlp_engine import EmptyChannelError
        mock_info = {
            "id": "PhotoOnly123",
            "title": "A beautiful photo",
            "description": "Sunset at the beach",
            "uploader": "photographer",
            "formats": [],  # yt-dlp provides no video formats for photos
            "webpage_url": "https://www.instagram.com/p/PhotoOnly123/",
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(EmptyChannelError) as ctx:
                self.adapter.scan("https://www.instagram.com/p/PhotoOnly123/")
            self.assertIn("contains only photos", str(ctx.exception))


class TestInstagramCarouselExtraction(unittest.TestCase):
    """Verifies extraction and multi-item normalization for Instagram Carousels."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_carousel_multi_item_and_photo_filtering(self):
        mock_info = {
            "_type": "playlist",
            "id": "CarouselParent123",
            "title": "Vacation Highlights",
            "description": "Best moments of our summer trip!",
            "uploader": "traveler",
            "webpage_url": "https://www.instagram.com/p/CarouselParent123/",
            "entries": [
                # Entry 1: Downloadable video
                {
                    "id": "Item_1",
                    "title": "Vacation Highlights",
                    "formats": [{"format_id": "v1", "url": "https://ig.com/v1.mp4", "vcodec": "h264", "acodec": "aac"}],
                    "duration": 15,
                    "thumbnail": "https://ig.com/t1.jpg",
                },
                # Entry 2: Static photo (should be filtered out honestly)
                {
                    "id": "Item_2",
                    "title": "Vacation Highlights",
                    "formats": [],
                    "duration": None,
                    "thumbnail": "https://ig.com/t2.jpg",
                },
                # Entry 3: Downloadable video
                {
                    "id": "Item_3",
                    "title": "Vacation Highlights",
                    "formats": [{"format_id": "v3", "url": "https://ig.com/v3.mp4", "vcodec": "h264", "acodec": "aac"}],
                    "duration": 22,
                    "thumbnail": "https://ig.com/t3.jpg",
                },
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.instagram.com/p/CarouselParent123/", DownloadSettings())

            # Should extract exactly the 2 video items, skipping the photo
            self.assertEqual(len(res.videos), 2)

            item1 = res.videos[0]
            item2 = res.videos[1]

            # Verify distinct unique IDs to prevent overwrite
            self.assertNotEqual(item1.video_id, item2.video_id)
            self.assertEqual(item1.video_id, "CarouselParent123_1")
            self.assertEqual(item2.video_id, "CarouselParent123_3")

            # Verify parent info preserved
            self.assertEqual(item1.extra_metadata.get("parent_id"), "CarouselParent123")
            self.assertEqual(item2.extra_metadata.get("parent_id"), "CarouselParent123")
            self.assertEqual(item1.url, "https://www.instagram.com/p/CarouselParent123/")

            # Verify titles are distinct so they don't overwrite on disk
            self.assertIn("Part 1", item1.title)
            self.assertIn("Part 3", item2.title)


class TestInstagramProfileScanning(unittest.TestCase):
    """Verifies public profile scanning, deduplication, limits, and completeness reporting."""

    def setUp(self):
        self.adapter = InstagramAdapter()

    def test_profile_scan_and_deduplication(self):
        mock_info = {
            "_type": "playlist",
            "id": "nasa",
            "title": "nasa",
            "uploader": "nasa",
            "uploader_id": "nasa",
            "webpage_url": "https://www.instagram.com/nasa/",
            "entries": [
                {"id": "Reel_A", "title": "Reel A", "formats": [{"vcodec": "h264"}], "duration": 10},
                {"id": "Reel_B", "title": "Reel B", "formats": [{"vcodec": "h264"}], "duration": 20},
                {"id": "Reel_A", "title": "Reel A Duplicate", "formats": [{"vcodec": "h264"}], "duration": 10},  # duplicate
                {"id": "Reel_C", "title": "Reel C", "formats": [{"vcodec": "h264"}], "duration": 30},
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.instagram.com/nasa/", DownloadSettings())
            # Deduplication should yield 3 unique items
            self.assertEqual(len(res.videos), 3)
            ids = [v.video_id for v in res.videos]
            self.assertEqual(ids, ["Reel_A", "Reel_B", "Reel_C"])
            self.assertEqual(res.extra_metadata.get("scan_completeness"), "complete")

    def test_profile_scan_max_videos_limit(self):
        mock_info = {
            "_type": "playlist",
            "id": "nasa",
            "title": "nasa",
            "entries": [
                {"id": f"Reel_{i}", "title": f"Reel {i}", "formats": [{"vcodec": "h264"}]}
                for i in range(10)
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            settings = DownloadSettings()
            settings.max_videos = 4
            res = self.adapter.scan("https://www.instagram.com/nasa/", settings)
            self.assertEqual(len(res.videos), 4)

    def test_profile_unauthenticated_limitation_handling(self):
        """
        Verify graceful handling when unauthenticated profile scraping fails
        due to yt-dlp upstream InstagramUserIE limitations.
        """
        from downloader.ytdlp_engine import ExtractionError
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError("Unable to extract user profile: login required")
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(ExtractionError) as ctx:
                self.adapter.scan("https://www.instagram.com/nasa/")
            self.assertIn("authentication is required", str(ctx.exception).lower())


class TestInstagramAvailabilityDetector(unittest.TestCase):
    """Verifies availability classification for Instagram media."""

    def setUp(self):
        self.detector = InstagramAvailabilityDetector()

    def test_registry_lookup(self):
        reg_detector = AvailabilityDetectorRegistry.get_detector("instagram")
        self.assertIsInstance(reg_detector, InstagramAvailabilityDetector)

    def test_available_video(self):
        info = {"id": "Chunk8-jurw", "formats": [{"format_id": "1", "vcodec": "h264"}]}
        res = self.detector.detect_entry(info)
        self.assertEqual(res.status, AvailabilityStatus.AVAILABLE)
        self.assertFalse(res.is_definitively_inaccessible())

    def test_deleted_or_not_found(self):
        res = self.detector.detect_error("HTTP Error 404: Not Found")
        self.assertEqual(res.status, AvailabilityStatus.DELETED)
        self.assertTrue(res.is_definitively_inaccessible())

    def test_login_required(self):
        res = self.detector.detect_error("This post is private or login required to view")
        self.assertEqual(res.status, AvailabilityStatus.AUTH_REQUIRED)
        self.assertTrue(res.is_definitively_inaccessible())

    def test_rate_limited(self):
        res = self.detector.detect_error("HTTP Error 429: Too Many Requests")
        self.assertEqual(res.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(res.is_definitively_inaccessible())

    def test_no_video_formats(self):
        res = self.detector.detect_error("No video formats found")
        self.assertEqual(res.status, AvailabilityStatus.NO_SUPPORTED_FORMAT)
        self.assertTrue(res.is_definitively_inaccessible())


class TestInstagramMetadataFormatter(unittest.TestCase):
    """Verifies InstagramMetadataFormatter output and strict credential protection."""

    def setUp(self):
        self.formatter = InstagramMetadataFormatter()

    def test_format_metadata_output(self):
        item = VideoItem(
            index=1,
            video_id="Chunk8-jurw",
            title="A mesmerizing view of Earth",
            duration="00:35",
            duration_seconds=35,
            url="https://www.instagram.com/reel/Chunk8-jurw/",
            platform="instagram",
            channel_title="nasa",
            extra_metadata={
                "uploader": "nasa",
                "width": 1080,
                "height": 1920,
            },
        )
        info = {
            "id": "Chunk8-jurw",
            "description": "A mesmerizing view of Earth from the ISS. Captured by @astronaut #Earth #NASA",
            "like_count": 50000,
            "comment_count": 1200,
            "tags": ["Earth", "NASA"],
            "uploader": "nasa",
            "uploader_id": "nasa",
            "width": 1080,
            "height": 1920,
            "vcodec": "h264",
            "acodec": "aac",
        }
        text = self.formatter.format(info, video=item)

        # Check essential headers and metadata
        self.assertIn("Platform:\nInstagram", text)
        self.assertIn("Media ID:\nChunk8-jurw", text)
        self.assertIn("Display Name:\nnasa", text)
        self.assertIn("A mesmerizing view of Earth", text)
        self.assertIn("@astronaut", text)
        self.assertIn("#Earth", text)
        self.assertIn("#NASA", text)
        self.assertIn("50,000", text)

    def test_zero_credential_leakage(self):
        """Verify that sensitive authentication tokens and cookies NEVER appear in metadata output."""
        item = VideoItem(
            index=1,
            video_id="Chunk8-jurw",
            title="Test Post",
            duration="00:15",
            url="https://www.instagram.com/reel/Chunk8-jurw/",
            platform="instagram",
        )
        info = {
            "id": "Chunk8-jurw",
            "sessionid": "SUPER_SECRET_SESSION_TOKEN_12345",
            "ds_user_id": "999888777",
            "cookies": "secret_cookie_data",
            "cookiefile": "C:/sensitive/path/cookies.txt",
        }
        text = self.formatter.format(info, video=item)
        self.assertNotIn("SUPER_SECRET_SESSION_TOKEN_12345", text)
        self.assertNotIn("999888777", text)
        self.assertNotIn("secret_cookie_data", text)
        self.assertNotIn("cookies.txt", text)


class TestInstagramErrorClassifier(unittest.TestCase):
    """Verifies ErrorClassifier integration for Instagram errors."""

    def test_classify_instagram_errors(self):
        err = DownloadError("[instagram] login required to view this post")
        classified = ErrorClassifier.classify(err, platform="instagram")
        self.assertTrue(classified.is_instagram)
        self.assertEqual(classified.category, ErrorCategory.LOGIN_REQUIRED)

        rate_err = DownloadError("[instagram] HTTP Error 429: Too Many Requests from Instagram")
        classified_rate = ErrorClassifier.classify(rate_err, platform="instagram")
        self.assertTrue(classified_rate.is_instagram)
        self.assertEqual(classified_rate.category, ErrorCategory.RATE_LIMITED)


class TestInstagramI18n(unittest.TestCase):
    """Verifies that all Instagram-related UI and error keys exist across en, zh_CN, and zh_TW."""

    def test_i18n_keys_present(self):
        required_keys = [
            "platform_instagram",
            "section_instagram_link",
            "instagram_url_label",
            "instagram_url_placeholder",
            "scan_instagram",
            "dialog_invalid_instagram_url_title",
            "dialog_invalid_instagram_url_msg",
            "empty_subtitle_instagram",
            "tooltip_instagram_no_subs",
            "tooltip_instagram_no_chapters",
            "settings_auth_instagram",
            "auth_instagram_hint",
            "auth_instagram_none_hint",
            "auth_test_instagram_tooltip",
            "status_instagram_session_detected",
            "auth_instagram_privacy_notice",
            "auth_click_test_instagram_hint",
            "auth_dialog_instagram_title",
        ]
        for key in required_keys:
            self.assertIn(key, I18nManager._STRINGS, f"Missing key in _STRINGS: {key}")
            lang_dict = I18nManager._STRINGS[key]
            self.assertIn("en", lang_dict, f"Missing 'en' for key: {key}")
            self.assertIn("zh_CN", lang_dict, f"Missing 'zh_CN' for key: {key}")
            self.assertIn("zh_TW", lang_dict, f"Missing 'zh_TW' for key: {key}")
            self.assertTrue(len(lang_dict["en"].strip()) > 0)
            self.assertTrue(len(lang_dict["zh_CN"].strip()) > 0)
            self.assertTrue(len(lang_dict["zh_TW"].strip()) > 0)


class TestDouyinRemainsFrozen(unittest.TestCase):
    """Verifies that Douyin platform remains frozen and disabled."""

    def test_douyin_is_disabled(self):
        self.assertFalse(PlatformRegistry.is_available("douyin"))
        douyin_adapter = PlatformRegistry.get_adapter("douyin")
        self.assertIsNotNone(douyin_adapter)
        self.assertIsInstance(douyin_adapter, DouyinAdapter)
        self.assertFalse(douyin_adapter.is_available)


class TestCleanInstagramTitle(unittest.TestCase):
    """Verifies clean_instagram_title behaves accurately for Instagram captions, titles, and placeholders."""

    def test_caption_takes_precedence_over_generic_title(self):
        title = clean_instagram_title(
            raw_title="Video by instagram",
            caption="😸Gingerton playing the piano😸\nFollow for more cute cat videos!",
            fallback="Instagram Video 12345",
        )
        self.assertEqual(title, "😸Gingerton playing the piano😸")

    def test_generic_title_with_empty_caption_uses_fallback(self):
        # yt-dlp returns 'Video by instagram' when there is no caption
        title = clean_instagram_title(
            raw_title="Video by instagram",
            caption="",
            fallback="Instagram Video 12345",
        )
        self.assertEqual(title, "Instagram Video 12345")
        self.assertNotIn("Video by instagram", title)

    def test_generic_post_by_with_empty_caption_uses_fallback(self):
        title = clean_instagram_title(
            raw_title="Post by travel_blogger",
            caption="",
            fallback="Instagram Post 999",
        )
        self.assertEqual(title, "Instagram Post 999")

    def test_authentic_raw_title_preserved_when_no_caption(self):
        title = clean_instagram_title(
            raw_title="Authentic Post Headline",
            caption="",
            fallback="Fallback",
        )
        self.assertEqual(title, "Authentic Post Headline")

    def test_long_caption_truncation(self):
        long_caption = "A " * 80  # 160 chars
        title = clean_instagram_title(
            raw_title="Video by instagram",
            caption=long_caption,
            fallback="Fallback",
        )
        self.assertLessEqual(len(title), 120)


class TestInstagramTitleSanitizationAndOutputNaming(unittest.TestCase):
    """Verifies that TitleSanitizerPP synchronizes video output filenames with authentic titles and companion assets."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ch_ig_test_"))

    def tearDown(self):
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_title_sanitizer_replaces_generic_instagram_title_with_target_title(self):
        """Verify TitleSanitizerPP replaces yt-dlp's 'Video by instagram' with VideoItem.title."""
        import yt_dlp
        from downloader.ytdlp_engine import TitleSanitizerPP
        from core.paths import resolve_media_filename, resolve_video_outtmpl

        target_title = "😸Gingerton😸"
        video_id = "Chunk8-jurw"

        info = {
            "id": video_id,
            "title": "Video by instagram",
            "description": "😸Gingerton😸 caption text",
            "extractor_key": "Instagram",
            "ext": "mp4",
        }

        pp = TitleSanitizerPP(
            target_dir=self.temp_dir,
            include_video_id=False,
            target_title=target_title,
            platform="instagram",
        )
        _, cleaned_info = pp.run(info)

        # Downloaded filename title stem in info must match target_title exactly
        self.assertEqual(cleaned_info["title"], target_title)

        # Companion asset filename (thumbnail/metadata) generated with video.title
        sidecar_meta = resolve_media_filename(target_title, video_id, ext="metadata.txt")
        sidecar_thumb = resolve_media_filename(target_title, video_id, ext="jpg")
        media_name = resolve_media_filename(target_title, video_id, ext="mp4")

        self.assertEqual(sidecar_meta, f"{target_title}.metadata.txt")
        self.assertEqual(sidecar_thumb, f"{target_title}.jpg")
        self.assertEqual(media_name, f"{target_title}.mp4")

        # Verify yt-dlp prepare_filename produces identical base name
        opts = {
            "outtmpl": resolve_video_outtmpl(self.temp_dir, include_video_id=False),
            "simulate": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            prepared = ydl.prepare_filename(cleaned_info)
            self.assertEqual(Path(prepared).name, f"{target_title}.mp4")

    def test_title_sanitizer_extracts_caption_when_no_target_title(self):
        """Verify TitleSanitizerPP extracts caption from info['description'] when no target_title is provided."""
        from downloader.ytdlp_engine import TitleSanitizerPP

        info = {
            "id": "BQ0eAlwhDrw",
            "title": "Video by instagram",
            "description": "Summer Roadtrip Adventure\nPart 1 of our roadtrip",
            "extractor_key": "Instagram",
        }

        pp = TitleSanitizerPP(
            target_dir=self.temp_dir,
            include_video_id=False,
            target_title=None,
            platform="instagram",
        )
        _, cleaned_info = pp.run(info)

        self.assertEqual(cleaned_info["title"], "Summer Roadtrip Adventure")
        self.assertNotIn("Video by instagram", cleaned_info["title"])

    def test_title_sanitizer_carousel_item_part_naming(self):
        """Verify Carousel items retain their distinct '(Part N)' titles and do not overwrite each other."""
        from downloader.ytdlp_engine import TitleSanitizerPP
        from core.paths import resolve_media_filename

        parent_caption = "Best moments of our summer trip!"
        item1_title = f"{parent_caption} (Part 1)"
        item2_title = f"{parent_caption} (Part 2)"

        info1 = {
            "id": "ParentPost_1",
            "title": "Post by traveler",
            "description": parent_caption,
            "extractor_key": "Instagram",
        }
        info2 = {
            "id": "ParentPost_2",
            "title": "Post by traveler",
            "description": parent_caption,
            "extractor_key": "Instagram",
        }

        pp1 = TitleSanitizerPP(target_dir=self.temp_dir, target_title=item1_title, platform="instagram")
        pp2 = TitleSanitizerPP(target_dir=self.temp_dir, target_title=item2_title, platform="instagram")

        _, c_info1 = pp1.run(info1)
        _, c_info2 = pp2.run(info2)

        self.assertEqual(c_info1["title"], item1_title)
        self.assertEqual(c_info2["title"], item2_title)

        fn1 = resolve_media_filename(item1_title, "ParentPost_1", ext="mp4")
        fn2 = resolve_media_filename(item2_title, "ParentPost_2", ext="mp4")
        self.assertNotEqual(fn1, fn2)
        self.assertIn("(Part 1)", fn1)
        self.assertIn("(Part 2)", fn2)


if __name__ == "__main__":
    unittest.main()
