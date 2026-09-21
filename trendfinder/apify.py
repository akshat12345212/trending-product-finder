"""Small, auditable Apify adapter for TikTok and YouTube discovery.

The adapter intentionally has no third-party dependencies.  The HTTP boundary is
kept in :func:`_request_json` so callers and tests can replace it without ever
making a paid call.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

API = "https://api.apify.com/v2/"
ACTORS = {"tiktok": "clockworks~tiktok-scraper", "youtube": "streamers~youtube-scraper"}
POLL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 900
PAGE_SIZE = 1000
_SLEEP: Callable[[float], None] = time.sleep


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token() -> Optional[str]:
    value = os.environ.get("APIFY_TOKEN")
    if value:
        return value.strip() or None
    path = os.environ.get("APIFY_TOKEN_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


def _request_json(method: str, url: str, token: str, body: Optional[dict] = None) -> Union[dict, list]:
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:  # no token in URL or logs
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _event(platform: str, candidate: dict, status: str, **extra: Any) -> dict:
    out = {"platform": platform, "candidate_id": candidate.get("id"), "candidate": candidate.get("name"), "status": status}
    out.update(extra)
    return out


def _state_path(raw_dir: Path) -> Path:
    return raw_dir / "apify_runs.json"


def _read_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _extract_data(value: Union[dict, list]) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def _status(run: dict) -> str:
    value = run.get("status") if isinstance(run, dict) else None
    return str(value or "").upper()


def _dataset_items(dataset_id: str, token: str) -> list:
    items: list = []
    offset = 0
    while True:
        url = API + "datasets/" + quote(dataset_id, safe="") + "/items?" + urlencode({"limit": PAGE_SIZE, "offset": offset, "format": "json"})
        page = _extract_data(_request_json("GET", url, token))
        if not isinstance(page, list):
            raise RuntimeError("Apify dataset returned an invalid page")
        items.extend(x for x in page if isinstance(x, dict))
        if len(page) < PAGE_SIZE:
            break
        offset += len(page)
    return items


def _strings(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _number(value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = value
    else:
        try:
            number = float(value.strip()) if isinstance(value, str) and value.strip() else None
        except (TypeError, ValueError):
            number = None
    if number is None or not math.isfinite(number) or number < 0:
        return None
    if float(number).is_integer():
        return int(number)
    return number


def _iso_time(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


COUNTRIES = {"united states": "US", "usa": "US", "united kingdom": "GB", "great britain": "GB", "india": "IN", "canada": "CA", "australia": "AU", "germany": "DE", "france": "FR", "japan": "JP", "brazil": "BR", "singapore": "SG"}


def _country(value: Any) -> Optional[str]:
    text = _strings(value).strip()
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return COUNTRIES.get(text.lower())


def _terms(candidate: dict) -> list[str]:
    values = [candidate.get("name")] + (candidate.get("aliases") or [])
    return [" ".join(re.findall(r"[\w]+", str(v).lower(), re.UNICODE)) for v in values if str(v or "").strip()]


def _match(candidate: dict, *values: Any) -> bool:
    haystack = " ".join(_strings(v).lower() for v in values)
    tokens = re.findall(r"[\w]+", haystack, re.UNICODE)
    for term in _terms(candidate):
        wanted = term.split()
        if wanted and any(tokens[i:i + len(wanted)] == wanted for i in range(len(tokens) - len(wanted) + 1)):
            return True
    return False


def _tiktok(item: dict, candidate: dict, observed: str, raw_file: str, run_id: str) -> dict:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    title = item.get("text") or item.get("desc") or item.get("title")
    duration = _number(item.get("videoMeta", {}).get("duration") if isinstance(item.get("videoMeta"), dict) else item.get("duration"))
    # A slideshow has no actual video duration and is therefore not a short.
    slideshow = bool(item.get("imagePost") or item.get("images") or item.get("isSlideshow"))
    is_short = (not slideshow and isinstance(duration, (int, float)) and duration <= 180 and duration >= 0
                and bool(item.get("webVideoUrl") or item.get("id")))
    published = _iso_time(item.get("createTimeISO")) or _iso_time(item.get("createTime"))
    return {"product_id": candidate.get("id"), "platform": "tiktok", "id": _strings(item.get("id")) or None, "url": item.get("webVideoUrl") or item.get("url"), "creator_id": author.get("id") or item.get("authorId"), "published_at": published, "observed_at": observed, "views": _number(item.get("playCount")), "likes": _number(item.get("diggCount")), "comments": _number(item.get("commentCount")), "country": _country(item.get("locationCreated")), "country_source": "TikTok locationCreated via Apify" if item.get("locationCreated") else None, "is_short": is_short, "product_match": _match(candidate, title, item.get("hashtags"), item.get("text")), "title": title, "raw_file": raw_file, "run_id": run_id}


def _youtube(item: dict, candidate: dict, observed: str, raw_file: str, run_id: str) -> dict:
    vid = item.get("id") if item.get("id") is not None else item.get("videoId")
    if vid is not None:
        vid = str(vid)
    url = item.get("url") or ("https://www.youtube.com/watch?v=" + vid if vid else None)
    title = item.get("title") or item.get("name")
    kind = str(item.get("type") or item.get("contentType") or "").lower()
    is_short = "/shorts/" in (url or "") or kind in {"short", "shorts", "youtube_short"} or item.get("isShort") is True
    return {"product_id": candidate.get("id"), "platform": "youtube", "id": vid, "url": url, "creator_id": item.get("channelId") or item.get("channel_id"), "published_at": _iso_time(item.get("date")) or _iso_time(item.get("publishedAt")), "observed_at": observed, "views": _number(item.get("viewCount") if item.get("viewCount") is not None else item.get("views")), "likes": _number(item.get("likes") if item.get("likes") is not None else item.get("likeCount")), "comments": _number(item.get("commentsCount") if item.get("commentsCount") is not None else item.get("commentCount")), "country": None, "country_source": None, "is_short": is_short, "product_match": _match(candidate, title, item.get("description")), "title": title, "raw_file": raw_file, "run_id": run_id}


def _sanitize(item: dict) -> dict:
    allowed = {"id", "videoId", "url", "webVideoUrl", "title", "name", "description", "text", "desc", "date", "publishedAt", "viewCount", "views", "likes", "likesCount", "likeCount", "commentsCount", "commentCount", "playCount", "diggCount", "locationCreated", "createTime", "createTimeISO", "type", "contentType", "channelId", "channel_id", "authorId", "authorMeta", "videoMeta", "duration", "hashtags", "imagePost", "images", "isSlideshow", "isAd", "isShort"}
    out = {k: v for k, v in item.items() if k in allowed and isinstance(v, (str, int, float, bool, type(None), list, dict))}
    # Keep evidence page URLs only.  CDN/download URLs may be signed and must
    # never be copied into durable raw evidence.
    for key in ("url", "webVideoUrl"):
        value = out.get(key)
        if isinstance(value, str):
            host = (urlparse(value).hostname or "").lower()
            if host not in {"tiktok.com", "www.tiktok.com", "youtube.com", "www.youtube.com", "youtu.be"}:
                out.pop(key, None)
    if isinstance(out.get("authorMeta"), dict):
        author = out["authorMeta"]
        out["authorMeta"] = {k: author.get(k) for k in ("id", "name", "uniqueId", "nickname") if isinstance(author.get(k), (str, int, float, bool, type(None)))}
    if isinstance(out.get("videoMeta"), dict):
        meta = out["videoMeta"]
        out["videoMeta"] = {k: meta.get(k) for k in ("duration", "width", "height", "ratio", "definition") if isinstance(meta.get(k), (str, int, float, bool, type(None)))}
    if isinstance(out.get("hashtags"), list):
        out["hashtags"] = [x for x in out["hashtags"] if isinstance(x, (str, int, float, bool))]
    return out


def _input_for(candidate: dict, platform: str, per_query: int) -> dict:
    if platform == "tiktok":
        return {"searchQueries": [candidate.get("name")], "searchSection": "/video", "resultsPerPage": int(per_query), "shouldDownloadVideos": False, "shouldDownloadCovers": False}
    return {"searchQueries": [candidate.get("name")], "maxResults": 0, "maxResultsShorts": int(per_query), "maxResultStreams": 0, "dateFilter": "month"}


def _config_key(candidate: dict, platform: str, inp: dict) -> Tuple[str, str]:
    base = str(candidate.get("id") or candidate.get("name") or "")
    digest = hashlib.sha256(json.dumps({"actor": ACTORS[platform], "input": inp}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    return base + ":" + platform + ":" + digest, digest


def _safe_stem(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "candidate"))
    return text.strip("._")[:80] or "candidate"


def collect_apify(candidates: list, raw_dir: Path, per_query: int = 100, max_charge_usd: float = 2.0) -> dict:
    """Collect and normalize matching videos; API failures are represented in events."""
    raw_dir = Path(raw_dir)
    result = {"videos": [], "events": []}
    if not isinstance(candidates, list) or not candidates:
        return result
    token = _token()
    if not token:
        result["events"].append({"status": "blocked", "reason": "APIFY_TOKEN or APIFY_TOKEN_FILE is required"})
        return result
    raw_dir.mkdir(parents=True, exist_ok=True)
    state_file = _state_path(raw_dir); state = _read_state(state_file)
    keys = [(c, p) for c in candidates if isinstance(c, dict) for p in ACTORS]
    try:
        parsed_budget = float(max_charge_usd)
        total_budget = parsed_budget if math.isfinite(parsed_budget) and parsed_budget > 0 else 0.0
    except (TypeError, ValueError):
        total_budget = 0.0
    allocation = math.floor((total_budget / max(1, len(keys))) * 1000000) / 1000000
    for candidate, platform in keys:
        inp = _input_for(candidate, platform, per_query)
        key, config_hash = _config_key(candidate, platform, inp)
        entry = state.get(key) if isinstance(state.get(key), dict) else {}
        run_id = entry.get("run_id"); observed = entry.get("observed_at") or _utc_now()
        try:
            if entry.get("uncertain") or entry.get("status") == "starting":
                result["events"].append(_event(platform, candidate, "uncertain", reason="previous start may have succeeded; verify Apify console before retry", config_hash=config_hash))
                continue
            if entry.get("status") in {"failed", "aborted", "timed-out"}:
                result["events"].append(_event(platform, candidate, entry["status"], run_id=run_id, provider_status=entry.get("provider_status"), config_hash=config_hash))
                continue
            run = None
            if run_id:
                run = _extract_data(_request_json("GET", API + "actor-runs/" + quote(str(run_id), safe=""), token))
                if not isinstance(run, dict):
                    raise RuntimeError("Apify run status response was invalid")
                current_status = _status(run)
                if current_status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                    terminal = current_status.lower()
                    state[key] = dict(entry, status=terminal, provider_status=current_status, run_id=run_id, config_hash=config_hash)
                    _write_state(state_file, state)
                    result["events"].append(_event(platform, candidate, terminal, run_id=run_id, provider_status=current_status, config_hash=config_hash))
                    continue
            if not run_id:
                if allocation <= 0:
                    result["events"].append(_event(platform, candidate, "blocked", reason="max_charge_usd is too small to allocate a positive provider cap", config_hash=config_hash))
                    continue
                query = urlencode({"maxTotalChargeUsd": ("%.6f" % allocation).rstrip("0").rstrip("."), "waitForFinish": "0"})
                state[key] = {"status": "starting", "uncertain": True, "platform": platform, "candidate_id": candidate.get("id"), "config_hash": config_hash, "input": inp, "started_at": _utc_now()}
                _write_state(state_file, state)
                try:
                    started = _extract_data(_request_json("POST", API + "actors/" + quote(ACTORS[platform], safe="~") + "/runs?" + query, token, inp))
                except Exception:
                    result["events"].append(_event(platform, candidate, "uncertain", reason="run start failed after durable start intent; verify Apify console before retry", config_hash=config_hash))
                    continue
                if not isinstance(started, dict):
                    raise RuntimeError("Apify returned an invalid run response")
                run_id = started.get("id") or started.get("runId")
                if not run_id:
                    result["events"].append(_event(platform, candidate, "uncertain", reason="Apify accepted start without a run id; verify Apify console before retry", config_hash=config_hash))
                    continue
                observed = _utc_now()
                entry = {"run_id": run_id, "platform": platform, "candidate_id": candidate.get("id"), "observed_at": observed, "config_hash": config_hash, "input": inp, "status": "started"}
                state[key] = entry; _write_state(state_file, state)
            deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
            while True:
                run = _extract_data(_request_json("GET", API + "actor-runs/" + quote(str(run_id), safe=""), token))
                status = _status(run if isinstance(run, dict) else {})
                if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}: break
                if time.monotonic() >= deadline:
                    result["events"].append(_event(platform, candidate, "timeout", run_id=run_id)); break
                _SLEEP(POLL_SECONDS)
            if not isinstance(run, dict) or _status(run) != "SUCCEEDED":
                terminal = _status(run if isinstance(run, dict) else {}) or "unknown"
                if terminal in {"FAILED", "ABORTED", "TIMED-OUT"}:
                    state[key] = dict(state.get(key, entry), status=terminal.lower(), provider_status=terminal)
                    _write_state(state_file, state)
                    result["events"].append(_event(platform, candidate, terminal.lower(), run_id=run_id, provider_status=terminal, config_hash=config_hash))
                continue
            dataset_id = run.get("defaultDatasetId") or run.get("datasetId")
            if not dataset_id: raise RuntimeError("successful Apify run has no dataset")
            items = _dataset_items(str(dataset_id), token)
            raw_name = "%s_%s_%s.json" % (platform, _safe_stem(candidate.get("id") or candidate.get("name")), hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:12])
            raw_file = str(raw_dir / raw_name)
            sanitized = [_sanitize(i) for i in items]
            raw = {"collected_at": observed, "platform": platform, "candidate_id": candidate.get("id"), "run_id": run_id, "config_hash": config_hash, "input": inp, "items": sanitized}
            Path(raw_file).write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
            normalizer = _tiktok if platform == "tiktok" else _youtube
            result["videos"].extend(normalizer(item, candidate, observed, raw_file, str(run_id)) for item in sanitized)
            result["events"].append(_event(platform, candidate, "succeeded", run_id=run_id, count=len(items), raw_file=raw_file))
        except (HTTPError, URLError, OSError, ValueError, TypeError, RuntimeError) as exc:
            result["events"].append(_event(platform, candidate, "error", error=str(exc), run_id=run_id))
    return result
