import argparse
import csv
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .engine import evaluate
from .public import collect_public, collect_seller_leads, seller_research_queue


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def csv_file(path, rows, fields):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {}
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    value = "'" + value
                safe[key] = value
            writer.writerow(safe)


def export_report(dataset, output):
    output.mkdir(parents=True, exist_ok=True)
    report = evaluate(dataset)
    report["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    source_candidates = {c["id"]: c for c in dataset["candidates"]}
    for item in report["candidates"]:
        original = source_candidates[item["id"]]
        item["hero_hypothesis"] = original.get("hero", {})
        item["shipping_evidence"] = original.get("shipping", {})
        item["seller_evidence"] = original.get("sellers", [])
        item["seller_checks"] = original.get("seller_checks", [])
    save_json(output / "dataset.json", dataset)
    save_json(output / "report.json", report)
    save_json(output / "international.json", report["international"])
    save_json(output / "india.json", report["india"])
    save_json(output / "seller-research-queue.json", seller_research_queue(dataset["candidates"]))
    fields = ["id", "name", "status", "international", "india", "stats", "reasons", "international_reasons", "india_reasons", "hero_hypothesis", "shipping_evidence", "seller_evidence"]
    csv_file(output / "all-candidates.csv", report["candidates"], fields)
    csv_file(output / "international.csv", report["international"], fields)
    csv_file(output / "india.csv", report["india"], fields)
    video_fields = ["product_id", "platform", "id", "url", "title", "creator_id", "published_at", "observed_at", "views", "likes", "comments", "country", "country_source", "is_short", "product_match"]
    csv_file(output / "video-evidence.csv", dataset.get("videos", []), video_fields)
    e = lambda value: html.escape(str(value))
    rows = []
    for item in report["candidates"]:
        details = []
        for video in [v for v in dataset.get("videos", []) if v.get("product_id") == item["id"]]:
            url = video.get("url", "")
            if not url.startswith(("https://", "http://")):
                url = "#"
            details.append('<tr><td><a target="_blank" rel="noopener" href="' + e(url) + '">' + e(video.get("title") or video.get("id")) + '</a></td>' + ''.join('<td>' + e(video.get(k) if video.get(k) is not None else "Unknown") + '</td>' for k in ("views", "likes", "comments", "country")) + '</tr>')
        reasons = item.get("international_reasons", item.get("reasons", []))
        india_reasons = item.get("india_reasons", [])
        counts = item["stats"]
        checks = source_candidates[item["id"]].get("seller_checks", [])
        check_text = '; '.join(c["channel"] + ': ' + c["status"] for c in checks) or "Not checked"
        rows.append('<article><div class="tag">' + e(item["status"]) + '</div><h2>' + e(item["name"]) + '</h2><p><strong>' + e(counts["qualifying_video_count"]) + '</strong> qualifying videos · ' + e(counts["platform_count"]) + ' platforms · ' + e(counts["country_count"]) + ' evidenced countries</p><p><b>International:</b> ' + e('; '.join(reasons) or 'Qualified') + '</p><p><b>India:</b> ' + e('; '.join(india_reasons) or ('Qualified' if item["india"] else 'Pending')) + '</p><p class="muted">Seller coverage: ' + e(check_text) + '</p><details><summary>Inspect ' + str(len(details)) + ' collected video records</summary><div class="scroll"><table><tr><th>Source video</th><th>Views</th><th>Likes</th><th>Comments</th><th>Country</th></tr>' + ''.join(details) + '</table></div></details></article>')
    events = dataset.get("collection", {}).get("events", [])
    failures = [x for x in events if x.get("status") not in ("complete", "succeeded", "success")]
    intro = "Live collection completed with evidence gaps. These are research candidates; only entries in the qualified exports meet the published gates."
    if dataset.get("collection", {}).get("assessment_mode") == "import":
        intro = "Imported evidence assessment. This command does not fetch new data or refresh observation timestamps."
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trending Product Finder — Evidence report</title><style>
    :root{font-family:system-ui,sans-serif;color:#18332e;background:#f3f5f1}body{max-width:1100px;margin:48px auto;padding:0 24px}h1{font-size:42px;letter-spacing:-1.5px;margin:8px 0}h2{font-size:24px}.eyebrow{letter-spacing:2px;font-size:12px;font-weight:700}.notice{background:#fff2d6;border-left:4px solid #bf8b24;padding:18px;line-height:1.6}.metrics{display:flex;gap:18px;margin:24px 0}.metric{background:#173f35;color:white;padding:22px;border-radius:12px;flex:1}.metric strong{display:block;font-size:34px}.metric span{font-size:13px}article{background:white;padding:24px;border:1px solid #dce4dd;border-radius:12px;margin:16px 0}p{line-height:1.6}.tag{float:right;text-transform:uppercase;font-size:11px;letter-spacing:1px;background:#edf0e6;padding:8px 12px;border-radius:20px}.muted{color:#617369;font-size:13px}a{color:#006a60}summary{cursor:pointer;font-weight:600}table{width:100%;border-collapse:collapse;font-size:13px;margin:20px 0}td,th{text-align:left;border-bottom:1px solid #e4e8e2;padding:10px}.scroll{overflow-x:auto}pre{white-space:pre-wrap;font-size:12px;background:white;padding:20px}footer{margin:32px 0;font-size:13px}@media(max-width:600px){.metrics{flex-direction:column}h1{font-size:32px}}
    </style><div class="eyebrow">TREND INTELLIGENCE / AUDITABLE EVIDENCE</div><h1>Trending Product Finder</h1>'''
    document += '<p class="muted">Evaluated ' + e(report["evaluated_at"]) + '</p><div class="notice">' + e(intro) + '</div><div class="metrics">'
    for value, label in ((len(dataset.get("videos", [])), "Collected video records"), (len(report["international"]), "Qualified international"), (len(report["india"]), "Qualified India opportunities")):
        document += '<div class="metric"><strong>' + str(value) + '</strong><span>' + label + '</span></div>'
    document += '</div><p>30-day window · ≥4% engagement · ≥10,000 views · ≥50 videos · ≥2 platforms · ≥5 countries. Shipping and India seller verification are additional gates.</p>'
    document += ''.join(rows) + '<details><summary>Collection gaps (' + str(len(failures)) + ')</summary><pre>' + e(json.dumps(failures, indent=2)) + '</pre></details><footer>Downloads: <a href="report.json">Full audit JSON</a> · <a href="video-evidence.csv">Video evidence CSV</a> · <a href="all-candidates.csv">All candidates CSV</a> · <a href="international.csv">International</a> · <a href="india.csv">India</a></footer></html>'
    (output / "report.html").write_text(document)
    return report


def main():
    parser = argparse.ArgumentParser(description="Collect and qualify trending product evidence. No fabricated examples in live mode.")
    parser.add_argument("--provider", choices=["public", "apify"], default="public")
    parser.add_argument("--candidates", type=Path, default=Path(__file__).resolve().parents[1] / "candidates.json")
    parser.add_argument("--input", type=Path, help="Assess a previously collected dataset without network access")
    parser.add_argument("--review", type=Path, help="Evidence ledger: candidate shipping/seller/hero fields and video match/country reviews")
    parser.add_argument("--output", type=Path, default=Path("results") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--per-query", type=int, default=100, help="Apify acquisition budget per candidate/platform; never limits qualified output")
    parser.add_argument("--max-charge-usd", type=float, default=2.0, help="Apify total invocation budget; applies only when explicitly selecting apify")
    parser.add_argument("--skip-seller-discovery", action="store_true", help="Skip network attempts; India still requires coverage evidence")
    parser.add_argument("--ask-token", action="store_true", help="Prompt securely for an Apify token for this process only; never saved")
    args = parser.parse_args()
    if args.per_query <= 0 or not math.isfinite(args.max_charge_usd) or args.max_charge_usd <= 0:
        parser.error("collection limits must be positive")
    if args.ask_token:
        if args.provider != "apify" or args.input:
            parser.error("--ask-token requires live --provider apify")
        import getpass
        import os
        os.environ["APIFY_TOKEN"] = getpass.getpass("Apify token (hidden, not saved): ")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.input:
        dataset = json.loads(args.input.read_text())
        dataset.setdefault("collection", {})["assessment_mode"] = "import"
    else:
        candidates = json.loads(args.candidates.read_text())
        if not isinstance(candidates, list) or not candidates:
            parser.error("candidates must be a nonempty JSON list")
        if len({c["id"] for c in candidates}) != len(candidates):
            parser.error("candidate IDs must be unique")
        raw = args.output / "raw"
        if args.provider == "public":
            collected = collect_public(candidates, raw)
        else:
            from .apify import collect_apify
            collected = collect_apify(candidates, raw, per_query=args.per_query, max_charge_usd=args.max_charge_usd)
        if not args.skip_seller_discovery:
            checks = collect_seller_leads(candidates, raw)
            collected["events"].extend(checks)
        dataset = {"candidates": candidates, "videos": collected["videos"],
                   "collection": {"mode": args.provider, "events": collected["events"],
                                  "started_from": str(args.candidates), "completed_at": datetime.now(timezone.utc).isoformat()}}
    if args.review:
        review = json.loads(args.review.read_text())
        by_id = {c["id"]: c for c in dataset["candidates"]}
        for row in review.get("candidates", []):
            if row["id"] not in by_id:
                parser.error("review references unknown candidate " + row["id"])
            for key in ("shipping", "sellers", "seller_checks", "hero"):
                if key in row:
                    by_id[row["id"]][key] = row[key]
        by_video = {(v["product_id"], v["platform"], v["id"]): v for v in dataset["videos"]}
        for row in review.get("videos", []):
            key = (row["product_id"], row["platform"], row["id"])
            if key not in by_video:
                parser.error("review references an unknown video")
            for field in ("product_match", "country", "country_source"):
                if field in row:
                    by_video[key][field] = row[field]
        dataset["collection"]["review_ledger"] = str(args.review)
        save_json(args.output / "review-ledger.json", review)
    report = export_report(dataset, args.output)
    print(json.dumps(report["summary"], indent=2))
    print("Report: " + str((args.output / "report.html").resolve()))
    if not report["international"]:
        print("No product currently clears all evidence gates. Inspect pending reasons; this is not proof that no trending products exist.")
