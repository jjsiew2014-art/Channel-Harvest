"""
rednote_formatter.py
Dedicated metadata TXT formatter for RedNote / XiaoHongShu notes (小红书 图文与视频笔记).
Adheres strictly to RedNote terminology, creator attribution, interaction metrics
(Likes 点赞, Collects 收藏, Comments 评论, Shares 分享), IP location, topics/tags,
media assets, and safe credential scrubbing.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
import re
from metadata.base_formatter import BaseMetadataFormatter


class RedNoteMetadataFormatter(BaseMetadataFormatter):
    """
    Formats RedNote (小红书) video notes, photo notes (图文), and Live Photo metadata
    into a dedicated, platform-appropriate .metadata.txt document.
    """

    @property
    def platform_id(self) -> str:
        return "rednote"

    @property
    def platform_display_name(self) -> str:
        return "RedNote (小红书)"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []
        extra = getattr(video, "extra_metadata", {}) or {}

        # ---------------------------------------------------------------------
        # Helper: Identifiers & Uploader Info
        # ---------------------------------------------------------------------
        note_id = str(
            info.get("id")
            or extra.get("note_id")
            or (video.video_id if video else None)
            or "N/A"
        )

        raw_title = info.get("title") or (video.title if video else None) or ""
        raw_desc = info.get("description") or extra.get("description") or ""

        # Title display (cleaned single-line representation)
        if raw_title:
            title_display = raw_title.splitlines()[0].strip()
        elif raw_desc:
            title_display = raw_desc.splitlines()[0].strip()[:100]
        else:
            title_display = f"RedNote {note_id}"

        # Uploader / Creator details
        creator_name = (
            info.get("uploader")
            or extra.get("uploader")
            or (video.channel_title if video else None)
            or "RedNote Creator"
        )
        user_id = str(
            info.get("uploader_id")
            or extra.get("uploader_id")
            or extra.get("user_id")
            or ""
        )
        red_id = str(
            extra.get("red_id")
            or info.get("red_id")
            or ""
        )

        profile_url = (
            f"https://www.xiaohongshu.com/user/profile/{user_id}"
            if user_id
            else "N/A"
        )

        webpage_url = (
            info.get("webpage_url")
            or (video.url if video else None)
            or f"https://www.xiaohongshu.com/explore/{note_id}"
        )

        # Note type classification
        is_photo = bool(
            extra.get("is_photo")
            or (video and getattr(video, "media_type", None) == "Photo")
            or info.get("media_type") == "PHOTO"
            or extra.get("photo_urls")
        )
        live_photos = extra.get("live_photo_urls") or {}
        if is_photo and live_photos:
            note_type_str = f"Live Photo Note (实况图文, {len(live_photos)} Live Clip(s))"
        elif is_photo:
            photo_cnt = extra.get("photo_count") or (len(extra.get("photo_urls", [])) if extra.get("photo_urls") else 0)
            note_type_str = f"Photo Note (图文笔记, {photo_cnt} Photos)" if photo_cnt else "Photo Note (图文笔记)"
        else:
            note_type_str = "Video Note (视频笔记)"

        # Date / Timestamp
        raw_time = (
            info.get("timestamp")
            or extra.get("upload_timestamp")
            or extra.get("time")
            or info.get("upload_date")
        )
        upload_date_val = self.format_date(raw_time)

        # Duration
        if is_photo:
            p_cnt = extra.get("photo_count") or (len(extra.get("photo_urls", [])) if extra.get("photo_urls") else 0)
            duration_val = f"Photo ({p_cnt}P)" if p_cnt else "Photo"
        else:
            dur_secs = info.get("duration") or (video.duration_seconds if video else None)
            if dur_secs is not None and dur_secs > 0:
                duration_val = self.format_duration(dur_secs)
            elif video and getattr(video, "duration", None) and video.duration not in ("-", "Photo"):
                duration_val = str(video.duration)
            else:
                duration_val = "N/A"

        # IP Location
        ip_location = str(
            extra.get("ip_location")
            or info.get("ip_location")
            or "N/A"
        )

        # ---------------------------------------------------------------------
        # 1. NOTE INFORMATION
        # ---------------------------------------------------------------------
        note_info_lines = [
            f"Title / Headline:\n{title_display}\n",
            f"Note ID:\n{note_id}\n",
            f"Note Type:\n{note_type_str}\n",
        ]

        coll_name = extra.get("collection_name") or info.get("collection_name")
        coll_id = extra.get("collection_id") or info.get("collection_id")
        if coll_name:
            coll_display = f"{coll_name} (ID: {coll_id})" if coll_id else str(coll_name)
            note_info_lines.append(f"Collection / Series (合集专栏):\n{coll_display}\n")

        note_info_lines.extend([
            f"Webpage URL:\n{webpage_url}\n",
            f"Publish Date:\n{upload_date_val}\n",
            f"Duration:\n{duration_val}\n",
            f"IP Location:\n{ip_location}",
        ])
        sections.append(self.make_section("NOTE INFORMATION", "\n".join(note_info_lines)))

        # ---------------------------------------------------------------------
        # 2. CREATOR INFORMATION
        # ---------------------------------------------------------------------
        creator_lines = [
            f"Creator:\n{creator_name}\n",
            f"User ID:\n{user_id or 'N/A'}\n",
            f"Red ID (小红书号):\n{red_id or 'N/A'}\n",
            f"Profile URL:\n{profile_url}",
        ]
        sections.append(self.make_section("CREATOR INFORMATION", "\n".join(creator_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT METRICS
        # ---------------------------------------------------------------------
        liked_val = self.format_number(extra.get("liked_count") or info.get("like_count"))
        collected_val = self.format_number(extra.get("collected_count") or info.get("collect_count"))
        comments_val = self.format_number(extra.get("comment_count") or info.get("comment_count"))
        shares_val = self.format_number(extra.get("share_count") or info.get("share_count"))

        engagement_lines = [
            f"Likes (点赞):\n{liked_val}\n",
            f"Collects (收藏):\n{collected_val}\n",
            f"Comments (评论):\n{comments_val}\n",
            f"Shares (分享):\n{shares_val}",
        ]
        sections.append(self.make_section("ENGAGEMENT METRICS", "\n".join(engagement_lines)))

        # ---------------------------------------------------------------------
        # 4. TOPICS & HASHTAGS
        # ---------------------------------------------------------------------
        tags = list(extra.get("tags") or info.get("tags") or [])
        if raw_desc or raw_title:
            found_hash = re.findall(r"#([^#\s\n\r]+)", f"{raw_title} {raw_desc}")
            for h in found_hash:
                cleaned_h = h.strip()
                if cleaned_h and cleaned_h not in tags:
                    tags.append(cleaned_h)

        if tags:
            tag_lines = [f"- #{t}" for t in tags]
            sections.append(self.make_section("TOPICS & HASHTAGS", "\n".join(tag_lines)))
        else:
            sections.append(self.make_section("TOPICS & HASHTAGS", "None"))

        # ---------------------------------------------------------------------
        # 5. DESCRIPTION & CAPTION
        # ---------------------------------------------------------------------
        desc_content = raw_desc.strip() if raw_desc else "None"
        sections.append(self.make_section("DESCRIPTION & CAPTION", desc_content))

        # ---------------------------------------------------------------------
        # 6. MEDIA ASSETS & TECHNICAL SPECIFICATIONS
        # ---------------------------------------------------------------------
        asset_lines = []
        if is_photo:
            photo_urls = extra.get("photo_urls") or []
            asset_lines.append(f"Photo Count: {len(photo_urls)}")
            if live_photos:
                asset_lines.append(f"Live Photo Clips: {len(live_photos)}")
            if photo_urls:
                asset_lines.append("\nPhoto URLs (CDN):")
                for idx, p_url in enumerate(photo_urls, 1):
                    has_live = " (Live Video Clip attached)" if idx in live_photos else ""
                    asset_lines.append(f"  [{idx:02d}] {p_url}{has_live}")
        else:
            origin_key = extra.get("origin_video_key") or "N/A"
            origin_vurl = extra.get("origin_video_url") or "N/A"
            asset_lines.append(f"Origin Video Key: {origin_key}")
            asset_lines.append(f"Origin Video URL: {origin_vurl}")
            if extra.get("backup_urls"):
                asset_lines.append(f"Backup Streams: {len(extra['backup_urls'])}")

        sections.append(self.make_section("MEDIA ASSETS", "\n".join(asset_lines) if asset_lines else "None"))

        header = self.make_header(f"REDNOTE {('PHOTO' if is_photo else 'VIDEO')} POST METADATA")
        return header + "".join(sections)
