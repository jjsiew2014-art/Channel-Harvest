"""
test_metadata_templates.py
Comprehensive unit test suite for platform-specific metadata templates in Channel Harvest.
Validates YouTube, TikTok, Bilibili, and Generic fallback formatters, dispatching logic,
security credential scrubbing, and UTF-8 file export.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.models import VideoItem, DownloadSettings, VideoStatus
from metadata.base_formatter import BaseMetadataFormatter
from metadata.youtube_formatter import YouTubeMetadataFormatter
from metadata.tiktok_formatter import TikTokMetadataFormatter
from metadata.bilibili_formatter import BilibiliMetadataFormatter
from metadata.generic_formatter import GenericMetadataFormatter
from metadata.metadata_exporter import MetadataExporter
from downloader.info_manager import InfoManager


class TestYouTubeMetadataFormatter(unittest.TestCase):
    """Tests for the dedicated YouTube metadata TXT formatter."""

    def setUp(self):
        self.formatter = YouTubeMetadataFormatter()

    def test_properties(self):
        self.assertEqual(self.formatter.platform_id, "youtube")
        self.assertEqual(self.formatter.platform_display_name, "YouTube")

    def test_full_youtube_metadata_formatting(self):
        info = {
            "title": "Quantum Computers Explained",
            "id": "JhHMJCUmq28",
            "uploader": "Kurzgesagt – In a Nutshell",
            "channel": "Kurzgesagt – In a Nutshell",
            "channel_id": "UCsXVk37bltHxD1rDPwtNM8Q",
            "channel_url": "https://www.youtube.com/channel/UCsXVk37bltHxD1rDPwtNM8Q",
            "upload_date": "20151208",
            "duration": 465,
            "webpage_url": "https://www.youtube.com/watch?v=JhHMJCUmq28",
            "view_count": 12345678,
            "like_count": 456789,
            "comment_count": 12345,
            "channel_follower_count": 21000000,
            "description": "Where are the limits of human knowledge?",
            "tags": ["Science", "Physics", "Quantum"],
            "categories": ["Education"],
            "chapters": [
                {"start_time": 0, "title": "Introduction"},
                {"start_time": 120, "title": "Qubits and Superposition"},
            ],
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "vcodec": "avc1.640028",
            "acodec": "mp4a.40.2",
            "audio_channels": 2,
            "asr": 44100,
            "language": "en",
            "format_id": "137+140",
            "ext": "mp4",
            "filesize": 52428800,
            "extractor_key": "Youtube",
        }
        video = VideoItem(
            index=1,
            video_id="JhHMJCUmq28",
            title="Quantum Computers Explained",
            duration="07:45",
            status=VideoStatus.READY,
            platform="youtube",
        )

        output = self.formatter.format(info, video)

        # Verify all expected sections exist
        self.assertIn("VIDEO INFORMATION", output)
        self.assertIn("STATISTICS", output)
        self.assertIn("DESCRIPTION", output)
        self.assertIn("TAGS", output)
        self.assertIn("CATEGORIES", output)
        self.assertIn("CHAPTERS", output)
        self.assertIn("OTHER INFORMATION", output)

        # Verify YouTube terminology
        self.assertIn("Channel:\nKurzgesagt – In a Nutshell", output)
        self.assertIn("Channel ID:\nUCsXVk37bltHxD1rDPwtNM8Q", output)
        self.assertIn("Channel Followers:\n21,000,000", output)
        self.assertIn("View Count:\n12,345,678", output)
        self.assertIn("Like Count:\n456,789", output)
        self.assertIn("Upload Date:\n2015-12-08", output)
        self.assertIn("Duration:\n07:45", output)
        self.assertIn("02:00 Qubits and Superposition", output)

    def test_missing_fields_graceful_handling(self):
        info = {"id": "test123"}
        output = self.formatter.format(info)
        self.assertIn("Title:\nN/A", output)
        self.assertIn("View Count:\nN/A", output)
        self.assertIn("TAGS", output)
        self.assertIn("None", output)
        self.assertNotIn("NoneType", output)


class TestTikTokMetadataFormatter(unittest.TestCase):
    """Tests for the dedicated TikTok metadata TXT formatter."""

    def setUp(self):
        self.formatter = TikTokMetadataFormatter()

    def test_properties(self):
        self.assertEqual(self.formatter.platform_id, "tiktok")
        self.assertEqual(self.formatter.platform_display_name, "TikTok")

    def test_full_tiktok_metadata_formatting(self):
        info = {
            "id": "7106594312292453678",
            "title": "When you try your best but you don't succeed #comedy #viral",
            "description": "When you try your best but you don't succeed #comedy #viral cc: @coolfriend",
            "uploader": "khaby.lame",
            "uploader_id": "khaby.lame",
            "channel": "Khaby Lame",
            "channel_id": "MS4wLjABAAAA...",
            "channel_url": "https://www.tiktok.com/@khaby.lame",
            "upload_date": "20220608",
            "duration": 25,
            "view_count": 85000000,
            "like_count": 12000000,
            "comment_count": 85000,
            "repost_count": 450000,
            "save_count": 620000,
            "channel_follower_count": 160000000,
            "track": "Original Sound - Khaby Lame",
            "artist": "Khaby Lame",
            "album": "TikTok Sounds",
            "width": 1080,
            "height": 1920,
            "fps": 60,
            "vcodec": "h264",
            "acodec": "aac",
            "ext": "mp4",
            "filesize": 15728640,
            "extractor_key": "TikTok",
        }
        video = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="When you try your best",
            duration="00:25",
            status=VideoStatus.READY,
            platform="tiktok",
            extra_metadata={
                "uploader": "@khaby.lame",
                "uploader_id": "khaby.lame",
            },
        )

        output = self.formatter.format(info, video)

        # Expected TikTok sections
        self.assertIn("VIDEO INFORMATION", output)
        self.assertIn("CREATOR INFORMATION", output)
        self.assertIn("ENGAGEMENT STATISTICS", output)
        self.assertIn("TIKTOK CONTENT & SOUND", output)
        self.assertIn("TECHNICAL & DOWNLOAD INFORMATION", output)
        self.assertIn("DESCRIPTION", output)

        # Verify TikTok specific vocabulary
        self.assertIn("Creator:\nKhaby Lame", output)
        self.assertIn("Handle:\n@khaby.lame", output)
        self.assertIn("Profile URL:\nhttps://www.tiktok.com/@khaby.lame", output)
        self.assertIn("Followers:\n160,000,000", output)

        # Engagement
        self.assertIn("Play Count:\n85,000,000", output)
        self.assertIn("Like Count:\n12,000,000", output)
        self.assertIn("Comment Count:\n85,000", output)
        self.assertIn("Share Count:\n450,000", output)
        self.assertIn("Collect Count:\n620,000", output)

        # Content & Sound
        self.assertIn("Sound Title:\nOriginal Sound - Khaby Lame", output)
        self.assertIn("Sound Artist:\nKhaby Lame", output)
        self.assertIn("Original Sound:\nYes", output)
        self.assertIn("Hashtags:\n#comedy, #viral", output)
        self.assertIn("Mentions:\n@coolfriend", output)

        # Strictly check that YouTube vocabulary is absent
        self.assertNotIn("Channel ID:", output)
        self.assertNotIn("Channel URL:", output)
        self.assertNotIn("Channel Followers:", output)
        self.assertNotIn("Subscribers", output)

    def test_tiktok_missing_sound_and_hashtags(self):
        info = {
            "id": "12345",
            "title": "Minimal TikTok",
            "description": "Simple description without tags",
        }
        output = self.formatter.format(info)
        self.assertIn("Sound Title:\nN/A", output)
        self.assertIn("Hashtags:\nNone", output)
        self.assertIn("Mentions:\nNone", output)


class TestBilibiliMetadataFormatter(unittest.TestCase):
    """Tests for the dedicated Bilibili metadata TXT formatter."""

    def setUp(self):
        self.formatter = BilibiliMetadataFormatter()

    def test_properties(self):
        self.assertEqual(self.formatter.platform_id, "bilibili")
        self.assertEqual(self.formatter.platform_display_name, "Bilibili")

    def test_single_bilibili_video_formatting(self):
        info = {
            "id": "BV1xx411c7mD",
            "bvid": "BV1xx411c7mD",
            "aid": 170001,
            "cid": 280001,
            "title": "Let's learn Python together",
            "uploader": "科技UP主",
            "uploader_id": "374756250",
            "uploader_url": "https://space.bilibili.com/374756250",
            "upload_date": "20230501",
            "duration": 612,
            "view_count": 5200000,
            "like_count": 340000,
            "coin_count": 280000,
            "favorite_count": 410000,
            "share_count": 50000,
            "comment_count": 18000,
            "danmaku_count": 92000,
            "channel_follower_count": 1250000,
            "category": "科技",
            "subcategory": "计算机技术",
            "copyright": 1,
            "description": "欢迎大家一起学习 Python！记得一键三连哦！",
            "width": 1920,
            "height": 1080,
            "fps": 60,
            "vcodec": "avc1.640028",
            "acodec": "mp4a.40.2",
            "ext": "mp4",
            "filesize": 88000000,
            "extractor_key": "BiliBili",
        }
        video = VideoItem(
            index=1,
            video_id="BV1xx411c7mD",
            title="Let's learn Python together",
            duration="10:12",
            status=VideoStatus.READY,
            platform="bilibili",
            extra_metadata={
                "bvid": "BV1xx411c7mD",
                "uploader": "科技UP主",
                "uploader_id": "374756250",
            },
        )

        output = self.formatter.format(info, video)

        # Expected sections
        self.assertIn("BASIC VIDEO INFORMATION", output)
        self.assertIn("UPLOADER INFORMATION", output)
        self.assertIn("ENGAGEMENT STATISTICS", output)
        self.assertIn("BILIBILI VIDEO DETAILS", output)
        self.assertIn("SOURCE & COLLECTION INFORMATION", output)
        self.assertIn("TECHNICAL & DOWNLOAD INFORMATION", output)
        self.assertIn("DESCRIPTION", output)

        # Identifiers
        self.assertIn("BVID:\nBV1xx411c7mD", output)
        self.assertIn("AID:\nav170001", output)
        self.assertIn("CID:\n280001", output)

        # Uploader
        self.assertIn("Uploader (UP主):\n科技UP主", output)
        self.assertIn("MID:\n374756250", output)
        self.assertIn("Space URL:\nhttps://space.bilibili.com/374756250", output)
        self.assertIn("Followers:\n1,250,000", output)

        # Engagement including unique Bilibili metrics
        self.assertIn("View Count (播放量):\n5,200,000", output)
        self.assertIn("Like Count (点赞):\n340,000", output)
        self.assertIn("Coin Count (投币):\n280,000", output)
        self.assertIn("Favorite Count (收藏):\n410,000", output)
        self.assertIn("Danmaku Count (弹幕):\n92,000", output)

        # Details
        self.assertIn("Category (主分区):\n科技", output)
        self.assertIn("Subcategory (子分区):\n计算机技术", output)
        self.assertIn("Copyright (版权):\nOriginal (自制)", output)

        # Strictly check that YouTube vocabulary is absent
        self.assertNotIn("Channel ID:", output)
        self.assertNotIn("Channel URL:", output)
        self.assertNotIn("Channel Followers:", output)
        self.assertNotIn("Subscribers", output)

    def test_multi_part_bilibili_video(self):
        info = {
            "id": "BV1MultiPart",
            "bvid": "BV1MultiPart",
            "title": "Tutorial Series",
        }
        video = VideoItem(
            index=2,
            video_id="BV1MultiPart_p2",
            title="Tutorial Series p02 Setting Up",
            duration="05:30",
            status=VideoStatus.READY,
            platform="bilibili",
            url="https://www.bilibili.com/video/BV1MultiPart?p=2",
            extra_metadata={
                "bvid": "BV1MultiPart",
                "part_number": 2,
                "part_title": "Setting Up",
                "cid": 998877,
                "total_parts": 10,
            },
        )

        output = self.formatter.format(info, video)
        self.assertIn("Part Number (分P序号):\nP2", output)
        self.assertIn("Part Title (分P标题):\nSetting Up", output)
        self.assertIn("CID:\n998877", output)
        self.assertIn("Total Parts (总P数):\n10", output)
        self.assertIn("Webpage URL:\nhttps://www.bilibili.com/video/BV1MultiPart?p=2", output)


class TestGenericMetadataFormatter(unittest.TestCase):
    """Tests for the generic fallback metadata formatter."""

    def setUp(self):
        self.formatter = GenericMetadataFormatter()

    def test_properties(self):
        self.assertEqual(self.formatter.platform_id, "generic")
        self.assertEqual(self.formatter.platform_display_name, "Generic Video")

    def test_generic_output_neutral_labels(self):
        info = {
            "id": "generic_001",
            "title": "Custom Video",
            "uploader": "Indie Author",
            "upload_date": "20240101",
            "duration": 180,
            "view_count": 500,
            "description": "Neutral platform description.",
        }
        output = self.formatter.format(info)

        self.assertIn("MEDIA INFORMATION", output)
        self.assertIn("Media ID:\ngeneric_001", output)
        self.assertIn("Creator / Uploader:\nIndie Author", output)
        self.assertIn("ENGAGEMENT STATISTICS", output)
        self.assertIn("View Count:\n500", output)

        # Verify no platform specific headers
        self.assertNotIn("Channel ID:", output)
        self.assertNotIn("BVID:", output)
        self.assertNotIn("UP主", output)
        self.assertNotIn("Sound Artist:", output)


class TestMetadataExporter(unittest.TestCase):
    """Tests for platform dispatching, security sanitization, and UTF-8 file writing."""

    def test_dispatcher_resolution(self):
        # By explicit platform string
        self.assertIsInstance(MetadataExporter.get_formatter(platform_id="youtube"), YouTubeMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(platform_id="tiktok"), TikTokMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(platform_id="bilibili"), BilibiliMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(platform_id="unknown_site"), GenericMetadataFormatter)

        # By VideoItem platform
        v_yt = VideoItem(index=1, video_id="1", title="yt", duration="1:00", status=VideoStatus.READY, platform="youtube")
        v_tt = VideoItem(index=2, video_id="2", title="tt", duration="1:00", status=VideoStatus.READY, platform="tiktok")
        v_bili = VideoItem(index=3, video_id="3", title="bili", duration="1:00", status=VideoStatus.READY, platform="bilibili")
        self.assertIsInstance(MetadataExporter.get_formatter(video=v_yt), YouTubeMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(video=v_tt), TikTokMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(video=v_bili), BilibiliMetadataFormatter)

        # By extractor_key in info
        self.assertIsInstance(MetadataExporter.get_formatter(info={"extractor_key": "Youtube"}), YouTubeMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(info={"extractor_key": "TikTok"}), TikTokMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(info={"extractor_key": "Bilibili"}), BilibiliMetadataFormatter)
        self.assertIsInstance(MetadataExporter.get_formatter(info={"extractor_key": "Vimeo"}), GenericMetadataFormatter)

    def test_credential_sanitization(self):
        """Ensures that auth cookies, SESSDATA, and tokens are scrubbed from exported metadata."""
        info = {
            "id": "leak_test",
            "title": "Secret Video",
            "description": "Check this auth: SESSDATA=abc123xyz456; and token bili_jct=secret_token_123; also Bearer eyJhbGciOi...",
        }
        output = MetadataExporter.export_metadata_txt(info, platform_id="bilibili")

        self.assertNotIn("abc123xyz456", output)
        self.assertNotIn("secret_token_123", output)
        self.assertNotIn("eyJhbGciOi", output)
        self.assertIn("[REDACTED_CREDENTIAL]", output)

    def test_utf8_file_writing(self):
        """Verifies explicit UTF-8 encoding with Chinese characters, emojis, and special punctuation."""
        info = {
            "id": "BV1utf8test",
            "bvid": "BV1utf8test",
            "title": "测试中文标题 🚀 & Special Characters (日本語・한국어)",
            "uploader": "创作者 🎉",
            "description": "详细描述：支持多语言与特殊表情符号 🌟\nLine 2",
        }
        with TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output_test.metadata.txt"
            success = MetadataExporter.save_metadata_file(dest, info, platform_id="bilibili")
            self.assertTrue(success)
            self.assertTrue(dest.is_file())

            content = dest.read_text(encoding="utf-8")
            self.assertIn("测试中文标题 🚀", content)
            self.assertIn("创作者 🎉", content)
            self.assertIn("🌟", content)

    def test_safe_file_writing_invalid_path(self):
        """Verifies that an unwritable target path logs a warning and returns False without crashing."""
        logs = []
        # Non-existent drive or invalid character path on Windows
        invalid_path = "Z:\\nonexistent_drive_987654\\sub\\test.metadata.txt"
        success = MetadataExporter.save_metadata_file(
            invalid_path,
            {"title": "Test"},
            log_callback=lambda msg: logs.append(msg),
        )
        self.assertFalse(success)
        self.assertTrue(any("Failed to save metadata" in l for l in logs))

    def test_infomanager_backward_compatibility(self):
        """Ensures InfoManager.format_metadata_txt delegates correctly and retains existing API contract."""
        info = {
            "title": "Delegation Test",
            "id": "dQw4w9WgXcQ",
            "extractor_key": "Youtube",
            "view_count": 1000,
        }
        output = InfoManager.format_metadata_txt(info)
        self.assertIn("VIDEO INFORMATION", output)
        self.assertIn("Delegation Test", output)
        self.assertIn("View Count:\n1,000", output)


if __name__ == "__main__":
    unittest.main()
