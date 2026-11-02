import tempfile
import os
"""
test_bilibili_adapter.py
Comprehensive unit tests for the Bilibili platform adapter, including URL detection,
URL validation, capabilities, multi-part (分 P) expansion, source title derivation,
authentication isolation, error classification, and cancellation handling.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.models import VideoItem, VideoStatus, DownloadSettings
from core.platform import (
    PlatformDetector,
    PlatformRegistry,
    PlatformCapabilities,
)
from core.platform.bilibili import BilibiliAdapter
from core.platform.auth import PlatformAuthConfig
from core.error_classifier import ErrorClassifier, ErrorCategory
from downloader.auth_checker import AuthStatusCode, AuthChecker


class TestBilibiliAdapter(unittest.TestCase):
    """Verifies Bilibili platform adapter integration and contract compliance."""

    def setUp(self):
        self.adapter = BilibiliAdapter()

    def test_registration_and_lookup(self):
        """Verify BilibiliAdapter is registered in PlatformRegistry and retrievable."""
        reg_adapter = PlatformRegistry.get_adapter("bilibili")
        self.assertIsNotNone(reg_adapter)
        self.assertEqual(reg_adapter.platform_id, "bilibili")
        self.assertEqual(reg_adapter.display_name, "Bilibili")
        self.assertTrue(PlatformRegistry.is_available("bilibili"))

        # Lookup by URL
        matched = PlatformRegistry.get_adapter_for_url("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertIs(matched, reg_adapter)

        matched_b23 = PlatformRegistry.get_adapter_for_url("https://b23.tv/BV1xx411c7mD")
        self.assertIs(matched_b23, reg_adapter)

    def test_platform_detector(self):
        """Verify PlatformDetector identifies various Bilibili URL formats."""
        test_cases = [
            ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
            ("https://bilibili.com/video/av170001", "bilibili"),
            ("https://m.bilibili.com/video/BV1xx411c7mD?p=2", "bilibili"),
            ("https://space.bilibili.com/393717148", "bilibili"),
            ("https://space.bilibili.com/393717148/video", "bilibili"),
            ("https://www.bilibili.com/medialist/play/ml12345", "bilibili"),
            ("https://b23.tv/BV1xx411c7mD", "bilibili"),
            ("https://b23.tv/abc1234", "bilibili"),
        ]
        for url, expected in test_cases:
            self.assertEqual(PlatformDetector.identify_platform_id(url), expected, f"Failed for {url}")

    def test_capabilities(self):
        """Verify Bilibili platform capabilities matrix."""
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertTrue(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertTrue(caps.supports_chapters)
        self.assertTrue(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_cookie_file)
        self.assertFalse(caps.supports_browser_cookies)
        self.assertEqual(caps.archive_prefix, "bilibili")

    def test_validate_url(self):
        """Verify Bilibili URL validation for supported and invalid formats."""
        valid_urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.bilibili.com/video/BV17x411w7KC?p=2",
            "https://www.bilibili.com/video/av170001",
            "https://space.bilibili.com/12345678",
            "https://space.bilibili.com/12345678/video",
            "https://space.bilibili.com/12345678/favlist?fid=123",
            "https://www.bilibili.com/medialist/play/12345/ml67890",
            "https://b23.tv/BV1xx411c7mD",
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
            "https://www.bilibili.com/invalid/path/123",
            "ftp://www.bilibili.com/video/BV1xx411c7mD",
        ]
        for u in invalid_urls:
            is_valid, _ = self.adapter.validate_url(u)
            self.assertFalse(is_valid, f"Expected {u} to be invalid")

    def test_clean_url_parameters(self):
        """Verify tracking parameters are cleaned while maintaining critical parameters."""
        url_with_tracking = "https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.999.0.0&vd_source=abcdef12345&p=3"
        cleaned = self.adapter.clean_url(url_with_tracking)
        self.assertIn("p=3", cleaned)
        self.assertNotIn("spm_id_from", cleaned)
        self.assertNotIn("vd_source", cleaned)

        # Single video without p
        url_single = "https://www.bilibili.com/video/BV1xx411c7mD?from=search"
        cleaned_single = self.adapter.clean_url(url_single)
        self.assertEqual(cleaned_single, "https://www.bilibili.com/video/BV1xx411c7mD")

    def test_archive_tag_generation(self):
        """Verify archive tags follow established '{archive_prefix} {video_id}' convention."""
        self.assertEqual(self.adapter.generate_archive_tag("BV1xx411c7mD"), "bilibili BV1xx411c7mD")
        self.assertEqual(self.adapter.generate_archive_tag("BV17x411w7KC_p2"), "bilibili BV17x411w7KC_p2")
        item = VideoItem(index=1, video_id="BV1xx411c7mD", title="Test", duration="01:00")
        self.assertEqual(self.adapter.get_archive_tag(item), "bilibili BV1xx411c7mD")

    def test_single_video_extraction(self):
        """Verify normal single-part BV video extraction produces normalized VideoItem."""
        mock_info = {
            "id": "BV1xx411c7mD",
            "title": "Bilibili Test Video",
            "uploader": "Test UP",
            "uploader_id": "123456",
            "duration": 185,
            "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "thumbnail": "https://i0.hdslb.com/bfs/archive/test.jpg",
            "upload_date": "20230501",
            "description": "Video description",
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.bilibili.com/video/BV1xx411c7mD")
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "BV1xx411c7mD")
            self.assertEqual(item.title, "Bilibili Test Video")
            self.assertEqual(item.channel_title, "Test UP")
            self.assertEqual(item.duration, "03:05")
            self.assertEqual(item.platform, "bilibili")
            self.assertEqual(item.url, "https://www.bilibili.com/video/BV1xx411c7mD")

    def test_multipart_video_expansion(self):
        """Verify multi-part video (分 P) is expanded into distinct items with {bvid}_p{page} IDs."""
        mock_playlist_info = {
            "_type": "playlist",
            "id": "BV17x411w7KC",
            "title": "Parent Multi-Part Video",
            "uploader": "Test UP",
            "uploader_id": "99999",
            "entries": [
                {
                    "id": "BV17x411w7KC",
                    "title": "Part One",
                    "duration": 60,
                    "url": "https://www.bilibili.com/video/BV17x411w7KC?p=1",
                    "page": 1,
                    "part": "Part One",
                },
                {
                    "id": "BV17x411w7KC",
                    "title": "Part Two",
                    "duration": 90,
                    "url": "https://www.bilibili.com/video/BV17x411w7KC?p=2",
                    "page": 2,
                    "part": "Part Two",
                },
            ],
        }

        mock_pages = [
            {"page": 1, "part": "Part One", "duration": 60, "cid": 101},
            {"page": 2, "part": "Part Two", "duration": 90, "cid": 102},
        ]

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, \
             patch.object(self.adapter, "_fetch_pagelist", return_value=mock_pages):
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_playlist_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = self.adapter.extract_entries("https://www.bilibili.com/video/BV17x411w7KC")
            self.assertEqual(len(items), 2)

            self.assertEqual(items[0].video_id, "BV17x411w7KC_p1")
            self.assertEqual(items[0].url, "https://www.bilibili.com/video/BV17x411w7KC?p=1")
            self.assertEqual(items[0].platform, "bilibili")
            self.assertIn("p01 Part One", items[0].title)

            self.assertEqual(items[1].video_id, "BV17x411w7KC_p2")
            self.assertEqual(items[1].url, "https://www.bilibili.com/video/BV17x411w7KC?p=2")
            self.assertEqual(items[1].platform, "bilibili")
            self.assertIn("p02 Part Two", items[1].title)

    def test_source_title_derivation(self):
        """Verify source title is derived correctly for UP space, collections, and single videos."""
        # Creator UP Space
        mock_space = {
            "_type": "playlist",
            "uploader": "Lao Ba UP",
            "title": "Lao Ba UP 的视频空间",
            "entries": [
                {"id": "BV1xx411c7mD", "title": "Clip 1", "duration": 10}
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_space
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            source_title = self.adapter.get_source_title("https://space.bilibili.com/12345")
            self.assertEqual(source_title, "Lao Ba UP")

        # Single Video
        mock_video = {
            "title": "Sample Standalone Video",
            "uploader": "Sample UP",
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_video
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            source_title = self.adapter.get_source_title("https://www.bilibili.com/video/BV1xx411c7mD")
            self.assertEqual(source_title, "Sample Standalone Video")

    def test_auth_isolation(self):
        """Verify Bilibili requests never leak YouTube/TikTok authentication settings."""
        # 1. Unauthenticated request
        unauth_config = PlatformAuthConfig(auth_method="none")
        ydl_opts = self.adapter.build_ydl_options(unauth_config)
        self.assertNotIn("cookiefile", ydl_opts)
        self.assertNotIn("cookiesfrombrowser", ydl_opts)

        # 2. Authenticated request with custom cookie file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tval\n")
            temp_path = tf.name

        try:
            auth_config = PlatformAuthConfig(
                auth_method="custom_file",
                cookie_file=temp_path,
            )
            ydl_opts_auth = self.adapter.build_ydl_options(auth_config)
            self.assertEqual(ydl_opts_auth.get("cookiefile"), str(Path(temp_path).resolve()))
            self.assertNotIn("cookiesfrombrowser", ydl_opts_auth)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 3. Ensure Bilibili never accepts browser cookies config
        browser_config = PlatformAuthConfig(
            auth_method="browser",
            browser_name="chrome",
            cookie_file="",
        )
        ydl_opts_browser = self.adapter.build_ydl_options(browser_config)
        self.assertNotIn("cookiesfrombrowser", ydl_opts_browser)

    def test_cancellation_during_extraction(self):
        """Verify extract_entries halts when is_cancelled returns True."""
        mock_playlist_info = {
            "_type": "playlist",
            "id": "space_123",
            "entries": [
                {"id": f"BV1{i}", "title": f"Video {i}", "duration": 100}
                for i in range(10)
            ],
        }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_playlist_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            cancelled_flag = [False]
            def check_cancelled():
                return cancelled_flag[0]

            def on_progress(count, total):
                if count >= 3:
                    cancelled_flag[0] = True

            items = self.adapter.extract_entries(
                "https://space.bilibili.com/123",
                is_cancelled=check_cancelled,
                progress_callback=on_progress,
            )
            # Should have halted early without processing all 10 items
            self.assertLess(len(items), 10)

    def test_error_classification_bilibili_412(self):
        """Verify Bilibili HTTP 412 WAF rate limiting is classified as RATE_LIMITED."""
        err_msg = "HTTP Error 412: Precondition Failed. bilibili API access restricted"
        classified = ErrorClassifier.classify(err_msg, platform="bilibili")
        self.assertEqual(classified.category, ErrorCategory.RATE_LIMITED)
        self.assertTrue(classified.is_bilibili)
        # Verify localized guidance suggests cookie file or waiting
        action_text = classified.get_localized_suggested_action()
        self.assertIn("cookie", action_text.lower())
        zh_user_msg = classified.get_localized_user_message("zh_CN")
        self.assertIn("Cookie", zh_user_msg)

    def test_error_classification_deleted_bvid(self):
        """Verify deleted or non-existent BV video is classified as VIDEO_UNAVAILABLE."""
        err_msg = "KeyError: 'bvid' This video may be deleted or geo-restricted"
        classified = ErrorClassifier.classify(err_msg, platform="bilibili")
        self.assertEqual(classified.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertTrue(classified.is_bilibili)

    def test_get_auth_config_with_settings_manager_duck_typing(self):
        """Verify get_auth_config retrieves custom cookie file via SettingsManager (.get())."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\ttest_val\n")
            temp_path = tf.name

        try:
            # Mock SettingsManager with .get(key, default)
            mock_sm = MagicMock()
            mock_sm.get.side_effect = lambda key, default=None: {
                "bilibili_auth_method": "custom_file",
                "bilibili_custom_cookie_file": temp_path,
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
        """Verify get_auth_config reports accurate descriptive status when file is missing."""
        # Case A: No file path configured
        mock_sm_empty = MagicMock()
        mock_sm_empty.get.side_effect = lambda key, default=None: {
            "bilibili_auth_method": "custom_file",
            "bilibili_custom_cookie_file": "",
        }.get(key, default)
        cfg_empty = self.adapter.get_auth_config(mock_sm_empty)
        self.assertFalse(cfg_empty.is_active)
        self.assertIn("No file path configured", cfg_empty.description)

        # Case B: File path configured but file does not exist on disk
        non_existent = r"C:\fake_dir\non_existent_cookies.txt"
        mock_sm_missing = MagicMock()
        mock_sm_missing.get.side_effect = lambda key, default=None: {
            "bilibili_auth_method": "custom_file",
            "bilibili_custom_cookie_file": non_existent,
        }.get(key, default)
        cfg_missing = self.adapter.get_auth_config(mock_sm_missing)
        self.assertFalse(cfg_missing.is_active)
        self.assertIn("File not found on disk", cfg_missing.description)

    def test_get_auth_config_dataclass_and_dict(self):
        """Verify get_auth_config supports DownloadSettings dataclass and plain dictionary."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n")
            temp_path = tf.name

        try:
            # Dataclass with attributes
            ds = DownloadSettings(
                bilibili_auth_method="custom_file",
                bilibili_custom_cookie_file=temp_path,
            )
            cfg_ds = self.adapter.get_auth_config(ds)
            self.assertEqual(cfg_ds.auth_method, "custom_file")
            self.assertTrue(cfg_ds.is_active)

            # Dictionary
            d = {
                "bilibili_auth_method": "custom_file",
                "bilibili_custom_cookie_file": temp_path,
            }
            cfg_d = self.adapter.get_auth_config(d)
            self.assertEqual(cfg_d.auth_method, "custom_file")
            self.assertTrue(cfg_d.is_active)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_error_classification_bilibili_352_risk_control(self):
        """Verify Bilibili Error 352 is classified as BILIBILI_API_BLOCKED and NOT COOKIE_FILE_INVALID."""
        err_msg = "ERROR: [BilibiliSpaceVideo] 3747562502752849: Request is rejected by server (352)"
        classified = ErrorClassifier.classify(err_msg, stage="scan")

        self.assertEqual(classified.category, ErrorCategory.BILIBILI_API_BLOCKED)
        self.assertNotEqual(classified.category, ErrorCategory.COOKIE_FILE_INVALID)
        self.assertEqual(classified.platform, "bilibili")
        self.assertTrue(classified.is_bilibili)
        self.assertTrue(classified.retryable)

        # English
        self.assertIn("Error 352", classified.title)
        self.assertIn("risk-control", classified.user_message)
        self.assertIn("cookie file", classified.suggested_action.lower())

        # Traditional Chinese (zh_TW)
        self.assertIn("352", classified.get_localized_title("zh_TW"))
        self.assertIn("352", classified.get_localized_user_message("zh_TW"))
        self.assertIn("Cookie", classified.get_localized_suggested_action("zh_TW"))

        # Simplified Chinese (zh_CN)
        self.assertIn("352", classified.get_localized_title("zh_CN"))
        self.assertIn("352", classified.get_localized_user_message("zh_CN"))
        self.assertIn("Cookie", classified.get_localized_suggested_action("zh_CN"))

    def test_scan_error_352_raises_actionable_error(self):
        """Verify scan() raises descriptive ExtractionError when yt-dlp receives Error 352."""
        from yt_dlp.utils import DownloadError as YtDlpDownloadError
        from downloader.ytdlp_engine import ExtractionError

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = YtDlpDownloadError("ERROR: [BilibiliSpaceVideo] 3747562502752849: Request is rejected by server (352)")
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(ExtractionError) as ctx:
                self.adapter.scan("https://space.bilibili.com/3747562502752849")
            self.assertIn("352", str(ctx.exception))
            self.assertIn("Cookie", str(ctx.exception))

    def test_scan_creator_propagates_cookie_file_to_ytdlp(self):
        """Verify scan() passes cookiefile option to YoutubeDL when cookie auth is configured."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tval\n")
            temp_path = tf.name

        try:
            auth_config = PlatformAuthConfig(
                auth_method="custom_file",
                cookie_file=temp_path,
                description="Custom Cookie File",
            )
            mock_info = {
                "_type": "playlist",
                "id": "3747562502752849",
                "title": "Creator Space",
                "uploader": "Test Creator",
                "entries": [
                    {"id": "BV1xx411c7mD", "title": "Video 1", "duration": 100}
                ],
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
                    "https://space.bilibili.com/3747562502752849",
                    auth_config=auth_config,
                )
                self.assertEqual(len(result.videos), 1)
                self.assertIn("cookiefile", captured_opts)
                self.assertEqual(captured_opts["cookiefile"], str(Path(temp_path).resolve()))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestBilibiliTitleMapping(unittest.TestCase):
    """
    Exhaustive tests for Bilibili title preservation, fallback priority,
    Unicode/CJK character support, and multi-platform isolation.
    """

    def setUp(self):
        self.adapter = BilibiliAdapter()

    def test_single_video_preserves_exact_title(self):
        """1. A Bilibili video extraction result with a valid title displays that exact title."""
        expected_title = "【4K60FPS】经典老歌精选 2026 Remastered (Official MV)"
        mock_info = {
            "id": "BV1xx411c7mD",
            "title": expected_title,
            "uploader": "音乐UP主",
            "duration": 215,
            "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.bilibili.com/video/BV1xx411c7mD")
            self.assertEqual(len(res.videos), 1)
            item = res.videos[0]
            self.assertEqual(item.title, expected_title)
            self.assertEqual(item.video_id, "BV1xx411c7mD")
            self.assertNotEqual(item.title, f"Bilibili Video {item.video_id}")

    def test_creator_submission_list_preserves_each_entry_title(self):
        """2. A creator submission list preserves each entry's actual title."""
        mock_space_info = {
            "_type": "playlist",
            "id": "3747562502752849",
            "title": "Bilibili",
            "entries": [
                {
                    "id": "BV1d6pX6NELn",
                    "title": "Guantanamera (Official Music)",
                    "duration": 217,
                    "uploader": "名将经典音乐",
                },
                {
                    "id": "BV1d6pX6KEDd",
                    "title": "Banana Boat (Official Music)",
                    "duration": 212,
                    "uploader": "名将经典音乐",
                },
                {
                    "id": "BV1R6pX6NEzP",
                    "title": "Summer Kisses Winter Tears (Official Music)",
                    "duration": 262,
                    "uploader": "名将经典音乐",
                },
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_space_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://space.bilibili.com/3747562502752849")
            self.assertEqual(len(res.videos), 3)
            self.assertEqual(res.source_title, "名将经典音乐")
            self.assertEqual(res.videos[0].title, "Guantanamera (Official Music)")
            self.assertEqual(res.videos[1].title, "Banana Boat (Official Music)")
            self.assertEqual(res.videos[2].title, "Summer Kisses Winter Tears (Official Music)")
            # Verify video IDs are preserved
            self.assertEqual(res.videos[0].video_id, "BV1d6pX6NELn")
            self.assertEqual(res.videos[1].video_id, "BV1d6pX6KEDd")
            self.assertEqual(res.videos[2].video_id, "BV1R6pX6NEzP")

    def test_playlist_preserves_distinct_entry_titles(self):
        """3. A playlist preserves the title of every individual entry without copying parent title."""
        mock_playlist_info = {
            "_type": "playlist",
            "id": "ml12345",
            "title": "Collection Parent Title",
            "entries": [
                {"id": "BV1entry1", "title": "Track 01: Overture", "duration": 150},
                {"id": "BV1entry2", "title": "Track 02: Symphony", "duration": 320},
                {"id": "BV1entry3", "title": "Track 03: Finale", "duration": 280},
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_playlist_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.bilibili.com/medialist/play/ml12345")
            self.assertEqual(len(res.videos), 3)
            self.assertEqual(res.videos[0].title, "Track 01: Overture")
            self.assertEqual(res.videos[1].title, "Track 02: Symphony")
            self.assertEqual(res.videos[2].title, "Track 03: Finale")

    def test_multipart_preserves_part_titles(self):
        """4. Multi-part videos preserve appropriate part titles following naming conventions."""
        mock_parent = {
            "id": "BV1multipart",
            "title": "Python 从入门到精通",
            "uploader": "技术讲师",
            "entries": [],
        }
        mock_pages = [
            {"page": 1, "part": "第1课：环境安装与配置", "duration": 600, "cid": 1001},
            {"page": 2, "part": "第2课：基础语法与变量", "duration": 900, "cid": 1002},
        ]
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, \
             patch.object(self.adapter, "_fetch_pagelist", return_value=mock_pages):
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_parent
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.bilibili.com/video/BV1multipart")
            self.assertEqual(len(res.videos), 2)
            self.assertEqual(res.videos[0].title, "Python 从入门到精通 p01 第1课：环境安装与配置")
            self.assertEqual(res.videos[0].video_id, "BV1multipart_p1")
            self.assertEqual(res.videos[1].title, "Python 从入门到精通 p02 第2课：基础语法与变量")
            self.assertEqual(res.videos[1].video_id, "BV1multipart_p2")

    def test_fallback_priority_hierarchy(self):
        """5 & 6. Validates title resolution priority hierarchy and ensures fallback never overwrites valid title."""
        # Priority 1: Valid title
        e1 = {"title": "Real Video Title", "name": "Secondary Name", "id": "BV1abc"}
        self.assertEqual(self.adapter._resolve_entry_title(e1, "BV1abc"), "Real Video Title")

        # Priority 2: Secondary field ('name') when primary ('title') is missing/empty
        e2 = {"title": "   ", "name": "Secondary Video Name", "id": "BV1def"}
        self.assertEqual(self.adapter._resolve_entry_title(e2, "BV1def"), "Secondary Video Name")

        # Priority 3: Fallback when all title fields are missing or empty
        e3 = {"title": "", "name": None, "id": "BV1empty"}
        self.assertEqual(self.adapter._resolve_entry_title(e3, "BV1empty"), "Bilibili Video BV1empty")

        # Fallback with no ID provided
        e4 = {"title": None}
        self.assertEqual(self.adapter._resolve_entry_title(e4, "", index=7), "Bilibili Video #7")

        # Never returns None or empty
        self.assertTrue(bool(self.adapter._resolve_entry_title({}, "BV1xyz")))
        self.assertTrue(bool(self.adapter._resolve_entry_title(None, "")))

    def test_original_video_id_and_archive_tag_preserved(self):
        """7. The original BV identifier remains available internally for download and deduplication."""
        mock_info = {
            "id": "BV1target99",
            "title": "Some Display Title",
            "uploader": "Creator",
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            res = self.adapter.scan("https://www.bilibili.com/video/BV1target99")
            v = res.videos[0]
            self.assertEqual(v.video_id, "BV1target99")
            self.assertEqual(v.title, "Some Display Title")
            # Archive tag must be stable based on video_id, NOT displayed title
            self.assertEqual(self.adapter.get_archive_tag(v), "bilibili BV1target99")

    def test_cjk_unicode_and_html_entities(self):
        """8. Titles containing Chinese characters, punctuation, spaces, and HTML entities display correctly."""
        raw_title = "【官方MV】Saxy &amp; Lovers &lt;特别篇&gt;：你好，世界！"
        expected = "【官方MV】Saxy & Lovers <特别篇>：你好，世界！"
        res = self.adapter._resolve_entry_title({"title": raw_title}, "BV1cjk")
        self.assertEqual(res, expected)

    def test_youtube_tiktok_adapters_unaffected(self):
        """9. Existing YouTube and TikTok platform adapters remain unaffected."""
        from core.platform.youtube import YouTubeAdapter
        from core.platform.tiktok import TikTokAdapter

        yt = YouTubeAdapter()
        tt = TikTokAdapter()
        self.assertEqual(yt.platform_id, "youtube")
        self.assertEqual(tt.platform_id, "tiktok")
        self.assertTrue(yt.capabilities.supports_channel_scan)
        self.assertTrue(tt.capabilities.supports_channel_scan)

    def test_table_widget_renders_real_title(self):
        """10. Table widget renders video.title directly in COL_TITLE without altering table structure."""
        from core.models import VideoItem, VideoStatus

        v = VideoItem(
            index=1,
            video_id="BV1d6pX6NELn",
            title="Guantanamera (Official Music)",
            duration="03:37",
            status=VideoStatus.READY,
            url="https://www.bilibili.com/video/BV1d6pX6NELn",
            channel_title="名将经典音乐",
            platform="bilibili",
            selected=True,
        )
        self.assertEqual(v.title, "Guantanamera (Official Music)")
        self.assertEqual(v.video_id, "BV1d6pX6NELn")
        self.assertTrue(v.selected)


if __name__ == "__main__":
    unittest.main()
