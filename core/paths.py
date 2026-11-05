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


def patch_subprocess_utf8_default() -> None:
    """
    On Windows, Python defaults subprocess text mode to the ANSI codepage (e.g. cp1252),
    which crashes with UnicodeDecodeError (e.g. charmap can't decode 0x9d) when child
    processes (ffmpeg, ffprobe, yt-dlp, etc.) output UTF-8 text in reader threads.
    This guarantees that whenever text mode is requested without explicit encoding,
    it always safely defaults to encoding='utf-8', errors='replace'.
    """
    import subprocess
    if getattr(subprocess.Popen, "_is_utf8_patched", False):
        return

    _orig_popen_init = subprocess.Popen.__init__

    def _safe_popen_init(self, *args, **kwargs):
        is_text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") is not None
        if is_text:
            kwargs.setdefault("encoding", "utf-8")
            kwargs.setdefault("errors", "replace")
        return _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _safe_popen_init
    subprocess.Popen._is_utf8_patched = True


# Install patch immediately upon importing core.paths
patch_subprocess_utf8_default()


def setup_runtime_environment() -> None:
    """
    Initializes runtime environment:
    1. Ensures cwd, TEMP/TMP environment, and tempfile are safe, writable, and non-system32.
    2. Prepends %APPDATA%/ChannelHarvest/packages to sys.path so updated packages (e.g. yt-dlp) are loaded.
    3. Prepends runtime and user-runtime directories to system PATH for child processes.
    4. Guarantees subprocess text mode defaults to UTF-8 with replace error handling on Windows.
    """
    patch_subprocess_utf8_default()
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


# Characters illegal in Windows filenames / path components:
# < > : " / \ | ? * and ASCII control characters 0x00-0x1F, 0x7F-0x9F
WINDOWS_ILLEGAL_CHAR_REGEX = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]')

# Windows reserved device names (case-insensitive)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

MAX_COMPONENT_LENGTH = 255
MAX_WINDOWS_PATH = 260
DEFAULT_SAFE_TITLE_LENGTH = 120
DEFAULT_RESERVE_SUFFIX_LENGTH = 45


def sanitize_filename(
    name: str,
    max_length: int = DEFAULT_SAFE_TITLE_LENGTH,
    fallback: str = "Untitled",
) -> str:
    r"""
    Centralized Windows-safe filename sanitizer.
    1. Replaces Windows-invalid filename characters (< > : " / \ | ? *) with underscores.
    2. Strips and replaces ASCII control characters (0x00-0x1F, 0x7F-0x9F) and lone surrogates.
    3. Normalizes whitespace and strips trailing/leading periods and spaces.
    4. Guards against Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    5. Preserves legitimate Unicode text (Chinese, Japanese, Korean, Malay, emojis, accents).
    6. Safely bounds length while respecting character boundaries to prevent Windows MAX_PATH
       and 255-character component limits.
    7. Provides a deterministic, safe fallback when the sanitized title is empty.
    """
    if not name or not isinstance(name, str):
        return fallback or "Untitled"

    # Remove unpaired UTF-16 surrogate characters
    clean = re.sub(r'[\ud800-\udfff]', '', name)

    # Normalize newlines and tabs to spaces
    clean = re.sub(r'[\r\n\t]+', ' ', clean)

    # Replace Windows illegal characters and control characters with '_'
    clean = WINDOWS_ILLEGAL_CHAR_REGEX.sub('_', clean)

    # Collapse multiple consecutive spaces to a single space
    clean = re.sub(r' +', ' ', clean).strip()

    # Strip trailing dots and spaces (Windows strictly forbids trailing '.' or ' ')
    clean = clean.rstrip('. ')

    # Guard against Windows reserved device names
    # e.g. "CON", "aux.mp4", "NUL.txt", "com1"
    if clean:
        parts = clean.split('.', 1)
        base = parts[0].strip().upper()
        if base in WINDOWS_RESERVED_NAMES:
            if len(parts) > 1:
                clean = f"_{parts[0]}_.{parts[1]}"
            else:
                clean = f"_{clean}_"

    # Enforce max_length while avoiding cutting on trailing spaces or periods
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip('. ')

    # Re-check trailing characters after truncation
    clean = clean.rstrip('. ')

    # If completely empty or only underscores/spaces after sanitization, return safe fallback
    if not clean or not clean.strip('._ '):
        return fallback or "Untitled"

    return clean


def sanitize_path_component(
    name: str,
    max_length: int = 80,
    fallback: str = "folder",
) -> str:
    """
    Sanitizes directory names / path components (e.g. channel folder, video folder)
    to safe Windows length and character constraints.
    """
    return sanitize_filename(name, max_length=max_length, fallback=fallback)


def calculate_safe_stem_length(
    target_dir: Optional[Path] = None,
    suffix: str = "",
    ext: str = "",
    reserve_extra: int = 0,
    reserve_temp_len: int = DEFAULT_RESERVE_SUFFIX_LENGTH,
) -> int:
    """
    Computes a safe maximum title/stem length for the given target directory and output parameters.
    Guarantees:
    1. Single component limit: stem + suffix + ext + format_suffix + .part <= 255 chars.
    2. Path budget: full path length <= 260 chars whenever possible.
    """
    ext_len = len(ext.lstrip(".")) + 1 if ext else 0
    fixed_overhead = len(suffix) + ext_len + reserve_temp_len + reserve_extra

    # Ceiling from NTFS 255-character component limit
    component_budget = MAX_COMPONENT_LENGTH - fixed_overhead

    # Ceiling from standard Windows MAX_PATH (260 chars)
    if target_dir is not None:
        try:
            target_str = str(target_dir.resolve())
        except Exception:
            target_str = str(target_dir)
        path_budget = MAX_WINDOWS_PATH - 1 - len(target_str) - fixed_overhead
        safe_len = min(component_budget, path_budget, DEFAULT_SAFE_TITLE_LENGTH)
    else:
        safe_len = min(component_budget, DEFAULT_SAFE_TITLE_LENGTH)

    return max(30, safe_len)


def resolve_video_output_dir(
    base_download_dir: Path,
    channel_title: Optional[str],
    create_channel_folder: bool,
    video_title: str,
    video_id: str,
    create_individual_video_folders: bool,
    duplicate_titles_in_queue: Optional[Set[str]] = None,
    number_prefix: str = "",
    custom_folder_name: Optional[str] = None,
) -> Path:
    """
    Centralized resolver for video output directory.
    Hierarchy:
        download_root
            ↓ (if custom_folder_name or (create_channel_folder and channel_title))
        custom_folder or channel_subfolder
            ↓ (if create_individual_video_folders)
        individual_video_folder

    Collision Handling:
        If multiple videos in the queue share the same sanitized title,
        or if a directory already exists on disk containing files belonging to a
        different video ID, appends ' [VIDEO_ID]' to ensure deterministic isolation.
    """
    # 1. Base / Custom folder / Channel level (bounded safely to 80-120 chars)
    if custom_folder_name and custom_folder_name.strip():
        clean_custom = sanitize_path_component(custom_folder_name.strip(), max_length=120, fallback="custom_folder")
        parent_dir = base_download_dir / clean_custom
    elif create_channel_folder and channel_title:
        clean_channel = sanitize_path_component(channel_title, max_length=80, fallback="channel")
        parent_dir = base_download_dir / clean_channel
    else:
        parent_dir = base_download_dir

    if not create_individual_video_folders:
        return parent_dir

    # 2. Individual video folder level (bounded safely to 80 chars)
    prefix = number_prefix or ""
    fallback_folder = f"video_{video_id}" if video_id else "video"
    reserve_extra = len(prefix)
    clean_title = sanitize_path_component(video_title, max_length=max(30, 80 - reserve_extra), fallback=fallback_folder)
    folder_base = f"{prefix}{clean_title}"
    id_tagged_dir = parent_dir / f"{folder_base} [{video_id}]"

    # If this video already has an ID-tagged folder from a previous collision run, reuse it
    if id_tagged_dir.is_dir():
        return id_tagged_dir

    # Check duplicate in queue
    is_dup_in_queue = bool(
        duplicate_titles_in_queue
        and (video_title in duplicate_titles_in_queue or clean_title in duplicate_titles_in_queue or folder_base in duplicate_titles_in_queue)
    )

    candidate_dir = parent_dir / folder_base

    # Check collision on disk: if candidate_dir exists and contains files for another video ID
    collision_on_disk = False
    if candidate_dir.is_dir():
        try:
            for item in candidate_dir.iterdir():
                if item.is_file():
                    # Look for [video_id] pattern in existing filenames (supports YouTube, TikTok, Facebook IDs)
                    m = re.search(r'\[([a-zA-Z0-9_-]{6,32})\]', item.name)
                    if m and m.group(1) != video_id:
                        collision_on_disk = True
                        break
        except Exception:
            pass

    if is_dup_in_queue or collision_on_disk:
        folder_name = f"{folder_base} [{video_id}]"
    else:
        folder_name = folder_base

    return parent_dir / folder_name


def format_number_prefix(
    index: int,
    max_index: Optional[int] = None,
    pad_width: Optional[int] = None,
) -> str:
    """
    Formats a 1-based scan order index into a filename prefix (e.g. '01_', '02_').
    Supports numbers up to 6 digits (up to 999,999 and beyond).

    Padding width rules:
    - If pad_width is explicitly provided and >= 2, uses pad_width.
    - Otherwise, if max_index is provided and > 0, width is max(2, min(6, len(str(max_index)))).
    - Defaults to width 2 (e.g. 01 to 99).
    """
    if index is None or index <= 0:
        index = 1

    if pad_width is not None and pad_width >= 2:
        width = pad_width
    elif max_index is not None and max_index > 0:
        width = max(2, min(6, len(str(max_index))))
    else:
        width = 2

    return f"{index:0{width}d}_"


def resolve_media_filename(
    title: str,
    video_id: str,
    ext: str = "",
    include_video_id: bool = False,
    suffix: str = "",
    target_dir: Optional[Path] = None,
    number_prefix: str = "",
) -> str:
    """
    Centralized filename generator for all video-related outputs:
    media, subtitles, thumbnails, descriptions, metadata, chapters.

    When include_video_id is True: '<clean_title> [<video_id>]<suffix>.<ext>'
    When include_video_id is False: '<clean_title><suffix>.<ext>'
    If ext is empty, returns the stem without trailing dot.
    """
    prefix = number_prefix or ""
    reserve_for_id = len(f" [{video_id}]") if (include_video_id and video_id) else 0
    reserve_for_prefix = len(prefix)
    safe_title_len = calculate_safe_stem_length(
        target_dir=target_dir,
        suffix=suffix,
        ext=ext,
        reserve_extra=reserve_for_id + reserve_for_prefix,
    )
    fallback_title = f"video_{video_id}" if video_id else "Untitled"
    clean_title = sanitize_filename(title, max_length=safe_title_len, fallback=fallback_title)
    clean_title = clean_title.replace("#", "").replace("＃", "").strip() or fallback_title

    if include_video_id and video_id:
        stem = f"{prefix}{clean_title} [{video_id}]{suffix}"
    else:
        stem = f"{prefix}{clean_title}{suffix}"

    if ext:
        ext_clean = ext.lstrip(".")
        return f"{stem}.{ext_clean}"
    return stem


def resolve_video_outtmpl(
    target_dir: Path,
    include_video_id: bool = False,
    suffix: str = "",
    number_prefix: str = "",
    custom_title: Optional[str] = None,
) -> str:
    """
    Centralized yt-dlp outtmpl pattern generator.
    When custom_title is provided: uses sanitized custom_title (with all '#' stripped) instead of '%(title)s'.
    When number_prefix is provided: '<target_dir>/<number_prefix>%(title)s...'
    When include_video_id is True: '<target_dir>/%(title)s [%(id)s]<suffix>.%(ext)s'
    When include_video_id is False: '<target_dir>/%(title)s<suffix>.%(ext)s'
    """
    prefix = number_prefix or ""
    if custom_title:
        safe_custom = sanitize_filename(custom_title, max_length=DEFAULT_SAFE_TITLE_LENGTH, fallback="video")
        safe_custom = safe_custom.replace("%", "%%").replace("#", "").replace("＃", "").strip()
        title_tag = safe_custom or "video"
    else:
        title_tag = "%(title)s"

    if include_video_id:
        tmpl = f"{prefix}{title_tag} [%(id)s]{suffix}.%(ext)s"
    else:
        tmpl = f"{prefix}{title_tag}{suffix}.%(ext)s"
    return str(target_dir / tmpl)


def validate_output_path(
    target_dir: Path,
    filename: Optional[str] = None,
    check_writable: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Validates that target_dir and optional filename meet Windows filesystem requirements:
    1. Directory exists or can be created.
    2. Directory is not inside protected system roots (e.g. C:\\Windows, System32).
    3. Directory is writable by the current process.
    4. If filename is provided:
       - No single component exceeds MAX_COMPONENT_LENGTH (255 characters).
       - Filename does not contain illegal characters (<>:"/\\|?* or control chars).
       - Filename does not use a Windows reserved device name (CON, PRN, AUX, etc.).
       - Filename does not have trailing dots or spaces.
       - Total path length does not exceed MAX_WINDOWS_PATH (260 characters).
    Returns:
        (is_valid: bool, error_message: Optional[str])
    """
    if not target_dir:
        return False, "Target directory cannot be empty."

    if is_protected_system_dir(target_dir):
        return False, f"Target directory '{target_dir}' is a protected Windows system directory."

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"Cannot create directory '{target_dir}': {e}"

    if check_writable:
        probe = target_dir / f".ch_val_{os.getpid()}_{int(time.time() * 1000)}.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as e:
            return False, f"Directory '{target_dir}' is not writable: {e}"

    if filename:
        if len(filename) > MAX_COMPONENT_LENGTH:
            return False, f"Filename component exceeds Windows limit of {MAX_COMPONENT_LENGTH} characters (length={len(filename)}): '{filename[:30]}...'"

        if WINDOWS_ILLEGAL_CHAR_REGEX.search(filename):
            return False, f"Filename contains invalid Windows characters: '{filename}'"

        if filename.endswith(" ") or filename.endswith("."):
            return False, f"Filename cannot end with a period or space on Windows: '{filename}'"

        base = filename.split('.')[0].strip().upper()
        if base in WINDOWS_RESERVED_NAMES:
            return False, f"Filename uses a reserved Windows device name ({base}): '{filename}'"

        try:
            full_path_str = str((target_dir / filename).resolve())
        except Exception:
            full_path_str = str(target_dir / filename)

        if len(full_path_str) >= MAX_WINDOWS_PATH:
            return False, f"Full path exceeds Windows MAX_PATH ({MAX_WINDOWS_PATH} characters, length={len(full_path_str)}): '{full_path_str}'"

    return True, None


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


