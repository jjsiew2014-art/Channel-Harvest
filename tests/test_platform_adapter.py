"""
test_platform_adapter.py
Unit tests for the Platform Adapter architecture, capabilities, detection, and registry.
"""

import unittest
from core.models import VideoItem, VideoStatus
from core.platform import (
    PlatformCapabilities,
    PlatformAdapter,
    PlatformDetector,
    PlatformRegistry,
    YouTubeAdapter,
)


class TestPlatformAdapterArchitecture(unittest.TestCase):
    """Verifies the multi-platform adapter layer contract and detection rules."""

    def test_platform_detector_youtube(self):
        """Verify standard YouTube URLs are detected as 'youtube'."""
        urls = [
            "https://www.youtube.com/@PythonSimplified",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "http://m.youtube.com/playlist?list=PL12345",
        ]
        for u in urls:
            self.assertEqual(PlatformDetector.identify_platform_id(u), "youtube", f"Failed for {u}")

    def test_platform_detector_tiktok(self):
        """Verify TikTok URLs are detected as 'tiktok'."""
        urls = [
            "https://www.tiktok.com/@creator",
            "https://www.tiktok.com/@creator/video/7123456789012345678",
            "https://vm.tiktok.com/ZM8abcde/",
            "https://vt.tiktok.com/ZS8abcde/",
        ]
        for u in urls:
            self.assertEqual(PlatformDetector.identify_platform_id(u), "tiktok", f"Failed for {u}")

    def test_platform_detector_douyin(self):
        """Verify Douyin URLs are detected as 'douyin'."""
        urls = [
            "https://www.douyin.com/user/MS4wLjABAAAA...",
            "https://www.douyin.com/video/7123456789012345678",
            "https://v.douyin.com/iABCdeF/",
            "https://www.iesdouyin.com/share/video/7123456789012345678",
        ]
        for u in urls:
            self.assertEqual(PlatformDetector.identify_platform_id(u), "douyin", f"Failed for {u}")

    def test_platform_detector_unknown(self):
        """Verify unsupported or invalid URLs return 'unknown'."""
        urls = [
            "https://example.com/video",
            "https://vimeo.com/12345678",
            "not a url",
            "",
        ]
        for u in urls:
            self.assertEqual(PlatformDetector.identify_platform_id(u), "unknown", f"Failed for {u}")

    def test_youtube_adapter_registration(self):
        """Verify YouTubeAdapter is registered in the PlatformRegistry."""
        adapter = PlatformRegistry.get_adapter("youtube")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.platform_id, "youtube")
        self.assertEqual(adapter.display_name, "YouTube")

        # Test lookup by URL
        matched = PlatformRegistry.get_adapter_for_url("https://www.youtube.com/@Channel")
        self.assertIs(matched, adapter)

    def test_youtube_capabilities(self):
        """Verify YouTube capabilities matrix."""
        adapter = PlatformRegistry.get_adapter("youtube")
        caps = adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertTrue(caps.supports_subtitles)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertTrue(caps.supports_chapters)
        self.assertTrue(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertTrue(caps.supports_browser_cookies)
        self.assertTrue(caps.supports_cookie_file)
        self.assertEqual(caps.archive_prefix, "youtube")

    def test_video_item_extension_fields(self):
        """Verify VideoItem supports platform and extra_metadata while keeping backward compatibility."""
        v = VideoItem(
            index=1,
            video_id="12345",
            title="Test Video",
            duration="01:23",
        )
        self.assertEqual(v.platform, "youtube")
        self.assertEqual(v.extra_metadata, {})

        # Test custom platform and metadata
        v_custom = VideoItem(
            index=2,
            video_id="67890",
            title="TikTok Clip",
            duration="00:15",
            platform="tiktok",
            extra_metadata={"author_id": "user123", "sound_id": "sound456"},
        )
        self.assertEqual(v_custom.platform, "tiktok")
        self.assertEqual(v_custom.extra_metadata["author_id"], "user123")


    def test_extract_entries_signatures_consistency(self):
        """Verify extract_entries signatures across all adapters agree on auth_config parameter."""
        import inspect
        from core.platform.douyin import DouyinAdapter
        from core.platform.tiktok import TikTokAdapter
        from downloader.ytdlp_engine import YtDlpEngine

        classes_to_check = [
            (PlatformAdapter, "extract_entries"),
            (YouTubeAdapter, "extract_entries"),
            (TikTokAdapter, "extract_entries"),
            (DouyinAdapter, "extract_entries"),
            (YtDlpEngine, "extract_channel_entries"),
        ]

        for cls, method_name in classes_to_check:
            method = getattr(cls, method_name)
            sig = inspect.signature(method)
            self.assertIn(
                "auth_config",
                sig.parameters,
                f"{cls.__name__}.{method_name} must accept 'auth_config'",
            )
            param = sig.parameters["auth_config"]
            self.assertEqual(
                param.default,
                None,
                f"{cls.__name__}.{method_name} 'auth_config' default must be None",
            )

    def test_youtube_extract_entries_with_auth_config_no_typeerror(self):
        """Verify YouTubeAdapter.extract_entries accepts auth_config without TypeError."""
        adapter = YouTubeAdapter()
        from core.platform.auth import PlatformAuthConfig
        fake_auth = PlatformAuthConfig(auth_method="browser", browser_name="firefox")
        fake_entries = [
            VideoItem(index=1, video_id="vid123", title="Video 1", duration="01:00")
        ]

        from downloader.ytdlp_engine import YtDlpEngine
        from unittest.mock import patch
        with patch.object(YtDlpEngine, "extract_channel_entries", return_value=fake_entries) as mock_extract:
            results = adapter.extract_entries(
                url="https://www.youtube.com/@Veritasium",
                auth_config=fake_auth,
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].platform, "youtube")
            mock_extract.assert_called_once()
            _, kwargs = mock_extract.call_args
            self.assertEqual(kwargs.get("auth_config"), fake_auth)

    def test_youtube_extract_entries_backward_compatibility(self):
        """Verify YouTubeAdapter.extract_entries works with legacy call patterns (no auth_config)."""
        adapter = YouTubeAdapter()
        fake_entries = [
            VideoItem(index=1, video_id="vid123", title="Video 1", duration="01:00")
        ]

        from downloader.ytdlp_engine import YtDlpEngine
        from unittest.mock import patch
        with patch.object(YtDlpEngine, "extract_channel_entries", return_value=fake_entries) as mock_extract:
            # 1. Positional URL only
            results = adapter.extract_entries("https://www.youtube.com/@Veritasium")
            self.assertEqual(len(results), 1)
            mock_extract.assert_called_once()

            # 2. Legacy browser_cookies and custom_cookie_file
            mock_extract.reset_mock()
            results = adapter.extract_entries(
                url="https://www.youtube.com/@Veritasium",
                log_callback=lambda msg: None,
                browser_cookies="chrome",
                custom_cookie_file="/path/to/cookies.txt",
            )
            self.assertEqual(len(results), 1)
            mock_extract.assert_called_once()

    def test_tiktok_extract_entries_with_auth_config_no_typeerror(self):
        """Verify TikTokAdapter.extract_entries accepts auth_config without TypeError."""
        from core.platform.tiktok import TikTokAdapter
        from core.platform.auth import PlatformAuthConfig
        adapter = TikTokAdapter()
        fake_auth = PlatformAuthConfig.none()

        from unittest.mock import patch, MagicMock
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = {
                "_type": "playlist",
                "entries": [
                    {"id": "71234567890", "title": "TikTok clip", "duration": 15}
                ]
            }
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            results = adapter.extract_entries(
                url="https://www.tiktok.com/@creator",
                auth_config=fake_auth,
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].platform, "tiktok")

    def test_channel_scan_worker_youtube_with_auth_config_end_to_end(self):
        """Regression test: verify ChannelScanWorker executes YouTube scan with auth_config without TypeError."""
        from PySide6.QtCore import QCoreApplication
        from downloader.ytdlp_engine import ChannelScanWorker
        from core.platform.auth import PlatformAuthConfig
        from unittest.mock import patch, MagicMock
        app = QCoreApplication.instance() or QCoreApplication([])

        auth = PlatformAuthConfig(auth_method="browser", browser_name="edge")
        worker = ChannelScanWorker(
            url="https://www.youtube.com/@Veritasium",
            auth_config=auth,
            platform_id="youtube",
        )

        completed_videos = []
        errors = []
        worker.scan_completed.connect(completed_videos.extend)
        worker.scan_error.connect(errors.append)

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            captured_opts = {}
            def mock_ydl_init(opts):
                captured_opts.update(opts)
                mock_inst = MagicMock()
                mock_inst.extract_info.return_value = {
                    "_type": "playlist",
                    "entries": [
                        {"id": "abc12345", "title": "Test Title", "duration": 120}
                    ]
                }
                mock_ydl_inst = MagicMock()
                mock_ydl_inst.__enter__.return_value = mock_inst
                mock_ydl_inst.__exit__.return_value = None
                return mock_ydl_inst

            mock_ydl_cls.side_effect = mock_ydl_init

            worker.run()

            self.assertEqual(len(errors), 0, f"Worker produced error: {errors}")
            self.assertEqual(len(completed_videos), 1)
            self.assertEqual(completed_videos[0].video_id, "abc12345")
            self.assertEqual(completed_videos[0].platform, "youtube")
            self.assertIn("cookiesfrombrowser", captured_opts)
            self.assertEqual(captured_opts["cookiesfrombrowser"][0], "edge")


if __name__ == "__main__":
    unittest.main()
