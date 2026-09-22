"""
tests/test_range_not_satisfiable.py
Unit tests for HTTP 416 (Requested Range Not Satisfiable) detection, error classification,
and safe partial file recovery in Channel Harvest.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.error_classifier import ErrorClassifier, ErrorCategory
from core.models import VideoItem, DownloadSettings, DownloadMode
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
    is_http_416_error,
    find_video_partial_files,
    find_completed_final_file,
)
from yt_dlp.utils import DownloadError


class TestRangeNotSatisfiableErrorClassification(unittest.TestCase):
    """Test suite for HTTP 416 classification, stage mapping, and diagnostic messaging."""

    def test_http_416_exact_error_message(self):
        msg = "ERROR: unable to download video data: HTTP Error 416: Requested range not satisfiable"
        err = ErrorClassifier.classify(
            raw_error=msg,
            video_id="f3CosPP_TVY",
            video_title="JaJamBo (Official Music)",
        )
        self.assertEqual(err.category, ErrorCategory.RANGE_NOT_SATISFIABLE)
        self.assertEqual(err.http_status, 416)
        self.assertEqual(err.stage, "Video Download / Resume")
        self.assertEqual(err.component, "yt-dlp / HTTP Download")
        self.assertFalse(err.retryable)
        self.assertIn("416", err.concise_status)
        self.assertIn("range", err.concise_status.lower())
        self.assertIn("range", err.message.lower())

    def test_http_416_variants_classification(self):
        variants = [
            "HTTP Error 416: Requested range not satisfiable",
            "[download] Got HTTP 416 error: Range not satisfiable",
            "ERROR: HTTP Error 416: Requested range not satisfiable (Server returned 416)",
            "unable to download video data: HTTP 416",
        ]
        for v in variants:
            with self.subTest(variant=v):
                self.assertTrue(is_http_416_error(v))
                err = ErrorClassifier.classify(raw_error=v)
                self.assertEqual(err.category, ErrorCategory.RANGE_NOT_SATISFIABLE)
                self.assertEqual(err.http_status, 416)

    def test_non_416_errors_not_confused(self):
        non_416 = [
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            "ERROR: unable to download video data: HTTP Error 404: Not Found",
            "ERROR: Unable to rename file: [WinError 32] The process cannot access the file",
            "ERROR: [youtube] 123: Private video",
        ]
        for msg in non_416:
            with self.subTest(msg=msg):
                self.assertFalse(is_http_416_error(msg))
                err = ErrorClassifier.classify(raw_error=msg)
                self.assertNotEqual(err.category, ErrorCategory.RANGE_NOT_SATISFIABLE)


class TestPartialFileHandlingAndIsolation(unittest.TestCase):
    """Test suite for discovering and safely removing partial files with strict video ID isolation."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ch_test_416_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_find_video_partial_files_matches_only_target_video(self):
        vid_target = "f3CosPP_TVY"
        vid_other = "abc999xyz88"

        # Create target video files
        p1 = self.test_dir / f"JaJamBo [{vid_target}].f137.mp4.part"
        p2 = self.test_dir / f"JaJamBo [{vid_target}].mp4.ytdl"
        p1.write_bytes(b"partial video data")
        p2.write_bytes(b"resume state")

        # Create other video files (should never be touched)
        other_part = self.test_dir / f"Other Song [{vid_other}].f137.mp4.part"
        other_part.write_bytes(b"other partial data")

        # Create finalized files (should never be identified as partial)
        final_file = self.test_dir / f"JaJamBo [{vid_target}].mp4"
        final_file.write_bytes(b"final mp4")

        found = find_video_partial_files(self.test_dir, vid_target)
        found_names = [f.name for f in found]

        self.assertEqual(len(found), 2)
        self.assertIn(p1.name, found_names)
        self.assertIn(p2.name, found_names)
        self.assertNotIn(other_part.name, found_names)
        self.assertNotIn(final_file.name, found_names)

    def test_find_completed_final_file(self):
        vid = "f3CosPP_TVY"

        # Initially no final file
        self.assertIsNone(find_completed_final_file(self.test_dir, vid))

        # Add partial file - still None
        (self.test_dir / f"JaJamBo [{vid}].mp4.part").write_bytes(b"data")
        self.assertIsNone(find_completed_final_file(self.test_dir, vid))

        # Add intermediate format file - still None
        (self.test_dir / f"JaJamBo [{vid}].f137.mp4").write_bytes(b"data")
        self.assertIsNone(find_completed_final_file(self.test_dir, vid))

        # Add valid final file
        final_mp4 = self.test_dir / f"JaJamBo [{vid}].mp4"
        final_mp4.write_bytes(b"valid complete media file")
        found = find_completed_final_file(self.test_dir, vid)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, final_mp4.name)

    def test_recover_from_range_error_preserves_completed_file(self):
        vid = "f3CosPP_TVY"
        final_file = self.test_dir / f"JaJamBo [{vid}].mp4"
        final_file.write_bytes(b"completed video")
        stale_part = self.test_dir / f"JaJamBo [{vid}].mp4.part"
        stale_part.write_bytes(b"stale part")

        video = VideoItem(index=1, video_id=vid, title="JaJamBo", duration="03:00")
        logs = []

        result = YtDlpEngine.recover_from_range_error(
            video=video,
            target_dir=self.test_dir,
            recovery_attempt=1,
            max_recovery_attempts=2,
            format_spec="bv*+ba/b",
            log_callback=logs.append,
        )

        self.assertEqual(result, "ALREADY_COMPLETE")
        self.assertTrue(final_file.exists(), "Completed file must be preserved!")
        self.assertFalse(stale_part.exists(), "Leftover .part file should be cleaned up")
        self.assertTrue(any("already exists" in l for l in logs))

    def test_recover_from_range_error_unlinks_stale_part_and_logs(self):
        vid = "f3CosPP_TVY"
        other_vid = "other12345"

        stale_part = self.test_dir / f"JaJamBo [{vid}].f137.mp4.part"
        stale_part.write_bytes(b"corrupt partial bytes")
        other_part = self.test_dir / f"Other [{other_vid}].f137.mp4.part"
        other_part.write_bytes(b"other video bytes")

        video = VideoItem(index=1, video_id=vid, title="JaJamBo", duration="03:00")
        logs = []

        result = YtDlpEngine.recover_from_range_error(
            video=video,
            target_dir=self.test_dir,
            recovery_attempt=1,
            max_recovery_attempts=2,
            format_spec="bv*+ba/b",
            log_callback=logs.append,
        )

        self.assertTrue(result)
        self.assertFalse(stale_part.exists(), "Stale part file must be deleted")
        self.assertTrue(other_part.exists(), "Other video's part file must NEVER be touched!")

        # Verify exact required log messages
        log_text = "\n".join(logs)
        self.assertIn(f"[Download] HTTP 416 detected for video {vid}", log_text)
        self.assertIn("[Download] Partial resume state appears invalid", log_text)
        self.assertIn("[Download] Waiting for download process to terminate", log_text)
        self.assertIn(f"[Download] Removing stale partial file: {stale_part.name}", log_text)
        self.assertIn("[Download] Starting fresh download without resume", log_text)
        self.assertIn("[Download] HTTP 416 recovery attempt 1/2", log_text)
        self.assertIn("[Download Diagnostics]", log_text)

    def test_recover_from_range_error_cancellation(self):
        vid = "f3CosPP_TVY"
        video = VideoItem(index=1, video_id=vid, title="JaJamBo", duration="03:00")

        with self.assertRaises(DownloadCancelledException):
            YtDlpEngine.recover_from_range_error(
                video=video,
                target_dir=self.test_dir,
                recovery_attempt=1,
                max_recovery_attempts=2,
                cancel_check=lambda: True,
            )


class TestYtDlpEngineRangeRecoveryExecution(unittest.TestCase):
    """Test suite verifying download_single_video bounded retry and continuedl toggle on HTTP 416."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ch_test_416_exec_"))
        self.engine = YtDlpEngine()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("yt_dlp.YoutubeDL")
    def test_video_only_recovers_on_first_416_attempt(self, mock_ydl_cls):
        vid = "f3CosPP_TVY"
        stale_part = self.test_dir / f"JaJamBo [{vid}].f137.mp4.part"
        stale_part.write_bytes(b"stale 416 bytes")

        video = VideoItem(
            index=1,
            video_id=vid,
            title="JaJamBo (Official Music)",
            duration="03:00",
            url=f"https://www.youtube.com/watch?v={vid}",
        )
        settings = DownloadSettings(download_mode=DownloadMode.VIDEO_ONLY)

        # First call fails with HTTP 416; second call succeeds
        mock_instance1 = MagicMock()
        mock_instance1.__enter__.return_value = mock_instance1
        mock_instance1.extract_info.side_effect = DownloadError(
            "ERROR: unable to download video data: HTTP Error 416: Requested range not satisfiable"
        )
        mock_instance2 = MagicMock()
        mock_instance2.__enter__.return_value = mock_instance2
        mock_instance2.extract_info.return_value = {"id": vid, "title": "JaJamBo"}

        mock_ydl_cls.side_effect = [mock_instance1, mock_instance2]

        logs = []
        result = self.engine.download_single_video(
            video=video,
            settings=settings,
            target_dir=self.test_dir,
            log_callback=logs.append,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["skipped"])
        # Stale part was deleted
        self.assertFalse(stale_part.exists())
        # Continuedl was set to False for recovery attempt
        second_call_opts = mock_ydl_cls.call_args_list[1][0][0]
        self.assertFalse(second_call_opts.get("continuedl"))

    @patch("yt_dlp.YoutubeDL")
    def test_video_only_exhausts_2_attempts_and_raises_proper_error(self, mock_ydl_cls):
        vid = "f3CosPP_TVY"
        video = VideoItem(
            index=1,
            video_id=vid,
            title="JaJamBo (Official Music)",
            duration="03:00",
            url=f"https://www.youtube.com/watch?v={vid}",
        )
        settings = DownloadSettings(download_mode=DownloadMode.VIDEO_ONLY)

        # Consistently fails with 416
        err_msg = "ERROR: unable to download video data: HTTP Error 416: Requested range not satisfiable"
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = DownloadError(err_msg)
        mock_ydl_cls.return_value = mock_instance

        logs = []
        with self.assertRaises(DownloaderError) as ctx:
            self.engine.download_single_video(
                video=video,
                settings=settings,
                target_dir=self.test_dir,
                log_callback=logs.append,
            )

        self.assertEqual(ctx.exception.stage, "Video Download / Resume")
        # Ensure it stopped after max 2 recoveries (1 initial + 2 retries = 3 calls total)
        self.assertEqual(mock_ydl_cls.call_count, 3)

        # Classified as RANGE_NOT_SATISFIABLE
        classified = ErrorClassifier.classify(ctx.exception.raw_error)
        self.assertEqual(classified.category, ErrorCategory.RANGE_NOT_SATISFIABLE)
        self.assertEqual(classified.http_status, 416)


if __name__ == "__main__":
    unittest.main()
