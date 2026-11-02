"""
generic_formatter.py
Generic fallback metadata TXT formatter for unrecognized or custom platforms.
Does not use platform-specific terminology.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
from metadata.base_formatter import BaseMetadataFormatter


class GenericMetadataFormatter(BaseMetadataFormatter):
    """
    Fallback metadata formatter used when video platform is unknown or unsupported.
    Provides standard neutral video details, creator info, basic stats, and technical attributes.
    """

    @property
    def platform_id(self) -> str:
        return "generic"

    @property
    def platform_display_name(self) -> str:
        return "Generic Video"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []

        # ---------------------------------------------------------------------
        # 1. MEDIA INFORMATION
        # ---------------------------------------------------------------------
        title_val = info.get("title") or (video.title if video else None) or "N/A"
        vid_id_val = info.get("id") or (video.video_id if video else None) or "N/A"
        creator_val = (
            info.get("uploader")
            or info.get("creator")
            or info.get("channel")
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )
        creator_url_val = (
            info.get("uploader_url")
            or info.get("channel_url")
            or "N/A"
        )
        upload_date_val = self.format_date(info.get("upload_date") or info.get("timestamp"))

        raw_dur = info.get("duration")
        if raw_dur is not None:
            duration_val = self.format_duration(raw_dur)
        elif video and getattr(video, "duration_seconds", None) is not None:
            duration_val = self.format_duration(video.duration_seconds)
        elif video and getattr(video, "duration", None):
            duration_val = str(video.duration)
        else:
            duration_val = "N/A"

        webpage_url_val = (
            info.get("webpage_url")
            or info.get("original_url")
            or (video.url if video else None)
            or "N/A"
        )

        media_info_lines = [
            f"Title:\n{title_val}\n",
            f"Media ID:\n{vid_id_val}\n",
            f"Creator / Uploader:\n{creator_val}\n",
            f"Creator URL:\n{creator_url_val}\n",
            f"Release Date:\n{upload_date_val}\n",
            f"Duration:\n{duration_val}\n",
            f"Webpage URL:\n{webpage_url_val}",
        ]
        sections.append(self.make_section("MEDIA INFORMATION", "\n".join(media_info_lines)))

        # ---------------------------------------------------------------------
        # 2. ENGAGEMENT STATISTICS
        # ---------------------------------------------------------------------
        view_cnt = self.format_number(info.get("view_count"))
        like_cnt = self.format_number(info.get("like_count"))
        comment_cnt = self.format_number(info.get("comment_count"))

        stats_lines = [
            f"View Count:\n{view_cnt}\n",
            f"Like Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 3. DESCRIPTION
        # ---------------------------------------------------------------------
        raw_desc = info.get("description")
        desc_text = str(raw_desc).strip() if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        sections.append(self.make_section("DESCRIPTION", desc_text))

        # ---------------------------------------------------------------------
        # 4. TAGS / KEYWORDS
        # ---------------------------------------------------------------------
        tags = info.get("tags")
        if tags and isinstance(tags, (list, tuple)) and len(tags) > 0:
            tags_text = "\n".join(str(t).strip() for t in tags if str(t).strip())
            if not tags_text:
                tags_text = "None"
        else:
            tags_text = "None"
        sections.append(self.make_section("TAGS", tags_text))

        # ---------------------------------------------------------------------
        # 5. TECHNICAL INFORMATION
        # ---------------------------------------------------------------------
        width = info.get("width")
        height = info.get("height")
        res = info.get("resolution") or (f"{width}x{height}" if width and height else None)

        fps = info.get("fps")
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        ext = info.get("ext")
        filesize = info.get("filesize") or info.get("filesize_approx")
        extractor = info.get("extractor_key") or info.get("extractor") or "Generic"

        tech_lines = [
            f"Resolution:\n{res or 'N/A'}\n",
            f"FPS:\n{fps if fps is not None else 'N/A'}\n",
            f"Video Codec:\n{vcodec if (vcodec and vcodec != 'none') else 'N/A'}\n",
            f"Audio Codec:\n{acodec if (acodec and acodec != 'none') else 'N/A'}\n",
            f"File Extension:\n{ext or 'N/A'}\n",
            f"File Size:\n{self.format_file_size(filesize)}\n",
            f"Extractor:\n{extractor}",
        ]
        sections.append(self.make_section("TECHNICAL INFORMATION", "\n".join(tech_lines)))

        return "".join(sections).rstrip() + "\n"
