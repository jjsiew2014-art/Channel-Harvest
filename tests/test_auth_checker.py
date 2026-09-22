"""
test_auth_checker.py
Comprehensive unit tests for the stage-aware YouTube authentication and
cookie verification pipeline in Channel Harvest.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from downloader.auth_checker import (
    AuthChecker,
    AuthStage,
    AuthStatusCode,
    AuthTestResult,
    is_browser_process_running,
    YOUTUBE_AUTH_COOKIE_NAMES,
)
from core.diagnostics import PrivacySanitizer


class TestAuthChecker(unittest.TestCase):
    """Unit test cases covering all 5 stages of the authentication pipeline."""

    # -------------------------------------------------------------------------
    # Stage 1: Browser / File Detection
    # -------------------------------------------------------------------------

    def test_missing_browser_detection(self):
        """Verify missing browser installation returns BROWSER_NOT_FOUND."""
        with patch("downloader.auth_checker.get_browser_database_path", return_value=Path("C:/Fake/Nonexistent/Cookies")):
            result = AuthChecker.test_authentication("firefox")
            self.assertFalse(result.success)
            self.assertEqual(result.stage, AuthStage.BROWSER_DETECTION)
            self.assertEqual(result.status_code, AuthStatusCode.BROWSER_NOT_FOUND)
            self.assertIn("No installation or user profile directory was found", result.reason)

    def test_empty_cookie_file_path(self):
        """Verify empty custom cookie file path returns BROWSER_NOT_FOUND."""
        result = AuthChecker.test_authentication("custom_file", custom_cookie_path="")
        self.assertFalse(result.success)
        self.assertEqual(result.stage, AuthStage.BROWSER_DETECTION)
        self.assertEqual(result.status_code, AuthStatusCode.BROWSER_NOT_FOUND)

    def test_nonexistent_cookie_file(self):
        """Verify non-existent cookie file path returns BROWSER_NOT_FOUND."""
        result = AuthChecker.test_authentication("custom_file", custom_cookie_path="C:/nonexistent/cookies.txt")
        self.assertFalse(result.success)
        self.assertEqual(result.stage, AuthStage.BROWSER_DETECTION)
        self.assertEqual(result.status_code, AuthStatusCode.BROWSER_NOT_FOUND)

    # -------------------------------------------------------------------------
    # Stage 2: Database Access / Lock Detection
    # -------------------------------------------------------------------------

    def test_database_locked_handling(self):
        """Verify that locked database triggers DATABASE_LOCKED without hardcoding browser closed."""
        fake_db = Path("C:/Fake/Cookies")
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch("downloader.auth_checker.get_browser_database_path", return_value=fake_db), \
             patch.object(AuthChecker, "_probe_database_lock", return_value=(True, "PermissionError: [WinError 32] Locked")):
            result = AuthChecker.test_authentication("chrome")
            self.assertFalse(result.success)
            self.assertEqual(result.stage, AuthStage.DATABASE_ACCESS)
            self.assertEqual(result.status_code, AuthStatusCode.DATABASE_LOCKED)
            self.assertIn("locked", result.reason.lower())

    # -------------------------------------------------------------------------
    # Stage 3: Cookie Decryption & App-Bound Detection
    # -------------------------------------------------------------------------

    def test_app_bound_decryption_failure(self):
        """Verify that yt-dlp DPAPI failure with v20 cookies reports COOKIE_DECRYPTION_FAILED with ABE info."""
        fake_db = Path("C:/Fake/Cookies")
        dpapi_err = "ERROR: Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927 for more info"
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch("downloader.auth_checker.get_browser_database_path", return_value=fake_db), \
             patch.object(AuthChecker, "_probe_database_lock", return_value=(False, "")), \
             patch.object(AuthChecker, "_extract_browser_cookies", return_value=(None, dpapi_err, True, False)):
            result = AuthChecker.test_authentication("chrome")
            self.assertFalse(result.success)
            self.assertEqual(result.stage, AuthStage.COOKIE_DECRYPTION)
            self.assertEqual(result.status_code, AuthStatusCode.COOKIE_DECRYPTION_FAILED)
            self.assertTrue(result.is_app_bound)
            self.assertIn("App-Bound Encryption", result.reason)
            self.assertIn("cookies.txt", result.suggested_action)

    def test_invalid_cookie_file_format(self):
        """Verify invalid cookie file content returns COOKIE_FILE_INVALID."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Invalid content that is not netscape cookies")
            tmp_name = f.name

        try:
            result = AuthChecker.test_authentication("custom_file", custom_cookie_path=tmp_name)
            self.assertFalse(result.success)
            self.assertEqual(result.stage, AuthStage.COOKIE_DECRYPTION)
            self.assertEqual(result.status_code, AuthStatusCode.COOKIE_FILE_INVALID)
        finally:
            Path(tmp_name).unlink()

    # -------------------------------------------------------------------------
    # Stage 4: YouTube Cookie Verification
    # -------------------------------------------------------------------------

    def test_no_youtube_cookies_found(self):
        """Verify cookies loaded from non-YouTube domains return NO_YOUTUBE_COOKIES."""
        non_yt_content = """# Netscape HTTP Cookie File
.example.com	TRUE	/	FALSE	2147483647	test_cookie	12345
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(non_yt_content)
            tmp_name = f.name

        try:
            result = AuthChecker.test_authentication("custom_file", custom_cookie_path=tmp_name)
            self.assertFalse(result.success)
            self.assertEqual(result.stage, AuthStage.COOKIE_EXTRACTION)
            self.assertEqual(result.status_code, AuthStatusCode.NO_YOUTUBE_COOKIES)
            self.assertEqual(result.youtube_cookie_count, 0)
            self.assertIn("no YouTube or Google cookies", result.reason)
        finally:
            Path(tmp_name).unlink()

    # -------------------------------------------------------------------------
    # Stage 5: Live Request Verification & Success
    # -------------------------------------------------------------------------

    def test_valid_youtube_cookie_file_success(self):
        """Verify valid YouTube cookie file with session cookies passes all stages."""
        valid_content = """# Netscape HTTP Cookie File
# This is a generated file!  Do not edit.
.youtube.com	TRUE	/	TRUE	2147483647	LOGIN_INFO	AFmmF2kwRA...
.youtube.com	TRUE	/	TRUE	2147483647	SID	sample_sid_token
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(valid_content)
            tmp_name = f.name

        try:
            with patch.object(AuthChecker, "_verify_live_request", return_value=(True, "")):
                result = AuthChecker.test_authentication("custom_file", custom_cookie_path=tmp_name)
                self.assertTrue(result.success)
                self.assertEqual(result.stage, AuthStage.COMPLETE)
                self.assertEqual(result.status_code, AuthStatusCode.SUCCESS)
                self.assertGreaterEqual(result.cookie_count, 2)
                self.assertGreaterEqual(result.youtube_cookie_count, 2)
                self.assertTrue(result.has_session)
        finally:
            Path(tmp_name).unlink()

    def test_youtube_live_request_rejected(self):
        """Verify YouTube rejection returns YOUTUBE_AUTH_REJECTED."""
        valid_content = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	2147483647	LOGIN_INFO	expired_token
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(valid_content)
            tmp_name = f.name

        try:
            with patch.object(AuthChecker, "_verify_live_request", return_value=(False, "HTTP Error 401: Unauthorized")):
                result = AuthChecker.test_authentication("custom_file", custom_cookie_path=tmp_name)
                self.assertFalse(result.success)
                self.assertEqual(result.stage, AuthStage.YOUTUBE_REQUEST)
                self.assertEqual(result.status_code, AuthStatusCode.YOUTUBE_AUTH_REJECTED)
                self.assertIn("rejected", result.reason.lower())
        finally:
            Path(tmp_name).unlink()

    # -------------------------------------------------------------------------
    # Diagnostic Report Privacy & Sanitization
    # -------------------------------------------------------------------------

    def test_diagnostic_report_privacy_sanitization(self):
        """Verify that zero cookie secrets, auth tokens, or private paths appear in reports."""
        secret_token = "MY_SUPER_SECRET_SESSION_TOKEN_9999"
        res = AuthTestResult(
            success=False,
            stage=AuthStage.COOKIE_DECRYPTION,
            status_code=AuthStatusCode.COOKIE_DECRYPTION_FAILED,
            browser_name="Chrome",
            profile_name="Default",
            reason="Windows DPAPI could not decrypt Chrome cookies.",
            suggested_action="Use a cookies.txt file.",
            technical_error=f"Exception with bearer {secret_token} and SID=S-1-5-21-1234567890-1234567890-1234567890",
        )

        report = res.to_diagnostic_report(ytdlp_version="2026.08.19")

        # Must not contain the raw secret token
        self.assertNotIn(secret_token, report)
        # SIDs must be sanitized
        self.assertNotIn("S-1-5-21-1234567890-1234567890-1234567890", report)
        # Required structural fields must be present
        self.assertIn("Channel Harvest Authentication Diagnostic", report)
        self.assertIn("Authentication Method:", report)
        self.assertIn("Browser Cookies", report)
        self.assertIn("Browser / Source:       Chrome", report)
        self.assertIn("Stage:                  Browser Cookie Decryption", report)
        self.assertIn("Status Code:            COOKIE_DECRYPTION_FAILED", report)
        self.assertIn("Elevation:", report)
        self.assertIn("User Context:", report)

    # -------------------------------------------------------------------------
    # Authentication Modes & File Validation
    # -------------------------------------------------------------------------

    def test_test_authentication_none(self):
        """Verify testing with 'none' immediately returns NOT_CONFIGURED without errors."""
        res = AuthChecker.test_authentication("none")
        self.assertTrue(res.success)
        self.assertEqual(res.status_code, AuthStatusCode.NOT_CONFIGURED)
        self.assertEqual(res.auth_method, "None")
        self.assertIn("Public YouTube downloads will proceed without", res.suggested_action)

    def test_validate_cookie_file_empty_and_missing(self):
        """Verify validate_cookie_file handles empty and nonexistent paths."""
        from downloader.auth_checker import validate_cookie_file
        res_none = validate_cookie_file(None)
        self.assertFalse(res_none["is_valid"])
        self.assertEqual(res_none["status_code"], AuthStatusCode.COOKIE_FILE_INVALID)

        res_empty = validate_cookie_file("   ")
        self.assertFalse(res_empty["is_valid"])
        self.assertEqual(res_empty["status_code"], AuthStatusCode.COOKIE_FILE_INVALID)

        res_missing = validate_cookie_file("C:/nonexistent/file/path/cookies.txt")
        self.assertFalse(res_missing["is_valid"])
        self.assertEqual(res_missing["status_code"], AuthStatusCode.BROWSER_NOT_FOUND)

    def test_validate_cookie_file_zero_byte(self):
        """Verify validate_cookie_file identifies zero-byte files."""
        from downloader.auth_checker import validate_cookie_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            tmp_path = f.name
        try:
            res = validate_cookie_file(tmp_path)
            self.assertFalse(res["is_valid"])
            self.assertEqual(res["status_code"], AuthStatusCode.COOKIE_FILE_INVALID)
            self.assertIn("empty", res["message"].lower())
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_validate_cookie_file_invalid_format(self):
        """Verify validate_cookie_file catches non-Netscape files."""
        from downloader.auth_checker import validate_cookie_file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Some random non-cookie file content\nhello world")
            tmp_path = f.name
        try:
            res = validate_cookie_file(tmp_path)
            self.assertFalse(res["is_valid"])
            self.assertEqual(res["status_code"], AuthStatusCode.COOKIE_FILE_INVALID)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_validate_cookie_file_non_youtube(self):
        """Verify validate_cookie_file identifies valid cookie files with NO YouTube cookies."""
        from downloader.auth_checker import validate_cookie_file
        content = "# Netscape HTTP Cookie File\n.github.com\tTRUE\t/\tTRUE\t2147483647\tuser_session\txyz123\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            res = validate_cookie_file(tmp_path)
            self.assertFalse(res["is_valid"])
            self.assertEqual(res["status_code"], AuthStatusCode.NO_YOUTUBE_COOKIES)
            self.assertIn("no YouTube or Google cookies", res["message"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_validate_cookie_file_valid_session(self):
        """Verify validate_cookie_file detects valid YouTube session cookies."""
        from downloader.auth_checker import validate_cookie_file
        content = (
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\ta_secret_session_token\n"
            ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tanother_token\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        try:
            res = validate_cookie_file(tmp_path)
            self.assertTrue(res["is_valid"])
            self.assertEqual(res["status_code"], AuthStatusCode.COOKIE_FILE_VALID)
            self.assertTrue(res["has_session"])
            self.assertEqual(res["youtube_cookie_count"], 2)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_get_browser_profiles(self):
        """Verify get_browser_profiles returns a list with at least 'Default'."""
        from downloader.auth_checker import get_browser_profiles
        profiles = get_browser_profiles("chrome")
        self.assertIsInstance(profiles, list)
        self.assertGreaterEqual(len(profiles), 1)
        self.assertIn("Default", profiles)

    def test_no_admin_recommendation_in_decryption_failure(self):
        """Verify that decryption failure explanation never suggests running as Administrator."""
        fake_db = Path("C:/Fake/Cookies")
        dpapi_err = "ERROR: Failed to decrypt with DPAPI."
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch("downloader.auth_checker.get_browser_database_path", return_value=fake_db), \
             patch.object(AuthChecker, "_probe_database_lock", return_value=(False, "")), \
             patch.object(AuthChecker, "_extract_browser_cookies", return_value=(None, dpapi_err, True, False)):
            result = AuthChecker.test_authentication("chrome")
            combined_text = (result.reason + " " + result.suggested_action).lower()
            self.assertNotIn("administrator", combined_text)
            self.assertNotIn("elevate", combined_text)
            self.assertNotIn("run as admin", combined_text)
            self.assertIn("cookies.txt", combined_text)


if __name__ == "__main__":
    unittest.main()