"""Synthetic parser fixtures; these are never used as live product evidence."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trendfinder.public import exact_count, product_match, search_videos, parse_watch, search_filter_url


class PublicParserTests(unittest.TestCase):
    def test_rounded_counts_are_unknown(self):
        self.assertIsNone(exact_count("1.2K"))
        self.assertIsNone(exact_count(True))
        self.assertIsNone(exact_count("-5"))
        self.assertEqual(exact_count("12,345"), 12345)
        self.assertEqual(exact_count("0"), 0)

    def test_product_matching_has_word_boundaries(self):
        c = {"name": "cat", "aliases": ["pet hair remover"]}
        self.assertFalse(product_match("vacation gadgets", c))
        self.assertTrue(product_match("Testing a pet-hair remover", c))

    def test_search_dedup_and_short_type(self):
        data = {"a": {"shortsLockupViewModel": {"onTap": {"innertubeCommand": {"reelWatchEndpoint": {"videoId": "abcdefghijk"}}}}},
                "b": {"videoRenderer": {"videoId": "abcdefghijk"}}}
        found = search_videos("var ytInitialData = " + json.dumps(data) + ";")
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["is_short"])

    def test_filter_follows_observed_page_endpoint(self):
        data = {"searchFilterRenderer": {"label": {"simpleText": "This month"}, "navigationEndpoint": {"commandMetadata": {"webCommandMetadata": {"url": "/results?search_query=test&sp=observed"}}}}}
        page = "var ytInitialData = " + json.dumps(data) + ";"
        self.assertEqual(search_filter_url(page, "This month"), "https://www.youtube.com/results?search_query=test&sp=observed")
        self.assertIsNone(search_filter_url(page, "Shorts"))

    def test_watch_does_not_infer_country_from_availability(self):
        player = {"videoDetails": {"videoId": "abcdefghijk", "title": "Pet hair remover", "viewCount": "15000", "channelId": "channel"},
                  "microformat": {"playerMicroformatRenderer": {"likeCount": "900", "publishDate": "2026-09-20T10:00:00Z", "availableCountries": ["US", "GB", "IN"], "canonicalUrl": "https://www.youtube.com/shorts/abcdefghijk"}}}
        page = "var ytInitialPlayerResponse = " + json.dumps(player) + ";"
        video = parse_watch(page, {"id": "pet", "name": "pet hair remover"}, {"id": "abcdefghijk", "is_short": True}, "2026-09-21T00:00:00Z")
        self.assertEqual(video["views"], 15000)
        self.assertEqual(video["likes"], 900)
        self.assertIsNone(video["comments"])
        self.assertIsNone(video["country"])
        self.assertTrue(video["product_match"])
        with self.assertRaises(ValueError):
            parse_watch(page, {"id": "pet", "name": "pet hair remover"}, {"id": "different"}, "2026-09-21T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
