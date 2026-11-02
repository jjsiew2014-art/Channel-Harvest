"""
test_path_sanitization_and_budget.py
Comprehensive test suite verifying Windows filename sanitization,
length budgeting, path validation, and cross-platform / sidecar consistency
in Channel Harvest.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.error_classifier import ErrorCategory, ErrorClassifier
from core.models import DownloadMode, DownloadSettings, VideoItem
from core.paths import (
    DEFAULT_SAFE_TITLE_LENGTH,
    MAX_COMPONENT_LENGTH,
    MAX_WINDOWS_PATH,
    WINDOWS_ILLEGAL_CHAR_REGEX,
    WINDOWS_RESERVED_NAMES,
    calculate_safe_stem_length,
    resolve_media_filename,
    resolve_video_output_dir,
    resolve_video_outtmpl,
    sanitize_filename,
    sanitize_path_component,
    validate_output_path,
)


class TestFilenameSanitization(unittest.TestCase):
    """Unit tests for centralized sanitize_filename function."""

    def test_illegal_characters_replaced(self):
        """Verify Windows illegal characters (< > : \" / \\ | ? *) are converted to underscores."""
        raw = 'Title with <angle> :colon "quotes" /slash \\backslash |pipe ?question *asterisk'
        cleaned = sanitize_filename(raw)
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)
        self.assertNotIn(":", cleaned)
        self.assertNotIn('"', cleaned)
        self.assertNotIn("/", cleaned)
        self.assertNotIn("\\", cleaned)
        self.assertNotIn("|", cleaned)
        self.assertNotIn("?", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertFalse(WINDOWS_ILLEGAL_CHAR_REGEX.search(cleaned))

    def test_control_characters_cleaned(self):
        """Verify ASCII control characters (0x00-0x1F, 0x7F-0x9F, \\r, \\n, \\t) are eliminated."""
        raw = "Line1\r\nLine2\tTabbed\x00Null\x1fUnitSep\x7fDel"
        cleaned = sanitize_filename(raw)
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertNotIn("\t", cleaned)
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("\x1f", cleaned)
        self.assertNotIn("\x7f", cleaned)
        self.assertFalse(WINDOWS_ILLEGAL_CHAR_REGEX.search(cleaned))

    def test_trailing_periods_and_spaces_stripped(self):
        """Verify Windows trailing dots and whitespace are stripped."""
        cases = [
            ("Video Title. . .", "Video Title"),
            ("   Leading and Trailing Spaces   ", "Leading and Trailing Spaces"),
            ("Ending with period.", "Ending with period"),
            ("Multiple... Dots...   ", "Multiple... Dots"),
        ]
        for raw, expected in cases:
            self.assertEqual(sanitize_filename(raw), expected)

    def test_windows_reserved_names_guarded(self):
        """Verify Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) are de-reserved."""
        reserved_stems = ["CON", "con", "Prn", "AUX", "nul", "COM1", "com9", "LPT1", "lpt9"]
        for res in reserved_stems:
            sanitized = sanitize_filename(res)
            # Must not match any reserved name exactly
            self.assertNotIn(sanitized.upper(), WINDOWS_RESERVED_NAMES)
            self.assertTrue(sanitized.startswith("_") and sanitized.endswith("_"))

        # Reserved names with extensions
        res_ext = ["con.mp4", "AUX.txt", "NUL.tar.gz", "com1.mov"]
        for res in res_ext:
            sanitized = sanitize_filename(res)
            base = sanitized.split(".")[0].upper()
            self.assertNotIn(base, WINDOWS_RESERVED_NAMES)

        # Names that start with reserved names but are different words must remain readable
        non_reserved = ["Constantine", "auxiliary", "nullify", "computer"]
        for name in non_reserved:
            sanitized = sanitize_filename(name)
            self.assertIn(name.lower(), sanitized.lower())

    def test_unicode_preservation(self):
        """Verify meaningful Unicode characters (CJK, Japanese, Korean, Malay, emojis, accents) are preserved."""
        cases = [
            "【官方双语】这是高质量中文视频 (2026)",
            "日本語タイトル：鬼滅の刃 - 全集中",
            "한국어 비디오 제목 입니다",
            "Video Pengembaraan Malaysia - Episod 1",
            "Highlights 🎬 & Best Moments 🔥 🚀 (1080p)",
            "Café & Résumé - Pâtisserie Française",
        ]
        for raw in cases:
            cleaned = sanitize_filename(raw)
            # Verify representative characters survived
            if "官方双语" in raw:
                self.assertIn("官方双语", cleaned)
            if "日本語" in raw:
                self.assertIn("日本語", cleaned)
            if "한국어" in raw:
                self.assertIn("한국어", cleaned)
            if "🎬" in raw:
                self.assertIn("🎬", cleaned)
            if "Café" in raw:
                self.assertIn("Café", cleaned)

    def test_fallback_for_empty_title(self):
        """Verify safe fallback when input is empty or contains only invalid characters."""
        self.assertEqual(sanitize_filename(""), "Untitled")
        self.assertEqual(sanitize_filename("   "), "Untitled")
        self.assertEqual(sanitize_filename("::: ??? ***"), "Untitled")
        self.assertEqual(sanitize_filename("...", fallback="video_12345"), "video_12345")

    def test_idempotence(self):
        """Verify sanitize_filename is deterministic and idempotent."""
        inputs = [
            "Normal Video",
            "CON",
            "Title with <angle> & :colon",
            "中文视频 🚀",
            "   Multiple... spaces... and dots...   ",
        ]
        for inp in inputs:
            once = sanitize_filename(inp)
            twice = sanitize_filename(once)
            self.assertEqual(once, twice)


class TestLengthBudgetAndLimits(unittest.TestCase):
    """Unit tests for Windows length budgeting and limits."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ch_path_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extremely_long_title_bounded_safely(self):
        """Verify Facebook-length title (300+ characters) is safely bounded."""
        long_fb_title = (
            "Breaking News: An extraordinarily long Facebook post description that spans multiple sentences "
            "and discusses various important community updates in great detail with plenty of adjectives, "
            "extra commentary, and emojis 🔥 🚀 explaining why everyone should pay close attention to this video "
            "and follow the page for future updates!" * 3
        )
        self.assertGreater(len(long_fb_title), 300)

        stem = resolve_media_filename(
            title=long_fb_title,
            video_id="1668739328296552",
            ext="mov",
            include_video_id=True,
            target_dir=self.temp_dir,
        )

        # Single filename component must be strictly <= 255 characters
        self.assertLessEqual(len(stem), MAX_COMPONENT_LENGTH)

        # Full path must be strictly <= 260 characters
        full_path = self.temp_dir / stem
        self.assertLessEqual(len(str(full_path.resolve())), MAX_WINDOWS_PATH)

    def test_single_component_ntfs_ceiling_with_format_suffixes(self):
        """Verify that even when yt-dlp appends format suffixes (.f1139573745394401v.mp4.part),
        the total single filename component never exceeds 255 characters."""
        very_long_title = "A" * 500
        safe_stem = resolve_media_filename(
            title=very_long_title,
            video_id="1668739328296552",
            include_video_id=True,
            target_dir=self.temp_dir,
        )

        # Simulated yt-dlp temporary format filename
        format_suffix = ".f1139573745394401v.mp4.part"
        simulated_temp_filename = f"{safe_stem}{format_suffix}"

        self.assertLessEqual(len(simulated_temp_filename), MAX_COMPONENT_LENGTH)

    def test_deep_directory_path_budget_calculation(self):
        """Verify calculate_safe_stem_length adjusts downwards when target_dir is deep."""
        shallow_dir = Path("C:/Downloads")
        deep_dir = Path("C:/Users/Admin/Documents/VeryLongChannelNameSubfolder/DeepNestedFolderLevel/TargetFolder")

        shallow_budget = calculate_safe_stem_length(shallow_dir, ext="mov")
        deep_budget = calculate_safe_stem_length(deep_dir, ext="mov")

        self.assertLessEqual(deep_budget, shallow_budget)
        self.assertGreaterEqual(deep_budget, 30)  # Safe floor


class TestSidecarAndOutputTemplateConsistency(unittest.TestCase):
    """Verify media files and all sidecars share identical stems and outtmpl patterns."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ch_sidecar_test_"))
        self.title = "Facebook Video: Exploring Modern Multi-Platform Architecture & Design | Part 1"
        self.video_id = "1668739328296552"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sidecar_stem_consistency(self):
        """Verify video, audio, thumbnail, subtitle, metadata, description, and chapters share identical stem."""
        for inc_id in (True, False):
            video_file = resolve_media_filename(self.title, self.video_id, ext="mov", include_video_id=inc_id, target_dir=self.temp_dir)
            audio_file = resolve_media_filename(self.title, self.video_id, ext="m4a", include_video_id=inc_id, target_dir=self.temp_dir)
            thumb_file = resolve_media_filename(self.title, self.video_id, ext="jpg", include_video_id=inc_id, target_dir=self.temp_dir)
            sub_file = resolve_media_filename(self.title, self.video_id, ext="srt", include_video_id=inc_id, target_dir=self.temp_dir)
            meta_file = resolve_media_filename(self.title, self.video_id, ext="metadata.txt", include_video_id=inc_id, target_dir=self.temp_dir)
            desc_file = resolve_media_filename(self.title, self.video_id, ext="description", include_video_id=inc_id, target_dir=self.temp_dir)
            chap_file = resolve_media_filename(self.title, self.video_id, ext="chapters.txt", include_video_id=inc_id, target_dir=self.temp_dir)

            stem_raw = resolve_media_filename(self.title, self.video_id, include_video_id=inc_id, target_dir=self.temp_dir)

            self.assertEqual(video_file, f"{stem_raw}.mov")
            self.assertEqual(audio_file, f"{stem_raw}.m4a")
            self.assertEqual(thumb_file, f"{stem_raw}.jpg")
            self.assertEqual(sub_file, f"{stem_raw}.srt")
            self.assertEqual(meta_file, f"{stem_raw}.metadata.txt")
            self.assertEqual(desc_file, f"{stem_raw}.description")
            self.assertEqual(chap_file, f"{stem_raw}.chapters.txt")

    def test_title_sanitizer_postprocessor_pre_process(self):
        """Verify TitleSanitizerPP pre-processes yt-dlp info_dict title so filenames are safe and bounded."""
        import yt_dlp
        from downloader.ytdlp_engine import TitleSanitizerPP
        opts = {
            "outtmpl": resolve_video_outtmpl(self.temp_dir, include_video_id=True),
            "simulate": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            pp = TitleSanitizerPP(downloader=ydl, target_dir=self.temp_dir, include_video_id=True)
            info = {"id": self.video_id, "title": self.title, "ext": "mov"}
            pp.run(info)
            prepared = ydl.prepare_filename(info)
            expected_name = resolve_media_filename(self.title, self.video_id, ext="mov", include_video_id=True, target_dir=self.temp_dir)
            self.assertEqual(Path(prepared).name, expected_name)

    def test_resolve_video_outtmpl_backward_compatibility(self):
        """Verify resolve_video_outtmpl without title retains legacy generic pattern."""
        legacy_outtmpl = resolve_video_outtmpl(self.temp_dir, include_video_id=True)
        self.assertIn("%(title)s [%(id)s].%(ext)s", legacy_outtmpl)

        legacy_no_id = resolve_video_outtmpl(self.temp_dir, include_video_id=False)
        self.assertIn("%(title)s.%(ext)s", legacy_no_id)


class TestRealWindowsFileSystemOperations(unittest.TestCase):
    """Verifies that actual file and folder creation operations succeed on Windows without Errno 22."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ch_fs_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_file_creation_with_long_facebook_title(self):
        """Verify real disk file creation succeeds with a 400+ character Facebook title containing special characters."""
        fb_title = (
            "🔥 [LIVE] Facebook Community Video: Special Report <2026> - Discussion: How to manage "
            "files, paths, and long strings on Windows with 100% reliability? | Questions & Answers * Must Watch! "
            "This description continues on and on to simulate extremely long real-world Facebook post captions "
            "that previously caused OSError [Errno 22] Invalid argument in yt-dlp downloads! 🚀"
        )
        video_id = "1668739328296552"

        # 1. Directory creation
        video_dir = resolve_video_output_dir(
            base_download_dir=self.temp_dir,
            channel_title="Facebook Channel * Official",
            create_channel_folder=True,
            video_title=fb_title,
            video_id=video_id,
            create_individual_video_folders=True,
        )
        video_dir.mkdir(parents=True, exist_ok=True)
        self.assertTrue(video_dir.is_dir())

        # 2. File creation for media and sidecars
        extensions = [
            "mov",
            "m4a",
            "jpg",
            "srt",
            "metadata.txt",
            "description",
            "chapters.txt",
            "f1139573745394401v.mp4.part",  # yt-dlp temp format
        ]
        created_files = []
        for ext in extensions:
            filename = resolve_media_filename(
                title=fb_title,
                video_id=video_id,
                ext=ext,
                include_video_id=True,
                target_dir=video_dir,
            )
            file_path = video_dir / filename
            # This write_text must NOT raise OSError: [Errno 22] Invalid argument
            file_path.write_text(f"dummy content for {ext}", encoding="utf-8")
            self.assertTrue(file_path.is_file())
            created_files.append(file_path)

        self.assertEqual(len(created_files), len(extensions))

    def test_validate_output_path_pre_download_check(self):
        """Verify validate_output_path accurately accepts valid paths and rejects invalid ones."""
        # 1. Valid path
        valid_dir = self.temp_dir / "valid_folder"
        is_val, err = validate_output_path(valid_dir, filename="my_safe_video [12345].mov")
        self.assertTrue(is_val)
        self.assertIsNone(err)

        # 2. Invalid filename with reserved name
        is_val_con, err_con = validate_output_path(valid_dir, filename="CON.txt")
        self.assertFalse(is_val_con)
        self.assertIn("reserved", err_con.lower())

        # 3. Invalid filename with illegal char
        is_val_char, err_char = validate_output_path(valid_dir, filename="invalid:char.mov")
        self.assertFalse(is_val_char)
        self.assertIn("invalid", err_char.lower())

        # 4. ErrorClassifier categorization
        classified = ErrorClassifier.classify(
            raw_error=err_con or "Invalid argument",
            component="yt-dlp",
            stage="path_validation",
        )
        self.assertEqual(classified.category, ErrorCategory.FILE_SYSTEM_ERROR)


if __name__ == "__main__":
    unittest.main()
