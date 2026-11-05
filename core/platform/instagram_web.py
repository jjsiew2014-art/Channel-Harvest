"""
instagram_web.py
Clean-room implementation of Instagram Web GraphQL & REST discovery client for Channel Harvest.

Discovers Instagram photos, carousel albums, standard videos, and Reels from public profiles
and authenticated sessions by communicating directly with Instagram's desktop web endpoints.
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

_logger = logging.getLogger("ChannelHarvest.InstagramWeb")


class InstagramWebError(Exception):
    """Base exception for Instagram Web operations."""
    pass


class InstagramAuthError(InstagramWebError):
    """Raised when authentication credentials are required, invalid, or expired."""
    pass


class InstagramRateLimitError(InstagramWebError):
    """Raised when Instagram rate limits or challenges the session."""
    pass


def format_instagram_caption_title(
    raw_text: Optional[str],
    fallback: str = "",
    max_chars: Optional[int] = None,
    chinese_max_words: int = 50,
    english_max_words: int = 30,
) -> str:
    """
    Normalizes Instagram caption text by:
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


class InstagramWebClient:
    """
    HTTP client for querying Instagram desktop web GraphQL and REST API endpoints.
    
    Supports:
    - Profile token & identifier harvesting (user_id, username, lsd, fb_dtsg, csrftoken) from HTML
    - Timeline post enumeration (Photos, Videos, Multi-item Carousels) via Polaris GraphQL
    - Reels enumeration via Polaris Profile Reels GraphQL
    - Resilient REST fallback (/api/v1/feed/user/{user_id}/) when GraphQL doc_id encounters rate limits
    - Cookie integration (MozillaCookieJar Netscape format, raw dictionary)
    """

    GRAPHQL_URL = "https://www.instagram.com/api/graphql"
    GRAPHQL_QUERY_URL = "https://www.instagram.com/graphql/query"
    BASE_URL = "https://www.instagram.com"

    # Known stable Persisted Query Doc IDs for Instagram Web
    DOC_ID_LOGGED_OUT_TIMELINE = "29239200285696526"
    DOC_ID_POSTS_PAGINATION = "29224840567111233"
    DOC_ID_POSTS_INITIAL = "29600383452901789"
    DOC_ID_REELS = "28686080707741651"
    DOC_ID_USER_PROFILE = "40158838120366999"

    QUERY_NAME_LOGGED_OUT_TIMELINE = "PolarisOwnerToTimelineMediaLoggedOutQuery_connection"
    QUERY_NAME_POSTS = "PolarisProfilePostsTabContentQuery_connection"
    QUERY_NAME_INITIAL_POSTS = "PolarisProfilePostsQuery"
    QUERY_NAME_REELS = "PolarisClipsTabRootPaginationQuery"
    QUERY_NAME_PROFILE = "PolarisProfilePageContentQuery"

    DEFAULT_APP_ID = "936619743392459"
    DEFAULT_ASBD_ID = "129477"

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
        self._timeline_cache: Dict[str, List[Dict[str, Any]]] = {}

        self._init_session(cookie_file=cookie_file, cookies=cookies)

    def _init_session(
        self,
        cookie_file: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initializes headers and cookies in requests Session."""
        self.session.headers.update({
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.BASE_URL,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "X-IG-App-ID": self.DEFAULT_APP_ID,
            "X-ASBD-ID": self.DEFAULT_ASBD_ID,
        })

        if cookie_file:
            cp = Path(cookie_file)
            if cp.is_file():
                loaded = False
                try:
                    raw_text = cp.read_text(encoding="utf-8", errors="ignore")
                    if "\t" in raw_text:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            jar = MozillaCookieJar(str(cp.resolve()))
                            jar.load(ignore_discard=True, ignore_expires=True)
                            self.session.cookies = jar
                            self.has_cookies = True
                            loaded = True
                            _logger.debug("Loaded Instagram cookies via MozillaCookieJar from %s", PrivacySanitizer.sanitize(str(cp)))

                    if not loaded:
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
                                self.session.cookies.set(k.strip(), v.strip(), domain=".instagram.com")
                                self.has_cookies = True
                except Exception as e:
                    _logger.debug("Instagram cookie file parsing exception: %s", e)

        if cookies and isinstance(cookies, dict):
            self.session.cookies.update(cookies)
            self.has_cookies = True

    @classmethod
    def extract_username_from_url(cls, url: str) -> str:
        """Extracts username from an Instagram profile or subpath URL."""
        if not url or not isinstance(url, str):
            return ""
        clean = url.split("?")[0].rstrip("/")
        parsed = urlparse(clean)
        path = parsed.path.strip("/")
        if not path:
            return ""
        segments = [p for p in path.split("/") if p]
        if not segments:
            return ""
        # First segment is the username unless it's a known non-profile path
        first = segments[0]
        if first.lower() in ("p", "reel", "reels", "tv", "stories", "explore", "direct"):
            return ""
        return first

    def extract_profile_info(
        self,
        profile_url: str,
        is_cancelled: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Fetches the Instagram profile HTML page and extracts essential tokens:
        username, user_id, lsd, fb_dtsg, and csrftoken.
        """
        if is_cancelled and is_cancelled():
            return {}

        username = self.extract_username_from_url(profile_url)
        clean_url = f"{self.BASE_URL}/{username}/" if username else profile_url.split("?")[0].rstrip("/") + "/"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            resp = self.session.get(clean_url, headers=headers, timeout=self.timeout)
            html_text = resp.text
        except Exception as e:
            _logger.debug("Failed to fetch Instagram profile HTML: %s", e)
            if log_callback:
                log_callback(f"[INSTAGRAM NOTICE] Could not connect to Instagram profile: {e}")
            return {}

        info: Dict[str, Any] = {
            "username": username,
            "user_id": "",
            "lsd": "",
            "dtsg": "",
            "csrf": "",
            "is_login_redirect": "accounts/login" in resp.url or "login" in resp.url.lower(),
        }

        # 1. Parse __eqmc script payload for LSD and DTSG tokens
        pos = html_text.find(' id="__eqmc"')
        if pos != -1:
            try:
                script_raw = html_text[html_text.find(">", pos) + 1 : html_text.find("</script>", pos)]
                eqmc = json.loads(script_raw)
                info["lsd"] = eqmc.get("l") or ""
                info["dtsg"] = eqmc.get("f") or ""
            except Exception:
                pass

        # Fallback LSD parsing
        if not info["lsd"]:
            lsd_match = (
                re.search(r'"LSD",\[\],\{"token":"([^"]+)"\}', html_text)
                or re.search(r'\[\],\{"token":"(.*?)"\}', html_text)
                or re.search(r'name="lsd"\s+value="([^"]+)"', html_text)
            )
            if lsd_match:
                info["lsd"] = lsd_match.group(1)

        # Fallback DTSG parsing
        if not info["dtsg"]:
            dtsg_match = (
                re.search(r'"dtsg":\{"token":"([^"]+)"', html_text)
                or re.search(r'DTSGInitialData\["[^"]*\{"token":"([^"]+)"', html_text)
            )
            if dtsg_match:
                info["dtsg"] = dtsg_match.group(1)

        # 2. Extract User ID
        user_id_match = (
            re.search(r'"profile_id":"(\d+)"', html_text)
            or re.search(r'"props":\{"id":"(\d+)"', html_text)
            or re.search(r'"owner":\{"id":"(\d+)"', html_text)
            or re.search(r'"user_id":"(\d+)"', html_text)
        )
        if user_id_match:
            info["user_id"] = user_id_match.group(1)

        # 3. Extract CSRF token from cookies or HTML
        csrf = self.session.cookies.get("csrftoken", domain=".instagram.com") or self.session.cookies.get("csrftoken")
        if not csrf:
            csrf_m = re.search(r'"csrf_token":"([^"]+)"', html_text)
            if csrf_m:
                csrf = csrf_m.group(1)
        info["csrf"] = csrf or ""
        info["html"] = html_text
        info["embedded_items"] = self.extract_media_from_html(html_text, fallback_author=username)

        return info

    def _post_graphql(
        self,
        doc_id: str,
        friendly_name: str,
        variables: Dict[str, Any],
        lsd: str = "",
        dtsg: str = "",
        referer: str = "",
    ) -> requests.Response:
        """Executes a POST request against Instagram's GraphQL endpoint."""
        csrf = self.session.cookies.get("csrftoken", domain=".instagram.com") or self.session.cookies.get("csrftoken") or ""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-FB-Friendly-Name": friendly_name,
            "X-FB-LSD": lsd or "",
            "X-ASBD-ID": self.DEFAULT_ASBD_ID,
            "X-IG-App-ID": self.DEFAULT_APP_ID,
            "X-CSRFToken": csrf,
            "Referer": referer or self.BASE_URL + "/",
            "Origin": self.BASE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        data = {
            "doc_id": doc_id,
            "lsd": lsd or "",
            "fb_dtsg": dtsg or "",
            "fb_api_req_friendly_name": friendly_name,
            "variables": json.dumps(variables, separators=(",", ":")),
        }

        return self.session.post(self.GRAPHQL_URL, headers=headers, data=data, timeout=self.timeout)

    def _parse_graphql_response(self, resp: requests.Response) -> List[Dict[str, Any]]:
        """Parses Instagram GraphQL JSON or streaming JSON-Lines responses."""
        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
        except Exception:
            pass

        results: List[Dict[str, Any]] = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    results.append(obj)
            except Exception:
                continue
        return results

    def extract_media_from_html(self, html_text: str, fallback_author: str = "") -> List[Dict[str, Any]]:
        """
        Extracts media items embedded in Instagram HTML page script tags.
        Instagram embeds initial timeline and reels media in ScheduledServerJS / RelayPrefetchedStreamCache
        which is accessible even for unauthenticated sessions.
        """
        if not html_text or not isinstance(html_text, str):
            return []

        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html_text, re.DOTALL)
        nodes = []
        seen_ids = set()

        for s in scripts:
            s = s.strip()
            if not s or (
                '"XIGPolaris' not in s
                and 'polaris_ordered_timeline_connection' not in s
                and 'clips_user_connection' not in s
                and 'xdt_api__v1' not in s
                and 'edge_owner_to_timeline_media' not in s
            ):
                continue

            data = None
            try:
                data = json.loads(s)
            except Exception:
                m = re.search(r'\{"require":.*\}', s)
                if m:
                    try:
                        data = json.loads(m.group(0))
                    except Exception:
                        pass

            if not data:
                continue

            def scan_obj(obj):
                if isinstance(obj, dict):
                    if "code" in obj and ("pk" in obj or "id" in obj) and (
                        "__typename" in obj
                        or "media_type" in obj
                        or "display_uri" in obj
                        or "video_versions" in obj
                        or "image_versions2" in obj
                    ):
                        node_id = str(obj.get("pk") or obj.get("id") or "").replace("POLARIS_", "")
                        if node_id and node_id not in seen_ids:
                            seen_ids.add(node_id)
                            nodes.append(obj)
                    for v in obj.values():
                        scan_obj(v)
                elif isinstance(obj, list):
                    for item in obj:
                        scan_obj(item)

            scan_obj(data)

        decomposed: List[Dict[str, Any]] = []
        for n in nodes:
            items = self._decompose_media_node(n, fallback_author=fallback_author)
            decomposed.extend(items)
        return decomposed

    def _decompose_media_node(self, node: Dict[str, Any], fallback_author: str = "Instagram") -> List[Dict[str, Any]]:
        """
        Decomposes an Instagram media node into one or more normalized items.
        Handles:
        - Single Image (media_type=1)
        - Single Video / Reel (media_type=2)
        - Carousel / Album (media_type=8) with multiple child photos/videos
        """
        if not node or not isinstance(node, dict):
            return []

        pk_val = str(node.get("pk") or "").strip()
        raw_id = str(node.get("id") or "").strip().replace("POLARIS_", "")
        code = str(node.get("code") or node.get("shortcode") or "").strip()
        post_id = pk_val or raw_id or code
        media_type = node.get("media_type")
        typename = str(node.get("__typename") or "")
        product_type = str(node.get("product_type") or "")

        is_video = (
            media_type == 2
            or bool(node.get("video_versions"))
            or "Video" in typename
            or bool(node.get("is_video"))
        )
        is_reel = bool(
            product_type == "clips"
            or "clips" in typename.lower()
            or "/reel/" in (node.get("seo_canonical_url") or "")
        )
        post_url = f"{self.BASE_URL}/reel/{code}/" if (is_reel and code) else (f"{self.BASE_URL}/p/{code}/" if code else "")

        display_uri = node.get("display_uri") or node.get("display_url") or node.get("thumbnail_src") or ""

        # Caption extraction
        raw_caption = ""
        cap_obj = node.get("caption")
        if isinstance(cap_obj, dict):
            raw_caption = cap_obj.get("text") or ""
        elif isinstance(cap_obj, str):
            raw_caption = cap_obj

        user_obj = node.get("user")
        author = fallback_author
        if isinstance(user_obj, dict):
            author = user_obj.get("username") or fallback_author
        taken_at = node.get("taken_at")

        items: List[Dict[str, Any]] = []

        # 1. Carousel Album (media_type == 8)
        carousel_media = node.get("carousel_media") or []
        if media_type == 8 and carousel_media:
            total_count = len(carousel_media)
            for idx, child in enumerate(carousel_media, start=1):
                child_id = str(child.get("id") or f"{post_id}_{idx}")
                child_media_type = child.get("media_type")

                # Direct URL selection
                direct_url = ""
                thumbnail_url = ""
                is_video = child_media_type == 2 or bool(child.get("video_versions"))

                if is_video:
                    v_versions = child.get("video_versions") or []
                    if v_versions and isinstance(v_versions, list):
                        direct_url = v_versions[0].get("url") or ""
                    img_versions = child.get("image_versions2", {}).get("candidates") or []
                    if img_versions and isinstance(img_versions, list):
                        thumbnail_url = img_versions[0].get("url") or ""
                    m_type_str = "video"
                else:
                    img_versions = child.get("image_versions2", {}).get("candidates") or []
                    if img_versions and isinstance(img_versions, list):
                        direct_url = img_versions[0].get("url") or ""
                        thumbnail_url = direct_url
                    m_type_str = "photo"

                if not direct_url:
                    continue

                fallback_title = f"Instagram {'Video' if is_video else 'Photo'} {child_id}"
                title = format_instagram_caption_title(raw_caption, fallback=fallback_title, max_chars=35)

                dur = child.get("video_duration")
                dur_sec = int(dur) if (dur and isinstance(dur, (int, float)) and dur > 0) else None

                items.append({
                    "id": child_id,
                    "parent_post_id": post_id,
                    "code": code,
                    "post_url": post_url,
                    "direct_url": direct_url,
                    "thumbnail": thumbnail_url,
                    "type": m_type_str,
                    "title": title,
                    "caption": raw_caption,
                    "duration": dur_sec,
                    "sequence_index": idx,
                    "media_count": total_count,
                    "taken_at": taken_at,
                    "author": author,
                })

            return items

        # 2. Single Video / Reel (media_type == 2 or video_versions or XIGPolarisVideoMedia)
        if is_video:
            v_versions = node.get("video_versions") or []
            direct_url = v_versions[0].get("url") if (v_versions and isinstance(v_versions, list)) else ""
            img_versions = node.get("image_versions2", {}).get("candidates") or []
            thumbnail_url = (img_versions[0].get("url") if (img_versions and isinstance(img_versions, list)) else "") or display_uri
            if not direct_url:
                direct_url = post_url or display_uri

            dur = node.get("video_duration")
            dur_sec = int(dur) if (dur and isinstance(dur, (int, float)) and dur > 0) else None
            m_type_str = "reel" if is_reel else "video"

            fallback_title = f"Instagram {'Reel' if is_reel else 'Video'} {post_id}"
            title = format_instagram_caption_title(raw_caption, fallback=fallback_title)

            items.append({
                "id": post_id,
                "parent_post_id": post_id,
                "code": code,
                "post_url": post_url,
                "direct_url": direct_url,
                "thumbnail": thumbnail_url,
                "type": m_type_str,
                "title": title,
                "caption": raw_caption,
                "duration": dur_sec,
                "sequence_index": 1,
                "media_count": 1,
                "taken_at": taken_at,
                "author": author,
            })
            return items

        # 3. Single Photo (media_type == 1 or default)
        img_versions = node.get("image_versions2", {}).get("candidates") or []
        direct_url = (img_versions[0].get("url") if (img_versions and isinstance(img_versions, list)) else "") or display_uri
        thumbnail_url = direct_url

        if direct_url or post_url:
            fallback_title = f"Instagram Photo {post_id}"
            title = format_instagram_caption_title(raw_caption, fallback=fallback_title)

            items.append({
                "id": post_id,
                "parent_post_id": post_id,
                "code": code,
                "post_url": post_url,
                "direct_url": direct_url or post_url,
                "thumbnail": thumbnail_url,
                "type": "photo",
                "title": title,
                "caption": raw_caption,
                "duration": None,
                "sequence_index": 1,
                "media_count": 1,
                "taken_at": taken_at,
                "author": author,
            })

        return items

    def scan_posts(
        self,
        username: str,
        user_id: Optional[str] = None,
        lsd: str = "",
        dtsg: str = "",
        profile_url: str = "",
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates all timeline posts (photos, carousel albums, videos, Reels) via Polaris GraphQL.
        Uses PolarisOwnerToTimelineMediaLoggedOutQuery_connection (doc_id 29239200285696526)
        which permits anonymous complete timeline enumeration, or PolarisProfilePostsTabContentQuery_connection
        when authenticated. Automatically falls back to REST API (/api/v1/feed/user/{id}/) if needed.
        """
        if not username:
            return []

        # Return cached timeline if previously fetched for this username in this session
        if max_count is None and username in self._timeline_cache:
            return list(self._timeline_cache[username])

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        cursor: Optional[str] = None
        page_num = 1
        graphql_failed = False

        # Ingest embedded items and ensure tokens (LSD, User ID) are populated
        if profile_url or not lsd or not user_id:
            try:
                p_url = profile_url or f"{self.BASE_URL}/{username}/"
                prof_info = self.extract_profile_info(p_url, is_cancelled=is_cancelled, log_callback=log_callback)
                for it in (prof_info.get("embedded_items") or []):
                    it_id = str(it.get("id") or "")
                    if it_id and it_id not in seen_ids:
                        seen_ids.add(it_id)
                        results.append(it)
                        if progress_callback:
                            progress_callback(len(results), f"Discovered Instagram {it['type'].capitalize()}: {it['title'][:35]}")
                if not user_id and prof_info.get("user_id"):
                    user_id = prof_info["user_id"]
                if not lsd and prof_info.get("lsd"):
                    lsd = prof_info["lsd"]
                if not dtsg and prof_info.get("dtsg"):
                    dtsg = prof_info["dtsg"]
            except Exception as e:
                _logger.debug("Initial HTML embedded items extraction notice: %s", e)

        while max_count is None or len(results) < max_count:
            if is_cancelled and is_cancelled():
                break

            batch_size = 50 if max_count is None else min(50, max_count - len(results))

            # Query selection:
            # When user_id is known, PolarisOwnerToTimelineMediaLoggedOutQuery_connection provides
            # unrestricted complete profile enumeration (Reels, photos, videos, carousels) without login cookies.
            if user_id:
                doc_id = self.DOC_ID_LOGGED_OUT_TIMELINE
                friendly_name = self.QUERY_NAME_LOGGED_OUT_TIMELINE
                variables = {
                    "after": cursor,
                    "first": batch_size,
                    "owner_id": str(user_id),
                    "media_id_to_filter": "0",
                    "additional_media_to_fetch": batch_size,
                    "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
                    "__relay_internal__pv__PolarisThreadsStyleCommentsEnabledrelayprovider": False,
                }
            elif cursor:
                doc_id = self.DOC_ID_POSTS_PAGINATION
                friendly_name = self.QUERY_NAME_POSTS
                variables = {
                    "after": cursor,
                    "before": None,
                    "data": {
                        "count": batch_size,
                        "include_relationship_info": True,
                        "latest_besties_reel_media": True,
                        "latest_reel_media": True,
                    },
                    "first": batch_size,
                    "last": None,
                    "username": username,
                    "__relay_internal__pv__PolarisShareMenurelayprovider": False,
                }
            else:
                doc_id = self.DOC_ID_POSTS_INITIAL
                friendly_name = self.QUERY_NAME_INITIAL_POSTS
                variables = {
                    "data": {
                        "count": batch_size,
                        "include_relationship_info": True,
                        "latest_besties_reel_media": True,
                        "latest_reel_media": True,
                    },
                    "username": username,
                    "__relay_internal__pv__PolarisShareMenurelayprovider": False,
                }

            try:
                resp = self._post_graphql(
                    doc_id=doc_id,
                    friendly_name=friendly_name,
                    variables=variables,
                    lsd=lsd,
                    dtsg=dtsg,
                    referer=profile_url or f"{self.BASE_URL}/{username}/",
                )
                if resp.status_code == 429:
                    raise InstagramRateLimitError("Instagram rate limit reached (HTTP 429)")

                json_objects = self._parse_graphql_response(resp)
            except Exception as e:
                _logger.debug("Instagram GraphQL posts query error: %s", e)
                graphql_failed = True
                break

            if not json_objects:
                graphql_failed = True
                break

            new_in_page = 0
            has_next = False
            page_info = {}

            for obj in json_objects:
                if "errors" in obj and not obj.get("data"):
                    graphql_failed = True
                    break

                conn = (
                    obj.get("data", {}).get("xdt_get_owner_to_timeline_media_logged_out", {})
                    or obj.get("data", {}).get("xdt_api__v1__feed__user_timeline_graphql_connection", {})
                    or obj.get("data", {}).get("user", {}).get("edge_owner_to_timeline_media", {})
                    or {}
                )
                edges = conn.get("edges", [])
                p_info = conn.get("page_info", {})
                if p_info:
                    page_info = p_info
                    has_next = page_info.get("has_next_page", False)
                    if page_info.get("end_cursor"):
                        cursor = page_info["end_cursor"]

                for edge in edges:
                    node = edge.get("node", {})
                    decomposed = self._decompose_media_node(node, fallback_author=username)
                    for item in decomposed:
                        item_id = item["id"]
                        if item_id in seen_ids:
                            continue
                        seen_ids.add(item_id)
                        new_in_page += 1
                        results.append(item)

                        if progress_callback:
                            progress_callback(len(results), f"Discovered Instagram {item['type'].capitalize()}: {item['title'][:35]}")

                        if max_count is not None and len(results) >= max_count:
                            break

            if graphql_failed or new_in_page == 0 or not cursor:
                break
            if page_info and not has_next:
                break

            page_num += 1
            if self.request_delay > 0:
                time.sleep(self.request_delay)

        # Fallback to REST API if GraphQL failed and user_id is available
        if graphql_failed and user_id and (max_count is None or len(results) < max_count):
            if log_callback:
                log_callback("[INSTAGRAM] Falling back to REST feed enumeration...")
            rest_items = self._scan_posts_rest_fallback(
                user_id=user_id,
                username=username,
                max_count=max_count,
                seen_ids=seen_ids,
                is_cancelled=is_cancelled,
                progress_callback=progress_callback,
            )
            results.extend(rest_items)

        if max_count is None:
            self._timeline_cache[username] = list(results)

        return results

    def scan_reels(
        self,
        user_id: str,
        username: str = "",
        lsd: str = "",
        dtsg: str = "",
        profile_url: str = "",
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Enumerates Reels from an Instagram profile.
        Combines embedded /reels/ HTML items, dedicated Reels GraphQL queries, and full timeline
        enumeration to retrieve all Reels without missing items.
        """
        if not user_id and not username:
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        cursor: Optional[str] = None
        reels_graphql_failed = False

        # 1. Probe /reels/ HTML page for embedded Reels
        if username and not (is_cancelled and is_cancelled()):
            reels_page_url = f"{self.BASE_URL}/{username}/reels/"
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Not-A.Brand";v="99", "Chromium";v="124", "Google Chrome";v="124"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
            try:
                r_page = self.session.get(reels_page_url, headers=headers, timeout=self.timeout)
                if r_page.status_code == 200:
                    page_items = self.extract_media_from_html(r_page.text, fallback_author=username)
                    for pit in page_items:
                        pit["type"] = "reel"
                        pid = str(pit.get("id") or "")
                        if pid and pid not in seen_ids:
                            seen_ids.add(pid)
                            results.append(pit)
                            if progress_callback:
                                progress_callback(len(results), f"Discovered Instagram Reel: {pit['title'][:35]}")
            except Exception as e:
                _logger.debug("Instagram reels HTML probe notice: %s", e)

        # 2. Try dedicated Reels GraphQL pagination (for authenticated queries / mock fixtures)
        if user_id:
            while max_count is None or len(results) < max_count:
                if is_cancelled and is_cancelled():
                    break

                batch_size = 50 if max_count is None else min(50, max_count - len(results))
                variables = {
                    "after": cursor,
                    "before": None,
                    "data": {
                        "include_feed_video": True,
                        "page_size": batch_size,
                        "target_user_id": str(user_id),
                    },
                    "first": batch_size,
                    "last": None,
                    "id": str(user_id),
                }

                try:
                    resp = self._post_graphql(
                        doc_id=self.DOC_ID_REELS,
                        friendly_name=self.QUERY_NAME_REELS,
                        variables=variables,
                        lsd=lsd,
                        dtsg=dtsg,
                        referer=profile_url or f"{self.BASE_URL}/{username}/reels/",
                    )
                    if resp.status_code == 429:
                        raise InstagramRateLimitError("Instagram rate limit reached (HTTP 429)")

                    json_objects = self._parse_graphql_response(resp)
                except Exception as e:
                    _logger.debug("Instagram GraphQL Reels query error: %s", e)
                    reels_graphql_failed = True
                    break

                if not json_objects:
                    reels_graphql_failed = True
                    break

                new_in_page = 0
                has_next = False
                page_info = {}

                for obj in json_objects:
                    if "errors" in obj and not obj.get("data"):
                        reels_graphql_failed = True
                        break

                    user_dict = obj.get("data", {}).get("fetch__XDTUserDict", {}) or obj.get("data", {})
                    conn = (
                        user_dict.get("clips_user_connection")
                        or user_dict.get("xdt_api__v1__clips__user__connection_v2")
                        or {}
                    )
                    edges = conn.get("edges", [])
                    p_info = conn.get("page_info", {})
                    if p_info:
                        page_info = p_info
                        has_next = page_info.get("has_next_page", False)
                        if page_info.get("end_cursor"):
                            cursor = page_info["end_cursor"]

                    for edge in edges:
                        node = edge.get("node", {}).get("media", {}) or edge.get("node", {})
                        decomposed = self._decompose_media_node(node, fallback_author=username)
                        for item in decomposed:
                            item["type"] = "reel"
                            item_id = item["id"]
                            if item_id in seen_ids:
                                continue
                            seen_ids.add(item_id)
                            new_in_page += 1
                            results.append(item)

                            if progress_callback:
                                progress_callback(len(results), f"Discovered Instagram Reel: {item['title'][:35]}")

                            if max_count is not None and len(results) >= max_count:
                                break

                if reels_graphql_failed or new_in_page == 0 or not cursor:
                    break
                if page_info and not has_next:
                    break

        # 3. If dedicated reels query yielded only initial items or failed (e.g. unauthenticated mode),
        # query timeline posts which contains all published Reels
        if (reels_graphql_failed or len(results) <= 13) and (max_count is None or len(results) < max_count):
            timeline_items = self.scan_posts(
                username=username,
                user_id=user_id,
                lsd=lsd,
                dtsg=dtsg,
                profile_url=profile_url,
                max_count=max_count,
                is_cancelled=is_cancelled,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )
            for it in timeline_items:
                if it.get("type") in ("reel", "video"):
                    it_copy = dict(it)
                    it_copy["type"] = "reel"
                    it_id = str(it_copy["id"])
                    if it_id not in seen_ids:
                        seen_ids.add(it_id)
                        results.append(it_copy)
                        if progress_callback:
                            progress_callback(len(results), f"Discovered Instagram Reel: {it_copy['title'][:35]}")
                        if max_count is not None and len(results) >= max_count:
                            break

        return results

    def _scan_posts_rest_fallback(
        self,
        user_id: str,
        username: str,
        max_count: Optional[int] = None,
        seen_ids: Optional[set] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """REST endpoint fallback: /api/v1/feed/user/{user_id}/."""
        results: List[Dict[str, Any]] = []
        if seen_ids is None:
            seen_ids = set()
        cursor: Optional[str] = None

        csrf = self.session.cookies.get("csrftoken", domain=".instagram.com") or self.session.cookies.get("csrftoken") or ""
        headers = {
            "Accept": "*/*",
            "X-IG-App-ID": self.DEFAULT_APP_ID,
            "X-ASBD-ID": self.DEFAULT_ASBD_ID,
            "X-CSRFToken": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.BASE_URL}/{username}/",
        }

        while max_count is None or len(results) < max_count:
            if is_cancelled and is_cancelled():
                break

            url = f"{self.BASE_URL}/api/v1/feed/user/{user_id}/?count=12"
            if cursor:
                url += f"&max_id={cursor}"

            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception:
                break

            items = data.get("items", [])
            cursor = data.get("next_max_id")
            more_available = data.get("more_available", False)

            new_in_page = 0
            for node in items:
                decomposed = self._decompose_media_node(node, fallback_author=username)
                for it in decomposed:
                    it_id = it["id"]
                    if it_id in seen_ids:
                        continue
                    seen_ids.add(it_id)
                    new_in_page += 1
                    results.append(it)

                    if progress_callback:
                        progress_callback(len(results), f"Discovered Instagram {it['type'].capitalize()}: {it['title'][:35]}")

                    if max_count is not None and len(results) >= max_count:
                        break

            if new_in_page == 0 or not cursor or not more_available:
                break

            if self.request_delay > 0:
                time.sleep(self.request_delay)

        return results

    def scan_profile(
        self,
        profile_url: str,
        max_count: Optional[int] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Unified profile scanner for Instagram:
        Extracts tokens & user information, then scans both timeline posts (photos, carousels, videos)
        and dedicated Reels, returning a deduplicated unified media candidate list.
        """
        info = self.extract_profile_info(profile_url, is_cancelled=is_cancelled, log_callback=log_callback)
        username = info.get("username")
        user_id = info.get("user_id")

        if not username:
            if log_callback:
                log_callback(f"[INSTAGRAM] Could not parse username from URL: {profile_url}")
            return []

        all_items: List[Dict[str, Any]] = []
        seen_media_ids = set()

        # 1. Timeline Posts (Photos, Videos, Carousels)
        posts = self.scan_posts(
            username=username,
            user_id=user_id,
            lsd=info.get("lsd", ""),
            dtsg=info.get("dtsg", ""),
            profile_url=profile_url,
            max_count=max_count,
            is_cancelled=is_cancelled,
            progress_callback=progress_callback,
            log_callback=log_callback,
        )
        for p in posts:
            m_id = p["id"]
            if m_id not in seen_media_ids:
                seen_media_ids.add(m_id)
                all_items.append(p)

        # 2. Reels tab (if user_id is available)
        if user_id and not (is_cancelled and is_cancelled()):
            reels = self.scan_reels(
                user_id=user_id,
                username=username,
                lsd=info.get("lsd", ""),
                dtsg=info.get("dtsg", ""),
                profile_url=profile_url,
                max_count=max_count,
                is_cancelled=is_cancelled,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )
            for r in reels:
                m_id = r["id"]
                if m_id not in seen_media_ids:
                    seen_media_ids.add(m_id)
                    all_items.append(r)

        return all_items
