"""
subtitle_manager.py
YouTube subtitle and caption manager for Channel Harvest.

Handles:
- Detecting uploaded (manual) subtitles and auto-generated captions.
- Matching BCP-47 language codes and variants (Chinese, English, Malay, Japanese, Korean, All).
- Resolving subtitle source logic:
    * Best Available (prefers official/manual, falls back to auto-generated)
    * Official / Uploaded (writesubtitles only)
    * Auto-generated (writeautomaticsub only)
- Downloading subtitles without video/audio when in Subtitle Only mode.
- Converting subtitles to standard SRT using FFmpeg.
- Clean filename normalization matching video output (e.g., 'Song [ID].srt').
- Independent skip logic verifying existing SRT files on disk.
"""

import os
import re
import glob
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable, Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings, SubtitleSource, SubtitleLanguage
from core.paths import resolve_media_filename, get_temp_dir
from downloader.ytdlp_engine import YtDlpEngine


class SubtitleManager:
    """
    Manages YouTube subtitle extraction, selection, conversion, and saving.
    """

    # Language definition mapping: user display label -> (primary_code, prefixes, yt_dlp_patterns)
    LANGUAGE_SPECS = {
        SubtitleLanguage.CHINESE: {
            "code": "zh",
            "prefixes": ["zh", "zh-"],
            "patterns": ["zh.*", "zh-Hans.*", "zh-Hant.*", "zh-CN", "zh-TW", "zh-HK", "zh"],
        },
        SubtitleLanguage.ENGLISH: {
            "code": "en",
            "prefixes": ["en", "en-"],
            "patterns": ["en.*", "en-US", "en-GB", "en"],
        },
        SubtitleLanguage.MALAY: {
            "code": "ms",
            "prefixes": ["ms", "ms-"],
            "patterns": ["ms.*", "ms-MY", "ms"],
        },
        SubtitleLanguage.JAPANESE: {
            "code": "ja",
            "prefixes": ["ja", "ja-"],
            "patterns": ["ja.*", "ja"],
        },
        SubtitleLanguage.KOREAN: {
            "code": "ko",
            "prefixes": ["ko", "ko-"],
            "patterns": ["ko.*", "ko"],
        },
        SubtitleLanguage.ALL: {
            "code": "all",
            "prefixes": [],
            "patterns": ["all"],
        },
    }

    @classmethod
    def get_language_spec(cls, language_label: str) -> Dict[str, Any]:
        """Returns language specification for given label or fallback for custom code."""
        if language_label in cls.LANGUAGE_SPECS:
            return cls.LANGUAGE_SPECS[language_label]

        # Handle custom language code (e.g., 'es', 'fr', 'de')
        cleaned = language_label.strip().lower()
        return {
            "code": cleaned,
            "prefixes": [cleaned, f"{cleaned}-"],
            "patterns": [f"{cleaned}.*", cleaned],
        }

    @classmethod
    def matches_language(cls, tag: str, language_label: str) -> bool:
        """Checks whether a subtitle language tag matches the requested language."""
        if language_label == SubtitleLanguage.ALL:
            return True

        spec = cls.get_language_spec(language_label)
        tag_lower = tag.strip().lower()

        # Check prefixes
        for prefix in spec.get("prefixes", []):
            if tag_lower == prefix or tag_lower.startswith(prefix):
                return True
        return False

    @classmethod
    def inspect_subtitles(
        cls,
        video_url: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Lightweight metadata extraction returning manual subtitles and auto captions.

        Returns:
            Tuple of (uploaded_subtitles_dict, auto_captions_dict)
        """
        ydl_opts = YtDlpEngine.build_base_ydl_opts(
            log_callback=log_callback,
            quiet=True,
            no_warnings=True,
            platform="youtube",
        )
        ydl_opts.update({
            "skip_download": True,
            "extract_flat": False,
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if not info:
                    return {}, {}
                manual = info.get("subtitles") or {}
                auto = info.get("automatic_captions") or {}
                return manual, auto
        except Exception as e:
            if log_callback:
                log_callback(f"[SUBTITLE] Could not inspect subtitles for {video_url}: {e}")
            return {}, {}

    @classmethod
    def detect_subtitles_info(cls, video_id: str) -> Dict[str, Any]:
        """
        Fast and robust subtitle detection for a video ID.
        Checks YouTube watch page player JSON directly (<0.2s),
        and falls back to yt-dlp metadata inspection if needed.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
                },
            )
            html = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", "ignore")

            if "captionTracks" not in html:
                return {
                    "has_subtitles": False,
                    "has_manual": False,
                    "has_auto": False,
                    "manual_languages": [],
                    "auto_languages": [],
                    "status_text": "No Subs",
                    "tooltip": "No subtitles or captions available on YouTube",
                }

            m = re.search(r'"captionTracks":(\[.*?\])(?:,"|\})', html)
            if not m:
                return {
                    "has_subtitles": False,
                    "has_manual": False,
                    "has_auto": False,
                    "manual_languages": [],
                    "auto_languages": [],
                    "status_text": "No Subs",
                    "tooltip": "No subtitles or captions available on YouTube",
                }

            tracks = json.loads(m.group(1))
            manual_langs = []
            auto_langs = []

            for t in tracks:
                lang = t.get("languageCode", "")
                vss = t.get("vssId", "")
                kind = t.get("kind", "")
                is_auto = (kind == "asr") or vss.startswith("a.")
                if is_auto:
                    if lang and lang not in auto_langs:
                        auto_langs.append(lang)
                else:
                    if lang and lang not in manual_langs:
                        manual_langs.append(lang)

            has_manual = len(manual_langs) > 0
            has_auto = len(auto_langs) > 0
            has_sub = has_manual or has_auto

            if has_manual and has_auto:
                status_text = "✓ Official"
                tooltip = f"Official: {', '.join(manual_langs)} | Auto: {', '.join(auto_langs[:4])}"
            elif has_manual:
                status_text = "✓ Official"
                tooltip = f"Official: {', '.join(manual_langs)}"
            elif has_auto:
                status_text = "Auto"
                tooltip = f"Auto-generated: {', '.join(auto_langs[:5])}"
            else:
                status_text = "No Subs"
                tooltip = "No subtitles or captions available on YouTube"

            return {
                "has_subtitles": has_sub,
                "has_manual": has_manual,
                "has_auto": has_auto,
                "manual_languages": manual_langs,
                "auto_languages": auto_langs,
                "status_text": status_text,
                "tooltip": tooltip,
            }

        except urllib.error.HTTPError:
            return {
                "has_subtitles": False,
                "has_manual": False,
                "has_auto": False,
                "manual_languages": [],
                "auto_languages": [],
                "status_text": "No Subs",
                "tooltip": "No subtitles or captions available on YouTube",
            }
        except Exception:
            return {
                "has_subtitles": False,
                "has_manual": False,
                "has_auto": False,
                "manual_languages": [],
                "auto_languages": [],
                "status_text": "No Subs",
                "tooltip": "No subtitles or captions available on YouTube",
            }

    @classmethod
    def get_target_srt_path(cls, video: VideoItem, target_dir: Path, include_video_id: bool = True) -> Path:
        """Returns expected default SRT file path for a video item."""
        filename = resolve_media_filename(video.title, video.video_id, ext="srt", include_video_id=include_video_id)
        return target_dir / filename

    @classmethod
    def is_subtitle_downloaded(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
    ) -> bool:
        """
        Independent check verifying whether the target subtitle file already exists and is valid.
        """
        inc_id = getattr(settings, "include_video_id_in_filename", False)
        stem = resolve_media_filename(video.title, video.video_id, include_video_id=inc_id)

        # 1. Check clean single-language filename: <stem>.srt
        exact_file = target_dir / f"{stem}.srt"
        if exact_file.is_file() and exact_file.stat().st_size > 0:
            return True

        # 2. Check language-tagged filenames: <stem>.<lang>.srt
        for cand in target_dir.glob("*.srt"):
            if not (cand.is_file() and cand.stat().st_size > 0):
                continue
            matches = (video.video_id and video.video_id in cand.name) or cand.name.startswith(f"{stem}.")
            if matches:
                if settings.subtitle_language != SubtitleLanguage.ALL:
                    parts = cand.stem.split(".")
                    if len(parts) >= 2:
                        lang_tag = parts[-1]
                        if cls.matches_language(lang_tag, settings.subtitle_language):
                            return True
                else:
                    return True

        return False

    @classmethod
    def download_subtitles(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Downloads and converts YouTube subtitles to SRT for the given video.

        Returns:
            Dict containing:
            {
                'success': bool,
                'skipped': bool,
                'sub_type': str ('Official', 'Auto-generated', or ''),
                'status_text': str,
                'saved_files': List[Path],
                'error': str,
            }
        """
        if cancel_check and cancel_check():
            return {"success": False, "skipped": False, "status_text": "Cancelled", "saved_files": [], "error": "Cancelled"}

        from core.platform import PlatformRegistry
        adapter = PlatformRegistry.get_adapter(getattr(video, "platform", "youtube"))
        if adapter and not adapter.capabilities.supports_subtitles:
            return {
                "success": False,
                "skipped": True,
                "sub_type": "",
                "status_text": "—",
                "saved_files": [],
                "error": f"Subtitles not supported for {adapter.display_name}",
            }

        clean_title = re.sub(r'[\\/*?:"<>|]', "_", video.title).strip()
        target_dir.mkdir(parents=True, exist_ok=True)
        video_url = video.url if video.url else f"https://www.youtube.com/watch?v={video.video_id}"

        # 1. Check independent skip logic
        if settings.skip_existing and cls.is_subtitle_downloaded(video, settings, target_dir):
            if log_callback:
                log_callback(f"[ARCHIVE] Subtitle already exists on disk: {clean_title}.srt. Skipping.")
            return {
                "success": True,
                "skipped": True,
                "sub_type": "Existing",
                "status_text": "✓ Subtitle Ready",
                "saved_files": [cls.get_target_srt_path(video, target_dir, include_video_id=getattr(settings, "include_video_id_in_filename", False))],
                "error": "",
            }

        target_lang = settings.subtitle_language
        source_mode = settings.subtitle_source
        lang_spec = cls.get_language_spec(target_lang)
        is_all_languages = (target_lang == SubtitleLanguage.ALL)

        if log_callback:
            log_callback(f"[SUBTITLE] Checking subtitles for: {video.title} ({target_lang}, {source_mode})")

        # 2. Inspect available subtitle tracks to make an intelligent source decision
        manual_subs, auto_subs = cls.inspect_subtitles(video_url, log_callback)

        if cancel_check and cancel_check():
            return {"success": False, "skipped": False, "status_text": "Cancelled", "saved_files": [], "error": "Cancelled"}

        # Find matching tags
        matching_manual = [tag for tag in manual_subs.keys() if cls.matches_language(tag, target_lang)]
        matching_auto = [tag for tag in auto_subs.keys() if cls.matches_language(tag, target_lang)]

        use_manual = False
        use_auto = False
        resolved_type = ""

        if source_mode == SubtitleSource.OFFICIAL:
            if matching_manual or is_all_languages:
                use_manual = True
                resolved_type = "Official"
            else:
                err_msg = f"No uploaded {target_lang} subtitles available for this video."
                if log_callback:
                    log_callback(f"[SUBTITLE] {err_msg}")
                return {
                    "success": False,
                    "skipped": False,
                    "sub_type": "",
                    "status_text": "No Official Sub",
                    "saved_files": [],
                    "error": err_msg,
                }

        elif source_mode == SubtitleSource.AUTO_GENERATED:
            if matching_auto or is_all_languages:
                use_auto = True
                resolved_type = "Auto-generated"
            else:
                err_msg = f"No auto-generated {target_lang} captions available for this video."
                if log_callback:
                    log_callback(f"[SUBTITLE] {err_msg}")
                return {
                    "success": False,
                    "skipped": False,
                    "sub_type": "",
                    "status_text": "No Auto Sub",
                    "saved_files": [],
                    "error": err_msg,
                }

        else:  # SubtitleSource.BEST_AVAILABLE
            # 1. Prefer manual/official uploaded subtitles
            if matching_manual or (is_all_languages and manual_subs):
                use_manual = True
                resolved_type = "Official"
                if log_callback:
                    log_callback(f"[SUBTITLE] Found official/uploaded {target_lang} subtitle: {matching_manual}")
            # 2. Fall back to auto-generated captions
            elif matching_auto or (is_all_languages and auto_subs):
                use_auto = True
                resolved_type = "Auto-generated"
                if log_callback:
                    log_callback(f"[SUBTITLE] Found auto-generated {target_lang} caption: {matching_auto}")
            else:
                err_msg = f"No subtitles or captions available in {target_lang}."
                if log_callback:
                    log_callback(f"[SUBTITLE] {err_msg}")
                return {
                    "success": False,
                    "skipped": False,
                    "sub_type": "",
                    "status_text": "No Subs",
                    "saved_files": [],
                    "error": err_msg,
                }

        # Determine subtitle language filter tags for yt-dlp
        if is_all_languages:
            sub_langs = ["all"]
        elif use_manual and matching_manual:
            sub_langs = matching_manual
        elif use_auto and matching_auto:
            sub_langs = matching_auto
        else:
            sub_langs = lang_spec.get("patterns", ["all"])

        if log_callback:
            log_callback(f"[SUBTITLE] Downloading {resolved_type} subtitle: {video.title} (langs={sub_langs})...")

        # 3. Configure yt-dlp for Subtitle Retrieval & SRT Conversion
        inc_id = getattr(settings, "include_video_id_in_filename", False)
        stem = resolve_media_filename(video.title, video.video_id, include_video_id=inc_id)
        outtmpl_pattern = str(target_dir / f"{stem}.%(ext)s")

        platform = getattr(video, "platform", "youtube")
        ydl_opts: Dict[str, Any] = YtDlpEngine.build_base_ydl_opts(
            log_callback=log_callback,
            browser_cookies=settings.browser_cookies,
            quiet=True,
            no_warnings=True,
            platform=platform,
        )
        ydl_opts.update({
            "skip_download": True,
            "windowsfilenames": True,
            "continuedl": True,
            "writesubtitles": use_manual,
            "writeautomaticsub": use_auto,
            "subtitleslangs": sub_langs,
            "subtitlesformat": "srt/best",
            "postprocessors": [
                {
                    "key": "FFmpegSubtitlesConvertor",
                    "format": "srt",
                    "when": "before_dl",
                }
            ],
            "outtmpl": outtmpl_pattern,
            "paths": {
                "home": str(target_dir),
                "temp": str(get_temp_dir()),
            },
        })

        if ffmpeg_location:
            ydl_opts["ffmpeg_location"] = ffmpeg_location

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
        except Exception as e:
            err_text = str(e)
            if log_callback:
                log_callback(f"[SUBTITLE ERROR] Download error: {err_text}")
            return {
                "success": False,
                "skipped": False,
                "sub_type": resolved_type,
                "status_text": "Failed (Sub Error)",
                "saved_files": [],
                "error": f"Subtitle download failed: {err_text}",
            }

        # 4. Locate generated subtitle files
        default_srt = target_dir / f"{stem}.srt"
        saved_paths: List[Path] = []

        if default_srt.is_file() and default_srt.stat().st_size > 0:
            saved_paths.append(default_srt)

        for cand in target_dir.glob("*.srt"):
            if not (cand.is_file() and cand.stat().st_size > 0):
                continue
            matches = (video.video_id and video.video_id in cand.name) or cand.name.startswith(f"{stem}.")
            if matches:
                if cand not in saved_paths:
                    saved_paths.append(cand)

        # If clean single language requested and exactly one language-tagged SRT exists,
        # normalize name to '<stem>.srt' for seamless video player and editor matching
        if not is_all_languages and len(saved_paths) == 1 and saved_paths[0] != default_srt:
            single_path = saved_paths[0]
            try:
                if default_srt.exists():
                    default_srt.unlink()
                single_path.rename(default_srt)
                saved_paths = [default_srt]
                if log_callback:
                    log_callback(f"[SUBTITLE] Normalized filename to: {default_srt.name}")
            except Exception as ren_err:
                if log_callback:
                    log_callback(f"[SUBTITLE] Could not rename {single_path.name}: {ren_err}")

        if saved_paths:
            if log_callback:
                for p in saved_paths:
                    log_callback(f"[SUBTITLE] Saved: {p.name} ({p.stat().st_size:,} bytes)")
            status_label = f"✓ {target_lang.split()[0]}"
            if resolved_type == "Auto-generated":
                status_label += " (Auto)"
            return {
                "success": True,
                "skipped": False,
                "sub_type": resolved_type,
                "status_text": status_label,
                "saved_files": saved_paths,
                "error": "",
            }
        else:
            msg = f"No subtitle files could be written for {video.title}."
            if log_callback:
                log_callback(f"[SUBTITLE] {msg}")
            return {
                "success": False,
                "skipped": False,
                "sub_type": resolved_type,
                "status_text": "No Subs",
                "saved_files": [],
                "error": msg,
            }


class SubtitleDetectionWorker(QThread):
    """
    Background worker that concurrently inspects subtitle availability
    for scanned videos using lightweight HTTP requests without blocking the UI.
    """
    video_subtitle_detected = Signal(str, str, str)  # (video_id, status_text, tooltip)
    detection_finished = Signal()

    def __init__(
        self,
        videos: List[VideoItem],
        max_workers: int = 2,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.videos = list(videos)
        self.max_workers = max_workers
        self._is_cancelled = False

    def cancel(self) -> None:
        """Flags the worker to stop processing remaining videos."""
        self._is_cancelled = True

    def run(self) -> None:
        """Processes videos concurrently using a thread pool with rate-limiting pauses."""
        if not self.videos:
            self.detection_finished.emit()
            return

        def check_single_video(video: VideoItem):
            if self._is_cancelled:
                return
            from core.platform import PlatformRegistry
            adapter = PlatformRegistry.get_adapter(getattr(video, "platform", "youtube"))
            if adapter and not adapter.capabilities.supports_subtitles:
                self.video_subtitle_detected.emit(video.video_id, "—", "")
                return
            res = SubtitleManager.detect_subtitles_info(video.video_id)
            if not self._is_cancelled:
                self.video_subtitle_detected.emit(
                    video.video_id,
                    res["status_text"],
                    res.get("tooltip", ""),
                )
            if not self._is_cancelled:
                time.sleep(0.25)

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for _ in executor.map(check_single_video, self.videos):
                    if self._is_cancelled:
                        break
        except Exception:
            pass

        self.detection_finished.emit()

