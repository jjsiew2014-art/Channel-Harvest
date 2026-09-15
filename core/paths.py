"""
paths.py
Application path resolution for Channel Harvest on Windows.

Standardizes storage locations for:
- Settings (settings.json)
- Download Archive (download_archive.txt)
- Logs and temporary data
Stored in %APPDATA%/ChannelHarvest/ so user data persists cleanly
and independently from the application code or standalone .exe distribution.
"""

import os
import shutil
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """
    Returns the application data directory:
    %APPDATA%/ChannelHarvest on Windows.
    Creates the directory if it does not already exist.
    Seamlessly migrates existing configuration from legacy YouTubeChannelDownloader directory if present.
    """
    app_data_env = os.environ.get("APPDATA")
    if app_data_env:
        base_dir = Path(app_data_env)
    else:
        # Fallback for systems without APPDATA variable set
        base_dir = Path.home() / "AppData" / "Roaming"

    app_dir = base_dir / "ChannelHarvest"
    legacy_dir = base_dir / "YouTubeChannelDownloader"

    # Seamless migration from legacy folder
    if not app_dir.exists() and legacy_dir.exists():
        try:
            shutil.copytree(legacy_dir, app_dir, dirs_exist_ok=True)
        except Exception:
            pass

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_settings_file() -> Path:
    """Returns path to settings.json in the AppData directory."""
    return get_app_data_dir() / "settings.json"


def get_archive_file() -> Path:
    """
    Returns path to download_archive.txt.
    yt-dlp uses this file to track downloaded video IDs and avoid duplicates.
    """
    return get_app_data_dir() / "download_archive.txt"


def get_logs_dir() -> Path:
    """Returns directory for application log files."""
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_resource_path(relative_path: str = "") -> Path:
    """
    Returns the absolute path to a bundled resource file.
    Works in development mode as well as PyInstaller frozen mode (onedir / onefile).
    """
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidate = Path(sys._MEIPASS) / relative_path
            if candidate.exists() or not relative_path:
                return candidate
        exe_dir = Path(sys.executable).resolve().parent
        if relative_path:
            cand_root = exe_dir / relative_path
            if cand_root.exists():
                return cand_root
            cand_internal = exe_dir / "_internal" / relative_path
            if cand_internal.exists():
                return cand_internal
        return (Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else exe_dir) / relative_path
    else:
        base_dir = Path(__file__).resolve().parent.parent

    if relative_path:
        return base_dir / relative_path
    return base_dir



def get_logo_file() -> Path:
    """
    Returns path to the Channel Harvest application logo image.
    Supports both source execution and PyInstaller bundled distribution.
    """
    return get_resource_path("Channel Harvest__Logo.png")


def get_app_icon_file() -> Path:
    """
    Returns path to the Channel Harvest application .ico file.
    Falls back to logo PNG if .ico is not found.
    """
    ico_path = get_resource_path("ChannelHarvest.ico")
    if ico_path.exists():
        return ico_path
    return get_logo_file()


def get_runtime_dir() -> Path:
    """
    Returns the path to the external runtime directory containing bundled binaries:
    ffmpeg.exe, ffprobe.exe, yt-dlp.exe.
    In frozen distribution: <app_dir>/runtime/
    In source execution: <project_root>/runtime/
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "runtime"


def get_user_runtime_dir() -> Path:
    """
    Returns the path to the user-level runtime directory in %APPDATA%/ChannelHarvest/runtime.
    Used for user-updated binaries (like yt-dlp.exe) when the system installation
    (e.g., Program Files) is read-only.
    """
    user_runtime = get_app_data_dir() / "runtime"
    user_runtime.mkdir(parents=True, exist_ok=True)
    return user_runtime


def get_bundled_executable(name: str) -> Optional[Path]:
    """
    Searches for a binary executable in order of priority:
    1. User AppData runtime (%APPDATA%/ChannelHarvest/runtime/<name>) - user-updated binaries
    2. App installation runtime directory (<app_dir>/runtime/<name>)
    3. PyInstaller internal bundle directory (sys._MEIPASS/runtime/<name> or sys._MEIPASS/<name>)
    Returns the Path if found and file exists, or None.
    """
    candidates = [
        get_user_runtime_dir() / name,
        get_runtime_dir() / name,
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates.append(meipass / "runtime" / name)
        candidates.append(meipass / name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def setup_runtime_environment() -> None:
    """
    Initializes runtime environment:
    1. Prepends %APPDATA%/ChannelHarvest/packages to sys.path so updated packages (e.g. yt-dlp) are loaded.
    2. Prepends runtime and user-runtime directories to system PATH for child processes.
    """
    user_pkgs = get_app_data_dir() / "packages"
    if user_pkgs.exists() and str(user_pkgs) not in sys.path:
        sys.path.insert(0, str(user_pkgs))

    user_runtime = get_user_runtime_dir()
    if user_runtime.exists():
        path_str = os.environ.get("PATH", "")
        if str(user_runtime) not in path_str:
            os.environ["PATH"] = f"{str(user_runtime)}{os.pathsep}{path_str}"

    runtime_dir = get_runtime_dir()
    if runtime_dir.exists():
        path_str = os.environ.get("PATH", "")
        if str(runtime_dir) not in path_str:
            os.environ["PATH"] = f"{str(runtime_dir)}{os.pathsep}{path_str}"

