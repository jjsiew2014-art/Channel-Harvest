"""
instagram_formatter.py
Dedicated metadata TXT formatter for Instagram Reels, standard video posts, and Carousel items.
Adheres strictly to Instagram terminology, account attribution, media types,
captions, hashtags, mentions, technical properties, and safe credential scrubbing.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
import datetime
import re
from metadata.base_formatter import BaseMetadataFormatter


class InstagramMetadataFormatter(BaseMetadataFormatter):
    """
    Formats Instagram video, Reel, and Carousel item metadata into a dedicated,
    platform-appropriate .metadata.txt document.
    """

    @property
    def platform_id(self) -> str:
        return "instagram"

    @property
    def platform_display_name(self) -> str:
        return "Instagram"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []
        extra = getattr(video, "extra_metadata", {}) or {}

        # ---------------------------------------------------------------------
        # Helper: Identifiers & Type
        # ---------------------------------------------------------------------
        vid_id = str(info.get("id") or (video.video_id if video else None) or "N/A")
        raw_title = info.get("title") or (video.title if video else None) or ""
        raw_caption = info.get("description") or extra.get("caption") or ""

        fallback_t = ""
        if video and getattr(video, "title", None) and not str(video.title).lower().startswith(("video by ", "post by ")):
            fallback_t = video.title
        elif vid_id != "N/A":
            fallback_t = f"Instagram Media {vid_id}"

        from core.platform.instagram import clean_instagram_title
        clean_t = clean_instagram_title(raw_title, caption=raw_caption, fallback=fallback_t)
        if not clean_t:
            clean_t = fallback_t or f"Instagram Media {vid_id}"
        title_val = clean_t

        original_url = (
            info.get("original_url")
            or info.get("webpage_url")
            or (video.url if video else None)
            or "N/A"
        )
        canonical_url = (
            info.get("webpage_url")
            or (f"https://www.instagram.com/p/{vid_id}/" if vid_id != "N/A" else "N/A")
        )

        is_carousel = extra.get("is_carousel") or ("parent_id" in extra and bool(extra.get("parent_id")))
        parent_url = extra.get("parent_url") or "N/A"
        parent_id = extra.get("parent_id") or "N/A"
        carousel_idx = extra.get("carousel_index")

        is_reel = (
            extra.get("is_reel")
            or "/reel/" in str(original_url).lower()
            or "/reel/" in str(canonical_url).lower()
            or str(info.get("extractor_key", "")).lower() == "instagramreel"
        )

        if is_carousel:
            media_type = f"Instagram Carousel Item (Item {carousel_idx})" if carousel_idx else "Instagram Carousel Item"
        elif is_reel:
            media_type = "Instagram Reel"
        else:
            media_type = "Standard Video Post"

        upload_date = self.format_date(info.get("upload_date") or extra.get("upload_date") or info.get("timestamp"))

        # Publication timestamp
        ts_raw = info.get("timestamp") or extra.get("timestamp")
        if isinstance(ts_raw, (int, float)) and ts_raw > 0:
            try:
                pub_time = datetime.datetime.fromtimestamp(ts_raw, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                pub_time = str(ts_raw)
        else:
            pub_time = "N/A"

        # Duration
        raw_dur = info.get("duration") or (video.duration_seconds if video else None)
        if raw_dur is not None:
            duration_val = self.format_duration(raw_dur)
        elif video and getattr(video, "duration", None):
            duration_val = str(video.duration)
        else:
            duration_val = "N/A"

        # ---------------------------------------------------------------------
        # 1. BASIC INFORMATION
        # ---------------------------------------------------------------------
        basic_lines = [
            f"Platform:\nInstagram\n",
            f"Media Title:\n{title_val}\n",
            f"Media ID:\n{vid_id}\n",
            f"Media Type:\n{media_type}\n",
            f"Original URL:\n{original_url}\n",
            f"Canonical URL:\n{canonical_url}\n",
        ]
        if is_carousel and parent_url != "N/A":
            basic_lines.append(f"Parent Post URL:\n{parent_url}\n")
            basic_lines.append(f"Parent Post ID:\n{parent_id}\n")
            if carousel_idx is not None:
                basic_lines.append(f"Carousel Item Index:\n{carousel_idx}\n")

        basic_lines.extend([
            f"Upload Date:\n{upload_date}\n",
            f"Publication Timestamp:\n{pub_time}\n",
            f"Duration:\n{duration_val}",
        ])
        sections.append(self.make_section("BASIC INFORMATION", "\n".join(basic_lines)))

        # ---------------------------------------------------------------------
        # 2. ACCOUNT / CREATOR INFORMATION
        # ---------------------------------------------------------------------
        username = (
            info.get("channel")
            or info.get("uploader_id")
            or extra.get("uploader")
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )
        display_name = info.get("uploader") or username or "N/A"
        uploader_id = info.get("uploader_id") or "N/A"
        profile_url = f"https://www.instagram.com/{username}/" if username != "N/A" else "N/A"

        account_lines = [
            f"Username:\n@{username if username != 'N/A' else 'N/A'}\n",
            f"Display Name:\n{display_name}\n",
            f"User ID / PK:\n{uploader_id}\n",
            f"Profile URL:\n{profile_url}",
        ]
        sections.append(self.make_section("ACCOUNT INFORMATION", "\n".join(account_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT STATISTICS
        # ---------------------------------------------------------------------
        like_cnt = self.format_number(info.get("like_count") or extra.get("like_count"))
        comment_cnt = self.format_number(info.get("comment_count") or extra.get("comment_count"))
        view_cnt = self.format_number(info.get("view_count") or info.get("play_count"))

        stats_lines = [
            f"Like Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}\n",
            f"View / Play Count:\n{view_cnt}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 4. CAPTION & HASHTAGS
        # ---------------------------------------------------------------------
        caption_text = str(raw_caption).strip() if (raw_caption is not None and str(raw_caption).strip()) else "N/A"

        # Extract hashtags and mentions from caption
        hashtags = re.findall(r"#([^\s#]+)", caption_text) if caption_text != "N/A" else []
        mentions = re.findall(r"@([^\s@]+)", caption_text) if caption_text != "N/A" else []

        caption_lines = [
            f"Caption:\n{caption_text}\n",
            f"Hashtags:\n{', '.join('#' + h for h in hashtags) if hashtags else 'None'}\n",
            f"Mentions:\n{', '.join('@' + m for m in mentions) if mentions else 'None'}",
        ]
        sections.append(self.make_section("CAPTION & TAGS", "\n".join(caption_lines)))

        # ---------------------------------------------------------------------
        # 5. MEDIA TECHNICAL INFORMATION
        # ---------------------------------------------------------------------
        width = info.get("width")
        height = info.get("height")
        if width and height:
            res_str = f"{width}x{height}"
        elif height:
            res_str = f"{height}p"
        else:
            res_str = "N/A"

        fps_val = self.sanitize_field(info.get("fps"))
        vcodec = self.sanitize_field(info.get("vcodec"))
        acodec = self.sanitize_field(info.get("acodec"))
        format_id = self.sanitize_field(info.get("format_id"))
        ext_val = self.sanitize_field(info.get("ext"))

        filesize_raw = info.get("filesize") or info.get("filesize_approx")
        filesize_str = self.format_file_size(filesize_raw)

        media_lines = [
            f"Resolution:\n{res_str}\n",
            f"Width:\n{self.sanitize_field(width)}\n",
            f"Height:\n{self.sanitize_field(height)}\n",
            f"Frame Rate (FPS):\n{fps_val}\n",
            f"Video Codec:\n{vcodec}\n",
            f"Audio Codec:\n{acodec}\n",
            f"Format ID:\n{format_id}\n",
            f"File Extension:\n{ext_val}\n",
            f"File Size:\n{filesize_str}",
        ]
        sections.append(self.make_section("MEDIA TECHNICAL INFORMATION", "\n".join(media_lines)))

        # ---------------------------------------------------------------------
        # 6. DOWNLOAD & AVAILABILITY
        # ---------------------------------------------------------------------
        avail_obj = getattr(video, "availability", None)
        avail_status = avail_obj.status.value if avail_obj else "AVAILABLE"

        thumbnail_url = self.sanitize_field(info.get("thumbnail") or extra.get("thumbnail"))
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        add_lines = [
            f"Availability Status:\n{avail_status}\n",
            f"Thumbnail URL:\n{thumbnail_url}\n",
            f"Metadata Export Timestamp:\n{now_str}",
        ]
        sections.append(self.make_section("EXPORT & AVAILABILITY", "\n".join(add_lines)))

        # ---------------------------------------------------------------------
        # Assemble complete document
        # ---------------------------------------------------------------------
        return "\n".join(sections).strip() + "\n"
