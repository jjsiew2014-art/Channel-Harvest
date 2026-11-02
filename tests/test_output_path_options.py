"""
test_output_path_options.py
Regression tests verifying yt-dlp output path options and output templates.

Verifies:
1. Omission of redundant 'paths' option in all download modes (VIDEO_ONLY, AUDIO_ONLY, VIDEO_AND_AUDIO).
2. Omission of redundant 'paths' option in auxiliary managers (subtitles, thumbnails, info/descriptions).
3. Absolute output templates anchored to target directory without --paths conflict warnings.
4. Audio-only WAV downloading and FFmpegExtractAudio postprocessing configuration.
5. Base yt-dlp options retain temp directory configuration for flat metadata extractions.
6. Zero '[yt-dlp WARNING] --paths is ignored' log messages are emitted during filename preparation.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yt_dlp

REAL_YOUTUBEDL = yt_dlp.YoutubeDL

from core.models import VideoItem, DownloadSettings, DownloadMode, VideoStatus
from core.paths import resolve_video_outtmpl
from downloader.format_selector import FormatSelector
from downloader.ytdlp_engine import YtDlpEngine, YtDlpLogger
from downloader.subtitle_manager import SubtitleManager
from downloader.thumbnail_manager import ThumbnailManager
from downloader.info_manager import InfoManager


class TestOutputPathOptions(unittest.TestCase):
    """Regression test suite for yt-dlp output path options and warning-free template resolution."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ch_test_outpaths_"))
        self.target_dir = self.test_dir / "Test Channel"
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.video = VideoItem(
            index=1,
            video_id="dQw4w9WgXcQ",
            title="Never Gonna Give You Up",
            duration="03:33",
            duration_seconds=213,
            status=VideoStatus.READY,
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            channel_title="Rick Astley",
            selected=True,
        )

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    def test_build_base_ydl_opts_retains_temp_path(self):
        """Base options for channel scanning and info extraction must retain safe temp path."""
        opts = YtDlpEngine.build_base_ydl_opts(platform="youtube")
        self.assertIn("paths", opts)
        self.assertIn("temp", opts["paths"])
        temp_p = Path(opts["paths"]["temp"])
        self.assertTrue(temp_p.exists())

    @patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL")
    def test_video_only_mode_omits_paths_and_has_absolute_outtmpl(self, mock_ydl_cls):
        """Video Only mode must omit paths and use absolute outtmpl without warnings."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_ONLY,
            format="MP4",
            quality="1080p",
            include_video_id_in_filename=True,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)

        self.assertTrue(mock_ydl_cls.called)
        ydl_opts = mock_ydl_cls.call_args[0][0]

        # 1. 'paths' option must be omitted to prevent conflict warning
        self.assertNotIn("paths", ydl_opts)

        # 2. 'outtmpl' must be an absolute path within target_dir
        outtmpl = ydl_opts["outtmpl"]
        self.assertTrue(os.path.isabs(outtmpl))
        self.assertTrue(str(outtmpl).startswith(str(self.target_dir)))
        self.assertIn("%(title)s [%(id)s].%(ext)s", outtmpl)

        # 3. Verify actual yt-dlp YoutubeDL instance prepares filename without warning
        warnings_caught = []
        test_opts = dict(ydl_opts)
        test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
        real_ydl = REAL_YOUTUBEDL(test_opts)
        fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "mp4"}
        prepared = real_ydl.prepare_filename(fake_info, warn=True)

        # Filename must match target directory
        expected_path = self.target_dir / "Never Gonna Give You Up [dQw4w9WgXcQ].mp4"
        self.assertEqual(Path(prepared), expected_path)

        # No --paths warning must be emitted
        for w in warnings_caught:
            self.assertNotIn("--paths is ignored", w)

    @patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL")
    def test_audio_only_wav_mode_omits_paths_and_configures_transcoding(self, mock_ydl_cls):
        """Audio Only mode with WAV format must omit paths, set absolute outtmpl, and configure FFmpegExtractAudio."""
        settings = DownloadSettings(
            download_mode=DownloadMode.AUDIO_ONLY,
            audio_format="WAV",
            include_video_id_in_filename=False,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)

        self.assertTrue(mock_ydl_cls.called)
        ydl_opts = mock_ydl_cls.call_args[0][0]

        # 1. 'paths' option must be omitted
        self.assertNotIn("paths", ydl_opts)

        # 2. 'outtmpl' must be absolute
        outtmpl = ydl_opts["outtmpl"]
        self.assertTrue(os.path.isabs(outtmpl))
        self.assertTrue(str(outtmpl).startswith(str(self.target_dir)))
        self.assertIn("%(title)s.%(ext)s", outtmpl)

        # 3. Postprocessors must include FFmpegExtractAudio with wav preferredcodec
        pps = ydl_opts.get("postprocessors", [])
        self.assertTrue(any(
            pp.get("key") == "FFmpegExtractAudio" and pp.get("preferredcodec") == "wav"
            for pp in pps
        ))

        # 4. yt-dlp prepare_filename must emit zero path warnings
        warnings_caught = []
        test_opts = dict(ydl_opts)
        test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
        real_ydl = REAL_YOUTUBEDL(test_opts)
        fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "wav"}
        prepared = real_ydl.prepare_filename(fake_info, warn=True)

        expected_path = self.target_dir / "Never Gonna Give You Up.wav"
        self.assertEqual(Path(prepared), expected_path)
        for w in warnings_caught:
            self.assertNotIn("--paths is ignored", w)

    @patch("downloader.ytdlp_engine.yt_dlp.YoutubeDL")
    def test_video_and_audio_mode_omits_paths_in_both_passes(self, mock_ydl_cls):
        """Video + Audio mode must omit paths in both video and audio passes."""
        settings = DownloadSettings(
            download_mode=DownloadMode.VIDEO_AND_AUDIO,
            format="MP4",
            quality="1080p",
            audio_format="MP3",
            include_video_id_in_filename=True,
        )
        engine = YtDlpEngine()
        engine.download_single_video(self.video, settings, self.target_dir)

        self.assertGreaterEqual(mock_ydl_cls.call_count, 2)
        v_call_opts = mock_ydl_cls.call_args_list[0][0][0]
        a_call_opts = mock_ydl_cls.call_args_list[1][0][0]

        # Video pass
        self.assertNotIn("paths", v_call_opts)
        self.assertTrue(os.path.isabs(v_call_opts["outtmpl"]))
        self.assertTrue(str(v_call_opts["outtmpl"]).startswith(str(self.target_dir)))

        # Audio pass
        self.assertNotIn("paths", a_call_opts)
        self.assertTrue(os.path.isabs(a_call_opts["outtmpl"]))
        self.assertTrue(str(a_call_opts["outtmpl"]).startswith(str(self.target_dir)))

        # Verify real yt-dlp prepare_filename warning-free for both
        for pass_opts, expected_suffix in ((v_call_opts, ".mp4"), (a_call_opts, ".mp3")):
            warnings_caught = []
            test_opts = dict(pass_opts)
            test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
            real_ydl = REAL_YOUTUBEDL(test_opts)
            fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "mp4"}
            prepared = real_ydl.prepare_filename(fake_info, warn=True)
            self.assertTrue(Path(prepared).is_relative_to(self.target_dir))
            for w in warnings_caught:
                self.assertNotIn("--paths is ignored", w)

    @patch("downloader.subtitle_manager.yt_dlp.YoutubeDL")
    def test_subtitle_manager_omits_paths_and_has_absolute_outtmpl(self, mock_ydl_cls):
        """SubtitleManager must omit paths and use absolute outtmpl anchored to target_dir."""
        settings = DownloadSettings(
            download_subtitles=True,
            subtitle_language="en",
            include_video_id_in_filename=False,
        )
        with patch.object(SubtitleManager, "inspect_subtitles", return_value=({"en": [{}]}, {})):
            mock_ydl_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance

            SubtitleManager.download_subtitles(self.video, settings, self.target_dir)

            self.assertTrue(mock_ydl_cls.called)
            ydl_opts = mock_ydl_cls.call_args[0][0]

            self.assertNotIn("paths", ydl_opts)
            self.assertTrue(os.path.isabs(ydl_opts["outtmpl"]))
            self.assertTrue(str(ydl_opts["outtmpl"]).startswith(str(self.target_dir)))

            # Test real yt-dlp prepare_filename warning-free
            warnings_caught = []
            test_opts = dict(ydl_opts)
            test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
            real_ydl = REAL_YOUTUBEDL(test_opts)
            fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "vtt"}
            prepared = real_ydl.prepare_filename(fake_info, warn=True)
            self.assertEqual(Path(prepared), self.target_dir / "Never Gonna Give You Up.vtt")
            for w in warnings_caught:
                self.assertNotIn("--paths is ignored", w)

    @patch("downloader.thumbnail_manager.yt_dlp.YoutubeDL")
    def test_thumbnail_manager_omits_paths_and_has_absolute_outtmpl(self, mock_ydl_cls):
        """ThumbnailManager must omit paths and use absolute outtmpl anchored to target_dir."""
        settings = DownloadSettings(
            download_thumbnail=True,
            thumbnail_format="PNG",
            include_video_id_in_filename=False,
        )
        mock_ydl_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance

        ThumbnailManager.download_thumbnail(self.video, settings, self.target_dir)

        self.assertTrue(mock_ydl_cls.called)
        ydl_opts = mock_ydl_cls.call_args[0][0]

        self.assertNotIn("paths", ydl_opts)
        self.assertTrue(os.path.isabs(ydl_opts["outtmpl"]))
        self.assertTrue(str(ydl_opts["outtmpl"]).startswith(str(self.target_dir)))

        # Test real yt-dlp prepare_filename warning-free
        warnings_caught = []
        test_opts = dict(ydl_opts)
        test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
        real_ydl = REAL_YOUTUBEDL(test_opts)
        fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "webp"}
        prepared = real_ydl.prepare_filename(fake_info, warn=True)
        self.assertEqual(Path(prepared), self.target_dir / "Never Gonna Give You Up.webp")
        for w in warnings_caught:
            self.assertNotIn("--paths is ignored", w)

    @patch("downloader.info_manager.yt_dlp.YoutubeDL")
    def test_info_manager_omits_paths_and_has_absolute_outtmpl(self, mock_ydl_cls):
        """InfoManager must omit paths and use absolute outtmpl anchored to target_dir."""
        settings = DownloadSettings(
            save_description=True,
            save_metadata=True,
            save_chapters=True,
            include_video_id_in_filename=False,
        )
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = {
            "title": "Never Gonna Give You Up",
            "id": "dQw4w9WgXcQ",
            "description": "Sample description",
            "chapters": [],
        }
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance

        InfoManager.save_video_info(self.video, settings, self.target_dir)

        self.assertTrue(mock_ydl_cls.called)
        ydl_opts = mock_ydl_cls.call_args[0][0]

        self.assertNotIn("paths", ydl_opts)
        self.assertTrue(os.path.isabs(ydl_opts["outtmpl"]))
        self.assertTrue(str(ydl_opts["outtmpl"]).startswith(str(self.target_dir)))

        # Test real yt-dlp prepare_filename warning-free
        warnings_caught = []
        test_opts = dict(ydl_opts)
        test_opts["logger"] = YtDlpLogger(log_callback=lambda msg: warnings_caught.append(msg))
        real_ydl = REAL_YOUTUBEDL(test_opts)
        fake_info = {"title": "Never Gonna Give You Up", "id": "dQw4w9WgXcQ", "ext": "description"}
        prepared = real_ydl.prepare_filename(fake_info, warn=True)
        self.assertEqual(Path(prepared), self.target_dir / "Never Gonna Give You Up.description")
        for w in warnings_caught:
            self.assertNotIn("--paths is ignored", w)


if __name__ == "__main__":
    unittest.main()
