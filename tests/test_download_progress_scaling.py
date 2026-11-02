# -*- coding: utf-8 -*-
"""
tests/test_download_progress_scaling.py

Unit test suite verifying download progress bar and percentage scaling across
multiple download options (Video + Audio, Thumbnail, Metadata, Subtitles).
Prevents premature 100% progress reporting before all requested assets finish.
"""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from core.models import (
    VideoItem,
    VideoStatus,
    DownloadSettings,
    DownloadMode,
)
from downloader.download_manager import DownloadManager


class TestDownloadProgressScaling(unittest.TestCase):
    """Verifies that progress percentages and progress bars scale accurately across multiple assets."""

    def test_01_compute_stage_weights_media_only(self):
        """Media only mode allocates 100% to media."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=False,
            has_thumb=False,
            has_meta=False,
        )
        self.assertEqual(ranges, {"media": (0.0, 100.0)})

    def test_02_compute_stage_weights_media_and_thumbnail(self):
        """Media + Thumbnail allocates 85% to media and 15% to thumbnail."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=False,
            has_thumb=True,
            has_meta=False,
        )
        self.assertEqual(ranges["media"], (0.0, 85.0))
        self.assertEqual(ranges["thumbnail"], (85.0, 100.0))
        self.assertEqual(ranges["media"][1], ranges["thumbnail"][0])

    def test_03_compute_stage_weights_media_thumbnail_metadata(self):
        """Media + Thumbnail + Metadata allocates 80% media, 10% thumb, 10% meta (the user's scenario)."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=False,
            has_thumb=True,
            has_meta=True,
        )
        self.assertEqual(ranges["media"], (0.0, 80.0))
        self.assertEqual(ranges["thumbnail"], (80.0, 90.0))
        self.assertEqual(ranges["metadata"], (90.0, 100.0))
        # Contiguity and completeness
        self.assertEqual(ranges["media"][1], ranges["thumbnail"][0])
        self.assertEqual(ranges["thumbnail"][1], ranges["metadata"][0])
        self.assertEqual(ranges["metadata"][1], 100.0)

    def test_04_compute_stage_weights_media_sub_thumb_meta(self):
        """All 4 stages active: 70% media, 10% sub, 10% thumb, 10% meta."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=True,
            has_thumb=True,
            has_meta=True,
        )
        self.assertEqual(ranges["media"], (0.0, 70.0))
        self.assertEqual(ranges["subtitles"], (70.0, 80.0))
        self.assertEqual(ranges["thumbnail"], (80.0, 90.0))
        self.assertEqual(ranges["metadata"], (90.0, 100.0))

    def test_05_compute_stage_weights_assets_only_all_three(self):
        """Assets Only mode with subtitles, thumbnail, and metadata partitions cleanly into 100%."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=False,
            has_sub=True,
            has_thumb=True,
            has_meta=True,
        )
        self.assertEqual(ranges["subtitles"], (0.0, 34.0))
        self.assertEqual(ranges["thumbnail"], (34.0, 67.0))
        self.assertEqual(ranges["metadata"], (67.0, 100.0))

    def test_06_compute_stage_weights_assets_only_two_assets(self):
        """Assets Only mode with thumbnail and metadata splits 50% / 50%."""
        ranges = DownloadManager._compute_stage_weights(
            has_media=False,
            has_sub=False,
            has_thumb=True,
            has_meta=True,
        )
        self.assertEqual(ranges["thumbnail"], (0.0, 50.0))
        self.assertEqual(ranges["metadata"], (50.0, 100.0))

    def test_07_media_download_does_not_emit_100_percent_when_thumbnail_and_metadata_pending(self):
        """
        Critical Bug Repro Test:
        When Video + Audio + Thumbnail + Metadata are selected:
        When yt-dlp finishes downloading media (raw percent 100%), the emitted percent
        must be 80.0%, NOT 100.0%!
        Only after Thumbnail and Metadata finish should 100.0% be emitted.
        """
        video = VideoItem(
            index=1,
            video_id="test_vid_123",
            title="Sample Video",
            duration="03:00",
            platform="youtube",
            url="https://www.youtube.com/watch?v=test_vid_123",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            download_thumbnail=True,
            save_metadata=True,
            save_description=True,
            download_folder="C:/fake_download",
        )

        dm = DownloadManager([video], settings)

        emitted_progress = []
        emitted_status = []
        dm.video_progress.connect(
            lambda vid, pct, dl, tot, spd, eta: emitted_progress.append((vid, pct, spd))
        )
        dm.video_status_changed.connect(
            lambda vid, status, err: emitted_status.append((vid, status))
        )

        # Mock dependencies to isolate progress emission flow
        with patch.object(dm.engine, "download_single_video") as mock_dl_media, \
             patch("downloader.download_manager.ThumbnailManager.download_thumbnail") as mock_thumb, \
             patch("downloader.download_manager.InfoManager.save_video_info") as mock_info, \
             patch("downloader.download_manager.ensure_safe_environment", return_value=("C:/fake", "C:/fake/temp")):

            def fake_download_media(**kwargs):
                cb = kwargs.get("progress_callback")
                # Simulate yt-dlp downloading video: raw 0%, 50%, 100%
                cb({"status": "downloading", "percent": 0.0, "downloaded_str": "0 MB", "total_str": "50 MB", "speed": "5 MB/s", "eta": "00:10"})
                cb({"status": "downloading", "percent": 50.0, "downloaded_str": "25 MB", "total_str": "50 MB", "speed": "5 MB/s", "eta": "00:05"})
                cb({"status": "downloading", "percent": 100.0, "downloaded_str": "50 MB", "total_str": "50 MB", "speed": "5 MB/s", "eta": "00:00"})
                # Simulate FFmpeg processing
                cb({"status": "processing", "percent": 100.0, "downloaded_str": "50 MB", "total_str": "50 MB", "operation": "Merging streams"})
                return {"success": True, "skipped": False, "info_dict": {"id": "test_vid_123"}}

            mock_dl_media.side_effect = fake_download_media
            mock_thumb.return_value = {"success": True, "skipped": False, "saved_file": Path("thumb.jpg")}
            mock_info.return_value = {"success": True, "skipped": False, "saved_files": [Path("meta.txt")]}

            dm.run()

        # Extract all emitted percentages in order
        percentages = [p[1] for p in emitted_progress]
        self.assertTrue(len(percentages) >= 5)

        # 1. During media download:
        # raw 0% -> 0.0%
        self.assertAlmostEqual(percentages[0], 0.0)
        # raw 50% -> 40.0%
        self.assertAlmostEqual(percentages[1], 40.0)
        # raw 100% (media finished) -> 80.0%, NOT 100.0%!
        self.assertAlmostEqual(percentages[2], 80.0)
        # FFmpeg processing -> 80.0%, NOT 100.0%!
        self.assertAlmostEqual(percentages[3], 80.0)

        # 2. Before thumbnail finishes, 100% must NOT have been emitted
        media_and_thumb_start_pcts = percentages[:5]
        for p in media_and_thumb_start_pcts:
            self.assertLess(p, 99.0, f"Premature 100% progress emitted: {p}")

        # 3. After thumbnail finishes: 90.0%
        self.assertIn(90.0, percentages)

        # 4. Only at the very end when metadata finishes does it reach 100.0%
        self.assertAlmostEqual(percentages[-1], 100.0)

        # 5. Check statuses emitted in logical progression
        status_names = [s[1] for s in emitted_status]
        self.assertIn("Downloading (Thumbnail)", status_names)
        self.assertIn("Saving (Metadata)", status_names)
        self.assertEqual(status_names[-1], VideoStatus.COMPLETED)

    def test_08_media_download_media_only_reaches_100_percent_on_media_completion(self):
        """When NO additional assets are selected, media completion legitimately reaches 100%."""
        video = VideoItem(
            index=1,
            video_id="media_only_vid",
            title="Media Only Video",
            duration="01:00",
            platform="youtube",
            url="https://www.youtube.com/watch?v=media_only_vid",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            download_thumbnail=False,
            download_subtitles=False,
            save_metadata=False,
            save_description=False,
            save_chapters=False,
            download_folder="C:/fake_download",
        )

        dm = DownloadManager([video], settings)
        emitted_progress = []
        dm.video_progress.connect(
            lambda vid, pct, dl, tot, spd, eta: emitted_progress.append(pct)
        )

        with patch.object(dm.engine, "download_single_video") as mock_dl_media, \
             patch("downloader.download_manager.ensure_safe_environment", return_value=("C:/fake", "C:/fake/temp")):

            def fake_download_media(**kwargs):
                cb = kwargs.get("progress_callback")
                cb({"status": "downloading", "percent": 50.0, "downloaded_str": "10 MB", "total_str": "20 MB", "speed": "2 MB/s", "eta": "00:05"})
                cb({"status": "downloading", "percent": 100.0, "downloaded_str": "20 MB", "total_str": "20 MB", "speed": "2 MB/s", "eta": "00:00"})
                return {"success": True, "skipped": False, "info_dict": {}}

            mock_dl_media.side_effect = fake_download_media
            dm.run()

        # In media-only mode, 50% maps to 50%, and 100% maps to 100%
        self.assertIn(50.0, emitted_progress)
        self.assertAlmostEqual(emitted_progress[-1], 100.0)

    def test_09_assets_only_mode_progress_progression(self):
        """In Assets Only mode with Thumbnail and Metadata, progress advances smoothly from 0 to 50 to 100."""
        video = VideoItem(
            index=1,
            video_id="assets_only_vid",
            title="Assets Only Video",
            duration="01:00",
            platform="youtube",
            url="https://www.youtube.com/watch?v=assets_only_vid",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.ASSETS_ONLY,
            download_thumbnail=True,
            save_metadata=True,
            save_description=False,
            save_chapters=False,
            download_folder="C:/fake_download",
        )

        dm = DownloadManager([video], settings)
        emitted_progress = []
        dm.video_progress.connect(
            lambda vid, pct, dl, tot, spd, eta: emitted_progress.append(pct)
        )

        with patch("downloader.download_manager.ThumbnailManager.download_thumbnail") as mock_thumb, \
             patch("downloader.download_manager.InfoManager.save_video_info") as mock_info, \
             patch("downloader.download_manager.ensure_safe_environment", return_value=("C:/fake", "C:/fake/temp")):

            mock_thumb.return_value = {"success": True, "skipped": False, "saved_file": Path("thumb.jpg")}
            mock_info.return_value = {"success": True, "skipped": False, "saved_files": [Path("meta.txt")]}

            dm.run()

        # Thumbnail range is 0.0 -> 50.0; Metadata range is 50.0 -> 100.0
        self.assertIn(0.0, emitted_progress)
        self.assertIn(50.0, emitted_progress)
        self.assertAlmostEqual(emitted_progress[-1], 100.0)

    def test_10_main_window_progress_bar_and_labels_update(self):
        """MainWindow progress bar and labels update accurately and independently for current video and overall progress."""
        import sys
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        win = MainWindow()
        win._queue_total = 2
        win._queue_completed = 0
        win._queue_skipped = 0
        win._queue_failed = 0

        # Simulate 80% progress when media finishes (with remaining assets pending)
        win._on_video_progress(
            video_id="v1",
            percent=80.0,
            downloaded_str="40.0 MB",
            total_str="50.0 MB",
            speed="5.0 MB/s",
            eta="00:02",
        )

        self.assertEqual(win.current_progress_bar.value(), 80)
        self.assertEqual(win.item_stats_label.text(), "40.0 MB / 50.0 MB")
        self.assertIn("5.0 MB/s", win.speed_label.text())
        self.assertIn("00:02", win.eta_label.text())
        # Overall progress bar remains independent from individual video ticks (still 0 completed)
        self.assertEqual(win.overall_progress_bar.value(), 0)

        # Simulate 90% when thumbnail finishes
        win._on_video_progress(
            video_id="v1",
            percent=90.0,
            downloaded_str="40.0 MB",
            total_str="50.0 MB",
            speed="Thumbnail",
            eta="00:00",
        )
        self.assertEqual(win.current_progress_bar.value(), 90)

        # Simulate 100% when metadata finishes (v1 completely finished)
        win._on_video_progress(
            video_id="v1",
            percent=100.0,
            downloaded_str="40.0 MB",
            total_str="50.0 MB",
            speed="Finished",
            eta="00:00",
        )
        self.assertEqual(win.current_progress_bar.value(), 100)

        # Overall progress signal for item 1 completion (1/2 = 50%)
        win._on_overall_progress(
            completed=1,
            skipped=0,
            failed=0,
            remaining=1,
            overall_pct=50.0,
        )
        self.assertEqual(win.overall_progress_bar.value(), 50)
        self.assertIn("1 / 2 completed", win.queue_label.text())

    def test_11_cancellation_during_asset_stages_halts_cleanly(self):
        """Cancelling the queue during asset stages halts execution without reaching 100%."""
        video = VideoItem(
            index=1,
            video_id="cancel_vid",
            title="Cancel Test Video",
            duration="02:00",
            platform="youtube",
            url="https://www.youtube.com/watch?v=cancel_vid",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            download_thumbnail=True,
            save_metadata=True,
            download_folder="C:/fake_download",
        )
        dm = DownloadManager([video], settings)
        emitted_progress = []
        dm.video_progress.connect(
            lambda vid, pct, dl, tot, spd, eta: emitted_progress.append((pct, spd))
        )

        with patch.object(dm.engine, "download_single_video") as mock_dl_media, \
             patch("downloader.download_manager.ThumbnailManager.download_thumbnail") as mock_thumb, \
             patch("downloader.download_manager.ensure_safe_environment", return_value=("C:/fake", "C:/fake/temp")):

            def fake_download_media(**kwargs):
                return {"success": True, "skipped": False, "info_dict": {}}

            def fake_download_thumb(**kwargs):
                dm.cancel()
                return {"success": False, "skipped": False, "error": "Cancelled"}

            mock_dl_media.side_effect = fake_download_media
            mock_thumb.side_effect = fake_download_thumb

            dm.run()

        # Last progress emitted must not be 100% finished
        final_pcts = [p[0] for p in emitted_progress]
        self.assertTrue(all(p < 100.0 for p in final_pcts), f"Progress reached 100% despite cancellation: {final_pcts}")

    def test_12_tag_embedding_stage_progress_and_never_premature_100(self):
        """
        Verifies that when tag embedding (embed_cover_art / embed_metadata / embed_lyrics) is enabled:
        - An 'embed' stage is cleanly allocated after media.
        - Media completion emits the end of media stage (e.g. 85%), NOT 100%!
        - Progress smoothly moves through the embed stage and reaches 100% only upon final completion.
        """
        ranges = DownloadManager._compute_stage_weights(
            has_media=True,
            has_sub=False,
            has_thumb=False,
            has_meta=False,
            has_embed=True,
        )
        self.assertEqual(ranges, {"media": (0.0, 85.0), "embed": (85.0, 100.0)})

        video = VideoItem(
            index=1,
            video_id="audio_tag_vid",
            title="Audio Tag Song",
            duration="03:30",
            platform="youtube",
            url="https://www.youtube.com/watch?v=audio_tag_vid",
        )
        settings = DownloadSettings(
            download_mode=DownloadMode.AUDIO_ONLY,
            download_thumbnail=False,
            embed_cover_art=True,
            embed_metadata=True,
            download_folder="C:/fake_download",
        )

        dm = DownloadManager([video], settings)
        emitted_progress = []
        emitted_status = []
        dm.video_progress.connect(
            lambda vid, pct, dl, tot, spd, eta: emitted_progress.append((pct, spd))
        )
        dm.video_status_changed.connect(
            lambda vid, status, err: emitted_status.append(status)
        )

        with patch.object(dm.engine, "download_single_video") as mock_dl_media, \
             patch("downloader.cover_art_manager.CoverArtManager.embed_cover_art_for_media_files", return_value=True), \
             patch("downloader.download_manager.ensure_safe_environment", return_value=("C:/fake", "C:/fake/temp")), \
             patch("pathlib.Path.is_dir", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.iterdir", return_value=[Path("C:/fake_download/Audio Tag Song.mp3")]):

            def fake_download_media(**kwargs):
                cb = kwargs.get("progress_callback")
                cb({"status": "downloading", "percent": 50.0, "downloaded_str": "5 MB", "total_str": "10 MB", "speed": "2 MB/s", "eta": "00:03"})
                cb({"status": "downloading", "percent": 100.0, "downloaded_str": "10 MB", "total_str": "10 MB", "speed": "2 MB/s", "eta": "00:00"})
                return {"success": True, "skipped": False, "info_dict": {"id": "audio_tag_vid", "title": "Audio Tag Song"}}

            mock_dl_media.side_effect = fake_download_media
            dm.run()

        pcts = [p[0] for p in emitted_progress]
        # While media was downloading, progress scaled within media range (0..85%)
        # 50% of 85% = 42.5%
        self.assertAlmostEqual(pcts[0], 42.5)
        # 100% of media stage = 85%, NOT 100%!
        self.assertAlmostEqual(pcts[1], 85.0)

        # Before embedding finishes, 100% must NOT have been emitted
        for p in pcts[:-1]:
            self.assertLess(p, 100.0, f"Premature 100% during tag embedding: {p}")

        # Intermediate embedding progress is emitted
        self.assertTrue(any(85.0 < p < 100.0 for p in pcts))

        # Only the final completion emission is 100.0%
        self.assertAlmostEqual(pcts[-1], 100.0)
        self.assertIn("Embedding Cover & Metadata", emitted_status)
        self.assertEqual(emitted_status[-1], VideoStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
