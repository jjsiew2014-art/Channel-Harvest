"""
facebook_formatter.py
Dedicated metadata TXT formatter for Facebook videos and Reels.
Adheres strictly to Facebook terminology, uploader/page attribution,
video types (Standard Video, Reel), metrics, media technical properties,
and safe credential scrubbing.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
import datetime
from metadata.base_formatter import BaseMetadataFormatter


class FacebookMetadataFormatter(BaseMetadataFormatter):
    """
    Formats Facebook video and Reel metadata into a dedicated, platform-appropriate .metadata.txt document.
    Replaces YouTube concepts (Channel, Subscribers) with Facebook concepts (Page, Creator, Reel, Reactions).
    """

    @property
    def platform_id(self) -> str:
        return "facebook"

    @property
    def platform_display_name(self) -> str:
        return "Facebook"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []
        extra = getattr(video, "extra_metadata", {}) or {}

        # ---------------------------------------------------------------------
        # Helper: Resolve Identifiers & Type
        # ---------------------------------------------------------------------
        vid_id = (
            str(info.get("id") or (video.video_id if video else None) or "N/A")
        )
        from core.platform.facebook import clean_facebook_title
        raw_title = info.get("title") or (video.title if video else None) or ""
        raw_desc = info.get("description") or ""

        clean_t = clean_facebook_title(raw_title, fallback="")
        if not clean_t and raw_desc:
            clean_t = clean_facebook_title(raw_desc, fallback="")
        if not clean_t:
            clean_t = (video.title if video else None) or f"Facebook Video {vid_id}"
        title_val = clean_t

        original_url = (
            info.get("original_url")
            or info.get("webpage_url")
            or (video.url if video else None)
            or "N/A"
        )
        canonical_url = (
            info.get("webpage_url")
            or (f"https://www.facebook.com/watch/?v={vid_id}" if vid_id != "N/A" else "N/A")
        )

        is_reel = (
            extra.get("is_reel")
            or "/reel/" in str(original_url).lower()
            or "/reel/" in str(canonical_url).lower()
            or str(info.get("extractor_key", "")).lower() == "facebookreel"
            or str(info.get("extractor", "")).lower() == "facebook:reel"
        )
        video_type = "Facebook Reel" if is_reel else "Standard Video"

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

        language_val = self.sanitize_field(info.get("language"))

        # ---------------------------------------------------------------------
        # 1. BASIC INFORMATION
        # ---------------------------------------------------------------------
        basic_lines = [
            f"Video Title:\n{title_val}\n",
            f"Video ID:\n{vid_id}\n",
            f"Original URL:\n{original_url}\n",
            f"Canonical Video URL:\n{canonical_url}\n",
            f"Video Type:\n{video_type}\n",
            f"Upload Date:\n{upload_date}\n",
            f"Publication Timestamp:\n{pub_time}\n",
            f"Duration:\n{duration_val}\n",
            f"Language:\n{language_val}",
        ]
        sections.append(self.make_section("BASIC INFORMATION", "\n".join(basic_lines)))

        # ---------------------------------------------------------------------
        # 2. PUBLISHER INFORMATION
        # ---------------------------------------------------------------------
        uploader_name = (
            info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or extra.get("uploader")
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )
        uploader_id = (
            info.get("uploader_id")
            or info.get("channel_id")
            or extra.get("uploader_id")
            or "N/A"
        )
        uploader_url = (
            info.get("uploader_url")
            or info.get("channel_url")
            or (f"https://www.facebook.com/{uploader_id}" if uploader_id != "N/A" else "N/A")
        )
        page_name = self.sanitize_field(info.get("channel") or (uploader_name if uploader_name != "N/A" else None))
        page_id = self.sanitize_field(info.get("channel_id") or (uploader_id if uploader_id != "N/A" else None))
        group_info = self.sanitize_field(info.get("group") or extra.get("group"))

        publisher_lines = [
            f"Uploader Display Name:\n{uploader_name}\n",
            f"Uploader ID:\n{uploader_id}\n",
            f"Uploader Profile URL:\n{uploader_url}\n",
            f"Page Name:\n{page_name}\n",
            f"Page ID:\n{page_id}\n",
            f"Source Page or Creator URL:\n{uploader_url}\n",
            f"Group or Collection:\n{group_info}",
        ]
        sections.append(self.make_section("PUBLISHER INFORMATION", "\n".join(publisher_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT STATISTICS
        # ---------------------------------------------------------------------
        view_cnt = self.format_number(info.get("view_count") or extra.get("view_count"))
        like_cnt = self.format_number(info.get("like_count") or extra.get("like_count"))
        comment_cnt = self.format_number(info.get("comment_count") or extra.get("comment_count"))
        share_cnt = self.format_number(info.get("repost_count") or info.get("share_count") or extra.get("repost_count"))

        stats_lines = [
            f"View Count / Play Count:\n{view_cnt}\n",
            f"Like or Reaction Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}\n",
            f"Share Count:\n{share_cnt}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 4. DESCRIPTION / CAPTION
        # ---------------------------------------------------------------------
        desc_text = str(raw_desc).strip() if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        sections.append(self.make_section("DESCRIPTION / CAPTION", desc_text))

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
            f"Actual Downloaded Resolution:\n{res_str}\n",
            f"Width:\n{self.sanitize_field(width)}\n",
            f"Height:\n{self.sanitize_field(height)}\n",
            f"Frame Rate (FPS):\n{fps_val}\n",
            f"Video Codec:\n{vcodec}\n",
            f"Audio Codec:\n{acodec}\n",
            f"Selected Format ID:\n{format_id}\n",
            f"File Extension:\n{ext_val}\n",
            f"Actual File Size:\n{filesize_str}",
        ]
        sections.append(self.make_section("MEDIA INFORMATION", "\n".join(media_lines)))

        # ---------------------------------------------------------------------
        # 6. ADDITIONAL INFORMATION
        # ---------------------------------------------------------------------
        thumbnail_url = self.sanitize_field(info.get("thumbnail") or extra.get("thumbnail"))
        tags_raw = info.get("tags")
        if isinstance(tags_raw, list) and tags_raw:
            tags_str = ", ".join(str(t) for t in tags_raw if t)
        else:
            tags_str = self.sanitize_field(tags_raw)

        subtitles_raw = info.get("subtitles")
        if isinstance(subtitles_raw, dict) and subtitles_raw:
            subs_str = ", ".join(subtitles_raw.keys())
        else:
            subs_str = "None"

        source_title_val = self.sanitize_field(getattr(video, "channel_title", None) or uploader_name)
        source_type_val = self.sanitize_field(video_type)

        add_lines = [
            f"Thumbnail URL:\n{thumbnail_url}\n",
            f"Tags / Hashtags:\n{tags_str}\n",
            f"Subtitle / Caption Languages:\n{subs_str}\n",
            f"Source Title:\n{source_title_val}\n",
            f"Source Type:\n{source_type_val}",
        ]
        sections.append(self.make_section("ADDITIONAL INFORMATION", "\n".join(add_lines)))

        return "\n".join(sections).strip() + "\n"