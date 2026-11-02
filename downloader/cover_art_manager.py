"""
cover_art_manager.py
YouTube Music / Art Track 1:1 Cover Art extraction, download, and ID3 tag embedding engine.

Features:
- Primary Layer: Queries YouTube Music Innertube API (WEB_REMIX) to retrieve original,
  unmodified 1:1 square master album artwork hosted on Google CDN (yt3/lh3.googleusercontent.com).
  Appends '=s0' to fetch maximum resolution (e.g., 1400x1400 or higher) without video borders.
- Fallback Layer: If native master art is not available on CDN but media is an Art Track/Topic track,
  downloads the highest-resolution video thumbnail and performs center 1:1 square crop via Pillow.
- Fast Header Parsing: Determines cover art dimensions in milliseconds using Range requests and
  Pillow ImageFile.Parser without downloading full multi-megabyte payloads during scan detection.
- Standalone File Download: Saves standalone 1:1 cover art files (e.g. '<stem>_cover.jpg').
- Audio Tag Embedding: Embeds 1:1 Cover Art into audio files (MP3 ID3 APIC, M4A/MP4 covr, FLAC,
  Opus) using bundled FFmpeg lossless stream copy (-c copy).
- Background Worker: CoverArtDetectionWorker runs off the UI thread to keep the interface smooth.
"""

import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable

from PIL import Image, ImageFile
from PySide6.QtCore import QThread, Signal, QObject

from core.models import VideoItem, DownloadSettings
from core.paths import resolve_media_filename, sanitize_filename, get_bundled_executable, get_temp_dir


SUPPORTED_COVER_ART_AUDIO_FORMATS = {"MP3", "M4A", "FLAC", "OPUS"}
UNSUPPORTED_COVER_ART_AUDIO_FORMATS = {"WAV", "AAC"}
SUPPORTED_COVER_ART_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".opus", ".ogg"}


class CoverArtManager:
    """
    Manages detection, retrieval, and audio embedding of 1:1 square Cover Art.
    """

    @classmethod
    def is_format_supported(cls, fmt: str) -> bool:
        """Checks if an audio container format supports embedded cover art."""
        if not fmt:
            return False
        clean = fmt.strip().lstrip(".").upper()
        return clean in SUPPORTED_COVER_ART_AUDIO_FORMATS

    INNERTUBE_URL = "https://music.youtube.com/youtubei/v1/next?prettyPrint=false"
    INNERTUBE_BROWSE_URL = "https://music.youtube.com/youtubei/v1/browse?prettyPrint=false"
    INNERTUBE_SEARCH_URL = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "67",
        "X-YouTube-Client-Version": "1.20231215.01.00",
        "Origin": "https://music.youtube.com",
    }

    @classmethod
    def extract_playlist_or_album_id(cls, url_or_id: Optional[str]) -> Optional[str]:
        """
        Extracts a clean YouTube / YouTube Music playlist ID or album release ID from a URL or raw ID.
        Supports:
        - OLAK5uy_... (YouTube Music album playlist)
        - MPREb_... (YouTube Music album release ID)
        - PL... / RD... (Standard YouTube playlists)
        - URLs with ?list=... or /browse/MPREb_... or /album/...
        """
        if not url_or_id:
            return None
        text = str(url_or_id).strip()

        # Direct IDs (e.g. OLAK5uy_..., MPREb_..., PL..., VLOLAK5uy_...)
        match_direct = re.match(r"^(?:VL)?(OLAK5uy_[a-zA-Z0-9_-]+|MPREb_[a-zA-Z0-9_-]+|PL[a-zA-Z0-9_-]+|RD[a-zA-Z0-9_-]+)$", text)
        if match_direct:
            return match_direct.group(1)

        # Query param list=...
        list_match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", text)
        if list_match:
            pid = list_match.group(1)
            if pid.startswith("VL"):
                pid = pid[2:]
            return pid

        # Path /browse/MPREb_... or /playlist/OLAK... or /album/MPREb_...
        path_match = re.search(r"/(?:browse|album|playlist)/((?:MPREb_|OLAK5uy_|PL)[a-zA-Z0-9_-]+)", text)
        if path_match:
            pid = path_match.group(1)
            if pid.startswith("VL"):
                pid = pid[2:]
            return pid

        return None

    @classmethod
    def detect_album_cover_art(cls, album_or_playlist_id: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
        """
        Retrieves original 1:1 square master album artwork hosted on Google CDN for an album or playlist
        via the YouTube Music Innertube /browse endpoint.

        Returns:
            Dict with 'source' ('innertube_master'), 'url', 'width', 'height', 'is_album': True,
            or None if not found.
        """
        clean_id = cls.extract_playlist_or_album_id(album_or_playlist_id) or album_or_playlist_id
        if not clean_id:
            return None

        # Build browseId: MPREb_ IDs are used directly, playlist IDs use 'VL' prefix
        if clean_id.startswith("MPREb_") or clean_id.startswith("VL"):
            browse_id = clean_id
        else:
            browse_id = f"VL{clean_id}"

        body = {
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20231215.01.00",
                    "hl": "en",
                    "gl": "US",
                }
            },
            "browseId": browse_id,
        }
        headers = dict(cls.DEFAULT_HEADERS)
        headers["Referer"] = f"https://music.youtube.com/browse/{browse_id}"

        try:
            req = urllib.request.Request(
                cls.INNERTUBE_BROWSE_URL,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            payload_str = json.dumps(data)
            matches = re.findall(
                r'https://[a-zA-Z0-9_-]+\.googleusercontent\.com/[a-zA-Z0-9_-]+',
                payload_str,
            )
            if matches:
                base_url = matches[0]
                master_url = f"{base_url}=s0"
                w, h = cls._probe_image_dimensions(master_url)
                if w <= 0 or h <= 0:
                    w, h = 1400, 1400

                album_title = None
                try:
                    header = data.get("header", {})
                    for k in (
                        "musicDetailHeaderRenderer",
                        "musicResponsiveHeaderRenderer",
                        "musicVisualHeaderRenderer",
                        "musicImmersiveHeaderRenderer",
                    ):
                        sub = header.get(k)
                        if sub and "title" in sub:
                            runs = sub["title"].get("runs", [])
                            if runs and "text" in runs[0]:
                                album_title = runs[0]["text"]
                                break
                    if not album_title:
                        edit_hdr = header.get("musicEditablePlaylistDetailHeaderRenderer", {}).get("header", {})
                        sub = edit_hdr.get("musicResponsiveHeaderRenderer") or edit_hdr.get("musicDetailHeaderRenderer")
                        if sub and "title" in sub:
                            runs = sub["title"].get("runs", [])
                            if runs and "text" in runs[0]:
                                album_title = runs[0]["text"]
                except Exception:
                    pass

                result = {
                    "source": "innertube_master",
                    "url": master_url,
                    "width": w,
                    "height": h,
                    "is_album": True,
                }
                if album_title:
                    result["album"] = album_title
                return result
        except Exception:
            pass

        return None

    @classmethod
    def _clean_song_query(cls, title: str, artist: str = "") -> str:
        """Cleans video title boilerplate (e.g. MV, 4K, Official, brackets) for YouTube Music search."""
        if not title:
            return (artist or "").strip()

        t = title
        # Remove bracketed metadata noise
        t = re.sub(r'【(?:Official\s*)?(?:Music\s*)?Video.*?】', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'\[(?:Official\s*)?(?:Music\s*)?Video.*?\]', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'\((?:Official\s*)?(?:Music\s*)?Video.*?\)', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'【(?:官方)?(?:音乐|歌词|完整)?\s*MV.*?】', ' ', t, flags=re.IGNORECASE)
        # Extract content from remaining brackets: e.g. 【车站 Farewell Station】 -> 车站 Farewell Station
        t = re.sub(r'[【\[](.*?)[】\]]', r' \1 ', t)
        # Remove video tags
        t = re.sub(r'(?:Official\s*)?(?:Music\s*)?Video', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'(?:官方|歌词版|Lyrics|Full)?\s*MV', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'歌词版|官方版|高清版|完整版|高品质', ' ', t)
        # Replace separators
        t = re.sub(r'[-–—|/•·_~]', ' ', t)
        # Consolidate whitespace
        t = ' '.join(t.split())
        if artist and artist.lower() not in t.lower():
            t = f"{artist} {t}"
        return t.strip()

    @classmethod
    def _search_music_album_cover_art(cls, query: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
        """
        Searches YouTube Music for an MV's corresponding song/album to retrieve original 1:1 master cover art.
        """
        if not query or not query.strip():
            return None

        body = {
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20231215.01.00",
                    "hl": "en",
                    "gl": "US",
                }
            },
            "query": query.strip(),
        }
        headers = dict(cls.DEFAULT_HEADERS)
        headers["Referer"] = "https://music.youtube.com/search"

        try:
            req = urllib.request.Request(
                cls.INNERTUBE_SEARCH_URL,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            payload_str = json.dumps(data)
            matches = re.findall(
                r'https://[a-zA-Z0-9_-]+\.googleusercontent\.com/[a-zA-Z0-9_-]+',
                payload_str,
            )
            if matches:
                base_url = matches[0]
                master_url = f"{base_url}=s0"
                w, h = cls._probe_image_dimensions(master_url)
                if w <= 0 or h <= 0:
                    w, h = 1400, 1400
                return {
                    "source": "innertube_master",
                    "url": master_url,
                    "width": w,
                    "height": h,
                    "is_search_matched": True,
                }
        except Exception:
            pass

        return None

    @classmethod
    def detect_cover_art(
        cls,
        video_id: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        playlist_id: Optional[str] = None,
        timeout: int = 8,
    ) -> Optional[Dict[str, Any]]:
        """
        Detects whether a YouTube video ID has 1:1 Cover Art and resolves its dimensions.
        Prioritizes:
        1. Original album artwork via playlist_id/album browse.
        2. Innertube /next Google CDN master artwork (Art Tracks / Topic tracks).
        3. YouTube Music search for MV tracks (Official Music Videos mapped to albums).
        4. Video thumbnail center-crop fallback.

        Returns:
            Dict with keys: 'url', 'width', 'height', 'source' ('innertube_master' or 'center_crop'),
            or None if no cover art is found.
        """
        if not video_id:
            return None

        # 1. If playlist or album ID provided, check album master art first
        if playlist_id:
            album_info = cls.detect_album_cover_art(playlist_id, timeout=timeout)
            if album_info and album_info.get("source") == "innertube_master":
                return album_info

        body = {
            "context": {
                "client": {
                    "clientName": "WEB_REMIX",
                    "clientVersion": "1.20231215.01.00",
                    "hl": "en",
                    "gl": "US",
                }
            },
            "enablePersistentPlaylistPanel": True,
            "isAudioOnly": True,
            "videoId": video_id,
        }

        headers = dict(cls.DEFAULT_HEADERS)
        headers["Referer"] = f"https://music.youtube.com/watch?v={video_id}"

        data = None
        payload_str = ""
        try:
            req = urllib.request.Request(
                cls.INNERTUBE_URL,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            payload_str = json.dumps(data)
        except Exception:
            data = None
            payload_str = ""

        # ---------------------------------------------------------------------
        # 2. Primary Layer: Google CDN 1:1 master Cover Art (googleusercontent)
        # ---------------------------------------------------------------------
        if payload_str:
            matches = re.findall(
                r'https://[a-zA-Z0-9_-]+\.googleusercontent\.com/[a-zA-Z0-9_-]+',
                payload_str,
            )
            if matches:
                base_url = matches[0]
                master_url = f"{base_url}=s0"
                w, h = cls._probe_image_dimensions(master_url)
                if w <= 0 or h <= 0:
                    # Default fallback resolution for high-res master art if probe fails
                    w, h = 1400, 1400
                return {
                    "source": "innertube_master",
                    "url": master_url,
                    "width": w,
                    "height": h,
                }

        # ---------------------------------------------------------------------
        # 3. MV Track Layer: For official Music Videos lacking CDN art in /next,
        #    search YouTube Music using song title/artist to retrieve original album art.
        # ---------------------------------------------------------------------
        search_query = None
        if data:
            try:
                panel = (
                    data.get("contents", {})
                    .get("singleColumnMusicWatchNextResultsRenderer", {})
                    .get("tabbedRenderer", {})
                    .get("watchNextTabbedResultsRenderer", {})
                    .get("tabs", [{}])[0]
                    .get("tabRenderer", {})
                    .get("content", {})
                    .get("musicQueueRenderer", {})
                    .get("content", {})
                    .get("playlistPanelRenderer", {})
                    .get("contents", [{}])[0]
                    .get("playlistPanelVideoRenderer", {})
                )
                runs_title = panel.get("title", {}).get("runs", [])
                p_title = runs_title[0].get("text", "") if runs_title else ""
                runs_author = panel.get("shortBylineText", {}).get("runs", [])
                p_author = runs_author[0].get("text", "") if runs_author else ""
                if p_title:
                    search_query = f"{p_title} {p_author}".strip()
            except Exception:
                search_query = None

        if not search_query and (title or artist):
            search_query = cls._clean_song_query(title or "", artist or "")

        if search_query:
            search_info = cls._search_music_album_cover_art(search_query, timeout=timeout)
            if search_info and search_info.get("source") == "innertube_master":
                return search_info

        # ---------------------------------------------------------------------
        # 4. Fallback Layer: Topic track video thumbnail center-crop from payload
        # ---------------------------------------------------------------------
        if payload_str:
            ytimg_matches = re.findall(
                r'https://i\.ytimg\.com/vi/[^/]+/(?:maxresdefault|hq720|sddefault|hqdefault)\.jpg[^"\'\s\\]*',
                payload_str,
            )
            if ytimg_matches:
                thumb_url = ytimg_matches[0]
                if "maxresdefault" in thumb_url:
                    h = 1080
                elif "hq720" in thumb_url:
                    h = 720
                elif "sddefault" in thumb_url:
                    h = 480
                else:
                    h = 360
                return {
                    "source": "center_crop",
                    "url": thumb_url,
                    "width": h,
                    "height": h,
                }

        # ---------------------------------------------------------------------
        # 5. Direct YouTube CDN Fallback Layer
        # ---------------------------------------------------------------------
        for res_name, dim in [("maxresdefault.jpg", 1080), ("hq720.jpg", 720), ("sddefault.jpg", 480), ("hqdefault.jpg", 360)]:
            cand_url = f"https://i.ytimg.com/vi/{video_id}/{res_name}"
            w_p, h_p = cls._probe_image_dimensions(cand_url, timeout=2)
            if w_p > 0 and h_p > 0:
                side = min(w_p, h_p)
                return {
                    "source": "center_crop",
                    "url": cand_url,
                    "width": side,
                    "height": side,
                }

        return None

    @classmethod
    def _probe_image_dimensions(cls, image_url: str, timeout: int = 3) -> Tuple[int, int]:
        """
        Fast dimension probe reading only the first few KB using Pillow ImageFile.Parser.
        """
        try:
            req = urllib.request.Request(
                image_url,
                headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-8192"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                chunk = resp.read()
                parser = ImageFile.Parser()
                parser.feed(chunk)
                if parser.image:
                    return parser.image.size
        except Exception:
            pass
        return (0, 0)

    @classmethod
    def detect_cover_art_for_videos(
        cls,
        videos: List[VideoItem],
        playlist_id: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Scans candidate videos in the list or playlist context to determine if Cover Art is available.
        Checks album master artwork first if playlist_id or source_url is present.
        """
        if not videos:
            return None

        # 1. Check if album/playlist cover art is available
        resolved_pid = playlist_id
        if not resolved_pid and source_url:
            resolved_pid = cls.extract_playlist_or_album_id(source_url)
        if not resolved_pid:
            # Check if any video has playlist_id in extra_metadata
            for v in videos:
                pid = v.extra_metadata.get("playlist_id") if hasattr(v, "extra_metadata") else None
                if pid:
                    resolved_pid = pid
                    break

        if resolved_pid:
            album_info = cls.detect_album_cover_art(resolved_pid)
            if album_info and album_info.get("source") == "innertube_master":
                for v in videos:
                    v.cover_art_url = album_info.get("url")
                    v.cover_art_width = album_info.get("width")
                    v.cover_art_height = album_info.get("height")
                    v._cover_info = album_info
                    if album_info.get("album") and hasattr(v, "extra_metadata") and not v.extra_metadata.get("album"):
                        v.extra_metadata["album"] = album_info.get("album")
                return album_info

        # 2. Candidate video detection with search fallback
        candidates = [v for v in videos if v.video_id and not v.is_inaccessible][:3]
        for v in candidates:
            v_pid = (v.extra_metadata.get("playlist_id") if hasattr(v, "extra_metadata") else None) or resolved_pid
            info = cls.detect_cover_art(
                video_id=v.video_id,
                title=getattr(v, "title", None),
                artist=getattr(v, "channel_title", None),
                playlist_id=v_pid,
            )
            if info:
                # Cache on video item for subsequent download
                v.cover_art_url = info.get("url")
                v.cover_art_width = info.get("width")
                v.cover_art_height = info.get("height")
                v._cover_info = info
                if info.get("album") and hasattr(v, "extra_metadata") and not v.extra_metadata.get("album"):
                    v.extra_metadata["album"] = info.get("album")
                # If master album art was resolved, propagate to all videos in list
                if info.get("source") == "innertube_master":
                    for other in videos:
                        if other is not v and not getattr(other, "cover_art_url", None):
                            other.cover_art_url = info.get("url")
                            other.cover_art_width = info.get("width")
                            other.cover_art_height = info.get("height")
                            other._cover_info = info
                            if info.get("album") and hasattr(other, "extra_metadata") and not other.extra_metadata.get("album"):
                                other.extra_metadata["album"] = info.get("album")
                return info

        return None

    @classmethod
    def download_cover_art(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        album: Optional[str] = None,
        info_dict: Optional[Dict[str, Any]] = None,
        downloaded_covers: Optional[set] = None,
    ) -> Dict[str, Any]:
        """
        Downloads 1:1 Cover Art and saves it as an image file in target_dir.
        If an album is identified, saves as '<album_name>.jpg' and skips duplicate
        downloads across tracks of the same album.
        Otherwise falls back to '<stem>_cover.jpg'.
        """
        if cancel_check and cancel_check():
            return {"success": False, "saved_file": None, "error": "Cancelled by user"}

        cover_info = getattr(video, "_cover_info", None)
        if not cover_info and getattr(video, "cover_art_url", None):
            cover_info = {
                "source": "innertube_master" if "googleusercontent" in video.cover_art_url else "center_crop",
                "url": video.cover_art_url,
                "width": getattr(video, "cover_art_width", 0) or 0,
                "height": getattr(video, "cover_art_height", 0) or 0,
            }
        if not cover_info:
            v_pid = video.extra_metadata.get("playlist_id") if hasattr(video, "extra_metadata") else None
            cover_info = cls.detect_cover_art(
                video_id=video.video_id,
                title=getattr(video, "title", None),
                artist=getattr(video, "channel_title", None),
                playlist_id=v_pid,
            )

        eff_album = (
            album
            or (info_dict.get("album") if info_dict else None)
            or getattr(video, "extra_metadata", {}).get("album")
            or (cover_info.get("album") if cover_info else None)
        )
        clean_album = ""
        if eff_album:
            cand = str(eff_album).strip()
            if cand.lower().startswith("album - "):
                cand = cand[8:].strip()
            if cand.lower() not in ("unknown", "unknown album", "untitled", "various artists", "various", "none"):
                clean_album = sanitize_filename(cand)

        target_dir.mkdir(parents=True, exist_ok=True)

        if clean_album:
            dest_file = target_dir / f"{clean_album}.jpg"
            is_album_cover = True
        else:
            include_id = getattr(settings, "include_video_id_in_filename", False)
            num_prefix = getattr(settings, "number_prefix", "")
            stem = resolve_media_filename(
                video.title,
                video.video_id,
                include_video_id=include_id,
                target_dir=target_dir,
                number_prefix=num_prefix,
            )
            dest_file = target_dir / f"{stem}_cover.jpg"
            is_album_cover = False

        dest_key = str(dest_file.resolve()).lower()
        url_key = cover_info.get("url") if cover_info else None

        already_downloaded = False
        if downloaded_covers is not None:
            if dest_key in downloaded_covers:
                already_downloaded = True
            elif is_album_cover and url_key and url_key in downloaded_covers:
                already_downloaded = True

        if not already_downloaded and dest_file.is_file() and dest_file.stat().st_size > 0:
            if is_album_cover or settings.skip_existing:
                already_downloaded = True

        if already_downloaded and dest_file.is_file() and dest_file.stat().st_size > 0:
            if log_callback:
                if is_album_cover:
                    log_callback(f"[Cover Art] Album cover already exists for '{clean_album}': {dest_file.name}. Skipping duplicate download.")
                else:
                    log_callback(f"[ARCHIVE] Cover Art already exists: {dest_file.name}. Skipping.")
            if downloaded_covers is not None:
                downloaded_covers.add(dest_key)
                if url_key:
                    downloaded_covers.add(url_key)
            return {"success": True, "saved_file": dest_file, "skipped": True}

        if not cover_info:
            return {"success": False, "saved_file": None, "error": "No cover art found"}

        source_type = cover_info.get("source", "innertube_master")
        image_url = cover_info.get("url", "")
        w = cover_info.get("width", 0)
        h = cover_info.get("height", 0)

        if log_callback:
            dims_str = f" ({w}x{h})" if w and h else ""
            log_callback(f"[Cover Art] Downloading 1:1 album art: {video.title}{dims_str}")

        try:
            if source_type == "innertube_master":
                req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    img_bytes = r.read()
                try:
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        if img.format == "JPEG":
                            with open(dest_file, "wb") as f:
                                f.write(img_bytes)
                        else:
                            img.convert("RGB").save(dest_file, "JPEG", quality=95)
                except Exception:
                    with open(dest_file, "wb") as f:
                        f.write(img_bytes)
            else:
                # Center crop from 16:9 thumbnail
                req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    raw_bytes = r.read()
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    orig_w, orig_h = img.size
                    side = min(orig_w, orig_h)
                    left = (orig_w - side) // 2
                    top = (orig_h - side) // 2
                    cropped = img.crop((left, top, left + side, top + side))
                    cropped.save(dest_file, "JPEG", quality=95)

            if downloaded_covers is not None:
                downloaded_covers.add(dest_key)
                if url_key:
                    downloaded_covers.add(url_key)

            if log_callback:
                log_callback(f"[Cover Art] Saved: {dest_file.name}")
            return {"success": True, "saved_file": dest_file, "skipped": False}

        except Exception as e:
            if log_callback:
                log_callback(f"[WARNING] Failed to download Cover Art: {e}")
            return {"success": False, "saved_file": None, "error": str(e)}

    @classmethod
    def _resolve_ffmpeg_executable(cls, ffmpeg_location: Optional[str] = None) -> str:
        """
        Resolves the full path to the ffmpeg executable.
        Correctly handles directory paths (e.g. from FFmpegChecker.get_ffmpeg_directory())
        as well as direct file paths.
        """
        if ffmpeg_location:
            loc = Path(ffmpeg_location)
            if loc.is_file():
                return str(loc)
            if loc.is_dir():
                cand = loc / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                if cand.is_file():
                    return str(cand)
        bundled = get_bundled_executable("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if bundled and Path(bundled).is_file():
            return str(bundled)
        return "ffmpeg"

    @classmethod
    def _resolve_ffprobe_executable(cls, ffmpeg_location: Optional[str] = None) -> str:
        """
        Resolves the full path to the ffprobe executable.
        Correctly handles directory paths as well as direct file paths.
        """
        if ffmpeg_location:
            loc = Path(ffmpeg_location)
            if loc.is_file():
                probe = loc.parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
                if probe.is_file():
                    return str(probe)
            elif loc.is_dir():
                probe = loc / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
                if probe.is_file():
                    return str(probe)
        bundled = get_bundled_executable("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if bundled and Path(bundled).is_file():
            return str(bundled)
        return "ffprobe"

    @classmethod
    def _has_video_stream(cls, path: Path, ffmpeg_location: Optional[str] = None) -> bool:
        """Determines if media_path contains an existing video stream."""
        ext = path.suffix.lower()
        if ext in (".mp3", ".m4a", ".aac", ".flac", ".opus", ".ogg", ".wav"):
            return False
        ffprobe_bin = cls._resolve_ffprobe_executable(ffmpeg_location)
        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            cmd = [
                str(ffprobe_bin), "-v", "error",
                "-select_streams", "v",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(path)
            ]
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                startupinfo=startupinfo,
            )
            return "video" in r.stdout.lower()
        except Exception:
            return True

    @classmethod
    def embed_cover_art_for_media_files(
        cls,
        video: VideoItem,
        media_paths: List[Path],
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Embeds 1:1 Cover Art and audio metadata into a list of downloaded media files for a single video.
        Downloads or reuses the cover art image file once for all files.
        """
        if cancel_check and cancel_check():
            return False
        valid_paths = [p for p in media_paths if p.is_file()]
        if not valid_paths:
            return False

        include_id = getattr(settings, "include_video_id_in_filename", False)
        num_prefix = getattr(settings, "number_prefix", "")
        stem = resolve_media_filename(
            video.title,
            video.video_id,
            include_video_id=include_id,
            target_dir=target_dir,
            number_prefix=num_prefix,
        )

        album_val = (metadata.get("album") if metadata else None) or getattr(video, "extra_metadata", {}).get("album")
        clean_album = ""
        if album_val:
            cand = str(album_val).strip()
            if cand.lower().startswith("album - "):
                cand = cand[8:].strip()
            if cand.lower() not in ("unknown", "unknown album", "untitled", "various artists", "various", "none"):
                clean_album = sanitize_filename(cand)

        cover_file = None
        if clean_album:
            album_cand = target_dir / f"{clean_album}.jpg"
            if album_cand.is_file() and album_cand.stat().st_size > 0:
                cover_file = album_cand

        if not cover_file:
            single_cand = target_dir / f"{stem}_cover.jpg"
            if single_cand.is_file() and single_cand.stat().st_size > 0:
                cover_file = single_cand

        if not cover_file:
            if not getattr(settings, "download_cover_art", False):
                # When user only requests tag embedding without saving cover art,
                # cache temporarily in safe temp directory so target_dir isn't polluted
                temp_dir = get_temp_dir()
                if clean_album:
                    temp_cand = temp_dir / f"{clean_album}.jpg"
                else:
                    temp_cand = temp_dir / f"{stem}_cover.jpg"

                if temp_cand.is_file() and temp_cand.stat().st_size > 0:
                    cover_file = temp_cand
                else:
                    res = cls.download_cover_art(
                        video=video,
                        settings=settings,
                        target_dir=temp_dir,
                        log_callback=log_callback,
                        cancel_check=cancel_check,
                        album=album_val,
                    )
                    if not res.get("success") or not res.get("saved_file"):
                        return False
                    cover_file = res["saved_file"]
            else:
                res = cls.download_cover_art(
                    video=video,
                    settings=settings,
                    target_dir=target_dir,
                    log_callback=log_callback,
                    cancel_check=cancel_check,
                    album=album_val,
                )
                if not res.get("success") or not res.get("saved_file"):
                    return False
                cover_file = res["saved_file"]

        if not cover_file or not cover_file.is_file():
            return False

        any_success = False
        for p in valid_paths:
            if cancel_check and cancel_check():
                break
            succ = cls.embed_cover_art(
                media_path=p,
                cover_image_path=cover_file,
                ffmpeg_location=ffmpeg_location,
                log_callback=log_callback,
                metadata=metadata,
            )
            if succ:
                any_success = True

        return any_success

    @classmethod
    def embed_cover_art_for_video(
        cls,
        video: VideoItem,
        media_path: Path,
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Embeds 1:1 Cover Art and metadata into a single downloaded media file."""
        return cls.embed_cover_art_for_media_files(
            video=video,
            media_paths=[media_path],
            settings=settings,
            target_dir=target_dir,
            ffmpeg_location=ffmpeg_location,
            log_callback=log_callback,
            cancel_check=cancel_check,
            metadata=metadata,
        )

    @classmethod
    def embed_metadata(
        cls,
        media_path: Path,
        metadata: Dict[str, str],
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Executes FFmpeg stream copy to embed metadata tags (title, artist, album, date, etc.)
        into media_path without requiring a cover art image.
        """
        if not media_path.is_file() or not metadata:
            return False

        ffmpeg_bin = cls._resolve_ffmpeg_executable(ffmpeg_location)
        ext = media_path.suffix.lower()
        if ext in (".wav", ".aac"):
            if log_callback:
                log_callback(f"[Metadata] Audio format {ext.upper()} does not support embedded metadata tags.")
            return False

        temp_out = media_path.with_name(f"{media_path.stem}.tmp_meta{ext}")

        meta_args = []
        for k, v in metadata.items():
            if v is not None and str(v).strip():
                meta_args.extend(["-metadata", f"{k}={str(v).strip()}"])

        if not meta_args:
            return True

        if ext == ".mp3":
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-map", "0:a",
                "-map_metadata", "0",
                "-c", "copy",
                "-id3v2_version", "3",
            ] + meta_args + [str(temp_out)]
        elif ext in (".m4a", ".flac", ".opus", ".ogg"):
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-map", "0:a",
                "-map_metadata", "0",
                "-c", "copy",
            ] + meta_args + [str(temp_out)]
        elif ext in (".mp4", ".mov", ".mkv", ".webm"):
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-map", "0",
                "-map_metadata", "0",
                "-c", "copy",
            ] + meta_args + [str(temp_out)]
        else:
            return False

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                timeout=30,
            )

            if proc.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 0:
                import time
                replaced = False
                for _ in range(6):
                    try:
                        temp_out.replace(media_path)
                        replaced = True
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.15)
                if replaced:
                    if log_callback:
                        log_callback(f"[Metadata] Embedded media metadata tags into: {media_path.name}")
                    return True
                else:
                    if log_callback:
                        log_callback(f"[WARNING] Could not replace {media_path.name} (file locked).")
                    if temp_out.is_file():
                        try:
                            temp_out.unlink()
                        except Exception:
                            pass
                    return False
            else:
                if temp_out.is_file():
                    try:
                        temp_out.unlink()
                    except Exception:
                        pass
                if log_callback:
                    err_hint = proc.stderr.splitlines()[-1] if proc.stderr else "Unknown error"
                    log_callback(f"[WARNING] FFmpeg metadata embed failed: {err_hint}")
                return False
        except Exception as e:
            if temp_out.is_file():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            if log_callback:
                log_callback(f"[WARNING] Metadata embed exception: {e}")
            return False

    @classmethod
    def embed_metadata_for_media_files(
        cls,
        media_paths: List[Path],
        metadata: Dict[str, str],
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Embeds metadata tags into a list of downloaded media files."""
        if cancel_check and cancel_check():
            return False
        valid_paths = [p for p in media_paths if p.is_file()]
        if not valid_paths or not metadata:
            return False

        any_success = False
        for p in valid_paths:
            if cancel_check and cancel_check():
                break
            succ = cls.embed_metadata(
                media_path=p,
                metadata=metadata,
                ffmpeg_location=ffmpeg_location,
                log_callback=log_callback,
            )
            if succ:
                any_success = True
        return any_success

    @classmethod
    def embed_cover_art(
        cls,
        media_path: Path,
        cover_image_path: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Executes FFmpeg stream copy to embed cover image into media_path ID3 / metadata tag,
        along with any provided metadata tags (title, artist, album, date, etc.).
        """
        if not media_path.is_file() or not cover_image_path.is_file():
            return False

        ffmpeg_bin = cls._resolve_ffmpeg_executable(ffmpeg_location)
        ext = media_path.suffix.lower()
        if ext in (".wav", ".aac"):
            if log_callback:
                log_callback(f"[Cover Art] Audio format {ext.upper()} does not support embedded cover art.")
            return False

        temp_out = media_path.with_name(f"{media_path.stem}.tmp_embed{ext}")

        # Build optional metadata arguments (-metadata key=value)
        meta_args = []
        if metadata:
            for k, v in metadata.items():
                if v is not None and str(v).strip():
                    meta_args.extend(["-metadata", f"{k}={str(v).strip()}"])

        if ext == ".mp3":
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-i", str(cover_image_path),
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "0",
                "-c", "copy",
                "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
            ] + meta_args + [str(temp_out)]
        elif ext in (".m4a",):
            # Audio-only container: cover art is the sole video stream in output (v:0)
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-i", str(cover_image_path),
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "0",
                "-c", "copy",
                "-disposition:v:0", "attached_pic",
            ] + meta_args + [str(temp_out)]
        elif ext in (".flac",):
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-i", str(cover_image_path),
                "-map", "0:a",
                "-map", "1:v",
                "-map_metadata", "0",
                "-c", "copy",
                "-disposition:v:0", "attached_pic",
            ] + meta_args + [str(temp_out)]
        elif ext in (".opus", ".ogg"):
            try:
                import base64
                import struct
                img_bytes = cover_image_path.read_bytes()
                try:
                    with Image.open(cover_image_path) as im:
                        img_w, img_h = im.size
                except Exception:
                    img_w, img_h = 1400, 1400
                mime = b"image/jpeg" if cover_image_path.suffix.lower() in (".jpg", ".jpeg") else b"image/png"
                desc = b""
                block = (
                    struct.pack(">I", 3) +
                    struct.pack(">I", len(mime)) + mime +
                    struct.pack(">I", len(desc)) + desc +
                    struct.pack(">IIII", img_w, img_h, 24, 0) +
                    struct.pack(">I", len(img_bytes)) + img_bytes
                )
                b64 = base64.b64encode(block).decode("ascii")
                cmd = [
                    str(ffmpeg_bin), "-y",
                    "-i", str(media_path),
                    "-map_metadata", "0",
                    "-c", "copy",
                    "-metadata", f"METADATA_BLOCK_PICTURE={b64}",
                ] + meta_args + [str(temp_out)]
            except Exception as e:
                if log_callback:
                    log_callback(f"[WARNING] Opus cover art block prep failed: {e}")
                return False
        elif ext in (".mp4", ".mov", ".mkv"):
            has_video = cls._has_video_stream(media_path, ffmpeg_location)
            if has_video:
                # Video stream exists (v:0): attached picture is v:1
                cmd = [
                    str(ffmpeg_bin), "-y",
                    "-i", str(media_path),
                    "-i", str(cover_image_path),
                    "-map", "0",
                    "-map", "1",
                    "-map_metadata", "0",
                    "-c", "copy",
                    "-disposition:v:1", "attached_pic",
                ] + meta_args + [str(temp_out)]
            else:
                # Audio-only stream in mp4 container: attached picture is v:0
                cmd = [
                    str(ffmpeg_bin), "-y",
                    "-i", str(media_path),
                    "-i", str(cover_image_path),
                    "-map", "0:a",
                    "-map", "1:v",
                    "-map_metadata", "0",
                    "-c", "copy",
                    "-disposition:v:0", "attached_pic",
                ] + meta_args + [str(temp_out)]
        else:
            # Fallback copy
            cmd = [
                str(ffmpeg_bin), "-y",
                "-i", str(media_path),
                "-i", str(cover_image_path),
                "-map", "0",
                "-map", "1",
                "-map_metadata", "0",
                "-c", "copy",
                "-disposition:v:0", "attached_pic",
            ] + meta_args + [str(temp_out)]

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=startupinfo,
                timeout=30,
            )

            if proc.returncode == 0 and temp_out.is_file() and temp_out.stat().st_size > 0:
                import time
                replaced = False
                for _ in range(6):
                    try:
                        temp_out.replace(media_path)
                        replaced = True
                        break
                    except (PermissionError, OSError):
                        time.sleep(0.15)
                if replaced:
                    if log_callback:
                        log_callback(f"[Cover Art] Embedded 1:1 Cover Art into: {media_path.name}")
                    return True
                else:
                    if log_callback:
                        log_callback(f"[WARNING] Could not replace {media_path.name} (file locked).")
                    if temp_out.is_file():
                        try:
                            temp_out.unlink()
                        except Exception:
                            pass
                    return False
            else:
                if temp_out.is_file():
                    try:
                        temp_out.unlink()
                    except Exception:
                        pass
                if log_callback:
                    err_hint = proc.stderr.splitlines()[-1] if proc.stderr else "Unknown error"
                    log_callback(f"[WARNING] FFmpeg embed failed: {err_hint}")
                return False
        except Exception as e:
            if temp_out.is_file():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            if log_callback:
                log_callback(f"[WARNING] Cover Art embed exception: {e}")
            return False


class CoverArtDetectionWorker(QThread):
    """
    Background worker that checks scanned videos for 1:1 Cover Art availability
    without blocking the GUI thread.
    """
    cover_art_detected = Signal(bool, int, int, object)  # (has_cover_art, width, height, cover_info)

    def __init__(
        self,
        videos: List[VideoItem],
        playlist_id: Optional[str] = None,
        source_url: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.videos = list(videos)
        self.playlist_id = playlist_id
        self.source_url = source_url
        self._is_cancelled = False

    def cancel(self) -> None:
        """Stops detection."""
        self._is_cancelled = True

    def run(self) -> None:
        """Executes detection off the main thread."""
        if not self.videos or self._is_cancelled:
            self.cover_art_detected.emit(False, 0, 0, None)
            return

        cover_info = CoverArtManager.detect_cover_art_for_videos(
            videos=self.videos,
            playlist_id=self.playlist_id,
            source_url=self.source_url,
        )
        if self._is_cancelled:
            return

        if cover_info:
            w = cover_info.get("width", 0)
            h = cover_info.get("height", 0)
            self.cover_art_detected.emit(True, w, h, cover_info)
        else:
            self.cover_art_detected.emit(False, 0, 0, None)
