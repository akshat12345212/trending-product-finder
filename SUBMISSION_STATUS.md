# Submission status — 21 September 2026

**Partial assignment delivery. The automation runs, but the required live qualified product lists have not been established.**

## Delivered and verified

- Runnable Python code with public YouTube collection and an optional Apify TikTok/YouTube adapter.
- Successful public end-to-end run: 144 video records representing 140 distinct videos across six candidate search hypotheses, using page-provided “This month” and “Shorts” filters.
- Exact view counts on 144 records and exact like counts on 140. No comment counts or creator-country evidence were exposed by the parsed public pages.
- All-candidate, international and India JSON/CSV outputs; per-video audit reasons; a browser-verified HTML report.
- 27 automated tests passed. Fixture records are synthetic and separated from real live evidence. See `VALIDATION.txt`.
- A one-page methodology and a review-ledger template.

## Observed pilot results

| Candidate hypothesis | Collected videos | Like count available | India seller estimate | Decision |
| --- | ---: | ---: | --- | --- |
| heatless curling rod | 25 | 25 | Unknown | Pending |
| pet hair remover | 25 | 24 | Unknown | Pending |
| silicone faucet mat | 19 | 18 | Unknown | Pending |
| compression packing cubes | 25 | 25 | Unknown | Pending |
| magnetic cable clips | 25 | 25 | Unknown | Pending |
| reusable lint roller | 25 | 23 | Unknown | Pending |

**Qualified international products: 0. Qualified India opportunities: 0.** These empty lists mean evidence is insufficient in this run, not that the market has no opportunities. Even the collected videos are not all confirmed product matches; the matching flag and audit reasons preserve that distinction.

## Unresolved dependencies

1. Obtain authorized access to sufficient live TikTok and YouTube data. Public TikTok timed out. No Apify credentials were configured, so no paid actor was launched. The adapter has transport-fixture coverage, but still needs live validation. Configuration instructions are in `README.md`.
2. Collect at least 50 qualifying videos per potential winner, with the required platform and country diversity. Validate ambiguous title/caption matches and obtain supported country evidence. Public comment counts are currently unavailable; they were not set to zero.
3. Complete India seller verification. All 24 pilot channel-discovery attempts were blocked or yielded no parseable listings. Search failure is not zero sellers. Resolve seller identity, activity and India delivery, including duplicate storefronts.
4. Confirm shipping suitability from actual packed specifications and route-specific restrictions. All six products remain pending this review.

The candidate list is a finite pilot universe. It is not autonomous open-ended product discovery or an exhaustive market scan. Broaden the candidate inputs and acquire deeper evidence for a final submission. Supplier sourcing is omitted because no comparable landed-cost quotations were verified.

The assignment has not been submitted to an evaluator. No message or purchase was performed.
