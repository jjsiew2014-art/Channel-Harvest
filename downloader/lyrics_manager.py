"""
lyrics_manager.py
LRC Synchronized Lyrics retrieval, file export, and audio tag embedding engine.
"""

import io
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

try:
    import requests
except ImportError:
    requests = None

try:
    import syncedlyrics
except ImportError:
    syncedlyrics = None

from core.models import VideoItem, DownloadSettings
from core.paths import resolve_media_filename, get_bundled_executable


class LyricsManager:
    """
    Manages search, download, and audio tag embedding of LRC synchronized lyrics.
    """

    LRCLIB_URL = "https://lrclib.net/api/search"
    LRCLIB_GET_URL = "https://lrclib.net/api/get"
    DEFAULT_HEADERS = {
        "User-Agent": "ChannelHarvest/1.4.1 (https://github.com/channel-harvest)",
    }

    KNOWN_ALIASES = [
        {"G.E.M.", "GEM", "邓紫棋", "鄧紫棋", "G.E.M. 邓紫棋", "G.E.M. 鄧紫棋"},
        {"周杰伦", "周杰倫", "Jay Chou"},
        {"陈奕迅", "陳奕迅", "Eason Chan"},
        {"林俊杰", "林俊傑", "JJ Lin"},
        {"五月天", "Mayday"},
        {"蔡依林", "Jolin Tsai"},
        {"王力宏", "Leehom Wang"},
        {"陶喆", "David Tao"},
        {"张学友", "張學友", "Jacky Cheung"},
        {"孙燕姿", "孫燕姿", "Stefanie Sun"},
        {"莫文蔚", "Karen Mok"},
        {"王菲", "Faye Wong"},
        {"田馥甄", "Hebe Tien"},
        {"薛之谦", "Joker Xue"},
        {"张杰", "Jason Zhang"},
        {"华晨宇", "Hua Chenyu"},
    ]

    @classmethod
    def expand_artist_candidates(cls, artist: str, channel_title: str = "") -> List[str]:
        """
        Decomposes and expands artist names into viable search aliases.
        Handles fused Latin + CJK strings (e.g. 'GEM鄧紫棋' -> 'G.E.M.', '邓紫棋', 'GEM').
        """
        raw_list = [artist, channel_title]
        candidates: List[str] = []

        for raw in raw_list:
            if not raw:
                continue
            a = str(raw).strip()
            if a.endswith(" - Topic"):
                a = a[:-8].strip()
            if a and a not in candidates:
                candidates.append(a)

            # Split concatenated Latin and CJK without spaces (e.g. 'GEM鄧紫棋' or 'Mayday五月天')
            parts = re.findall(r"[a-zA-Z0-9\.\'\s]+|[\u4e00-\u9fff\u3400-\u4dbf]+", a)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) > 1:
                for p in parts:
                    if p not in candidates and len(p) >= 2:
                        candidates.append(p)

        # Match known alias groups
        for c in list(candidates):
            c_clean = c.replace(".", "").strip().upper()
            for alias_group in cls.KNOWN_ALIASES:
                group_upper = {x.replace(".", "").strip().upper() for x in alias_group}
                if c_clean in group_upper or c in alias_group:
                    for alias in alias_group:
                        if alias not in candidates:
                            candidates.append(alias)

        return candidates

    @classmethod
    def extract_title_candidates(cls, raw_title: str, artist_cands: Optional[List[str]] = None) -> List[str]:
        """
        Extracts clean track title candidates from video title, stripping numbering and video noise.
        """
        candidates: List[str] = []
        if not raw_title:
            return candidates

        t = raw_title.strip()
        # Strip sequence numbering prefix: e.g. '01_THE SKY' -> 'THE SKY', '1 - Song' -> 'Song'
        t = re.sub(r'^\d+[\s._-]+', '', t).strip()

        # Strip artist prefix if present
        if artist_cands:
            for a in artist_cands:
                if t.lower().startswith(a.lower() + " -"):
                    t = t[len(a) + 2:].strip()
                elif t.lower().startswith(a.lower() + "：") or t.lower().startswith(a.lower() + ":"):
                    t = t[len(a) + 1:].strip()

        brackets = re.findall(r'[【\[\(](.*?)[】\]\)]', t)
        noise_patterns = [
            r'official\s*(?:music\s*)?video',
            r'music\s*video',
            r'官方(?:完整版|音乐|歌词)?\s*mv',
            r'歌词版|官方版|完整版|高清版|高品质',
            r'lyrics\s*(?:video)?',
            r'audio',
            r'4k|1080p|hd',
            r'mv'
        ]

        def is_noise(s: str) -> bool:
            s_clean = s.strip().lower()
            for p in noise_patterns:
                if re.fullmatch(p, s_clean, re.I):
                    return True
            return False

        clean_brackets = [b.strip() for b in brackets if not is_noise(b)]

        main_clean = t
        for b in brackets:
            main_clean = main_clean.replace(f"【{b}】", " ").replace(f"[{b}]", " ").replace(f"({b})", " ")
        for p in noise_patterns:
            main_clean = re.sub(p, " ", main_clean, flags=re.I)
        main_clean = " ".join(main_clean.split()).strip(" -_–—|/")

        if main_clean and len(main_clean) >= 2:
            candidates.append(main_clean)

        for b in clean_brackets:
            # Check if bracket contains bilingual titles (e.g. '车站 Farewell Station')
            parts = re.findall(r"[a-zA-Z0-9\s\.\']+|[\u4e00-\u9fff\u3400-\u4dbf]+", b)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) > 1:
                for p in parts:
                    if p not in candidates and len(p) >= 2:
                        candidates.append(p)
            if b not in candidates:
                candidates.append(b)

        return candidates

    @classmethod
    def clean_query(cls, title: str, artist: str = "") -> str:
        """Cleans video title noise for backward-compatible fallback query formatting."""
        if not title:
            return (artist or "").strip()

        t = title
        t = re.sub(r'^\d+[\s._-]+', '', t).strip()
        t = re.sub(r'【(?:Official\s*)?(?:Music\s*)?Video.*?】', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'\[(?:Official\s*)?(?:Music\s*)?Video.*?\]', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'\((?:Official\s*)?(?:Music\s*)?Video.*?\)', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'【(?:官方)?(?:音乐|歌词|完整)?\s*MV.*?】', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'[【\[](.*?)[】\]]', r' \1 ', t)
        t = re.sub(r'(?:Official\s*)?(?:Music\s*)?Video', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'(?:官方|歌词版|Lyrics|Full)?\s*MV', ' ', t, flags=re.IGNORECASE)
        t = re.sub(r'歌词版|官方版|高清版|完整版|高品质', ' ', t)
        t = re.sub(r'[-–—|/•·_~]', ' ', t)
        t = ' '.join(t.split())
        if artist and artist.lower() not in t.lower():
            t = f"{artist} {t}"
        return t.strip()

    @classmethod
    def validate_lyrics(cls, lrc_text: str, artist_cands: List[str]) -> bool:
        """
        Validates that returned LRC lyrics do not belong to a completely mismatched artist.
        Scans metadata [ar:...] and credited composer/lyricist/performer headers.
        """
        if not lrc_text or not artist_cands:
            return True

        credited = []
        for m in re.finditer(r'\[ar:\s*([^\]]+)\]', lrc_text, re.I):
            credited.append(m.group(1).strip())
        for m in re.finditer(r'(?:歌手|演唱|Artist|作曲|作词|Lyricist|Composer)\s*[:：]\s*([^\r\n\[\]/&|]+)', lrc_text, re.I):
            credited.append(m.group(1).strip())

        if credited:
            for c in credited:
                c_low = c.lower()
                for cand in artist_cands:
                    cand_low = cand.lower()
                    if cand_low in c_low or c_low in cand_low:
                        return True
            # Explicit credits found in lyrics but none match the artist candidates
            return False

        return True

    @classmethod
    def _fetch_lrclib_search(
        cls,
        title_cands: List[str],
        artist_cands: List[str],
        album: str = "",
        duration: Optional[int] = None,
        timeout: int = 5,
    ) -> Optional[str]:
        """Queries LRCLIB /api/search with artist and title candidates."""
        for t in title_cands:
            for a in artist_cands:
                query = f"{a} {t}"
                try:
                    if requests is not None:
                        resp = requests.get(
                            cls.LRCLIB_URL,
                            params={"q": query},
                            headers=cls.DEFAULT_HEADERS,
                            timeout=timeout,
                        )
                        if not resp.ok:
                            continue
                        data = resp.json()
                    else:
                        url = f"{cls.LRCLIB_URL}?{urllib.parse.urlencode({'q': query})}"
                        req = urllib.request.Request(url, headers=cls.DEFAULT_HEADERS)
                        with urllib.request.urlopen(req, timeout=timeout) as r:
                            data = json.loads(r.read().decode("utf-8"))

                    if isinstance(data, list) and data:
                        # Prioritize candidates where album matches if album is specified
                        def candidate_rank(item: Dict[str, Any]) -> int:
                            score = 0
                            art = (item.get("artistName") or "").lower()
                            trk = (item.get("trackName") or "").lower()
                            alb = (item.get("albumName") or "").lower()
                            if any(ac.lower() == art for ac in artist_cands):
                                score += 30
                            if t.lower() == trk:
                                score += 30
                            if album and alb and album.lower() in alb:
                                score += 20
                            if duration and item.get("duration"):
                                if abs(float(item["duration"]) - float(duration)) < 6:
                                    score += 15
                            return score

                        sorted_candidates = sorted(data, key=candidate_rank, reverse=True)
                        for item in sorted_candidates:
                            synced = item.get("syncedLyrics")
                            if synced and "[" in synced:
                                item_art = (item.get("artistName") or "").lower()
                                item_trk = (item.get("trackName") or "").lower()
                                matched_art = any(ac.lower() in item_art or item_art in ac.lower() for ac in artist_cands)
                                matched_trk = (t.lower() in item_trk or item_trk in t.lower())
                                if matched_art and matched_trk:
                                    return synced
                except Exception:
                    pass
        return None

    @classmethod
    def _fetch_lrclib_get(
        cls,
        title_cands: List[str],
        artist_cands: List[str],
        album: str = "",
        timeout: int = 4,
    ) -> Optional[str]:
        """Queries LRCLIB /api/get for direct track and artist matches."""
        for t in title_cands:
            for a in artist_cands:
                param_variants = []
                if album:
                    param_variants.append({"track_name": t, "artist_name": a, "album_name": album})
                param_variants.append({"track_name": t, "artist_name": a})

                for params in param_variants:
                    try:
                        if requests is not None:
                            resp = requests.get(
                                cls.LRCLIB_GET_URL,
                                params=params,
                                headers=cls.DEFAULT_HEADERS,
                                timeout=timeout,
                            )
                            if not resp.ok:
                                continue
                            data = resp.json()
                        else:
                            url = f"{cls.LRCLIB_GET_URL}?{urllib.parse.urlencode(params)}"
                            req = urllib.request.Request(url, headers=cls.DEFAULT_HEADERS)
                            with urllib.request.urlopen(req, timeout=timeout) as r:
                                data = json.loads(r.read().decode("utf-8"))

                        if isinstance(data, dict):
                            synced = data.get("syncedLyrics")
                            if synced and "[" in synced:
                                return synced
                    except Exception:
                        pass
        return None

    @classmethod
    def fetch_lyrics(
        cls,
        title: str,
        artist: str = "",
        album: str = "",
        duration: Optional[int] = None,
        channel_title: str = "",
        video_id: str = "",
        timeout: int = 6,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        Retrieves synchronized LRC lyrics with multi-provider candidate expansion and artist validation.
        """
        artist_cands = cls.expand_artist_candidates(artist=artist, channel_title=channel_title)
        title_cands = cls.extract_title_candidates(raw_title=title, artist_cands=artist_cands)

        if not title_cands:
            single = cls.clean_query(title, artist)
            if single:
                title_cands.append(single)

        if log_callback:
            log_callback(f"[Lyrics] Searching synchronized lyrics for: '{title_cands[0] if title_cands else title}' (Artist: {artist_cands[0] if artist_cands else artist})")

        # 1. Primary: High-precision LRCLIB search
        lrc = cls._fetch_lrclib_search(
            title_cands=title_cands,
            artist_cands=artist_cands,
            album=album,
            duration=duration,
            timeout=timeout,
        )
        if lrc:
            if log_callback:
                log_callback("[Lyrics] Matched synchronized lyrics via LRCLIB.")
            return lrc

        # 2. Secondary: Direct LRCLIB exact get
        lrc = cls._fetch_lrclib_get(
            title_cands=title_cands,
            artist_cands=artist_cands,
            album=album,
            timeout=timeout,
        )
        if lrc:
            if log_callback:
                log_callback("[Lyrics] Matched synchronized lyrics via LRCLIB exact get.")
            return lrc

        # 3. Tertiary: syncedlyrics multi-provider with strict artist validation
        if syncedlyrics is not None:
            for t in title_cands:
                for a in artist_cands:
                    q = f"{a} {t}"
                    try:
                        raw = syncedlyrics.search(q, synced_only=True)
                        if raw and "[" in raw and "]" in raw:
                            if cls.validate_lyrics(raw, artist_cands):
                                if log_callback:
                                    log_callback(f"[Lyrics] Matched synchronized lyrics via provider: '{q}'")
                                return raw
                            else:
                                if log_callback:
                                    log_callback(f"[Lyrics] Discarded mismatched provider lyrics for query '{q}'.")
                    except Exception:
                        pass

        # 4. Final attempt: broad clean query with syncedlyrics
        if syncedlyrics is not None:
            broad_query = cls.clean_query(title, artist)
            if broad_query:
                try:
                    raw = syncedlyrics.search(broad_query, synced_only=True)
                    if raw and "[" in raw and "]" in raw:
                        if cls.validate_lyrics(raw, artist_cands):
                            if log_callback:
                                log_callback(f"[Lyrics] Matched synchronized lyrics via broad query '{broad_query}'")
                            return raw
                except Exception:
                    pass

        return None

    SUPPORTED_LYRICS_AUDIO_FORMATS = {"MP3", "M4A", "FLAC", "OPUS"}
    SUPPORTED_LYRICS_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".flac", ".opus", ".ogg"}

    @classmethod
    def is_format_supported(cls, fmt: str) -> bool:
        """Checks if an audio container format supports embedded lyrics."""
        if not fmt:
            return False
        clean = fmt.strip().lstrip(".").upper()
        return clean in cls.SUPPORTED_LYRICS_AUDIO_FORMATS

    @classmethod
    def _resolve_ffmpeg_executable(cls, ffmpeg_location: Optional[str] = None) -> str:
        """Resolves ffmpeg executable path."""
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
    def embed_lyrics(
        cls,
        media_path: Path,
        lrc_text: str,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Embeds synchronized LRC lyrics into an audio file using FFmpeg lossless stream copy.
        """
        if not media_path.is_file() or not lrc_text:
            return False

        ext = media_path.suffix.lower()
        if ext in (".wav", ".aac"):
            if log_callback:
                log_callback(f"[Lyrics] Audio format {ext.upper()} does not support embedded lyrics tags.")
            return False

        ffmpeg_bin = cls._resolve_ffmpeg_executable(ffmpeg_location)
        temp_out = media_path.with_name(f"{media_path.stem}.tmp_lyr{ext}")

        meta_args = [
            "-metadata", f"lyrics={lrc_text}",
            "-metadata", f"LYRICS={lrc_text}",
            "-metadata", f"unsyncedlyrics={lrc_text}",
        ]

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
                        log_callback(f"[Lyrics] Embedded synchronized lyrics into: {media_path.name}")
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
                    log_callback(f"[WARNING] FFmpeg lyrics embed failed: {err_hint}")
                return False
        except Exception as e:
            if temp_out.is_file():
                try:
                    temp_out.unlink()
                except Exception:
                    pass
            if log_callback:
                log_callback(f"[WARNING] Lyrics embed exception: {e}")
            return False

    @classmethod
    def embed_lyrics_for_media_files(
        cls,
        video: VideoItem,
        media_paths: List[Path],
        settings: DownloadSettings,
        target_dir: Path,
        ffmpeg_location: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        artist: Optional[str] = None,
        title: Optional[str] = None,
        album: Optional[str] = None,
        duration: Optional[int] = None,
    ) -> bool:
        """
        Embeds synchronized lyrics into a list of media files for a single video.
        """
        if cancel_check and cancel_check():
            return False

        valid_paths = [p for p in media_paths if p.is_file() and p.suffix.lower() in cls.SUPPORTED_LYRICS_AUDIO_EXTENSIONS]
        if not valid_paths:
            return False

        lrc_text = getattr(video, "_lrc_text", None)
        if not lrc_text:
            include_id = getattr(settings, "include_video_id_in_filename", False)
            num_prefix = getattr(settings, "number_prefix", "")
            stem = resolve_media_filename(
                video.title,
                video.video_id,
                include_video_id=include_id,
                target_dir=target_dir,
                number_prefix=num_prefix,
            )
            lrc_file = target_dir / f"{stem}.lrc"
            if lrc_file.is_file():
                try:
                    with open(lrc_file, "r", encoding="utf-8") as f:
                        lrc_text = f.read()
                except Exception:
                    pass

        if not lrc_text:
            lrc_text = cls.fetch_lyrics(
                title=title or video.title,
                artist=artist or video.channel_title,
                album=album or video.extra_metadata.get("album", ""),
                duration=duration or video.duration_seconds,
                channel_title=video.channel_title,
                video_id=video.video_id,
                log_callback=log_callback,
            )
            if lrc_text:
                video._lrc_text = lrc_text

        if not lrc_text:
            return False

        any_success = False
        for p in valid_paths:
            if cancel_check and cancel_check():
                break
            succ = cls.embed_lyrics(
                media_path=p,
                lrc_text=lrc_text,
                ffmpeg_location=ffmpeg_location,
                log_callback=log_callback,
            )
            if succ:
                any_success = True

        return any_success

    @classmethod
    def format_lrc(cls, raw_lrc: str, title: str = "", artist: str = "") -> str:
        """Formats and ensures valid ID3 LRC headers ([ti:...], [ar:...], [by:...])."""
        if not raw_lrc:
            return ""

        headers = []
        if title and "[ti:" not in raw_lrc.lower():
            headers.append(f"[ti:{title.strip()}]")
        if artist and "[ar:" not in raw_lrc.lower():
            headers.append(f"[ar:{artist.strip()}]")
        if "[by:" not in raw_lrc.lower():
            headers.append("[by:ChannelHarvest]")

        if headers:
            return "\n".join(headers) + "\n" + raw_lrc.lstrip()
        return raw_lrc

    @classmethod
    def download_lyrics(
        cls,
        video: VideoItem,
        settings: DownloadSettings,
        target_dir: Path,
        log_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        info_dict: Optional[Dict[str, Any]] = None,
        artist: Optional[str] = None,
        title: Optional[str] = None,
        album: Optional[str] = None,
        duration: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves and saves synchronized LRC lyrics as '<stem>.lrc'.
        """
        if cancel_check and cancel_check():
            return {"success": False, "saved_file": None, "error": "Cancelled by user"}

        include_id = getattr(settings, "include_video_id_in_filename", False)
        num_prefix = getattr(settings, "number_prefix", "")
        stem = resolve_media_filename(
            video.title,
            video.video_id,
            include_video_id=include_id,
            target_dir=target_dir,
            number_prefix=num_prefix,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_file = target_dir / f"{stem}.lrc"

        # Check existing
        if settings.skip_existing and dest_file.is_file() and dest_file.stat().st_size > 0:
            if log_callback:
                log_callback(f"[ARCHIVE] Lyrics file already exists: {dest_file.name}. Skipping.")
            return {"success": True, "saved_file": dest_file, "skipped": True}

        # Resolve high-fidelity metadata
        eff_title = title or (info_dict.get("track") if info_dict else None) or (info_dict.get("title") if info_dict else None) or video.title
        raw_art = artist or (info_dict.get("artist") if info_dict else None) or (info_dict.get("creator") if info_dict else None) or (info_dict.get("uploader") if info_dict else None) or video.channel_title
        eff_artist = str(raw_art).strip() if raw_art else ""
        if eff_artist.endswith(" - Topic"):
            eff_artist = eff_artist[:-8].strip()
        eff_album = album or (info_dict.get("album") if info_dict else None) or video.extra_metadata.get("album", "")
        eff_duration = duration or (info_dict.get("duration") if info_dict else None) or video.duration_seconds

        # Check pre-cached lyrics
        lrc_text = getattr(video, "_lrc_text", None)
        if not lrc_text:
            lrc_text = cls.fetch_lyrics(
                title=eff_title,
                artist=eff_artist,
                album=eff_album,
                duration=eff_duration,
                channel_title=video.channel_title,
                video_id=video.video_id,
                log_callback=log_callback,
            )

        if not lrc_text:
            if log_callback:
                log_callback(f"[INFO] No synchronized LRC lyrics found for: {eff_title}")
            return {"success": False, "saved_file": None, "error": "No lyrics found"}

        # Cache on video item
        video._lrc_text = lrc_text

        # Format LRC headers and save
        header_artist = eff_artist or video.channel_title
        formatted = cls.format_lrc(lrc_text, title=eff_title, artist=header_artist)
        try:
            with open(dest_file, "w", encoding="utf-8") as f:
                f.write(formatted)
            if log_callback:
                log_callback(f"[Lyrics] Saved: {dest_file.name}")
            return {"success": True, "saved_file": dest_file, "skipped": False}
        except Exception as e:
            if log_callback:
                log_callback(f"[WARNING] Failed to write lyrics file: {e}")
            return {"success": False, "saved_file": None, "error": str(e)}
