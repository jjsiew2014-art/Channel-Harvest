"""
bilibili.py
PlatformAdapter implementation for Bilibili (哔哩哔哩, 中国大陆版) in Channel Harvest.
Encapsulates URL parsing, short link (b23.tv) redirect resolution, validation,
platform-scoped authentication, multi-part video (分 P) expansion, UP space scanning,
and yt-dlp extraction for Bilibili videos.
"""

import json
import re
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



_PATCHED_BILIBILI_EXTRACTORS = False


def _patch_bilibili_extractors() -> None:
    """
    Enhances yt-dlp's Bilibili extractors so that space video lists, collections,
    and playlists preserve the real video title, duration, uploader, thumbnail,
    and description already returned by Bilibili's API in extract_flat mode.
    
    Upstream yt-dlp BilibiliSpaceVideoIE and BilibiliSpaceListBaseIE omit video_title
    in their url_result calls, causing entries to lack titles when using extract_flat.
    This enhancement preserves all entry metadata without requiring any extra network requests.
    """
    global _PATCHED_BILIBILI_EXTRACTORS
    if _PATCHED_BILIBILI_EXTRACTORS:
        return

    try:
        from yt_dlp.extractor.bilibili import (
            BilibiliSpaceVideoIE,
            BilibiliSpaceListBaseIE,
            BiliBiliIE,
            BilibiliCollectionListIE,
        )
        from yt_dlp.utils import traverse_obj, parse_duration, variadic, url_or_none, ExtractorError
        from yt_dlp.networking.exceptions import HTTPError
        from urllib.parse import parse_qs
        import math

        # 1. Patch BilibiliSpaceVideoIE._real_extract
        orig_space_video_real_extract = getattr(
            BilibiliSpaceVideoIE, "_orig_real_extract", BilibiliSpaceVideoIE._real_extract
        )
        BilibiliSpaceVideoIE._orig_real_extract = orig_space_video_real_extract

        def patched_space_video_real_extract(self, url):
            playlist_id, is_video_url = self._match_valid_url(url).group("id", "video")
            if not is_video_url:
                self.to_screen("A channel URL was given. Only the channel's videos will be downloaded. "
                               "To download audios, add a \"/upload/audio\" to the URL")

            def fetch_page(page_idx):
                query = {
                    "keyword": "",
                    "mid": playlist_id,
                    "order": traverse_obj(parse_qs(url), ("order", 0)) or "pubdate",
                    "order_avoided": "true",
                    "platform": "web",
                    "pn": page_idx + 1,
                    "ps": 30,
                    "tid": 0,
                    "web_location": "333.1387",
                    "special_type": "",
                    "index": 0,
                    **self._dm_params,
                }
                try:
                    response = self._download_json(
                        "https://api.bilibili.com/x/space/wbi/arc/search",
                        playlist_id,
                        query=self._sign_wbi(query, playlist_id),
                        note=f"Downloading space page {page_idx}",
                        headers={
                            "Referer": url,
                            "Origin": "https://space.bilibili.com",
                            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
                        },
                    )
                except ExtractorError as e:
                    if isinstance(e.cause, HTTPError) and e.cause.status == 412:
                        raise ExtractorError(
                            "Request is blocked by server (412), please wait and try later.", expected=True
                        )
                    raise
                status_code = response["code"]
                if status_code == -401:
                    raise ExtractorError(
                        "Request is blocked by server (401), please wait and try later.", expected=True
                    )
                elif status_code == -352:
                    raise ExtractorError("Request is rejected by server (352)", expected=True)
                elif status_code != 0:
                    raise ExtractorError(f"Request failed ({status_code}): {response.get('message') or 'Unknown error'}")
                return response["data"]

            def get_metadata(page_data):
                page_size = page_data["page"]["ps"]
                entry_count = page_data["page"]["count"]
                return {
                    "page_count": math.ceil(entry_count / page_size),
                    "page_size": page_size,
                }

            def get_entries(page_data):
                for entry in traverse_obj(page_data, ("list", "vlist", ..., {dict})):
                    if traverse_obj(entry, ("meta", "attribute")) == 156:
                        # hidden-mode collection doesn't show its videos in uploads; extract as playlist instead
                        yield self.url_result(
                            f"https://space.bilibili.com/{entry['mid']}/lists/{entry['meta']['id']}?type=season",
                            BilibiliCollectionListIE,
                            f"{entry['mid']}_{entry['meta']['id']}",
                        )
                    else:
                        bvid = entry.get("bvid")
                        title = entry.get("title")
                        dur_raw = entry.get("length")
                        dur_secs = parse_duration(dur_raw) if isinstance(dur_raw, str) else entry.get("duration")
                        yield self.url_result(
                            f"https://www.bilibili.com/video/{bvid}",
                            BiliBiliIE,
                            bvid,
                            title,
                            duration=dur_secs,
                            uploader=entry.get("author"),
                            thumbnail=entry.get("pic"),
                            description=entry.get("description"),
                        )

            _, paged_list = self._extract_playlist(fetch_page, get_metadata, get_entries)
            return self.playlist_result(paged_list, playlist_id)

        BilibiliSpaceVideoIE._real_extract = patched_space_video_real_extract

        # 2. Patch BilibiliSpaceListBaseIE._get_entries (Collections, Series, Playlists, Favlists)
        orig_space_list_get_entries = getattr(
            BilibiliSpaceListBaseIE, "_orig_get_entries", BilibiliSpaceListBaseIE._get_entries
        )
        BilibiliSpaceListBaseIE._orig_get_entries = orig_space_list_get_entries

        def patched_space_list_get_entries(self, page_data, bvid_keys, ending_key="bvid"):
            raw_items = list(traverse_obj(page_data, (*variadic(bvid_keys, (str, bytes, dict, set)), ...)))
            for item in raw_items:
                if isinstance(item, dict):
                    bvid = traverse_obj(item, ending_key, "bvid", "bv_id", ("meta", "bvid"), {str})
                    if not bvid:
                        continue
                    title = traverse_obj(item, "title", ("meta", "title"), "name", {str})
                    dur_raw = traverse_obj(
                        item, "duration", "length", {lambda v: v if isinstance(v, (int, float, str)) else None}
                    )
                    dur_secs = (
                        parse_duration(dur_raw)
                        if isinstance(dur_raw, str)
                        else (int(dur_raw) if isinstance(dur_raw, (int, float)) else None)
                    )
                    uploader = traverse_obj(item, ("author", "name"), ("upper", "name"), "author", "uploader", {str})
                    thumbnail = traverse_obj(item, "pic", "cover", ("meta", "cover"), {url_or_none})
                    description = traverse_obj(item, "description", "intro", ("meta", "description"), {str})
                    yield self.url_result(
                        f"https://www.bilibili.com/video/{bvid}",
                        BiliBiliIE,
                        bvid,
                        title,
                        duration=dur_secs,
                        uploader=uploader,
                        thumbnail=thumbnail,
                        description=description,
                    )
                elif isinstance(item, str):
                    yield self.url_result(f"https://www.bilibili.com/video/{item}", BiliBiliIE, item)

        BilibiliSpaceListBaseIE._get_entries = patched_space_list_get_entries
        _PATCHED_BILIBILI_EXTRACTORS = True
    except Exception as e:
        import logging
        logging.getLogger("ChannelHarvest.Bilibili").warning(f"Could not patch Bilibili yt-dlp extractors: {e}")


# Initialize yt-dlp extractor enhancement
_patch_bilibili_extractors()


class BilibiliAdapter(PlatformAdapter):
    """
    Concrete platform adapter for Bilibili (哔哩哔哩).
    Integrates Bilibili as a first-class platform in Channel Harvest using the
    official yt-dlp Bilibili extractor and pagelist API.
    """

    # URL pattern recognition
    _BV_PATTERN = re.compile(r"https?://(?:www\.|m\.)?bilibili\.com/video/(?P<id>[bB][vV][\w]+)", re.IGNORECASE)
    _AV_PATTERN = re.compile(r"https?://(?:www\.|m\.)?bilibili\.com/video/[aA][vV](?P<id>\d+)", re.IGNORECASE)
    _SPACE_PATTERN = re.compile(r"https?://space\.bilibili\.com/(?P<id>\d+)", re.IGNORECASE)
    _SERIES_PATTERN = re.compile(r"https?://space\.bilibili\.com/\d+/(?:channel/seriesdetail|lists/\d+)", re.IGNORECASE)
    _COLLECTION_PATTERN = re.compile(r"https?://space\.bilibili\.com/\d+/(?:channel/collectiondetail|lists/\d+)", re.IGNORECASE)
    _FAVLIST_PATTERN = re.compile(r"https?://(?:space\.bilibili\.com/\d+/favlist|(?:www\.)?bilibili\.com/(?:medialist|list)/)", re.IGNORECASE)
    _B23_PATTERN = re.compile(r"https?://b23\.tv/(?P<id>[\w]+)", re.IGNORECASE)

    @staticmethod
    def _resolve_entry_title(entry: Any, fallback_id: str = "", index: int = 1) -> str:
        """
        Resolves the actual video title following the strict priority order:
        1. Valid, non-empty extracted video title ('title', 'part', 'part_title', 'video_title')
        2. Another reliable title field present in the entry ('name', 'fulltitle', 'alt_title', 'headline')
        3. A clearly identifiable fallback: 'Bilibili Video {video_id}' (or 'Bilibili Video #{index}')

        Guarantees:
        - Never returns None, empty string, raw dict, or internal metadata object.
        - Unescapes HTML entities.
        - Strips whitespace.
        - Fallback never overwrites an existing valid title.
        """
        if isinstance(entry, str) and entry.strip():
            raw_title = entry.strip()
        elif isinstance(entry, dict):
            # Priority 1: primary title fields
            primary_candidates = [
                entry.get("title"),
                entry.get("video_title"),
                entry.get("part"),
                entry.get("part_title"),
            ]
            raw_title = next((t for t in primary_candidates if isinstance(t, str) and t.strip()), None)

            # Priority 2: secondary reliable title fields
            if not raw_title:
                secondary_candidates = [
                    entry.get("name"),
                    entry.get("fulltitle"),
                    entry.get("alt_title"),
                    entry.get("headline"),
                    entry.get("subject"),
                ]
                raw_title = next((t for t in secondary_candidates if isinstance(t, str) and t.strip()), None)
        else:
            raw_title = None

        if raw_title:
            import html
            import re
            # Strip keyword highlight tags from search results, then unescape HTML entities
            cleaned = re.sub(r"</?em(?:\s+[^>]*)?>", "", raw_title).strip()
            cleaned = html.unescape(cleaned).strip()
            if cleaned:
                if len(cleaned) > 200:
                    cleaned = cleaned[:200].strip()
                return cleaned

        # Priority 3: Clearly identifiable fallback
        clean_id = (fallback_id or "").strip()
        if clean_id:
            return f"Bilibili Video {clean_id}"
        return f"Bilibili Video #{index}"

    def __init__(self):
        _patch_bilibili_extractors()
        self._capabilities = PlatformCapabilities(
            supports_video=True,
            supports_audio=True,
            supports_subtitles=True,       # CC and uploaded subtitle tracks
            supports_thumbnails=True,      # Video cover / pic
            supports_description=True,     # Video description
            supports_metadata=True,        # Metadata (.metadata.txt)
            supports_chapters=True,        # Chapters when provided by yt-dlp
            supports_playlists=True,       # Collections, series, favlists, anthologies
            supports_channel_scan=True,    # UP space / creator submissions
            supports_browser_cookies=False,# Browser cookies not required for initial release
            supports_cookie_file=True,     # Custom Netscape cookie file (SESSDATA)
            archive_prefix="bilibili",
        )

    @property
    def platform_id(self) -> str:
        return "bilibili"

    @property
    def display_name(self) -> str:
        return "Bilibili"

    @property
    def is_available(self) -> bool:
        from core.platform.detector import PlatformRegistry
        override = PlatformRegistry.get_availability_override(self.platform_id)
        if override is not None:
            return override
        return True

    @property
    def unavailable_reason(self) -> Optional[str]:
        return None

    @property
    def capabilities(self) -> PlatformCapabilities:
        return self._capabilities

    def matches_url(self, url: str) -> bool:
        """Determines whether the given URL belongs to Bilibili."""
        if not url or not isinstance(url, str):
            return False
        return PlatformDetector.identify_platform_id(url) == "bilibili"

    def resolve_short_url(self, url: str, timeout: float = 5.0) -> str:
        """
        Follows HTTP redirects for Bilibili short share links (b23.tv)
        to discover the canonical web URL.
        """
        if "b23.tv" not in url:
            return url
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
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

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates Bilibili URL format.
        Accepts video URLs (BV/AV), multi-part pages (?p=2), space profiles,
        playlists/collections, or mobile share snippets containing Bilibili URLs.
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()
        if not cleaned:
            return False, "URL cannot be empty. Please enter a Bilibili video or space URL."

        try:
            parsed = urlparse(cleaned)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                return False, "URL must begin with http:// or https://"

            netloc = (parsed.netloc or "").lower().split(":")[0]
            if not any(netloc == host or netloc.endswith("." + host) for host in PlatformDetector.BILIBILI_DOMAINS):
                return False, f"Domain '{parsed.netloc}' is not a valid Bilibili domain."

            if not parsed.path or parsed.path == "/":
                return False, "Please provide a specific Bilibili video (BV/AV), UP space, or collection URL."

            is_matched = (
                bool(self._BV_PATTERN.search(cleaned))
                or bool(self._AV_PATTERN.search(cleaned))
                or bool(self._SPACE_PATTERN.search(cleaned))
                or bool(self._SERIES_PATTERN.search(cleaned))
                or bool(self._COLLECTION_PATTERN.search(cleaned))
                or bool(self._FAVLIST_PATTERN.search(cleaned))
                or bool(self._B23_PATTERN.search(cleaned))
            )
            if not is_matched:
                return False, "Please provide a valid Bilibili video (BV/AV), UP space, or playlist URL."

            return True, ""

        except Exception as e:
            return False, f"Malformed URL: {str(e)}"

    def normalize_url(self, url: str) -> str:
        """
        Normalizes Bilibili URL for scanning:
        1. Extracts URL from mobile app share text if present.
        2. Resolves b23.tv short redirects.
        3. Strips tracking query parameters (spm_id_from, from_source, vd_source, etc.)
           while strictly preserving functional parameters:
           - 'p' (page index for multi-part videos, e.g. ?p=2)
           - 'sid' (series/collection identifier)
           - 'fid' (favorites list identifier)
           - 'bvid' (bvid parameter if present in query)
        """
        extracted = PlatformDetector.extract_url(url)
        cleaned = (extracted or url).strip()

        # Follow redirects for short share links (b23.tv)
        if "b23.tv" in cleaned.lower():
            cleaned = self.resolve_short_url(cleaned)

        try:
            parsed = urlparse(cleaned)
            query_params = parse_qs(parsed.query, keep_blank_values=False)

            # Preserve only essential functional query parameters
            kept_params = {}
            for key in ("p", "sid", "fid", "bvid"):
                if key in query_params and query_params[key]:
                    kept_params[key] = query_params[key]

            new_query = urlencode(kept_params, doseq=True) if kept_params else ""
            normalized = urlunparse((
                parsed.scheme,
                parsed.netloc.lower(),
                parsed.path.rstrip("/") if parsed.path != "/" else "/",
                parsed.params,
                new_query,
                "",  # strip fragment
            ))
            return normalized
        except Exception:
            return cleaned.rstrip("/")

    def build_video_url(self, video_id: str, original_url: str = "") -> str:
        """
        Constructs a canonical playback URL from a video identifier.
        Handles both single video IDs (BV...) and multi-part video IDs (BV..._p2).
        """
        if original_url and "bilibili.com" in original_url:
            return original_url

        if "_p" in video_id:
            parts = video_id.split("_p", 1)
            bvid = parts[0]
            try:
                p_num = int(parts[1])
                return f"https://www.bilibili.com/video/{bvid}?p={p_num}"
            except ValueError:
                return f"https://www.bilibili.com/video/{bvid}"

        return f"https://www.bilibili.com/video/{video_id}"

    def clean_url(self, url: str) -> str:
        """Alias for normalize_url with tracking parameter removal."""
        return self.normalize_url(url)

    def generate_archive_tag(self, video_id: str) -> str:
        """Returns archive file tag for video ID."""
        return f"{self._capabilities.archive_prefix} {video_id}"

    def get_archive_tag(self, video: Any) -> str:
        """Returns the entry format for download_archive.txt (e.g. 'bilibili {video_id}')."""
        vid_id = video.video_id if hasattr(video, "video_id") else str(video)
        return self.generate_archive_tag(vid_id)

    def get_source_title(self, url: str, auth_config: Optional[Any] = None) -> str:
        """Retrieves human-readable source title (UP creator, collection, or video title)."""
        scan_res = self.scan(url, auth_config=auth_config)
        return scan_res.source_title

    def build_ydl_options(
        self,
        auth_config: Optional[PlatformAuthConfig] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Builds yt-dlp option dictionary for Bilibili requests."""
        from downloader.ytdlp_engine import YtDlpEngine
        engine = YtDlpEngine()
        opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="bilibili",
            auth_config=auth_config,
        )
        opts.update(kwargs)
        return opts

    def get_auth_config(self, settings: Optional[Any] = None) -> PlatformAuthConfig:
        """
        Resolves Bilibili-specific authentication configuration.
        Strictly isolated from YouTube and TikTok authentication settings.
        Supports:
        1. None (auth_method == 'none')
        2. Custom Cookie File (auth_method == 'custom_file' with valid cookie_file path)
        """
        auth_method = "none"
        custom_cookie_file = ""

        if settings is not None:
            if hasattr(settings, "get") and callable(settings.get):
                auth_method = settings.get("bilibili_auth_method", "none") or "none"
                custom_cookie_file = settings.get("bilibili_custom_cookie_file", "") or ""
            elif hasattr(settings, "bilibili_auth_method"):
                auth_method = getattr(settings, "bilibili_auth_method", "none") or "none"
                custom_cookie_file = getattr(settings, "bilibili_custom_cookie_file", "") or ""
            elif isinstance(settings, dict):
                auth_method = settings.get("bilibili_auth_method", "none") or "none"
                custom_cookie_file = settings.get("bilibili_custom_cookie_file", "") or ""
        else:
            try:
                from core.settings import SettingsManager
                sm = SettingsManager()
                auth_method = sm.get("bilibili_auth_method", "none")
                custom_cookie_file = sm.get("bilibili_custom_cookie_file", "")
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

        # Fallback to 'all' if Bilibili has no authentication configured
        from core.platform.auth import resolve_effective_cookie_file
        eff_method, eff_file, desc_suffix = resolve_effective_cookie_file(
            "bilibili", auth_method, custom_cookie_file, settings=settings
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

    def extract_entries(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[VideoItem]:
        """Extracts video entries from a Bilibili URL."""
        return self.scan(
            url=url,
            log_callback=log_callback,
            browser_cookies=browser_cookies,
            custom_cookie_file=custom_cookie_file,
            auth_config=auth_config,
            is_cancelled=is_cancelled,
            progress_callback=progress_callback,
        ).videos

    def _fetch_pagelist(self, bvid: str, timeout: float = 6.0) -> List[Dict[str, Any]]:
        """
        Directly queries Bilibili's official public pagelist endpoint:
        https://api.bilibili.com/x/player/pagelist?bvid={bvid}
        Returns list of page info dicts with 'page', 'part', 'duration', 'cid'.
        """
        try:
            req_url = f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}"
            req = urllib.request.Request(
                req_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": f"https://www.bilibili.com/video/{bvid}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
                if payload.get("code") == 0 and isinstance(payload.get("data"), list):
                    return payload["data"]
        except Exception:
            pass
        return []

    def scan(
        self,
        url: str,
        log_callback: Optional[Callable[[str], None]] = None,
        browser_cookies: Optional[str] = None,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ScanResult:
        """
        Scans a Bilibili video, multi-part video (分 P), UP space, or playlist/collection
        and returns a normalized ScanResult.
        """
        is_valid, reason = self.validate_url(url)
        if not is_valid:
            from downloader.ytdlp_engine import InvalidURLError
            raise InvalidURLError(reason)

        normalized_url = self.normalize_url(url)
        if log_callback:
            log_callback(f"[INFO] Connecting to Bilibili: {normalized_url}")

        from downloader.ytdlp_engine import YtDlpEngine, NetworkError, ExtractionError, EmptyChannelError
        engine = YtDlpEngine()

        # Resolve authentication
        if auth_config is None or not auth_config.is_active:
            if auth_config is None:
                auth_config = self.get_auth_config()
            if not auth_config.is_active and custom_cookie_file:
                cpath = Path(custom_cookie_file)
                if cpath.is_file():
                    auth_config = PlatformAuthConfig(
                        auth_method="custom_file",
                        cookie_file=str(cpath.resolve()),
                        description="Custom Cookie File",
                    )

        ydl_opts = engine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="bilibili",
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
                            log_callback(f"[INFO] Fetching metadata from Bilibili (attempt {attempt}/{max_attempts})...")
                        else:
                            log_callback("[INFO] Fetching metadata from Bilibili...")
                    info = ydl.extract_info(normalized_url, download=False)
                    if info:
                        break

            except UnsupportedError as e:
                from downloader.ytdlp_engine import InvalidURLError
                raise InvalidURLError(f"Bilibili URL not supported: {str(e)}") from e

            except DownloadError as e:
                err_msg = str(e)
                last_exception = e

                # Bilibili Risk Control Challenge (Error 352)
                if "352" in err_msg or "rejected by server (352)" in err_msg.lower() or "code: -352" in err_msg.lower():
                    raise ExtractionError(
                        "Bilibili server rejected the request (Risk Control Challenge / Error 352). "
                        "Bilibili requires an active authenticated session (Cookie file with SESSDATA) "
                        "or a cooldown period to query creator submission lists."
                    ) from e

                # HTTP 412 server rejection / rate limit
                if "412" in err_msg or "blocked by server (412)" in err_msg.lower():
                    raise ExtractionError(
                        "Bilibili rejected the request (HTTP 412 Precondition Failed / WAF Block). "
                        "Bilibili's anti-scraping system requires account authentication (Cookie file) "
                        "or a cooldown period to access this space / submission list."
                    ) from e

                # Deleted, private, or inaccessible video
                if "KeyError('bvid')" in err_msg or "keyerror: 'bvid'" in err_msg.lower() or "deleted or geo-restricted" in err_msg.lower():
                    raise ExtractionError("This Bilibili video is unavailable, deleted, or region-restricted.") from e

                if "private" in err_msg.lower() or "not have permission" in err_msg.lower():
                    raise ExtractionError("This Bilibili content is private or requires permission to access.") from e

                # Transient network error: bounded retry
                if attempt < max_attempts and any(term in err_msg.lower() for term in ("timed out", "timeout", "connection reset", "connection refused", "network is unreachable")):
                    if log_callback:
                        log_callback(f"[WARNING] Bilibili request attempt {attempt} encountered network timeout. Retrying in {attempt}s...")
                    time.sleep(1.0 * attempt)
                    continue

                if any(term in err_msg.lower() for term in ("unable to download", "timed out", "connection")):
                    raise NetworkError(f"Network connection to Bilibili failed: {err_msg}") from e

                raise ExtractionError(f"Bilibili extraction failed: {err_msg}") from e

            except Exception as e:
                last_exception = e
                err_str = str(e)
                if "352" in err_str or "rejected by server (352)" in err_str.lower():
                    raise ExtractionError(
                        "Bilibili server rejected the request (Risk Control Challenge / Error 352). "
                        "Please configure a valid Bilibili cookie file with active session (SESSDATA) in Settings."
                    ) from e
                if "412" in err_str:
                    raise ExtractionError(
                        "Bilibili rejected the request (HTTP 412 Precondition Failed). "
                        "Please configure a valid Bilibili cookie file in Settings or wait before retrying."
                    ) from e
                if attempt < max_attempts:
                    time.sleep(1.0 * attempt)
                    continue
                raise ExtractionError(f"Unexpected error during Bilibili extraction: {err_str}") from e

        if not info:
            if last_exception:
                raise ExtractionError(f"Bilibili extraction failed: {str(last_exception)}") from last_exception
            raise EmptyChannelError("No information could be retrieved for this Bilibili URL.")

        # Determine source title & source type
        uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
        uploader_id = info.get("uploader_id") or ""
        raw_main_title = self._resolve_entry_title(info, fallback_id=str(info.get("id") or ""), index=1)
        main_title = raw_main_title if raw_main_title and not raw_main_title.startswith("Bilibili Video ") else (info.get("title") or "Bilibili")

        # Determine if this was an anthology / multi-part video or a collection / space
        raw_entries = info.get("entries")
        video_items: List[VideoItem] = []
        detector = AvailabilityDetectorRegistry.get_detector("bilibili")
        auth_active = bool(auth_config and auth_config.is_active)

        def _make_item(idx, vid_id, item_title, dur_str, dur_secs, item_url, chan_title, extra_meta, entry_dict):
            avail = detector.detect_entry(
                entry=entry_dict,
                video_id=vid_id,
                title=item_title,
                url=item_url,
                auth_active=auth_active,
            )
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

            return VideoItem(
                index=idx,
                video_id=vid_id,
                title=item_title,
                duration=dur_str,
                duration_seconds=dur_secs,
                status=status,
                subtitle_status="Checking...",
                url=item_url,
                selected=selected,
                channel_title=chan_title,
                platform="bilibili",
                error_reason=error_reason,
                extra_metadata=extra_meta,
                availability=avail,
            )

        # Check if URL requested a specific page parameter, e.g. ?p=2
        parsed_orig = urlparse(normalized_url)
        query_dict = parse_qs(parsed_orig.query)
        requested_p = None
        if "p" in query_dict and query_dict["p"]:
            try:
                requested_p = int(query_dict["p"][0])
            except ValueError:
                pass

        # Case 1: Multi-part video or single BV/AV video
        # A Bilibili video can either have entries (anthology) or be a single video entry
        is_video_url = "/video/" in normalized_url
        bvid_match = self._BV_PATTERN.search(normalized_url) or self._AV_PATTERN.search(normalized_url)

        if is_video_url and bvid_match:
            bvid = info.get("id") or bvid_match.group("id")
            source_title = main_title
            source_type = "video"

            # Check if this video has multiple parts (分 P)
            pages = self._fetch_pagelist(bvid)
            if not pages and raw_entries and isinstance(raw_entries, list) and len(raw_entries) > 1:
                pages = []
                for p_idx, p_entry in enumerate(raw_entries, start=1):
                    pages.append({
                        "page": p_entry.get("page") or p_idx,
                        "part": p_entry.get("part") or p_entry.get("title") or "",
                        "duration": p_entry.get("duration"),
                        "cid": p_entry.get("cid"),
                    })

            if len(pages) > 1 and requested_p is None:
                # Multi-part video: expand all parts into VideoItems
                for idx, page_info in enumerate(pages, start=1):
                    if is_cancelled and is_cancelled():
                        break
                    if progress_callback:
                        progress_callback(idx, len(pages))
                    p_num = page_info.get("page", idx)
                    p_part = self._resolve_entry_title(page_info, fallback_id="", index=idx)
                    p_dur_raw = page_info.get("duration")
                    p_dur_secs = int(p_dur_raw) if isinstance(p_dur_raw, (int, float)) else None
                    p_dur_str = YtDlpEngine.format_duration(p_dur_secs)

                    # Formulate distinct part title following yt-dlp standard
                    if p_part and p_part != main_title and not p_part.startswith("Bilibili Video "):
                        item_title = f"{main_title} p{p_num:02d} {p_part}"
                    else:
                        item_title = f"{main_title} p{p_num:02d}"

                    item_id = f"{bvid}_p{p_num}"
                    part_url = f"https://www.bilibili.com/video/{bvid}?p={p_num}"

                    extra_meta = {
                        "uploader": uploader,
                        "uploader_id": uploader_id,
                        "bvid": bvid,
                        "part_number": p_num,
                        "part_title": p_part if not p_part.startswith("Bilibili Video ") else "",
                        "cid": page_info.get("cid"),
                        "total_parts": len(pages),
                    }

                    item = _make_item(
                        idx=idx,
                        vid_id=item_id,
                        item_title=item_title,
                        dur_str=p_dur_str,
                        dur_secs=p_dur_secs,
                        item_url=part_url,
                        chan_title=uploader or main_title,
                        extra_meta=extra_meta,
                        entry_dict=page_info,
                    )
                    video_items.append(item)

            elif len(pages) > 1 and requested_p is not None:
                # Single part selected via ?p=N parameter
                target_page = next((p for p in pages if p.get("page") == requested_p), None)
                p_part = self._resolve_entry_title(target_page, fallback_id="", index=requested_p) if target_page else ""
                p_dur_raw = target_page.get("duration") if target_page else info.get("duration")
                p_dur_secs = int(p_dur_raw) if isinstance(p_dur_raw, (int, float)) else None
                p_dur_str = YtDlpEngine.format_duration(p_dur_secs)

                if p_part and p_part != main_title and not p_part.startswith("Bilibili Video "):
                    item_title = f"{main_title} p{requested_p:02d} {p_part}"
                else:
                    item_title = f"{main_title} p{requested_p:02d}"

                item_id = f"{bvid}_p{requested_p}"
                extra_meta = {
                    "uploader": uploader,
                    "uploader_id": uploader_id,
                    "bvid": bvid,
                    "part_number": requested_p,
                    "part_title": p_part if not p_part.startswith("Bilibili Video ") else "",
                    "cid": target_page.get("cid") if target_page else None,
                }
                item = _make_item(
                    idx=1,
                    vid_id=item_id,
                    item_title=item_title,
                    dur_str=p_dur_str,
                    dur_secs=p_dur_secs,
                    item_url=normalized_url,
                    chan_title=uploader or main_title,
                    extra_meta=extra_meta,
                    entry_dict=target_page or info,
                )
                video_items.append(item)

            else:
                # Standard single video (1 part)
                single_title = self._resolve_entry_title(info, fallback_id=bvid, index=1)
                dur_raw = info.get("duration")
                dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
                dur_str = YtDlpEngine.format_duration(dur_secs)
                webpage_url = info.get("webpage_url") or normalized_url

                extra_meta = {
                    "uploader": uploader,
                    "uploader_id": uploader_id,
                    "view_count": info.get("view_count"),
                    "like_count": info.get("like_count"),
                    "comment_count": info.get("comment_count"),
                    "danmaku_count": info.get("danmaku_count"),
                }

                item = _make_item(
                    idx=1,
                    vid_id=bvid,
                    item_title=single_title,
                    dur_str=dur_str,
                    dur_secs=dur_secs,
                    item_url=webpage_url,
                    chan_title=uploader or main_title,
                    extra_meta=extra_meta,
                    entry_dict=info,
                )
                video_items.append(item)

        # Case 2: Space / Playlist / Collection (list of video entries)
        elif raw_entries is not None:
            entries_list = [e for e in raw_entries if e]
            if not entries_list:
                raise EmptyChannelError(f"No public videos found for Bilibili source '{main_title}'.")

            # Determine source title for space / collection
            if "space.bilibili.com" in normalized_url:
                first_up = None
                for e in entries_list:
                    up = e.get("uploader") or (e.get("author") if isinstance(e.get("author"), str) else None)
                    if up and up.strip() and up != "Bilibili":
                        first_up = up.strip()
                        break
                source_title = first_up or uploader or (main_title if main_title != "Bilibili" else f"UP: {uploader_id}")
                source_type = "creator"
            else:
                source_title = main_title if main_title != "Bilibili" else "Bilibili Collection"
                source_type = "playlist"

            seen_ids = set()
            idx_counter = 1

            for entry in entries_list:
                if is_cancelled and is_cancelled():
                    break
                if progress_callback:
                    progress_callback(idx_counter, len(entries_list))
                if not entry:
                    continue

                vid_id = str(entry.get("id") or entry.get("bvid") or entry.get("bv_id") or "").strip()
                # Guard against duplicate pagination entries
                if vid_id and vid_id in seen_ids:
                    continue
                if vid_id:
                    seen_ids.add(vid_id)

                entry_title = self._resolve_entry_title(entry, fallback_id=vid_id, index=idx_counter)

                dur_raw = entry.get("duration")
                if isinstance(dur_raw, (int, float)):
                    dur_secs = int(dur_raw)
                elif isinstance(dur_raw, str):
                    from yt_dlp.utils import parse_duration
                    dur_secs = parse_duration(dur_raw)
                else:
                    dur_secs = None
                dur_str = YtDlpEngine.format_duration(dur_secs)

                entry_url = entry.get("url") or entry.get("webpage_url") or self.build_video_url(vid_id)
                entry_uploader = (
                    entry.get("uploader")
                    or (entry.get("author") if isinstance(entry.get("author"), str) else None)
                    or uploader
                    or source_title
                )

                extra_meta = {
                    "uploader": entry_uploader,
                    "uploader_id": entry.get("uploader_id") or uploader_id,
                    "view_count": entry.get("view_count"),
                    "like_count": entry.get("like_count"),
                }

                item = _make_item(
                    idx=idx_counter,
                    vid_id=vid_id,
                    item_title=entry_title,
                    dur_str=dur_str,
                    dur_secs=dur_secs,
                    item_url=entry_url,
                    chan_title=entry_uploader,
                    extra_meta=extra_meta,
                    entry_dict=entry,
                )
                video_items.append(item)
                idx_counter += 1

        else:
            # Fallback for unexpected single entry structure
            single_title = self._resolve_entry_title(info, fallback_id=str(info.get("id") or "bilibili_video"), index=1)
            source_title = single_title
            source_type = "video"
            vid_id = str(info.get("id") or "bilibili_video")
            dur_raw = info.get("duration")
            dur_secs = int(dur_raw) if isinstance(dur_raw, (int, float)) else None
            dur_str = YtDlpEngine.format_duration(dur_secs)

            item = _make_item(
                idx=1,
                vid_id=vid_id,
                item_title=single_title,
                dur_str=dur_str,
                dur_secs=dur_secs,
                item_url=normalized_url,
                chan_title=uploader or source_title,
                extra_meta={},
                entry_dict=info,
            )
            video_items.append(item)

        if not video_items:
            raise EmptyChannelError(f"No downloadable videos found for Bilibili source '{source_title}'.")

        if log_callback:
            log_callback(f"[SUCCESS] Successfully retrieved {len(video_items)} Bilibili video(s).")
            if video_items:
                log_callback(f"[INFO] Bilibili sample: '{video_items[0].title}' (ID: {video_items[0].video_id})")

        return ScanResult(
            videos=video_items,
            source_title=source_title,
            source_type=source_type,
            platform="bilibili",
            url=url,
        )
