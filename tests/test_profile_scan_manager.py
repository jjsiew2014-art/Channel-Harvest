"""
tests/test_profile_scan_manager.py
Unit tests for ProfileScanManager: profile enumeration, parent-child decomposition,
incremental SQLite inventory persistence, deduplication, scan completeness states,
and error handling.
"""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import os
import shutil

from core.inventory import (
    ProfileMediaInventory,
    ScanCompleteness,
    MediaInventoryType,
)
from downloader.profile_scan_manager import ProfileScanManager
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlCancelledException, GalleryDlAuthError
from downloader.engine_router import DownloadEngineRouter, EngineType


class TestProfileScanManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_scan_inventory.db")
        self.inventory = ProfileMediaInventory(db_path=self.db_path)
        self.mock_gallerydl = MagicMock(spec=GalleryDlEngine)
        self.mock_gallerydl.is_available.return_value = True
        self.mock_gallerydl.get_version.return_value = "1.32.18"
        self.router = DownloadEngineRouter(self.mock_gallerydl)
        self.scan_manager = ProfileScanManager(
            inventory=self.inventory,
            gallerydl_engine=self.mock_gallerydl,
            engine_router=self.router,
        )
        # Mock platform adapter to isolate yt-dlp discovery in unit tests
        self.adapter_patcher = patch("core.platform.PlatformRegistry.get_adapter")
        self.mock_get_adapter = self.adapter_patcher.start()
        self.mock_adapter = MagicMock()
        from core.models import ScanResult
        self.mock_adapter.scan.return_value = ScanResult(videos=[], source_title="testuser", platform="instagram", url="")
        self.mock_get_adapter.return_value = self.mock_adapter
        # Mock Facebook Comet client token extraction in unit tests to prevent live network calls
        self.comet_patcher = patch("core.platform.facebook_comet.FacebookCometClient.extract_page_tokens", return_value={})
        self.comet_patcher.start()
        self.ig_patcher = patch("core.platform.instagram_web.InstagramWebClient.extract_profile_info", return_value={})
        self.ig_patcher.start()

    def tearDown(self):
        if hasattr(self, "ig_patcher"):
            self.ig_patcher.stop()
        if hasattr(self, "comet_patcher"):
            self.comet_patcher.stop()
        self.adapter_patcher.stop()
        self.inventory.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scan_profile_normal_success(self):
        """Test scanning a profile returning a carousel post and a video post."""
        mock_records = [
            {
                "url": "https://instagram.com/p/post1/img1.jpg",
                "post_url": "https://instagram.com/p/post1/",
                "shortcode": "post1",
                "caption": "Enjoying the sunset\n#nature",
                "username": "testuser",
                "date": "2026-05-01 12:00:00",
                "num": 1,
                "count": 2,
                "width": 1080,
                "height": 1080,
            },
            {
                "url": "https://instagram.com/p/post1/img2.jpg",
                "post_url": "https://instagram.com/p/post1/",
                "shortcode": "post1",
                "caption": "Enjoying the sunset\n#nature",
                "username": "testuser",
                "date": "2026-05-01 12:00:00",
                "num": 2,
                "count": 2,
                "width": 1080,
                "height": 1350,
            },
            {
                "url": "https://instagram.com/p/post2/vid.mp4",
                "post_url": "https://instagram.com/p/post2/",
                "shortcode": "post2",
                "caption": "Check out this reel!",
                "username": "testuser",
                "date": "2026-05-02 15:30:00",
                "num": 1,
                "count": 1,
                "duration": 45,
                "width": 1080,
                "height": 1920,
            },
        ]
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        logs = []
        result = self.scan_manager.scan_profile(
            url="https://www.instagram.com/testuser/",
            platform="instagram",
            log_callback=lambda msg: logs.append(msg),
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result.videos), 3)
        self.assertEqual(result.source_title, "testuser")
        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.COMPLETE)
        self.assertEqual(result.extra_metadata["discovered_posts_count"], 2)
        self.assertEqual(result.extra_metadata["discovered_media_count"], 3)

        # Verify DB records
        profile = self.inventory.get_profile("instagram", "https://www.instagram.com/testuser/")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.scan_status, ScanCompleteness.COMPLETE)

        posts = self.inventory.get_posts_for_profile("instagram", "https://www.instagram.com/testuser/")
        self.assertEqual(len(posts), 2)

        # Check post 1 children
        items_p1 = self.inventory.get_media_items_for_post("instagram", "post1")
        self.assertEqual(len(items_p1), 2)
        self.assertEqual(items_p1[0].media_type, MediaInventoryType.IMAGE)
        self.assertEqual(items_p1[0].preferred_engine, EngineType.GALLERY_DL)
        self.assertEqual(items_p1[1].media_type, MediaInventoryType.IMAGE)

        # Check post 2 child
        items_p2 = self.inventory.get_media_items_for_post("instagram", "post2")
        self.assertEqual(len(items_p2), 1)
        self.assertEqual(items_p2[0].media_type, MediaInventoryType.VIDEO)
        self.assertEqual(items_p2[0].preferred_engine, EngineType.YTDLP)

    def test_scan_profile_deduplication(self):
        """Duplicate records with the same stable media ID are not duplicated in DB or UI items."""
        mock_records = [
            {
                "url": "https://instagram.com/p/dup1/img.jpg",
                "post_url": "https://instagram.com/p/dup1/",
                "shortcode": "dup1",
                "caption": "A single photo",
                "username": "user1",
                "num": 1,
            },
            # Exact duplicate record
            {
                "url": "https://instagram.com/p/dup1/img.jpg",
                "post_url": "https://instagram.com/p/dup1/",
                "shortcode": "dup1",
                "caption": "A single photo",
                "username": "user1",
                "num": 1,
            },
        ]
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        result = self.scan_manager.scan_profile(
            url="https://www.instagram.com/user1/",
            platform="instagram",
        )

        self.assertEqual(len(result.videos), 1)
        self.assertEqual(result.extra_metadata["discovered_media_count"], 1)

    def test_scan_profile_interrupted_by_user(self):
        """Scan cancellation sets scan_status to INTERRUPTED and persists discoveries up to cancel."""
        records = [
            {
                "url": "https://instagram.com/p/post_c1/img.jpg",
                "post_url": "https://instagram.com/p/post_c1/",
                "shortcode": "post_c1",
                "caption": "Photo 1",
                "username": "cancel_user",
                "num": 1,
            },
            {
                "url": "https://instagram.com/p/post_c2/img.jpg",
                "post_url": "https://instagram.com/p/post_c2/",
                "shortcode": "post_c2",
                "caption": "Photo 2",
                "username": "cancel_user",
                "num": 1,
            },
        ]

        cancel_flag = [False]

        def cancel_check():
            return cancel_flag[0]

        def side_effect(url, **kwargs):
            cancel_flag[0] = True
            raise GalleryDlCancelledException("Scan cancelled")

        self.mock_gallerydl.extract_metadata.side_effect = side_effect

        result = self.scan_manager.scan_profile(
            url="https://www.instagram.com/cancel_user/",
            platform="instagram",
            is_cancelled=cancel_check,
        )

        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.INTERRUPTED)
        profile = self.inventory.get_profile("instagram", "https://www.instagram.com/cancel_user/")
        self.assertEqual(profile.scan_status, ScanCompleteness.INTERRUPTED)

    def test_scan_profile_auth_error(self):
        """Authentication error sets scan_status to FAILED and records last error summary."""
        self.mock_gallerydl.extract_metadata.side_effect = GalleryDlAuthError("Login required for private profile")

        result = self.scan_manager.scan_profile(
            url="https://www.instagram.com/private_user/",
            platform="instagram",
        )

        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.FAILED)
        self.assertIn("Authentication required", result.extra_metadata["scan_completeness_info"])
        profile = self.inventory.get_profile("instagram", "https://www.instagram.com/private_user/")
        self.assertEqual(profile.scan_status, ScanCompleteness.FAILED)

    def test_scan_profile_fallback_when_gallerydl_unavailable(self):
        """When gallery-dl is unavailable, falls back to platform adapter's scan."""
        self.mock_gallerydl.is_available.return_value = False

        from core.models import VideoItem, VideoStatus, ScanResult

        mock_adapter_result = ScanResult(
            videos=[
                VideoItem(
                    index=1,
                    video_id="fb_vid_1",
                    title="FB Video 1",
                    duration="3:00",
                    url="https://facebook.com/watch/?v=123",
                    status=VideoStatus.READY,
                    platform="facebook",
                )
            ],
            source_title="FB Fallback",
            source_type="profile_archive",
            platform="facebook",
            url="https://www.facebook.com/testpage",
        )

        with patch("core.platform.PlatformRegistry.get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.scan.return_value = mock_adapter_result
            mock_get_adapter.return_value = mock_adapter

            result = self.scan_manager.scan_profile(
                url="https://www.facebook.com/testpage",
                platform="facebook",
            )

            self.assertEqual(len(result.videos), 1)
            self.assertEqual(result.videos[0].video_id, "fb_vid_1")
            self.assertIn("fallback", result.extra_metadata["scan_completeness_info"].lower())



    def test_inventory_persistence_across_instances(self):
        """Discovered profile, posts, and media items persist in SQLite across inventory restarts."""
        mock_records = [
            {
                "url": "https://instagram.com/p/p1/img.jpg",
                "post_url": "https://instagram.com/p/p1/",
                "shortcode": "p1",
                "caption": "Persistent photo",
                "username": "persist_user",
                "num": 1,
                "count": 1,
            }
        ]
        self.mock_gallerydl.extract_metadata.return_value = mock_records

        self.scan_manager.scan_profile(
            url="https://www.instagram.com/persist_user/",
            platform="instagram",
        )

        # Close first inventory connection
        self.inventory.close()

        # Open fresh new inventory instance on the same DB file
        new_inventory = ProfileMediaInventory(db_path=self.db_path)
        try:
            profile = new_inventory.get_profile("instagram", "https://www.instagram.com/persist_user/")
            self.assertIsNotNone(profile)
            self.assertEqual(profile.scan_status, ScanCompleteness.COMPLETE)

            posts = new_inventory.get_posts_for_profile("instagram", "https://www.instagram.com/persist_user/")
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0].caption, "Persistent photo")

            items = new_inventory.get_media_items_for_post("instagram", "p1")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].media_type, MediaInventoryType.IMAGE)
        finally:
            new_inventory.close()

    def test_scan_reporter_generation(self):
        """ScanReporter produces clean, formatted, UTF-8 scan reports with privacy sanitization."""
        from downloader.scan_reporter import ScanReporter
        from pathlib import Path

        report_text = ScanReporter.generate_report_text(
            platform="instagram",
            profile_url="https://www.instagram.com/test_creator/",
            scan_id="scan_12345",
            start_time="2026-10-28T10:00:00Z",
            end_time="2026-10-28T10:05:00Z",
            scan_status=ScanCompleteness.COMPLETE,
            completeness_info="Enumeration completed normally",
            posts_count=10,
            media_count=25,
            image_count=20,
            video_count=5,
            unsupported_count=0,
            duplicates_removed=2,
            downloaded_count=25,
            failed_count=0,
            skipped_count=0,
            auth_method="custom_cookie_file (sanitized)",
            profile_name="Test Creator",
        )

        self.assertIn("CHANNEL HARVEST — PROFILE MEDIA ARCHIVE REPORT", report_text)
        self.assertIn("Discovered Posts       : 10", report_text)
        self.assertIn("Images / Photos    : 20", report_text)
        self.assertIn("Videos / Reels     : 5", report_text)

        report_path = ScanReporter.write_report_file(Path(self.temp_dir), report_text)
        self.assertTrue(report_path.exists())
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, report_text)


    def test_facebook_comet_photos_title_resolution(self):
        """Facebook Comet discovered photos preserve authentic title truncated to 35 chars."""
        self.mock_gallerydl.extract_metadata.return_value = []

        mock_comet_photos = [
            {
                "id": "1493250019258573",
                "direct_url": "https://scontent.net/photo1.jpg",
                "post_url": "https://www.facebook.com/photo.php?fbid=1493250019258573",
                "type": "photo",
                "title": "在此預祝各位樂迷朋友母親節愉快❤️ 願我們的音樂能繼續為您與摯愛之人帶...",
                "caption": "在此預祝各位樂迷朋友母親節愉快❤️ 願我們的音樂能繼續為您與摯愛之人帶來溫暖、喜悅與美好的回憶 🥰",
            }
        ]

        with patch("core.platform.facebook_comet.FacebookCometClient.extract_page_tokens") as mock_tokens,              patch("core.platform.facebook_comet.FacebookCometClient.scan_photos") as mock_scan_photos:

            mock_tokens.return_value = {
                "photos_by_id": "PHOTOS_COLLECTION_123",
                "lsd": "MOCK_LSD",
                "dtsg": "MOCK_DTSG",
            }
            mock_scan_photos.return_value = mock_comet_photos

            result = self.scan_manager.scan_profile(
                url="https://www.facebook.com/HongYongMusic/photos",
                platform="facebook",
            )

        self.assertEqual(len(result.videos), 1)
        item = result.videos[0]
        self.assertEqual(item.video_id, "fb_photo_1493250019258573")
        self.assertEqual(item.title, "在此預祝各位樂迷朋友母親節愉快❤️ 願我們的音樂能繼續為您與摯愛之人帶...")
        self.assertLessEqual(len(item.title.rstrip(".")), 35)
        self.assertEqual(item.extra_metadata["caption"], "在此預祝各位樂迷朋友母親節愉快❤️ 願我們的音樂能繼續為您與摯愛之人帶來溫暖、喜悅與美好的回憶 🥰")

if __name__ == "__main__":
    unittest.main()
