"""
downloader/profile_scan_manager.py
Dual-Engine Profile Scan Manager for Facebook & Instagram in Channel Harvest.

Coordinates dual-engine profile-level scanning:
- gallery-dl for image-oriented media discovery (photos, albums, carousels).
- yt-dlp for video-oriented media discovery (standard videos, Reels, watch posts).
- Normalization into unified MediaType (PHOTO, VIDEO, REEL, UNKNOWN).
- Strict duration normalization: numeric duration_seconds, "-" for photos.
- Parent-child decomposition and incremental SQLite ProfileMediaInventory persistence.
- Independent engine outcome tracking and scan completeness states (COMPLETE, PARTIAL, INTERRUPTED, FAILED).
- Sanitized diagnostic logging and UTF-8 scan report generation.
"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable

from core.inventory import (
    ProfileMediaInventory,
    ProfileRecord,
    PostRecord,
    MediaItemRecord,
    ScanCompleteness,
    MediaInventoryType,
    generate_stable_media_id,
)
from core.models import VideoItem, VideoStatus, ScanResult, MediaType
from core.media_classifier import MediaClassifier
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlCancelledException, GalleryDlAuthError
from downloader.engine_router import DownloadEngineRouter, EngineType

_logger = logging.getLogger("ChannelHarvest.ProfileScanManager")


class ProfileScanManager:
    """
    Coordinates dual-engine profile media archiving scans across Facebook and Instagram.
    Separates scanning from downloading, ensuring persistent incremental inventory.
    """

    def __init__(
        self,
        inventory: Optional[ProfileMediaInventory] = None,
        gallerydl_engine: Optional[GalleryDlEngine] = None,
        engine_router: Optional[DownloadEngineRouter] = None,
        video_discovery_engine: Optional[Any] = None,
    ):
        self.inventory = inventory or ProfileMediaInventory()
        self.gallerydl = gallerydl_engine or GalleryDlEngine()
        self.router = engine_router or DownloadEngineRouter(self.gallerydl)
        from downloader.profile_video_discovery_engine import ProfileVideoDiscoveryEngine
        self.video_engine = video_discovery_engine or ProfileVideoDiscoveryEngine(self.gallerydl)

    def scan_profile(
        self,
        url: str,
        platform: str,
        custom_cookie_file: Optional[str] = None,
        auth_config: Optional[Any] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> ScanResult:
        """
        Executes a dual-engine profile scan for Facebook or Instagram.
        Attempts both gallery-dl (photos) and yt-dlp (videos) discovery,
        merging, deduplicating, and persisting discoveries incrementally.
        """
        scan_id = f"scan_{platform}_{int(time.time())}"
        start_time_iso = datetime.now(timezone.utc).isoformat()

        from core.platform import PlatformRegistry
        adapter = PlatformRegistry.get_adapter(platform)

        is_mock_adapter = bool(adapter and hasattr(adapter, "scan") and hasattr(adapter.scan, "mock"))

        if auth_config is None and adapter:
            from core.settings import SettingsManager
            try:
                sm = SettingsManager()
                auth_config = adapter.get_auth_config(sm)
            except Exception:
                auth_config = adapter.get_auth_config()

        if not custom_cookie_file:
            if auth_config and auth_config.cookie_file:
                custom_cookie_file = auth_config.cookie_file
            else:
                try:
                    from core.settings import SettingsManager
                    sm = SettingsManager()
                    pfx = f"{platform}_" if platform != "youtube" else ""
                    stored_file = sm.get(f"{pfx}custom_cookie_file", "")
                    if stored_file and Path(stored_file).is_file():
                        custom_cookie_file = stored_file
                except Exception:
                    pass

        auth_desc = auth_config.description if auth_config else "None"
        if log_callback:
            log_callback(f"[SCAN] Initializing dual-engine profile scan for {platform.capitalize()}: {url}")
            log_callback(f"[AUTH] Platform: {platform.capitalize()} | Authentication: {auth_desc}")
            if auth_config and auth_config.auth_method == "none" and "No file path configured" in auth_desc:
                log_callback(f"[AUTH NOTICE] {platform.capitalize()}: Custom Cookie File is selected in Settings but no file path is configured. Continuing with unauthenticated access.")
            elif auth_config and auth_config.auth_method == "none" and "not found" in auth_desc.lower():
                log_callback(f"[AUTH WARNING] {platform.capitalize()}: Configured cookie file does not exist on disk. Continuing with unauthenticated access.")

        # Initialize profile record in inventory
        profile_rec = ProfileRecord(
            platform=platform,
            profile_url=url,
            scan_id=scan_id,
            scan_start_time=start_time_iso,
            scan_status=ScanCompleteness.PARTIAL,
            scan_completeness_info="Scan in progress...",
        )
        self.inventory.upsert_profile(profile_rec)

        discovered_posts: List[PostRecord] = []
        discovered_media_items: List[MediaItemRecord] = []
        discovered_video_items: List[VideoItem] = []
        seen_post_ids = set()
        seen_media_ids = set()
        seen_urls = set()
        media_id_to_index: Dict[str, int] = {}

        gallery_attempted = False
        gallery_success = False
        gallery_timed_out = False
        gallery_error: Optional[str] = None

        ytdlp_attempted = False
        ytdlp_success = False
        ytdlp_error: Optional[str] = None

        scan_interrupted = False

        # =========================================================================
        # TASK 1: gallery-dl Image Discovery (Photos, Albums, Carousels)
        # =========================================================================
        is_fb_video_tab = platform == "facebook" and any(k in url.lower() for k in ("/reels", "/reel", "/videos"))
        is_fb_photo_tab = platform == "facebook" and any(k in url.lower() for k in ("/photos", "/photos_by", "/photos_albums"))
        is_ig_reels_tab = platform == "instagram" and any(k in url.lower() for k in ("/reels", "/reel"))
        is_video_only_tab = is_fb_video_tab or is_ig_reels_tab
        can_use_gallerydl = self.gallerydl.is_available() and not is_video_only_tab
        if is_fb_video_tab and log_callback:
            log_callback("[SCAN] Facebook Reels/Videos tab detected; skipping gallery-dl photo scan and focusing on video discovery.")
        elif is_ig_reels_tab and log_callback:
            log_callback("[SCAN] Instagram Reels tab detected; skipping gallery-dl photo scan and focusing on video discovery.")
        if can_use_gallerydl and not (is_cancelled and is_cancelled()):
            gallery_attempted = True
            try:
                task_label = "Task 1/1" if is_fb_photo_tab else "Task 1/2"
                if log_callback:
                    log_callback(f"[SCAN] {task_label}: Discovering photos with gallery-dl (v{self.gallerydl.get_version()})...")

                raw_records = self.gallerydl.extract_metadata(
                    url=url,
                    custom_cookie_file=custom_cookie_file,
                    log_callback=log_callback,
                    cancel_check=is_cancelled,
                )
                gallery_timed_out = getattr(raw_records, "timed_out", False)
                if gallery_timed_out:
                    gallery_error = f"gallery-dl reached timeout limit, but preserved {len(raw_records)} record(s)"
                    gallery_success = len(raw_records) > 0
                else:
                    gallery_success = True

                if log_callback:
                    log_callback(f"[SCAN] gallery-dl returned {len(raw_records)} item record(s). Merging into inventory...")

                for idx, record in enumerate(raw_records, start=1):
                    if is_cancelled and is_cancelled():
                        scan_interrupted = True
                        break

                    parent_meta, children = MediaClassifier.decompose_post(
                        record, platform=platform, discovery_source="gallery-dl"
                    )

                    parent_id = parent_meta.get("post_id") or f"post_{idx}"
                    post_rec = PostRecord(
                        platform=platform,
                        post_id=parent_id,
                        profile_id=parent_meta.get("profile_id"),
                        profile_url=url,
                        original_url=parent_meta.get("original_url"),
                        canonical_url=parent_meta.get("canonical_url"),
                        caption=parent_meta.get("caption"),
                        author=parent_meta.get("author"),
                        publication_date=parent_meta.get("publication_date"),
                        post_type=parent_meta.get("post_type"),
                        discovery_source="gallery-dl",
                        discovery_timestamp=start_time_iso,
                    )
                    self.inventory.upsert_post(post_rec)
                    if parent_id not in seen_post_ids:
                        seen_post_ids.add(parent_id)
                        discovered_posts.append(post_rec)

                    for c_idx, child in enumerate(children, start=1):
                        m_url = child.get("media_url")
                        m_type = child.get("media_type") or MediaInventoryType.IMAGE
                        m_id = generate_stable_media_id(
                            platform=platform,
                            platform_media_id=child.get("media_id"),
                            post_id=parent_id,
                            media_sequence_index=child.get("media_sequence_index", c_idx),
                            media_url=m_url,
                        )

                        if m_id in seen_media_ids:
                            continue
                        seen_media_ids.add(m_id)
                        if m_url:
                            seen_urls.add(m_url)
                        if child.get("media_id"):
                            seen_media_ids.add(str(child.get("media_id")))

                        route_decision = self.router.route_media_item(
                            item=child, platform=platform, auth_config=auth_config
                        )

                        item_rec = MediaItemRecord(
                            media_id=m_id,
                            platform=platform,
                            parent_post_id=parent_id,
                            media_url=m_url,
                            media_type=m_type,
                            media_sequence_index=child.get("media_sequence_index", c_idx),
                            media_count=child.get("media_count"),
                            mime_type=child.get("mime_type"),
                            extension=child.get("extension"),
                            width=child.get("width"),
                            height=child.get("height"),
                            duration=child.get("duration"),
                            discovery_source="gallery-dl",
                            preferred_engine=route_decision.engine,
                            selected_engine=route_decision.engine,
                            download_status="PENDING",
                        )
                        self.inventory.upsert_media_item(item_rec)
                        discovered_media_items.append(item_rec)

                        raw_title = parent_meta.get("caption") or f"{platform.capitalize()} {m_type} {m_id}"
                        if platform == "facebook":
                            from core.platform.facebook_comet import format_caption_title
                            fb_clean_id = m_id.replace("fb_photo_", "").replace("fb_reel_", "").replace("fb_video_", "")
                            fallback_name = "Photo" if m_type == MediaInventoryType.IMAGE else ("Reel" if m_type == MediaInventoryType.REEL else "Video")
                            first_line_title = format_caption_title(raw_title, fallback=f"Facebook {fallback_name} {fb_clean_id}", max_chars=35)
                        elif platform == "instagram":
                            from core.platform.instagram_web import format_instagram_caption_title
                            ig_clean_id = m_id.replace("ig_photo_", "").replace("ig_reel_", "").replace("ig_video_", "")
                            fallback_name = "Photo" if m_type == MediaInventoryType.IMAGE else ("Reel" if m_type == MediaInventoryType.REEL else "Video")
                            first_line_title = format_instagram_caption_title(raw_title, fallback=f"Instagram {fallback_name} {ig_clean_id}", max_chars=35)
                        else:
                            first_line_title = raw_title.splitlines()[0][:100].strip() if raw_title else f"{platform.capitalize()} {m_id}"

                        dur_sec = int(child.get("duration")) if (child.get("duration") and isinstance(child.get("duration"), (int, float)) and child.get("duration") > 0) else None
                        ui_media_type = MediaType.PHOTO if m_type == MediaInventoryType.IMAGE else (MediaType.REEL if m_type == MediaInventoryType.REEL else MediaType.VIDEO)

                        v_item = VideoItem(
                            index=len(discovered_video_items) + 1,
                            video_id=m_id,
                            title=first_line_title,
                            duration="-" if ui_media_type == MediaType.PHOTO else (f"{dur_sec // 60:02d}:{dur_sec % 60:02d}" if dur_sec else "-"),
                            duration_seconds=dur_sec,
                            status=VideoStatus.READY,
                            url=m_url or post_rec.canonical_url or url,
                            channel_title=post_rec.author or platform.capitalize(),
                            platform=platform,
                            media_type=ui_media_type,
                            extra_metadata={
                                "media_id": m_id,
                                "parent_post_id": parent_id,
                                "media_type": m_type,
                                "engine": route_decision.engine,
                                "post_url": post_rec.canonical_url,
                                "caption": post_rec.caption,
                                "author": post_rec.author,
                                "publication_date": post_rec.publication_date,
                                "media_sequence_index": child.get("media_sequence_index", c_idx),
                                "media_count": child.get("media_count"),
                            },
                        )
                        media_id_to_index[m_id] = len(discovered_video_items)
                        discovered_video_items.append(v_item)

                        if progress_callback:
                            try:
                                progress_callback(len(discovered_posts), len(discovered_media_items), f"Discovered {ui_media_type}: {first_line_title}")
                            except Exception:
                                pass

            except GalleryDlCancelledException:
                scan_interrupted = True
                if log_callback:
                    log_callback("[SCAN] gallery-dl photo discovery cancelled by user.")
            except GalleryDlAuthError as e:
                gallery_error = f"Authentication required: {e.message}"
                if log_callback:
                    log_callback(f"[WARNING] gallery-dl auth notice: {gallery_error}")
            except Exception as e:
                gallery_error = str(e)
                if log_callback:
                    log_callback(f"[WARNING] gallery-dl discovery notice: {e}")
        else:
            if not can_use_gallerydl:
                gallery_error = "gallery-dl is not available (fallback to video-only discovery)"
                if log_callback:
                    log_callback("[INFO] gallery-dl is not available; photo discovery skipped, falling back to video-only discovery.")

        # Facebook Comet Photo Discovery & Inventory Enrichment:
        # For Facebook profiles, modern collections require Comet GraphQL to paginate through all photos.
        # Queries the photos collection with complete enumeration (max_count=None) and merges any photos
        # that gallery-dl missed into inventory.
        if platform == "facebook" and not is_fb_video_tab and not scan_interrupted and not (is_cancelled and is_cancelled()):
            try:
                from core.platform.facebook_comet import FacebookCometClient, format_caption_title
                valid_cookie = custom_cookie_file if (custom_cookie_file and Path(custom_cookie_file).is_file()) else None
                comet_client = FacebookCometClient(cookie_file=valid_cookie)
                tokens = comet_client.extract_page_tokens(url, is_cancelled=is_cancelled, log_callback=log_callback)
                photos_id = tokens.get("photos_by_id") or tokens.get("page_id")
                if photos_id and tokens.get("lsd"):
                    if log_callback:
                        log_callback("[SCAN] Querying Facebook Comet photo collection for complete enumeration...")
                    comet_photos = comet_client.scan_photos(
                        photos_id=photos_id,
                        lsd=tokens["lsd"],
                        dtsg=tokens.get("dtsg", ""),
                        profile_url=url,
                        max_count=None,
                        is_cancelled=is_cancelled,
                        progress_callback=lambda c, msg: progress_callback(len(discovered_posts), len(discovered_media_items) + c, msg) if progress_callback else None,
                        log_callback=log_callback,
                    )
                    if comet_photos:
                        merged_count = 0
                        for idx, p in enumerate(comet_photos, start=1):
                            if is_cancelled and is_cancelled():
                                scan_interrupted = True
                                break
                            p_id = p["id"]
                            direct_url = p.get("direct_url")
                            m_id = f"fb_photo_{p_id}"
                            if (
                                m_id in seen_media_ids
                                or p_id in seen_media_ids
                                or (direct_url and direct_url in seen_urls)
                            ):
                                # If an item was previously recorded with a generic fallback title, upgrade to Comet's authentic title
                                existing_idx = media_id_to_index.get(m_id) or media_id_to_index.get(p_id)
                                if existing_idx is not None and 0 < existing_idx <= len(discovered_video_items):
                                    existing_item = discovered_video_items[existing_idx - 1]
                                    if (
                                        existing_item.title.startswith("Facebook ")
                                        and p.get("title")
                                        and not p["title"].startswith(f"Facebook Photo {p_id}")
                                    ):
                                        formatted_photo_title = format_caption_title(p.get("title"), fallback=f"Facebook Photo {p_id}", max_chars=35)
                                        existing_item.title = formatted_photo_title
                                continue

                            seen_media_ids.add(m_id)
                            seen_media_ids.add(p_id)
                            if direct_url:
                                seen_urls.add(direct_url)
                            merged_count += 1

                            parent_id = f"fb_photo_post_{p_id}"
                            raw_caption = p.get("caption") or p.get("title")
                            formatted_photo_title = format_caption_title(p.get("title") or raw_caption, fallback=f"Facebook Photo {p_id}", max_chars=35)
                            post_rec = PostRecord(
                                platform="facebook",
                                post_id=parent_id,
                                profile_id=photos_id,
                                profile_url=url,
                                original_url=p.get("post_url"),
                                canonical_url=p.get("post_url"),
                                caption=raw_caption or formatted_photo_title,
                                discovery_source="facebook-comet",
                                discovery_timestamp=start_time_iso,
                            )
                            self.inventory.upsert_post(post_rec)
                            if parent_id not in seen_post_ids:
                                seen_post_ids.add(parent_id)
                                discovered_posts.append(post_rec)

                            item_rec = MediaItemRecord(
                                media_id=m_id,
                                platform="facebook",
                                parent_post_id=parent_id,
                                media_url=direct_url,
                                media_type=MediaInventoryType.IMAGE,
                                media_sequence_index=1,
                                discovery_source="facebook-comet",
                                preferred_engine=EngineType.GALLERY_DL,
                                selected_engine=EngineType.GALLERY_DL,
                                download_status="PENDING",
                            )
                            self.inventory.upsert_media_item(item_rec)
                            discovered_media_items.append(item_rec)

                            v_item = VideoItem(
                                index=len(discovered_video_items) + 1,
                                video_id=m_id,
                                title=formatted_photo_title,
                                duration="-",
                                duration_seconds=None,
                                status=VideoStatus.READY,
                                url=direct_url,
                                channel_title=post_rec.author or "Facebook",
                                platform="facebook",
                                media_type=MediaType.PHOTO,
                                extra_metadata={
                                    "media_id": m_id,
                                    "parent_post_id": parent_id,
                                    "media_type": MediaInventoryType.IMAGE,
                                    "engine": EngineType.GALLERY_DL,
                                    "post_url": p.get("post_url"),
                                    "caption": raw_caption or formatted_photo_title,
                                },
                            )
                            media_id_to_index[m_id] = len(discovered_video_items)
                            discovered_video_items.append(v_item)

                        if merged_count > 0:
                            if log_callback:
                                log_callback(f"[SCAN] Facebook Comet merged {merged_count} photo(s) into inventory (total photos: {len(discovered_media_items)}).")
                            gallery_success = True
            except Exception as e:
                _logger.debug("Facebook Comet photo discovery notice: %s", e)

        # Instagram Web Photo Discovery & Inventory Enrichment:
        # Paginates Instagram timeline posts via Polaris GraphQL/REST to discover all photos & carousels
        # and merges any items missed by gallery-dl into inventory.
        ig_scanned_video_records: List[Dict[str, Any]] = []
        if platform == "instagram" and not is_ig_reels_tab and not scan_interrupted and not (is_cancelled and is_cancelled()):
            try:
                from core.platform.instagram_web import InstagramWebClient, format_instagram_caption_title
                valid_cookie = custom_cookie_file if (custom_cookie_file and Path(custom_cookie_file).is_file()) else None
                ig_client = InstagramWebClient(cookie_file=valid_cookie)
                ig_info = ig_client.extract_profile_info(url, is_cancelled=is_cancelled, log_callback=log_callback)
                ig_username = ig_info.get("username")
                if ig_username:
                    if log_callback:
                        log_callback(f"[SCAN] Querying Instagram Web feed for complete photo enumeration (@{ig_username})...")
                    ig_items = ig_client.scan_posts(
                        username=ig_username,
                        user_id=ig_info.get("user_id"),
                        lsd=ig_info.get("lsd", ""),
                        dtsg=ig_info.get("dtsg", ""),
                        profile_url=url,
                        max_count=None,
                        is_cancelled=is_cancelled,
                        progress_callback=lambda c, msg: progress_callback(len(discovered_posts), len(discovered_media_items) + c, msg) if progress_callback else None,
                        log_callback=log_callback,
                    )
                    if ig_items:
                        merged_count = 0
                        for idx, item in enumerate(ig_items, start=1):
                            if is_cancelled and is_cancelled():
                                scan_interrupted = True
                                break

                            item_type = item.get("type", "photo")
                            if item_type != "photo":
                                ig_scanned_video_records.append(item)
                                continue

                            item_id = str(item["id"])
                            direct_url = item.get("direct_url")
                            m_id = f"ig_photo_{item_id}"
                            if (
                                m_id in seen_media_ids
                                or item_id in seen_media_ids
                                or (direct_url and direct_url in seen_urls)
                            ):
                                existing_idx = media_id_to_index.get(m_id) or media_id_to_index.get(item_id)
                                if existing_idx is not None and 0 < existing_idx <= len(discovered_video_items):
                                    existing_item = discovered_video_items[existing_idx - 1]
                                    if (
                                        existing_item.title.startswith("Instagram ")
                                        and item.get("title")
                                        and not item["title"].startswith(f"Instagram Photo {item_id}")
                                    ):
                                        existing_item.title = item["title"]
                                continue

                            seen_media_ids.add(m_id)
                            seen_media_ids.add(item_id)
                            if direct_url:
                                seen_urls.add(direct_url)
                            merged_count += 1

                            parent_id = f"ig_post_{item.get('parent_post_id') or item_id}"
                            raw_caption = item.get("caption") or ""
                            formatted_photo_title = item.get("title") or format_instagram_caption_title(
                                raw_caption, fallback=f"Instagram Photo {item_id}", max_chars=35
                            )

                            post_rec = PostRecord(
                                platform="instagram",
                                post_id=parent_id,
                                profile_id=ig_info.get("user_id") or ig_username,
                                profile_url=url,
                                original_url=item.get("post_url"),
                                canonical_url=item.get("post_url"),
                                caption=raw_caption or formatted_photo_title,
                                author=item.get("author") or ig_username,
                                discovery_source="instagram-web",
                                discovery_timestamp=start_time_iso,
                            )
                            self.inventory.upsert_post(post_rec)
                            if parent_id not in seen_post_ids:
                                seen_post_ids.add(parent_id)
                                discovered_posts.append(post_rec)

                            item_rec = MediaItemRecord(
                                media_id=m_id,
                                platform="instagram",
                                parent_post_id=parent_id,
                                media_url=direct_url,
                                media_type=MediaInventoryType.IMAGE,
                                media_sequence_index=item.get("sequence_index", 1),
                                media_count=item.get("media_count", 1),
                                discovery_source="instagram-web",
                                preferred_engine=EngineType.GALLERY_DL,
                                selected_engine=EngineType.GALLERY_DL,
                                download_status="PENDING",
                            )
                            self.inventory.upsert_media_item(item_rec)
                            discovered_media_items.append(item_rec)

                            v_item = VideoItem(
                                index=len(discovered_video_items) + 1,
                                video_id=m_id,
                                title=formatted_photo_title,
                                duration="-",
                                duration_seconds=None,
                                status=VideoStatus.READY,
                                url=direct_url,
                                channel_title=item.get("author") or ig_username,
                                platform="instagram",
                                media_type=MediaType.PHOTO,
                                extra_metadata={
                                    "media_id": m_id,
                                    "parent_post_id": parent_id,
                                    "media_type": MediaInventoryType.IMAGE,
                                    "engine": EngineType.GALLERY_DL,
                                    "post_url": item.get("post_url"),
                                    "caption": raw_caption or formatted_photo_title,
                                    "author": item.get("author") or ig_username,
                                    "media_sequence_index": item.get("sequence_index", 1),
                                    "media_count": item.get("media_count", 1),
                                },
                            )
                            media_id_to_index[m_id] = len(discovered_video_items)
                            discovered_video_items.append(v_item)

                        if merged_count > 0:
                            if log_callback:
                                log_callback(f"[SCAN] Instagram Web merged {merged_count} photo(s) into inventory (total photos: {len(discovered_media_items)}).")
                            gallery_success = True
            except Exception as e:
                _logger.debug("Instagram Web photo discovery notice: %s", e)

        # =========================================================================
        # TASK 2: Independent Profile Video Discovery & yt-dlp Metadata Extraction
        # =========================================================================
        video_attempted = False
        video_success = False
        video_timed_out = False
        video_error: Optional[str] = None
        discovered_candidates_count = 0

        if is_fb_photo_tab:
            if log_callback:
                log_callback("[SCAN] Facebook Photos tab detected; skipping video/reels discovery and focusing on photo discovery.")
        elif not scan_interrupted and not (is_cancelled and is_cancelled()):
            video_attempted = True
            task_label = "Task 1/1" if is_video_only_tab else "Task 2/2"
            try:
                if log_callback:
                    log_callback(f"[SCAN] {task_label}: Discovering videos & Reels with ProfileVideoDiscoveryEngine...")

                if self.video_engine.supports_platform(platform):
                    v_res = self.video_engine.discover(
                        profile_url=url,
                        platform=platform,
                        auth_context=auth_config,
                        custom_cookie_file=custom_cookie_file,
                        cancel_token=is_cancelled,
                        progress_callback=lambda count, msg: progress_callback(len(discovered_posts), len(discovered_media_items) + count, msg) if progress_callback else None,
                        log_callback=log_callback,
                        raw_records=ig_scanned_video_records if ig_scanned_video_records else None,
                    )
                    discovered_candidates_count = len(v_res.candidates)
                    video_timed_out = v_res.diagnostics.get("timed_out", False)
                    video_error = v_res.error
                    video_success = v_res.status in (ScanCompleteness.COMPLETE, ScanCompleteness.PARTIAL)

                    if log_callback:
                        if v_res.candidates:
                            log_callback(f"[SCAN] ProfileVideoDiscoveryEngine returned {len(v_res.candidates)} video candidate(s). Extracting metadata with yt-dlp...")
                        else:
                            log_callback(f"[SCAN] ProfileVideoDiscoveryEngine returned 0 video candidate(s). Video metadata extraction skipped.")
                            if v_res.error:
                                log_callback(f"[VIDEO DISCOVERY NOTICE] {v_res.error}")

                    # =================================================================
                    # TASK 3: yt-dlp Individual-Video Metadata Extraction
                    # =================================================================
                    for cand in v_res.candidates:
                        if is_cancelled and is_cancelled():
                            scan_interrupted = True
                            break

                        stable_id = cand.deduplication_key or generate_stable_media_id(
                            platform=platform,
                            platform_media_id=cand.media_id,
                            post_id=cand.media_id,
                            media_sequence_index=1,
                            media_url=cand.video_url,
                        )

                        item_mtype = cand.media_type
                        inv_mtype = MediaInventoryType.REEL if item_mtype == MediaType.REEL else MediaInventoryType.VIDEO

                        # Check if already seen via gallery-dl: merge complementary video duration/formats
                        already_seen = (
                            stable_id in seen_media_ids
                            or (cand.media_id and cand.media_id in seen_media_ids)
                            or (cand.media_id and cand.media_id in seen_post_ids)
                            or (cand.media_id and f"{platform}_{cand.media_id}_1" in seen_media_ids)
                            or (cand.video_url and any(cand.video_url in (v.url or "") for v in discovered_video_items))
                        )
                        if already_seen:
                            matched_idx = media_id_to_index.get(stable_id)
                            if matched_idx is None and cand.media_id:
                                matched_idx = media_id_to_index.get(cand.media_id)
                                if matched_idx is None:
                                    matched_idx = media_id_to_index.get(f"{platform}_{cand.media_id}_1")
                            if matched_idx is None:
                                for i, v in enumerate(discovered_video_items):
                                    if cand.media_id and cand.media_id in (v.video_id or ""):
                                        matched_idx = i
                                        break
                                    if cand.video_url and cand.video_url in (v.url or ""):
                                        matched_idx = i
                                        break
                            if matched_idx is not None and matched_idx < len(discovered_video_items):
                                existing_v = discovered_video_items[matched_idx]
                                existing_v.media_type = item_mtype
                                if cand.duration_seconds:
                                    existing_v.duration_seconds = cand.duration_seconds
                                    existing_v.duration = f"{cand.duration_seconds // 60:02d}:{cand.duration_seconds % 60:02d}" if cand.duration_seconds < 3600 else f"{cand.duration_seconds // 3600}:{(cand.duration_seconds % 3600) // 60:02d}:{cand.duration_seconds % 60:02d}"
                                existing_v.extra_metadata["engine"] = EngineType.YTDLP
                                existing_v.extra_metadata["media_type"] = inv_mtype
                            continue

                        # Extract metadata via yt-dlp on individual candidate video URL
                        v_item = self.video_engine.extract_candidate_metadata(
                            candidate=cand,
                            auth_config=auth_config,
                            custom_cookie_file=custom_cookie_file,
                            log_callback=log_callback,
                            is_cancelled=is_cancelled,
                        )

                        seen_media_ids.add(stable_id)
                        if cand.media_id:
                            seen_media_ids.add(cand.media_id)

                        # Upsert post into inventory
                        post_rec = PostRecord(
                            platform=platform,
                            post_id=cand.media_id or stable_id,
                            profile_url=url,
                            original_url=cand.video_url,
                            canonical_url=cand.canonical_webpage_url or cand.video_url,
                            caption=v_item.title,
                            author=v_item.channel_title,
                            post_type="reel" if item_mtype == MediaType.REEL else "video",
                            discovery_source="ProfileVideoDiscoveryEngine",
                            discovery_timestamp=start_time_iso,
                        )
                        self.inventory.upsert_post(post_rec)
                        if post_rec.post_id not in seen_post_ids:
                            seen_post_ids.add(post_rec.post_id)
                            discovered_posts.append(post_rec)

                        # Upsert media item into inventory
                        item_rec = MediaItemRecord(
                            media_id=stable_id,
                            platform=platform,
                            parent_post_id=post_rec.post_id,
                            media_url=cand.video_url,
                            media_type=inv_mtype,
                            media_sequence_index=1,
                            media_count=1,
                            duration=cand.duration_seconds,
                            discovery_source="ProfileVideoDiscoveryEngine",
                            preferred_engine=EngineType.YTDLP,
                            selected_engine=EngineType.YTDLP,
                            download_status="PENDING",
                        )
                        self.inventory.upsert_media_item(item_rec)
                        discovered_media_items.append(item_rec)

                        v_item.index = len(discovered_video_items) + 1
                        media_id_to_index[stable_id] = len(discovered_video_items)
                        if cand.media_id:
                            media_id_to_index[cand.media_id] = len(discovered_video_items)
                        discovered_video_items.append(v_item)

                        if progress_callback:
                            try:
                                progress_callback(len(discovered_posts), len(discovered_media_items), f"Discovered {item_mtype}: {v_item.title[:60]}")
                            except Exception:
                                pass
                else:
                    video_error = f"Platform '{platform}' is not supported by ProfileVideoDiscoveryEngine"
                    if log_callback:
                        log_callback(f"[INFO] {video_error}")

            except Exception as e:
                video_error = str(e)
                if log_callback:
                    log_callback(f"[WARNING] ProfileVideoDiscoveryEngine notice: {e}")

        # =========================================================================
        # Evaluation of Scan Completeness State
        # =========================================================================
        photo_count = len([v for v in discovered_video_items if v.media_type == MediaType.PHOTO])
        video_count = len([v for v in discovered_video_items if v.media_type in (MediaType.VIDEO, MediaType.REEL)])
        total_discovered = len(discovered_video_items)

        if scan_interrupted or (is_cancelled and is_cancelled()):
            scan_status = ScanCompleteness.INTERRUPTED
            completeness_info = f"Scan interrupted by user. Preserved {total_discovered} discovered items ({photo_count} photos, {video_count} videos)."
        elif not is_fb_photo_tab and not is_fb_video_tab and (gallery_timed_out or video_timed_out) and total_discovered > 0:
            scan_status = ScanCompleteness.PARTIAL
            timeout_actor = "gallery-dl and video discovery" if (gallery_timed_out and video_timed_out) else ("gallery-dl" if gallery_timed_out else "video discovery")
            completeness_info = f"Partial scan: {timeout_actor} reached timeout limit, preserved {total_discovered} discovered items ({photo_count} photos, {video_count} videos)."
        elif is_fb_photo_tab and gallery_success:
            scan_status = ScanCompleteness.COMPLETE
            completeness_info = f"Photo enumeration completed successfully ({photo_count} photos)."
        elif is_fb_video_tab and video_success:
            scan_status = ScanCompleteness.COMPLETE
            completeness_info = f"Video and Reel enumeration completed successfully ({video_count} videos/Reels)."
        elif gallery_success and video_success:
            scan_status = ScanCompleteness.COMPLETE
            completeness_info = f"Dual-engine enumeration completed successfully ({photo_count} photos, {video_count} videos/Reels)."
        elif total_discovered > 0:
            scan_status = ScanCompleteness.PARTIAL
            if gallery_success and not video_success:
                v_reason = video_error or "Platform extractor does not support profile-wide video enumeration"
                completeness_info = f"Partial scan: photo discovery succeeded ({photo_count} photos), video discovery notice: {v_reason}. Direct individual video and Reel URLs remain fully supported."
            elif video_success and not gallery_success:
                completeness_info = f"Partial scan: video discovery succeeded ({video_count} videos), photo discovery notice: {gallery_error or 'none'}"
            else:
                completeness_info = f"Partial scan: {total_discovered} media items discovered ({photo_count} photos, {video_count} videos)."
        else:
            scan_status = ScanCompleteness.FAILED
            completeness_info = f"Scan failed to discover media. Errors: gallery-dl ({gallery_error or 'unavailable'}); video discovery ({video_error or 'unavailable'}). Direct individual video and Reel URLs remain fully supported."

        end_time_iso = datetime.now(timezone.utc).isoformat()
        last_error_summary = None
        if scan_status == ScanCompleteness.FAILED:
            last_error_summary = gallery_error or video_error or "Discovery failed"
        elif scan_status == ScanCompleteness.PARTIAL:
            last_error_summary = video_error or gallery_error

        # Update profile summary in persistent inventory
        self.inventory.update_profile_scan_status(
            platform=platform,
            profile_url=url,
            scan_status=scan_status,
            scan_end_time=end_time_iso,
            completeness_info=completeness_info,
            last_error_summary=last_error_summary,
        )

        p_rec = self.inventory.get_profile(platform, url)
        if p_rec:
            p_rec.discovered_posts_count = len(discovered_posts)
            p_rec.discovered_media_count = total_discovered
            self.inventory.upsert_profile(p_rec)

        # Build source title
        source_title = ""
        if discovered_posts and discovered_posts[0].author:
            source_title = discovered_posts[0].author
        elif discovered_video_items and discovered_video_items[0].channel_title:
            source_title = discovered_video_items[0].channel_title
        else:
            source_title = f"{platform.capitalize()} Archive"

        if log_callback:
            log_callback("=" * 64)
            log_callback(
                f"[SCAN RESULT] Status: {scan_status} | Total Media: {total_discovered} "
                f"({photo_count} Photos, {video_count} Videos/Reels) | Posts: {len(discovered_posts)}"
            )
            log_callback(f"[SCAN DETAILS] {completeness_info}")
            log_callback("=" * 64)

        return ScanResult(
            videos=discovered_video_items,
            source_title=source_title,
            source_type="profile_archive",
            platform=platform,
            url=url,
            extra_metadata={
                "scan_id": scan_id,
                "scan_status": scan_status,
                "scan_completeness_info": completeness_info,
                "discovered_posts_count": len(discovered_posts),
                "discovered_media_count": total_discovered,
                "photo_count": photo_count,
                "video_count": video_count,
                "gallerydl_status": "SUCCESS" if gallery_success else ("FAILED" if gallery_attempted else "SKIPPED"),
                "video_discovery_status": "SUCCESS" if video_success else ("FAILED" if video_attempted else "SKIPPED"),
                "ytdlp_status": "SUCCESS" if video_success else ("FAILED" if video_attempted else "SKIPPED"),
                "last_error_summary": last_error_summary,
            },
        )