"""
core/platform/rednote.py
PlatformAdapter implementation for RedNote (小红书 / Xiaohongshu) in Channel Harvest.
Encapsulates URL parsing, mobile short link redirect resolution (xhslink.com),
validation, platform-scoped authentication, note extraction (Photos & Videos),
and creator profile scanning.
"""

import json
import re
import urllib.request
import urllib.error
import http.cookiejar
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    cffi_requests = None
    HAS_CURL_CFFI = False

from core.models import VideoItem, DownloadSettings, VideoStatus, ScanResult, MediaType
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector
from core.platform.auth import PlatformAuthConfig, resolve_effective_cookie_file
from core.settings import SettingsManager


def inspect_rednote_cookie_file_safe(cookie_path_str: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Safely inspects a cookie file for RedNote / Xiaohongshu without exposing sensitive session values.
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

        total_cookies = 0
        rednote_cookies = 0
        has_a1 = False
        has_web_session = False
        has_gid = False
        has_webid = False
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
                    cookie_name = parts[5].strip()
                    if any(h in domain for h in ("xiaohongshu.com", "rednote.com")):
                        rednote_cookies += 1
                        if cookie_name == "a1":
                            has_a1 = True
                        elif cookie_name == "web_session":
                            has_web_session = True
                        elif cookie_name.lower() in ("gid", "webgid"):
                            has_gid = True
                        elif cookie_name.lower() in ("webid", "web_id"):
                            has_webid = True

        if total_cookies == 0 and not has_netscape_header:
            return False, f"File does not look like a valid Netscape format cookie file: {cpath.name}", {"size": size}

        has_session = has_a1 or has_web_session
        msg = "Cookie file contains valid RedNote session" if has_session else "Cookie file contains RedNote cookies"
        return True, msg, {
            "filename": cpath.name,
            "size": size,
            "total_cookies": total_cookies,
            "rednote_cookies": rednote_cookies,
            "has_a1": has_a1,
            "has_web_session": has_web_session,
            "has_gid": has_gid,
            "has_webid": has_webid,
            "has_session": has_session,
        }

    except Exception as e:
        return False, f"Cannot read cookie file: {str(e)}", {}


def clean_rednote_state_json(raw_json: str) -> str:
    """
    Sanitizes JavaScript object syntax embedded in window.__INITIAL_STATE__
    into valid JSON (handling undefined, new Set([]), new Map(), and other JS instantiations).
    """
    if not raw_json:
        return "{}"
    # 1. Replace undefined with null
    s = re.sub(r"\bundefined\b", "null", raw_json)
    # 2. Replace new Set(...) with inner array or []
    s = re.sub(r"new\s+Set\s*\((.*?)\)", lambda m: m.group(1).strip() or "[]", s)
    # 3. Replace new Map(...) with {}
    s = re.sub(r"new\s+Map\s*\(.*?\)", "{}", s)
    # 4. Replace other new constructs with null
    s = re.sub(r"new\s+[A-Za-z0-9_]+\s*\(.*?\)", "null", s)
    return s


def format_rednote_upload_date(raw_time: Any) -> Tuple[Optional[str], Optional[int]]:
    """
    Parses RedNote timestamp (in milliseconds or seconds) into ('YYYY-MM-DD', timestamp_sec).
    Returns (None, None) if missing or unparseable.
    """
    if not raw_time:
        return None, None
    try:
        val = int(raw_time)
        ts_sec = int(val / 1000) if val > 1e11 else int(val)
        if 1_000_000_000 <= ts_sec <= 2_500_000_000:
            dt = datetime.fromtimestamp(ts_sec)
            return dt.strftime("%Y-%m-%d"), ts_sec
    except Exception:
        pass
    return None, None


def is_minimal_or_emoji_title(title: str) -> bool:
    """
    Detects if a title consists solely of emojis, symbols, whitespace,
    or fewer than 2 alphanumeric / CJK characters (e.g. '🤍☕️', '🪽..', '-', '..').
    """
    if not title:
        return True
    clean = title.strip()
    if not clean:
        return True
    alphanumeric_cjk = re.findall(r"[\w\u4e00-\u9fff]", clean)
    return len(alphanumeric_cjk) < 2


def enrich_rednote_title(
    raw_title: str,
    upload_date: Optional[str] = None,
    author: str = "",
    note_id: str = "",
    index: int = 1,
) -> str:
    """
    Enriches RedNote note titles:
    Uniformly prepends [YYYY-MM-DD] to ALL RedNote posts (photos and videos),
    regardless of whether the title contains emojis, text, or symbols.
    - If title is purely punctuation/empty (like '-' or '..'):
      falls back to '[YYYY-MM-DD] {author} Note {note_id}'.
    - Avoids double-prepending if title already starts with '[YYYY-MM-DD]'.
    - If upload_date is not available (e.g. unparseable or mock test without date),
      returns clean_t safely.
    """
    clean_t = (raw_title or "").splitlines()[0].strip() if raw_title else ""

    # Check if title has any substantive characters (letters, numbers, CJK, or emojis)
    has_substantive = bool(re.search(r"[\w\u4e00-\u9fff\U00010000-\U0010ffff]", clean_t))
    if not has_substantive:
        author_part = f"{author} " if author else ""
        nid_part = f"Note {note_id}" if note_id else f"P{index:02d}"
        clean_t = f"{author_part}{nid_part}".strip()
        if upload_date:
            return f"[{upload_date}] {clean_t}"
        return clean_t

    if upload_date:
        if not re.match(r"^\[\d{4}-\d{2}-\d{2}\]", clean_t):
            return f"[{upload_date}] {clean_t}"

    return clean_t


class RedNoteAdapter(PlatformAdapter):
    """
    Concrete platform adapter for RedNote / XiaoHongShu (小红书).
    Supports single Video notes, Photo (image carousel) notes, mobile short links (xhslink.com),
    creator profiles (xiaohongshu.com/user/profile/<userId>), and creator collections/columns (合集与专栏).
    """

    _NOTE_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/(?:explore|discovery/item|red_video|notes?)/(?P<id>[a-f0-9]+)",
        re.IGNORECASE,
    )
    _USER_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/user/profile/(?P<user_id>[a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )
    _COLLECTION_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/(?:(?:collection|column|board|series|page/collection|page/column)/(?P<id>[a-zA-Z0-9_-]+)|user/profile/[a-zA-Z0-9_-]+/(?:collection|column|board)/(?P<profile_coll_id>[a-zA-Z0-9_-]+))",
        re.IGNORECASE,
    )
    _SHORT_URL_PATTERN = re.compile(
        r"https?://xhslink\.com/(?:[a-zA-Z0-9_\-]+/)?(?P<id>[a-zA-Z0-9]+)",
        re.IGNORECASE,
    )

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=False,   # RedNote does not provide external subtitle tracks
            supports_thumbnails=True,  # Video / note covers supported
            supports_description=True, # Post description / caption supported
            supports_metadata=True,    # Metadata (.metadata.txt) supported
            supports_chapters=False,   # Notes do not have chapters
            supports_playlists=True,   # Collections and columns (合集与专栏) supported
            supports_channel_scan=True,# Creator profile scanning supported
            supports_browser_cookies=True, # Browser cookie extraction (Chrome, Edge, etc.)
            supports_cookie_file=True, # Custom Netscape cookie file
            supports_profile_media_archive=True,
            archive_prefix="rednote",
        )

    @property
    def platform_id(self) -> str:
        return "rednote"

    @property
    def display_name(self) -> str:
        return "RedNote"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Determines whether the given URL is a RedNote / XiaoHongShu URL."""
        if not url or not isinstance(url, str):
            return False
        return PlatformDetector.identify_platform_id(url) == "rednote"

    def is_collection_url(self, url: str) -> bool:
        """Determines whether the given URL points to a RedNote collection, column, or board."""
        if not url or not isinstance(url, str):
            return False
        clean = self.normalize_url(url)
        if self._COLLECTION_URL_PATTERN.search(clean):
            return True
        if "/user/profile/" in clean and any(k in clean.lower() for k in ("tab=collection", "tab=column", "tab=board", "collection_id=", "column_id=")):
            return True
        return False

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """Validates RedNote URL format or share snippet containing a RedNote link."""
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a RedNote note, collection, or creator link."

        try:
            parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = parsed.netloc.lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.REDNOTE_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid RedNote domain."

            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific RedNote note, collection/column, or creator profile link."

            return True, ""

        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def resolve_short_url(self, url: str, timeout: float = 6.0) -> str:
        """
        Follows HTTP redirects for RedNote short share URLs (e.g. xhslink.com/...)
        to discover the canonical web URL containing the necessary xsec_token.
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        Normalizes RedNote URL for scanning:
        1. Extracts URL from mobile app share text or emoji snippets.
        2. Follows redirects for short links (xhslink.com).
        3. Strips superficial query parameters while preserving xsec_token.
        4. Canonicalizes desktop dual feed (/red_video/<id>) and notes paths (/notes/<id>)
           to canonical discovery item URLs (/discovery/item/<id>) with webshare parameters
           so both yt-dlp and internal extraction engines can scan and download reliably.
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()

        if "xhslink.com" in cleaned:
            resolved = self.resolve_short_url(cleaned)
            if resolved:
                cleaned = resolved

        # Ensure scheme
        if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
            cleaned = "https://" + cleaned

        try:
            parsed = urlparse(cleaned)
            path = parsed.path or ""
            # Canonicalize /red_video/<id> or /notes/<id> or /note/<id>
            m = re.match(r"^/(?:red_video|notes?)/(?P<id>[a-f0-9]+)", path, re.IGNORECASE)
            if m:
                note_id = m.group("id")
                qs = parse_qs(parsed.query, keep_blank_values=True)
                xsec_token = qs.get("xsec_token", [""])[0]

                params = [
                    ("source", "webshare"),
                    ("xhsshare", "pc_web"),
                ]
                if xsec_token:
                    params.append(("xsec_token", xsec_token))
                params.append(("xsec_source", "pc_share"))

                for k, vals in qs.items():
                    if k not in ("source", "xhsshare", "xsec_token", "xsec_source"):
                        for v in vals:
                            params.append((k, v))
                query_str = urlencode(params, safe="=")
                return f"https://www.xiaohongshu.com/discovery/item/{note_id}?{query_str}"

            # If discovery/item or explore has pc_dual_feed, upgrade to pc_share
            if "xsec_source=pc_dual_feed" in cleaned:
                cleaned = cleaned.replace("xsec_source=pc_dual_feed", "xsec_source=pc_share")

            # Clean note-level referral tracking params from creator profile URLs.
            # When an author avatar is clicked on a PC note, Xiaohongshu appends the note's
            # xsec_source=pc_note and xsec_token to the profile URL. Because that token is
            # note-scoped or temporary, Xiaohongshu's backend returns empty notes (0 notes)
            # when requested with an expired or mismatched token.
            if "/user/profile/" in path:
                qs = parse_qs(parsed.query, keep_blank_values=True)
                if qs.get("xsec_source", [""])[0] in ("pc_note", "pc_feed", "pc_search") or not qs.get("xsec_token"):
                    clean_params = [(k, v) for k, vals in qs.items() for v in vals if k not in ("xsec_token", "xsec_source")]
                    query_str = f"?{urlencode(clean_params)}" if clean_params else ""
                    scheme = parsed.scheme or "https"
                    return f"{scheme}://{parsed.netloc}{path}{query_str}"
        except Exception:
            pass

        return cleaned

    @staticmethod
    def resolve_xhscdn_url(raw_url: str, file_id: str = "") -> str:
        """
        Resolves Xiaohongshu CDN image URL to the canonical highest-quality
        asset path, preserving subpath prefixes (e.g. spectrum/, notes_pre_post/)
        from international and domestic CDN routes.
        """
        clean = (raw_url or "").split("?")[0].split("!")[0].strip()

        # 1. If URL is on rednotecdn.com with signed path /<timestamp>/<token>/<rel_path>
        m_cdn = re.search(r"/[0-9]{10,}/[^/]+/(.+)$", clean)
        if m_cdn:
            rel_path = m_cdn.group(1).lstrip("/")
            return f"https://sns-img-qc.xhscdn.com/{rel_path}"

        # 2. If explicit file_id is provided
        if file_id:
            if "spectrum" in clean:
                return f"https://sns-img-qc.xhscdn.com/spectrum/{file_id}"
            if "notes_pre_post" in clean:
                return f"https://sns-img-qc.xhscdn.com/notes_pre_post/{file_id}"
            return f"https://sns-img-qc.xhscdn.com/{file_id}"

        # 3. If clean URL is already an xhscdn.com URL, keep it without preview suffixes
        if "xhscdn.com" in clean:
            return re.sub(r"![a-zA-Z0-9_\-]+$", "", raw_url.split("?")[0])

        # 4. Fallback: clean URL or file_id
        if clean:
            return clean

        return raw_url

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """Constructs canonical browse URL for a RedNote item."""
        if original_url and ("xiaohongshu.com/explore/" in original_url or "xsec_token" in original_url):
            return original_url
        return f"https://www.xiaohongshu.com/explore/{video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        return f"rednote {video.video_id}"

    def get_auth_config(self, settings: Optional[Any] = None) -> PlatformAuthConfig:
        """
        Resolves RedNote-specific authentication configuration with fallback to global 'all'.
        """
        auth_method = "none"
        browser_cookies = "none"
        browser_profile = "Default"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("rednote_auth_method", "none") or "none"
                browser_cookies = settings.get("rednote_browser_cookies", "none") or "none"
                browser_profile = settings.get("rednote_browser_profile", "Default") or "Default"
                custom_cookie_file = settings.get("rednote_custom_cookie_file", "") or ""
            elif hasattr(settings, "rednote_auth_method"):
                auth_method = getattr(settings, "rednote_auth_method", "none") or "none"
                browser_cookies = getattr(settings, "rednote_browser_cookies", "none") or "none"
                browser_profile = getattr(settings, "rednote_browser_profile", "Default") or "Default"
                custom_cookie_file = getattr(settings, "rednote_custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                auth_method = settings.get("rednote_auth_method", "none") or "none"
                browser_cookies = settings.get("rednote_browser_cookies", "none") or "none"
                browser_profile = settings.get("rednote_browser_profile", "Default") or "Default"
                custom_cookie_file = settings.get("rednote_custom_cookie_file", "") or ""

        # Fallback to SettingsManager if not configured
        if auth_method == "none" and browser_cookies == "none" and not custom_cookie_file:
            try:
                sm = SettingsManager()
                auth_method = sm.get("rednote_auth_method", "none")
                browser_cookies = sm.get("rednote_browser_cookies", "none")
                browser_profile = sm.get("rednote_browser_profile", "Default")
                custom_cookie_file = sm.get("rednote_custom_cookie_file", "")
            except Exception:
                pass

        # Check effective cookie file with 'all' fallback
        eff_method, eff_file, desc_suffix = resolve_effective_cookie_file(
            "rednote", auth_method, custom_cookie_file, settings=settings
        )

        if eff_method == "custom_file" and eff_file:
            cp = Path(eff_file)
            if cp.is_file():
                return PlatformAuthConfig(
                    auth_method="custom_file",
                    cookie_file=str(cp.resolve()),
                    description=f"Custom Cookie File{desc_suffix}",
                )

        if auth_method == "browser" or (browser_cookies not in ("none", "", "null", "false", None) and browser_cookies != "custom_file"):
            b_name = browser_cookies if browser_cookies != "custom_file" else "none"
            if b_name and b_name.lower() not in ("none", "", "null", "false"):
                return PlatformAuthConfig(
                    auth_method="browser",
                    browser_name=b_name.lower(),
                    browser_profile=browser_profile,
                    description=f"Browser Cookies ({b_name.capitalize()})",
                )

        return PlatformAuthConfig.none()

    def _build_cookiejar(self, auth_config: Optional[PlatformAuthConfig]) -> http.cookiejar.CookieJar:
        """Constructs an HTTP CookieJar from the resolved authentication configuration."""
        cookiejar = http.cookiejar.CookieJar()
        if not auth_config or not auth_config.is_active:
            return cookiejar

        if auth_config.auth_method == "custom_file" and auth_config.cookie_file:
            cpath = Path(auth_config.cookie_file)
            if cpath.is_file():
                try:
                    cj = http.cookiejar.MozillaCookieJar(str(cpath.resolve()))
                    cj.load(ignore_discard=True, ignore_expires=True)
                    return cj
                except Exception:
                    pass

        elif auth_config.auth_method == "browser" and auth_config.browser_name:
            try:
                import yt_dlp.cookies
                b_cj = yt_dlp.cookies.extract_cookies_from_browser(
                    auth_config.browser_name,
                    profile=auth_config.browser_profile,
                )
                if b_cj:
                    return b_cj
            except Exception:
                pass

        return cookiejar

    def _fetch_html(
        self,
        url: str,
        cookiejar: Optional[Any] = None,
        timeout: float = 12.0,
    ) -> str:
        """
        Fetches RedNote HTML content.
        Uses curl_cffi with Chrome TLS fingerprinting to bypass WAF login redirects.
        Falls back to urllib.request if curl_cffi is unavailable or during mocked unit tests.
        """
        # If urllib.request.build_opener is a Mock (e.g. in offline unit tests), use it directly
        try:
            from unittest.mock import Mock
            if isinstance(urllib.request.build_opener, Mock):
                opener = urllib.request.build_opener()
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                        ),
                        "Referer": "https://www.xiaohongshu.com/",
                    },
                )
                with opener.open(req, timeout=timeout) as response:
                    return response.read().decode("utf-8", errors="ignore")
        except Exception:
            pass

        if HAS_CURL_CFFI and cffi_requests is not None:
            try:
                session = cffi_requests.Session(impersonate="chrome120")
                if cookiejar:
                    session.cookies.update(cookiejar)
                headers = {
                    "Referer": "https://www.xiaohongshu.com/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
                resp = session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200 and "/login" not in resp.url and "/404" not in resp.url:
                    return resp.text
                if "/404" in resp.url:
                    raise RuntimeError(
                        "REDNOTE_NOTE_NOT_FOUND: Note not found or link has expired/truncated xsec_token. "
                        "Please copy the complete original share URL without omitting any parameters."
                    )
                if "/login" in resp.url and "/login" not in url:
                    raise RuntimeError(
                        "REDNOTE_ACCESS_DENIED: Redirected to login page. "
                        "Please configure RedNote browser or custom cookies in Settings."
                    )
            except Exception as ce:
                if "REDNOTE_" in str(ce):
                    raise

        # Fallback to urllib.request
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar or http.cookiejar.CookieJar()))
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.xiaohongshu.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        try:
            with opener.open(req, timeout=timeout) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else url
                if "/404" in final_url and "/404" not in url:
                    raise RuntimeError(
                        "REDNOTE_NOTE_NOT_FOUND: Note not found or link has expired/truncated xsec_token. "
                        "Please copy the complete original share URL without omitting any parameters."
                    )
                if "/login" in final_url and "/login" not in url:
                    raise RuntimeError(
                        "REDNOTE_ACCESS_DENIED: Redirected to login page. "
                        "Please configure RedNote browser or custom cookies in Settings."
                    )
                return response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise RuntimeError(
                    f"REDNOTE_ACCESS_DENIED: HTTP {e.code} when accessing RedNote note. Fresh cookies may be required."
                ) from e
            raise RuntimeError(f"HTTP error accessing RedNote: {e.code} {e.reason}") from e
        except Exception as e:
            if "REDNOTE_" in str(e):
                raise
            raise RuntimeError(f"Network error accessing RedNote: {str(e)}") from e

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        """
        Extracts note entries (Photos or Videos) from RedNote URLs or creator profiles.
        Handles xhslink.com redirect resolution and parses window.__INITIAL_STATE__.
        """
        clean_url = self.normalize_url(url)
        if log_callback:
            log_callback(f"[INFO] Scanning RedNote target: {clean_url}")

        # Resolve auth configuration if not explicitly passed
        if auth_config is None:
            auth_config = self.get_auth_config()

        # Check if collection or column URL
        if self.is_collection_url(clean_url):
            return self._extract_collection_entries(clean_url, log_callback=log_callback, auth_config=auth_config)

        # Check if creator profile URL
        m_user = self._USER_URL_PATTERN.search(clean_url)
        if m_user:
            user_id = m_user.group("user_id")
            return self._extract_profile_entries(user_id, clean_url, log_callback=log_callback, auth_config=auth_config)

        # Single Note Extraction
        cookiejar = self._build_cookiejar(auth_config)
        html = self._fetch_html(clean_url, cookiejar=cookiejar)

        # Extract window.__INITIAL_STATE__
        state_data = {}
        target = "window.__INITIAL_STATE__="
        idx = html.find(target)
        if idx == -1:
            m = re.search(r"window\.__INITIAL_STATE__\s*=", html)
            if m:
                idx = m.start()
                target = m.group(0)

        if idx != -1:
            start = idx + len(target)
            end = html.find("</script>", start)
            if end != -1:
                raw_json = html[start:end].rstrip(";\n\r ")
                cleaned_json = clean_rednote_state_json(raw_json)
                try:
                    state_data = json.loads(cleaned_json)
                except Exception:
                    state_data = {}

        if not state_data:
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})\s*;</script>", html, re.DOTALL)
            if not match:
                match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})</script>", html, re.DOTALL)
            if match:
                try:
                    cleaned_json = clean_rednote_state_json(match.group(1))
                    state_data = json.loads(cleaned_json)
                except Exception:
                    state_data = {}

        if not state_data:
            raise RuntimeError(
                "REDNOTE_INITIAL_STATE_NOT_FOUND: Could not extract note metadata from RedNote page. "
                "The link may require an xsec_token or fresh login session cookies."
            )

        note_map = state_data.get("note", {}).get("noteDetailMap", {})
        if not note_map:
            raise RuntimeError(
                "REDNOTE_NOTE_EMPTY: Note details empty or blocked. "
                "Please configure RedNote cookies in Settings."
            )

        # Match note id from URL or take first available in noteDetailMap
        m_nid = self._NOTE_URL_PATTERN.search(clean_url)
        note_id = m_nid.group("id") if m_nid else list(note_map.keys())[0]
        note_data = note_map.get(note_id, {}).get("note", {})
        if not note_data and note_map:
            note_id = list(note_map.keys())[0]
            note_data = note_map[note_id].get("note", {})

        if not note_data:
            raise RuntimeError(f"REDNOTE_NOTE_NOT_FOUND: Could not find note data for ID {note_id}.")

        note_type = str(note_data.get("type", "normal")).lower()
        raw_title = note_data.get("title") or note_data.get("desc") or f"RedNote {note_id}"
        raw_title = raw_title.splitlines()[0][:100].strip() if raw_title else f"RedNote {note_id}"
        user_info = note_data.get("user", {})
        uploader = user_info.get("nickname") or user_info.get("unique_id") or "RedNote Creator"
        user_id_val = str(user_info.get("userId") or user_info.get("user_id") or "")
        red_id_val = str(user_info.get("redId") or user_info.get("uniqueId") or user_info.get("unique_id") or "")
        desc = note_data.get("desc") or ""

        interact_info = note_data.get("interactInfo") or {}
        liked_count = interact_info.get("likedCount")
        collected_count = interact_info.get("collectedCount")
        comment_count = interact_info.get("commentCount")
        share_count = interact_info.get("shareCount")
        ip_location = note_data.get("ipLocation") or ""
        upload_timestamp = note_data.get("time") or note_data.get("lastUpdateTime")
        upload_date_val, upload_ts_val = format_rednote_upload_date(upload_timestamp)
        tag_list = note_data.get("tagList") or []
        tags = [t.get("name") for t in tag_list if isinstance(t, dict) and t.get("name")]

        title = enrich_rednote_title(
            raw_title=raw_title,
            upload_date=upload_date_val,
            author=uploader,
            note_id=note_id,
        )

        items: List[VideoItem] = []

        if note_type == "video":
            # Video note
            video_info = note_data.get("video", {})
            dur_raw = (
                video_info.get("capa", {}).get("duration")
                or video_info.get("media", {}).get("video", {}).get("duration")
                or video_info.get("duration", 0)
            )
            if dur_raw:
                dur_secs = int(dur_raw / 1000) if dur_raw > 1000 else int(dur_raw)
            else:
                dur_secs = 0

            # Streams info
            h264_streams = video_info.get("media", {}).get("stream", {}).get("h264", [])
            master_url = ""
            backup_urls = []
            if h264_streams and isinstance(h264_streams, list):
                master_url = h264_streams[0].get("masterUrl", "")
                backup_urls = h264_streams[0].get("backupUrls", [])
                if not dur_secs and h264_streams[0].get("duration"):
                    s_dur = h264_streams[0].get("duration")
                    dur_secs = int(s_dur / 1000) if s_dur > 1000 else int(s_dur)

            origin_key = video_info.get("consumer", {}).get("originVideoKey", "")
            origin_url = (
                f"https://sns-video-bd.xhscdn.com/{origin_key}"
                if origin_key
                else (master_url or (backup_urls[0] if backup_urls else ""))
            )

            dur_str = f"{dur_secs // 60:02d}:{dur_secs % 60:02d}" if dur_secs > 0 else "-"

            # Check cover thumbnail - prefer direct uncompressed master image from CDN
            cover_list = note_data.get("imageList", [])
            cover_url = ""
            cover_w = None
            cover_h = None
            if cover_list:
                first_img = cover_list[0]
                cover_w = first_img.get("width")
                cover_h = first_img.get("height")
                fid = first_img.get("fileId") or ""
                raw_u = first_img.get("urlDefault") or first_img.get("url") or first_img.get("urlPre") or ""
                cover_url = self.resolve_xhscdn_url(raw_u, fid)
            if not cover_url:
                v_img = video_info.get("image", {})
                first_frame_fid = v_img.get("firstFrameFileid") or ""
                thumb_fid = v_img.get("thumbnailFileid") or ""
                target_fid = first_frame_fid or thumb_fid
                raw_vimg = v_img.get("urlDefault") or v_img.get("url") or v_img.get("urlPre") or ""
                if target_fid or raw_vimg:
                    cover_url = self.resolve_xhscdn_url(raw_vimg, target_fid)

            item = VideoItem(
                index=1,
                video_id=note_id,
                title=title,
                duration=dur_str,
                duration_seconds=dur_secs if dur_secs > 0 else None,
                status=VideoStatus.READY,
                subtitle_status="—",
                url=clean_url,
                channel_title=uploader,
                platform="rednote",
                media_type=MediaType.VIDEO,
                cover_art_url=cover_url or None,
                cover_art_width=cover_w or None,
                cover_art_height=cover_h or None,
                extra_metadata={
                    "origin_video_url": origin_url,
                    "master_stream_url": master_url,
                    "backup_urls": backup_urls,
                    "origin_video_key": origin_key,
                    "thumbnail_url": cover_url or None,
                    "description": desc,
                    "raw_title": raw_title,
                    "uploader": uploader,
                    "uploader_id": user_id_val,
                    "user_id": user_id_val,
                    "red_id": red_id_val,
                    "liked_count": liked_count,
                    "collected_count": collected_count,
                    "comment_count": comment_count,
                    "share_count": share_count,
                    "ip_location": ip_location,
                    "upload_timestamp": upload_ts_val or upload_timestamp,
                    "upload_date": upload_date_val,
                    "tags": tags,
                    "note_type": "video",
                    "media_type": "VIDEO",
                },
            )
            items.append(item)

        else:
            # Photo / Image-text note (normal)
            image_list = note_data.get("imageList") or note_data.get("imagesList") or note_data.get("images") or []
            photo_urls = []
            live_photo_urls = {}
            for p_idx, img in enumerate(image_list, 1):
                fid = img.get("fileId") or ""
                raw_img = img.get("urlDefault") or img.get("url") or img.get("urlPre") or ""
                resolved_img = self.resolve_xhscdn_url(raw_img, fid)
                if resolved_img:
                    photo_urls.append(resolved_img)

                # Check if this image has an associated LivePhoto video stream
                if img.get("livePhoto"):
                    stream = img.get("stream", {})
                    streams = stream.get("h264") or stream.get("h265") or []
                    if streams and isinstance(streams, list):
                        v_u = streams[0].get("masterUrl") or (streams[0].get("backupUrls", [None])[0] if streams[0].get("backupUrls") else "")
                        if v_u:
                            live_photo_urls[p_idx] = v_u

            p_count = len(photo_urls)
            cover_url = photo_urls[0] if photo_urls else None
            first_w = image_list[0].get("width") if image_list else None
            first_h = image_list[0].get("height") if image_list else None

            item = VideoItem(
                index=1,
                video_id=note_id,
                title=title,
                duration="Photo",
                duration_seconds=0,
                status=VideoStatus.READY,
                subtitle_status="—",
                url=clean_url,
                channel_title=uploader,
                platform="rednote",
                media_type=MediaType.PHOTO,
                cover_art_url=cover_url or None,
                cover_art_width=first_w,
                cover_art_height=first_h,
                extra_metadata={
                    "is_photo": True,
                    "photo_count": p_count,
                    "photo_urls": photo_urls,
                    "live_photo_urls": live_photo_urls,
                    "thumbnail_url": cover_url or None,
                    "description": desc,
                    "raw_title": raw_title,
                    "uploader": uploader,
                    "uploader_id": user_id_val,
                    "user_id": user_id_val,
                    "red_id": red_id_val,
                    "liked_count": liked_count,
                    "collected_count": collected_count,
                    "comment_count": comment_count,
                    "share_count": share_count,
                    "ip_location": ip_location,
                    "upload_timestamp": upload_ts_val or upload_timestamp,
                    "upload_date": upload_date_val,
                    "tags": tags,
                    "note_type": "normal",
                    "media_type": "PHOTO",
                },
            )
            items.append(item)

        if log_callback:
            log_callback(f"[SUCCESS] Successfully parsed RedNote entry: {title} (Type: {note_type})")

        return items

    def _parse_initial_state(self, html: str) -> Dict[str, Any]:
        """Extracts and parses window.__INITIAL_STATE__ JSON from RedNote SSR HTML."""
        if not html:
            return {}

        state_data: Dict[str, Any] = {}
        target = "window.__INITIAL_STATE__="
        idx = html.find(target)
        if idx == -1:
            m = re.search(r"window\.__INITIAL_STATE__\s*=", html)
            if m:
                idx = m.start()
                target = m.group(0)

        if idx != -1:
            start = idx + len(target)
            end = html.find("</script>", start)
            if end != -1:
                raw_json = html[start:end].rstrip(";\n\r ")
                cleaned_json = clean_rednote_state_json(raw_json)
                try:
                    state_data = json.loads(cleaned_json)
                except Exception:
                    state_data = {}

        if not state_data:
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})\s*;</script>", html, re.DOTALL)
            if not match:
                match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?})</script>", html, re.DOTALL)
            if match:
                try:
                    cleaned_json = clean_rednote_state_json(match.group(1))
                    state_data = json.loads(cleaned_json)
                except Exception:
                    state_data = {}

        return state_data

    def _extract_collection_entries(
        self,
        collection_url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        auth_config: Optional[PlatformAuthConfig] = None,
    ) -> List[VideoItem]:
        """
        Extracts notes from a RedNote collection / column / board / series page via window.__INITIAL_STATE__.
        Decomposes discovered items into Photos (MediaType.PHOTO) and Videos (MediaType.VIDEO).
        """
        clean_url = self.normalize_url(collection_url)
        if log_callback:
            log_callback(f"[INFO] Scanning RedNote collection / column: {clean_url}")

        cookiejar = self._build_cookiejar(auth_config)
        html = self._fetch_html(clean_url, cookiejar=cookiejar)
        state_data = self._parse_initial_state(html)

        if not state_data:
            raise RuntimeError("REDNOTE_COLLECTION_BLOCKED: Could not extract collection initial state. Fresh cookies may be required.")

        # Identify collection/column identifier from URL
        m_coll = self._COLLECTION_URL_PATTERN.search(clean_url)
        collection_id = ""
        if m_coll:
            collection_id = m_coll.group("id") or m_coll.group("profile_coll_id") or ""
        if not collection_id:
            qs = parse_qs(urlparse(clean_url).query)
            collection_id = qs.get("collection_id", [""])[0] or qs.get("column_id", [""])[0] or qs.get("id", [""])[0]

        # Locate collection dictionary in state tree
        coll_data = (
            state_data.get("collection")
            or state_data.get("collectionData")
            or state_data.get("column")
            or state_data.get("columnData")
            or state_data.get("board")
            or state_data.get("boardData")
            or state_data.get("series")
            or {}
        )
        if not coll_data:
            user_data = state_data.get("user") or {}
            up_data = user_data.get("userPageData") or state_data.get("userPageData") or {}
            coll_data = (
                up_data.get("collectionDetail")
                or up_data.get("columnDetail")
                or up_data.get("currentCollection")
                or up_data.get("currentColumn")
                or up_data.get("collectionData")
                or up_data.get("columnData")
                or up_data.get("collectData")
                or {}
            )

        if not coll_data and ("notes" in state_data or "noteList" in state_data):
            coll_data = state_data

        collection_name = (
            coll_data.get("name")
            or coll_data.get("title")
            or coll_data.get("collectionName")
            or coll_data.get("columnName")
            or coll_data.get("boardName")
            or coll_data.get("desc")
            or (f"RedNote Collection {collection_id}" if collection_id else "RedNote Collection")
        )
        collection_name = str(collection_name).splitlines()[0].strip()[:100]

        creator_info = (
            coll_data.get("user")
            or coll_data.get("author")
            or coll_data.get("creator")
            or state_data.get("user", {}).get("basicInfo")
            or state_data.get("basicInfo")
            or {}
        )
        uploader = creator_info.get("nickname") or creator_info.get("name") or "RedNote Creator"
        user_id = str(creator_info.get("userId") or creator_info.get("user_id") or "")
        red_id = str(creator_info.get("redId") or creator_info.get("uniqueId") or creator_info.get("unique_id") or "")

        raw_notes = (
            coll_data.get("notes")
            or coll_data.get("noteList")
            or coll_data.get("items")
            or coll_data.get("collectionNotes")
            or state_data.get("notes")
            or state_data.get("noteList")
            or []
        )
        if not raw_notes and "note" in state_data and isinstance(state_data["note"], dict):
            raw_notes = list(state_data["note"].get("noteDetailMap", {}).values())

        # Flatten multi-column waterfall layout if notes are arranged into columns
        notes_list: List[Dict[str, Any]] = []
        if isinstance(raw_notes, list):
            if raw_notes and isinstance(raw_notes[0], list):
                max_col_len = max(len(col) for col in raw_notes if isinstance(col, list))
                for r in range(max_col_len):
                    for col in raw_notes:
                        if isinstance(col, list) and r < len(col) and isinstance(col[r], dict):
                            notes_list.append(col[r])
            else:
                for item in raw_notes:
                    if isinstance(item, dict):
                        notes_list.append(item)
        elif isinstance(raw_notes, dict):
            for val in raw_notes.values():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            notes_list.append(item)
                elif isinstance(val, dict):
                    notes_list.append(val)

        if not notes_list:
            raise RuntimeError(f"No notes found in RedNote collection '{collection_name}' (ID: {collection_id or 'unknown'}).")

        items: List[VideoItem] = []
        photo_count_total = 0
        video_count_total = 0
        guest_mode_detected = False
        seen_nids = set()

        for idx, raw_note in enumerate(notes_list, 1):
            if not isinstance(raw_note, dict):
                continue

            note_info = (
                raw_note.get("note")
                or raw_note.get("noteCard")
                or raw_note.get("card")
                or raw_note
            )
            if not isinstance(note_info, dict):
                continue

            nid = note_info.get("noteId") or note_info.get("id") or note_info.get("note_id")
            ntype = str(note_info.get("type", "")).lower()

            cover = note_info.get("cover") or note_info.get("image") or {}
            raw_cover = ""
            cover_w = None
            cover_h = None
            file_id = ""

            if isinstance(cover, dict):
                raw_cover = cover.get("urlDefault") or cover.get("url") or cover.get("urlPre") or ""
                cover_w = cover.get("width")
                cover_h = cover.get("height")
                file_id = cover.get("fileId") or ""
            elif isinstance(cover, str):
                raw_cover = cover

            if not file_id and raw_cover:
                clean_path = raw_cover.split("?")[0].rstrip("/")
                segments = clean_path.split("/")
                if len(segments) >= 2:
                    if segments[-2] in ("spectrum", "notes_pre_post", "pre_post"):
                        file_id = f"{segments[-2]}/{segments[-1]}"
                    else:
                        file_id = segments[-1]

            cover_url = self.resolve_xhscdn_url(raw_cover, file_id)

            if not nid:
                nid = file_id or f"{collection_id}_{idx}"
                guest_mode_detected = True

            if nid in seen_nids:
                continue
            seen_nids.add(nid)

            raw_time = note_info.get("time") or note_info.get("upload_timestamp") or note_info.get("lastUpdateTime")
            upload_date, upload_ts_sec = format_rednote_upload_date(raw_time)

            raw_title = (
                note_info.get("displayTitle")
                or note_info.get("title")
                or note_info.get("desc")
                or f"{collection_name} P{idx:02d}"
            )
            raw_title = raw_title.splitlines()[0][:100].strip() if raw_title else f"{collection_name} P{idx:02d}"

            n_user = note_info.get("user") or {}
            n_uploader = n_user.get("nickname") or n_user.get("name") or uploader

            ntitle = enrich_rednote_title(
                raw_title=raw_title,
                upload_date=upload_date,
                author=n_uploader,
                note_id=nid,
                index=idx,
            )

            xsec = note_info.get("xsecToken") or note_info.get("xsec_token") or ""
            note_url = f"https://www.xiaohongshu.com/discovery/item/{nid}?source=webshare&xhsshare=pc_web&xsec_token={xsec}&xsec_source=pc_share"

            is_video = (
                ntype == "video"
                or "video" in note_info
                or bool(note_info.get("video"))
                or bool(note_info.get("originVideoKey"))
            )

            origin_video_url = None
            if is_video:
                video_count_total += 1
                v_consumer = note_info.get("video", {}).get("consumer", {}) if isinstance(note_info.get("video"), dict) else {}
                orig_key = v_consumer.get("originVideoKey") or note_info.get("originVideoKey") or ""
                if orig_key:
                    origin_video_url = f"https://sns-video-bd.xhscdn.com/{orig_key}"

                v_info = note_info.get("video") if isinstance(note_info.get("video"), dict) else {}
                dur_raw = v_info.get("duration", 0) or note_info.get("duration", 0)
                dur_sec = int(dur_raw / 1000) if dur_raw > 1000 else int(dur_raw) if dur_raw > 0 else 0
                dur_str = f"{dur_sec // 60:02d}:{dur_sec % 60:02d}" if dur_sec > 0 else "Video"
            else:
                photo_count = 1
                if note_info.get("imageCount"):
                    try:
                        photo_count = int(note_info.get("imageCount"))
                    except Exception:
                        photo_count = 1
                elif note_info.get("imageList"):
                    photo_count = len(note_info.get("imageList"))
                photo_count_total += photo_count
                dur_sec = 0
                dur_str = f"{photo_count}P" if photo_count > 1 else "Photo"

            interact_info = note_info.get("interactInfo") or {}

            item = VideoItem(
                index=idx,
                video_id=nid,
                title=ntitle,
                duration=dur_str,
                duration_seconds=dur_sec if is_video else 0,
                status=VideoStatus.READY,
                subtitle_status="—",
                url=note_url,
                channel_title=n_uploader,
                platform="rednote",
                media_type=MediaType.VIDEO if is_video else MediaType.PHOTO,
                cover_art_url=cover_url or None,
                cover_art_width=cover_w,
                cover_art_height=cover_h,
                extra_metadata={
                    "collection_id": collection_id,
                    "collection_name": collection_name,
                    "source_type": "collection",
                    "is_photo": not is_video,
                    "xsec_token": xsec,
                    "note_type": "video" if is_video else "normal",
                    "media_type": "VIDEO" if is_video else "PHOTO",
                    "uploader": n_uploader,
                    "uploader_id": user_id,
                    "user_id": user_id,
                    "red_id": red_id,
                    "upload_date": upload_date,
                    "upload_timestamp": upload_ts_sec or raw_time,
                    "raw_title": raw_title,
                    "liked_count": interact_info.get("likedCount"),
                    "collected_count": interact_info.get("collectedCount"),
                    "comment_count": interact_info.get("commentCount"),
                    "share_count": interact_info.get("shareCount"),
                    "photo_count": photo_count if not is_video else None,
                    "photo_urls": [cover_url] if (not is_video and cover_url) else [],
                    "raw_cover": raw_cover if raw_cover else None,
                    "origin_video_url": origin_video_url,
                    "thumbnail_url": cover_url or None,
                    "canonical_url": note_url,
                },
            )
            items.append(item)

        if guest_mode_detected and log_callback:
            log_callback(
                "[AUTH NOTICE] Collection notes retrieved in guest browsing mode. "
                "For full multi-photo sets and authenticated video streams, configure RedNote cookies in Settings."
            )

        if log_callback:
            log_callback(
                f"[SUCCESS] Retrieved {len(items)} note(s) from RedNote collection: {collection_name} "
                f"({photo_count_total} Photos, {video_count_total} Videos)"
            )

        return items

    @staticmethod
    def _collect_notes_from_state(state_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extracts and flattens creator notes from window.__INITIAL_STATE__.
        Traverses user.notes (including 2D waterfall columns), userPageData.notes,
        userPageData.noteList, userPageData.items, and state.notes.
        Guarantees that placeholder empty sublists (e.g. [[], [], ...]) do not mask
        valid note structures in alternative keys.
        """
        if not isinstance(state_data, dict):
            return []

        user_data = state_data.get("user") or {}
        user_page_data = user_data.get("userPageData") or state_data.get("userPageData") or {}

        def has_valid_notes(candidate: Any) -> bool:
            if not candidate:
                return False
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, list) and len(item) > 0:
                        return True
                    if isinstance(item, dict) and item:
                        return True
                return False
            if isinstance(candidate, dict):
                return any(isinstance(v, list) and len(v) > 0 for v in candidate.values())
            return False

        candidate_sources = [
            user_data.get("notes"),
            user_page_data.get("notes"),
            user_page_data.get("noteList"),
            user_page_data.get("items"),
            state_data.get("notes"),
            state_data.get("feed", {}).get("feeds"),
        ]

        raw_notes = None
        for src in candidate_sources:
            if has_valid_notes(src):
                raw_notes = src
                break

        if not raw_notes:
            return []

        notes_list: List[Dict[str, Any]] = []
        if isinstance(raw_notes, list):
            if raw_notes and isinstance(raw_notes[0], list):
                max_col_len = max((len(col) for col in raw_notes if isinstance(col, list)), default=0)
                for r in range(max_col_len):
                    for col in raw_notes:
                        if isinstance(col, list) and r < len(col) and isinstance(col[r], dict):
                            notes_list.append(col[r])
            else:
                for item in raw_notes:
                    if isinstance(item, dict):
                        notes_list.append(item)
        elif isinstance(raw_notes, dict):
            for val in raw_notes.values():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            notes_list.append(item)
                elif isinstance(val, dict) and "notes" in val and isinstance(val["notes"], list):
                    for item in val["notes"]:
                        if isinstance(item, dict):
                            notes_list.append(item)

        return notes_list

    def _extract_profile_entries(
        self,
        user_id: str,
        profile_url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        auth_config: Optional[PlatformAuthConfig] = None,
    ) -> List[VideoItem]:
        """
        Extracts notes from a creator's public profile page via window.__INITIAL_STATE__.
        Decomposes discovered items into Photos (MediaType.PHOTO) and Videos (MediaType.VIDEO).
        Supports automatic fallback to clean canonical profile URLs if tokened URL yields 0 notes.
        """
        if log_callback:
            log_callback(f"[INFO] Scanning RedNote creator profile: {profile_url}")

        cookiejar = self._build_cookiejar(auth_config)
        html = ""
        state_data = {}
        try:
            html = self._fetch_html(profile_url, cookiejar=cookiejar)
            state_data = self._parse_initial_state(html)
        except Exception as fetch_err:
            if log_callback:
                log_callback(f"[INFO] Initial profile request failed ({fetch_err}); attempting clean URL recovery...")

        notes_list = self._collect_notes_from_state(state_data) if state_data else []

        # Fallback recovery: if initial request returned 0 notes (e.g. due to expired or note-scoped xsec_token),
        # retry with canonical clean profile URLs across domains
        if not notes_list:
            candidate_urls = [
                f"https://www.xiaohongshu.com/user/profile/{user_id}",
                f"https://www.rednote.com/user/profile/{user_id}",
            ]
            for candidate_url in candidate_urls:
                if candidate_url == profile_url:
                    continue
                if log_callback:
                    log_callback(f"[INFO] Initial profile request yielded 0 notes; retrying with clean URL: {candidate_url}")
                try:
                    fallback_html = self._fetch_html(candidate_url, cookiejar=cookiejar)
                    fallback_state = self._parse_initial_state(fallback_html)
                    if fallback_state:
                        candidate_notes = self._collect_notes_from_state(fallback_state)
                        if candidate_notes:
                            state_data = fallback_state
                            notes_list = candidate_notes
                            profile_url = candidate_url
                            break
                except Exception:
                    pass

        if not state_data:
            raise RuntimeError("REDNOTE_PROFILE_BLOCKED: Could not extract profile initial state. Fresh cookies required.")

        user_data = state_data.get("user") or {}
        user_page_data = user_data.get("userPageData") or state_data.get("userPageData") or {}
        basic_info = (
            user_page_data.get("basicInfo")
            or user_data.get("basicInfo")
            or state_data.get("basicInfo")
            or {}
        )
        uploader = (
            basic_info.get("nickname")
            or basic_info.get("name")
            or user_data.get("nickname")
            or f"RedNote Creator {user_id}"
        )

        if not notes_list:
            posted_cnt = user_page_data.get("posted")
            if posted_cnt == 0:
                raise RuntimeError(f"Creator {uploader} (ID: {user_id}) has published 0 public notes.")
            raise RuntimeError(
                f"No public notes found for RedNote creator {uploader} (ID: {user_id}). "
                f"The notes may require authentication or account login cookies in Settings."
            )

        items: List[VideoItem] = []
        photo_count_total = 0
        video_count_total = 0
        guest_mode_detected = False
        seen_nids = set()

        for idx, raw_note in enumerate(notes_list, 1):
            if not isinstance(raw_note, dict):
                continue

            note_info = (
                raw_note.get("note")
                or raw_note.get("noteCard")
                or raw_note.get("card")
                or raw_note
            )
            if not isinstance(note_info, dict):
                continue

            # High-resolution cover extraction and asset file ID resolution
            cover_info = note_info.get("cover") or note_info.get("image") or {}
            file_id = ""
            raw_cover = ""
            cover_url = ""
            cover_w = None
            cover_h = None
            if isinstance(cover_info, dict):
                file_id = cover_info.get("fileId") or ""
                raw_cover = (
                    cover_info.get("urlDefault")
                    or cover_info.get("urlPre")
                    or cover_info.get("url")
                    or ""
                )
                cover_url = self.resolve_xhscdn_url(raw_cover, file_id)
                if not file_id and raw_cover:
                    # In RedNote web SSR, asset IDs are the last path segment before parameters/tags
                    path_clean = raw_cover.split("?")[0].split("!")[0]
                    segments = [s for s in path_clean.split("/") if s]
                    if segments and len(segments[-1]) >= 20:
                        file_id = segments[-1]
                cover_w = cover_info.get("width")
                cover_h = cover_info.get("height")

            explicit_nid = note_info.get("noteId") or note_info.get("id") or note_info.get("note_id") or ""
            if explicit_nid:
                nid = explicit_nid
            else:
                guest_mode_detected = True
                nid = file_id or f"{user_id}_{note_info.get('time') or idx}"

            if not nid or nid in seen_nids:
                continue
            seen_nids.add(nid)

            raw_time = note_info.get("time") or note_info.get("upload_timestamp") or note_info.get("lastUpdateTime")
            upload_date, upload_ts_sec = format_rednote_upload_date(raw_time)

            raw_title = (
                note_info.get("displayTitle")
                or note_info.get("title")
                or note_info.get("desc")
                or f"RedNote {nid}"
            )
            raw_title = raw_title.splitlines()[0].strip() if raw_title else f"RedNote {nid}"

            ntitle = enrich_rednote_title(
                raw_title=raw_title,
                upload_date=upload_date,
                author=uploader,
                note_id=nid,
                index=idx,
            )

            ntype = str(note_info.get("type") or note_info.get("modelType") or note_info.get("cardType") or "normal").lower()
            xsec = note_info.get("xsecToken") or note_info.get("xsec_token") or ""

            if explicit_nid:
                note_url = f"https://www.xiaohongshu.com/explore/{explicit_nid}"
                if xsec:
                    note_url += f"?xsec_token={xsec}"
                canonical_share_url = (
                    f"https://www.xiaohongshu.com/discovery/item/{explicit_nid}"
                    f"?source=webshare&xhsshare=pc_web&xsec_token={xsec}&xsec_source=pc_share"
                    if xsec else
                    f"https://www.xiaohongshu.com/discovery/item/{explicit_nid}?source=webshare&xhsshare=pc_web&xsec_source=pc_share"
                )
            else:
                base_p = profile_url.split("#")[0]
                note_url = f"{base_p}#{nid}"
                canonical_share_url = note_url

            vid_obj = note_info.get("video")
            has_video_obj = bool(isinstance(vid_obj, dict) and vid_obj)
            is_video = (ntype == "video") or has_video_obj

            dur_sec = None
            dur_str = "-"
            origin_video_url = None
            photo_count = None
            photo_urls = []

            if is_video:
                video_count_total += 1
                vid_data = vid_obj if isinstance(vid_obj, dict) else {}
                duration_raw = vid_data.get("duration") or note_info.get("duration")
                if duration_raw:
                    try:
                        dur_sec = int(duration_raw)
                        if dur_sec > 1000:
                            dur_sec = dur_sec // 1000
                        mins = dur_sec // 60
                        secs = dur_sec % 60
                        dur_str = f"{mins:02d}:{secs:02d}"
                    except Exception:
                        dur_sec = None
                        dur_str = "-"
                origin_key = (
                    vid_data.get("consumer", {}).get("originVideoKey")
                    if isinstance(vid_data.get("consumer"), dict)
                    else None
                )
                if origin_key:
                    origin_video_url = f"https://sns-video-bd.xhscdn.com/{origin_key}"
            else:
                photo_count_total += 1
                img_list = note_info.get("imageList") or note_info.get("images")
                if isinstance(img_list, list) and img_list:
                    photo_count = len(img_list)
                    for img in img_list:
                        if isinstance(img, dict):
                            p_fid = img.get("fileId") or ""
                            p_raw = img.get("urlDefault") or img.get("url") or img.get("urlPre") or ""
                            resolved_p = self.resolve_xhscdn_url(p_raw, p_fid)
                            if resolved_p:
                                photo_urls.append(resolved_p)
                elif note_info.get("imageCount"):
                    try:
                        photo_count = int(note_info.get("imageCount"))
                    except Exception:
                        photo_count = None

                if not photo_urls and cover_url:
                    photo_urls = [cover_url]

                if not photo_count and photo_urls:
                    photo_count = len(photo_urls)

                if photo_count and photo_count > 0:
                    dur_str = f"{photo_count}P"
                else:
                    dur_str = "Photo"

            item = VideoItem(
                index=idx,
                video_id=nid,
                title=ntitle,
                duration=dur_str,
                duration_seconds=dur_sec,
                status=VideoStatus.READY,
                subtitle_status="—",
                url=note_url,
                channel_title=uploader,
                platform="rednote",
                media_type=MediaType.VIDEO if is_video else MediaType.PHOTO,
                cover_art_url=cover_url or None,
                cover_art_width=cover_w,
                cover_art_height=cover_h,
                extra_metadata={
                    "is_photo": not is_video,
                    "xsec_token": xsec,
                    "note_type": ntype,
                    "media_type": "VIDEO" if is_video else "IMAGE",
                    "uploader": uploader,
                    "uploader_id": user_id,
                    "user_id": user_id,
                    "upload_date": upload_date,
                    "upload_timestamp": upload_ts_sec or raw_time,
                    "raw_title": raw_title,
                    "liked_count": (note_info.get("interactInfo") or {}).get("likedCount"),
                    "collected_count": (note_info.get("interactInfo") or {}).get("collectedCount"),
                    "comment_count": (note_info.get("interactInfo") or {}).get("commentCount"),
                    "share_count": (note_info.get("interactInfo") or {}).get("shareCount"),
                    "photo_count": photo_count,
                    "photo_urls": photo_urls if not is_video else [],
                    "raw_cover": raw_cover if raw_cover else None,
                    "origin_video_url": origin_video_url,
                    "thumbnail_url": cover_url or None,
                    "canonical_url": canonical_share_url,
                },
            )
            items.append(item)

        if guest_mode_detected and log_callback:
            log_callback(
                "[AUTH NOTICE] Creator notes retrieved in guest browsing mode. "
                "For full multi-photo sets and authenticated video streams, configure RedNote cookies in Settings."
            )

        if log_callback:
            log_callback(
                f"[SUCCESS] Retrieved {len(items)} note(s) from RedNote creator profile: {uploader} "
                f"({photo_count_total} Photos, {video_count_total} Videos)"
            )

        return items

    def scan_profile_archive(
        self,
        url: str,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> ScanResult:
        """
        Coordinates full creator profile scanning through ProfileScanManager.
        """
        from downloader.profile_scan_manager import ProfileScanManager
        manager = ProfileScanManager()
        return manager.scan_profile(
            url=url,
            platform="rednote",
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            log_callback=log_callback,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )

    def scan(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> ScanResult:
        """Scans RedNote URL returning a normalized ScanResult."""
        clean_url = self.normalize_url(url)
        videos = self.extract_entries(
            url=clean_url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
        )
        first_uploader = videos[0].channel_title if videos else "RedNote Creator"
        is_coll = self.is_collection_url(clean_url)
        is_user_profile = bool(self._USER_URL_PATTERN.search(clean_url))

        if is_coll:
            coll_name = (videos[0].extra_metadata.get("collection_name") if videos else "") or "RedNote Collection"
            source_title = coll_name
            source_type = "collection"
        elif is_user_profile:
            source_title = first_uploader
            source_type = "creator"
        elif videos and videos[0].media_type == MediaType.PHOTO:
            source_title = first_uploader
            source_type = "photo"
        else:
            source_title = first_uploader
            source_type = "video"

        return ScanResult(
            source_title=source_title,
            videos=videos,
            source_type=source_type,
            platform="rednote",
            url=clean_url,
        )
