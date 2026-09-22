"""
runtime_manager.py
Unified Channel Harvest Runtime Manager and Coordinated Update Coordinator.

Coordinates all four core YouTube extraction and media processing components:
1. yt-dlp (Download engine & YouTube extractor)
2. yt-dlp-ejs (YouTube JavaScript challenge solver scripts & NPM components)
3. Deno (JavaScript execution runtime)
4. FFmpeg & FFprobe (High-definition video/audio multiplexer & converter)

Features:
- Live version detection from bundled or user-updated environments.
- Coordinated update checking against official release endpoints (GitHub Releases / PyPI / Gyan.dev).
- Safe, non-blocking background QThread workers for UI responsiveness.
- Active download locking: refuses to replace binaries while downloads are in flight.
- Atomic replacement with pre-execution validation (--version / -version) and rollback protection.
- Fully self-contained: resolves strictly relative to application runtime or %APPDATA%/ChannelHarvest.
"""

import os
import re
import sys
import json
import shutil
import zipfile
import logging
import subprocess
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

from PySide6.QtCore import QThread, Signal, QObject

from core.paths import (
    get_runtime_dir,
    get_user_runtime_dir,
    get_bundled_executable,
    get_deno_executable,
    get_app_data_dir,
    get_logs_dir,
)
from downloader.updater import YtDlpUpdater, parse_version, _is_dir_writable
from downloader.deno_checker import DenoChecker
from downloader.ffmpeg_checker import FFmpegChecker
from core.diagnostics import ErrorTracker

_logger = logging.getLogger("ChannelHarvest.RuntimeManager")


def _log_runtime(msg: str) -> None:
    try:
        log_file = get_logs_dir() / "runtime_manager.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


@dataclass
class ComponentInfo:
    """Represents live status and version metadata for a runtime component."""
    key: str
    display_name: str
    current_version: str = "Unknown"
    latest_version: str = ""
    has_update: bool = False
    status: str = "Checking"  # "Up to date", "Update available", "Not Found", "Error"
    error_message: str = ""
    path: str = ""


class RuntimeManager:
    """
    Coordinates detection, checking, and updating for all four runtime components.
    """

    KEY_YTDLP = "ytdlp"
    KEY_EJS = "ejs"
    KEY_DENO = "deno"
    KEY_FFMPEG = "ffmpeg"

    ALL_COMPONENTS = [KEY_YTDLP, KEY_EJS, KEY_DENO, KEY_FFMPEG]

    # Official API endpoints
    EJS_PYPI_API = "https://pypi.org/pypi/yt-dlp-ejs/json"
    EJS_GITHUB_API = "https://api.github.com/repos/yt-dlp/yt-dlp-ejs/releases/latest"

    DENO_GITHUB_API = "https://api.github.com/repos/denoland/deno/releases/latest"
    DENO_WIN_ASSET_NAME = "deno-x86_64-pc-windows-msvc.zip"

    FFMPEG_GYAN_VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/release-version"
    FFMPEG_GYAN_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    FFMPEG_BTBN_GITHUB_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"

    # In-memory cache for fast, non-blocking UI access
    _cached_versions: Optional[Dict[str, ComponentInfo]] = None

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalidates the in-memory cached component version details."""
        cls._cached_versions = None

    # -------------------------------------------------------------------------
    # 1. Version Detection
    # -------------------------------------------------------------------------

    @classmethod
    def get_installed_versions(cls, force_refresh: bool = False) -> Dict[str, ComponentInfo]:
        """Gathers live versions and status for all four runtime components."""
        if not force_refresh and cls._cached_versions is not None:
            return {
                k: ComponentInfo(
                    key=v.key,
                    display_name=v.display_name,
                    current_version=v.current_version,
                    latest_version=v.latest_version,
                    status=v.status,
                    has_update=v.has_update,
                    error_message=v.error_message,
                    path=v.path,
                )
                for k, v in cls._cached_versions.items()
            }

        results: Dict[str, ComponentInfo] = {}

        # 1. yt-dlp
        ytdlp_ver = YtDlpUpdater.get_installed_version(force_refresh=force_refresh)
        ytdlp_bin = get_bundled_executable("yt-dlp.exe")
        ytdlp_ok = ytdlp_ver not in ("Unknown", "", "Not Found")
        results[cls.KEY_YTDLP] = ComponentInfo(
            key=cls.KEY_YTDLP,
            display_name="yt-dlp",
            current_version=ytdlp_ver,
            status="Up to date" if ytdlp_ok else "Not Found",
            path=str(ytdlp_bin) if ytdlp_bin else "",
        )

        # 2. EJS (yt-dlp-ejs)
        ejs_ver = "Not Installed"
        try:
            import yt_dlp_ejs
            ejs_ver = getattr(yt_dlp_ejs, "__version__", getattr(yt_dlp_ejs, "version", "Unknown"))
        except ImportError:
            pass
        ejs_ok = ejs_ver not in ("Not Installed", "Unknown", "")
        results[cls.KEY_EJS] = ComponentInfo(
            key=cls.KEY_EJS,
            display_name="EJS",
            current_version=ejs_ver,
            status="Up to date" if ejs_ok else "Not Installed",
            path="Python Package (yt-dlp-ejs)",
        )

        # 3. Deno
        is_deno_ok, deno_path, deno_ver, _ = DenoChecker.detect(force_refresh=force_refresh)
        results[cls.KEY_DENO] = ComponentInfo(
            key=cls.KEY_DENO,
            display_name="Deno",
            current_version=deno_ver if is_deno_ok else "Not Found",
            status="Up to date" if is_deno_ok else "Not Found",
            path=str(deno_path) if deno_path else "",
        )

        # 4. FFmpeg
        is_ffmpeg_ok, ffmpeg_path, ffmpeg_ver, _ = FFmpegChecker.detect(force_refresh=force_refresh)
        # Parse clean semver or release tag
        parsed_ver = ffmpeg_ver
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", ffmpeg_ver)
        if m:
            parsed_ver = m.group(1)
        results[cls.KEY_FFMPEG] = ComponentInfo(
            key=cls.KEY_FFMPEG,
            display_name="FFmpeg",
            current_version=parsed_ver if is_ffmpeg_ok else "Not Found",
            status="Up to date" if is_ffmpeg_ok else "Not Found",
            path=str(ffmpeg_path) if ffmpeg_path else "",
        )

        cls._cached_versions = {
            k: ComponentInfo(
                key=v.key,
                display_name=v.display_name,
                current_version=v.current_version,
                latest_version=v.latest_version,
                status=v.status,
                has_update=v.has_update,
                error_message=v.error_message,
                path=v.path,
            )
            for k, v in results.items()
        }

        return results

    # -------------------------------------------------------------------------
    # 2. Check for Updates
    # -------------------------------------------------------------------------

    @classmethod
    def check_component_update(cls, key: str, timeout: int = 8) -> ComponentInfo:
        """Checks official release channels for a specific component."""
        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}
        info = cls.get_installed_versions().get(key)
        if not info:
            return ComponentInfo(key=key, display_name=key, status="Error", error_message="Unknown component")

        try:
            if key == cls.KEY_YTDLP:
                has_up, cur_v, lat_v, err = YtDlpUpdater.check_latest_version(timeout=timeout)
                info.current_version = cur_v
                info.latest_version = lat_v
                info.has_update = has_up
                info.error_message = err
                if err:
                    info.status = "Error"
                elif has_up:
                    info.status = "Update available"
                else:
                    info.status = "Up to date"

            elif key == cls.KEY_EJS:
                latest_v = ""
                err = ""
                # Try PyPI first
                try:
                    req = urllib.request.Request(cls.EJS_PYPI_API, headers=headers)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            latest_v = str(data.get("info", {}).get("version", ""))
                except Exception as pypi_err:
                    _log_runtime(f"[EJS] PyPI check failed: {pypi_err}, trying GitHub...")

                # Fallback to GitHub
                if not latest_v:
                    try:
                        req = urllib.request.Request(cls.EJS_GITHUB_API, headers=headers)
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            if resp.status == 200:
                                data = json.loads(resp.read().decode("utf-8"))
                                latest_v = str(data.get("tag_name", "")).lstrip("v")
                    except Exception as gh_err:
                        err = f"Could not check EJS updates: {gh_err}"

                if latest_v:
                    info.latest_version = latest_v
                    cur_t = parse_version(info.current_version)
                    lat_t = parse_version(latest_v)
                    info.has_update = lat_t > cur_t
                    info.status = "Update available" if info.has_update else "Up to date"
                else:
                    info.status = "Error"
                    info.error_message = err or "Unable to contact update server"

            elif key == cls.KEY_DENO:
                latest_v = ""
                err = ""
                try:
                    req = urllib.request.Request(cls.DENO_GITHUB_API, headers=headers)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            latest_v = str(data.get("tag_name", "")).lstrip("v")
                except Exception as gh_err:
                    err = f"Could not check Deno updates: {gh_err}"

                if latest_v:
                    info.latest_version = latest_v
                    cur_t = parse_version(info.current_version)
                    lat_t = parse_version(latest_v)
                    info.has_update = lat_t > cur_t
                    info.status = "Update available" if info.has_update else "Up to date"
                else:
                    info.status = "Error"
                    info.error_message = err or "Unable to contact update server"

            elif key == cls.KEY_FFMPEG:
                latest_v = ""
                err = ""
                # Try Gyan.dev release-version endpoint
                try:
                    req = urllib.request.Request(cls.FFMPEG_GYAN_VERSION_URL, headers=headers)
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        if resp.status == 200:
                            txt = resp.read().decode("utf-8").strip()
                            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", txt)
                            if m:
                                latest_v = m.group(1)
                except Exception as gyan_err:
                    _log_runtime(f"[FFMPEG] Gyan version check failed: {gyan_err}")

                # Fallback to BtbN GitHub Releases
                if not latest_v:
                    try:
                        req = urllib.request.Request(cls.FFMPEG_BTBN_GITHUB_API, headers=headers)
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            if resp.status == 200:
                                data = json.loads(resp.read().decode("utf-8"))
                                tag = str(data.get("tag_name", ""))
                                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", tag)
                                if m:
                                    latest_v = m.group(1)
                    except Exception as btbn_err:
                        err = f"Could not check FFmpeg updates: {btbn_err}"

                if latest_v:
                    info.latest_version = latest_v
                    cur_t = parse_version(info.current_version)
                    lat_t = parse_version(latest_v)
                    info.has_update = lat_t > cur_t
                    info.status = "Update available" if info.has_update else "Up to date"
                else:
                    info.status = "Error"
                    info.error_message = err or "Unable to contact update server"

        except Exception as e:
            _log_runtime(f"[CHECK EXCEPTION] {key}: {e}")
            info.status = "Error"
            info.error_message = str(e)

        return info

    @classmethod
    def check_all_updates(cls, timeout: int = 8) -> Dict[str, ComponentInfo]:
        """Checks updates for all 4 runtime components."""
        cls.get_installed_versions(force_refresh=True)
        results: Dict[str, ComponentInfo] = {}
        for key in cls.ALL_COMPONENTS:
            results[key] = cls.check_component_update(key, timeout=timeout)
        return results

    # -------------------------------------------------------------------------
    # 3. Component Update Installation (Safe, Validated, Atomic)
    # -------------------------------------------------------------------------

    @classmethod
    def install_update(cls, key: str, is_download_active: bool = False) -> Tuple[bool, str, str]:
        """
        Safely installs an update for the specified component.
        Guarantees:
        1. Refuses to replace binaries if is_download_active is True.
        2. Downloads to temporary file first.
        3. Pre-validates binary execution before replacement.
        4. Keeps .old backup so rollback is immediate if an error occurs.
        5. Relative paths only via core.paths.

        Returns:
            Tuple of (success: bool, new_version: str, error_message: str)
        """
        if is_download_active:
            msg = "Download queue is currently active. Please pause or wait for downloads to complete before updating."
            _log_runtime(f"[INSTALL BLOCKED] {key}: {msg}")
            return False, "", msg

        _log_runtime(f"[INSTALL START] Updating component: {key}")

        if key == cls.KEY_YTDLP:
            res = YtDlpUpdater.install_update()
        elif key == cls.KEY_EJS:
            res = cls._install_ejs_update()
        elif key == cls.KEY_DENO:
            res = cls._install_deno_update()
        elif key == cls.KEY_FFMPEG:
            res = cls._install_ffmpeg_update()
        else:
            return False, "", f"Unknown component key: {key}"

        if res[0]:
            cls.invalidate_cache()
            cls.get_installed_versions(force_refresh=True)
        return res

    @classmethod
    def _install_ejs_update(cls) -> Tuple[bool, str, str]:
        """Updates yt-dlp-ejs via pip (dev mode) or wheel extraction (frozen mode)."""
        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}
        is_frozen = getattr(sys, "frozen", False)

        # 1. In source mode, try pip install --upgrade yt-dlp-ejs
        if not is_frozen:
            try:
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-warn-script-location", "yt-dlp-ejs"]
                proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags, timeout=120)
                if proc.returncode == 0:
                    import importlib
                    try:
                        import yt_dlp_ejs
                        importlib.reload(yt_dlp_ejs)
                    except Exception:
                        pass
                    info = cls.get_installed_versions().get(cls.KEY_EJS)
                    new_ver = info.current_version if info else "Updated"
                    _log_runtime(f"[EJS] Updated via pip to {new_ver}")
                    return True, new_ver, ""
            except Exception as e:
                _log_runtime(f"[EJS] pip update exception: {e}, falling back to wheel download...")

        # 2. Standalone wheel download to %APPDATA%/ChannelHarvest/packages/
        try:
            req = urllib.request.Request(cls.EJS_PYPI_API, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                pypi_data = json.loads(resp.read().decode("utf-8"))

            urls = pypi_data.get("urls", [])
            whl_url = None
            target_ver = pypi_data.get("info", {}).get("version", "Unknown")
            for u in urls:
                if u.get("filename", "").endswith("-none-any.whl") or u.get("filename", "").endswith(".whl"):
                    whl_url = u.get("url")
                    break

            if not whl_url:
                return False, "", "Could not locate compatible wheel package on PyPI."

            pkgs_dir = get_app_data_dir() / "packages"
            pkgs_dir.mkdir(parents=True, exist_ok=True)
            temp_whl = pkgs_dir / "temp_ejs.whl"

            whl_req = urllib.request.Request(whl_url, headers=headers)
            with urllib.request.urlopen(whl_req, timeout=90) as resp:
                with open(temp_whl, "wb") as f:
                    shutil.copyfileobj(resp, f)

            with zipfile.ZipFile(temp_whl, "r") as zf:
                for member in zf.namelist():
                    if member.startswith("yt_dlp_ejs/"):
                        zf.extract(member, pkgs_dir)

            temp_whl.unlink(missing_ok=True)

            if str(pkgs_dir) not in sys.path:
                sys.path.insert(0, str(pkgs_dir))

            import importlib
            importlib.invalidate_caches()
            try:
                import yt_dlp_ejs
                importlib.reload(yt_dlp_ejs)
            except Exception:
                pass

            _log_runtime(f"[EJS] Standalone wheel extracted to {pkgs_dir}, version: {target_ver}")
            return True, target_ver, ""

        except Exception as e:
            _log_runtime(f"[EJS] Install failed: {e}")
            return False, "", f"Failed to update EJS: {e}"

    @classmethod
    def _install_deno_update(cls) -> Tuple[bool, str, str]:
        """Downloads official Deno zip, verifies deno.exe --version, and atomically replaces it."""
        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}

        # 1. Fetch latest release info to get asset download URL
        try:
            req = urllib.request.Request(cls.DENO_GITHUB_API, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            asset_url = None
            tag_name = str(data.get("tag_name", "")).lstrip("v")
            for asset in data.get("assets", []):
                if asset.get("name") == cls.DENO_WIN_ASSET_NAME:
                    asset_url = asset.get("browser_download_url")
                    break

            if not asset_url:
                # Direct fallback URL
                asset_url = f"https://github.com/denoland/deno/releases/download/v{tag_name}/{cls.DENO_WIN_ASSET_NAME}"

        except Exception as e:
            _log_runtime(f"[DENO] Failed to query release assets: {e}")
            return False, "", f"Failed to locate Deno download URL: {e}"

        # 2. Determine target directories
        runtime_dir = get_runtime_dir()
        target_dir = runtime_dir if _is_dir_writable(runtime_dir) else get_user_runtime_dir()
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_zip = target_dir / "temp_deno.zip"
        temp_exe = target_dir / "deno.exe.new"
        final_exe = target_dir / "deno.exe"
        old_backup = target_dir / "deno.exe.old"

        try:
            # Download zip
            _log_runtime(f"[DENO] Downloading {asset_url} to {temp_zip}...")
            dl_req = urllib.request.Request(asset_url, headers=headers)
            with urllib.request.urlopen(dl_req, timeout=120) as resp:
                with open(temp_zip, "wb") as f:
                    shutil.copyfileobj(resp, f)

            # Unpack deno.exe
            with zipfile.ZipFile(temp_zip, "r") as zf:
                if "deno.exe" not in zf.namelist():
                    temp_zip.unlink(missing_ok=True)
                    return False, "", "Downloaded zip did not contain deno.exe"
                with zf.open("deno.exe") as src, open(temp_exe, "wb") as dst:
                    shutil.copyfileobj(src, dst)

            temp_zip.unlink(missing_ok=True)

            # Verify the new binary executes
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            test_proc = subprocess.run(
                [str(temp_exe), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creation_flags,
            )

            if test_proc.returncode != 0 or not test_proc.stdout.strip():
                temp_exe.unlink(missing_ok=True)
                err_msg = f"Downloaded Deno binary failed execution test: {test_proc.stderr}"
                _log_runtime(f"[DENO ERROR] {err_msg}")
                return False, "", err_msg

            # Parse new version
            first_line = test_proc.stdout.strip().splitlines()[0]
            m = re.search(r"deno\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", first_line, re.IGNORECASE)
            new_ver = m.group(1) if m else tag_name

            # Atomically swap
            if old_backup.exists():
                old_backup.unlink(missing_ok=True)
            if final_exe.exists():
                try:
                    final_exe.rename(old_backup)
                except Exception:
                    pass

            temp_exe.replace(final_exe)
            old_backup.unlink(missing_ok=True)

            DenoChecker._cached_result = None  # Reset detection cache
            _log_runtime(f"[DENO SUCCESS] Deno updated to {new_ver} at {final_exe}")
            return True, new_ver, ""

        except Exception as e:
            _log_runtime(f"[DENO EXCEPTION] {e}")
            temp_zip.unlink(missing_ok=True)
            temp_exe.unlink(missing_ok=True)
            # Restore backup if needed
            if old_backup.exists() and not final_exe.exists():
                try:
                    old_backup.rename(final_exe)
                except Exception:
                    pass
            return False, "", f"Deno update failed: {e}"

    @classmethod
    def _install_ffmpeg_update(cls) -> Tuple[bool, str, str]:
        """Downloads official FFmpeg release essentials, verifies ffmpeg.exe -version, and atomically replaces it."""
        headers = {"User-Agent": "ChannelHarvest-Downloader/1.0"}

        runtime_dir = get_runtime_dir()
        target_dir = runtime_dir if _is_dir_writable(runtime_dir) else get_user_runtime_dir()
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_zip = target_dir / "temp_ffmpeg.zip"
        temp_ffmpeg = target_dir / "ffmpeg.exe.new"
        temp_ffprobe = target_dir / "ffprobe.exe.new"
        final_ffmpeg = target_dir / "ffmpeg.exe"
        final_ffprobe = target_dir / "ffprobe.exe"
        old_ffmpeg_backup = target_dir / "ffmpeg.exe.old"
        old_ffprobe_backup = target_dir / "ffprobe.exe.old"

        try:
            _log_runtime(f"[FFMPEG] Downloading {cls.FFMPEG_GYAN_DOWNLOAD_URL} to {temp_zip}...")
            dl_req = urllib.request.Request(cls.FFMPEG_GYAN_DOWNLOAD_URL, headers=headers)
            with urllib.request.urlopen(dl_req, timeout=300) as resp:
                with open(temp_zip, "wb") as f:
                    shutil.copyfileobj(resp, f)

            # Unpack ffmpeg.exe and ffprobe.exe
            with zipfile.ZipFile(temp_zip, "r") as zf:
                ffmpeg_member = None
                ffprobe_member = None
                for name in zf.namelist():
                    if name.endswith("bin/ffmpeg.exe") or name.endswith("/ffmpeg.exe") or name == "ffmpeg.exe":
                        ffmpeg_member = name
                    elif name.endswith("bin/ffprobe.exe") or name.endswith("/ffprobe.exe") or name == "ffprobe.exe":
                        ffprobe_member = name

                if not ffmpeg_member:
                    temp_zip.unlink(missing_ok=True)
                    return False, "", "Downloaded archive did not contain ffmpeg.exe"

                with zf.open(ffmpeg_member) as src, open(temp_ffmpeg, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                if ffprobe_member:
                    with zf.open(ffprobe_member) as src, open(temp_ffprobe, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            temp_zip.unlink(missing_ok=True)

            # Verify the new ffmpeg.exe runs
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            test_proc = subprocess.run(
                [str(temp_ffmpeg), "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creation_flags,
            )

            if test_proc.returncode != 0 or not test_proc.stdout.strip():
                temp_ffmpeg.unlink(missing_ok=True)
                temp_ffprobe.unlink(missing_ok=True)
                err_msg = f"Downloaded FFmpeg binary failed execution test: {test_proc.stderr}"
                _log_runtime(f"[FFMPEG ERROR] {err_msg}")
                return False, "", err_msg

            # Parse new version
            first_line = test_proc.stdout.strip().splitlines()[0]
            m = re.search(r"ffmpeg\s+version\s+([0-9A-Za-z_\.\-]+)", first_line, re.IGNORECASE)
            new_ver = m.group(1) if m else "Updated"

            # Atomically swap ffmpeg.exe
            if old_ffmpeg_backup.exists():
                old_ffmpeg_backup.unlink(missing_ok=True)
            if final_ffmpeg.exists():
                try:
                    final_ffmpeg.rename(old_ffmpeg_backup)
                except Exception:
                    pass
            temp_ffmpeg.replace(final_ffmpeg)
            old_ffmpeg_backup.unlink(missing_ok=True)

            # Atomically swap ffprobe.exe if present
            if temp_ffprobe.exists():
                if old_ffprobe_backup.exists():
                    old_ffprobe_backup.unlink(missing_ok=True)
                if final_ffprobe.exists():
                    try:
                        final_ffprobe.rename(old_ffprobe_backup)
                    except Exception:
                        pass
                temp_ffprobe.replace(final_ffprobe)
                old_ffprobe_backup.unlink(missing_ok=True)

            FFmpegChecker._cached_result = None  # Reset cache
            _log_runtime(f"[FFMPEG SUCCESS] FFmpeg updated to {new_ver} at {final_ffmpeg}")
            return True, new_ver, ""

        except Exception as e:
            _log_runtime(f"[FFMPEG EXCEPTION] {e}")
            temp_zip.unlink(missing_ok=True)
            temp_ffmpeg.unlink(missing_ok=True)
            temp_ffprobe.unlink(missing_ok=True)
            if old_ffmpeg_backup.exists() and not final_ffmpeg.exists():
                try:
                    old_ffmpeg_backup.rename(final_ffmpeg)
                except Exception:
                    pass
            if old_ffprobe_backup.exists() and not final_ffprobe.exists():
                try:
                    old_ffprobe_backup.rename(final_ffprobe)
                except Exception:
                    pass
            return False, "", f"FFmpeg update failed: {e}"


# =============================================================================
# Background QThread Workers for UI Responsiveness
# =============================================================================

class CheckRuntimeWorker(QThread):
    """
    Background worker thread checking all 4 runtime components without blocking the GUI.
    """
    # Emits dict of {component_key: ComponentInfo}
    check_completed = Signal(dict)
    progress = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

    def run(self):
        self.progress.emit("Checking runtime updates...")
        results = RuntimeManager.check_all_updates()
        self.check_completed.emit(results)


class InstallRuntimeWorker(QThread):
    """
    Background worker thread installing updates for specified components.
    """
    # (component_key, success, new_ver, error_msg)
    component_finished = Signal(str, bool, str, str)
    # (total_success, total_failed)
    all_finished = Signal(int, int)
    progress = Signal(str, str)

    def __init__(self, components_to_update: List[str], is_download_active: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.components = list(components_to_update)
        self.is_download_active = is_download_active

    def run(self):
        success_count = 0
        fail_count = 0

        for key in self.components:
            self.progress.emit(key, "Updating...")
            success, new_ver, err = RuntimeManager.install_update(key, is_download_active=self.is_download_active)
            if success:
                success_count += 1
            else:
                fail_count += 1
            self.component_finished.emit(key, success, new_ver, err)

        self.all_finished.emit(success_count, fail_count)
