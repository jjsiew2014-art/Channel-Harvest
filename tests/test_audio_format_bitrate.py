"""
test_audio_format_bitrate.py
Unit tests for platform audio format and bitrate/quality options mapping in Channel Harvest.
Verifies format-specific options (WAV PCM depth, FLAC compression, OPUS 160 kbps, MP3 kbps),
FFmpeg postprocessor argument generation, localization, and GUI combo synchronization.
"""

import unittest
import sys
from PySide6.QtWidgets import QApplication

from core.models import DownloadSettings
from core.i18n import I18nManager
from downloader.format_selector import FormatSelector


class TestAudioFormatBitrateMapping(unittest.TestCase):
    """Tests for format-specific audio bitrate and quality options in FormatSelector."""

    def test_audio_formats_list(self):
        self.assertEqual(FormatSelector.AUDIO_FORMATS[0], "WAV")
        self.assertIn("WAV", FormatSelector.AUDIO_FORMATS)
        self.assertIn("FLAC", FormatSelector.AUDIO_FORMATS)
        self.assertIn("MP3", FormatSelector.AUDIO_FORMATS)
        self.assertIn("M4A", FormatSelector.AUDIO_FORMATS)
        self.assertIn("AAC", FormatSelector.AUDIO_FORMATS)
        self.assertIn("OPUS", FormatSelector.AUDIO_FORMATS)

    def test_default_audio_format_is_wav(self):
        from core.settings import SettingsManager
        self.assertEqual(SettingsManager.DEFAULT_SETTINGS.get("audio_format"), "WAV")
        self.assertEqual(DownloadSettings().audio_format, "WAV")
        # Build spec with default empty settings
        _, ext, _ = FormatSelector.build_audio_format_spec(DownloadSettings(audio_format=""))
        self.assertEqual(ext, "wav")

    def test_wav_options_non_kbps(self):
        wav_opts = FormatSelector.get_audio_bitrate_options("WAV")
        self.assertIn("Best Available", wav_opts)
        self.assertIn("16-bit PCM", wav_opts)
        self.assertIn("24-bit PCM", wav_opts)
        self.assertIn("32-bit Float", wav_opts)
        # Ensure no kbps options are present in WAV
        for opt in wav_opts:
            self.assertNotIn("kbps", opt)

    def test_flac_options_non_kbps(self):
        flac_opts = FormatSelector.get_audio_bitrate_options("FLAC")
        self.assertIn("Best Available", flac_opts)
        self.assertIn("Level 8 (Highest)", flac_opts)
        self.assertIn("Level 5 (Default)", flac_opts)
        self.assertIn("Level 0 (Fastest)", flac_opts)
        self.assertIn("24-bit", flac_opts)
        self.assertIn("16-bit", flac_opts)
        # Ensure no lossy kbps options are present in FLAC
        for opt in flac_opts:
            self.assertNotIn("kbps", opt)

    def test_opus_options_include_160k(self):
        opus_opts = FormatSelector.get_audio_bitrate_options("OPUS")
        self.assertIn("160 kbps", opus_opts)
        self.assertIn("256 kbps", opus_opts)
        self.assertIn("128 kbps", opus_opts)
        self.assertIn("Best Available", opus_opts)

    def test_mp3_and_aac_options(self):
        mp3_opts = FormatSelector.get_audio_bitrate_options("MP3")
        self.assertIn("320 kbps", mp3_opts)
        self.assertIn("128 kbps", mp3_opts)

        aac_opts = FormatSelector.get_audio_bitrate_options("AAC")
        self.assertIn("160 kbps", aac_opts)
        self.assertIn("256 kbps", aac_opts)

    def test_wav_postprocessor_args(self):
        s16 = DownloadSettings(audio_format="WAV", audio_bitrate="16-bit PCM")
        args16 = FormatSelector.get_audio_postprocessor_args(s16)
        self.assertEqual(args16, {"extractaudio": ["-c:a", "pcm_s16le"]})

        s24 = DownloadSettings(audio_format="WAV", audio_bitrate="24-bit PCM")
        args24 = FormatSelector.get_audio_postprocessor_args(s24)
        self.assertEqual(args24, {"extractaudio": ["-c:a", "pcm_s24le"]})

        sf = DownloadSettings(audio_format="WAV", audio_bitrate="32-bit Float")
        argsf = FormatSelector.get_audio_postprocessor_args(sf)
        self.assertEqual(argsf, {"extractaudio": ["-c:a", "pcm_f32le"]})

        s_auto = DownloadSettings(audio_format="WAV", audio_bitrate="Best Available")
        self.assertEqual(FormatSelector.get_audio_postprocessor_args(s_auto), {})

    def test_flac_postprocessor_args(self):
        s_lvl8 = DownloadSettings(audio_format="FLAC", audio_bitrate="Level 8 (Highest)")
        args8 = FormatSelector.get_audio_postprocessor_args(s_lvl8)
        self.assertEqual(args8, {"extractaudio": ["-compression_level", "8"]})

        s_24 = DownloadSettings(audio_format="FLAC", audio_bitrate="24-bit")
        args24 = FormatSelector.get_audio_postprocessor_args(s_24)
        self.assertEqual(args24, {"extractaudio": ["-sample_fmt", "s32"]})

    def test_lossy_postprocessor_args_empty_and_quality_set(self):
        s_mp3 = DownloadSettings(audio_format="MP3", audio_bitrate="320 kbps")
        # Postprocessor args should be empty since preferredquality is handled natively
        self.assertEqual(FormatSelector.get_audio_postprocessor_args(s_mp3), {})
        _, _, pps = FormatSelector.build_audio_format_spec(s_mp3)
        self.assertEqual(pps[0]["preferredquality"], "320")

        s_opus = DownloadSettings(audio_format="OPUS", audio_bitrate="160 kbps")
        _, _, pps_opus = FormatSelector.build_audio_format_spec(s_opus)
        self.assertEqual(pps_opus[0]["preferredquality"], "160")

    def test_mp3_best_available_maps_to_320kbps(self):
        # When MP3 is selected and audio_bitrate is 'Best Available', 320 kbps must be chosen
        s_mp3_best = DownloadSettings(audio_format="MP3", audio_bitrate="Best Available")
        _, _, pps_mp3 = FormatSelector.build_audio_format_spec(s_mp3_best)
        self.assertEqual(pps_mp3[0]["preferredquality"], "320")

        # When audio_bitrate is empty / None for MP3
        s_mp3_none = DownloadSettings(audio_format="MP3", audio_bitrate="")
        _, _, pps_none = FormatSelector.build_audio_format_spec(s_mp3_none)
        self.assertEqual(pps_none[0]["preferredquality"], "320")

        # Explicit lower bitrate choice for MP3 remains intact
        s_mp3_192 = DownloadSettings(audio_format="MP3", audio_bitrate="192 kbps")
        _, _, pps_192 = FormatSelector.build_audio_format_spec(s_mp3_192)
        self.assertEqual(pps_192[0]["preferredquality"], "192")

    def test_other_audio_formats_best_available_preserved(self):
        # Other audio formats must keep their native behavior without preferredquality
        for fmt in ("WAV", "FLAC", "M4A", "AAC", "OPUS"):
            s_best = DownloadSettings(audio_format=fmt, audio_bitrate="Best Available")
            _, ext, pps = FormatSelector.build_audio_format_spec(s_best)
            self.assertEqual(ext, fmt.lower())
            self.assertNotIn("preferredquality", pps[0])


class TestAudioBitrateLocalization(unittest.TestCase):
    """Tests for i18n localization of audio bitrate and quality options."""

    def tearDown(self):
        I18nManager.set_language(I18nManager.LANG_EN)

    def test_english_labels(self):
        I18nManager.set_language("en")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Best Available"), "Best Available")
        self.assertEqual(I18nManager.get_audio_bitrate_label("16-bit PCM"), "16-bit PCM")
        self.assertEqual(I18nManager.get_audio_bitrate_label("24-bit PCM"), "24-bit PCM")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Level 8 (Highest)"), "Level 8 (Highest)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("320 kbps"), "320 kbps")

    def test_simplified_chinese_labels(self):
        I18nManager.set_language("zh_CN")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Best Available"), "最高音质")
        self.assertEqual(I18nManager.get_audio_bitrate_label("16-bit PCM"), "16位 PCM (CD音质)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("24-bit PCM"), "24位 PCM (录音室母带)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Level 8 (Highest)"), "8级 (最高压缩)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("320 kbps"), "320 kbps")

    def test_traditional_chinese_labels(self):
        I18nManager.set_language("zh_TW")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Best Available"), "最高音質")
        self.assertEqual(I18nManager.get_audio_bitrate_label("16-bit PCM"), "16位元 PCM (CD音質)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("24-bit PCM"), "24位元 PCM (錄音室母帶)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("Level 8 (Highest)"), "8級 (最高壓縮)")
        self.assertEqual(I18nManager.get_audio_bitrate_label("320 kbps"), "320 kbps")


class TestMainWindowAudioComboInteraction(unittest.TestCase):
    """Tests for GUI synchronization between audio format and audio bitrate dropdowns."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_dynamic_format_switching_in_gui(self):
        from gui.main_window import MainWindow
        from core.settings import SettingsManager
        orig_afmt = SettingsManager().get("audio_format", "WAV")
        orig_mode = SettingsManager().get("download_mode", "Video Only")
        try:
            SettingsManager().set("download_mode", "Video Only")
            window = MainWindow()

            # Switch to WAV
            window.audio_format_combo.setCurrentText("WAV")
            wav_items = [window.audio_bitrate_combo.itemData(i) for i in range(window.audio_bitrate_combo.count())]
            self.assertIn("16-bit PCM", wav_items)
            self.assertIn("24-bit PCM", wav_items)
            for it in wav_items:
                self.assertNotIn("kbps", it)

            # Switch to MP3
            window.audio_format_combo.setCurrentText("MP3")
            mp3_items = [window.audio_bitrate_combo.itemData(i) for i in range(window.audio_bitrate_combo.count())]
            self.assertIn("320 kbps", mp3_items)
            self.assertIn("128 kbps", mp3_items)

            # Switch to FLAC
            window.audio_format_combo.setCurrentText("FLAC")
            flac_items = [window.audio_bitrate_combo.itemData(i) for i in range(window.audio_bitrate_combo.count())]
            self.assertIn("Level 8 (Highest)", flac_items)
            self.assertIn("Level 5 (Default)", flac_items)
            for it in flac_items:
                self.assertNotIn("kbps", it)

            # Switch to OPUS
            window.audio_format_combo.setCurrentText("OPUS")
            opus_items = [window.audio_bitrate_combo.itemData(i) for i in range(window.audio_bitrate_combo.count())]
            self.assertIn("160 kbps", opus_items)

            # Verify Mode dropdown reordering and default Video Only selection
            from core.models import DownloadMode
            expected_modes = [
                DownloadMode.VIDEO_AND_AUDIO,
                DownloadMode.VIDEO_ONLY,
                DownloadMode.AUDIO_ONLY,
                DownloadMode.IMAGE_ONLY,
                DownloadMode.ASSETS_ONLY,
            ]
            actual_modes = [window.mode_combo.itemData(i) for i in range(window.mode_combo.count())]
            self.assertEqual(actual_modes, expected_modes)
            # Default selection when settings are freshly loaded or defaulted
            self.assertEqual(window.mode_combo.currentData(), DownloadMode.VIDEO_ONLY)

            window.close()
        finally:
            SettingsManager().set("audio_format", orig_afmt)
            SettingsManager().set("download_mode", orig_mode)


if __name__ == "__main__":
    unittest.main()
