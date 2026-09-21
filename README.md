# Trending Product Finder — International + India

A Python automation with real public collection, optional TikTok/YouTube Apify collection, strict evidence gates, India seller discovery and auditable JSON/CSV/HTML output.

**Submission status: implementation and public pilot are provided; a fully verified qualifying product list is not yet established.** Public collection has data gaps. Do not present pending candidates as assignment-qualified products. See the included `results/live-public/report.html` and `SUBMISSION_STATUS.md` for observed results.

## Run

Requires Python 3.9+ and `curl` on PATH. No Python packages need installation. On Windows, install Python and curl or run in WSL.

```sh
python3 run.py --provider public --output results/new-public-run
```

The public route fetches real YouTube search/video metadata, attempts TikTok reachability, and attempts India seller discovery. It does not sign in, bypass challenges, or substitute synthetic data. Hidden comments and unavailable geography remain unknown. Public search is first-page-only and cannot meet the complete discovery requirement by itself.

For broader two-platform collection, configure an Apify account with access to the named actors, then run:

```sh
python3 run.py --provider apify --ask-token --per-query 100 --max-charge-usd 2 --output results/apify-run
```

The terminal prompts for the token without echoing it. It is retained only in that Python process. Alternatively, set `APIFY_TOKEN_FILE` to a local mode-0600 file managed by you; never put a token in a command argument, Git, screenshots or the submitted ZIP. Actor execution may spend provider credits. The budget argument is an invocation allocation using Apify's per-run charge parameter, subject to provider pricing and enforcement; it is not a guarantee of enough data. Increase acquisition breadth only within your budget. The Apify path is implemented and tested against transport fixtures; it has not been live-validated without credentials.

Reuse the same output directory to resume recorded runs. Use a new output directory for a genuinely new collection. Preserve run state; an uncertain run start must be resolved in Apify before a new billable start. Provider failures remain visible. Do not repeatedly create new runs to work around an access denial.

## Review evidence and re-evaluate

`candidates.json` defines the pilot search universe and aliases. Add candidates to expand it. All candidates are assessed; all qualifiers are exported. Acquisition limits and final output size are separate.

Inspect `seller-research-queue.json`, `raw/seller-discovery.json`, video evidence and the source links. Record verified shipping, seller/channel coverage and optional video matching/geography corrections in a ledger following `evidence-ledger.template.json`. The template contains placeholders only and does not qualify anything.

```sh
python3 run.py --input results/live-public/dataset.json --review your-review-ledger.json --output results/reviewed
```

Reassessment preserves original observation timestamps; it never makes stale data fresh. Only shipping/sellers/channel checks/hero fields and video match/country evidence can be changed by a review ledger. New metrics must come from a new collection or a documented imported dataset. Human review is an explicit part of this version, especially for shipping restrictions and seller identity; those steps are not claimed to be fully automated.

For each seller channel, record queries and aliases, review date, pages covered, unresolved leads and a source URL. Only mark `complete` when all matching leads in that search scope have been adjudicated. A seller record needs a canonical business ID shared across its storefronts, name, source URL, channel, current activity and evidence of India delivery. Unknown values block an India recommendation. For shipping, retain the supplier's packed dimensions/weight and the route-specific carrier/restriction review in ledger notes with source links.

## Outputs

- `report.html`: readable report with expandable live video evidence and collection gaps.
- `international.json` / `.csv` and `india.json` / `.csv`: every qualified product, without a shortlist cap.
- `all-candidates.csv`: all assessed candidates including pending/rejected ones.
- `video-evidence.csv`: source URLs, observed timestamps and measurements; empty cells mean unknown.
- `report.json`: thresholds, per-video decisions, counted evidence, product rejection/pending reasons.
- `dataset.json`: reproducible normalized input; `raw/`: collection receipts and parsed source fields.
- `seller-research-queue.json`: links to research, never evidence of absence.

## Validation

```sh
python3 -m unittest discover -s tests -v
```

Tests use explicitly synthetic fixtures for boundaries and failure modes. They cover thresholds, deduplication, country proof, creator limits, freshness, shipping, seller uncertainty, provider pagination/resumption and safe report rendering. Live pilot output is kept separately under `results/`.

## References and limitations

- [Assignment](https://docs.google.com/document/d/1cm-_2svmjtRXDbBif0ajB05QGWKyPIKZN4KhymBYg2k/edit)
- [TikTok actor input contract](https://apify.com/clockworks/tiktok-scraper/input-schema)
- [YouTube actor input contract](https://apify.com/streamers/youtube-scraper/input-schema)
- [Apify actor run API](https://docs.apify.com/api/v2/act-runs-post)
- [Apify dataset items API](https://docs.apify.com/api/v2/dataset-items-get)

See `METHODOLOGY.md` for the brief's judgment calls. Public HTML can change; transport fixtures do not establish continued provider compatibility. Caption matching can miss synonyms and cannot visually identify products. Geographic metadata is incomplete. Seller search is not a census. There are no fabricated winner rows, supplier quotes or unsupported profitability claims.
