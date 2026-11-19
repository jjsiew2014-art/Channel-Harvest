import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import shutil

from core.models import VideoItem, VideoStatus, DownloadSettings, DownloadMode, MediaType
from core.error_classifier import ErrorCategory
from core.platform.rednote import RedNoteAdapter
from downloader.download_manager import DownloadManager
from downloader.ytdlp_engine import DownloaderError


class TestRedNoteBatchFix(unittest.TestCase):
    def setUp(self):
        self.adapter = RedNoteAdapter()
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolve_xhscdn_url_variations(self):
        """Verifies resolve_xhscdn_url resolves all subpath prefixes without truncating to file_id."""
        # 1. Rednotecdn signed token with spectrum/
        u1 = "http://sns-web-i10.rednotecdn.com/202611061601/ba9b7714dc0f926ebef4d39b1879d587/spectrum/1040g0k03272ikr99ma005n4skivk1o8uvc4oehg!nc_n_webp_mw_1"
        self.assertEqual(
            self.adapter.resolve_xhscdn_url(u1),
            "https://sns-img-qc.xhscdn.com/spectrum/1040g0k03272ikr99ma005n4skivk1o8uvc4oehg"
        )

        # 2. Rednotecdn signed token with notes_pre_post/
        u2 = "http://sns-web-i10.rednotecdn.com/202611061601/5591e404abcd81cfb85174f24d6dbc28/notes_pre_post/1040g3k0326tg1puc56005n4skivk1o8u6755g4o!nc_n_webp_mw_1"
        self.assertEqual(
            self.adapter.resolve_xhscdn_url(u2),
            "https://sns-img-qc.xhscdn.com/notes_pre_post/1040g3k0326tg1puc56005n4skivk1o8u6755g4o"
        )

        # 3. Standard rednotecdn signed token without subfolder
        u3 = "http://sns-web-i10.rednotecdn.com/202611061601/023bd7a338967d6f14fb089abb8c2174/1040g2sg32754emf978q05n4skivk1o8ugbgtodg!nc_n_webp_mw_1"
        self.assertEqual(
            self.adapter.resolve_xhscdn_url(u3),
            "https://sns-img-qc.xhscdn.com/1040g2sg32754emf978q05n4skivk1o8ugbgtodg"
        )

        # 4. Explicit fileId with spectrum in raw URL
        self.assertEqual(
            self.adapter.resolve_xhscdn_url("http://example.com/spectrum/some_hash!preview", "fid_12345"),
            "https://sns-img-qc.xhscdn.com/spectrum/fid_12345"
        )

        # 5. Domestic xhscdn URL keeps domain and cleans watermark suffix
        u5 = "https://sns-webpic-qc.xhscdn.com/hash/abc12345!nd_dft_wlteh_webp_3"
        self.assertEqual(
            self.adapter.resolve_xhscdn_url(u5),
            "https://sns-webpic-qc.xhscdn.com/hash/abc12345"
        )

    def test_extract_profile_entries_subpaths(self):
        """Verifies profile extraction accurately attaches spectrum and notes_pre_post CDN paths."""
        mock_html = """
        <!DOCTYPE html><html><body>
        <script>window.__INITIAL_STATE__={"user":{"userPageData":{"basicInfo":{"nickname":"DIOR迪奥"},"notes":[[
            {"noteCard":{"type":"normal","title":"Item Spectrum","cover":{"urlDefault":"http://sns-web-i10.rednotecdn.com/202611061600/token1/spectrum/1040g_spec01!mw_1"}}},
            {"noteCard":{"type":"normal","title":"Item PrePost","cover":{"urlDefault":"http://sns-web-i10.rednotecdn.com/202611061600/token2/notes_pre_post/1040g_pre02!mw_1"}}},
            {"noteCard":{"type":"video","title":"Item Video","cover":{"urlDefault":"http://sns-web-i10.rednotecdn.com/202611061600/token3/1040g_vid03!mw_1"}}}
        ]]}}};</script>
        </body></html>
        """
        with patch.object(self.adapter, "_fetch_html", return_value=mock_html):
            items = self.adapter.extract_entries("https://www.rednote.com/user/profile/5c9ca4bf000000001000e11e")
            self.assertEqual(len(items), 3)

            # Item 0: Spectrum photo
            self.assertEqual(items[0].media_type, MediaType.PHOTO)
            self.assertEqual(items[0].cover_art_url, "https://sns-img-qc.xhscdn.com/spectrum/1040g_spec01")
            self.assertEqual(items[0].extra_metadata["photo_urls"], ["https://sns-img-qc.xhscdn.com/spectrum/1040g_spec01"])

            # Item 1: PrePost photo
            self.assertEqual(items[1].media_type, MediaType.PHOTO)
            self.assertEqual(items[1].cover_art_url, "https://sns-img-qc.xhscdn.com/notes_pre_post/1040g_pre02")
            self.assertEqual(items[1].extra_metadata["photo_urls"], ["https://sns-img-qc.xhscdn.com/notes_pre_post/1040g_pre02"])

            # Item 2: Video note
            self.assertEqual(items[2].media_type, MediaType.VIDEO)
            self.assertEqual(items[2].cover_art_url, "https://sns-img-qc.xhscdn.com/1040g_vid03")

    def test_guest_profile_video_gating_in_download_manager(self):
        """Verifies guest-mode profile video note skips with LOGIN_REQUIRED without UnboundLocalError."""
        settings = DownloadSettings()
        settings.download_dir = str(self.temp_dir)
        settings.mode = DownloadMode.VIDEO_AND_IMAGE
        settings.rednote_auth_method = "none"
        settings.rednote_browser_cookies = "none"
        settings.rednote_custom_cookie_file = ""

        video = VideoItem(
            index=1,
            video_id="1040g00832755l92p70205n4skivk1o8uoo0n99g",
            title="Dior Christmas Guest Video",
            duration="01:30",
            duration_seconds=90,
            status=VideoStatus.READY,
            subtitle_status="—",
            url="https://www.rednote.com/user/profile/5c9ca4bf000000001000e11e#1040g00832755l92p70205n4skivk1o8uoo0n99g",
            channel_title="DIOR迪奥",
            platform="rednote",
            media_type=MediaType.VIDEO,
            extra_metadata={
                "is_photo": False,
                "origin_video_url": None,
            }
        )

        mock_engine = MagicMock()
        dm = DownloadManager(
            videos=[video],
            settings=settings,
        )
        dm.engine = mock_engine

        logs = []
        dm.log_message.connect(logs.append)
        status_updates = []
        dm.video_status_changed.connect(lambda vid, st, tip: status_updates.append((st, tip)))

        dm.run()

        # Must skip cleanly due to login requirement
        self.assertEqual(video.status, VideoStatus.SKIPPED)
        self.assertEqual(video.extra_metadata.get("inaccessibility"), ErrorCategory.LOGIN_REQUIRED)
        self.assertTrue(any("LOGIN REQUIRED" in tip.upper() for _, tip in status_updates))
        self.assertTrue(any("AUTH NOTICE" in log for log in logs))
        mock_engine.download_single_video.assert_not_called()

    def test_photo_download_fallback_domain(self):
        """Verifies that if sns-img-qc returns 404, download_manager falls back to sns-img-hw seamlessly."""
        settings = DownloadSettings()
        settings.mode = DownloadMode.IMAGE_ONLY
        settings.download_folder = str(self.temp_dir)

        video = VideoItem(
            index=1,
            video_id="photo_item_fallback",
            title="Dior Photo Item",
            duration="Photo",
            duration_seconds=0,
            status=VideoStatus.READY,
            subtitle_status="—",
            url="https://www.rednote.com/user/profile/5c9ca4bf000000001000e11e#photo_item_fallback",
            channel_title="DIOR迪奥",
            platform="rednote",
            media_type=MediaType.PHOTO,
            extra_metadata={
                "is_photo": True,
                "photo_urls": ["https://sns-img-qc.xhscdn.com/spectrum/1040g_spec01"],
            }
        )

        dm = DownloadManager(
            videos=[video],
            settings=settings,
        )

        import urllib.error
        def mock_open(req, *args, **kwargs):
            url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
            if "sns-img-qc.xhscdn.com" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            elif "sns-img-hw.xhscdn.com" in url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
                mock_resp.__enter__.return_value = mock_resp
                return mock_resp
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)

        with patch("urllib.request.OpenerDirector.open", side_effect=mock_open):
            dm.run()

        self.assertEqual(video.status, VideoStatus.COMPLETED)
        saved_files = list(self.temp_dir.glob("**/*.jpg"))
        self.assertTrue(len(saved_files) >= 1)


if __name__ == "__main__":
    unittest.main()
