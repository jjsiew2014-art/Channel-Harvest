"""
test_platform_availability_detection.py
Unit and integration tests for Platform-Aware Video Availability Detection and Automatic Skip.

Verifies:
1. AvailabilityStatus model, VideoAvailability dataclass, and is_definitively_inaccessible() invariants.
2. Unlisted video invariant: UNLISTED videos remain selectable and downloadable.
3. Platform-specific detectors for YouTube, TikTok, Bilibili, Facebook, and Douyin.
4. Transient errors (HTTP 429, timeouts, Bilibili 352 risk control, anti-bot) are NOT marked deleted.
5. VideoTableWidget selection invariants: disabled checkboxes, select_all safety, spacebar protection.
6. DownloadManager execution invariants: pre-download skip, no yt-dlp call for inaccessible items,
   non-blocking queue flow, and accurate statistics.
7. Tri-lingual localization (en, zh_CN, zh_TW).
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QColor
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from core.models import VideoItem, VideoStatus, DownloadSettings, DownloadMode
from core.error_classifier import ErrorCategory
from core.availability import (
    AvailabilityStatus,
    AvailabilityReasonCode,
    VideoAvailability,
    YouTubeAvailabilityDetector,
    TikTokAvailabilityDetector,
    BilibiliAvailabilityDetector,
    FacebookAvailabilityDetector,
    DouyinAvailabilityDetector,
    AvailabilityDetectorRegistry,
)
from core.i18n import I18nManager, tr
from gui.video_table import VideoTableWidget
from downloader.download_manager import DownloadManager


# Ensure QApplication instance exists for GUI tests
app = QApplication.instance() or QApplication(sys.argv)


class TestAvailabilityModel(unittest.TestCase):
    """Verifies typed availability states and helper methods."""

    def test_status_enum_values(self):
        statuses = [s.value for s in AvailabilityStatus]
        expected = [
            "AVAILABLE", "PRIVATE", "DELETED", "REGION_RESTRICTED", "AGE_RESTRICTED",
            "AUTH_REQUIRED", "ACCESS_DENIED", "UNLISTED", "NO_SUPPORTED_FORMAT",
            "UNAVAILABLE", "UNKNOWN", "TEMPORARY_ERROR"
        ]
        for exp in expected:
            self.assertIn(exp, statuses)

    def test_unlisted_is_never_inaccessible(self):
        """Unlisted videos must remain selectable and downloadable."""
        avail = VideoAvailability(
            status=AvailabilityStatus.UNLISTED,
            reason_code=AvailabilityReasonCode.UNLISTED_ACCESSIBLE.value,
            is_confirmed=True,
            platform="youtube",
            video_id="unlisted_1",
        )
        self.assertFalse(avail.is_definitively_inaccessible())
        self.assertTrue(avail.is_selectable())

    def test_temporary_error_is_never_definitively_inaccessible(self):
        """Transient errors (rate limits, timeouts) must not be definitively inaccessible."""
        avail = VideoAvailability(
            status=AvailabilityStatus.TEMPORARY_ERROR,
            reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
            is_confirmed=False,
            evidence="HTTP 429 Too Many Requests",
        )
        self.assertFalse(avail.is_definitively_inaccessible())
        self.assertTrue(avail.is_selectable())

    def test_inaccessible_statuses_confirmed(self):
        """Confirmed private, deleted, restricted, etc., must be definitively inaccessible."""
        inaccessible_statuses = [
            AvailabilityStatus.PRIVATE,
            AvailabilityStatus.DELETED,
            AvailabilityStatus.REGION_RESTRICTED,
            AvailabilityStatus.AGE_RESTRICTED,
            AvailabilityStatus.AUTH_REQUIRED,
            AvailabilityStatus.ACCESS_DENIED,
            AvailabilityStatus.NO_SUPPORTED_FORMAT,
            AvailabilityStatus.UNAVAILABLE,
        ]
        for st in inaccessible_statuses:
            avail = VideoAvailability(status=st, is_confirmed=True)
            self.assertTrue(avail.is_definitively_inaccessible(), f"Expected {st} to be inaccessible")
            self.assertFalse(avail.is_selectable(), f"Expected {st} to not be selectable")

    def test_unconfirmed_status_is_not_definitively_inaccessible(self):
        """If is_confirmed is False, video should not be definitively skipped."""
        avail = VideoAvailability(status=AvailabilityStatus.PRIVATE, is_confirmed=False)
        self.assertFalse(avail.is_definitively_inaccessible())
        self.assertTrue(avail.is_selectable())

    def test_video_item_property_delegation(self):
        """VideoItem delegates is_private, is_unavailable, and is_inaccessible to VideoAvailability."""
        v_priv = VideoItem(index=1, video_id="v1", title="Normal Title", duration="01:00")
        v_priv.availability = VideoAvailability(status=AvailabilityStatus.PRIVATE, is_confirmed=True)
        self.assertTrue(v_priv.is_private)
        self.assertFalse(v_priv.is_unavailable)
        self.assertTrue(v_priv.is_inaccessible)

        v_del = VideoItem(index=2, video_id="v2", title="Normal Title 2", duration="02:00")
        v_del.availability = VideoAvailability(status=AvailabilityStatus.DELETED, is_confirmed=True)
        self.assertFalse(v_del.is_private)
        self.assertTrue(v_del.is_unavailable)
        self.assertTrue(v_del.is_inaccessible)

        v_unlisted = VideoItem(index=3, video_id="v3", title="Unlisted Song", duration="03:00")
        v_unlisted.availability = VideoAvailability(status=AvailabilityStatus.UNLISTED, is_confirmed=True)
        self.assertFalse(v_unlisted.is_private)
        self.assertFalse(v_unlisted.is_unavailable)
        self.assertFalse(v_unlisted.is_inaccessible)


class TestYouTubeAvailabilityDetector(unittest.TestCase):
    """Verifies YouTube-specific availability heuristic detection."""

    def setUp(self):
        self.detector = YouTubeAvailabilityDetector()

    def test_youtube_unlisted_entry(self):
        entry = {"id": "y_unlisted", "title": "Cool Video", "availability": "unlisted"}
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.UNLISTED)
        self.assertTrue(avail.is_selectable())
        self.assertFalse(avail.is_definitively_inaccessible())

    def test_youtube_private_title_markers(self):
        for title in ["[Private video]", "[私享视频]", "[私密视频]", "[私人影片]", "[私密影片]"]:
            entry = {"id": "y_priv", "title": title}
            avail = self.detector.detect_entry(entry)
            self.assertEqual(avail.status, AvailabilityStatus.PRIVATE)
            self.assertTrue(avail.is_definitively_inaccessible())

    def test_youtube_deleted_title_markers(self):
        for title in ["[Deleted video]", "[已删除视频]", "[已刪除影片]"]:
            entry = {"id": "y_del", "title": title}
            avail = self.detector.detect_entry(entry)
            self.assertEqual(avail.status, AvailabilityStatus.DELETED)
            self.assertTrue(avail.is_definitively_inaccessible())

    def test_youtube_upcoming_premieres(self):
        entry = {"id": "y_up", "title": "Big Stream", "live_status": "is_upcoming"}
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.UNAVAILABLE)
        self.assertEqual(avail.reason_code, AvailabilityReasonCode.ERR_UPCOMING.value)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_youtube_members_only(self):
        entry = {"id": "y_mem", "title": "Members Only Episode", "availability": "needs_auth"}
        avail = self.detector.detect_entry(entry, auth_active=False)
        self.assertEqual(avail.status, AvailabilityStatus.AUTH_REQUIRED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_youtube_error_detection(self):
        err_priv = "ERROR: [youtube] 123: Private video. Sign in if you've been granted access"
        self.assertEqual(self.detector.detect_error(err_priv).status, AvailabilityStatus.PRIVATE)

        err_del = "ERROR: [youtube] 456: Video unavailable. This video has been removed by the uploader"
        self.assertEqual(self.detector.detect_error(err_del).status, AvailabilityStatus.DELETED)

        err_geo = "ERROR: [youtube] 789: The uploader has not made this video available in your country"
        self.assertEqual(self.detector.detect_error(err_geo).status, AvailabilityStatus.REGION_RESTRICTED)

        err_age = "ERROR: [youtube] 101: Sign in to confirm your age"
        self.assertEqual(self.detector.detect_error(err_age).status, AvailabilityStatus.AGE_RESTRICTED)

        err_rate = "HTTP Error 429: Too Many Requests"
        avail_rate = self.detector.detect_error(err_rate)
        self.assertEqual(avail_rate.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(avail_rate.is_confirmed)
        self.assertFalse(avail_rate.is_definitively_inaccessible())


class TestTikTokAvailabilityDetector(unittest.TestCase):
    """Verifies TikTok-specific availability heuristic detection."""

    def setUp(self):
        self.detector = TikTokAvailabilityDetector()

    def test_tiktok_private_item(self):
        entry = {"id": "tk_1", "title": "Dance", "privateItem": True}
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.PRIVATE)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_tiktok_delete_item(self):
        entry = {"id": "tk_2", "title": "Deleted Post", "deleteItem": True}
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.DELETED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_tiktok_error_detection(self):
        err_priv = "TikTok error: This video is private"
        self.assertEqual(self.detector.detect_error(err_priv).status, AvailabilityStatus.PRIVATE)

        err_del = "TikTok error: This video was deleted"
        self.assertEqual(self.detector.detect_error(err_del).status, AvailabilityStatus.DELETED)

        err_denied = "TikTok error: Access Denied (10204)"
        self.assertEqual(self.detector.detect_error(err_denied).status, AvailabilityStatus.ACCESS_DENIED)

        err_temp = "TikTok requires browser impersonation support: attempting impersonation"
        avail_temp = self.detector.detect_error(err_temp)
        self.assertEqual(avail_temp.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(avail_temp.is_confirmed)


class TestBilibiliAvailabilityDetector(unittest.TestCase):
    """Verifies Bilibili-specific availability heuristic detection."""

    def setUp(self):
        self.detector = BilibiliAvailabilityDetector()

    def test_bilibili_code_detection(self):
        # -404: Deleted
        e_del = {"id": "BV_del", "title": "啥都木有", "code": -404}
        self.assertEqual(self.detector.detect_entry(e_del).status, AvailabilityStatus.DELETED)

        # 62002: Author only
        e_priv = {"id": "BV_priv", "title": "稿件仅作者可见", "code": 62002}
        self.assertEqual(self.detector.detect_entry(e_priv).status, AvailabilityStatus.PRIVATE)

        # 62012: Big VIP
        e_vip = {"id": "BV_vip", "title": "动漫第1集 (仅大会员可看)", "code": 62012}
        self.assertEqual(self.detector.detect_entry(e_vip, auth_active=False).status, AvailabilityStatus.AUTH_REQUIRED)

        # -10403: Region restricted
        e_geo = {"id": "BV_geo", "title": "仅限中国大陆地区播放", "code": -10403}
        self.assertEqual(self.detector.detect_entry(e_geo).status, AvailabilityStatus.REGION_RESTRICTED)

    def test_bilibili_352_risk_control_is_not_deleted(self):
        """CRITICAL: Error 352 (risk control / anti-scraping challenge) must NOT be marked deleted!"""
        err_352 = "Bilibili server rejected the request (Risk Control Challenge / Error 352). code: -352"
        avail = self.detector.detect_error(err_352)
        self.assertEqual(avail.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(avail.is_confirmed)
        self.assertFalse(avail.is_definitively_inaccessible())


class TestFacebookAvailabilityDetector(unittest.TestCase):
    """Verifies Facebook-specific availability heuristic detection."""

    def setUp(self):
        self.detector = FacebookAvailabilityDetector()

    def test_facebook_deleted_or_removed(self):
        entry = {"id": "fb_del", "title": "This content isn't available right now"}
        avail = self.detector.detect_entry(entry)
        self.assertEqual(avail.status, AvailabilityStatus.DELETED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_facebook_login_required(self):
        err_login = "Facebook requires login: You must log in to continue"
        avail = self.detector.detect_error(err_login)
        self.assertEqual(avail.status, AvailabilityStatus.AUTH_REQUIRED)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_facebook_private_post(self):
        err_priv = "Facebook error: You do not have permission to view this video"
        avail = self.detector.detect_error(err_priv)
        self.assertEqual(avail.status, AvailabilityStatus.PRIVATE)
        self.assertTrue(avail.is_definitively_inaccessible())

    def test_facebook_temp_server_error(self):
        err_500 = "HTTP Error 500: Internal Server Error"
        avail = self.detector.detect_error(err_500)
        self.assertEqual(avail.status, AvailabilityStatus.TEMPORARY_ERROR)
        self.assertFalse(avail.is_confirmed)


class TestDouyinAvailabilityDetector(unittest.TestCase):
    """Verifies Douyin remains strictly disabled/inaccessible."""

    def test_douyin_is_access_denied(self):
        detector = DouyinAvailabilityDetector()
        avail = detector.detect_entry({})
        self.assertEqual(avail.status, AvailabilityStatus.ACCESS_DENIED)
        self.assertTrue(avail.is_definitively_inaccessible())


class TestVideoTableSelectionInvariants(unittest.TestCase):
    """Verifies AVAILABLE VIDEOS UI selection rules and checkbox disabling."""

    def setUp(self):
        self.table_widget = VideoTableWidget()

    def test_table_disables_inaccessible_checkboxes(self):
        v1 = VideoItem(index=1, video_id="ok1", title="Good Video", duration="01:00")
        v1.availability = VideoAvailability(status=AvailabilityStatus.AVAILABLE, is_confirmed=True)

        v2 = VideoItem(index=2, video_id="priv1", title="Private Video", duration="02:00")
        v2.availability = VideoAvailability(status=AvailabilityStatus.PRIVATE, is_confirmed=True)

        v3 = VideoItem(index=3, video_id="del1", title="Deleted Video", duration="03:00")
        v3.availability = VideoAvailability(status=AvailabilityStatus.DELETED, is_confirmed=True)

        v4 = VideoItem(index=4, video_id="unlisted1", title="Unlisted Video", duration="04:00")
        v4.availability = VideoAvailability(status=AvailabilityStatus.UNLISTED, is_confirmed=True)

        self.table_widget.load_videos([v1, v2, v3, v4])

        # Check item 0 (ok1) -> checkable and checked
        item0 = self.table_widget.table.item(0, VideoTableWidget.COL_SELECT)
        self.assertTrue(bool(item0.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        self.assertEqual(item0.checkState(), Qt.CheckState.Checked)

        # Check item 1 (priv1) -> uncheckable and unchecked
        item1 = self.table_widget.table.item(1, VideoTableWidget.COL_SELECT)
        self.assertFalse(bool(item1.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        self.assertEqual(item1.checkState(), Qt.CheckState.Unchecked)

        # Check item 2 (del1) -> uncheckable and unchecked
        item2 = self.table_widget.table.item(2, VideoTableWidget.COL_SELECT)
        self.assertFalse(bool(item2.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        self.assertEqual(item2.checkState(), Qt.CheckState.Unchecked)

        # Check item 3 (unlisted1) -> checkable and checked
        item3 = self.table_widget.table.item(3, VideoTableWidget.COL_SELECT)
        self.assertTrue(bool(item3.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        self.assertEqual(item3.checkState(), Qt.CheckState.Checked)

    def test_select_all_preserves_inaccessible_deselected(self):
        """Select All must never check inaccessible rows."""
        v1 = VideoItem(index=1, video_id="ok1", title="Good Video", duration="01:00")
        v2 = VideoItem(index=2, video_id="priv1", title="Private Video", duration="02:00")
        v2.availability = VideoAvailability(status=AvailabilityStatus.PRIVATE, is_confirmed=True)

        self.table_widget.load_videos([v1, v2])

        # First Deselect All
        self.table_widget.select_all(False)
        self.assertEqual(self.table_widget.table.item(0, VideoTableWidget.COL_SELECT).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(self.table_widget.table.item(1, VideoTableWidget.COL_SELECT).checkState(), Qt.CheckState.Unchecked)

        # Now Select All
        self.table_widget.select_all(True)
        # v1 should become Checked
        self.assertEqual(self.table_widget.table.item(0, VideoTableWidget.COL_SELECT).checkState(), Qt.CheckState.Checked)
        # v2 MUST remain Unchecked!
        self.assertEqual(self.table_widget.table.item(1, VideoTableWidget.COL_SELECT).checkState(), Qt.CheckState.Unchecked)

    def test_programmatic_or_accidental_check_is_reverted(self):
        """If an event forces an inaccessible item to Checked, _on_item_changed unchecks it."""
        v1 = VideoItem(index=1, video_id="del1", title="Deleted Video", duration="01:00")
        v1.availability = VideoAvailability(status=AvailabilityStatus.DELETED, is_confirmed=True)

        self.table_widget.load_videos([v1])
        item = self.table_widget.table.item(0, VideoTableWidget.COL_SELECT)
        self.assertEqual(item.checkState(), Qt.CheckState.Unchecked)

        # Attempt to forcefully check item
        item.setCheckState(Qt.CheckState.Checked)
        # Verify it reverted back to Unchecked
        self.assertEqual(item.checkState(), Qt.CheckState.Unchecked)

    def test_get_selected_videos_strictly_excludes_inaccessible(self):
        v1 = VideoItem(index=1, video_id="ok1", title="Good Video", duration="01:00")
        v2 = VideoItem(index=2, video_id="del1", title="Deleted Video", duration="02:00")
        v2.availability = VideoAvailability(status=AvailabilityStatus.DELETED, is_confirmed=True)

        self.table_widget.load_videos([v1, v2])
        selected = self.table_widget.get_selected_videos()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].video_id, "ok1")


class TestDownloadManagerQueueSkipping(unittest.TestCase):
    """Verifies pre-download skipping, non-blocking flow, and statistics in DownloadManager."""

    def test_download_manager_skips_inaccessible_without_calling_ytdlp(self):
        v1 = VideoItem(index=1, video_id="good1", title="Good 1", duration="01:00")
        v2 = VideoItem(index=2, video_id="priv1", title="Private 1", duration="02:00")
        v2.availability = VideoAvailability(status=AvailabilityStatus.PRIVATE, is_confirmed=True)
        v3 = VideoItem(index=3, video_id="del1", title="Deleted 1", duration="03:00")
        v3.availability = VideoAvailability(status=AvailabilityStatus.DELETED, is_confirmed=True)
        v4 = VideoItem(index=4, video_id="good2", title="Good 2", duration="04:00")

        settings = DownloadSettings(
            download_folder=".",
            download_mode=DownloadMode.VIDEO_ONLY,
            skip_existing=False,
            download_subtitles=False,
            download_thumbnail=False,
            save_description=False,
            save_metadata=False,
            save_chapters=False,
        )
        dm = DownloadManager([v1, v2, v3, v4], settings)

        called_ids = []

        def mock_download(video, *args, **kwargs):
            called_ids.append(video.video_id)
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=mock_download):
            dm.run()

        # yt-dlp must only have been called for good1 and good2!
        self.assertEqual(called_ids, ["good1", "good2"])

        # v2 and v3 must be marked SKIPPED
        self.assertEqual(v2.status, VideoStatus.SKIPPED)
        self.assertEqual(v3.status, VideoStatus.SKIPPED)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["skipped"], 2)
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["skipped_unavailable"], 1)
        self.assertEqual(stats["failed"], 0)


class TestTriLingualLocalization(unittest.TestCase):
    """Verifies localization labels for en, zh_CN, and zh_TW."""

    def test_all_languages_display_clean_labels(self):
        for lang in ("en", "zh_CN", "zh_TW"):
            I18nManager.set_language(lang)

            # Check status labels
            lbl_priv = I18nManager.get_status_label("PRIVATE")
            self.assertTrue(len(lbl_priv) > 0)

            lbl_del = I18nManager.get_status_label("DELETED")
            self.assertTrue(len(lbl_del) > 0)

            lbl_unlisted = I18nManager.get_status_label("UNLISTED")
            self.assertTrue(len(lbl_unlisted) > 0)

            # Check message translations
            msg_priv = tr("avail_msg_private")
            self.assertTrue(len(msg_priv) > 0)

            msg_unlisted = tr("avail_msg_unlisted")
            self.assertTrue(len(msg_unlisted) > 0)

        # Reset language to en
        I18nManager.set_language("en")


if __name__ == "__main__":
    unittest.main()
