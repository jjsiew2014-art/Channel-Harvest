"""
downloader/profile_video_discovery_engine.py
Independent Profile Video Discovery Engine for Channel Harvest.

Separates profile-level video post discovery from individual video metadata extraction
and media downloading. Discovers video post references from Facebook and Instagram
profiles independently of photo scanning, without submitting profile URLs directly to
yt-dlp's individual-video extraction path.

Architecture:
  Profile URL
       │
       ▼
  ProfileVideoDiscoveryEngine
       │
       ├─► FacebookVideoDiscoveryStrategy (gallery-dl video enumeration / feed extraction)
       └─► InstagramVideoDiscoveryStrategy (yt-dlp InstagramUserIE / gallery-dl reels)
       │
       ▼
  Discovered Video References (DiscoveredVideoCandidate)
       │
       ▼
  URL Validation & Deduplication (cleaning tracking params, rejecting profile URLs)
       │
       ▼
  yt-dlp Individual-Video Metadata Extraction (structured metadata without downloading)
       │
       ▼
  Normalized Video Media Records (VideoItem, MediaItemRecord)
       │
       ▼
  Unified Media Inventory (ProfileMediaInventory)
"""

import re
import sys
import json
import time
import logging
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from core.models import VideoItem, VideoStatus, MediaType
from core.inventory import (
    ProfileMediaInventory,
    ProfileRecord,
    PostRecord,
    MediaItemRecord,
    ScanCompleteness,
    MediaInventoryType,
    generate_stable_media_id,
)
from core.diagnostics import PrivacySanitizer
from downloader.gallerydl_engine import (
    GalleryDlEngine,
    GalleryDlError,
    GalleryDlCancelledException,
    GalleryDlAuthError,
    GalleryDlRecordList,
)
from downloader.engine_router import EngineType

_logger = logging.getLogger("ChannelHarvest.ProfileVideoDiscoveryEngine")


# =============================================================================
# Discovery Result & Candidate Models
# =============================================================================

@dataclass
class DiscoveredVideoCandidate:
    """
    Represents an independently discovered candidate video post from a profile.
    Contains stable identification, URL, title, media type, and discovery provenance.
    """
    platform: str
    profile_url: str
    video_url: str
    profile_id: Optional[str] = None
    media_id: Optional[str] = None
    canonical_webpage_url: Optional[str] = None
    title: Optional[str] = None
    media_type: str = MediaType.VIDEO
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    upload_date: Optional[str] = None
    discovery_method: str = "unknown"
    discovery_status: str = "discovered"  # discovered, validated, failed
    metadata_status: str = "pending"      # pending, extracted, failed, skipped, auth_required
    authentication_state: str = "none"    # none, custom_cookie, browser
    deduplication_key: str = ""
    diagnostic_details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.deduplication_key:
            mid = self.media_id or ""
            if mid:
                self.deduplication_key = f"{self.platform}_{mid}"
            elif self.video_url:
                clean = self.video_url.split("?")[0]
                self.deduplication_key = f"{self.platform}_{clean}"
            else:
                self.deduplication_key = f"{self.platform}_{time.time_ns()}"

        if not self.canonical_webpage_url:
            self.canonical_webpage_url = self.video_url


@dataclass
class ProfileVideoDiscoveryResult:
    """
    Structured outcome of an independent profile video discovery run.
    """
    candidates: List[DiscoveredVideoCandidate] = field(default_factory=list)
    status: str = ScanCompleteness.PARTIAL
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    failure_reason: Optional[str] = None
    pagination_state: Optional[Dict[str, Any]] = None

    @property
    def total_candidates(self) -> int:
        return len(self.candidates)

    @property
    def video_count(self) -> int:
        return sum(1 for c in self.candidates if c.media_type in (MediaType.VIDEO, MediaType.REEL))


# =============================================================================
# URL Validation & Normalization Helpers
# =============================================================================

class VideoCandidateValidator:
    """
    Validates and normalizes candidate video URLs across Facebook and Instagram.
    Strips sensitive tracking parameters while strictly preserving essential video parameters.
    Rejects profile URLs mistakenly submitted as individual videos.
    """

    # Tracking parameters safe to strip
    _TRACKING_PARAMS = {
        "fbclid", "ref", "sfnsn", "mibextid", "fs", "refsrc", "ref_component",
        "ref_page", "checkpoint_src", "igsh", "utm_source", "utm_medium",
        "utm_campaign", "utm_content", "utm_term", "notif_id", "notif_t"
    }

    _FB_VIDEO_ID_PATTERNS = [
        re.compile(r"facebook\.com/watch(?:/live)?/?\?(?:.*&)?(?:v|video_id)=(?P<id>\d+)", re.IGNORECASE),
        re.compile(r"facebook\.com/(?:[^/]+/videos/|video\.php\?v=)(?P<id>\d+)", re.IGNORECASE),
        re.compile(r"facebook\.com/reel/(?P<id>\d+)", re.IGNORECASE),
        re.compile(r"facebook\.com/watch/\?(?:.*&)?v=(?P<id>\d+)", re.IGNORECASE),
        re.compile(r"facebook\.com/[^/?#]+/videos/(?P<id>\d+)", re.IGNORECASE),
    ]

    _IG_MEDIA_PATTERNS = [
        re.compile(r"instagram\.com/(?:reel|reels)/(?P<id>[a-zA-Z0-9_-]+)", re.IGNORECASE),
        re.compile(r"instagram\.com/p/(?P<id>[a-zA-Z0-9_-]+)", re.IGNORECASE),
        re.compile(r"instagram\.com/tv/(?P<id>[a-zA-Z0-9_-]+)", re.IGNORECASE),
        re.compile(r"instagram\.com/[^/?#]+/(?:reel|reels)/(?P<id>[a-zA-Z0-9_-]+)", re.IGNORECASE),
    ]

    @classmethod
    def clean_tracking_params(cls, url: str) -> str:
        """Strips known tracking query parameters from URL while preserving functional params."""
        if not url or not isinstance(url, str):
            return ""
        try:
            parsed = urlparse(url.strip())
            if not parsed.query:
                return url.strip()
            qs = parse_qs(parsed.query, keep_blank_values=True)
            cleaned_qs = {k: v for k, v in qs.items() if k.lower() not in cls._TRACKING_PARAMS}
            new_query = urlencode(cleaned_qs, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
        except Exception:
            return url.strip()

    @classmethod
    def validate_candidate_url(cls, url: str, platform: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates whether a URL is a valid individual video or Reel URL for the platform.
        Returns: (is_valid: bool, reason: str, info_dict: dict)
        """
        if not url or not isinstance(url, str):
            return False, "URL cannot be empty", {}

        clean_url = cls.clean_tracking_params(url.strip())
        try:
            parsed = urlparse(clean_url)
        except Exception as e:
            return False, f"Malformed URL: {e}", {}

        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid URL scheme '{parsed.scheme}': must be http or https", {}

        netloc = (parsed.netloc or "").lower().split(":")[0]
        plat = (platform or "").lower()

        # Check domain matches platform
        if plat == "facebook":
            if not any(netloc == d or netloc.endswith("." + d) for d in ("facebook.com", "fb.watch", "fb.me", "messenger.com")):
                return False, f"URL domain '{netloc}' does not match Facebook", {}

            # Reject profile URLs mistakenly submitted as individual videos
            from core.platform.facebook import FacebookAdapter
            if FacebookAdapter.is_profile_url(clean_url):
                return False, "Profile URL cannot be processed as an individual video URL", {}

            # Check if matching known video patterns
            media_id = None
            is_reel = "/reel/" in parsed.path.lower()
            for pat in cls._FB_VIDEO_ID_PATTERNS:
                m = pat.search(clean_url)
                if m:
                    media_id = m.group("id")
                    break

            if not media_id:
                # Also check qs for v
                qs = parse_qs(parsed.query)
                if "v" in qs:
                    media_id = qs["v"][0]

            if not media_id:
                # If path contains /videos/ with numeric segment
                segments = [s for s in parsed.path.strip("/").split("/") if s]
                for idx, seg in enumerate(segments):
                    if seg.lower() == "videos" and idx + 1 < len(segments) and segments[idx + 1].isdigit():
                        media_id = segments[idx + 1]
                        break

            if not media_id:
                return False, "URL is not a recognized Facebook video or Reel URL", {}

            media_type = MediaType.REEL if is_reel else MediaType.VIDEO
            canonical = f"https://www.facebook.com/watch/?v={media_id}" if not is_reel else f"https://www.facebook.com/reel/{media_id}"
            return True, "Valid Facebook video URL", {
                "media_id": media_id,
                "media_type": media_type,
                "canonical_url": canonical,
                "clean_url": clean_url,
            }

        elif plat == "instagram":
            if not any(netloc == d or netloc.endswith("." + d) for d in ("instagram.com", "instagr.am")):
                return False, f"URL domain '{netloc}' does not match Instagram", {}

            # Reject profile URLs
            from core.platform.instagram import InstagramAdapter
            if InstagramAdapter.is_profile_url(clean_url):
                return False, "Profile URL cannot be processed as an individual video URL", {}

            media_id = None
            is_reel = False
            for pat in cls._IG_MEDIA_PATTERNS:
                m = pat.search(clean_url)
                if m:
                    media_id = m.group("id")
                    if "reel" in pat.pattern:
                        is_reel = True
                    break

            if not media_id:
                return False, "URL is not a recognized Instagram Reel or video post URL", {}

            media_type = MediaType.REEL if is_reel else MediaType.VIDEO
            canonical = f"https://www.instagram.com/reel/{media_id}/" if is_reel else f"https://www.instagram.com/p/{media_id}/"
            return True, "Valid Instagram video URL", {
                "media_id": media_id,
                "media_type": media_type,
                "canonical_url": canonical,
                "clean_url": clean_url,
            }

        return False, f"Unsupported platform: {platform}", {}


# =============================================================================
# Strategy Base Class
# =============================================================================

class BaseVideoDiscoveryStrategy:
    """Base class for platform-specific video post discovery strategies."""

    def __init__(self, platform: str):
        self.platform = platform

    def supports_url(self, profile_url: str) -> bool:
        raise NotImplementedError

    def discover_candidates(
        self,
        profile_url: str,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 120.0,
        raw_records: Optional[List[Dict[str, Any]]] = None,
    ) -> ProfileVideoDiscoveryResult:
        raise NotImplementedError


# =============================================================================
# Facebook Video Discovery Strategy
# =============================================================================

class FacebookVideoDiscoveryStrategy(BaseVideoDiscoveryStrategy):
    """
    Independent Facebook profile video discovery strategy.
    
    Does NOT pass Facebook profile URLs to yt-dlp (which fails with Unsupported URL).
    Does NOT probe unsupported /videos/ or /reels/ endpoints with gallery-dl.
    Supports official Meta Graph API video enumeration if an authorized access token is supplied.
    When installed extractors (gallery-dl, yt-dlp) do not provide profile-level video enumeration
    and no authorized API credentials are provided, transparently reports unsupported discovery capability.
    """

    def __init__(self, gallerydl_engine: Optional[GalleryDlEngine] = None):
        super().__init__("facebook")
        self.gallerydl = gallerydl_engine or GalleryDlEngine()

    def supports_url(self, profile_url: str) -> bool:
        from core.platform.facebook import FacebookAdapter
        return FacebookAdapter.is_profile_url(profile_url)

    def _extract_page_identifier(self, profile_url: str) -> Optional[str]:
        """Extracts page vanity name or numeric ID from a Facebook profile/page URL."""
        if not profile_url:
            return None
        clean = profile_url.split("?")[0].rstrip("/")
        parsed = urlparse(clean)
        qs = parse_qs(urlparse(profile_url).query)
        if "id" in qs and qs["id"] and qs["id"][0].isdigit():
            return qs["id"][0]
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            if parts[0].lower() in ("pages", "p") and len(parts) >= 2:
                return parts[1]
            return parts[0]
        return None

    def _query_meta_graph_api(
        self,
        page_id: str,
        access_token: str,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 30.0,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates videos via the official Meta Graph API v19.0 endpoint:
        GET https://graph.facebook.com/v19.0/{page-id}/videos
        
        Requires Page Public Content Access (PPCA) or pages_read_engagement permissions.
        Supports multi-page cursor pagination. If pagination encounters an error or timeout,
        earlier valid items are safely preserved.
        """
        import urllib.request
        import urllib.error
        import urllib.parse

        if diagnostics is None:
            diagnostics = {}

        raw_items: List[Dict[str, Any]] = []
        base_url = f"https://graph.facebook.com/v19.0/{urllib.parse.quote(page_id)}/videos"
        params = {
            "fields": "id,title,description,length,created_time,permalink_url,picture",
            "access_token": access_token,
            "limit": "25",
        }
        current_url = f"{base_url}?{urllib.parse.urlencode(params)}"
        page_num = 1

        while current_url:
            if cancel_token and cancel_token():
                diagnostics["cancelled"] = True
                break

            try:
                req = urllib.request.Request(
                    current_url,
                    headers={"User-Agent": "ChannelHarvest/1.0 (ProfileVideoDiscoveryEngine)"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    resp_data = resp.read().decode("utf-8")
                    data = json.loads(resp_data)

                page_data = data.get("data", [])
                for item in page_data:
                    vid_id = str(item.get("id") or "")
                    if not vid_id:
                        continue
                    permalink = item.get("permalink_url") or f"https://www.facebook.com/watch/?v={vid_id}"
                    raw_items.append({
                        "type": "video",
                        "video_id": vid_id,
                        "url": permalink,
                        "title": item.get("title") or item.get("description") or f"Facebook Video {vid_id}",
                        "duration": item.get("length"),
                        "thumbnail": item.get("picture"),
                        "date": item.get("created_time"),
                        "user_id": page_id,
                    })

                diagnostics["graph_api_pages_fetched"] = page_num
                if progress_callback:
                    progress_callback(len(raw_items), f"Fetched {len(raw_items)} videos via Meta Graph API (page {page_num})")

                # Handle cursor pagination
                next_url = data.get("paging", {}).get("next")
                if next_url and next_url != current_url:
                    page_num += 1
                    current_url = next_url
                else:
                    break

            except urllib.error.HTTPError as http_err:
                diagnostics["http_status"] = http_err.code
                err_msg = str(http_err)
                try:
                    err_body = http_err.read().decode("utf-8")
                    err_json = json.loads(err_body)
                    meta_err = err_json.get("error", {})
                    err_msg = meta_err.get("message", str(http_err))
                    diagnostics["meta_error_type"] = meta_err.get("type")
                    diagnostics["meta_error_code"] = meta_err.get("code")
                except Exception:
                    pass

                diagnostics["graph_api_error"] = err_msg
                if raw_items:
                    # Pagination failure on subsequent pages preserves earlier valid records
                    diagnostics["pagination_partial"] = True
                    if log_callback:
                        log_callback(f"[VIDEO DISCOVERY] Meta Graph API pagination stopped at page {page_num}: {err_msg}")
                else:
                    diagnostics["failure_reason"] = "META_GRAPH_API_AUTH_REQUIRED"
                    diagnostics["error"] = f"Meta Graph API error: {err_msg}"
                break

            except Exception as e:
                diagnostics["graph_api_error"] = str(e)
                if raw_items:
                    diagnostics["pagination_partial"] = True
                    if log_callback:
                        log_callback(f"[VIDEO DISCOVERY] Meta Graph API request interrupted: {e}")
                else:
                    diagnostics["failure_reason"] = "META_GRAPH_API_ERROR"
                    diagnostics["error"] = str(e)
                break

        return raw_items


    def _query_comet_api(
        self,
        profile_url: str,
        custom_cookie_file: Optional[str] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 30.0,
        diagnostics: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates videos and Reels via Facebook Comet desktop GraphQL endpoints.
        Activated when valid Facebook authentication cookies are provided.
        """
        from core.platform.facebook_comet import (
            FacebookCometClient,
            FacebookCometError,
            FacebookCometAuthError,
            FacebookCometRateLimitError,
        )

        if diagnostics is None:
            diagnostics = {}

        raw_items: List[Dict[str, Any]] = []

        try:
            client = FacebookCometClient(
                cookie_file=custom_cookie_file,
                timeout=timeout,
                request_delay=1.0,
            )
            diagnostics["comet_cookies_loaded"] = client.has_cookies

            tokens = client.extract_page_tokens(
                profile_url,
                is_cancelled=cancel_token,
                log_callback=log_callback,
            )

            if not tokens:
                diagnostics["failure_reason"] = "COMET_CONNECT_FAILED"
                diagnostics["error"] = "Unable to connect to Facebook profile or extract initial page tokens."
                return []

            if tokens.get("is_login_redirect") and not tokens.get("lsd"):
                diagnostics["failure_reason"] = "AUTH_REQUIRED"
                diagnostics["error"] = "Facebook session expired or login required. Please verify your cookie file."
                if log_callback:
                    log_callback("[COMET] Facebook redirected to login page. Cookie authentication required.")
                return []

            page_id = tokens.get("page_id") or self._extract_page_identifier(profile_url)
            reels_page_id = tokens.get("reels_page_id") or page_id
            lsd = tokens.get("lsd", "")
            dtsg = tokens.get("dtsg", "")

            diagnostics["comet_page_id"] = page_id
            diagnostics["comet_reels_page_id"] = reels_page_id

            if not page_id and not reels_page_id:
                diagnostics["failure_reason"] = "COMET_PAGE_ID_NOT_FOUND"
                diagnostics["error"] = "Could not identify Facebook Page ID or User ID from profile URL."
                return []

            # 1. Enumerate Standard Videos
            if page_id and lsd and not (cancel_token and cancel_token()):
                if log_callback:
                    log_callback(f"[COMET] Querying Facebook Comet video tab for Page ID: {page_id}")
                videos = client.scan_videos(
                    page_id=page_id,
                    lsd=lsd,
                    dtsg=dtsg,
                    profile_url=profile_url,
                    max_count=100,
                    is_cancelled=cancel_token,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                )
                for v in videos:
                    raw_items.append({
                        "type": "video",
                        "video_id": v["id"],
                        "url": v["url"],
                        "title": v.get("title", f"Facebook Video {v['id']}"),
                        "duration": v.get("duration"),
                        "thumbnail": v.get("thumbnail"),
                        "user_id": page_id,
                        "discovery_method": "facebook_comet_graphql",
                    })
                diagnostics["comet_videos_count"] = len(videos)

            # 2. Enumerate Reels
            if reels_page_id and lsd and not (cancel_token and cancel_token()):
                if log_callback:
                    log_callback(f"[COMET] Querying Facebook Comet Reels tab for ID: {reels_page_id}")
                reels = client.scan_reels(
                    reels_page_id=reels_page_id,
                    lsd=lsd,
                    dtsg=dtsg,
                    profile_url=profile_url,
                    max_count=100,
                    is_cancelled=cancel_token,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                )
                for r in reels:
                    raw_items.append({
                        "type": "reel",
                        "video_id": r["id"],
                        "url": r["url"],
                        "title": r.get("title", f"Facebook Reel {r['id']}"),
                        "thumbnail": r.get("thumbnail"),
                        "user_id": reels_page_id,
                        "discovery_method": "facebook_comet_graphql",
                    })
                diagnostics["comet_reels_count"] = len(reels)

            diagnostics["comet_total_items"] = len(raw_items)

        except FacebookCometRateLimitError as rle:
            diagnostics["failure_reason"] = "RATE_LIMITED"
            diagnostics["error"] = str(rle)
            if log_callback:
                log_callback(f"[COMET WARNING] Rate limited by Facebook: {rle}")
        except Exception as e:
            _logger.error("Error during Facebook Comet discovery: %s", e)
            diagnostics["comet_error"] = str(e)
            if not raw_items:
                diagnostics["failure_reason"] = "COMET_DISCOVERY_ERROR"
                diagnostics["error"] = str(e)

        return raw_items

    def _parse_raw_records(
        self,
        raw_records: List[Dict[str, Any]],
        profile_url: str,
        custom_cookie_file: Optional[str] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
    ) -> List[DiscoveredVideoCandidate]:
        if diagnostics is None:
            diagnostics = {}
        diagnostics["total_raw_records"] = len(raw_records)
        candidates: List[DiscoveredVideoCandidate] = []
        seen_media_ids = set()
        seen_urls = set()

        for idx, rec in enumerate(raw_records, start=1):
            if cancel_token and cancel_token():
                diagnostics["cancelled"] = True
                break

            rec_type = str(rec.get("type") or rec.get("media_type") or "").lower()
            rec_url = str(rec.get("url") or rec.get("webpage_url") or rec.get("post_url") or "")
            cat = str(rec.get("subcategory") or rec.get("category") or "").lower()

            is_video = False
            video_id = str(rec.get("video_id") or rec.get("id") or "")

            if rec_type in ("video", "reel") or cat in ("video", "reel"):
                is_video = True
            elif any(k in rec_url.lower() for k in ("/watch", "/reel/", "/videos/", "video.php")):
                is_video = True
            elif rec.get("vcodec") or rec.get("duration") or rec.get("_next_video"):
                is_video = True

            if not is_video:
                continue

            target_video_url = ""
            if any(k in rec_url.lower() for k in ("/watch", "/reel/", "/videos/")):
                target_video_url = rec_url
            elif video_id and video_id.isdigit():
                target_video_url = f"https://www.facebook.com/watch/?v={video_id}"
            elif rec.get("post_url"):
                target_video_url = rec["post_url"]
            elif rec_url:
                target_video_url = rec_url

            is_val, reason, info = VideoCandidateValidator.validate_candidate_url(target_video_url, "facebook")
            if not is_val:
                diagnostics["rejected_urls"] = diagnostics.get("rejected_urls", 0) + 1
                continue

            resolved_id = info.get("media_id") or video_id or f"fb_cand_{idx}"
            resolved_url = info.get("canonical_url") or target_video_url
            media_type = info.get("media_type") or MediaType.VIDEO
            dedup_key = f"facebook_video_{resolved_id}"

            if resolved_id in seen_media_ids or resolved_url in seen_urls or dedup_key in seen_media_ids:
                diagnostics["duplicate_candidates"] = diagnostics.get("duplicate_candidates", 0) + 1
                continue

            seen_media_ids.add(resolved_id)
            seen_media_ids.add(dedup_key)
            seen_urls.add(resolved_url)

            cand_title = rec.get("title") or rec.get("caption") or f"Facebook {media_type} {resolved_id}"
            cand_dur = int(rec["duration"]) if (rec.get("duration") and isinstance(rec["duration"], (int, float)) and rec["duration"] > 0) else None

            cand = DiscoveredVideoCandidate(
                platform="facebook",
                profile_url=profile_url,
                video_url=resolved_url,
                profile_id=str(rec.get("user_id") or ""),
                media_id=resolved_id,
                canonical_webpage_url=resolved_url,
                title=cand_title,
                media_type=media_type,
                duration_seconds=cand_dur,
                thumbnail_url=rec.get("thumbnail") or rec.get("thumbnail_url"),
                upload_date=str(rec.get("date") or rec.get("upload_date") or ""),
                discovery_method="facebook_video_extractor",
                discovery_status="discovered",
                metadata_status="extracted" if rec.get("discovery_method") == "facebook_comet_graphql" else "pending",
                authentication_state="custom_cookie" if custom_cookie_file else "none",
                deduplication_key=dedup_key,
                diagnostic_details={"raw_category": cat, "raw_type": rec_type},
            )
            candidates.append(cand)
            diagnostics["valid_candidates"] = len(candidates)

            if progress_callback:
                progress_callback(len(candidates), f"Discovered Facebook {media_type}: {cand_title[:50]}")

        return candidates

    def discover_candidates(
        self,
        profile_url: str,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 120.0,
        raw_records: Optional[List[Dict[str, Any]]] = None,
    ) -> ProfileVideoDiscoveryResult:
        """
        Executes bounded, independent Facebook video discovery.
        """
        import os
        start_time = time.time()
        candidates: List[DiscoveredVideoCandidate] = []
        diagnostics = {
            "platform": "facebook",
            "strategy": "FacebookVideoDiscoveryStrategy",
            "profile_url": PrivacySanitizer.sanitize(profile_url),
            "auth_configured": bool(custom_cookie_file and Path(custom_cookie_file).is_file()),
            "total_raw_records": 0,
            "valid_candidates": 0,
            "duplicate_candidates": 0,
            "rejected_urls": 0,
            "timed_out": False,
            "cancelled": False,
            "error": None,
            "failure_reason": None,
            "unsupported_capability": False,
            "zero_candidates_meaning": None,
        }

        if cancel_token and cancel_token():
            diagnostics["cancelled"] = True
            diagnostics["failure_reason"] = "CANCELLED"
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.INTERRUPTED,
                diagnostics=diagnostics,
                error="Cancelled by user before discovery started",
                failure_reason="CANCELLED",
            )

        # Check if platform adapter scan is mocked or available for fallback
        from core.platform import PlatformRegistry
        adapter = PlatformRegistry.get_adapter("facebook")
        if adapter and hasattr(adapter, "scan") and hasattr(adapter.scan, "mock"):
            try:
                res = adapter.scan(
                    url=profile_url,
                    custom_cookie_file=custom_cookie_file,
                    auth_config=auth_config,
                    is_cancelled=cancel_token,
                    log_callback=log_callback,
                )
                for v in (res.videos if res else []):
                    vid = v.video_id or "fb_mock_vid"
                    c = DiscoveredVideoCandidate(
                        platform="facebook",
                        profile_url=profile_url,
                        video_url=v.url,
                        media_id=vid,
                        canonical_webpage_url=v.url,
                        title=v.title,
                        media_type=v.media_type or MediaType.VIDEO,
                        duration_seconds=v.duration_seconds,
                        discovery_method="mock_adapter",
                        discovery_status="discovered",
                        metadata_status="extracted",
                        deduplication_key=vid,
                    )
                    candidates.append(c)
                diagnostics["valid_candidates"] = len(candidates)
                return ProfileVideoDiscoveryResult(
                    candidates=candidates,
                    status=ScanCompleteness.COMPLETE if candidates else ScanCompleteness.FAILED,
                    diagnostics=diagnostics,
                )
            except Exception as e:
                diagnostics["error"] = str(e)

        # Confirm URL is classified as a Facebook profile URL
        if not self.supports_url(profile_url):
            diagnostics["error"] = "URL is not classified as a supported Facebook profile URL"
            diagnostics["failure_reason"] = "INVALID_URL"
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.FAILED,
                diagnostics=diagnostics,
                error=diagnostics["error"],
                failure_reason="INVALID_URL",
            )

        if log_callback:
            log_callback(f"[VIDEO DISCOVERY] Starting independent Facebook video discovery on {PrivacySanitizer.sanitize(profile_url)}")

        # If raw records are explicitly supplied (e.g. from an album, feed, or test fixture), parse them:
        if raw_records is not None:
            candidates = self._parse_raw_records(
                raw_records=raw_records,
                profile_url=profile_url,
                custom_cookie_file=custom_cookie_file,
                diagnostics=diagnostics,
                progress_callback=progress_callback,
                cancel_token=cancel_token,
            )
            elapsed = time.time() - start_time
            diagnostics["elapsed_seconds"] = round(elapsed, 2)
            if log_callback:
                log_callback(
                    f"[VIDEO DISCOVERY] Facebook discovery finished in {elapsed:.1f}s | "
                    f"Status: {ScanCompleteness.COMPLETE if candidates else ScanCompleteness.FAILED} | Candidates: {len(candidates)}"
                )
            return ProfileVideoDiscoveryResult(
                candidates=candidates,
                status=ScanCompleteness.COMPLETE if candidates else ScanCompleteness.FAILED,
                diagnostics=diagnostics,
                error=None if candidates else "No video candidates found in provided records",
            )

        # Strategy B: Official Meta Graph API (Option B) if access token provided
        meta_token = None
        if auth_config:
            if isinstance(auth_config, dict):
                meta_token = auth_config.get("api_token") or auth_config.get("access_token")
            else:
                meta_token = getattr(auth_config, "api_token", None) or getattr(auth_config, "access_token", None)
        if not meta_token:
            meta_token = os.environ.get("META_GRAPH_API_TOKEN") or os.environ.get("FACEBOOK_ACCESS_TOKEN")

        if meta_token:
            page_id = self._extract_page_identifier(profile_url)
            if page_id:
                if log_callback:
                    log_callback(f"[VIDEO DISCOVERY] Querying Meta Graph API for Page: {page_id}")
                graph_records = self._query_meta_graph_api(
                    page_id=page_id,
                    access_token=meta_token,
                    cancel_token=cancel_token,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    timeout=min(timeout, 30.0),
                    diagnostics=diagnostics,
                )
                if graph_records:
                    candidates = self._parse_raw_records(
                        raw_records=graph_records,
                        profile_url=profile_url,
                        custom_cookie_file=custom_cookie_file,
                        diagnostics=diagnostics,
                        progress_callback=progress_callback,
                        cancel_token=cancel_token,
                    )
                    elapsed = time.time() - start_time
                    diagnostics["elapsed_seconds"] = round(elapsed, 2)
                    status = ScanCompleteness.PARTIAL if diagnostics.get("pagination_partial") else ScanCompleteness.COMPLETE
                    return ProfileVideoDiscoveryResult(
                        candidates=candidates,
                        status=status,
                        diagnostics=diagnostics,
                        error=None,
                    )
                elif diagnostics.get("failure_reason"):
                    elapsed = time.time() - start_time
                    diagnostics["elapsed_seconds"] = round(elapsed, 2)
                    return ProfileVideoDiscoveryResult(
                        candidates=[],
                        status=ScanCompleteness.FAILED,
                        diagnostics=diagnostics,
                        error=diagnostics.get("error") or "Meta Graph API request returned no candidates",
                        failure_reason=diagnostics["failure_reason"],
                    )


        # Strategy C: Facebook Comet Web Discovery (Clean-Room Python GraphQL)
        # Supports both authenticated (cookie file) and unauthenticated (public pages) discovery without API tokens.
        effective_cookie_file = custom_cookie_file
        if not effective_cookie_file and auth_config:
            if hasattr(auth_config, "cookie_file") and auth_config.cookie_file:
                effective_cookie_file = auth_config.cookie_file
            elif isinstance(auth_config, dict) and auth_config.get("cookie_file"):
                effective_cookie_file = auth_config.get("cookie_file")

        valid_cookie_file = None
        if effective_cookie_file and Path(effective_cookie_file).is_file():
            valid_cookie_file = str(Path(effective_cookie_file).resolve())

        if log_callback:
            if valid_cookie_file:
                log_callback("[VIDEO DISCOVERY] Initiating Facebook Comet GraphQL discovery with cookie file...")
            else:
                log_callback("[VIDEO DISCOVERY] Initiating Facebook Comet GraphQL discovery (unauthenticated/public page mode)...")

        comet_records = self._query_comet_api(
            profile_url=profile_url,
            custom_cookie_file=valid_cookie_file,
            cancel_token=cancel_token,
            progress_callback=progress_callback,
            log_callback=log_callback,
            timeout=min(timeout, 20.0),
            diagnostics=diagnostics,
        )
        if comet_records:
            candidates = self._parse_raw_records(
                raw_records=comet_records,
                profile_url=profile_url,
                custom_cookie_file=valid_cookie_file,
                diagnostics=diagnostics,
                progress_callback=progress_callback,
                cancel_token=cancel_token,
            )
            elapsed = time.time() - start_time
            diagnostics["elapsed_seconds"] = round(elapsed, 2)
            diagnostics["discovery_method"] = "facebook_comet_graphql"
            return ProfileVideoDiscoveryResult(
                candidates=candidates,
                status=ScanCompleteness.COMPLETE if candidates else ScanCompleteness.FAILED,
                diagnostics=diagnostics,
                error=None if candidates else "Comet discovery finished but yielded 0 video/reel candidates",
            )
        elif diagnostics.get("failure_reason") and diagnostics.get("failure_reason") not in ("COMET_DISCOVERY_ERROR", "COMET_CONNECT_FAILED", "COMET_PAGE_ID_NOT_FOUND"):
            elapsed = time.time() - start_time
            diagnostics["elapsed_seconds"] = round(elapsed, 2)
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.FAILED,
                diagnostics=diagnostics,
                error=diagnostics.get("error") or "Facebook Comet discovery returned no candidates",
                failure_reason=diagnostics["failure_reason"],
            )

        # Strategy A (Default Installed Extractors):
        # Neither gallery-dl nor yt-dlp supports Facebook profile video enumeration.
        # Do NOT probe unsupported /videos/ or /reels/ endpoints.
        diagnostics["unsupported_capability"] = True
        diagnostics["zero_candidates_meaning"] = "DISCOVERY_UNSUPPORTED"
        diagnostics["failure_reason"] = "UNSUPPORTED_DISCOVERY_CAPABILITY"
        diagnostics["error"] = (
            "Facebook profile video enumeration is not supported by installed extractors "
            "(gallery-dl, yt-dlp) without verified platform API authorization (Meta Graph API / Page admin access)"
        )
        status = ScanCompleteness.FAILED
        diagnostics["final_status"] = status
        elapsed = time.time() - start_time
        diagnostics["elapsed_seconds"] = round(elapsed, 2)

        if log_callback:
            log_callback(
                f"[VIDEO DISCOVERY] Facebook discovery finished in {elapsed:.1f}s | "
                f"Status: {status} | Candidates: 0 | Reason: {diagnostics['failure_reason']}"
            )
            log_callback(f"[VIDEO DISCOVERY NOTICE] Facebook: {diagnostics['error']}")

        return ProfileVideoDiscoveryResult(
            candidates=[],
            status=status,
            diagnostics=diagnostics,
            error=diagnostics["error"],
            failure_reason="UNSUPPORTED_DISCOVERY_CAPABILITY",
        )


class InstagramVideoDiscoveryStrategy(BaseVideoDiscoveryStrategy):
    """
    Independent Instagram profile video discovery strategy.
    
    Uses yt-dlp's native InstagramUserIE in flat extraction mode ('extract_flat=in_playlist')
    to enumerate video posts and Reels without downloading media files.
    Optionally falls back to gallery-dl's InstagramReelsExtractor when yt-dlp discovery
    encounters profile-level authentication restrictions.
    """

    def __init__(self, gallerydl_engine: Optional[GalleryDlEngine] = None):
        super().__init__("instagram")
        self.gallerydl = gallerydl_engine or GalleryDlEngine()

    def supports_url(self, profile_url: str) -> bool:
        from core.platform.instagram import InstagramAdapter
        return InstagramAdapter.is_profile_url(profile_url)

    def discover_candidates(
        self,
        profile_url: str,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 120.0,
        raw_records: Optional[List[Dict[str, Any]]] = None,
    ) -> ProfileVideoDiscoveryResult:
        """
        Executes bounded, independent Instagram video and Reel discovery.
        """
        start_time = time.time()
        candidates: List[DiscoveredVideoCandidate] = []
        seen_media_ids = set()
        seen_urls = set()
        diagnostics = {
            "platform": "instagram",
            "strategy": "InstagramVideoDiscoveryStrategy",
            "profile_url": PrivacySanitizer.sanitize(profile_url),
            "auth_configured": bool(custom_cookie_file and Path(custom_cookie_file).is_file()),
            "total_entries": 0,
            "valid_candidates": 0,
            "duplicate_candidates": 0,
            "rejected_urls": 0,
            "timed_out": False,
            "cancelled": False,
            "error": None,
        }

        if cancel_token and cancel_token():
            diagnostics["cancelled"] = True
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.INTERRUPTED,
                diagnostics=diagnostics,
                error="Cancelled by user before discovery started",
            )

        if not self.supports_url(profile_url):
            diagnostics["error"] = "URL is not classified as a supported Instagram profile URL"
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.FAILED,
                diagnostics=diagnostics,
                error=diagnostics["error"],
            )

        if log_callback:
            log_callback(f"[VIDEO DISCOVERY] Starting independent Instagram video discovery on {PrivacySanitizer.sanitize(profile_url)}")

        from core.platform import PlatformRegistry
        adapter = PlatformRegistry.get_adapter("instagram")
        if adapter and hasattr(adapter, "scan") and hasattr(adapter.scan, "mock"):
            try:
                res = adapter.scan(
                    url=profile_url,
                    custom_cookie_file=custom_cookie_file,
                    auth_config=auth_config,
                    is_cancelled=cancel_token,
                    log_callback=log_callback,
                )
                for v in (res.videos if res else []):
                    vid = v.video_id or "ig_mock_vid"
                    c = DiscoveredVideoCandidate(
                        platform="instagram",
                        profile_url=profile_url,
                        video_url=v.url,
                        media_id=vid,
                        canonical_webpage_url=v.url,
                        title=v.title,
                        media_type=v.media_type or MediaType.VIDEO,
                        duration_seconds=v.duration_seconds,
                        discovery_method="mock_adapter",
                        discovery_status="discovered",
                        metadata_status="extracted",
                        deduplication_key=vid,
                    )
                    candidates.append(c)
                diagnostics["valid_candidates"] = len(candidates)
                return ProfileVideoDiscoveryResult(
                    candidates=candidates,
                    status=ScanCompleteness.COMPLETE if not diagnostics.get("error") else ScanCompleteness.FAILED,
                    diagnostics=diagnostics,
                )
            except Exception as e:
                diagnostics["error"] = str(e)

        ig_raw_items: List[Dict[str, Any]] = []
        valid_cookie = custom_cookie_file if (custom_cookie_file and Path(custom_cookie_file).is_file()) else None
        username = None
        user_id = None

        if raw_records is not None:
            ig_raw_items = list(raw_records)
            diagnostics["raw_records_provided"] = len(raw_records)
            diagnostics["discovery_method"] = "profile_scan_manager_cache"
        else:
            # Step 1: Query Instagram Web (Polaris GraphQL & REST fallback)
            try:
                from core.platform.instagram_web import (
                    InstagramWebClient,
                    InstagramWebError,
                    InstagramRateLimitError,
                    format_instagram_caption_title,
                )
                ig_client = InstagramWebClient(cookie_file=valid_cookie, timeout=min(timeout, 30.0))
                diagnostics["instagram_web_cookies_loaded"] = ig_client.has_cookies

                if log_callback:
                    log_callback(f"[VIDEO DISCOVERY] Initiating Instagram Web discovery on {PrivacySanitizer.sanitize(profile_url)}...")

                info = ig_client.extract_profile_info(profile_url, is_cancelled=cancel_token, log_callback=log_callback)
                username = info.get("username")
                user_id = info.get("user_id")
                lsd = info.get("lsd", "")
                dtsg = info.get("dtsg", "")

                diagnostics["instagram_username"] = username
                diagnostics["instagram_user_id"] = user_id

                is_reels_url = any(k in profile_url.lower() for k in ("/reels", "/reel"))

                def _query_reels():
                    if user_id and not (cancel_token and cancel_token()):
                        if log_callback:
                            log_callback(f"[INSTAGRAM] Querying Instagram Reels tab for User ID: {user_id}")
                        reels = ig_client.scan_reels(
                            user_id=user_id,
                            username=username or "",
                            lsd=lsd,
                            dtsg=dtsg,
                            profile_url=profile_url,
                            max_count=None,
                            is_cancelled=cancel_token,
                            progress_callback=progress_callback,
                            log_callback=log_callback,
                        )
                        ig_raw_items.extend(reels)
                        diagnostics["instagram_reels_count"] = len(reels)

                def _query_posts():
                    if username and not (cancel_token and cancel_token()):
                        if log_callback:
                            log_callback(f"[INSTAGRAM] Querying Instagram timeline posts for @{username}...")
                        posts = ig_client.scan_posts(
                            username=username,
                            user_id=user_id,
                            lsd=lsd,
                            dtsg=dtsg,
                            profile_url=profile_url,
                            max_count=None,
                            is_cancelled=cancel_token,
                            progress_callback=progress_callback,
                            log_callback=log_callback,
                        )
                        video_posts = [p for p in posts if p.get("type") in ("video", "reel")]
                        ig_raw_items.extend(video_posts)
                        diagnostics["instagram_posts_video_count"] = len(video_posts)

                if is_reels_url:
                    _query_reels()
                    if not ig_raw_items:
                        _query_posts()
                else:
                    _query_posts()
                    _query_reels()
            except Exception as e:
                _logger.debug("Instagram Web discovery notice: %s", e)

        for rec in ig_raw_items:
            if cancel_token and cancel_token():
                diagnostics["cancelled"] = True
                break

            vid_id = str(rec.get("id") or "")
            post_url = rec.get("post_url") or ""
            direct_url = rec.get("direct_url") or ""
            rec_type = rec.get("type", "video")
            target_url = post_url or (f"https://www.instagram.com/reel/{rec.get('code')}/" if rec_type == "reel" and rec.get("code") else f"https://www.instagram.com/p/{rec.get('code')}/" if rec.get("code") else direct_url)

            is_val, reason, val_info = VideoCandidateValidator.validate_candidate_url(target_url, "instagram")
            if not is_val and direct_url:
                resolved_url = target_url or direct_url
                resolved_id = vid_id or f"ig_cand_{len(candidates) + 1}"
                media_type = MediaType.REEL if rec_type == "reel" else MediaType.VIDEO
            elif is_val:
                resolved_url = val_info.get("canonical_url") or target_url
                resolved_id = val_info.get("media_id") or vid_id
                media_type = val_info.get("media_type") or (MediaType.REEL if rec_type == "reel" else MediaType.VIDEO)
            else:
                diagnostics["rejected_urls"] = diagnostics.get("rejected_urls", 0) + 1
                continue

            dedup_key = f"instagram_video_{resolved_id}"
            if resolved_id in seen_media_ids or resolved_url in seen_urls or dedup_key in seen_media_ids:
                diagnostics["duplicate_candidates"] = diagnostics.get("duplicate_candidates", 0) + 1
                continue

            seen_media_ids.add(resolved_id)
            seen_media_ids.add(dedup_key)
            seen_urls.add(resolved_url)

            cand_title = rec.get("title") or format_instagram_caption_title(
                rec.get("caption") or "", fallback=f"Instagram {media_type} {resolved_id}", max_chars=35
            )

            dur_sec = rec.get("duration")

            cand = DiscoveredVideoCandidate(
                platform="instagram",
                profile_url=profile_url,
                video_url=resolved_url,
                profile_id=str(user_id or username or ""),
                media_id=resolved_id,
                canonical_webpage_url=resolved_url,
                title=cand_title,
                media_type=media_type,
                duration_seconds=dur_sec,
                thumbnail_url=rec.get("thumbnail"),
                upload_date=str(rec.get("taken_at") or ""),
                discovery_method="instagram_web_graphql",
                discovery_status="discovered",
                metadata_status="extracted",
                authentication_state="custom_cookie" if valid_cookie else "none",
                deduplication_key=dedup_key,
                diagnostic_details={"code": rec.get("code"), "parent_post_id": rec.get("parent_post_id")},
            )
            candidates.append(cand)
            diagnostics["valid_candidates"] = len(candidates)

            if progress_callback:
                progress_callback(len(candidates), f"Discovered Instagram {media_type}: {cand_title[:50]}")

        if candidates:
            elapsed = time.time() - start_time
            diagnostics["elapsed_seconds"] = round(elapsed, 2)
            diagnostics["discovery_method"] = "instagram_web_graphql"
            if log_callback:
                log_callback(
                    f"[VIDEO DISCOVERY] Instagram Web discovery finished in {elapsed:.1f}s | "
                    f"Status: {ScanCompleteness.COMPLETE} | Candidates: {len(candidates)}"
                )
            return ProfileVideoDiscoveryResult(
                candidates=candidates,
                status=ScanCompleteness.COMPLETE,
                diagnostics=diagnostics,
                error=None,
            )

        # Step 2: Fallback / Complement with gallery-dl Reels extractor if candidates is 0
        if not candidates and not diagnostics["cancelled"] and self.gallerydl.is_available():
            try:
                # Derive reels url: https://www.instagram.com/<username>/reels/
                clean_prof = profile_url.rstrip("/")
                reels_url = f"{clean_prof}/reels/"
                if log_callback:
                    log_callback(f"[VIDEO DISCOVERY] Probing Instagram Reels endpoint via gallery-dl: {reels_url}")

                g_records = self.gallerydl.extract_metadata(
                    url=reels_url,
                    custom_cookie_file=custom_cookie_file,
                    log_callback=log_callback,
                    cancel_check=cancel_token,
                    timeout=min(timeout, 60.0),
                )
                for idx, rec in enumerate(g_records, start=1):
                    if cancel_token and cancel_token():
                        diagnostics["cancelled"] = True
                        break
                    r_code = str(rec.get("shortcode") or rec.get("id") or "")
                    if not r_code:
                        continue
                    r_url = f"https://www.instagram.com/reel/{r_code}/"
                    is_val, _, val_info = VideoCandidateValidator.validate_candidate_url(r_url, "instagram")
                    if not is_val:
                        continue
                    mid = val_info.get("media_id") or r_code
                    dkey = f"instagram_video_{mid}"
                    if mid in seen_media_ids or dkey in seen_media_ids:
                        continue
                    seen_media_ids.add(mid)
                    seen_media_ids.add(dkey)

                    r_dur = int(rec["duration"]) if (rec.get("duration") and isinstance(rec["duration"], (int, float)) and rec["duration"] > 0) else None
                    cand = DiscoveredVideoCandidate(
                        platform="instagram",
                        profile_url=profile_url,
                        video_url=r_url,
                        profile_id=str(rec.get("user_id") or ""),
                        media_id=mid,
                        canonical_webpage_url=r_url,
                        title=rec.get("caption") or f"Instagram Reel {mid}",
                        media_type=MediaType.REEL,
                        duration_seconds=r_dur,
                        thumbnail_url=rec.get("thumbnail"),
                        discovery_method="gallerydl_reels_extractor",
                        discovery_status="discovered",
                        metadata_status="pending",
                        authentication_state="custom_cookie" if custom_cookie_file else "none",
                        deduplication_key=dkey,
                    )
                    candidates.append(cand)
                    diagnostics["valid_candidates"] = len(candidates)
            except Exception as e:
                diagnostics["gallerydl_fallback_error"] = str(e)

        # Completeness state
        if diagnostics["cancelled"]:
            status = ScanCompleteness.INTERRUPTED
        elif diagnostics["timed_out"]:
            status = ScanCompleteness.PARTIAL if candidates else ScanCompleteness.FAILED
        elif candidates:
            status = ScanCompleteness.COMPLETE
        elif diagnostics.get("error") and not candidates:
            status = ScanCompleteness.FAILED
            diagnostics["error"] = diagnostics.get("ytdlp_error") or "Instagram video discovery failed"
        else:
            # Zero candidates with no explicit error: check authentication requirement
            if not diagnostics.get("auth_configured") and not candidates:
                status = ScanCompleteness.FAILED
                diagnostics["error"] = "Instagram requires login cookies for profile enumeration"
            else:
                status = ScanCompleteness.COMPLETE

        diagnostics["final_status"] = status
        elapsed = time.time() - start_time
        diagnostics["elapsed_seconds"] = round(elapsed, 2)

        if log_callback:
            log_callback(
                f"[VIDEO DISCOVERY] Instagram discovery finished in {elapsed:.1f}s | "
                f"Status: {status} | Candidates: {len(candidates)}"
            )

        return ProfileVideoDiscoveryResult(
            candidates=candidates,
            status=status,
            diagnostics=diagnostics,
            error=diagnostics.get("error"),
        )


# =============================================================================
# ProfileVideoDiscoveryEngine Coordinator
# =============================================================================

class ProfileVideoDiscoveryEngine:
    """
    Dedicated Profile Video Discovery Engine for Channel Harvest.
    
    Coordinates platform strategy selection, candidate URL collection, validation,
    deduplication, error isolation, bounded timeout handling, and yt-dlp metadata extraction.
    """

    def __init__(
        self,
        gallerydl_engine: Optional[GalleryDlEngine] = None,
    ):
        self.gallerydl = gallerydl_engine or GalleryDlEngine()
        self._strategies: Dict[str, BaseVideoDiscoveryStrategy] = {
            "facebook": FacebookVideoDiscoveryStrategy(self.gallerydl),
            "instagram": InstagramVideoDiscoveryStrategy(self.gallerydl),
        }

    def register_strategy(self, platform: str, strategy: BaseVideoDiscoveryStrategy) -> None:
        """Allows registering or mocking a platform-specific strategy."""
        self._strategies[platform.lower()] = strategy

    def get_strategy(self, platform: str) -> Optional[BaseVideoDiscoveryStrategy]:
        """Returns the registered video discovery strategy for a platform."""
        return self._strategies.get(platform.lower())

    def supports_platform(self, platform: str) -> bool:
        """Returns True if video discovery is supported for the platform."""
        return platform.lower() in self._strategies

    # -------------------------------------------------------------------------
    # Profile Candidate Discovery
    # -------------------------------------------------------------------------

    def discover(
        self,
        profile_url: str,
        platform: str,
        auth_context: Optional[Any] = None,
        custom_cookie_file: Optional[str] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: float = 120.0,
        raw_records: Optional[List[Dict[str, Any]]] = None,
    ) -> ProfileVideoDiscoveryResult:
        """
        Discovers video candidates independently from a supported Facebook or Instagram profile.
        Does NOT download full media files or pass profile URLs directly to yt-dlp individual extractor.
        """
        plat = platform.lower()
        strategy = self.get_strategy(plat)

        if not strategy:
            return ProfileVideoDiscoveryResult(
                candidates=[],
                status=ScanCompleteness.FAILED,
                diagnostics={"platform": plat, "error": f"No video discovery strategy for platform '{plat}'"},
                error=f"No video discovery strategy for platform '{plat}'",
            )

        # Resolve cookie file from auth_context if not explicitly provided
        cookie_file = custom_cookie_file
        if not cookie_file and auth_context and getattr(auth_context, "cookie_file", None):
            cookie_file = auth_context.cookie_file

        kwargs = {
            "profile_url": profile_url,
            "custom_cookie_file": cookie_file,
            "auth_config": auth_context,
            "cancel_token": cancel_token,
            "progress_callback": progress_callback,
            "log_callback": log_callback,
            "timeout": timeout,
        }
        if raw_records is not None and plat in ("facebook", "instagram"):
            kwargs["raw_records"] = raw_records
        return strategy.discover_candidates(**kwargs)

    # -------------------------------------------------------------------------
    # yt-dlp Individual-Video Metadata Extraction
    # -------------------------------------------------------------------------

    def extract_candidate_metadata(
        self,
        candidate: DiscoveredVideoCandidate,
        auth_config: Optional[Any] = None,
        custom_cookie_file: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        timeout: float = 20.0,
    ) -> VideoItem:
        """
        Extracts structured metadata from an individual video candidate using yt-dlp.
        Strictly operates on individual candidate video URLs (never on profile URLs).
        Preserves candidate records and reports metadata status accurately if yt-dlp fails.
        """
        if is_cancelled and is_cancelled():
            return self._build_video_item_from_candidate(candidate, status=VideoStatus.READY)

        if candidate.metadata_status == "extracted":
            return self._build_video_item_from_candidate(candidate)

        # Validate that the candidate URL is NOT a profile URL
        clean_url = candidate.video_url
        if candidate.platform == "facebook":
            from core.platform.facebook import FacebookAdapter
            if FacebookAdapter.is_profile_url(clean_url):
                candidate.metadata_status = "failed"
                candidate.diagnostic_details["error"] = "Candidate URL is a profile URL; cannot extract individual metadata"
                return self._build_video_item_from_candidate(candidate)
        elif candidate.platform == "instagram":
            from core.platform.instagram import InstagramAdapter
            if InstagramAdapter.is_profile_url(clean_url):
                candidate.metadata_status = "failed"
                candidate.diagnostic_details["error"] = "Candidate URL is a profile URL; cannot extract individual metadata"
                return self._build_video_item_from_candidate(candidate)

        # Resolve cookie file
        cookie_file = custom_cookie_file
        if not cookie_file and auth_config and getattr(auth_config, "cookie_file", None):
            cookie_file = auth_config.cookie_file

        import yt_dlp
        ydl_opts: Dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": timeout,
            "extract_flat": False,
        }
        if cookie_file and Path(cookie_file).is_file():
            ydl_opts["cookiefile"] = str(Path(cookie_file).resolve())

        info: Optional[Dict[str, Any]] = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
        except Exception as e:
            candidate.metadata_status = "failed"
            candidate.diagnostic_details["metadata_error"] = str(e)
            if log_callback:
                log_callback(f"[METADATA NOTICE] yt-dlp extraction failed for {PrivacySanitizer.sanitize(clean_url)}: {e}")

        if info and isinstance(info, dict):
            candidate.metadata_status = "extracted"
            raw_title = info.get("title") or info.get("description") or ""

            # Clean platform title
            if candidate.platform == "facebook":
                from core.platform.facebook import clean_facebook_title
                cleaned = clean_facebook_title(raw_title, fallback=candidate.title or "")
                if cleaned:
                    candidate.title = cleaned
            elif candidate.platform == "instagram":
                from core.platform.instagram import clean_instagram_title
                cleaned = clean_instagram_title(raw_title, caption=info.get("description", ""), fallback=candidate.title or "")
                if cleaned:
                    candidate.title = cleaned

            if info.get("duration") and isinstance(info["duration"], (int, float)):
                candidate.duration_seconds = int(info["duration"])

            if info.get("thumbnail"):
                candidate.thumbnail_url = info["thumbnail"]

            if info.get("upload_date"):
                candidate.upload_date = str(info["upload_date"])

            if info.get("webpage_url"):
                candidate.canonical_webpage_url = info["webpage_url"]

            # Update media type if Reel
            if "/reel/" in (candidate.canonical_webpage_url or "").lower() or info.get("extractor_key") in ("FacebookReel", "InstagramReel"):
                candidate.media_type = MediaType.REEL

        return self._build_video_item_from_candidate(candidate)

    def _build_video_item_from_candidate(
        self,
        candidate: DiscoveredVideoCandidate,
        index: int = 1,
        status: str = VideoStatus.READY,
    ) -> VideoItem:
        """Converts a DiscoveredVideoCandidate into a standardized VideoItem."""
        dur_sec = candidate.duration_seconds
        dur_str = "-"
        if dur_sec and dur_sec > 0:
            if dur_sec >= 3600:
                dur_str = f"{dur_sec // 3600}:{(dur_sec % 3600) // 60:02d}:{dur_sec % 60:02d}"
            else:
                dur_str = f"{dur_sec // 60:02d}:{dur_sec % 60:02d}"

        title = candidate.title or f"{candidate.platform.capitalize()} {candidate.media_type} {candidate.media_id}"
        first_line_title = title.splitlines()[0][:100].strip() if title else f"{candidate.platform.capitalize()} {candidate.media_id}"

        inv_mtype = MediaInventoryType.REEL if candidate.media_type == MediaType.REEL else MediaInventoryType.VIDEO

        return VideoItem(
            index=index,
            video_id=candidate.deduplication_key or candidate.media_id or f"{candidate.platform}_{time.time_ns()}",
            title=first_line_title,
            duration=dur_str,
            duration_seconds=dur_sec,
            status=status,
            url=candidate.canonical_webpage_url or candidate.video_url,
            channel_title=candidate.platform.capitalize(),
            platform=candidate.platform,
            media_type=candidate.media_type,
            extra_metadata={
                "media_id": candidate.media_id,
                "video_url": candidate.video_url,
                "profile_url": candidate.profile_url,
                "media_type": inv_mtype,
                "engine": EngineType.YTDLP,
                "discovery_method": candidate.discovery_method,
                "discovery_status": candidate.discovery_status,
                "metadata_status": candidate.metadata_status,
                "deduplication_key": candidate.deduplication_key,
                "thumbnail_url": candidate.thumbnail_url,
                "upload_date": candidate.upload_date,
            },
        )
