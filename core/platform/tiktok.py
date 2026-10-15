"""
tiktok.py
PlatformAdapter implementation for TikTok in Channel Harvest.
Encapsulates URL parsing, validation, and yt-dlp extraction for TikTok videos and creators.
"""

import re
from typing import List, Tuple, Optional, Callable, Dict, Any
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import UnsupportedError, DownloadError, ExtractorError

from core.models import VideoItem, DownloadSettings, VideoStatus
from core.platform.base import PlatformAdapter
from core.platform.capabilities import PlatformCapabilities
from core.platform.detector import PlatformDetector


class TikTokAdapter(PlatformAdapter):
    """
    Concrete platform adapter for TikTok.
    Supports single video URLs, mobile share URLs, and creator profiles.
    """

    # Supported TikTok URL regex patterns
    _VIDEO_URL_PATTERN = re.compile(
        r"https?://(?:www\.|m\.)?tiktok\.com/(?:@[^/]+/video/|v/|embed/|share/video/)(?P<id>\d+)",
        re.IGNORECASE,
    )
    _SHORT_URL_PATTERN = re.compile(
        r"https?://(?:(?:vm|vt)\.tiktok\.com|(?:www\.)?tiktok\.com/t)/(?P<id>[\w-]+)",
        re.IGNORECASE,
    )
    _USER_URL_PATTERN = re.compile(
        r"https?://(?:www\.)?tiktok\.com/@(?P<user>[\w.-]+)/?$",
        re.IGNORECASE,
    )

    def __init__(self):
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=False,   # Standalone SRT not provided by TikTok
            supports_thumbnails=True,  # Video cover / thumbnail supported
            supports_description=True, # Caption / description supported
            supports_metadata=True,    # Full metadata (.metadata.txt) supported
            supports_chapters=False,   # TikTok short videos do not have chapters
            supports_playlists=True,   # User feeds / collections supported
            supports_channel_scan=True,# Creator scanning supported
            supports_browser_cookies=False,
            supports_cookie_file=False,
            archive_prefix="tiktok",
        )

    @property
    def platform_id(self) -> str:
        return "tiktok"

    @property
    def display_name(self) -> str:
        return "TikTok"

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Determines whether the given URL is a TikTok URL."""
        if not url or not isinstance(url, str):
            return False
        return PlatformDetector.identify_platform_id(url) == "tiktok"

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """Validates TikTok URL format."""
        cleaned = url.strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a TikTok video or profile URL."

        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = parsed.netloc.lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.TIKTOK_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid TikTok domain."

            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific TikTok video or creator profile URL."

            return True, ""

        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def normalize_url(self, url: str) -> str:
        """Strips web tracking parameters from TikTok URLs for clean caching."""
        cleaned = url.strip()
        # Remove common query trackers
        if "?" in cleaned:
            base, _ = cleaned.split("?", 1)
            cleaned = base
        return cleaned.rstrip("/")

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """Constructs a playback URL for a TikTok video."""
        if original_url and "tiktok.com" in original_url:
            return original_url
        return f"https://www.tiktok.com/@tiktok/video/{video_id}"

    def get_archive_tag(self, video: VideoItem) -> str:
        return f"tiktok {video.video_id}"

    def get_auth_config(self, settings: Optional[Any] = None) -> "PlatformAuthConfig":
        """
        TikTok does not currently implement platform authentication.
        Always returns None to ensure YouTube credentials are never leaked or applied.
        """
        from core.platform.auth import PlatformAuthConfig
        return PlatformAuthConfig.none()

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
    ) -> List[VideoItem]:
        """
        Extracts video entries from a TikTok video or profile using yt-dlp.
        Runs with platform authentication strictly scoped to None.
        """
        is_valid, reason = self.validate_url(url)
        if not is_valid:
            from downloader.ytdlp_engine import InvalidURLError
            raise InvalidURLError(reason)

        normalized_url = self.normalize_url(url)
        if log_callback:
            log_callback(f"[INFO] Connecting to TikTok: {normalized_url}")

        from downloader.ytdlp_engine import YtDlpEngine, NetworkError, ExtractionError, EmptyChannelError
        engine = YtDlpEngine()

        ydl_opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="tiktok",
            auth_config=auth_config,
        )
        ydl_opts.update({
            "skip_download": True,
            "extract_flat": "in_playlist",
        })

        import time
        max_attempts = 3
        info = None
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if log_callback:
                        if attempt > 1:
                            log_callback(f"[INFO] Fetching metadata from TikTok (attempt {attempt}/{max_attempts})...")
                        else:
                            log_callback("[INFO] Fetching metadata from TikTok...")
                    info = ydl.extract_info(normalized_url, download=False)
                    if info:
                        break

            except UnsupportedError as e:
                from downloader.ytdlp_engine import InvalidURLError
                raise InvalidURLError(f"TikTok URL not supported: {str(e)}") from e

            except DownloadError as e:
                err_msg = str(e)
                last_exception = e

                # Fail fast immediately if impersonation is missing
                if "no impersonate target is available" in err_msg.lower() or "attempting impersonation" in err_msg.lower():
                    raise ExtractionError(
                        f"TikTok requires browser impersonation support, but the current runtime does not provide a compatible impersonation target: {err_msg}"
                    ) from e

                # Non-retryable permanent errors
                if "blocked" in err_msg.lower() or "10204" in err_msg:
                    raise ExtractionError(f"TikTok access restricted: {err_msg}") from e
                if "private" in err_msg.lower() or "not have permission" in err_msg.lower():
                    raise ExtractionError(f"TikTok post is private: {err_msg}") from e
                if "unavailable" in err_msg.lower() or "removed" in err_msg.lower():
                    raise ExtractionError(f"TikTok video unavailable: {err_msg}") from e

                # Transient HTTP 403 or network issue: bounded retry
                if attempt < max_attempts:
                    if log_callback:
                        log_callback(f"[WARNING] TikTok request attempt {attempt} returned temporary status. Retrying in {attempt}s...")
                    time.sleep(1.0 * attempt)
                    continue

                if any(term in err_msg.lower() for term in ("unable to download", "timed out", "connection")):
                    raise NetworkError(f"Network connection to TikTok failed: {err_msg}") from e
                raise ExtractionError(f"TikTok extraction failed: {err_msg}") from e

            except Exception as e:
                last_exception = e
                if attempt < max_attempts:
                    time.sleep(1.0 * attempt)
                    continue
                raise ExtractionError(f"Unexpected error during TikTok extraction: {str(e)}") from e

        if not info:
            if last_exception:
                raise ExtractionError(f"TikTok extraction failed: {str(last_exception)}") from last_exception
            raise EmptyChannelError("No information could be retrieved for this TikTok URL.")

        uploader = (
            info.get("uploader")
            or info.get("uploader_id")
            or info.get("channel")
            or "TikTok Creator"
        )
        if uploader and not uploader.startswith("@"):
            uploader_tag = f"@{uploader}"
        else:
            uploader_tag = uploader

        channel_title = uploader_tag

        raw_entries = info.get("entries")
        if raw_entries is not None:
            entries_list = [e for e in raw_entries if e]
        elif info.get("id"):
            entries_list = [info]
        else:
            entries_list = []

        if not entries_list:
            raise EmptyChannelError(f"No public videos found for TikTok creator '{channel_title}'.")

        video_items: List[VideoItem] = []
        index_counter = 1

        for entry in entries_list:
            if not entry:
                continue

            vid_id = str(entry.get("id") or "")
            raw_title = entry.get("title") or entry.get("description") or f"TikTok by {uploader_tag}"
            raw_title = raw_title.splitlines()[0] if raw_title else f"TikTok by {uploader_tag}"
            if len(raw_title) > 120:
                raw_title = raw_title[:120].strip()

            duration_raw = entry.get("duration")
            duration_str = YtDlpEngine.format_duration(duration_raw)
            duration_secs = int(duration_raw) if isinstance(duration_raw, (int, float)) else None

            webpage_url = entry.get("webpage_url") or entry.get("url") or self.build_video_url(vid_id)

            extra_meta = {
                "uploader": uploader_tag,
                "uploader_id": entry.get("uploader_id", ""),
                "view_count": entry.get("view_count"),
                "like_count": entry.get("like_count"),
                "comment_count": entry.get("comment_count"),
                "repost_count": entry.get("repost_count"),
                "track": entry.get("track"),
                "artist": entry.get("artist"),
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
                platform="tiktok",
                extra_metadata=extra_meta,
            )
            video_items.append(item)
            index_counter += 1

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} TikTok video(s).")

        return video_items
