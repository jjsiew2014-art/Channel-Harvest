"""
tests/test_rednote_adapter.py
Comprehensive unit tests for RedNote (小红书) platform adapter, URL detection,
mobile share extraction, short link resolution, note extraction (Photos & Videos),
profile scanning, engine routing, and platform-scoped authentication in Channel Harvest.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from core.models import VideoItem, VideoStatus, MediaType
from core.platform.rednote import RedNoteAdapter, inspect_rednote_cookie_file_safe
from core.platform.detector import PlatformDetector, PlatformRegistry
from core.inventory import MediaInventoryType
from downloader.engine_router import DownloadEngineRouter, EngineType
from core.settings import SettingsManager


class TestRedNoteAdapter(unittest.TestCase):
    """Unit tests for RedNoteAdapter and RedNote integration."""

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.settings_path = Path(self.tmp_dir.name) / "settings.json"
        self.file_patcher = patch("core.settings.get_settings_file", return_value=self.settings_path)
        self.file_patcher.start()
        self.isolated_sm = SettingsManager(settings_path=self.settings_path)
        self.sm_patcher = patch("core.settings.SettingsManager", return_value=self.isolated_sm)
        self.sm_patcher.start()
        self.adapter = RedNoteAdapter()
        PlatformRegistry.register(self.adapter)

    def tearDown(self):
        self.sm_patcher.stop()
        self.file_patcher.stop()
        self.tmp_dir.cleanup()

    def test_properties_and_capabilities(self):
        """Verifies platform metadata and capability flags."""
        self.assertEqual(self.adapter.platform_id, "rednote")
        self.assertEqual(self.adapter.display_name, "RedNote")
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertFalse(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_chapters)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_browser_cookies)
        self.assertTrue(caps.supports_cookie_file)
        self.assertEqual(caps.archive_prefix, "rednote")

    def test_matches_url(self):
        """Verifies URL pattern matching across desktop, mobile short links, and share snippets."""
        valid_urls = [
            "https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9",
            "http://xiaohongshu.com/explore/6411cf99000000001300b6d9",
            "https://www.xiaohongshu.com/discovery/item/6411cf99000000001300b6d9?xsec_token=CB123",
            "https://xhslink.com/a/abc123XYZ",
            "https://xhslink.com/m/def456UVW",
            "https://rednote.com/explore/6411cf99000000001300b6d9",
            "https://www.xiaohongshu.com/user/profile/5c31698d0000000007018a31",
            "82 复制打开小红书，查看这篇笔记： https://xhslink.com/a/abc123XYZ 01/22 b@h.rc",
            "64 复制本条信息打开【小红书】App！https://xhslink.com/m/4def56GHI，快来看~",
        ]
        for url in valid_urls:
            self.assertTrue(self.adapter.matches_url(url), f"Should match RedNote: {url}")
            self.assertEqual(PlatformDetector.identify_platform_id(url), "rednote")

        invalid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.douyin.com/video/7106594312292453678",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://example.com/test",
            "",
            None,
        ]
        for url in invalid_urls:
            self.assertFalse(self.adapter.matches_url(url), f"Should NOT match RedNote: {url}")

    def test_extract_url_mobile_snippets(self):
        """Tests that PlatformDetector cleans complex mobile app share texts."""
        snippets = [
            (
                "82 复制打开小红书，查看这篇笔记： https://xhslink.com/a/abc123XYZ 01/22 b@h.rc",
                "https://xhslink.com/a/abc123XYZ",
            ),
            (
                "【香妃蛋糕也太香了吧🔥】 https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9?xsec_token=CB123 复制打开【小红书】App！",
                "https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9?xsec_token=CB123",
            ),
            (
                "64 复制本条信息打开【小红书】App！https://xhslink.com/m/4def56GHI，快来看~",
                "https://xhslink.com/m/4def56GHI",
            ),
        ]
        for raw, expected in snippets:
            clean = PlatformDetector.extract_url(raw)
            self.assertEqual(clean, expected)

    def test_validate_url(self):
        """Tests URL validation logic."""
        ok, msg = self.adapter.validate_url("https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

        ok, msg = self.adapter.validate_url("https://xhslink.com/a/abc123XYZ")
        self.assertTrue(ok)

        ok, msg = self.adapter.validate_url("")
        self.assertFalse(ok)

        ok, msg = self.adapter.validate_url("ftp://xiaohongshu.com/explore/123")
        self.assertFalse(ok)

    def test_resolve_short_url(self):
        """Tests HTTP redirect tracking for xhslink.com short URLs."""
        destination = "https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9?xsec_token=CB123XYZ"
        mock_resp = MagicMock()
        mock_resp.geturl.return_value = destination
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            resolved = self.adapter.resolve_short_url("https://xhslink.com/a/abc123XYZ")
            self.assertEqual(resolved, destination)

    def test_extract_entries_photo_note(self):
        """Tests extracting an image-carousel (photo note) with multiple photos."""
        fake_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Note</title></head>
        <body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"6411cf99000000001300b6d9":{"note":{"title":"Delicious Cake Recipe","desc":"Step by step guide with photos #baking","type":"normal","user":{"nickname":"PastryChef","userId":"user123"},"imageList":[{"urlDefault":"https://sns-webpic-qc.xhscdn.com/img1!nd_dft_wlteh_webp_3"},{"urlDefault":"https://sns-webpic-qc.xhscdn.com/img2!nd_dft_wlteh_webp_3"},{"urlDefault":"https://sns-webpic-qc.xhscdn.com/img3!nd_dft_wlteh_webp_3"}]}}}}};</script>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            items = self.adapter.extract_entries("https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9")

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "6411cf99000000001300b6d9")
            self.assertEqual(item.title, "Delicious Cake Recipe")
            self.assertEqual(item.media_type, MediaType.PHOTO)
            self.assertEqual(item.duration, "-")
            self.assertIsNone(item.duration_seconds)
            self.assertEqual(item.channel_title, "PastryChef")
            self.assertTrue(item.extra_metadata.get("is_photo"))
            self.assertEqual(item.extra_metadata.get("photo_count"), 3)
            # Verify watermark parameters (!nd_...) were stripped from CDN URLs
            expected_urls = [
                "https://sns-webpic-qc.xhscdn.com/img1",
                "https://sns-webpic-qc.xhscdn.com/img2",
                "https://sns-webpic-qc.xhscdn.com/img3",
            ]
            self.assertEqual(item.extra_metadata.get("photo_urls"), expected_urls)

    def test_extract_entries_video_note(self):
        """Tests extracting a single video note."""
        fake_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Video Note</title></head>
        <body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"6522ef88000000001400a7e8":{"note":{"title":"Tokyo Travel Vlog","desc":"Day 1 in Shibuya #travel","type":"video","user":{"nickname":"TravelerBob","userId":"user456"},"video":{"duration":75000,"consumer":{"originVideoKey":"orig_video_key_12345"}},"imageList":[{"urlDefault":"https://sns-webpic-qc.xhscdn.com/cover1"}]}}}}};</script>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            items = self.adapter.extract_entries("https://www.xiaohongshu.com/explore/6522ef88000000001400a7e8")

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "6522ef88000000001400a7e8")
            self.assertEqual(item.title, "Tokyo Travel Vlog")
            self.assertEqual(item.media_type, MediaType.VIDEO)
            self.assertEqual(item.duration_seconds, 75)
            self.assertEqual(item.duration, "01:15")
            self.assertEqual(item.channel_title, "TravelerBob")
            self.assertEqual(
                item.extra_metadata.get("origin_video_url"),
                "https://sns-video-bd.xhscdn.com/orig_video_key_12345",
            )

    def test_extract_profile_entries(self):
        """Tests extracting notes from a creator's public profile page."""
        fake_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Creator Profile</title></head>
        <body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"FamousCreator"}},"notes":[{"noteId":"note01","displayTitle":"Photo Post 1","type":"normal","xsecToken":"token1","cover":{"urlDefault":"https://sns-webpic-qc.xhscdn.com/c1"}},{"noteId":"note02","displayTitle":"Video Post 2","type":"video","xsecToken":"token2","cover":{"urlDefault":"https://sns-webpic-qc.xhscdn.com/c2"}}]}};</script>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            items = self.adapter.extract_entries("https://www.xiaohongshu.com/user/profile/5c31698d0000000007018a31")

            self.assertEqual(len(items), 2)
            self.assertEqual(items[0].video_id, "note01")
            self.assertEqual(items[0].media_type, MediaType.PHOTO)
            self.assertEqual(items[0].url, "https://www.xiaohongshu.com/explore/note01?xsec_token=token1")

            self.assertEqual(items[1].video_id, "note02")
            self.assertEqual(items[1].media_type, MediaType.VIDEO)
            self.assertEqual(items[1].url, "https://www.xiaohongshu.com/explore/note02?xsec_token=token2")

    def test_engine_router_rednote(self):
        """Tests DownloadEngineRouter routing policies for RedNote images and videos."""
        router = DownloadEngineRouter()

        # 1. Photo item -> EngineType.INTERNAL
        photo_item = VideoItem(
            index=1,
            video_id="rn_photo",
            title="Photo Note",
            duration="Photo",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={"is_photo": True, "photo_urls": ["http://img1.jpg"]},
        )
        dec_photo = router.route_media_item(photo_item, platform="rednote")
        self.assertEqual(dec_photo.engine, EngineType.INTERNAL)
        self.assertTrue(dec_photo.is_internal)
        self.assertEqual(dec_photo.media_type, MediaInventoryType.IMAGE)

        # 2. Video item -> EngineType.YTDLP
        video_item = VideoItem(
            index=2,
            video_id="rn_video",
            title="Video Note",
            duration="01:23",
            platform="rednote",
            media_type=MediaType.VIDEO,
            extra_metadata={"note_type": "video"},
        )
        dec_video = router.route_media_item(video_item, platform="rednote")
        self.assertEqual(dec_video.engine, EngineType.YTDLP)
        self.assertTrue(dec_video.is_ytdlp)
        self.assertEqual(dec_video.media_type, MediaInventoryType.VIDEO)

    def test_cookie_file_inspection_and_all_fallback(self):
        """Tests safe Netscape cookie inspection and 'all' platform cookie fallback."""
        cookie_file = Path(self.tmp_dir.name) / "test_cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".xiaohongshu.com\tTRUE\t/\tTRUE\t2147483647\ta1\t18e12345678\n"
            ".xiaohongshu.com\tTRUE\t/\tTRUE\t2147483647\tweb_session\t0101abcd\n",
            encoding="utf-8",
        )

        ok, msg, details = inspect_rednote_cookie_file_safe(str(cookie_file))
        self.assertTrue(ok)
        self.assertTrue(details["has_a1"])
        self.assertTrue(details["has_web_session"])
        self.assertTrue(details["has_session"])
        self.assertEqual(details["rednote_cookies"], 2)

        # Test auth config with 'all' fallback
        all_cookie_file = Path(self.tmp_dir.name) / "all_cookies.txt"
        all_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".xiaohongshu.com\tTRUE\t/\tTRUE\t2147483647\ta1\tuniversal_a1\n",
            encoding="utf-8",
        )
        fake_settings = {
            "rednote_auth_method": "none",
            "rednote_custom_cookie_file": "",
            "all_auth_method": "custom_file",
            "all_custom_cookie_file": str(all_cookie_file),
        }
        cfg = self.adapter.get_auth_config(settings=fake_settings)
        self.assertTrue(cfg.is_active)
        self.assertEqual(cfg.auth_method, "custom_file")
        self.assertIn("all_cookies.txt", cfg.cookie_file)
        self.assertIn("All Platforms", cfg.description)

    def test_rednote_photo_download_and_pillow_conversion(self):
        """Tests that RedNote photo downloads create a dedicated subfolder and invoke Pillow conversion."""
        from downloader.download_manager import DownloadManager
        from core.models import DownloadSettings
        import io
        from PIL import Image

        settings = DownloadSettings(
            download_folder=self.tmp_dir.name,
            create_individual_video_folders=False,
            create_channel_folder=False,
            image_format="PNG",
            image_quality="90%",
            preserve_original_images=True,
        )

        video = VideoItem(
            index=1,
            video_id="6411test",
            title="Photo Note Test",
            duration="Photo",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "is_photo": True,
                "photo_count": 2,
                "photo_urls": [
                    "https://sns-webpic-qc.xhscdn.com/test1",
                    "https://sns-webpic-qc.xhscdn.com/test2",
                ],
                "description": "Lovely photo caption",
            },
        )

        dm = DownloadManager(videos=[video], settings=settings)

        # Create a tiny 10x10 JPEG in bytes to simulate image downloads
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        dummy_jpeg_bytes = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.return_value = dummy_jpeg_bytes
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            dm.run()

        # Check dedicated subfolder was created
        subfolder = Path(self.tmp_dir.name) / "Photo Note Test"
        self.assertTrue(subfolder.exists(), f"Dedicated subfolder must exist at {subfolder}")

        # Check images were converted to PNG
        png_files = list(subfolder.glob("*.png"))
        self.assertEqual(len(png_files), 2, "Both images should be converted to PNG via Pillow")
        self.assertEqual(video.status, VideoStatus.COMPLETED)

    def test_normalize_user_cases(self):
        """Tests normalization of user share snippet (URL 1) and red_video format (URL 2)."""
        u1 = (
            "49 【9min保姆级英国旅行攻略🇬🇧 旅游不烧心🔥 - Taoyii桃一 | 小红书 - 你的生活兴趣社区】 "
            "😆 BflHCUUeI0gwEda 😆 "
            "https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3?source=webshare&xhsshare=pc_web&xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=&xsec_source=pc_share"
        )
        u2 = (
            "https://www.xiaohongshu.com/red_video/6aca0fd6000000001403b6f3?xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=&xsec_source=pc_dual_feed"
        )

        norm1 = self.adapter.normalize_url(u1)
        norm2 = self.adapter.normalize_url(u2)

        # Both should normalize to discovery/item with note ID and xsec_token
        self.assertIn("https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3", norm1)
        self.assertIn("xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=", norm1)
        self.assertIn("xsec_source=pc_share", norm1)

        self.assertIn("https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3", norm2)
        self.assertIn("xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=", norm2)
        self.assertIn("xsec_source=pc_share", norm2)
        self.assertNotIn("red_video", norm2)

    def test_extract_entries_red_video_format(self):
        """Tests that red_video URLs extract successfully via discovery/item canonicalization."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"6aca0fd6000000001403b6f3":{"note":{"title":"UK Travel Guide 9min","desc":"Must see in London #travel","type":"video","user":{"nickname":"Taoyii桃一","userId":"54d20e612e1d9334e94bed8a"},"video":{"duration":565000,"consumer":{"originVideoKey":"video_key_uk"},"media":{"stream":{"h264":[{"masterUrl":"http://sns-video-zl.xhscdn.com/stream/uk.mp4","backupUrls":["http://sns-bak.xhscdn.com/uk.mp4"]}]}}},"imageList":[{"urlDefault":"https://sns-webpic-qc.xhscdn.com/cover_uk"}]}}}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            u2 = "https://www.xiaohongshu.com/red_video/6aca0fd6000000001403b6f3?xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=&xsec_source=pc_dual_feed"
            items = self.adapter.extract_entries(u2)

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.video_id, "6aca0fd6000000001403b6f3")
            self.assertEqual(item.title, "UK Travel Guide 9min")
            self.assertEqual(item.channel_title, "Taoyii桃一")
            self.assertEqual(item.media_type, MediaType.VIDEO)
            self.assertEqual(item.duration, "09:25")
            self.assertEqual(item.duration_seconds, 565)
            self.assertEqual(item.extra_metadata.get("origin_video_url"), "https://sns-video-bd.xhscdn.com/video_key_uk")

    def test_scan_returns_valid_scan_result(self):
        """Verifies adapter.scan returns a compliant ScanResult without TypeError."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"6aca0fd6000000001403b6f3":{"note":{"title":"UK Travel Guide 9min","desc":"Must see in London #travel","type":"video","user":{"nickname":"Taoyii桃一","userId":"54d20e612e1d9334e94bed8a"},"video":{"duration":565000,"consumer":{"originVideoKey":"video_key_uk"}},"imageList":[{"urlDefault":"https://sns-webpic-qc.xhscdn.com/cover_uk"}]}}}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            u = "https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3?source=webshare&xhsshare=pc_web&xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=&xsec_source=pc_share"
            res = self.adapter.scan(u)

            self.assertEqual(res.source_title, "Taoyii桃一")
            self.assertEqual(res.platform, "rednote")
            self.assertEqual(len(res.videos), 1)
            self.assertEqual(res.videos[0].title, "UK Travel Guide 9min")
            self.assertEqual(res.source_type, "video")

    def test_rednote_master_cover_url_extraction(self):
        """Verifies that master image CDN URL is extracted using fileId and avoids low-res preview suffixes."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"6aca0fd6000000001403b6f3":{"note":{"title":"UK Travel Guide 9min","desc":"Must see in London #travel","type":"video","user":{"nickname":"Taoyii桃一","userId":"54d20e612e1d9334e94bed8a"},"video":{"duration":565000,"consumer":{"originVideoKey":"video_key_uk"}},"imageList":[{"fileId":"1040g00832654b3lbkq004017n9763rcaj57lbio","urlDefault":"http://sns-webpic-qc.xhscdn.com/hash/1040g00832654b3lbkq004017n9763rcaj57lbio!nd_dft_wlteh_webp_3","urlPre":"http://sns-webpic-qc.xhscdn.com/hash/1040g00832654b3lbkq004017n9763rcaj57lbio!nd_prv_wlteh_webp_3","width":2880,"height":3839}]}}}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            u = "https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3?source=webshare&xhsshare=pc_web&xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7-E4hzzoV8gEq9oNjM=&xsec_source=pc_share"
            items = self.adapter.extract_entries(u)

            self.assertEqual(len(items), 1)
            item = items[0]
            # Should be direct uncompressed master image URL without !nd_prv or !nd_dft suffix
            self.assertEqual(item.cover_art_url, "https://sns-img-qc.xhscdn.com/1040g00832654b3lbkq004017n9763rcaj57lbio")
            self.assertEqual(item.cover_art_width, 2880)
            self.assertEqual(item.cover_art_height, 3839)
            self.assertEqual(item.extra_metadata.get("thumbnail_url"), "https://sns-img-qc.xhscdn.com/1040g00832654b3lbkq004017n9763rcaj57lbio")

    def test_thumbnail_manager_direct_master_download(self):
        """Verifies ThumbnailManager retrieves direct master image without delegating to yt-dlp preview."""
        from core.models import DownloadSettings, ThumbnailFormat
        from downloader.thumbnail_manager import ThumbnailManager
        import io
        from PIL import Image

        # Generate fake uncompressed JPEG image
        img = Image.new("RGB", (2880, 3839), color=(200, 100, 50))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG", quality=95)
        raw_jpeg_data = img_bytes.getvalue()

        video = VideoItem(
            index=1,
            video_id="6aca0fd6000000001403b6f3",
            title="High Res RedNote Note",
            duration="09:25",
            status=VideoStatus.READY,
            url="https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3",
            channel_title="Taoyii桃一",
            platform="rednote",
            cover_art_url="https://sns-img-qc.xhscdn.com/1040g00832654b3lbkq004017n9763rcaj57lbio",
        )
        settings = DownloadSettings(
            download_thumbnail=True,
            thumbnail_format=ThumbnailFormat.JPG,
        )

        mock_url_resp = MagicMock()
        mock_url_resp.read.return_value = raw_jpeg_data
        mock_url_resp.__enter__.return_value = mock_url_resp

        with patch("urllib.request.urlopen", return_value=mock_url_resp), \
             patch("downloader.thumbnail_manager.yt_dlp.YoutubeDL") as mock_ydl:
            target_out = Path(self.tmp_dir.name) / "thumb_test"
            target_out.mkdir(parents=True, exist_ok=True)

            res = ThumbnailManager.download_thumbnail(
                video=video,
                settings=settings,
                target_dir=target_out,
            )

            self.assertTrue(res["success"])
            self.assertIsNotNone(res["saved_file"])
            # yt-dlp should NOT have been invoked because direct master download succeeded
            self.assertFalse(mock_ydl.called)

            saved = Path(res["saved_file"])
            self.assertTrue(saved.exists())
            with Image.open(saved) as im:
                self.assertEqual(im.size, (2880, 3839))
                self.assertEqual(im.format, "JPEG")

    def test_rednote_photo_note_extraction_with_livephoto(self):
        """Verifies multi-image photo note extraction and LivePhoto video streams."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"note":{"noteDetailMap":{"photo_note_123":{"note":{"title":"London Highlights 🇬🇧","desc":"Spring in London #travel","type":"normal","user":{"nickname":"LondonTraveler","userId":"user_london_01"},"originalCommentIds":new Set([]),"activeMap":new Map(),"status":undefined,"imageList":[{"fileId":"fid_photo_01","width":1080,"height":1440,"livePhoto":true,"stream":{"h264":[{"masterUrl":"https://sns-video-qc.xhscdn.com/live_01.mp4"}]}},{"fileId":"fid_photo_02","width":1080,"height":1440,"livePhoto":false},{"urlDefault":"http://sns-webpic-qc.xhscdn.com/hash/fid_photo_03!nd_dft_wlteh_webp_3","width":1080,"height":1440}]}}}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            u = "https://www.xiaohongshu.com/discovery/item/photo_note_123?xsec_token=token_abc"
            items = self.adapter.extract_entries(u)

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.media_type, MediaType.PHOTO)
            self.assertEqual(item.formatted_duration, "3P")
            self.assertEqual(item.cover_art_url, "https://sns-img-qc.xhscdn.com/fid_photo_01")
            self.assertEqual(item.extra_metadata.get("photo_count"), 3)
            self.assertEqual(
                item.extra_metadata.get("photo_urls"),
                [
                    "https://sns-img-qc.xhscdn.com/fid_photo_01",
                    "https://sns-img-qc.xhscdn.com/fid_photo_02",
                    "http://sns-webpic-qc.xhscdn.com/hash/fid_photo_03",
                ],
            )
            self.assertEqual(
                item.extra_metadata.get("live_photo_urls"),
                {1: "https://sns-video-qc.xhscdn.com/live_01.mp4"},
            )

            # Test scan() returns source_type="photo" for photo note
            scan_res = self.adapter.scan(u)
            self.assertEqual(scan_res.source_type, "photo")
            self.assertEqual(scan_res.source_title, "LondonTraveler")

    def test_rednote_photo_note_formatted_duration(self):
        """Verifies formatted_duration returns {count}P for photos and time strings for videos."""
        v_photo_multi = VideoItem(
            index=1,
            video_id="p1",
            title="9 Photos",
            duration="Photo",
            status=VideoStatus.READY,
            media_type=MediaType.PHOTO,
            extra_metadata={"photo_count": 9},
        )
        self.assertEqual(v_photo_multi.formatted_duration, "9P")

        v_photo_single = VideoItem(
            index=2,
            video_id="p2",
            title="1 Photo",
            duration="Photo",
            status=VideoStatus.READY,
            media_type=MediaType.PHOTO,
            extra_metadata={"photo_count": 1},
        )
        self.assertEqual(v_photo_single.formatted_duration, "1P")

        v_photo_zero = VideoItem(
            index=3,
            video_id="p3",
            title="0 Photos",
            duration="Photo",
            status=VideoStatus.READY,
            media_type=MediaType.PHOTO,
            extra_metadata={"photo_count": 0},
        )
        self.assertEqual(v_photo_zero.formatted_duration, "-")

        v_video = VideoItem(
            index=4,
            video_id="v1",
            title="Video Item",
            duration="09:25",
            status=VideoStatus.READY,
            media_type=MediaType.VIDEO,
            duration_seconds=565,
        )
        self.assertEqual(v_video.formatted_duration, "09:25")

    def test_rednote_photo_note_download_manager_pipeline_and_archive(self):
        """Verifies DownloadManager internal pipeline downloads images, LivePhoto clips, converts format, and updates archive."""
        import io
        from PIL import Image
        from core.models import DownloadSettings
        from downloader.download_manager import DownloadManager

        img = Image.new("RGB", (200, 200), color=(120, 180, 240))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        fake_jpg_bytes = buf.getvalue()
        fake_mp4_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"

        def fake_opener_open(req, *args, **kwargs):
            url_str = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
            resp = MagicMock()
            if url_str.endswith(".mp4") or "live" in url_str:
                resp.read.return_value = fake_mp4_bytes
            else:
                resp.read.return_value = fake_jpg_bytes
            resp.__enter__.return_value = resp
            return resp

        archive_path = Path(self.tmp_dir.name) / "test_download_archive.txt"
        dest_dir = Path(self.tmp_dir.name) / "dl_dest"

        video = VideoItem(
            index=1,
            video_id="rn_photo_dl_001",
            title="London Travel Notes",
            duration="2P",
            status=VideoStatus.READY,
            url="https://www.xiaohongshu.com/discovery/item/rn_photo_dl_001",
            channel_title="Taoyii桃一",
            platform="rednote",
            media_type=MediaType.PHOTO,
            cover_art_url="https://sns-img-qc.xhscdn.com/img1",
            extra_metadata={
                "is_photo": True,
                "photo_count": 2,
                "photo_urls": [
                    "https://sns-img-qc.xhscdn.com/img1",
                    "https://sns-img-qc.xhscdn.com/img2",
                ],
                "live_photo_urls": {
                    1: "https://sns-video-qc.xhscdn.com/live1.mp4",
                },
                "description": "Lovely sights in London!",
                "media_type": "PHOTO",
            },
        )

        settings = DownloadSettings(
            download_folder=str(dest_dir),
            channel_title="Taoyii桃一",
            create_channel_folder=True,
            create_individual_video_folders=False,
            image_format="PNG",
            image_quality="100% (Best)",
            save_metadata=True,
            save_description=True,
            skip_existing=True,
        )

        with patch("urllib.request.build_opener") as mock_bld, \
             patch("downloader.download_manager.get_archive_file", return_value=str(archive_path)):
            mock_op = MagicMock()
            mock_op.open.side_effect = fake_opener_open
            mock_bld.return_value = mock_op

            dm = DownloadManager([video], settings)
            dm.run()

            # First run: should succeed and download
            self.assertEqual(video.status, VideoStatus.COMPLETED)

            note_dir = dest_dir / "Taoyii桃一" / "London Travel Notes"
            self.assertTrue(note_dir.is_dir(), f"Note folder should exist at {note_dir}")

            p1 = note_dir / "London Travel Notes_01.png"
            p1_live = note_dir / "London Travel Notes_01_live.mp4"
            p2 = note_dir / "London Travel Notes_02.png"
            meta = note_dir / "London Travel Notes.metadata.txt"
            desc = note_dir / "London Travel Notes.description"

            self.assertTrue(p1.exists(), "Photo 1 should exist as PNG")
            self.assertTrue(p1_live.exists(), "Live Photo 1 MP4 should exist")
            self.assertTrue(p2.exists(), "Photo 2 should exist as PNG")
            self.assertTrue(meta.exists(), "Metadata text file should exist")
            self.assertTrue(desc.exists(), "Description file should exist")

            with Image.open(p1) as im:
                self.assertEqual(im.format, "PNG")

            # Check archive file contains entry
            self.assertTrue(archive_path.exists())
            with open(archive_path, "r", encoding="utf-8") as af:
                lines = [l.strip() for l in af]
            self.assertIn("rednote rn_photo_dl_001", lines)

            # Second run: should be skipped because of archive file
            video_second = VideoItem(
                index=1,
                video_id="rn_photo_dl_001",
                title="London Travel Notes",
                duration="2P",
                status=VideoStatus.READY,
                url="https://www.xiaohongshu.com/discovery/item/rn_photo_dl_001",
                channel_title="Taoyii桃一",
                platform="rednote",
                media_type=MediaType.PHOTO,
                extra_metadata={
                    "is_photo": True,
                    "photo_count": 2,
                    "photo_urls": [
                        "https://sns-img-qc.xhscdn.com/img1",
                        "https://sns-img-qc.xhscdn.com/img2",
                    ],
                    "media_type": "PHOTO",
                },
            )

            dm2 = DownloadManager([video_second], settings)
            dm2.run()
            self.assertEqual(video_second.status, VideoStatus.SKIPPED)

    def test_profile_scan_creator_decomposes_photos_and_videos(self):
        """Verifies creator profile scan decomposes items into Photos and Videos with proper metadata."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"Taoyii桃一","redId":"taoyii123"},"notes":[{"noteId":"photo_001","displayTitle":"London Afternoon Tea 🫖","type":"normal","xsecToken":"token_photo_1","cover":{"fileId":"fid_tea_cover","width":1080,"height":1440},"imageList":[{"fileId":"f1"},{"fileId":"f2"},{"fileId":"f3"}]},{"noteId":"video_002","displayTitle":"UK Travel Vlog 9min 🔥","type":"video","xsecToken":"token_video_2","cover":{"fileId":"fid_vlog_cover","width":1080,"height":1920},"video":{"duration":565000,"consumer":{"originVideoKey":"orig_key_vlog"}}}]}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            profile_url = "https://www.xiaohongshu.com/user/profile/54d20e612e1d9334e94bed8a"
            res = self.adapter.scan(profile_url)

            self.assertEqual(res.source_title, "Taoyii桃一")
            self.assertEqual(res.source_type, "creator")
            self.assertEqual(res.platform, "rednote")
            self.assertEqual(len(res.videos), 2)

            # Item 1: Photo note
            p_item = res.videos[0]
            self.assertEqual(p_item.video_id, "photo_001")
            self.assertEqual(p_item.title, "London Afternoon Tea 🫖")
            self.assertEqual(p_item.media_type, MediaType.PHOTO)
            self.assertEqual(p_item.formatted_duration, "3P")
            self.assertEqual(p_item.cover_art_url, "https://sns-img-qc.xhscdn.com/fid_tea_cover")
            self.assertEqual(p_item.extra_metadata.get("photo_count"), 3)
            self.assertTrue(p_item.extra_metadata.get("is_photo"))
            self.assertEqual(p_item.extra_metadata.get("uploader"), "Taoyii桃一")
            self.assertIn("xsec_token=token_photo_1", p_item.url)

            # Item 2: Video note
            v_item = res.videos[1]
            self.assertEqual(v_item.video_id, "video_002")
            self.assertEqual(v_item.title, "UK Travel Vlog 9min 🔥")
            self.assertEqual(v_item.media_type, MediaType.VIDEO)
            self.assertEqual(v_item.duration_seconds, 565)
            self.assertEqual(v_item.formatted_duration, "09:25")
            self.assertEqual(v_item.cover_art_url, "https://sns-img-qc.xhscdn.com/fid_vlog_cover")
            self.assertFalse(v_item.extra_metadata.get("is_photo"))
            self.assertEqual(
                v_item.extra_metadata.get("origin_video_url"),
                "https://sns-video-bd.xhscdn.com/orig_key_vlog",
            )
            self.assertIn("xsec_token=token_video_2", v_item.url)

    def test_profile_scan_waterfall_2d_columns_flattening(self):
        """Verifies multi-column waterfall layout in userPageData is interleaved into ordered notes."""
        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"TravelBlogger"},"notes":[[{"noteId":"col0_row0","displayTitle":"Post 1","type":"normal","xsecToken":"t1"},{"noteId":"col0_row1","displayTitle":"Post 3","type":"video","xsecToken":"t3"}],[{"noteId":"col1_row0","displayTitle":"Post 2","type":"video","xsecToken":"t2"},{"noteId":"col1_row1","displayTitle":"Post 4","type":"normal","xsecToken":"t4"}]]}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            profile_url = "https://www.rednote.com/user/profile/5c31698d0000000007018a31"
            items = self.adapter.extract_entries(profile_url)

            self.assertEqual(len(items), 4)
            # Should be interleaved in chronological order: row 0 cols, row 1 cols
            self.assertEqual([it.video_id for it in items], ["col0_row0", "col1_row0", "col0_row1", "col1_row1"])
            self.assertEqual(items[0].media_type, MediaType.PHOTO)
            self.assertEqual(items[1].media_type, MediaType.VIDEO)
            self.assertEqual(items[2].media_type, MediaType.VIDEO)
            self.assertEqual(items[3].media_type, MediaType.PHOTO)

    def test_profile_scan_manager_rednote_integration(self):
        """Verifies ProfileScanManager coordinates RedNote creator scans and populates inventory."""
        from downloader.profile_scan_manager import ProfileScanManager
        from core.inventory import ProfileMediaInventory

        fake_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"InventoryCreator"},"notes":[{"noteId":"rn_inv_p1","displayTitle":"Inventory Photo","type":"normal","xsecToken":"tok_inv_1","cover":{"fileId":"fid_p1"}},{"noteId":"rn_inv_v2","displayTitle":"Inventory Video","type":"video","xsecToken":"tok_inv_2","video":{"duration":120000,"consumer":{"originVideoKey":"orig_inv_key"}}}]}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            inv_db_path = Path(self.tmp_dir.name) / "test_inventory.db"
            inv = ProfileMediaInventory(db_path=inv_db_path)
            mgr = ProfileScanManager(inventory=inv)

            profile_url = "https://www.xiaohongshu.com/user/profile/5c31698d0000000007018a31"
            res = mgr.scan_profile(url=profile_url, platform="rednote")

            self.assertEqual(res.source_title, "InventoryCreator")
            self.assertEqual(res.source_type, "creator")
            self.assertEqual(len(res.videos), 2)

            # Check inventory persistence
            prof_rec = inv.get_profile(platform="rednote", profile_url=profile_url)
            self.assertIsNotNone(prof_rec)
            self.assertEqual(prof_rec.discovered_posts_count, 2)
            self.assertEqual(prof_rec.discovered_media_count, 2)

            posts = inv.get_posts_for_profile("rednote", profile_url)
            self.assertEqual(len(posts), 2)
            post_types = {p.post_type for p in posts}
            self.assertIn("photo", post_types)
            self.assertIn("video", post_types)

            media_items = inv.get_media_items_for_profile("rednote", profile_url)
            self.assertEqual(len(media_items), 2)
            item_types = {m.media_type for m in media_items}
            self.assertIn(MediaInventoryType.IMAGE, item_types)
            self.assertIn(MediaInventoryType.VIDEO, item_types)

    def test_profile_scan_error_handling(self):
        """Verifies clear error reporting when creator profile lacks initial state or redirects to login."""
        fake_blocked_html = """
        <!DOCTYPE html>
        <html><head><title>Login Required</title></head>
        <body><div class="login-container">Please login to view user profile</div></body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_blocked_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            profile_url = "https://www.xiaohongshu.com/user/profile/5c31698d0000000007018a31"
            with self.assertRaises(RuntimeError) as cm:
                self.adapter.extract_entries(profile_url)
            self.assertIn("REDNOTE_PROFILE_BLOCKED", str(cm.exception))

    def test_profile_scan_guest_mode_note_id_masked(self):
        """Verifies that creator profile SSR with masked noteId in guest mode falls back to fileId without dropping items."""
        fake_guest_html = """
        <!DOCTYPE html>
        <html><body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"DIOR迪奥"},"notes":[[{"id":"","noteCard":{"noteId":"","displayTitle":"Dior Holiday Video","type":"video","xsecToken":"tok_vid","cover":{"urlDefault":"http://sns-web-i10.rednotecdn.com/202611061459/c868a28e9334ed5b8ed6cddac1d168d8/1040g00832755l92p70205n4skivk1o8uoo0n99g!nc_n_webp_mw_1","width":1080,"height":1351}}},{"id":"","noteCard":{"noteId":"","displayTitle":"Dior Holiday Photo","type":"normal","xsecToken":"tok_photo","cover":{"urlDefault":"http://sns-web-i10.rednotecdn.com/202611061459/e1770d68538229950adf6e3aa316c3ea/1040g2sg32754emf978q05n4skivk1o8ugbgtodg!nc_n_webp_mw_1","width":1800,"height":2250}}}]]}}};</script>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_guest_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.build_opener") as mock_opener_cls:
            mock_opener = MagicMock()
            mock_opener.open.return_value = mock_resp
            mock_opener_cls.return_value = mock_opener

            logs = []
            profile_url = "https://www.rednote.com/user/profile/5c9ca4bf000000001000e11e"
            items = self.adapter._extract_profile_entries(
                user_id="5c9ca4bf000000001000e11e",
                profile_url=profile_url,
                log_callback=logs.append,
            )

            self.assertEqual(len(items), 2)
            # Both items resolved via fallback fileId
            self.assertEqual(items[0].video_id, "1040g00832755l92p70205n4skivk1o8uoo0n99g")
            self.assertEqual(items[0].title, "Dior Holiday Video")
            self.assertEqual(items[0].media_type, MediaType.VIDEO)
            self.assertEqual(items[0].cover_art_url, "https://sns-img-qc.xhscdn.com/1040g00832755l92p70205n4skivk1o8uoo0n99g")

            self.assertEqual(items[1].video_id, "1040g2sg32754emf978q05n4skivk1o8ugbgtodg")
            self.assertEqual(items[1].title, "Dior Holiday Photo")
            self.assertEqual(items[1].media_type, MediaType.PHOTO)
            self.assertEqual(items[1].cover_art_url, "https://sns-img-qc.xhscdn.com/1040g2sg32754emf978q05n4skivk1o8ugbgtodg")
            self.assertEqual(items[1].extra_metadata.get("photo_urls"), ["https://sns-img-qc.xhscdn.com/1040g2sg32754emf978q05n4skivk1o8ugbgtodg"])

            # Verify guest mode notice logged
            self.assertTrue(any("guest browsing mode" in log for log in logs))


if __name__ == "__main__":
    unittest.main()
