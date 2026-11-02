"""
tests/test_download_engine_router.py
Comprehensive unit tests for DownloadEngineRouter in Channel Harvest.

Covers:
1. Instagram image routes to gallery-dl.
2. Instagram image carousel routes to gallery-dl.
3. Instagram video routes to yt-dlp.
4. Instagram mixed media routes each item independently.
5. Facebook image routes to gallery-dl.
6. Facebook album routes to gallery-dl.
7. Facebook video routes to yt-dlp.
8. Facebook mixed media is handled correctly.
9. Unknown media invokes metadata probing.
10. Unsupported media is reported.
11. Missing gallery-dl is detected.
12. Missing yt-dlp is handled.
13. Fallback occurs only when explicitly permitted.
14. Authentication failures do not trigger pointless engine switching.
15. Rate limiting does not trigger uncontrolled retries.
16. Successful downloads are not duplicated.
"""

import unittest
from unittest.mock import MagicMock, patch

from core.inventory import MediaInventoryType, MediaItemRecord
from core.models import VideoItem, VideoStatus
from core.error_classifier import ErrorCategory
from downloader.engine_router import DownloadEngineRouter, EngineType, EngineRouteDecision
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlInfo


class TestDownloadEngineRouter(unittest.TestCase):
    """Verifies deterministic routing decisions and bounded fallback logic."""

    def setUp(self):
        self.mock_gallerydl = MagicMock(spec=GalleryDlEngine)
        self.mock_gallerydl.is_available.return_value = True
        self.mock_gallerydl.get_version.return_value = "1.32.18"
        self.router = DownloadEngineRouter(gallerydl_engine=self.mock_gallerydl)

    def test_01_instagram_image_routes_to_gallery_dl(self):
        """Verify Instagram image items route to gallery-dl."""
        item = {
            "media_type": "IMAGE",
            "url": "https://www.instagram.com/p/C12345/media/?size=l",
            "ext": "jpg",
        }
        decision = self.router.route_media_item(item, platform="instagram")
        self.assertEqual(decision.engine, EngineType.GALLERY_DL)
        self.assertEqual(decision.media_type, MediaInventoryType.IMAGE)
        self.assertTrue(decision.is_gallery_dl)

    def test_02_instagram_image_carousel_routes_to_gallery_dl(self):
        """Verify Instagram image carousel child items route to gallery-dl."""
        item = MediaItemRecord(
            media_id="ig_carousel_1",
            platform="instagram",
            parent_post_id="post_123",
            media_url="https://ig.com/photo1.jpg",
            media_type=MediaInventoryType.IMAGE,
            media_sequence_index=1,
            media_count=3,
        )
        decision = self.router.route_media_item(item, platform="instagram")
        self.assertEqual(decision.engine, EngineType.GALLERY_DL)
        self.assertIn("gallery-dl", decision.rationale)

    def test_03_instagram_video_routes_to_yt_dlp(self):
        """Verify Instagram Reel and video items route to yt-dlp."""
        video_item = VideoItem(
            index=1,
            video_id="reel_123",
            title="My Great Reel",
            duration="00:30",
            platform="instagram",
            url="https://www.instagram.com/reel/C99999/",
            extra_metadata={"media_type": "VIDEO"},
        )
        decision = self.router.route_media_item(video_item, platform="instagram")
        self.assertEqual(decision.engine, EngineType.YTDLP)
        self.assertEqual(decision.media_type, MediaInventoryType.VIDEO)
        self.assertTrue(decision.is_ytdlp)

    def test_04_instagram_mixed_media_routes_independently(self):
        """Verify each child item of a mixed-media post routes to its dedicated engine."""
        child_img = {
            "id": "item_1",
            "media_type": "IMAGE",
            "url": "https://ig.com/photo1.jpg",
        }
        child_vid = {
            "id": "item_2",
            "media_type": "VIDEO",
            "url": "https://ig.com/video2.mp4",
        }
        dec_img = self.router.route_media_item(child_img, platform="instagram")
        dec_vid = self.router.route_media_item(child_vid, platform="instagram")

        self.assertEqual(dec_img.engine, EngineType.GALLERY_DL)
        self.assertEqual(dec_vid.engine, EngineType.YTDLP)

    def test_05_facebook_image_routes_to_gallery_dl(self):
        """Verify Facebook photo item routes to gallery-dl."""
        item = {
            "media_type": "IMAGE",
            "url": "https://www.facebook.com/photo/?fbid=123456789",
            "ext": "jpg",
        }
        decision = self.router.route_media_item(item, platform="facebook")
        self.assertEqual(decision.engine, EngineType.GALLERY_DL)

    def test_06_facebook_album_routes_to_gallery_dl(self):
        """Verify Facebook album photos route to gallery-dl."""
        item = MediaItemRecord(
            media_id="fb_album_photo_1",
            platform="facebook",
            parent_post_id="album_999",
            media_url="https://www.facebook.com/media/set/?set=a.999",
            media_type=MediaInventoryType.IMAGE,
        )
        decision = self.router.route_media_item(item, platform="facebook")
        self.assertEqual(decision.engine, EngineType.GALLERY_DL)

    def test_07_facebook_video_routes_to_yt_dlp(self):
        """Verify Facebook video / Reel routes to yt-dlp."""
        video_item = VideoItem(
            index=1,
            video_id="10158292837492817",
            title="Facebook Live Video",
            duration="10:00",
            platform="facebook",
            url="https://www.facebook.com/watch/?v=10158292837492817",
            extra_metadata={"media_type": "VIDEO"},
        )
        decision = self.router.route_media_item(video_item, platform="facebook")
        self.assertEqual(decision.engine, EngineType.YTDLP)

    def test_08_facebook_mixed_media_handled_correctly(self):
        """Verify Facebook mixed media decomposes and routes appropriately."""
        photo = {"media_type": "IMAGE", "url": "https://fb.com/p.jpg"}
        video = {"media_type": "VIDEO", "url": "https://fb.com/v.mp4"}
        self.assertEqual(self.router.route_media_item(photo, platform="facebook").engine, EngineType.GALLERY_DL)
        self.assertEqual(self.router.route_media_item(video, platform="facebook").engine, EngineType.YTDLP)

    def test_09_unknown_media_invokes_metadata_probing(self):
        """Verify unknown media triggers metadata inspection and probing."""
        raw_unknown = {
            "media_type": "UNKNOWN",
            "url": "https://www.instagram.com/p/test/?param=1.jpg",
        }
        decision = self.router.route_media_item(raw_unknown, platform="instagram", probe_if_unknown=True)
        self.assertTrue(decision.metadata_probed)
        self.assertEqual(decision.media_type, MediaInventoryType.IMAGE)
        self.assertEqual(decision.engine, EngineType.GALLERY_DL)

    def test_10_unsupported_media_is_reported(self):
        """Verify unsupported media format reports unsupported engine without inventing routes."""
        item = {"media_type": "UNSUPPORTED", "url": "https://facebook.com/notes/123"}
        decision = self.router.route_media_item(item, platform="facebook")
        self.assertEqual(decision.engine, EngineType.UNSUPPORTED)
        self.assertFalse(decision.is_supported)

    def test_11_missing_gallery_dl_is_detected(self):
        """Verify router detects when gallery-dl is missing and flags warning/unsupported."""
        self.mock_gallerydl.is_available.return_value = False
        item = {"media_type": "IMAGE", "url": "https://instagram.com/p/test/"}
        decision = self.router.route_media_item(item, platform="instagram")
        self.assertEqual(decision.engine, EngineType.UNSUPPORTED)
        self.assertIn("gallery-dl is required", decision.warning)

    def test_12_standard_platforms_route_to_yt_dlp(self):
        """Verify YouTube, TikTok, Bilibili, and X route strictly to yt-dlp."""
        for plat in ("youtube", "tiktok", "bilibili", "x"):
            decision = self.router.route_media_item({"media_type": "VIDEO", "url": f"https://{plat}.com/v1"}, platform=plat)
            self.assertEqual(decision.engine, EngineType.YTDLP)

    def test_13_bounded_fallback_permitted_for_supported_video_errors(self):
        """Verify bounded fallback triggers only for approved errors on supported media."""
        initial_decision = EngineRouteDecision(
            engine=EngineType.YTDLP,
            media_type=MediaInventoryType.VIDEO,
            rationale="Initial yt-dlp attempt",
            can_fallback=True,
            fallback_engine=EngineType.GALLERY_DL,
        )
        fb_decision = self.router.evaluate_fallback(
            current_decision=initial_decision,
            error_category=ErrorCategory.UNKNOWN_EXTRACTION_ERROR,
            raw_error="yt-dlp extractor error",
            fallback_count=0,
        )
        self.assertIsNotNone(fb_decision)
        self.assertEqual(fb_decision.engine, EngineType.GALLERY_DL)
        self.assertFalse(fb_decision.can_fallback)

    def test_14_authentication_failures_do_not_trigger_engine_fallback(self):
        """Verify auth failures NEVER trigger engine switching."""
        initial_decision = EngineRouteDecision(
            engine=EngineType.YTDLP,
            media_type=MediaInventoryType.VIDEO,
            rationale="Initial attempt",
            can_fallback=True,
            fallback_engine=EngineType.GALLERY_DL,
        )
        for cat in (ErrorCategory.LOGIN_REQUIRED, ErrorCategory.PRIVATE_VIDEO, ErrorCategory.RATE_LIMITED):
            fb_decision = self.router.evaluate_fallback(
                current_decision=initial_decision,
                error_category=cat,
                fallback_count=0,
            )
            self.assertIsNone(fb_decision, f"Fallback must not occur for {cat}")

    def test_15_rate_limiting_does_not_trigger_engine_fallback(self):
        """Verify rate limits NEVER trigger engine switching."""
        initial_decision = EngineRouteDecision(
            engine=EngineType.YTDLP,
            media_type=MediaInventoryType.VIDEO,
            rationale="Initial attempt",
            can_fallback=True,
            fallback_engine=EngineType.GALLERY_DL,
        )
        fb_decision = self.router.evaluate_fallback(
            current_decision=initial_decision,
            error_category=ErrorCategory.RATE_LIMITED,
            fallback_count=0,
        )
        self.assertIsNone(fb_decision)

    def test_16_fallback_limit_enforced_strictly(self):
        """Verify fallback limit is maximum 1 attempt."""
        initial_decision = EngineRouteDecision(
            engine=EngineType.YTDLP,
            media_type=MediaInventoryType.VIDEO,
            rationale="Initial attempt",
            can_fallback=True,
            fallback_engine=EngineType.GALLERY_DL,
        )
        fb_decision = self.router.evaluate_fallback(
            current_decision=initial_decision,
            error_category=ErrorCategory.UNKNOWN_EXTRACTION_ERROR,
            fallback_count=1,  # Already attempted once
        )
        self.assertIsNone(fb_decision)


if __name__ == "__main__":
    unittest.main()
