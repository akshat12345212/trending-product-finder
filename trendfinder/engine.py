"""Pure, deterministic scoring for collected product and video evidence."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
THRESHOLDS = {'lookback_days': 30, 'observed_max_age_days': 7, 'minimum_views': 10000, 'minimum_engagement_rate': 0.04, 'minimum_unique_videos': 50, 'minimum_platforms': 2, 'minimum_videos_per_platform': 5, 'minimum_countries': 5, 'minimum_videos_per_country': 3, 'minimum_creators': 10, 'maximum_videos_per_creator': 5, 'shipping_max_weight_kg': 1.0, 'shipping_max_longest_side_cm': 40.0, 'seller_check_fresh_days': 7, 'maximum_india_sellers': 5}
PLATFORMS = {'tiktok', 'youtube', 'instagram'}
CHANNELS = {'amazon_in', 'flipkart', 'instagram', 'shopify'}
ISO2 = set('AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW'.split())
HOSTS = {'tiktok': {'tiktok.com', 'www.tiktok.com'}, 'youtube': {'youtube.com', 'www.youtube.com', 'youtu.be'}, 'instagram': {'instagram.com', 'www.instagram.com'}}

def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None

def _num(value: Any, integer=False, positive=False) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and (not integer or isinstance(value, int)) and isfinite(value) and (value > 0 if positive else value >= 0)

def _video_url(value: Any, platform: str | None) -> tuple[str | None, str | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return (None, None, 'missing evidence URL')
    try:
        p = urlparse(value.strip())
    except ValueError:
        return (None, None, 'invalid evidence URL')
    host = (p.hostname or '').lower()
    if p.scheme not in {'http', 'https'} or not host or p.username is not None or (p.password is not None) or (host not in HOSTS.get(platform, set())):
        return (None, None, 'URL host does not match platform')
    pairs = dict(parse_qsl(p.query, keep_blank_values=True))
    identity = None
    if platform == 'youtube':
        if host == 'youtu.be' and p.path.strip('/'):
            identity = p.path.strip('/').split('/')[0]
        elif p.path.startswith('/shorts/'):
            identity = p.path.split('/', 2)[2].split('/')[0]
        elif p.path == '/watch' and pairs.get('v'):
            identity = pairs['v']
        else:
            return (None, None, 'URL path is not a plausible video')
        keep = [('v', identity)] if p.path == '/watch' else []
    elif platform == 'tiktok':
        bits = p.path.strip('/').split('/')
        if len(bits) < 3 or not bits[0].startswith('@') or bits[1] != 'video' or (not bits[2]):
            return (None, None, 'URL path is not a plausible video')
        (identity, keep) = (bits[2], [])
    else:
        bits = p.path.strip('/').split('/')
        if len(bits) != 2 or bits[0] != 'reel' or (not bits[1]):
            return (None, None, 'URL path is not a plausible video')
        (identity, keep) = (bits[1], [])
    return (urlunparse(('https', host, p.path.rstrip('/') or '/', '', urlencode(keep), '')), identity, None)

def _video_result(v: dict[str, Any], now: datetime, seen: set[str]) -> dict[str, Any]:
    r: list[str] = []
    platform = v.get('platform')
    supplied_id = v.get('id')
    creator = v.get('creator_id')
    if platform not in PLATFORMS:
        r.append('unsupported platform')
    if not isinstance(supplied_id, str) or not supplied_id.strip():
        r.append('video id missing')
    if not isinstance(creator, str) or not creator.strip():
        r.append('creator id missing')
    if v.get('is_short') is not True:
        r.append('not a verified short')
    if v.get('product_match') is not True:
        r.append('product match not verified')
    (published, observed) = (_dt(v.get('published_at')), _dt(v.get('observed_at')))
    if not published:
        r.append('invalid published_at')
    elif published > now:
        r.append('published_at is in the future')
    elif published < now - timedelta(days=THRESHOLDS['lookback_days']):
        r.append('outside lookback')
    if not observed:
        r.append('invalid observed_at')
    elif observed > now:
        r.append('observed_at is in the future')
    elif observed < now - timedelta(days=THRESHOLDS['observed_max_age_days']):
        r.append('observation is stale')
    if published and observed and (observed < published):
        r.append('observation before publication')
    (views, likes, comments) = (v.get('views'), v.get('likes'), v.get('comments'))
    er = None
    if not _num(views, integer=True, positive=True) or views < THRESHOLDS['minimum_views']:
        r.append('views below threshold or invalid')
    if not _num(likes, integer=True) or not _num(comments, integer=True):
        r.append('engagement metric invalid')
    elif _num(views, integer=True, positive=True):
        er = (likes + comments) / views
        if er < THRESHOLDS['minimum_engagement_rate']:
            r.append('engagement rate below threshold')
    canonical = identity = None
    if platform in PLATFORMS:
        (canonical, identity, err) = _video_url(v.get('url'), platform)
        if err:
            r.append(err)
    if identity and supplied_id != identity:
        r.append('video id does not match URL')
    dedup = f'{platform}:{identity or supplied_id}' if platform in PLATFORMS and (identity or supplied_id) else None
    if dedup and dedup in seen:
        r.append('duplicate canonical video')
    if dedup:
        seen.add(dedup)
    country = v.get('country')
    country = country.upper() if isinstance(country, str) else None
    if country is not None and country not in ISO2:
        r.append('invalid country')
    geo = bool(country in ISO2 and v.get('country_source'))
    geo_reason = None if geo else 'country proof missing' if country else 'country unknown'
    return {'id': supplied_id, 'platform': platform, 'url': v.get('url'), 'canonical_url': canonical, 'creator_id': creator, 'country': country, 'country_eligible': geo, 'views': views, 'likes': likes, 'comments': comments, 'engagement_rate': er, 'qualifies': not r, 'counted_for_diversity': False, 'reasons': r, 'geography_reason': geo_reason}

def _shipping(c: dict[str, Any]) -> tuple[bool, list[str]]:
    s = c.get('shipping') or {}
    r = []
    if s.get('status') == 'rejected':
        r.append('shipping rejected')
    elif s.get('status') != 'verified':
        r.append('shipping is not verified')
    if not _generic_url(s.get('evidence_url')):
        r.append('shipping evidence URL missing or invalid')
    if not _num(s.get('weight_kg'), positive=True) or s['weight_kg'] > THRESHOLDS['shipping_max_weight_kg']:
        r.append('weight exceeds shipping limit or is invalid')
    if not _num(s.get('longest_side_cm'), positive=True) or s['longest_side_cm'] > THRESHOLDS['shipping_max_longest_side_cm']:
        r.append('longest side exceeds shipping limit or is invalid')
    if s.get('fragile') is not False:
        r.append('fragile must be false')
    if s.get('restricted') is not False:
        r.append('restricted must be false')
    return (not r, r)

def _generic_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and (parsed.username is None) and (parsed.password is None)

def _fresh(value: Any, now: datetime) -> bool:
    d = _dt(value)
    return d is not None and now - timedelta(days=THRESHOLDS['seller_check_fresh_days']) <= d <= now

def evaluate(dataset: dict[str, Any], now: datetime | None=None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    by_product: dict[Any, list[dict[str, Any]]] = {}
    for v in dataset.get('videos', []) if isinstance(dataset.get('videos', []), list) else []:
        if isinstance(v, dict):
            by_product.setdefault(v.get('product_id'), []).append(v)
    (results, international, india) = ([], [], [])
    for c in sorted((x for x in dataset.get('candidates', []) if isinstance(x, dict)), key=lambda x: str(x.get('id', ''))):
        seen: set[str] = set()
        ordered_videos = sorted(by_product.get(c.get('id'), []), key=lambda x: -(_dt(x.get('observed_at')) or datetime.min.replace(tzinfo=timezone.utc)).timestamp())
        ev = [_video_result(v, now, seen) for v in ordered_videos]
        good = [x for x in ev if x['qualifies']]
        creator_seen: dict[tuple[str, str], int] = {}
        diversity = []
        for x in good:
            key = (x['platform'], x['creator_id'])
            n = creator_seen.get(key, 0)
            if n < THRESHOLDS['maximum_videos_per_creator']:
                x['counted_for_diversity'] = True
                diversity.append(x)
            else:
                x['reasons'].append('creator contribution capped at 5')
            creator_seen[key] = n + 1
        pcounts = {p: sum((x['platform'] == p for x in diversity)) for p in PLATFORMS if any((x['platform'] == p for x in diversity))}
        geo = [x for x in diversity if x['country_eligible']]
        ccounts = {co: sum((x['country'] == co for x in geo)) for co in ISO2 if any((x['country'] == co for x in geo))}
        creators = {x['platform'] + ':' + x['creator_id'] for x in diversity}
        qplatforms = {p for (p, n) in pcounts.items() if n >= THRESHOLDS['minimum_videos_per_platform']}
        qcountries = {co for (co, n) in ccounts.items() if n >= THRESHOLDS['minimum_videos_per_country']}
        trend = ([] if len(diversity) >= THRESHOLDS['minimum_unique_videos'] else ['fewer than 50 unique qualifying videos']) + ([] if len(qplatforms) >= THRESHOLDS['minimum_platforms'] else ['fewer than 2 platforms with 5 qualifying videos']) + ([] if len(qcountries) >= THRESHOLDS['minimum_countries'] else ['fewer than 5 countries with 3 qualifying videos']) + ([] if len(creators) >= THRESHOLDS['minimum_creators'] else ['fewer than 10 platform-namespaced creators'])
        (ship_ok, ship_reasons) = _shipping(c)
        intl_reasons = trend + ([] if ship_ok else ship_reasons)
        intl = not intl_reasons
        checks = c.get('seller_checks') or []
        checks_ok = all((any((isinstance(x, dict) and x.get('channel') == ch and (x.get('status') == 'complete') and x.get('query') and _generic_url(x.get('evidence_url')) and _fresh(x.get('checked_at'), now) for x in checks)) for ch in CHANNELS))
        (sellers, unknown, excluded) = ({}, False, False)
        for s in c.get('sellers') or []:
            if not isinstance(s, dict) or not s.get('seller_id'):
                unknown = True
                continue
            if s.get('active') is False or s.get('india_delivery') is False:
                excluded = True
                continue
            if s.get('active') is not True or s.get('india_delivery') is not True:
                unknown = True
                continue
            if s.get('channel') not in CHANNELS or not s.get('name') or (not _generic_url(s.get('url'))) or (not _fresh(s.get('checked_at'), now)):
                unknown = True
                continue
            sellers[s['seller_id']] = s
        hero = c.get('hero') or {}
        hero_ok = all((isinstance(hero.get(k), str) and hero[k].strip() for k in ('problem', 'demonstration', 'differentiation')))
        india_reasons = ([] if intl else ['international qualification missing']) + ([] if checks_ok else ['four fresh channel checks not complete']) + (['seller coverage pending: activity, delivery, URL, name, channel, or freshness unknown'] if unknown else []) + (['five or more deduplicated active India sellers'] if len(sellers) >= 5 else []) + ([] if hero_ok else ['hero fields incomplete'])
        ind = intl and (not india_reasons)
        status = 'qualified' if intl else 'rejected' if 'shipping rejected' in ship_reasons else 'pending'
        estimated = len(sellers) if checks_ok and (not unknown) else None
        stats = {'qualifying_video_count': len(diversity), 'collected_valid_video_count': len(good), 'platform_count': len(qplatforms), 'collected_platform_count': len(pcounts), 'platform_counts': dict(sorted(pcounts.items())), 'qualifying_platforms': sorted(qplatforms), 'country_count': len(qcountries), 'collected_country_count': len(ccounts), 'country_counts': dict(sorted(ccounts.items())), 'qualifying_countries': sorted(qcountries), 'creator_count': len(creators), 'estimated_india_seller_count': estimated, 'observed_confirmed_seller_count': len(sellers), 'seller_coverage': 'unknown' if unknown or not checks_ok else 'estimated'}
        item = {'id': c.get('id'), 'name': c.get('name'), 'status': status, 'international': intl, 'india': ind, 'reasons': sorted(set(intl_reasons + india_reasons)), 'international_reasons': sorted(set(intl_reasons)), 'india_reasons': sorted(set(india_reasons)), 'video_evaluations': ev, 'qualifying_video_ids': [x['id'] for x in diversity], 'stats': stats, 'shipping_reasons': ship_reasons}
        results.append(item)
        if intl:
            international.append(item)
        if ind:
            india.append(item)
    return {'summary': {'candidate_count': len(results), 'international_count': len(international), 'india_count': len(india)}, 'thresholds': THRESHOLDS.copy(), 'collection': dataset.get('collection', {}), 'candidates': results, 'international': international, 'india': india}
