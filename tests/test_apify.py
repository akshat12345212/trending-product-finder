import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from trendfinder import apify


class FakeApi:
    def __init__(self, pages=None, status="SUCCEEDED"):
        self.calls = []
        self.pages = pages or [[{"id": "v1", "webVideoUrl": "https://www.tiktok.com/@a/video/v1", "text": "blue widget", "createTime": 1720000000, "playCount": 4, "diggCount": 1, "commentCount": 2, "locationCreated": "US", "authorMeta": {"id": "a"}, "videoMeta": {"duration": 20}}]]
        self.status = status

    def __call__(self, method, url, token, body=None):
        self.calls.append((method, url, body, token))
        if "/runs?" in url and method == "POST":
            return {"data": {"id": "run-1"}}
        if "actor-runs/run-1" in url:
            return {"data": {"id": "run-1", "status": self.status, "defaultDatasetId": "ds-1"}}
        if "datasets/ds-1/items" in url:
            offset = int(url.split("offset=")[1].split("&")[0])
            index = offset // apify.PAGE_SIZE
            return {"data": self.pages[index] if index < len(self.pages) else []}
        raise AssertionError(url)


class ApifyTests(unittest.TestCase):
    candidate = {"id": "p1", "name": "Blue Widget", "aliases": ["widget blue"]}

    def test_missing_credentials_is_blocked_without_videos(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            out = apify.collect_apify([self.candidate], Path(d))
        self.assertEqual(out["videos"], [])
        self.assertEqual(out["events"][0]["status"], "blocked")

    def test_tiktok_normalization_and_raw_provenance(self):
        fake = FakeApi()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake), patch.object(apify, "_SLEEP", lambda _: None):
            out = apify.collect_apify([self.candidate], Path(d), max_charge_usd=2)
            video = next(x for x in out["videos"] if x["platform"] == "tiktok")
            self.assertTrue(video["product_match"])
            self.assertEqual(video["country"], "US")
            self.assertEqual(video["country_source"], "TikTok locationCreated via Apify")
            self.assertTrue(Path(video["raw_file"]).exists())
            self.assertEqual(json.loads(Path(video["raw_file"]).read_text())["run_id"], "run-1")
            self.assertNotIn("secret", Path(video["raw_file"]).read_text())
        self.assertTrue(any("maxTotalChargeUsd" in call[1] for call in fake.calls if call[0] == "POST"))

    def test_youtube_short_and_unknown_country(self):
        fake = FakeApi(pages=[[{"id": "y1", "url": "https://youtube.com/shorts/y1", "title": "Blue Widget", "date": "2026-09-01T00:00:00Z", "viewCount": 9, "channelId": "c1", "type": "shorts"}]])
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake), patch.object(apify, "_SLEEP", lambda _: None):
            out = apify.collect_apify([self.candidate], Path(d))
        yt = next(x for x in out["videos"] if x["platform"] == "youtube")
        self.assertTrue(yt["is_short"])
        self.assertIsNone(yt["country"])
        self.assertIsNone(yt["likes"])

    def test_pagination_fetches_all_pages(self):
        pages = [[{"id": "v1", "webVideoUrl": "https://www.tiktok.com/@a/video/v1", "text": "Blue Widget", "createTime": 1720000000, "authorMeta": {"id": "a"}, "videoMeta": {"duration": 3}}] * apify.PAGE_SIZE, [{"id": "v2", "webVideoUrl": "https://www.tiktok.com/@a/video/v2", "text": "Blue Widget", "createTime": 1720000000, "authorMeta": {"id": "b"}, "videoMeta": {"duration": 3}}]]
        fake = FakeApi(pages=pages)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake), patch.object(apify, "_SLEEP", lambda _: None):
            out = apify.collect_apify([self.candidate], Path(d), per_query=1)
        self.assertEqual(len([x for x in out["videos"] if x["platform"] == "tiktok"]), apify.PAGE_SIZE + 1)

    def test_failed_run_is_event_only_and_resume_state_prevents_start(self):
        fake = FakeApi(status="FAILED")
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake):
            raw = Path(d)
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "apify_runs.json").write_text(json.dumps({"p1:tiktok": {"run_id": "run-1", "observed_at": "2026-09-21T00:00:00Z"}, "p1:youtube": {"run_id": "run-1", "observed_at": "2026-09-21T00:00:00Z"}}))
            out = apify.collect_apify([self.candidate], Path(d))
        self.assertEqual(out["videos"], [])
        self.assertTrue(any(c[0] == "POST" for c in fake.calls))

    def test_uncertain_start_is_durable_and_not_retried(self):
        calls = []

        def uncertain(method, url, token, body=None):
            calls.append((method, url))
            if method == "POST":
                raise OSError("connection lost after request")
            raise AssertionError("unexpected request")

        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", uncertain):
            first = apify.collect_apify([self.candidate], Path(d))
            post_count = len([x for x in calls if x[0] == "POST"])
            second = apify.collect_apify([self.candidate], Path(d))
        self.assertEqual(post_count, 2)
        self.assertEqual(len([x for x in calls if x[0] == "POST"]), post_count)
        self.assertTrue(all(e["status"] == "uncertain" for e in first["events"] + second["events"]))

    def test_changed_query_gets_distinct_state_and_new_run(self):
        fake = FakeApi()
        changed = dict(self.candidate, name="Red Widget")
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake), patch.object(apify, "_SLEEP", lambda _: None):
            apify.collect_apify([self.candidate], Path(d), max_charge_usd=4)
            apify.collect_apify([changed], Path(d), max_charge_usd=4)
            state = json.loads((Path(d) / "apify_runs.json").read_text())
        posts = [c for c in fake.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 4)  # two platforms for each distinct input
        self.assertGreaterEqual(len(state), 4)

    def test_saved_failed_run_emits_event_without_restart(self):
        fake = FakeApi()
        inp = apify._input_for(self.candidate, "tiktok", 100)
        key, digest = apify._config_key(self.candidate, "tiktok", inp)
        youtube_input = apify._input_for(self.candidate, "youtube", 100)
        youtube_key, youtube_digest = apify._config_key(self.candidate, "youtube", youtube_input)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake):
            Path(d).mkdir(parents=True, exist_ok=True)
            (Path(d) / "apify_runs.json").write_text(json.dumps({key: {"status": "failed", "provider_status": "FAILED", "run_id": "old-run", "config_hash": digest}, youtube_key: {"status": "failed", "provider_status": "FAILED", "run_id": "old-run", "config_hash": youtube_digest}}))
            out = apify.collect_apify([self.candidate], Path(d))
        self.assertFalse(any(c[0] == "POST" for c in fake.calls))
        tiktok = [e for e in out["events"] if e["platform"] == "tiktok"]
        self.assertEqual(tiktok[0]["status"], "failed")

    def test_tiny_budget_blocks_without_provider_start(self):
        fake = FakeApi()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", fake):
            out = apify.collect_apify([self.candidate], Path(d), max_charge_usd=0.000001)
        self.assertFalse(any(c[0] == "POST" for c in fake.calls))
        self.assertTrue(all(e["status"] == "blocked" for e in out["events"]))

    def test_invalid_numbers_dataset_and_slideshow_are_safe(self):
        self.assertIsNone(apify._number(float("nan")))
        self.assertIsNone(apify._number(float("inf")))
        self.assertIsNone(apify._number(-1))
        self.assertEqual(apify._number(2.0), 2)

        class BadDataset(FakeApi):
            def __call__(self, method, url, token, body=None):
                if "datasets/" in url:
                    return {"data": {"not": "a list"}}
                return super().__call__(method, url, token, body)

        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"APIFY_TOKEN": "secret"}), patch.object(apify, "_request_json", BadDataset()), patch.object(apify, "_SLEEP", lambda _: None):
            out = apify.collect_apify([self.candidate], Path(d))
        self.assertTrue(any(e["status"] == "error" for e in out["events"]))

        raw_item = {"id": "slide", "webVideoUrl": "https://www.tiktok.com/@a/video/slide", "text": "Blue Widget", "videoMeta": {"duration": 10}, "isSlideshow": True, "isAd": True}
        normalized = apify._tiktok(apify._sanitize(raw_item), self.candidate, "2026-09-21T00:00:00Z", "raw.json", "run")
        self.assertFalse(normalized["is_short"])
        self.assertTrue(apify._sanitize(raw_item)["isSlideshow"])


if __name__ == "__main__":
    unittest.main()
