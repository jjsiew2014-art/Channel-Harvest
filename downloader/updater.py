"""
updater.py
Official yt-dlp update checker and installer for Channel Harvest.

Features:
- Queries official yt-dlp release channels (GitHub Releases API with PyPI fallback).
- Performs safe, non-blocking background checks via QThread.
- Compares versions reliably using numeric tuple decomposition.
- Safe pip upgrade subprocess execution with Windows window suppression.
- Dedicated logging to %APPDATA%/ChannelHarvest/logs/updater.log.
"""

import re
import sys
import json
import logging
import subprocess
import importlib
import urllib.request
from typing import Tuple, Optional
from pathlib import Path

import yt_dlp
from PySide6.QtCore import QThread, Signal

from core.paths import (
    get_logs_dir,
    get_runtime_dir,
    get_user_runtime_dir,
    get_bundled_executable,
    get_app_data_dir,
)

# Configure updater logger
_logger = logging.getLogger("ChannelHarvest.Updater")


def _get_updater_log_file() -> Path:
    return get_logs_dir() / "updater.log"


def _log_updater(message: str) -> None:
    try:
        log_file = _get_updater_log_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
    except Exception:
        pass


def _is_dir_writable(path: Path) -> bool:
    """Checks whether the directory can be written to."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / f".writable_test_{os.getpid()}"
        with open(test_file, "w") as f:
            f.write("test")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """Parses a version string into a comparable tuple of integers."""
    numbers = re.findall(r"\d+", ver_str or "")
    return tuple(int(n) for n in numbers) if numbers else (0,)


class YtDlpUpdater:
    """
    Manages checking and updating yt-dlp from official release sources.
    Works seamlessly in both source (Python) and frozen (PyInstaller) production environments.
    """

    GITHUB_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    GITHUB_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    PYPI_API_URL = "https://pypi.org/pypi/yt-dlp/json"

    @classmethod
    def get_installed_version(cls) -> str:
        """Returns the currently installed yt-dlp version string."""
        # 1. Check bundled or user-updated binary version
        bundled_exe = get_bundled_executable("yt-dlp.exe")
        if bundled_exe and bundled_exe.exists():
            try:
                startupinfo = None
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0

                proc = subprocess.run(
                    [str(bundled_exe), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=creation_flags,
                    startupinfo=startupinfo,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip().splitlines()[0]
            except Exception:
                pass

        # 2. Fallback to Python module version
        return getattr(yt_dlp.version, "__version__", "Unknown")

    @classmethod
    def check_latest_version(cls, timeout: int = 8) -> Tuple[bool, str, str, str]:
        """
        Queries official sources for the latest yt-dlp release.

        Returns:
            Tuple of (has_update: bool, current_version: str, latest_version: str, error_message: str)
        """
        current_ver = cls.get_installed_version()
        current_tuple = parse_version(current_ver)
        latest_ver = ""
        error_msg = ""

        # 1. Try official GitHub Releases API
        headers = {
            "User-Agent": "ChannelHarvest-Downloader/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            req = urllib.request.Request(cls.GITHUB_API_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    latest_ver = str(data.get("tag_name", "")).lstrip("v")
        except Exception as gh_err:
            _log_updater(f"[INFO] GitHub API check failed ({gh_err}), falling back to PyPI...")

        # 2. Fallback to official PyPI API if GitHub was unreachable or rate-limited
        if not latest_ver:
            try:
                pypi_req = urllib.request.Request(cls.PYPI_API_URL, headers=headers)
                with urllib.request.urlopen(pypi_req, timeout=timeout) as pypi_resp:
                    if pypi_resp.status == 200:
                        pypi_data = json.loads(pypi_resp.read().decode("utf-8"))
                        latest_ver = str(pypi_data.get("info", {}).get("version", ""))
            except Exception as pypi_err:
                _log_updater(f"[ERROR] PyPI check also failed: {pypi_err}")
                error_msg = "Unable to connect to the update server. Please check your internet connection."

        if not latest_ver:
            if not error_msg:
                error_msg = "Could not parse version from official release source."
            return False, current_ver, "", error_msg

        latest_tuple = parse_version(latest_ver)
        has_update = latest_tuple > current_tuple

        _log_updater(
            f"[CHECK] Current: {current_ver} ({current_tuple}), "
            f"Latest: {latest_ver} ({latest_tuple}), HasUpdate: {has_update}"
        )
        return has_update, current_ver, latest_ver, ""

    @classmethod
    def install_update(cls) -> Tuple[bool, str, str]:
        """
        Safely installs the latest yt-dlp update.
        In standalone / frozen production mode:
          1. Downloads the official yt-dlp.exe binary into runtime directory.
          2. Verifies integrity by executing `--version`.
          3. Atomically replaces target binary (with fallback to AppData if Program Files is read-only).
          4. Downloads wheel package to AppData packages so embedded python module is also updated.
        In source / developer mode:
          Uses pip install --upgrade with binary update fallback.

        Returns:
            Tuple of (success: bool, new_version: str, error_message: str)
        """
        old_ver = cls.get_installed_version()
        _log_updater(f"[INSTALL] Starting yt-dlp update from version {old_ver}...")

        is_frozen = getattr(sys, "frozen", False)
        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}

        # Standalone binary update mechanism (frozen or standalone preference)
        if is_frozen or get_bundled_executable("yt-dlp.exe") is not None:
            return cls._install_standalone_update(old_ver)

        # Developer / source mode fallback with pip
        try:
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-warn-script-location",
                "yt-dlp",
            ]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=creation_flags,
                timeout=120,
            )
            if result.returncode == 0:
                try:
                    importlib.reload(yt_dlp)
                    importlib.reload(yt_dlp.version)
                except Exception:
                    pass
                new_ver = cls.get_installed_version()
                _log_updater(f"[INSTALL SUCCESS] yt-dlp updated via pip to {new_ver}.")
                return True, new_ver, ""
            else:
                _log_updater(f"[INSTALL WARN] pip update failed, falling back to binary download: {result.stderr}")
                return cls._install_standalone_update(old_ver)
        except Exception as e:
            _log_updater(f"[INSTALL WARN] pip update exception: {e}, attempting binary download...")
            return cls._install_standalone_update(old_ver)

    @classmethod
    def _install_standalone_update(cls, old_ver: str) -> Tuple[bool, str, str]:
        """Downloads standalone binary and library updates cleanly without pip."""
        import shutil
        import zipfile

        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}

        # 1. Determine destination directory for yt-dlp.exe
        runtime_dir = get_runtime_dir()
        if _is_dir_writable(runtime_dir):
            target_dir = runtime_dir
        else:
            target_dir = get_user_runtime_dir()

        target_dir.mkdir(parents=True, exist_ok=True)
        final_exe = target_dir / "yt-dlp.exe"
        temp_exe = target_dir / "yt-dlp.exe.new"
        old_backup = target_dir / "yt-dlp.exe.old"

        _log_updater(f"[INSTALL] Downloading standalone yt-dlp.exe to {temp_exe}...")

        try:
            req = urllib.request.Request(cls.GITHUB_DOWNLOAD_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp:
                with open(temp_exe, "wb") as f:
                    shutil.copyfileobj(resp, f)

            # Verify the downloaded binary runs and outputs valid version
            startupinfo = None
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            test_proc = subprocess.run(
                [str(temp_exe), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creation_flags,
                startupinfo=startupinfo,
            )

            if test_proc.returncode != 0 or not test_proc.stdout.strip():
                if temp_exe.exists():
                    temp_exe.unlink()
                err_msg = f"Downloaded yt-dlp.exe failed verification: {test_proc.stderr}"
                _log_updater(f"[INSTALL ERROR] {err_msg}")
                return False, old_ver, err_msg

            new_binary_version = test_proc.stdout.strip().splitlines()[0]

            # Atomically replace executable
            if old_backup.exists():
                try:
                    old_backup.unlink()
                except Exception:
                    pass

            if final_exe.exists():
                try:
                    final_exe.rename(old_backup)
                except Exception:
                    pass

            temp_exe.replace(final_exe)

            if old_backup.exists():
                try:
                    old_backup.unlink()
                except Exception:
                    pass

            _log_updater(f"[INSTALL SUCCESS] yt-dlp.exe updated to {new_binary_version} at {final_exe}")

            # 2. Also attempt to update the embedded Python package in AppData/packages
            try:
                pypi_req = urllib.request.Request(cls.PYPI_API_URL, headers=headers)
                with urllib.request.urlopen(pypi_req, timeout=15) as pypi_resp:
                    pypi_data = json.loads(pypi_resp.read().decode("utf-8"))
                    urls = pypi_data.get("urls", [])
                    whl_url = None
                    for u in urls:
                        if u.get("filename", "").endswith("-none-any.whl"):
                            whl_url = u.get("url")
                            break

                    if whl_url:
                        pkgs_dir = get_app_data_dir() / "packages"
                        pkgs_dir.mkdir(parents=True, exist_ok=True)
                        temp_whl = pkgs_dir / "temp_ytdlp.whl"

                        whl_req = urllib.request.Request(whl_url, headers=headers)
                        with urllib.request.urlopen(whl_req, timeout=90) as whl_resp:
                            with open(temp_whl, "wb") as f:
                                shutil.copyfileobj(whl_resp, f)

                        with zipfile.ZipFile(temp_whl, "r") as zf:
                            for member in zf.namelist():
                                if member.startswith("yt_dlp/"):
                                    zf.extract(member, pkgs_dir)

                        if temp_whl.exists():
                            temp_whl.unlink()

                        if str(pkgs_dir) not in sys.path:
                            sys.path.insert(0, str(pkgs_dir))

                        importlib.invalidate_caches()
                        try:
                            importlib.reload(yt_dlp)
                            importlib.reload(yt_dlp.version)
                        except Exception:
                            pass
                        _log_updater(f"[INSTALL SUCCESS] yt-dlp Python package extracted to {pkgs_dir}")
            except Exception as pkg_err:
                _log_updater(f"[INSTALL INFO] Python package update skipped ({pkg_err}), CLI binary is ready.")

            return True, new_binary_version, ""

        except Exception as e:
            _log_updater(f"[INSTALL EXCEPTION] {e}")
            if temp_exe.exists():
                try:
                    temp_exe.unlink()
                except Exception:
                    pass
            return False, old_ver, f"Update failed: {e}"



class CheckUpdateWorker(QThread):
    """
    Background worker thread to check for yt-dlp updates without blocking the UI.
    """

    # (has_update, current_ver, latest_ver, error_msg)
    check_completed = Signal(bool, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        has_update, current_ver, latest_ver, error_msg = YtDlpUpdater.check_latest_version()
        self.check_completed.emit(has_update, current_ver, latest_ver, error_msg)


class InstallUpdateWorker(QThread):
    """
    Background worker thread to perform yt-dlp update installation.
    """

    # (success, new_version, error_msg)
    install_completed = Signal(bool, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        success, new_ver, error_msg = YtDlpUpdater.install_update()
        self.install_completed.emit(success, new_ver, error_msg)
