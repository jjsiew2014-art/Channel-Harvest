"""
test_subprocess_utf8_encoding.py
Unit tests verifying that subprocess calls across Channel Harvest (including ffmpeg,
ffprobe, Deno, and gallery-dl) safely decode UTF-8 text streams on Windows without
crashing from UnicodeDecodeError (e.g. 'charmap' codec can't decode byte 0x9d).
"""

import os
import sys
import unittest
import subprocess
from pathlib import Path

from core.paths import patch_subprocess_utf8_default, setup_runtime_environment
from downloader.cover_art_manager import CoverArtManager
from downloader.ffmpeg_checker import FFmpegChecker


class TestSubprocessUtf8Encoding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patch_subprocess_utf8_default()

    def test_01_subprocess_popen_patched_utf8_default(self):
        """Verify that subprocess.Popen defaults to UTF-8 with errors='replace' in text mode."""
        # A child process that writes byte 0x9d (right double curly quote in UTF-8: \xe2\x80\x9d) to stderr
        test_script = (
            "import sys\n"
            "sys.stderr.buffer.write(b'start ' + '\u201d'.encode('utf-8') + b' end\\n')\n"
            "sys.stdout.buffer.write(b'title: ' + '\u4e13\u8f91\u5c01\u9762 \u2014 \u6d4b\u8bd5'.encode('utf-8') + b'\\n')\n"
        )
        cmd = [sys.executable, "-c", test_script]

        # Call subprocess.run with text=True and WITHOUT passing encoding or errors
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("start", proc.stderr)
        self.assertIn("end", proc.stderr)
        self.assertIn("title:", proc.stdout)
        self.assertIn("专辑封面", proc.stdout)

    def test_02_ffmpeg_metadata_with_curly_quotes_and_unicode(self):
        """Verify real FFmpeg execution with metadata containing 0x9d (smart quotes) and Unicode."""
        is_avail, ffmpeg_bin, ver, msg = FFmpegChecker.detect()
        if not is_avail or not ffmpeg_bin or not Path(ffmpeg_bin).is_file():
            self.skipTest("ffmpeg binary not available in local test environment")

        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            in_audio = tmp_path / "input.mp3"

            # 1. Synthesize 0.3s test mp3
            synth_cmd = [
                str(ffmpeg_bin), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                "-c:a", "libmp3lame", str(in_audio)
            ]
            r = subprocess.run(synth_cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)

            # 2. Embed metadata with smart quotes (0x9d) and full Unicode
            tricky_metadata = {
                "title": "Song with “Smart Quotes” & 🎵 Emoji",
                "artist": "Artist — em-dash & ‘single quote’",
                "album": "Album “Title” 特别专辑 (2026)",
                "date": "2026",
            }
            succ = CoverArtManager.embed_metadata(
                media_path=in_audio,
                metadata=tricky_metadata,
                ffmpeg_location=str(Path(ffmpeg_bin).parent),
            )
            self.assertTrue(succ, "Metadata embedding failed")

            # 3. Verify ffprobe inspects cleanly without charmap decoding crash
            ffprobe_bin = CoverArtManager._resolve_ffprobe_executable(str(Path(ffmpeg_bin).parent))
            probe_cmd = [
                str(ffprobe_bin), "-v", "error", "-show_entries",
                "format_tags=title,artist,album", "-of", "default=noprint_wrappers=1",
                str(in_audio)
            ]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            self.assertEqual(probe_res.returncode, 0)
            self.assertIn("Smart Quotes", probe_res.stdout)


if __name__ == "__main__":
    unittest.main()
