"""
test_settings_auth_ui.py
Unit tests for the Authentication UI controls, validation, profile selection,
persistence, helper text, and safe backward-compatibility handling in SettingsDialog.
"""

import sys
import unittest
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication

from core.settings import SettingsManager
from core.i18n import I18nManager
from core.platform import PlatformRegistry, YouTubeAdapter
from gui.settings_dialog import SettingsDialog
from downloader.auth_checker import AuthStatusCode

# Ensure QApplication instance exists
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestSettingsAuthUI(unittest.TestCase):
    """Verifies SettingsDialog authentication UI components and state management."""

    def setUp(self):
        # Use an isolated temp settings file
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.tmp_dir.name) / "test_settings.json"
        self.settings_manager = SettingsManager(settings_path=self.settings_file)
        self.dialog = SettingsDialog(settings_manager=self.settings_manager)

    def tearDown(self):
        self.dialog.close()
        self.tmp_dir.cleanup()

    def test_visible_auth_choices_none_and_custom_file_only(self):
        """
        Verify that the visible authentication choices in the method selector
        are exactly None and Custom Cookie File. Browser Cookies must be hidden.
        """
        self.assertFalse(self.dialog.auth_none_rb.isHidden())
        self.assertFalse(self.dialog.auth_file_rb.isHidden())
        # Browser cookies radio button must be hidden, not displayed as a disabled control
        self.assertTrue(self.dialog.auth_browser_rb.isHidden())
        self.assertTrue(self.dialog.auth_browser_panel.isHidden())

        # Check visible radio buttons in method selector
        visible_radios = [
            rb for rb in (
                self.dialog.auth_none_rb,
                self.dialog.auth_browser_rb,
                self.dialog.auth_file_rb,
            )
            if not rb.isHidden()
        ]
        self.assertEqual(len(visible_radios), 2)
        self.assertIn(self.dialog.auth_none_rb, visible_radios)
        self.assertIn(self.dialog.auth_file_rb, visible_radios)

    def test_default_none_state(self):
        """Verify default initialization has 'None' selected and panels set accordingly."""
        self.assertTrue(self.dialog.auth_none_rb.isChecked())
        self.assertFalse(self.dialog.auth_browser_rb.isChecked())
        self.assertFalse(self.dialog.auth_file_rb.isChecked())

        self.assertFalse(self.dialog.auth_none_panel.isHidden())
        self.assertTrue(self.dialog.auth_browser_panel.isHidden())
        self.assertTrue(self.dialog.auth_file_panel.isHidden())

    def test_switch_to_custom_file_mode_and_validate(self):
        """Verify switching to custom file mode, helper text, and real-time validation."""
        self.dialog.auth_file_rb.click()

        self.assertEqual(self.settings_manager.get("auth_method"), "custom_file")
        self.assertTrue(self.dialog.auth_none_panel.isHidden())
        self.assertTrue(self.dialog.auth_browser_panel.isHidden())
        self.assertFalse(self.dialog.auth_file_panel.isHidden())

        # Helper text recommending Custom Cookie File must be displayed
        self.assertTrue(hasattr(self.dialog, "cookie_file_hint_lbl"))
        self.assertIn(
            "For authenticated downloads, export your browser cookies to a Netscape-format cookies.txt file and select it here.",
            self.dialog.cookie_file_hint_lbl.text(),
        )

        # Test empty file validation
        self.dialog.cookie_file_edit.setText("")
        self.assertIn("Not configured", self.dialog.cookie_file_status_lbl.text())

        # Test valid session cookie file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\tval123\n")
            tmp_cookie_path = f.name

        try:
            self.dialog.cookie_file_edit.setText(tmp_cookie_path)
            self.assertEqual(self.settings_manager.get("custom_cookie_file"), tmp_cookie_path)
            self.assertIn("Cookie file detected", self.dialog.cookie_file_status_lbl.text())

            # Test clear button does NOT delete file on disk
            self.dialog._clear_file_btn.click()
            self.assertEqual(self.dialog.cookie_file_edit.text(), "")
            self.assertEqual(self.settings_manager.get("custom_cookie_file"), "")
            self.assertTrue(Path(tmp_cookie_path).is_file(), "Clear button must NOT delete file on disk")
        finally:
            Path(tmp_cookie_path).unlink(missing_ok=True)

    def test_saved_browser_cookies_fallback_to_none_when_no_cookie_file(self):
        """
        Verify that previously saved Browser Cookies setting safely and predictably
        falls back to None when no valid cookie file exists, displaying explanatory text.
        """
        settings_path = Path(self.tmp_dir.name) / "browser_fallback_none.json"
        sm = SettingsManager(settings_path=settings_path)
        sm.set("auth_method", "browser")
        sm.set("browser_cookies", "chrome")
        sm.set("custom_cookie_file", "")

        dlg = SettingsDialog(settings_manager=sm)
        try:
            # Must show None selected
            self.assertTrue(dlg.auth_none_rb.isChecked())
            self.assertFalse(dlg.auth_file_rb.isChecked())
            self.assertFalse(dlg.auth_none_panel.isHidden())
            self.assertTrue(dlg.auth_file_panel.isHidden())
            self.assertTrue(dlg.auth_browser_panel.isHidden())

            # Fallback explanatory notice must be visible (not hidden)
            self.assertFalse(dlg.auth_fallback_notice_lbl.isHidden())
            self.assertIn("Browser cookie extraction is temporarily unavailable", dlg.auth_fallback_notice_lbl.text())
            self.assertIn("Authentication is set to None", dlg.auth_fallback_notice_lbl.text())

            # Once user actively selects a method, notice should hide
            dlg.auth_file_rb.click()
            self.assertTrue(dlg.auth_fallback_notice_lbl.isHidden())
        finally:
            dlg.close()

    def test_saved_browser_cookies_fallback_to_custom_file_when_valid_file_exists(self):
        """
        Verify that previously saved Browser Cookies setting safely falls back
        to Custom Cookie File when a valid cookie file exists, with explanatory text.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\tval123\n")
            tmp_cookie_path = f.name

        try:
            settings_path = Path(self.tmp_dir.name) / "browser_fallback_file.json"
            sm = SettingsManager(settings_path=settings_path)
            sm.set("auth_method", "browser")
            sm.set("browser_cookies", "chrome")
            sm.set("custom_cookie_file", tmp_cookie_path)

            dlg = SettingsDialog(settings_manager=sm)
            try:
                # Must show Custom Cookie File selected
                self.assertTrue(dlg.auth_file_rb.isChecked())
                self.assertFalse(dlg.auth_none_rb.isChecked())
                self.assertFalse(dlg.auth_file_panel.isHidden())
                self.assertTrue(dlg.auth_none_panel.isHidden())
                self.assertTrue(dlg.auth_browser_panel.isHidden())

                # Fallback explanatory notice must be visible (not hidden)
                self.assertFalse(dlg.auth_fallback_notice_lbl.isHidden())
                self.assertIn("Switched to your configured Custom Cookie File", dlg.auth_fallback_notice_lbl.text())
            finally:
                dlg.close()
        finally:
            Path(tmp_cookie_path).unlink(missing_ok=True)

    def test_browser_cookies_backend_code_still_available(self):
        """
        Verify backend browser cookies capabilities remain intact for future reactivation:
        profile resolution, browser combo options, and underlying auth config generation.
        """
        # Browser profile resolution still works
        self.assertGreaterEqual(self.dialog.browser_combo.count(), 6)
        self.dialog._populate_profiles_for_browser("chrome")
        self.assertGreaterEqual(self.dialog.profile_combo.count(), 1)

        # Programmatic backend invocation of browser mode still works
        self.dialog._on_auth_method_button_clicked(1)
        self.assertEqual(self.settings_manager.get("auth_method"), "browser")

        # YouTube adapter backend resolution still supports browser cookies
        adapter = YouTubeAdapter()
        auth = adapter.get_auth_config(settings={"auth_method": "browser", "browser_cookies": "chrome"})
        self.assertTrue(auth.is_active)
        self.assertEqual(auth.auth_method, "browser")
        self.assertEqual(auth.browser_name, "chrome")

    def test_auth_platform_dropdown_douyin_greyed_out_and_unselectable(self):
        """
        Verify that in the authentication settings platform dropdown,
        Douyin is greyed out and unselectable while temporarily frozen.
        """
        combo = self.dialog.auth_platform_combo
        model = combo.model()
        yt_idx = combo.findData("youtube")
        dy_idx = combo.findData("douyin")

        self.assertGreaterEqual(yt_idx, 0)
        self.assertGreaterEqual(dy_idx, 0)

        # YouTube item must be enabled and selectable
        yt_item = model.item(yt_idx)
        self.assertTrue(yt_item.isEnabled())
        self.assertTrue(yt_item.isSelectable())

        # Douyin item must be disabled, unselectable, greyed out, and have tooltip
        dy_item = model.item(dy_idx)
        self.assertFalse(dy_item.isEnabled())
        self.assertFalse(dy_item.isSelectable())
        self.assertTrue(bool(dy_item.toolTip()))

        # If a change event targets Douyin, it must revert to YouTube
        combo.setCurrentIndex(dy_idx)
        self.assertEqual(combo.currentData(), "youtube")
        self.assertEqual(self.dialog._current_auth_platform, "youtube")

    def test_douyin_auth_ui_hides_browser_cookies(self):
        """Verify Douyin auth settings in SettingsDialog also hide browser cookies when platform is enabled."""
        PlatformRegistry.set_platform_available("douyin", True)
        try:
            self.dialog._update_auth_platform_combo_availability()
            idx = self.dialog.auth_platform_combo.findData("douyin")
            if idx >= 0:
                self.dialog.auth_platform_combo.setCurrentIndex(idx)
                self.dialog._on_auth_platform_changed(idx)

                # Both radio buttons visible are None and Custom Cookie File
                self.assertFalse(self.dialog.auth_none_rb.isHidden())
                self.assertFalse(self.dialog.auth_file_rb.isHidden())
                self.assertTrue(self.dialog.auth_browser_rb.isHidden())
                self.assertTrue(self.dialog.auth_browser_panel.isHidden())
        finally:
            PlatformRegistry.reset_availability_overrides()
            self.dialog._update_auth_platform_combo_availability()

    def test_retranslation_bilingual(self):
        """Verify dynamic retranslation between English and Chinese."""
        I18nManager.set_language("zh_CN")
        self.dialog.retranslate_ui()
        self.assertIn("登录方式", self.dialog.auth_method_lbl.text())
        self.assertIn("不使用", self.dialog.auth_none_rb.text())
        self.assertIn("Cookie 文件", self.dialog.auth_file_rb.text())
        self.assertIn("需要登录验证时", self.dialog.cookie_file_hint_lbl.text())

        I18nManager.set_language("en")
        self.dialog.retranslate_ui()
        self.assertIn("Authentication Method", self.dialog.auth_method_lbl.text())
        self.assertIn("None", self.dialog.auth_none_rb.text())
        self.assertIn("Custom Cookie File", self.dialog.auth_file_rb.text())
        self.assertIn("For authenticated downloads", self.dialog.cookie_file_hint_lbl.text())


if __name__ == "__main__":
    unittest.main()
