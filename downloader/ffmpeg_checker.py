"""
ffmpeg_checker.py
FFmpeg and FFprobe detection and verification utility for Windows.

Checks whether FFmpeg is available on the system for merging high-quality
separate video and audio streams from YouTube into MP4, MKV, or WEBM containers.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


from core.paths import get_bundled_executable


class FFmpegChecker:
    """
    Detects FFmpeg and FFprobe across locally bundled runtime folders,
    system PATH, or WinGet directories.
    """

    _cached_result: Optional[Tuple[bool, Optional[str], str, str]] = None

    @classmethod
    def detect(cls, force_refresh: bool = False) -> Tuple[bool, Optional[str], str, str]:
        """
        Detects FFmpeg availability.
        Priority:
        1. Bundled runtime directory (runtime/ffmpeg.exe or AppData runtime)
        2. System PATH
        3. Known common Windows installation locations

        Returns:
            Tuple of:
            (is_available: bool, ffmpeg_path: Optional[str], version_str: str, status_message: str)
        """
        if cls._cached_result is not None and not force_refresh:
            return cls._cached_result

        # 1. Check bundled executable first (Priority 1)
        bundled_ffmpeg = get_bundled_executable("ffmpeg.exe")
        ffmpeg_bin = str(bundled_ffmpeg) if bundled_ffmpeg else None

        # 2. Check system PATH (Priority 2)
        if not ffmpeg_bin:
            ffmpeg_bin = shutil.which("ffmpeg")

        # 3. Check known common Windows locations if not directly in PATH
        if not ffmpeg_bin:
            candidates = []
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                winget_pkg = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
                if winget_pkg.exists():
                    candidates.extend(winget_pkg.glob("**/ffmpeg.exe"))

            program_files = os.environ.get("ProgramFiles")
            if program_files:
                candidates.append(Path(program_files) / "ffmpeg" / "bin" / "ffmpeg.exe")

            # Check legacy relative directories
            script_dir = Path(__file__).resolve().parent.parent
            candidates.append(script_dir / "bin" / "ffmpeg.exe")
            candidates.append(script_dir / "resources" / "bin" / "ffmpeg.exe")

            for c in candidates:
                if c.exists() and os.access(str(c), os.X_OK):
                    ffmpeg_bin = str(c)
                    break


        if not ffmpeg_bin:
            result = (
                False,
                None,
                "Not Found",
                "FFmpeg is not installed. High-definition video and audio merging may be limited.",
            )
            cls._cached_result = result
            return result

        # 3. Retrieve version information
        version_str = "Unknown"
        try:
            startupinfo = None
            if os.name == "nt":
                # Hide console window popup on Windows
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            proc = subprocess.run(
                [ffmpeg_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                startupinfo=startupinfo,
            )
            if proc.returncode == 0 and proc.stdout:
                first_line = proc.stdout.splitlines()[0]
                match = re.search(r"version\s+([^\s]+)", first_line)
                if match:
                    version_str = match.group(1)
                else:
                    version_str = first_line[:30]
        except Exception as e:
            version_str = f"Installed ({str(e)})"

        status_msg = f"✓ Installed (v{version_str})"
        result = (True, ffmpeg_bin, version_str, status_msg)
        cls._cached_result = result
        return result

    @classmethod
    def get_ffmpeg_directory(cls) -> Optional[str]:
        """
        Returns the directory containing ffmpeg.exe, suitable for yt-dlp's
        ffmpeg_location option.
        """
        is_available, ffmpeg_path, _, _ = cls.detect()
        if is_available and ffmpeg_path:
            return str(Path(ffmpeg_path).parent)
        return None

    @classmethod
    def get_ffprobe_path(cls) -> Optional[str]:
        """Returns path to ffprobe.exe if available."""
        bundled_probe = get_bundled_executable("ffprobe.exe")
        if bundled_probe:
            return str(bundled_probe)

        ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            return ffprobe_bin

        is_available, ffmpeg_path, _, _ = cls.detect()
        if is_available and ffmpeg_path:
            sibling = Path(ffmpeg_path).parent / "ffprobe.exe"
            if sibling.exists():
                return str(sibling)
        return None

