"""
tests/test_instagram_web_integration.py
Comprehensive unit test suite for Instagram Web GraphQL & REST Clean-Room Discovery Integration.

Tests:
1. Caption formatting & hashtag stripping (format_instagram_caption_title, clean_instagram_title).
2. Token & identifier harvesting from HTML (username, user_id, lsd, dtsg, csrf).
3. Media node decomposition (single photo, single video/reel, multi-item carousel album).
4. Timeline posts pagination via Polaris GraphQL and REST fallback.
5. Dedicated Reels pagination via Polaris Reels GraphQL.
6. Unified profile scanning (scan_profile).
7. Full integration with ProfileVideoDiscoveryEngine & InstagramVideoDiscoveryStrategy.
8. Full integration with ProfileScanManager (dual-engine inventory persistence & UI items).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import VideoItem, VideoStatus, MediaType
from core.inventory import (
    ProfileMediaInventory,
    ScanCompleteness,
    MediaInventoryType,
)
from core.platform.instagram import InstagramAdapter, clean_instagram_title
from core.platform.instagram_web import (
    InstagramWebClient,
    InstagramWebError,
    InstagramRateLimitError,
    format_instagram_caption_title,
)
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlRecordList
from downloader.profile_video_discovery_engine import (
    ProfileVideoDiscoveryEngine,
    InstagramVideoDiscoveryStrategy,
    DiscoveredVideoCandidate,
)
from downloader.profile_scan_manager import ProfileScanManager
from downloader.engine_router import EngineType


class TestInstagramWebIntegration(unittest.TestCase):
    """Unit test suite for Instagram Web clean-room discovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ig_inventory.db"
        self.inventory = ProfileMediaInventory(db_path=self.db_path)
        self.mock_gallerydl = MagicMock(spec=GalleryDlEngine)
        self.mock_gallerydl.is_available.return_value = True
        self.mock_gallerydl.get_version.return_value = "1.32.18"

        self.video_engine = ProfileVideoDiscoveryEngine(gallerydl_engine=self.mock_gallerydl)
        self.scan_manager = ProfileScanManager(
            inventory=self.inventory,
            gallerydl_engine=self.mock_gallerydl,
            video_discovery_engine=self.video_engine,
        )

    def tearDown(self):
        try:
            self.inventory.close()
            self.temp_dir.cleanup()
        except Exception:
            pass

    # =========================================================================
    # 1. Caption Formatting & Hashtag Stripping Tests
    # =========================================================================

    def test_01_format_caption_title_strips_hashtags(self):
        """Hashtags (# and full-width ＃) must be stripped, with English 30-word and Chinese 50-word bounds."""
        raw = "#nature #photography Beautiful sunset at Mount Fuji #japan"
        result = format_instagram_caption_title(raw, fallback="Instagram Photo 123")
        self.assertNotIn("#", result)
        self.assertNotIn("＃", result)
        self.assertEqual(result, "nature photography Beautiful sunset at Mount Fuji japan")

        # English truncation > 30 words
        long_en = " ".join([f"word{i}" for i in range(1, 40)])
        result_en = format_instagram_caption_title(long_en)
        self.assertTrue(result_en.endswith("..."))
        self.assertEqual(result_en, " ".join([f"word{i}" for i in range(1, 31)]) + "...")

        # Chinese truncation > 50 words/chars
        long_cn = "中" * 60
        result_cn = format_instagram_caption_title(long_cn)
        self.assertTrue(result_cn.endswith("..."))
        self.assertEqual(result_cn, ("中" * 50) + "...")

    def test_02_format_caption_title_only_hashtags_fallback(self):
        """Titles consisting only of '#' or '＃' must degrade gracefully to fallback."""
        raw = "# ####### ＃＃＃"
        result = format_instagram_caption_title(raw, fallback="Instagram Photo 9999", max_chars=35)
        self.assertEqual(result, "Instagram Photo 9999")

    def test_03_format_caption_title_empty_or_none(self):
        """Empty or None input must return the fallback string."""
        self.assertEqual(format_instagram_caption_title(None, fallback="Fallback 1"), "Fallback 1")
        self.assertEqual(format_instagram_caption_title("", fallback="Fallback 2"), "Fallback 2")
        self.assertEqual(format_instagram_caption_title("   \n\t  ", fallback="Fallback 3"), "Fallback 3")

    def test_04_format_caption_title_whitespace_collapsing(self):
        """Newlines, carriage returns, tabs, and multiple spaces must be collapsed into single space."""
        raw = "Line 1\n\nLine 2\r\n\tLine 3    with   spaces"
        result = format_instagram_caption_title(raw, max_chars=50)
        self.assertEqual(result, "Line 1 Line 2 Line 3 with spaces")

    def test_05_clean_instagram_title_in_adapter(self):
        """clean_instagram_title in instagram.py must strip '#' and bound to 30 English words / 50 Chinese words."""
        # English: over 30 words truncated to 30 words + ...
        raw_en = "word " * 40
        cleaned_en = clean_instagram_title(raw_title=raw_en, caption=raw_en, fallback="Instagram Reel 111")
        self.assertNotIn("#", cleaned_en)
        self.assertTrue(cleaned_en.endswith("..."))
        self.assertEqual(len(cleaned_en.replace("...", "").split()), 30)

        # Chinese: over 50 chars truncated to 50 chars + ...
        raw_cn = "中" * 60
        cleaned_cn = clean_instagram_title(raw_title=raw_cn, caption=raw_cn, fallback="Instagram Reel 222")
        self.assertNotIn("#", cleaned_cn)
        self.assertEqual(cleaned_cn, ("中" * 50) + "...")

    # =========================================================================
    # 2. Token & Identifier Extraction Tests
    # =========================================================================

    def test_06_extract_username_from_url(self):
        client = InstagramWebClient()
        self.assertEqual(client.extract_username_from_url("https://www.instagram.com/nasa/"), "nasa")
        self.assertEqual(client.extract_username_from_url("https://instagram.com/taylorswift"), "taylorswift")
        self.assertEqual(client.extract_username_from_url("https://www.instagram.com/natgeo/reels/"), "natgeo")
        self.assertEqual(client.extract_username_from_url("https://www.instagram.com/p/C-xyz123/"), "")

    @patch("requests.Session.get")
    def test_07_extract_profile_info_from_html(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.url = "https://www.instagram.com/nasa/"
        mock_resp.text = """
        <!DOCTYPE html>
        <html>
        <head>
            <script id="__eqmc" type="application/json">{"l":"mock_lsd_token_abc","f":"mock_dtsg_token_xyz"}</script>
        </head>
        <body>
            <script>
                var user_info = {"props":{"id":"528817151"},"username":"nasa"};
            </script>
        </body>
        </html>
        """
        mock_get.return_value = mock_resp

        client = InstagramWebClient()
        info = client.extract_profile_info("https://www.instagram.com/nasa/")

        self.assertEqual(info["username"], "nasa")
        self.assertEqual(info["user_id"], "528817151")
        self.assertEqual(info["lsd"], "mock_lsd_token_abc")
        self.assertEqual(info["dtsg"], "mock_dtsg_token_xyz")
        self.assertFalse(info["is_login_redirect"])

    # =========================================================================
    # 3. Media Node Decomposition Tests
    # =========================================================================

    def test_08_decompose_single_photo_node(self):
        client = InstagramWebClient()
        node = {
            "id": "3100000000000000001",
            "code": "C123Photo",
            "media_type": 1,
            "caption": {"text": "A stunning mountain view #mountains #travel"},
            "user": {"username": "photographer"},
            "image_versions2": {
                "candidates": [
                    {"url": "https://scontent.cdninstagram.com/v/t51.2885-15/photo_hd.jpg"}
                ]
            },
        }

        items = client._decompose_media_node(node)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "3100000000000000001")
        self.assertEqual(item["type"], "photo")
        self.assertEqual(item["direct_url"], "https://scontent.cdninstagram.com/v/t51.2885-15/photo_hd.jpg")
        self.assertNotIn("#", item["title"])
        self.assertEqual(item["sequence_index"], 1)
        self.assertEqual(item["media_count"], 1)

    def test_09_decompose_single_reel_node(self):
        client = InstagramWebClient()
        node = {
            "id": "3100000000000000002",
            "code": "C123Reel",
            "media_type": 2,
            "product_type": "clips",
            "caption": {"text": "Exciting dance routine #viral #dance"},
            "user": {"username": "dancer"},
            "video_duration": 42.5,
            "video_versions": [
                {"url": "https://scontent.cdninstagram.com/v/t50.2886-16/reel_video.mp4"}
            ],
            "image_versions2": {
                "candidates": [
                    {"url": "https://scontent.cdninstagram.com/v/t51.2885-15/thumb.jpg"}
                ]
            },
        }

        items = client._decompose_media_node(node)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "3100000000000000002")
        self.assertEqual(item["type"], "reel")
        self.assertEqual(item["direct_url"], "https://scontent.cdninstagram.com/v/t50.2886-16/reel_video.mp4")
        self.assertEqual(item["duration"], 42)
        self.assertNotIn("#", item["title"])

    def test_10_decompose_carousel_album_node(self):
        """A carousel album with 2 photos and 1 video must decompose into 3 distinct items with parent-child linkage."""
        client = InstagramWebClient()
        node = {
            "id": "3100000000000000003",
            "code": "C123Carousel",
            "media_type": 8,
            "caption": {"text": "Trip to Japan album #japan #kyoto #memories"},
            "user": {"username": "traveler"},
            "carousel_media": [
                {
                    "id": "sub_photo_1",
                    "media_type": 1,
                    "image_versions2": {"candidates": [{"url": "https://cdn.example.com/p1.jpg"}]},
                },
                {
                    "id": "sub_video_2",
                    "media_type": 2,
                    "video_duration": 18.0,
                    "video_versions": [{"url": "https://cdn.example.com/v2.mp4"}],
                    "image_versions2": {"candidates": [{"url": "https://cdn.example.com/thumb2.jpg"}]},
                },
                {
                    "id": "sub_photo_3",
                    "media_type": 1,
                    "image_versions2": {"candidates": [{"url": "https://cdn.example.com/p3.jpg"}]},
                },
            ],
        }

        items = client._decompose_media_node(node)
        self.assertEqual(len(items), 3)

        # Child 1: Photo
        self.assertEqual(items[0]["id"], "sub_photo_1")
        self.assertEqual(items[0]["type"], "photo")
        self.assertEqual(items[0]["sequence_index"], 1)
        self.assertEqual(items[0]["media_count"], 3)
        self.assertEqual(items[0]["parent_post_id"], "3100000000000000003")

        # Child 2: Video
        self.assertEqual(items[1]["id"], "sub_video_2")
        self.assertEqual(items[1]["type"], "video")
        self.assertEqual(items[1]["sequence_index"], 2)
        self.assertEqual(items[1]["duration"], 18)

        # Child 3: Photo
        self.assertEqual(items[2]["id"], "sub_photo_3")
        self.assertEqual(items[2]["type"], "photo")
        self.assertEqual(items[2]["sequence_index"], 3)

    # =========================================================================
    # 4. GraphQL Pagination & REST Fallback Tests
    # =========================================================================

    @patch("requests.Session.post")
    @patch("core.platform.instagram_web.InstagramWebClient.extract_profile_info", return_value={"user_id": "12345", "lsd": "test_lsd", "embedded_items": []})
    def test_11_scan_posts_graphql_pagination(self, mock_extract, mock_post):
        """Verifies multi-page GraphQL pagination via end_cursor."""
        page1 = {
            "data": {
                "xdt_api__v1__feed__user_timeline_graphql_connection": {
                    "edges": [
                        {
                            "node": {
                                "id": "post_101",
                                "code": "C101",
                                "media_type": 1,
                                "caption": {"text": "First page photo #art"},
                                "image_versions2": {"candidates": [{"url": "https://cdn.example.com/p101.jpg"}]},
                            }
                        }
                    ],
                    "page_info": {
                        "has_next_page": True,
                        "end_cursor": "cursor_page_2",
                    },
                }
            }
        }
        page2 = {
            "data": {
                "xdt_api__v1__feed__user_timeline_graphql_connection": {
                    "edges": [
                        {
                            "node": {
                                "id": "post_102",
                                "code": "C102",
                                "media_type": 1,
                                "caption": {"text": "Second page photo #gallery"},
                                "image_versions2": {"candidates": [{"url": "https://cdn.example.com/p102.jpg"}]},
                            }
                        }
                    ],
                    "page_info": {
                        "has_next_page": False,
                        "end_cursor": None,
                    },
                }
            }
        }

        r1 = MagicMock()
        r1.status_code = 200
        r1.json.return_value = page1
        r1.text = json.dumps(page1)

        r2 = MagicMock()
        r2.status_code = 200
        r2.json.return_value = page2
        r2.text = json.dumps(page2)

        mock_post.side_effect = [r1, r2]

        client = InstagramWebClient(request_delay=0)
        items = client.scan_posts(username="art_creator")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], "post_101")
        self.assertEqual(items[1]["id"], "post_102")
        self.assertEqual(mock_post.call_count, 2)

    @patch("requests.Session.post")
    @patch("requests.Session.get")
    def test_12_scan_posts_rest_fallback(self, mock_get, mock_post):
        """When GraphQL fails with errors, the client must automatically fall back to the REST endpoint."""
        # GraphQL returns error
        err_resp = MagicMock()
        err_resp.status_code = 200
        err_resp.json.return_value = {"errors": [{"message": "Rate limit / doc_id error"}]}
        err_resp.text = json.dumps({"errors": [{"message": "Rate limit / doc_id error"}]})
        mock_post.return_value = err_resp

        # REST endpoint returns items
        rest_data = {
            "items": [
                {
                    "id": "rest_post_201",
                    "code": "C201",
                    "media_type": 1,
                    "caption": {"text": "REST recovered photo #awesome"},
                    "image_versions2": {"candidates": [{"url": "https://cdn.example.com/rest201.jpg"}]},
                }
            ],
            "more_available": False,
            "next_max_id": None,
        }
        rest_resp = MagicMock()
        rest_resp.status_code = 200
        rest_resp.json.return_value = rest_data
        mock_get.return_value = rest_resp

        client = InstagramWebClient(request_delay=0)
        items = client.scan_posts(username="artist", user_id="123456")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "rest_post_201")
        self.assertEqual(items[0]["direct_url"], "https://cdn.example.com/rest201.jpg")

    # =========================================================================
    # 5. Reels Tab GraphQL Pagination Tests
    # =========================================================================

    @patch("requests.Session.post")
    def test_13_scan_reels_graphql(self, mock_post):
        reels_data = {
            "data": {
                "fetch__XDTUserDict": {
                    "clips_user_connection": {
                        "edges": [
                            {
                                "node": {
                                    "media": {
                                        "id": "reel_301",
                                        "code": "CReel301",
                                        "media_type": 2,
                                        "caption": {"text": "Amazing trick shot #skills"},
                                        "video_duration": 15.0,
                                        "video_versions": [{"url": "https://cdn.example.com/reel301.mp4"}],
                                        "image_versions2": {"candidates": [{"url": "https://cdn.example.com/thumb301.jpg"}]},
                                    }
                                }
                            }
                        ],
                        "page_info": {"has_next_page": False, "end_cursor": None},
                    }
                }
            }
        }
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = reels_data
        r.text = json.dumps(reels_data)
        mock_post.return_value = r

        client = InstagramWebClient(request_delay=0)
        items = client.scan_reels(user_id="123456", username="trickster")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "reel_301")
        self.assertEqual(items[0]["type"], "reel")
        self.assertEqual(items[0]["direct_url"], "https://cdn.example.com/reel301.mp4")

    # =========================================================================
    # 6. InstagramVideoDiscoveryStrategy Integration Tests
    # =========================================================================

    @patch("core.platform.instagram_web.InstagramWebClient.extract_profile_info")
    @patch("core.platform.instagram_web.InstagramWebClient.scan_posts")
    @patch("core.platform.instagram_web.InstagramWebClient.scan_reels")
    def test_14_instagram_video_discovery_strategy(self, mock_scan_reels, mock_scan_posts, mock_extract_info):
        mock_extract_info.return_value = {
            "username": "superstar",
            "user_id": "998877",
            "lsd": "mock_lsd",
            "dtsg": "mock_dtsg",
        }
        mock_scan_posts.return_value = [
            {
                "id": "vid_401",
                "code": "CVid401",
                "type": "video",
                "title": "Music Video Clip",
                "caption": "Music Video Clip #music #song",
                "post_url": "https://www.instagram.com/p/CVid401/",
                "direct_url": "https://cdn.example.com/vid401.mp4",
                "duration": 60,
                "thumbnail": "https://cdn.example.com/thumb401.jpg",
                "taken_at": 1690000000,
            }
        ]
        mock_scan_reels.return_value = [
            {
                "id": "reel_402",
                "code": "CReel402",
                "type": "reel",
                "title": "Backstage Moment",
                "caption": "Backstage Moment #bts",
                "post_url": "https://www.instagram.com/reel/CReel402/",
                "direct_url": "https://cdn.example.com/reel402.mp4",
                "duration": 25,
                "thumbnail": "https://cdn.example.com/thumb402.jpg",
                "taken_at": 1690000050,
            }
        ]

        strategy = InstagramVideoDiscoveryStrategy(gallerydl_engine=self.mock_gallerydl)
        res = strategy.discover_candidates(profile_url="https://www.instagram.com/superstar/")

        self.assertEqual(res.status, ScanCompleteness.COMPLETE)
        self.assertEqual(len(res.candidates), 2)

        # Candidate 1: Video
        c1 = res.candidates[0]
        self.assertEqual(c1.media_id, "CVid401")
        self.assertEqual(c1.media_type, MediaType.VIDEO)
        self.assertEqual(c1.title, "Music Video Clip")
        self.assertEqual(c1.duration_seconds, 60)

        # Candidate 2: Reel
        c2 = res.candidates[1]
        self.assertEqual(c2.media_id, "CReel402")
        self.assertEqual(c2.media_type, MediaType.REEL)
        self.assertEqual(c2.title, "Backstage Moment")
        self.assertEqual(c2.duration_seconds, 25)

    # =========================================================================
    # 7. ProfileScanManager Instagram Integration Tests
    # =========================================================================

    @patch("core.platform.instagram_web.InstagramWebClient.extract_profile_info")
    @patch("core.platform.instagram_web.InstagramWebClient.scan_posts")
    def test_15_profile_scan_manager_instagram_photo_enrichment(self, mock_scan_posts, mock_extract_info):
        """Verifies that ProfileScanManager discovers Instagram photos and carousels, populating inventory and UI."""
        # gallery-dl returns 0 photos
        self.mock_gallerydl.extract_metadata.return_value = GalleryDlRecordList([])

        mock_extract_info.return_value = {
            "username": "photogallery",
            "user_id": "112233",
            "lsd": "mock_lsd",
            "dtsg": "mock_dtsg",
        }
        mock_scan_posts.return_value = [
            {
                "id": "photo_501",
                "parent_post_id": "post_500",
                "code": "CPhoto501",
                "type": "photo",
                "title": "Kyoto Temple Garden",
                "caption": "Kyoto Temple Garden #kyoto #japan",
                "post_url": "https://www.instagram.com/p/CPhoto501/",
                "direct_url": "https://cdn.example.com/photo501.jpg",
                "thumbnail": "https://cdn.example.com/photo501.jpg",
                "sequence_index": 1,
                "media_count": 2,
                "author": "photogallery",
            },
            {
                "id": "photo_502",
                "parent_post_id": "post_500",
                "code": "CPhoto501",
                "type": "photo",
                "title": "Kyoto Temple Garden",
                "caption": "Kyoto Temple Garden #kyoto #japan",
                "post_url": "https://www.instagram.com/p/CPhoto501/",
                "direct_url": "https://cdn.example.com/photo502.jpg",
                "thumbnail": "https://cdn.example.com/photo502.jpg",
                "sequence_index": 2,
                "media_count": 2,
                "author": "photogallery",
            },
        ]

        # Video engine returns empty for this test
        self.video_engine.discover = MagicMock(return_value=MagicMock(candidates=[], status=ScanCompleteness.COMPLETE, error=None))

        res = self.scan_manager.scan_profile(
            url="https://www.instagram.com/photogallery/",
            platform="instagram",
        )

        # Discovered 2 photos
        self.assertEqual(len(res.videos), 2)
        v1 = res.videos[0]
        self.assertEqual(v1.media_type, MediaType.PHOTO)
        self.assertEqual(v1.duration, "-")
        self.assertEqual(v1.status, VideoStatus.READY)
        self.assertNotIn("#", v1.title)
        self.assertEqual(v1.title, "Kyoto Temple Garden")

        # Inventory persistence check
        stored_items = self.inventory.get_media_items_for_post("instagram", "ig_post_post_500")
        self.assertEqual(len(stored_items), 2)
        self.assertEqual(stored_items[0].media_type, MediaInventoryType.IMAGE)
        self.assertEqual(stored_items[0].media_sequence_index, 1)
        self.assertEqual(stored_items[1].media_sequence_index, 2)


    def test_16_extract_media_from_html(self):
        """extract_media_from_html extracts items from RelayPrefetchedStreamCache script blocks."""
        html = '''
        <html>
        <head><title>Profile</title></head>
        <body>
        <script type="application/json" data-sjs>
        {"require":[["RelayPrefetchedStreamCache","next",[],[null,{"result":{"data":{"user":{"edge_owner_to_timeline_media":{"edges":[{"node":{"__typename":"GraphImage","pk":"998877","code":"C_test123","display_uri":"https://cdn.example.com/test.jpg","caption":{"text":"Hello from HTML #tag"},"taken_at_timestamp":1700000000}}]}}}}}]]]}
        </script>
        </body>
        </html>
        '''
        client = InstagramWebClient()
        items = client.extract_media_from_html(html, fallback_author="testuser")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "998877")
        self.assertEqual(item["code"], "C_test123")
        self.assertEqual(item["title"], "Hello from HTML tag")
        self.assertNotIn("#", item["title"])
        self.assertEqual(item["direct_url"], "https://cdn.example.com/test.jpg")
        self.assertEqual(item["author"], "testuser")


if __name__ == "__main__":
    unittest.main()
