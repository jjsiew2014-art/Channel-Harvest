"""
tests/test_skip_downloaded_media.py
Tests verifying that the 'skip downloaded media' setting properly controls whether
already downloaded files are skipped or re-downloaded / overwritten across all engines
(yt-dlp, gallery-dl, internal pipelines).
"""

import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.settings import SettingsManager
from downloader.download_manager import DownloadManager
from downloader.ytdlp_engine import YtDlpEngine, find_completed_final_file
from downloader.gallerydl_engine import GalleryDlEngine


class TestSkipDownloadedMedia(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_settings_manager_synchronization(self):
        """Verify skip_downloaded_media and skip_existing are synchronized in SettingsManager."""
        sm = SettingsManager()
        sm.set("skip_downloaded_media", False)
        self.assertFalse(sm.get("skip_downloaded_media"))
        self.assertFalse(sm.get("skip_existing"))

        sm.set("skip_downloaded_media", True)
        self.assertTrue(sm.get("skip_downloaded_media"))
        self.assertTrue(sm.get("skip_existing"))

        sm.set("skip_existing", False)
        self.assertFalse(sm.get("skip_downloaded_media"))
        self.assertFalse(sm.get("skip_existing"))

    def test_02_download_settings_model_synchronization(self):
        """Verify DownloadSettings post_init synchronizes skip_downloaded_media and skip_existing."""
        s1 = DownloadSettings(skip_downloaded_media=False, skip_existing=False)
        self.assertFalse(s1.skip_downloaded_media)
        self.assertFalse(s1.skip_existing)

        s2 = DownloadSettings(skip_downloaded_media=True, skip_existing=False)
        self.assertTrue(s2.skip_downloaded_media)
        self.assertTrue(s2.skip_existing)

        s3 = DownloadSettings(skip_downloaded_media=False, skip_existing=True)
        self.assertTrue(s3.skip_downloaded_media)
        self.assertTrue(s3.skip_existing)

    def test_03_ytdlp_options_when_skip_is_disabled(self):
        """Verify yt-dlp receives overwrites=True and continuedl=False when skip_existing is False."""
        captured_opts = {}

        def mock_extract_info(url, download=True):
            return {"id": "test_vid", "title": "Test Video"}

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl_instance = MagicMock()
            mock_ydl_instance.__enter__.return_value = mock_ydl_instance
            mock_ydl_instance.extract_info.side_effect = mock_extract_info
            mock_ydl_cls.side_effect = lambda opts: (captured_opts.update(opts), mock_ydl_instance)[1]

            engine = YtDlpEngine()
            video = VideoItem(index=1, video_id="vid_123", title="Sample Title", duration="03:30", url="https://www.youtube.com/watch?v=vid_123")
            settings = DownloadSettings(
                download_mode=DownloadMode.VIDEO_ONLY,
                skip_downloaded_media=False,
                skip_existing=False,
            )

            res = engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.target_dir,
            )

            self.assertTrue(res["success"])
            self.assertFalse(res["skipped"])
            self.assertTrue(captured_opts.get("overwrites"), "overwrites must be True when skip is disabled")
            self.assertFalse(captured_opts.get("continuedl"), "continuedl must be False when skip is disabled")
            self.assertNotIn("download_archive", captured_opts, "download_archive must not be used when skip is disabled")

    def test_04_ytdlp_options_when_skip_is_enabled(self):
        """Verify yt-dlp receives continuedl=True and overwrites=False when skip_existing is True."""
        captured_opts = {}

        def mock_extract_info(url, download=True):
            return {"id": "test_vid", "title": "Test Video"}

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl_instance = MagicMock()
            mock_ydl_instance.__enter__.return_value = mock_ydl_instance
            mock_ydl_instance.extract_info.side_effect = mock_extract_info
            mock_ydl_cls.side_effect = lambda opts: (captured_opts.update(opts), mock_ydl_instance)[1]

            engine = YtDlpEngine()
            video = VideoItem(index=1, video_id="vid_123", title="Sample Title", duration="03:30", url="https://www.youtube.com/watch?v=vid_123")
            settings = DownloadSettings(
                download_mode=DownloadMode.VIDEO_ONLY,
                skip_downloaded_media=True,
                skip_existing=True,
            )

            res = engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.target_dir,
            )

            self.assertTrue(res["success"])
            self.assertTrue(captured_opts.get("continuedl"), "continuedl must be True when skip is enabled")
            self.assertFalse(captured_opts.get("overwrites"), "overwrites must be False when skip is enabled")

    def test_05_recover_from_range_error_honors_skip_setting(self):
        """Verify recover_from_range_error only returns ALREADY_COMPLETE when skip_existing is True."""
        # Create a pre-existing completed file
        test_file = self.target_dir / "Sample Title [vid_123].mp4"
        test_file.write_bytes(b"existing video content")

        video = VideoItem(index=1, video_id="vid_123", title="Sample Title", duration="03:30")

        # Case A: skip_existing is True -> returns ALREADY_COMPLETE and preserves file
        status_true = YtDlpEngine.recover_from_range_error(
            video=video,
            target_dir=self.target_dir,
            recovery_attempt=1,
            skip_existing=True,
        )
        self.assertEqual(status_true, "ALREADY_COMPLETE")
        self.assertTrue(test_file.exists())

        # Case B: skip_existing is False -> removes conflicting file to allow clean fresh overwrite
        status_false = YtDlpEngine.recover_from_range_error(
            video=video,
            target_dir=self.target_dir,
            recovery_attempt=1,
            skip_existing=False,
        )
        self.assertNotEqual(status_false, "ALREADY_COMPLETE")
        self.assertFalse(test_file.exists(), "Conflicting file should be unlinked for fresh overwrite")

    def test_06_gallerydl_no_skip_argument(self):
        """Verify gallery-dl is passed --no-skip when skip_existing is False."""
        captured_args = []

        def mock_execute(args, **kwargs):
            captured_args.extend(args)
            return (0, "Success", "")

        g_engine = GalleryDlEngine()
        g_engine._execute_process = mock_execute

        # Download with skip_existing=False
        res = g_engine.download_media(
            url="https://www.instagram.com/p/test12345/",
            target_dir=self.target_dir,
            filename_stem="test_post",
            skip_existing=False,
        )
        self.assertIn("--no-skip", captured_args)
        self.assertFalse(res["skipped"])

    def test_07_download_manager_does_not_skip_when_disabled(self):
        """Verify DownloadManager executes download and marks COMPLETED when skip is False."""
        video = VideoItem(index=1, video_id="v999", title="Music Track", duration="03:30", url="https://www.youtube.com/watch?v=v999")
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            download_folder=str(self.target_dir),
            create_channel_folder=False,
            create_individual_video_folders=False,
            skip_downloaded_media=False,
            skip_existing=False,
        )

        # Pre-create completed file on disk
        dest_file = self.target_dir / "Music Track.mp4"
        dest_file.write_bytes(b"old media content")

        mock_engine = MagicMock()
        mock_engine.download_single_video.return_value = {
            "success": True,
            "skipped": False,
            "info_dict": {"id": "v999", "title": "Music Track"},
        }

        dm = DownloadManager([video], settings)
        dm.engine = mock_engine

        statuses = []
        dm.video_status_changed.connect(lambda vid, st, msg: statuses.append(st))

        dm.run()

        # Must not be skipped
        self.assertEqual(video.status, VideoStatus.COMPLETED)
        self.assertIn(VideoStatus.COMPLETED, statuses)
        self.assertNotIn(VideoStatus.SKIPPED, statuses)


if __name__ == "__main__":
    unittest.main()
