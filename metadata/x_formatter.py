"""
x_formatter.py
Dedicated metadata TXT formatter for X (Twitter) video posts and multi-media items.
Adheres strictly to X terminology, account attribution, media indexing,
post text, hashtags, mentions, engagement metrics, technical properties, and safe credential scrubbing.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
import datetime
import re
from metadata.base_formatter import BaseMetadataFormatter


class XMetadataFormatter(BaseMetadataFormatter):
    """
    Formats X (Twitter) video post and multi-media item metadata into a dedicated,
    platform-appropriate .metadata.txt document.
    """

    @property
    def platform_id(self) -> str:
        return "x"

    @property
    def platform_display_name(self) -> str:
        return "X (Twitter)"

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
        if video and getattr(video, "title", None):
            fallback_t = video.title
        elif vid_id != "N/A":
            fallback_t = f"X Post {vid_id}"

        from core.platform.x import clean_x_title
        clean_t = clean_x_title(raw_title, caption=raw_caption, fallback=fallback_t)
        if not clean_t:
            clean_t = fallback_t or f"X Video {vid_id}"
        title_val = clean_t

        original_url = (
            info.get("original_url")
            or info.get("webpage_url")
            or (video.url if video else None)
            or "N/A"
        )
        canonical_url = (
            info.get("webpage_url")
            or (f"https://x.com/i/status/{vid_id}" if vid_id != "N/A" else "N/A")
        )

        is_multi_media = extra.get("is_multi_media") or ("parent_id" in extra and bool(extra.get("parent_id")))
        parent_url = extra.get("parent_url") or "N/A"
        parent_id = extra.get("parent_id") or "N/A"
        media_idx = extra.get("media_index")
        media_count = extra.get("media_count")

        if is_multi_media:
            if media_idx and media_count:
                media_type = f"X Multi-Media Video Post (Part {media_idx} of {media_count})"
            elif media_idx:
                media_type = f"X Multi-Media Video Post (Part {media_idx})"
            else:
                media_type = "X Multi-Media Video Post"
        else:
            media_type = "X Video Post"

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
            f"Platform:\nX (Twitter)\n",
            f"Post Title:\n{title_val}\n",
            f"Post ID:\n{parent_id if is_multi_media and parent_id != 'N/A' else vid_id}\n",
            f"Media Item ID:\n{vid_id}\n",
            f"Media Type:\n{media_type}\n",
            f"Original URL:\n{original_url}\n",
            f"Canonical URL:\n{canonical_url}\n",
        ]
        if is_multi_media and parent_url != "N/A":
            basic_lines.append(f"Parent Post URL:\n{parent_url}\n")
            if media_idx is not None:
                basic_lines.append(f"Media Index:\n{media_idx}\n")
            if media_count is not None:
                basic_lines.append(f"Media Total Count:\n{media_count}\n")

        basic_lines.extend([
            f"Upload Date:\n{upload_date}\n",
            f"Publication Timestamp:\n{pub_time}\n",
            f"Duration:\n{duration_val}",
        ])
        sections.append(self.make_section("BASIC INFORMATION", "\n".join(basic_lines)))

        # ---------------------------------------------------------------------
        # 2. ACCOUNT / AUTHOR INFORMATION
        # ---------------------------------------------------------------------
        username = (
            info.get("uploader_id")
            or info.get("channel")
            or extra.get("uploader_id")
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )
        display_name = info.get("uploader") or extra.get("uploader") or username or "N/A"
        user_id = str(info.get("channel_id") or "N/A")
        profile_url = f"https://x.com/{username}" if username != "N/A" else "N/A"

        account_lines = [
            f"Author Username:\n@{username if username != 'N/A' else 'N/A'}\n",
            f"Author Display Name:\n{display_name}\n",
            f"Author User ID:\n{user_id}\n",
            f"Profile URL:\n{profile_url}",
        ]
        sections.append(self.make_section("ACCOUNT INFORMATION", "\n".join(account_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT STATISTICS (Never fabricate missing values)
        # ---------------------------------------------------------------------
        view_raw = info.get("view_count") or extra.get("view_count")
        like_raw = info.get("like_count") or extra.get("like_count")
        repost_raw = info.get("repost_count") or extra.get("repost_count")
        reply_raw = info.get("comment_count") or extra.get("comment_count")
        quote_raw = info.get("quote_count") or extra.get("quote_count")

        stats_lines = [
            f"View Count:\n{self.format_number(view_raw)}\n",
            f"Like Count:\n{self.format_number(like_raw)}\n",
            f"Repost Count (Retweets):\n{self.format_number(repost_raw)}\n",
            f"Reply Count:\n{self.format_number(reply_raw)}\n",
            f"Quote Count:\n{self.format_number(quote_raw)}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 4. POST TEXT & TAGS
        # ---------------------------------------------------------------------
        post_text = str(raw_caption).strip() if (raw_caption is not None and str(raw_caption).strip()) else "N/A"

        # Extract hashtags and mentions
        hashtags = info.get("tags") or []
        if not hashtags and post_text != "N/A":
            hashtags = re.findall(r"#([^\s#]+)", post_text)
        mentions = re.findall(r"@([a-zA-Z0-9_]+)", post_text) if post_text != "N/A" else []

        text_lines = [
            f"Post Text:\n{post_text}\n",
            f"Hashtags:\n{', '.join('#' + str(h) for h in hashtags) if hashtags else 'None'}\n",
            f"Mentioned Users:\n{', '.join('@' + str(m) for m in mentions) if mentions else 'None'}",
        ]
        sections.append(self.make_section("POST TEXT & TAGS", "\n".join(text_lines)))

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
        # 6. EXPORT & AVAILABILITY
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

        return "\n".join(sections).strip() + "\n"
