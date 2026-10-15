"""
douyin.py
PlatformAdapter implementation for Douyin (Chinese TikTok) in Channel Harvest.
Encapsulates URL parsing, short link redirect resolution, validation, platform-scoped
authentication, profile scanning, and yt-dlp extraction for Douyin videos.
"""

import json
import re
import urllib.request
import urllib.error
import http.cookiejar
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import UnsupportedError, DownloadError, ExtractorError

from core.models import VideoItem, DownloadSettings, VideoStatus
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector
from core.platform.auth import PlatformAuthConfig
from core.settings import SettingsManager


def inspect_cookie_file_safe(cookie_path_str: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Safely inspects a cookie file without exposing sensitive session values, tokens, or paths.
    Returns:
        (is_valid, message, details_dict)
    """
    if not cookie_path_str:
        return False, "Cookie file path not specified", {}

    cpath = Path(cookie_path_str)
    if not cpath.is_file():
        return False, f"Cookie file does not exist: {cpath.name}", {}

    try:
        size = cpath.stat().st_size
        if size == 0:
            return False, f"Cookie file is empty (0 bytes): {cpath.name}", {"size": 0}

        # Check readability and count entries
        total_cookies = 0
        douyin_cookies = 0
        has_uifid = False
        has_uifid_temp = False
        has_s_v_web_id = False
        has_ttwid = False
        has_sessionid = False
        has_netscape_header = False

        with open(cpath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s.startswith("# Netscape HTTP Cookie File") or s.startswith("# HTTP Cookie File"):
                    has_netscape_header = True
                    continue
                if s.startswith("#"):
                    continue

                parts = s.split("\t")
                if len(parts) >= 7:
                    total_cookies += 1
                    domain = parts[0].lower()
                    cookie_name = parts[5]
                    if "douyin.com" in domain or "iesdouyin.com" in domain:
                        douyin_cookies += 1
                        if cookie_name == "UIFID":
                            has_uifid = True
                        elif cookie_name == "UIFID_TEMP":
                            has_uifid_temp = True
                        elif cookie_name == "s_v_web_id":
                            has_s_v_web_id = True
                        elif cookie_name == "ttwid":
                            has_ttwid = True
                        elif cookie_name == "sessionid":
                            has_sessionid = True

        if total_cookies == 0 and not has_netscape_header:
            return False, f"File does not look like a valid Netscape format cookie file: {cpath.name}", {"size": size}

        return True, "Cookie file is readable Netscape format", {
            "filename": cpath.name,
            "size": size,
            "total_cookies": total_cookies,
            "douyin_cookies": douyin_cookies,
            "has_uifid": has_uifid,
            "has_uifid_temp": has_uifid_temp,
            "has_s_v_web_id": has_s_v_web_id,
            "has_ttwid": has_ttwid,
            "has_sessionid": has_sessionid,
        }

    except Exception as e:
        return False, f"Cannot read cookie file: {str(e)}", {}


class DouyinAdapter(PlatformAdapter):
    """
    Concrete platform adapter for Douyin (抖音).
    Supports single video URLs, mobile share URLs (v.douyin.com), iesdouyin links,
    and Douyin creator profiles (douyin.com/user/<sec_uid>).
    """

    # Supported Douyin video and user URL patterns
    _VIDEO_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?douyin\.com/(?:video|note)/(?P<id>\d+)",
        re.IGNORECASE,
    )
    _IESDOUYIN_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?iesdouyin\.com/share/video/(?P<id>\d+)",
        re.IGNORECASE,
    )
    _SHORT_URL_PATTERN = re.compile(
        r"https?://v\.douyin\.com/(?P<id>[a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )
    _USER_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?douyin\.com/user/(?P<sec_uid>[a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )
    _IES_USER_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?iesdouyin\.com/share/user/(?P<sec_uid>[a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )

    # -------------------------------------------------------------------------
    # TEMPORARY FEATURE FREEZE
    # -------------------------------------------------------------------------
    # Douyin support is temporarily frozen and disabled because its web detail endpoint
    # (/aweme/v1/web/aweme/detail/) currently returns HTTP 403 Forbidden due to ByteDance
    # server-side ArgusSecurityPlugin WAF blocking ("Blocked by ArgusSecurityPlugin Uifid Not Found").
    # The current upstream yt-dlp versions tested (2026.08.19 bundled, nightly 2026.09.27.dev0,
    # and upstream master) do not resolve this problem as yt-dlp lacks an interactive verification
    # challenge solver. Douyin support should only be re-enabled after a verified upstream
    # extraction fix is available.
    #
    # This freeze can be reversed at any time by setting IS_AVAILABLE = True or dynamically
    # via PlatformRegistry.set_platform_available("douyin", True).
    IS_AVAILABLE: bool = False
    UNAVAILABLE_REASON_KEY: str = "platform_douyin_unavailable_tooltip"

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=False,   # Douyin does not provide external subtitle tracks
            supports_thumbnails=True,  # Video cover / thumbnail supported
            supports_description=True, # Video caption / description supported
            supports_metadata=True,    # Metadata (.metadata.txt) supported
            supports_chapters=False,   # Douyin short videos do not have chapters
            supports_playlists=False,  # Douyin playlists not supported in yt-dlp
            supports_channel_scan=True, # Creator profile scanning supported via DouyinAdapter profile scanner
            supports_browser_cookies=True, # Browser cookie extraction (Chrome, Edge, Firefox, etc.)
            supports_cookie_file=True, # Custom Netscape cookie file
            archive_prefix="douyin",
        )

    @property
    def platform_id(self) -> str:
        return "douyin"

    @property
    def display_name(self) -> str:
        return "Douyin"

    @property
    def is_available(self) -> bool:
        from core.platform.detector import PlatformRegistry
        override = PlatformRegistry.get_availability_override(self.platform_id)
        if override is not None:
            return override
        return self.IS_AVAILABLE

    @property
    def unavailable_reason(self) -> Optional[str]:
        return self.UNAVAILABLE_REASON_KEY

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Determines whether the given URL is a Douyin URL."""
        if not url or not isinstance(url, str):
            return False
        return PlatformDetector.identify_platform_id(url) == "douyin"

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """Validates Douyin URL format or share snippet containing a Douyin link."""
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a Douyin video or share link."

        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = parsed.netloc.lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.DOUYIN_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid Douyin domain."

            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific Douyin video or creator profile link."

            return True, ""

        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def resolve_short_url(self, url: str, timeout: float = 5.0) -> str:
        """
        Follows HTTP redirects for Douyin short URLs (e.g. v.douyin.com)
        to discover the canonical web URL.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    )
                },
            )
            opener = urllib.request.build_opener()
            with opener.open(req, timeout=timeout) as response:
                return response.geturl()
        except urllib.error.HTTPError as e:
            if e.headers and "Location" in e.headers:
                return e.headers["Location"]
            return url
        except Exception:
            return url

    def normalize_url(self, url: str) -> str:
        """
        Normalizes Douyin URL for scanning:
        1. Extracts URL from mobile app share text if present.
        2. Resolves short link (v.douyin.com) redirects to destination URL.
        3. If destination/input is a user profile (e.g. /user/<sec_uid>, /share/user/<sec_uid>, or ?sec_uid=...),
           extracts the sec_uid and canonicalizes to https://www.douyin.com/user/<sec_uid>.
        4. If destination/input is a video (e.g. /video/<id>, /share/video/<id>, /note/<id>),
           extracts the numeric video ID and canonicalizes to https://www.douyin.com/video/<id>.
        5. Strips tracking query parameters.
        Never returns legacy iesdouyin.com/share/user/ URLs.
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()

        # Follow redirects for short share links (e.g. v.douyin.com/iABCxyz/)
        if "v.douyin.com" in cleaned:
            resolved = self.resolve_short_url(cleaned)
            if resolved:
                cleaned = resolved

        # Check user profile patterns: /user/<sec_uid>, /share/user/<sec_uid>, or ?sec_uid=...
        m_user = re.search(r"/(?:user|share/user)/(?P<sec_uid>[a-zA-Z0-9_-]+)", cleaned)
        if not m_user:
            m_user = re.search(r"[?&]sec_uid=(?P<sec_uid>[a-zA-Z0-9_-]+)", cleaned)
        if m_user:
            sec_uid = m_user.group("sec_uid")
            return f"https://www.douyin.com/user/{sec_uid}"

        # Extract numeric video ID if present in the URL path
        m_vid = re.search(r"/(?:video|share/video|note)/(?P<id>\d+)", cleaned, re.IGNORECASE)
        if m_vid:
            vid_id = m_vid.group("id")
            return f"https://www.douyin.com/video/{vid_id}"

        # Clean query parameters from other Douyin URLs
        if "?" in cleaned:
            base, _ = cleaned.split("?", 1)
            cleaned = base

        return cleaned.rstrip("/")

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """Constructs a playback URL for a Douyin video."""
        if original_url and "douyin.com/video/" in original_url:
            return original_url
        return f"https://www.douyin.com/video/{video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        return f"douyin {video.video_id}"

    def get_auth_config(self, settings: Optional[Any] = None) -> "PlatformAuthConfig":
        """
        Resolves Douyin-specific authentication configuration.
        Supports Browser Cookies and Custom Cookie File independently of YouTube.
        Zero credentials, tokens, or cookie settings are inherited from YouTube.
        """
        from core.settings import SettingsManager

        auth_method = "none"
        browser_cookies = "none"
        browser_profile = "Default"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("douyin_auth_method", "none") or "none"
                browser_cookies = settings.get("douyin_browser_cookies", "none") or "none"
                browser_profile = settings.get("douyin_browser_profile", "Default") or "Default"
                custom_cookie_file = settings.get("douyin_custom_cookie_file", "") or ""
            elif hasattr(settings, "douyin_auth_method"):
                auth_method = getattr(settings, "douyin_auth_method", "none") or "none"
                browser_cookies = getattr(settings, "douyin_browser_cookies", "none") or "none"
                browser_profile = getattr(settings, "douyin_browser_profile", "Default") or "Default"
                custom_cookie_file = getattr(settings, "douyin_custom_cookie_file", "") or getattr(settings, "custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                if "douyin_auth_method" in settings or "douyin_browser_cookies" in settings:
                    auth_method = settings.get("douyin_auth_method", "none") or "none"
                    browser_cookies = settings.get("douyin_browser_cookies", "none") or "none"
                    browser_profile = settings.get("douyin_browser_profile", "Default") or "Default"
                    custom_cookie_file = settings.get("douyin_custom_cookie_file", "") or settings.get("custom_cookie_file", "") or ""
                elif settings.get("platform") == "douyin":
                    auth_method = settings.get("auth_method", "none") or "none"
                    browser_cookies = settings.get("browser_cookies", "none") or "none"
                    browser_profile = settings.get("browser_profile", "Default") or "Default"
                    custom_cookie_file = settings.get("custom_cookie_file", "") or ""

        # Read from global SettingsManager if not explicitly specified
        if auth_method == "none" and browser_cookies == "none" and not custom_cookie_file:
            try:
                sm = SettingsManager()
                auth_method = sm.get("douyin_auth_method", "none")
                browser_cookies = sm.get("douyin_browser_cookies", "none")
                browser_profile = sm.get("douyin_browser_profile", "Default")
                custom_cookie_file = sm.get("douyin_custom_cookie_file", "")
            except Exception:
                pass

        # Normalize auth_method if missing but custom_cookie_file or browser_cookies is set
        if auth_method == "none":
            if custom_cookie_file:
                auth_method = "custom_file"
            elif browser_cookies not in ("none", "", None):
                if browser_cookies == "custom_file":
                    auth_method = "custom_file"
                elif browser_cookies in ("chrome", "firefox", "edge", "brave", "opera", "vivaldi", "chromium", "safari"):
                    auth_method = "browser"

        if auth_method == "custom_file" or browser_cookies == "custom_file":
            if not custom_cookie_file:
                try:
                    sm = SettingsManager()
                    custom_cookie_file = sm.get("douyin_custom_cookie_file", "")
                except Exception:
                    pass
            cookie_path = Path(custom_cookie_file) if custom_cookie_file else None
            if cookie_path and cookie_path.is_file():
                return PlatformAuthConfig(
                    auth_method="custom_file",
                    cookie_file=str(cookie_path.resolve()),
                    description="Custom Cookie File",
                )
            if custom_cookie_file:
                return PlatformAuthConfig(
                    auth_method="custom_file",
                    cookie_file=str(custom_cookie_file),
                    description="Custom Cookie File",
                )
            return PlatformAuthConfig.none()

        elif auth_method == "browser" or browser_cookies not in ("none", "", "null", "false", None):
            b_name = browser_cookies if browser_cookies != "custom_file" else "none"
            if b_name and b_name.lower() not in ("none", "", "null", "false"):
                return PlatformAuthConfig(
                    auth_method="browser",
                    browser_name=b_name.lower(),
                    browser_profile=browser_profile,
                    description=f"Browser Cookies ({b_name.capitalize()})",
                )
            return PlatformAuthConfig.none()

        return PlatformAuthConfig.none()

    def _extract_profile_entries(
        self,
        sec_uid: str,
        profile_url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        """
        Extracts public video entries for a Douyin creator profile.
        Queries the Douyin web post API with platform-scoped authentication headers and cookies.
        """
        from downloader.ytdlp_engine import YtDlpEngine, NetworkError, ExtractionError, EmptyChannelError

        if log_callback:
            log_callback(f"[INFO] Scanning Douyin creator profile: {profile_url}")

        cookiejar = http.cookiejar.CookieJar()
        if auth_config and auth_config.is_active:
            if auth_config.auth_method == "custom_file" and auth_config.cookie_file:
                is_ok, msg, details = inspect_cookie_file_safe(auth_config.cookie_file)
                if not is_ok:
                    if log_callback:
                        log_callback(f"[AUTH ERROR] Douyin cookie file invalid: {msg}")
                    raise ExtractionError(f"COOKIE_FILE_INVALID: Specified Douyin cookie file is invalid ({msg}).")
                try:
                    cpath = Path(auth_config.cookie_file)
                    cj = http.cookiejar.MozillaCookieJar(str(cpath.resolve()))
                    cj.load(ignore_discard=True, ignore_expires=True)
                    cookiejar = cj
                    if log_callback:
                        fname = details.get("filename", "cookies.txt")
                        fsize = details.get("size", 0)
                        dy_cnt = details.get("douyin_cookies", 0)
                        log_callback(f"[AUTH DIAGNOSTIC] Applied Douyin cookie file to profile scanner: {fname} ({fsize} bytes, {dy_cnt} Douyin cookies).")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[WARNING] Could not load Douyin cookie file: {e}")
            elif auth_config.auth_method == "browser" and auth_config.browser_name:
                try:
                    import yt_dlp.cookies
                    b_cj = yt_dlp.cookies.extract_cookies_from_browser(
                        auth_config.browser_name,
                        profile=auth_config.browser_profile,
                    )
                    if b_cj:
                        cookiejar = b_cj
                        if log_callback:
                            log_callback(f"[AUTH] Applied Douyin browser cookies ({auth_config.browser_name}) to profile scanner.")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[WARNING] Could not extract Douyin browser cookies: {e}")

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))

        api_url = (
            f"https://www.douyin.com/aweme/v1/web/aweme/post/?"
            f"device_platform=webapp&aid=6383&channel=channel_pc_web&"
            f"sec_user_id={sec_uid}&max_cursor=0&count=20"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://www.douyin.com/user/{sec_uid}",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(api_url, headers=headers)

        try:
            with opener.open(req, timeout=10) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            err_low = (err_body + " " + str(e.reason)).lower()
            if e.code == 403 or any(k in err_low for k in ("argus", "fresh cookies", "uifid not found")):
                if auth_config and auth_config.is_active:
                    raise ExtractionError(
                        "DOUYIN_API_BLOCKED: Douyin profile API blocked the request (HTTP 403: Blocked by ArgusSecurityPlugin / Uifid Not Found). "
                        "Cookies were provided, but Douyin requires interactive security verification (UIFID token)."
                    ) from e
                else:
                    raise ExtractionError(
                        "DOUYIN_SESSION_REQUIRED: Douyin requires fresh session cookies to scan creator profiles. "
                        "Please configure Douyin Authentication (Browser Cookies or Custom Cookie File) in Settings."
                    ) from e
            raise ExtractionError(f"Douyin profile request failed (HTTP {e.code}): {e.reason}") from e
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "connection" in err_msg.lower():
                raise NetworkError(f"Network error while connecting to Douyin profile: {err_msg}") from e
            raise ExtractionError(f"Douyin profile extraction failed: {err_msg}") from e

        aweme_list = data.get("aweme_list") or []
        if not aweme_list:
            raise EmptyChannelError("No public videos found for this Douyin creator.")

        video_items: List[VideoItem] = []
        for idx, entry in enumerate(aweme_list, 1):
            if not entry:
                continue
            vid_id = str(entry.get("aweme_id") or entry.get("id") or "")
            if not vid_id:
                continue

            author = entry.get("author") or {}
            uploader = author.get("nickname") or author.get("unique_id") or "Douyin Creator"
            title = entry.get("desc") or f"Douyin by {uploader}"
            title = title.splitlines()[0] if title else f"Douyin by {uploader}"
            if len(title) > 120:
                title = title[:120].strip()

            dur_raw = entry.get("duration") or entry.get("video", {}).get("duration")
            if isinstance(dur_raw, (int, float)):
                dur_secs = int(dur_raw / 1000.0) if dur_raw > 1000 else int(dur_raw)
            else:
                dur_secs = 0
            dur_str = YtDlpEngine.format_duration(dur_secs)

            stats = entry.get("statistics") or {}
            cover_list = entry.get("video", {}).get("cover", {}).get("url_list") or []
            cover_url = cover_list[0] if cover_list else ""
            extra_meta = {
                "uploader": uploader,
                "uploader_id": author.get("unique_id") or author.get("short_id") or "",
                "sec_uid": author.get("sec_uid") or sec_uid,
                "like_count": stats.get("digg_count"),
                "comment_count": stats.get("comment_count"),
                "repost_count": stats.get("share_count"),
                "thumbnail": cover_url,
            }

            video_items.append(
                VideoItem(
                    index=idx,
                    video_id=vid_id,
                    title=title,
                    duration=dur_str,
                    duration_seconds=dur_secs,
                    status=VideoStatus.READY,
                    subtitle_status="—",
                    url=self.build_video_url(vid_id),
                    selected=True,
                    channel_title=uploader,
                    platform="douyin",
                    extra_metadata=extra_meta,
                )
            )

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} Douyin video(s) from creator profile.")

        return video_items

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[PlatformAuthConfig] = None,
    ) -> List[VideoItem]:
        """
        Extracts video entries from a Douyin video or creator profile URL.
        Runs with platform authentication strictly scoped to Douyin.
        """
        from core.platform.detector import PlatformRegistry
        if not PlatformRegistry.is_available(self.platform_id):
            from core.error_classifier import ErrorClassifier
            err = ErrorClassifier.for_unavailable_platform(self.platform_id)
            if log_callback:
                log_callback(f"[BLOCKED] {err.title}: {err.user_message}")
            raise RuntimeError(f"[PLATFORM_TEMPORARILY_UNAVAILABLE] {err.user_message}")

        is_valid, reason = self.validate_url(url)
        if not is_valid:
            from downloader.ytdlp_engine import InvalidURLError
            raise InvalidURLError(reason)

        from downloader.ytdlp_engine import YtDlpEngine, NetworkError, ExtractionError, EmptyChannelError, InvalidURLError

        normalized_url = self.normalize_url(url)

        # Resolve Douyin-scoped authentication configuration
        if auth_config is None:
            auth_config = self.get_auth_config(
                settings={
                    "douyin_auth_method": "custom_file" if custom_cookie_file else "none",
                    "douyin_browser_cookies": browser_cookies or ("custom_file" if custom_cookie_file else "none"),
                    "douyin_custom_cookie_file": custom_cookie_file,
                } if (browser_cookies or custom_cookie_file) else None
            )

        # Distinguish profile URL vs single video URL
        m_user = self._USER_URL_PATTERN.search(normalized_url)
        if m_user:
            sec_uid = m_user.group("sec_uid")
            return self._extract_profile_entries(
                sec_uid=sec_uid,
                profile_url=normalized_url,
                log_callback=log_callback,
                auth_config=auth_config,
            )

        # Check custom cookie file integrity and log safe diagnostics
        if auth_config and auth_config.is_active:
            if auth_config.auth_method == "custom_file":
                cfile = auth_config.cookie_file or ""
                is_ok, msg, details = inspect_cookie_file_safe(cfile)
                if not is_ok:
                    if log_callback:
                        log_callback(f"[AUTH ERROR] Douyin cookie file invalid: {msg}")
                    raise ExtractionError(f"COOKIE_FILE_INVALID: Specified Douyin cookie file is invalid ({msg}).")

                if log_callback:
                    fname = details.get("filename", "cookies.txt")
                    fsize = details.get("size", 0)
                    tot = details.get("total_cookies", 0)
                    dy_cnt = details.get("douyin_cookies", 0)
                    log_callback(f"[AUTH DIAGNOSTIC] Douyin cookie file verified: {fname} ({fsize} bytes, {tot} entries, {dy_cnt} for douyin.com).")
                    if not details.get("has_uifid"):
                        log_callback("[AUTH DIAGNOSTIC] Notice: Cookie file does not contain authenticated 'UIFID' device token (found: UIFID_TEMP / session tokens). ArgusSecurityPlugin verification may fail.")
                    log_callback("[AUTH] Passing verified cookie file to yt-dlp extraction engine.")
            elif auth_config.auth_method == "browser":
                if log_callback:
                    log_callback(f"[AUTH] Passing Douyin browser cookies ({auth_config.browser_name}) to yt-dlp extraction engine.")
        else:
            if log_callback:
                log_callback("[AUTH] No cookies configured for Douyin (Authentication: None).")

        # Single video extraction via yt-dlp
        if log_callback:
            log_callback(f"[INFO] Connecting to Douyin video: {normalized_url}")

        engine = YtDlpEngine()
        ydl_opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="douyin",
            auth_config=auth_config,
        )
        ydl_opts.update({
            "skip_download": True,
            "extract_flat": "in_playlist",
        })

        info = None
        last_exception = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if log_callback:
                    log_callback("[INFO] Fetching metadata from Douyin...")
                info = ydl.extract_info(normalized_url, download=False)

        except UnsupportedError as e:
            raise InvalidURLError(f"Douyin URL not supported: {str(e)}") from e

        except DownloadError as e:
            err_msg = str(e)
            last_exception = e
            err_low = err_msg.lower()

            # Session cookies / ArgusSecurityPlugin check -> Fail fast immediately, DO NOT retry!
            if any(term in err_low for term in ("fresh cookies", "s_v_web_id", "argussecurityplugin", "uifid not found")) or ("failed to download web detail json" in err_low and "403" in err_low):
                if auth_config and auth_config.is_active:
                    raise ExtractionError(
                        f"DOUYIN_API_BLOCKED: Douyin web detail API blocked the request (HTTP 403: Blocked by ArgusSecurityPlugin / Uifid Not Found). "
                        f"Cookies were provided ({auth_config.description}), but Douyin requires interactive device security verification (UIFID token)."
                    ) from e
                else:
                    raise ExtractionError(
                        "DOUYIN_SESSION_REQUIRED: Douyin requires fresh session cookies to retrieve video details. "
                        "Please configure Douyin Authentication (Browser Cookies or Custom Cookie File) in Settings."
                    ) from e

            # Unsupported URL -> Fail fast
            if "unsupported url" in err_low:
                raise ExtractionError(f"DOUYIN_EXTRACTOR_INCOMPATIBLE: Douyin URL not supported: {err_msg}") from e

            # Non-retryable permanent errors -> Fail fast
            if "private" in err_low or "not have permission" in err_low:
                raise ExtractionError(f"Douyin video is private: {err_msg}") from e
            if "unavailable" in err_low or "removed" in err_low or "deleted" in err_low:
                raise ExtractionError(f"Douyin video unavailable: {err_msg}") from e

            if any(term in err_low for term in ("unable to download", "timed out", "connection")):
                raise NetworkError(f"Network connection to Douyin failed: {err_msg}") from e
            raise ExtractionError(f"UNKNOWN_EXTRACTION_ERROR: {err_msg}") from e

        except Exception as e:
            last_exception = e
            err_msg = str(e)
            err_low = err_msg.lower()
            if any(term in err_low for term in ("fresh cookies", "s_v_web_id", "argussecurityplugin", "uifid not found")) or ("failed to download web detail json" in err_low and "403" in err_low):
                if auth_config and auth_config.is_active:
                    raise ExtractionError(
                        f"DOUYIN_API_BLOCKED: Douyin web detail API blocked the request (HTTP 403: Blocked by ArgusSecurityPlugin / Uifid Not Found). "
                        f"Cookies were provided ({auth_config.description}), but Douyin requires interactive device security verification (UIFID token)."
                    ) from e
                else:
                    raise ExtractionError(
                        "DOUYIN_SESSION_REQUIRED: Douyin requires fresh session cookies to retrieve video details. "
                        "Please configure Douyin Authentication (Browser Cookies or Custom Cookie File) in Settings."
                    ) from e
            if "unsupported url" in err_low:
                raise ExtractionError(f"DOUYIN_EXTRACTOR_INCOMPATIBLE: Douyin URL not supported: {err_msg}") from e
            raise ExtractionError(f"UNKNOWN_EXTRACTION_ERROR: {str(e)}") from e

        if not info:
            if last_exception:
                raise ExtractionError(f"Douyin extraction failed: {str(last_exception)}") from last_exception
            raise EmptyChannelError("No information could be retrieved for this Douyin URL.")

        uploader = (
            info.get("uploader")
            or info.get("channel")
            or info.get("uploader_id")
            or "Douyin Creator"
        )
        channel_title = uploader

        raw_entries = info.get("entries")
        if raw_entries is not None:
            entries_list = [e for e in raw_entries if e]
        elif info.get("id"):
            entries_list = [info]
        else:
            entries_list = []

        if not entries_list:
            raise EmptyChannelError(f"No public videos found for Douyin creator '{channel_title}'.")

        video_items: List[VideoItem] = []
        index_counter = 1

        for entry in entries_list:
            if not entry:
                continue

            vid_id = str(entry.get("id") or "")
            raw_title = entry.get("title") or entry.get("description") or f"Douyin by {channel_title}"
            raw_title = raw_title.splitlines()[0] if raw_title else f"Douyin by {channel_title}"
            if len(raw_title) > 120:
                raw_title = raw_title[:120].strip()

            duration_raw = entry.get("duration")
            duration_str = YtDlpEngine.format_duration(duration_raw)
            duration_secs = int(duration_raw) if isinstance(duration_raw, (int, float)) else None

            webpage_url = entry.get("webpage_url") or entry.get("url") or self.build_video_url(vid_id)

            extra_meta = {
                "uploader": channel_title,
                "uploader_id": entry.get("uploader_id", ""),
                "channel_id": entry.get("channel_id", ""),
                "view_count": entry.get("view_count"),
                "like_count": entry.get("like_count"),
                "comment_count": entry.get("comment_count"),
                "repost_count": entry.get("repost_count"),
                "track": entry.get("track"),
                "artists": entry.get("artists") or entry.get("artist"),
                "upload_date": entry.get("upload_date"),
            }

            item = VideoItem(
                index=index_counter,
                video_id=vid_id,
                title=raw_title,
                duration=duration_str,
                duration_seconds=duration_secs,
                status=VideoStatus.READY,
                subtitle_status="—",
                url=webpage_url,
                selected=True,
                channel_title=channel_title,
                platform="douyin",
                extra_metadata=extra_meta,
            )
            video_items.append(item)
            index_counter += 1

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} Douyin video(s).")

        return video_items
