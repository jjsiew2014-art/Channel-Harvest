"""
test_rednote_metadata_and_audio_fallback.py
Unit tests for RedNote dedicated metadata formatter and direct-stream audio-only extraction fallback.
Channel Harvest - RedNote Integration.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.models import VideoItem, MediaType, DownloadMode, DownloadSettings, VideoStatus
from core.inventory import MediaInventoryType
from metadata.rednote_formatter import RedNoteMetadataFormatter
from metadata.metadata_exporter import MetadataExporter
from downloader.engine_router import DownloadEngineRouter, EngineType
from downloader.download_manager import DownloadManager
from downloader.ytdlp_engine import DownloaderError


class TestRedNoteMetadataFormatter(unittest.TestCase):
    """Tests for RedNote dedicated metadata TXT formatting."""

    def setUp(self) -> None:
        self.formatter = RedNoteMetadataFormatter()

    def test_platform_identifiers(self) -> None:
        self.assertEqual(self.formatter.platform_id, "rednote")
        self.assertIn("RedNote", self.formatter.platform_display_name)
        self.assertIn("小红书", self.formatter.platform_display_name)

    def test_format_video_note_metadata(self) -> None:
        video = VideoItem(
            index=1,
            video_id="6aca0fd6000000001403b6f3",
            title="9min保姆级英国旅行攻略",
            duration="09:12",
            duration_seconds=552,
            url="https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3",
            channel_title="Taoyii桃一",
            platform="rednote",
            media_type=MediaType.VIDEO,
            extra_metadata={
                "uploader": "Taoyii桃一",
                "uploader_id": "5c9ca4bf000000001000e11e",
                "red_id": "taoyii_uk",
                "liked_count": 12850,
                "collected_count": 9430,
                "comment_count": 820,
                "share_count": 3150,
                "ip_location": "英国",
                "upload_timestamp": 1715000000,
                "tags": ["英国旅行", "伦敦生活", "攻略"],
                "origin_video_key": "spectrum/origin_video_12345",
                "origin_video_url": "https://sns-video-bd.xhscdn.com/spectrum/origin_video_12345",
                "description": "这是详细的9分钟英国自由行攻略，含签证与交通！#伦敦大笨钟 #旅行分享",
            },
        )
        info = {
            "id": video.video_id,
            "title": video.title,
            "webpage_url": video.url,
        }

        output = self.formatter.format(info, video=video)

        self.assertIn("REDNOTE VIDEO POST METADATA", output)
        self.assertIn("9min保姆级英国旅行攻略", output)
        self.assertIn("6aca0fd6000000001403b6f3", output)
        self.assertIn("Video Note (视频笔记)", output)
        self.assertIn("Taoyii桃一", output)
        self.assertIn("5c9ca4bf000000001000e11e", output)
        self.assertIn("taoyii_uk", output)
        self.assertIn("12,850", output)
        self.assertIn("9,430", output)
        self.assertIn("820", output)
        self.assertIn("3,150", output)
        self.assertIn("英国", output)
        self.assertIn("#英国旅行", output)
        self.assertIn("#伦敦大笨钟", output)
        self.assertIn("spectrum/origin_video_12345", output)
        self.assertIn("https://sns-video-bd.xhscdn.com/spectrum/origin_video_12345", output)
        self.assertIn("这是详细的9分钟英国自由行攻略", output)

    def test_format_photo_and_live_photo_note(self) -> None:
        video = VideoItem(
            index=1,
            video_id="65f123450000000001020304",
            title="周末法式复古胶片风穿搭",
            duration="Photo",
            duration_seconds=0,
            url="https://www.xiaohongshu.com/discovery/item/65f123450000000001020304",
            channel_title="时尚博主小周",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "is_photo": True,
                "photo_count": 3,
                "photo_urls": [
                    "https://sns-img-qc.xhscdn.com/spectrum/photo1",
                    "https://sns-img-qc.xhscdn.com/spectrum/photo2",
                    "https://sns-img-qc.xhscdn.com/spectrum/photo3",
                ],
                "live_photo_urls": {
                    2: "https://sns-video-bd.xhscdn.com/live_clip_2.mp4",
                },
                "liked_count": 4200,
                "collected_count": 1800,
                "description": "今日法式OOTD穿搭打卡 #每日穿搭 #复古胶片",
            },
        )
        info = {
            "id": video.video_id,
            "title": video.title,
            "webpage_url": video.url,
            "media_type": "PHOTO",
        }

        output = self.formatter.format(info, video=video)

        self.assertIn("REDNOTE PHOTO POST METADATA", output)
        self.assertIn("Live Photo Note (实况图文", output)
        self.assertIn("Photo Count: 3", output)
        self.assertIn("Live Photo Clips: 1", output)
        self.assertIn("spectrum/photo1", output)
        self.assertIn("(Live Video Clip attached)", output)


class TestMetadataExporterRedNoteIntegration(unittest.TestCase):
    """Tests for MetadataExporter integration and credential scrubbing."""

    def test_exporter_resolves_rednote_formatter(self) -> None:
        fmt_explicit = MetadataExporter.get_formatter(platform_id="rednote")
        self.assertIsInstance(fmt_explicit, RedNoteMetadataFormatter)

        fmt_alias = MetadataExporter.get_formatter(platform_id="xiaohongshu")
        self.assertIsInstance(fmt_alias, RedNoteMetadataFormatter)

        video = VideoItem(index=1, video_id="test1", title="test", duration="1:00", platform="rednote")
        fmt_video = MetadataExporter.get_formatter(video=video)
        self.assertIsInstance(fmt_video, RedNoteMetadataFormatter)

        info_extractor = {"extractor_key": "XiaoHongShu"}
        fmt_extractor = MetadataExporter.get_formatter(info=info_extractor)
        self.assertIsInstance(fmt_extractor, RedNoteMetadataFormatter)

    def test_rednote_sensitive_credential_scrubbing(self) -> None:
        raw_text = (
            "User Session Log:\n"
            "Cookie: a1=18ecb94a20b08k9j; web_session=040069b18362402; "
            "webId=abcde12345; gid=yyd123456; \n"
            "URL: https://www.xiaohongshu.com/discovery/item/123?xsec_token=AB69S5DpiKQYe8DVHYqR6z-FeVe7&source=web\n"
        )
        sanitized = MetadataExporter.sanitize_credentials(raw_text)

        self.assertNotIn("18ecb94a20b08k9j", sanitized)
        self.assertNotIn("040069b18362402", sanitized)
        self.assertNotIn("abcde12345", sanitized)
        self.assertNotIn("AB69S5DpiKQYe8DVHYqR6z-FeVe7", sanitized)
        self.assertIn("[REDACTED_CREDENTIAL]", sanitized)


class TestRedNoteAudioRoutingAndFallback(unittest.TestCase):
    """Tests for DownloadEngineRouter audio routing and DownloadManager audio fallback."""

    def test_engine_router_allows_audio_fallback(self) -> None:
        router = DownloadEngineRouter()
        item = VideoItem(index=1, video_id="vid1", title="Title", duration="02:00", platform="rednote")
        item.extra_metadata["media_type"] = "VIDEO"

        # Explicit AUDIO routing
        decision = router._apply_routing_policy("rednote", MediaInventoryType.AUDIO, item.extra_metadata)
        self.assertEqual(decision.engine, EngineType.YTDLP)
        self.assertTrue(decision.can_fallback)
        self.assertEqual(decision.fallback_engine, EngineType.INTERNAL)

    def test_audio_only_direct_stream_extraction_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            video_item = VideoItem(
                index=1,
                video_id="6aca0fd6000000001403b6f3",
                title="Taoyii桃一 英国攻略",
                duration="05:00",
                duration_seconds=300,
                url="https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3",
                channel_title="Taoyii桃一",
                platform="rednote",
                media_type=MediaType.VIDEO,
                extra_metadata={
                    "origin_video_url": "https://sns-video-bd.xhscdn.com/test_video.mp4",
                    "description": "英国攻略文案",
                },
            )

            settings = DownloadSettings(
                download_mode=DownloadMode.AUDIO_ONLY,
                audio_format="MP3",
                audio_bitrate="320 kbps",
                download_folder=str(target_dir),
                create_channel_folder=False,
                create_individual_video_folders=False,
            )

            manager = DownloadManager(videos=[video_item], settings=settings)

            # Mock YtDlpEngine.download_video to simulate yt-dlp WAF failure triggering fallback
            def fake_download_video(*args, **kwargs):
                raise DownloaderError("yt-dlp blocked by RedNote login barrier", raw_error="Blocked")

            # Mock urlopen to return a dummy MP4 payload
            class FakeResponse:
                def __init__(self):
                    self.headers = {"Content-Length": "100"}
                    self._chunks = [b"FAKE_MP4_DATA_CHUNK"]

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, chunk_size):
                    return self._chunks.pop(0) if self._chunks else b""

            def fake_urlopen(req, *args, **kwargs):
                return FakeResponse()

            # Mock subprocess.run for FFmpeg to produce the output MP3 file
            def fake_subprocess_run(cmd, *args, **kwargs):
                if any(flag in cmd for flag in ("-vn", "-c")):
                    out_path = Path(cmd[-1])
                    if not str(out_path).startswith("-"):
                        out_path.write_bytes(b"FAKE_MP3_AUDIO_CONTENT")
                return mock.MagicMock(returncode=0)

            with (
                mock.patch("downloader.ytdlp_engine.YtDlpEngine.download_single_video", side_effect=fake_download_video),
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
                mock.patch("subprocess.run", side_effect=fake_subprocess_run),
                mock.patch("downloader.download_manager.get_bundled_executable", return_value=Path(tmpdir) / "ffmpeg.exe"),
            ):
                (Path(tmpdir) / "ffmpeg.exe").write_bytes(b"MZ")
                manager.run()

            # The resulting downloaded audio file should be an MP3
            expected_mp3 = target_dir / f"{video_item.title}.mp3"
            self.assertTrue(expected_mp3.is_file(), f"Expected audio file {expected_mp3} was not created")
            self.assertEqual(expected_mp3.read_bytes(), b"FAKE_MP3_AUDIO_CONTENT")

            # Intermediate .mp4 must have been cleaned up in AUDIO_ONLY mode
            intermediate_mp4 = target_dir / f"{video_item.title}.mp4"
            self.assertFalse(intermediate_mp4.exists(), "Intermediate MP4 file should be unlinked in Audio Only mode")

    def test_video_and_audio_direct_stream_companion_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            video_item = VideoItem(
                index=1,
                video_id="6aca0fd6000000001403b6f3",
                title="Taoyii桃一 英国攻略",
                duration="05:00",
                duration_seconds=300,
                url="https://www.xiaohongshu.com/discovery/item/6aca0fd6000000001403b6f3",
                channel_title="Taoyii桃一",
                platform="rednote",
                media_type=MediaType.VIDEO,
                extra_metadata={
                    "origin_video_url": "https://sns-video-bd.xhscdn.com/test_video.mp4",
                },
            )

            settings = DownloadSettings(
                download_mode=DownloadMode.VIDEO_AND_AUDIO,
                format="mp4",
                audio_format="M4A",
                download_folder=str(target_dir),
                create_channel_folder=False,
                create_individual_video_folders=False,
            )

            manager = DownloadManager(videos=[video_item], settings=settings)

            def fake_download_video(*args, **kwargs):
                raise DownloaderError("yt-dlp blocked", raw_error="Blocked")

            class FakeResponse:
                def __init__(self):
                    self.headers = {"Content-Length": "100"}
                    self._chunks = [b"FAKE_MP4_VIDEO_CONTENT"]

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, chunk_size):
                    return self._chunks.pop(0) if self._chunks else b""

            def fake_subprocess_run(cmd, *args, **kwargs):
                if any(flag in cmd for flag in ("-vn", "-c")):
                    out_path = Path(cmd[-1])
                    if not str(out_path).startswith("-"):
                        out_path.write_bytes(b"FAKE_M4A_AUDIO_CONTENT")
                return mock.MagicMock(returncode=0)

            with (
                mock.patch("downloader.ytdlp_engine.YtDlpEngine.download_single_video", side_effect=fake_download_video),
                mock.patch("urllib.request.urlopen", side_effect=lambda *args, **kwargs: FakeResponse()),
                mock.patch("subprocess.run", side_effect=fake_subprocess_run),
                mock.patch("downloader.download_manager.get_bundled_executable", return_value=Path(tmpdir) / "ffmpeg.exe"),
            ):
                (Path(tmpdir) / "ffmpeg.exe").write_bytes(b"MZ")
                manager.run()

            # In VIDEO_AND_AUDIO mode, BOTH video and companion audio must exist
            expected_mp4 = target_dir / f"{video_item.title}.mp4"
            expected_m4a = target_dir / f"{video_item.title}.m4a"
            self.assertTrue(expected_mp4.is_file(), "Video file should be preserved in Video + Audio mode")
            self.assertTrue(expected_m4a.is_file(), "Companion audio file should be created in Video + Audio mode")

    def test_photo_note_metadata_txt_generation_in_download_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            video_item = VideoItem(
                index=1,
                video_id="65f123450000000001020304",
                title="法式复古穿搭",
                duration="Photo",
                duration_seconds=0,
                url="https://www.xiaohongshu.com/discovery/item/65f123450000000001020304",
                channel_title="时尚博主小周",
                platform="rednote",
                media_type=MediaType.PHOTO,
                extra_metadata={
                    "is_photo": True,
                    "photo_count": 2,
                    "photo_urls": [
                        "https://sns-img-qc.xhscdn.com/spectrum/photo1",
                        "https://sns-img-qc.xhscdn.com/spectrum/photo2",
                    ],
                    "liked_count": 3500,
                    "collected_count": 1200,
                    "comment_count": 98,
                    "share_count": 45,
                    "ip_location": "上海",
                    "description": "法式复古穿搭分享 #每日穿搭 #复古",
                },
            )

            settings = DownloadSettings(
                download_mode=DownloadMode.IMAGE_ONLY,
                save_metadata=True,
                download_folder=str(target_dir),
                create_channel_folder=False,
                create_individual_video_folders=False,
            )

            manager = DownloadManager(videos=[video_item], settings=settings)

            class FakeImageResponse:
                def __init__(self):
                    self.headers = {"Content-Length": "50"}
                    self._chunks = [b"FAKE_JPEG_IMAGE_BYTES"]

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def read(self, *args):
                    return self._chunks.pop(0) if self._chunks else b""

            with (
                mock.patch("urllib.request.urlopen", side_effect=lambda *args, **kwargs: FakeImageResponse()),
                mock.patch("urllib.request.OpenerDirector.open", side_effect=lambda *args, **kwargs: FakeImageResponse()),
            ):
                manager.run()

            # Photo target dir is target_dir / video_item.title
            photo_dir = target_dir / video_item.title
            self.assertTrue(photo_dir.is_dir(), f"Expected directory {photo_dir} was not created")
            meta_file = photo_dir / f"{video_item.title}.metadata.txt"
            self.assertTrue(meta_file.is_file(), f"Metadata file {meta_file} was not generated")

            content = meta_file.read_text(encoding="utf-8")
            self.assertIn("REDNOTE PHOTO POST METADATA", content)
            self.assertIn("法式复古穿搭", content)
            self.assertIn("时尚博主小周", content)
            self.assertIn("3,500", content)
            self.assertIn("上海", content)
            self.assertIn("#每日穿搭", content)


if __name__ == "__main__":
    unittest.main()
