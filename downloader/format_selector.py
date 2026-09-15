"""
format_selector.py
Intelligent yt-dlp format and resolution string generator.

Translates high-level user choices (MP4, MKV, WEBM, 1080p, 720p, Bitrate limits)
into optimal yt-dlp stream selection rules.

Key Principles:
1. Does NOT blindly request '-f mp4' (which often grabs low-quality 720p pre-merged files).
2. Requests separate high-definition video (bv*) and audio (ba*) streams and instructs
   FFmpeg to merge them into the user's preferred container.
3. Treats resolution as a MAXIMUM ceiling: if 1080p is unavailable, gracefully falls back
   to the highest available lower resolution without failing.
4. Treats bitrate as a preference: gracefully falls back if no exact bitrate match exists.
"""

from typing import Optional, Tuple
from core.models import DownloadSettings


class FormatSelector:
    """
    Constructs yt-dlp format expressions and container specifications
    based on user settings.
    """

    # Resolution to max pixel height mapping
    QUALITY_MAP = {
        "2160p": 2160,
        "1440p": 1440,
        "1080p": 1080,
        "720p": 720,
        "480p": 480,
        "360p": 360,
        "Best Available": None,
    }

    # Bitrate to max kbps mapping
    BITRATE_MAP = {
        "8000 kbps": 8000,
        "5000 kbps": 5000,
        "3000 kbps": 3000,
        "2000 kbps": 2000,
        "1000 kbps": 1000,
        "Best Available": None,
    }

    # Supported audio extraction formats
    AUDIO_FORMATS = ["MP3", "M4A", "WAV", "AAC", "FLAC", "OPUS"]

    # Audio bitrate mapping for FFmpegExtractAudio
    AUDIO_BITRATE_MAP = {
        "320 kbps": "320",
        "256 kbps": "256",
        "192 kbps": "192",
        "128 kbps": "128",
        "96 kbps": "96",
        "64 kbps": "64",
        "Best Available": None,
    }

    @classmethod
    def get_audio_bitrate_value(cls, bitrate_str: str) -> Optional[str]:
        """Returns string bitrate (e.g. '320') or None if Best Available."""
        return cls.AUDIO_BITRATE_MAP.get(bitrate_str)

    @classmethod
    def get_max_height(cls, quality_str: str) -> Optional[int]:
        """Returns maximum height in pixels or None if Best Available."""
        return cls.QUALITY_MAP.get(quality_str)

    @classmethod
    def get_max_bitrate(cls, bitrate_str: str) -> Optional[int]:
        """Returns maximum bitrate in kbps or None if Best Available."""
        return cls.BITRATE_MAP.get(bitrate_str)

    @classmethod
    def build_format_spec(cls, settings: DownloadSettings) -> Tuple[str, str]:
        """
        Builds the yt-dlp format string and the target container extension.

        Args:
            settings: DownloadSettings instance chosen by user.

        Returns:
            Tuple of (format_string: str, merge_output_format: str)
        """
        target_container = settings.format.lower().strip()
        if target_container not in ("mp4", "mkv", "webm", "mov"):
            target_container = "mp4"

        max_height = cls.get_max_height(settings.quality)
        max_bitrate = cls.get_max_bitrate(settings.bitrate)

        # Height filter clause, e.g. [height<=?1080]
        h_filter = f"[height<=?{max_height}]" if max_height else ""

        # Bitrate filter clause, e.g. [tbr<=?5000]
        tbr_filter = f"[tbr<=?{max_bitrate}]" if max_bitrate else ""

        # Build format rules per container
        if target_container == "mp4":
            # MP4 prefers H.264 (avc1) / MP4 video + AAC (m4a) audio for universal playback
            # Then falls back to any best video + m4a audio, then best video + audio merged to mp4
            format_rules = [
                # 1. Native MP4 video + AAC audio matching bitrate & height
                f"bv*[ext=mp4]{h_filter}{tbr_filter}+ba[ext=m4a]" if (h_filter or tbr_filter) else "bv*[ext=mp4]+ba[ext=m4a]",
                # 2. Native MP4 video matching height
                f"bv*[ext=mp4]{h_filter}+ba[ext=m4a]" if h_filter else None,
                # 3. Best video matching height + best audio (FFmpeg will remux/transcode to MP4)
                f"bv*{h_filter}+ba" if h_filter else "bv*+ba",
                # 4. Fallback to pre-merged stream matching height
                f"b{h_filter}" if h_filter else "b",
                # 5. Final universal fallback
                "bv*+ba/b",
            ]
            merge_ext = "mp4"

        elif target_container == "mov":
            # QuickTime MOV natively requires H.264 (avc1) video + AAC (m4a) audio for clean muxing
            format_rules = [
                f"bv*[vcodec^=avc1]{h_filter}{tbr_filter}+ba[ext=m4a]" if (h_filter or tbr_filter) else "bv*[vcodec^=avc1]+ba[ext=m4a]",
                f"bv*[vcodec^=avc1]{h_filter}+ba[ext=m4a]" if h_filter else None,
                f"bv*[vcodec^=avc1]{h_filter}+ba" if h_filter else "bv*[vcodec^=avc1]+ba",
                f"b[vcodec^=avc1]{h_filter}" if h_filter else "b[vcodec^=avc1]",
                "bv*[ext=mp4]+ba[ext=m4a]",
                "bv*+ba/b",
            ]
            merge_ext = "mov"

        elif target_container == "webm":
            # WEBM prefers VP9/AV1 video + Opus audio
            format_rules = [
                f"bv*[ext=webm]{h_filter}{tbr_filter}+ba[ext=webm]" if (h_filter or tbr_filter) else "bv*[ext=webm]+ba[ext=webm]",
                f"bv*[ext=webm]{h_filter}+ba[ext=webm]" if h_filter else None,
                f"bv*{h_filter}+ba" if h_filter else "bv*+ba",
                f"b{h_filter}" if h_filter else "b",
                "bv*+ba/b",
            ]
            merge_ext = "webm"

        else:  # mkv
            # MKV accepts any modern video and audio codec natively
            format_rules = [
                f"bv*{h_filter}{tbr_filter}+ba" if (h_filter or tbr_filter) else "bv*+ba",
                f"bv*{h_filter}+ba" if h_filter else None,
                f"b{h_filter}" if h_filter else "b",
                "bv*+ba/b",
            ]
            merge_ext = "mkv"

        # Filter out None entries and join with / fallback operator
        valid_rules = [r for r in format_rules if r]
        # Remove duplicate rules while maintaining order
        seen = set()
        deduped = []
        for r in valid_rules:
            if r not in seen:
                seen.add(r)
                deduped.append(r)

        format_string = "/".join(deduped)
        return format_string, merge_ext

    @classmethod
    def build_video_format_spec(cls, settings: DownloadSettings) -> Tuple[str, str]:
        """
        Builds the yt-dlp format string and target container for video download
        (contains both video and audio merged into a complete playable video file).
        """
        return cls.build_format_spec(settings)

    @classmethod
    def build_audio_format_spec(cls, settings: DownloadSettings) -> Tuple[str, str, list]:
        """
        Builds the yt-dlp format string, output audio extension, and postprocessors
        for standalone audio extraction.

        Returns:
            Tuple of (format_string: str, audio_ext: str, postprocessors: list)
        """
        audio_ext = (settings.audio_format or "MP3").lower().strip()
        valid_exts = [fmt.lower() for fmt in cls.AUDIO_FORMATS]
        if audio_ext not in valid_exts:
            audio_ext = "mp3"

        # Stream selector preference
        if audio_ext == "m4a":
            format_spec = "ba[ext=m4a]/ba/b"
        elif audio_ext == "opus":
            format_spec = "ba[ext=webm]/ba/b"
        else:
            format_spec = "ba/b"

        # Postprocessors: extract audio and transcode/remux using FFmpeg
        postprocessor = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_ext,
        }

        bitrate_val = cls.get_audio_bitrate_value(settings.audio_bitrate)
        if bitrate_val and audio_ext in ("mp3", "m4a", "aac", "opus"):
            postprocessor["preferredquality"] = bitrate_val

        return format_spec, audio_ext, [postprocessor]
