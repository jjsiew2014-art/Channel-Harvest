"""
auth_checker.py
Stage-aware YouTube authentication and browser cookie verification module for Channel Harvest.

Provides step-by-step diagnostic verification:
Stage 1: Browser Detection (Checks executable / profile presence)
Stage 2: Cookie Database Access (Detects file locks / running processes)
Stage 3: Cookie Decryption & Extraction (Evidence-based DPAPI / App-Bound detection)
Stage 4: YouTube Cookie Verification (Inspects session & login tokens)
Stage 5: YouTube Live Request Verification (Lightweight authenticated query)

Guarantees strict privacy: zero cookie values, tokens, or personal paths are exposed.
"""

import os
import sys
import tempfile
import sqlite3
import shutil
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Set, List, Dict, Any

from core.diagnostics import PrivacySanitizer
from core.version import __version__


# =============================================================================
# Stage & Status Definitions
# =============================================================================

class AuthStage:
    BROWSER_DETECTION = "Browser Detection"
    DATABASE_ACCESS = "Cookie Database Access"
    COOKIE_DECRYPTION = "Browser Cookie Decryption"
    COOKIE_EXTRACTION = "YouTube Cookie Verification"
    YOUTUBE_REQUEST = "YouTube Request"
    COMPLETE = "Verification Complete"


class AuthStatusCode:
    NOT_CONFIGURED = "NOT_CONFIGURED"
    BROWSER_COOKIE_EXTRACTION_SUCCESS = "BROWSER_COOKIE_EXTRACTION_SUCCESS"
    COOKIE_DECRYPTION_FAILED = "COOKIE_DECRYPTION_FAILED"
    COOKIE_FILE_VALID = "COOKIE_FILE_VALID"
    COOKIE_FILE_INVALID = "COOKIE_FILE_INVALID"
    YOUTUBE_SESSION_AUTHENTICATED = "YOUTUBE_SESSION_AUTHENTICATED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    BOT_VERIFICATION_REQUIRED = "BOT_VERIFICATION_REQUIRED"
    NO_YOUTUBE_COOKIES = "NO_YOUTUBE_COOKIES"
    AUTHENTICATION_TEST_FAILED = "AUTHENTICATION_TEST_FAILED"
    UNKNOWN_AUTHENTICATION_ERROR = "UNKNOWN_AUTHENTICATION_ERROR"

    # Backward compatibility aliases
    SUCCESS = "YOUTUBE_SESSION_AUTHENTICATED"
    BROWSER_NOT_FOUND = "BROWSER_NOT_FOUND"
    DATABASE_LOCKED = "DATABASE_LOCKED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    YOUTUBE_AUTH_REJECTED = "AUTHENTICATION_REQUIRED"
    UNKNOWN_ERROR = "UNKNOWN_AUTHENTICATION_ERROR"


# Essential YouTube session authentication cookie names
YOUTUBE_AUTH_COOKIE_NAMES: Set[str] = {
    "LOGIN_INFO",
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}

# Browser process executables mapping
BROWSER_PROCESS_MAP: Dict[str, List[str]] = {
    "chrome": ["chrome.exe"],
    "edge": ["msedge.exe"],
    "brave": ["brave.exe"],
    "firefox": ["firefox.exe"],
    "opera": ["opera.exe"],
    "vivaldi": ["vivaldi.exe"],
}


@dataclass
class AuthTestResult:
    """Structured result of an authentication verification attempt."""
    success: bool
    stage: str
    status_code: str
    browser_name: str
    auth_method: str = ""
    profile_name: str = "Default"
    cookie_count: int = 0
    youtube_cookie_count: int = 0
    has_session: bool = False
    reason: str = ""
    suggested_action: str = ""
    technical_error: str = ""
    raw_error: str = ""
    browser_running: bool = False
    is_app_bound: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.auth_method:
            b_low = str(self.browser_name).lower()
            if b_low in ("custom cookie file", "custom_file") or b_low.endswith(".txt"):
                self.auth_method = "Custom Cookie File"
            elif self.status_code == AuthStatusCode.NOT_CONFIGURED or b_low in ("none", ""):
                self.auth_method = "None"
            else:
                self.auth_method = "Browser Cookies"

    def to_diagnostic_report(self, ytdlp_version: Optional[str] = None) -> str:
        """
        Generates a clean, standardized, sanitized troubleshooting report
        strictly adhering to privacy boundaries (no cookies, tokens, or private paths).
        """
        if ytdlp_version is None:
            try:
                import yt_dlp
                ytdlp_version = getattr(yt_dlp.version, "__version__", "Unknown")
            except Exception:
                ytdlp_version = "Unknown"

        # Check process elevation
        is_elevated = False
        try:
            if sys.platform == "win32":
                is_elevated = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            pass
        elevation_str = "Elevated (Administrator)" if is_elevated else "Standard User (Not Elevated)"

        # User context (masked/sanitized)
        user_name = os.environ.get("USERNAME", "Unknown")
        user_context = PrivacySanitizer.sanitize_message(f"User: {user_name}")

        tech_err = PrivacySanitizer.sanitize_message(self.technical_error or self.raw_error or "None")

        lines = [
            "Channel Harvest Authentication Diagnostic",
            "========================================",
            f"Timestamp:              {self.timestamp}",
            f"App Version:            {__version__}",
            f"yt-dlp Version:         {ytdlp_version}",
            f"Authentication Method:  {self.auth_method}",
            f"Browser / Source:       {self.browser_name}",
            f"Browser Profile:        {self.profile_name}",
            f"Stage:                  {self.stage}",
            f"Status Code:            {self.status_code}",
            f"Cookies Extracted:      {self.cookie_count}",
            f"YouTube Cookies:        {self.youtube_cookie_count}",
            f"Session Authenticated:  {'Yes' if self.has_session else 'No'}",
            f"Browser Process Running:{'Yes' if self.browser_running else 'No'}",
            f"Elevation:              {elevation_str}",
            f"User Context:           {user_context}",
            "",
            f"Reason:                 {self.reason}",
            f"Suggested Action:       {self.suggested_action}",
            "",
            "Technical Error:",
            f"{tech_err}",
            "========================================",
            "Note: All session tokens, cookies, and personal paths have been sanitized."
        ]
        return "\n".join(lines)



# =============================================================================
# Process & System Probes
# =============================================================================

def is_browser_process_running(browser_name: str) -> bool:
    """Checks if executable processes for the target browser are currently running on Windows."""
    if sys.platform != "win32":
        return False

    exe_targets = BROWSER_PROCESS_MAP.get(browser_name.lower(), [])
    if not exe_targets:
        return False

    exe_targets_lower = {e.lower() for e in exe_targets}

    # Use Toolhelp32 snapshot via ctypes for lightweight, 0-dependency check
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_wchar * 260)
        ]

    try:
        snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return False
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        found = False
        if ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.lower() in exe_targets_lower:
                    found = True
                    break
                if not ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        ctypes.windll.kernel32.CloseHandle(snap)
        return found
    except Exception:
        return False


def get_browser_database_path(browser_name: str, profile: Optional[str] = None) -> Optional[Path]:
    """Locates the primary cookie database file for a supported browser."""
    b_name = browser_name.lower().strip()
    if sys.platform != "win32":
        return None

    appdata_local = os.environ.get("LOCALAPPDATA", "")
    appdata_roaming = os.environ.get("APPDATA", "")

    if b_name == "chrome":
        root = Path(appdata_local) / "Google" / "Chrome" / "User Data"
        prof = profile or "Default"
        cand = root / prof / "Network" / "Cookies"
        if cand.is_file():
            return cand
        cand_legacy = root / prof / "Cookies"
        if cand_legacy.is_file():
            return cand_legacy
        return root

    elif b_name == "edge":
        root = Path(appdata_local) / "Microsoft" / "Edge" / "User Data"
        prof = profile or "Default"
        cand = root / prof / "Network" / "Cookies"
        if cand.is_file():
            return cand
        cand_legacy = root / prof / "Cookies"
        if cand_legacy.is_file():
            return cand_legacy
        return root

    elif b_name == "brave":
        root = Path(appdata_local) / "BraveSoftware" / "Brave-Browser" / "User Data"
        prof = profile or "Default"
        cand = root / prof / "Network" / "Cookies"
        if cand.is_file():
            return cand
        cand_legacy = root / prof / "Cookies"
        if cand_legacy.is_file():
            return cand_legacy
        return root

    elif b_name == "opera":
        root = Path(appdata_roaming) / "Opera Software" / "Opera Stable"
        cand = root / "Network" / "Cookies"
        if cand.is_file():
            return cand
        cand_legacy = root / "Cookies"
        if cand_legacy.is_file():
            return cand_legacy
        return root

    elif b_name == "vivaldi":
        root = Path(appdata_local) / "Vivaldi" / "User Data"
        prof = profile or "Default"
        cand = root / prof / "Network" / "Cookies"
        if cand.is_file():
            return cand
        cand_legacy = root / prof / "Cookies"
        if cand_legacy.is_file():
            return cand_legacy
        return root

    elif b_name == "firefox":
        root = Path(appdata_roaming) / "Mozilla" / "Firefox" / "Profiles"
        if root.is_dir():
            for p in root.glob("*"):
                cand = p / "cookies.sqlite"
                if cand.is_file():
                    return cand
        return root

    return None


def get_browser_profiles(browser_name: str) -> List[str]:
    """Discovers available user profiles for the specified browser on Windows."""
    b_name = (browser_name or "").lower().strip()
    if sys.platform != "win32":
        return ["Default"]

    appdata_local = os.environ.get("LOCALAPPDATA", "")
    appdata_roaming = os.environ.get("APPDATA", "")
    profiles = []

    try:
        user_data_path = None
        if b_name == "chrome":
            user_data_path = Path(appdata_local) / "Google" / "Chrome" / "User Data"
        elif b_name == "edge":
            user_data_path = Path(appdata_local) / "Microsoft" / "Edge" / "User Data"
        elif b_name == "brave":
            user_data_path = Path(appdata_local) / "BraveSoftware" / "Brave-Browser" / "User Data"
        elif b_name == "vivaldi":
            user_data_path = Path(appdata_local) / "Vivaldi" / "User Data"
        elif b_name == "opera":
            user_data_path = Path(appdata_roaming) / "Opera Software" / "Opera Stable"
        elif b_name == "firefox":
            ff_root = Path(appdata_roaming) / "Mozilla" / "Firefox" / "Profiles"
            if ff_root.is_dir():
                for p in sorted(ff_root.glob("*")):
                    if p.is_dir() and (p / "cookies.sqlite").exists():
                        profiles.append(p.name)
            return profiles or ["Default"]

        if user_data_path and user_data_path.is_dir():
            if (user_data_path / "Default").is_dir():
                profiles.append("Default")
            for p in sorted(user_data_path.glob("Profile *")):
                if p.is_dir():
                    profiles.append(p.name)
    except Exception:
        pass

    return profiles or ["Default"]


# =============================================================================
# Stage-Aware Authentication Tester
# =============================================================================

class AuthChecker:
    """
    Coordinates and executes stage-by-stage authentication verification:
    1. Browser Detection
    2. Database Access
    3. Cookie Decryption
    4. Cookie Verification
    5. YouTube Live Request
    """

    _cookie_file_cache: Dict[str, Tuple[float, int, Dict[str, Any]]] = {}

    @classmethod
    def invalidate_cookie_file_cache(cls) -> None:
        """Clears the cached cookie file validation results."""
        cls._cookie_file_cache.clear()

    @classmethod
    def validate_cookie_file(cls, file_path_str: Optional[str]) -> Dict[str, Any]:
        """
        Performs synchronous, non-destructive validation of an exported cookie file.
        Checks: file exists, readable, non-empty, Netscape format, and YouTube cookies.
        Strict privacy: NEVER returns or logs raw cookie values.
        """
        if not file_path_str or not file_path_str.strip():
            return {
                "is_valid": False,
                "status_code": AuthStatusCode.COOKIE_FILE_INVALID,
                "message": "No cookie file selected.",
                "cookie_count": 0,
                "youtube_cookie_count": 0,
                "has_session": False,
            }

        p = Path(file_path_str.strip())
        if not p.is_file():
            return {
                "is_valid": False,
                "status_code": AuthStatusCode.BROWSER_NOT_FOUND,
                "message": "The specified cookie file does not exist on disk.",
                "cookie_count": 0,
                "youtube_cookie_count": 0,
                "has_session": False,
            }

        try:
            stat_res = p.stat()
            if stat_res.st_size == 0:
                return {
                    "is_valid": False,
                    "status_code": AuthStatusCode.COOKIE_FILE_INVALID,
                    "message": "The cookie file is empty.",
                    "cookie_count": 0,
                    "youtube_cookie_count": 0,
                    "has_session": False,
                }
            cache_key = str(p.resolve())
            mtime = stat_res.st_mtime
            size = stat_res.st_size
            if cache_key in cls._cookie_file_cache:
                c_mtime, c_size, c_res = cls._cookie_file_cache[cache_key]
                if c_mtime == mtime and c_size == size:
                    return c_res.copy()
        except Exception as e:
            return {
                "is_valid": False,
                "status_code": AuthStatusCode.DATABASE_LOCKED,
                "message": f"Cannot access cookie file: {e}",
                "cookie_count": 0,
                "youtube_cookie_count": 0,
                "has_session": False,
            }

        jar, parse_err = cls._load_cookie_file(p)
        if parse_err or not jar or len(jar) == 0:
            res = {
                "is_valid": False,
                "status_code": AuthStatusCode.COOKIE_FILE_INVALID,
                "message": "This does not appear to be a valid cookies.txt file.",
                "cookie_count": 0,
                "youtube_cookie_count": 0,
                "has_session": False,
            }
            cls._cookie_file_cache[cache_key] = (mtime, size, res.copy())
            return res

        total_cookies = len(jar)
        yt_cookies, has_session = cls._inspect_youtube_cookies(jar)
        yt_count = len(yt_cookies)

        if yt_count == 0:
            res = {
                "is_valid": False,
                "status_code": AuthStatusCode.NO_YOUTUBE_COOKIES,
                "message": "Cookie file parsed, but contains no YouTube or Google cookies.",
                "cookie_count": total_cookies,
                "youtube_cookie_count": 0,
                "has_session": False,
            }
            cls._cookie_file_cache[cache_key] = (mtime, size, res.copy())
            return res

        session_str = "YouTube session detected" if has_session else "YouTube cookies found (no login session)"
        res = {
            "is_valid": True,
            "status_code": AuthStatusCode.COOKIE_FILE_VALID,
            "message": f"✓ Cookie file detected ({yt_count} YouTube cookies, {session_str})",
            "cookie_count": total_cookies,
            "youtube_cookie_count": yt_count,
            "has_session": has_session,
        }
        cls._cookie_file_cache[cache_key] = (mtime, size, res.copy())
        return res

    @classmethod
    def test_authentication(
        cls,
        browser_or_file: str,
        custom_cookie_path: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> AuthTestResult:
        """
        Runs the full stage-aware test on the selected browser or cookie file.
        Returns a rich AuthTestResult with exact stage and actionable guidance.
        """
        target = (browser_or_file or "").strip()
        if target.lower() in ("none", ""):
            return AuthTestResult(
                success=True,
                stage=AuthStage.COMPLETE,
                status_code=AuthStatusCode.NOT_CONFIGURED,
                browser_name="None",
                auth_method="None",
                profile_name="N/A",
                reason="Authentication is not configured.",
                suggested_action="Public YouTube downloads will proceed without authentication.",
                technical_error="",
            )

        is_custom_file = (target.lower() == "custom_file") or (target.lower().endswith(".txt"))
        effective_file_path = custom_cookie_path if target.lower() == "custom_file" else target

        if is_custom_file:
            return cls._test_cookie_file(effective_file_path)
        else:
            return cls._test_browser(target, profile=profile)

    # -------------------------------------------------------------------------
    # Browser Verification Flow
    # -------------------------------------------------------------------------

    @classmethod
    def _test_browser(cls, browser_name: str, profile: Optional[str] = None) -> AuthTestResult:
        b_name = browser_name.lower().strip()
        display_name = browser_name.capitalize()
        prof_name = profile or "Default"
        running = is_browser_process_running(b_name)

        # ---------------------------------------------------------------------
        # STAGE 1: Browser Detection
        # ---------------------------------------------------------------------
        db_path = get_browser_database_path(b_name, profile=prof_name)
        if not db_path or not db_path.exists():
            return AuthTestResult(
                success=False,
                stage=AuthStage.BROWSER_DETECTION,
                status_code=AuthStatusCode.BROWSER_NOT_FOUND,
                browser_name=display_name,
                profile_name=prof_name,
                browser_running=running,
                reason=f"No installation or user profile directory was found for {display_name} on this computer.",
                suggested_action=f"Ensure {display_name} is installed and has been run under your Windows user account, or select 'Custom Cookie File (cookies.txt)' in Settings.",
                technical_error=f"Browser path does not exist: {db_path or 'None'}",
            )

        # ---------------------------------------------------------------------
        # STAGE 2: Cookie Database Access (Check lock without hardcoding closed rule)
        # ---------------------------------------------------------------------
        if db_path.is_file():
            is_locked, lock_err = cls._probe_database_lock(db_path)
            if is_locked:
                return AuthTestResult(
                    success=False,
                    stage=AuthStage.DATABASE_ACCESS,
                    status_code=AuthStatusCode.DATABASE_LOCKED,
                    browser_name=display_name,
                    profile_name=prof_name,
                    browser_running=running,
                    reason=f"The {display_name} cookie database is locked by another process (typically because {display_name} is running).",
                    suggested_action=f"Completely close all {display_name} browser windows and background processes, or use an exported cookies.txt file.",
                    technical_error=lock_err,
                )

        # ---------------------------------------------------------------------
        # STAGE 3: Cookie Decryption & Extraction
        # ---------------------------------------------------------------------
        jar, decrypt_err, is_abe, is_lock_err = cls._extract_browser_cookies(b_name, profile=prof_name)

        if is_lock_err:
            return AuthTestResult(
                success=False,
                stage=AuthStage.DATABASE_ACCESS,
                status_code=AuthStatusCode.DATABASE_LOCKED,
                browser_name=display_name,
                profile_name=prof_name,
                browser_running=running,
                reason=f"The {display_name} cookie database is locked by Windows while the browser is running.",
                suggested_action=f"Completely close all {display_name} browser processes, or export cookies to a cookies.txt file.",
                technical_error=decrypt_err,
            )

        if decrypt_err:
            if "Failed to decrypt with DPAPI" in decrypt_err or is_abe:
                reason_msg = (
                    f"Channel Harvest could not decrypt the cookies stored by {display_name}. "
                    f"Modern Chromium browsers (Chrome 127+, Edge, Brave) utilize App-Bound Encryption, "
                    f"which protects browser cookies from access by external applications. "
                    f"Your YouTube login may still be working normally in {display_name}."
                )
                suggested_msg = (
                    f"Recommended solution: Export your YouTube cookies as a cookies.txt file "
                    f"(using a browser extension such as 'Get cookies.txt LOCALLY') and select it under Custom Cookie File in Settings."
                )
                return AuthTestResult(
                    success=False,
                    stage=AuthStage.COOKIE_DECRYPTION,
                    status_code=AuthStatusCode.COOKIE_DECRYPTION_FAILED,
                    browser_name=display_name,
                    profile_name=prof_name,
                    browser_running=running,
                    is_app_bound=is_abe,
                    reason=reason_msg,
                    suggested_action=suggested_msg,
                    technical_error=decrypt_err,
                )
            else:
                return AuthTestResult(
                    success=False,
                    stage=AuthStage.COOKIE_DECRYPTION,
                    status_code=AuthStatusCode.EXTRACTION_FAILED,
                    browser_name=display_name,
                    profile_name=prof_name,
                    browser_running=running,
                    reason=f"Failed to extract cookies from {display_name}: {decrypt_err}",
                    suggested_action="Verify that the browser profile is accessible and not corrupted, or use a cookies.txt file.",
                    technical_error=decrypt_err,
                )

        if not jar:
            return AuthTestResult(
                success=False,
                stage=AuthStage.COOKIE_DECRYPTION,
                status_code=AuthStatusCode.EXTRACTION_FAILED,
                browser_name=display_name,
                profile_name=prof_name,
                browser_running=running,
                reason=f"No cookies could be read from {display_name}.",
                suggested_action="Check that you are logged into YouTube in this browser profile, or use a cookies.txt file.",
                technical_error="Cookie jar returned empty or None",
            )

        # ---------------------------------------------------------------------
        # STAGE 4: YouTube Cookie Verification
        # ---------------------------------------------------------------------
        total_cookies = len(jar)
        yt_cookies, has_session = cls._inspect_youtube_cookies(jar)

        if not yt_cookies:
            return AuthTestResult(
                success=False,
                stage=AuthStage.COOKIE_EXTRACTION,
                status_code=AuthStatusCode.NO_YOUTUBE_COOKIES,
                browser_name=display_name,
                profile_name=prof_name,
                cookie_count=total_cookies,
                youtube_cookie_count=0,
                has_session=False,
                browser_running=running,
                reason=f"{display_name} cookies were loaded, but no YouTube or Google cookies were found.",
                suggested_action=f"Open {display_name}, navigate to https://www.youtube.com, log in to your account, then test again.",
                technical_error=f"Found {total_cookies} total cookies, 0 for youtube.com/google.com",
            )

        # ---------------------------------------------------------------------
        # STAGE 5: YouTube Live Request Verification
        # ---------------------------------------------------------------------
        req_ok, req_err = cls._verify_live_request(jar)
        if not req_ok:
            is_bot = "bot" in req_err.lower()
            return AuthTestResult(
                success=False,
                stage=AuthStage.YOUTUBE_REQUEST,
                status_code=AuthStatusCode.BOT_VERIFICATION_REQUIRED if is_bot else AuthStatusCode.AUTHENTICATION_REQUIRED,
                browser_name=display_name,
                profile_name=prof_name,
                cookie_count=total_cookies,
                youtube_cookie_count=len(yt_cookies),
                has_session=has_session,
                browser_running=running,
                reason="YouTube requested additional verification." if is_bot else "YouTube rejected the authenticated request (cookies may be expired or revoked).",
                suggested_action="Consider using a valid browser cookie source and retrying later." if is_bot else f"Log in to YouTube again in {display_name} to refresh your session cookies.",
                technical_error=req_err or "Authenticated YouTube query failed",
            )

        # STAGE COMPLETE: Success!
        if has_session:
            status = AuthStatusCode.YOUTUBE_SESSION_AUTHENTICATED
            reason_msg = f"{display_name} session cookies successfully verified. YouTube session authenticated."
            action_msg = "YouTube authentication is active. Channel Harvest will use these credentials for downloads."
        else:
            status = AuthStatusCode.BROWSER_COOKIE_EXTRACTION_SUCCESS
            reason_msg = f"{display_name} cookies loaded and query succeeded without authentication. No active YouTube login session was found."
            action_msg = f"Log in to YouTube in {display_name} if you wish to access members-only or age-restricted videos."

        return AuthTestResult(
            success=True,
            stage=AuthStage.COMPLETE,
            status_code=status,
            browser_name=display_name,
            profile_name=prof_name,
            cookie_count=total_cookies,
            youtube_cookie_count=len(yt_cookies),
            has_session=has_session,
            browser_running=running,
            reason=reason_msg,
            suggested_action=action_msg,
            technical_error="",
        )

    # -------------------------------------------------------------------------
    # Custom Cookie File (.txt) Verification Flow
    # -------------------------------------------------------------------------

    @classmethod
    def _test_cookie_file(cls, file_path_str: Optional[str]) -> AuthTestResult:
        disp_name = "Custom Cookie File"

        # ---------------------------------------------------------------------
        # STAGE 1: File Detection
        # ---------------------------------------------------------------------
        if not file_path_str or not file_path_str.strip():
            return AuthTestResult(
                success=False,
                stage=AuthStage.BROWSER_DETECTION,
                status_code=AuthStatusCode.BROWSER_NOT_FOUND,
                browser_name=disp_name,
                profile_name="N/A",
                reason="No cookie file path was specified.",
                suggested_action="Click 'Browse...' in Settings and select a valid exported Netscape-formatted cookies.txt file.",
                technical_error="Cookie file path is empty",
            )

        cookie_path = Path(file_path_str.strip())
        if not cookie_path.is_file():
            return AuthTestResult(
                success=False,
                stage=AuthStage.BROWSER_DETECTION,
                status_code=AuthStatusCode.BROWSER_NOT_FOUND,
                browser_name=disp_name,
                profile_name="N/A",
                reason="The specified cookie file does not exist on disk.",
                suggested_action="Verify the file path and ensure the cookies.txt file has not been moved or deleted.",
                technical_error=f"File not found: {cookie_path}",
            )

        # ---------------------------------------------------------------------
        # STAGE 2: File Access
        # ---------------------------------------------------------------------
        try:
            with open(cookie_path, "r", encoding="utf-8", errors="replace") as f:
                content_sample = f.read(1024)
        except Exception as e:
            return AuthTestResult(
                success=False,
                stage=AuthStage.DATABASE_ACCESS,
                status_code=AuthStatusCode.DATABASE_LOCKED,
                browser_name=disp_name,
                profile_name="N/A",
                reason=f"Cannot read cookie file: {e}",
                suggested_action="Check file permissions and ensure another application does not have the file locked exclusively.",
                technical_error=str(e),
            )

        # ---------------------------------------------------------------------
        # STAGE 3: Cookie Parsing
        # ---------------------------------------------------------------------
        jar, parse_err = cls._load_cookie_file(cookie_path)
        if parse_err or not jar:
            return AuthTestResult(
                success=False,
                stage=AuthStage.COOKIE_DECRYPTION,
                status_code=AuthStatusCode.COOKIE_FILE_INVALID,
                browser_name=disp_name,
                profile_name="N/A",
                reason="The selected file is not a valid Netscape-format cookies.txt file.",
                suggested_action="Export your cookies from your browser using a standard extension (e.g. 'Get cookies.txt LOCALLY') in Netscape format.",
                technical_error=parse_err or "No valid cookies could be parsed",
            )

        # ---------------------------------------------------------------------
        # STAGE 4: YouTube Cookie Verification
        # ---------------------------------------------------------------------
        total_cookies = len(jar)
        yt_cookies, has_session = cls._inspect_youtube_cookies(jar)

        if not yt_cookies:
            return AuthTestResult(
                success=False,
                stage=AuthStage.COOKIE_EXTRACTION,
                status_code=AuthStatusCode.NO_YOUTUBE_COOKIES,
                browser_name=disp_name,
                profile_name="N/A",
                cookie_count=total_cookies,
                youtube_cookie_count=0,
                has_session=False,
                reason="The cookie file was parsed, but contains no YouTube or Google cookies.",
                suggested_action="Make sure you were logged into YouTube in the browser tab when exporting cookies.",
                technical_error=f"Parsed {total_cookies} total cookies, 0 for youtube.com",
            )

        # ---------------------------------------------------------------------
        # STAGE 5: YouTube Live Request Verification
        # ---------------------------------------------------------------------
        req_ok, req_err = cls._verify_live_request(jar)
        if not req_ok:
            is_bot = "bot" in req_err.lower()
            return AuthTestResult(
                success=False,
                stage=AuthStage.YOUTUBE_REQUEST,
                status_code=AuthStatusCode.BOT_VERIFICATION_REQUIRED if is_bot else AuthStatusCode.AUTHENTICATION_REQUIRED,
                browser_name=disp_name,
                profile_name="N/A",
                cookie_count=total_cookies,
                youtube_cookie_count=len(yt_cookies),
                has_session=has_session,
                reason="YouTube requested additional verification." if is_bot else "YouTube rejected the authenticated request using the provided cookie file.",
                suggested_action="Consider using a valid browser cookie source and retrying later." if is_bot else "Re-export fresh cookies from an active YouTube browser session.",
                technical_error=req_err or "Authenticated YouTube query failed",
            )

        # STAGE COMPLETE: Success!
        if has_session:
            status = AuthStatusCode.YOUTUBE_SESSION_AUTHENTICATED
            reason_msg = "Cookie file successfully loaded. YouTube session authenticated."
            action_msg = "YouTube authentication is active. Channel Harvest will use this cookie file for downloads."
        else:
            status = AuthStatusCode.COOKIE_FILE_VALID
            reason_msg = "Cookie file loaded and query succeeded without authentication. No active YouTube login session was found."
            action_msg = "Make sure you were signed in to YouTube before exporting cookies if you need access to private or restricted content."

        return AuthTestResult(
            success=True,
            stage=AuthStage.COMPLETE,
            status_code=status,
            browser_name=disp_name,
            profile_name="N/A",
            cookie_count=total_cookies,
            youtube_cookie_count=len(yt_cookies),
            has_session=has_session,
            reason=reason_msg,
            suggested_action=action_msg,
            technical_error="",
        )

    # -------------------------------------------------------------------------
    # Internal Probes & Extractors
    # -------------------------------------------------------------------------

    @classmethod
    def _probe_database_lock(cls, db_file: Path) -> Tuple[bool, str]:
        """Probes whether an SQLite database file can be copied or opened."""
        try:
            with tempfile.TemporaryDirectory(prefix="ch_probe_") as td:
                dst = Path(td) / "probe.sqlite"
                shutil.copy2(db_file, dst)
                conn = sqlite3.connect(dst)
                conn.execute("SELECT 1")
                conn.close()
            return False, ""
        except PermissionError as pe:
            return True, f"PermissionError: {pe}"
        except Exception as ex:
            msg = str(ex).lower()
            if "used by another process" in msg or "locked" in msg or "permission denied" in msg:
                return True, str(ex)
            return False, ""

    @classmethod
    def _extract_browser_cookies(
        cls,
        browser_name: str,
        profile: Optional[str] = None,
    ) -> Tuple[Optional[Any], str, bool, bool]:
        """
        Uses yt-dlp's native extract_cookies_from_browser mechanism.
        Returns: (cookie_jar, error_str, is_app_bound, is_lock_error)
        """
        try:
            from yt_dlp.cookies import extract_cookies_from_browser
            jar = extract_cookies_from_browser(browser_name, profile=profile)
            return jar, "", False, False
        except Exception as e:
            raw_err = str(e)
            err_lower = raw_err.lower()

            # Check database lock indicators
            is_lock_error = (
                isinstance(e, PermissionError) or
                "could not copy" in err_lower or
                "used by another process" in err_lower or
                "[errno 13]" in err_lower or
                "[winerror 32]" in err_lower
            )

            # Check evidence for App-Bound Encryption (v20) vs standard DPAPI
            is_abe = False
            if "failed to decrypt with dpapi" in err_lower:
                # Probe the database for v20 ciphertext
                is_abe = cls._check_db_has_v20(browser_name, profile=profile)

            return None, raw_err, is_abe, is_lock_error

    @classmethod
    def _check_db_has_v20(cls, browser_name: str, profile: Optional[str] = None) -> bool:
        """Inspects if the Chromium cookie database contains cookies with the v20 prefix."""
        db_path = get_browser_database_path(browser_name, profile=profile)
        if not db_path or not db_path.is_file():
            return False

        try:
            with tempfile.TemporaryDirectory(prefix="ch_abe_") as td:
                dst = Path(td) / "temp.sqlite"
                shutil.copy2(db_path, dst)
                conn = sqlite3.connect(dst)
                c = conn.cursor()
                c.execute("SELECT DISTINCT substr(encrypted_value, 1, 3) FROM cookies WHERE length(encrypted_value) > 3")
                rows = c.fetchall()
                conn.close()
                for (p,) in rows:
                    if p in (b"v20", "v20"):
                        return True
        except Exception:
            pass
        return False

    @classmethod
    def _load_cookie_file(cls, cookie_path: Path) -> Tuple[Optional[Any], str]:
        """Loads a Netscape-formatted cookie file using yt-dlp / MozillaCookieJar."""
        try:
            import yt_dlp
            opts = {
                "cookiefile": str(cookie_path.resolve()),
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                jar = ydl.cookiejar
                if jar and len(jar) > 0:
                    return jar, ""
        except Exception as ex:
            return None, str(ex)

        try:
            from http.cookiejar import MozillaCookieJar
            cj = MozillaCookieJar(str(cookie_path.resolve()))
            cj.load(ignore_discard=True, ignore_expires=True)
            if len(cj) > 0:
                return cj, ""
        except Exception as ex:
            return None, str(ex)

        return None, "File contains no recognizable cookies in Netscape format"

    @classmethod
    def _inspect_youtube_cookies(cls, jar: Any) -> Tuple[List[Any], bool]:
        """
        Inspects the cookie jar for YouTube/Google domains and checks
        if any core authentication/session cookies are present.
        """
        yt_cookies = []
        has_session = False

        for c in jar:
            domain = getattr(c, "domain", "").lower()
            if "youtube.com" in domain or "google.com" in domain:
                yt_cookies.append(c)
                name = getattr(c, "name", "")
                if name in YOUTUBE_AUTH_COOKIE_NAMES:
                    has_session = True

        return yt_cookies, has_session

    @classmethod
    def _verify_live_request(cls, jar: Any) -> Tuple[bool, str]:
        """
        Executes a lightweight authenticated read-only YouTube query using yt-dlp
        to verify that YouTube accepts the credentials.
        """
        try:
            import yt_dlp
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.cookiejar = jar
                ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False, process=False)
            return True, ""
        except Exception as ex:
            err_str = str(ex)
            err_lower = err_str.lower()
            if "sign in" in err_lower or "401" in err_lower or "login" in err_lower or "unauthorized" in err_lower:
                return False, f"YouTube rejected login: {PrivacySanitizer.sanitize_message(err_str)}"
            if "bot" in err_lower or "confirm you're not a bot" in err_lower:
                return False, f"Bot verification requested: {PrivacySanitizer.sanitize_message(err_str)}"
            return False, PrivacySanitizer.sanitize_message(err_str)


# Module-level convenience aliases
validate_cookie_file = AuthChecker.validate_cookie_file