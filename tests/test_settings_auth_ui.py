"""
test_settings_auth_ui.py
Unit tests for the YouTube Authentication UI controls, validation, profile selection,
and persistence in SettingsDialog.
"""

import sys
import unittest
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication

from core.settings import SettingsManager
from core.i18n import I18nManager
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

    def test_default_none_state(self):
        """Verify default initialization has 'None' selected and panels set accordingly."""
        self.assertTrue(self.dialog.auth_none_rb.isChecked())
        self.assertFalse(self.dialog.auth_browser_rb.isChecked())
        self.assertFalse(self.dialog.auth_file_rb.isChecked())

        self.assertFalse(self.dialog.auth_none_panel.isHidden())
        self.assertTrue(self.dialog.auth_browser_panel.isHidden())
        self.assertTrue(self.dialog.auth_file_panel.isHidden())

    def test_switch_to_browser_mode(self):
        """Verify switching to browser mode populates profiles and updates panels."""
        self.dialog.auth_browser_rb.click()

        self.assertEqual(self.settings_manager.get("auth_method"), "browser")
        self.assertTrue(self.dialog.auth_none_panel.isHidden())
        self.assertFalse(self.dialog.auth_browser_panel.isHidden())
        self.assertTrue(self.dialog.auth_file_panel.isHidden())

        # Profiles should be populated
        self.assertGreaterEqual(self.dialog.profile_combo.count(), 1)
        self.assertEqual(self.dialog.profile_combo.currentText(), "Default")

        # Switching browser updates settings
        edge_idx = self.dialog.browser_combo.findData("edge")
        if edge_idx >= 0:
            self.dialog.browser_combo.setCurrentIndex(edge_idx)
            self.assertEqual(self.settings_manager.get("browser_cookies"), "edge")

    def test_switch_to_custom_file_mode_and_validate(self):
        """Verify switching to custom file mode and real-time validation."""
        self.dialog.auth_file_rb.click()

        self.assertEqual(self.settings_manager.get("auth_method"), "custom_file")
        self.assertTrue(self.dialog.auth_none_panel.isHidden())
        self.assertTrue(self.dialog.auth_browser_panel.isHidden())
        self.assertFalse(self.dialog.auth_file_panel.isHidden())

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

    def test_retranslation_bilingual(self):
        """Verify dynamic retranslation between English and Chinese."""
        I18nManager.set_language("zh_CN")
        self.dialog.retranslate_ui()
        self.assertIn("登录方式", self.dialog.auth_method_lbl.text())
        self.assertIn("不使用", self.dialog.auth_none_rb.text())
        self.assertIn("浏览器 Cookie", self.dialog.auth_browser_rb.text())
        self.assertIn("Cookie 文件", self.dialog.auth_file_rb.text())

        I18nManager.set_language("en")
        self.dialog.retranslate_ui()
        self.assertIn("Authentication Method", self.dialog.auth_method_lbl.text())
        self.assertIn("None", self.dialog.auth_none_rb.text())
        self.assertIn("Browser Cookies", self.dialog.auth_browser_rb.text())
        self.assertIn("Custom Cookie File", self.dialog.auth_file_rb.text())


if __name__ == "__main__":
    unittest.main()
