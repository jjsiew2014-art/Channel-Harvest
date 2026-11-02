"""
downloader/gallerydl_engine.py
First-Class gallery-dl Download and Extraction Engine for Channel Harvest.

Handles:
1. Runtime capability and executable / python module discovery.
2. Version detection and capability probing.
3. Safe subprocess invocation with process tracking, cancellation, and pipe safety.
4. Structured JSON extraction parsing (--dump-json / --resolve-json).
5. Custom Cookie File propagation (-C / --cookies) with strict credential scrubbing.
6. Safe media downloading with output sanitization and progress tracking.
7. Error classification for authentication, rate limits, access restrictions, and network failures.
"""

import os
import sys
import re
import json
import shutil
import logging
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable

from core.paths import (
    get_bundled_executable,
    get_runtime_dir,
    get_user_runtime_dir,
    sanitize_filename,
    get_temp_dir,
)
from core.diagnostics import PrivacySanitizer

_logger = logging.getLogger("ChannelHarvest.GalleryDlEngine")


class GalleryDlError(Exception):
    """Base exception for gallery-dl engine errors."""
    def __init__(self, message: str, raw_error: str = "", exit_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.raw_error = raw_error
        self.exit_code = exit_code


class GalleryDlNotFoundError(GalleryDlError):
    """Raised when gallery-dl executable or module is not installed or discoverable."""
    pass


class GalleryDlAuthError(GalleryDlError):
    """Raised when authentication is required or rejected."""
    pass


class GalleryDlCancelledException(GalleryDlError):
    """Raised when gallery-dl operation was cancelled by user."""
    pass


class GalleryDlExecutionResult(tuple):
    """3-tuple compatible execution result supporting .timed_out attribute."""
    def __new__(cls, returncode: int, stdout: str, stderr: str, timed_out: bool = False):
        return super().__new__(cls, (returncode, stdout, stderr))

    def __init__(self, returncode: int, stdout: str, stderr: str, timed_out: bool = False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


class GalleryDlRecordList(list):
    """List of extracted metadata records supporting .timed_out attribute."""
    def __init__(self, iterable=None, timed_out: bool = False):
        super().__init__(iterable or [])
        self.timed_out = timed_out


@dataclass
class GalleryDlInfo:
    """Runtime capability information for gallery-dl."""
    available: bool = False
    version: str = "Unknown"
    executable_path: Optional[str] = None
    is_python_module: bool = False
    error: str = ""


class GalleryDlEngine:
    """
    Subprocess-driven gallery-dl integration engine.
    Ensures safe, bounded execution and child process lifecycle management.
    """

    _active_processes: set = set()
    _proc_lock = threading.Lock()
    _cached_info: Optional[GalleryDlInfo] = None
    _cache_lock = threading.Lock()

    @classmethod
    def invalidate_cache(cls) -> None:
        with cls._cache_lock:
            cls._cached_info = None

    def __init__(self):
        pass

    # -------------------------------------------------------------------------
    # Runtime Capability Detection
    # -------------------------------------------------------------------------

    @classmethod
    def detect_runtime(cls, force_refresh: bool = False) -> GalleryDlInfo:
        """
        Detects whether gallery-dl is available and returns capability info.
        Order of resolution:
        1. Bundled executable in user AppData (%APPDATA%/ChannelHarvest/runtime/gallery-dl.exe)
        2. Bundled executable in app installation (<app_root>/runtime/gallery-dl.exe)
        3. PyInstaller bundle directory (sys._MEIPASS/runtime/gallery-dl.exe)
        4. Executable in system PATH (gallery-dl.exe or gallery-dl)
        5. Python module execution (sys.executable -m gallery_dl)
        """
        with cls._cache_lock:
            if cls._cached_info is not None and not force_refresh:
                return cls._cached_info

            info = GalleryDlInfo()

            # 1. Check bundled executable via get_bundled_executable
            bundled = get_bundled_executable("gallery-dl.exe")
            if bundled and bundled.is_file():
                ver = cls._query_version([str(bundled)])
                if ver:
                    info.available = True
                    info.version = ver
                    info.executable_path = str(bundled)
                    cls._cached_info = info
                    return info

            # 2. Check system PATH
            path_exe = shutil.which("gallery-dl.exe") or shutil.which("gallery-dl")
            if path_exe:
                ver = cls._query_version([path_exe])
                if ver:
                    info.available = True
                    info.version = ver
                    info.executable_path = str(path_exe)
                    cls._cached_info = info
                    return info

            # 3. Check Python module execution
            try:
                import gallery_dl
                ver = getattr(gallery_dl, "__version__", None)
                if not ver:
                    ver = cls._query_version([sys.executable, "-m", "gallery_dl"])
                if ver:
                    info.available = True
                    info.version = str(ver)
                    info.is_python_module = True
                    info.executable_path = sys.executable
                    cls._cached_info = info
                    return info
            except ImportError:
                pass

            info.available = False
            info.error = "gallery-dl is not installed or discoverable."
            cls._cached_info = info
            return info

    @classmethod
    def is_available(cls) -> bool:
        """Returns True if gallery-dl is ready to run."""
        return cls.detect_runtime().available

    @classmethod
    def get_version(cls) -> str:
        """Returns detected gallery-dl version."""
        return cls.detect_runtime().version

    @classmethod
    def _query_version(cls, base_cmd: List[str]) -> Optional[str]:
        """Runs --version check safely with timeout."""
        try:
            cmd = base_cmd + ["--version"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if res.returncode == 0:
                v_out = res.stdout.strip()
                if v_out:
                    return v_out.splitlines()[0].strip()
        except Exception:
            pass
        return None

    def get_base_command(self) -> List[str]:
        """Returns base command list to launch gallery-dl."""
        info = self.detect_runtime()
        if not info.available:
            raise GalleryDlNotFoundError(
                "gallery-dl executable or Python module could not be found. "
                "Please verify that gallery-dl is installed or bundled."
            )
        if info.is_python_module:
            return [sys.executable, "-m", "gallery_dl"]
        return [info.executable_path]

    # -------------------------------------------------------------------------
    # Subprocess Execution & Process Tracking
    # -------------------------------------------------------------------------

    def _execute_process(
        self,
        args: List[str],
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        timeout: Optional[float] = None,
    ) -> GalleryDlExecutionResult:
        """
        Safely executes gallery-dl subprocess without shell=True,
        tracking PID for cancellation, preserving outputs on timeout, and avoiding pipe deadlocks.
        Returns a GalleryDlExecutionResult supporting 3-tuple unpacking: (returncode, stdout, stderr)
        with an accessible .timed_out boolean property.
        """
        cmd = self.get_base_command() + args

        # Redact secrets / cookie files from logged command representation
        safe_logged_args = []
        skip_next = False
        for i, a in enumerate(cmd):
            if skip_next:
                safe_logged_args.append("[REDACTED_COOKIE_PATH]")
                skip_next = False
                continue
            if a in ("-C", "--cookies"):
                safe_logged_args.append(a)
                skip_next = True
                continue
            safe_logged_args.append(PrivacySanitizer.sanitize(a))

        if log_callback:
            log_callback(f"[INFO] Running gallery-dl: {' '.join(safe_logged_args)}")

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

        with self._proc_lock:
            self._active_processes.add(proc)

        stdout_lines = []
        stderr_lines = []

        def read_stdout():
            try:
                for line in proc.stdout:
                    stdout_lines.append(line)
            except Exception:
                pass

        def read_stderr():
            try:
                for line in proc.stderr:
                    stderr_lines.append(line)
                    if log_callback:
                        clean_line = line.strip()
                        if clean_line:
                            log_callback(f"[gallery-dl] {clean_line}")
            except Exception:
                pass

        t_out = threading.Thread(target=read_stdout, daemon=True)
        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        start_time = threading.Event()
        start_time.wait(0.01)

        poll_interval = 0.1
        elapsed = 0.0
        timed_out = False

        try:
            while proc.poll() is None:
                if cancel_check and cancel_check():
                    self._terminate_proc(proc)
                    raise GalleryDlCancelledException("gallery-dl operation was cancelled by user.")

                start_time.wait(poll_interval)
                elapsed += poll_interval
                if timeout and elapsed > timeout:
                    timed_out = True
                    self._terminate_proc(proc)
                    break

            t_out.join(timeout=2.0)
            t_err.join(timeout=2.0)
            returncode = proc.returncode if not timed_out else -1

        finally:
            with self._proc_lock:
                self._active_processes.discard(proc)
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

        full_stdout = "".join(stdout_lines)
        full_stderr = "".join(stderr_lines)
        return GalleryDlExecutionResult(returncode, full_stdout, full_stderr, timed_out=timed_out)

    @classmethod
    def _terminate_proc(cls, proc: subprocess.Popen) -> None:
        """Safely terminates child process and its tree."""
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
        except Exception:
            pass

    @classmethod
    def terminate_all_processes(cls) -> None:
        """Kills all active gallery-dl child processes."""
        with cls._proc_lock:
            for proc in list(cls._active_processes):
                cls._terminate_proc(proc)
            cls._active_processes.clear()

    # -------------------------------------------------------------------------
    # Structured Metadata Extraction
    # -------------------------------------------------------------------------

    def extract_metadata(
        self,
        url: str,
        custom_cookie_file: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        resolve_urls: bool = True,
        timeout: float = 180.0,
    ) -> List[Dict[str, Any]]:
        """
        Extracts structured JSON metadata for a URL using --dump-json or --resolve-json.
        Returns normalized list of extractor result dictionaries.
        Preserves partially discovered records upon timeout.
        """
        args = [
            "--dump-json" if not resolve_urls else "--resolve-json",
            "--simulate",
            "--no-colors",
            "--retries", "3",
            "--http-timeout", "20",
        ]

        low_url = (url or "").lower()
        if "facebook.com" in low_url or "fb.watch" in low_url or "fb.me" in low_url:
            args.extend([
                "--option", "extractor.facebook.loop=false",
                "--option", "extractor.facebook.videos=true",
            ])

        if custom_cookie_file and Path(custom_cookie_file).is_file():
            args.extend(["--cookies", str(Path(custom_cookie_file).resolve())])

        args.append(url)

        res = self._execute_process(
            args=args,
            log_callback=log_callback,
            cancel_check=cancel_check,
            timeout=timeout,
        )

        returncode, stdout, stderr = res[0], res[1], res[2]
        timed_out = getattr(res, "timed_out", False)

        parsed_records = self.parse_dump_json(stdout, stderr=stderr, returncode=returncode)

        if timed_out:
            if parsed_records:
                if log_callback:
                    log_callback(
                        f"[WARNING] gallery-dl timed out after {timeout}s, "
                        f"but successfully recovered {len(parsed_records)} discovered record(s)."
                    )
                return GalleryDlRecordList(parsed_records, timed_out=True)
            else:
                raise GalleryDlError(f"gallery-dl operation timed out after {timeout} seconds.")

        if returncode != 0 and not parsed_records:
            self._check_stderr_errors(stderr, returncode=returncode)
            raise GalleryDlError(f"gallery-dl failed with exit code {returncode}: {stderr.strip() or stdout.strip()}")

        return GalleryDlRecordList(parsed_records, timed_out=False)

    @classmethod
    def parse_dump_json(
        cls,
        stdout: str,
        stderr: str = "",
        returncode: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Parses gallery-dl dump-json output with resilience to interleaved log output,
        truncated JSON arrays, and multi-record deduplication.
        Handles type codes:
          1: Directory / category metadata
          2: Directory / file metadata (Message.Directory)
          3: Downloadable media URL / file item metadata (Message.Url)
          6: Queue metadata (Message.Queue)
          -1: Error record
        """
        results: List[Dict[str, Any]] = []
        seen_media: Dict[str, Dict[str, Any]] = {}

        # Strip non-record log prefixes from stdout
        lines = [
            ln for ln in stdout.splitlines()
            if not re.match(r'^\s*\[(facebook|instagram|gallery-dl|urllib3|requests|debug|info|warning|error)', ln, re.I)
            and not re.match(r'^\s*(DEBUG|INFO|WARNING|ERROR):', ln, re.I)
        ]
        cleaned = "\n".join(lines).strip()

        if not cleaned:
            if stderr and returncode != 0:
                cls._check_stderr_errors(stderr, returncode=returncode)
            return results

        parsed = None
        # Attempt 1: Direct JSON parsing
        try:
            parsed = json.loads(cleaned)
        except Exception:
            pass

        # Attempt 2: Outer bracket boundary search
        if parsed is None:
            f_brk = cleaned.find('[')
            l_brk = cleaned.rfind(']')
            if f_brk != -1 and l_brk != -1 and l_brk > f_brk:
                try:
                    parsed = json.loads(cleaned[f_brk:l_brk + 1])
                except Exception:
                    pass

        # Attempt 3: Line-by-line JSON parsing
        if parsed is None:
            line_objs = []
            for ln in cleaned.splitlines():
                t = ln.strip()
                if not t:
                    continue
                try:
                    obj = json.loads(t)
                    line_objs.append(obj)
                except Exception:
                    pass
            if line_objs:
                parsed = line_objs

        # Attempt 4: Resilient raw_decode scan across complete records (recovers truncated output)
        if parsed is None:
            decoder = json.JSONDecoder()
            parsed = []
            pos = 0
            while pos < len(cleaned):
                idx_brk = cleaned.find('[', pos)
                idx_brc = cleaned.find('{', pos)
                if idx_brk == -1 and idx_brc == -1:
                    break
                idx = min(idx_brk, idx_brc) if (idx_brk != -1 and idx_brc != -1) else (idx_brk if idx_brk != -1 else idx_brc)
                try:
                    obj, end_pos = decoder.raw_decode(cleaned[idx:])
                    if isinstance(obj, list):
                        if obj and isinstance(obj[0], int) and obj[0] in (-1, 1, 2, 3, 6):
                            parsed.append(obj)
                            pos = idx + end_pos
                            continue
                        elif obj and all(isinstance(x, list) for x in obj):
                            parsed.extend(obj)
                            pos = idx + end_pos
                            continue
                    elif isinstance(obj, dict):
                        parsed.append(obj)
                        pos = idx + end_pos
                        continue
                except Exception:
                    pass
                pos = idx + 1

        if not isinstance(parsed, list):
            if isinstance(parsed, dict):
                return [parsed]
            return results

        for item in parsed:
            if isinstance(item, list) and len(item) >= 2:
                code = item[0]
                if code == -1:
                    err_dict = item[1] if isinstance(item[1], dict) else {"message": str(item[1])}
                    err_msg = err_dict.get("message") or err_dict.get("error") or "Extraction aborted"
                    if any(k in err_msg.lower() for k in ("login", "redirect to login", "authentication")):
                        raise GalleryDlAuthError(f"gallery-dl authentication required: {err_msg}")
                    continue

                rec = None
                if code in (2, 3, 6):
                    # [3, url, metadata_dict] or [2, url, metadata_dict] or [2, metadata_dict]
                    if len(item) >= 3 and isinstance(item[2], dict):
                        rec = dict(item[2])
                        rec["url"] = item[1]
                    elif isinstance(item[1], dict):
                        rec = dict(item[1])
                elif code == 1 and isinstance(item[1], dict):
                    rec = dict(item[1])

                if rec:
                    item_id = str(rec.get("id") or rec.get("photo_id") or rec.get("video_id") or rec.get("url") or "")
                    if item_id:
                        if item_id in seen_media:
                            seen_media[item_id].update(rec)
                        else:
                            seen_media[item_id] = rec
                            results.append(rec)
                    else:
                        results.append(rec)

            elif isinstance(item, dict):
                item_id = str(item.get("id") or item.get("url") or "")
                if item_id:
                    if item_id in seen_media:
                        seen_media[item_id].update(item)
                    else:
                        seen_media[item_id] = item
                        results.append(item)
                else:
                    results.append(item)

        return results

    @classmethod
    def _check_stderr_errors(cls, stderr: str, returncode: int = 0) -> None:
        """Inspects stderr for specific failure classifications."""
        low = stderr.lower()
        if "detected possible jump to the beginning of the set" in low:
            # Informational pagination wrap message from FacebookExtractor; not a failure
            return
        if "login" in low or "authentication" in low or "unauthorized" in low or "redirect to login" in low:
            raise GalleryDlAuthError(f"gallery-dl authentication required: {stderr.strip()}", raw_error=stderr, exit_code=returncode)
        if "rate limit" in low or "http error 429" in low:
            raise GalleryDlError(f"gallery-dl rate limit reached: {stderr.strip()}", raw_error=stderr, exit_code=returncode)
        if "not found" in low or "http error 404" in low:
            raise GalleryDlError(f"gallery-dl content not found: {stderr.strip()}", raw_error=stderr, exit_code=returncode)

    # -------------------------------------------------------------------------
    # Media Download Execution
    # -------------------------------------------------------------------------

    def download_media(
        self,
        url: str,
        target_dir: Path,
        filename_stem: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Downloads a media item or image set using gallery-dl.
        Parameters:
            url: The media or post URL.
            target_dir: Target output directory.
            filename_stem: Optional custom filename stem (sanitized).
            custom_cookie_file: Path to custom Netscape cookies.txt file.
            progress_callback: Progress signal callback.
            log_callback: Log output callback.
            cancel_check: Cancellation check callable.
        Returns:
            Dict containing: success, downloaded_files, skipped, error
        """
        target_dir = Path(target_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        args = [
            "--directory", str(target_dir),
            "--windows-filenames",
            "--no-colors",
            "--retries", "3",
            "--http-timeout", "30",
        ]

        low_url = (url or "").lower()
        if "facebook.com" in low_url or "fb.watch" in low_url or "fb.me" in low_url:
            args.extend([
                "--option", "extractor.facebook.loop=false",
                "--option", "extractor.facebook.videos=true",
            ])

        if filename_stem:
            clean_stem = sanitize_filename(filename_stem, max_length=120, fallback="media")
            args.extend(["--filename", f"{clean_stem}.{{extension}}"])

        if custom_cookie_file and Path(custom_cookie_file).is_file():
            args.extend(["--cookies", str(Path(custom_cookie_file).resolve())])

        args.append(url)

        if progress_callback:
            progress_callback({
                "status": "downloading",
                "percent": 10.0,
                "downloaded_str": "-- KB",
                "total_str": "-- KB",
                "speed": "gallery-dl",
                "eta": "--:--",
                "step": "Image Download",
            })

        # Track directory snapshot before download to discover downloaded files
        existing_files = set(target_dir.iterdir()) if target_dir.exists() else set()

        res = self._execute_process(
            args=args,
            log_callback=log_callback,
            cancel_check=cancel_check,
            timeout=300.0,
        )

        returncode, stdout, stderr = res[0], res[1], res[2]

        # Snapshot after download
        new_files = [f for f in target_dir.iterdir() if f not in existing_files and f.is_file()]

        if returncode == 0:
            if progress_callback:
                progress_callback({
                    "status": "downloading",
                    "percent": 100.0,
                    "downloaded_str": f"{len(new_files)} file(s)",
                    "total_str": f"{len(new_files)} file(s)",
                    "speed": "Finished",
                    "eta": "00:00",
                    "step": "Completed",
                })

            return {
                "success": True,
                "downloaded_files": [str(f) for f in new_files],
                "skipped": len(new_files) == 0,
                "error": "",
                "exit_code": returncode,
            }

        # Check for error classifications
        err_msg = stderr.strip() or stdout.strip() or f"gallery-dl exited with code {returncode}"
        self._check_stderr_errors(err_msg, returncode=returncode)

        return {
            "success": False,
            "downloaded_files": [str(f) for f in new_files],
            "skipped": False,
            "error": err_msg,
            "exit_code": returncode,
        }
