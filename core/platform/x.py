"""
x.py
PlatformAdapter implementation for X (formerly Twitter) in Channel Harvest.
Encapsulates URL parsing, validation, normalization, platform-scoped authentication,
and yt-dlp extraction for single video posts, multi-video posts, and profiles.
Channel Harvest - Multi-Platform Architecture.
"""

import re
import time
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


def clean_x_title(raw_title: str, caption: str = "", fallback: str = "") -> str:
    """
    Produces a clean, human-readable title for an X (Twitter) post or media item.
    - Strips trailing t.co short links often appended to tweets.
    - Strips redundant 'Username - ' prefixes added by some yt-dlp extractors.
    - Bounded to a readable first line or sentence (up to 120 chars).
    - Preserves meaningful Unicode, Chinese, Emoji, hashtags, and mentions.
    - Falls back to raw_title or fallback if text is empty.
    """
    candidate = ""
    # Try raw_title first, then caption/description
    text_source = (raw_title or "").strip() or (caption or "").strip()

    if text_source:
        # Strip trailing t.co URLs (e.g. https://t.co/xyz123)
        cleaned_text = re.sub(r"https?://t\.co/[a-zA-Z0-9_-]+", "", text_source).strip()

        # Split into lines and take the first non-empty line
        lines = [ln.strip() for ln in cleaned_text.splitlines() if ln.strip()]
        if lines:
            first_line = lines[0]
            # Strip redundant 'Author - ' or 'Author: ' prefix if present
            if " - " in first_line:
                parts = first_line.split(" - ", 1)
                # If first part looks like a short screen name / title and second part has content
                if len(parts) == 2 and len(parts[0]) <= 30 and parts[1].strip():
                    first_line = parts[1].strip()
            elif ": " in first_line:
                parts = first_line.split(": ", 1)
                if len(parts) == 2 and len(parts[0]) <= 30 and parts[1].strip():
                    first_line = parts[1].strip()

            if len(first_line) > 120:
                # Truncate at word/space boundary if possible
                truncated = first_line[:120]
                if " " in truncated:
                    truncated = truncated.rsplit(" ", 1)[0]
                first_line = truncated

            candidate = first_line

    if candidate:
        return candidate

    if raw_title and isinstance(raw_title, str) and raw_title.strip():
        # Fallback to sanitized raw title
        cleaned_raw = re.sub(r"https?://t\.co/[a-zA-Z0-9_-]+", "", raw_title).strip()
        lines = [ln.strip() for ln in cleaned_raw.splitlines() if ln.strip()]
        if lines:
            return lines[0][:120]

    return fallback


class XAdapter(PlatformAdapter):
    """
    Concrete platform adapter for X (formerly Twitter).
    Supports single video posts, multi-video posts, Custom Cookie File authentication,
    and profile scanning where supported by the underlying extractor.
    """

    # Matches X / Twitter status URL: /username/status/<id> or /i/status/<id> or /i/web/status/<id>
    # Optional trailing /video/<index> or /photo/<index>
    _STATUS_PATTERN = re.compile(
        r"https?://(?:(?:www|m(?:obile)?)\.)?(?:twitter|x)\.com/(?:(?:i/web|[^/?#]+)/status(?:es)?|i/status)/(?P<id>\d+)(?:/(?:video|photo)/(?P<index>\d+))?",
        re.IGNORECASE,
    )

    # Reserved system paths that cannot be user profiles
    _RESERVED_PATHS = {
        "i", "home", "explore", "notifications", "messages", "search", "settings",
        "login", "logout", "signup", "tos", "privacy", "about", "intent", "share",
        "hashtag", "search-advanced", "who_to_follow", "account", "download",
        "help", "privacy", "rules", "personalization", "safety", "verify"
    }

    # Matches profile URL: x.com/<username> or twitter.com/<username>
    _PROFILE_PATTERN = re.compile(
        r"https?://(?:(?:www|m(?:obile)?)\.)?(?:twitter|x)\.com/(?P<username>[a-zA-Z0-9_]{1,50})/?(?:$|[?#])",
        re.IGNORECASE,
    )

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=True,
            supports_thumbnails=True,
            supports_description=True,
            supports_metadata=True,
            supports_chapters=False,   # X does not feature chapters
            supports_playlists=True,   # Multi-video tweets
            supports_channel_scan=True,# Profile scanning where extractor permits
            supports_browser_cookies=False,
            supports_cookie_file=True, # Custom Cookie File authentication
            archive_prefix="x",
        )

    @property
    def platform_id(self) -> str:
        return "x"

    @property
    def display_name(self) -> str:
        return "X (Twitter)"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Returns True if the URL belongs to X (Twitter)."""
        if not url or not isinstance(url, str):
            return False
        clean = PlatformDetector.extract_url(url)
        if not clean:
            return False
        if not (clean.startswith("http://") or clean.startswith("https://")):
            clean = "https://" + clean
        try:
            parsed = urlparse(clean)
            netloc = (parsed.netloc or "").lower().split(":")[0]
            return any(netloc == host or netloc.endswith("." + host) for host in ("x.com", "twitter.com"))
        except Exception:
            return False

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates whether the X/Twitter URL is supported.
        Supports:
        - /<username>/status/<id>
        - /i/status/<id>
        - /i/web/status/<id>
        - /<username> (user profile)
        Returns: (is_valid: bool, error_reason: str)
        """
        if not url or not isinstance(url, str):
            return False, "URL cannot be empty."

        clean = PlatformDetector.extract_url(url)
        if not clean:
            return False, "No valid URL found in input."

        if not (clean.startswith("http://") or clean.startswith("https://")):
            clean = "https://" + clean

        if not self.matches_url(clean):
            return False, "Domain is not a valid X (Twitter) domain."

        try:
            parsed = urlparse(clean)
            path = (parsed.path or "").strip("/")
            if not path:
                return False, "Please enter a specific X (Twitter) post or profile URL."

            # Check status post path
            m_status = self._STATUS_PATTERN.search(clean)
            if m_status:
                return True, ""

            # Check profile path
            m_prof = self._PROFILE_PATTERN.search(clean)
            if m_prof:
                uname = m_prof.group("username").lower()
                if uname not in self._RESERVED_PATHS:
                    return True, ""
                return False, f"'{uname}' is a reserved X (Twitter) system path, not a user profile."

            return False, "Unrecognized X (Twitter) URL format. Supported formats include post URLs (e.g. https://x.com/username/status/...) and profiles."
        except Exception as e:
            return False, f"Malformed URL: {e}"

    def normalize_url(self, url: str) -> str:
        """
        Normalizes an X (Twitter) URL:
        - Ensures https:// protocol
        - Standardizes hostname to x.com
        - Normalizes post path to /username/status/<id> or /i/status/<id>
        - Preserves /video/<index> if present
        - Strips tracking query parameters (?s=..., ?t=..., etc.)
        """
        clean = PlatformDetector.extract_url(url)
        if not clean:
            return url.strip()

        if not (clean.startswith("http://") or clean.startswith("https://")):
            clean = "https://" + clean

        try:
            parsed = urlparse(clean)
            netloc = "x.com"

            m_status = self._STATUS_PATTERN.search(clean)
            if m_status:
                post_id = m_status.group("id")
                idx = m_status.group("index")
                # Extract username from path if not 'i' or 'i/web'
                parts = [p for p in parsed.path.strip("/").split("/") if p]
                username = "i"
                if parts and parts[0].lower() not in ("i", "i/web", "statuses"):
                    username = parts[0]

                normalized_path = f"/{username}/status/{post_id}"
                if idx:
                    normalized_path += f"/video/{idx}"
                return f"https://{netloc}{normalized_path}"

            m_prof = self._PROFILE_PATTERN.search(clean)
            if m_prof:
                uname = m_prof.group("username")
                return f"https://{netloc}/{uname}"

            return f"https://{netloc}{parsed.path}"
        except Exception:
            return clean

    def build_video_url(self, video_id: Any, original_url: str = "") -> str:
        """Constructs a canonical playback URL from a video/item ID."""
        if hasattr(video_id, "video_id"):
            orig = getattr(video_id, "url", "") or original_url
            video_id = getattr(video_id, "video_id", "")
            if not original_url:
                original_url = orig

        if original_url and "/status/" in original_url.lower():
            return self.normalize_url(original_url)

        if video_id:
            vid_str = str(video_id)
            if "_" in vid_str:
                parent_id, idx = vid_str.split("_", 1)
                return f"https://x.com/i/status/{parent_id}/video/{idx}"
            return f"https://x.com/i/status/{vid_str}"

        if original_url:
            return self.normalize_url(original_url)

        return "https://x.com/"

    def get_archive_tag(self, video: VideoItem) -> str:
        """Returns the entry format for download_archive.txt."""
        return f"x {video.video_id}"

    def build_ydl_opts(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        auth_config: Optional[PlatformAuthConfig] = None,
        extract_flat: bool = False,
        playlistend: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Builds standard yt-dlp options dictionary for X (Twitter) operations."""
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="x",
            auth_config=auth_config,
        )
        if extract_flat:
            opts["extract_flat"] = "in_playlist"
        if playlistend:
            opts["playlistend"] = playlistend
        opts["skip_download"] = True
        opts["ignoreerrors"] = True
        opts.update(kwargs)
        return opts

    def get_auth_config(self, settings: Optional[Any] = None) -> PlatformAuthConfig:
        """
        Resolves X-specific authentication configuration.
        Supports Custom Cookie File (auth_method == 'custom_file' with valid cookie_file path).
        """
        auth_method = "none"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("x_auth_method", "none") or "none"
                custom_cookie_file = settings.get("x_custom_cookie_file", "") or ""
            elif hasattr(settings, "x_auth_method"):
                auth_method = getattr(settings, "x_auth_method", "none") or "none"
                custom_cookie_file = getattr(settings, "x_custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                auth_method = settings.get("x_auth_method", "none") or "none"
                custom_cookie_file = settings.get("x_custom_cookie_file", "") or ""
        else:
            try:
                from core.settings import SettingsManager
                sm = SettingsManager()
                auth_method = sm.get("x_auth_method", "none")
                custom_cookie_file = sm.get("x_custom_cookie_file", "")
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
        Scans an X (Twitter) URL (single video post, multi-video post, or profile)
        and returns a normalized ScanResult.
        """
        from downloader.ytdlp_engine import (
            InvalidURLError,
            EmptyChannelError,
            ExtractionError,
            NetworkError,
            YtDlpEngine,
        )

        if log_callback is not None and not callable(log_callback):
            if isinstance(log_callback, DownloadSettings) or hasattr(log_callback, "x_auth_method"):
                kwargs["settings"] = log_callback
            log_callback = None

        is_valid, reason = self.validate_url(url)
        if not is_valid:
            raise InvalidURLError(reason)

        normalized_url = self.normalize_url(url)
        if log_callback:
            log_callback(f"[INFO] Connecting to X (Twitter): {normalized_url}")

        # Resolve authentication
        if auth_config is None:
            settings_dict: Dict[str, Any] = {}
            if custom_cookie_file:
                settings_dict["x_auth_method"] = "custom_file"
                settings_dict["x_custom_cookie_file"] = custom_cookie_file
            auth_config = self.get_auth_config(settings=settings_dict if settings_dict else None)

        auth_active = auth_config.is_active if auth_config else False
        detector = AvailabilityDetectorRegistry.get_detector("x")

        # Determine if this is a profile URL
        is_profile = (
            self._PROFILE_PATTERN.search(normalized_url) is not None
            and "/status/" not in normalized_url
            and "/statuses/" not in normalized_url
        )

        ydl_opts = self.build_ydl_opts(
            log_callback=log_callback,
            auth_config=auth_config,
            extract_flat=is_profile,
        )

        info: Optional[Dict[str, Any]] = None
        extraction_failed_err = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(normalized_url, download=False)
        except DownloadError as e:
            extraction_failed_err = e
        except ExtractorError as e:
            extraction_failed_err = e
        except Exception as e:
            extraction_failed_err = e

        if extraction_failed_err is not None:
            err_str = str(extraction_failed_err)
            avail = detector.detect_error(
                error_msg=err_str,
                url=normalized_url,
                auth_active=auth_active,
            )

            # Profile URL handling when extractor lacks profile scraping support
            if is_profile and any(t in err_str.lower() for t in ("unsupported url", "generic", "not found")):
                raise ExtractionError(
                    "X (Twitter) profile timeline extraction is not supported by the current yt-dlp extractor. "
                    "Please provide individual post URLs (https://x.com/username/status/...)."
                )

            # Check if post has no video (text or photo only)
            if avail.status == AvailabilityStatus.NO_SUPPORTED_FORMAT or "no video could be found" in err_str.lower() or "there's no video" in err_str.lower():
                raise ExtractionError(
                    "This X (Twitter) post contains no downloadable video media (text or image post)."
                )

            if avail.status == AvailabilityStatus.AUTH_REQUIRED:
                raise ExtractionError(
                    "X (Twitter) authentication is required to access this resource. Please configure a valid Custom Cookie File in Settings."
                )

            if avail.status == AvailabilityStatus.PRIVATE:
                raise ExtractionError(
                    "This X (Twitter) account is protected. Access requires authorized credentials via Custom Cookie File."
                )

            if avail.status == AvailabilityStatus.DELETED:
                raise EmptyChannelError(
                    "This X (Twitter) post is unavailable or has been deleted."
                )

            if any(term in err_str.lower() for term in ("network", "connection", "timed out", "timeout")):
                raise NetworkError(f"Network error while connecting to X (Twitter): {err_str}")

            raise ExtractionError(f"X (Twitter) extraction failed: {err_str}")

        if not info:
            raise EmptyChannelError(f"No metadata returned for X (Twitter) URL: {normalized_url}")

        video_items: List[VideoItem] = []
        source_title = ""
        source_type = "video"
        scan_completeness = "complete"
        partial_reason = ""

        info_type = info.get("_type")
        is_playlist = (info_type == "playlist") or ("entries" in info)

        if is_playlist:
            raw_entries = info.get("entries") or []
            parent_id = str(info.get("id") or "")
            parent_title = info.get("title") or ""
            uploader = (
                info.get("uploader")
                or info.get("channel")
                or info.get("uploader_id")
                or ""
            )

            if is_profile:
                source_type = "channel"
                source_title = uploader or parent_title or (self._PROFILE_PATTERN.search(normalized_url).group("username") if self._PROFILE_PATTERN.search(normalized_url) else "X Profile")
            else:
                source_type = "playlist"
                parent_desc = info.get("description") or ""
                source_title = clean_x_title(parent_title, caption=parent_desc, fallback=f"X Post {parent_id}")

            for idx, entry in enumerate(raw_entries, start=1):
                if is_cancelled and is_cancelled():
                    scan_completeness = "interrupted"
                    partial_reason = "Scan interrupted by user."
                    break

                if not entry or not isinstance(entry, dict):
                    continue

                # Filter out photo or text-only entries
                formats = entry.get("formats") or []
                has_video_formats = any(f.get("vcodec") != "none" for f in formats) if formats else False
                dur_val = entry.get("duration")

                # If entry has no formats and dur_val is None, skip text/photo-only
                if not formats and dur_val is None and entry.get("_type") != "url":
                    continue
                if formats and not has_video_formats and dur_val is None:
                    continue

                item_caption = entry.get("description") or info.get("description") or ""
                raw_entry_title = entry.get("title") or ""

                if is_profile:
                    item_id = str(entry.get("id") or f"{parent_id}_{idx}")
                    clean_t = clean_x_title(raw_entry_title, caption=item_caption, fallback=f"X Video {item_id}")
                    entry_url = entry.get("webpage_url") or entry.get("url") or f"https://x.com/i/status/{item_id}"
                else:
                    # Multi-video tweet item
                    item_id = f"{parent_id}_{idx}"
                    clean_base = clean_x_title(raw_entry_title, caption=item_caption, fallback=f"X Video {parent_id}")
                    clean_t = f"{clean_base} (Part {idx})"
                    # Use native yt-dlp multi-video syntax: .../video/<idx>
                    uname = info.get("uploader_id") or "i"
                    entry_url = f"https://x.com/{uname}/status/{parent_id}/video/{idx}"

                entry_uploader = entry.get("uploader") or entry.get("channel") or uploader or "X (Twitter)"
                dur_raw = entry.get("duration")
                dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
                dur_str = YtDlpEngine.format_duration(dur_secs)

                avail = detector.detect_entry(
                    entry=entry,
                    video_id=item_id,
                    title=clean_t,
                    url=entry_url,
                    auth_active=auth_active,
                )

                extra_meta = {
                    "parent_id": parent_id,
                    "parent_url": normalized_url,
                    "media_index": idx if not is_profile else None,
                    "media_count": len(raw_entries) if not is_profile else None,
                    "uploader": entry_uploader,
                    "uploader_id": entry.get("uploader_id") or info.get("uploader_id"),
                    "caption": item_caption,
                    "timestamp": entry.get("timestamp") or info.get("timestamp"),
                    "upload_date": entry.get("upload_date") or info.get("upload_date"),
                    "like_count": entry.get("like_count") or info.get("like_count"),
                    "repost_count": entry.get("repost_count") or info.get("repost_count"),
                    "comment_count": entry.get("comment_count") or info.get("comment_count"),
                    "view_count": entry.get("view_count") or info.get("view_count"),
                    "thumbnail": entry.get("thumbnail"),
                    "is_multi_media": not is_profile and len(raw_entries) > 1,
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
                    video_id=item_id,
                    title=clean_t,
                    duration=dur_str,
                    duration_seconds=dur_secs,
                    status=status,
                    subtitle_status="—",
                    url=entry_url,
                    selected=selected,
                    channel_title=entry_uploader,
                    platform="x",
                    error_reason=error_reason,
                    extra_metadata=extra_meta,
                    availability=avail,
                )
                video_items.append(item)

        else:
            # Single video post
            vid_id = str(info.get("id") or "x_video")
            raw_title = info.get("title") or ""
            raw_caption = info.get("description") or ""

            clean_t = clean_x_title(raw_title, caption=raw_caption, fallback=f"X Video {vid_id}")
            uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "X (Twitter)"
            webpage_url = info.get("webpage_url") or normalized_url

            dur_raw = info.get("duration")
            dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
            dur_str = YtDlpEngine.format_duration(dur_secs)

            source_type = "video"
            source_title = clean_t

            avail = detector.detect_entry(
                entry=info,
                video_id=vid_id,
                title=clean_t,
                url=webpage_url,
                auth_active=auth_active,
            )

            if avail.status == AvailabilityStatus.NO_SUPPORTED_FORMAT:
                raise EmptyChannelError(
                    f"This X (Twitter) post ('{vid_id}') contains no downloadable video stream."
                )

            extra_meta = {
                "uploader": uploader,
                "uploader_id": info.get("uploader_id"),
                "caption": raw_caption,
                "like_count": info.get("like_count"),
                "repost_count": info.get("repost_count"),
                "comment_count": info.get("comment_count"),
                "view_count": info.get("view_count"),
                "thumbnail": info.get("thumbnail"),
                "timestamp": info.get("timestamp"),
                "upload_date": info.get("upload_date"),
                "is_multi_media": False,
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
                title=clean_t,
                duration=dur_str,
                duration_seconds=dur_secs,
                status=status,
                subtitle_status="—",
                url=webpage_url,
                selected=selected,
                channel_title=uploader,
                platform="x",
                error_reason=error_reason,
                extra_metadata=extra_meta,
                availability=avail,
            )
            video_items.append(item)

        # Deduplicate entries by video_id while preserving order
        seen_ids = set()
        deduped: List[VideoItem] = []
        for v in video_items:
            if v.video_id not in seen_ids:
                seen_ids.add(v.video_id)
                deduped.append(v)
        video_items = deduped

        # Re-index items
        for i, v in enumerate(video_items, start=1):
            v.index = i

        # Honor max_videos limit if set
        settings = kwargs.get("settings")
        max_vids = getattr(settings, "max_videos", None) if settings else kwargs.get("max_videos")
        if max_vids and isinstance(max_vids, int) and max_vids > 0:
            if len(video_items) > max_vids:
                video_items = video_items[:max_vids]
                scan_completeness = "partial"
                partial_reason = f"Capped at max_videos limit ({max_vids})."

        if not video_items:
            raise EmptyChannelError(
                f"No downloadable videos found for X (Twitter) source '{source_title or normalized_url}'."
            )

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} X (Twitter) video(s).")
            if video_items:
                log_callback(f"[INFO] First item: '{video_items[0].title}' (ID: {video_items[0].video_id})")

        return ScanResult(
            videos=video_items,
            source_title=source_title,
            source_type=source_type,
            platform="x",
            url=url,
            extra_metadata={
                "scan_completeness": scan_completeness,
                "partial_reason": partial_reason,
            },
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
        """Scans the X (Twitter) URL and returns normalized VideoItems."""
        return self.scan(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            is_cancelled=is_cancelled,
            **kwargs,
        ).videos
