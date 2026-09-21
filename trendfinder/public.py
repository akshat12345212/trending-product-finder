"""Best-effort public collection; unavailable fields stay unknown.

No cookies, login, proxy rotation, or CAPTCHA bypass. Public page layouts can
change. Every request records a receipt and the parsed source fields.
"""
import concurrent.futures
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from urllib.parse import urlparse, parse_qs, urljoin
from html.parser import HTMLParser


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def fetch(url):
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--location", "--max-time", "12",
         "--max-filesize", "10000000", "--proto", "=https", "--proto-redir", "=https",
         "--user-agent", "Mozilla/5.0", "--write-out", "\n%{http_code}", url],
        capture_output=True, timeout=16)
    if result.returncode:
        raise RuntimeError("public request failed (curl code %d)" % result.returncode)
    body, _, status = result.stdout.rpartition(b"\n")
    if status != b"200":
        raise RuntimeError("HTTP " + status.decode("ascii", "replace"))
    return body.decode("utf-8", "replace")


def embedded(page, variable):
    match = re.search(r"(?:var\s+)?" + re.escape(variable) + r"\s*=\s*", page)
    if not match:
        raise ValueError("page did not expose " + variable)
    return json.JSONDecoder().raw_decode(page[match.end():])[0]


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    return value.get("simpleText") or "".join(x.get("text", "") for x in value.get("runs", []))


def exact_count(value):
    """Never convert rounded '1.2K' display text into an exact measurement."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:,[0-9]{3})*", value):
        return int(value.replace(",", ""))
    return None


def product_match(title, candidate):
    normalized = " ".join(re.findall(r"\w+", title.casefold()))
    for alias in [candidate["name"]] + candidate.get("aliases", []):
        needle = " ".join(re.findall(r"\w+", alias.casefold()))
        if needle and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", normalized):
            return True
    return False


def search_videos(page):
    data = embedded(page, "ytInitialData")
    found = {}
    for node in walk(data):
        if "shortsLockupViewModel" in node:
            item = node["shortsLockupViewModel"]
            endpoint = item.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {})
            vid = endpoint.get("videoId")
            if vid:
                found[vid] = {"id": vid, "is_short": True, "search_title": item.get("accessibilityText", "")}
        for kind in ("reelItemRenderer", "videoRenderer"):
            item = node.get(kind, {})
            vid = item.get("videoId")
            if vid:
                found.setdefault(vid, {"id": vid, "is_short": kind == "reelItemRenderer", "search_title": text(item.get("title"))})
    return list(found.values())


def search_filter_url(page, label):
    """Follow the filter URL exposed by the actual page instead of guessing it."""
    for node in walk(embedded(page, "ytInitialData")):
        item = node.get("searchFilterRenderer", {})
        if text(item.get("label")) == label:
            path = (item.get("navigationEndpoint") or {}).get("commandMetadata", {}).get("webCommandMetadata", {}).get("url", "")
            if path.startswith("/results?"):
                return "https://www.youtube.com" + path
    return None


def parse_watch(page, candidate, discovered, observed):
    player = embedded(page, "ytInitialPlayerResponse")
    details = player.get("videoDetails", {})
    micro = player.get("microformat", {}).get("playerMicroformatRenderer", {})
    if not details.get("videoId") or details["videoId"] != discovered["id"]:
        raise ValueError("video metadata missing or identity mismatch")
    comments = None
    try:
        initial = embedded(page, "ytInitialData")
        for node in walk(initial):
            header = node.get("commentsHeaderRenderer", {})
            count = exact_count(text(header.get("countText")))
            if count is not None:
                comments = count
    except ValueError:
        pass
    is_short = discovered.get("is_short") is True or "/shorts/" in micro.get("canonicalUrl", "")
    vid = details["videoId"]
    title = details.get("title", "")
    return {
        "product_id": candidate["id"], "platform": "youtube", "id": vid,
        "url": "https://www.youtube.com/" + ("shorts/" + vid if is_short else "watch?v=" + vid),
        "creator_id": details.get("channelId"), "title": title,
        "published_at": micro.get("publishDate"), "observed_at": observed,
        "views": exact_count(details.get("viewCount")),
        "likes": exact_count(micro.get("likeCount")), "comments": comments,
        "country": None, "country_source": None,
        "is_short": is_short, "product_match": product_match(title, candidate),
        "match_method": "title phrase match; ambiguous items require review",
        "source": "public YouTube embedded metadata",
        "source_sha256": hashlib.sha256(page.encode()).hexdigest(),
    }


def collect_public(candidates, raw_dir, progress=print):
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    videos, events, discoveries = [], [], []
    # A single reachability probe avoids repeatedly hammering a blocked source.
    tik_url = "https://www.tiktok.com/search?q=trending%20products"
    try:
        page = fetch(tik_url)
        events.append({"platform": "tiktok", "status": "blocked", "url": tik_url,
                       "reason": "Public search did not provide a supported structured video dataset; use Apify adapter.",
                       "observed_at": timestamp(), "response_sha256": hashlib.sha256(page.encode()).hexdigest()})
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        events.append({"platform": "tiktok", "status": "blocked", "url": tik_url,
                       "reason": str(error), "observed_at": timestamp()})
    for candidate in candidates:
        progress("Collecting public YouTube evidence: " + candidate["name"])
        query = candidate["name"] + " shorts"
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query) + "&hl=en"
        try:
            page = fetch(url)
            filters_applied = []
            for label in ("This month", "Shorts"):
                filtered_url = search_filter_url(page, label)
                if filtered_url:
                    page = fetch(filtered_url)
                    url = filtered_url
                    filters_applied.append(label)
            found = search_videos(page)
            discoveries.append({"product_id": candidate["id"], "query": query, "url": url,
                                "observed_at": timestamp(), "items": found, "filters_applied": filters_applied,
                                "source_sha256": hashlib.sha256(page.encode()).hexdigest()})
            def collect_one(item):
                watch_url = "https://www.youtube.com/watch?v=" + item["id"] + "&hl=en"
                try:
                    page = fetch(watch_url)
                    video = parse_watch(page, candidate, item, timestamp())
                    return video, None
                except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                    return None, {"platform": "youtube", "product_id": candidate["id"],
                                  "url": watch_url, "status": "blocked", "reason": str(error), "observed_at": timestamp()}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                for video, error in pool.map(collect_one, found):
                    if video:
                        videos.append(video)
                    if error:
                        events.append(error)
            events.append({"platform": "youtube", "product_id": candidate["id"], "url": url,
                           "status": "partial", "discovered_count": len(found), "filters_applied": filters_applied, "observed_at": timestamp(),
                           "reason": "First public search page only; no pagination. Some engagement and country fields may be unavailable."})
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            events.append({"platform": "youtube", "product_id": candidate["id"], "url": url,
                           "status": "blocked", "reason": str(error), "observed_at": timestamp()})
    for name, data in (("public-videos.json", videos), ("public-discovery.json", discoveries), ("public-events.json", events)):
        (raw_dir / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"videos": videos, "events": events}


def seller_research_queue(candidates):
    """Queries are a research queue, never proof that no competitors exist."""
    queries = []
    suffixes = {"amazon_in": "site:amazon.in", "flipkart": "site:flipkart.com",
                "instagram": "site:instagram.com India buy order", "shopify": "India buy Shopify"}
    for candidate in candidates:
        for alias in [candidate["name"]] + candidate.get("aliases", []):
            for channel, suffix in suffixes.items():
                q = '"' + alias + '" ' + suffix
                queries.append({"product_id": candidate["id"], "channel": channel,
                                "query": q, "url": "https://www.google.com/search?q=" + quote_plus(q),
                                "status": "not_checked"})
    return queries


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append(href)


def collect_seller_leads(candidates, raw_dir, progress=print):
    """Attempt each channel, retaining discovery separately from active sellers.

    Search results cannot establish buyability or unique merchant identity. A
    completed channel review must be supplied in the evidence ledger.
    """
    receipts = []
    for candidate in candidates:
        progress("Checking India seller discovery: " + candidate["name"])
        checks = []
        name = quote_plus(candidate["name"])
        for channel, url in (
            ("amazon_in", "https://www.amazon.in/s?k=" + name),
            ("flipkart", "https://www.flipkart.com/search?q=" + name),
            ("instagram", "https://www.google.com/search?q=" + quote_plus('"' + candidate["name"] + '" site:instagram.com India buy')),
            ("shopify", "https://www.google.com/search?q=" + quote_plus('"' + candidate["name"] + '" India buy Shopify')),
        ):
            receipt = {"product_id": candidate["id"], "channel": channel, "query": candidate["name"],
                       "evidence_url": url, "checked_at": timestamp(), "status": "partial", "leads": []}
            try:
                page = fetch(url)
                receipt["response_sha256"] = hashlib.sha256(page.encode()).hexdigest()
                parser = Links(); parser.feed(page)
                for href in parser.links:
                    if href.startswith("/url?"):
                        href = parse_qs(urlparse(href).query).get("q", [""])[0]
                    href = urljoin(url, href)
                    parsed = urlparse(href)
                    host = parsed.hostname or ""
                    valid = (channel == "amazon_in" and host.endswith("amazon.in") and "/dp/" in parsed.path)
                    valid |= channel == "flipkart" and host.endswith("flipkart.com") and "/p/" in parsed.path
                    valid |= channel == "instagram" and host in ("instagram.com", "www.instagram.com")
                    valid |= channel == "shopify" and "/products/" in parsed.path and host not in ("google.com", "www.google.com")
                    if valid:
                        clean = parsed._replace(query="", fragment="").geturl()
                        if clean not in receipt["leads"]:
                            receipt["leads"].append(clean)
                receipt["reason"] = "Discovery only; unique seller identity, matching product, stock and India delivery require verification."
                if not receipt["leads"]:
                    receipt["status"] = "blocked"
                    receipt["reason"] = "No parseable listings; challenge, changed layout or empty search cannot establish zero sellers."
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
                receipt["status"] = "blocked"
                receipt["reason"] = str(error)
            checks.append(receipt)
            receipts.append(receipt)
        candidate["seller_checks"] = checks
    Path(raw_dir).mkdir(parents=True, exist_ok=True)
    (Path(raw_dir) / "seller-discovery.json").write_text(json.dumps(receipts, indent=2) + "\n")
    return receipts
