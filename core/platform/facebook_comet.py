"""
facebook_comet.py
Clean-room implementation of Facebook Comet GraphQL web discovery client for Channel Harvest.

Discovers Facebook videos, Reels, and photos from public pages and profiles
by communicating directly with Facebook's desktop web Comet GraphQL endpoints.
Independent of yt-dlp and gallery-dl extraction logic, outputting normalized
video URLs (for yt-dlp) and image URLs (for gallery-dl / direct download).

MIT License compliant. Contains no code or direct translations from GPL projects.
"""

import re
import time
import json
import html
import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable, Generator
from urllib.parse import urlparse, parse_qs, urlencode

import requests
from http.cookiejar import MozillaCookieJar

from core.diagnostics import PrivacySanitizer

_logger = logging.getLogger("ChannelHarvest.FacebookComet")


class FacebookCometError(Exception):
    """Base exception for Facebook Comet operations."""
    pass


class FacebookCometAuthError(FacebookCometError):
    """Raised when authentication credentials are missing, invalid, or expired."""
    pass


class FacebookCometRateLimitError(FacebookCometError):
    """Raised when Facebook rate limits or challenges the session."""
    pass


def format_caption_title(
    raw_text: Optional[str],
    fallback: str = "",
    max_chars: Optional[int] = None,
    chinese_max_words: int = 50,
    english_max_words: int = 30,
) -> str:
    """
    Normalizes Facebook caption text by:
    - Stripping all '#' and full-width '＃' characters to avoid file management issues.
    - Collapsing newlines, tabs, and multiple spaces into a single space.
    - If the resulting text is empty (or was solely '#'), gracefully degrading to fallback.
    - Title display limits:
      * Chinese text (contains CJK characters): capped at 50 words/characters.
      * English / Western text (no CJK): capped at 30 words (not letters).
      * If truncated, appends '...'.
    """
    if not raw_text or not isinstance(raw_text, str):
        return fallback
    clean_no_hash = raw_text.replace("#", "").replace("＃", "")
    clean = " ".join(clean_no_hash.split()).strip()
    if not clean:
        return fallback

    is_chinese = bool(re.search(r'[一-鿿㐀-䶿豈-﫿]', clean))
    if is_chinese:
        matches = list(re.finditer(r'[一-鿿㐀-䶿豈-﫿]|[a-zA-Z0-9]+', clean))
        if len(matches) > chinese_max_words:
            cut_pos = matches[chinese_max_words - 1].end()
            return clean[:cut_pos].rstrip(" .,;:-_，。！？；：、") + "..."
        return clean
    else:
        words = clean.split()
        if len(words) > english_max_words:
            return " ".join(words[:english_max_words]).rstrip(" .,;:-_") + "..."
        return clean


class FacebookCometClient:
    """
    HTTP client for querying Facebook desktop Comet GraphQL endpoints.
    
    Supports:
    - Token harvesting (lsd, fb_dtsg, pageID, reelsID, photosID) from page HTML
    - Video enumeration via PagesCometChannelTabAllVideosCardImplPaginationQuery
    - Reels enumeration via ProfileCometAppCollectionReelsRendererPaginationQuery
    - Photo enumeration via ProfileCometAppCollectionPhotosRendererPaginationQuery
    """

    GRAPHQL_URL = "https://www.facebook.com/api/graphql"
    BASE_URL = "https://www.facebook.com"

    # Known stable Persisted Query Doc IDs for desktop Comet web interface
    DOC_ID_VIDEOS = "24545934291687581"
    DOC_ID_REELS = "28517740954539304"
    DOC_ID_PHOTOS = "6684543058255697"

    QUERY_NAME_VIDEOS = "PagesCometChannelTabAllVideosCardImplPaginationQuery"
    QUERY_NAME_REELS = "ProfileCometAppCollectionReelsRendererPaginationQuery"
    QUERY_NAME_PHOTOS = "ProfileCometAppCollectionPhotosRendererPaginationQuery"

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        cookie_file: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: float = 20.0,
        request_delay: float = 0.2,
    ):
        self.timeout = timeout
        self.request_delay = request_delay
        self.session = requests.Session()
        self.has_cookies = False

        self._init_session(cookie_file=cookie_file, cookies=cookies)

    def _init_session(
        self,
        cookie_file: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initializes headers and cookies in requests Session."""
        self.session.headers.update({
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.BASE_URL,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        })

        if cookie_file:
            cp = Path(cookie_file)
            if cp.is_file():
                loaded = False
                try:
                    raw_text = cp.read_text(encoding="utf-8", errors="ignore")
                    # If standard tab-delimited Netscape format, use MozillaCookieJar safely
                    if "\t" in raw_text:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            jar = MozillaCookieJar(str(cp.resolve()))
                            jar.load(ignore_discard=True, ignore_expires=True)
                            self.session.cookies = jar
                            self.has_cookies = True
                            loaded = True
                            _logger.debug("Loaded cookies via MozillaCookieJar from %s", PrivacySanitizer.sanitize(str(cp)))
                    
                    if not loaded:
                        # Fallback line-by-line parser for space-delimited or malformed cookie files
                        for line in raw_text.splitlines():
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            parts = re.split(r"\t+|\s+", line)
                            if len(parts) >= 7:
                                name, val = parts[5], parts[6]
                                self.session.cookies.set(name, val, domain=parts[0], path=parts[2])
                                self.has_cookies = True
                            elif "=" in line:
                                k, v = line.split("=", 1)
                                self.session.cookies.set(k.strip(), v.strip())
                                self.has_cookies = True
                except Exception as e:
                    _logger.debug("Cookie file parsing exception: %s", e)

        if cookies and isinstance(cookies, dict):
            self.session.cookies.update(cookies)
            self.has_cookies = True

    def extract_page_tokens(
        self,
        profile_url: str,
        is_cancelled: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Fetches the profile or video tab HTML page and extracts essential tokens:
        lsd, dtsg, page_id, reels_page_id, photos_by_id.
        """
        if is_cancelled and is_cancelled():
            return {}

        clean_url = profile_url.split("?")[0].rstrip("/")
        base_url = re.sub(r'/(photos|photos_by|photos_albums|reels|videos)/?$', '', clean_url, flags=re.IGNORECASE)
        # Target the videos subpath for reliable pageid extraction
        target_probe_url = profile_url
        if not any(k in profile_url.lower() for k in ("/videos", "/reels", "profile.php")):
            target_probe_url = f"{base_url}/videos" if base_url else f"{clean_url}/videos"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            resp = self.session.get(target_probe_url, headers=headers, timeout=self.timeout)
            html = resp.text
        except Exception as e:
            _logger.debug("Failed to fetch initial page HTML for token extraction: %s", e)
            if log_callback:
                log_callback(f"[COMET NOTICE] Could not connect to Facebook profile: {e}")
            return {}

        tokens: Dict[str, Any] = {
            "lsd": "",
            "dtsg": "",
            "page_id": "",
            "reels_page_id": "",
            "photos_by_id": "",
            "is_login_redirect": "login.php" in resp.url or "login" in resp.url.lower(),
        }

        # 1. LSD token
        lsd_match = (
            re.search(r'\[\],\{"token":"(.*?)"\},\d+\]', html)
            or re.search(r'LSD\["[^"]*\{"token":"([^"]+)"', html)
            or re.search(r'"LSD",\[\],\{"token":"([^"]+)"\}', html)
            or re.search(r'name="lsd"\s+value="([^"]+)"', html)
        )
        if lsd_match:
            tokens["lsd"] = lsd_match.group(1)

        # 2. DTSG token
        dtsg_match = (
            re.search(r'DTSGInitialData\["[^"]*\{"token":"([^"]+)"', html)
            or re.search(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"\}', html)
            or re.search(r'name="fb_dtsg"\s+value="([^"]+)"', html)
        )
        if dtsg_match:
            tokens["dtsg"] = dtsg_match.group(1)

        # 3. Video Page ID
        page_id_match = (
            re.search(r'pageid["\s:=]+(\d+)', html, re.IGNORECASE)
            or re.search(r'pageid.:.(\d+)', html, re.IGNORECASE)
            or re.search(r'"pageID":"(\d+)"', html)
            or re.search(r'delegate_page":\{"id":"(\d+)"', html)
            or re.search(r'"identifier":"(\d+)"', html)
        )
        if page_id_match:
            tokens["page_id"] = page_id_match.group(1)
        else:
            # Fallback: check profile.php?id= numeric ID
            parsed = urlparse(profile_url)
            qs = parse_qs(parsed.query)
            if "id" in qs and qs["id"] and qs["id"][0].isdigit():
                tokens["page_id"] = qs["id"][0]

        # 4. Reels Page ID
        reels_id_match = re.search(
            r'\{[^\}]*"tab_key":"owner_reels",?[^\}]*"id":"([^}"]+)"',
            html,
            re.IGNORECASE,
        )
        if reels_id_match:
            tokens["reels_page_id"] = reels_id_match.group(1)
        elif tokens["page_id"]:
            tokens["reels_page_id"] = tokens["page_id"]

        # 5. Photos by ID
        photos_id_match = (
            re.search(r'photos_by","id":"([^"]+)"', html)
            or re.search(r'"photos_by":\s*\{"id":"([^"]+)"', html)
            or re.search(r'photos_by[^{"]*\{"id":"([^"]+)"', html)
        )
        if photos_id_match:
            tokens["photos_by_id"] = photos_id_match.group(1)
        elif tokens["page_id"]:
            tokens["photos_by_id"] = tokens["page_id"]

        _logger.debug(
            "Extracted Comet tokens: lsd=%s, dtsg=%s, page_id=%s, reels_page_id=%s",
            bool(tokens["lsd"]),
            bool(tokens["dtsg"]),
            tokens["page_id"],
            tokens["reels_page_id"],
        )
        return tokens

    def _post_graphql(
        self,
        doc_id: str,
        friendly_name: str,
        variables: Dict[str, Any],
        lsd: str,
        dtsg: str,
        referer: str,
    ) -> requests.Response:
        """Executes a single POST request to the Facebook Comet GraphQL endpoint."""
        payload = {
            "lsd": lsd,
            "fb_dtsg": dtsg,
            "doc_id": doc_id,
            "fb_api_req_friendly_name": friendly_name,
            "server_timestamps": "true",
            "variables": json.dumps(variables),
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "x-fb-friendly-name": friendly_name,
            "x-fb-lsd": lsd,
            "Referer": referer,
        }
        return self.session.post(
            self.GRAPHQL_URL,
            data=payload,
            headers=headers,
            timeout=self.timeout,
        )

    @staticmethod
    def _parse_graphql_response(resp: Any) -> List[Dict[str, Any]]:
        """Parses a GraphQL response which may be single JSON, dict, or multi-line streaming JSON."""
        json_objects = []
        try:
            data = resp.json()
            if isinstance(data, dict):
                json_objects.append(data)
        except Exception:
            pass

        if not json_objects:
            raw_text = getattr(resp, "text", "") or ""
            raw_text = raw_text.strip()
            if raw_text:
                for line in raw_text.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            json_objects.append(json.loads(line))
                        except Exception:
                            pass
        return json_objects

    def scan_videos(
        self,
        page_id: str,
        lsd: str,
        dtsg: str,
        profile_url: str,
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates standard Facebook videos from a page or profile via Comet GraphQL.
        """
        if not page_id or not lsd:
            _logger.warning("scan_videos called without valid page_id or lsd token")
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        cursor: Optional[str] = None
        page_num = 1

        while max_count is None or len(results) < max_count:
            if is_cancelled and is_cancelled():
                break

            batch_size = 12 if max_count is None else min(12, max_count - len(results))
            variables = {
                "alwaysIncludeAudioRooms": True,
                "count": batch_size,
                "cursor": cursor,
                "pageID": str(page_id),
                "scale": 1,
                "showReactions": True,
                "useDefaultActor": False,
                "id": str(page_id),
            }

            try:
                resp = self._post_graphql(
                    doc_id=self.DOC_ID_VIDEOS,
                    friendly_name=self.QUERY_NAME_VIDEOS,
                    variables=variables,
                    lsd=lsd,
                    dtsg=dtsg,
                    referer=profile_url,
                )
                if resp.status_code == 429:
                    raise FacebookCometRateLimitError("Facebook rate limit reached (HTTP 429)")
                if resp.status_code != 200:
                    _logger.warning("Comet video GraphQL returned HTTP %d", resp.status_code)
                    break

                json_objects = self._parse_graphql_response(resp)
            except Exception as e:
                _logger.debug("Error executing Comet video GraphQL: %s", e)
                if log_callback:
                    log_callback(f"[COMET NOTICE] Video query page {page_num} ended: {e}")
                break

            new_in_page = 0
            has_next = False
            page_info = {}
            for obj in json_objects:
                all_videos = obj.get("data", {}).get("node", {}).get("all_videos", {})
                edges = all_videos.get("edges", [])
                p_info = all_videos.get("page_info", {})
                if p_info:
                    page_info = p_info
                    has_next = page_info.get("has_next_page", False)
                    if page_info.get("end_cursor"):
                        cursor = page_info["end_cursor"]

                for edge in edges:
                    node = edge.get("node", {})
                    vid_id = str(node.get("id") or "")
                    if not vid_id or vid_id in seen_ids:
                        continue

                    seen_ids.add(vid_id)
                    new_in_page += 1

                    # Extract authentic caption / title
                    raw_title = ""
                    savable = node.get("savable_description")
                    if isinstance(savable, dict):
                        raw_title = savable.get("text", "")
                    elif isinstance(savable, str):
                        raw_title = savable
                    if not raw_title:
                        msg = node.get("message")
                        if isinstance(msg, dict):
                            raw_title = msg.get("text", "")
                        elif isinstance(msg, str):
                            raw_title = msg
                    if not raw_title:
                        raw_title = node.get("name") or ""

                    title = format_caption_title(raw_title, fallback=f"Facebook Video {vid_id}", max_chars=35)

                    item = {
                        "id": vid_id,
                        "url": f"https://www.facebook.com/watch/?v={vid_id}",
                        "type": "video",
                        "title": title,
                        "duration": node.get("playable_duration_in_ms", 0) // 1000 if node.get("playable_duration_in_ms") else None,
                        "thumbnail": node.get("preferred_thumbnail", {}).get("image", {}).get("uri"),
                        "created_time": node.get("creation_time"),
                        "cursor": edge.get("cursor"),
                    }
                    results.append(item)

                    if progress_callback:
                        progress_callback(len(results), f"Discovered Facebook Video: {title[:40]}")

                    if max_count is not None and len(results) >= max_count:
                        break

                    if edge.get("cursor"):
                        cursor = edge.get("cursor")

            if new_in_page == 0 or not cursor:
                break
            if page_info and not has_next:
                break

            page_num += 1
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return results

    def scan_reels(
        self,
        reels_page_id: str,
        lsd: str,
        dtsg: str,
        profile_url: str,
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates Facebook Reels from a page or profile via Comet GraphQL.
        """
        if not reels_page_id or not lsd:
            _logger.warning("scan_reels called without valid reels_page_id or lsd token")
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        cursor: Optional[str] = None
        page_num = 1

        while max_count is None or len(results) < max_count:
            if is_cancelled and is_cancelled():
                break

            batch_size = 10 if max_count is None else min(10, max_count - len(results))
            variables = {
                "count": batch_size,
                "cursor": cursor,
                "feedLocation": "COMET_MEDIA_VIEWER",
                "feedbackSource": 65,
                "focusCommentID": None,
                "renderLocation": None,
                "scale": 1,
                "useDefaultActor": True,
                "id": str(reels_page_id),
                "__relay_internal__pv__FBReelsMediaFooter_comet_enable_reels_ads_gkrelayprovider": True,
                "__relay_internal__pv__IsWorkUserrelayprovider": False,
            }

            try:
                resp = self._post_graphql(
                    doc_id=self.DOC_ID_REELS,
                    friendly_name=self.QUERY_NAME_REELS,
                    variables=variables,
                    lsd=lsd,
                    dtsg=dtsg,
                    referer=profile_url,
                )
                if resp.status_code == 429:
                    raise FacebookCometRateLimitError("Facebook rate limit reached (HTTP 429)")
                if resp.status_code != 200:
                    _logger.warning("Comet reels GraphQL returned HTTP %d", resp.status_code)
                    break

                json_objects = self._parse_graphql_response(resp)
            except Exception as e:
                _logger.debug("Error executing Comet reels GraphQL: %s", e)
                if log_callback:
                    log_callback(f"[COMET NOTICE] Reels query page {page_num} ended: {e}")
                break

            new_in_page = 0
            has_next = False
            page_info = {}
            for obj in json_objects:
                shorts = obj.get("data", {}).get("node", {}).get("aggregated_fb_shorts", {})
                edges = shorts.get("edges", [])
                p_info = shorts.get("page_info", {})
                if p_info:
                    page_info = p_info
                    has_next = page_info.get("has_next_page", False)
                    if page_info.get("end_cursor"):
                        cursor = page_info["end_cursor"]

                for edge in edges:
                    prn = edge.get("profile_reel_node", {}).get("node", {})
                    edge_node = edge.get("node", {})
                    reel_id = (
                        prn.get("video", {}).get("id")
                        or prn.get("id")
                        or edge_node.get("id")
                    )
                    reel_id = str(reel_id or "")
                    if not reel_id or reel_id in seen_ids:
                        continue

                    seen_ids.add(reel_id)
                    new_in_page += 1

                    # Extract authentic post caption / title
                    raw_caption = ""
                    msg = prn.get("message") or edge_node.get("message")
                    if isinstance(msg, dict):
                        raw_caption = msg.get("text", "")
                    elif isinstance(msg, str):
                        raw_caption = msg

                    if not raw_caption:
                        savable = prn.get("savable_description") or edge_node.get("savable_description")
                        if isinstance(savable, dict):
                            raw_caption = savable.get("text", "")
                        elif isinstance(savable, str):
                            raw_caption = savable

                    if not raw_caption:
                        raw_caption = (
                            prn.get("short_form_video_context", {}).get("video", {}).get("name")
                            or edge_node.get("name")
                            or ""
                        )

                    title = format_caption_title(raw_caption, fallback=f"Facebook Reel {reel_id}", max_chars=35)

                    thumbnail_uri = (
                        prn.get("short_form_video_context", {}).get("playback_video", {}).get("thumbnailImage", {}).get("uri")
                        or prn.get("short_form_video_context", {}).get("video", {}).get("first_frame_thumbnail")
                        or edge_node.get("thumbnail_uri")
                    )

                    item = {
                        "id": reel_id,
                        "url": f"https://www.facebook.com/reel/{reel_id}",
                        "type": "reel",
                        "title": title,
                        "thumbnail": thumbnail_uri,
                        "cursor": edge.get("cursor"),
                    }
                    results.append(item)

                    if progress_callback:
                        progress_callback(len(results), f"Discovered Facebook Reel: {title[:40]}")

                    if max_count is not None and len(results) >= max_count:
                        break

                    if edge.get("cursor"):
                        cursor = edge.get("cursor")

            if new_in_page == 0 or not cursor:
                break
            if page_info and not has_next:
                break

            page_num += 1
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return results

    def fetch_photo_caption(self, photo_id: str, timeout: float = 4.0) -> Optional[str]:
        """
        Fetches the authentic original post caption for a Facebook photo by requesting photo.php.
        Extracts and unescapes the caption from <meta name="description" ...> or <meta property="og:description" ...>.
        Returns None if no caption is found or on error.
        """
        if not photo_id:
            return None
        url = f"{self.BASE_URL}/photo.php?fbid={photo_id}"
        try:
            resp = self.session.get(url, stream=True, timeout=timeout)
            if resp.status_code != 200:
                resp.close()
                return None
            chunk = b""
            for data in resp.iter_content(chunk_size=4096):
                chunk += data
                # Stop reading once the description meta tag has been fully received or threshold reached
                if (b"description" in chunk and b">" in chunk[chunk.find(b"description"):]) or len(chunk) >= 32768:
                    break
            resp.close()

            text = chunk.decode("utf-8", errors="ignore")
            m = re.search(r'<meta\s+name=["\']description["\']\s+content=(["\'])(.*?)\1', text, re.DOTALL)
            if not m:
                m = re.search(r'<meta\s+content=(["\'])(.*?)\1\s+name=["\']description["\']', text, re.DOTALL)
            if not m:
                m = re.search(r'<meta\s+property=["\']og:description["\']\s+content=(["\'])(.*?)\1', text, re.DOTALL)
            if not m:
                m = re.search(r'<meta\s+content=(["\'])(.*?)\1\s+property=["\']og:description["\']', text, re.DOTALL)

            if m:
                raw = html.unescape(m.group(2)).strip()
                raw_clean = raw.replace("#", "").replace("＃", "").strip()
                if raw_clean and raw_clean.lower() != "no photo description available.":
                    return raw
        except Exception as e:
            _logger.debug("Failed to fetch photo caption for %s: %s", photo_id, e)
        return None

    def scan_photos(
        self,
        photos_id: str,
        lsd: str,
        dtsg: str,
        profile_url: str,
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        resolve_captions: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates high-resolution photos from a page or profile via Comet GraphQL.
        When resolve_captions=True, concurrently retrieves authentic original post
        captions and formats titles to at most 35 characters.
        """
        if not photos_id or not lsd:
            _logger.warning("scan_photos called without valid photos_id or lsd token")
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        cursor: Optional[str] = None
        page_num = 1

        while max_count is None or len(results) < max_count:
            if is_cancelled and is_cancelled():
                break

            batch_size = 12 if max_count is None else min(12, max_count - len(results))
            variables = {
                "count": batch_size,
                "cursor": cursor,
                "scale": 1,
                "id": str(photos_id),
            }

            try:
                resp = self._post_graphql(
                    doc_id=self.DOC_ID_PHOTOS,
                    friendly_name=self.QUERY_NAME_PHOTOS,
                    variables=variables,
                    lsd=lsd,
                    dtsg=dtsg,
                    referer=profile_url,
                )
                if resp.status_code == 429:
                    raise FacebookCometRateLimitError("Facebook rate limit reached (HTTP 429)")
                if resp.status_code != 200:
                    _logger.warning("Comet photo GraphQL returned HTTP %d", resp.status_code)
                    break

                json_objects = self._parse_graphql_response(resp)
            except Exception as e:
                _logger.debug("Error executing Comet photo GraphQL: %s", e)
                if log_callback:
                    log_callback(f"[COMET NOTICE] Photos query page {page_num} ended: {e}")
                break

            new_in_page = 0
            has_next = False
            page_info = {}
            for obj in json_objects:
                page_items = obj.get("data", {}).get("node", {}).get("pageItems", {})
                edges = page_items.get("edges", [])
                p_info = page_items.get("page_info", {})
                if p_info:
                    page_info = p_info
                    has_next = page_info.get("has_next_page", False)
                    if page_info.get("end_cursor"):
                        cursor = page_info["end_cursor"]

                # 1. Collect valid new candidate photo items in this page
                page_candidates = []
                for edge in edges:
                    node = edge.get("node", {})
                    inner_node = node.get("node", {})
                    pid = str(inner_node.get("id") or node.get("id") or "")
                    img_uri = (
                        inner_node.get("viewer_image", {}).get("uri")
                        or node.get("viewer_image", {}).get("uri")
                        or inner_node.get("image", {}).get("uri")
                        or node.get("image", {}).get("uri")
                    )
                    post_url = node.get("url") or f"https://www.facebook.com/photo.php?fbid={pid}"

                    if not pid or not img_uri or pid in seen_ids:
                        continue

                    seen_ids.add(pid)
                    new_in_page += 1
                    page_candidates.append({
                        "pid": pid,
                        "img_uri": img_uri,
                        "post_url": post_url,
                        "inner_node": inner_node,
                        "node": node,
                        "edge": edge,
                    })

                    if edge.get("cursor"):
                        cursor = edge.get("cursor")

                    if max_count is not None and len(results) + len(page_candidates) >= max_count:
                        break

                # 2. Concurrently resolve authentic captions if enabled
                captions_map: Dict[str, Optional[str]] = {}
                if resolve_captions and page_candidates and not (is_cancelled and is_cancelled()):
                    pids_to_fetch = [c["pid"] for c in page_candidates]
                    try:
                        with ThreadPoolExecutor(max_workers=min(8, len(pids_to_fetch))) as executor:
                            future_to_pid = {
                                executor.submit(self.fetch_photo_caption, p): p
                                for p in pids_to_fetch
                            }
                            for future in as_completed(future_to_pid):
                                p_id = future_to_pid[future]
                                try:
                                    captions_map[p_id] = future.result()
                                except Exception:
                                    captions_map[p_id] = None
                    except Exception as e:
                        _logger.debug("Failed during parallel photo caption resolution: %s", e)

                # 3. Assemble results with formatted authentic titles (max 35 chars)
                for cand in page_candidates:
                    if is_cancelled and is_cancelled():
                        break

                    pid = cand["pid"]
                    inner_node = cand["inner_node"]
                    node = cand["node"]
                    edge = cand["edge"]

                    caption = captions_map.get(pid)
                    if not caption:
                        acc_caption = inner_node.get("accessibility_caption") or node.get("accessibility_caption") or ""
                        if acc_caption.strip().lower() != "no photo description available.":
                            caption = acc_caption.strip()

                    title = format_caption_title(caption, fallback=f"Facebook Photo {pid}", max_chars=35)

                    item = {
                        "id": pid,
                        "direct_url": cand["img_uri"],
                        "post_url": cand["post_url"],
                        "type": "photo",
                        "title": title,
                        "caption": caption or title,
                        "cursor": edge.get("cursor"),
                    }
                    results.append(item)

                    if progress_callback:
                        progress_callback(len(results), f"Discovered Facebook Photo: {title[:40]}")

                    if max_count is not None and len(results) >= max_count:
                        break

            if new_in_page == 0 or not cursor:
                break
            if page_info and not has_next:
                break

            page_num += 1
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return results
