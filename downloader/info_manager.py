"""
info_manager.py
YouTube video information extractor and archiver for Channel Harvest.

Handles:
- Video Description extraction preserving original text, line breaks, and Unicode (.description).
- Comprehensive structured video metadata extraction (.metadata.txt).
- Human-readable timestamped chapter list generation (.chapters.txt).
- Single-pass extraction efficiency (one yt-dlp call retrieves all requested info assets).
- Independent disk verification to fetch missing info without re-downloading media.
- Non-fatal error isolation to ensure batch queue continuity.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Tuple, Optional, Callable, Any, List

import yt_dlp

from core.models import VideoItem, DownloadSettings
from core.paths import resolve_media_filename, sanitize_filename, get_temp_dir
from downloader.ytdlp_engine import YtDlpEngine


class InfoManager:
    """
    Manages YouTube Description, Metadata, and Chapters archival extraction.
    """

    @classmethod
    def sanitize_title(cls, title: str) -> str:
        """Removes filesystem-invalid characters while preserving Unicode/Chinese characters."""
        return re.sub(r'[\\/*?:"<>|]', "_", title).strip()

    @classmethod
    def format_timestamp(cls, seconds: Optional[float]) -> str:
        """Formats seconds into standardized HH:MM:SS timestamp."""
        if seconds is None:
            return "00:00:00"
        try:
            s = int(seconds)
            if s < 0:
                return "00:00:00"
            hours = s // 3600
            minutes = (s % 3600) // 60
            secs = s % 60
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "00:00:00"

    @classmethod
    def get_description_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False) -> Path:
        """Returns the expected output path for the description file."""
        filename = resolve_media_filename(video.title, video.video_id, "description", include_video_id=include_video_id)
        return target_dir / filename

    @classmethod
    def format_duration(cls, seconds: Optional[float]) -> str:
        """Formats seconds into human-readable duration string (MM:SS or HH:MM:SS)."""
        if seconds is None:
            return "N/A"
        try:
            s = int(seconds)
            if s < 0:
                return "N/A"
            hours = s // 3600
            minutes = (s % 3600) // 60
            secs = s % 60
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "N/A"

    @classmethod
    def format_chapter_time(cls, seconds: Optional[float]) -> str:
        """Formats chapter timestamp into MM:SS or HH:MM:SS."""
        if seconds is None:
            return "00:00"
        try:
            s = int(seconds)
            if s < 0:
                return "00:00"
            hours = s // 3600
            minutes = (s % 3600) // 60
            secs = s % 60
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            return f"{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return "00:00"

    @classmethod
    def format_number(cls, val: Any) -> str:
        """Formats integer/float with comma thousands grouping, or returns N/A."""
        if val is None or val == "":
            return "N/A"
        try:
            return f"{int(val):,}"
        except (ValueError, TypeError):
            return str(val)

    @classmethod
    def format_date(cls, val: Any) -> str:
        """Formats YYYYMMDD string into YYYY-MM-DD, or returns as-is / N/A."""
        if not val:
            return "N/A"
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s

    @classmethod
    def format_metadata_txt(cls, info: Dict[str, Any], video: Optional[VideoItem] = None) -> str:
        """
        Converts raw yt-dlp metadata into a clean, human-readable TXT file formatted with sections.
        """
        sep = "=" * 40
        sections: List[str] = []

        def add_section(title: str, content: str):
            clean_content = content.strip()
            sections.append(f"{sep}\n{title}\n{sep}\n\n{clean_content}\n")

        # 1. VIDEO INFORMATION
        title_val = info.get("title") or (video.title if video else None) or "N/A"
        vid_id_val = info.get("id") or (video.video_id if video else None) or "N/A"
        uploader_val = info.get("uploader") or info.get("channel") or "N/A"
        channel_val = info.get("channel") or info.get("uploader") or (video.channel_title if video else None) or "N/A"
        channel_id_val = info.get("channel_id") or info.get("uploader_id") or "N/A"
        channel_url_val = info.get("channel_url") or info.get("uploader_url") or (f"https://www.youtube.com/channel/{channel_id_val}" if channel_id_val != "N/A" else "N/A")
        upload_date_val = cls.format_date(info.get("upload_date"))
        duration_val = cls.format_duration(info.get("duration") if info.get("duration") is not None else (video.duration_seconds if video else None))
        if duration_val == "N/A" and video and video.duration:
            duration_val = video.duration
        webpage_url_val = info.get("webpage_url") or info.get("original_url") or (video.url if video else None) or (f"https://www.youtube.com/watch?v={vid_id_val}" if vid_id_val != "N/A" else "N/A")

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
        add_section("VIDEO INFORMATION", "\n".join(video_info_lines))

        # 2. STATISTICS
        view_cnt = cls.format_number(info.get("view_count"))
        like_cnt = cls.format_number(info.get("like_count"))
        comment_cnt = cls.format_number(info.get("comment_count"))
        sub_cnt = cls.format_number(info.get("channel_follower_count") or info.get("subscriber_count"))

        stats_lines = [
            f"View Count:\n{view_cnt}\n",
            f"Like Count:\n{like_cnt}\n",
            f"Comment Count:\n{comment_cnt}\n",
            f"Channel Followers:\n{sub_cnt}",
        ]
        add_section("STATISTICS", "\n".join(stats_lines))

        # 3. DESCRIPTION
        raw_desc = info.get("description")
        desc_text = raw_desc if (raw_desc is not None and str(raw_desc).strip()) else "N/A"
        add_section("DESCRIPTION", desc_text)

        # 4. TAGS
        tags = info.get("tags")
        if tags and isinstance(tags, (list, tuple)) and len(tags) > 0:
            tags_text = "\n".join(str(t).strip() for t in tags if str(t).strip())
            if not tags_text:
                tags_text = "None"
        else:
            tags_text = "None"
        add_section("TAGS", tags_text)

        # 5. CATEGORIES
        categories = info.get("categories")
        if categories and isinstance(categories, (list, tuple)) and len(categories) > 0:
            cats_text = "\n".join(str(c).strip() for c in categories if str(c).strip())
            if not cats_text:
                cats_text = "None"
        else:
            cats_text = "None"
        add_section("CATEGORIES", cats_text)

        # 6. CHAPTERS
        chapters = info.get("chapters")
        if chapters and isinstance(chapters, (list, tuple)) and len(chapters) > 0:
            chap_lines = []
            for chap in chapters:
                st = chap.get("start_time", 0)
                ts = cls.format_chapter_time(st)
                ct = str(chap.get("title", "")).strip()
                chap_lines.append(f"{ts} {ct}")
            chapters_text = "\n".join(chap_lines)
        else:
            chapters_text = "None"
        add_section("CHAPTERS", chapters_text)

        # 7. OTHER INFORMATION
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

        add_section("OTHER INFORMATION", "\n".join(other_lines))

        return "\n".join(sections).rstrip() + "\n"

    @classmethod
    def get_metadata_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False) -> Path:
        """Returns the expected output path for the .metadata.txt file."""
        filename = resolve_media_filename(video.title, video.video_id, "metadata.txt", include_video_id=include_video_id)
        return target_dir / filename

    @classmethod
    def get_chapters_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False) -> Path:
        """Returns the expected output path for the .chapters.txt file."""
        filename = resolve_media_filename(video.title, video.video_id, "chapters.txt", include_video_id=include_video_id)
        return target_dir / filename

    @classmethod
    def is_info_complete(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
    ) -> Tuple[bool, Dict[str, bool]]:
        """
        Checks whether all requested information files for this video already exist on disk.

        Returns:
            Tuple of (all_complete: bool, status_by_key: Dict[str, bool])
        """
        inc_id = getattr(settings, "include_video_id_in_filename", False)
        desc_path = cls.get_description_path(video, target_dir, include_video_id=inc_id)
        meta_path = cls.get_metadata_path(video, target_dir, include_video_id=inc_id)
        chap_path = cls.get_chapters_path(video, target_dir, include_video_id=inc_id)

        def file_exists(primary_path: Path, alt_func) -> bool:
            if primary_path.is_file() and primary_path.stat().st_size > 0:
                return True
            alt_path = alt_func(video, target_dir, include_video_id=not inc_id)
            if alt_path.is_file() and alt_path.stat().st_size > 0:
                return True
            return False

        needed: Dict[str, bool] = {}
        if settings.save_description:
            needed["description"] = file_exists(desc_path, cls.get_description_path)
        if settings.save_metadata:
            needed["metadata"] = file_exists(meta_path, cls.get_metadata_path)
        if settings.save_chapters:
            needed["chapters"] = file_exists(chap_path, cls.get_chapters_path)

        all_present = len(needed) > 0 and all(needed.values())
        return all_present, needed

    @classmethod
    def save_video_info(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        info_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Extracts and saves requested description, metadata, and chapters in a single yt-dlp pass.

        Returns:
            Dict containing:
            {
                'success': bool,
                'skipped': bool,
                'saved_files': List[Path],
                'error': str,
            }
        """
        # 1. Quick exit if none of the information assets are requested
        if not (settings.save_description or settings.save_metadata or settings.save_chapters):
            return {"success": True, "skipped": True, "saved_files": [], "error": ""}

        # 2. Check cancellation
        if cancel_check and cancel_check():
            return {
                "success": False,
                "skipped": False,
                "saved_files": [],
                "error": "Cancelled by user",
            }

        inc_id = getattr(settings, "include_video_id_in_filename", False)
        clean_title = sanitize_filename(video.title)
        target_dir.mkdir(parents=True, exist_ok=True)
        if not video.url:
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter(getattr(video, "platform", "youtube"))
            video_url = adapter.build_video_url(video.video_id) if adapter else f"https://www.youtube.com/watch?v={video.video_id}"
        else:
            video_url = video.url

        desc_path = cls.get_description_path(video, target_dir, include_video_id=inc_id)
        meta_path = cls.get_metadata_path(video, target_dir, include_video_id=inc_id)
        chap_path = cls.get_chapters_path(video, target_dir, include_video_id=inc_id)

        # 3. Independent disk skip check
        if settings.skip_existing:
            all_present, _ = cls.is_info_complete(video, settings, target_dir)
            if all_present:
                if log_callback:
                    log_callback(f"[ARCHIVE] Video information files already exist: {clean_title}. Skipping.")
                return {
                    "success": True,
                    "skipped": True,
                    "saved_files": [],
                    "error": "",
                }

        # 4. Prepare yt-dlp options for single-pass extraction
        stem = resolve_media_filename(video.title, video.video_id, include_video_id=inc_id)
        outtmpl_pattern = str(target_dir / f"{stem}.%(ext)s")

        platform = getattr(video, "platform", "youtube")
        ydl_opts: Dict[str, Any] = YtDlpEngine.build_base_ydl_opts(
            log_callback=log_callback,
            browser_cookies=settings.browser_cookies,
            quiet=True,
            no_warnings=True,
            platform=platform,
            settings=settings,
        )
        ydl_opts.update({
            "skip_download": True,
            "windowsfilenames": True,
            "continuedl": True,
            "outtmpl": outtmpl_pattern,
            "paths": {
                "home": str(target_dir),
                "temp": str(get_temp_dir()),
            },
        })

        need_meta_write = settings.save_metadata and (not settings.skip_existing or not (meta_path.is_file() and meta_path.stat().st_size > 0))
        need_desc_write = settings.save_description and (not settings.skip_existing or not (desc_path.is_file() and desc_path.stat().st_size > 0))

        if need_meta_write:
            if log_callback:
                log_callback(f"[Metadata] Saving: {video.title}")

        if need_desc_write:
            ydl_opts["writedescription"] = True
            if log_callback:
                log_callback(f"[Description] Saving: {video.title}")

        if ffmpeg_location:
            ydl_opts["ffmpeg_location"] = ffmpeg_location

        # 5. Execute unified extraction pass (or reuse pre-extracted info_dict)
        info: Optional[Dict[str, Any]] = info_dict
        if info is None:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=True)
            except Exception as e:
                err_msg = str(e)
                if log_callback:
                    if settings.save_metadata:
                        log_callback(f"[Metadata] Failed: {video.title}\nReason: {err_msg}")
                    if settings.save_description:
                        log_callback(f"[Description] Failed: {video.title}\nReason: {err_msg}")
                    if settings.save_chapters:
                        log_callback(f"[Chapters] Extraction failed for {video.title}: {err_msg}")
                return {
                    "success": False,
                    "skipped": False,
                    "saved_files": [],
                    "error": err_msg,
                }

        saved_files: List[Path] = []

        # 6. Format and handle Metadata (.metadata.txt)
        if settings.save_metadata:
            if meta_path.is_file() and meta_path.stat().st_size > 0 and settings.skip_existing:
                saved_files.append(meta_path)
                if log_callback:
                    log_callback(f"[Metadata] Skipped (already exists): {meta_path.name}")
            elif info:
                try:
                    formatted_meta = cls.format_metadata_txt(info, video)
                    meta_path.write_text(formatted_meta, encoding="utf-8")
                    saved_files.append(meta_path)
                    if log_callback:
                        log_callback(f"[Metadata] Saved: {meta_path.name}")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[Metadata] Failed: {video.title}\nReason: {e}")

        # 7. Verify and handle Description (.description)
        if settings.save_description:
            if desc_path.is_file() and desc_path.stat().st_size > 0:
                saved_files.append(desc_path)
                if log_callback:
                    log_callback(f"[Description] Saved: {desc_path.name}")
            else:
                found_desc = False
                for cand in target_dir.glob("*.description"):
                    if cand.is_file() and cand.stat().st_size > 0:
                        if cand.name.startswith(f"{stem}.") or (video.video_id and video.video_id in cand.name):
                            saved_files.append(cand)
                            found_desc = True
                            if log_callback:
                                log_callback(f"[Description] Saved: {cand.name}")
                            break
                if not found_desc:
                    raw_desc = (info or {}).get("description")
                    if raw_desc is not None:
                        try:
                            desc_path.write_text(raw_desc, encoding="utf-8")
                            saved_files.append(desc_path)
                            if log_callback:
                                log_callback(f"[Description] Saved: {desc_path.name}")
                        except Exception as e:
                            if log_callback:
                                log_callback(f"[Description] Failed: {video.title}\nReason: {e}")
                    else:
                        if log_callback:
                            log_callback(f"[Description] Failed: {video.title}\nReason: Description unavailable")

        # 8. Extract and handle Chapters (.chapters.txt)
        if settings.save_chapters:
            chapters = (info or {}).get("chapters")
            if chapters:
                try:
                    lines: List[str] = []
                    for chap in chapters:
                        start_time = chap.get("start_time", 0)
                        ts_str = cls.format_timestamp(start_time)
                        chap_title = str(chap.get("title", "")).strip()
                        lines.append(f"{ts_str} {chap_title}")

                    chap_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    saved_files.append(chap_path)
                    if log_callback:
                        log_callback(f"[Chapters] Found: {len(chapters)} chapters")
                        log_callback(f"[Chapters] Saved: {chap_path.name}")
                except Exception as e:
                    if log_callback:
                        log_callback(f"[Chapters] Failed writing chapters for {video.title}: {e}")
            else:
                if log_callback:
                    log_callback(f"[Chapters] No chapters available: {video.title}")

        return {
            "success": True,
            "skipped": False,
            "saved_files": saved_files,
            "error": "",
        }
