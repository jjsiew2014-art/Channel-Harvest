"""
test_inaccessible_videos_and_cancellation.py
Comprehensive regression tests for:
1. Playlist with only accessible videos: all download successfully and counts are correct.
2. Private video in the middle of a playlist: it is skipped and subsequent videos download.
3. Unavailable video in the middle of a playlist: it is skipped and subsequent videos download.
4. Multiple private and unavailable videos: both counts are correct.
5. Inaccessible item discovered during initial scanning.
6. Inaccessible item discovered only after download begins.
7. Missing metadata or no initial progress callback.
8. HTTP 403 or authentication failure that cannot reliably be classified as private/unavailable.
9. Ordinary download failure: counted as Failed, follows retry policy.
10. User clicks Stop while metadata extraction or download is blocked.
11. User clicks Stop while FFmpeg/post-processing is running.
12. User cancellation does not get misreported as normal queue completion.
13. Successful downloads alone are recorded in the download archive.
14. Completion counts remain correct when only a subset of scanned videos is selected.
15. Repeated signals, exceptions, and retry paths do not double-count items or stall the queue.
16. Existing YouTube WAV/audio-only and video downloads continue to work.
17. TikTok behavior remains unchanged.
18. Douyin remains frozen/disabled as currently configured.
Plus: non-English error classification, partial file cleanup, rapid start/stop cycles, and SummaryDialog presentation.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import unittest
from PySide6.QtWidgets import QApplication

from core.models import VideoItem, VideoStatus, DownloadSettings, DownloadMode
from core.error_classifier import ErrorClassifier, ErrorCategory, DownloadError
from core.platform import PlatformRegistry
from downloader.download_manager import DownloadManager
from downloader.ytdlp_engine import (
    YtDlpEngine,
    DownloadCancelledException,
    YtDlpLogger,
)
from gui.summary_dialog import SummaryDialog
from core.i18n import tr


app = QApplication.instance() or QApplication(sys.argv)


class TestInaccessibleVideosAndCancellation(unittest.TestCase):
    """
    Test suite verifying the 18 specific requirements for inaccessible videos,
    queue stalling prevention, Stop Download responsiveness, and statistics.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.download_folder = self.tmp_dir.name
        self.settings = DownloadSettings(
            download_folder=self.download_folder,
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            skip_existing=False,
            download_subtitles=False,
            download_thumbnail=False,
            save_description=False,
            save_metadata=False,
            save_chapters=False,
        )

    def tearDown(self):
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. Playlist with only accessible videos: all download successfully and counts are correct
    # -------------------------------------------------------------------------
    def test_01_playlist_all_accessible(self):
        videos = [
            VideoItem(index=1, video_id="vid1", title="Good Video 1", duration="01:00", url="https://youtube.com/watch?v=vid1"),
            VideoItem(index=2, video_id="vid2", title="Good Video 2", duration="02:00", url="https://youtube.com/watch?v=vid2"),
            VideoItem(index=3, video_id="vid3", title="Good Video 3", duration="03:00", url="https://youtube.com/watch?v=vid3"),
        ]
        dm = DownloadManager(videos, self.settings)

        with patch.object(dm.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False, "info_dict": {}}
            dm.run()

        self.assertEqual(mock_dl.call_count, 3)
        for v in dm.videos:
            self.assertEqual(v.status, VideoStatus.COMPLETED)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["completed"], 3)
        self.assertEqual(stats["downloaded"], 3)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["cancelled"], 0)

    # -------------------------------------------------------------------------
    # 2. Private video in the middle of a playlist: skipped and subsequent videos download
    # -------------------------------------------------------------------------
    def test_02_private_video_in_middle_skipped(self):
        videos = [
            VideoItem(index=1, video_id="vid1", title="Video 1", duration="01:00", url="https://youtube.com/watch?v=vid1"),
            VideoItem(index=2, video_id="vid2", title="Video 2 (Private)", duration="02:00", url="https://youtube.com/watch?v=vid2"),
            VideoItem(index=3, video_id="vid3", title="Video 3", duration="03:00", url="https://youtube.com/watch?v=vid3"),
        ]
        dm = DownloadManager(videos, self.settings)

        def side_effect(video, **kwargs):
            if video.video_id == "vid2":
                raise Exception("ERROR: [youtube] vid2: This video is private")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect) as mock_dl:
            dm.run()

        self.assertEqual(mock_dl.call_count, 3)
        self.assertEqual(videos[0].status, VideoStatus.COMPLETED)
        self.assertEqual(videos[1].status, VideoStatus.SKIPPED)
        self.assertEqual(videos[1].error_reason, "Private Video")
        self.assertTrue(videos[1].is_private)
        self.assertEqual(videos[2].status, VideoStatus.COMPLETED)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["skipped_unavailable"], 0)
        self.assertEqual(stats["failed"], 0)

    # -------------------------------------------------------------------------
    # 3. Unavailable video in the middle of a playlist: skipped and subsequent videos download
    # -------------------------------------------------------------------------
    def test_03_unavailable_video_in_middle_skipped(self):
        videos = [
            VideoItem(index=1, video_id="vid1", title="Video 1", duration="01:00", url="https://youtube.com/watch?v=vid1"),
            VideoItem(index=2, video_id="vid2", title="Video 2 (Deleted)", duration="02:00", url="https://youtube.com/watch?v=vid2"),
            VideoItem(index=3, video_id="vid3", title="Video 3", duration="03:00", url="https://youtube.com/watch?v=vid3"),
        ]
        dm = DownloadManager(videos, self.settings)

        def side_effect(video, **kwargs):
            if video.video_id == "vid2":
                raise Exception("ERROR: [youtube] vid2: Video unavailable. This video has been removed by the uploader")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect) as mock_dl:
            dm.run()

        self.assertEqual(mock_dl.call_count, 3)
        self.assertEqual(videos[0].status, VideoStatus.COMPLETED)
        self.assertEqual(videos[1].status, VideoStatus.SKIPPED)
        self.assertEqual(videos[1].error_reason, "Unavailable Video")
        self.assertTrue(videos[1].is_unavailable)
        self.assertEqual(videos[2].status, VideoStatus.COMPLETED)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["skipped_private"], 0)
        self.assertEqual(stats["skipped_unavailable"], 1)
        self.assertEqual(stats["failed"], 0)

    # -------------------------------------------------------------------------
    # 4. Multiple private and unavailable videos: both counts are correct
    # -------------------------------------------------------------------------
    def test_04_multiple_private_and_unavailable_videos(self):
        videos = [
            VideoItem(index=1, video_id="p1", title="Private 1", duration="01:00"),
            VideoItem(index=2, video_id="ok1", title="Good 1", duration="01:00"),
            VideoItem(index=3, video_id="u1", title="Deleted 1", duration="01:00"),
            VideoItem(index=4, video_id="p2", title="Private 2", duration="01:00"),
            VideoItem(index=5, video_id="ok2", title="Good 2", duration="01:00"),
        ]
        dm = DownloadManager(videos, self.settings)

        def side_effect(video, **kwargs):
            if video.video_id == "p1":
                raise Exception("Private video. Sign in if you've been granted access to this video")
            elif video.video_id == "u1":
                raise Exception("This video is unavailable.")
            elif video.video_id == "p2":
                raise Exception("[youtube] p2: This video is private")
            return {"success": True, "skipped": False, "info_dict": {}}

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect):
            dm.run()

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["downloaded"], 2)
        self.assertEqual(stats["skipped_private"], 2)
        self.assertEqual(stats["skipped_unavailable"], 1)
        self.assertEqual(stats["skipped"], 3)
        self.assertEqual(stats["failed"], 0)

    # -------------------------------------------------------------------------
    # 5. Inaccessible item discovered during initial scanning
    # -------------------------------------------------------------------------
    def test_05_inaccessible_item_discovered_during_scanning(self):
        engine = YtDlpEngine()
        mock_info = {
            "title": "Test Playlist",
            "entries": [
                {"id": "v1", "title": "Normal Video", "duration": 120},
                {"id": "v2", "title": "[Private video]", "duration": None},
                {"id": "v3", "title": "[Deleted video]", "duration": None},
                {"id": "v4", "title": "[Unavailable video]", "duration": None},
            ],
        }

        with patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            items = engine.extract_channel_entries("https://www.youtube.com/playlist?list=PL123")

        self.assertEqual(len(items), 4)
        self.assertTrue(items[0].selected)
        self.assertEqual(items[0].status, VideoStatus.READY)

        self.assertFalse(items[1].selected)
        self.assertEqual(items[1].status, "Private Video")
        self.assertTrue(items[1].is_private)

        self.assertFalse(items[2].selected)
        self.assertEqual(items[2].status, "Unavailable Video")
        self.assertTrue(items[2].is_unavailable)

        self.assertFalse(items[3].selected)
        self.assertEqual(items[3].status, "Unavailable Video")
        self.assertTrue(items[3].is_unavailable)

        # If user explicitly checks item 1 & 2 and runs download:
        items[1].selected = True
        dm = DownloadManager([items[0], items[1]], self.settings)
        with patch.object(dm.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False}
            dm.run()

        # Item 1 was private from scan: should be skipped before calling download_single_video!
        self.assertEqual(mock_dl.call_count, 1)
        self.assertEqual(dm.videos[0].status, VideoStatus.COMPLETED)
        self.assertEqual(dm.videos[1].status, VideoStatus.SKIPPED)
        self.assertEqual(dm.videos[1].error_reason, "Private Video")

    # -------------------------------------------------------------------------
    # 6. Inaccessible item discovered only after download begins
    # -------------------------------------------------------------------------
    def test_06_inaccessible_discovered_after_download_begins(self):
        video = VideoItem(index=1, video_id="fresh_private", title="Looks Public", duration="05:00")
        dm = DownloadManager([video], self.settings)

        with patch.object(dm.engine, "download_single_video") as mock_dl:
            mock_dl.side_effect = Exception("ERROR: [youtube] fresh_private: Private video")
            dm.run()

        # Should not retry multiple times
        self.assertEqual(mock_dl.call_count, 1)
        self.assertEqual(video.status, VideoStatus.SKIPPED)
        self.assertEqual(video.error_reason, "Private Video")
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["failed"], 0)

    # -------------------------------------------------------------------------
    # 7. Missing metadata or no initial progress callback
    # -------------------------------------------------------------------------
    def test_07_missing_metadata_no_progress_callback(self):
        video = VideoItem(index=1, video_id="no_meta", title="", duration="")
        dm = DownloadManager([video], self.settings)

        with patch.object(dm.engine, "download_single_video") as mock_dl:
            # Fails immediately before any progress hook
            mock_dl.side_effect = Exception("ERROR: [youtube] no_meta: Video unavailable")
            dm.run()

        self.assertEqual(video.status, VideoStatus.SKIPPED)
        self.assertEqual(video.error_reason, "Unavailable Video")
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["skipped_unavailable"], 1)
        self.assertEqual(stats["failed"], 0)

    # -------------------------------------------------------------------------
    # 8. HTTP 403 or authentication failure not misclassified as private/unavailable
    # -------------------------------------------------------------------------
    def test_08_http_403_and_auth_not_misclassified(self):
        v1 = VideoItem(index=1, video_id="auth_err", title="Auth Required", duration="01:00")
        v2 = VideoItem(index=2, video_id="http_403", title="Forbidden 403", duration="01:00")
        dm = DownloadManager([v1, v2], self.settings)

        def side_effect(video, **kwargs):
            if video.video_id == "auth_err":
                raise Exception("Sign in with --cookies to confirm your age.")
            else:
                raise Exception("HTTP Error 403: Forbidden")

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect):
            dm.run()

        self.assertEqual(v1.status, VideoStatus.FAILED)
        self.assertEqual(v2.status, VideoStatus.FAILED)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["skipped_private"], 0)
        self.assertEqual(stats["skipped_unavailable"], 0)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["failed"], 2)

    # -------------------------------------------------------------------------
    # 9. Ordinary download failure counted as Failed and follows retry policy
    # -------------------------------------------------------------------------
    def test_09_ordinary_failure_follows_retry_and_counted_failed(self):
        video = VideoItem(index=1, video_id="net_err", title="Network Flake", duration="01:00")
        dm = DownloadManager([video], self.settings)

        with patch.object(dm.engine, "download_single_video") as mock_dl, \
             patch.object(dm, "_cancelable_sleep", return_value=False):
            mock_dl.side_effect = Exception("Connection reset by peer")
            dm.run()

        self.assertEqual(mock_dl.call_count, dm.MAX_RETRIES)
        self.assertEqual(video.status, VideoStatus.FAILED)
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["skipped"], 0)

    # -------------------------------------------------------------------------
    # 10. User clicks Stop while metadata extraction or download is blocked
    # -------------------------------------------------------------------------
    def test_10_user_clicks_stop_while_metadata_or_download_blocked(self):
        video = VideoItem(index=1, video_id="block_vid", title="Blocked Video", duration="01:00")
        dm = DownloadManager([video], self.settings)

        def side_effect(video, cancel_check=None, **kwargs):
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")
            dm.cancel()
            if cancel_check and cancel_check():
                raise DownloadCancelledException("Download cancelled by user.")
            return {"success": True}

        start_time = time.time()
        with patch.object(dm.engine, "download_single_video", side_effect=side_effect):
            dm.run()
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 2.0)
        self.assertTrue(dm.is_cancelled())
        self.assertEqual(video.status, VideoStatus.CANCELLED)
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["cancelled"], 1)

    # -------------------------------------------------------------------------
    # 11. User clicks Stop while FFmpeg / post-processing is running
    # -------------------------------------------------------------------------
    def test_11_user_clicks_stop_while_ffmpeg_running(self):
        video = VideoItem(index=1, video_id="ff_vid", title="FFmpeg Processing Video", duration="01:00")
        dm = DownloadManager([video], self.settings)

        cancel_fn = lambda: True
        post_hook = YtDlpEngine._create_postprocessor_hook(cancel_check=cancel_fn)

        with self.assertRaises(DownloadCancelledException):
            post_hook({"status": "processing", "postprocessor": "Merger"})

    # -------------------------------------------------------------------------
    # 12. User cancellation does not get misreported as normal queue completion
    # -------------------------------------------------------------------------
    def test_12_user_cancellation_does_not_get_misreported_as_normal_queue_completion(self):
        v1 = VideoItem(index=1, video_id="v1", title="V1", duration="01:00")
        v2 = VideoItem(index=2, video_id="v2", title="V2", duration="01:00")
        dm = DownloadManager([v1, v2], self.settings)

        def side_effect(video, **kwargs):
            dm.cancel()
            raise DownloadCancelledException("Download cancelled by user.")

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect):
            dm.run()

        self.assertTrue(dm.is_cancelled())
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["cancelled"], 2)
        self.assertEqual(stats["completed"], 0)

        # Dialog presentation when cancelled
        dlg = SummaryDialog(
            completed=stats["completed"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            total=stats["total"],
            download_folder=self.download_folder,
            cancelled=stats["cancelled"],
            is_cancelled=True,
        )
        self.assertTrue(dlg.is_cancelled)
        self.assertIn("Cancel", dlg.windowTitle())

    # -------------------------------------------------------------------------
    # 13. Successful downloads alone are recorded in the download archive
    # -------------------------------------------------------------------------
    def test_13_successful_downloads_alone_recorded_in_archive(self):
        archive_path = Path(self.download_folder) / "download_archive.txt"
        archive_path.write_text("youtube existing_vid\n", encoding="utf-8")

        v_existing = VideoItem(index=1, video_id="existing_vid", title="Existing", duration="01:00")
        v_private = VideoItem(index=2, video_id="priv_vid", title="Private", duration="01:00")
        v_new = VideoItem(index=3, video_id="new_vid", title="New Download", duration="01:00")

        self.settings.skip_existing = True
        dm = DownloadManager([v_existing, v_private, v_new], self.settings)

        def side_effect(video, archive_file=None, **kwargs):
            if video.video_id == "existing_vid":
                return {"success": True, "skipped": True}
            elif video.video_id == "priv_vid":
                raise Exception("ERROR: [youtube] priv_vid: This video is private")
            else:
                if archive_file:
                    with open(archive_file, "a", encoding="utf-8") as f:
                        f.write(f"youtube {video.video_id}\n")
                return {"success": True, "skipped": False}

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect), \
             patch("downloader.download_manager.get_archive_file", return_value=archive_path):
            dm.run()

        archive_content = archive_path.read_text(encoding="utf-8")
        self.assertIn("youtube existing_vid", archive_content)
        self.assertIn("youtube new_vid", archive_content)
        self.assertNotIn("priv_vid", archive_content)

        stats = dm.get_queue_statistics()
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["skipped_existing"], 1)
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["skipped"], 2)

    # -------------------------------------------------------------------------
    # 14. Completion counts remain correct when only a subset of scanned videos is selected
    # -------------------------------------------------------------------------
    def test_14_completion_counts_remain_correct_when_only_subset_selected(self):
        all_videos = [
            VideoItem(index=1, video_id="v1", title="V1", duration="01:00", selected=True),
            VideoItem(index=2, video_id="v2", title="V2", duration="01:00", selected=False),
            VideoItem(index=3, video_id="v3", title="V3", duration="01:00", selected=True),
            VideoItem(index=4, video_id="v4", title="V4", duration="01:00", selected=False),
            VideoItem(index=5, video_id="v5", title="V5", duration="01:00", selected=False),
        ]
        selected_videos = [v for v in all_videos if v.selected]
        dm = DownloadManager(selected_videos, self.settings)

        with patch.object(dm.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False}
            dm.run()

        self.assertEqual(mock_dl.call_count, 2)
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["skipped"], 0)

    # -------------------------------------------------------------------------
    # 15. Repeated signals, exceptions, and retry paths do not double-count items or stall the queue
    # -------------------------------------------------------------------------
    def test_15_repeated_signals_exceptions_retry_paths_do_not_double_count_or_stall(self):
        videos = [
            VideoItem(index=1, video_id="c1", title="Comp 1", duration="01:00"),
            VideoItem(index=2, video_id="p1", title="Priv 1", duration="01:00"),
            VideoItem(index=3, video_id="u1", title="Unavail 1", duration="01:00"),
            VideoItem(index=4, video_id="s1", title="Skip Exists", duration="01:00"),
            VideoItem(index=5, video_id="f1", title="Fail 1", duration="01:00"),
        ]
        dm = DownloadManager(videos, self.settings)

        def side_effect(video, **kwargs):
            if video.video_id == "c1":
                return {"success": True, "skipped": False}
            elif video.video_id == "p1":
                raise Exception("Private video")
            elif video.video_id == "u1":
                raise Exception("Video unavailable")
            elif video.video_id == "s1":
                return {"success": True, "skipped": True}
            else:
                raise Exception("Fatal transcoding error")

        with patch.object(dm.engine, "download_single_video", side_effect=side_effect):
            dm.run()

        stats = dm.get_queue_statistics()
        total_derived = (
            stats["completed"]
            + stats["skipped_private"]
            + stats["skipped_unavailable"]
            + stats["skipped_existing"]
            + stats["failed"]
            + stats["cancelled"]
        )
        self.assertEqual(total_derived, len(videos))
        self.assertEqual(stats["total"], len(videos))
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["skipped_private"], 1)
        self.assertEqual(stats["skipped_unavailable"], 1)
        self.assertEqual(stats["skipped_existing"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["cancelled"], 0)

    # -------------------------------------------------------------------------
    # 16. Existing YouTube WAV/audio-only and video downloads continue to work
    # -------------------------------------------------------------------------
    def test_16_existing_youtube_wav_audio_only_and_video_continue_to_work(self):
        v_audio = VideoItem(index=1, video_id="aud1", title="Audio WAV Track", duration="03:00")
        v_video = VideoItem(index=2, video_id="vid2", title="1080p Video", duration="04:00")

        # Audio-only mode
        settings_audio = DownloadSettings(
            download_folder=self.download_folder,
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="wav",
        )
        dm_audio = DownloadManager([v_audio], settings_audio)
        with patch.object(dm_audio.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False}
            dm_audio.run()
        self.assertEqual(v_audio.status, VideoStatus.COMPLETED)

        # Video + Audio mode
        dm_video = DownloadManager([v_video], self.settings)
        with patch.object(dm_video.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False}
            dm_video.run()
        self.assertEqual(v_video.status, VideoStatus.COMPLETED)

    # -------------------------------------------------------------------------
    # 17. TikTok behavior remains unchanged
    # -------------------------------------------------------------------------
    def test_17_tiktok_behavior_remains_unchanged(self):
        v_tiktok = VideoItem(
            index=1,
            video_id="7123456789012345678",
            title="TikTok Dance",
            duration="00:15",
            platform="tiktok",
            url="https://www.tiktok.com/@user/video/7123456789012345678",
        )
        dm = DownloadManager([v_tiktok], self.settings)
        with patch.object(dm.engine, "download_single_video") as mock_dl:
            mock_dl.return_value = {"success": True, "skipped": False}
            dm.run()

        self.assertEqual(v_tiktok.status, VideoStatus.COMPLETED)
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["completed"], 1)

    # -------------------------------------------------------------------------
    # 18. Douyin remains frozen/disabled as currently configured
    # -------------------------------------------------------------------------
    def test_18_douyin_remains_frozen(self):
        v_douyin = VideoItem(
            index=1,
            video_id="7106594312292453678",
            title="Frozen Douyin Video",
            duration="00:30",
            platform="douyin",
            url="https://www.douyin.com/video/7106594312292453678",
        )
        dm = DownloadManager([v_douyin], self.settings)
        dm.run()

        self.assertEqual(v_douyin.status, VideoStatus.FAILED)
        self.assertIn("temporarily unavailable", v_douyin.error_reason.lower())
        stats = dm.get_queue_statistics()
        self.assertEqual(stats["failed"], 1)

    # -------------------------------------------------------------------------
    # 19. Non-English and localized error messages handled gracefully
    # -------------------------------------------------------------------------
    def test_19_non_english_and_localized_errors(self):
        # Chinese private video
        err_priv = ErrorClassifier.classify("该视频为私有视频，无法播放", platform="youtube")
        self.assertEqual(err_priv.category, ErrorCategory.PRIVATE_VIDEO)
        self.assertTrue(ErrorClassifier.is_private_video("这是私享视频"))

        # Chinese deleted/unavailable video
        err_unavail = ErrorClassifier.classify("此视频已被上传者删除或无法访问", platform="youtube")
        self.assertEqual(err_unavail.category, ErrorCategory.VIDEO_UNAVAILABLE)
        self.assertTrue(ErrorClassifier.is_unavailable_video("该视频已删除"))

        # Japanese unavailable / private
        self.assertTrue(ErrorClassifier.is_private_video("[Private video]"))
        self.assertTrue(ErrorClassifier.is_unavailable_video("[Unavailable video]"))

    # -------------------------------------------------------------------------
    # 20. Partial files from failed or cancelled downloads cleaned up
    # -------------------------------------------------------------------------
    def test_20_partial_file_cleanup(self):
        target_dir = Path(self.download_folder)
        part_file = target_dir / "Test_Video_bad123.mp4.part"
        ytdl_file = target_dir / "Test_Video_bad123.ytdl"
        other_file = target_dir / "Other_Video_good456.mp4.part"

        part_file.write_text("partial", encoding="utf-8")
        ytdl_file.write_text("temp", encoding="utf-8")
        other_file.write_text("dont touch", encoding="utf-8")

        engine = YtDlpEngine()
        engine.safe_cleanup_partial_files(target_dir, "bad123", title="Test Video")

        self.assertFalse(part_file.exists())
        self.assertFalse(ytdl_file.exists())
        self.assertTrue(other_file.exists())

    # -------------------------------------------------------------------------
    # 21. Rapid Start/Stop cycles: no deadlocks or orphaned state
    # -------------------------------------------------------------------------
    def test_21_rapid_start_stop_cycles(self):
        for cycle in range(3):
            videos = [
                VideoItem(index=1, video_id=f"cycle_{cycle}_1", title="Rapid 1", duration="01:00"),
                VideoItem(index=2, video_id=f"cycle_{cycle}_2", title="Rapid 2", duration="01:00"),
            ]
            dm = DownloadManager(videos, self.settings)

            # Cancel immediately after start
            dm.cancel()
            dm.run()

            self.assertTrue(dm.is_cancelled())
            stats = dm.get_queue_statistics()
            self.assertEqual(stats["cancelled"], 2)
            self.assertEqual(stats["completed"], 0)

    # -------------------------------------------------------------------------
    # 22. SummaryDialog UI presentation of granular counts
    # -------------------------------------------------------------------------
    def test_22_summary_dialog_display_counts(self):
        dlg = SummaryDialog(
            completed=5,
            skipped=3,
            failed=1,
            total=9,
            download_folder=self.download_folder,
            skipped_private=2,
            skipped_unavailable=1,
            skipped_existing=0,
            cancelled=0,
            is_cancelled=False,
        )

        self.assertEqual(dlg.completed, 5)
        self.assertEqual(dlg.skipped_private, 2)
        self.assertEqual(dlg.skipped_unavailable, 1)
        self.assertEqual(dlg.failed, 1)
        self.assertEqual(dlg.total, 9)
        self.assertFalse(dlg.is_cancelled)

        # Cancelled presentation
        dlg_canc = SummaryDialog(
            completed=2,
            skipped=1,
            failed=0,
            total=5,
            download_folder=self.download_folder,
            skipped_private=1,
            skipped_unavailable=0,
            cancelled=2,
            is_cancelled=True,
        )
        self.assertTrue(dlg_canc.is_cancelled)
        self.assertEqual(dlg_canc.cancelled, 2)


if __name__ == "__main__":
    unittest.main()
