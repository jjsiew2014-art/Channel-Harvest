"""
test_standalone_ytdlp_packaging.py
Unit tests verifying:
1. validate_standalone_ytdlp correctly identifies and validates official standalone Windows x64 yt-dlp.
2. validate_standalone_ytdlp rejects script wrappers, pip launchers, 32-bit binaries, and truncated files.
3. RuntimeManager reports standalone build, architecture, and curl_cffi availability.
4. DiagnosticReporter includes full yt-dlp standalone build and impersonation diagnostics.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from downloader.updater import validate_standalone_ytdlp
from downloader.runtime_manager import RuntimeManager
from core.diagnostics import DiagnosticReporter


class TestStandaloneYtDlpPackaging(unittest.TestCase):
    def test_official_bundled_ytdlp_is_valid(self):
        """Verifies that runtime/yt-dlp.exe is an official standalone Windows x64 binary."""
        bundled_exe = PROJECT_ROOT / "runtime" / "yt-dlp.exe"
        self.assertTrue(bundled_exe.is_file(), f"runtime/yt-dlp.exe does not exist at {bundled_exe}")

        is_valid, reason, info = validate_standalone_ytdlp(bundled_exe)
        self.assertTrue(is_valid, f"runtime/yt-dlp.exe failed validation: {reason}")
        self.assertEqual(info.get("machine"), "x86_64")
        self.assertEqual(info.get("build_type"), "Windows x64 Standalone")
        self.assertEqual(info.get("curl_cffi"), "Available")
        self.assertIn("Available", info.get("impersonation", ""))
        self.assertGreaterEqual(info.get("size", 0), 10 * 1024 * 1024)

    def test_validator_rejects_undersized_file(self):
        """Verifies that validate_standalone_ytdlp rejects files smaller than 5 MB."""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"MZ\x00\x00" * 100)
            temp_path = Path(f.name)

        try:
            is_valid, reason, info = validate_standalone_ytdlp(temp_path)
            self.assertFalse(is_valid)
            self.assertIn("File size too small", reason)
            self.assertIn("INVALID", info.get("build_type", ""))
        finally:
            temp_path.unlink(missing_ok=True)

    def test_validator_rejects_pip_launcher_signatures(self):
        """Verifies that validate_standalone_ytdlp rejects binaries containing pip launcher signatures."""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            # Create a 6MB dummy file with MZ header, PE header (machine 0x8664), but containing simple_launcher
            pe_data = bytearray(6 * 1024 * 1024)
            pe_data[0:2] = b"MZ"
            pe_data[0x3C:0x40] = (128).to_bytes(4, "little")
            pe_data[128:132] = b"PE\x00\x00"
            pe_data[132:134] = (0x8664).to_bytes(2, "little")  # x86_64
            # Inject simple_launcher signature
            pe_data[1000:1015] = b"simple_launcher"
            f.write(pe_data)
            temp_path = Path(f.name)

        try:
            is_valid, reason, info = validate_standalone_ytdlp(temp_path)
            self.assertFalse(is_valid)
            self.assertIn("pip/distlib simple_launcher", reason)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_runtime_manager_reports_standalone_info(self):
        """Verifies that RuntimeManager accurately reports the standalone yt-dlp properties."""
        rm = RuntimeManager()
        installed = rm.get_installed_versions()
        self.assertIn("ytdlp", installed)
        ytdlp_info = installed["ytdlp"]

        self.assertEqual(ytdlp_info.build_type, "Windows x64 Standalone")
        self.assertEqual(ytdlp_info.architecture, "x86_64")
        self.assertEqual(ytdlp_info.curl_cffi, "Available")
        self.assertIn("Available", ytdlp_info.impersonation)
        self.assertEqual(ytdlp_info.status, "Up to date")

    def test_diagnostic_report_includes_ytdlp_standalone_metrics(self):
        """Verifies that DiagnosticReporter includes build, architecture, and curl_cffi in report."""
        reporter = DiagnosticReporter()
        report = reporter.generate_report()

        self.assertIn("Build: Windows x64 Standalone", report)
        self.assertIn("Architecture: x86_64", report)
        self.assertIn("curl_cffi: Available", report)
        self.assertIn("Impersonation: Available", report)


if __name__ == "__main__":
    unittest.main()
