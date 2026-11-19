"""
test_rednote_title_enrichment.py
Unit tests verifying Mode A smart title enrichment for RedNote (XiaoHongShu 小红书).
Ensures pure emoji / minimal symbol titles are safely prepended with [YYYY-MM-DD]
to prevent file collisions and provide clarity, while normal text titles remain un-prefixed.
"""

import unittest
from unittest.mock import patch
from core.platform.rednote import (
    RedNoteAdapter,
    is_minimal_or_emoji_title,
    enrich_rednote_title,
    format_rednote_upload_date,
)
from core.models import VideoItem, VideoStatus, MediaType


class TestRedNoteTitleEnrichment(unittest.TestCase):

    def setUp(self):
        self.adapter = RedNoteAdapter()

    def test_format_rednote_upload_date(self):
        # Millisecond timestamp
        date_str, ts_sec = format_rednote_upload_date(1786591729000)
        self.assertIsNotNone(date_str)
        self.assertTrue(date_str.startswith("2026-"))
        self.assertEqual(ts_sec, 1786591729)

        # Seconds timestamp
        date_str_sec, ts_sec2 = format_rednote_upload_date(1786591729)
        self.assertEqual(date_str_sec, date_str)
        self.assertEqual(ts_sec2, 1786591729)

        # Invalid / missing
        self.assertEqual(format_rednote_upload_date(None), (None, None))
        self.assertEqual(format_rednote_upload_date("invalid"), (None, None))

    def test_is_minimal_or_emoji_title(self):
        # Normal text titles (Chinese, English, alphanumeric) -> False
        self.assertFalse(is_minimal_or_emoji_title("Memories🖤"))
        self.assertFalse(is_minimal_or_emoji_title("All white🪽🖤"))
        self.assertFalse(is_minimal_or_emoji_title("little demon🪽"))
        self.assertFalse(is_minimal_or_emoji_title("Outfits check🩰 舒适穿搭"))
        self.assertFalse(is_minimal_or_emoji_title("Shanghai*⛲️🐈‍"))
        self.assertFalse(is_minimal_or_emoji_title("穿搭日常"))
        self.assertFalse(is_minimal_or_emoji_title("OOTD"))

        # Pure emoji or minimal symbol titles (< 2 text chars) -> True
        self.assertTrue(is_minimal_or_emoji_title("🤍⛲️ "))
        self.assertTrue(is_minimal_or_emoji_title("🖤🐈‍ "))
        self.assertTrue(is_minimal_or_emoji_title("🪽.. "))
        self.assertTrue(is_minimal_or_emoji_title("🤍🩰 "))
        self.assertTrue(is_minimal_or_emoji_title("🤍🫖🍃 "))
        self.assertTrue(is_minimal_or_emoji_title("-"))
        self.assertTrue(is_minimal_or_emoji_title(".."))
        self.assertTrue(is_minimal_or_emoji_title(""))

    def test_enrich_rednote_title_universal_date_prefix(self):
        # 1. Normal text titles now also get [YYYY-MM-DD] prepended
        self.assertEqual(
            enrich_rednote_title("Outfits check🩰 舒适穿搭", upload_date="2026-07-25", author="imszy"),
            "[2026-07-25] Outfits check🩰 舒适穿搭",
        )
        self.assertEqual(
            enrich_rednote_title("Memories🖤", upload_date="2026-08-13", author="imszy"),
            "[2026-08-13] Memories🖤",
        )
        self.assertEqual(
            enrich_rednote_title("All white🪽🖤", upload_date="2026-07-29", author="imszy"),
            "[2026-07-29] All white🪽🖤",
        )

        # 2. Pure emoji titles get [YYYY-MM-DD] prepended
        self.assertEqual(
            enrich_rednote_title("🤍⛲️ ", upload_date="2026-08-07", author="imszy"),
            "[2026-08-07] 🤍⛲️",
        )
        self.assertEqual(
            enrich_rednote_title("🪽.. ", upload_date="2026-07-31", author="imszy"),
            "[2026-07-31] 🪽..",
        )
        self.assertEqual(
            enrich_rednote_title("🤍🩰 ", upload_date="2026-07-28", author="imszy"),
            "[2026-07-28] 🤍🩰",
        )

        # 3. Pure punctuation or empty title falls back safely with author and date
        self.assertEqual(
            enrich_rednote_title("-", upload_date="2026-07-15", author="imszy", note_id="1040g_abc"),
            "[2026-07-15] imszy Note 1040g_abc",
        )

        # 4. Avoid double-prefixing if title already starts with [YYYY-MM-DD]
        self.assertEqual(
            enrich_rednote_title("[2026-08-13] Memories🖤", upload_date="2026-08-13", author="imszy"),
            "[2026-08-13] Memories🖤",
        )

        # 5. Without upload_date (e.g. None), returns clean_t safely
        self.assertEqual(
            enrich_rednote_title("Outfits check🩰 舒适穿搭", upload_date=None, author="imszy"),
            "Outfits check🩰 舒适穿搭",
        )

    def test_profile_entries_enrichment(self):
        import json
        mock_state = {
            "user": {
                "userPageData": {
                    "basicInfo": {"nickname": "imszy"},
                    "notes": [
                        {
                            "id": "note_01",
                            "type": "normal",
                            "displayTitle": "🤍⛲️ ",
                            "time": 1786080753000,
                            "cover": {"urlDefault": "https://sns-img-qc.xhscdn.com/c1.jpg"},
                        },
                        {
                            "id": "note_02",
                            "type": "video",
                            "displayTitle": "Outfits check🩰 舒适穿搭",
                            "time": 1784958660000,
                            "cover": {"urlDefault": "https://sns-img-qc.xhscdn.com/c2.jpg"},
                        },
                    ],
                }
            }
        }
        mock_html = f"<script>window.__INITIAL_STATE__={json.dumps(mock_state)};</script>"

        with patch.object(self.adapter, "_fetch_html", return_value=mock_html):
            items = self.adapter._extract_profile_entries(
                user_id="5b9c90b9923cef000158b58e",
                profile_url="https://www.xiaohongshu.com/user/profile/5b9c90b9923cef000158b58e",
            )

        self.assertEqual(len(items), 2)
        # First item (pure emoji) should have date prepended
        self.assertTrue(items[0].title.startswith("[2026-"))
        self.assertIn("🤍⛲️", items[0].title)
        self.assertEqual(items[0].extra_metadata.get("raw_title"), "🤍⛲️")
        self.assertTrue(items[0].extra_metadata.get("upload_date").startswith("2026-"))

        # Second item (video, normal text) also gets date prepended
        self.assertTrue(items[1].title.startswith("[2026-"))
        self.assertIn("Outfits check🩰 舒适穿搭", items[1].title)
        self.assertEqual(items[1].extra_metadata.get("raw_title"), "Outfits check🩰 舒适穿搭")
        self.assertTrue(items[1].extra_metadata.get("upload_date").startswith("2026-"))


if __name__ == "__main__":
    unittest.main()
