import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from trendfinder.engine import evaluate


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def video(i, product="p1", **overrides):
    v = {
        "product_id": product, "platform": "tiktok" if i % 2 else "youtube", "id": f"v{i}",
        "url": f"https://www.tiktok.com/@creator{i}/video/v{i}" if i % 2 else f"https://www.youtube.com/shorts/v{i}",
        "creator_id": f"creator{i % 20}", "published_at": "2026-09-10T12:00:00Z", "observed_at": "2026-09-20T12:00:00Z",
        "views": 10_000, "likes": 400, "comments": 0, "country": ["IN", "US", "GB", "CA", "AU"][i % 5], "country_source": "creator profile",
        "is_short": True, "product_match": True,
    }
    v.update(overrides)
    return v


def candidate(**overrides):
    c = {
        "id": "p1", "name": "Useful thing", "shipping": {"status": "verified", "evidence_url": "https://shop.example/product", "weight_kg": 1.0, "longest_side_cm": 40.0, "fragile": False, "restricted": False},
        "hero": {"problem": "p", "demonstration": "d", "differentiation": "x"},
        "seller_checks": [{"channel": ch, "status": "complete", "query": "useful thing", "checked_at": "2026-09-20T12:00:00Z", "evidence_url": "https://shop.example/search"} for ch in ("amazon_in", "flipkart", "instagram", "shopify")],
        "sellers": [{"seller_id": "one", "name": "One", "channel": "shopify", "url": "https://shop.example/product", "active": True, "india_delivery": True, "checked_at": "2026-09-20T12:00:00Z"}],
    }
    c.update(overrides)
    return c


class EngineTests(unittest.TestCase):
    def test_exact_boundaries_qualify_both_lists_and_keep_all_ids(self):
        result = evaluate({"candidates": [candidate()], "videos": [video(i) for i in range(50)], "collection": {"failed": []}}, NOW)
        self.assertEqual(result["summary"], {"candidate_count": 1, "international_count": 1, "india_count": 1})
        self.assertEqual(len(result["international"][0]["qualifying_video_ids"]), 50)

    def test_duplicate_ids_urls_and_tracking_aliases_cannot_inflate(self):
        videos = [video(i) for i in range(50)]
        videos[1]["id"] = videos[0]["id"]
        videos[1]["platform"] = videos[0]["platform"]
        videos[1]["url"] = videos[0]["url"] + "?utm_source=alias"
        result = evaluate({"candidates": [candidate()], "videos": videos}, NOW)
        item = result["candidates"][0]
        self.assertFalse(item["international"])
        self.assertTrue(any("duplicate" in r for e in item["video_evaluations"] for r in e["reasons"]))

    def test_freshness_future_and_country_proof_are_audited(self):
        videos = [video(i) for i in range(50)]
        videos[0].update(observed_at="2026-09-01T00:00:00Z")
        videos[1].update(published_at="2026-09-22T00:00:00Z")
        videos[2].update(country=None, country_source=None)
        result = evaluate({"candidates": [candidate()], "videos": videos}, NOW)
        evaluations = result["candidates"][0]["video_evaluations"]
        reasons = [set(e["reasons"]) for e in evaluations]
        self.assertTrue(any("observation is stale" in r for r in reasons))
        self.assertTrue(any("published_at is in the future" in r for r in reasons))
        self.assertTrue(any(e["geography_reason"] == "country unknown" for e in evaluations))

    def test_shipping_rejection_is_explicit_and_unknown_sellers_block_india(self):
        bad_shipping = candidate(shipping={"status": "rejected", "evidence_url": "https://shop.example/product", "weight_kg": 1, "longest_side_cm": 40, "fragile": False, "restricted": False})
        bad_shipping["sellers"][0]["india_delivery"] = None
        result = evaluate({"candidates": [bad_shipping], "videos": [video(i) for i in range(50)]}, NOW)
        item = result["candidates"][0]
        self.assertFalse(item["india"])
        self.assertIn("shipping rejected", item["reasons"])
        self.assertIn("seller coverage pending: activity, delivery, URL, name, channel, or freshness unknown", item["reasons"])

    def test_blocked_or_stale_channel_coverage_blocks_india_but_preserves_collection(self):
        checks = candidate()["seller_checks"]
        checks[0]["status"] = "blocked"
        checks[1]["checked_at"] = "2026-09-01T00:00:00Z"
        result = evaluate({"candidates": [candidate(seller_checks=checks)], "videos": [video(i) for i in range(50)], "collection": {"failed": ["flipkart"]}}, NOW)
        item = result["candidates"][0]
        self.assertTrue(item["international"])
        self.assertFalse(item["india"])
        self.assertIn("four fresh channel checks not complete", item["reasons"])
        self.assertEqual(result["collection"]["failed"], ["flipkart"])

    def test_shipping_is_required_for_international_and_unknown_country_still_counts_video(self):
        c = candidate(shipping={"status": "rejected", "evidence_url": "https://shop.example/product", "weight_kg": 1, "longest_side_cm": 40, "fragile": False, "restricted": False})
        videos = [video(i) for i in range(50)]
        videos[0].update(country="IN", country_source=None)
        result = evaluate({"candidates": [c], "videos": videos}, NOW)
        item = result["candidates"][0]
        self.assertFalse(item["international"])
        self.assertEqual(item["status"], "rejected")
        self.assertEqual(item["stats"]["qualifying_video_count"], 50)
        self.assertEqual(item["stats"]["country_counts"]["IN"], 9)

    def test_creator_cap_is_per_platform_namespace_and_audited(self):
        videos = [video(i) for i in range(50)]
        for i in range(12):
            videos[i]["creator_id"] = "same-creator"
        result = evaluate({"candidates": [candidate()], "videos": videos}, NOW)
        evaluations = result["candidates"][0]["video_evaluations"]
        self.assertEqual(sum(e["counted_for_diversity"] for e in evaluations if e["creator_id"] == "same-creator"), 10)
        self.assertTrue(any("creator contribution capped at 5" in e["reasons"] for e in evaluations))

    def test_estimate_requires_complete_checks_and_duplicate_prefers_fresh_observation(self):
        videos = [video(i) for i in range(50)]
        old = dict(videos[0])
        old["observed_at"] = "2026-09-14T12:00:00Z"
        videos.append(old)
        incomplete = candidate(seller_checks=[])
        result = evaluate({"candidates": [incomplete], "videos": videos}, NOW)
        item = result["candidates"][0]
        self.assertIsNone(item["stats"]["estimated_india_seller_count"])
        self.assertEqual(item["stats"]["observed_confirmed_seller_count"], 1)
        self.assertEqual(sum(e["qualifies"] for e in item["video_evaluations"]), 50)

    def test_non_boolean_seller_flags_are_unknown_and_credentials_invalid(self):
        c = candidate()
        c["sellers"][0]["active"] = 1
        c["sellers"][0]["url"] = "https://user:pass@shop.example/product"
        result = evaluate({"candidates": [c], "videos": [video(i) for i in range(50)]}, NOW)
        item = result["candidates"][0]
        self.assertEqual(item["stats"]["seller_coverage"], "unknown")
        self.assertIsNone(item["stats"]["estimated_india_seller_count"])

    def test_exact_video_and_metric_boundaries(self):
        videos = [video(i) for i in range(49)]
        result = evaluate({"candidates": [candidate()], "videos": videos}, NOW)
        self.assertFalse(result["candidates"][0]["international"])
        low = video(100, id="v100", likes=399)
        result = evaluate({"candidates": [candidate()], "videos": [low]}, NOW)
        self.assertIn("engagement rate below threshold", result["candidates"][0]["video_evaluations"][0]["reasons"])
        low["likes"] = 400
        low["views"] = 9_999
        result = evaluate({"candidates": [candidate()], "videos": [low]}, NOW)
        self.assertIn("views below threshold or invalid", result["candidates"][0]["video_evaluations"][0]["reasons"])

    def test_shipping_and_seller_limits_and_no_output_list_cap(self):
        heavy = candidate(shipping={"status": "verified", "evidence_url": "https://shop.example/product", "weight_kg": 1.01, "longest_side_cm": 40, "fragile": False, "restricted": False})
        sellers = [dict(candidate()["sellers"][0], seller_id=f"seller-{i}") for i in range(5)]
        five_sellers = candidate(sellers=sellers)
        videos = [video(i) for i in range(50)]
        result = evaluate({"candidates": [heavy, five_sellers], "videos": videos}, NOW)
        self.assertEqual(len(result["international"]), 1)
        self.assertEqual(result["international"][0]["id"], "p1")
        self.assertIn("shipping", result["candidates"][0]["international_reasons"][0])
        self.assertIn("five or more deduplicated active India sellers", result["candidates"][1]["india_reasons"])
        two = evaluate({"candidates": [candidate(), candidate(id="p2", name="Second")], "videos": videos + [dict(video(i), product_id="p2") for i in range(50)]}, NOW)
        self.assertEqual(len(two["international"]), 2)


if __name__ == "__main__":
    unittest.main()
