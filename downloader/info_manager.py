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
    def get_description_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False, number_prefix: str = "") -> Path:
        """Returns the expected output path for the description file."""
        filename = resolve_media_filename(video.title, video.video_id, "description", include_video_id=include_video_id, target_dir=target_dir, number_prefix=number_prefix)
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
        Delegates to the platform-specific MetadataExporter.
        """
        from metadata.metadata_exporter import MetadataExporter
        return MetadataExporter.export_metadata_txt(info, video)

    @classmethod
    def get_metadata_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False, number_prefix: str = "") -> Path:
        """Returns the expected output path for the .metadata.txt file."""
        filename = resolve_media_filename(video.title, video.video_id, "metadata.txt", include_video_id=include_video_id, target_dir=target_dir, number_prefix=number_prefix)
        return target_dir / filename

    @classmethod
    def get_chapters_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = False, number_prefix: str = "") -> Path:
        """Returns the expected output path for the .chapters.txt file."""
        filename = resolve_media_filename(video.title, video.video_id, "chapters.txt", include_video_id=include_video_id, target_dir=target_dir, number_prefix=number_prefix)
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
        num_prefix = getattr(settings, "number_prefix", "")
        desc_path = cls.get_description_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)
        meta_path = cls.get_metadata_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)
        chap_path = cls.get_chapters_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)

        def file_exists(primary_path: Path, alt_func) -> bool:
            if primary_path.is_file() and primary_path.stat().st_size > 0:
                return True
            alt_path = alt_func(video, target_dir, include_video_id=not inc_id, number_prefix=num_prefix)
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

        num_prefix = getattr(settings, "number_prefix", "")
        desc_path = cls.get_description_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)
        meta_path = cls.get_metadata_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)
        chap_path = cls.get_chapters_path(video, target_dir, include_video_id=inc_id, number_prefix=num_prefix)

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
        stem = resolve_media_filename(video.title, video.video_id, include_video_id=inc_id, target_dir=target_dir, number_prefix=num_prefix)
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
        ydl_opts.pop("paths", None)
        ydl_opts.update({
            "skip_download": True,
            "windowsfilenames": True,
            "continuedl": True,
            "outtmpl": outtmpl_pattern,
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
                from metadata.metadata_exporter import MetadataExporter
                success = MetadataExporter.save_metadata_file(
                    target_path=meta_path,
                    info=info,
                    video=video,
                    platform_id=getattr(video, "platform", None),
                    log_callback=log_callback,
                )
                if success:
                    saved_files.append(meta_path)
                    if log_callback:
                        log_callback(f"[Metadata] Saved: {meta_path.name}")
                else:
                    if log_callback:
                        log_callback(f"[Metadata] Failed: {video.title}")

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
