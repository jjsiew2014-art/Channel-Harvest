"""
app.py
Main entry point for the Channel Harvest desktop application.

To launch the application:
    python app.py

Requirements:
    PySide6 (Qt for Python)
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QIcon

from core.paths import get_logo_file, get_app_icon_file, setup_runtime_environment
from core.settings import SettingsManager
from gui.main_window import MainWindow
from gui.styles import ThemeManager


def _qt_message_handler(mode: QtMsgType, context, message: str) -> None:
    """Filters benign Qt internal warnings (e.g. stylesheet font pointSize resolution)."""
    if "Point size <= 0" in message or "setPointSize" in message:
        return
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        sys.stderr.write(f"{message}\n")


def main() -> None:
    """
    Main function:
    1. Initializes runtime environment (user packages and runtime binaries).
    2. Initializes the Qt Application object.
    3. Configures high-DPI scaling for crisp display on Windows monitors.
    4. Applies the saved theme preference (System, Light, Dark) and window icon.
    5. Displays the MainWindow and enters the Qt event loop.
    """
    # Initialize runtime paths and environment
    setup_runtime_environment()

    # Install Qt message filter to suppress benign C++ stylesheet font warnings
    qInstallMessageHandler(_qt_message_handler)

    # Configure Windows taskbar grouping and icon display
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ChannelHarvest.Downloader.App.1.0")
    except Exception:
        pass

    # Create the Qt Application instance
    app = QApplication(sys.argv)
    app.setApplicationName("Channel Harvest")
    app.setApplicationDisplayName("Channel Harvest")
    app.setOrganizationName("ChannelHarvest")

    # Set application icon (used for taskbar and dialogs)
    app_icon = get_app_icon_file()
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))

    # Apply saved theme preference (System, Light, Dark)
    settings = SettingsManager()
    saved_theme = settings.get("theme", "System")
    ThemeManager.apply_theme(saved_theme, app=app)

    # Instantiate and display the main window
    window = MainWindow()
    window.show()

    # Start the event loop and exit with its return code when closed
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
