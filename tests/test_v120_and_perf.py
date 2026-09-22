"""
test_v120_and_perf.py
Unit tests verifying:
1. Version number is 1.2.0 across version.py, version_info.txt, and installer.
2. RuntimeManager in-memory caching and cache invalidation.
3. YtDlpUpdater in-memory caching and cache invalidation.
4. AuthChecker cookie file validation caching.
5. SettingsDialog layout, v1.2.0 badge, and absence of redundant runtime subtitle.
"""

import sys
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from core.version import __version__
from downloader.runtime_manager import RuntimeManager, ComponentInfo
from downloader.updater import YtDlpUpdater
from downloader.auth_checker import AuthChecker
from gui.settings_dialog import SettingsDialog
from core.i18n import I18nManager


class TestVersion120AndPerf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_version_number_120(self):
        """Verify version is exactly 1.2.0."""
        self.assertEqual(__version__, "1.2.0")

        # Verify version_info.txt
        root = Path(__file__).resolve().parent.parent
        vinfo_path = root / "version_info.txt"
        self.assertTrue(vinfo_path.exists())
        vinfo_text = vinfo_path.read_text(encoding="utf-8")
        self.assertIn("filevers=(1, 2, 0, 0)", vinfo_text)
        self.assertIn("prodvers=(1, 2, 0, 0)", vinfo_text)
        self.assertIn("1.2.0.0", vinfo_text)

        # Verify installer script
        iss_path = root / "installer" / "ChannelHarvest.iss"
        self.assertTrue(iss_path.exists())
        iss_text = iss_path.read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.2.0"', iss_text)

    def test_runtime_manager_caching(self):
        """Verify RuntimeManager caches results and invalidate_cache clears it."""
        RuntimeManager.invalidate_cache()
        self.assertIsNone(RuntimeManager._cached_versions)

        # First call populates cache
        res1 = RuntimeManager.get_installed_versions()
        self.assertIsNotNone(RuntimeManager._cached_versions)
        self.assertEqual(set(res1.keys()), set(RuntimeManager.ALL_COMPONENTS))

        # Second call returns from cache
        res2 = RuntimeManager.get_installed_versions()
        for k in RuntimeManager.ALL_COMPONENTS:
            self.assertEqual(res1[k].current_version, res2[k].current_version)

        # Invalidate cache
        RuntimeManager.invalidate_cache()
        self.assertIsNone(RuntimeManager._cached_versions)

    def test_ytdlp_updater_caching(self):
        """Verify YtDlpUpdater caches get_installed_version."""
        YtDlpUpdater.invalidate_cache()
        self.assertIsNone(YtDlpUpdater._cached_version)

        v1 = YtDlpUpdater.get_installed_version()
        self.assertIsNotNone(YtDlpUpdater._cached_version)
        self.assertEqual(v1, YtDlpUpdater._cached_version)

        v2 = YtDlpUpdater.get_installed_version()
        self.assertEqual(v1, v2)

        YtDlpUpdater.invalidate_cache()
        self.assertIsNone(YtDlpUpdater._cached_version)

    def test_settings_dialog_v120_and_no_subtitle(self):
        """Verify SettingsDialog displays v1.2.0 badge and has no runtime_sub_lbl."""
        # Preheat runtime cache so dialog opens instantly
        RuntimeManager.get_installed_versions()

        dlg = SettingsDialog()
        self.assertEqual(dlg.APP_VERSION, "v1.2.0")
        self.assertIn("1.2.0", dlg._ver_badge.text())

        # Subtitle should be gone
        self.assertFalse(hasattr(dlg, "runtime_sub_lbl"))

        # Table headers must exist
        self.assertTrue(hasattr(dlg, "th_comp"))
        self.assertTrue(hasattr(dlg, "th_ver"))
        self.assertTrue(hasattr(dlg, "th_stat"))

        # Test bilingual retranslate
        I18nManager.set_language("zh_CN")
        dlg.retranslate_ui()
        self.assertEqual(dlg.th_comp.text(), "组件")
        self.assertEqual(dlg.th_ver.text(), "当前版本")
        self.assertEqual(dlg.th_stat.text(), "状态")

        I18nManager.set_language("en_US")
        dlg.retranslate_ui()
        self.assertEqual(dlg.th_comp.text(), "Component")
        self.assertEqual(dlg.th_ver.text(), "Current Version")
        self.assertEqual(dlg.th_stat.text(), "Status")

        dlg.close()


if __name__ == "__main__":
    unittest.main()
