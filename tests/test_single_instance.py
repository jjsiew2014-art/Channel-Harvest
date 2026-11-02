# -*- coding: utf-8 -*-
"""
tests/test_single_instance.py

Unit test suite verifying Single-Instance Application guard and duplicate launch prevention:
- Primary instance lock acquisition and IPC server listening.
- Secondary instance duplicate launch detection and exit code 0 behavior.
- Primary instance activation signal dispatch.
- Resource cleanup on close, permitting future launches.
- MainWindow bring_to_front window unminimization and activation.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from core.single_instance import SingleInstanceManager
from gui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestSingleInstance(unittest.TestCase):
    """Verifies SingleInstanceManager behavior."""

    def test_01_primary_instance_binds_and_runs(self):
        """Primary instance successfully acquires lock and begins listening."""
        mgr = SingleInstanceManager(key="ChannelHarvest_Test_Inst01")
        try:
            is_running = mgr.is_already_running()
            self.assertFalse(is_running, "Primary instance should report is_already_running as False")
            self.assertIsNotNone(mgr.server)
            self.assertTrue(mgr.server.isListening())
        finally:
            mgr.close()

    def test_02_secondary_instance_detected_and_signals_primary(self):
        """Secondary instance reports is_already_running as True and signals primary instance."""
        primary = SingleInstanceManager(key="ChannelHarvest_Test_Inst02")
        secondary = SingleInstanceManager(key="ChannelHarvest_Test_Inst02")
        try:
            self.assertFalse(primary.is_already_running())

            activated_signal_received = False

            def on_activate():
                nonlocal activated_signal_received
                activated_signal_received = True

            primary.activate_requested.connect(on_activate)

            # Secondary instance attempts to start with the same key
            is_dup = secondary.is_already_running()
            self.assertTrue(is_dup, "Secondary instance should report is_already_running as True")

            # Process Qt events to receive the local connection signal
            app.processEvents()
            self.assertTrue(activated_signal_received, "Primary instance should have received activate_requested signal")
        finally:
            secondary.close()
            primary.close()

    def test_03_close_releases_resources_allowing_subsequent_launch(self):
        """Closing primary instance releases local socket and mutex, allowing subsequent launch."""
        first = SingleInstanceManager(key="ChannelHarvest_Test_Inst03")
        self.assertFalse(first.is_already_running())
        first.close()

        # Subsequent launch should succeed as primary
        second = SingleInstanceManager(key="ChannelHarvest_Test_Inst03")
        try:
            self.assertFalse(second.is_already_running())
        finally:
            second.close()

    def test_04_main_window_bring_to_front(self):
        """MainWindow.bring_to_front unminimizes, shows, and raises the window."""
        win = MainWindow()
        try:
            with patch.object(win, "isMinimized", return_value=True), \
                 patch.object(win, "showNormal") as mock_show_normal, \
                 patch.object(win, "raise_") as mock_raise, \
                 patch.object(win, "activateWindow") as mock_activate:

                win.bring_to_front()

                mock_show_normal.assert_called_once()
                mock_raise.assert_called_once()
                mock_activate.assert_called_once()
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
