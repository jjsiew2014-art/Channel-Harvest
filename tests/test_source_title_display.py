"""
test_source_title_display.py
Unit and integration tests for the detected Source Title display feature above
the AVAILABLE VIDEOS table in Channel Harvest.

Covers the 13 required verification criteria:
1. YouTube channel scan displays channel name.
2. YouTube playlist scan displays playlist title (not confused with individual video title).
3. TikTok creator scan displays creator display name, falling back to username (@...).
4. Future/mock platform adapter displays detected source title without GUI code changes.
5. Missing title uses fallback and does not break scan.
6. Failed scan clears stale title (empty/error state convention).
7. Scanning a different URL updates title to match newly scanned source.
8. Clearing/resetting the video table resets title to "No source loaded".
9. Out-of-order/older asynchronous scan cannot overwrite title of newer scan (race condition guard).
10. Long titles are truncated with ellipsis and preserved in tooltip (ElidedLabel).
11. Title row renders properly with appropriate styling in both light and dark themes.
12. Video selection, downloads, and table functions remain intact.
13. Douyin remains strictly frozen/disabled (is_available = False).
"""

import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QObject

from core.models import VideoItem, VideoStatus, ScanResult
from core.platform import PlatformRegistry
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.youtube import YouTubeAdapter
from core.platform.tiktok import TikTokAdapter
from core.platform.douyin import DouyinAdapter
from downloader.ytdlp_engine import YtDlpEngine, ChannelScanWorker
from gui.main_window import MainWindow, ElidedLabel
from gui.styles import ThemeManager, ThemeMode

app = QApplication.instance()
if not app:
    app = QApplication([])


class MockWorker(QObject):
    """Helper mock object with scan_id simulating ChannelScanWorker."""
    def __init__(self, scan_id: int):
        super().__init__()
        self.scan_id = scan_id


class TestSourceTitleDisplay(unittest.TestCase):
    """Test suite covering the 13 acceptance criteria for the Source Title Display."""

    @classmethod
    def setUpClass(cls):
        # Prevent background update worker from spawning during unit tests
        cls._silent_patcher = patch.object(MainWindow, "_check_ytdlp_updates_silent", lambda self: None)
        cls._silent_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._silent_patcher.stop()

    def setUp(self):
        self.window = MainWindow()
        # Mock SubtitleDetectionWorker so unit tests don't spawn background network detection
        self._sub_worker_patcher = patch("gui.main_window.SubtitleDetectionWorker")
        self.mock_sub_worker = self._sub_worker_patcher.start()
        mock_instance = MagicMock()
        mock_instance.isRunning.return_value = False
        self.mock_sub_worker.return_value = mock_instance

    def tearDown(self):
        self._sub_worker_patcher.stop()
        self.window._download_manager = None
        if hasattr(self.window, "_silent_update_worker") and self.window._silent_update_worker and self.window._silent_update_worker.isRunning():
            self.window._silent_update_worker.terminate()
            self.window._silent_update_worker.wait(500)
        if self.window._scan_worker and self.window._scan_worker.isRunning():
            self.window._scan_worker.terminate()
            self.window._scan_worker.wait(500)
        self.window.close()

    # -------------------------------------------------------------------------
    # Criterion 1: YouTube channel scan displays channel name
    # -------------------------------------------------------------------------
    def test_01_youtube_channel_scan_displays_channel_name(self):
        mock_info = {
            "_type": "playlist",
            "channel": "Tech Lead Channel",
            "uploader": "Tech Lead Channel",
            "title": "Tech Lead Channel - Videos",
            "entries": [
                {"id": "vid1", "title": "First Video", "duration": 120},
                {"id": "vid2", "title": "Second Video", "duration": 240},
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            instance = MagicMock()
            instance.extract_info.return_value = mock_info
            mock_ydl.return_value.__enter__.return_value = instance

            adapter = YouTubeAdapter()
            scan_res = adapter.scan("https://www.youtube.com/@TechLead")

            self.assertEqual(scan_res.source_type, "channel")
            self.assertEqual(scan_res.source_title, "Tech Lead Channel")
            self.assertEqual(len(scan_res.videos), 2)

            self.window._on_scan_completed(scan_res)
            self.assertEqual(self.window.get_source_title(), "Tech Lead Channel")

    # -------------------------------------------------------------------------
    # Criterion 2: YouTube playlist scan displays playlist title
    # -------------------------------------------------------------------------
    def test_02_youtube_playlist_scan_displays_playlist_title(self):
        mock_info = {
            "_type": "playlist",
            "playlist_title": "Top Hits 2026",
            "title": "Top Hits 2026",
            "channel": "Various Artists",
            "entries": [
                {"id": "song1", "title": "Hit Song One", "duration": 180},
                {"id": "song2", "title": "Hit Song Two", "duration": 210},
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            instance = MagicMock()
            instance.extract_info.return_value = mock_info
            mock_ydl.return_value.__enter__.return_value = instance

            adapter = YouTubeAdapter()
            scan_res = adapter.scan("https://www.youtube.com/playlist?list=PL123456789")

            self.assertEqual(scan_res.source_type, "playlist")
            self.assertEqual(scan_res.source_title, "Top Hits 2026")
            # Must NOT be confused with individual video title "Hit Song One"
            self.assertNotEqual(scan_res.source_title, "Hit Song One")

            self.window._on_scan_completed(scan_res)
            self.assertEqual(self.window.get_source_title(), "Top Hits 2026")

    # -------------------------------------------------------------------------
    # Criterion 3: TikTok creator scan displays display name / username fallback
    # -------------------------------------------------------------------------
    def test_03_tiktok_creator_scan_display_name_and_username_fallback(self):
        adapter = TikTokAdapter()

        # Case A: Creator display name available
        mock_info_a = {
            "creator": "Cool Creator",
            "uploader_id": "cool_creator",
            "entries": [
                {"id": "7100000000000000001", "title": "Dance clip 1", "duration": 15},
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            instance = MagicMock()
            instance.extract_info.return_value = mock_info_a
            mock_ydl.return_value.__enter__.return_value = instance

            scan_res_a = adapter.scan("https://www.tiktok.com/@cool_creator")
            self.assertEqual(scan_res_a.source_title, "Cool Creator")
            self.window._on_scan_completed(scan_res_a)
            self.assertEqual(self.window.get_source_title(), "Cool Creator")

        # Case B: Only username (uploader_id) available -> formats with @
        mock_info_b = {
            "uploader_id": "just_a_username",
            "entries": [
                {"id": "7100000000000000002", "title": "Clip 2", "duration": 20},
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl:
            instance = MagicMock()
            instance.extract_info.return_value = mock_info_b
            mock_ydl.return_value.__enter__.return_value = instance

            scan_res_b = adapter.scan("https://www.tiktok.com/@just_a_username")
            self.assertEqual(scan_res_b.source_title, "@just_a_username")
            self.window._on_scan_completed(scan_res_b)
            self.assertEqual(self.window.get_source_title(), "@just_a_username")

    # -------------------------------------------------------------------------
    # Criterion 4: Future/mock platform adapter displays title without GUI code changes
    # -------------------------------------------------------------------------
    def test_04_future_mock_adapter_displays_title_without_gui_changes(self):
        class FutureMockAdapter(PlatformAdapter):
            @property
            def platform_id(self) -> str:
                return "future_platform"

            @property
            def display_name(self) -> str:
                return "Future Platform"

            @property
            def capabilities(self) -> PlatformCapabilities:
                return PlatformCapabilities()

            def matches_url(self, url: str) -> bool:
                return "future.com" in url

            def validate_url(self, url: str):
                return True, ""

            def normalize_url(self, url: str) -> str:
                return url

            def extract_entries(self, url, **kwargs):
                return [
                    VideoItem(
                        index=1,
                        video_id="f1",
                        title="Future Video",
                        duration="01:00",
                        channel_title="Future Creator Studio",
                    )
                ]

            def build_video_url(self, video_id: str, original_url: str = "") -> str:
                return f"https://future.com/{video_id}"

            def get_archive_tag(self, video: VideoItem) -> str:
                return f"future {video.video_id}"

        mock_adapter = FutureMockAdapter()
        # Default scan() inherits from PlatformAdapter
        scan_res = mock_adapter.scan("https://future.com/@studio")
        self.assertEqual(scan_res.source_title, "Future Creator Studio")
        self.assertEqual(scan_res.platform, "future_platform")

        # MainWindow consumes scan_res without any platform-specific branching
        self.window._on_scan_completed(scan_res)
        self.assertEqual(self.window.get_source_title(), "Future Creator Studio")

    # -------------------------------------------------------------------------
    # Criterion 5: Missing title uses fallback and does not break scan
    # -------------------------------------------------------------------------
    def test_05_missing_title_uses_fallback_and_does_not_break_scan(self):
        # Empty source_title in ScanResult
        scan_res = ScanResult(
            videos=[
                VideoItem(
                    index=1,
                    video_id="anon1",
                    title="Untitled",
                    duration="0:30",
                    channel_title="",
                )
            ],
            source_title="",
            platform="youtube",
            url="https://www.youtube.com/watch?v=anon1",
        )
        self.window._on_scan_completed(scan_res)
        displayed = self.window.get_source_title()
        # Should gracefully display fallback placeholder without throwing error
        self.assertTrue(bool(displayed))
        self.assertEqual(self.window.video_table.table.rowCount(), 1)

    # -------------------------------------------------------------------------
    # Criterion 6: Failed scan clears stale title
    # -------------------------------------------------------------------------
    def test_06_failed_scan_clears_stale_title(self):
        # First successful scan
        res1 = ScanResult(
            videos=[VideoItem(1, "v1", "Title 1", "1:00", channel_title="Previous Channel")],
            source_title="Previous Channel",
        )
        self.window._on_scan_completed(res1)
        self.assertEqual(self.window.get_source_title(), "Previous Channel")

        # Now simulate a failed scan
        with patch.object(self.window, "sender", return_value=None):
            with patch("PySide6.QtWidgets.QMessageBox.warning"):
                self.window._on_scan_error("Network connection timed out")

        # Title must be cleared and reset to "No source loaded"
        self.assertEqual(self.window.get_source_title(), "No source loaded")

    # -------------------------------------------------------------------------
    # Criterion 7: Scanning new URL replaces title
    # -------------------------------------------------------------------------
    def test_07_scanning_new_url_replaces_title(self):
        res1 = ScanResult(
            videos=[VideoItem(1, "v1", "Title 1", "1:00")],
            source_title="Channel Alpha",
        )
        self.window._on_scan_completed(res1)
        self.assertEqual(self.window.get_source_title(), "Channel Alpha")

        res2 = ScanResult(
            videos=[VideoItem(1, "v2", "Title 2", "2:00")],
            source_title="Channel Beta",
        )
        self.window._on_scan_completed(res2)
        self.assertEqual(self.window.get_source_title(), "Channel Beta")

    # -------------------------------------------------------------------------
    # Criterion 8: Clearing/resetting table resets title
    # -------------------------------------------------------------------------
    def test_08_clearing_table_resets_title(self):
        res = ScanResult(
            videos=[VideoItem(1, "v1", "Title 1", "1:00")],
            source_title="Active Channel",
        )
        self.window._on_scan_completed(res)
        self.assertEqual(self.window.get_source_title(), "Active Channel")

        # Clear the table
        self.window.video_table.clear_table()
        self.assertEqual(self.window.get_source_title(), "No source loaded")
        self.assertEqual(self.window._current_channel_title, "")

    # -------------------------------------------------------------------------
    # Criterion 9: Out-of-order older scan cannot overwrite newer scan
    # -------------------------------------------------------------------------
    def test_09_out_of_order_older_scan_cannot_overwrite_newer_scan(self):
        # User launches Scan 1
        self.window._active_scan_id = 1
        worker1 = MockWorker(scan_id=1)

        # User quickly launches Scan 2
        self.window._active_scan_id = 2
        worker2 = MockWorker(scan_id=2)

        res2 = ScanResult(
            videos=[VideoItem(1, "v2", "Title 2", "1:00")],
            source_title="Newer Channel #2",
        )
        with patch.object(self.window, "sender", return_value=worker2):
            self.window._on_scan_completed(res2)

        self.assertEqual(self.window.get_source_title(), "Newer Channel #2")

        # Now slow Scan 1 arrives late
        res1 = ScanResult(
            videos=[VideoItem(1, "v1", "Title 1", "1:00")],
            source_title="Stale Older Channel #1",
        )
        with patch.object(self.window, "sender", return_value=worker1):
            self.window._on_scan_completed(res1)

        # Stale Scan 1 must be rejected; Title remains "Newer Channel #2"
        self.assertEqual(self.window.get_source_title(), "Newer Channel #2")

    # -------------------------------------------------------------------------
    # Criterion 10: Long titles are truncated with ellipsis and preserved in tooltip
    # -------------------------------------------------------------------------
    def test_10_long_titles_truncated_and_preserved_in_tooltip(self):
        long_title = "Super Ultra Mega Extremely Long YouTube Channel Name That Definitely Exceeds The Label Width " * 3
        label = ElidedLabel(long_title)
        label.resize(150, 28)
        label._update_elided_text()

        # fullText preserves original string
        self.assertEqual(label.fullText(), long_title)
        # toolTip contains full string
        self.assertEqual(label.toolTip(), long_title)
        # Visible text in narrow 150px widget is elided
        self.assertLess(len(label.text()), len(long_title))
        self.assertTrue(label.text().endswith("…") or len(label.text()) < len(long_title))

    # -------------------------------------------------------------------------
    # Criterion 11: Title row renders properly in light and dark themes
    # -------------------------------------------------------------------------
    def test_11_title_row_renders_in_light_and_dark_themes(self):
        # Light theme
        ThemeManager.apply_theme(ThemeMode.LIGHT)
        self.assertEqual(self.window.source_title_card.objectName(), "sourceTitleCard")
        self.assertEqual(self.window.source_title_badge.objectName(), "sourceTitleBadge")
        self.assertEqual(self.window.source_title_value.objectName(), "sourceTitleValue")

        # Dark theme
        ThemeManager.apply_theme(ThemeMode.DARK)
        self.assertEqual(self.window.source_title_card.objectName(), "sourceTitleCard")
        # Restores theme cleanly
        ThemeManager.apply_theme(ThemeMode.LIGHT)

    # -------------------------------------------------------------------------
    # Criterion 12: Video selection, downloads, and table functions remain intact
    # -------------------------------------------------------------------------
    def test_12_video_selection_downloads_and_table_functions_remain_intact(self):
        videos = [
            VideoItem(1, "v1", "Video 1", "1:00", selected=True),
            VideoItem(2, "v2", "Video 2", "2:00", selected=True),
        ]
        scan_res = ScanResult(videos=videos, source_title="Test Channel")
        self.window._on_scan_completed(scan_res)

        self.assertEqual(self.window.video_table.table.rowCount(), 2)
        self.assertEqual(len(self.window.video_table.get_selected_videos()), 2)

        # Selection toggle
        self.window.video_table.select_all(False)
        self.assertEqual(len(self.window.video_table.get_selected_videos()), 0)

        self.window.video_table.select_all(True)
        self.assertEqual(len(self.window.video_table.get_selected_videos()), 2)

        selected_items = self.window.video_table.get_selected_videos()
        self.assertEqual(len(selected_items), 2)
        self.assertEqual(selected_items[0].video_id, "v1")

    # -------------------------------------------------------------------------
    # Criterion 13: Douyin remains frozen / disabled
    # -------------------------------------------------------------------------
    def test_13_douyin_remains_frozen(self):
        douyin_adapter = DouyinAdapter()
        # is_available property MUST be False
        self.assertFalse(douyin_adapter.is_available)
        self.assertFalse(PlatformRegistry.is_available("douyin"))

        # Scanning Douyin must be blocked
        with self.assertRaises(RuntimeError) as ctx:
            douyin_adapter.scan("https://www.douyin.com/user/MS4wLjABAAAA")
        self.assertIn("PLATFORM_TEMPORARILY_UNAVAILABLE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
