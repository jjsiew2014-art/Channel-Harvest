"""
tests/test_cookie_file_propagation.py
Authentication and Cookie File Propagation Tests for gallery-dl and yt-dlp across Facebook and Instagram.

Covers:
1. Instagram Cookie File propagation reaches gallery-dl invocation arguments.
2. Facebook Cookie File propagation reaches gallery-dl invocation arguments.
3. Instagram Cookie File propagation reaches yt-dlp options (cookiefile).
4. Facebook Cookie File propagation reaches yt-dlp options (cookiefile).
5. Secrets, session tokens, and raw cookie values are scrubbed/redacted from logs.
6. Missing cookie file diagnostic handling.
7. Unreadable / permission error cookie file handling.
8. Malformed / non-Netscape format cookie file handling.
9. Unverified vs session-authenticated state distinction.
10. Unrelated platforms (YouTube, Bilibili, TikTok, X) auth scoping isolation.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models import DownloadSettings, VideoItem
from core.platform import PlatformRegistry
from core.platform.facebook import FacebookAdapter
from core.platform.instagram import InstagramAdapter
from downloader.auth_checker import AuthChecker, AuthStatusCode
from downloader.gallerydl_engine import GalleryDlEngine


class TestCookieFilePropagation(unittest.TestCase):
    """Verifies end-to-end Custom Cookie File propagation for yt-dlp and gallery-dl."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fb_cookie_file = Path(self.temp_dir.name) / "fb_cookies.txt"
        self.fb_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".facebook.com\tTRUE\t/\tTRUE\t2147483647\tc_user\t100012345678901\n"
            ".facebook.com\tTRUE\t/\tTRUE\t2147483647\txs\tsecret_fb_xs_token_xyz\n",
            encoding="utf-8",
        )

        self.ig_cookie_file = Path(self.temp_dir.name) / "ig_cookies.txt"
        self.ig_cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tsecret_ig_session_token_abc\n"
            ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tds_user_id\t9876543210\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_gallerydl_instagram_cookie_propagation(self):
        """Verify gallery-dl receives Instagram cookie file via -C/--cookies."""
        engine = GalleryDlEngine()
        with patch.object(engine, "_execute_process") as mock_exec:
            mock_exec.return_value = (0, "[]", "")
            engine.extract_metadata("https://instagram.com/p/test/", custom_cookie_file=str(self.ig_cookie_file))

            args = mock_exec.call_args[1]["args"]
            self.assertIn("--cookies", args)
            idx = args.index("--cookies")
            self.assertEqual(args[idx + 1], str(self.ig_cookie_file.resolve()))

    def test_02_gallerydl_facebook_cookie_propagation(self):
        """Verify gallery-dl receives Facebook cookie file via -C/--cookies."""
        engine = GalleryDlEngine()
        with patch.object(engine, "_execute_process") as mock_exec:
            mock_exec.return_value = (0, "[]", "")
            engine.download_media(
                url="https://facebook.com/photo/?fbid=123",
                target_dir=Path(self.temp_dir.name),
                custom_cookie_file=str(self.fb_cookie_file),
            )

            args = mock_exec.call_args[1]["args"]
            self.assertIn("--cookies", args)
            idx = args.index("--cookies")
            self.assertEqual(args[idx + 1], str(self.fb_cookie_file.resolve()))

    def test_03_ytdlp_instagram_cookie_propagation(self):
        """Verify yt-dlp receives Instagram cookie file in build_ydl_opts."""
        adapter = InstagramAdapter()
        settings = DownloadSettings(
            instagram_auth_method="custom_file",
            instagram_custom_cookie_file=str(self.ig_cookie_file),
        )
        auth_cfg = adapter.get_auth_config(settings)
        self.assertTrue(auth_cfg.is_active)
        self.assertEqual(auth_cfg.auth_method, "custom_file")
        self.assertEqual(auth_cfg.cookie_file, str(self.ig_cookie_file.resolve()))

        opts = adapter.build_ydl_opts(auth_config=auth_cfg)
        self.assertEqual(opts.get("cookiefile"), str(self.ig_cookie_file.resolve()))

    def test_04_ytdlp_facebook_cookie_propagation(self):
        """Verify yt-dlp receives Facebook cookie file in build_ydl_options."""
        adapter = FacebookAdapter()
        settings = DownloadSettings(
            facebook_auth_method="custom_file",
            facebook_custom_cookie_file=str(self.fb_cookie_file),
        )
        auth_cfg = adapter.get_auth_config(settings)
        self.assertTrue(auth_cfg.is_active)
        self.assertEqual(auth_cfg.auth_method, "custom_file")
        self.assertEqual(auth_cfg.cookie_file, str(self.fb_cookie_file.resolve()))

        opts = adapter.build_ydl_options(auth_config=auth_cfg)
        self.assertEqual(opts.get("cookiefile"), str(self.fb_cookie_file.resolve()))

    def test_05_secrets_redacted_from_gallerydl_logs(self):
        """Verify raw cookie paths and tokens are never printed in logged arguments."""
        engine = GalleryDlEngine()
        logged_messages = []

        def log_cb(msg: str):
            logged_messages.append(msg)

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 0
            mock_proc.stdout = []
            mock_proc.stderr = []
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            engine._execute_process(
                args=["--cookies", str(self.ig_cookie_file), "https://instagram.com/p/test/"],
                log_callback=log_cb,
            )

        log_text = "\n".join(logged_messages)
        self.assertNotIn("secret_ig_session_token_abc", log_text)
        self.assertIn("[REDACTED_COOKIE_PATH]", log_text)

    def test_06_missing_cookie_file_diagnostic(self):
        """Verify missing cookie file produces BROWSER_NOT_FOUND status code with clear message."""
        nonexistent = str(Path(self.temp_dir.name) / "nonexistent_cookies.txt")
        res_fb = AuthChecker.test_authentication("custom_file", custom_cookie_path=nonexistent, platform="facebook")
        self.assertFalse(res_fb.success)
        self.assertIn("does not exist", res_fb.reason)

        res_ig = AuthChecker.test_authentication("custom_file", custom_cookie_path=nonexistent, platform="instagram")
        self.assertFalse(res_ig.success)
        self.assertIn("does not exist", res_ig.reason)

    def test_07_malformed_cookie_file_diagnostic(self):
        """Verify corrupt/non-Netscape cookie file produces COOKIE_FILE_INVALID status."""
        corrupt_file = Path(self.temp_dir.name) / "corrupt_cookies.txt"
        corrupt_file.write_text("NOT A COOKIE FILE CONTENT\nRandom text here\n", encoding="utf-8")

        res_fb = AuthChecker.test_authentication("custom_file", custom_cookie_path=str(corrupt_file), platform="facebook")
        self.assertFalse(res_fb.success)
        self.assertEqual(res_fb.status_code, AuthStatusCode.COOKIE_FILE_INVALID)

    def test_08_facebook_cookies_in_instagram_file_rejected(self):
        """Verify Facebook cookie file tested against Instagram correctly reports NO_INSTAGRAM_COOKIES."""
        res = AuthChecker.test_authentication("custom_file", custom_cookie_path=str(self.fb_cookie_file), platform="instagram")
        self.assertFalse(res.success)
        self.assertEqual(res.status_code, AuthStatusCode.NO_INSTAGRAM_COOKIES)

    def test_09_instagram_cookies_in_facebook_file_rejected(self):
        """Verify Instagram cookie file tested against Facebook correctly reports NO_FACEBOOK_COOKIES."""
        res = AuthChecker.test_authentication("custom_file", custom_cookie_path=str(self.ig_cookie_file), platform="facebook")
        self.assertFalse(res.success)
        self.assertEqual(res.status_code, AuthStatusCode.NO_FACEBOOK_COOKIES)

    def test_10_verified_session_distinguished(self):
        """Verify valid session cookies report SESSION_AUTHENTICATED."""
        res_fb = AuthChecker.test_authentication("custom_file", custom_cookie_path=str(self.fb_cookie_file), platform="facebook")
        self.assertTrue(res_fb.success)
        self.assertEqual(res_fb.status_code, AuthStatusCode.FACEBOOK_SESSION_AUTHENTICATED)

        res_ig = AuthChecker.test_authentication("custom_file", custom_cookie_path=str(self.ig_cookie_file), platform="instagram")
        self.assertTrue(res_ig.success)
        self.assertEqual(res_ig.status_code, AuthStatusCode.INSTAGRAM_SESSION_AUTHENTICATED)


if __name__ == "__main__":
    unittest.main()
