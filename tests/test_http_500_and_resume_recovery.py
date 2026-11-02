"""
tests/test_http_500_and_resume_recovery.py
Deterministic regression tests for YouTube HTTP 500 errors, interrupted download
recovery, and queue resilience in Channel Harvest.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.error_classifier import ErrorClassifier, ErrorCategory
from core.models import VideoItem, DownloadSettings, DownloadMode, VideoStatus
from downloader.download_manager import DownloadManager
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
    is_http_500_error,
    is_transient_retryable_error,
    find_video_partial_files,
)
from yt_dlp.utils import DownloadError


class TestHttp500AndResumeRecovery(unittest.TestCase):
    """
    Comprehensive deterministic test suite covering all requirements for
    handling HTTP 500 errors, resuming interrupted downloads, and preserving queue progress.
    """

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ch_test_500_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_sample_videos(self, count=3):
        return [
            VideoItem(
                index=i,
                video_id=f"vid_test_{i:03d}",
                title=f"Sample Track {i}",
                duration="03:30",
                platform="youtube",
                url=f"https://www.youtube.com/watch?v=vid_test_{i:03d}",
            )
            for i in range(1, count + 1)
        ]

    # -------------------------------------------------------------------------
    # 1. HTTP 500 followed by successful retry
    # -------------------------------------------------------------------------
    def test_1_http_500_followed_by_successful_retry(self):
        videos = self._create_sample_videos(1)
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )
        dm = DownloadManager(videos, settings)
        status_updates = []
        queue_finished = []

        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        attempts = 0
        def mock_download(video, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise DownloaderError(
                    "ERROR: unable to download video data: HTTP Error 500: Internal Server Error",
                    stage="audio",
                    raw_error="HTTP Error 500: Internal Server Error",
                )
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                # Use zero sleep for fast deterministic execution
                with patch.object(dm, "_cancelable_sleep", return_value=False):
                    dm.run()

        # Should have attempted twice and succeeded on attempt 2
        self.assertEqual(attempts, 2)
        v_statuses = [st for vid, st, msg in status_updates if vid == "vid_test_001"]
        self.assertTrue(any("Server Error Retry 2/3" in st for st in v_statuses))
        self.assertIn(VideoStatus.COMPLETED, v_statuses)
        self.assertEqual(queue_finished[0], (1, 0, 0, 1))

    # -------------------------------------------------------------------------
    # 2. Repeated HTTP 500 responses that exhaust the retry limit
    # -------------------------------------------------------------------------
    def test_2_repeated_http_500_exhausts_retry_limit(self):
        videos = self._create_sample_videos(1)
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )
        dm = DownloadManager(videos, settings)
        status_updates = []
        progress_updates = []
        queue_finished = []

        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.video_progress.connect(lambda vid, pct, d, t, sp, eta: progress_updates.append((vid, pct, sp)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        attempts = 0
        def mock_download(video, **kwargs):
            nonlocal attempts
            attempts += 1
            raise DownloaderError(
                "ERROR: [download] Got error: HTTP Error 500: Internal Server Error",
                stage="audio",
                raw_error="HTTP Error 500: Internal Server Error",
            )

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                with patch.object(dm, "_cancelable_sleep", return_value=False):
                    dm.run()

        # All 3 attempts should be executed
        self.assertEqual(attempts, 3)
        v_statuses = [st for vid, st, msg in status_updates if vid == "vid_test_001"]
        self.assertIn("Failed — HTTP 500", v_statuses)

        # Check that error tooltip contains clear user reason
        final_tooltips = [msg for vid, st, msg in status_updates if st == "Failed — HTTP 500"]
        self.assertTrue(len(final_tooltips) > 0)
        self.assertIn("Server temporarily unavailable after retries", final_tooltips[0])

        # Final progress must be 0.0% / "Failed"
        self.assertEqual(progress_updates[-1][1], 0.0)
        self.assertEqual(progress_updates[-1][2], "Failed")

        # Queue finished with 0 completed, 0 skipped, 1 failed
        self.assertEqual(queue_finished[0], (0, 0, 1, 1))

    # -------------------------------------------------------------------------
    # 3. HTTP 500 during a media fragment download
    # -------------------------------------------------------------------------
    def test_3_http_500_during_media_fragment_download(self):
        err_msg = "[download] Got error: HTTP Error 500: Internal Server Error"
        self.assertTrue(is_http_500_error(err_msg))
        self.assertTrue(is_transient_retryable_error(err_msg))

        err = ErrorClassifier.classify(
            raw_error=err_msg,
            stage="video",
            video_id="vid_frag_001",
        )
        self.assertEqual(err.category, ErrorCategory.HTTP_500)
        self.assertEqual(err.http_status, 500)
        self.assertTrue(err.retryable)
        self.assertIn("temporary internal error", err.user_message.lower())

    # -------------------------------------------------------------------------
    # 4. HTTP 500 during metadata extraction
    # -------------------------------------------------------------------------
    def test_4_http_500_during_metadata_extraction(self):
        engine = YtDlpEngine()
        url = "https://www.youtube.com/@SomeChannel"

        attempts = 0
        def fake_extract_info(url, download=False):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise DownloadError("HTTP Error 500: Internal Server Error")
            return {
                "title": "SomeChannel",
                "entries": [
                    {"id": "v1", "title": "Track 1", "duration": 180, "url": "https://youtube.com/watch?v=v1"}
                ]
            }

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_inst = MagicMock()
            mock_inst.extract_info.side_effect = fake_extract_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_inst

            with patch("time.sleep", return_value=None):
                items = engine.extract_channel_entries(url)

        self.assertEqual(attempts, 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].video_id, "v1")

    # -------------------------------------------------------------------------
    # 5. Recovery with fresh media URL when needed
    # -------------------------------------------------------------------------
    def test_5_recovery_with_fresh_media_url(self):
        engine = YtDlpEngine()
        video = self._create_sample_videos(1)[0]
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )

        attempts = 0
        def fake_extract(url, download=True):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                # Simulates stale URL expiring with 500
                raise DownloadError("HTTP Error 500: Internal Server Error")
            # Attempt 2 extracts fresh URL and succeeds
            return {"title": "Sample Track 1", "id": video.video_id}

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_inst = MagicMock()
            mock_inst.extract_info.side_effect = fake_extract
            mock_ydl_cls.return_value.__enter__.return_value = mock_inst

            # On attempt 1, download_single_video raises DownloaderError and preserves partial files
            with self.assertRaises(DownloaderError) as cm:
                engine.download_single_video(
                    video=video,
                    settings=settings,
                    target_dir=self.test_dir,
                )
            self.assertIn("500", str(cm.exception))

            # Attempt 2 (called by DownloadManager with fresh YoutubeDL instance)
            res = engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.test_dir,
            )
            self.assertTrue(res.get("success"))
            self.assertEqual(attempts, 2)

    # -------------------------------------------------------------------------
    # 6. Partial-file preservation and safe resume
    # -------------------------------------------------------------------------
    def test_6_partial_file_preservation_and_safe_resume(self):
        video = self._create_sample_videos(1)[0]
        engine = YtDlpEngine()
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )

        # Create a partial file representing interrupted download
        part_file = self.test_dir / f"Sample Track 1 [{video.video_id}].f251.webm.part"
        part_file.write_bytes(b"initial 1024 bytes of stream")

        # Other video file
        other_file = self.test_dir / "Other Song [vid_other].wav"
        other_file.write_bytes(b"complete audio")

        def fake_extract_500(url, download=True):
            raise DownloadError("HTTP Error 500: Internal Server Error")

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_inst = MagicMock()
            mock_inst.extract_info.side_effect = fake_extract_500
            mock_ydl_cls.return_value.__enter__.return_value = mock_inst

            with self.assertRaises(DownloaderError):
                engine.download_single_video(video, settings, self.test_dir)

        # The partial file must NOT be deleted during transient HTTP 500!
        self.assertTrue(part_file.exists())
        self.assertEqual(part_file.stat().st_size, 28)

        # When retries are exhausted, safe_cleanup_partial_files cleans it up
        engine.safe_cleanup_partial_files(self.test_dir, video.video_id, title=video.title)
        self.assertFalse(part_file.exists())
        # Unrelated file must remain intact
        self.assertTrue(other_file.exists())

    # -------------------------------------------------------------------------
    # 7. Queue continuation after the current item ultimately fails
    # -------------------------------------------------------------------------
    def test_7_queue_continuation_after_current_item_fails(self):
        videos = self._create_sample_videos(3)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)
        queue_finished = []
        logs = []

        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))
        dm.log_message.connect(lambda msg: logs.append(msg))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_002":
                raise DownloaderError(
                    "HTTP Error 500: Internal Server Error",
                    stage="video",
                    raw_error="HTTP Error 500: Internal Server Error",
                )
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                with patch.object(dm, "_cancelable_sleep", return_value=False):
                    dm.run()

        # Videos 1 and 3 succeeded, Video 2 failed
        self.assertEqual(queue_finished[0], (2, 0, 1, 3))
        self.assertTrue(any("Item 2/3 failed. Continuing to next item" in log for log in logs))

    # -------------------------------------------------------------------------
    # 8. User cancellation during a retry delay
    # -------------------------------------------------------------------------
    def test_8_user_cancellation_during_retry_delay(self):
        videos = self._create_sample_videos(3)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)
        status_updates = []
        queue_finished = []

        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        def mock_download(video, **kwargs):
            raise DownloaderError(
                "HTTP Error 500: Internal Server Error",
                stage="video",
                raw_error="HTTP Error 500: Internal Server Error",
            )

        def mock_sleep_cancel(seconds):
            # User cancels immediately when retry delay starts
            dm.cancel()
            return True

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                with patch.object(dm, "_cancelable_sleep", side_effect=mock_sleep_cancel):
                    dm.run()

        # All videos must reach CANCELLED, not stuck
        cancelled_statuses = [st for vid, st, msg in status_updates if st == VideoStatus.CANCELLED]
        self.assertTrue(len(cancelled_statuses) >= 3)
        self.assertTrue(dm.is_cancelled())

    # -------------------------------------------------------------------------
    # 9. Accurate final item status, progress, counters, and archive behavior
    # -------------------------------------------------------------------------
    def test_9_accurate_final_status_counters_and_archive(self):
        videos = self._create_sample_videos(2)
        archive_path = self.test_dir / "download_archive.txt"
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            skip_existing=True,
        )
        dm = DownloadManager(videos, settings)
        queue_finished = []
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_002":
                raise DownloaderError("HTTP Error 500: Internal Server Error", stage="video", raw_error="HTTP Error 500")
            # Video 1 succeeds: simulate write to archive
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with open(archive_path, "a", encoding="utf-8") as f:
                f.write(f"youtube {video.video_id}\n")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch("downloader.download_manager.get_archive_file", return_value=archive_path):
            with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
                with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                    with patch.object(dm, "_cancelable_sleep", return_value=False):
                        dm.run()

        # Only video 1 should be recorded in archive, never failed video 2
        self.assertTrue(archive_path.exists())
        content = archive_path.read_text(encoding="utf-8")
        self.assertIn("vid_test_001", content)
        self.assertNotIn("vid_test_002", content)
        self.assertEqual(queue_finished[0], (1, 0, 1, 2))

    # -------------------------------------------------------------------------
    # 10. Distinguish HTTP 500 from private and unavailable videos
    # -------------------------------------------------------------------------
    def test_10_distinguish_http_500_from_private_and_unavailable(self):
        err_500 = ErrorClassifier.classify("ERROR: unable to download video data: HTTP Error 500: Internal Server Error")
        self.assertEqual(err_500.category, ErrorCategory.HTTP_500)
        self.assertNotEqual(err_500.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertNotEqual(err_500.category, ErrorCategory.VIDEO_UNAVAILABLE)

        err_priv = ErrorClassifier.classify("ERROR: This video is private")
        self.assertEqual(err_priv.category, ErrorCategory.PRIVATE_VIDEO)

        err_unavail = ErrorClassifier.classify("ERROR: This video is unavailable")
        self.assertEqual(err_unavail.category, ErrorCategory.VIDEO_UNAVAILABLE)

        err_403 = ErrorClassifier.classify("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        self.assertEqual(err_403.category, ErrorCategory.HTTP_403)


if __name__ == "__main__":
    unittest.main()
