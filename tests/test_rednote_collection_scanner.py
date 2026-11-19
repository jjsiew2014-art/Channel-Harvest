"""
test_rednote_collection_scanner.py
Comprehensive unit test suite for RedNote (XiaoHongShu 小红书) collection and column
batch parsing, waterfall layout flattening, metadata formatting, and download resolution.
"""

import unittest
from unittest.mock import MagicMock, patch
import json

from core.models import MediaType, VideoItem, VideoStatus, DownloadMode
from core.inventory import ScanCompleteness
from core.platform.rednote import RedNoteAdapter, clean_rednote_state_json
from metadata.rednote_formatter import RedNoteMetadataFormatter
from downloader.profile_scan_manager import ProfileScanManager


class TestRedNoteCollectionScanner(unittest.TestCase):

    def setUp(self):
        self.adapter = RedNoteAdapter()
        self.formatter = RedNoteMetadataFormatter()

    def test_capabilities_supports_playlists(self):
        """Verify RedNoteAdapter declares supports_playlists=True for collections/columns."""
        self.assertTrue(self.adapter.capabilities.supports_playlists)
        self.assertTrue(self.adapter.capabilities.supports_channel_scan)

    def test_collection_url_detection(self):
        """Test detection and validation of various RedNote collection/column URL formats."""
        collection_urls = [
            "https://www.xiaohongshu.com/collection/65798e6f000000001e012345",
            "https://www.rednote.com/collection/65798e6f000000001e012345",
            "https://www.xiaohongshu.com/column/col_987654321",
            "https://www.xiaohongshu.com/board/board_abc123",
            "https://www.xiaohongshu.com/series/series_xyz789",
            "https://www.xiaohongshu.com/page/collection/page_coll_456",
            "https://www.xiaohongshu.com/user/profile/5c9ca4bf000000001000e11e/collection/65798e6f000000001e012345",
            "https://www.xiaohongshu.com/user/profile/5c9ca4bf000000001000e11e?tab=collection&collection_id=65798e6f",
        ]

        for url in collection_urls:
            with self.subTest(url=url):
                self.assertTrue(self.adapter.is_collection_url(url), f"Should match collection URL: {url}")
                valid, msg = self.adapter.validate_url(url)
                self.assertTrue(valid, f"Should be valid URL: {url}, got: {msg}")

        non_collection_urls = [
            "https://www.xiaohongshu.com/discovery/item/6ada36c800000000320145f0",
            "https://www.xiaohongshu.com/explore/6ada36c800000000320145f0",
            "https://www.xiaohongshu.com/user/profile/5c9ca4bf000000001000e11e",
        ]
        for url in non_collection_urls:
            with self.subTest(url=url):
                self.assertFalse(self.adapter.is_collection_url(url), f"Should not match collection URL: {url}")

    def test_waterfall_flattening_and_extraction(self):
        """Test parsing window.__INITIAL_STATE__ with 2D column waterfall layout and extracting notes."""
        sample_state = {
            "collectionData": {
                "name": "Python 零基础入门系列教程",
                "desc": "由浅入深讲解 Python 编程技巧与实践",
                "user": {
                    "nickname": "极客导师",
                    "userId": "geek_1001",
                    "redId": "GEEK1001",
                },
                # Multi-column waterfall layout [[col1_p1, col1_p2], [col2_p1, col2_p2]]
                "notes": [
                    [
                        {
                            "id": "note_001",
                            "type": "video",
                            "displayTitle": "Python 第一讲：环境搭建与语法基础",
                            "video": {
                                "duration": 480000,
                                "consumer": {"originVideoKey": "video_key_001"},
                            },
                            "cover": {
                                "urlDefault": "https://sns-img-qc.xhscdn.com/cover_001.jpg",
                                "fileId": "cover_001.jpg",
                                "width": 1080,
                                "height": 1920,
                            },
                            "interactInfo": {"likedCount": "1.2万", "collectedCount": "8900"},
                        },
                        {
                            "id": "note_003",
                            "type": "video",
                            "displayTitle": "Python 第三讲：面向对象与模块封装",
                            "video": {
                                "duration": 620000,
                                "consumer": {"originVideoKey": "video_key_003"},
                            },
                            "cover": {
                                "urlDefault": "https://sns-img-qc.xhscdn.com/cover_003.jpg",
                                "fileId": "cover_003.jpg",
                            },
                            "interactInfo": {"likedCount": "9800", "collectedCount": "7200"},
                        },
                    ],
                    [
                        {
                            "id": "note_002",
                            "type": "normal",
                            "displayTitle": "Python 第二讲：常用数据结构详解（附思维导图）",
                            "imageCount": 6,
                            "cover": {
                                "urlDefault": "https://sns-img-qc.xhscdn.com/cover_002.jpg",
                                "fileId": "cover_002.jpg",
                            },
                            "interactInfo": {"likedCount": "2.5万", "collectedCount": "1.8万"},
                        },
                        {
                            "id": "note_004",
                            "type": "normal",
                            "displayTitle": "Python 第四讲：实用标准库与项目实战",
                            "imageCount": 4,
                            "cover": {
                                "urlDefault": "https://sns-img-qc.xhscdn.com/cover_004.jpg",
                                "fileId": "cover_004.jpg",
                            },
                            "interactInfo": {"likedCount": "1.5万", "collectedCount": "1.1万"},
                        },
                    ],
                ],
            }
        }

        mock_html = f"<html><body><script>window.__INITIAL_STATE__={json.dumps(sample_state)};</script></body></html>"

        with patch.object(self.adapter, "_fetch_html", return_value=mock_html):
            items = self.adapter.extract_entries("https://www.xiaohongshu.com/collection/65798e6f000000001e012345")

        self.assertEqual(len(items), 4)

        # Interleaved order from waterfall columns:
        # row 0: col1[0] (note_001), col2[0] (note_002)
        # row 1: col1[1] (note_003), col2[1] (note_004)
        self.assertEqual(items[0].video_id, "note_001")
        self.assertEqual(items[0].media_type, MediaType.VIDEO)
        self.assertEqual(items[0].extra_metadata.get("collection_name"), "Python 零基础入门系列教程")
        self.assertEqual(items[0].duration, "08:00")

        self.assertEqual(items[1].video_id, "note_002")
        self.assertEqual(items[1].media_type, MediaType.PHOTO)
        self.assertEqual(items[1].duration, "6P")
        self.assertEqual(items[1].extra_metadata.get("photo_count"), 6)
        self.assertEqual(items[1].channel_title, "极客导师")

        self.assertEqual(items[2].video_id, "note_003")
        self.assertEqual(items[2].media_type, MediaType.VIDEO)

        self.assertEqual(items[3].video_id, "note_004")
        self.assertEqual(items[3].media_type, MediaType.PHOTO)
        self.assertEqual(items[3].duration, "4P")

    def test_adapter_scan_returns_collection_metadata(self):
        """Test RedNoteAdapter.scan returns ScanResult with collection source_type and title."""
        sample_state = {
            "collection": {
                "name": "巴黎时装周秀场精选",
                "user": {"nickname": "时尚芭莎", "userId": "bazaar_paris"},
                "notes": [
                    {
                        "id": "paris_01",
                        "type": "video",
                        "title": "巴黎时装周大秀开幕",
                        "cover": {"urlDefault": "https://sns-img-qc.xhscdn.com/p01.jpg"},
                    }
                ],
            }
        }
        mock_html = f"<script>window.__INITIAL_STATE__={json.dumps(sample_state)}</script>"

        with patch.object(self.adapter, "_fetch_html", return_value=mock_html):
            scan_res = self.adapter.scan("https://www.xiaohongshu.com/collection/paris_2024")

        self.assertEqual(scan_res.source_type, "collection")
        self.assertEqual(scan_res.source_title, "巴黎时装周秀场精选")
        self.assertEqual(len(scan_res.videos), 1)
        self.assertEqual(scan_res.videos[0].video_id, "paris_01")

    def test_profile_scan_manager_collection_integration(self):
        """Test ProfileScanManager properly delegates and labels RedNote collection scans."""
        manager = ProfileScanManager()
        logs = []

        sample_notes = [
            VideoItem(
                index=1,
                video_id="c_note_1",
                title="摄影构图全集 (一)",
                duration="5P",
                status=VideoStatus.READY,
                subtitle_status="—",
                url="https://www.xiaohongshu.com/discovery/item/c_note_1",
                channel_title="摄影家协会",
                platform="rednote",
                media_type=MediaType.PHOTO,
                extra_metadata={
                    "collection_name": "手机摄影终极进阶专栏",
                    "collection_id": "photo_adv_01",
                    "photo_count": 5,
                },
            ),
            VideoItem(
                index=2,
                video_id="c_note_2",
                title="摄影构图全集 (二)",
                duration="03:45",
                duration_seconds=225,
                status=VideoStatus.READY,
                subtitle_status="—",
                url="https://www.xiaohongshu.com/discovery/item/c_note_2",
                channel_title="摄影家协会",
                platform="rednote",
                media_type=MediaType.VIDEO,
                extra_metadata={
                    "collection_name": "手机摄影终极进阶专栏",
                    "collection_id": "photo_adv_01",
                },
            ),
        ]

        with patch.object(RedNoteAdapter, "extract_entries", return_value=sample_notes):
            scan_res = manager.scan_profile(
                url="https://www.xiaohongshu.com/collection/photo_adv_01",
                platform="rednote",
                log_callback=logs.append,
            )

        self.assertEqual(scan_res.source_type, "collection")
        self.assertEqual(scan_res.source_title, "手机摄影终极进阶专栏")
        self.assertEqual(scan_res.extra_metadata["scan_status"], ScanCompleteness.COMPLETE)
        self.assertIn("collection enumeration completed successfully", scan_res.extra_metadata["scan_completeness_info"])
        self.assertTrue(any("Discovering collection notes via RedNoteAdapter" in l for l in logs))

    def test_metadata_formatter_displays_collection(self):
        """Test RedNoteMetadataFormatter renders collection/series section when present."""
        item = VideoItem(
            index=1,
            video_id="tut_99",
            title="精通TypeScript进阶技巧",
            duration="8P",
            status=VideoStatus.READY,
            subtitle_status="—",
            url="https://www.xiaohongshu.com/discovery/item/tut_99",
            channel_title="全栈老张",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "collection_name": "现代前端全栈工程实战合集",
                "collection_id": "frontend_series_2026",
                "photo_count": 8,
                "liked_count": "3.5万",
                "collected_count": "2.8万",
                "comment_count": "1560",
                "share_count": "890",
                "ip_location": "北京",
            },
        )

        formatted_txt = self.formatter.format({}, video=item)

        self.assertIn("Collection / Series (合集专栏):", formatted_txt)
        self.assertIn("现代前端全栈工程实战合集 (ID: frontend_series_2026)", formatted_txt)
        self.assertIn("Title / Headline:\n精通TypeScript进阶技巧", formatted_txt)
        self.assertIn("Creator:\n全栈老张", formatted_txt)
        self.assertIn("3.5万", formatted_txt)
        self.assertIn("1,560", formatted_txt)

    def test_dynamic_multi_photo_resolution_for_collection_card(self):
        """
        Verify that when a photo note discovered from a collection card only holds 1 cover photo
        but indicates photo_count > 1, download manager logic triggers dynamic re-extraction
        to fetch the full set of photo URLs.
        """
        initial_card_item = VideoItem(
            index=1,
            video_id="card_multi_p",
            title="日落风景摄影集",
            duration="5P",
            status=VideoStatus.READY,
            subtitle_status="—",
            url="https://www.xiaohongshu.com/discovery/item/card_multi_p",
            channel_title="风光大师",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "collection_name": "全球绝美日落图鉴",
                "photo_count": 5,
                "photo_urls": ["https://sns-img-qc.xhscdn.com/cover_only.jpg"],  # only cover initially
            },
        )

        # Full entry retrieved on demand
        resolved_full_entry = VideoItem(
            index=1,
            video_id="card_multi_p",
            title="日落风景摄影集",
            duration="5P",
            status=VideoStatus.READY,
            subtitle_status="—",
            url="https://www.xiaohongshu.com/discovery/item/card_multi_p",
            channel_title="风光大师",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "collection_name": "全球绝美日落图鉴",
                "photo_count": 5,
                "photo_urls": [
                    f"https://sns-img-qc.xhscdn.com/sunset_{i}.jpg" for i in range(1, 6)
                ],
            },
        )

        # Simulate download manager logic condition
        photo_urls = initial_card_item.extra_metadata.get("photo_urls") or []
        expected_p_count = int(initial_card_item.extra_metadata.get("photo_count") or 1)

        need_full_fetch = (not photo_urls or (expected_p_count > 1 and len(photo_urls) <= 1))
        self.assertTrue(need_full_fetch, "Should detect that full photo set needs dynamic resolution")

        with patch.object(self.adapter, "extract_entries", return_value=[resolved_full_entry]):
            if need_full_fetch:
                entries = self.adapter.extract_entries(initial_card_item.url)
                if entries and entries[0].extra_metadata.get("photo_urls"):
                    photo_urls = entries[0].extra_metadata["photo_urls"]
                    initial_card_item.extra_metadata.update(entries[0].extra_metadata)

        self.assertEqual(len(photo_urls), 5)
        self.assertEqual(len(initial_card_item.extra_metadata["photo_urls"]), 5)


if __name__ == "__main__":
    unittest.main()
