"""
youtube_formatter.py
Dedicated metadata TXT formatter for YouTube videos.
Preserves existing field structure, layout, and backward compatibility.
Channel Harvest - Multi-Platform Architecture.
"""

from typing import Dict, Any, Optional, List
from metadata.base_formatter import BaseMetadataFormatter


class YouTubeMetadataFormatter(BaseMetadataFormatter):
    """
    Formats YouTube video metadata into the standard Channel Harvest .metadata.txt format.
    Maintains 100% compatibility with existing test fixtures and user archives.
    """

    @property
    def platform_id(self) -> str:
        return "youtube"

    @property
    def platform_display_name(self) -> str:
        return "YouTube"

    def format(self, info: Dict[str, Any], video: Optional[Any] = None) -> str:
        sections: List[str] = []

        # ---------------------------------------------------------------------
        # 1. VIDEO INFORMATION
        # ---------------------------------------------------------------------
        title_val = info.get("title") or (video.title if video else None) or "N/A"
        vid_id_val = info.get("id") or (video.video_id if video else None) or "N/A"
        uploader_val = info.get("uploader") or info.get("channel") or "N/A"
        channel_val = info.get("channel") or info.get("uploader") or (getattr(video, "channel_title", None) if video else None) or "N/A"
        channel_id_val = info.get("channel_id") or info.get("uploader_id") or "N/A"

        if info.get("channel_url"):
            channel_url_val = info["channel_url"]
        elif info.get("uploader_url"):
            channel_url_val = info["uploader_url"]
        elif channel_id_val != "N/A":
            channel_url_val = f"https://www.youtube.com/channel/{channel_id_val}"
        else:
            channel_url_val = "N/A"

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
            or (f"https://www.youtube.com/watch?v={vid_id_val}" if vid_id_val != "N/A" else "N/A")
        )

        video_info_lines = [
            f"Title:\n{title_val}\n",
            f"Video ID:\n{vid_id_val}\n",
            f"Uploader:\n{uploader_val}\n",
            f"Channel:\n{channel_val}\n",
            f"Channel ID:\n{channel_id_val}\n",
            f"Channel URL:\n{channel_url_val}\n",
            f"Upload Date:\n{upload_date_val}\n",
            f"Duration:\n{duration_val}\n",
            f"Webpage URL:\n{webpage_url_val}",
        ]
        sections.append(self.make_section("VIDEO INFORMATION", "\n".join(video_info_lines)))

        # ---------------------------------------------------------------------
        # 2. STATISTICS
        # ---------------------------------------------------------------------
        view_cnt = self.format_number(info.get("view_count"))
        like_cnt = self.format_number(info.get("like_count"))
        comment_cnt = self.format_number(info.get("comment_count"))
        sub_cnt = self.format_number(info.get("channel_follower_count") or info.get("subscriber_count"))

        stats_lines = [
            f"View Count:\n{view_cnt}\n",
            f"Like Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}\n",
            f"Channel Followers:\n{sub_cnt}",
        ]
        sections.append(self.make_section("STATISTICS", "\n".join(stats_lines)))

        # ---------------------------------------------------------------------
        # 3. DESCRIPTION
        # ---------------------------------------------------------------------
        raw_desc = info.get("description")
        desc_text = str(raw_desc).strip() if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        sections.append(self.make_section("DESCRIPTION", desc_text))

        # ---------------------------------------------------------------------
        # 4. TAGS
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
        # 5. CATEGORIES
        # ---------------------------------------------------------------------
        categories = info.get("categories")
        if categories and isinstance(categories, (list, tuple)) and len(categories) > 0:
            cats_text = "\n".join(str(c).strip() for c in categories if str(c).strip())
            if not cats_text:
                cats_text = "None"
        else:
            cats_text = "None"
        sections.append(self.make_section("CATEGORIES", cats_text))

        # ---------------------------------------------------------------------
        # 6. CHAPTERS
        # ---------------------------------------------------------------------
        chapters = info.get("chapters")
        if chapters and isinstance(chapters, (list, tuple)) and len(chapters) > 0:
            chap_lines = []
            for chap in chapters:
                st = chap.get("start_time", 0)
                ts = self.format_duration(st)
                if ts == "N/A":
                    ts = "00:00"
                ct = str(chap.get("title", "")).strip()
                chap_lines.append(f"{ts} {ct}")
            chapters_text = "\n".join(chap_lines)
        else:
            chapters_text = "None"
        sections.append(self.make_section("CHAPTERS", chapters_text))

        # ---------------------------------------------------------------------
        # 7. OTHER INFORMATION
        # ---------------------------------------------------------------------
        other_lines: List[str] = []

        width = info.get("width")
        height = info.get("height")
        res = info.get("resolution") or (f"{width}x{height}" if width and height else None)
        other_lines.append(f"Resolution:\n{res or 'N/A'}\n")

        fps = info.get("fps")
        other_lines.append(f"FPS:\n{fps if fps is not None else 'N/A'}\n")

        vcodec = info.get("vcodec")
        other_lines.append(f"Video Codec:\n{vcodec if (vcodec and vcodec != 'none') else 'N/A'}\n")

        acodec = info.get("acodec")
        other_lines.append(f"Audio Codec:\n{acodec if (acodec and acodec != 'none') else 'N/A'}\n")

        achannels = info.get("audio_channels")
        other_lines.append(f"Audio Channels:\n{achannels if achannels is not None else 'N/A'}\n")

        asr = info.get("asr")
        other_lines.append(f"Audio Sample Rate:\n{f'{asr} Hz' if asr else 'N/A'}\n")

        lang = info.get("language") or info.get("audio_language")
        other_lines.append(f"Audio Language:\n{lang or 'N/A'}\n")

        fmt_id = info.get("format_id")
        if fmt_id:
            other_lines.append(f"Format ID:\n{fmt_id}\n")

        ext = info.get("ext")
        if ext:
            other_lines.append(f"File Extension:\n{ext}\n")

        filesize = info.get("filesize") or info.get("filesize_approx")
        if filesize:
            other_lines.append(f"File Size:\n{self.format_file_size(filesize)}\n")

        license_val = info.get("license")
        other_lines.append(f"License:\n{license_val or 'N/A'}\n")

        age_limit = info.get("age_limit")
        if age_limit is not None:
            age_str = "All ages (0)" if age_limit == 0 else f"{age_limit}+"
        else:
            age_str = "N/A"
        other_lines.append(f"Age Limit:\n{age_str}\n")

        avail = info.get("availability")
        other_lines.append(f"Availability:\n{avail or 'N/A'}\n")

        live_status = info.get("live_status") or ("Live" if info.get("is_live") else "Not live")
        other_lines.append(f"Live Status:\n{live_status}\n")

        # Playlist / Collection Information
        playlist = info.get("playlist_title") or info.get("playlist")
        if playlist:
            other_lines.append(f"Playlist Title:\n{playlist}\n")
            pos = info.get("playlist_index") or info.get("playlist_autonumber")
            if pos is not None:
                other_lines.append(f"Playlist Position:\n{pos}\n")

        extractor = info.get("extractor_key") or info.get("extractor")
        other_lines.append(f"Extractor:\n{extractor or 'YouTube'}\n")

        for key, label in [
            ("track", "Music Track"),
            ("artist", "Music Artist"),
            ("album", "Music Album"),
            ("genre", "Genre"),
            ("release_year", "Release Year"),
            ("release_date", "Release Date"),
            ("creator", "Creator"),
        ]:
            val = info.get(key)
            if val:
                other_lines.append(f"{label}:\n{val}\n")

        sections.append(self.make_section("OTHER INFORMATION", "\n".join(other_lines)))

        return "".join(sections).rstrip() + "\n"
