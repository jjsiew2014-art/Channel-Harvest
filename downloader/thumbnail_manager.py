"""
thumbnail_manager.py
YouTube video thumbnail downloader and format converter for Channel Harvest.

Key Features:
- Downloads video thumbnails using yt-dlp native functionality (--write-thumbnail).
- Converts thumbnails to requested format using yt-dlp native postprocessor:
    * JPG: Converted to standard JPEG image (.jpg)
    * PNG: Converted to Portable Network Graphics (.png)
    * WEBP: Converted to WebP image (.webp)
    * Original: Saved in native source format without conversion
- Standalone output: Always saved as separate image files (e.g. 'Song [ID].jpg'),
  never embedded into media files.
- Clean filename sanitization matching video container naming.
- Independent skip logic: Checks disk for existing thumbnail files before downloading,
  enabling users to retrieve missing thumbnails for previously downloaded videos.
- Non-fatal error isolation: Failures are reported clearly to the Activity Log
  without aborting the batch queue or marking media downloads as failed.
- Compatible with bundled runtime FFmpeg.
"""

import os
import re
from pathlib import Path
from typing import Dict, Tuple, Optional, Callable, Any, List

import yt_dlp
from yt_dlp.utils import DownloadError

from core.models import VideoItem, DownloadSettings, ThumbnailFormat
from downloader.ytdlp_engine import YtDlpEngine


class ThumbnailManager:
    """
    Manages YouTube thumbnail downloading, conversion, and caching verification.
    """

    SUPPORTED_FORMATS: List[str] = [
        ThumbnailFormat.JPG,
        ThumbnailFormat.PNG,
        ThumbnailFormat.WEBP,
        ThumbnailFormat.ORIGINAL,
    ]

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

    @classmethod
    def sanitize_title(cls, title: str) -> str:
        """Removes filesystem-invalid characters while preserving Unicode/Chinese characters."""
        return re.sub(r'[\\/*?:"<>|]', "_", title).strip()

    @classmethod
    def get_target_extension(cls, format_choice: str) -> Optional[str]:
        """Returns the target file extension for the given format choice, or None for Original."""
        fmt = (format_choice or "JPG").strip().upper()
        if fmt == ThumbnailFormat.JPG:
            return "jpg"
        elif fmt == ThumbnailFormat.PNG:
            return "png"
        elif fmt == ThumbnailFormat.WEBP:
            return "webp"
        return None  # Original format depends on source

    @classmethod
    def is_thumbnail_downloaded(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
    ) -> Tuple[bool, Optional[Path]]:
        """
        Independently checks whether a valid thumbnail file for this video already exists on disk.

        Returns:
            Tuple of (exists: bool, file_path: Optional[Path])
        """
        clean_title = cls.sanitize_title(video.title)
        target_ext = cls.get_target_extension(settings.thumbnail_format)

        # 1. Check exact expected filename: <title> [<id>].<ext>
        if target_ext:
            exact_path = target_dir / f"{clean_title} [{video.video_id}].{target_ext}"
            if exact_path.is_file() and exact_path.stat().st_size > 0:
                return True, exact_path
            # For JPG, also check .jpeg
            if target_ext == "jpg":
                alt_jpeg = target_dir / f"{clean_title} [{video.video_id}].jpeg"
                if alt_jpeg.is_file() and alt_jpeg.stat().st_size > 0:
                    return True, alt_jpeg

        # 2. Check any image file containing the video ID in target directory
        for cand in target_dir.glob(f"*{video.video_id}*"):
            if cand.is_file() and cand.stat().st_size > 0:
                suffix_lower = cand.suffix.lower()
                if target_ext:
                    if suffix_lower == f".{target_ext}" or (target_ext == "jpg" and suffix_lower == ".jpeg"):
                        return True, cand
                elif suffix_lower in cls.IMAGE_EXTENSIONS:
                    return True, cand

        return False, None

    @classmethod
    def download_thumbnail(
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
        Downloads and converts the YouTube thumbnail for the given video as a separate image file.

        Returns:
            Dict containing:
            {
                'success': bool,
                'skipped': bool,
                'saved_file': Optional[Path],
                'error': str,
            }
        """
        if cancel_check and cancel_check():
            return {
                "success": False,
                "skipped": False,
                "saved_file": None,
                "error": "Cancelled by user",
            }

        clean_title = cls.sanitize_title(video.title)
        target_dir.mkdir(parents=True, exist_ok=True)
        video_url = video.url if video.url else f"https://www.youtube.com/watch?v={video.video_id}"

        # 1. Independent disk skip check
        if settings.skip_existing:
            already_exists, existing_file = cls.is_thumbnail_downloaded(video, settings, target_dir)
            if already_exists and existing_file is not None:
                if log_callback:
                    log_callback(f"[ARCHIVE] Thumbnail already exists: {existing_file.name}. Skipping.")
                return {
                    "success": True,
                    "skipped": True,
                    "saved_file": existing_file,
                    "error": "",
                }

        fmt_choice = (settings.thumbnail_format or ThumbnailFormat.JPG).strip().upper()
        target_ext = cls.get_target_extension(fmt_choice)

        if log_callback:
            log_callback(f"[Thumbnail] Downloading: {video.title}")

        # 2. Configure yt-dlp options for native thumbnail retrieval & conversion
        outtmpl_pattern = str(target_dir / f"{clean_title} [{video.video_id}].%(ext)s")

        ydl_opts: Dict[str, Any] = YtDlpEngine.build_base_ydl_opts(
            log_callback=log_callback,
            browser_cookies=settings.browser_cookies,
            quiet=True,
            no_warnings=True,
        )
        ydl_opts.update({
            "skip_download": True,
            "writethumbnail": True,
            "windowsfilenames": True,
            "continuedl": True,
            "outtmpl": outtmpl_pattern,
        })

        # Add native yt-dlp thumbnail converter postprocessor if conversion requested
        if target_ext:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegThumbnailsConvertor",
                    "format": target_ext,
                    "when": "before_dl",
                }
            ]

        if ffmpeg_location:
            ydl_opts["ffmpeg_location"] = ffmpeg_location

        # 3. Execute download via yt-dlp (reuse info_dict if provided to avoid duplicate network extraction)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if info_dict:
                    ydl.process_ie_result(info_dict, download=True)
                else:
                    ydl.download([video_url])
        except Exception as e:
            err_msg = str(e)
            if log_callback:
                log_callback(f"[Thumbnail] Failed: {video.title}")
                log_callback(f"Reason: {err_msg}")
            return {
                "success": False,
                "skipped": False,
                "saved_file": None,
                "error": err_msg,
            }

        # 4. Locate and verify saved thumbnail file
        saved_file: Optional[Path] = None

        if target_ext:
            expected_file = target_dir / f"{clean_title} [{video.video_id}].{target_ext}"
            if expected_file.is_file() and expected_file.stat().st_size > 0:
                saved_file = expected_file
            elif target_ext == "jpg":
                alt_jpeg = target_dir / f"{clean_title} [{video.video_id}].jpeg"
                if alt_jpeg.is_file() and alt_jpeg.stat().st_size > 0:
                    saved_file = alt_jpeg

        if not saved_file:
            # Fallback search for any image file containing video_id
            for cand in target_dir.glob(f"*{video.video_id}*"):
                if cand.suffix.lower() in cls.IMAGE_EXTENSIONS and cand.is_file() and cand.stat().st_size > 0:
                    saved_file = cand
                    break

        if saved_file is not None:
            if log_callback:
                log_callback(f"[Thumbnail] Saved: {saved_file.name}")
            return {
                "success": True,
                "skipped": False,
                "saved_file": saved_file,
                "error": "",
            }
        else:
            reason = "No thumbnail file was generated by yt-dlp."
            if log_callback:
                log_callback(f"[Thumbnail] Failed: {video.title}")
                log_callback(f"Reason: {reason}")
            return {
                "success": False,
                "skipped": False,
                "saved_file": None,
                "error": reason,
            }
