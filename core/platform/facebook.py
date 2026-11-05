"""
facebook.py
PlatformAdapter implementation for Facebook in Channel Harvest.
Encapsulates URL parsing, short/redirect URL resolution, validation,
platform-scoped authentication, and yt-dlp extraction for Facebook videos and Reels.
"""

import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import yt_dlp
from yt_dlp.utils import UnsupportedError, DownloadError, ExtractorError

from core.models import VideoItem, DownloadSettings, VideoStatus, ScanResult
from core.availability import AvailabilityDetectorRegistry, AvailabilityStatus
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector
from core.platform.auth import PlatformAuthConfig

# Regular expression components for Facebook metrics/stats prefixes
# English metrics (views, reactions, shares, comments, likes, plays)
_EN_METRICS = r'(?:views?|reactions?|shares?|comments?|likes?|plays?)'
# Chinese metrics (观看, 次观看, 播放, 点赞, 心情, 分享, 评论, 留言, 互动, etc.)
_CHINESE_METRICS = r'(?:(?:次|个|個|条|條|则|則)?\s*(?:观看|觀看|播放|赞|讚|点赞|點讚|心情|分享|评论|評論|留言|互动|互動))'
_STAT_KEYWORD = rf'(?:{_EN_METRICS}|{_CHINESE_METRICS})'
_STAT_TOKEN = rf'[\d.,]+[kKmMbB千百萬万wW]?\+?\s*{_STAT_KEYWORD}'

# Matches the leading stats prefix before the real title separator (| or ｜ or — or – or ' - ' or ' : ' or \n)
_FACEBOOK_STAT_PREFIX_RE = re.compile(
    rf"""^\s*['"]?(?:{_STAT_TOKEN}\s*[\xb7\u2022,·/&|-]?\s*)*{_STAT_TOKEN}\s*(?:[|\uff5c\u2014\u2013]|\s+-\s+|\s*:\s+|\r?\n)\s*""",
    re.IGNORECASE,
)

# Matches titles that consist solely of stats metrics with no subsequent title
_FACEBOOK_STAT_ONLY_RE = re.compile(
    rf"""^\s*['"]?(?:{_STAT_TOKEN}\s*[\xb7\u2022,·/&|-]?\s*)*{_STAT_TOKEN}\s*['"]?\s*$""",
    re.IGNORECASE,
)


def clean_facebook_title(raw_title: str, fallback: str = "") -> str:
    """
    Strips leading Facebook views, reactions, shares, and metrics prefixes from video and Reel titles,
    preserving only the subsequent authentic video title.

    Examples:
        '9.7K views · 352 reactions | My Reel Title 👊 | Page' -> 'My Reel Title 👊 | Page'
        '119 reactions · 1.4K shares | Asif Nawab Butt on Reels' -> 'Asif Nawab Butt on Reels'
        '1.5万次观看 · 352次点赞 | 视频标题' -> '视频标题'
        '500 views | Single Stat Title' -> 'Single Stat Title'
        '10 views on life and philosophy | My Lecture' -> '10 views on life and philosophy | My Lecture'
    """
    if not raw_title or not isinstance(raw_title, str):
        return fallback
    clean = raw_title.strip()

    # Multiline check: if line 1 is only stats, take subsequent lines
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if len(lines) > 1 and _FACEBOOK_STAT_ONLY_RE.match(lines[0]):
        remainder = " ".join(lines[1:]).strip()
        cleaned_rem = clean_facebook_title(remainder, fallback=fallback)
        if cleaned_rem and cleaned_rem != fallback:
            return cleaned_rem

    m = _FACEBOOK_STAT_PREFIX_RE.match(clean)
    if m:
        stripped = clean[m.end():].strip().strip("'\"")
        if stripped:
            first_line = stripped.splitlines()[0].strip()
            if first_line:
                clean = first_line
    else:
        clean = lines[0] if lines else ""

    if _FACEBOOK_STAT_ONLY_RE.match(clean):
        return fallback

    # Strip all "#" and full-width "＃" characters and apply Chinese 50 / English 30 word capping
    from core.platform.facebook_comet import format_caption_title
    return format_caption_title(clean, fallback=fallback)

class FacebookAdapter(PlatformAdapter):
    @classmethod
    def is_profile_url(cls, url: str) -> bool:
        """
        Determines whether the given Facebook URL points to a profile, page, or album archive
        rather than an individual video, Reel, watch URL, or short link.
        """
        if not url or not isinstance(url, str):
            return False
        clean = (PlatformDetector.extract_url(url) or url).strip()
        parsed = urlparse(clean)
        path = parsed.path.rstrip("/")
        low_path = path.lower()

        # Specific individual media endpoints with query parameters or short links
        qs = parsed.query
        if "watch" in low_path and ("v=" in qs or "video_id=" in qs):
            return False
        if "video.php" in low_path and ("v=" in qs or "video_id=" in qs):
            return False
        if any(k in low_path for k in ("fb.watch", "fb.me", "/share/v", "/share/r")):
            return False

        segments = [s for s in path.strip("/").split("/") if s]

        # Individual video/reel with numeric/explicit ID
        if len(segments) >= 2 and segments[-2].lower() in ("reel", "videos") and segments[-1].isdigit():
            return False
        if len(segments) >= 3 and segments[-2].lower() == "videos" and segments[-1].isdigit():
            return False

        # Individual video/reel with explicit root segments (e.g. /reel/<id> or /watch/<id>)
        if len(segments) >= 2 and segments[0].lower() in ("reel", "watch"):
            return False

        # Profile tabs (photos, videos, reels, posts, about, community)
        if len(segments) >= 2 and segments[-1].lower() in ("videos", "video", "reels", "reel", "photos", "photo", "photos_albums", "about", "community", "posts"):
            return True

        if "profile.php" in low_path and "id=" in parsed.query:
            return True
        if len(segments) >= 2 and segments[0].lower() in ("pages", "people") and segments[-1].isdigit():
            return True
        if len(segments) == 1 and not any(k in segments[0].lower() for k in (
            "home.php", "messages", "login.php", "help", "settings", "recover",
            "notifications", "marketplace", "groups", "events", "watch", "reel"
        )):
            return True
        if "photo" in low_path or "set=a." in clean.lower() or "/media/set" in low_path:
            return True
        return False

    @staticmethod
    def clean_title(raw_title: str, fallback: str = "") -> str:
        return clean_facebook_title(raw_title, fallback=fallback)
    """
    Concrete platform adapter for Facebook.
    Supports Facebook videos, Reels, mobile variants, and redirecting share links.
    """

    # Primary Facebook URL patterns
    _WATCH_PATTERN = re.compile(
        r"https?://(?:[\w-]+\.)?facebook\.com/watch(?:/live)?/?\?(?:.*&)?(?:v|video_id)=(?P<id>\d+)",
        re.IGNORECASE,
    )
    _VIDEO_PATH_PATTERN = re.compile(
        r"https?://(?:[\w-]+\.)?facebook\.com/(?:[^/]+/videos/|video\.php\?v=)(?P<id>\d+)",
        re.IGNORECASE,
    )
    _REEL_PATTERN = re.compile(
        r"https?://(?:[\w-]+\.)?facebook\.com/reel/(?P<id>\d+)",
        re.IGNORECASE,
    )
    _SHORT_URL_PATTERN = re.compile(
        r"https?://(?:(?:www\.)?fb\.watch|(?:www\.)?fb\.me|(?:[\w-]+\.)?facebook\.com/share/(?:v|r))/(?P<id>[\w-]+)",
        re.IGNORECASE,
    )

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=False,   # Facebook videos typically lack standard external SRT
            supports_thumbnails=True,  # Video thumbnail supported
            supports_description=True, # Post description / caption supported
            supports_metadata=True,    # Full metadata (.metadata.txt) supported
            supports_chapters=False,   # Facebook videos do not have chapters
            supports_playlists=False,  # Single video / reel primary focus
            supports_channel_scan=True,# Video scanning supported
            supports_browser_cookies=False,  # Browser cookies not supported in initial release
            supports_cookie_file=True, # Custom cookie file fully supported
            supports_profile_media_archive=True,
            archive_prefix="facebook",
        )

    @property
    def platform_id(self) -> str:
        return "facebook"

    @property
    def display_name(self) -> str:
        return "Facebook"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Determines whether the given URL is a Facebook URL."""
        if not url or not isinstance(url, str):
            return False
        return PlatformDetector.identify_platform_id(url) == "facebook"

    def resolve_short_link(self, url: str, timeout: float = 6.0) -> str:
        """
        Follows HTTP redirects for Facebook short share links (fb.watch, fb.me, facebook.com/share/)
        to discover the canonical web URL.
        """
        cleaned = (url or "").strip()
        low = cleaned.lower()
        if not any(k in low for k in ("fb.watch", "fb.me", "/share/v/", "/share/r/")):
            return cleaned

        try:
            req = urllib.request.Request(
                cleaned,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            opener = urllib.request.build_opener()
            with opener.open(req, timeout=timeout) as response:
                return response.geturl()
        except urllib.error.HTTPError as e:
            if e.headers and "Location" in e.headers:
                return e.headers["Location"]
            return cleaned
        except Exception:
            return cleaned

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates Facebook URL format.
        Accepts standard video URLs, /watch/?v=..., /reel/..., /videos/..., mobile domains,
        and share URLs.
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a Facebook video or Reel URL."

        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = (parsed.netloc or "").lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.FACEBOOK_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid Facebook domain."

            path = parsed.path or ""
            if not path or path == "/":
                return False, "Please provide a specific Facebook video or Reel URL."

            # Check known supported path patterns
            qs = parse_qs(parsed.query)
            has_video_param = any(k in qs for k in ("v", "video_id", "story_fbid"))

            is_watch = path.startswith("/watch") and has_video_param
            is_reel = "/reel/" in path or "/reels/" in path or path.rstrip("/").endswith("/reel") or path.rstrip("/").endswith("/reels")
            is_videos = "/videos/" in path or path.rstrip("/").endswith("/videos")
            is_video_php = "video.php" in path and has_video_param
            is_short = any(host in netloc for host in ("fb.watch", "fb.me")) or "/share/" in path
            is_permalink = ("permalink.php" in path or "/posts/" in path or "/story.php" in path) and (has_video_param or any(c.isdigit() for c in path))

            is_photo = 'photo' in path or 'photo.php' in path or '/photos' in path or 'fbid=' in parsed.query
            is_album = '/media/set' in path or 'set=a.' in parsed.query
            segments = [p for p in path.strip('/').split('/') if p]
            is_profile = self.is_profile_url(cleaned) or (len(segments) == 1 and not any(k in segments[0].lower() for k in ('home.php', 'messages', 'login.php', 'help', 'settings', 'recover', 'notifications', 'marketplace', 'groups', 'events', 'watch', 'reel'))) or (len(segments) >= 2 and segments[0] in ('pages', 'people') and segments[-1].isdigit()) or ('profile.php' in path and 'id=' in parsed.query)

            if not (is_watch or is_reel or is_videos or is_video_php or is_short or is_permalink or is_photo or is_album or is_profile):
                return False, "Unsupported Facebook URL format. Please provide a video or Reel link."

            return True, ""

        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def normalize_url(self, url: str) -> str:
        """
        Normalizes Facebook URL for extraction.
        Strips transient tracking parameters (ref, fbclid, mibextid, etc.) while
        carefully preserving essential video identifiers (v, video_id, story_fbid).
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()

        try:
            parsed = urlparse(cleaned)
            netloc = (parsed.netloc or "").lower().split(":")[0]

            # Preserve scheme and domain
            scheme = parsed.scheme or "https"
            path = parsed.path

            # Clean tracking query parameters
            qs = parse_qs(parsed.query)
            keep_params = {"v", "video_id", "story_fbid", "id"}
            cleaned_query_dict = {k: v for k, v in qs.items() if k in keep_params}

            # Standardize /watch path if v query param exists
            if "v" in cleaned_query_dict and (path == "/watch" or path == "/watch/"):
                path = "/watch/"

            new_query = urlencode(cleaned_query_dict, doseq=True) if cleaned_query_dict else ""
            normalized = urlunparse((scheme, netloc, path, "", new_query, ""))
            return normalized.rstrip("/") if not new_query and not path.endswith("/") else normalized
        except Exception:
            return cleaned

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """Constructs a canonical playback URL from a video ID."""
        if original_url and "facebook.com" in original_url:
            return original_url
        return f"https://www.facebook.com/watch/?v={video_id}"

    def clean_url(self, url: str) -> str:
        """Alias for normalize_url."""
        return self.normalize_url(url)

    def get_canonical_url(self, video_id: str, original_url: str = "") -> str:
        """Alias for build_video_url."""
        return self.build_video_url(video_id, original_url)

    def generate_archive_tag(self, video_id: str) -> str:
        """Generates the archive tag for a video ID."""
        return f"facebook {video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        """Returns the entry format for download_archive.txt."""
        return self.generate_archive_tag(video.video_id)

    def build_ydl_options(
        self,
        auth_config: Optional[PlatformAuthConfig] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Builds yt-dlp option dictionary for Facebook requests."""
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="facebook",
            auth_config=auth_config,
        )
        opts.update(kwargs)
        return opts

    def get_auth_config(self, settings: Optional[Any] = None) -> PlatformAuthConfig:
        """
        Resolves Facebook-specific authentication configuration.
        Strictly isolated from YouTube, TikTok, and Bilibili authentication settings.
        Supports:
        1. None (auth_method == 'none')
        2. Custom Cookie File (auth_method == 'custom_file' with valid cookie_file path)
        """
        from pathlib import Path
        auth_method = "none"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("facebook_auth_method", "none") or "none"
                custom_cookie_file = settings.get("facebook_custom_cookie_file", "") or ""
            elif hasattr(settings, "facebook_auth_method"):
                auth_method = getattr(settings, "facebook_auth_method", "none") or "none"
                custom_cookie_file = getattr(settings, "facebook_custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                auth_method = settings.get("facebook_auth_method", "none") or "none"
                custom_cookie_file = settings.get("facebook_custom_cookie_file", "") or ""
        else:
            try:
                from core.settings import SettingsManager
                sm = SettingsManager()
                auth_method = sm.get("facebook_auth_method", "none")
                custom_cookie_file = sm.get("facebook_custom_cookie_file", "")
            except Exception:
                pass

        if auth_method == "custom_file":
            if not custom_cookie_file:
                return PlatformAuthConfig(
                    auth_method="none",
                    description="Custom Cookie File (No file path configured)",
                )
            cpath = Path(custom_cookie_file)
            if not cpath.is_file():
                return PlatformAuthConfig(
                    auth_method="none",
                    description="Custom Cookie File (File not found on disk)",
                )
            return PlatformAuthConfig(
                auth_method="custom_file",
                cookie_file=str(cpath.resolve()),
                description="Custom Cookie File",
            )

        # Fallback to 'all' if Facebook has no authentication configured
        from core.platform.auth import resolve_effective_cookie_file
        eff_method, eff_file, desc_suffix = resolve_effective_cookie_file(
            "facebook", auth_method, custom_cookie_file, settings=settings
        )
        if eff_method == "custom_file" and eff_file:
            cpath = Path(eff_file)
            if cpath.is_file():
                return PlatformAuthConfig(
                    auth_method="custom_file",
                    cookie_file=str(cpath.resolve()),
                    description=f"Custom Cookie File{desc_suffix}",
                )

        return PlatformAuthConfig.none()

    def scan(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        **kwargs,
    ) -> ScanResult:
        """
        Scans a Facebook video or Reel URL and returns a normalized ScanResult.
        Runs yt-dlp metadata extraction without downloading media.
        """
        if is_cancelled and is_cancelled():
            return ScanResult(source_title="", videos=[], url=url)

        is_valid, reason = self.validate_url(url)
        if not is_valid:
            from downloader.ytdlp_engine import InvalidURLError
            raise InvalidURLError(reason)

        # Resolve short share links if needed
        resolved_url = self.resolve_short_link(url)
        normalized_url = self.normalize_url(resolved_url)

        if self.is_profile_url(normalized_url):
            if log_callback:
                log_callback(f"[INFO] Facebook profile URL detected: {normalized_url}. Direct playlist extraction via yt-dlp is not supported by yt-dlp.")
            from downloader.ytdlp_engine import InvalidURLError
            raise InvalidURLError(
                f"Facebook profile URL '{normalized_url}' cannot be scanned directly as a video playlist by yt-dlp. Profile archive scanning is handled via ProfileScanManager / gallery-dl."
            )

        if log_callback:
            log_callback(f"[INFO] Connecting to Facebook: {normalized_url}")

        from downloader.ytdlp_engine import YtDlpEngine, NetworkError, ExtractionError, EmptyChannelError
        engine = YtDlpEngine()

        # Resolve authentication configuration
        if auth_config is None:
            settings_dict = {}
            if custom_cookie_file:
                settings_dict["facebook_auth_method"] = "custom_file"
                settings_dict["facebook_custom_cookie_file"] = custom_cookie_file
            auth_config = self.get_auth_config(settings=settings_dict if settings_dict else None)

        ydl_opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="facebook",
            auth_config=auth_config,
        )
        ydl_opts.update({
            "skip_download": True,
            "extract_flat": "in_playlist",
        })

        max_attempts = 2
        info = None
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if log_callback:
                        if attempt > 1:
                            log_callback(f"[INFO] Fetching metadata from Facebook (attempt {attempt}/{max_attempts})...")
                        else:
                            log_callback("[INFO] Fetching metadata from Facebook...")
                    info = ydl.extract_info(normalized_url, download=False)
                    if info:
                        break

            except UnsupportedError as e:
                from downloader.ytdlp_engine import InvalidURLError
                raise InvalidURLError(f"Facebook URL not supported by extractor: {str(e)}") from e

            except DownloadError as e:
                err_msg = str(e)
                last_exception = e
                low = err_msg.lower()

                # Distinguish authentication requirements and access restrictions
                if any(k in low for k in ("log in to continue", "you must log in", "login required")):
                    raise ExtractionError(f"Facebook requires login to access this content. Configure a valid cookie file in Settings: {err_msg}") from e
                if any(k in low for k in ("isn't available right now", "content isn't available", "not available", "may have been removed")):
                    raise ExtractionError(f"Facebook video is unavailable or private: {err_msg}") from e
                if "permission" in low or "private" in low or "access denied" in low:
                    raise ExtractionError(f"Facebook access denied or private post: {err_msg}") from e

                # Transient network or HTTP 5xx errors
                if attempt < max_attempts:
                    if any(k in low for k in ("http error 5", "500", "502", "503", "timed out", "connection")):
                        if log_callback:
                            log_callback(f"[WARNING] Facebook temporary error: {err_msg}. Retrying in 1.5s...")
                        time.sleep(1.5)
                        continue

                if any(term in low for term in ("unable to download", "timed out", "connection", "network")):
                    raise NetworkError(f"Network error while connecting to Facebook: {err_msg}") from e

                raise ExtractionError(f"Facebook extraction failed: {err_msg}") from e

            except Exception as e:
                last_exception = e
                if attempt < max_attempts:
                    time.sleep(1.5)
                    continue
                raise ExtractionError(f"Unexpected error during Facebook extraction: {str(e)}") from e

        if not info:
            if last_exception:
                raise ExtractionError(f"Facebook extraction failed: {str(last_exception)}") from last_exception
            raise EmptyChannelError("No video information could be retrieved for this Facebook URL.")

        # Classify entries vs single video
        raw_entries = info.get("entries")
        video_items: List[VideoItem] = []
        detector = AvailabilityDetectorRegistry.get_detector("facebook")
        auth_active = bool(auth_config and auth_config.is_active)

        if raw_entries is not None:
            # Listing / Playlist case
            entries_list = [e for e in raw_entries if e]
            raw_source_title = info.get("title") or info.get("uploader") or "Facebook Videos"
            source_title = clean_facebook_title(raw_source_title, fallback=info.get("uploader") or "Facebook Videos")
            source_type = "page"

            for idx, entry in enumerate(entries_list, start=1):
                vid_id = str(entry.get("id") or f"fb_{idx}")
                raw_title = entry.get("title") or ""
                raw_desc = entry.get("description") or ""

                clean_title = clean_facebook_title(raw_title, fallback="")
                if not clean_title and raw_desc:
                    clean_title = clean_facebook_title(raw_desc, fallback="")
                if not clean_title:
                    clean_title = f"Facebook Video {vid_id}"

                dur_raw = entry.get("duration")
                dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
                dur_str = YtDlpEngine.format_duration(dur_secs)

                entry_url = entry.get("webpage_url") or entry.get("url") or self.build_video_url(vid_id)
                uploader = entry.get("uploader") or entry.get("channel") or info.get("uploader") or source_title

                avail = detector.detect_entry(
                    entry=entry,
                    video_id=vid_id,
                    title=clean_title,
                    url=entry_url,
                    auth_active=auth_active,
                )

                extra_meta = {
                    "uploader": uploader,
                    "uploader_id": entry.get("uploader_id") or info.get("uploader_id"),
                    "view_count": entry.get("view_count"),
                    "like_count": entry.get("like_count"),
                    "comment_count": entry.get("comment_count"),
                    "repost_count": entry.get("repost_count") or entry.get("share_count"),
                    "thumbnail": entry.get("thumbnail"),
                    "timestamp": entry.get("timestamp"),
                    "upload_date": entry.get("upload_date"),
                }

                if avail.is_definitively_inaccessible():
                    selected = False
                    status = VideoStatus.SKIPPED
                    error_reason = avail.user_message or avail.status.value
                    if avail.status == AvailabilityStatus.PRIVATE:
                        extra_meta["inaccessibility"] = "PRIVATE_VIDEO"
                    else:
                        extra_meta["inaccessibility"] = "VIDEO_UNAVAILABLE"
                else:
                    selected = True
                    status = VideoStatus.READY
                    error_reason = ""

                item = VideoItem(
                    index=idx,
                    video_id=vid_id,
                    title=clean_title,
                    duration=dur_str,
                    duration_seconds=dur_secs,
                    status=status,
                    subtitle_status="—",
                    url=entry_url,
                    selected=selected,
                    channel_title=uploader,
                    platform="facebook",
                    error_reason=error_reason,
                    extra_metadata=extra_meta,
                    availability=avail,
                )
                video_items.append(item)

        else:
            # Single video / Reel case
            vid_id = str(info.get("id") or "facebook_video")
            raw_title = info.get("title") or ""
            raw_desc = info.get("description") or ""

            # Extract real title whenever available; strip leading views and reactions
            clean_title = clean_facebook_title(raw_title, fallback="")
            if not clean_title and raw_desc:
                clean_title = clean_facebook_title(raw_desc, fallback="")
            if not clean_title:
                clean_title = f"Facebook Video {vid_id}" 

            dur_raw = info.get("duration")
            dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
            dur_str = YtDlpEngine.format_duration(dur_secs)

            uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
            webpage_url = info.get("webpage_url") or normalized_url

            # Detect if this is a Reel
            is_reel = (
                "/reel/" in normalized_url.lower()
                or str(info.get("extractor_key", "")).lower() == "facebookreel"
                or str(info.get("extractor", "")).lower() == "facebook:reel"
            )
            source_type = "reel" if is_reel else "video"
            source_title = clean_title

            avail = detector.detect_entry(
                entry=info,
                video_id=vid_id,
                title=clean_title,
                url=webpage_url,
                auth_active=auth_active,
            )

            extra_meta = {
                "uploader": uploader,
                "uploader_id": info.get("uploader_id"),
                "uploader_url": info.get("uploader_url"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "repost_count": info.get("repost_count") or info.get("share_count"),
                "thumbnail": info.get("thumbnail"),
                "timestamp": info.get("timestamp"),
                "upload_date": info.get("upload_date"),
                "is_reel": is_reel,
            }

            if avail.is_definitively_inaccessible():
                selected = False
                status = VideoStatus.SKIPPED
                error_reason = avail.user_message or avail.status.value
                if avail.status == AvailabilityStatus.PRIVATE:
                    extra_meta["inaccessibility"] = "PRIVATE_VIDEO"
                else:
                    extra_meta["inaccessibility"] = "VIDEO_UNAVAILABLE"
            else:
                selected = True
                status = VideoStatus.READY
                error_reason = ""

            item = VideoItem(
                index=1,
                video_id=vid_id,
                title=clean_title,
                duration=dur_str,
                duration_seconds=dur_secs,
                status=status,
                subtitle_status="—",
                url=webpage_url,
                selected=selected,
                channel_title=uploader or "Facebook",
                platform="facebook",
                error_reason=error_reason,
                extra_metadata=extra_meta,
                availability=avail,
            )
            video_items.append(item)

        if not video_items:
            raise EmptyChannelError(f"No downloadable videos found for Facebook source '{source_title}'.")

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} Facebook video(s).")
            if video_items:
                log_callback(f"[INFO] Facebook video: '{video_items[0].title}' (ID: {video_items[0].video_id})")

        return ScanResult(
            videos=video_items,
            source_title=source_title,
            source_type=source_type,
            platform="facebook",
            url=url,
        )

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        **kwargs,
    ) -> List[VideoItem]:
        """Scans the Facebook URL and returns normalized VideoItems."""
        return self.scan(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            is_cancelled=is_cancelled,
            **kwargs,
        ).videos

    def scan_profile_archive(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        **kwargs,
    ) -> ScanResult:
        """
        Scans a Facebook profile or public page media archive using ProfileScanManager.
        Discovers photo albums, photos, and videos with persistent inventory.
        """
        if auth_config is None:
            auth_config = self.get_auth_config()
        if not custom_cookie_file and auth_config and auth_config.cookie_file:
            custom_cookie_file = auth_config.cookie_file

        from downloader.profile_scan_manager import ProfileScanManager
        manager = ProfileScanManager()
        return manager.scan_profile(
            url=url,
            platform=self.platform_id,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            log_callback=log_callback,
            is_cancelled=is_cancelled,
        )
    def get_comet_client(
        self,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> Any:
        """
        Returns an initialized FacebookCometClient configured with the effective cookie file.
        """
        from core.platform.facebook_comet import FacebookCometClient
        eff_cookie = custom_cookie_file
        if not eff_cookie:
            if auth_config is None:
                auth_config = self.get_auth_config()
            if auth_config and auth_config.cookie_file:
                eff_cookie = auth_config.cookie_file
        return FacebookCometClient(cookie_file=eff_cookie)

