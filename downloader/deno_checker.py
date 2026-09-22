"""
deno_checker.py
Deno JavaScript runtime detection and verification utility for Channel Harvest.

Detects whether Deno is available to yt-dlp for solving YouTube JavaScript challenges (EJS)
without triggering console popups on Windows.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from core.paths import get_deno_executable


class DenoChecker:
    """
    Detects Deno JavaScript runtime across locally bundled runtime folder,
    system PATH, and user environments.
    """

    _cached_result: Optional[Tuple[bool, Optional[str], str, str]] = None

    @classmethod
    def detect(cls, force_refresh: bool = False) -> Tuple[bool, Optional[str], str, str]:
        """
        Detects Deno availability.
        Priority:
        1. Bundled runtime directory (runtime/deno.exe or AppData runtime)
        2. System PATH
        3. Common user directory (%USERPROFILE%/.deno/bin/deno.exe)

        Returns:
            Tuple of:
            (is_available: bool, deno_path: Optional[str], version_str: str, status_message: str)
        """
        if cls._cached_result is not None and not force_refresh:
            return cls._cached_result

        # 1. Check bundled executable first
        bundled_deno = get_deno_executable()
        deno_bin = str(bundled_deno) if bundled_deno else None

        # 2. Check user profile .deno/bin
        if not deno_bin:
            user_profile = os.environ.get("USERPROFILE")
            if user_profile:
                candidate = Path(user_profile) / ".deno" / "bin" / "deno.exe"
                if candidate.is_file():
                    deno_bin = str(candidate)

        # 3. Check system PATH
        if not deno_bin:
            deno_bin = shutil.which("deno.exe") or shutil.which("deno")

        if not deno_bin or not Path(deno_bin).is_file():
            cls._cached_result = (
                False,
                None,
                "",
                "Deno JavaScript runtime not found. YouTube may rate-limit extraction without it.",
            )
            return cls._cached_result

        # Validate executable and query version
        try:
            creation_flags = 0
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW

            proc = subprocess.run(
                [deno_bin, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
                creationflags=creation_flags,
            )

            if proc.returncode == 0 and proc.stdout:
                first_line = proc.stdout.strip().splitlines()[0]
                m = re.search(r"deno\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", first_line, re.IGNORECASE)
                version_str = m.group(1) if m else "2.x"
                cls._cached_result = (
                    True,
                    deno_bin,
                    version_str,
                    f"Deno v{version_str} ready",
                )
                return cls._cached_result

        except Exception as e:
            cls._cached_result = (
                False,
                deno_bin,
                "",
                f"Found deno.exe at {deno_bin} but failed to execute: {e}",
            )
            return cls._cached_result

        cls._cached_result = (
            False,
            deno_bin,
            "",
            f"Deno at {deno_bin} returned non-zero exit code.",
        )
        return cls._cached_result

    @classmethod
    def is_available(cls) -> bool:
        """Convenience method returning True if Deno is usable."""
        is_ok, _, _, _ = cls.detect()
        return is_ok

    @classmethod
    def get_deno_path(cls) -> Optional[str]:
        """Convenience method returning the executable path if available."""
        is_ok, path, _, _ = cls.detect()
        return path if is_ok else None

    @classmethod
    def get_version(cls) -> str:
        """Returns the version string (e.g. '2.9.7') or empty string."""
        _, _, ver, _ = cls.detect()
        return ver
