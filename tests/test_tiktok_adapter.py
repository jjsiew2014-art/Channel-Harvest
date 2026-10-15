"""
test_tiktok_adapter.py
Comprehensive unit tests for the TikTok platform adapter, URL detection, capabilities,
error handling, file organization, and settings persistence in Channel Harvest.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.platform.tiktok import TikTokAdapter
from core.platform.detector import PlatformDetector, PlatformRegistry
from core.error_classifier import ErrorClassifier, ErrorCategory
from core.paths import resolve_video_output_dir, should_include_video_id, resolve_media_filename, sanitize_filename
from core.settings import SettingsManager


class TestTikTokAdapter(unittest.TestCase):
    """Tests for the TikTokAdapter implementation."""

    def setUp(self):
        self.adapter = TikTokAdapter()

    def test_properties(self):
        self.assertEqual(self.adapter.platform_id, "tiktok")
        self.assertEqual(self.adapter.display_name, "TikTok")
        caps = self.adapter.capabilities
        self.assertTrue(caps.supports_video)
        self.assertTrue(caps.supports_audio)
        self.assertTrue(caps.supports_thumbnails)
        self.assertTrue(caps.supports_description)
        self.assertTrue(caps.supports_metadata)
        self.assertFalse(caps.supports_subtitles)
        self.assertFalse(caps.supports_chapters)
        self.assertTrue(caps.supports_playlists)
        self.assertTrue(caps.supports_channel_scan)
        self.assertFalse(caps.supports_browser_cookies)
        self.assertFalse(caps.supports_cookie_file)
        self.assertEqual(caps.archive_prefix, "tiktok")

    def test_matches_url(self):
        # Valid TikTok URLs
        valid_urls = [
            "https://www.tiktok.com/@tiktok/video/7106594312292453678",
            "http://tiktok.com/@creator/video/1234567890123456789",
            "https://m.tiktok.com/v/7106594312292453678.html",
            "https://vm.tiktok.com/ZM8example/",
            "https://vt.tiktok.com/ZS8example/",
            "https://www.tiktok.com/@khaby.lame",
            "https://tiktok.com/@user",
        ]
        for url in valid_urls:
            self.assertTrue(self.adapter.matches_url(url), f"Should match TikTok: {url}")

        # Invalid or non-TikTok URLs
        invalid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.instagram.com/reel/C123456/",
            "https://douyin.com/video/123456",
            "https://example.com/tiktok",
            "",
            None,
        ]
        for url in invalid_urls:
            self.assertFalse(self.adapter.matches_url(url), f"Should not match TikTok: {url}")

    def test_validate_url(self):
        # Valid URLs
        valid_urls = [
            "https://www.tiktok.com/@creator/video/7106594312292453678",
            "https://vm.tiktok.com/ZM8123456/",
            "https://www.tiktok.com/@creator",
        ]
        for url in valid_urls:
            is_valid, err = self.adapter.validate_url(url)
            self.assertTrue(is_valid, f"Should be valid: {url}, got error: {err}")
            self.assertEqual(err, "")

        # Empty
        is_valid, err = self.adapter.validate_url("")
        self.assertFalse(is_valid)
        self.assertIn("cannot be empty", err)

        # No scheme
        is_valid, err = self.adapter.validate_url("ftp://tiktok.com/@creator")
        self.assertFalse(is_valid)
        self.assertIn("http:// or https://", err)

        # Non-TikTok domain
        is_valid, err = self.adapter.validate_url("https://www.youtube.com/@channel")
        self.assertFalse(is_valid)
        self.assertIn("not a valid TikTok domain", err)

        # Bare domain with no path
        is_valid, err = self.adapter.validate_url("https://www.tiktok.com/")
        self.assertFalse(is_valid)
        self.assertIn("specific TikTok video or creator profile", err)

    def test_normalize_url(self):
        tracked_url = "https://www.tiktok.com/@creator/video/7106594312292453678?is_from_webapp=1&sender_device=pc&_r=1"
        normalized = self.adapter.normalize_url(tracked_url)
        self.assertEqual(normalized, "https://www.tiktok.com/@creator/video/7106594312292453678")


class TestPlatformDetectorAndRegistry(unittest.TestCase):
    """Tests for platform detection and registry operations."""

    def test_identify_platform_id(self):
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.youtube.com/@Veritasium"), "youtube")
        self.assertEqual(PlatformDetector.identify_platform_id("https://youtu.be/dQw4w9WgXcQ"), "youtube")
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.tiktok.com/@tiktok/video/123"), "tiktok")
        self.assertEqual(PlatformDetector.identify_platform_id("https://vm.tiktok.com/ZM8123/"), "tiktok")
        self.assertEqual(PlatformDetector.identify_platform_id("https://vt.tiktok.com/ZS8123/"), "tiktok")
        self.assertEqual(PlatformDetector.identify_platform_id("https://www.douyin.com/video/123"), "douyin")
        self.assertEqual(PlatformDetector.identify_platform_id("https://example.com/video"), "unknown")
        self.assertEqual(PlatformDetector.identify_platform_id(""), "unknown")

    def test_registry_resolution(self):
        yt_adapter = PlatformRegistry.get_adapter("youtube")
        self.assertIsNotNone(yt_adapter)
        self.assertEqual(yt_adapter.platform_id, "youtube")

        tt_adapter = PlatformRegistry.get_adapter("tiktok")
        self.assertIsNotNone(tt_adapter)
        self.assertEqual(tt_adapter.platform_id, "tiktok")

        # Resolving via URL
        adapter_by_url = PlatformRegistry.get_adapter_for_url("https://www.tiktok.com/@test/video/12345")
        self.assertIsNotNone(adapter_by_url)
        self.assertEqual(adapter_by_url.platform_id, "tiktok")

        adapter_by_yt_url = PlatformRegistry.get_adapter_for_url("https://www.youtube.com/watch?v=12345678901")
        self.assertIsNotNone(adapter_by_yt_url)
        self.assertEqual(adapter_by_yt_url.platform_id, "youtube")


class TestTikTokErrorClassification(unittest.TestCase):
    """Tests that TikTok specific errors are accurately classified into the error model."""

    def test_status_10204_ip_blocked(self):
        raw = "ERROR: [TikTok] 7106594312292453678: TikTok said: status 10204: Your IP address is blocked from accessing this post"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7106594312292453678")
        self.assertEqual(err.category, ErrorCategory.REGION_RESTRICTED)
        self.assertFalse(err.retryable)
        self.assertIn("blocked", err.technical_details.lower())

    def test_tiktok_missing_impersonation_fail_fast(self):
        """Verifies missing impersonation fails fast and provides specific guidance without YouTube mentions."""
        raw = (
            "[TikTok] The extractor is attempting impersonation, but no impersonate target is available.\n"
            "ERROR: [TikTok] 7692114317151423775: Unable to download webpage: HTTP Error 403: Forbidden"
        )
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7692114317151423775")
        self.assertEqual(err.category, ErrorCategory.IMPERSONATION_ERROR)
        self.assertFalse(err.retryable)
        self.assertEqual(err.platform, "tiktok")
        self.assertEqual(
            err.user_message,
            "TikTok requires browser impersonation support, but the current runtime does not provide a compatible impersonation target.",
        )
        self.assertNotIn("YouTube", err.user_message)
        self.assertNotIn("YouTube", err.suggested_action)
        self.assertNotIn("Settings > YouTube", err.suggested_action)

        # Chinese localization verification
        zh_msg = err.get_localized_user_message("zh_CN")
        self.assertIn("TikTok 需要浏览器模拟 (impersonation) 支持", zh_msg)
        zh_act = err.get_localized_suggested_action("zh_CN")
        self.assertNotIn("YouTube", zh_act)

    def test_tiktok_http_403_no_youtube_leakage(self):
        """Verifies TikTok HTTP 403 has platform context and no YouTube authentication reference."""
        raw = "ERROR: [TikTok] 7692114317151423775: Unable to download webpage: HTTP Error 403: Forbidden"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7692114317151423775")
        self.assertEqual(err.category, ErrorCategory.HTTP_403_FORBIDDEN)
        self.assertTrue(err.retryable)  # Bounded retry for transient 403
        self.assertEqual(err.platform, "tiktok")
        self.assertEqual(err.user_message, "TikTok rejected the request (HTTP 403 Forbidden).")
        self.assertNotIn("YouTube", err.user_message)
        self.assertNotIn("YouTube", err.suggested_action)
        self.assertNotIn("Settings > YouTube", err.suggested_action)

        # Chinese localization
        zh_msg = err.get_localized_user_message("zh_CN")
        self.assertEqual(zh_msg, "TikTok 拒绝了请求 (HTTP 403 禁止访问)。")
        zh_act = err.get_localized_suggested_action("zh_CN")
        self.assertNotIn("YouTube", zh_act)

    def test_youtube_http_403_unaffected(self):
        """Verifies YouTube HTTP 403 continues to have YouTube-specific context."""
        raw = "ERROR: [youtube] dQw4w9WgXcQ: Unable to download webpage: HTTP Error 403: Forbidden"
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="dQw4w9WgXcQ")
        self.assertEqual(err.category, ErrorCategory.HTTP_403_FORBIDDEN)
        self.assertEqual(err.platform, "youtube")
        self.assertIn("YouTube", err.user_message)
        self.assertIn("YouTube", err.suggested_action)

    def test_tiktok_private_post_permission(self):
        raw = "ERROR: [TikTok] 7106594312292453678: This post is private. You do not have permission to view it."
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7106594312292453678")
        self.assertEqual(err.category, ErrorCategory.LOGIN_REQUIRED)
        self.assertEqual(err.platform, "tiktok")
        self.assertNotIn("YouTube", err.suggested_action)

    def test_tiktok_private_post(self):
        raw = "ERROR: [TikTok] 7106594312292453678: This post is private."
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7106594312292453678")
        self.assertEqual(err.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertEqual(err.platform, "tiktok")
        self.assertNotIn("YouTube", err.suggested_action)

    def test_tiktok_unavailable(self):
        raw = "ERROR: [TikTok] 7106594312292453678: Video unavailable or has been removed."
        err = ErrorClassifier.classify(raw, component="yt-dlp", stage="Video Download", video_id="7106594312292453678")
        self.assertEqual(err.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertEqual(err.platform, "tiktok")


class TestTikTokFileOrganization(unittest.TestCase):
    """Tests output naming and directory resolution for 19-digit numerical TikTok IDs."""

    def test_filename_with_and_without_id(self):
        title = "Funny TikTok Dance Video"
        video_id = "7106594312292453678"

        with_id = resolve_media_filename(title, video_id, include_video_id=True)
        self.assertEqual(with_id, f"Funny TikTok Dance Video [{video_id}]")

        without_id = resolve_media_filename(title, video_id, include_video_id=False)
        self.assertEqual(without_id, "Funny TikTok Dance Video")

    def test_long_caption_title_sanitization(self):
        long_caption = "A" * 200 + " #viral #fyp #tiktok"
        sanitized = sanitize_filename(long_caption, max_length=150)
        self.assertLessEqual(len(sanitized), 150)

    def test_directory_resolution_for_tiktok_id(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            video_id = "7106594312292453678"
            title = "Test TikTok Clip"

            # Normal unique individual folder
            target = resolve_video_output_dir(
                base_download_dir=base_dir,
                channel_title="TikTokCreator",
                create_channel_folder=True,
                video_title=title,
                video_id=video_id,
                create_individual_video_folders=True,
            )
            self.assertEqual(target.parent.name, "TikTokCreator")
            self.assertEqual(target.name, title)

            # With queue title collision -> ID suffix appended
            target_collision = resolve_video_output_dir(
                base_download_dir=base_dir,
                channel_title="TikTokCreator",
                create_channel_folder=True,
                video_title=title,
                video_id=video_id,
                create_individual_video_folders=True,
                duplicate_titles_in_queue={title},
            )
            self.assertEqual(target_collision.name, f"{title} [{video_id}]")


class TestSettingsPersistence(unittest.TestCase):
    """Tests that the selected platform setting persists correctly."""

    def test_selected_platform_persistence(self):
        with TemporaryDirectory() as tmp_dir:
            settings_file = Path(tmp_dir) / "settings.json"
            sm = SettingsManager(settings_path=settings_file)

            # Default should be youtube
            self.assertEqual(sm.get("selected_platform"), "youtube")

            # Update to tiktok and reload
            sm.set("selected_platform", "tiktok")

            sm2 = SettingsManager(settings_path=settings_file)
            self.assertEqual(sm2.get("selected_platform"), "tiktok")


class TestTikTokRuntimeDiagnostic(unittest.TestCase):
    """Tests runtime diagnostic and impersonation detection."""

    def test_impersonation_diagnostic_reporting(self):
        from downloader.runtime_manager import RuntimeManager, ImpersonationState
        diag = RuntimeManager.get_impersonation_diagnostic()

        self.assertIn("curl_cffi_available", diag)
        self.assertIn("curl_cffi_version", diag)
        self.assertIn("state", diag)
        self.assertIn("available_targets", diag)
        self.assertIn("default_target", diag)

        # In current environment, curl_cffi is installed
        self.assertTrue(diag["curl_cffi_available"])
        self.assertEqual(diag["state"], ImpersonationState.AVAILABLE.value)
        self.assertIsNotNone(diag["curl_cffi_version"])
        self.assertIsInstance(diag["available_targets"], list)
        self.assertGreater(len(diag["available_targets"]), 0)

    def test_diagnostic_report_formatting_and_privacy(self):
        from core.diagnostics import DiagnosticReporter
        report = DiagnosticReporter.generate_report()

        self.assertIn("Impersonation State", report)
        self.assertIn("curl_cffi Version", report)
        self.assertIn("Default Target", report)

        # Ensure strict privacy: no credentials, tokens, or cookie secrets leaked
        self.assertNotIn("sessionid", report)
        self.assertNotIn("token", report.lower())
        self.assertNotIn("cookie=", report.lower())


class TestTikTokUIIntegration(unittest.TestCase):
    """Verifies TikTok UI specific behaviors: subtitle column removal, title extension, and subtitle checkbox disabling."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_video_table_subtitle_column_hidden_on_tiktok(self):
        from gui.video_table import VideoTableWidget

        vt = VideoTableWidget()
        vt.resize(1000, 500)
        vt.show()
        self.app.processEvents()

        # YouTube platform
        vt.set_platform("youtube")
        self.app.processEvents()
        self.assertFalse(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        yt_title_width = vt.table.columnWidth(vt.COL_TITLE)

        # TikTok platform -> Subtitle hidden, Title horizontal width expanded
        vt.set_platform("tiktok")
        self.app.processEvents()
        self.assertTrue(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        tiktok_title_width = vt.table.columnWidth(vt.COL_TITLE)
        self.assertGreater(tiktok_title_width, yt_title_width)
        self.assertEqual(tiktok_title_width - yt_title_width, 150)

        # Switch back to YouTube -> Subtitle restored, Title width restored
        vt.set_platform("youtube")
        self.app.processEvents()
        self.assertFalse(vt.table.isColumnHidden(vt.COL_SUBTITLE))
        self.assertEqual(vt.table.columnWidth(vt.COL_SUBTITLE), 150)
        self.assertEqual(vt.table.columnWidth(vt.COL_TITLE), yt_title_width)

        vt.close()

    def test_main_window_tiktok_subtitles_greyed_out_and_table_extended(self):
        from gui.main_window import MainWindow

        w = MainWindow()
        w.resize(1100, 600)
        w.show()
        self.app.processEvents()

        # On YouTube: subtitles_cb is enabled
        w._apply_platform_ui("youtube")
        self.app.processEvents()
        self.assertTrue(w.subtitles_cb.isEnabled())
        self.assertFalse(w.video_table.table.isColumnHidden(w.video_table.COL_SUBTITLE))

        # On TikTok: subtitles_cb is greyed out (disabled) and unchecked
        w._apply_platform_ui("tiktok")
        self.app.processEvents()
        self.assertFalse(w.subtitles_cb.isEnabled())
        self.assertFalse(w.subtitles_cb.isChecked())
        self.assertIn("TikTok", w.subtitles_cb.toolTip())
        self.assertTrue(w.video_table.table.isColumnHidden(w.video_table.COL_SUBTITLE))

        # Switch back to YouTube: subtitles_cb is re-enabled, table restores subtitle column
        w._apply_platform_ui("youtube")
        self.app.processEvents()
        self.assertTrue(w.subtitles_cb.isEnabled())
        self.assertFalse(w.video_table.table.isColumnHidden(w.video_table.COL_SUBTITLE))

        w.close()


if __name__ == "__main__":
    unittest.main()

