"""
tiktok_formatter.py
Dedicated metadata TXT formatter for TikTok videos.
Adheres strictly to TikTok terminology, creator attribution, sound/music info,
hashtags, mentions, and engagement metrics.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
import re
from metadata.base_formatter import BaseMetadataFormatter


class TikTokMetadataFormatter(BaseMetadataFormatter):
    """
    Formats TikTok video metadata into a dedicated, platform-appropriate .metadata.txt document.
    Replaces YouTube concepts (Channel, Subscribers) with TikTok concepts (Creator, Handle, Followers).
    """

    @property
    def platform_id(self) -> str:
        return "tiktok"

    @property
    def platform_display_name(self) -> str:
        return "TikTok"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []
        extra = getattr(video, "extra_metadata", {}) or {}

        # ---------------------------------------------------------------------
        # Helper: Extract Creator Handle & URL
        # ---------------------------------------------------------------------
        raw_uploader_id = (
            info.get("uploader_id")
            or extra.get("uploader_id")
            or ""
        )
        raw_uploader = (
            info.get("uploader")
            or extra.get("uploader")
            or ""
        )

        handle = "N/A"
        if raw_uploader_id:
            handle = raw_uploader_id if raw_uploader_id.startswith("@") else f"@{raw_uploader_id}"
        elif raw_uploader:
            handle = raw_uploader if raw_uploader.startswith("@") else f"@{raw_uploader}"

        # Creator Display Name / Nickname
        creator_name = (
            info.get("channel")
            or info.get("creator")
            or (raw_uploader.lstrip("@") if raw_uploader else None)
            or (getattr(video, "channel_title", None) if video else None)
            or "N/A"
        )
        if creator_name.startswith("@") and raw_uploader and not raw_uploader.startswith("@"):
            creator_name = raw_uploader

        creator_id_val = (
            info.get("channel_id")
            or raw_uploader_id.lstrip("@")
            or "N/A"
        )

        if info.get("uploader_url"):
            profile_url = info["uploader_url"]
        elif info.get("channel_url"):
            profile_url = info["channel_url"]
        elif handle != "N/A":
            profile_url = f"https://www.tiktok.com/{handle}"
        else:
            profile_url = "N/A"

        # ---------------------------------------------------------------------
        # 1. VIDEO INFORMATION
        # ---------------------------------------------------------------------
        vid_id_val = info.get("id") or (video.video_id if video else None) or "N/A"

        # TikTok titles are often the first line of the caption
        raw_title = info.get("title") or (video.title if video else None) or ""
        raw_desc = info.get("description") or ""

        if raw_title:
            # Clean single line for title
            title_display = raw_title.splitlines()[0].strip() if raw_title else "N/A"
        elif raw_desc:
            title_display = raw_desc.splitlines()[0].strip()[:100]
        else:
            title_display = "N/A"

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
            or (f"https://www.tiktok.com/{handle}/video/{vid_id_val}" if (handle != "N/A" and vid_id_val != "N/A") else "N/A")
        )

        video_info_lines = [
            f"Title / Caption:\n{title_display}\n",
            f"Video ID:\n{vid_id_val}\n",
            f"Webpage URL:\n{webpage_url_val}\n",
            f"Upload Date:\n{upload_date_val}\n",
            f"Duration:\n{duration_val}",
        ]
        sections.append(self.make_section("VIDEO INFORMATION", "\n".join(video_info_lines)))

        # ---------------------------------------------------------------------
        # 2. CREATOR INFORMATION
        # ---------------------------------------------------------------------
        followers_val = self.format_number(info.get("channel_follower_count") or info.get("subscriber_count"))
        creator_lines = [
            f"Creator:\n{creator_name}\n",
            f"Handle:\n{handle}\n",
            f"Creator ID:\n{creator_id_val}\n",
            f"Profile URL:\n{profile_url}\n",
            f"Followers:\n{followers_val}",
        ]
        sections.append(self.make_section("CREATOR INFORMATION", "\n".join(creator_lines)))

        # ---------------------------------------------------------------------
        # 3. ENGAGEMENT STATISTICS
        # ---------------------------------------------------------------------
        play_cnt = self.format_number(info.get("view_count") if info.get("view_count") is not None else extra.get("view_count"))
        like_cnt = self.format_number(info.get("like_count") if info.get("like_count") is not None else extra.get("like_count"))
        comment_cnt = self.format_number(info.get("comment_count") if info.get("comment_count") is not None else extra.get("comment_count"))
        share_cnt = self.format_number(
            info.get("repost_count")
            if info.get("repost_count") is not None
            else info.get("share_count")
            if info.get("share_count") is not None
            else extra.get("repost_count")
        )
        collect_cnt = self.format_number(
            info.get("save_count")
            if info.get("save_count") is not None
            else info.get("collect_count")
            if info.get("collect_count") is not None
            else info.get("favorite_count")
        )

        stats_lines = [
            f"Play Count:\n{play_cnt}\n",
            f"Like Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}\n",
            f"Share Count:\n{share_cnt}\n",
            f"Collect Count:\n{collect_cnt}",
        ]
        sections.append(self.make_section("ENGAGEMENT STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 4. TIKTOK CONTENT & SOUND
        # ---------------------------------------------------------------------
        music_info = info.get("music_info") if isinstance(info.get("music_info"), dict) else {}

        music_title = (
            info.get("track")
            or info.get("alt_title")
            or music_info.get("title")
            or extra.get("track")
            or "N/A"
        )
        music_author = (
            info.get("artist")
            or (", ".join(str(a) for a in info["artists"]) if isinstance(info.get("artists"), list) else None)
            or music_info.get("author")
            or extra.get("artist")
            or "N/A"
        )
        music_album = info.get("album") or music_info.get("album") or "N/A"
        sound_dur = music_info.get("duration") or info.get("sound_duration")
        sound_dur_val = self.format_duration(sound_dur) if sound_dur is not None else "N/A"

        is_orig = music_info.get("original")
        if is_orig is True:
            orig_sound_val = "Yes"
        elif is_orig is False:
            orig_sound_val = "No"
        elif "original sound" in str(music_title).lower():
            orig_sound_val = "Yes"
        else:
            orig_sound_val = "N/A"

        # Hashtags Extraction: from tags list or regex on description
        tags = info.get("tags")
        hashtags_list: List[str] = []
        if tags and isinstance(tags, (list, tuple)):
            for t in tags:
                tag_str = str(t).strip()
                if tag_str:
                    hashtags_list.append(tag_str if tag_str.startswith("#") else f"#{tag_str}")

        if not hashtags_list and raw_desc:
            found_tags = re.findall(r"#([\w\u4e00-\u9fff]+)", raw_desc)
            for ft in found_tags:
                ft_str = f"#{ft}"
                if ft_str not in hashtags_list:
                    hashtags_list.append(ft_str)

        hashtags_display = ", ".join(hashtags_list) if hashtags_list else "None"

        # Mentions Extraction: regex @user from description
        mentions_list: List[str] = []
        if raw_desc:
            found_mentions = re.findall(r"@([a-zA-Z0-9_.-]+)", raw_desc)
            for fm in found_mentions:
                fm_str = f"@{fm}"
                if fm_str not in mentions_list and fm_str != handle:
                    mentions_list.append(fm_str)

        mentions_display = ", ".join(mentions_list) if mentions_list else "None"

        sound_lines = [
            f"Sound Title:\n{music_title}\n",
            f"Sound Artist:\n{music_author}\n",
            f"Sound Album:\n{music_album}\n",
            f"Sound Duration:\n{sound_dur_val}\n",
            f"Original Sound:\n{orig_sound_val}\n",
            f"Hashtags:\n{hashtags_display}\n",
            f"Mentions:\n{mentions_display}",
        ]
        sections.append(self.make_section("TIKTOK CONTENT & SOUND", "\n".join(sound_lines)))

        # ---------------------------------------------------------------------
        # 5. TECHNICAL & DOWNLOAD INFORMATION
        # ---------------------------------------------------------------------
        width = info.get("width")
        height = info.get("height")
        res = info.get("resolution") or (f"{width}x{height}" if width and height else None)

        fps = info.get("fps")
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        ext = info.get("ext")
        filesize = info.get("filesize") or info.get("filesize_approx")
        extractor = info.get("extractor_key") or info.get("extractor") or "TikTok"

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
        # 6. DESCRIPTION / CAPTION
        # ---------------------------------------------------------------------
        desc_text = str(raw_desc).strip() if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        sections.append(self.make_section("DESCRIPTION", desc_text))

        return "".join(sections).rstrip() + "\n"
