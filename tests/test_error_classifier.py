"""
test_error_classifier.py
Unit tests for the Channel Harvest Error Classification and Diagnostic Reporting Layer.
"""

import unittest
from core.error_classifier import ErrorClassifier, ErrorCategory, DownloadError
from core.diagnostics import PrivacySanitizer, ErrorTracker


class TestErrorClassifier(unittest.TestCase):
    """Tests comprehensive pattern matching, evidence-based classification, and stages."""

    def test_http_403_pure_vs_po_token(self):
        # Pure 403 Forbidden without PO token evidence
        err1 = ErrorClassifier.classify(
            raw_error="[yt-dlp ERROR] ERROR: unable to download video data: HTTP Error 403: Forbidden",
            video_id="N0Yt10WBNBE",
            video_title="劉秋儀【第21集】-兩顆心",
        )
        self.assertEqual(err1.category, ErrorCategory.HTTP_403_FORBIDDEN)
        self.assertEqual(err1.http_status, 403)
        self.assertFalse(err1.retryable)
        self.assertIn("403", err1.concise_status)

        # 403 with explicit PO Token evidence
        err2 = ErrorClassifier.classify(
            raw_error="HTTP Error 403: Forbidden. A valid PO Token is required to download this video stream",
            video_id="abc123xyz",
        )
        self.assertEqual(err2.category, ErrorCategory.PO_TOKEN_REQUIRED)
        self.assertEqual(err2.http_status, 403)
        self.assertFalse(err2.retryable)

    def test_http_429_rate_limit_vs_bot_verification(self):
        # Pure 429 Too Many Requests
        err1 = ErrorClassifier.classify(
            raw_error="HTTP Error 429: Too Many Requests. YouTube has rate-limited requests from this IP.",
        )
        self.assertEqual(err1.category, ErrorCategory.RATE_LIMITED)
        self.assertEqual(err1.http_status, 429)
        self.assertTrue(err1.retryable)
        self.assertIn("429", err1.concise_status)

        # 429 / HTTP error with bot verification challenge
        err2 = ErrorClassifier.classify(
            raw_error="HTTP Error 429: Sign in to confirm you're not a bot",
        )
        self.assertEqual(err2.category, ErrorCategory.BOT_VERIFICATION)
        self.assertFalse(err2.retryable)
        self.assertIn("Bot", err2.concise_status)

    def test_http_status_codes(self):
        codes = [
            (404, "HTTP Error 404: Not Found", ErrorCategory.HTTP_404_NOT_FOUND, False),
            (500, "HTTP Error 500: Internal Server Error", ErrorCategory.HTTP_500_SERVER_ERROR, True),
            (502, "HTTP Error 502: Bad Gateway", ErrorCategory.HTTP_502_BAD_GATEWAY, True),
            (503, "HTTP Error 503: Service Unavailable", ErrorCategory.HTTP_503_SERVICE_UNAVAILABLE, True),
        ]
        for status_code, raw_msg, expected_cat, expected_retry in codes:
            with self.subTest(status_code=status_code):
                err = ErrorClassifier.classify(raw_error=raw_msg)
                self.assertEqual(err.http_status, status_code)
                self.assertEqual(err.category, expected_cat)
                self.assertEqual(err.retryable, expected_retry)

    def test_http_416_range_not_satisfiable(self):
        err = ErrorClassifier.classify(
            raw_error="ERROR: unable to download video data: HTTP Error 416: Requested range not satisfiable",
            video_id="f3CosPP_TVY",
            video_title="JaJamBo (Official Music)",
        )
        self.assertEqual(err.category, ErrorCategory.RANGE_NOT_SATISFIABLE)
        self.assertEqual(err.http_status, 416)
        self.assertEqual(err.stage, "Video Download / Resume")
        self.assertEqual(err.component, "yt-dlp / HTTP Download")
        self.assertFalse(err.retryable)
        self.assertIn("416", err.concise_status)

    def test_video_availability_and_privacy(self):
        # Private video
        err_priv = ErrorClassifier.classify("ERROR: [youtube] 123: Private video. Sign in if you've been granted access")
        self.assertEqual(err_priv.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertFalse(err_priv.retryable)

        # Video unavailable
        err_unavail = ErrorClassifier.classify("ERROR: [youtube] 123: Video unavailable")
        self.assertEqual(err_unavail.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertFalse(err_unavail.retryable)

        # Region restricted
        err_region = ErrorClassifier.classify("ERROR: The uploader has not made this video available in your country")
        self.assertEqual(err_region.category, ErrorCategory.REGION_RESTRICTED)
        self.assertFalse(err_region.retryable)

        # Age restricted
        err_age = ErrorClassifier.classify("ERROR: Sign in to confirm your age. This video may be inappropriate for some users.")
        self.assertEqual(err_age.category, ErrorCategory.AGE_RESTRICTED)
        self.assertFalse(err_age.retryable)

    def test_runtime_deno_and_ejs(self):
        # EJS challenge failure
        err_ejs = ErrorClassifier.classify("Solving JS challenges using deno failed: ReferenceError: window is not defined")
        self.assertEqual(err_ejs.category, ErrorCategory.EJS_CHALLENGE_FAILED)
        self.assertFalse(err_ejs.retryable)
        self.assertEqual(err_ejs.component, "EJS")

        # Deno missing or broken
        err_deno = ErrorClassifier.classify("deno: command not found or Deno executable not found")
        self.assertEqual(err_deno.category, ErrorCategory.DENO_MISSING_OR_BROKEN)
        self.assertFalse(err_deno.retryable)
        self.assertEqual(err_deno.component, "Deno")

    def test_ffmpeg_and_postprocessing(self):
        err_ffmpeg = ErrorClassifier.classify("ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide path")
        self.assertEqual(err_ffmpeg.category, ErrorCategory.FFMPEG_ERROR)
        self.assertEqual(err_ffmpeg.component, "FFmpeg")
        self.assertFalse(err_ffmpeg.retryable)

    def test_network_and_timeout(self):
        err_net = ErrorClassifier.classify("[youtube] Connection reset by peer while downloading chunk")
        self.assertEqual(err_net.category, ErrorCategory.NETWORK_ERROR)
        self.assertTrue(err_net.retryable)

        err_time = ErrorClassifier.classify("Read timed out after 30.0 seconds")
        self.assertEqual(err_time.category, ErrorCategory.TIMEOUT)
        self.assertTrue(err_time.retryable)

    def test_stage_inference_and_preservation(self):
        # Preserved when explicitly supplied
        err_explicit = ErrorClassifier.classify("HTTP Error 403: Forbidden", stage="audio")
        self.assertEqual(err_explicit.stage, "audio")

        # Inferred from raw output when omitted
        err_inferred_audio = ErrorClassifier.classify("[ExtractAudio] Destination: song.wav\nffmpeg failed")
        self.assertEqual(err_inferred_audio.stage, "audio")

        err_inferred_sub = ErrorClassifier.classify("Writing video subtitles failed: HTTP 404")
        self.assertEqual(err_inferred_sub.stage, "subtitle")

        err_inferred_post = ErrorClassifier.classify("Postprocessing: Merging formats into 'video.mp4'")
        self.assertIn(err_inferred_post.stage, ("conversion", "postprocess"))

    def test_filesystem_and_format_errors(self):
        # Disk full
        err_disk = ErrorClassifier.classify("OSError: [Errno 28] No space left on device")
        self.assertEqual(err_disk.category, ErrorCategory.DISK_SPACE_ERROR)
        self.assertFalse(err_disk.retryable)

        # Permission denied
        err_perm = ErrorClassifier.classify("PermissionError: [Errno 13] Permission denied: 'C:\\Videos'")
        self.assertEqual(err_perm.category, ErrorCategory.PERMISSION_ERROR)
        self.assertFalse(err_perm.retryable)

        # Format not available
        err_fmt = ErrorClassifier.classify("ERROR: Requested format is not available")
        self.assertEqual(err_fmt.category, ErrorCategory.FORMAT_ERROR)
        self.assertFalse(err_fmt.retryable)

    def test_cancellation_and_unknown(self):
        # Cancelled
        err_cancel = ErrorClassifier.classify("Download cancelled by user")
        self.assertEqual(err_cancel.category, ErrorCategory.CANCELLED)
        self.assertFalse(err_cancel.retryable)

        # Unknown
        err_unk = ErrorClassifier.classify("Unexpected internal glitch 999xyz")
        self.assertEqual(err_unk.category, ErrorCategory.UNKNOWN_ERROR)
        self.assertFalse(err_unk.retryable)

    def test_file_locked_winerror_32(self):
        # 1. Exact WinError 32 rename error from yt-dlp
        raw = (
            "ERROR: Unable to rename file:\n"
            "[WinError 32] The process cannot access the file because it is being used by another process: "
            "'C:\\Users\\Admin\\Downloads\\Music\\JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4.part' -> "
            "'C:\\Users\\Admin\\Downloads\\Music\\JaJamBo (Official Music) [f3CosPP_TVY].f137.mp4'. Giving up after 3 retries"
        )
        err = ErrorClassifier.classify(raw, video_id="f3CosPP_TVY", video_title="JaJamBo (Official Music)")
        self.assertEqual(err.category, ErrorCategory.FILE_LOCKED)
        self.assertEqual(err.category, ErrorCategory.FILE_ACCESS_CONFLICT)
        self.assertEqual(err.component, "Windows File System")
        self.assertEqual(err.stage, "File Finalization")
        self.assertEqual(err.concise_status, "Failed — File locked")
        self.assertIn("temporarily locked by another Windows process", err.user_message)
        self.assertIn("antivirus", err.suggested_action.lower())
        self.assertFalse(err.retryable)

        # Standardized diagnostic report
        report = err.to_report()
        self.assertIn("Error Category: FILE_LOCKED", report)
        self.assertIn("Component: Windows File System", report)
        self.assertIn("Stage: File Finalization", report)

        # 2. Chinese translation
        from core.i18n import I18nManager
        I18nManager.set_language("zh_CN")
        self.assertEqual(err.get_localized_title(), "文件重命名锁定 (WinError 32)")
        I18nManager.set_language("en")

    def test_i18n_status_translations(self):
        from core.i18n import I18nManager
        from core.models import VideoStatus

        # English mode
        I18nManager.set_language("en")
        self.assertEqual(I18nManager.get_status_label("Failed — HTTP 403"), "Failed — HTTP 403")
        self.assertEqual(I18nManager.get_status_label("Failed — File locked"), "Failed — File locked")
        self.assertEqual(I18nManager.get_status_label("Failed — Range error (416)"), "Failed — Range error (416)")
        self.assertEqual(I18nManager.get_status_label(VideoStatus.COMPLETED), "Completed")
        self.assertEqual(I18nManager.get_status_label(VideoStatus.FAILED), "Failed")

        # Chinese mode
        I18nManager.set_language("zh_CN")
        self.assertEqual(I18nManager.get_status_label("Failed — HTTP 403"), "失败 — HTTP 403")
        self.assertEqual(I18nManager.get_status_label("Failed — File locked"), "失败 — 文件被锁定")
        self.assertEqual(I18nManager.get_status_label("Failed — Range error (416)"), "失败 — 请求范围异常 (416)")
        self.assertEqual(I18nManager.get_status_label("Failed — Rate limited (429)"), "失败 — Rate limited (429)")
        self.assertEqual(I18nManager.get_status_label(VideoStatus.COMPLETED), "已完成")
        self.assertEqual(I18nManager.get_status_label(VideoStatus.FAILED), "失败")

        # Localized user message and suggested action
        err = ErrorClassifier.classify("Permission denied: 'C:\\test'")
        self.assertIn("权限", err.get_localized_user_message())
        self.assertIn("写入权限", err.get_localized_suggested_action())

        # Restore English
        I18nManager.set_language("en")
        self.assertIn("denied", err.get_localized_user_message())


class TestPrivacySanitizerAndReport(unittest.TestCase):
    """Tests credential redaction, path masking, and diagnostic report generation."""

    def test_token_and_cookie_scrubbing(self):
        dirty_string = (
            "Request failed with Cookie: session=abc123secretsession; and "
            "po_token=Mn8792hjs87ahkda87sydka87 and "
            "Authorization: Bearer my_secret_bearer_token"
        )
        sanitized = PrivacySanitizer.sanitize(dirty_string)
        self.assertNotIn("abc123secretsession", sanitized)
        self.assertNotIn("Mn8792hjs87ahkda87sydka87", sanitized)
        self.assertNotIn("my_secret_bearer_token", sanitized)
        self.assertIn("<REDACTED>", sanitized)

    def test_windows_user_path_scrubbing(self):
        path_string = r"Error opening file: C:\Users\Admin\AppData\Local\yt-dlp\cache.db"
        sanitized = PrivacySanitizer.sanitize(path_string)
        self.assertNotIn(r"C:\Users\Admin", sanitized)
        self.assertIn(r"<UserPath>\AppData\Local\yt-dlp\cache.db", sanitized)

    def test_report_structure(self):
        err = ErrorClassifier.classify(
            raw_error="[yt-dlp ERROR] unable to download video data: HTTP Error 403: Forbidden\nCookie: auth=xyz",
            stage="audio",
            video_id="TEST_VID_123",
            video_title="Secret Video Title",
        )
        runtime_info = {
            "yt-dlp": "2025.02.19",
            "ejs": "0.4.0",
            "deno": "2.1.2",
            "ffmpeg": "7.0.1",
        }
        report = err.to_report(runtime_info=runtime_info)

        self.assertIn("Channel Harvest Error Report", report)
        self.assertIn("Video: Secret Video Title", report)
        self.assertIn("Video ID: TEST_VID_123", report)
        self.assertIn("Stage: Audio", report)
        self.assertIn("Error Category: HTTP_403", report)
        self.assertIn("HTTP Status: 403", report)
        self.assertIn("What you can do:", report)
        self.assertIn("yt-dlp: 2025.02.19", report)
        self.assertIn("Deno: 2.1.2", report)
        self.assertIn("FFmpeg: 7.0.1", report)
        self.assertIn("EJS: 0.4.0", report)
        # Verify no unredacted cookie
        self.assertNotIn("xyz", report)
        self.assertIn("<REDACTED>", report)


class TestErrorTracker(unittest.TestCase):
    """Tests diagnostic session error tracking."""

    def setUp(self):
        ErrorTracker.clear_errors()

    def test_record_and_retrieve(self):
        self.assertIsNone(ErrorTracker.get_last_download_error())
        err = ErrorClassifier.classify("HTTP Error 404: Not Found", video_id="test1")
        ErrorTracker.record_error(err)
        last = ErrorTracker.get_last_download_error()
        self.assertIsNotNone(last)
        self.assertEqual(last.video_id, "test1")
        self.assertEqual(last.category, ErrorCategory.HTTP_404_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
