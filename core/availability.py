"""
core/availability.py
Platform-Aware Availability Detection and State Model for Channel Harvest.

Provides:
- AvailabilityStatus: Typed enum representing all supported availability states.
- AvailabilityReasonCode: Machine-readable reason codes.
- VideoAvailability: Dataclass capturing typed availability metadata, diagnostic evidence,
  and confirmation state.
- PlatformAvailabilityDetector: Abstract base class for platform-specific detectors.
- YouTubeAvailabilityDetector, TikTokAvailabilityDetector, BilibiliAvailabilityDetector,
  FacebookAvailabilityDetector, InstagramAvailabilityDetector, DouyinAvailabilityDetector: Dedicated detectors.
- AvailabilityDetectorRegistry: Factory and registry for resolving platform detectors.
"""

from __future__ import annotations
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Type


class AvailabilityStatus(str, Enum):
    """
    Explicit, typed availability states for media items across all platforms.
    """
    AVAILABLE = "AVAILABLE"
    PRIVATE = "PRIVATE"
    DELETED = "DELETED"
    REGION_RESTRICTED = "REGION_RESTRICTED"
    AGE_RESTRICTED = "AGE_RESTRICTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNLISTED = "UNLISTED"
    NO_SUPPORTED_FORMAT = "NO_SUPPORTED_FORMAT"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    TEMPORARY_ERROR = "TEMPORARY_ERROR"


class AvailabilityReasonCode(str, Enum):
    """
    Machine-readable reason codes for availability classifications.
    """
    OK = "OK"
    UNLISTED_ACCESSIBLE = "UNLISTED_ACCESSIBLE"
    ERR_PRIVATE = "ERR_PRIVATE"
    ERR_DELETED = "ERR_DELETED"
    ERR_REGION_RESTRICTED = "ERR_REGION_RESTRICTED"
    ERR_AGE_RESTRICTED = "ERR_AGE_RESTRICTED"
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_ACCESS_DENIED = "ERR_ACCESS_DENIED"
    ERR_NO_SUPPORTED_FORMAT = "ERR_NO_SUPPORTED_FORMAT"
    ERR_UNAVAILABLE = "ERR_UNAVAILABLE"
    ERR_UPCOMING = "ERR_UPCOMING"
    ERR_TEMPORARY = "ERR_TEMPORARY"
    ERR_UNKNOWN = "ERR_UNKNOWN"


@dataclass
class VideoAvailability:
    """
    Normalized, typed availability description for a single video item.

    Attributes:
        status: Specific AvailabilityStatus.
        reason_code: Machine-readable reason code from AvailabilityReasonCode.
        user_message: Human-readable explanatory message.
        is_confirmed: True if definitively verified inaccessible; False if suspected or temporary.
        evidence: Diagnostic evidence (e.g. raw error string, HTTP status, platform code).
        platform: Platform identifier ('youtube', 'tiktok', 'bilibili', 'facebook', 'douyin').
        video_id: Stable video identifier if available.
        source_title: Original source title (preserved intact).
        source_url: Original source URL (preserved intact).
        extra: Additional diagnostic or platform-specific key-values.
    """
    status: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    reason_code: str = AvailabilityReasonCode.OK.value
    user_message: str = ""
    is_confirmed: bool = True
    evidence: str = ""
    platform: str = "youtube"
    video_id: str = ""
    source_title: str = ""
    source_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_definitively_inaccessible(self) -> bool:
        """
        Determines whether the video is definitively inaccessible and should be automatically
        deselected, uncheckable, and excluded from the download queue.

        CRITICAL INVARIANTS:
        1. UNLISTED videos are NOT inaccessible. They must remain selectable and downloadable.
        2. TEMPORARY_ERROR (e.g. HTTP 429, timeouts, bot challenges) is NOT definitively inaccessible.
        3. AVAILABLE is selectable.
        4. PRIVATE, DELETED, REGION_RESTRICTED, AGE_RESTRICTED (without auth), AUTH_REQUIRED,
           ACCESS_DENIED, NO_SUPPORTED_FORMAT, and UNAVAILABLE are definitively inaccessible when confirmed.
        """
        if not self.is_confirmed:
            return False

        inaccessible_set = {
            AvailabilityStatus.PRIVATE,
            AvailabilityStatus.DELETED,
            AvailabilityStatus.REGION_RESTRICTED,
            AvailabilityStatus.AGE_RESTRICTED,
            AvailabilityStatus.AUTH_REQUIRED,
            AvailabilityStatus.ACCESS_DENIED,
            AvailabilityStatus.NO_SUPPORTED_FORMAT,
            AvailabilityStatus.UNAVAILABLE,
        }
        return self.status in inaccessible_set

    def is_selectable(self) -> bool:
        """Returns True if the video can be selected by the user for download."""
        return not self.is_definitively_inaccessible()

    def get_localized_message(self, lang_code: Optional[str] = None) -> str:
        """
        Returns a localized explanatory message suitable for tooltips and status display.
        """
        from core.i18n import I18nManager, tr

        curr_lang = lang_code or I18nManager.get_language()
        is_tw = (curr_lang == "zh_TW")
        is_cn = (curr_lang == "zh_CN")

        if self.status == AvailabilityStatus.AVAILABLE:
            return "Video is available." if not is_cn and not is_tw else ("视频可用。" if is_cn else "影片可用。")
        elif self.status == AvailabilityStatus.UNLISTED:
            return tr("avail_msg_unlisted")
        elif self.status == AvailabilityStatus.PRIVATE:
            return tr("avail_msg_private")
        elif self.status == AvailabilityStatus.DELETED:
            return tr("avail_msg_deleted")
        elif self.status == AvailabilityStatus.REGION_RESTRICTED:
            return tr("avail_msg_region_restricted")
        elif self.status == AvailabilityStatus.AGE_RESTRICTED:
            return tr("avail_msg_age_restricted")
        elif self.status == AvailabilityStatus.AUTH_REQUIRED:
            return tr("avail_msg_auth_required")
        elif self.status == AvailabilityStatus.ACCESS_DENIED:
            return tr("avail_msg_access_denied")
        elif self.reason_code == AvailabilityReasonCode.ERR_UPCOMING.value:
            return tr("avail_msg_upcoming")
        elif self.status == AvailabilityStatus.UNAVAILABLE:
            return tr("avail_msg_unavailable")
        elif self.status == AvailabilityStatus.TEMPORARY_ERROR:
            return "Temporary network or server error." if not is_cn and not is_tw else ("临时网络或服务器错误。" if is_cn else "暫時網路或伺服器錯誤。")
        
        return self.user_message or self.status.value


# =============================================================================
# Platform-Specific Availability Detectors
# =============================================================================

class PlatformAvailabilityDetector:
    """
    Abstract base detector for evaluating video availability.
    Each platform implements dedicated heuristic rules based on its own API and yt-dlp output.
    """
    platform_name: str = "generic"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        """
        Evaluates a scanned entry dictionary (from yt-dlp extract_flat or extract_info).
        """
        raise NotImplementedError

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        """
        Evaluates an extraction or download error message.
        """
        raise NotImplementedError


class YouTubeAvailabilityDetector(PlatformAvailabilityDetector):
    """
    YouTube-specific availability detector.
    Understands YouTube's flat extraction markers, availability flags, and error signatures.
    """
    platform_name: str = "youtube"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or "")
        raw_title = title or str(entry.get("title") or "")
        t_clean = raw_title.strip()
        t_lower = t_clean.lower()
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")
        avail_flag = str(entry.get("availability") or "").lower().strip()
        live_status = str(entry.get("live_status") or "").lower().strip()

        # 1. Unlisted check (MUST NOT be treated as unavailable!)
        if avail_flag == "unlisted":
            return VideoAvailability(
                status=AvailabilityStatus.UNLISTED,
                reason_code=AvailabilityReasonCode.UNLISTED_ACCESSIBLE.value,
                user_message="Unlisted video (accessible with link)",
                is_confirmed=True,
                evidence=f"availability={avail_flag}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # 2. Private video detection
        is_private_title = (
            t_clean in ("[Private video]", "[私享视频]", "[私密视频]", "[私人影片]", "[私密影片]")
            or "private video" in t_lower
            or "私享视频" in t_clean
            or "私密视频" in t_clean
            or "私人影片" in t_clean
            or "私密影片" in t_clean
        )
        if avail_flag == "private" or is_private_title:
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Private video. Sign in if you've been granted access.",
                is_confirmed=True,
                evidence=f"availability={avail_flag}, title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # 3. Deleted video detection
        is_deleted_title = (
            t_clean in ("[Deleted video]", "[已删除视频]", "[已刪除影片]")
            or "deleted video" in t_lower
            or "已删除视频" in t_clean
            or "已刪除影片" in t_clean
        )
        if avail_flag == "deleted" or is_deleted_title:
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="This video has been removed or deleted.",
                is_confirmed=True,
                evidence=f"availability={avail_flag}, title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # 4. Upcoming / premiere live stream
        if live_status in ("is_upcoming", "post_live") or t_clean.startswith("Premieres in "):
            return VideoAvailability(
                status=AvailabilityStatus.UNAVAILABLE,
                reason_code=AvailabilityReasonCode.ERR_UPCOMING.value,
                user_message="Upcoming live stream or premiere is not yet downloadable.",
                is_confirmed=True,
                evidence=f"live_status={live_status}, title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # 5. Members-only / authentication required
        if avail_flag in ("needs_auth", "subscriber_only", "premium_only"):
            if not auth_active:
                return VideoAvailability(
                    status=AvailabilityStatus.AUTH_REQUIRED,
                    reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                    user_message="Members-only content requires login authorization.",
                    is_confirmed=True,
                    evidence=f"availability={avail_flag}",
                    platform=self.platform_name,
                    video_id=vid_id,
                    source_title=raw_title,
                    source_url=vid_url,
                )

        # 6. Unavailable video detection
        is_unavailable_title = (
            t_clean in ("[Unavailable video]", "[不可用视频]", "[無法播放影片]", "[無法存取影片]")
            or "unavailable video" in t_lower
            or "不可用视频" in t_clean
            or "無法播放影片" in t_clean
            or "無法存取影片" in t_clean
        )
        if avail_flag == "unavailable" or is_unavailable_title:
            return VideoAvailability(
                status=AvailabilityStatus.UNAVAILABLE,
                reason_code=AvailabilityReasonCode.ERR_UNAVAILABLE.value,
                user_message="Video is unavailable.",
                is_confirmed=True,
                evidence=f"availability={avail_flag}, title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # Default: Available
        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # Check for transient/temporary errors FIRST to avoid misclassifying rate limits/timeouts as deleted
        if any(term in low for term in ("http error 429", "too many requests", "bot verification", "sign in to confirm you’re not a bot", "timed out", "timeout", "connection reset")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Temporary rate limit or network issue.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Private
        if any(term in low for term in ("private video", "sign in if you've been granted access", "video is private")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Private video. Sign in if you've been granted access.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Deleted
        if any(term in low for term in (
            "video has been removed",
            "removed by the uploader",
            "removed by the user",
            "video has been deleted",
            "violating youtube's terms of service",
            "account has been terminated",
            "this video does not exist",
        )):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="This video has been removed or deleted.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Region restricted
        if any(term in low for term in ("not made this video available in your country", "blocked it in your country", "geo-restricted", "who has blocked it in your country")):
            return VideoAvailability(
                status=AvailabilityStatus.REGION_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_REGION_RESTRICTED.value,
                user_message="This video is not available in your country.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Age restricted
        if "sign in to confirm your age" in low:
            return VideoAvailability(
                status=AvailabilityStatus.AGE_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_AGE_RESTRICTED.value,
                user_message="Sign in to confirm your age.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Members-only / Auth
        if any(term in low for term in ("members-only content", "join this channel to get access", "this video is only available to channel members")):
            return VideoAvailability(
                status=AvailabilityStatus.AUTH_REQUIRED,
                reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                user_message="This video is only available to channel members.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # Upcoming
        if any(term in low for term in ("premieres in", "live event will begin in")):
            return VideoAvailability(
                status=AvailabilityStatus.UNAVAILABLE,
                reason_code=AvailabilityReasonCode.ERR_UPCOMING.value,
                user_message="Upcoming premiere or live stream is not yet available.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        # General unavailable
        if any(term in low for term in ("video unavailable", "this video is unavailable", "not available")):
            return VideoAvailability(
                status=AvailabilityStatus.UNAVAILABLE,
                reason_code=AvailabilityReasonCode.ERR_UNAVAILABLE.value,
                user_message="Video unavailable.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=msg,
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class TikTokAvailabilityDetector(PlatformAvailabilityDetector):
    """
    TikTok-specific availability detector.
    Inspects privateItem, deleteItem, creator restrictions, and TikTok error signatures.
    """
    platform_name: str = "tiktok"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or "")
        raw_title = title or str(entry.get("title") or "")
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")

        # 1. Private post / item
        if entry.get("privateItem") is True or entry.get("is_private") is True:
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="This TikTok video is private.",
                is_confirmed=True,
                evidence="privateItem=True",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        # 2. Deleted item
        if entry.get("deleteItem") is True or entry.get("is_delete") is True:
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="This TikTok video was deleted.",
                is_confirmed=True,
                evidence="deleteItem=True",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # Temporary / Anti-bot / Impersonation errors MUST NOT be treated as permanent deletion
        if any(term in low for term in ("impersonate target", "attempting impersonation", "timed out", "timeout", "connection", "rate limited")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Temporary TikTok network or runtime error.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("this video is private", "this post is private", "not have permission", "private")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="This TikTok video is private.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("this video was deleted", "video currently unavailable", "removed", "video unavailable")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="This TikTok video was deleted or removed.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("access denied", "10204", "blocked")):
            return VideoAvailability(
                status=AvailabilityStatus.ACCESS_DENIED,
                reason_code=AvailabilityReasonCode.ERR_ACCESS_DENIED.value,
                user_message="TikTok access denied (Code 10204).",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=msg,
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class BilibiliAvailabilityDetector(PlatformAvailabilityDetector):
    """
    Bilibili-specific availability detector.
    Understands Bilibili response codes:
    - -404: Deleted / Video does not exist
    - 62002: Author only (Private)
    - 62012: Big VIP only (大会员)
    - 62014: Charging exclusive (充电专属)
    - -10403: Geo/Area restriction
    - 352: Risk Control Challenge (Temporary / Anti-scraping — NOT deleted!)
    - 412: WAF Precondition Failed (Temporary)
    """
    platform_name: str = "bilibili"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or entry.get("bvid") or "")
        raw_title = title or str(entry.get("title") or "")
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")
        code = entry.get("code")

        if code == -404 or raw_title in ("视频不存在", "啥都木有"):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Bilibili video is deleted or does not exist.",
                is_confirmed=True,
                evidence=f"code={code}, title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if code == 62002 or "稿件仅作者可见" in raw_title:
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Bilibili video is visible only to author (Private).",
                is_confirmed=True,
                evidence=f"code={code}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if code in (62012, 62014) or any(k in raw_title for k in ("仅大会员可看", "充电专属")):
            if not auth_active:
                return VideoAvailability(
                    status=AvailabilityStatus.AUTH_REQUIRED,
                    reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                    user_message="Bilibili content requires VIP (大会员) or charging subscription.",
                    is_confirmed=True,
                    evidence=f"code={code}",
                    platform=self.platform_name,
                    video_id=vid_id,
                    source_title=raw_title,
                    source_url=vid_url,
                )

        if code == -10403 or any(k in raw_title for k in ("地区限制", "仅限中国大陆地区播放")):
            return VideoAvailability(
                status=AvailabilityStatus.REGION_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_REGION_RESTRICTED.value,
                user_message="Bilibili video is region-restricted.",
                is_confirmed=True,
                evidence=f"code={code}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # CRITICAL: Error 352 or 412 is a risk control / anti-scraping challenge; MUST NOT be marked deleted!
        if any(term in low for term in ("352", "rejected by server (352)", "code: -352", "412", "blocked by server (412)")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Bilibili risk control challenge (Error 352/412). Requires authenticated session or cooldown.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("keyerror('bvid')", "keyerror: 'bvid'", "deleted or geo-restricted", "-404", "视频不存在")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Bilibili video is deleted or unavailable.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("62002", "稿件仅作者可见", "private", "not have permission")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Bilibili video is private (visible only to author).",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("62012", "62014", "大会员", "充电专属")):
            return VideoAvailability(
                status=AvailabilityStatus.AUTH_REQUIRED,
                reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                user_message="Bilibili video requires VIP or charging subscription.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(term in low for term in ("-10403", "地区限制", "仅限中国大陆")):
            return VideoAvailability(
                status=AvailabilityStatus.REGION_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_REGION_RESTRICTED.value,
                user_message="Bilibili video is region-restricted.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=msg,
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class FacebookAvailabilityDetector(PlatformAvailabilityDetector):
    """
    Facebook-specific availability detector.
    Understands Facebook access denied, login required, content deleted, and privacy restrictions.
    """
    platform_name: str = "facebook"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or "")
        raw_title = title or str(entry.get("title") or "")
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")
        t_low = raw_title.lower()

        if any(k in t_low for k in ("isn't available right now", "content isn't available", "may have been removed", "deleted")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Facebook video is unavailable or has been removed.",
                is_confirmed=True,
                evidence=f"title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if any(k in t_low for k in ("log in to continue", "login required")):
            if not auth_active:
                return VideoAvailability(
                    status=AvailabilityStatus.AUTH_REQUIRED,
                    reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                    user_message="Facebook requires login to access this content.",
                    is_confirmed=True,
                    evidence=f"title={raw_title}",
                    platform=self.platform_name,
                    video_id=vid_id,
                    source_title=raw_title,
                    source_url=vid_url,
                )

        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # Temporary server/network error
        if any(k in low for k in ("http error 5", "500", "502", "503", "timed out", "timeout", "connection")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Temporary Facebook server or network error.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("log in to continue", "you must log in", "login required")):
            return VideoAvailability(
                status=AvailabilityStatus.AUTH_REQUIRED,
                reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                user_message="Facebook requires login to access this content.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("isn't available right now", "content isn't available", "not available", "may have been removed", "broken link")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Facebook content is unavailable, deleted, or removed.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("permission", "private", "access denied")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Facebook post is private or access is restricted.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("not available in your location", "not available in your region")):
            return VideoAvailability(
                status=AvailabilityStatus.REGION_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_REGION_RESTRICTED.value,
                user_message="Facebook video is not available in your region.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=msg,
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class InstagramAvailabilityDetector(PlatformAvailabilityDetector):
    """
    Instagram-specific availability detector.
    Understands Instagram login requirements, private accounts, deleted posts,
    photo-only posts (no video format), and rate-limiting.
    """
    platform_name: str = "instagram"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or "")
        raw_title = title or str(entry.get("title") or "")
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")
        t_low = raw_title.lower()

        if any(k in t_low for k in ("sorry, this page isn't available", "page not found", "post unavailable", "deleted", "removed")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Instagram post is unavailable or has been removed.",
                is_confirmed=True,
                evidence=f"title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if any(k in t_low for k in ("login required", "log in to continue", "checkpoint_required")):
            if not auth_active:
                return VideoAvailability(
                    status=AvailabilityStatus.AUTH_REQUIRED,
                    reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                    user_message="Instagram requires authentication to access this content.",
                    is_confirmed=True,
                    evidence=f"title={raw_title}",
                    platform=self.platform_name,
                    video_id=vid_id,
                    source_title=raw_title,
                    source_url=vid_url,
                )

        # Check for photo-only items without video formats
        formats = entry.get("formats") or []
        dur_val = entry.get("duration")
        has_video = any(f.get("vcodec") != "none" for f in formats) if formats else False
        if not has_video and dur_val is None:
            return VideoAvailability(
                status=AvailabilityStatus.NO_SUPPORTED_FORMAT,
                reason_code=AvailabilityReasonCode.ERR_NO_SUPPORTED_FORMAT.value,
                user_message="Instagram item is an image/photo without video formats.",
                is_confirmed=True,
                evidence="no_video_formats",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # Temporary server/network / rate-limiting error
        if any(k in low for k in ("http error 5", "500", "502", "503", "timed out", "timeout", "connection", "http error 429", "too many requests", "rate limit", "please wait a few minutes")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Temporary Instagram server, network, or rate-limiting error.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("login required", "log in to continue", "you must log in", "checkpoint_required", "redirected to login", "main webpage is locked behind the login page")):
            return VideoAvailability(
                status=AvailabilityStatus.AUTH_REQUIRED,
                reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                user_message="Instagram requires login to access this content. Configure a Custom Cookie File.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("private account", "this account is private", "user is private", "account is private")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="Instagram account is private. Access requires authorized credentials via Custom Cookie File.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("no video in this post", "there is no video in this post", "no video formats found")):
            return VideoAvailability(
                status=AvailabilityStatus.NO_SUPPORTED_FORMAT,
                reason_code=AvailabilityReasonCode.ERR_NO_SUPPORTED_FORMAT.value,
                user_message="Instagram post contains no downloadable video formats.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("sorry, this page isn't available", "page not found", "not found", "404", "does not exist", "post has been removed", "broken link")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="Instagram content is unavailable or has been removed.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("not available in your location", "not available in your region")):
            return VideoAvailability(
                status=AvailabilityStatus.REGION_RESTRICTED,
                reason_code=AvailabilityReasonCode.ERR_REGION_RESTRICTED.value,
                user_message="Instagram video is not available in your region.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=msg,
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class XAvailabilityDetector(PlatformAvailabilityDetector):
    """
    X (formerly Twitter)-specific availability detector.
    Understands X login requirements, protected accounts/posts, deleted posts,
    text/photo-only posts (no video format), withheld/suspended accounts,
    rate-limiting (HTTP 429), and temporary server errors.
    """
    platform_name: str = "x"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        vid_id = video_id or str(entry.get("id") or "")
        raw_title = title or str(entry.get("title") or "")
        vid_url = url or str(entry.get("url") or entry.get("webpage_url") or "")
        t_low = raw_title.lower()

        if any(k in t_low for k in ("sorry, that page doesn't exist", "sorry, that page does not exist", "tweet has been deleted", "this tweet was deleted", "page doesn't exist", "post unavailable", "deleted", "removed", "status not found", "no status found")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="X (Twitter) post is unavailable or has been deleted.",
                is_confirmed=True,
                evidence=f"title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if any(k in t_low for k in ("protected account", "this tweet is from a protected account", "account is protected")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="X (Twitter) account is protected. Access requires authorized credentials via Custom Cookie File.",
                is_confirmed=True,
                evidence=f"title={raw_title}",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        if any(k in t_low for k in ("login required", "log in to continue", "log in to x", "log in to twitter", "authorization required", "subscribers only")):
            if not auth_active:
                return VideoAvailability(
                    status=AvailabilityStatus.AUTH_REQUIRED,
                    reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                    user_message="X (Twitter) requires authentication to access this content.",
                    is_confirmed=True,
                    evidence=f"title={raw_title}",
                    platform=self.platform_name,
                    video_id=vid_id,
                    source_title=raw_title,
                    source_url=vid_url,
                )

        # Check for photo-only or text-only items without video formats
        formats = entry.get("formats") or []
        dur_val = entry.get("duration")
        has_video = any(f.get("vcodec") != "none" for f in formats) if formats else False
        if not has_video and dur_val is None:
            return VideoAvailability(
                status=AvailabilityStatus.NO_SUPPORTED_FORMAT,
                reason_code=AvailabilityReasonCode.ERR_NO_SUPPORTED_FORMAT.value,
                user_message="X (Twitter) item contains no downloadable video media.",
                is_confirmed=True,
                evidence="no_video_formats",
                platform=self.platform_name,
                video_id=vid_id,
                source_title=raw_title,
                source_url=vid_url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.AVAILABLE,
            reason_code=AvailabilityReasonCode.OK.value,
            user_message="Video is available.",
            is_confirmed=True,
            evidence="normal",
            platform=self.platform_name,
            video_id=vid_id,
            source_title=raw_title,
            source_url=vid_url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        msg = str(error_msg or "")
        low = msg.lower()

        # Temporary server/network / rate-limiting error
        if any(k in low for k in ("http error 429", "too many requests", "rate limit", "rate-limit", "rate limit exceeded", "http error 5", "500", "502", "503", "504", "timed out", "timeout", "connection", "temporary")):
            return VideoAvailability(
                status=AvailabilityStatus.TEMPORARY_ERROR,
                reason_code=AvailabilityReasonCode.ERR_TEMPORARY.value,
                user_message="Temporary X (Twitter) server, network, or rate-limiting error.",
                is_confirmed=False,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("requires authentication", "login required", "log in to view", "authorization required", "subscribers only", "this tweet is unavailable", "locked behind")):
            return VideoAvailability(
                status=AvailabilityStatus.AUTH_REQUIRED,
                reason_code=AvailabilityReasonCode.ERR_AUTH_REQUIRED.value,
                user_message="X (Twitter) requires login to access this content. Configure a Custom Cookie File.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("protected account", "this tweet is from a protected account", "account is protected")):
            return VideoAvailability(
                status=AvailabilityStatus.PRIVATE,
                reason_code=AvailabilityReasonCode.ERR_PRIVATE.value,
                user_message="X (Twitter) account is protected. Access requires authorized credentials via Custom Cookie File.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("no video could be found in this tweet", "there's no video in this tweet", "no video in this tweet", "no video formats found", "media is not a video", "no video")):
            return VideoAvailability(
                status=AvailabilityStatus.NO_SUPPORTED_FORMAT,
                reason_code=AvailabilityReasonCode.ERR_NO_SUPPORTED_FORMAT.value,
                user_message="X (Twitter) post contains no downloadable video formats.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("sorry, that page doesn't exist", "sorry, that page does not exist", "tweet has been deleted", "this tweet was deleted", "page doesn't exist", "does not exist", "not found", "404", "status not found", "no status found", "post has been removed", "deleted")):
            return VideoAvailability(
                status=AvailabilityStatus.DELETED,
                reason_code=AvailabilityReasonCode.ERR_DELETED.value,
                user_message="X (Twitter) content is unavailable or has been deleted.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        if any(k in low for k in ("withheld", "suspended", "account has been suspended", "restricted")):
            return VideoAvailability(
                status=AvailabilityStatus.UNAVAILABLE,
                reason_code=AvailabilityReasonCode.ERR_UNAVAILABLE.value,
                user_message="X (Twitter) account or post has been suspended or withheld.",
                is_confirmed=True,
                evidence=msg,
                platform=self.platform_name,
                video_id=video_id,
                source_title=title,
                source_url=url,
            )

        return VideoAvailability(
            status=AvailabilityStatus.UNKNOWN,
            reason_code=AvailabilityReasonCode.ERR_UNKNOWN.value,
            user_message=f"Unknown X (Twitter) extraction status: {msg}",
            is_confirmed=False,
            evidence=msg,
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )


class DouyinAvailabilityDetector(PlatformAvailabilityDetector):
    """
    Douyin detector.
    Douyin remains strictly frozen/disabled in Channel Harvest.
    """
    platform_name: str = "douyin"

    def detect_entry(
        self,
        entry: Dict[str, Any],
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        return VideoAvailability(
            status=AvailabilityStatus.ACCESS_DENIED,
            reason_code=AvailabilityReasonCode.ERR_ACCESS_DENIED.value,
            user_message="Douyin platform adapter is frozen/disabled.",
            is_confirmed=True,
            evidence="platform_disabled",
            platform=self.platform_name,
            video_id=video_id,
            source_title=title,
            source_url=url,
        )

    def detect_error(
        self,
        error_msg: str,
        video_id: str = "",
        title: str = "",
        url: str = "",
        auth_active: bool = False,
    ) -> VideoAvailability:
        return self.detect_entry({}, video_id, title, url, auth_active)


# =============================================================================
# Registry & Factory
# =============================================================================

x_detector_instance = XAvailabilityDetector()

class AvailabilityDetectorRegistry:
    """
    Registry for obtaining the appropriate platform-specific availability detector.
    """
    _detectors: Dict[str, PlatformAvailabilityDetector] = {
        "youtube": YouTubeAvailabilityDetector(),
        "youtubemusic": YouTubeAvailabilityDetector(),
        "tiktok": TikTokAvailabilityDetector(),
        "bilibili": BilibiliAvailabilityDetector(),
        "facebook": FacebookAvailabilityDetector(),
        "instagram": InstagramAvailabilityDetector(),
        "x": x_detector_instance,
        "twitter": x_detector_instance,
        "douyin": DouyinAvailabilityDetector(),
    }

    @classmethod
    def get_detector(cls, platform: Optional[str]) -> PlatformAvailabilityDetector:
        plat = (platform or "youtube").lower().strip()
        return cls._detectors.get(plat, cls._detectors["youtube"])
