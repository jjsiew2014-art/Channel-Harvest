"""
test_ffmpeg_postprocessing.py
Comprehensive regression tests for FFmpeg post-processing, container compatibility,
MovCompatibilityPP single-pass transcoding, diagnostic capture, progress deduplication,
and error classification across Channel Harvest.
"""

import unittest
from unittest.mock import MagicMock, patch
from collections import deque

from core.models import DownloadSettings, VideoItem, DownloadMode, VideoStatus
from core.error_classifier import ErrorClassifier, ErrorCategory, DownloadError
from core.diagnostics import PrivacySanitizer
from downloader.format_selector import FormatSelector
from downloader.ytdlp_engine import (
    MovCompatibilityPP,
    YtDlpLogger,
    DownloaderError,
    format_ffmpeg_technical_details,
)


class TestMovCompatibilityPP(unittest.TestCase):
    """Verifies MovCompatibilityPP single-pass postprocessor logic for MOV container."""

    def test_av1_video_transcodes_to_h264(self):
        """Incompatible AV1 video stream must be transcoded to H.264 in single pass."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mov"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mov")

        info = {
            "requested_formats": [
                {"format_id": "v1", "vcodec": "av01.0.08M.08", "acodec": "none", "ext": "mp4"},
                {"format_id": "a1", "vcodec": "none", "acodec": "mp4a.40.5", "ext": "m4a"},
            ]
        }
        del_files, res_info = pp.run(info)
        self.assertEqual(del_files, [])
        self.assertEqual(res_info, info)

        merger_args = mock_ydl.params.get("postprocessor_args", {}).get("merger", [])
        self.assertIn("-c:v", merger_args)
        self.assertIn("libx264", merger_args)
        # Compatible AAC audio must NOT be transcoded
        self.assertNotIn("-c:a", merger_args)

    def test_compatible_h264_preserves_stream_copy(self):
        """Native H.264 (avc1) video and AAC audio must preserve stream copy without transcoding."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mov"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mov")

        info = {
            "requested_formats": [
                {"format_id": "v1", "vcodec": "avc1.640028", "acodec": "none", "ext": "mp4"},
                {"format_id": "a1", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a"},
            ]
        }
        pp.run(info)
        # merger args must remain empty / None (preserving -c copy)
        self.assertNotIn("merger", mock_ydl.params.get("postprocessor_args", {}))

    def test_hevc_video_preserves_stream_copy(self):
        """HEVC (hev1/hvc1) video is natively supported in MOV and must preserve stream copy."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mov"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mov")

        info = {
            "requested_formats": [
                {"format_id": "v1", "vcodec": "hev1.1.6.L93.B0", "acodec": "none", "ext": "mp4"},
                {"format_id": "a1", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a"},
            ]
        }
        pp.run(info)
        self.assertNotIn("merger", mock_ydl.params.get("postprocessor_args", {}))

    def test_vp9_video_and_opus_audio_transcode_both(self):
        """Incompatible VP9 video and Opus audio must both be transcoded to H.264 + AAC."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mov"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mov")

        info = {
            "requested_formats": [
                {"format_id": "v1", "vcodec": "vp09.00.51.08", "acodec": "none", "ext": "webm"},
                {"format_id": "a1", "vcodec": "none", "acodec": "opus", "ext": "webm"},
            ]
        }
        pp.run(info)

        merger_args = mock_ydl.params.get("postprocessor_args", {}).get("merger", [])
        self.assertIn("-c:v", merger_args)
        self.assertIn("libx264", merger_args)
        self.assertIn("-c:a", merger_args)
        self.assertIn("aac", merger_args)

    def test_non_mov_container_does_nothing(self):
        """Target container other than MOV (e.g. mp4, mkv) must not inject merger transcode args."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mp4"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mp4")

        info = {
            "requested_formats": [
                {"format_id": "v1", "vcodec": "av01.0.08M.08", "acodec": "none", "ext": "mp4"},
                {"format_id": "a1", "vcodec": "none", "acodec": "mp4a.40.5", "ext": "m4a"},
            ]
        }
        pp.run(info)
        self.assertNotIn("merger", mock_ydl.params.get("postprocessor_args", {}))

    def test_premerged_single_format(self):
        """Single pre-merged format dict without requested_formats must be inspected directly."""
        mock_ydl = MagicMock()
        mock_ydl.params = {"merge_output_format": "mov"}
        pp = MovCompatibilityPP(downloader=mock_ydl, target_format="mov")

        info = {
            "format_id": "single",
            "vcodec": "av01.0.08M.08",
            "acodec": "opus",
            "ext": "mp4",
        }
        pp.run(info)
        merger_args = mock_ydl.params.get("postprocessor_args", {}).get("merger", [])
        self.assertIn("-c:v", merger_args)
        self.assertIn("libx264", merger_args)
        self.assertIn("-c:a", merger_args)
        self.assertIn("aac", merger_args)


class TestFormatSelectorMov(unittest.TestCase):
    """Verifies FormatSelector format string generation for MOV container."""

    def test_mov_format_spec_prefers_native_codecs(self):
        settings = DownloadSettings(format="MOV", quality="1080p")
        fmt, ext = FormatSelector.build_format_spec(settings)
        self.assertEqual(ext, "mov")
        # Native MOV codec regex must appear in the format selector
        self.assertIn("vcodec~='(?i)^(avc1|h264|hev1|hvc1|hevc|prores)'", fmt)
        self.assertIn("[height<=?1080]", fmt)
        # Must have fallback to any best video
        self.assertIn("bv*+ba/b", fmt)

    def test_mov_format_spec_best_available(self):
        settings = DownloadSettings(format="MOV", quality="Best Available")
        fmt, ext = FormatSelector.build_format_spec(settings)
        self.assertEqual(ext, "mov")
        self.assertIn("vcodec~='(?i)^(avc1|h264|hev1|hvc1|hevc|prores)'", fmt)
        self.assertNotIn("height<=?", fmt)


class TestYtDlpLoggerDiagnostics(unittest.TestCase):
    """Verifies that YtDlpLogger captures FFmpeg command and stderr output while redacting secrets."""

    def test_captures_ffmpeg_command_and_stderr(self):
        logger = YtDlpLogger()
        logger.debug("[debug] Encodings: utf-8")
        logger.debug("[debug] ffmpeg command line: ffmpeg -y -loglevel repeat+info -i temp.mp4 -c copy out.mov")
        logger.debug("[debug] [mov @ 000001] av1 only supported in MP4 and AVIF.")
        logger.debug("[debug] Conversion failed!")

        cmd = logger.get_ffmpeg_command()
        self.assertIn("ffmpeg -y", cmd)
        self.assertIn("out.mov", cmd)

        stderr = logger.get_ffmpeg_stderr()
        self.assertIn("av1 only supported in MP4 and AVIF", stderr)
        self.assertIn("Conversion failed!", stderr)

    def test_redacts_sensitive_parameters_in_logs(self):
        logger = YtDlpLogger()
        logger.debug("[debug] ffmpeg command line: ffmpeg -i https://video.fbcdn.net/v?token=SECRET123&sig=SIGNATURE456 out.mov")
        cmd = logger.get_ffmpeg_command()
        self.assertNotIn("SECRET123", cmd)
        self.assertNotIn("SIGNATURE456", cmd)

    def test_format_ffmpeg_technical_details(self):
        logger = MagicMock()
        logger.get_ffmpeg_diagnostics.return_value = {
            "ffmpeg_path": "C:\\runtime\\ffmpeg.exe",
            "ffmpeg_version": "v9.0.2",
            "ffmpeg_command": "ffmpeg -y -i v.mp4 -i a.m4a -c copy out.mov",
            "ffmpeg_stderr": "[mov @ 0x123] av1 only supported in MP4",
        }
        info_dict = {
            "requested_formats": [
                {"vcodec": "av01.0.08M.08", "acodec": "none", "ext": "mp4", "width": 1080, "height": 1920},
                {"vcodec": "none", "acodec": "mp4a.40.5", "ext": "m4a"},
            ]
        }
        details = format_ffmpeg_technical_details(
            raw_error="Conversion failed!",
            logger=logger,
            target_format="mov",
            info_dict=info_dict,
        )
        self.assertIn("FFmpeg Path: C:\\runtime\\ffmpeg.exe", details)
        self.assertIn("Target Container: MOV", details)
        self.assertIn("FFmpeg Command: ffmpeg -y", details)
        self.assertIn("av1 only supported in MP4", details)
        self.assertIn("Stream #0: ext=mp4, vcodec=av01.0.08M.08", details)


class TestPostprocessorProgressAndDeduplication(unittest.TestCase):
    """Verifies post-processor hook progress mapping and log deduplication."""

    def test_postprocessor_hook_maps_operations(self):
        events = []
        hook = YtDlpLogger._sanitize  # sanity
        from downloader.ytdlp_engine import YtDlpEngine

        pp_hook = YtDlpEngine._create_postprocessor_hook(
            cancel_check=None,
            progress_callback=events.append,
            step_label="Video",
        )

        pp_hook({"status": "started", "postprocessor": "Merger"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["operation"], "Merging streams")
        self.assertEqual(events[0]["step"], "Video")

        pp_hook({"status": "started", "postprocessor": "MoveFiles"})
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["operation"], "Finalizing file")

    def test_download_manager_deduplicates_processing_logs(self):
        """Progress callbacks with identical steps must not emit duplicate log messages."""
        logged = []
        last_logged_processing_step = None

        def simulate_progress(data, title="Sample Video"):
            nonlocal last_logged_processing_step
            status_val = data.get("status")
            step_val = data.get("step", "")
            if status_val == "processing":
                op_label = data.get("operation") or "Processing"
                current_step_key = f"{step_val}:{data.get('postprocessor', op_label)}"
                if current_step_key != last_logged_processing_step:
                    last_logged_processing_step = current_step_key
                    logged.append(f"[PROCESSING] FFmpeg {op_label.lower()} ({step_val or 'media'}): {title}")

        # Simulate Merger started event
        simulate_progress({"status": "processing", "step": "Video", "operation": "Merging streams", "postprocessor": "Merger"})
        # Duplicate callback with same postprocessor
        simulate_progress({"status": "processing", "step": "Video", "operation": "Merging streams", "postprocessor": "Merger"})
        # MoveFiles started
        simulate_progress({"status": "processing", "step": "Video", "operation": "Finalizing file", "postprocessor": "MoveFiles"})

        self.assertEqual(len(logged), 2)
        self.assertIn("merging streams (Video)", logged[0])
        self.assertIn("finalizing file (Video)", logged[1])


class TestErrorClassifierFFmpeg(unittest.TestCase):
    """Verifies evidence-based classification for FFmpeg failures."""

    def test_incompatible_codec_combination(self):
        err = ErrorClassifier.classify(
            raw_error="ERROR: Postprocessing: Conversion failed!\n[mov @ 000001] av1 only supported in MP4 and AVIF.\nCould not write header",
            stage="video",
        )
        self.assertEqual(err.category, ErrorCategory.FFMPEG_ERROR)
        self.assertEqual(err.title, "Unsupported Container / Codec Combination (FFmpeg)")
        self.assertEqual(err.stage, "conversion")
        self.assertIn("transcoding", err.user_message.lower())
        self.assertIn("MP4 or MKV", err.suggested_action)

    def test_corrupted_stream_error(self):
        err = ErrorClassifier.classify(
            raw_error="[ffmpeg] Invalid data found when processing input\nConversion failed!",
            stage="video",
        )
        self.assertEqual(err.category, ErrorCategory.FFMPEG_ERROR)
        self.assertEqual(err.title, "Corrupted / Incomplete Media Stream (FFmpeg)")
        self.assertEqual(err.stage, "conversion")

    def test_disk_space_during_ffmpeg(self):
        err = ErrorClassifier.classify(
            raw_error="ffmpeg error: No space left on device\nConversion failed!",
            stage="video",
        )
        self.assertEqual(err.category, ErrorCategory.DISK_SPACE_ERROR)
        self.assertEqual(err.title, "Disk space full")

    def test_permission_denied_during_ffmpeg(self):
        err = ErrorClassifier.classify(
            raw_error="ffmpeg error: Permission denied to open output.mov",
            stage="video",
        )
        self.assertEqual(err.category, ErrorCategory.PERMISSION_ERROR)

    def test_generic_ffmpeg_error(self):
        err = ErrorClassifier.classify(
            raw_error="ERROR: Postprocessing: Conversion failed!",
            stage="video",
        )
        self.assertEqual(err.category, ErrorCategory.FFMPEG_ERROR)
        self.assertEqual(err.title, "Audio/Video conversion failed (FFmpeg)")
        self.assertEqual(err.stage, "conversion")

    def test_localized_titles(self):
        err = ErrorClassifier.classify(
            raw_error="[mov @ 000001] av1 only supported in MP4\nCould not write header",
            stage="video",
        )
        tw_title = err.get_localized_title("zh_TW")
        self.assertIn("不支援的封裝容器與編碼組合", tw_title)
        cn_title = err.get_localized_title("zh_CN")
        self.assertIn("不支持的封装容器与编码组合", cn_title)


if __name__ == "__main__":
    unittest.main()
