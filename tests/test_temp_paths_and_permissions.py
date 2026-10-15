"""
test_temp_paths_and_permissions.py
Unit tests verifying temporary directory resolution, safe working directory enforcement,
and temporary file permission error classification.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core.paths import (
    is_protected_system_dir,
    get_temp_dir,
    cleanup_temp_dir,
    ensure_safe_environment,
    get_app_data_dir,
)
from downloader.ytdlp_engine import YtDlpEngine
from core.error_classifier import ErrorClassifier, ErrorCategory
from core.diagnostics import DiagnosticReporter


class TestTempPathsAndPermissions(unittest.TestCase):
    """Verifies that Channel Harvest safely isolates temporary files and correctly handles permissions."""

    def test_is_protected_system_dir(self):
        # Known protected system directories
        self.assertTrue(is_protected_system_dir(r"C:\Windows"))
        self.assertTrue(is_protected_system_dir(r"C:\Windows\System32"))
        self.assertTrue(is_protected_system_dir(r"C:\Program Files"))
        self.assertTrue(is_protected_system_dir(r"C:\Program Files (x86)"))

        # Subdirectory under System32
        self.assertTrue(is_protected_system_dir(r"C:\Windows\System32\drivers"))

        # Empty or None
        self.assertFalse(is_protected_system_dir(None))
        self.assertFalse(is_protected_system_dir(""))

        # Dedicated user temp dir is NOT protected
        temp_dir = get_temp_dir()
        self.assertFalse(is_protected_system_dir(temp_dir))

    def test_get_temp_dir(self):
        temp_dir = get_temp_dir()
        self.assertIsInstance(temp_dir, Path)
        self.assertTrue(temp_dir.exists())
        self.assertTrue(temp_dir.is_dir())
        self.assertFalse(is_protected_system_dir(temp_dir))

        # Verify writability
        test_file = temp_dir / ".ch_test_write.tmp"
        test_file.write_text("ok", encoding="utf-8")
        self.assertTrue(test_file.exists())
        test_file.unlink(missing_ok=True)

    def test_cleanup_temp_dir(self):
        temp_dir = get_temp_dir()
        stale_probe = temp_dir / ".ch_stale_probe.tmp"
        stale_probe.write_text("probe", encoding="utf-8")
        self.assertTrue(stale_probe.exists())

        cleanup_temp_dir(max_age_seconds=0)
        self.assertFalse(stale_probe.exists())

    def test_ensure_safe_environment_with_protected_cwd(self):
        # Simulate being launched inside C:\Windows\System32
        with patch("pathlib.Path.cwd", return_value=Path(r"C:\Windows\System32")):
            with patch("os.chdir") as mock_chdir:
                cwd, safe_temp = ensure_safe_environment()
                # Should detect System32 and chdir to AppData directory
                mock_chdir.assert_called_with(str(get_app_data_dir()))
                self.assertFalse(is_protected_system_dir(safe_temp))

    def test_build_base_ydl_opts_sets_temp_path(self):
        opts = YtDlpEngine.build_base_ydl_opts(platform="tiktok")
        self.assertIn("paths", opts)
        self.assertIn("temp", opts["paths"])
        temp_path = Path(opts["paths"]["temp"])
        self.assertTrue(temp_path.exists())
        self.assertFalse(is_protected_system_dir(temp_path))

        # YouTube opts also receive temp path
        yt_opts = YtDlpEngine.build_base_ydl_opts(platform="youtube")
        self.assertIn("paths", yt_opts)
        self.assertIn("temp", yt_opts["paths"])

    def test_error_classifier_temp_permission_error(self):
        raw_error = (
            "[yt-dlp] [info] Testing format bytevc1_1080p_529535-1\n"
            "ERROR: [Errno 13] Permission denied: 'C:\\WINDOWS\\system32\\tmpkadw_44i.tmp'"
        )
        err = ErrorClassifier.classify(raw_error, platform="tiktok")
        self.assertEqual(err.category, ErrorCategory.PERMISSION_ERROR)
        self.assertEqual(err.title, "Temporary file permission denied")
        self.assertIn("configured temporary directory is not writable", err.user_message)
        self.assertIn("%TEMP%", err.suggested_action)
        # Must NOT advise changing the destination folder
        self.assertNotIn("destination folder", err.user_message.lower())

        # Chinese localization
        zh_msg = err.get_localized_user_message("zh")
        self.assertEqual(zh_msg, "Channel Harvest 无法创建临时下载文件，因为配置的临时目录不可写。")

        zh_action = err.get_localized_suggested_action("zh")
        self.assertIn("%TEMP%", zh_action)
        self.assertIn("临时目录", zh_action)

        zh_title = err.get_localized_title("zh")
        self.assertEqual(zh_title, "临时文件创建权限被拒绝")

    def test_error_classifier_destination_permission_error(self):
        raw_error = "ERROR: [Errno 13] Permission denied: 'C:\\Users\\Admin\\Downloads\\MyVideo.mp4'"
        err = ErrorClassifier.classify(raw_error, platform="tiktok")
        self.assertEqual(err.category, ErrorCategory.PERMISSION_ERROR)
        self.assertEqual(err.title, "Permission denied")
        self.assertIn("destination folder", err.user_message)
        self.assertIn("destination folder", err.suggested_action)

    def test_diagnostics_report_includes_working_and_temp_dirs(self):
        report = DiagnosticReporter.generate_report()
        self.assertIn("Working Directory:", report)
        self.assertIn("Temporary Directory:", report)


if __name__ == "__main__":
    unittest.main()
