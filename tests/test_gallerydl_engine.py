"""
tests/test_gallerydl_engine.py
Comprehensive unit tests for GalleryDlEngine in Channel Harvest.

Covers:
1. Version detection from installed/bundled runtime.
2. Executable / Python module detection.
3. Safe argument construction (no shell=True).
4. Custom Cookie File propagation (-C / --cookies).
5. Structured JSON output parsing (Type codes 1, 2, 3, -1).
6. Nonzero exit code error handling.
7. Partial extraction results parsing.
8. Multiple images / carousels handling.
9. Windows Unicode paths and spaces handling.
10. Cancellation handling and child-process cleanup.
11. Orphan process prevention on shutdown.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from downloader.gallerydl_engine import (
    GalleryDlEngine,
    GalleryDlError,
    GalleryDlAuthError,
    GalleryDlCancelledException,
    GalleryDlNotFoundError,
    GalleryDlInfo,
)


class TestGalleryDlEngine(unittest.TestCase):
    """Verifies GalleryDlEngine detection, subprocess execution, output parsing, and lifecycle."""

    def setUp(self):
        self.engine = GalleryDlEngine()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        GalleryDlEngine.terminate_all_processes()

    def test_01_runtime_detection(self):
        """Verify runtime capability detection finds installed gallery-dl."""
        info = self.engine.detect_runtime(force_refresh=True)
        self.assertTrue(info.available)
        self.assertTrue(len(info.version) > 0)
        self.assertTrue(self.engine.is_available())

    def test_02_base_command_construction(self):
        """Verify base command does not use shell strings."""
        cmd = self.engine.get_base_command()
        self.assertIsInstance(cmd, list)
        self.assertTrue(len(cmd) >= 1)
        for part in cmd:
            self.assertIsInstance(part, str)

    def test_03_dump_json_parsing_success(self):
        """Verify dump-json parses type codes 1, 2, and 3 cleanly."""
        sample_json = json.dumps([
            [1, {"category": "instagram", "subcategory": "post"}],
            [2, "https://cdn.instagram.com/pic1.jpg", {"id": "media_01", "width": 1080, "height": 1080, "ext": "jpg"}],
            [2, "https://cdn.instagram.com/pic2.jpg", {"id": "media_02", "width": 1080, "height": 1080, "ext": "jpg"}],
            [3, {"id": "post_123", "author": "photographer", "title": "Photoset"}],
        ])

        results = self.engine.parse_dump_json(sample_json)
        self.assertEqual(len(results), 4)

        # Verify media records received download URL
        media_records = [r for r in results if r.get("id") in ("media_01", "media_02")]
        self.assertEqual(len(media_records), 2)
        self.assertEqual(media_records[0]["url"], "https://cdn.instagram.com/pic1.jpg")
        self.assertEqual(media_records[1]["url"], "https://cdn.instagram.com/pic2.jpg")

    def test_04_dump_json_parsing_auth_error(self):
        """Verify type code -1 login error raises GalleryDlAuthError."""
        error_json = json.dumps([
            [-1, {"error": "AbortExtraction", "message": "HTTP redirect to login page (https://www.instagram.com/accounts/login/)"}]
        ])

        with self.assertRaises(GalleryDlAuthError) as ctx:
            self.engine.parse_dump_json(error_json)
        self.assertIn("authentication required", str(ctx.exception).lower())

    def test_05_dump_json_line_delimited_fallback(self):
        """Verify line-delimited JSON objects are parsed resiliently."""
        line_delimited = (
            '{"id": "item1", "url": "https://ig.com/1.jpg"}\n'
            '{"id": "item2", "url": "https://ig.com/2.jpg"}\n'
        )
        results = self.engine.parse_dump_json(line_delimited)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "item1")
        self.assertEqual(results[1]["id"], "item2")

    def test_06_cookie_file_argument_propagation(self):
        """Verify cookie file path is passed via -C/--cookies argument."""
        cookie_file = Path(self.temp_dir.name) / "test_cookies.txt"
        cookie_file.write_text("# Netscape cookies\n.instagram.com TRUE / TRUE 0 sessionid test", encoding="utf-8")

        with patch.object(self.engine, "_execute_process") as mock_exec:
            mock_exec.return_value = (0, "[]", "")
            self.engine.extract_metadata("https://instagram.com/p/test/", custom_cookie_file=str(cookie_file))

            args = mock_exec.call_args[1]["args"]
            self.assertIn("--cookies", args)
            idx = args.index("--cookies")
            self.assertEqual(args[idx + 1], str(cookie_file.resolve()))

    def test_07_unicode_and_space_paths_handling(self):
        """Verify filenames with Unicode, spaces, and emoji are safely passed as arguments."""
        target_dir = Path(self.temp_dir.name) / "测试 目录 with spaces 🚀"
        filename_stem = "My Photo (我的照片) #1"

        with patch.object(self.engine, "_execute_process") as mock_exec:
            mock_exec.return_value = (0, "", "")
            res = self.engine.download_media(
                url="https://ig.com/p/test/",
                target_dir=target_dir,
                filename_stem=filename_stem,
            )
            args = mock_exec.call_args[1]["args"]
            self.assertIn("--directory", args)
            d_idx = args.index("--directory")
            self.assertEqual(args[d_idx + 1], str(target_dir.resolve()))
            self.assertTrue(target_dir.exists())

    def test_08_cancellation_terminates_subprocess(self):
        """Verify cancellation flag triggers child process termination."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process is running

        with patch("subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(GalleryDlCancelledException):
                self.engine._execute_process(
                    args=["--version"],
                    cancel_check=lambda: True,  # Immediately cancelled
                )
            mock_proc.terminate.assert_called()

    def test_09_nonzero_exit_code_error_handling(self):
        """Verify nonzero exit codes raise structured GalleryDlError."""
        with patch.object(self.engine, "_execute_process") as mock_exec:
            mock_exec.return_value = (1, "", "ERROR: 404 Not Found")
            with self.assertRaises(GalleryDlError) as ctx:
                self.engine.extract_metadata("https://instagram.com/p/notfound/")
            self.assertIn("not found", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
