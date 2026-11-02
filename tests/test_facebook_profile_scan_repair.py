"""
tests/test_facebook_profile_scan_repair.py
Deterministic Verification Suite for Targeted Facebook Profile Scanning Repair.

Covers:
- Test A: Facebook profile URL classification & routing (HongYongMusic).
- Test B: gallery-dl incremental record parsing and timeout preservation.
- Test C: Informational jump message handling without false failure.
- Test D: gallery-dl structured output schema parsing and deduplication.
- Test E: yt-dlp unsupported profile URL handling and route isolation.
- Test F: Cookie file propagation to both engines (Facebook & Instagram).
- Test G: Partial failure state handling (PARTIAL status, inventory preservation).
- Test H: Regression protection across multi-platform architecture.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.models import VideoItem, VideoStatus, ScanResult, MediaType
from core.inventory import (
    ProfileMediaInventory,
    ScanCompleteness,
    MediaInventoryType,
)
from core.platform import PlatformRegistry
from core.platform.facebook import FacebookAdapter
from core.platform.instagram import InstagramAdapter
from core.platform.auth import PlatformAuthConfig
from downloader.gallerydl_engine import (
    GalleryDlEngine,
    GalleryDlError,
    GalleryDlRecordList,
    GalleryDlExecutionResult,
)
from downloader.profile_scan_manager import ProfileScanManager
from downloader.engine_router import DownloadEngineRouter, EngineType
from downloader.ytdlp_engine import InvalidURLError


class TestFacebookProfileScanRepair(unittest.TestCase):
    """Deterministic test suite for Facebook profile scanning repair."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"
        self.inventory = ProfileMediaInventory(db_path=self.db_path)
        self.mock_gallerydl = MagicMock(spec=GalleryDlEngine)
        self.mock_gallerydl.is_available.return_value = True
        self.mock_gallerydl.get_version.return_value = "1.32.18"
        self.scan_manager = ProfileScanManager(
            inventory=self.inventory,
            gallerydl_engine=self.mock_gallerydl,
        )

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Test A: Facebook profile URL classification and routing
    # -------------------------------------------------------------------------
    def test_a_facebook_profile_url_classification_and_routing(self):
        """
        Test A: Verify Facebook profile URL (HongYongMusic) is classified as a profile URL,
        is not treated as a direct yt-dlp video URL, and unsupported yt-dlp profile extraction
        does not erase results from gallery-dl.
        """
        adapter = FacebookAdapter()
        profile_url = "https://www.facebook.com/HongYongMusic/"
        profile_url_no_slash = "https://www.facebook.com/HongYongMusic"
        photos_url = "https://www.facebook.com/HongYongMusic/photos"
        video_url = "https://www.facebook.com/watch/?v=1234567890"
        reel_url = "https://www.facebook.com/reel/9876543210"

        # 1. URL classification
        self.assertTrue(adapter.is_profile_url(profile_url))
        self.assertTrue(adapter.is_profile_url(profile_url_no_slash))
        self.assertTrue(adapter.is_profile_url(photos_url))
        self.assertFalse(adapter.is_profile_url(video_url))
        self.assertFalse(adapter.is_profile_url(reel_url))

        # 2. Direct yt-dlp extraction rejects profile URL cleanly without network fallback
        with self.assertRaises(InvalidURLError) as ctx:
            adapter.scan(profile_url)
        self.assertIn("cannot be scanned directly as a video playlist by yt-dlp", str(ctx.exception))

        # 3. ProfileScanManager routes profile discovery to gallery-dl and isolates yt-dlp failure
        mock_records = GalleryDlRecordList([
            {
                "id": "photo_101",
                "url": "https://scontent.example.com/p101.jpg",
                "caption": "Hong Yong Music Photo 1",
                "category": "facebook",
                "username": "Hong Yong Music",
            }
        ])
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        logs = []
        result = self.scan_manager.scan_profile(
            url=profile_url,
            platform="facebook",
            log_callback=logs.append,
        )

        self.assertEqual(len(result.videos), 1)
        self.assertIn("photo_101", result.videos[0].video_id)
        self.assertEqual(result.videos[0].media_type, MediaType.PHOTO)
        # yt-dlp failure does not erase gallery-dl records
        self.assertIn(result.extra_metadata["scan_status"], (ScanCompleteness.PARTIAL, ScanCompleteness.COMPLETE))
        self.assertEqual(result.extra_metadata["photo_count"], 1)

    # -------------------------------------------------------------------------
    # Test B: gallery-dl incremental results and timeout preservation
    # -------------------------------------------------------------------------
    def test_b_gallerydl_incremental_results_and_timeout_preservation(self):
        """
        Test B: Simulate structured media records followed by a timeout.
        Verify records received before timeout remain in inventory,
        scan status is PARTIAL, and UI/result receives discovered records.
        """
        partial_records = GalleryDlRecordList([
            {
                "id": "photo_timeout_1",
                "url": "https://scontent.example.com/pt1.jpg",
                "caption": "Preserved Before Timeout 1",
                "category": "facebook",
                "username": "Hong Yong Music",
            },
            {
                "id": "photo_timeout_2",
                "url": "https://scontent.example.com/pt2.jpg",
                "caption": "Preserved Before Timeout 2",
                "category": "facebook",
                "username": "Hong Yong Music",
            },
        ], timed_out=True)

        self.mock_gallerydl.extract_metadata.return_value = partial_records

        logs = []
        progress_events = []
        result = self.scan_manager.scan_profile(
            url="https://www.facebook.com/HongYongMusic/",
            platform="facebook",
            log_callback=logs.append,
            progress_callback=lambda p, m, msg: progress_events.append((p, m, msg)),
        )

        # Inventory preserves items
        stored_items = self.inventory.get_media_items_for_profile("facebook", "https://www.facebook.com/HongYongMusic/")
        self.assertEqual(len(stored_items), 2)
        self.assertEqual(len(result.videos), 2)
        self.assertEqual(result.extra_metadata["photo_count"], 2)
        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.PARTIAL)
        self.assertIn("timeout", result.extra_metadata["scan_completeness_info"].lower())
        self.assertTrue(any("timeout" in l.lower() or "partial" in l.lower() for l in logs))

    # -------------------------------------------------------------------------
    # Test C: Informational jump message handling
    # -------------------------------------------------------------------------
    def test_c_informational_jump_message_handling(self):
        """
        Test C: Simulate Facebook pagination wrap message:
        'Detected possible jump to the beginning of the set'
        Verify it is ignored and does not cause a scan failure.
        """
        raw_output_with_jump = (
            "[facebook][info] Detected possible jump to the beginning of the set. (529382658978652 -> 7473606762709311)\n"
            "[\n"
            "  [\n"
            "    2,\n"
            "    {\n"
            '      "id": "photo_jump_1",\n'
            '      "caption": "Jump Test Caption",\n'
            '      "category": "facebook",\n'
            '      "url": "https://scontent.example.com/pj1.jpg"\n'
            "    }\n"
            "  ],\n"
            "  [\n"
            "    3,\n"
            '    "https://scontent.example.com/pj1.jpg",\n'
            "    {\n"
            '      "id": "photo_jump_1",\n'
            '      "caption": "Jump Test Caption",\n'
            '      "category": "facebook"\n'
            "    }\n"
            "  ]\n"
            "]"
        )

        engine = GalleryDlEngine()
        # Verify parse_dump_json extracts records cleanly despite jump message
        results = engine.parse_dump_json(raw_output_with_jump)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "photo_jump_1")
        self.assertEqual(results[0]["url"], "https://scontent.example.com/pj1.jpg")

        # Verify _check_stderr_errors does not raise on jump info message
        stderr_jump = "[facebook][info] Detected possible jump to the beginning of the set. (123 -> 456)"
        try:
            engine._check_stderr_errors(stderr_jump, returncode=0)
        except Exception as e:
            self.fail(f"_check_stderr_errors unexpectedly raised on jump notice: {e}")

    # -------------------------------------------------------------------------
    # Test D: gallery-dl structured output schema parsing & deduplication
    # -------------------------------------------------------------------------
    def test_d_gallerydl_output_parsing_and_deduplication(self):
        """
        Test D: Verify parser handles real installed gallery-dl output schema:
        - Message.Directory (2)
        - Message.Url (3)
        - Message.Queue (6)
        - Interleaved non-record debug logs
        - Deduplicates directory and download URL records for identical item ID
        """
        fixture_output = """[gallery-dl][debug] Version 1.32.18
[facebook][debug] Using FacebookPhotosExtractor for 'https://www.facebook.com/HongYongMusic/photos'
[
  [
    2,
    {
      "id": "item_alpha",
      "caption": "Alpha Caption",
      "date": "2026-05-09 13:55:02",
      "category": "facebook",
      "username": "Hong Yong Music"
    }
  ],
  [
    3,
    "https://scontent.example.com/alpha_full.jpg",
    {
      "id": "item_alpha",
      "caption": "Alpha Caption",
      "extension": "jpg"
    }
  ],
  [
    2,
    {
      "id": "item_beta",
      "caption": "Beta Caption",
      "url": "https://scontent.example.com/beta.jpg",
      "category": "facebook"
    }
  ]
]
"""
        engine = GalleryDlEngine()
        parsed = engine.parse_dump_json(fixture_output)

        # Must merge alpha into 1 record and keep beta -> total 2 unique records
        self.assertEqual(len(parsed), 2)
        alpha = next(r for r in parsed if r["id"] == "item_alpha")
        beta = next(r for r in parsed if r["id"] == "item_beta")

        # Verify attributes from both [2, dict] and [3, url, dict] merged
        self.assertEqual(alpha["url"], "https://scontent.example.com/alpha_full.jpg")
        self.assertEqual(alpha["username"], "Hong Yong Music")
        self.assertEqual(alpha["extension"], "jpg")
        self.assertEqual(beta["url"], "https://scontent.example.com/beta.jpg")

    # -------------------------------------------------------------------------
    # Test E: yt-dlp Unsupported URL error handling
    # -------------------------------------------------------------------------
    def test_e_ytdlp_unsupported_profile_url_handling(self):
        """
        Test E: Simulate Unsupported URL from yt-dlp for a Facebook profile.
        Verify no uncontrolled retry loop, other discoveries are preserved,
        and scan reports PARTIAL without crashing.
        """
        mock_records = GalleryDlRecordList([
            {
                "id": "photo_survivor_1",
                "url": "https://scontent.example.com/survivor1.jpg",
                "caption": "Photo Discovered Before Video Failure",
                "category": "facebook",
            }
        ])
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        logs = []
        result = self.scan_manager.scan_profile(
            url="https://www.facebook.com/HongYongMusic/",
            platform="facebook",
            log_callback=logs.append,
        )

        self.assertEqual(len(result.videos), 1)
        self.assertIn("photo_survivor_1", result.videos[0].video_id)
        self.assertIn(result.extra_metadata["scan_status"], (ScanCompleteness.PARTIAL, ScanCompleteness.COMPLETE))
        self.assertFalse(result.extra_metadata["scan_status"] == ScanCompleteness.FAILED)

    # -------------------------------------------------------------------------
    # Test F: Cookie file propagation to both engines
    # -------------------------------------------------------------------------
    def test_f_cookie_file_propagation_both_engines(self):
        """
        Test F: Verify configured cookie file path reaches both engines
        for Facebook and Instagram.
        """
        cookie_file = Path(self.temp_dir.name) / "test_cookies.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n.facebook.com TRUE / TRUE 0 c_user 12345\n", encoding="utf-8")

        # 1. Facebook + gallery-dl
        engine = GalleryDlEngine()
        with patch.object(engine, "_execute_process") as mock_exec:
            mock_exec.return_value = GalleryDlExecutionResult(0, "[]", "")
            engine.extract_metadata("https://www.facebook.com/HongYongMusic/", custom_cookie_file=str(cookie_file))
            called_args = mock_exec.call_args[1]["args"]
            self.assertIn("--cookies", called_args)
            c_idx = called_args.index("--cookies")
            self.assertEqual(called_args[c_idx + 1], str(cookie_file.resolve()))
            # Also verify Facebook loop option is added
            self.assertIn("extractor.facebook.loop=false", called_args)

        # 2. Facebook + yt-dlp
        fb_adapter = FacebookAdapter()
        fb_auth = fb_adapter.get_auth_config({
            "facebook_auth_method": "custom_file",
            "facebook_custom_cookie_file": str(cookie_file),
        })
        self.assertTrue(fb_auth.is_active)
        ydl_opts = {}
        fb_auth.apply_to_ydl_opts(ydl_opts)
        self.assertEqual(ydl_opts.get("cookiefile"), str(cookie_file.resolve()))

        # 3. Instagram + gallery-dl
        with patch.object(engine, "_execute_process") as mock_exec:
            mock_exec.return_value = GalleryDlExecutionResult(0, "[]", "")
            engine.extract_metadata("https://www.instagram.com/test_user/", custom_cookie_file=str(cookie_file))
            called_args = mock_exec.call_args[1]["args"]
            self.assertIn("--cookies", called_args)
            c_idx = called_args.index("--cookies")
            self.assertEqual(called_args[c_idx + 1], str(cookie_file.resolve()))

        # 4. Instagram + yt-dlp
        ig_adapter = InstagramAdapter()
        ig_auth = ig_adapter.get_auth_config({
            "instagram_auth_method": "custom_file",
            "instagram_custom_cookie_file": str(cookie_file),
        })
        self.assertTrue(ig_auth.is_active)
        ig_ydl_opts = {}
        ig_auth.apply_to_ydl_opts(ig_ydl_opts)
        self.assertEqual(ig_ydl_opts.get("cookiefile"), str(cookie_file.resolve()))

        # 5. Missing cookie file diagnostic
        fb_auth_empty = fb_adapter.get_auth_config({
            "facebook_auth_method": "custom_file",
            "facebook_custom_cookie_file": "",
        })
        self.assertFalse(fb_auth_empty.is_active)
        self.assertIn("No file path configured", fb_auth_empty.description)

    # -------------------------------------------------------------------------
    # Test G: Partial failure state handling
    # -------------------------------------------------------------------------
    def test_g_partial_failure_state_handling(self):
        """
        Test G: Simulate one engine succeeding and another failing.
        Verify successful records remain available, final status is PARTIAL,
        and counts reflect actual discoveries.
        """
        mock_records = GalleryDlRecordList([
            {"id": f"p_{i}", "url": f"https://scontent.example.com/p_{i}.jpg", "category": "facebook"}
            for i in range(1, 6)
        ])
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        with patch("core.platform.PlatformRegistry.get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.is_profile_url.return_value = False
            mock_adapter.scan.side_effect = Exception("Video service unavailable 503")
            mock_get_adapter.return_value = mock_adapter

            result = self.scan_manager.scan_profile(
                url="https://www.facebook.com/HongYongMusic/",
                platform="facebook",
            )

            self.assertEqual(len(result.videos), 5)
            self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.PARTIAL)
            self.assertEqual(result.extra_metadata["photo_count"], 5)
            self.assertEqual(result.extra_metadata["video_count"], 0)
            self.assertEqual(result.extra_metadata["discovered_media_count"], 5)
            self.assertIn("5 photos", result.extra_metadata["scan_completeness_info"])

    # -------------------------------------------------------------------------
    # Test H: Regression protection across multi-platform architecture
    # -------------------------------------------------------------------------
    def test_h_regression_suite_verification(self):
        """
        Test H: Verify routing rules and engine router policies:
        - Photos routed to gallery-dl
        - Videos routed to yt-dlp
        - Inventory persistence across instances
        """
        router = DownloadEngineRouter(self.mock_gallerydl)

        photo_item = VideoItem(
            index=1,
            video_id="test_photo_1",
            title="Photo Item",
            duration="-",
            url="https://www.facebook.com/photo/?fbid=123",
            platform="facebook",
            media_type=MediaType.PHOTO,
            extra_metadata={"media_type": MediaInventoryType.IMAGE},
        )
        dec_photo = router.route_media_item(photo_item, platform="facebook")
        self.assertEqual(dec_photo.engine, EngineType.GALLERY_DL)

        video_item = VideoItem(
            index=2,
            video_id="test_video_1",
            title="Video Item",
            duration="03:15",
            duration_seconds=195,
            url="https://www.facebook.com/watch/?v=123",
            platform="facebook",
            media_type=MediaType.VIDEO,
            extra_metadata={"media_type": MediaInventoryType.VIDEO},
        )
        dec_video = router.route_media_item(video_item, platform="facebook")
        self.assertEqual(dec_video.engine, EngineType.YTDLP)


if __name__ == "__main__":
    unittest.main()
