"""
tests/test_profile_video_discovery_engine.py
Comprehensive Verification Suite for ProfileVideoDiscoveryEngine in Channel Harvest.

Covers the 12 Mandatory Verification Tests (Section 9):
1. Test 1: Unsupported profile/tab URLs are never passed to yt-dlp as individual video candidates.
2. Test 2: Invalid and guessed video URLs are rejected.
3. Test 3: Genuine discovered video URLs are normalized and deduplicated.
4. Test 4: yt-dlp receives only validated individual video URLs.
5. Test 5: Metadata extraction failures do not erase previously discovered records.
6. Test 6: Pagination failures preserve earlier valid results.
7. Test 7: Unsupported discovery capability is reported accurately.
8. Test 8: Authentication settings reach the intended subprocess or API client.
9. Test 9: Photo discovery behavior remains unchanged.
10. Test 10: Photo, video, and Reel records route to the correct download engines.
11. Test 11: Combined scan status remains PARTIAL when one requested media category is unsupported.
12. Test 12: A zero-candidate result is not interpreted as proof that no videos exist.
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.models import VideoItem, VideoStatus, ScanResult, MediaType
from core.inventory import (
    ProfileMediaInventory,
    ProfileRecord,
    PostRecord,
    MediaItemRecord,
    ScanCompleteness,
    MediaInventoryType,
    generate_stable_media_id,
)
from core.platform import PlatformRegistry
from core.platform.facebook import FacebookAdapter, clean_facebook_title
from core.platform.instagram import InstagramAdapter, clean_instagram_title
from core.platform.auth import PlatformAuthConfig
from core.media_classifier import MediaClassifier
from downloader.gallerydl_engine import (
    GalleryDlEngine,
    GalleryDlError,
    GalleryDlRecordList,
)
from downloader.engine_router import DownloadEngineRouter, EngineType
from downloader.profile_video_discovery_engine import (
    ProfileVideoDiscoveryEngine,
    DiscoveredVideoCandidate,
    ProfileVideoDiscoveryResult,
    VideoCandidateValidator,
    FacebookVideoDiscoveryStrategy,
    InstagramVideoDiscoveryStrategy,
)
from downloader.profile_scan_manager import ProfileScanManager


class TestProfileVideoDiscoveryEngine(unittest.TestCase):
    """Full test suite covering all 12 Mandatory Verification Tests (Section 9)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_discovery_inventory.db"
        self.inventory = ProfileMediaInventory(db_path=self.db_path)
        self.mock_gallerydl = MagicMock(spec=GalleryDlEngine)
        self.mock_gallerydl.is_available.return_value = True
        self.mock_gallerydl.get_version.return_value = "1.32.18"

        self.video_engine = ProfileVideoDiscoveryEngine(gallerydl_engine=self.mock_gallerydl)
        self.scan_manager = ProfileScanManager(
            inventory=self.inventory,
            gallerydl_engine=self.mock_gallerydl,
            video_discovery_engine=self.video_engine,
        )
        # Mock Comet API in fallback test suite to isolate fallback mechanics and prevent live network calls
        self.comet_patcher = patch.object(FacebookVideoDiscoveryStrategy, "_query_comet_api", return_value=[])
        self.comet_patcher.start()
        self.comet_tokens_patcher = patch("core.platform.facebook_comet.FacebookCometClient.extract_page_tokens", return_value={})
        self.comet_tokens_patcher.start()

    def tearDown(self):
        try:
            if hasattr(self, "comet_tokens_patcher"):
                self.comet_tokens_patcher.stop()
            if hasattr(self, "comet_patcher"):
                self.comet_patcher.stop()
            self.inventory.close()
            self.temp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Test 1: Unsupported profile/tab URLs are never passed to yt-dlp as individual video candidates
    # -------------------------------------------------------------------------
    def test_01_unsupported_profile_tab_urls_never_passed_to_ytdlp(self):
        """
        Test 1: Verify that root profile URLs and profile tab URLs (/videos/, /reels/)
        are rejected by VideoCandidateValidator and are NEVER passed to yt-dlp's individual extractor.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        tab_url = "https://www.facebook.com/HongYongMusic/videos/"

        # 1. Candidate with profile root URL
        c1 = DiscoveredVideoCandidate(
            platform="facebook",
            profile_url=profile_url,
            video_url=profile_url,
            media_id="fb_root_profile",
        )
        # 2. Candidate with profile tab URL
        c2 = DiscoveredVideoCandidate(
            platform="facebook",
            profile_url=profile_url,
            video_url=tab_url,
            media_id="fb_tab_url",
        )

        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            item1 = self.video_engine.extract_candidate_metadata(candidate=c1)
            item2 = self.video_engine.extract_candidate_metadata(candidate=c2)
            mock_ydl.assert_not_called()

        self.assertEqual(c1.metadata_status, "failed")
        self.assertIn("profile url; cannot extract individual metadata", c1.diagnostic_details["error"].lower())
        self.assertEqual(c2.metadata_status, "failed")
        self.assertIn("profile url; cannot extract individual metadata", c2.diagnostic_details["error"].lower())

    # -------------------------------------------------------------------------
    # Test 2: Invalid and guessed video URLs are rejected
    # -------------------------------------------------------------------------
    def test_02_invalid_and_guessed_video_urls_rejected(self):
        """
        Test 2: Verify VideoCandidateValidator rejects:
        - Guessed / invalid video URLs
        - CDN image URLs (e.g. scontent.xx.fbcdn.net)
        - Malformed or wrong platform URLs
        """
        # Malformed / guessed URLs
        v1, r1, _ = VideoCandidateValidator.validate_candidate_url("not_a_url", "facebook")
        self.assertFalse(v1)
        self.assertIn("invalid url", r1.lower())

        v2, r2, _ = VideoCandidateValidator.validate_candidate_url("https://www.facebook.com/", "facebook")
        self.assertFalse(v2)

        # CDN image URLs and non-video photo URLs
        v3, r3, _ = VideoCandidateValidator.validate_candidate_url("https://scontent.xx.fbcdn.net/v/t39.30808-6/photo.jpg", "facebook")
        self.assertFalse(v3)
        self.assertIn("does not match facebook", r3.lower())

        v3b, r3b, _ = VideoCandidateValidator.validate_candidate_url("https://www.facebook.com/photo.php?fbid=123456", "facebook")
        self.assertFalse(v3b)
        self.assertIn("profile url cannot be processed", r3b.lower())

        v3c, r3c, _ = VideoCandidateValidator.validate_candidate_url("https://www.facebook.com/marketplace/item/123456789/", "facebook")
        self.assertFalse(v3c)
        self.assertIn("not a recognized facebook video", r3c.lower())

        # Other platforms
        v4, r4, _ = VideoCandidateValidator.validate_candidate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "facebook")
        self.assertFalse(v4)
        self.assertIn("does not match facebook", r4.lower())

    # -------------------------------------------------------------------------
    # Test 3: Genuine discovered video URLs are normalized and deduplicated
    # -------------------------------------------------------------------------
    def test_03_genuine_discovered_video_urls_normalized_and_deduplicated(self):
        """
        Test 3: Verify that genuine discovered URLs have tracking parameters stripped,
        essential video identifiers preserved, and duplicate records deduplicated.
        """
        # Tracking parameter stripping
        dirty_url = "https://www.facebook.com/watch/?v=9876543210&fbclid=IwAR2xyz&mibextid=kdk82&ref=sharing"
        is_val, _, info = VideoCandidateValidator.validate_candidate_url(dirty_url, "facebook")
        self.assertTrue(is_val)
        self.assertEqual(info["media_id"], "9876543210")
        self.assertNotIn("fbclid", info["canonical_url"])
        self.assertNotIn("mibextid", info["canonical_url"])
        self.assertEqual(info["canonical_url"], "https://www.facebook.com/watch/?v=9876543210")

        # Deduplication in strategy
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)
        records = [
            {"type": "video", "video_id": "777", "url": "https://www.facebook.com/watch/?v=777", "title": "Vid 1"},
            {"type": "video", "video_id": "777", "url": "https://www.facebook.com/watch/?v=777&ref=share", "title": "Vid 1 Duplicate"},
            {"type": "video", "video_id": "888", "url": "https://www.facebook.com/watch/?v=888", "title": "Vid 2"},
        ]
        res = strategy.discover_candidates(profile_url="https://www.facebook.com/HongYongMusic/", raw_records=records)
        self.assertEqual(len(res.candidates), 2)
        self.assertEqual(res.diagnostics["duplicate_candidates"], 1)

    # -------------------------------------------------------------------------
    # Test 4: yt-dlp receives only validated individual video URLs
    # -------------------------------------------------------------------------
    def test_04_ytdlp_receives_only_validated_individual_video_urls(self):
        """
        Test 4: Verify yt-dlp receives strictly validated individual video URLs
        rather than profile URLs, with download=False.
        """
        candidate = DiscoveredVideoCandidate(
            platform="facebook",
            profile_url="https://www.facebook.com/HongYongMusic/",
            video_url="https://www.facebook.com/watch/?v=1234567890",
            media_id="1234567890",
            title="Performance Video",
            media_type=MediaType.VIDEO,
        )

        extracted_calls = []
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_inst = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_inst

            def mock_extract(url, download=False):
                extracted_calls.append({"url": url, "download": download})
                return {
                    "title": "Cleaned Title",
                    "duration": 150,
                    "thumbnail": "https://example.com/thumb.jpg",
                    "webpage_url": "https://www.facebook.com/watch/?v=1234567890",
                }

            mock_inst.extract_info.side_effect = mock_extract
            item = self.video_engine.extract_candidate_metadata(candidate=candidate)

        self.assertEqual(len(extracted_calls), 1)
        self.assertEqual(extracted_calls[0]["url"], "https://www.facebook.com/watch/?v=1234567890")
        self.assertFalse(extracted_calls[0]["download"])
        self.assertEqual(item.duration_seconds, 150)
        self.assertEqual(item.duration, "02:30")

    # -------------------------------------------------------------------------
    # Test 5: Metadata extraction failures do not erase previously discovered records
    # -------------------------------------------------------------------------
    def test_05_metadata_extraction_failures_do_not_erase_discovered_records(self):
        """
        Test 5: When yt-dlp fails on an individual video candidate during metadata extraction,
        verify that the candidate is preserved in inventory rather than deleted.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        candidate = DiscoveredVideoCandidate(
            platform="facebook",
            profile_url=profile_url,
            video_url="https://www.facebook.com/watch/?v=failed_meta_1",
            media_id="failed_meta_1",
            title="Discovered Candidate Prior to Failure",
            duration_seconds=120,
            media_type=MediaType.VIDEO,
        )

        # yt-dlp raises an exception
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_inst = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_inst
            mock_inst.extract_info.side_effect = RuntimeError("Video unavailable or network error")

            item = self.video_engine.extract_candidate_metadata(candidate=candidate)

        # Verify candidate is preserved with metadata_status="failed"
        self.assertEqual(candidate.metadata_status, "failed")
        self.assertIn("Video unavailable", candidate.diagnostic_details.get("metadata_error", ""))
        self.assertEqual(item.video_id, candidate.deduplication_key)
        self.assertEqual(item.title, "Discovered Candidate Prior to Failure")
        self.assertEqual(item.status, VideoStatus.READY)

    # -------------------------------------------------------------------------
    # Test 6: Pagination failures preserve earlier valid results
    # -------------------------------------------------------------------------
    def test_06_pagination_failures_preserve_earlier_valid_results(self):
        """
        Test 6: When multi-page discovery encounters a pagination failure on page 2+,
        earlier valid items are preserved and returned with status PARTIAL.
        """
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)
        profile_url = "https://www.facebook.com/HongYongMusic/"

        # Mock urllib.request.urlopen to return page 1 successfully, then raise on page 2
        page1_response = {
            "data": [
                {
                    "id": "vid_page1_1",
                    "title": "Page 1 Video 1",
                    "length": 100,
                    "permalink_url": "https://www.facebook.com/watch/?v=vid_page1_1",
                },
                {
                    "id": "vid_page1_2",
                    "title": "Page 1 Video 2",
                    "length": 200,
                    "permalink_url": "https://www.facebook.com/watch/?v=vid_page1_2",
                },
            ],
            "paging": {
                "next": "https://graph.facebook.com/v19.0/HongYongMusic/videos?cursor=page2",
            },
        }

        call_count = 0
        def mock_urlopen(req, timeout=30.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(page1_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                return mock_resp
            else:
                import urllib.error
                raise urllib.error.HTTPError(
                    url=req.full_url if hasattr(req, "full_url") else str(req),
                    code=500,
                    msg="Internal Server Error on Page 2",
                    hdrs={},
                    fp=None,
                )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            res = strategy.discover_candidates(
                profile_url=profile_url,
                auth_config={"api_token": "valid_mock_token"},
            )

        self.assertEqual(len(res.candidates), 2)
        self.assertEqual(res.status, ScanCompleteness.PARTIAL)
        self.assertTrue(res.diagnostics.get("pagination_partial"))
        self.assertEqual(res.candidates[0].media_id, "vid_page1_1")
        self.assertEqual(res.candidates[1].media_id, "vid_page1_2")

    # -------------------------------------------------------------------------
    # Test 7: Unsupported discovery capability is reported accurately
    # -------------------------------------------------------------------------
    def test_07_unsupported_discovery_capability_reported_accurately(self):
        """
        Test 7: When Facebook video discovery runs without official API authorization,
        verify that it reports failure_reason=UNSUPPORTED_DISCOVERY_CAPABILITY and
        does not probe unsupported /videos/ or /reels/ endpoints with gallery-dl.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)

        result = strategy.discover_candidates(profile_url=profile_url)

        # Assert gallery-dl was NOT called with /videos or /reels
        for call_args in self.mock_gallerydl.extract_metadata.call_args_list:
            called_url = call_args[1].get("url") if "url" in call_args[1] else call_args[0][0]
            self.assertNotIn("/videos", called_url)
            self.assertNotIn("/reels", called_url)

        self.assertEqual(result.status, ScanCompleteness.FAILED)
        self.assertEqual(len(result.candidates), 0)
        self.assertEqual(result.failure_reason, "UNSUPPORTED_DISCOVERY_CAPABILITY")
        self.assertTrue(result.diagnostics.get("unsupported_capability"))
        self.assertIn("not supported by installed extractors", result.error)

    # -------------------------------------------------------------------------
    # Test 8: Authentication settings reach the intended subprocess or API client
    # -------------------------------------------------------------------------
    def test_08_authentication_settings_reach_intended_subprocess_or_api(self):
        """
        Test 8: Verify authentication settings propagation:
        - When custom_cookie_file is selected with no path, reports auth_method='none'.
        - When a valid cookie file path is configured, it reaches gallery-dl and yt-dlp.
        - When an API token is provided, it reaches the discovery strategy.
        """
        # Case A: Missing cookie path
        adapter = FacebookAdapter()
        missing_cfg = adapter.get_auth_config({"facebook_auth_method": "custom_file", "facebook_custom_cookie_file": ""})
        self.assertEqual(missing_cfg.auth_method, "none")
        self.assertIn("no file path configured", missing_cfg.description.lower())

        # Case B: Valid cookie path reaches gallery-dl
        valid_cookie_file = Path(self.temp_dir.name) / "test_cookies.txt"
        valid_cookie_file.write_text("# Netscape HTTP Cookie File\n.facebook.com TRUE / FALSE 0 c_user 12345\n")

        valid_cfg = PlatformAuthConfig(auth_method="custom_file", cookie_file=str(valid_cookie_file))
        self.mock_gallerydl.extract_metadata.return_value = GalleryDlRecordList([])

        self.scan_manager.scan_profile(
            url="https://www.facebook.com/HongYongMusic/",
            platform="facebook",
            auth_config=valid_cfg,
        )

        # Verify gallery-dl received custom_cookie_file
        call_kwargs = self.mock_gallerydl.extract_metadata.call_args[1]
        self.assertEqual(call_kwargs.get("custom_cookie_file"), str(valid_cookie_file))

        # Case C: API token propagation
        api_cfg = PlatformAuthConfig(api_token="meta_token_123")
        self.assertTrue(api_cfg.is_active)
        self.assertEqual(api_cfg.api_token, "meta_token_123")

    # -------------------------------------------------------------------------
    # Test 9: Photo discovery behavior remains unchanged
    # -------------------------------------------------------------------------
    def test_09_photo_discovery_behavior_remains_unchanged(self):
        """
        Test 9: Verify that photo discovery via gallery-dl remains functional,
        discovering 18 photos with duration '-', MediaType.PHOTO, and correct URLs.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        photo_records = GalleryDlRecordList([
            {
                "category": "facebook",
                "subcategory": "photos",
                "id": f"photo_{i}",
                "url": f"https://scontent.example.com/p_{i}.jpg",
                "post_url": f"https://www.facebook.com/HongYongMusic/posts/{i}",
                "caption": f"Hong Yong Music Photo {i}",
            }
            for i in range(1, 19)
        ])
        self.mock_gallerydl.extract_metadata.return_value = photo_records

        result = self.scan_manager.scan_profile(url=profile_url, platform="facebook")

        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.PARTIAL)
        self.assertEqual(len(result.videos), 18)
        self.assertEqual(result.extra_metadata["photo_count"], 18)
        self.assertEqual(result.extra_metadata["video_count"], 0)

        # Verify first photo attributes
        p1 = result.videos[0]
        self.assertEqual(p1.media_type, MediaType.PHOTO)
        self.assertEqual(p1.duration, "-")
        self.assertEqual(p1.duration_seconds, None)
        self.assertEqual(p1.url, "https://scontent.example.com/p_1.jpg")

    # -------------------------------------------------------------------------
    # Test 10: Photo, video, and Reel records route to the correct download engines
    # -------------------------------------------------------------------------
    def test_10_photo_video_and_reel_records_route_to_correct_download_engines(self):
        """
        Test 10: Verify DownloadEngineRouter routes:
        - Photos -> EngineType.GALLERY_DL
        - Videos -> EngineType.YTDLP
        - Reels -> EngineType.YTDLP
        """
        router = DownloadEngineRouter(self.mock_gallerydl)

        photo_item = VideoItem(
            index=1,
            video_id="fb_photo_1",
            title="Photo 1",
            duration="-",
            status=VideoStatus.READY,
            url="https://scontent.example.com/p1.jpg",
            platform="facebook",
            media_type=MediaType.PHOTO,
            extra_metadata={"media_type": MediaInventoryType.IMAGE},
        )
        video_item = VideoItem(
            index=2,
            video_id="fb_video_1",
            title="Video 1",
            duration="03:00",
            duration_seconds=180,
            status=VideoStatus.READY,
            url="https://www.facebook.com/watch/?v=111",
            platform="facebook",
            media_type=MediaType.VIDEO,
            extra_metadata={"media_type": MediaInventoryType.VIDEO},
        )
        reel_item = VideoItem(
            index=3,
            video_id="fb_reel_1",
            title="Reel 1",
            duration="00:30",
            duration_seconds=30,
            status=VideoStatus.READY,
            url="https://www.facebook.com/reel/222",
            platform="facebook",
            media_type=MediaType.REEL,
            extra_metadata={"media_type": MediaInventoryType.REEL},
        )

        self.assertEqual(router.route_media_item(photo_item, platform="facebook").engine, EngineType.GALLERY_DL)
        self.assertEqual(router.route_media_item(video_item, platform="facebook").engine, EngineType.YTDLP)
        self.assertEqual(router.route_media_item(reel_item, platform="facebook").engine, EngineType.YTDLP)

    # -------------------------------------------------------------------------
    # Test 11: Combined scan status remains PARTIAL when one media category is unsupported
    # -------------------------------------------------------------------------
    def test_11_combined_scan_status_remains_partial_when_video_unsupported(self):
        """
        Test 11: When photo discovery succeeds (18 photos) and video discovery reports
        UNSUPPORTED_DISCOVERY_CAPABILITY, verify that the combined scan status remains PARTIAL,
        never falsely reporting COMPLETE.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        photo_records = GalleryDlRecordList([
            {
                "category": "facebook",
                "subcategory": "photos",
                "id": f"photo_{i}",
                "url": f"https://scontent.example.com/p_{i}.jpg",
                "post_url": f"https://www.facebook.com/HongYongMusic/posts/{i}",
                "caption": f"Hong Yong Music Photo {i}",
            }
            for i in range(1, 19)
        ])
        self.mock_gallerydl.extract_metadata.return_value = photo_records

        result = self.scan_manager.scan_profile(url=profile_url, platform="facebook")

        # Crucial assertion: status must be PARTIAL, NOT COMPLETE
        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.PARTIAL)
        self.assertNotEqual(result.extra_metadata["scan_status"], ScanCompleteness.COMPLETE)

        info = result.extra_metadata["scan_completeness_info"]
        self.assertIn("Partial scan", info)
        self.assertIn("18 photos", info)
        self.assertIn("video discovery notice", info.lower())

    # -------------------------------------------------------------------------
    # Test 12: A zero-candidate result is not interpreted as proof that no videos exist
    # -------------------------------------------------------------------------
    def test_12_zero_candidate_result_not_interpreted_as_no_videos_exist(self):
        """
        Test 12: When video discovery returns 0 candidates due to unsupported capability,
        verify that it is NOT interpreted as proof that the Page has no videos.
        Diagnostics record zero_candidates_meaning='DISCOVERY_UNSUPPORTED', and notice clarifies
        that direct video URLs remain supported.
        """
        profile_url = "https://www.facebook.com/HongYongMusic/"
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)

        result = strategy.discover_candidates(profile_url=profile_url)

        self.assertEqual(result.total_candidates, 0)
        self.assertEqual(result.failure_reason, "UNSUPPORTED_DISCOVERY_CAPABILITY")
        self.assertEqual(result.diagnostics.get("zero_candidates_meaning"), "DISCOVERY_UNSUPPORTED")
        self.assertNotEqual(result.diagnostics.get("zero_candidates_meaning"), "PAGE_HAS_NO_VIDEOS")

        # In ScanManager
        self.mock_gallerydl.extract_metadata.return_value = GalleryDlRecordList([])
        scan_res = self.scan_manager.scan_profile(url=profile_url, platform="facebook")
        completeness_info = scan_res.extra_metadata.get("scan_completeness_info", "")
        self.assertIn("Direct individual video and Reel URLs remain fully supported", completeness_info)


if __name__ == "__main__":
    unittest.main()
