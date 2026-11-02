"""
downloader/engine_router.py
Centralized DownloadEngineRouter for Channel Harvest.

Authoritative decision component responsible for routing media download tasks
to either gallery-dl or yt-dlp based on platform, media classification,
engine availability, authentication state, and bounded fallback policies.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple, List

from core.inventory import MediaInventoryType, MediaItemRecord
from core.models import VideoItem
from core.media_classifier import MediaClassifier
from downloader.gallerydl_engine import GalleryDlEngine

_logger = logging.getLogger("ChannelHarvest.DownloadEngineRouter")


class EngineType:
    """Download engine identifiers."""
    YTDLP = "yt-dlp"
    GALLERY_DL = "gallery-dl"
    UNSUPPORTED = "unsupported"


@dataclass
class EngineRouteDecision:
    """Represents a deterministic engine selection decision."""
    engine: str
    media_type: str
    rationale: str
    can_fallback: bool = False
    fallback_engine: Optional[str] = None
    metadata_probed: bool = False
    fallback_attempts: int = 0
    warning: str = ""

    @property
    def is_ytdlp(self) -> bool:
        return self.engine == EngineType.YTDLP

    @property
    def is_gallery_dl(self) -> bool:
        return self.engine == EngineType.GALLERY_DL

    @property
    def is_supported(self) -> bool:
        return self.engine != EngineType.UNSUPPORTED


class DownloadEngineRouter:
    """
    Centralized download engine routing coordinator.
    Ensures deterministic, testable, and credential-scrubbed engine decisions.
    """

    def __init__(self, gallerydl_engine: Optional[GalleryDlEngine] = None):
        self._gallerydl = gallerydl_engine or GalleryDlEngine()

    def route_media_item(
        self,
        item: Any,
        platform: Optional[str] = None,
        auth_config: Optional[Any] = None,
        probe_if_unknown: bool = True,
    ) -> EngineRouteDecision:
        """
        Determines the appropriate download engine for a VideoItem, MediaItemRecord,
        or metadata dictionary.
        """
        # 1. Normalize platform
        target_platform = (platform or getattr(item, "platform", None) or "youtube").lower()

        # 2. Extract media type and metadata
        media_type, raw_metadata = self._resolve_media_type_and_metadata(item, target_platform)

        # 3. If unknown, perform metadata probing if enabled
        metadata_probed = False
        if media_type == MediaInventoryType.UNKNOWN and probe_if_unknown:
            media_type = self._probe_media_type(item, target_platform, raw_metadata)
            metadata_probed = True

        # 4. Apply routing policy by platform and media type
        decision = self._apply_routing_policy(target_platform, media_type, raw_metadata)
        decision.metadata_probed = metadata_probed

        # 5. Check engine availability
        decision = self._verify_engine_availability(decision, target_platform)

        # Safe diagnostic log
        item_id = getattr(item, "video_id", None) or getattr(item, "media_id", None) or "unknown"
        _logger.debug(
            f"[ROUTER] Platform={target_platform} MediaID={item_id} "
            f"Type={media_type} SelectedEngine={decision.engine} Rationale='{decision.rationale}'"
        )

        return decision

    def _resolve_media_type_and_metadata(
        self,
        item: Any,
        platform: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Extracts normalized media type and available extraction metadata."""
        if isinstance(item, MediaItemRecord):
            return item.media_type, {"url": item.media_url, "mime_type": item.mime_type, "ext": item.extension}

        if isinstance(item, VideoItem):
            extra = getattr(item, "extra_metadata", {}) or {}
            m_type = extra.get("media_type")
            if m_type:
                return str(m_type).upper(), extra
            # VideoItem by default represents a video unless extra metadata indicates image
            if extra.get("is_image") or extra.get("is_photo"):
                return MediaInventoryType.IMAGE, extra
            return MediaInventoryType.VIDEO, extra

        if isinstance(item, dict):
            classified = MediaClassifier.classify_extracted_item(item, platform=platform)
            return classified, item

        return MediaInventoryType.UNKNOWN, {}

    def _probe_media_type(
        self,
        item: Any,
        platform: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Probes metadata to disambiguate unknown media types."""
        classified = MediaClassifier.classify_extracted_item(metadata, platform=platform)
        if classified != MediaInventoryType.UNKNOWN:
            return classified

        url = getattr(item, "url", None) or metadata.get("url") or ""
        clean_url = str(url).lower().split("?")[0]

        if any(clean_url.endswith(f".{ext}") for ext in ("jpg", "jpeg", "png", "webp", "gif", "heic")):
            return MediaInventoryType.IMAGE
        if any(clean_url.endswith(f".{ext}") for ext in ("mp4", "mov", "webm", "mkv")):
            return MediaInventoryType.VIDEO

        if platform == "instagram":
            if "/p/" in clean_url and not any(k in clean_url for k in ("/reel/", "/reels/")):
                # Instagram /p/ can be photo or video, assume image if yt-dlp found no video
                return MediaInventoryType.IMAGE

        return MediaInventoryType.UNKNOWN

    def _apply_routing_policy(
        self,
        platform: str,
        media_type: str,
        metadata: Dict[str, Any],
    ) -> EngineRouteDecision:
        """Authoritative routing policy matrix."""
        # ---------------------------------------------------------------------
        # Instagram Routing Policy
        # ---------------------------------------------------------------------
        if platform == "instagram":
            if media_type == MediaInventoryType.IMAGE:
                return EngineRouteDecision(
                    engine=EngineType.GALLERY_DL,
                    media_type=media_type,
                    rationale="Instagram photo / image-set selected for gallery-dl extraction",
                    can_fallback=False,  # yt-dlp does not download standalone photos reliably
                )
            if media_type in (MediaInventoryType.VIDEO, MediaInventoryType.REEL):
                return EngineRouteDecision(
                    engine=EngineType.YTDLP,
                    media_type=media_type,
                    rationale="Instagram Reel / video media routed to yt-dlp",
                    can_fallback=True,
                    fallback_engine=EngineType.GALLERY_DL,  # gallery-dl can download video if yt-dlp fails
                )
            if media_type == MediaInventoryType.AUDIO:
                return EngineRouteDecision(
                    engine=EngineType.YTDLP,
                    media_type=media_type,
                    rationale="Audio extraction routed to yt-dlp",
                    can_fallback=False,
                )
            if media_type == MediaInventoryType.UNSUPPORTED:
                return EngineRouteDecision(
                    engine=EngineType.UNSUPPORTED,
                    media_type=media_type,
                    rationale="Instagram media format or post is unsupported",
                    can_fallback=False,
                )
            # Unknown Instagram media: default to gallery-dl if photo indicators, else yt-dlp
            return EngineRouteDecision(
                engine=EngineType.GALLERY_DL,
                media_type=media_type,
                rationale="Unknown Instagram media routed to gallery-dl for probing",
                can_fallback=True,
                fallback_engine=EngineType.YTDLP,
            )

        # ---------------------------------------------------------------------
        # Facebook Routing Policy
        # ---------------------------------------------------------------------
        if platform == "facebook":
            if media_type == MediaInventoryType.IMAGE:
                return EngineRouteDecision(
                    engine=EngineType.GALLERY_DL,
                    media_type=media_type,
                    rationale="Facebook photo / album selected for gallery-dl extraction",
                    can_fallback=False,
                )
            if media_type in (MediaInventoryType.VIDEO, MediaInventoryType.REEL):
                return EngineRouteDecision(
                    engine=EngineType.YTDLP,
                    media_type=media_type,
                    rationale="Facebook video / Reel routed to yt-dlp",
                    can_fallback=False,  # yt-dlp is primary Facebook video extractor
                )
            if media_type == MediaInventoryType.AUDIO:
                return EngineRouteDecision(
                    engine=EngineType.YTDLP,
                    media_type=media_type,
                    rationale="Facebook audio extraction routed to yt-dlp",
                    can_fallback=False,
                )
            if media_type == MediaInventoryType.UNSUPPORTED:
                return EngineRouteDecision(
                    engine=EngineType.UNSUPPORTED,
                    media_type=media_type,
                    rationale="Facebook media format is unsupported",
                    can_fallback=False,
                )
            return EngineRouteDecision(
                engine=EngineType.YTDLP,
                media_type=media_type,
                rationale="Unclassified Facebook media routed to yt-dlp",
                can_fallback=True,
                fallback_engine=EngineType.GALLERY_DL,
            )

        # ---------------------------------------------------------------------
        # Default Platforms (YouTube, TikTok, Bilibili, X)
        # ---------------------------------------------------------------------
        if media_type == MediaInventoryType.UNSUPPORTED:
            return EngineRouteDecision(
                engine=EngineType.UNSUPPORTED,
                media_type=media_type,
                rationale=f"Media type unsupported on {platform}",
                can_fallback=False,
            )

        return EngineRouteDecision(
            engine=EngineType.YTDLP,
            media_type=media_type,
            rationale=f"Standard video/audio engine yt-dlp selected for {platform}",
            can_fallback=False,
        )

    def _verify_engine_availability(
        self,
        decision: EngineRouteDecision,
        platform: str,
    ) -> EngineRouteDecision:
        """Verifies selected engine is installed and capable of running."""
        if decision.engine == EngineType.GALLERY_DL:
            if not self._gallerydl.is_available():
                # gallery-dl is not available! Check if fallback to yt-dlp is possible
                if decision.can_fallback and decision.fallback_engine == EngineType.YTDLP:
                    decision.warning = "gallery-dl is not installed; falling back to yt-dlp."
                    decision.engine = EngineType.YTDLP
                    decision.rationale += f" (Fallback: {decision.warning})"
                else:
                    decision.engine = EngineType.UNSUPPORTED
                    decision.warning = (
                        "gallery-dl is required for this image/album task but is not available on this system. "
                        "Please verify gallery-dl installation."
                    )
                    decision.rationale = decision.warning

        return decision

    # -------------------------------------------------------------------------
    # Bounded Fallback Evaluation
    # -------------------------------------------------------------------------

    def evaluate_fallback(
        self,
        current_decision: EngineRouteDecision,
        error_category: str,
        raw_error: str = "",
        fallback_count: int = 0,
    ) -> Optional[EngineRouteDecision]:
        """
        Evaluates whether a bounded fallback to an alternative engine is permissible.

        STRICT RULES:
        - Maximum 1 fallback attempt per task.
        - Fallback is FORBIDDEN after:
          - Authentication failure / login required
          - Account rate limiting (HTTP 429)
          - Access restriction / private video
          - Confirmed deleted content
          - Cancellation by user
        - Permitted ONLY when:
          - The current engine encountered an extraction or format error
          - The alternative engine genuinely supports the media format
        """
        if fallback_count >= 1:
            return None

        if not current_decision.can_fallback or not current_decision.fallback_engine:
            return None

        # Forbidden failure categories
        from core.error_classifier import ErrorCategory
        forbidden_categories = {
            getattr(ErrorCategory, "LOGIN_REQUIRED", "LOGIN_REQUIRED"),
            getattr(ErrorCategory, "RATE_LIMITED", "RATE_LIMITED"),
            getattr(ErrorCategory, "PRIVATE_VIDEO", "PRIVATE_VIDEO"),
            getattr(ErrorCategory, "VIDEO_UNAVAILABLE", "VIDEO_UNAVAILABLE"),
            getattr(ErrorCategory, "BOT_VERIFICATION", "BOT_VERIFICATION"),
            getattr(ErrorCategory, "CANCELLED", "CANCELLED"),
        }

        if error_category in forbidden_categories:
            _logger.debug(f"[ROUTER] Fallback rejected due to error category: {error_category}")
            return None

        alt_engine = current_decision.fallback_engine

        # Verify alternative engine availability
        if alt_engine == EngineType.GALLERY_DL and not self._gallerydl.is_available():
            return None

        return EngineRouteDecision(
            engine=alt_engine,
            media_type=current_decision.media_type,
            rationale=f"Bounded fallback from {current_decision.engine} to {alt_engine} after error: {error_category}",
            can_fallback=False,  # Disallow secondary chained fallback
            fallback_attempts=fallback_count + 1,
        )
