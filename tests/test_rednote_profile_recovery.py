"""
test_rednote_profile_recovery.py
Unit tests verifying profile URL normalization, note-scoped token sanitization,
and automatic fallback recovery for RedNote (XiaoHongShu 小红书) creator profile scanning.
"""

import unittest
from unittest.mock import patch, MagicMock
from core.platform.rednote import RedNoteAdapter
from core.models import MediaType


class TestRedNoteProfileRecovery(unittest.TestCase):

    def setUp(self):
        self.adapter = RedNoteAdapter()

    def test_normalize_url_strips_note_scoped_referral_params(self):
        """
        Verify that when a user copies a profile link from a PC note
        (containing xsec_source=pc_note and note-scoped xsec_token),
        normalize_url strips them to prevent Xiaohongshu SSR from returning 0 notes.
        """
        raw_url = (
            "https://www.rednote.com/user/profile/5b9c90b9923cef000158b58e"
            "?xsec_token=ABvLuFEN2d6xcX1X_uyATkmn7TDwRd1J8vZmLf3Bzotr0=&xsec_source=pc_note"
        )
        normalized = self.adapter.normalize_url(raw_url)
        self.assertEqual(normalized, "https://www.rednote.com/user/profile/5b9c90b9923cef000158b58e")

        raw_xhs = (
            "https://www.xiaohongshu.com/user/profile/5c9ca4bf000000001000e11e"
            "?xsec_source=pc_feed&xsec_token=AB123456"
        )
        normalized_xhs = self.adapter.normalize_url(raw_xhs)
        self.assertEqual(normalized_xhs, "https://www.xiaohongshu.com/user/profile/5c9ca4bf000000001000e11e")

    def test_collect_notes_ignores_empty_placeholder_sublists(self):
        """
        Verify _collect_notes_from_state does not stop on [[], [], [], [], []]
        and inspects alternative keys in userPageData.
        """
        state_data = {
            "user": {
                "notes": [[], [], [], [], []],  # Empty tab placeholders
                "userPageData": {
                    "notes": [
                        {
                            "id": "note_alt_01",
                            "type": "normal",
                            "displayTitle": "Alternative Note Title",
                            "cover": {"urlDefault": "https://sns-img-qc.xhscdn.com/alt01.jpg"},
                        }
                    ]
                },
            }
        }
        collected = self.adapter._collect_notes_from_state(state_data)
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0]["id"], "note_alt_01")

    def test_profile_fallback_recovery_when_initial_request_empty(self):
        """
        Verify that if initial request yields 0 notes (e.g. due to expired token),
        _extract_profile_entries automatically falls back to clean URLs and recovers items.
        """
        import json
        empty_state = {"user": {"notes": [[], [], [], [], []]}}
        success_state = {
            "user": {
                "notes": [
                    [
                        {
                            "id": "rec_01",
                            "type": "normal",
                            "displayTitle": "Recovered Note",
                            "cover": {"urlDefault": "https://sns-img-qc.xhscdn.com/c1.jpg"},
                        }
                    ]
                ]
            }
        }
        empty_html = f"<script>window.__INITIAL_STATE__={json.dumps(empty_state)};</script>"
        success_html = f"<script>window.__INITIAL_STATE__={json.dumps(success_state)};</script>"

        def mock_fetch(url, **kwargs):
            if "INVALID" in url or "xsec_token" in url:
                return empty_html
            return success_html

        with patch.object(self.adapter, "_fetch_html", side_effect=mock_fetch):
            items = self.adapter._extract_profile_entries(
                user_id="user_test_99",
                profile_url="https://www.xiaohongshu.com/user/profile/user_test_99?xsec_token=INVALID",
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].video_id, "rec_01")
        self.assertEqual(items[0].title, "Recovered Note")


if __name__ == "__main__":
    unittest.main()
