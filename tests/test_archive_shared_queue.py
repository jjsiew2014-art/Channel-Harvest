"""
tests/test_archive_shared_queue.py
Integration tests for DownloadManager unified shared queue executing both
gallery-dl photo/album tasks and yt-dlp video tasks in the same queue session.
"""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
import os
from pathlib import Path

import sys
from PySide6.QtWidgets import QApplication

from core.models import VideoItem, DownloadSettings, VideoStatus, DownloadMode
from core.inventory import (
    ProfileMediaInventory,
    MediaItemRecord,
    MediaDownloadStatus,
    MediaInventoryType,
)
from downloader.download_manager import DownloadManager, kill_child_processes
from downloader.gallerydl_engine import GalleryDlEngine
from downloader.ytdlp_engine import YtDlpEngine, DownloaderError
from downloader.engine_router import DownloadEngineRouter, EngineType


# Ensure QApplication exists for Qt signals
app = QApplication.instance() or QApplication(sys.argv)


class TestArchiveSharedQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, "downloads")
        os.makedirs(self.output_dir, exist_ok=True)
        self.db_path = os.path.join(self.temp_dir, "test_queue_inventory.db")
        self.inventory = ProfileMediaInventory(db_path=self.db_path)

        self.settings = DownloadSettings(
            download_folder=self.output_dir,
            quality="Best Available",
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            download_thumbnail=False,
            download_subtitles=False,
            save_metadata=False,
            save_description=False,
            create_individual_video_folders=False,
        )

    def tearDown(self):
        self.inventory.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_shared_queue_mixed_engines_success(self):
        """Queue runs gallery-dl for image items and yt-dlp for video items in the same session."""
        # Setup inventory records
        item_photo = MediaItemRecord(
            media_id="fb_photo_1",
            platform="facebook",
            parent_post_id="post_1",
            media_url="https://facebook.com/photo/1",
            media_type=MediaInventoryType.IMAGE,
            preferred_engine=EngineType.GALLERY_DL,
            selected_engine=EngineType.GALLERY_DL,
            download_status=MediaDownloadStatus.PENDING,
        )
        item_video = MediaItemRecord(
            media_id="fb_video_1",
            platform="facebook",
            parent_post_id="post_2",
            media_url="https://facebook.com/watch/?v=999",
            media_type=MediaInventoryType.VIDEO,
            preferred_engine=EngineType.YTDLP,
            selected_engine=EngineType.YTDLP,
            download_status=MediaDownloadStatus.PENDING,
        )
        self.inventory.upsert_media_item(item_photo)
        self.inventory.upsert_media_item(item_video)

        # Create VideoItem entries for UI/Queue
        photo_video_item = VideoItem(
            index=1,
            video_id="fb_photo_1",
            title="Facebook Photo 1",
            duration="Photo",
            url="https://facebook.com/photo/1",
            status=VideoStatus.READY,
            platform="facebook",
            extra_metadata={"media_type": MediaInventoryType.IMAGE},
        )
        video_video_item = VideoItem(
            index=2,
            video_id="fb_video_1",
            title="Facebook Video 1",
            duration="1:25",
            url="https://facebook.com/watch/?v=999",
            status=VideoStatus.READY,
            platform="facebook",
            extra_metadata={"media_type": MediaInventoryType.VIDEO},
        )

        manager = DownloadManager(
            videos=[photo_video_item, video_video_item],
            settings=self.settings,
        )
        manager.inventory = self.inventory

        # Mock gallerydl_engine and ytdlp engine
        manager.gallerydl_engine = MagicMock(spec=GalleryDlEngine)
        manager.gallerydl_engine.download_media.return_value = {
            "success": True,
            "downloaded_files": [os.path.join(self.output_dir, "fb_photo_1.jpg")],
            "error": None,
        }

        manager.engine = MagicMock(spec=YtDlpEngine)
        manager.engine.download_single_video.return_value = {
            "success": True,
            "skipped": False,
            "info_dict": {"id": "fb_video_1", "title": "Facebook Video 1"},
        }

        # Track signals
        completed_ids = []
        manager.video_status_changed.connect(
            lambda vid, status, reason: completed_ids.append(vid) if status == VideoStatus.COMPLETED else None
        )

        # Run the manager loop directly in current thread
        manager.run()

        # Both items should be called with their appropriate engines
        manager.gallerydl_engine.download_media.assert_called_once()
        manager.engine.download_single_video.assert_called_once()

        self.assertEqual(photo_video_item.status, VideoStatus.COMPLETED)
        self.assertEqual(video_video_item.status, VideoStatus.COMPLETED)
        self.assertIn("fb_photo_1", completed_ids)
        self.assertIn("fb_video_1", completed_ids)

        # Verify persistent inventory was updated for both items
        rec_photo = self.inventory.get_media_item("facebook", "fb_photo_1")
        self.assertIsNotNone(rec_photo)
        self.assertEqual(rec_photo.download_status, MediaDownloadStatus.COMPLETED)

        rec_video = self.inventory.get_media_item("facebook", "fb_video_1")
        self.assertIsNotNone(rec_video)
        self.assertEqual(rec_video.download_status, MediaDownloadStatus.COMPLETED)

    def test_shared_queue_cancellation(self):
        """Cancelling download manager marks remaining tasks as CANCELLED."""
        v1 = VideoItem(
            index=1,
            video_id="v1",
            title="Photo 1",
            duration="Photo",
            url="https://instagram.com/p/1",
            status=VideoStatus.READY,
            platform="instagram",
            extra_metadata={"media_type": MediaInventoryType.IMAGE},
        )
        v2 = VideoItem(
            index=2,
            video_id="v2",
            title="Video 2",
            duration="0:45",
            url="https://instagram.com/reel/2",
            status=VideoStatus.READY,
            platform="instagram",
            extra_metadata={"media_type": MediaInventoryType.VIDEO},
        )

        manager = DownloadManager(videos=[v1, v2], settings=self.settings)
        manager.cancel()
        manager.run()

        self.assertEqual(v1.status, VideoStatus.CANCELLED)
        self.assertEqual(v2.status, VideoStatus.CANCELLED)

    def test_kill_child_processes_inspects_gallerydl(self):
        """kill_child_processes logic includes 'gallery-dl' in target executables."""
        # Inspect source code of kill_child_processes
        import inspect
        source = inspect.getsource(kill_child_processes)
        self.assertIn("'gallery-dl'", source)


if __name__ == "__main__":
    unittest.main()
