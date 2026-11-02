"""
core/media_classifier.py
Media Classification Layer for Channel Harvest.

Accurately classifies extracted items and post components into standardized
media categories (IMAGE, VIDEO, AUDIO, UNKNOWN, UNSUPPORTED) using extractor
metadata, MIME types, codec information, and platform indicators rather than
relying solely on URL file extensions.
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from core.inventory import MediaInventoryType


# Known MIME type prefix / exact mappings
_IMAGE_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
    "image/tiff", "image/avif", "image/heic", "image/heif"
}

_VIDEO_MIME_TYPES = {
    "video/mp4", "video/webm", "video/quicktime", "video/x-matroska",
    "video/ogg", "video/avi", "video/3gpp"
}

_AUDIO_MIME_TYPES = {
    "audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav",
    "audio/flac", "audio/opus", "audio/webm"
}

_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tiff", "avif", "heic", "heif"}
_VIDEO_EXTENSIONS = {"mp4", "webm", "mkv", "mov", "avi", "flv", "m4v", "ts", "3gp"}
_AUDIO_EXTENSIONS = {"mp3", "m4a", "wav", "aac", "flac", "opus", "ogg"}


class MediaClassifier:
    """
    Authoritative classification logic for media items extracted by yt-dlp or gallery-dl.
    """

    @classmethod
    def classify_extracted_item(cls, info: Dict[str, Any], platform: str = "") -> str:
        """
        Classifies an extractor dictionary record into MediaInventoryType.
        Inspects:
        1. Explicit extractor _type, vcodec, acodec, is_video, media_type flags.
        2. Extractor class name or category indicators.
        3. MIME types (e.g. Content-Type header or mime field).
        4. Technical attributes: duration, width/height without vcodec='none'.
        5. File extensions as a guarded secondary signal.
        """
        if not info or not isinstance(info, dict):
            return MediaInventoryType.UNKNOWN

        # 1. Explicit media_type / category property if set by upstream extractor
        explicit_type = info.get("media_type") or info.get("type")
        if explicit_type:
            up_str = str(explicit_type).strip().upper()
            if up_str in ("IMAGE", "PHOTO", "PICTURE"):
                return MediaInventoryType.IMAGE
            if up_str in ("VIDEO", "REEL", "CLIP", "ANIMATION"):
                return MediaInventoryType.VIDEO
            if up_str in ("AUDIO", "MUSIC", "SOUND", "PODCAST"):
                return MediaInventoryType.AUDIO
            if up_str in ("UNSUPPORTED", "NON_MEDIA"):
                return MediaInventoryType.UNSUPPORTED
            if up_str == "UNKNOWN":
                return MediaInventoryType.UNKNOWN

        # 2. Check MIME type if present
        mime = (info.get("mime_type") or info.get("mime") or "").strip().lower()
        if mime:
            if mime in _IMAGE_MIME_TYPES or mime.startswith("image/"):
                return MediaInventoryType.IMAGE
            if mime in _VIDEO_MIME_TYPES or mime.startswith("video/"):
                return MediaInventoryType.VIDEO
            if mime in _AUDIO_MIME_TYPES or mime.startswith("audio/"):
                return MediaInventoryType.AUDIO

        # 3. Check gallery-dl specific item indicators
        # gallery-dl files often have extension, category, or url
        cat = str(info.get("category", "")).lower()
        subcat = str(info.get("subcategory", "")).lower()

        # If extractor category is clearly photo/image
        if "photo" in cat or "photo" in subcat or "image" in cat:
            return MediaInventoryType.IMAGE
        if "video" in cat or "reel" in subcat:
            return MediaInventoryType.VIDEO

        # Reel detection
        web_url = str(info.get("webpage_url") or info.get("url") or "").lower()
        if "/reel/" in web_url or "/reels/" in web_url or info.get("is_reel") is True:
            return MediaInventoryType.REEL

        # 4. Check yt-dlp video/audio properties
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        duration = info.get("duration")
        is_video_flag = info.get("is_video")

        if is_video_flag is True:
            return MediaInventoryType.VIDEO
        if is_video_flag is False and (info.get("is_image") is True or info.get("url", "").endswith(tuple(_IMAGE_EXTENSIONS))):
            return MediaInventoryType.IMAGE

        # If vcodec is present and not 'none':
        if vcodec and vcodec != "none":
            return MediaInventoryType.VIDEO

        # If only acodec is present and vcodec == 'none':
        if vcodec == "none" and acodec and acodec != "none":
            return MediaInventoryType.AUDIO

        # Check duration: videos typically have duration > 0
        if duration is not None and isinstance(duration, (int, float)) and duration > 0:
            return MediaInventoryType.VIDEO

        # 5. Extension fallback
        ext = (info.get("ext") or info.get("extension") or "").strip().lower()
        if not ext and info.get("url"):
            clean_url = info["url"].split("?")[0].split("#")[0]
            if "." in clean_url:
                ext = clean_url.rsplit(".", 1)[-1].lower()

        if ext in _IMAGE_EXTENSIONS:
            return MediaInventoryType.IMAGE
        if ext in _VIDEO_EXTENSIONS:
            return MediaInventoryType.VIDEO
        if ext in _AUDIO_EXTENSIONS:
            return MediaInventoryType.AUDIO

        # 6. Platform specific heuristics
        if platform == "instagram":
            # Instagram carousel child or photo post
            if info.get("__typename") == "GraphImage" or info.get("display_url"):
                return MediaInventoryType.IMAGE
            if info.get("__typename") == "GraphVideo" or info.get("video_url"):
                return MediaInventoryType.VIDEO

        if platform == "facebook":
            if info.get("photo_url") or "photo" in info.get("webpage_url", ""):
                return MediaInventoryType.IMAGE

        return MediaInventoryType.UNKNOWN

    @classmethod
    def decompose_post(
        cls,
        post_dict: Dict[str, Any],
        platform: str,
        discovery_source: str = "auto",
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Decomposes a raw post extraction record into:
        (parent_post_metadata, list_of_child_media_items).

        Correctly preserves multi-media carousels, albums, and mixed media
        without flattening or collapsing multi-image posts.
        """
        post_id = str(post_dict.get("id") or post_dict.get("post_id") or post_dict.get("shortcode") or post_dict.get("code") or "")
        caption = post_dict.get("description") or post_dict.get("caption") or post_dict.get("title") or ""
        author = post_dict.get("uploader") or post_dict.get("channel") or post_dict.get("username") or post_dict.get("author") or ""
        if not author and isinstance(post_dict.get("user"), dict):
            author = post_dict["user"].get("username") or post_dict["user"].get("full_name") or ""
        elif not author and isinstance(post_dict.get("user"), str):
            author = post_dict.get("user")
        pub_date = post_dict.get("upload_date") or post_dict.get("date") or post_dict.get("timestamp")
        post_url = post_dict.get("post_url") or post_dict.get("webpage_url") or post_dict.get("original_url") or post_dict.get("url") or ""

        parent_meta = {
            "platform": platform,
            "post_id": post_id,
            "profile_id": post_dict.get("channel_id") or post_dict.get("uploader_id") or author,
            "original_url": post_url,
            "canonical_url": post_dict.get("webpage_url") or post_url,
            "caption": str(caption).strip() if caption else None,
            "author": str(author).strip() if author else None,
            "publication_date": str(pub_date) if pub_date else None,
            "post_type": "post",
            "discovery_source": discovery_source,
        }

        children = []

        # Check for multi-entry container (e.g. yt-dlp playlist/entries or gallery-dl sub-items)
        entries = post_dict.get("entries")
        gallery_files = post_dict.get("files") or post_dict.get("media")

        if entries and isinstance(entries, list):
            parent_meta["post_type"] = "carousel" if platform == "instagram" else "album"
            for idx, entry in enumerate(entries, start=1):
                if not entry:
                    continue
                m_type = cls.classify_extracted_item(entry, platform=platform)
                m_id = str(entry.get("id") or f"{post_id}_{idx}")
                children.append({
                    "media_id": m_id,
                    "platform": platform,
                    "parent_post_id": post_id,
                    "media_url": entry.get("url") or entry.get("webpage_url"),
                    "media_type": m_type,
                    "media_sequence_index": idx,
                    "media_count": len(entries),
                    "mime_type": entry.get("mime_type"),
                    "extension": entry.get("ext"),
                    "width": entry.get("width"),
                    "height": entry.get("height"),
                    "duration": entry.get("duration"),
                    "discovery_source": discovery_source,
                    "raw_info": entry,
                })

        elif gallery_files and isinstance(gallery_files, list):
            parent_meta["post_type"] = "carousel" if platform == "instagram" else "album"
            for idx, f_item in enumerate(gallery_files, start=1):
                if not f_item:
                    continue
                f_dict = f_item if isinstance(f_item, dict) else {"url": str(f_item)}
                m_type = cls.classify_extracted_item(f_dict, platform=platform)
                m_id = str(f_dict.get("id") or f"{post_id}_{idx}")
                children.append({
                    "media_id": m_id,
                    "platform": platform,
                    "parent_post_id": post_id,
                    "media_url": f_dict.get("url"),
                    "media_type": m_type,
                    "media_sequence_index": idx,
                    "media_count": len(gallery_files),
                    "mime_type": f_dict.get("mime_type"),
                    "extension": f_dict.get("ext"),
                    "width": f_dict.get("width"),
                    "height": f_dict.get("height"),
                    "duration": f_dict.get("duration"),
                    "discovery_source": discovery_source,
                    "raw_info": f_dict,
                })

        else:
            # Single media item or individual gallery-dl record
            m_type = cls.classify_extracted_item(post_dict, platform=platform)
            seq_idx = int(post_dict.get("num") or post_dict.get("media_sequence_index") or 1)
            count = int(post_dict.get("count") or post_dict.get("media_count") or 1)
            if count > 1 or seq_idx > 1:
                parent_meta["post_type"] = "carousel" if platform == "instagram" else "album"
            else:
                parent_meta["post_type"] = "video" if m_type == MediaInventoryType.VIDEO else ("photo" if m_type == MediaInventoryType.IMAGE else "post")
            children.append({
                "media_id": post_dict.get("media_id") or post_dict.get("id"),
                "platform": platform,
                "parent_post_id": post_id,
                "media_url": post_dict.get("url") or post_url,
                "media_type": m_type,
                "media_sequence_index": seq_idx,
                "media_count": count,
                "mime_type": post_dict.get("mime_type"),
                "extension": post_dict.get("ext"),
                "width": post_dict.get("width"),
                "height": post_dict.get("height"),
                "duration": post_dict.get("duration"),
                "discovery_source": discovery_source,
                "raw_info": post_dict,
            })
        return parent_meta, children
