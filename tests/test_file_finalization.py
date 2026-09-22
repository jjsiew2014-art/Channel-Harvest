"""
test_file_finalization.py
Unit tests for Windows file-locking (WinError 32) finalization, retry backoff, and error handling.
"""

import os
import time
import threading
import tempfile
import unittest
from pathlib import Path

from core.error_classifier import ErrorClassifier, ErrorCategory
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloaderError,
    DownloadCancelledException,
    parse_locked_rename_paths,
    is_final_output_file,
    RENAME_ERROR_PATTERN,
)


class TestFileFinalization(unittest.TestCase):
    """Tests for Windows file-locking detection, path parsing, retry backoff, and safety."""

    def test_parse_locked_rename_paths(self):
        # 1. Standard single-quoted yt-dlp WinError 32 message
        msg1 = (
            "ERROR: Unable to rename file:\n"
            "[WinError 32] The process cannot access the file because it is being used by another process: "
            "'C:\\Users\\Admin\\Downloads\\Music\\JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4.part' -> "
            "'C:\\Users\\Admin\\Downloads\\Music\\JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4'. Giving up after 3 retries"
        )
        paths1 = parse_locked_rename_paths(msg1)
        self.assertIsNotNone(paths1)
        src1, dst1 = paths1
        self.assertEqual(src1.name, "JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4.part")
        self.assertEqual(dst1.name, "JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4")

        # 2. Double-quoted message
        msg2 = (
            'ERROR: Unable to rename file: [WinError 32] The process cannot access the file because it is being used by another process: '
            '"D:/Videos/Song [abc1234].mp4.part" -> "D:/Videos/Song [abc1234].mp4"'
        )
        paths2 = parse_locked_rename_paths(msg2)
        self.assertIsNotNone(paths2)
        src2, dst2 = paths2
        self.assertEqual(src2.name, "Song [abc1234].mp4.part")
        self.assertEqual(dst2.name, "Song [abc1234].mp4")

        # 3. Message without 'Unable to rename file:' prefix
        msg3 = (
            "[WinError 32] The process cannot access the file because it is being used by another process: "
            "'track.m4a.part' -> 'track.m4a'"
        )
        paths3 = parse_locked_rename_paths(msg3)
        self.assertIsNotNone(paths3)
        src3, dst3 = paths3
        self.assertEqual(src3.name, "track.m4a.part")
        self.assertEqual(dst3.name, "track.m4a")

        # 4. Non-locking error returns None
        msg4 = "ERROR: [youtube] f3CosPP_TVY: Video unavailable"
        self.assertIsNone(parse_locked_rename_paths(msg4))

    def test_is_final_output_file(self):
        vid = "f3CosPP_TVY"
        # Intermediate video/audio streams should be False
        self.assertFalse(is_final_output_file(Path(f"Title [{vid}].f137.mp4"), vid))
        self.assertFalse(is_final_output_file(Path(f"Title [{vid}].f140.m4a"), vid))
        self.assertFalse(is_final_output_file(Path(f"Title [{vid}].temp.mp4"), vid))
        self.assertFalse(is_final_output_file(Path(f"Title [{vid}].mp4.part"), vid))
        self.assertFalse(is_final_output_file(Path(f"Title [{vid}].mp4.ytdl"), vid))

        # Final completed media outputs should be True
        self.assertTrue(is_final_output_file(Path(f"Title [{vid}].mp4"), vid))
        self.assertTrue(is_final_output_file(Path(f"Title [{vid}].mkv"), vid))
        self.assertTrue(is_final_output_file(Path(f"Title [{vid}].mp3"), vid))
        self.assertTrue(is_final_output_file(Path(f"Title [{vid}].wav"), vid))
        self.assertTrue(is_final_output_file(Path(f"Title [{vid}].webm"), vid))

    def test_safe_finalize_rename_when_destination_already_complete(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            src = tmp_path / "video.mp4.part"
            dst = tmp_path / "video.mp4"

            # Create destination with valid content
            dst.write_bytes(b"EXISTING COMPLETE CONTENT")
            # Create stale source with equal or smaller size
            src.write_bytes(b"STALE PART")

            logs = []
            res = YtDlpEngine.safe_finalize_rename(
                src_path=src,
                dst_path=dst,
                raw_error="[WinError 32]",
                log_callback=logs.append,
            )

            self.assertTrue(res)
            self.assertTrue(dst.is_file())
            self.assertEqual(dst.read_bytes(), b"EXISTING COMPLETE CONTENT")
            # Stale source should have been cleanly unlinked
            self.assertFalse(src.exists())
            self.assertIn("[File Finalization] File rename successful after retry.", logs)

    def test_safe_finalize_rename_transient_lock_cleared(self):
        """Simulates an external process locking the file briefly, then clearing the lock."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            src = tmp_path / "sample.mp4.part"
            dst = tmp_path / "sample.mp4"

            payload = b"FINAL VIDEO PAYLOAD 1234567890" * 1024
            src.write_bytes(payload)

            logs = []

            # Lock file for 1.8 seconds in a background thread
            def background_lock():
                with open(src, "r+b"):
                    time.sleep(1.8)

            t = threading.Thread(target=background_lock)
            t.start()
            time.sleep(0.1)  # Ensure background lock is acquired

            res = YtDlpEngine.safe_finalize_rename(
                src_path=src,
                dst_path=dst,
                raw_error="[WinError 32]",
                log_callback=logs.append,
            )
            t.join()

            self.assertTrue(res)
            self.assertTrue(dst.is_file())
            self.assertEqual(dst.stat().st_size, len(payload))
            self.assertFalse(src.exists())

            # Verify diagnostic log sequence
            self.assertTrue(any("Retrying rename in 1 second..." in line for line in logs))
            self.assertTrue(any("Retry 1/5..." in line for line in logs))
            self.assertTrue(any("Retrying rename in 2 seconds..." in line for line in logs))
            self.assertTrue(any("Retry 2/5..." in line for line in logs))
            self.assertIn("[File Finalization] File rename successful after retry.", logs)

    def test_safe_finalize_rename_permanent_lock_fails_at_5_attempts(self):
        """Simulates a file that remains permanently locked, verifying max 5 retries without infinite loop."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            src = tmp_path / "locked.mp4.part"
            dst = tmp_path / "locked.mp4"

            src.write_bytes(b"CONTENT")

            # Hold lock permanently throughout test
            lock_handle = open(src, "r+b")

            logs = []

            # Mock delays to test 5 attempts quickly without waiting 25s
            original_delays = [0.01, 0.01, 0.01, 0.01, 0.01]
            try:
                # Monkeypatch delays locally for test speed
                import downloader.ytdlp_engine as engine_mod
                # Temporarily run with quick delays
                delays_backup = [1.0, 2.0, 4.0, 8.0, 10.0]

                # We can test by calling safe_finalize_rename with a custom cancel check or testing retry loop
                # Let's verify by patching delays:
                from unittest.mock import patch

                # We patch delays inside safe_finalize_rename
                # Since delays is a local list, we test the actual logic with 5 attempts
                with patch("time.sleep", return_value=None):
                    res = YtDlpEngine.safe_finalize_rename(
                        src_path=src,
                        dst_path=dst,
                        raw_error="[WinError 32]",
                        log_callback=logs.append,
                    )
            finally:
                lock_handle.close()

            self.assertFalse(res)
            # Verify 5 attempts were made
            retry_entries = [line for line in logs if "Retry " in line]
            self.assertEqual(len(retry_entries), 5)
            self.assertIn("[File Finalization] Retry 1/5...", logs)
            self.assertIn("[File Finalization] Retry 5/5...", logs)
            self.assertIn(
                "[File Finalization] Unable to finalize file after 5 attempts. Error Category: FILE_LOCKED",
                logs,
            )

    def test_safe_finalize_rename_cancellation(self):
        """Verify that user cancellation during finalization backoff raises DownloadCancelledException immediately."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            src = tmp_path / "cancelled.mp4.part"
            dst = tmp_path / "cancelled.mp4"

            src.write_bytes(b"DATA")

            logs = []
            cancelled = False

            def cancel_check():
                return cancelled

            # Trigger cancellation after brief start
            def trigger_cancel():
                time.sleep(0.2)
                nonlocal cancelled
                cancelled = True

            t = threading.Thread(target=trigger_cancel)
            t.start()

            # Lock file so attempt 1 fails
            with open(src, "r+b"):
                with self.assertRaises(DownloadCancelledException):
                    YtDlpEngine.safe_finalize_rename(
                        src_path=src,
                        dst_path=dst,
                        raw_error="[WinError 32]",
                        log_callback=logs.append,
                        cancel_check=cancel_check,
                    )
            t.join()


if __name__ == "__main__":
    unittest.main()
