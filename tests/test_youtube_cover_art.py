# -*- coding: utf-8 -*-
"""
tests/test_youtube_cover_art.py

Comprehensive test suite verifying YouTube Art Track / Topic 1:1 Cover Art:
- Detection via Innertube API and fallback center-crop.
- Image downloading and FFmpeg lossless tag embedding.
- Background worker execution and cancellation.
- MainWindow UI gating, dynamic dimension display, and platform scoping.
"""

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from core.models import VideoItem, DownloadSettings, DownloadMode
from core.i18n import I18nManager, tr
from core.settings import SettingsManager
from downloader.cover_art_manager import CoverArtManager, CoverArtDetectionWorker
from gui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestCoverArtManager(unittest.TestCase):
    """Verifies CoverArtManager detection, download, and embedding functions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("urllib.request.urlopen")
    def test_01_detect_cover_art_innertube_master(self, mock_urlopen):
        """Innertube master album art URL from Google CDN is parsed and appended with '=s0'."""
        cdn_url = "https://lh3.googleusercontent.com/test_album_art_hash"
        fake_json = {
            "contents": {
                "singleColumnMusicWatchNextResultsRenderer": {
                    "tabbedRenderer": {
                        "thumbnail": {
                            "musicThumbnailRenderer": {
                                "thumbnail": {
                                    "thumbnails": [{"url": f"{cdn_url}=w544-h544"}]
                                }
                            }
                        }
                    }
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        # Mock probe dimensions
        with patch.object(CoverArtManager, "_probe_image_dimensions", return_value=(1400, 1400)):
            mock_urlopen.return_value = mock_resp
            info = CoverArtManager.detect_cover_art("test_vid_id")

            self.assertIsNotNone(info)
            self.assertEqual(info["source"], "innertube_master")
            self.assertEqual(info["url"], f"{cdn_url}=s0")
            self.assertEqual(info["width"], 1400)
            self.assertEqual(info["height"], 1400)

    @patch("urllib.request.urlopen")
    def test_02_detect_cover_art_fallback_center_crop(self, mock_urlopen):
        """When no Google CDN url is present, falls back to maxresdefault 1:1 center crop."""
        fake_json = {
            "contents": {
                "thumbnail": {
                    "thumbnails": [{"url": "https://i.ytimg.com/vi/test_vid_id/maxresdefault.jpg"}]
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        info = CoverArtManager.detect_cover_art("test_vid_id")
        self.assertIsNotNone(info)
        self.assertEqual(info["source"], "center_crop")
        self.assertEqual(info["width"], 1080)
        self.assertEqual(info["height"], 1080)

    @patch("urllib.request.urlopen")
    def test_03_detect_cover_art_none(self, mock_urlopen):
        """When video ID is empty or request fails, returns None."""
        self.assertIsNone(CoverArtManager.detect_cover_art(""))

        mock_urlopen.side_effect = Exception("HTTP 404")
        self.assertIsNone(CoverArtManager.detect_cover_art("non_existent_id"))

    def test_03b_extract_playlist_or_album_id(self):
        """Verifies parsing of various YouTube Music album and playlist URLs/IDs."""
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw"),
            "OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw",
        )
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("VLOLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw"),
            "OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw",
        )
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("MPREb_NW5VK16O4Zc"),
            "MPREb_NW5VK16O4Zc",
        )
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("https://music.youtube.com/playlist?list=OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw"),
            "OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw",
        )
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("https://music.youtube.com/browse/MPREb_NW5VK16O4Zc"),
            "MPREb_NW5VK16O4Zc",
        )
        self.assertEqual(
            CoverArtManager.extract_playlist_or_album_id("https://music.youtube.com/watch?v=aaZi5kiQLsc&list=OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw"),
            "OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw",
        )
        self.assertIsNone(CoverArtManager.extract_playlist_or_album_id("https://www.youtube.com/watch?v=aaZi5kiQLsc"))

    @patch("urllib.request.urlopen")
    def test_03c_detect_album_cover_art_browse(self, mock_urlopen):
        """Innertube /browse returns original Google CDN master album cover with =s0."""
        cdn_url = "https://yt3.googleusercontent.com/master_album_hash"
        fake_browse = {
            "header": {
                "musicDetailHeaderRenderer": {
                    "thumbnail": {
                        "croppedSquareThumbnailRenderer": {
                            "thumbnail": {"thumbnails": [{"url": f"{cdn_url}=w544-h544-l90-rj"}]}
                        }
                    }
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_browse).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(CoverArtManager, "_probe_image_dimensions", return_value=(1440, 1440)):
            mock_urlopen.return_value = mock_resp
            info = CoverArtManager.detect_album_cover_art("OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw")

            self.assertIsNotNone(info)
            self.assertEqual(info["source"], "innertube_master")
            self.assertEqual(info["url"], f"{cdn_url}=s0")
            self.assertEqual(info["width"], 1440)
            self.assertEqual(info["height"], 1440)
            self.assertTrue(info.get("is_album"))

    @patch("urllib.request.urlopen")
    def test_03d_detect_cover_art_mv_in_album_playlist(self, mock_urlopen):
        """When an MV video is inside an album playlist, CoverArtManager prioritizes the album master artwork."""
        album_cdn = "https://yt3.googleusercontent.com/album_artwork_1440"
        fake_browse = {
            "header": {
                "musicDetailHeaderRenderer": {
                    "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": [{"url": album_cdn}]}}}
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_browse).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(CoverArtManager, "_probe_image_dimensions", return_value=(1440, 1440)):
            mock_urlopen.return_value = mock_resp
            info = CoverArtManager.detect_cover_art(
                video_id="aaZi5kiQLsc",
                title="Axel Lee 李雨壕 - 【车站 Farewell Station】 歌词版 Lyrics MV",
                artist="Axel Lee 李雨壕",
                playlist_id="OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw",
            )
            self.assertIsNotNone(info)
            self.assertEqual(info["source"], "innertube_master")
            self.assertEqual(info["url"], f"{album_cdn}=s0")
            self.assertEqual(info["width"], 1440)
            self.assertEqual(info["height"], 1440)

    @patch("urllib.request.urlopen")
    def test_03e_detect_cover_art_mv_search_fallback(self, mock_urlopen):
        """When an MV video is scanned standalone and /next lacks CDN art, searches YouTube Music for album art."""
        # Call 1: /next returns no googleusercontent, but contains playlistPanel with title & author
        fake_next = {
            "contents": {
                "singleColumnMusicWatchNextResultsRenderer": {
                    "tabbedRenderer": {
                        "watchNextTabbedResultsRenderer": {
                            "tabs": [{
                                "tabRenderer": {
                                    "content": {
                                        "musicQueueRenderer": {
                                            "content": {
                                                "playlistPanelRenderer": {
                                                    "contents": [{
                                                        "playlistPanelVideoRenderer": {
                                                            "title": {"runs": [{"text": "车站"}]},
                                                            "shortBylineText": {"runs": [{"text": "Axel Lee"}]},
                                                        }
                                                    }]
                                                }
                                            }
                                        }
                                    }
                                }
                            }]
                        }
                    }
                }
            }
        }

        # Call 2: /search returns googleusercontent album artwork
        search_cdn = "https://yt3.googleusercontent.com/master_song_art"
        fake_search = {
            "contents": {
                "tabbedSearchResultsRenderer": {
                    "tabs": [{
                        "tabRenderer": {
                            "content": {
                                "sectionListRenderer": {
                                    "contents": [{
                                        "musicCardShelfRenderer": {
                                            "thumbnail": {
                                                "musicThumbnailRenderer": {
                                                    "thumbnail": {"thumbnails": [{"url": f"{search_cdn}=w120-h120"}]}
                                                }
                                            }
                                        }
                                    }]
                                }
                            }
                        }
                    }]
                }
            }
        }

        resp_next = MagicMock()
        resp_next.read.return_value = json.dumps(fake_next).encode("utf-8")
        resp_next.__enter__.return_value = resp_next

        resp_search = MagicMock()
        resp_search.read.return_value = json.dumps(fake_search).encode("utf-8")
        resp_search.__enter__.return_value = resp_search

        mock_urlopen.side_effect = [resp_next, resp_search]

        with patch.object(CoverArtManager, "_probe_image_dimensions", return_value=(1440, 1440)):
            info = CoverArtManager.detect_cover_art(
                video_id="aaZi5kiQLsc",
                title="Axel Lee 李雨壕 - 【车站 Farewell Station】 歌词版 Lyrics MV",
                artist="Axel Lee 李雨壕",
            )
            self.assertIsNotNone(info)
            self.assertEqual(info["source"], "innertube_master")
            self.assertEqual(info["url"], f"{search_cdn}=s0")
            self.assertEqual(info["width"], 1440)
            self.assertEqual(info["height"], 1440)

    @patch("urllib.request.urlopen")
    def test_03f_detect_cover_art_for_videos_propagates_album_art(self, mock_urlopen):
        """detect_cover_art_for_videos assigns master album art to all videos in an album containing MVs."""
        album_cdn = "https://yt3.googleusercontent.com/master_full_album"
        fake_browse = {
            "header": {
                "musicDetailHeaderRenderer": {
                    "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": [{"url": album_cdn}]}}}
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(fake_browse).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        v1 = VideoItem(index=1, video_id="mv_id_1", title="Axel Lee - Track 1 MV", duration="3:45", channel_title="Axel Lee")
        v2 = VideoItem(index=2, video_id="mv_id_2", title="Axel Lee - Track 2 MV", duration="4:12", channel_title="Axel Lee")

        with patch.object(CoverArtManager, "_probe_image_dimensions", return_value=(1440, 1440)):
            info = CoverArtManager.detect_cover_art_for_videos([v1, v2], playlist_id="OLAK5uy_koLAJbbEzIeWZvS1cUB1nrCf3wZ8ERzyw")

            self.assertIsNotNone(info)
            self.assertEqual(info["source"], "innertube_master")
            # Both videos inherit the high-res 1440x1440 album art
            self.assertEqual(v1.cover_art_url, f"{album_cdn}=s0")
            self.assertEqual(v1.cover_art_width, 1440)
            self.assertEqual(v2.cover_art_url, f"{album_cdn}=s0")
            self.assertEqual(v2.cover_art_width, 1440)

    @patch("urllib.request.urlopen")
    def test_04_download_cover_art_master(self, mock_urlopen):
        """Downloads master 1:1 image and saves as <stem>_cover.jpg."""
        img = Image.new("RGB", (1400, 1400), color="blue")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        raw = img_bytes.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        video = VideoItem(index=1, video_id="abc12345", title="Bohemian Rhapsody", duration="5:55")
        video._cover_info = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/master=s0",
            "width": 1400,
            "height": 1400,
        }
        settings = DownloadSettings(download_folder=str(self.target_dir))

        res = CoverArtManager.download_cover_art(video, settings, self.target_dir)
        self.assertTrue(res["success"])
        saved = res["saved_file"]
        self.assertTrue(saved.is_file())
        self.assertTrue(saved.name.endswith("_cover.jpg"))

        # Verify image dimensions
        with Image.open(saved) as read_img:
            self.assertEqual(read_img.size, (1400, 1400))

    @patch("urllib.request.urlopen")
    def test_05_download_cover_art_crop_fallback(self, mock_urlopen):
        """Downloads 16:9 thumbnail and center-crops into a 1:1 square."""
        img_16_9 = Image.new("RGB", (1280, 720), color="red")
        buf = io.BytesIO()
        img_16_9.save(buf, format="JPEG")
        raw = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        video = VideoItem(index=1, video_id="xyz98765", title="Topic Song", duration="3:30")
        video._cover_info = {
            "source": "center_crop",
            "url": "https://i.ytimg.com/vi/xyz98765/hq720.jpg",
            "width": 720,
            "height": 720,
        }
        settings = DownloadSettings(download_folder=str(self.target_dir))

        res = CoverArtManager.download_cover_art(video, settings, self.target_dir)
        self.assertTrue(res["success"])
        saved = res["saved_file"]
        self.assertTrue(saved.is_file())

        with Image.open(saved) as read_img:
            self.assertEqual(read_img.size, (720, 720))

    @patch("urllib.request.urlopen")
    def test_05b_download_cover_art_album_deduplication(self, mock_urlopen):
        """When tracks share the same album, Cover Art is saved once as <album_name>.jpg and duplicates are skipped."""
        img = Image.new("RGB", (1400, 1400), color="purple")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        downloaded_covers = set()
        settings = DownloadSettings(download_folder=str(self.target_dir))

        # Track 1
        video1 = VideoItem(
            index=1,
            video_id="gem_sky_01",
            title="01_THE SKY",
            duration="4:39",
            extra_metadata={"album": "REVELATION"},
        )
        video1._cover_info = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/master_album_art=s0",
            "width": 1400,
            "height": 1400,
        }

        res1 = CoverArtManager.download_cover_art(
            video=video1,
            settings=settings,
            target_dir=self.target_dir,
            album="REVELATION",
            downloaded_covers=downloaded_covers,
        )
        self.assertTrue(res1["success"])
        self.assertFalse(res1["skipped"])
        saved1 = res1["saved_file"]
        self.assertEqual(saved1.name, "REVELATION.jpg")
        self.assertTrue(saved1.is_file())
        self.assertEqual(mock_urlopen.call_count, 1)

        # Track 2 (Same album)
        video2 = VideoItem(
            index=2,
            video_id="gem_hell_02",
            title="02_HELL",
            duration="3:45",
            extra_metadata={"album": "REVELATION"},
        )
        video2._cover_info = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/master_album_art=s0",
            "width": 1400,
            "height": 1400,
        }

        res2 = CoverArtManager.download_cover_art(
            video=video2,
            settings=settings,
            target_dir=self.target_dir,
            album="REVELATION",
            downloaded_covers=downloaded_covers,
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2["skipped"])
        saved2 = res2["saved_file"]
        self.assertEqual(saved2.name, "REVELATION.jpg")
        # Urlopen must NOT be called a second time
        self.assertEqual(mock_urlopen.call_count, 1)

        # Confirm only ONE cover art image exists in the directory
        all_jpgs = list(self.target_dir.glob("*.jpg"))
        self.assertEqual(len(all_jpgs), 1)
        self.assertEqual(all_jpgs[0].name, "REVELATION.jpg")

    @patch("urllib.request.urlopen")
    def test_05c_download_cover_art_sanitized_album_name(self, mock_urlopen):
        """Sanitizes special album characters and strips 'Album - ' prefix."""
        img = Image.new("RGB", (1000, 1000), color="green")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        downloaded_covers = set()
        settings = DownloadSettings(download_folder=str(self.target_dir))

        video = VideoItem(
            index=1,
            video_id="mayday_01",
            title="突然好想你",
            duration="4:26",
            extra_metadata={"album": "Album - 后·青春期的诗"},
        )
        video._cover_info = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/mayday_art=s0",
            "width": 1000,
            "height": 1000,
        }

        res = CoverArtManager.download_cover_art(
            video=video,
            settings=settings,
            target_dir=self.target_dir,
            album="Album - 后·青春期的诗",
            downloaded_covers=downloaded_covers,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["saved_file"].name, "后·青春期的诗.jpg")
        self.assertTrue(res["saved_file"].is_file())

    def test_05d_download_manager_module_level_lyrics_and_cover_manager(self):
        """Verify LyricsManager and CoverArtManager are imported at module level in download_manager."""
        import downloader.download_manager as dm_module
        self.assertTrue(hasattr(dm_module, "LyricsManager"))
        self.assertTrue(hasattr(dm_module, "CoverArtManager"))
        from downloader.lyrics_manager import LyricsManager
        from downloader.cover_art_manager import CoverArtManager
        self.assertIs(dm_module.LyricsManager, LyricsManager)
        self.assertIs(dm_module.CoverArtManager, CoverArtManager)

    @patch("subprocess.run")
    def test_06_embed_cover_art_mp3(self, mock_subproc):
        """Embeds cover art into MP3 file using FFmpeg id3v2 copy."""
        media_file = self.target_dir / "song.mp3"
        cover_file = self.target_dir / "song_cover.jpg"
        media_file.write_bytes(b"dummy mp3 data")
        cover_file.write_bytes(b"dummy jpg data")

        # Mock successful ffmpeg creation of tmp_embed
        def side_effect(cmd, **kwargs):
            tmp_path = Path(cmd[-1])
            tmp_path.write_bytes(b"embedded mp3 data")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_subproc.side_effect = side_effect

        success = CoverArtManager.embed_cover_art(media_file, cover_file)
        self.assertTrue(success)
        self.assertEqual(media_file.read_bytes(), b"embedded mp3 data")

    @patch("subprocess.run")
    def test_07_embed_cover_art_m4a_attached_pic_disposition(self, mock_subproc):
        """Audio-only M4A container must use -disposition:v:0 attached_pic (not v:1)."""
        media_file = self.target_dir / "audio.m4a"
        cover_file = self.target_dir / "audio_cover.jpg"
        media_file.write_bytes(b"dummy m4a data")
        cover_file.write_bytes(b"dummy jpg data")

        captured_cmd = []

        def side_effect(cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = list(cmd)
            tmp_path = Path(cmd[-1])
            tmp_path.write_bytes(b"embedded m4a data")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_subproc.side_effect = side_effect

        success = CoverArtManager.embed_cover_art(media_file, cover_file)
        self.assertTrue(success)
        self.assertIn("-disposition:v:0", captured_cmd)
        self.assertNotIn("-disposition:v:1", captured_cmd)
        self.assertIn("attached_pic", captured_cmd)
        self.assertEqual(media_file.read_bytes(), b"embedded m4a data")

    @patch("subprocess.run")
    def test_08_embed_cover_art_opus_vorbis_comment(self, mock_subproc):
        """Opus / Ogg must use METADATA_BLOCK_PICTURE vorbis comment."""
        media_file = self.target_dir / "song.opus"
        cover_file = self.target_dir / "song_cover.jpg"
        media_file.write_bytes(b"dummy opus data")
        cover_file.write_bytes(b"dummy jpg data")

        captured_cmd = []

        def side_effect(cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = list(cmd)
            tmp_path = Path(cmd[-1])
            tmp_path.write_bytes(b"embedded opus data")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_subproc.side_effect = side_effect

        success = CoverArtManager.embed_cover_art(media_file, cover_file)
        self.assertTrue(success)
        self.assertTrue(any("METADATA_BLOCK_PICTURE=" in arg for arg in captured_cmd))
        self.assertEqual(media_file.read_bytes(), b"embedded opus data")

    @patch.object(CoverArtManager, "download_cover_art")
    @patch.object(CoverArtManager, "embed_cover_art", return_value=True)
    def test_09_embed_cover_art_for_media_files_multiple(self, mock_embed, mock_dl):
        """embed_cover_art_for_media_files processes multiple media files in one call."""
        cover_file = self.target_dir / "song_cover.jpg"
        cover_file.write_bytes(b"cover image")
        mock_dl.return_value = {"success": True, "saved_file": cover_file}

        f1 = self.target_dir / "song.m4a"
        f2 = self.target_dir / "song.mp4"
        f1.write_bytes(b"m4a")
        f2.write_bytes(b"mp4")

        video = VideoItem(index=1, video_id="vid123", title="Multi Track", duration="4:00")
        settings = DownloadSettings(download_folder=str(self.target_dir))

        res = CoverArtManager.embed_cover_art_for_media_files(
            video=video,
            media_paths=[f1, f2],
            settings=settings,
            target_dir=self.target_dir,
        )
        self.assertTrue(res)
        self.assertEqual(mock_embed.call_count, 2)

    def test_10_is_format_supported(self):
        """Verify CoverArtManager.is_format_supported identifies burn-in capable containers."""
        for fmt in ("MP3", "M4A", "FLAC", "OPUS", ".mp3", ".m4a", ".flac", ".opus"):
            self.assertTrue(CoverArtManager.is_format_supported(fmt), f"Expected {fmt} to be supported")

        for fmt in ("WAV", "AAC", ".wav", ".aac", "OGG_VORBIS", ""):
            self.assertFalse(CoverArtManager.is_format_supported(fmt), f"Expected {fmt} to be unsupported")

    @patch("subprocess.run")
    def test_11_embed_cover_art_rejects_wav_and_aac(self, mock_subproc):
        """WAV and raw AAC must be rejected immediately without invoking FFmpeg."""
        cover_file = self.target_dir / "cover.jpg"
        cover_file.write_bytes(b"jpg")

        wav_file = self.target_dir / "audio.wav"
        wav_file.write_bytes(b"wav")
        self.assertFalse(CoverArtManager.embed_cover_art(wav_file, cover_file))

        aac_file = self.target_dir / "audio.aac"
        aac_file.write_bytes(b"aac")
        self.assertFalse(CoverArtManager.embed_cover_art(aac_file, cover_file))

        # FFmpeg subprocess should never have been run
        mock_subproc.assert_not_called()

    def test_12_resolve_ffmpeg_and_ffprobe_executable(self):
        """Executable resolution correctly maps directory paths to ffmpeg.exe and ffprobe.exe."""
        dummy_dir = self.target_dir / "bin_dir"
        dummy_dir.mkdir()
        fake_ffmpeg = dummy_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        fake_ffmpeg.write_bytes(b"")
        fake_ffprobe = dummy_dir / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        fake_ffprobe.write_bytes(b"")

        # Pass directory path: should return the executable inside the directory
        res_ffmpeg = CoverArtManager._resolve_ffmpeg_executable(str(dummy_dir))
        self.assertEqual(res_ffmpeg, str(fake_ffmpeg))

        res_ffprobe = CoverArtManager._resolve_ffprobe_executable(str(dummy_dir))
        self.assertEqual(res_ffprobe, str(fake_ffprobe))

        # Pass direct file path
        self.assertEqual(CoverArtManager._resolve_ffmpeg_executable(str(fake_ffmpeg)), str(fake_ffmpeg))
        self.assertEqual(CoverArtManager._resolve_ffprobe_executable(str(fake_ffprobe)), str(fake_ffprobe))

    @patch("subprocess.run")
    def test_13_embed_cover_art_with_metadata_tags(self, mock_subproc):
        """embed_cover_art injects -metadata key=value and -map_metadata 0 into ffmpeg arguments."""
        media_file = self.target_dir / "song.mp3"
        cover_file = self.target_dir / "song_cover.jpg"
        media_file.write_bytes(b"dummy mp3 data")
        cover_file.write_bytes(b"dummy jpg data")

        captured_cmd = []

        def side_effect(cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = list(cmd)
            tmp_path = Path(cmd[-1])
            tmp_path.write_bytes(b"embedded mp3 data")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_subproc.side_effect = side_effect

        meta = {
            "title": "Song Title",
            "artist": "Song Artist",
            "album": "Song Album",
            "date": "2024",
        }
        success = CoverArtManager.embed_cover_art(
            media_path=media_file,
            cover_image_path=cover_file,
            metadata=meta,
        )
        self.assertTrue(success)
        self.assertIn("-map_metadata", captured_cmd)
        self.assertIn("0", captured_cmd)
        self.assertIn("-metadata", captured_cmd)
        self.assertIn("title=Song Title", captured_cmd)
        self.assertIn("artist=Song Artist", captured_cmd)
        self.assertIn("album=Song Album", captured_cmd)
        self.assertIn("date=2024", captured_cmd)

    def test_14_real_ffmpeg_embed_and_ffprobe_verify_all_formats(self):
        """Real integration test with bundled FFmpeg across MP3, M4A, FLAC, and OPUS."""
        from core.paths import get_bundled_executable
        from downloader.ffmpeg_checker import FFmpegChecker

        ffmpeg_dir = FFmpegChecker.get_ffmpeg_directory()
        if not ffmpeg_dir:
            self.skipTest("FFmpeg directory not found on test system.")

        ffmpeg_bin = CoverArtManager._resolve_ffmpeg_executable(ffmpeg_dir)
        ffprobe_bin = CoverArtManager._resolve_ffprobe_executable(ffmpeg_dir)
        if not Path(ffmpeg_bin).is_file() or not Path(ffprobe_bin).is_file():
            self.skipTest("FFmpeg or FFprobe executable not present.")

        cover_img = self.target_dir / "cover.jpg"
        im = Image.new("RGB", (300, 300), color=(128, 64, 255))
        im.save(cover_img, "JPEG")

        test_metadata = {
            "title": "Universal Track Title",
            "artist": "Star Performer",
            "album": "Cosmic Sounds",
            "date": "2025",
        }

        formats_codecs = [
            ("mp3", "libmp3lame"),
            ("m4a", "aac"),
            ("flac", "flac"),
            ("opus", "libopus"),
        ]

        for fmt, codec in formats_codecs:
            media_file = self.target_dir / f"test_audio.{fmt}"
            # Synthesize 0.5s audio tone
            gen_cmd = [
                ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                "-c:a", codec, str(media_file)
            ]
            r = subprocess.run(gen_cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"Failed to synthesize {fmt}: {r.stderr}")

            # Test embedding with directory path as ffmpeg_location!
            succ = CoverArtManager.embed_cover_art(
                media_path=media_file,
                cover_image_path=cover_img,
                ffmpeg_location=ffmpeg_dir,
                metadata=test_metadata,
            )
            self.assertTrue(succ, f"Embedding failed for {fmt}")

            # Probe with real ffprobe
            probe_cmd = [
                ffprobe_bin, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(media_file)
            ]
            p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            self.assertEqual(p_res.returncode, 0)
            data = json.loads(p_res.stdout)

            streams = data.get("streams", [])
            format_tags = data.get("format", {}).get("tags", {})

            # 1. Verify cover art attached pic stream or METADATA_BLOCK_PICTURE
            has_attached_pic = False
            for s in streams:
                if s.get("codec_type") == "video":
                    if s.get("disposition", {}).get("attached_pic") == 1 or fmt == "mp3":
                        has_attached_pic = True
                        break
            if fmt == "opus" and not has_attached_pic:
                has_attached_pic = "METADATA_BLOCK_PICTURE" in format_tags or "metadata_block_picture" in format_tags

            self.assertTrue(has_attached_pic, f"Attached picture missing in {fmt}")

            # 2. Verify metadata tags (in format tags or stream 0 audio tags)
            combined_tags = dict(format_tags)
            # In Opus/Ogg, Vorbis comments reside in stream 0 (audio stream)
            if streams and streams[0].get("codec_type") == "audio":
                combined_tags.update(streams[0].get("tags", {}))
            norm_tags = {k.lower(): v for k, v in combined_tags.items()}

            self.assertEqual(norm_tags.get("title"), "Universal Track Title", f"Title missing in {fmt}")
            self.assertEqual(norm_tags.get("artist"), "Star Performer", f"Artist missing in {fmt}")
            self.assertEqual(norm_tags.get("album"), "Cosmic Sounds", f"Album missing in {fmt}")

    def test_15_real_ffmpeg_embed_metadata_only_and_ffprobe_verify(self):
        from downloader.ffmpeg_checker import FFmpegChecker
        """Verify metadata-only embedding into MP3, M4A, FLAC, and OPUS via FFmpeg stream copy."""
        ffmpeg_dir = FFmpegChecker.get_ffmpeg_directory()
        if not ffmpeg_dir:
            self.skipTest("FFmpeg directory not found on test system.")

        ffmpeg_bin = CoverArtManager._resolve_ffmpeg_executable(ffmpeg_dir)
        ffprobe_bin = CoverArtManager._resolve_ffprobe_executable(ffmpeg_dir)
        if not Path(ffmpeg_bin).is_file() or not Path(ffprobe_bin).is_file():
            self.skipTest("FFmpeg or FFprobe executable not present.")

        test_metadata = {
            "title": "Pure Audio Title",
            "artist": "Solo Maestro",
            "album": "Acoustic Sessions",
            "date": "2026",
            "track": "3",
            "genre": "Acoustic",
        }

        formats_codecs = [
            ("mp3", "libmp3lame"),
            ("m4a", "aac"),
            ("flac", "flac"),
            ("opus", "libopus"),
        ]

        for fmt, codec in formats_codecs:
            media_file = self.target_dir / f"meta_test_audio.{fmt}"
            gen_cmd = [
                ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=520:duration=0.5",
                "-c:a", codec, str(media_file)
            ]
            r = subprocess.run(gen_cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"Failed to synthesize {fmt}: {r.stderr}")

            # Embed metadata without cover art
            succ = CoverArtManager.embed_metadata(
                media_path=media_file,
                metadata=test_metadata,
                ffmpeg_location=ffmpeg_dir,
            )
            self.assertTrue(succ, f"Metadata embedding failed for {fmt}")

            # Verify with ffprobe
            probe_cmd = [
                ffprobe_bin, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(media_file)
            ]
            p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            self.assertEqual(p_res.returncode, 0)
            data = json.loads(p_res.stdout)

            streams = data.get("streams", [])
            format_tags = data.get("format", {}).get("tags", {})
            combined_tags = dict(format_tags)
            if streams and streams[0].get("codec_type") == "audio":
                combined_tags.update(streams[0].get("tags", {}))
            norm_tags = {k.lower(): v for k, v in combined_tags.items()}

            self.assertEqual(norm_tags.get("title"), "Pure Audio Title", f"Title missing in {fmt}")
            self.assertEqual(norm_tags.get("artist"), "Solo Maestro", f"Artist missing in {fmt}")
            self.assertEqual(norm_tags.get("album"), "Acoustic Sessions", f"Album missing in {fmt}")

        # Unsupported formats must be rejected immediately
        wav_file = self.target_dir / "unsupported.wav"
        wav_file.write_bytes(b"RIFFdummyWAVE")
        self.assertFalse(CoverArtManager.embed_metadata(wav_file, test_metadata))

        aac_file = self.target_dir / "unsupported.aac"
        aac_file.write_bytes(b"dummyAAC")
        self.assertFalse(CoverArtManager.embed_metadata(aac_file, test_metadata))


class TestCoverArtDetectionWorker(unittest.TestCase):
    """Verifies CoverArtDetectionWorker background thread behavior."""

    @patch.object(CoverArtManager, "detect_cover_art_for_videos")
    def test_worker_signals_success(self, mock_detect):
        mock_detect.return_value = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/test=s0",
            "width": 1400,
            "height": 1400,
        }
        videos = [VideoItem(index=1, video_id="abc", title="Track 1", duration="3:00")]
        worker = CoverArtDetectionWorker(videos)

        captured = []
        worker.cover_art_detected.connect(lambda has_cov, w, h, info: captured.append((has_cov, w, h, info)))
        worker.run()

        self.assertEqual(len(captured), 1)
        has_cov, w, h, info = captured[0]
        self.assertTrue(has_cov)
        self.assertEqual(w, 1400)
        self.assertEqual(h, 1400)
        self.assertIsNotNone(info)

    @patch.object(CoverArtManager, "detect_cover_art_for_videos")
    def test_worker_signals_failure_when_no_cover(self, mock_detect):
        mock_detect.return_value = None
        videos = [VideoItem(index=1, video_id="abc", title="Track 1", duration="3:00")]
        worker = CoverArtDetectionWorker(videos)

        captured = []
        worker.cover_art_detected.connect(lambda has_cov, w, h, info: captured.append((has_cov, w, h, info)))
        worker.run()

        self.assertEqual(len(captured), 1)
        has_cov, w, h, info = captured[0]
        self.assertFalse(has_cov)
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)
        self.assertIsNone(info)


class TestCoverArtUIGating(unittest.TestCase):
    """Verifies MainWindow UI gating, dynamic text dimensions, and platform scoping."""

    def setUp(self):
        self.temp_settings_dir = tempfile.TemporaryDirectory()
        settings_path = Path(self.temp_settings_dir.name) / "settings.json"
        self.settings_manager = SettingsManager(settings_path=settings_path)
        self.settings_manager.set("download_mode", DownloadMode.VIDEO_AND_AUDIO)
        self.settings_manager.set("selected_platform", "youtube")
        self.settings_manager.set("audio_format", "MP3")

        self.window = MainWindow(settings_manager=self.settings_manager)
        # Explicitly ensure mode is Video + Audio for baseline tests
        idx = self.window.mode_combo.findData(DownloadMode.VIDEO_AND_AUDIO)
        if idx >= 0:
            self.window.mode_combo.setCurrentIndex(idx)

    def tearDown(self):
        self.window.close()
        self.temp_settings_dir.cleanup()

    def test_01_initial_state_disabled(self):
        """Initial state before scanning: both Cover Art checkboxes are disabled."""
        self.assertFalse(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())
        self.assertEqual(self.window.cover_art_cb.text(), tr("cb_download_cover_art"))

    def test_02_cover_art_detected_enables_and_shows_dimensions(self):
        """When Cover Art is detected with dimensions, checkbox enables and reflects width x height."""
        self.window.mode_combo.setCurrentIndex(self.window.mode_combo.findData(DownloadMode.VIDEO_AND_AUDIO))
        info = {
            "source": "innertube_master",
            "url": "https://lh3.googleusercontent.com/test=s0",
            "width": 1400,
            "height": 1400,
        }
        self.window._on_cover_art_detected(True, 1400, 1400, info)

        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertEqual(self.window.cover_art_cb.text(), tr("cb_download_cover_art"))
        self.assertIn("1400 x 1400", self.window.cover_art_dims_label.text())
        self.assertFalse(self.window.cover_art_dims_label.isHidden())
        # Audio mode enables embed_cover_art_cb
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

    def test_03_mode_gating_audio_only_vs_video_only(self):
        """embed_cover_art_cb is only enabled in Audio Only and Video + Audio modes."""
        info = {"source": "innertube_master", "url": "test", "width": 1400, "height": 1400}
        self.window._on_cover_art_detected(True, 1400, 1400, info)

        # 1. Audio Only -> Enabled
        self.window.mode_combo.setCurrentIndex(self.window.mode_combo.findData(DownloadMode.AUDIO_ONLY))
        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

        # 2. Video Only -> Embed disabled, Download Cover Art enabled
        self.window.mode_combo.setCurrentIndex(self.window.mode_combo.findData(DownloadMode.VIDEO_ONLY))
        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())

        # 3. Assets Only -> Embed disabled, Download Cover Art enabled
        self.window.mode_combo.setCurrentIndex(self.window.mode_combo.findData(DownloadMode.ASSETS_ONLY))
        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())

        # 4. Image Only -> Both disabled
        self.window.mode_combo.setCurrentIndex(self.window.mode_combo.findData(DownloadMode.IMAGE_ONLY))
        self.assertFalse(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())

    def test_04_platform_scoping(self):
        """Cover Art options are only visible and active for YouTube; hidden for other platforms."""
        info = {"source": "innertube_master", "url": "test", "width": 1400, "height": 1400}
        self.window._on_cover_art_detected(True, 1400, 1400, info)

        # On YouTube: not hidden and enabled
        self.assertFalse(self.window.cover_art_cb.isHidden())
        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isHidden())
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

        # Switch to TikTok: disabled and hidden
        self.window._apply_platform_ui("tiktok")
        self.assertTrue(self.window.cover_art_cb.isHidden())
        self.assertFalse(self.window.cover_art_cb.isEnabled())
        self.assertTrue(self.window.embed_cover_art_cb.isHidden())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())

        # Switch back to YouTube: restored
        self.window._apply_platform_ui("youtube")
        self.assertFalse(self.window.cover_art_cb.isHidden())
        self.assertTrue(self.window.cover_art_cb.isEnabled())
        self.assertFalse(self.window.embed_cover_art_cb.isHidden())
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

    def test_05_retranslate_ui_preserves_dimensions(self):
        """Switching UI language preserves dynamic dimensions in label underneath."""
        info = {"source": "innertube_master", "url": "test", "width": 1400, "height": 1400}
        self.window._on_cover_art_detected(True, 1400, 1400, info)

        I18nManager.set_language(I18nManager.LANG_ZH)
        self.window.retranslate_ui()
        self.assertEqual(self.window.cover_art_cb.text(), tr("cb_download_cover_art"))
        self.assertIn("1400 x 1400", self.window.cover_art_dims_label.text())
        self.assertFalse(self.window.cover_art_dims_label.isHidden())
        self.assertEqual(self.window.embed_cover_art_cb.text(), tr("cb_embed_cover_art"))

        I18nManager.set_language(I18nManager.LANG_ZH_TW)
        self.window.retranslate_ui()
        self.assertEqual(self.window.cover_art_cb.text(), tr("cb_download_cover_art"))
        self.assertIn("1400 x 1400", self.window.cover_art_dims_label.text())
        self.assertFalse(self.window.cover_art_dims_label.isHidden())
        self.assertEqual(self.window.embed_cover_art_cb.text(), tr("cb_embed_cover_art"))

        # Restore English
        I18nManager.set_language(I18nManager.LANG_EN)
        self.window.retranslate_ui()
        self.assertEqual(self.window.cover_art_cb.text(), tr("cb_download_cover_art"))
        self.assertIn("1400 x 1400", self.window.cover_art_dims_label.text())
        self.assertFalse(self.window.cover_art_dims_label.isHidden())

    def test_06_unsupported_audio_format_disables_and_unchecks_embed(self):
        """Selecting WAV or AAC automatically unchecks and disables embed_cover_art_cb."""
        info = {"source": "innertube_master", "url": "test", "width": 1400, "height": 1400}
        self.window._on_cover_art_detected(True, 1400, 1400, info)

        # 1. Switch to MP3 -> Enabled
        mp3_idx = self.window.audio_format_combo.findText("MP3")
        self.window.audio_format_combo.setCurrentIndex(mp3_idx)
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

        # Check the box
        self.window.embed_cover_art_cb.setChecked(True)
        self.assertTrue(self.window.embed_cover_art_cb.isChecked())

        # 2. Switch to WAV -> Must automatically uncheck and disable
        wav_idx = self.window.audio_format_combo.findText("WAV")
        self.window.audio_format_combo.setCurrentIndex(wav_idx)
        self.assertFalse(self.window.embed_cover_art_cb.isChecked())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())
        self.assertEqual(self.window.embed_cover_art_cb.toolTip(), tr("tooltip_embed_cover_art_unsupported"))

        # 3. Switch to AAC -> Remains disabled and unchecked
        aac_idx = self.window.audio_format_combo.findText("AAC")
        self.window.audio_format_combo.setCurrentIndex(aac_idx)
        self.assertFalse(self.window.embed_cover_art_cb.isChecked())
        self.assertFalse(self.window.embed_cover_art_cb.isEnabled())

        # 4. Switch to M4A -> Becomes enabled again
        m4a_idx = self.window.audio_format_combo.findText("M4A")
        self.window.audio_format_combo.setCurrentIndex(m4a_idx)
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

        # 5. Switch to FLAC -> Enabled
        flac_idx = self.window.audio_format_combo.findText("FLAC")
        self.window.audio_format_combo.setCurrentIndex(flac_idx)
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

        # 6. Switch to OPUS -> Enabled
        opus_idx = self.window.audio_format_combo.findText("OPUS")
        self.window.audio_format_combo.setCurrentIndex(opus_idx)
        self.assertTrue(self.window.embed_cover_art_cb.isEnabled())

    def test_07_unsupported_audio_format_disables_and_unchecks_embed_metadata(self):
        """Selecting WAV or AAC automatically unchecks and disables embed_metadata_cb."""
        # Switch mode to Audio Only so audio checkboxes are active
        idx_ao = self.window.mode_combo.findData(DownloadMode.AUDIO_ONLY)
        self.window.mode_combo.setCurrentIndex(idx_ao)

        # 1. Switch to MP3 -> Enabled
        mp3_idx = self.window.audio_format_combo.findText("MP3")
        self.window.audio_format_combo.setCurrentIndex(mp3_idx)
        self.assertTrue(self.window.embed_metadata_cb.isEnabled())

        # Check the box
        self.window.embed_metadata_cb.setChecked(True)
        self.assertTrue(self.window.embed_metadata_cb.isChecked())

        # 2. Switch to WAV -> Must automatically uncheck and disable
        wav_idx = self.window.audio_format_combo.findText("WAV")
        self.window.audio_format_combo.setCurrentIndex(wav_idx)
        self.assertFalse(self.window.embed_metadata_cb.isChecked())
        self.assertFalse(self.window.embed_metadata_cb.isEnabled())
        self.assertEqual(self.window.embed_metadata_cb.toolTip(), tr("tooltip_embed_media_metadata_unsupported"))

        # 3. Switch to AAC -> Remains disabled and unchecked
        aac_idx = self.window.audio_format_combo.findText("AAC")
        self.window.audio_format_combo.setCurrentIndex(aac_idx)
        self.assertFalse(self.window.embed_metadata_cb.isChecked())
        self.assertFalse(self.window.embed_metadata_cb.isEnabled())

        # 4. Switch to M4A -> Becomes enabled again
        m4a_idx = self.window.audio_format_combo.findText("M4A")
        self.window.audio_format_combo.setCurrentIndex(m4a_idx)
        self.assertTrue(self.window.embed_metadata_cb.isEnabled())

        # 5. Switch to FLAC -> Enabled
        flac_idx = self.window.audio_format_combo.findText("FLAC")
        self.window.audio_format_combo.setCurrentIndex(flac_idx)
        self.assertTrue(self.window.embed_metadata_cb.isEnabled())

        # 6. Switch to OPUS -> Enabled
        opus_idx = self.window.audio_format_combo.findText("OPUS")
        self.window.audio_format_combo.setCurrentIndex(opus_idx)
        self.assertTrue(self.window.embed_metadata_cb.isEnabled())

        # 7. Mode gating: Switch mode to Video Only -> Disabled
        idx_vo = self.window.mode_combo.findData(DownloadMode.VIDEO_ONLY)
        self.window.mode_combo.setCurrentIndex(idx_vo)
        self.assertFalse(self.window.embed_metadata_cb.isEnabled())

        # Switch back to Audio Only -> Re-enabled
        self.window.mode_combo.setCurrentIndex(idx_ao)
        self.assertTrue(self.window.embed_metadata_cb.isEnabled())


class TestAutoClearAndFolderLabels(unittest.TestCase):
    """Verifies Request 1 (folder label typo), Requests 2 & 3 (auto-clear options)."""

    def setUp(self):
        self.temp_settings_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_settings_dir.name) / "settings.json"
        self.settings_manager = SettingsManager(settings_path=self.settings_path)
        self.window = MainWindow(settings_manager=self.settings_manager)

    def tearDown(self):
        self.window.close()
        self.temp_settings_dir.cleanup()

    def test_01_create_individual_media_folder_no_trailing_s(self):
        """Verify 'Create individual media folder' in English has no trailing 's' in folder."""
        I18nManager.set_language(I18nManager.LANG_EN)
        self.window.retranslate_ui()
        label_text = self.window.individual_media_folder_cb.text()
        self.assertEqual(label_text, "Create individual media folder")
        self.assertFalse(label_text.endswith("folders"))

    def test_02_settings_dialog_clear_options_persistence(self):
        """Verify clear link and clear media table checkboxes in SettingsDialog persist to SettingsManager."""
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(parent=self.window, settings_manager=self.settings_manager)
        try:
            # Default is False
            self.assertFalse(dlg.clear_link_cb.isChecked())
            self.assertFalse(dlg.clear_table_cb.isChecked())

            # Toggle ON
            dlg.clear_link_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("clear_link_after_download"))
            dlg.clear_table_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("clear_media_table_after_download"))

            # Toggle OFF
            dlg.clear_link_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("clear_link_after_download"))
            dlg.clear_table_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("clear_media_table_after_download"))
        finally:
            dlg.close()

    @patch("gui.summary_dialog.SummaryDialog.exec")
    def test_03_main_window_auto_clear_after_download_completed(self, mock_dialog_exec):
        """When enabled, completing download queue automatically clears URL input and media table."""
        # Enable both auto-clear settings
        self.settings_manager.set("clear_link_after_download", True)
        self.settings_manager.set("clear_media_table_after_download", True)

        # Set up active state in MainWindow
        self.window.url_input.setText("https://www.youtube.com/watch?v=abcdefghijk")
        self.settings_manager.set("last_channel_url", "https://www.youtube.com/watch?v=abcdefghijk")
        test_video = VideoItem(index=1, video_id="test1", title="Song 1", duration="3:00")
        self.window.video_table.load_videos([test_video])
        self.window._detected_cover_art = {"url": "https://lh3.googleusercontent.com/test"}
        self.window._cover_art_dims = (1400, 1400)

        self.assertEqual(len(self.window.video_table.videos), 1)
        self.assertEqual(self.window.url_input.text(), "https://www.youtube.com/watch?v=abcdefghijk")

        # Trigger queue finished
        self.window._on_queue_finished(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
        )

        # URL should be cleared
        self.assertEqual(self.window.url_input.text(), "")
        self.assertEqual(self.settings_manager.get("last_channel_url"), "")

        # Media table and cover art state should be cleared
        self.assertEqual(len(self.window.video_table.videos), 0)
        self.assertIsNone(self.window._detected_cover_art)
        self.assertEqual(self.window._cover_art_dims, (0, 0))

    @patch("gui.summary_dialog.SummaryDialog.exec")
    def test_04_main_window_no_clear_when_disabled(self, mock_dialog_exec):
        """When disabled, completing download queue preserves URL input and media table."""
        self.settings_manager.set("clear_link_after_download", False)
        self.settings_manager.set("clear_media_table_after_download", False)

        self.window.url_input.setText("https://www.youtube.com/watch?v=keepurl12345")
        test_video = VideoItem(index=1, video_id="test2", title="Song 2", duration="2:30")
        self.window.video_table.load_videos([test_video])

        self.window._on_queue_finished(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
        )

        # Content should remain
        self.assertEqual(self.window.url_input.text(), "https://www.youtube.com/watch?v=keepurl12345")
        self.assertEqual(len(self.window.video_table.videos), 1)

    def test_05_clear_custom_folder_name_toggle_persistence(self):
        """Verify Automatic Clear Custom Folder Name switch persists to SettingsManager."""
        from gui.settings_dialog import SettingsDialog
        from gui.toggle_switch import ToggleSwitch

        dlg = SettingsDialog(None, settings_manager=self.settings_manager)
        try:
            self.assertTrue(hasattr(dlg, "clear_custom_folder_cb"))
            self.assertIsInstance(dlg.clear_custom_folder_cb, ToggleSwitch)
            self.assertFalse(dlg.clear_custom_folder_cb.isChecked())

            # Toggle ON
            dlg.clear_custom_folder_cb.setChecked(True)
            self.assertTrue(self.settings_manager.get("clear_custom_folder_name_after_download"))

            # Toggle OFF
            dlg.clear_custom_folder_cb.setChecked(False)
            self.assertFalse(self.settings_manager.get("clear_custom_folder_name_after_download"))
        finally:
            dlg.close()

    @patch("gui.summary_dialog.SummaryDialog.exec")
    def test_06_main_window_auto_clear_custom_folder_name_when_enabled(self, mock_dialog_exec):
        """When enabled, completing download queue automatically clears the custom folder name input."""
        self.settings_manager.set("clear_custom_folder_name_after_download", True)
        self.window.unique_folder_input.setText("My Album Custom Folder")
        self.assertEqual(self.window.unique_folder_input.text(), "My Album Custom Folder")

        self.window._on_queue_finished(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
        )

        self.assertEqual(self.window.unique_folder_input.text(), "")

    @patch("gui.summary_dialog.SummaryDialog.exec")
    def test_07_main_window_preserve_custom_folder_name_when_disabled(self, mock_dialog_exec):
        """When disabled, completing download queue preserves the custom folder name input."""
        self.settings_manager.set("clear_custom_folder_name_after_download", False)
        self.window.unique_folder_input.setText("Keep Custom Folder")

        self.window._on_queue_finished(
            completed=1,
            skipped=0,
            failed=0,
            total=1,
        )

        self.assertEqual(self.window.unique_folder_input.text(), "Keep Custom Folder")

    def test_09_embed_metadata_persistence(self):
        """Verify embed_metadata setting persists to SettingsManager."""
        from core.settings import SettingsManager
        from gui.main_window import MainWindow
        sm = SettingsManager()
        orig = sm.get("embed_metadata", False)
        try:
            sm.set("embed_metadata", True)
            win = MainWindow(settings_manager=sm)
            self.assertTrue(win.settings_manager.get("embed_metadata"))
            win.close()
        finally:
            sm.set("embed_metadata", orig)

    def test_08_general_section_above_appearance_and_toggle_switch_instances(self):
        """Verify GENERAL section is placed above APPEARANCE and uses ToggleSwitch controls."""
        from gui.settings_dialog import SettingsDialog
        from gui.toggle_switch import ToggleSwitch

        dlg = SettingsDialog(None, settings_manager=self.settings_manager)
        try:
            self.assertTrue(hasattr(dlg, "general_title"))
            self.assertTrue(hasattr(dlg, "appear_title"))
            self.assertEqual(dlg.general_title.text(), "GENERAL")
            self.assertEqual(dlg.appear_title.text(), "APPEARANCE")

            # Check all 4 toggles
            self.assertIsInstance(dlg.notif_cb, ToggleSwitch)
            self.assertIsInstance(dlg.clear_link_cb, ToggleSwitch)
            self.assertIsInstance(dlg.clear_media_list_cb, ToggleSwitch)
            self.assertIsInstance(dlg.clear_custom_folder_cb, ToggleSwitch)

            # Ensure GENERAL section precedes APPEARANCE in the scroll layout
            scroll_content = dlg.general_title.parentWidget()
            layout = scroll_content.layout()
            gen_idx = -1
            app_idx = -1
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w == dlg.general_title:
                    gen_idx = i
                elif w == dlg.appear_title:
                    app_idx = i

            self.assertNotEqual(gen_idx, -1, "GENERAL title not found in layout")
            self.assertNotEqual(app_idx, -1, "APPEARANCE title not found in layout")
            self.assertLess(gen_idx, app_idx, "GENERAL section must appear above APPEARANCE section")
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
