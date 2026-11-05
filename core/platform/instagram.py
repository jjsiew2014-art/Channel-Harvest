"""
instagram.py
PlatformAdapter implementation for Instagram in Channel Harvest.
Encapsulates URL parsing, validation, normalization, platform-scoped authentication,
and yt-dlp extraction for single Reels, standard video posts, Carousels, and public profiles.
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


def clean_instagram_title(raw_title: str, caption: str = "", fallback: str = "") -> str:
    """
    Produces a clean, human-readable title for an Instagram media item.
    Prefers authentic caption text if available, stripping leading/trailing whitespace
    and bounded to a readable first line or sentence. Falls back to raw_title or fallback.
    Strips '#' and '＃' characters and truncates to 35 characters with '...' if long.
    """
    from core.platform.instagram_web import format_instagram_caption_title

    candidate_text = ""
    if caption and isinstance(caption, str) and caption.strip():
        lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]
        if lines:
            candidate_text = lines[0]

    if not candidate_text and raw_title and isinstance(raw_title, str) and raw_title.strip():
        lines = [ln.strip() for ln in raw_title.splitlines() if ln.strip()]
        if lines:
            cand = lines[0]
            if not cand.lower().startswith(("video by ", "post by ")):
                candidate_text = cand

    return format_instagram_caption_title(candidate_text, fallback=fallback, max_chars=35)


class InstagramAdapter(PlatformAdapter):
    @classmethod
    def is_profile_url(cls, url: str) -> bool:
        """Determines whether the given Instagram URL is a public user profile URL."""
        if not url or not isinstance(url, str):
            return False
        clean = (PlatformDetector.extract_url(url) or url).strip()
        m_prof = cls._PROFILE_PATTERN.search(clean)
        if m_prof:
            uname = m_prof.group("username").lower()
            return uname not in cls._RESERVED_PATHS
        return False

    """
    Concrete platform adapter for Instagram.
    Supports single Reels, standard video posts, Carousels, and public profile scanning.
    """

    # Primary Instagram URL patterns
    # Matches: /reel/<id>, /reels/<id>, /p/<id>, /tv/<id>, and with optional username prefix: /<user>/reel/<id>
    _MEDIA_PATTERN = re.compile(
        r"https?://(?:[\w-]+\.)?instagram\.com(?:/(?!share/)[^/?#]+)?/(?P<type>p|tv|reels?)/(?P<id>[a-zA-Z0-9_-]+)",
        re.IGNORECASE,
    )

    # Matches public profile URL: instagram.com/<username>/ (excluding reserved paths like p, reel, reels, tv, stories, explore, etc.)
    _RESERVED_PATHS = {
        "p", "reel", "reels", "tv", "stories", "story", "explore", "direct",
        "accounts", "emails", "developer", "about", "legal", "privacy", "terms",
        "api", "graphql", "static", "challenge", "login"
    }

    _PROFILE_PATTERN = re.compile(
        r"https?://(?:[\w-]+\.)?instagram\.com/(?P<username>[a-zA-Z0-9._]{1,30})/?(?:$|[?#])",
        re.IGNORECASE,
    )

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=False,   # Instagram media does not provide separate external SRT subtitles
            supports_thumbnails=True,  # Video / media thumbnails supported
            supports_description=True, # Post caption supported
            supports_metadata=True,    # Dedicated Instagram .metadata.txt supported
            supports_chapters=False,   # Instagram media does not feature chapters
            supports_playlists=True,   # Carousel posts and multi-item media
            supports_channel_scan=True,# Public profile scanning
            supports_browser_cookies=False,
            supports_cookie_file=True, # Custom Cookie File authentication
            supports_profile_media_archive=True,
            archive_prefix="instagram",
        )

    @property
    def platform_id(self) -> str:
        return "instagram"

    @property
    def display_name(self) -> str:
        return "Instagram"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Returns True if the URL belongs to Instagram."""
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
            return any(netloc == host or netloc.endswith("." + host) for host in ("instagram.com", "instagr.am"))
        except Exception:
            return False

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates whether the Instagram URL is supported.
        Supports:
        - /reel/<shortcode>/ or /reels/<shortcode>/
        - /p/<shortcode>/
        - /tv/<shortcode>/
        - /<username>/ (public profile)
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
            return False, "Domain is not a valid Instagram domain."

        try:
            parsed = urlparse(clean)
            path = (parsed.path or "").strip("/")
            if not path:
                return False, "Please enter a specific Instagram post, Reel, or profile URL."

            # Check media path (reel, reels, p, tv)
            m_media = self._MEDIA_PATTERN.search(clean)
            if m_media:
                return True, ""

            # Check profile path
            m_prof = self._PROFILE_PATTERN.search(clean)
            if m_prof:
                uname = m_prof.group("username").lower()
                if uname not in self._RESERVED_PATHS:
                    return True, ""
                return False, f"'{uname}' is a reserved Instagram system path, not a user profile."

            # Check stories (unsupported scope in initial release)
            if "/stories/" in clean.lower():
                return False, "Instagram Stories are not supported in this release."

            return False, "Unrecognized Instagram URL format. Supported formats include Reels, Posts, and Profiles."
        except Exception as e:
            return False, f"Malformed URL: {e}"

    def normalize_url(self, url: str) -> str:
        """
        Normalizes an Instagram URL:
        - Ensures https:// protocol
        - Standardizes hostname to www.instagram.com
        - Normalizes /reels/ to /reel/
        - Strips tracking query parameters (?igsh=..., ?utm_source=..., etc.)
        - Ensures clean trailing slash
        """
        clean = PlatformDetector.extract_url(url)
        if not clean:
            return url.strip()

        if not (clean.startswith("http://") or clean.startswith("https://")):
            clean = "https://" + clean

        try:
            parsed = urlparse(clean)
            netloc = "www.instagram.com"
            path = parsed.path.rstrip("/")

            # Normalize /reels/ -> /reel/
            path = re.sub(r"/reels/([^/]+)", r"/reel/\1", path)

            # Strip query params
            return f"https://{netloc}{path}/"
        except Exception:
            return clean

    def build_video_url(self, video_id: Any, original_url: str = "") -> str:
        """Constructs a canonical playback URL from a video/item ID."""
        if hasattr(video_id, "video_id"):
            orig = getattr(video_id, "url", "") or original_url
            video_id = getattr(video_id, "video_id", "")
            if not original_url:
                original_url = orig

        if original_url and "/reel/" in original_url.lower():
            clean_orig = self.normalize_url(original_url)
            return clean_orig

        if video_id:
            # If video_id contains an underscore (e.g. parent_subid from carousel), use parent_id if separable
            raw_id = str(video_id).split("_")[0] if "_" in str(video_id) else str(video_id)
            return f"https://www.instagram.com/p/{raw_id}/"

        if original_url:
            return self.normalize_url(original_url)

        return "https://www.instagram.com/"

    def get_archive_tag(self, video: VideoItem) -> str:
        """Returns the entry format for download_archive.txt."""
        return f"instagram {video.video_id}"

    def build_ydl_opts(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        auth_config: Optional[PlatformAuthConfig] = None,
        extract_flat: bool = False,
        playlistend: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Builds standard yt-dlp options dictionary for Instagram operations."""
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="instagram",
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
        Resolves Instagram-specific authentication configuration.
        Strictly isolated from YouTube, TikTok, Facebook, and Bilibili authentication settings.
        Supports:
        1. None (auth_method == 'none')
        2. Custom Cookie File (auth_method == 'custom_file' with valid cookie_file path)
        """
        from pathlib import Path
        auth_method = "none"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("instagram_auth_method", "none") or "none"
                custom_cookie_file = settings.get("instagram_custom_cookie_file", "") or ""
            elif hasattr(settings, "instagram_auth_method"):
                auth_method = getattr(settings, "instagram_auth_method", "none") or "none"
                custom_cookie_file = getattr(settings, "instagram_custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                auth_method = settings.get("instagram_auth_method", "none") or "none"
                custom_cookie_file = settings.get("instagram_custom_cookie_file", "") or ""
        else:
            try:
                from core.settings import SettingsManager
                sm = SettingsManager()
                auth_method = sm.get("instagram_auth_method", "none")
                custom_cookie_file = sm.get("instagram_custom_cookie_file", "")
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

        # Fallback to 'all' if Instagram has no authentication configured
        from core.platform.auth import resolve_effective_cookie_file
        eff_method, eff_file, desc_suffix = resolve_effective_cookie_file(
            "instagram", auth_method, custom_cookie_file, settings=settings
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
        Scans an Instagram URL (Reel, Post, Carousel, or Profile) and returns a normalized ScanResult.
        Distinguishes single items from multi-entry carousels and public profiles,
        filters non-video items safely, applies availability detection, and tracks scan completeness.
        """
        from downloader.ytdlp_engine import (
            InvalidURLError,
            EmptyChannelError,
            ExtractionError,
            NetworkError,
            YtDlpEngine,
        )

        if log_callback is not None and not callable(log_callback):
            if isinstance(log_callback, DownloadSettings) or hasattr(log_callback, "instagram_auth_method"):
                kwargs["settings"] = log_callback
            log_callback = None

        is_valid, reason = self.validate_url(url)
        if not is_valid:
            raise InvalidURLError(reason)

        normalized_url = self.normalize_url(url)
        if log_callback:
            log_callback(f"[INFO] Connecting to Instagram: {normalized_url}")

        # Resolve authentication
        if auth_config is None:
            settings_dict: Dict[str, Any] = {}
            if custom_cookie_file:
                settings_dict["instagram_auth_method"] = "custom_file"
                settings_dict["instagram_custom_cookie_file"] = custom_cookie_file
            auth_config = self.get_auth_config(settings=settings_dict if settings_dict else None)

        auth_active = auth_config.is_active if auth_config else False
        detector = AvailabilityDetectorRegistry.get_detector("instagram")

        ydl_opts = self.build_ydl_opts(
            log_callback=log_callback,
            auth_config=auth_config,
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

            # If it's a photo-only post
            if avail.status == AvailabilityStatus.NO_SUPPORTED_FORMAT or "no video in this post" in err_str.lower():
                raise ExtractionError(
                    "This Instagram post contains only photos and no downloadable video media."
                )

            if avail.status == AvailabilityStatus.AUTH_REQUIRED:
                raise ExtractionError(
                    "Instagram authentication is required to access this resource. Please configure a valid Custom Cookie File in Settings."
                )

            if avail.status == AvailabilityStatus.PRIVATE:
                raise ExtractionError(
                    "This Instagram account or post is private. Access requires authorized credentials via Custom Cookie File."
                )

            if avail.status == AvailabilityStatus.DELETED:
                raise EmptyChannelError(
                    "This Instagram content is unavailable or has been removed."
                )

            if any(term in err_str.lower() for term in ("network", "connection", "timed out", "timeout")):
                raise NetworkError(f"Network error while connecting to Instagram: {err_str}")

            raise ExtractionError(f"Instagram extraction failed: {err_str}")

        if not info:
            raise EmptyChannelError(f"No metadata returned for Instagram URL: {normalized_url}")

        video_items: List[VideoItem] = []
        source_title = ""
        source_type = "video"
        scan_completeness = "complete"
        partial_reason = ""

        # Determine if result is a playlist (Profile or Carousel) or single post
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

            # Check if this is a profile or a carousel
            is_profile = self._PROFILE_PATTERN.search(normalized_url) is not None and "/p/" not in normalized_url and "/reel/" not in normalized_url
            if is_profile:
                source_type = "channel"
                source_title = uploader or parent_title or self._PROFILE_PATTERN.search(normalized_url).group("username")
            else:
                source_type = "carousel"
                parent_desc = info.get("description") or ""
                source_title = clean_instagram_title(parent_title, caption=parent_desc, fallback=f"Instagram Carousel {parent_id}")

            for idx, entry in enumerate(raw_entries, start=1):
                if is_cancelled and is_cancelled():
                    scan_completeness = "interrupted"
                    partial_reason = "Scan interrupted by user."
                    break

                if not entry or not isinstance(entry, dict):
                    continue

                # Filter out photo-only entries in carousels/playlists
                formats = entry.get("formats") or []
                has_video_formats = any(f.get("vcodec") != "none" for f in formats) if formats else False
                
                # If entry has no formats and is explicitly photo, skip it honestly
                if not formats or (not has_video_formats and formats and all(f.get("vcodec") == "none" for f in formats)):
                    # Check if entry duration or video_versions indicate video
                    dur_val = entry.get("duration")
                    if dur_val is None and not formats:
                        # Photo-only carousel item: do not emit as fake video
                        continue

                item_caption = entry.get("description") or info.get("description") or ""
                raw_entry_title = entry.get("title") or ""

                if is_profile:
                    item_id = str(entry.get("id") or f"{parent_id}_{idx}")
                    clean_t = clean_instagram_title(raw_entry_title, caption=item_caption, fallback=f"Instagram Video {item_id}")
                else:
                    # Carousel item
                    item_id = f"{parent_id}_{idx}"
                    clean_base = clean_instagram_title(raw_entry_title, caption=item_caption, fallback=f"Carousel Item {idx}")
                    clean_t = f"{clean_base} (Part {idx})"

                entry_uploader = entry.get("uploader") or entry.get("channel") or uploader or "Instagram"
                if is_profile:
                    entry_url = entry.get("webpage_url") or entry.get("url") or (f"https://www.instagram.com/p/{item_id}/" if item_id else normalized_url)
                else:
                    entry_url = entry.get("webpage_url") or normalized_url

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
                    "carousel_index": idx if not is_profile else None,
                    "uploader": entry_uploader,
                    "uploader_id": entry.get("uploader_id") or info.get("uploader_id"),
                    "caption": item_caption,
                    "timestamp": entry.get("timestamp") or info.get("timestamp"),
                    "upload_date": entry.get("upload_date") or info.get("upload_date"),
                    "like_count": entry.get("like_count"),
                    "comment_count": entry.get("comment_count"),
                    "thumbnail": entry.get("thumbnail"),
                    "is_carousel": not is_profile,
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
                    platform="instagram",
                    error_reason=error_reason,
                    extra_metadata=extra_meta,
                    availability=avail,
                )
                video_items.append(item)

        else:
            # Single video / Reel post
            vid_id = str(info.get("id") or "instagram_video")
            raw_title = info.get("title") or ""
            raw_caption = info.get("description") or ""

            clean_t = clean_instagram_title(raw_title, caption=raw_caption, fallback=f"Instagram Video {vid_id}")
            uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Instagram"
            webpage_url = info.get("webpage_url") or normalized_url

            dur_raw = info.get("duration")
            dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
            dur_str = YtDlpEngine.format_duration(dur_secs)

            is_reel = (
                "/reel/" in normalized_url.lower()
                or str(info.get("extractor_key", "")).lower() == "instagramreel"
            )
            source_type = "reel" if is_reel else "video"
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
                    f"This Instagram post ('{vid_id}') contains only photos and no downloadable video stream."
                )

            extra_meta = {
                "uploader": uploader,
                "uploader_id": info.get("uploader_id"),
                "caption": raw_caption,
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
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
                title=clean_t,
                duration=dur_str,
                duration_seconds=dur_secs,
                status=status,
                subtitle_status="—",
                url=webpage_url,
                selected=selected,
                channel_title=uploader,
                platform="instagram",
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
            video_items = video_items[:max_vids]

        if not video_items:
            raise EmptyChannelError(
                f"No downloadable videos or Reels found for Instagram source '{source_title or normalized_url}'."
            )

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} Instagram video(s).")
            if video_items:
                log_callback(f"[INFO] First item: '{video_items[0].title}' (ID: {video_items[0].video_id})")

        return ScanResult(
            videos=video_items,
            source_title=source_title,
            source_type=source_type,
            platform="instagram",
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
        """Scans the Instagram URL and returns normalized VideoItems."""
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
        Scans an Instagram profile media archive using ProfileScanManager.
        Discovers photos, carousels, and videos with persistent inventory.
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
