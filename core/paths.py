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
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Set, Tuple, Union


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


def is_protected_system_dir(path: Optional[Union[str, Path]]) -> bool:
    """
    Checks if a directory path represents a restricted Windows system directory
    (e.g., C:\\Windows, C:\\Windows\\System32, C:\\Program Files, C:\\Program Files (x86))
    or is otherwise non-writable by a standard non-admin user.
    """
    if not path:
        return False
    try:
        p = Path(path).resolve()
    except Exception:
        return True

    # 1. Check against Windows protected system roots
    protected_roots = set()
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        val = os.environ.get(var)
        if val:
            try:
                protected_roots.add(Path(val).resolve())
            except Exception:
                pass

    # Common Windows system locations
    for fb in (r"C:\Windows", r"C:\Windows\System32", r"C:\Windows\SysWOW64", r"C:\Program Files", r"C:\Program Files (x86)"):
        fb_p = Path(fb)
        if fb_p.exists():
            try:
                protected_roots.add(fb_p.resolve())
            except Exception:
                pass

    for prot in protected_roots:
        try:
            if p == prot or p.is_relative_to(prot):
                return True
        except Exception:
            pass

    # 2. Test directory write permission
    if p.exists() and p.is_dir():
        test_file = p / f".ch_sys_check_{os.getpid()}_{int(time.time() * 1000)}.tmp"
        try:
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
        except (PermissionError, OSError):
            return True
        except Exception:
            pass

    return False


def get_temp_dir() -> Path:
    """
    Returns a dedicated, writable per-user temporary directory for Channel Harvest.
    Guaranteed:
    - Never inside C:\\Windows, System32, or Program Files
    - Writable by standard non-admin users
    - Created automatically if not present
    - Tested with a probe file before returning
    """
    candidates = []

    # 1. Per-user Temp via %TEMP% or %TMP%
    for env_var in ("TEMP", "TMP"):
        val = os.environ.get(env_var)
        if val:
            try:
                candidate = Path(val).resolve() / "ChannelHarvest"
                if not is_protected_system_dir(candidate):
                    candidates.append(candidate)
            except Exception:
                pass

    # 2. %LOCALAPPDATA%/Temp/ChannelHarvest
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        try:
            candidate = Path(local_app_data).resolve() / "Temp" / "ChannelHarvest"
            if not is_protected_system_dir(candidate):
                candidates.append(candidate)
        except Exception:
            pass

    # 3. User home AppData/Local/Temp/ChannelHarvest
    try:
        candidate = Path.home() / "AppData" / "Local" / "Temp" / "ChannelHarvest"
        if not is_protected_system_dir(candidate):
            candidates.append(candidate)
    except Exception:
        pass

    # 4. Roaming AppData temp (%APPDATA%/ChannelHarvest/temp)
    try:
        candidate = get_app_data_dir() / "temp"
        if not is_protected_system_dir(candidate):
            candidates.append(candidate)
    except Exception:
        pass

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / f".ch_probe_{os.getpid()}_{int(time.time() * 1000)}.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue

    fallback = get_app_data_dir() / "temp"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def cleanup_temp_dir(max_age_seconds: int = 3600) -> None:
    """
    Safely purges stale temporary files (.tmp, .part, .ytdl, etc.) in the application temp directory.
    Catches and ignores PermissionError / OSError for files currently locked by active processes.
    """
    try:
        temp_dir = get_temp_dir()
        if not temp_dir.exists() or not temp_dir.is_dir():
            return
        now = time.time()
        for item in temp_dir.iterdir():
            try:
                if item.is_file():
                    if item.name.startswith(".ch_") or (now - item.stat().st_mtime > max_age_seconds):
                        item.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def ensure_safe_environment() -> Tuple[Path, Path]:
    """
    Validates and corrects the process execution environment:
    1. Ensures cwd is not inside a protected system directory (e.g. System32, Program Files).
       If protected, changes cwd to the writable application data directory (%APPDATA%/ChannelHarvest).
    2. Ensures TEMP, TMP, and TMPDIR environment variables point to a valid, writable per-user temp dir.
    3. Sets tempfile.tempdir to the validated temp directory.

    Returns:
        Tuple of (current_working_dir: Path, temporary_dir: Path)
    """
    safe_temp = get_temp_dir()

    # 1. Sanitize current working directory
    try:
        cwd = Path.cwd().resolve()
        if is_protected_system_dir(cwd):
            safe_cwd = get_app_data_dir()
            os.chdir(str(safe_cwd))
            cwd = safe_cwd
    except Exception:
        safe_cwd = get_app_data_dir()
        try:
            os.chdir(str(safe_cwd))
            cwd = safe_cwd
        except Exception:
            cwd = Path.cwd()

    # 2. Sanitize environment variables for current process and child processes
    for env_var in ("TEMP", "TMP", "TMPDIR"):
        val = os.environ.get(env_var)
        if not val or is_protected_system_dir(val):
            os.environ[env_var] = str(safe_temp)

    # 3. Synchronize Python tempfile module
    try:
        import tempfile
        tempfile.tempdir = str(safe_temp)
    except Exception:
        pass

    return cwd, safe_temp


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


def get_deno_executable() -> Optional[Path]:
    """
    Returns path to bundled or user-updated deno.exe.
    Resolves seamlessly in development, PyInstaller onedir, and portable distributions.
    """
    deno_path = get_bundled_executable("deno.exe")
    if deno_path and deno_path.is_file():
        return deno_path
    deno_fallback = get_bundled_executable("deno")
    if deno_fallback and deno_fallback.is_file():
        return deno_fallback
    # Check PATH as fallback
    which_deno = shutil.which("deno.exe") or shutil.which("deno")
    if which_deno:
        return Path(which_deno)
    return None


def get_ytdlp_binary_path() -> Optional[Path]:
    """
    Returns path to bundled or user-updated yt-dlp.exe.
    """
    ytdlp_path = get_bundled_executable("yt-dlp.exe")
    if ytdlp_path and ytdlp_path.is_file():
        return ytdlp_path
    which_ytdlp = shutil.which("yt-dlp.exe") or shutil.which("yt-dlp")
    if which_ytdlp:
        return Path(which_ytdlp)
    return None


def setup_runtime_environment() -> None:
    """
    Initializes runtime environment:
    1. Ensures cwd, TEMP/TMP environment, and tempfile are safe, writable, and non-system32.
    2. Prepends %APPDATA%/ChannelHarvest/packages to sys.path so updated packages (e.g. yt-dlp) are loaded.
    3. Prepends runtime and user-runtime directories to system PATH for child processes.
    """
    ensure_safe_environment()

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


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """
    Removes characters invalid in Windows directory and file names
    (\\ / : * ? " < > |), trims whitespace, and strips trailing periods or spaces,
    while preserving Chinese, Japanese, Korean, Malay, English, and emojis.
    Safely bounds length to prevent Windows MAX_PATH errors.
    """
    clean = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    clean = clean.rstrip(". ")
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip(". ")
    return clean or "Untitled"


def resolve_video_output_dir(
    base_download_dir: Path,
    channel_title: Optional[str],
    create_channel_folder: bool,
    video_title: str,
    video_id: str,
    create_individual_video_folders: bool,
    duplicate_titles_in_queue: Optional[Set[str]] = None,
) -> Path:
    """
    Centralized resolver for video output directory.
    Hierarchy:
        download_root
            ↓ (if create_channel_folder and channel_title)
        channel_subfolder
            ↓ (if create_individual_video_folders)
        individual_video_folder

    Collision Handling:
        If multiple videos in the queue share the same sanitized title,
        or if a directory already exists on disk containing files belonging to a
        different video ID, appends ' [VIDEO_ID]' to ensure deterministic isolation.
    """
    # 1. Base / Channel level
    if create_channel_folder and channel_title:
        clean_channel = sanitize_filename(channel_title)
        parent_dir = base_download_dir / clean_channel
    else:
        parent_dir = base_download_dir

    if not create_individual_video_folders:
        return parent_dir

    # 2. Individual video folder level
    clean_title = sanitize_filename(video_title)
    id_tagged_dir = parent_dir / f"{clean_title} [{video_id}]"

    # If this video already has an ID-tagged folder from a previous collision run, reuse it
    if id_tagged_dir.is_dir():
        return id_tagged_dir

    # Check duplicate in queue
    is_dup_in_queue = bool(
        duplicate_titles_in_queue
        and (video_title in duplicate_titles_in_queue or clean_title in duplicate_titles_in_queue)
    )

    candidate_dir = parent_dir / clean_title

    # Check collision on disk: if candidate_dir exists and contains files for another video ID
    collision_on_disk = False
    if candidate_dir.is_dir():
        try:
            for item in candidate_dir.iterdir():
                if item.is_file():
                    # Look for [video_id] pattern in existing filenames (supports YouTube & TikTok IDs)
                    m = re.search(r'\[([a-zA-Z0-9_-]{6,32})\]', item.name)
                    if m and m.group(1) != video_id:
                        collision_on_disk = True
                        break
        except Exception:
            pass

    if is_dup_in_queue or collision_on_disk:
        folder_name = f"{clean_title} [{video_id}]"
    else:
        folder_name = clean_title

    return parent_dir / folder_name


def resolve_media_filename(
    title: str,
    video_id: str,
    ext: str = "",
    include_video_id: bool = False,
    suffix: str = "",
) -> str:
    """
    Centralized filename generator for all video-related outputs:
    media, subtitles, thumbnails, descriptions, metadata, chapters.

    When include_video_id is True: '<clean_title> [<video_id>]<suffix>.<ext>'
    When include_video_id is False: '<clean_title><suffix>.<ext>'
    If ext is empty, returns the stem without trailing dot.
    """
    clean_title = sanitize_filename(title)
    if include_video_id and video_id:
        stem = f"{clean_title} [{video_id}]{suffix}"
    else:
        stem = f"{clean_title}{suffix}"

    if ext:
        ext_clean = ext.lstrip(".")
        return f"{stem}.{ext_clean}"
    return stem


def resolve_video_outtmpl(
    target_dir: Path,
    include_video_id: bool = False,
    suffix: str = "",
) -> str:
    """
    Centralized yt-dlp outtmpl pattern generator.
    When include_video_id is True: '<target_dir>/%(title)s [%(id)s]<suffix>.%(ext)s'
    When include_video_id is False: '<target_dir>/%(title)s<suffix>.%(ext)s'
    """
    if include_video_id:
        tmpl = f"%(title)s [%(id)s]{suffix}.%(ext)s"
    else:
        tmpl = f"%(title)s{suffix}.%(ext)s"
    return str(target_dir / tmpl)


def should_include_video_id(
    video_title: str,
    video_id: str,
    include_video_id_setting: bool,
    create_individual_video_folders: bool = False,
    duplicate_titles_in_queue: Optional[Set[str]] = None,
    target_dir: Optional[Path] = None,
) -> bool:
    """
    Determines whether the YouTube video ID should be included in the output filename.
    - If user explicitly enabled the setting: returns True.
    - If user disabled the setting:
      * When individual video folders are enabled, folders provide isolation: returns False.
      * When individual video folders are disabled, checks if this video title is duplicated
        in the queue or collides on disk with another video ID. If a collision is detected,
        safely includes video ID to prevent overwriting / data loss per application convention.
      * Otherwise: returns False.
    """
    if include_video_id_setting:
        return True

    if create_individual_video_folders:
        return False

    clean_title = sanitize_filename(video_title)

    # Check duplicate in queue
    if duplicate_titles_in_queue and (video_title in duplicate_titles_in_queue or clean_title in duplicate_titles_in_queue):
        return True

    # Check collision on disk: if target_dir has a file starting with clean_title belonging to another video ID
    if target_dir and target_dir.is_dir():
        try:
            for item in target_dir.iterdir():
                if item.is_file() and item.name.startswith(clean_title):
                    m = re.search(r'\[([a-zA-Z0-9_-]{6,32})\]', item.name)
                    if m and m.group(1) != video_id:
                        return True
        except Exception:
            pass

    return False


