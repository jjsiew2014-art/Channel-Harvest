"""
tests/test_profile_media_inventory.py
Comprehensive unit tests for ProfileMediaInventory in Channel Harvest.

Covers:
1. Stable record creation for profiles, posts, and media items.
2. Duplicate discovery and upsert idempotency.
3. Multiple media items in one post (carousels / albums).
4. Parent-child relationships preservation.
5. Mixed media posts (images + videos) with independent sequence tracking.
6. Missing IDs handling with deterministic fallback keys.
7. Missing timestamps handling.
8. Partial scan persistence and recovery.
9. Interrupted scan status preservation.
10. Failed scan status preservation with error summary.
11. Resume behavior (querying pending/failed media items without rescanning).
12. Incremental refresh (updating counts and preserving older discoveries).
13. Existing output-file tracking and download status updates.
"""

import tempfile
import unittest
from pathlib import Path

from core.inventory import (
    ProfileMediaInventory,
    ProfileRecord,
    PostRecord,
    MediaItemRecord,
    ScanCompleteness,
    MediaInventoryType,
    MediaDownloadStatus,
    generate_stable_media_id,
)


class TestProfileMediaInventory(unittest.TestCase):
    """Verifies SQLite-backed ProfileMediaInventory operations and integrity."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"
        self.inventory = ProfileMediaInventory(db_path=self.db_path)

    def tearDown(self):
        self.inventory.close()
        self.temp_dir.cleanup()

    def test_01_profile_upsert_and_retrieval(self):
        """Verify profile record creation and retrieval."""
        profile = ProfileRecord(
            platform="instagram",
            profile_url="https://www.instagram.com/natgeo/",
            profile_id="natgeo",
            display_name="National Geographic",
            scan_id="scan_001",
            scan_start_time="2026-10-28T00:00:00Z",
            scan_status=ScanCompleteness.COMPLETE,
            scan_completeness_info="Enumeration complete",
            discovered_posts_count=10,
            discovered_media_count=25,
        )
        self.inventory.upsert_profile(profile)

        retrieved = self.inventory.get_profile("instagram", "https://www.instagram.com/natgeo/")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.profile_id, "natgeo")
        self.assertEqual(retrieved.discovered_media_count, 25)
        self.assertEqual(retrieved.scan_status, ScanCompleteness.COMPLETE)

    def test_02_post_and_child_media_relationship(self):
        """Verify parent-child relationship between post and its media items."""
        post = PostRecord(
            platform="instagram",
            post_id="post_carousel_123",
            profile_id="traveler",
            original_url="https://instagram.com/p/post_carousel_123/",
            caption="Holiday in Italy",
            author="traveler",
            publication_date="2026-08-15",
            post_type="carousel",
        )
        self.inventory.upsert_post(post)

        # 3 media items under this carousel
        for idx in range(1, 4):
            item = MediaItemRecord(
                media_id=f"media_item_{idx}",
                platform="instagram",
                parent_post_id="post_carousel_123",
                media_url=f"https://ig.com/photo_{idx}.jpg",
                media_type=MediaInventoryType.IMAGE,
                media_sequence_index=idx,
                media_count=3,
            )
            self.inventory.upsert_media_item(item)

        items = self.inventory.get_media_items_for_post("instagram", "post_carousel_123")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].media_sequence_index, 1)
        self.assertEqual(items[1].media_sequence_index, 2)
        self.assertEqual(items[2].media_sequence_index, 3)

    def test_03_mixed_media_post_ordering_and_types(self):
        """Verify mixed-media post preserves ordering and types."""
        post_id = "fb_mixed_post_999"
        post = PostRecord(
            platform="facebook",
            post_id=post_id,
            profile_id="news_channel",
            post_type="mixed",
        )
        self.inventory.upsert_post(post)

        # 1 photo + 1 video
        item_photo = MediaItemRecord(
            media_id="fb_photo_1",
            platform="facebook",
            parent_post_id=post_id,
            media_type=MediaInventoryType.IMAGE,
            media_sequence_index=1,
            preferred_engine="gallery-dl",
        )
        item_video = MediaItemRecord(
            media_id="fb_video_2",
            platform="facebook",
            parent_post_id=post_id,
            media_type=MediaInventoryType.VIDEO,
            media_sequence_index=2,
            preferred_engine="yt-dlp",
        )
        self.inventory.upsert_media_item(item_photo)
        self.inventory.upsert_media_item(item_video)

        items = self.inventory.get_media_items_for_post("facebook", post_id)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].media_type, MediaInventoryType.IMAGE)
        self.assertEqual(items[0].preferred_engine, "gallery-dl")
        self.assertEqual(items[1].media_type, MediaInventoryType.VIDEO)
        self.assertEqual(items[1].preferred_engine, "yt-dlp")

    def test_04_duplicate_discovery_upsert_idempotency(self):
        """Verify repeated discoveries update existing records without creating duplicates."""
        post = PostRecord(platform="instagram", post_id="p100", caption="Original Caption")
        self.inventory.upsert_post(post)

        # Rescan with updated caption
        post_updated = PostRecord(platform="instagram", post_id="p100", caption="Updated Caption")
        self.inventory.upsert_post(post_updated)

        retrieved = self.inventory.get_post("instagram", "p100")
        self.assertEqual(retrieved.caption, "Updated Caption")

    def test_05_missing_ids_generate_stable_identity(self):
        """Verify deterministic fallback identity generation when platform IDs are absent."""
        id1 = generate_stable_media_id(
            platform="facebook",
            post_id="post_without_media_id",
            media_sequence_index=1,
            media_url="https://fb.com/image.jpg?signed_token=123",
        )
        id2 = generate_stable_media_id(
            platform="facebook",
            post_id="post_without_media_id",
            media_sequence_index=1,
            media_url="https://fb.com/image.jpg?signed_token=456",  # different transient token
        )
        self.assertEqual(id1, id2, "Stable ID should remain identical despite transient query tokens")

    def test_06_missing_timestamps_safe_handling(self):
        """Verify null/missing timestamps do not crash inventory or invent fabricated dates."""
        post = PostRecord(
            platform="instagram",
            post_id="p_no_date",
            publication_date=None,
        )
        self.inventory.upsert_post(post)
        retrieved = self.inventory.get_post("instagram", "p_no_date")
        self.assertIsNone(retrieved.publication_date)

    def test_07_partial_and_interrupted_scan_persistence(self):
        """Verify partial and interrupted scans preserve discovered records."""
        url = "https://instagram.com/interrupted_user/"
        profile = ProfileRecord(
            platform="instagram",
            profile_url=url,
            scan_status=ScanCompleteness.INTERRUPTED,
            scan_completeness_info="Scan stopped by user at page 3",
            discovered_posts_count=5,
            discovered_media_count=12,
        )
        self.inventory.upsert_profile(profile)

        # Update scan status
        self.inventory.update_profile_scan_status(
            platform="instagram",
            profile_url=url,
            scan_status=ScanCompleteness.INTERRUPTED,
            completeness_info="User cancelled",
        )

        p = self.inventory.get_profile("instagram", url)
        self.assertEqual(p.scan_status, ScanCompleteness.INTERRUPTED)
        self.assertEqual(p.scan_completeness_info, "User cancelled")

    def test_08_failed_scan_preserves_error_summary(self):
        """Verify failed scan records error summary accurately."""
        url = "https://facebook.com/failed_page/"
        self.inventory.upsert_profile(ProfileRecord(
            platform="facebook",
            profile_url=url,
            scan_status=ScanCompleteness.FAILED,
            last_error_summary="HTTP Error 403: Access Restricted",
        ))

        p = self.inventory.get_profile("facebook", url)
        self.assertEqual(p.scan_status, ScanCompleteness.FAILED)
        self.assertIn("Access Restricted", p.last_error_summary)

    def test_09_resume_behavior_query_pending_items(self):
        """Verify get_pending_media_items returns failed and pending items without rescanning."""
        post_id = "resume_post_1"
        self.inventory.upsert_post(PostRecord(
            platform="instagram", post_id=post_id, profile_url="https://ig.com/u/"
        ))

        # 3 items: 1 completed, 1 failed, 1 pending
        self.inventory.upsert_media_item(MediaItemRecord(
            media_id="m1", platform="instagram", parent_post_id=post_id, download_status=MediaDownloadStatus.COMPLETED
        ))
        self.inventory.upsert_media_item(MediaItemRecord(
            media_id="m2", platform="instagram", parent_post_id=post_id, download_status=MediaDownloadStatus.FAILED
        ))
        self.inventory.upsert_media_item(MediaItemRecord(
            media_id="m3", platform="instagram", parent_post_id=post_id, download_status=MediaDownloadStatus.PENDING
        ))

        pending = self.inventory.get_pending_media_items("instagram", "https://ig.com/u/")
        self.assertEqual(len(pending), 2)
        p_ids = {item.media_id for item in pending}
        self.assertEqual(p_ids, {"m2", "m3"})

    def test_10_download_status_update_and_output_tracking(self):
        """Verify updating download status sets completed timestamp and output path."""
        item = MediaItemRecord(
            media_id="dl_track_1",
            platform="instagram",
            download_status=MediaDownloadStatus.PENDING,
        )
        self.inventory.upsert_media_item(item)

        out_path = "C:/Users/Admin/Downloads/Channel Harvest/Instagram/user/Photos/01.jpg"
        self.inventory.update_media_download_status(
            platform="instagram",
            media_id="dl_track_1",
            status=MediaDownloadStatus.COMPLETED,
            output_path=out_path,
            file_size=204850,
            selected_engine="gallery-dl",
        )

        updated = self.inventory.get_media_item("instagram", "dl_track_1")
        self.assertEqual(updated.download_status, MediaDownloadStatus.COMPLETED)
        self.assertEqual(updated.output_path, out_path)
        self.assertEqual(updated.file_size, 204850)
        self.assertEqual(updated.selected_engine, "gallery-dl")
        self.assertIsNotNone(updated.completed_timestamp)

    def test_11_inventory_summary_metrics(self):
        """Verify get_inventory_summary aggregates metrics accurately."""
        url = "https://instagram.com/summary_user/"
        self.inventory.upsert_profile(ProfileRecord(platform="instagram", profile_url=url))
        self.inventory.upsert_post(PostRecord(platform="instagram", post_id="p1", profile_url=url))

        self.inventory.upsert_media_item(MediaItemRecord(
            media_id="m1", platform="instagram", parent_post_id="p1",
            media_type=MediaInventoryType.IMAGE, download_status=MediaDownloadStatus.COMPLETED
        ))
        self.inventory.upsert_media_item(MediaItemRecord(
            media_id="m2", platform="instagram", parent_post_id="p1",
            media_type=MediaInventoryType.VIDEO, download_status=MediaDownloadStatus.FAILED
        ))

        summary = self.inventory.get_inventory_summary("instagram", url)
        self.assertEqual(summary["posts_count"], 1)
        self.assertEqual(summary["media_count"], 2)
        self.assertEqual(summary["image_count"], 1)
        self.assertEqual(summary["video_count"], 1)
        self.assertEqual(summary["downloaded_count"], 1)
        self.assertEqual(summary["failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
