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
from core.paths import resolve_media_filename, sanitize_filename, get_temp_dir
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
        include_id = getattr(settings, "include_video_id_in_filename", False)
        num_prefix = getattr(settings, "number_prefix", "")
        clean_title = sanitize_filename(video.title)
        target_ext = cls.get_target_extension(settings.thumbnail_format)

        # 1. Check exact expected filename according to current setting
        if target_ext:
            expected_name = resolve_media_filename(video.title, video.video_id, target_ext, include_video_id=include_id, target_dir=target_dir, number_prefix=num_prefix)
            exact_path = target_dir / expected_name
            if exact_path.is_file() and exact_path.stat().st_size > 0:
                return True, exact_path
            # For JPG, also check .jpeg
            if target_ext == "jpg":
                alt_jpeg_name = resolve_media_filename(video.title, video.video_id, "jpeg", include_video_id=include_id, target_dir=target_dir)
                alt_jpeg = target_dir / alt_jpeg_name
                if alt_jpeg.is_file() and alt_jpeg.stat().st_size > 0:
                    return True, alt_jpeg

            # Also check alternative naming (e.g. if previously downloaded with/without ID)
            alt_name = resolve_media_filename(video.title, video.video_id, target_ext, include_video_id=not include_id, target_dir=target_dir)
            alt_path = target_dir / alt_name
            if alt_path.is_file() and alt_path.stat().st_size > 0:
                return True, alt_path
            if target_ext == "jpg":
                alt_name2 = resolve_media_filename(video.title, video.video_id, "jpeg", include_video_id=not include_id, target_dir=target_dir)
                alt_path2 = target_dir / alt_name2
                if alt_path2.is_file() and alt_path2.stat().st_size > 0:
                    return True, alt_path2

        # 2. Check any image file containing the video ID in target directory
        if video.video_id:
            for cand in target_dir.glob(f"*{video.video_id}*"):
                if cand.is_file() and cand.stat().st_size > 0:
                    suffix_lower = cand.suffix.lower()
                    if target_ext:
                        if suffix_lower == f".{target_ext}" or (target_ext == "jpg" and suffix_lower == ".jpeg"):
                            return True, cand
                    elif suffix_lower in cls.IMAGE_EXTENSIONS:
                        return True, cand

        # 3. Check any image file starting with clean_title if include_id is False
        if not include_id:
            for cand in target_dir.iterdir():
                if cand.is_file() and cand.stat().st_size > 0:
                    if cand.name.startswith(f"{clean_title}."):
                        suffix_lower = cand.suffix.lower()
                        if target_ext:
                            if suffix_lower == f".{target_ext}" or (target_ext == "jpg" and suffix_lower == ".jpeg"):
                                return True, cand
                        elif suffix_lower in cls.IMAGE_EXTENSIONS:
                            return True, cand

        return False, None

    @classmethod
    def _save_image_data(
        cls,
        img_bytes: bytes,
        target_dir: Path,
        stem: str,
        target_ext: Optional[str],
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[Path]:
        """
        Saves raw image bytes to disk in the requested format (JPG, PNG, WEBP, or Original)
        using Pillow with maximum fidelity and zero unnecessary loss.
        """
        if not img_bytes:
            return None
        import io
        from PIL import Image

        try:
            with Image.open(io.BytesIO(img_bytes)) as im:
                src_format = (im.format or "").upper()
                if not target_ext:  # Original format
                    ext = "jpg" if src_format in ("JPEG", "JPG") else src_format.lower()
                    if not ext or ext == "none":
                        ext = "jpg"
                    dest_file = target_dir / f"{stem}.{ext}"
                    dest_file.write_bytes(img_bytes)
                    return dest_file

                target_ext_clean = target_ext.lower().lstrip(".")
                if target_ext_clean == "jpg":
                    dest_file = target_dir / f"{stem}.jpg"
                    if src_format in ("JPEG", "JPG"):
                        # Already JPEG: write source bytes directly with 100% original quality
                        dest_file.write_bytes(img_bytes)
                        return dest_file
                    if im.mode in ("RGBA", "LA", "P"):
                        im = im.convert("RGB")
                    im.save(dest_file, "JPEG", quality=95, subsampling=0)
                    return dest_file
                elif target_ext_clean == "png":
                    dest_file = target_dir / f"{stem}.png"
                    if src_format == "PNG":
                        dest_file.write_bytes(img_bytes)
                        return dest_file
                    im.save(dest_file, "PNG", optimize=True)
                    return dest_file
                elif target_ext_clean == "webp":
                    dest_file = target_dir / f"{stem}.webp"
                    if src_format == "WEBP":
                        dest_file.write_bytes(img_bytes)
                        return dest_file
                    im.save(dest_file, "WEBP", quality=95)
                    return dest_file
                else:
                    dest_file = target_dir / f"{stem}.{target_ext_clean}"
                    dest_file.write_bytes(img_bytes)
                    return dest_file
        except Exception as e:
            if log_callback:
                log_callback(f"[Thumbnail] Image processing error: {e}")
            return None

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

        include_id = getattr(settings, "include_video_id_in_filename", False)
        clean_title = sanitize_filename(video.title)
        target_dir.mkdir(parents=True, exist_ok=True)
        if not video.url:
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter(getattr(video, "platform", "youtube"))
            video_url = adapter.build_video_url(video.video_id) if adapter else f"https://www.youtube.com/watch?v={video.video_id}"
        else:
            video_url = video.url

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
        num_prefix = getattr(settings, "number_prefix", "")
        stem = resolve_media_filename(video.title, video.video_id, include_video_id=include_id, target_dir=target_dir, number_prefix=num_prefix)

        if log_callback:
            log_callback(f"[Thumbnail] Downloading: {video.title}")

        # 1.5 Direct Master Thumbnail Download
        # If the platform adapter has already extracted an authentic master image URL (e.g. RedNote CDN)
        direct_thumb_url = getattr(video, "cover_art_url", None) or (getattr(video, "extra_metadata", None) or {}).get("thumbnail_url")
        if direct_thumb_url and isinstance(direct_thumb_url, str) and direct_thumb_url.startswith(("http://", "https://")):
            if not ("!nd_prv" in direct_thumb_url or "_prv_" in direct_thumb_url):
                try:
                    import urllib.request
                    ref_url = getattr(video, "url", "") or "https://www.xiaohongshu.com/"
                    req = urllib.request.Request(
                        direct_thumb_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                            "Referer": ref_url,
                            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        img_bytes = resp.read()

                    if img_bytes and len(img_bytes) > 500:
                        saved_file = cls._save_image_data(
                            img_bytes=img_bytes,
                            target_dir=target_dir,
                            stem=stem,
                            target_ext=target_ext,
                            log_callback=log_callback,
                        )
                        if saved_file and saved_file.is_file() and saved_file.stat().st_size > 0:
                            if log_callback:
                                log_callback(f"[Thumbnail] Saved: {saved_file.name}")
                            return {
                                "success": True,
                                "skipped": False,
                                "saved_file": saved_file,
                                "error": "",
                            }
                except Exception as direct_err:
                    if log_callback:
                        log_callback(f"[Thumbnail] Direct master thumbnail retrieval failed ({direct_err}), falling back to engine...")

        # 2. Configure yt-dlp options for native thumbnail retrieval & conversion
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
            "writethumbnail": True,
            "windowsfilenames": True,
            "continuedl": settings.skip_existing,
            "overwrites": not settings.skip_existing,
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
        # Sanitize info_dict thumbnails to remove low-res preview urls (like !nd_prv...)
        if info_dict and "thumbnails" in info_dict:
            orig_thumbs = info_dict.get("thumbnails") or []
            if orig_thumbs:
                filtered = [
                    t for t in orig_thumbs
                    if not (isinstance(t.get("url"), str) and ("!nd_prv" in t["url"] or "_prv_" in t["url"]))
                ]
                if filtered:
                    info_dict["thumbnails"] = filtered
                if direct_thumb_url and isinstance(direct_thumb_url, str):
                    info_dict["thumbnails"].append({
                        "url": direct_thumb_url,
                        "preference": 1000,
                        "width": getattr(video, "cover_art_width", None) or 3840,
                        "height": getattr(video, "cover_art_height", None) or 2160,
                    })
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
            expected_file = target_dir / f"{stem}.{target_ext}"
            if expected_file.is_file() and expected_file.stat().st_size > 0:
                saved_file = expected_file
            elif target_ext == "jpg":
                alt_jpeg = target_dir / f"{stem}.jpeg"
                if alt_jpeg.is_file() and alt_jpeg.stat().st_size > 0:
                    saved_file = alt_jpeg

        if not saved_file:
            # Fallback search for any image file matching stem or video_id
            for cand in target_dir.iterdir():
                if cand.is_file() and cand.stat().st_size > 0 and cand.suffix.lower() in cls.IMAGE_EXTENSIONS:
                    if cand.name.startswith(f"{stem}.") or (video.video_id and video.video_id in cand.name):
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
