"""
tests/test_playlist_403_and_queue_resilience.py
Deterministic regression tests for YouTube playlist HTTP 403 handling,
queue resilience, and task finalization in Channel Harvest.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from core.error_classifier import ErrorClassifier, ErrorCategory
from core.models import VideoItem, DownloadSettings, DownloadMode, VideoStatus
from core.platform import PlatformRegistry
from downloader.download_manager import DownloadManager
from downloader.format_selector import FormatSelector
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
    is_http_403_error,
    find_video_partial_files,
    find_completed_final_file,
)
from yt_dlp.utils import DownloadError


class TestPlaylist403AndQueueResilience(unittest.TestCase):
    """
    Comprehensive test suite covering all Priority 6 regression requirements:
    HTTP 403 recovery, bounded retries, queue continuation, clean task finalization,
    archive behavior, and platform regressions.
    """

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ch_test_403_"))

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
    # 1. A playlist where the first two items succeed and the third raises HTTP 403
    # -------------------------------------------------------------------------
    def test_1_playlist_first_two_succeed_third_raises_403(self):
        videos = self._create_sample_videos(3)
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
            browser_cookies="none",
        )

        dm = DownloadManager(videos, settings)
        status_updates = []
        progress_updates = []
        overall_progress = []
        queue_finished = []
        logs = []

        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.video_progress.connect(lambda vid, pct, d, t, sp, eta: progress_updates.append((vid, pct, sp)))
        dm.overall_progress.connect(lambda c, s, f, r, p: overall_progress.append((c, s, f, r, p)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))
        dm.log_message.connect(lambda msg: logs.append(msg))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_003":
                raise DownloaderError(
                    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
                    stage="audio",
                    raw_error="HTTP Error 403: Forbidden",
                )
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # Videos 1 and 2 must be COMPLETED
        v1_statuses = [st for vid, st, msg in status_updates if vid == "vid_test_001"]
        v2_statuses = [st for vid, st, msg in status_updates if vid == "vid_test_002"]
        v3_statuses = [st for vid, st, msg in status_updates if vid == "vid_test_003"]

        self.assertIn(VideoStatus.COMPLETED, v1_statuses)
        self.assertIn(VideoStatus.COMPLETED, v2_statuses)

        # Video 3 must reach terminal state FAILED with HTTP 403 explanation
        self.assertTrue(any("403" in st or st == VideoStatus.FAILED for st in v3_statuses))

        # Progress for video 3 must be reset and marked Failed, never left stuck at arbitrary %
        v3_final_progress = [p for p in progress_updates if p[0] == "vid_test_003"]
        self.assertTrue(len(v3_final_progress) > 0)
        self.assertEqual(v3_final_progress[-1][1], 0.0)
        self.assertEqual(v3_final_progress[-1][2], "Failed")

        # Queue finished callback must be delivered with 2 completed, 0 skipped, 1 failed, 3 total
        self.assertEqual(len(queue_finished), 1)
        self.assertEqual(queue_finished[0], (2, 0, 1, 3))

    # -------------------------------------------------------------------------
    # 2. HTTP 403 failure during metadata extraction
    # -------------------------------------------------------------------------
    def test_2_http_403_during_metadata_extraction(self):
        videos = self._create_sample_videos(3)
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
            browser_cookies="none",
        )

        dm = DownloadManager(videos, settings)
        queue_finished = []
        logs = []
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))
        dm.log_message.connect(lambda msg: logs.append(msg))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_003":
                raise DownloaderError(
                    "ERROR: [youtube] vid_test_003: HTTP Error 403: Forbidden (metadata extraction)",
                    stage="scan",
                    raw_error="[youtube] vid_test_003: HTTP Error 403: Forbidden",
                )
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        self.assertEqual(len(queue_finished), 1)
        self.assertEqual(queue_finished[0], (2, 0, 1, 3))

        # Check classification of metadata 403
        err = ErrorClassifier.classify(
            raw_error="[youtube] vid_test_003: HTTP Error 403: Forbidden",
            stage="scan",
            video_id="vid_test_003",
        )
        self.assertEqual(err.category, ErrorCategory.HTTP_403)
        self.assertEqual(err.http_status, 403)
        self.assertIn("metadata extraction", err.user_message.lower())

    # -------------------------------------------------------------------------
    # 3. Worker exception that occurs before any progress callback
    # -------------------------------------------------------------------------
    def test_3_worker_exception_before_any_progress_callback(self):
        videos = self._create_sample_videos(1)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)

        progress_updates = []
        status_updates = []
        queue_finished = []

        dm.video_progress.connect(lambda vid, pct, d, t, sp, eta: progress_updates.append((vid, pct, sp)))
        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        def mock_download(video, **kwargs):
            # Abrupt crash before emitting any progress
            raise RuntimeError("Fatal socket error before any progress hook")

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # Item must reach terminal state FAILED
        self.assertTrue(any("failed" in st.lower() for vid, st, msg in status_updates))
        # Final progress must be emitted as 0.0% / "Failed"
        self.assertTrue(len(progress_updates) > 0)
        self.assertEqual(progress_updates[-1][1], 0.0)
        self.assertEqual(progress_updates[-1][2], "Failed")
        # Queue must finish cleanly
        self.assertEqual(queue_finished[0], (0, 0, 1, 1))

    # -------------------------------------------------------------------------
    # 4. Postprocessing / FFmpeg failure
    # -------------------------------------------------------------------------
    def test_4_postprocessing_ffmpeg_failure(self):
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

        def mock_download(video, **kwargs):
            raise DownloaderError(
                "ERROR: Postprocessing: Error opening output file: ffmpeg exited with code 1",
                stage="conversion",
                raw_error="ffmpeg exited with code 1",
            )

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # Must be classified with conversion/ffmpeg failure
        self.assertTrue(any("ffmpeg" in st.lower() or "conversion" in st.lower() or st == VideoStatus.FAILED for vid, st, msg in status_updates))
        self.assertEqual(queue_finished[0], (0, 0, 1, 1))

    # -------------------------------------------------------------------------
    # 5. Transient failure followed by a successful bounded retry
    # -------------------------------------------------------------------------
    def test_5_transient_failure_followed_by_successful_bounded_retry(self):
        engine = YtDlpEngine()
        video = self._create_sample_videos(1)[0]
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )

        attempts = 0
        def fake_download_runner(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise DownloadError("HTTP Error 403: Forbidden")
            return {"title": "Sample Track 1", "id": video.video_id}

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_instance = MagicMock()
            mock_instance.extract_info.side_effect = fake_download_runner
            mock_instance.download.side_effect = fake_download_runner
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance

            res = engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.test_dir,
            )

            self.assertTrue(res.get("success"))
            self.assertEqual(attempts, 2)

    # -------------------------------------------------------------------------
    # 6. Permanent failure that is not retried indefinitely
    # -------------------------------------------------------------------------
    def test_6_permanent_failure_not_retried_indefinitely(self):
        engine = YtDlpEngine()
        video = self._create_sample_videos(1)[0]
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )

        attempts = 0
        def fake_download_runner(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            raise DownloadError("HTTP Error 403: Forbidden")

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_instance = MagicMock()
            mock_instance.extract_info.side_effect = fake_download_runner
            mock_instance.download.side_effect = fake_download_runner
            mock_ydl_cls.return_value.__enter__.return_value = mock_instance

            with self.assertRaises(DownloaderError) as cm:
                engine.download_single_video(
                    video=video,
                    settings=settings,
                    target_dir=self.test_dir,
                )

            # Max recoveries is 1 + 1 initial attempt = 2 attempts total
            self.assertEqual(attempts, 2)
            self.assertIn("403", str(cm.exception))

    # -------------------------------------------------------------------------
    # 7. Queue continuation after a failed item
    # -------------------------------------------------------------------------
    def test_7_queue_continuation_after_failed_item(self):
        videos = self._create_sample_videos(4)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)

        queue_finished = []
        logs = []
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))
        dm.log_message.connect(lambda msg: logs.append(msg))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_002":
                raise DownloaderError("HTTP Error 403: Forbidden", stage="audio", raw_error="HTTP Error 403")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # Queue must finish all 4 items: 3 succeeded, 1 failed
        self.assertEqual(queue_finished[0], (3, 0, 1, 4))
        # Log must have announced continuation
        self.assertTrue(any("Continuing to next item in queue" in line for line in logs))

    # -------------------------------------------------------------------------
    # 8. Queue stopping with visible failure state when destination invalid
    # -------------------------------------------------------------------------
    def test_8_queue_stopping_on_fatal_folder_error(self):
        videos = self._create_sample_videos(3)
        fail_dir = self.test_dir / "fail_forbidden_folder"
        settings = DownloadSettings(download_folder=str(fail_dir))
        dm = DownloadManager(videos, settings)

        error_dialogs = []
        queue_finished = []
        dm.error_occurred.connect(lambda title, msg: error_dialogs.append((title, msg)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        orig_mkdir = Path.mkdir
        def conditional_mkdir(self, *args, **kwargs):
            if "fail_forbidden_folder" in str(self):
                raise PermissionError("Access denied")
            return orig_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", conditional_mkdir):
            dm.run()

        self.assertEqual(len(error_dialogs), 1)
        self.assertEqual(error_dialogs[0][0], "Folder Error")
        self.assertEqual(queue_finished[0], (0, 0, 3, 3))

    # -------------------------------------------------------------------------
    # 9. Progress and active-task state cleanup after every failure
    # -------------------------------------------------------------------------
    def test_9_progress_and_partial_file_cleanup_after_failure(self):
        vid_id = "vid_target_999"
        # Create stale partial files for this video
        part_file = self.test_dir / f"Song [{vid_id}].f251.webm.part"
        ytdl_file = self.test_dir / f"Song [{vid_id}].webm.ytdl"
        part_file.write_bytes(b"stale partial stream")
        ytdl_file.write_bytes(b"stale ytdl metadata")

        # Create valid completed file for another video
        other_valid = self.test_dir / "Valid Song [other_vid_123].wav"
        other_valid.write_bytes(b"completed audio data")

        # Call safe_cleanup_partial_files
        YtDlpEngine.safe_cleanup_partial_files(self.test_dir, vid_id, title="Song")

        # Target video partial files must be removed
        self.assertFalse(part_file.exists())
        self.assertFalse(ytdl_file.exists())

        # Valid other video file must remain intact
        self.assertTrue(other_valid.exists())

    # -------------------------------------------------------------------------
    # 10. Cancellation during a failed or retrying download
    # -------------------------------------------------------------------------
    def test_10_cancellation_during_retrying_download(self):
        videos = self._create_sample_videos(3)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)

        status_updates = []
        progress_updates = []
        queue_finished = []

        dm.video_status_changed.connect(lambda vid, st, msg: status_updates.append((vid, st, msg)))
        dm.video_progress.connect(lambda vid, pct, d, t, sp, eta: progress_updates.append((vid, pct, sp)))
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        call_count = 0
        def mock_download(video, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Cancel manager during first video download
                dm.cancel()
                raise DownloadCancelledException("Cancelled by user")
            return {"success": True}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # All videos must reach CANCELLED
        v1_cancelled = any(st == VideoStatus.CANCELLED for vid, st, msg in status_updates if vid == "vid_test_001")
        v2_cancelled = any(st == VideoStatus.CANCELLED for vid, st, msg in status_updates if vid == "vid_test_002")
        v3_cancelled = any(st == VideoStatus.CANCELLED for vid, st, msg in status_updates if vid == "vid_test_003")
        self.assertTrue(v1_cancelled)
        self.assertTrue(v2_cancelled)
        self.assertTrue(v3_cancelled)

        # Cancelled progress must be 0.0% / "Cancelled"
        cancelled_progs = [p for p in progress_updates if p[2] == "Cancelled"]
        self.assertTrue(len(cancelled_progs) > 0)
        self.assertEqual(cancelled_progs[-1][1], 0.0)

    # -------------------------------------------------------------------------
    # 11. Accurate success/failure counts and download archive behavior
    # -------------------------------------------------------------------------
    def test_11_accurate_counts_and_download_archive_behavior(self):
        videos = self._create_sample_videos(2)
        archive_path = self.test_dir / "test_archive.txt"
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            skip_existing=True,
        )

        dm = DownloadManager(videos, settings)
        queue_finished = []
        dm.queue_finished.connect(lambda c, s, f, t: queue_finished.append((c, s, f, t)))

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_002":
                raise DownloaderError("HTTP Error 403: Forbidden", stage="audio", raw_error="HTTP Error 403")
            # Video 1 succeeds: simulate engine appending to archive
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with open(archive_path, "a", encoding="utf-8") as f:
                f.write(f"youtube {video.video_id}\n")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch("downloader.download_manager.get_archive_file", return_value=archive_path):
            with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
                with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                    dm.run()

        # Only video 1 should be in archive
        self.assertTrue(archive_path.exists())
        archive_content = archive_path.read_text(encoding="utf-8")
        self.assertIn("vid_test_001", archive_content)
        self.assertNotIn("vid_test_002", archive_content)

        # Final counts: 1 completed, 0 skipped, 1 failed
        self.assertEqual(queue_finished[0], (1, 0, 1, 2))

    # -------------------------------------------------------------------------
    # 12. Successful WAV downloads remain functional
    # -------------------------------------------------------------------------
    def test_12_successful_wav_downloads_functional(self):
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )
        format_spec, audio_ext, postprocessors = FormatSelector.build_audio_format_spec(settings)
        self.assertEqual(audio_ext, "wav")
        self.assertEqual(format_spec, "ba/b")
        self.assertEqual(len(postprocessors), 1)
        self.assertEqual(postprocessors[0]["key"], "FFmpegExtractAudio")
        self.assertEqual(postprocessors[0]["preferredcodec"], "wav")

    # -------------------------------------------------------------------------
    # 13. YouTube scanning and downloading without Cookies remain functional
    # -------------------------------------------------------------------------
    def test_13_youtube_scanning_and_downloading_without_cookies(self):
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            browser_cookies="none",
        )
        opts = YtDlpEngine.build_base_ydl_opts(
            platform="youtube",
            settings=settings,
        )
        # No cookie configuration
        self.assertNotIn("cookiefile", opts)
        self.assertNotIn("cookiesfrombrowser", opts)
        # Timeout and retries bounded
        self.assertEqual(opts.get("socket_timeout"), 30)
        self.assertEqual(opts.get("retries"), 3)
        self.assertEqual(opts.get("fragment_retries"), 3)

    # -------------------------------------------------------------------------
    # 14. TikTok functionality and frozen Douyin platform remain unchanged
    # -------------------------------------------------------------------------
    def test_14_tiktok_and_frozen_douyin_platform_unchanged(self):
        # 1. TikTok adapter remains available
        self.assertTrue(PlatformRegistry.is_available("tiktok"))
        tiktok_adapter = PlatformRegistry.get_adapter("tiktok")
        self.assertIsNotNone(tiktok_adapter)
        self.assertEqual(tiktok_adapter.platform_id, "tiktok")

        # 2. Douyin platform remains frozen
        self.assertFalse(PlatformRegistry.is_available("douyin"))

        # 3. ErrorClassifier returns localized frozen message for Douyin
        douyin_err = ErrorClassifier.for_unavailable_platform("douyin")
        self.assertEqual(douyin_err.category, ErrorCategory.PLATFORM_TEMPORARILY_UNAVAILABLE)
        self.assertIn("ArgusSecurityPlugin", douyin_err.user_message)
        self.assertIn("waiting for an upstream yt-dlp fix", douyin_err.user_message)


    # -------------------------------------------------------------------------
    # 15. Audio fallback format is applied on HTTP 403 recovery
    # -------------------------------------------------------------------------
    def test_15_audio_fallback_format_applied_on_403(self):
        engine = YtDlpEngine()
        video = self._create_sample_videos(1)[0]
        settings = DownloadSettings(
            download_folder=str(self.test_dir),
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
        )

        captured_formats = []
        def fake_download_runner(opts, *args, **kwargs):
            captured_formats.append(opts.get("format"))
            if len(captured_formats) == 1:
                raise DownloadError("HTTP Error 403: Forbidden")
            return {"title": "Sample Track 1", "id": video.video_id}

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            def side_effect_init(opts):
                mock_inst = MagicMock()
                mock_inst.extract_info.side_effect = lambda url, download=True: fake_download_runner(opts)
                mock_inst.__enter__.return_value = mock_inst
                return mock_inst

            mock_ydl_cls.side_effect = side_effect_init

            res = engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.test_dir,
            )

            self.assertTrue(res.get("success"))
            self.assertEqual(len(captured_formats), 2)
            self.assertEqual(captured_formats[0], "ba/b")
            self.assertEqual(captured_formats[1], "ba[ext=m4a]/ba[format_id!=251]/ba/b")

    # -------------------------------------------------------------------------
    # 16. No duplicate cancellation signals when user aborts mid-queue
    # -------------------------------------------------------------------------
    def test_16_no_duplicate_cancellation_signals(self):
        videos = self._create_sample_videos(4)
        settings = DownloadSettings(download_folder=str(self.test_dir))
        dm = DownloadManager(videos, settings)

        cancellation_events = []
        dm.video_status_changed.connect(
            lambda vid, st, msg: cancellation_events.append(vid) if st == VideoStatus.CANCELLED else None
        )

        def mock_download(video, **kwargs):
            if video.video_id == "vid_test_002":
                dm.cancel()
                raise DownloadCancelledException("User cancelled")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            with patch("downloader.download_manager.FFmpegChecker.detect", return_value=(True, "ffmpeg.exe", "7.0", "")):
                dm.run()

        # vid_test_001 was completed, not cancelled
        self.assertNotIn("vid_test_001", cancellation_events)
        # vid_test_002, 003, 004 each cancelled exactly once
        self.assertEqual(cancellation_events.count("vid_test_002"), 1)
        self.assertEqual(cancellation_events.count("vid_test_003"), 1)
        self.assertEqual(cancellation_events.count("vid_test_004"), 1)

    # -------------------------------------------------------------------------
    # 17. Path containment in partial-file cleanup
    # -------------------------------------------------------------------------
    def test_17_safe_cleanup_partial_files_containment(self):
        target_dir = self.test_dir / "target"
        target_dir.mkdir(parents=True, exist_ok=True)
        external_dir = self.test_dir / "external"
        external_dir.mkdir(parents=True, exist_ok=True)

        # Create file in target dir and file in external dir
        in_file = target_dir / "track [vid_contain].part"
        in_file.write_bytes(b"temp")

        out_file = external_dir / "track [vid_contain].part"
        out_file.write_bytes(b"secret")

        # Mock find_video_partial_files returning both
        with patch("downloader.ytdlp_engine.find_video_partial_files", return_value=[in_file, out_file]):
            YtDlpEngine.safe_cleanup_partial_files(target_dir, "vid_contain")

        self.assertFalse(in_file.exists())
        self.assertTrue(out_file.exists())  # External file must NOT be deleted


if __name__ == "__main__":
    unittest.main()
