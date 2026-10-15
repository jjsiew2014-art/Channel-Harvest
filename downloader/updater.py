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

import os
import re
import sys
import json
import logging
import subprocess
import importlib
import urllib.request
from typing import Tuple, Optional, Dict, Any
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


_ytdlp_validation_cache: Dict[Tuple[str, int, int], Tuple[bool, str, Dict[str, Any]]] = {}


def invalidate_ytdlp_validation_cache() -> None:
    """Clears the standalone yt-dlp binary validation cache."""
    global _ytdlp_validation_cache
    _ytdlp_validation_cache.clear()


def validate_standalone_ytdlp(candidate_path: Path, force_refresh: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates that candidate_path is an official standalone Windows x64 yt-dlp executable.

    Enforces strict security and packaging requirements:
    1. File must exist and size must be >= 5 MB (rejects ~100 KB script wrappers).
    2. Must be a valid Windows PE binary (MZ header, PE signature).
    3. Architecture must be x86_64 / AMD64 (PE machine type 0x8664).
    4. Must NOT be a pip/distlib wrapper (rejects simple_launcher, t64.pdb, t64.exe).
    5. Must NOT contain developer-local Python shebang or pythoncore path strings.
    6. Must successfully execute and return a valid version.
    7. Must successfully execute --verbose --list-impersonate-targets:
       - Distribution tag must not be (pip)
       - curl_cffi must be present in optional libraries / request handlers
       - Available impersonation targets must be present

    Caches validation results by (path, size, mtime) to ensure instantaneous subsequent checks.
    """
    info: Dict[str, Any] = {
        "path": str(candidate_path),
        "size": 0,
        "machine": "unknown",
        "version": "",
        "build_type": "unknown",
        "curl_cffi": "Unavailable",
        "curl_cffi_version": "",
        "impersonation": "Unavailable",
        "impersonation_state": "IMPERSONATION_UNAVAILABLE",
        "available_targets": [],
        "default_target": "",
    }

    if not candidate_path.is_file():
        return False, f"File does not exist: {candidate_path}", info

    try:
        st = candidate_path.stat()
        size = st.st_size
        mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    except Exception as e:
        return False, f"Failed to access file stats: {e}", info

    info["size"] = size
    cache_key = (str(candidate_path.resolve()), size, mtime_ns)

    if not force_refresh and cache_key in _ytdlp_validation_cache:
        c_valid, c_reason, c_info = _ytdlp_validation_cache[cache_key]
        return c_valid, c_reason, dict(c_info)

    MIN_STANDALONE_SIZE = 5 * 1024 * 1024  # 5 MB minimum
    if size < MIN_STANDALONE_SIZE:
        info["build_type"] = "INVALID — Python-dependent launcher"
        return False, f"File size too small for standalone build: {size:,} bytes (expected >= 5 MB). Appears to be a script wrapper.", info

    # 2. Windows PE header check
    try:
        with open(candidate_path, "rb") as f:
            header = f.read(1024)
            if header[:2] != b"MZ":
                return False, "Not a valid Windows executable (missing MZ signature)", info

            pe_offset = int.from_bytes(header[0x3C:0x40], "little")
            f.seek(pe_offset)
            pe_sig = f.read(4)
            if pe_sig != b"PE\x00\x00":
                return False, "Invalid PE header signature", info

            machine = int.from_bytes(f.read(2), "little")
            if machine == 0x8664:
                info["machine"] = "x86_64"
            elif machine == 0x014C:
                info["machine"] = "x86_32"
                return False, "Executable architecture is 32-bit (x86). 64-bit AMD64 (0x8664) required.", info
            elif machine == 0xAA64:
                info["machine"] = "ARM64"
                return False, "Executable architecture is ARM64. x86_64 required for standard release.", info
            else:
                info["machine"] = f"0x{machine:04x}"
                return False, f"Unexpected machine architecture: 0x{machine:04x}. Expected x86_64 (0x8664).", info

            # 3. Content inspection for pip/distlib wrapper signatures
            f.seek(0)
            sample = f.read(2 * 1024 * 1024)
            f.seek(max(0, size - 262144))
            sample += f.read()

            suspicious_markers = [
                (b"simple_launcher", "pip/distlib simple_launcher wrapper detected"),
                (b"t64.pdb", "pip/distlib t64.pdb launcher marker detected"),
                (b"t64.exe", "pip/distlib t64.exe launcher marker detected"),
                (b"pythoncore", "Hardcoded pythoncore developer Python path detected"),
            ]
            for marker, reason in suspicious_markers:
                if marker in sample:
                    info["build_type"] = "INVALID — Python-dependent launcher"
                    return False, f"Invalid build type: {reason}", info

            if re.search(rb"#!.*python", sample, re.IGNORECASE):
                info["build_type"] = "INVALID — Python-dependent launcher"
                return False, "Invalid build type: Shebang pointing to Python interpreter found", info

    except Exception as e:
        return False, f"Failed to parse PE binary headers: {e}", info

    # 4. Diagnostic execution check (extracts version, distribution tag, curl_cffi, and targets)
    startupinfo = None
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        diag_proc = subprocess.run(
            [str(candidate_path), "--verbose", "--list-impersonate-targets"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=creation_flags,
            startupinfo=startupinfo,
        )
        if diag_proc.returncode != 0:
            return False, f"--verbose execution failed (code {diag_proc.returncode}): {diag_proc.stderr.strip()}", info

        combined_output = f"{diag_proc.stdout}\n{diag_proc.stderr}"

        # Extract version directly from diagnostic output (avoids redundant second process spawn)
        m_ver = re.search(r"yt-dlp version (?:stable@)?([0-9\.]+)", combined_output)
        if m_ver:
            info["version"] = m_ver.group(1)
        else:
            ver_proc = subprocess.run(
                [str(candidate_path), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creation_flags,
                startupinfo=startupinfo,
            )
            if ver_proc.returncode == 0 and ver_proc.stdout.strip():
                info["version"] = ver_proc.stdout.strip().splitlines()[0]
            else:
                return False, f"--version execution failed (code {ver_proc.returncode}): {ver_proc.stderr.strip()}", info

        # Distribution check
        if "(pip)" in combined_output:
            info["build_type"] = "INVALID — Python-dependent launcher"
            return False, "Executable is a pip distribution, not a standalone binary", info

        if "(win_exe)" in combined_output or "(pyinstaller)" in combined_output or "standalone" in combined_output.lower():
            info["build_type"] = "Windows x64 Standalone"
        else:
            info["build_type"] = "Windows Standalone"

        # curl_cffi check
        m_curl_ver = re.search(r"curl_cffi-([0-9a-zA-Z\.]+)", combined_output, re.IGNORECASE)
        curl_ver_str = m_curl_ver.group(1) if m_curl_ver else ""
        info["curl_cffi_version"] = curl_ver_str

        has_curl_cffi_lib = bool(re.search(r"curl_cffi(?:-[0-9a-zA-Z\.]+)?", combined_output, re.IGNORECASE))
        has_curl_cffi_handler = "curl_cffi" in combined_output.split("Request Handlers:")[-1].splitlines()[0] if "Request Handlers:" in combined_output else False

        if not (has_curl_cffi_lib or has_curl_cffi_handler):
            info["curl_cffi"] = "Unavailable"
            info["impersonation_state"] = "IMPERSONATION_UNAVAILABLE"
            return False, "curl_cffi is missing from optional libraries and request handlers", info
        info["curl_cffi"] = "Available"

        # Impersonate targets check
        impersonate_section = diag_proc.stdout
        available_targets = []
        for line in impersonate_section.splitlines():
            if "curl_cffi" in line and "(unavailable)" not in line.lower():
                parts = line.split()
                if parts:
                    target_name = parts[0]
                    if len(parts) >= 2 and parts[1] != "curl_cffi":
                        target_name = f"{parts[0]}:{parts[1]}"
                    available_targets.append(target_name)

        info["available_targets"] = available_targets
        if not available_targets:
            info["impersonation"] = "Unavailable"
            info["impersonation_state"] = "IMPERSONATION_UNAVAILABLE"
            return False, "All impersonate targets report unavailable", info

        info["default_target"] = "chrome" if any("chrome" in t.lower() for t in available_targets) else (available_targets[0].split(":")[0].lower() if available_targets else "")
        info["impersonation_state"] = "IMPERSONATION_AVAILABLE"
        info["impersonation"] = f"Available ({len(available_targets)} targets)"

    except Exception as e:
        info["impersonation_state"] = "RUNTIME_INCOMPATIBLE"
        return False, f"Failed to execute diagnostic check: {e}", info

    _ytdlp_validation_cache[cache_key] = (True, "Valid official standalone Windows x64 yt-dlp binary", dict(info))
    return True, "Valid official standalone Windows x64 yt-dlp binary", info


class YtDlpUpdater:
    """
    Manages checking and updating yt-dlp from official release sources.
    Works seamlessly in both source (Python) and frozen (PyInstaller) production environments.
    """

    GITHUB_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    GITHUB_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    PYPI_API_URL = "https://pypi.org/pypi/yt-dlp/json"

    _cached_version: Optional[str] = None

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalidates cached yt-dlp version."""
        cls._cached_version = None

    @classmethod
    def get_installed_version(cls, force_refresh: bool = False) -> str:
        """Returns the currently installed yt-dlp version string."""
        if not force_refresh and cls._cached_version is not None:
            return cls._cached_version

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
                    cls._cached_version = proc.stdout.strip().splitlines()[0]
                    return cls._cached_version
            except Exception:
                pass

        # 2. Fallback to Python module version
        cls._cached_version = getattr(yt_dlp.version, "__version__", "Unknown")
        return cls._cached_version

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
                "yt-dlp-ejs",
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
                cls.invalidate_cache()
                new_ver = cls.get_installed_version(force_refresh=True)
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

            # Comprehensive standalone validation (verifies standalone PE x64, rejects pip launchers, checks curl_cffi & targets)
            is_valid, v_reason, v_info = validate_standalone_ytdlp(temp_exe)
            if not is_valid:
                if temp_exe.exists():
                    try:
                        temp_exe.unlink()
                    except Exception:
                        pass
                err_msg = f"Downloaded yt-dlp.exe failed standalone validation: {v_reason}"
                _log_updater(f"[INSTALL ERROR] {err_msg}")
                return False, old_ver, err_msg

            new_binary_version = v_info.get("version") or old_ver
            b_type = v_info.get("build_type", "Windows x64 Standalone")

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

            try:
                temp_exe.replace(final_exe)
            except Exception as replace_err:
                # Rollback if replacement failed
                if old_backup.exists() and not final_exe.exists():
                    try:
                        old_backup.rename(final_exe)
                    except Exception:
                        pass
                raise replace_err

            if old_backup.exists():
                try:
                    old_backup.unlink()
                except Exception:
                    pass

            _log_updater(f"[INSTALL SUCCESS] yt-dlp.exe updated to {new_binary_version} ({b_type}) at {final_exe}")

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

            cls.invalidate_cache()
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
