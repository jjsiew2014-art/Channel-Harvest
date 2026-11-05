"""
tests/test_facebook_comet_integration.py
Comprehensive unit test suite for Facebook Comet GraphQL Clean-Room Discovery Integration.

Tests:
1. Token harvesting from HTML (lsd, dtsg, pageID, reelsID, photosID).
2. Video enumeration via Comet GraphQL (watch/?v= canonical URLs, titles, cursors).
3. Reels enumeration via Comet GraphQL (reel/ canonical URLs, JSON Lines format).
4. Photo enumeration via Comet GraphQL (direct high-res image URIs, post URLs).
5. Error handling: rate-limits, network timeouts, invalid tokens.
6. Full integration with ProfileVideoDiscoveryEngine & FacebookVideoDiscoveryStrategy.
7. Full integration with ProfileScanManager (photo fallback & video candidate routing).
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
from core.platform.facebook import FacebookAdapter
from core.platform.facebook_comet import (
    FacebookCometClient,
    FacebookCometError,
    FacebookCometRateLimitError,
)
from downloader.gallerydl_engine import GalleryDlEngine, GalleryDlRecordList
from downloader.profile_video_discovery_engine import (
    ProfileVideoDiscoveryEngine,
    FacebookVideoDiscoveryStrategy,
    DiscoveredVideoCandidate,
)
from downloader.profile_scan_manager import ProfileScanManager
from downloader.engine_router import EngineType


class TestFacebookCometIntegration(unittest.TestCase):
    """Unit test suite for Facebook Comet GraphQL Clean-Room discovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_comet_inventory.db"
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

        # Create a valid test cookie file
        self.cookie_file = Path(self.temp_dir.name) / "fb_cookies.txt"
        self.cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1798765432\tc_user\t100012345678\n"
            ".facebook.com\tTRUE\t/\tTRUE\t1798765432\txs\t2%3Aabc123xyz\n"
        )

    def tearDown(self):
        try:
            self.inventory.close()
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_token_harvesting_from_html(self):
        """Test 1: Verify extraction of dynamic tokens and IDs from Facebook HTML."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file))

        mock_html = """
        <html>
        <head>
            <script>["LSD",[],{"token":"TEST_LSD_TOKEN_999"},123]</script>
            <script>["DTSGInitialData",[],{"token":"TEST_DTSG_TOKEN_888"},456]</script>
        </head>
        <body>
            <div data-pagelet="ProfileAppSection">
                <a href="/pages/123456789/videos" pageid="123456789">Videos</a>
                <div data-meta='{"tab_key":"owner_reels","id":"REELS_CONTAINER_ID_555"}'></div>
                <div data-meta='{"photos_by":{"id":"PHOTOS_CONTAINER_ID_444"}}'></div>
            </div>
        </body>
        </html>
        """

        with patch.object(client.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.text = mock_html
            mock_resp.url = "https://www.facebook.com/TestPage/videos"
            mock_get.return_value = mock_resp

            tokens = client.extract_page_tokens("https://www.facebook.com/TestPage/")

        self.assertEqual(tokens["lsd"], "TEST_LSD_TOKEN_999")
        self.assertEqual(tokens["dtsg"], "TEST_DTSG_TOKEN_888")
        self.assertEqual(tokens["page_id"], "123456789")
        self.assertEqual(tokens["reels_page_id"], "REELS_CONTAINER_ID_555")
        self.assertEqual(tokens["photos_by_id"], "PHOTOS_CONTAINER_ID_444")
        self.assertFalse(tokens["is_login_redirect"])

    def test_02_video_enumeration_graphql(self):
        """Test 2: Verify video enumeration via Comet GraphQL returns watch URLs and metadata."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        # Mock page 1 response with 2 videos + cursor
        mock_data_page1 = {
            "data": {
                "node": {
                    "all_videos": {
                        "edges": [
                            {
                                "cursor": "CURSOR_PAGE_2",
                                "node": {
                                    "id": "1001",
                                    "name": "First Video Title",
                                    "playable_duration_in_ms": 125000,
                                    "preferred_thumbnail": {"image": {"uri": "https://fbcdn.net/thumb1.jpg"}},
                                    "creation_time": 1700000000,
                                },
                            },
                            {
                                "cursor": "CURSOR_PAGE_2",
                                "node": {
                                    "id": "1002",
                                    "savable_description": {"text": "Second Video Caption"},
                                    "playable_duration_in_ms": 60000,
                                    "preferred_thumbnail": {"image": {"uri": "https://fbcdn.net/thumb2.jpg"}},
                                },
                            },
                        ]
                    }
                }
            }
        }
        # Mock page 2 response with 1 video, no cursor (end of stream)
        mock_data_page2 = {
            "data": {
                "node": {
                    "all_videos": {
                        "edges": [
                            {
                                "cursor": None,
                                "node": {
                                    "id": "1003",
                                    "name": "Third Video Title",
                                    "playable_duration_in_ms": 45000,
                                },
                            }
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post:
            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.json.return_value = mock_data_page1

            resp2 = MagicMock()
            resp2.status_code = 200
            resp2.json.return_value = mock_data_page2

            mock_post.side_effect = [resp1, resp2]

            videos = client.scan_videos(
                page_id="123456789",
                lsd="TEST_LSD",
                dtsg="TEST_DTSG",
                profile_url="https://www.facebook.com/TestPage/",
                max_count=10,
            )

        self.assertEqual(len(videos), 3)
        self.assertEqual(videos[0]["id"], "1001")
        self.assertEqual(videos[0]["url"], "https://www.facebook.com/watch/?v=1001")
        self.assertEqual(videos[0]["title"], "First Video Title")
        self.assertEqual(videos[0]["duration"], 125)

        self.assertEqual(videos[1]["id"], "1002")
        self.assertEqual(videos[1]["title"], "Second Video Caption")

        self.assertEqual(videos[2]["id"], "1003")
        self.assertEqual(videos[2]["url"], "https://www.facebook.com/watch/?v=1003")

    def test_03_reels_enumeration_json_lines(self):
        """Test 3: Verify Reels enumeration handles Facebook's streaming JSON-Lines format."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        mock_reels_data = {
            "data": {
                "node": {
                    "aggregated_fb_shorts": {
                        "edges": [
                            {
                                "cursor": "REEL_CURSOR_1",
                                "node": {
                                    "id": "reel_node_901",
                                    "message": {"text": "Viral Reel 1"},
                                    "thumbnail_uri": "https://fbcdn.net/reel_thumb1.jpg",
                                },
                                "profile_reel_node": {
                                    "node": {"video": {"id": "901"}}
                                },
                            },
                            {
                                "cursor": None,
                                "node": {
                                    "id": "902",
                                    "message": {"text": "Viral Reel 2"},
                                    "thumbnail_uri": "https://fbcdn.net/reel_thumb2.jpg",
                                },
                            },
                        ]
                    }
                }
            }
        }
        raw_text_json_lines = json.dumps(mock_reels_data)

        with patch.object(client, "_post_graphql") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = raw_text_json_lines
            mock_post.return_value = resp

            reels = client.scan_reels(
                reels_page_id="REELS_PAGE_123",
                lsd="TEST_LSD",
                dtsg="TEST_DTSG",
                profile_url="https://www.facebook.com/TestPage/",
                max_count=10,
            )

        self.assertEqual(len(reels), 2)
        self.assertEqual(reels[0]["id"], "901")
        self.assertEqual(reels[0]["url"], "https://www.facebook.com/reel/901")
        self.assertEqual(reels[0]["type"], "reel")
        self.assertEqual(reels[0]["title"], "Viral Reel 1")

        self.assertEqual(reels[1]["id"], "902")
        self.assertEqual(reels[1]["url"], "https://www.facebook.com/reel/902")
        self.assertEqual(reels[1]["type"], "reel")

    def test_04_photos_enumeration_graphql(self):
        """Test 4: Verify photo enumeration via Comet GraphQL returns high-res image URIs."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        mock_photos_data = {
            "data": {
                "node": {
                    "pageItems": {
                        "edges": [
                            {
                                "cursor": "PHOTO_CUR_1",
                                "node": {
                                    "id": "photo_888",
                                    "url": "https://www.facebook.com/photo.php?fbid=photo_888",
                                    "viewer_image": {"uri": "https://scontent.net/photo_888_highres.jpg"},
                                },
                            }
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_photos_data
            mock_post.return_value = resp

            photos = client.scan_photos(
                photos_id="PHOTOS_TAB_456",
                lsd="TEST_LSD",
                dtsg="TEST_DTSG",
                profile_url="https://www.facebook.com/TestPage/",
                max_count=10,
            )

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["id"], "photo_888")
        self.assertEqual(photos[0]["direct_url"], "https://scontent.net/photo_888_highres.jpg")
        self.assertEqual(photos[0]["post_url"], "https://www.facebook.com/photo.php?fbid=photo_888")
        self.assertEqual(photos[0]["title"], "Facebook Photo photo_888")

    def test_04b_fetch_photo_caption_parsing(self):
        """Test 4b: Verify fetch_photo_caption parses meta description, unescapes entities, and handles newlines."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        html_sample = (
            '<!DOCTYPE html><html><head>'
            '<meta name="description" content="&#x5728;&#x6b64;&#x9810;&#x795d;&#x5404;&#x4f4d;&#x6a02;&#x8ff7;&#x670b;&#x53cb; &quot;&#x6bcd;&#x89aa;&#x7bc0;&#x6109;&#x5feb;&quot; \n\n願我們的音樂為您帶來溫暖" />'
            '</head><body></body></html>'
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [html_sample.encode("utf-8")]

        with patch.object(client.session, "get", return_value=mock_resp):
            caption = client.fetch_photo_caption("1493250019258573")

        self.assertIsNotNone(caption)
        self.assertIn("在此預祝各位樂迷朋友", caption)
        self.assertIn('"母親節愉快"', caption)
        self.assertIn("願我們的音樂為您帶來溫暖", caption)

    def test_04c_photos_caption_resolution_and_truncation(self):
        """Test 4c: Verify scan_photos resolves authentic photo captions and truncates >50 Chinese words with ..."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        long_caption = (
            "在此預祝各位樂迷朋友母親節愉快願我們的音樂能繼續為您與摯愛之人帶來溫暖喜悅與美好的回憶親情永駐健康快樂萬事如意天天開心幸福美滿永遠相隨伴你左右幸福平安"
        )
        short_caption = "卜卜脆～ 大家猜猜看這是誰？"

        mock_photos_data = {
            "data": {
                "node": {
                    "pageItems": {
                        "edges": [
                            {
                                "cursor": "PHOTO_CUR_1",
                                "node": {
                                    "id": "photo_101",
                                    "url": "https://www.facebook.com/photo.php?fbid=photo_101",
                                    "viewer_image": {"uri": "https://scontent.net/photo_101.jpg"},
                                },
                            },
                            {
                                "cursor": "PHOTO_CUR_2",
                                "node": {
                                    "id": "photo_102",
                                    "url": "https://www.facebook.com/photo.php?fbid=photo_102",
                                    "viewer_image": {"uri": "https://scontent.net/photo_102.jpg"},
                                },
                            },
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post, \
             patch.object(client, "fetch_photo_caption") as mock_fetch_caption:

            mock_graphql_resp = MagicMock()
            mock_graphql_resp.status_code = 200
            mock_graphql_resp.json.return_value = mock_photos_data
            mock_post.return_value = mock_graphql_resp

            def mock_caption_lookup(pid, timeout=4.0):
                if pid == "photo_101":
                    return long_caption
                elif pid == "photo_102":
                    return short_caption
                return None

            mock_fetch_caption.side_effect = mock_caption_lookup

            photos = client.scan_photos(
                photos_id="PHOTOS_TAB_999",
                lsd="TEST_LSD",
                dtsg="TEST_DTSG",
                profile_url="https://www.facebook.com/TestPage/",
                resolve_captions=True,
            )

        self.assertEqual(len(photos), 2)

        # photo_101 has a long caption > 50 Chinese words: should be truncated to 50 chars + "..."
        p1 = photos[0]
        self.assertEqual(p1["id"], "photo_101")
        self.assertTrue(p1["title"].endswith("..."))
        # The content before '...' must be at most 50 words/chars
        title_core = p1["title"][:-3]
        self.assertLessEqual(len(title_core), 50)
        self.assertEqual(p1["title"], long_caption[:50].rstrip(" .,;:-_，。！？；：、") + "...")
        self.assertEqual(p1["caption"], long_caption)

        # photo_102 has a short caption <= 35 chars: should remain intact without "..."
        p2 = photos[1]
        self.assertEqual(p2["id"], "photo_102")
        self.assertEqual(p2["title"], short_caption)
        self.assertEqual(p2["caption"], short_caption)

    def test_04d_photos_fallback_when_caption_unavailable(self):
        """Test 4d: Verify scan_photos falls back cleanly to 'Facebook Photo {id}' when no caption exists."""
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        mock_photos_data = {
            "data": {
                "node": {
                    "pageItems": {
                        "edges": [
                            {
                                "cursor": "PHOTO_CUR_FALLBACK",
                                "node": {
                                    "id": "1493250019258573",
                                    "accessibility_caption": "No photo description available.",
                                    "url": "https://www.facebook.com/photo.php?fbid=1493250019258573",
                                    "viewer_image": {"uri": "https://scontent.net/photo_fallback.jpg"},
                                },
                            }
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post, \
             patch.object(client, "fetch_photo_caption", return_value=None):

            mock_graphql_resp = MagicMock()
            mock_graphql_resp.status_code = 200
            mock_graphql_resp.json.return_value = mock_photos_data
            mock_post.return_value = mock_graphql_resp

            photos = client.scan_photos(
                photos_id="PHOTOS_TAB_FALLBACK",
                lsd="TEST_LSD",
                dtsg="TEST_DTSG",
                profile_url="https://www.facebook.com/TestPage/",
                resolve_captions=True,
            )

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["id"], "1493250019258573")
        self.assertEqual(photos[0]["title"], "Facebook Photo 1493250019258573")

    def test_05_strategy_comet_discovery_with_cookies(self):
        """
        Test 5: Verify FacebookVideoDiscoveryStrategy executes Comet discovery
        when a valid cookie file is provided and returns extracted candidates.
        """
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)
        profile_url = "https://www.facebook.com/TestPage/"

        mock_comet_records = [
            {
                "type": "video",
                "video_id": "vid_2001",
                "url": "https://www.facebook.com/watch/?v=vid_2001",
                "title": "Discovered Comet Video",
                "duration": 90,
                "thumbnail": "https://fbcdn.net/thumb2001.jpg",
                "discovery_method": "facebook_comet_graphql",
            },
            {
                "type": "reel",
                "video_id": "3001",
                "url": "https://www.facebook.com/reel/3001",
                "title": "Discovered Comet Reel",
                "thumbnail": "https://fbcdn.net/thumb3001.jpg",
                "discovery_method": "facebook_comet_graphql",
            },
        ]

        with patch.object(strategy, "_query_comet_api", return_value=mock_comet_records):
            result = strategy.discover_candidates(
                profile_url=profile_url,
                custom_cookie_file=str(self.cookie_file),
            )

        self.assertEqual(result.status, ScanCompleteness.COMPLETE)
        self.assertEqual(len(result.candidates), 2)

        cand1 = result.candidates[0]
        self.assertEqual(cand1.video_url, "https://www.facebook.com/watch/?v=vid_2001")
        self.assertEqual(cand1.media_type, MediaType.VIDEO)
        self.assertEqual(cand1.metadata_status, "extracted")
        self.assertEqual(cand1.title, "Discovered Comet Video")
        self.assertEqual(cand1.duration_seconds, 90)

        cand2 = result.candidates[1]
        self.assertEqual(cand2.video_url, "https://www.facebook.com/reel/3001")
        self.assertEqual(cand2.media_type, MediaType.REEL)
        self.assertEqual(cand2.metadata_status, "extracted")

    def test_06_profile_scan_manager_comet_photo_fallback(self):
        """
        Test 6: Verify ProfileScanManager falls back to Facebook Comet photo discovery
        when gallery-dl yields 0 photos, merging high-res photos into inventory.
        """
        self.mock_gallerydl.extract_metadata.return_value = GalleryDlRecordList([])

        mock_tokens = {
            "lsd": "MOCK_LSD",
            "dtsg": "MOCK_DTSG",
            "page_id": "PAGE_111",
            "photos_by_id": "PHOTOS_222",
            "reels_page_id": "REELS_333",
            "is_login_redirect": False,
        }
        mock_photos = [
            {
                "id": "photo_comet_1",
                "direct_url": "https://fbcdn.net/highres_1.jpg",
                "post_url": "https://www.facebook.com/photo.php?fbid=photo_comet_1",
                "type": "photo",
                "title": "Photo Title 1",
            }
        ]

        with patch("core.platform.facebook_comet.FacebookCometClient.extract_page_tokens", return_value=mock_tokens), \
             patch("core.platform.facebook_comet.FacebookCometClient.scan_photos", return_value=mock_photos), \
             patch.object(self.video_engine, "discover") as mock_vid_discover:

            mock_vid_discover.return_value = MagicMock(candidates=[], diagnostics={}, status=ScanCompleteness.FAILED, error=None)

            result = self.scan_manager.scan_profile(
                url="https://www.facebook.com/TestPage/",
                platform="facebook",
                custom_cookie_file=str(self.cookie_file),
            )

        self.assertEqual(len(result.videos), 1)
        v = result.videos[0]
        self.assertEqual(v.media_type, MediaType.PHOTO)
        self.assertEqual(v.url, "https://fbcdn.net/highres_1.jpg")
        self.assertEqual(v.video_id, "fb_photo_photo_comet_1")
        self.assertEqual(v.extra_metadata["engine"], EngineType.GALLERY_DL)

    def test_07_adapter_get_comet_client_helper(self):
        """Test 7: Verify FacebookAdapter helper creates an initialized CometClient."""
        adapter = FacebookAdapter()
        client = adapter.get_comet_client(custom_cookie_file=str(self.cookie_file))
        self.assertIsInstance(client, FacebookCometClient)
        self.assertTrue(client.has_cookies)


    def test_08_strategy_comet_discovery_unauthenticated_public_mode(self):
        """
        Test 8: Verify FacebookVideoDiscoveryStrategy executes Comet discovery
        in unauthenticated public mode when custom_cookie_file is None or empty.
        """
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)
        profile_url = "https://www.facebook.com/HongYongMusic/"

        mock_comet_records = [
            {
                "type": "video",
                "video_id": "4001",
                "url": "https://www.facebook.com/watch/?v=4001",
                "title": "Public Facebook Video",
                "duration": 60,
                "discovery_method": "facebook_comet_graphql",
            },
            {
                "type": "reel",
                "video_id": "5001",
                "url": "https://www.facebook.com/reel/5001",
                "title": "Public Facebook Reel",
                "discovery_method": "facebook_comet_graphql",
            },
        ]

        with patch.object(strategy, "_query_comet_api", return_value=mock_comet_records) as mock_query:
            result = strategy.discover_candidates(
                profile_url=profile_url,
                custom_cookie_file=None,
            )
            # Verify _query_comet_api was called with custom_cookie_file=None
            self.assertIsNone(mock_query.call_args[1]["custom_cookie_file"])

        self.assertEqual(result.status, ScanCompleteness.COMPLETE)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.candidates[0].media_type, MediaType.VIDEO)
        self.assertEqual(result.candidates[0].metadata_status, "extracted")
        self.assertEqual(result.candidates[1].media_type, MediaType.REEL)
        self.assertEqual(result.candidates[1].metadata_status, "extracted")

    def test_09_strategy_comet_discovery_auth_required_login_redirect(self):
        """
        Test 9: Verify FacebookVideoDiscoveryStrategy returns AUTH_REQUIRED
        when Comet discovery detects a private page / login wall without cookies.
        """
        strategy = FacebookVideoDiscoveryStrategy(self.mock_gallerydl)
        profile_url = "https://www.facebook.com/PrivatePage/"

        def mock_query_auth_req(profile_url, custom_cookie_file, **kwargs):
            diag = kwargs.get("diagnostics", {})
            diag["failure_reason"] = "AUTH_REQUIRED"
            diag["error"] = "Facebook session expired or login required."
            return []

        with patch.object(strategy, "_query_comet_api", side_effect=mock_query_auth_req):
            result = strategy.discover_candidates(
                profile_url=profile_url,
                custom_cookie_file=None,
            )

        self.assertEqual(result.status, ScanCompleteness.FAILED)
        self.assertEqual(result.failure_reason, "AUTH_REQUIRED")

    def test_10_format_caption_title_truncation(self):
        """
        Test 10: Verify format_caption_title normalizes newlines and whitespace,
        truncates captions longer than 35 characters to 35 chars + '...',
        and leaves captions <= 35 characters intact.
        """
        from core.platform.facebook_comet import format_caption_title

        # 1. Short Chinese caption <= 50 words/chars
        short_cap = "一天一首新年歌 - 謝采妘『賀新年』"
        self.assertEqual(format_caption_title(short_cap), short_cap)

        # 2. Chinese capped at 50 words/chars
        exact_50 = "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十"
        self.assertEqual(format_caption_title(exact_50), exact_50)
        long_chinese = exact_50 + "超出的額外文字"
        self.assertEqual(format_caption_title(long_chinese), exact_50 + "...")

        # 3. English capped at 30 words
        english_short = "This is a short english title with ten words here"
        self.assertEqual(format_caption_title(english_short), english_short)
        english_long = " ".join([f"word{i}" for i in range(1, 40)])
        expected_english = " ".join([f"word{i}" for i in range(1, 31)]) + "..."
        self.assertEqual(format_caption_title(english_long), expected_english)

        # 4. Strip '#' characters
        self.assertEqual(format_caption_title("#谢采妘 #柔情蜜意"), "谢采妘 柔情蜜意")
        self.assertEqual(format_caption_title("＃谢采妘 ＃柔情蜜意"), "谢采妘 柔情蜜意")

        # 5. Fallback on empty, None, or only '#'
        self.assertEqual(format_caption_title("", fallback="Fallback Title"), "Fallback Title")
        self.assertEqual(format_caption_title(None, fallback="Fallback Title"), "Fallback Title")
        self.assertEqual(format_caption_title("   \n  \t  ", fallback="Fallback Title"), "Fallback Title")
        self.assertEqual(format_caption_title("#", fallback="Facebook Photo 1493250019258573"), "Facebook Photo 1493250019258573")
        self.assertEqual(format_caption_title("###", fallback="Facebook Photo 1493250019258573"), "Facebook Photo 1493250019258573")
        self.assertEqual(format_caption_title("# # #", fallback="Facebook Photo 1493250019258573"), "Facebook Photo 1493250019258573")
        self.assertEqual(format_caption_title("＃＃＃", fallback="Facebook Photo 1493250019258573"), "Facebook Photo 1493250019258573")

    def test_11_reels_authentic_caption_extraction(self):
        """
        Test 11: Verify scan_reels extracts authentic caption from profile_reel_node.node.message
        and applies 35-char truncation with '...'.
        """
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        mock_reels_data = {
            "data": {
                "node": {
                    "aggregated_fb_shorts": {
                        "page_info": {"has_next_page": False, "end_cursor": None},
                        "edges": [
                            {
                                "cursor": "CUR_1",
                                "node": {
                                    "__typename": "TimelineAppCollectionItem",
                                    "id": "item_1",
                                },
                                "profile_reel_node": {
                                    "node": {
                                        "video": {"id": "1099945519309349"},
                                        "message": {
                                            "text": "一天一首新年歌 - 謝采妘『賀新年』\n\n#童年回憶 #過年歌 #賀歲歌 #chinesemusic #chinesenewyear"
                                        },
                                        "short_form_video_context": {
                                            "playback_video": {
                                                "thumbnailImage": {"uri": "https://fbcdn.net/thumb_live.jpg"}
                                            }
                                        },
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_reels_data
            mock_post.return_value = resp

            reels = client.scan_reels(
                reels_page_id="REELS_123",
                lsd="LSD_TEST",
                dtsg="DTSG_TEST",
                profile_url="https://www.facebook.com/HongYongMusic/reels/",
                max_count=None,
            )

        self.assertEqual(len(reels), 1)
        r = reels[0]
        self.assertEqual(r["id"], "1099945519309349")
        self.assertEqual(r["url"], "https://www.facebook.com/reel/1099945519309349")
        self.assertEqual(r["thumbnail"], "https://fbcdn.net/thumb_live.jpg")
        # Verify title is authentic post caption with '#' stripped (<50 Chinese words/chars remains intact)
        self.assertEqual(r["title"], "一天一首新年歌 - 謝采妘『賀新年』 童年回憶 過年歌 賀歲歌 chinesemusic chinesenewyear")

    def test_12_complete_enumeration_pagination(self):
        """
        Test 12: Verify scan_reels with max_count=None iterates through multiple pages
        until has_next_page is False.
        """
        client = FacebookCometClient(cookie_file=str(self.cookie_file), request_delay=0.0)

        page1 = {
            "data": {
                "node": {
                    "aggregated_fb_shorts": {
                        "page_info": {"has_next_page": True, "end_cursor": "PAGE2_CURSOR"},
                        "edges": [
                            {
                                "cursor": "PAGE2_CURSOR",
                                "node": {"id": "edge_1"},
                                "profile_reel_node": {
                                    "node": {
                                        "video": {"id": f"reel_{i}"},
                                        "message": {"text": f"Reel Caption {i}"},
                                    }
                                },
                            }
                            for i in range(1, 11)
                        ]
                    }
                }
            }
        }
        page2 = {
            "data": {
                "node": {
                    "aggregated_fb_shorts": {
                        "page_info": {"has_next_page": False, "end_cursor": None},
                        "edges": [
                            {
                                "cursor": None,
                                "node": {"id": "edge_2"},
                                "profile_reel_node": {
                                    "node": {
                                        "video": {"id": f"reel_{i}"},
                                        "message": {"text": f"Reel Caption {i}"},
                                    }
                                },
                            }
                            for i in range(11, 21)
                        ]
                    }
                }
            }
        }

        with patch.object(client, "_post_graphql") as mock_post:
            resp1 = MagicMock()
            resp1.status_code = 200
            resp1.json.return_value = page1

            resp2 = MagicMock()
            resp2.status_code = 200
            resp2.json.return_value = page2

            mock_post.side_effect = [resp1, resp2]

            reels = client.scan_reels(
                reels_page_id="REELS_PAGE",
                lsd="LSD_TEST",
                dtsg="DTSG_TEST",
                profile_url="https://www.facebook.com/HongYongMusic/reels/",
                max_count=None,
            )

        self.assertEqual(len(reels), 20)
        self.assertEqual(reels[0]["id"], "reel_1")
        self.assertEqual(reels[19]["id"], "reel_20")

    def test_13_photos_tab_skips_video_discovery_and_completes(self):
        """
        Test 13: Verify that scanning a dedicated Facebook Photos tab URL:
        1. Discovers and merges photos into inventory.
        2. Skips video and Reels discovery (preventing multi-minute timeouts).
        3. Returns ScanCompleteness.COMPLETE with photo count.
        """
        self.mock_gallerydl.extract_metadata.return_value = GalleryDlRecordList([
            {"id": "photo_gdl_1", "url": "https://fbcdn.net/p1.jpg", "category": "facebook"}
        ])

        mock_tokens = {
            "lsd": "MOCK_LSD",
            "dtsg": "MOCK_DTSG",
            "page_id": "PAGE_111",
            "photos_by_id": "PHOTOS_222",
            "reels_page_id": "REELS_333",
            "is_login_redirect": False,
        }
        mock_comet_photos = [
            {
                "id": "photo_comet_100",
                "direct_url": "https://fbcdn.net/p100.jpg",
                "post_url": "https://www.facebook.com/photo.php?fbid=photo_comet_100",
                "type": "photo",
                "title": "Photo Title 100",
            }
        ]

        with patch("core.platform.facebook_comet.FacebookCometClient.extract_page_tokens", return_value=mock_tokens), \
             patch("core.platform.facebook_comet.FacebookCometClient.scan_photos", return_value=mock_comet_photos), \
             patch.object(self.video_engine, "discover") as mock_vid_discover:

            result = self.scan_manager.scan_profile(
                url="https://www.facebook.com/HongYongMusic/photos",
                platform="facebook",
                custom_cookie_file=str(self.cookie_file),
            )

            # Video engine discover MUST NOT be called when scanning Photos tab
            mock_vid_discover.assert_not_called()

        self.assertEqual(result.extra_metadata["scan_status"], ScanCompleteness.COMPLETE)
        self.assertEqual(result.extra_metadata["photo_count"], 2)
        self.assertEqual(result.extra_metadata["video_count"], 0)
        self.assertIn("Photo enumeration completed successfully (2 photos)", result.extra_metadata["scan_completeness_info"])


if __name__ == "__main__":
    unittest.main()

