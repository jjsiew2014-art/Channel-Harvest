"""
bilibili_formatter.py
Dedicated metadata TXT formatter for Bilibili videos (哔哩哔哩, 中国大陆版).
Handles Bilibili identifiers (BVID, AID, CID), multi-part videos (分 P),
UP space attribution, Bilibili-specific engagement metrics (Coins 投币, Danmaku 弹幕),
and categories.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
from metadata.base_formatter import BaseMetadataFormatter


class BilibiliMetadataFormatter(BaseMetadataFormatter):
    """
    Formats Bilibili video metadata into a dedicated, platform-appropriate .metadata.txt document.
    Replaces YouTube concepts (Channel, Subscribers) with Bilibili concepts (Uploader, MID, Space URL, Followers).
    """

    @property
    def platform_id(self) -> str:
        return "bilibili"

    @property
    def platform_display_name(self) -> str:
        return "Bilibili"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []
        extra = getattr(video, "extra_metadata", {}) or {}

        # ---------------------------------------------------------------------
        # Helper: Extract Identifiers & Uploader
        # ---------------------------------------------------------------------
        # BVID resolution
        raw_bvid = (
            info.get("bvid")
            or extra.get("bvid")
            or (info.get("id") if str(info.get("id", "")).startswith("BV") else None)
            or (video.video_id.split("_p")[0] if (video and str(video.video_id).startswith("BV")) else None)
            or "N/A"
        )

        # AID resolution
        raw_aid = (
            info.get("aid")
            or extra.get("aid")
            or (info.get("id") if (info.get("id") and str(info.get("id")).isdigit()) else None)
            or "N/A"
        )
        if raw_aid != "N/A":
            aid_str = f"av{raw_aid}" if not str(raw_aid).lower().startswith("av") else str(raw_aid)
        else:
            aid_str = "N/A"

        # CID resolution
        raw_cid = (
            info.get("cid")
            or extra.get("cid")
            or "N/A"
        )

        # Multi-part video attributes
        part_num = (
            extra.get("part_number")
            or info.get("page")
            or info.get("part_number")
            or info.get("playlist_index")
        )
        part_num_str = f"P{part_num}" if part_num is not None else "N/A"

        part_title = (
            extra.get("part_title")
            or info.get("part")
            or info.get("part_title")
            or "N/A"
        )

        total_parts = (
            extra.get("total_parts")
            or info.get("total_parts")
            or (len(info["pages"]) if isinstance(info.get("pages"), list) else None)
        )
        total_parts_str = str(total_parts) if total_parts is not None else "N/A"

        # Uploader details
        uploader_name = (
            info.get("uploader")
            or info.get("author")
            or extra.get("uploader")
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )

        uploader_mid = (
            info.get("uploader_id")
            or info.get("mid")
            or extra.get("uploader_id")
            or "N/A"
        )

        if info.get("uploader_url"):
            space_url = info["uploader_url"]
        elif uploader_mid != "N/A":
            space_url = f"https://space.bilibili.com/{uploader_mid}"
        else:
            space_url = "N/A"

        # ---------------------------------------------------------------------
        # 1. BASIC VIDEO INFORMATION
        # ---------------------------------------------------------------------
        title_val = info.get("title") or (video.title if video else None) or "N/A"

        upload_date_val = self.format_date(
            info.get("upload_date")
            or info.get("pubdate")
            or info.get("timestamp")
        )

        raw_dur = info.get("duration")
        if raw_dur is not None:
            duration_val = self.format_duration(raw_dur)
        elif video and getattr(video, "duration_seconds", None) is not None:
            duration_val = self.format_duration(video.duration_seconds)
        elif video and getattr(video, "duration", None):
            duration_val = str(video.duration)
        else:
            duration_val = "N/A"

        # Webpage URL
        if info.get("webpage_url"):
            webpage_url_val = info["webpage_url"]
        elif video and video.url:
            webpage_url_val = video.url
        elif raw_bvid != "N/A":
            if part_num is not None and str(part_num) not in ("1", "P1"):
                webpage_url_val = f"https://www.bilibili.com/video/{raw_bvid}?p={part_num}"
            else:
                webpage_url_val = f"https://www.bilibili.com/video/{raw_bvid}"
        else:
            webpage_url_val = "N/A"

        video_info_lines = [
            f"Title:\n{title_val}\n",
            f"BVID:\n{raw_bvid}\n",
            f"AID:\n{aid_str}\n",
            f"Webpage URL:\n{webpage_url_val}\n",
            f"Upload Date:\n{upload_date_val}\n",
            f"Duration:\n{duration_val}",
        ]
        sections.append(self.make_section("BASIC VIDEO INFORMATION", "\n".join(video_info_lines)))

        # ---------------------------------------------------------------------
        # 2. UPLOADER INFORMATION
        # ---------------------------------------------------------------------
        followers_val = self.format_number(
            info.get("channel_follower_count")
            or info.get("follower_count")
            or info.get("subscriber_count")
        )

        uploader_lines = [
            f"Uploader (UP主):\n{uploader_name}\n",
            f"MID:\n{uploader_mid}\n",
            f"Space URL:\n{space_url}\n",
            f"Followers:\n{followers_val}",
        ]
        sections.append(self.make_section("UPLOADER INFORMATION", "\n".join(uploader_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT STATISTICS
        # ---------------------------------------------------------------------
        view_cnt = self.format_number(info.get("view_count") if info.get("view_count") is not None else extra.get("view_count"))
        like_cnt = self.format_number(info.get("like_count") if info.get("like_count") is not None else extra.get("like_count"))
        coin_cnt = self.format_number(
            info.get("coin_count")
            if info.get("coin_count") is not None
            else info.get("coins")
            if info.get("coins") is not None
            else extra.get("coin_count")
        )
        favorite_cnt = self.format_number(
            info.get("favorite_count")
            if info.get("favorite_count") is not None
            else info.get("favorites")
            if info.get("favorites") is not None
            else extra.get("favorite_count")
        )
        share_cnt = self.format_number(
            info.get("share_count")
            if info.get("share_count") is not None
            else info.get("shares")
            if info.get("shares") is not None
            else extra.get("share_count")
        )
        comment_cnt = self.format_number(
            info.get("comment_count")
            if info.get("comment_count") is not None
            else info.get("comments")
            if info.get("comments") is not None
            else extra.get("comment_count")
        )
        danmaku_cnt = self.format_number(
            info.get("danmaku_count")
            if info.get("danmaku_count") is not None
            else info.get("danmaku")
            if info.get("danmaku") is not None
            else extra.get("danmaku_count")
        )

        stats_lines = [
            f"View Count (播放量):\n{view_cnt}\n",
            f"Like Count (点赞):\n{like_cnt}\n",
            f"Coin Count (投币):\n{coin_cnt}\n",
            f"Favorite Count (收藏):\n{favorite_cnt}\n",
            f"Share Count (分享):\n{share_cnt}\n",
            f"Comment Count (评论):\n{comment_cnt}\n",
            f"Danmaku Count (弹幕):\n{danmaku_cnt}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 4. BILIBILI VIDEO DETAILS
        # ---------------------------------------------------------------------
        category_val = (
            info.get("category")
            or info.get("tname")
            or (", ".join(str(c) for c in info["categories"]) if isinstance(info.get("categories"), list) else None)
            or "N/A"
        )
        subcategory_val = info.get("subcategory") or info.get("tag") or "N/A"

        # Copyright formatting
        raw_copyright = info.get("copyright")
        if raw_copyright in (1, "1"):
            copyright_val = "Original (自制)"
        elif raw_copyright in (2, "2"):
            copyright_val = "Repost (转载)"
        elif raw_copyright:
            copyright_val = str(raw_copyright)
        else:
            copyright_val = "N/A"

        details_lines = [
            f"Part Number (分P序号):\n{part_num_str}\n",
            f"Part Title (分P标题):\n{part_title}\n",
            f"CID:\n{raw_cid}\n",
            f"Total Parts (总P数):\n{total_parts_str}\n",
            f"Category (主分区):\n{category_val}\n",
            f"Subcategory (子分区):\n{subcategory_val}\n",
            f"Copyright (版权):\n{copyright_val}",
        ]
        sections.append(self.make_section("BILIBILI VIDEO DETAILS", "\n".join(details_lines)))

        # ---------------------------------------------------------------------
        # 5. SOURCE & COLLECTION INFORMATION
        # ---------------------------------------------------------------------
        season_title = (
            info.get("season_title")
            or info.get("series")
            or "N/A"
        )
        season_id = (
            info.get("season_id")
            or info.get("series_id")
            or "N/A"
        )
        collection_title = (
            info.get("collection")
            or info.get("playlist_title")
            or info.get("playlist")
            or "N/A"
        )

        collection_lines = [
            f"Season / Series Title:\n{season_title}\n",
            f"Season / Series ID:\n{season_id}\n",
            f"Collection / Playlist:\n{collection_title}",
        ]
        sections.append(self.make_section("SOURCE & COLLECTION INFORMATION", "\n".join(collection_lines)))

        # ---------------------------------------------------------------------
        # 6. TECHNICAL & DOWNLOAD INFORMATION
        # ---------------------------------------------------------------------
        width = info.get("width")
        height = info.get("height")
        res = info.get("resolution") or (f"{width}x{height}" if width and height else None)

        fps = info.get("fps")
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        ext = info.get("ext")
        filesize = info.get("filesize") or info.get("filesize_approx")
        extractor = info.get("extractor_key") or info.get("extractor") or "Bilibili"

        tech_lines = [
            f"Resolution:\n{res or 'N/A'}\n",
            f"FPS:\n{fps if fps is not None else 'N/A'}\n",
            f"Video Codec:\n{vcodec if (vcodec and vcodec != 'none') else 'N/A'}\n",
            f"Audio Codec:\n{acodec if (acodec and acodec != 'none') else 'N/A'}\n",
            f"File Extension:\n{ext or 'N/A'}\n",
            f"File Size:\n{self.format_file_size(filesize)}\n",
            f"Extractor:\n{extractor}",
        ]
        sections.append(self.make_section("TECHNICAL & DOWNLOAD INFORMATION", "\n".join(tech_lines)))

        # ---------------------------------------------------------------------
        # 7. DESCRIPTION
        # ---------------------------------------------------------------------
        raw_desc = info.get("description")
        desc_text = str(raw_desc).strip() if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        sections.append(self.make_section("DESCRIPTION", desc_text))

        return "".join(sections).rstrip() + "\n"
