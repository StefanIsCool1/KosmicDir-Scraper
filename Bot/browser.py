"""
Browser automation with Playwright.
Handles: launching browser, capturing responses, human-like scrolling, pagination,
         and detecting detail page links for nested member directories.
         Supports results loaded inside iframes (e.g. YourMembership searchserver).
"""

import random
import re
import time
import threading
import json
import os
from collections import deque
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from config import (
    DEFAULT_IDLE_TIMEOUT, SEARCH_IDLE_TIMEOUT, PAGINATION_IDLE_TIMEOUT,
    NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
    JSON_JUNK_DOMAINS,
    JSON_DIRECTORY_KEYWORDS, JSON_URL_KEYWORDS, JSON_URL_EXCLUDE_PATTERNS,
    JSON_URL_EXCLUDE_TOKENS, JSON_STRUCTURE_FIELDS,
    DIRECTORY_URL_KEYWORDS,
    NEXT_BUTTON_SELECTORS, LOAD_MORE_SELECTORS,
    SCROLL_BATCH_SIZE, SCROLL_STALE_THRESHOLD,
    CATEGORY_SKIP_VISIBLE_THRESHOLD,
    CHILD_HUB_MIN_LINKS,
    INTENT_LOW_RECORDS, INTENT_LOW_VISIBLE,
    INTENT_MAX_SUBPAGES, INTENT_SUBPAGE_DEPTH,
    XHR_MAX_REPLAYS, XHR_MAX_PAGINATION_PAGES,
    XHR_PAGE_PARAMS, XHR_TERM_PARAMS, XHR_LETTER_PARAMS,
    block_unnecessary_resources,
    unblock_resources,
    launch_browser,
    new_stealth_page,
)
from _pw import IS_PATCHRIGHT
from navigator import find_directory_url, trigger_search, count_visible_results, detect_category_links, try_view_all
from intent_filter import filter_categories_by_intent
from debug import debug
from playwright.sync_api import Playwright
from detail_crawler import collect_page_links, detect_detail_links, is_shallow_data, html_has_contact_info, CONTACT_KEYS


# Content keywords that indicate directory-related HTML (used in multiple checks)
_DIRECTORY_CONTENT_KEYWORDS = [
    "member", "directory", "listing", "result", "profile",
    "load more", "company", "contact",
    "doctor", "restaurant", "attorney", "clinic",
]

# Loose US phone pattern — fallback signal that a deliberately visited
# category page holds listing data even when none of the keywords above
# appear in its HTML.
_PHONE_RE = re.compile(r"\(\d{3}\)\s*\d{3}[-.\s]\d{4}|\b\d{3}[-.]\d{3}[-.]\d{4}\b")

# --- IFRAME DETECTION ---

# URL patterns that indicate an iframe contains directory/search results
IFRAME_CONTENT_URL_PATTERNS = [
    "searchserver", "people", "directory", "member",
    "searchresults", "search_results",
    "widget", "feeds", "membee",
    "doctor", "restaurant", "attorney", "clinic",
    "listing",
]

# CSS selectors for known result iframes
IFRAME_SELECTORS = [
    "iframe#SearchResultsFrame",      # YourMembership
    "iframe[id*='search' i]",
    "iframe[id*='result' i]",
    "iframe[id*='directory' i]",
    "iframe[id*='member' i]",
    "iframe[id*='membee' i]",         # Membee widget
    "iframe[src*='searchserver']",
    "iframe[src*='directory']",
    "iframe[src*='member']",
    "iframe[src*='widget']",
    "iframe[src*='feeds']",
]

# Third-party domains that are NEVER directory result frames
THIRD_PARTY_FRAME_DOMAINS = [
    "stripe.com", "js.stripe.com", "m.stripe.network", "m.stripe.com",
    "facebook.com", "connect.facebook.net",
    "google.com", "googleapis.com", "gstatic.com",
    "youtube.com", "twitter.com", "linkedin.com",
    "newrelic.com", "nr-data.net",
    "cloudflare.com", "recaptcha.net",
    "doubleclick.net", "googlesyndication.com",
]


def _is_third_party_frame(frame_url: str) -> bool:
    """Check if a frame URL belongs to a known third-party domain."""
    try:
        frame_domain = urlparse(frame_url).netloc.lower()
        return any(domain in frame_domain for domain in THIRD_PARTY_FRAME_DOMAINS)
    except Exception:
        return False


def _find_member_array(data, max_depth: int = 3) -> bool:
    """Recursively look for a list of member-shape dicts inside an envelope JSON.

    Catches platforms where the directory data is wrapped, which Method 3
    (which only checks data[0] or top-level keys) misses:
      - GraphQL:   {"data": {"members": {"edges": [{"node": {...}}, ...]}}}
      - Drupal:    {"data": [{"attributes": {...}}, ...]}
      - SharePoint:{"d": {"results": [{...}]}}
      - WP custom: {"items": [{"acf": {...}}, ...]}

    Thresholds tuned conservatively so config blobs, i18n bundles, and
    chat-widget agent lists don't trip a false positive:
      - List must have >=3 entries
      - >=2 of the first 5 entries must each have >=3 matching JSON_STRUCTURE_FIELDS keys
      - Handles 1-key wrapper entries by unwrapping one level (node/attributes/fields)

    Bounded: max_depth=3, 20 list items per level, 25 dict values per level.
    Wrapped in try/except by the caller; any exception → no detection.
    """
    if max_depth < 0:
        return False

    if isinstance(data, list):
        if len(data) >= 3:
            matching = 0
            for entry in data[:5]:
                if not isinstance(entry, dict):
                    continue
                keys_lower = {k.lower() for k in entry.keys()}
                if len(keys_lower & set(JSON_STRUCTURE_FIELDS)) >= 3:
                    matching += 1
                    continue
                # Wrapper unwrap: if any nested value is a dict with member-shape
                # keys, treat as a wrapped record. Handles JSON:API ({id, type,
                # attributes:{...}}), Elasticsearch ({_id, _source:{...}}),
                # Salesforce ({Id, fields:{...}}), GraphQL ({node:{...}}), etc.
                for v in entry.values():
                    if isinstance(v, dict):
                        v_keys = {k.lower() for k in v.keys()}
                        if len(v_keys & set(JSON_STRUCTURE_FIELDS)) >= 3:
                            matching += 1
                            break
            if matching >= 2:
                return True
        # Recurse — bounded sample of items
        for item in data[:20]:
            if _find_member_array(item, max_depth - 1):
                return True
    elif isinstance(data, dict):
        # Bounded sample of values — pathological cases (large i18n bundles,
        # config blobs) can have hundreds of keys
        for value in list(data.values())[:25]:
            if _find_member_array(value, max_depth - 1):
                return True
    return False


# --- Method 1 (keyword content match) — tokenize-based to kill substring FPs ---
# The old behavior was `str(data).lower()` + substring check, which had a
# major false-positive class: keyword "user" matched "userip" inside an
# unrelated geo JSON; "doctor" matched inside ad-slot paths like
# "/4020/usn.health/healthcare/doctors/profile/...".
#
# Tokenizer below splits text on non-letter chars AND camelCase transitions,
# so identifiers like memberDirectory / member_directory / Members / "Member
# Directory" all surface "member"/"members" as standalone tokens, while
# "userip" / "memberxyz" surface only as themselves and never match.

_NON_LETTER_RE = re.compile(r'[^A-Za-z]+')
# Splits "memberDirectory" -> ["member", "Directory"] and "XMLParser" -> ["XML", "Parser"]
_CAMEL_BOUNDARY_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _build_keyword_tokens() -> set[str]:
    """Build the set of acceptable lowercase tokens, including simple plurals.

    Plural rules cover the common English cases without a real morphology
    library:
      consonant + y -> ies     (directory -> directories, company -> companies)
      vowel + y    -> +s       (attorney -> attorneys, lawyer N/A — ends in r)
      ends in 's'  -> +es      (business -> businesses)
      otherwise    -> +s       (member -> members, doctor -> doctors)
    """
    vowels = set("aeiou")
    tokens: set[str] = set()
    for kw in JSON_DIRECTORY_KEYWORDS:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        tokens.add(kw_lower)
        if kw_lower.endswith('y') and len(kw_lower) > 1:
            if kw_lower[-2] in vowels:
                tokens.add(kw_lower + 's')           # attorney -> attorneys
            else:
                tokens.add(kw_lower[:-1] + 'ies')    # directory -> directories
        elif kw_lower.endswith('s'):
            tokens.add(kw_lower + 'es')              # business -> businesses
        else:
            tokens.add(kw_lower + 's')               # member -> members
    return tokens


_DIRECTORY_KEYWORD_TOKENS = _build_keyword_tokens()


def _extract_word_tokens(text: str) -> set[str]:
    """Split text into a lowercased token set for whole-word keyword matching.

    Splits on non-letter chars first (paths, punctuation, separators), then
    on camelCase boundaries inside each remaining run. The result is a flat
    set of word-shaped tokens that can be intersected with a keyword set.
    """
    tokens: set[str] = set()
    for part in _NON_LETTER_RE.split(text):
        if not part:
            continue
        for sub in _CAMEL_BOUNDARY_RE.split(part):
            if sub:
                tokens.add(sub.lower())
    return tokens


def _is_directory_json(data, url: str) -> bool:
    """Apply the 4-method directory-data detection to a parsed JSON payload.

    Extracted so both the application/json branch in on_response and the
    JSON-as-text/html fallback in the pending-response loop share the exact
    same gate. Mirrors the previous inline logic 1:1 plus the URL-exclude veto.
    """
    url_lower = url.lower()
    is_directory_data = False

    # Method 1: keyword in tokenized data (whole-word + camelCase aware)
    tokens = _extract_word_tokens(str(data))
    if tokens & _DIRECTORY_KEYWORD_TOKENS:
        is_directory_data = True

    # Method 2: URL contains directory-related patterns
    if not is_directory_data:
        if any(kw in url_lower for kw in JSON_URL_KEYWORDS):
            if not any(excl in url_lower for excl in JSON_URL_EXCLUDE_PATTERNS):
                is_directory_data = True

    # Method 3: JSON structure has member-like fields
    if not is_directory_data:
        sample = data[0] if isinstance(data, list) and data else data
        if isinstance(sample, dict):
            keys_lower = {k.lower() for k in sample.keys()}
            matches = keys_lower & set(JSON_STRUCTURE_FIELDS)
            if len(matches) >= 3:
                is_directory_data = True

    # Method 4: recursive envelope unwrap
    if not is_directory_data and _find_member_array(data):
        is_directory_data = True

    # Final veto: known non-data endpoints even if content matched
    if is_directory_data and any(excl in url_lower for excl in JSON_URL_EXCLUDE_PATTERNS):
        is_directory_data = False

    # Commerce-endpoint veto: cart/checkout ops never hold members, but
    # their payloads trip Method 1 (Walmart's MergeAndGetCart carries a
    # stray "member" token in membership fields). Tokenize the ORIGINAL-
    # case URL so camelCase operation names split (MergeAndGetCart →
    # "cart") — lowercasing first would fuse them into one unmatched token.
    if is_directory_data and (_extract_word_tokens(url) & JSON_URL_EXCLUDE_TOKENS):
        is_directory_data = False

    return is_directory_data


# Name-like keys that mark a JSON list as member records (same set the
# trigger_search member-data check and main.py's is_member_list use).
_MEMBER_NAME_KEYS = {
    "name", "companyname", "company_name", "businessname",
    "organizationname", "title", "nam", "displayname",
    "providername", "practicename", "firmname",
    "restaurantname", "doctorname", "fullname",
    "entityname", "officename", "attorneyname",
}


def _looks_like_member_records(lst) -> bool:
    """True if `lst` is a list of dicts whose entries carry a name-like key.

    Used by the skip-pagination gate: counting EVERY list in captured JSON
    (the old behavior) let a 60-entry i18n bundle or config array suppress
    pagination on a site whose real member data is paginated.
    """
    if not isinstance(lst, list) or len(lst) < 3 or not isinstance(lst[0], dict):
        return False
    keys = {k.lower() for k in lst[0].keys()}
    if keys & _MEMBER_NAME_KEYS:
        return True
    # Airtable shape: {"id": ..., "fields": {"Name": ...}}
    if "fields" in keys and isinstance(lst[0].get("fields"), dict):
        return bool({k.lower() for k in lst[0]["fields"].keys()} & _MEMBER_NAME_KEYS)
    return False


def _count_json_member_records(results: list) -> int:
    """Total member-shaped records across the captured JSON responses.

    Junk that slips capture (Partytown worker proxies, cart/session GraphQL,
    i18n bundles) makes `results` non-empty on many sites, so any gate that
    asks "did we capture data yet?" must count member RECORDS, not responses.
    """
    count = 0
    for r in results:
        data = r.get("data", {})
        if isinstance(data, list) and _looks_like_member_records(data):
            count += len(data)
        elif isinstance(data, dict) and "raw_html" not in data:
            for val in data.values():
                if isinstance(val, list) and _looks_like_member_records(val):
                    count += len(val)
    return count


def _find_enumerable_params(url: str) -> dict:
    """Classify a captured URL's query params into page/term/letter buckets.

    Pure — no network. Drives replay_directory_xhrs: page-like params get
    incremented, term-like params get the intent terms substituted, letter-
    like params iterate a-z0-9. A term-like param whose current value is a
    single character is reclassified as letter-like (starts-with engines).
    """
    out: dict[str, list] = {"page": [], "term": [], "letter": []}
    try:
        parsed = urlparse(url)
    except Exception:
        return out
    if not parsed.query:
        return out
    params = parse_qs(parsed.query, keep_blank_values=True)
    for name, values in params.items():
        lname = name.lower()
        val = (values[0] if values else "").strip()
        if lname in XHR_LETTER_PARAMS or (
                lname in XHR_TERM_PARAMS and len(val) == 1 and val.isalnum()):
            out["letter"].append(name)
        elif lname in XHR_PAGE_PARAMS:
            out["page"].append(name)
        elif lname in XHR_TERM_PARAMS:
            out["term"].append(name)
    return out


def _replace_query_param(url: str, name: str, value) -> str:
    """Return `url` with query param `name` set to `value` (others intact)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[name] = [str(value)]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def _infer_page_size(query_params: dict) -> int:
    """Best-effort page size from a limit/per_page/size-style param, else 20."""
    for k, vals in query_params.items():
        if k.lower() in {"limit", "pagesize", "per_page", "perpage",
                         "size", "count", "rows"}:
            try:
                n = int((vals[0] if vals else "").strip())
                if n > 0:
                    return n
            except (ValueError, IndexError):
                pass
    return 20


def replay_directory_xhrs(page, results, intent) -> int:
    """Re-fetch captured directory-API endpoints with mutated params.

    A site that answered its search over XHR usually exposes page/query/letter
    params we can walk directly — cheaper and more complete than driving the
    UI. Replays go through page.context.request so the browser's cookies and
    anti-bot clearance ride along (curl_cffi carries neither and would 403 on
    exactly these sites). New responses are gated through the SAME
    _is_directory_json used by on_response and appended in the same shape, so
    all downstream counting/dedup/detail logic works unchanged.

    Agent mode only (intent gate lives at the call site AND here). Fail-open:
    any error just returns the records added so far. Returns NEW record count.
    """
    if not intent:
        return 0
    try:
        req = page.context.request
    except Exception:
        return 0

    # Candidate endpoints: URLs already gated by _is_directory_json, GET-shaped
    # with a mutable query string. Dedup, preserve capture order.
    candidates: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for r in results:
        url = r.get("url", "")
        data = r.get("data")
        if not url or url in seen:
            continue
        if not isinstance(data, (list, dict)):
            continue
        if isinstance(data, dict) and "raw_html" in data:
            continue
        params = _find_enumerable_params(url)
        if params["page"] or params["term"] or params["letter"]:
            seen.add(url)
            candidates.append((url, params))

    if not candidates:
        return 0

    # Intent term queries (canonical + up to 3 aliases), deduped.
    canonical = (intent.get("industry_canonical") or "").strip()
    aliases = [(a or "").strip()
               for a in (intent.get("industry_aliases") or []) if (a or "").strip()]
    term_values: list[str] = []
    seen_terms: set[str] = set()
    for t in [canonical] + aliases[:3]:
        if t and t.lower() not in seen_terms:
            term_values.append(t)
            seen_terms.add(t.lower())

    start_records = _count_json_member_records(results)
    counters = {"replays": 0, "consec_fail": 0}

    def _fetch(u: str):
        """GET u through the browser context; return parsed JSON or None."""
        if counters["replays"] >= XHR_MAX_REPLAYS or counters["consec_fail"] >= 3:
            return None
        counters["replays"] += 1
        try:
            resp = req.get(u, timeout=15000)
            if not resp.ok:
                counters["consec_fail"] += 1
                return None
            data = resp.json()
            counters["consec_fail"] = 0
            return data
        except Exception:
            counters["consec_fail"] += 1
            return None
        finally:
            time.sleep(random.uniform(0.1, 0.25))

    def _absorb(u: str, data) -> bool:
        """Gate + append exactly like on_response. True if member data."""
        if data is not None and _is_directory_json(data, u):
            results.append({"url": u, "data": data})
            return True
        return False

    def _stop() -> bool:
        return (counters["replays"] >= XHR_MAX_REPLAYS
                or counters["consec_fail"] >= 3
                or _count_json_member_records(results) >= 300)

    for base_url, params in candidates:
        if _stop():
            break

        # --- Strategy 1: pagination (increment page/offset until dry) ---
        for pname in params["page"]:
            if _stop():
                break
            qp = parse_qs(urlparse(base_url).query, keep_blank_values=True)
            try:
                cur = int((qp.get(pname, ["0"])[0] or "0").strip())
            except ValueError:
                continue
            is_offset = pname.lower() in {"offset", "start", "skip"}
            step = _infer_page_size(qp) if is_offset else 1
            prev_hash = None
            nxt = cur
            for _ in range(XHR_MAX_PAGINATION_PAGES):
                if _stop():
                    break
                nxt += step
                u = _replace_query_param(base_url, pname, nxt)
                before = _count_json_member_records(results)
                data = _fetch(u)
                if data is None:
                    break
                h = hash(json.dumps(data, sort_keys=True, default=str))
                if h == prev_hash:
                    break              # same payload — endpoint clamps, stop
                prev_hash = h
                _absorb(u, data)
                if _count_json_member_records(results) == before:
                    break              # no new members — end of the list

        # --- Strategy 2: intent terms (does the intent live in this API?) ---
        for pname in params["term"]:
            for tv in term_values:
                if _stop():
                    break
                u = _replace_query_param(base_url, pname, tv)
                _absorb(u, _fetch(u))

        # --- Strategy 3: letters (starts-with API mirror of search_all_letters) ---
        for pname in params["letter"]:
            for ch in "abcdefghijklmnopqrstuvwxyz0123456789":
                if _stop():
                    break
                u = _replace_query_param(base_url, pname, ch)
                _absorb(u, _fetch(u))

    added = _count_json_member_records(results) - start_records
    if counters["replays"] > 0:
        print(f"  XHR replay: {counters['replays']} requests, {added} new member records")
        debug.decision("CAPTURE", "xhr replay",
                       f"{counters['replays']} requests, {added} new records",
                       data={"candidates": len(candidates)})
    return added


def discover_intent_subpages(page, intent, results, link_collector,
                             html_collector) -> bool:
    """BFS-crawl intent-matched category / sub-directory links.

    The normal category iteration only runs in the no-search fallback; when a
    search fired weakly or a few records trickled in, the intent-relevant
    sub-pages are never explored. This finds LOTS of them: it seeds from the
    landing page's intent-matched children (relaxed detect_category_links +
    strict-subset filter_categories_by_intent), then walks each sub-page
    through the SAME collect-links / capture-HTML / paginate recipe the
    category loop uses, and re-detects deeper children as it goes.

    JSON XHRs the navigations fire are captured by the live on_response
    listener into `results` — nothing extra needed for network data.

    Agent mode only (caller AND this fn gate on intent). Same-origin, depth-
    and count-capped, fail-open. Returns True if it visited any sub-page.
    """
    if not intent:
        return False
    try:
        origin = urlparse(page.url).netloc.lower()
    except Exception:
        return False

    aliases = {(a or "").lower() for a in intent.get("industry_aliases", []) if a}
    canon = (intent.get("industry_canonical") or "").lower()
    if canon:
        aliases.add(canon)

    def _norm(u: str) -> str:
        try:
            return urlparse(u)._replace(fragment="").geturl().rstrip("/")
        except Exception:
            return u

    def _same_origin(u: str) -> bool:
        try:
            return urlparse(u).netloc.lower() == origin
        except Exception:
            return False

    def _substring_pick(cands: list) -> list:
        return [c for c in cands
                if any(a and a in (c.get("text") or "").lower() for a in aliases)]

    llm_budget = {"n": 3}   # hard cap on LLM-backed picks per domain

    def _pick(cands: list, examine_depth: int) -> list:
        """Intent-narrow candidate children. filter_categories_by_intent
        falls OPEN (returns the same full list) when there's no intent signal,
        so only a STRICT subset counts as a real match. The LLM layer is
        allowed at shallow depths within budget; deeper/over-budget picks use
        substring only to keep AI cost near one call per domain."""
        if not cands:
            return []
        if examine_depth <= 1 and llm_budget["n"] > 0:
            llm_budget["n"] -= 1
            picked = filter_categories_by_intent(cands, intent)
            if 0 < len(picked) < len(cands):
                return picked
            # fell open (no intent signal) — fall through to substring backstop
        return _substring_pick(cands)

    # Seed sub-pages: reuse a cached pick for this domain+industry if we have
    # one (skips the landing detect + LLM), else compute and cache it.
    from cache import get_cached_intent_subpages, set_cached_intent_subpages
    cached = get_cached_intent_subpages(origin, canon)
    if cached:
        seed = [{"text": "", "href": h} for h in cached if _same_origin(h)]
        print(f"  Intent sub-page crawl: using {len(seed)} cached seed links")
    else:
        seed = _pick(detect_category_links(page, ignore_visible=True, top_groups=3), 0)
        seed = [c for c in seed if _same_origin(c["href"])]
        if seed:
            set_cached_intent_subpages(origin, canon, [c["href"] for c in seed])
    if not seed:
        return False

    visited = {_norm(page.url)}
    queue: deque = deque()
    for c in seed:
        n = _norm(c["href"])
        if n not in visited:
            visited.add(n)
            queue.append((c["href"], 1))

    print(f"  Intent sub-page crawl: {len(queue)} seed links matched intent")
    visited_count = 0

    while queue:
        if visited_count >= INTENT_MAX_SUBPAGES:
            break
        if _count_json_member_records(results) >= 50 or len(html_collector) >= 40:
            debug.decision("EXPAND", "intent sub-pages: early stop",
                           f"visited {visited_count}, "
                           f"{_count_json_member_records(results)} records, "
                           f"{len(html_collector)} html pages")
            break

        href, depth = queue.popleft()
        try:
            page.goto(href, timeout=15000)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass
            page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
            visited_count += 1
            print(f"  Sub-page {visited_count}/{INTENT_MAX_SUBPAGES} (d{depth}): {href[:100]}")

            link_collector.extend(collect_page_links(page))

            try:
                html = page.content()
                if (any(kw in html.lower() for kw in _DIRECTORY_CONTENT_KEYWORDS)
                        or _PHONE_RE.search(html)):
                    html_collector.append(html)
            except Exception:
                pass

            handle_pagination(page, threading.Event(),
                              link_collector=link_collector,
                              html_collector=html_collector)

            # Go deeper: re-detect intent-matched children of THIS sub-page.
            if depth < INTENT_SUBPAGE_DEPTH:
                children = _pick(
                    detect_category_links(page, ignore_visible=True, top_groups=3),
                    depth)
                for c in children:
                    n = _norm(c["href"])
                    if n not in visited and _same_origin(c["href"]):
                        visited.add(n)
                        queue.append((c["href"], depth + 1))
        except Exception as e:
            print(f"  Error on sub-page '{href[:80]}': {e}")
            continue

    if visited_count:
        debug.decision("EXPAND", "intent sub-pages crawled",
                       f"visited {visited_count} pages",
                       data={"records": _count_json_member_records(results),
                             "html_pages": len(html_collector)})
    return visited_count > 0


def find_content_frame(page):
    """Detect if search results are loaded inside an iframe.

    Checks for known iframe patterns (YourMembership's SearchResultsFrame, etc.).
    If found, returns the Playwright Frame object for that iframe.
    If no iframe is found, returns None.

    Retries up to 3 times with waits ONLY if there are promising non-junk frames
    that might still be loading (e.g. membee widgets).
    """
    JUNK_FRAME_PATTERNS = [
        "about:blank", "recaptcha", "google.com/recaptcha", "doubleclick",
        "maps.google", "maps.googleapis", "analytics", "gtag",
    ]

    def _has_promising_frames():
        """Check if any non-main frames exist that aren't known junk."""
        for f in page.frames:
            if f == page.main_frame:
                continue
            url = f.url.lower()
            if any(junk in url for junk in JUNK_FRAME_PATTERNS):
                continue
            if _is_third_party_frame(f.url):
                continue
            # This frame has a real URL — might be a content iframe loading
            return True
        return False

    for attempt in range(3):
        if attempt > 0:
            # Only retry if there are promising frames that might still be loading
            if not _has_promising_frames():
                break
            print(f"  Iframe detection: retry {attempt + 1}/3...")
            page.wait_for_timeout(3000)

        # Method 1: Check known iframe selectors in the main page
        for selector in IFRAME_SELECTORS:
            try:
                iframe_el = page.locator(selector).first
                if iframe_el.is_visible(timeout=2000):
                    frame = iframe_el.content_frame()
                    if frame:
                        # Skip third-party iframes
                        if _is_third_party_frame(frame.url):
                            continue
                        try:
                            frame_html = frame.content()
                            if any(kw in frame_html.lower() for kw in
                                   _DIRECTORY_CONTENT_KEYWORDS):
                                print(f"  Found results iframe: {selector}")
                                return frame
                        except Exception:
                            pass
            except Exception:
                continue

        # Method 2: Scan all frames by URL pattern
        # Match against the iframe's path only — not the full URL with fragments/params.
        # This prevents false matches where the site's own URL (containing "directory"
        # or "member") is embedded in a third-party iframe's hash/query params.
        for frame in page.frames:
            if frame == page.main_frame:
                continue

            # Skip third-party iframes
            if _is_third_party_frame(frame.url):
                continue

            frame_path = urlparse(frame.url).path.lower()
            if any(pattern in frame_path for pattern in IFRAME_CONTENT_URL_PATTERNS):
                try:
                    frame_html = frame.content()
                    if any(kw in frame_html.lower() for kw in
                           ["member", "directory", "listing", "result",
                            "profile", "load more", "company"]):
                        print(f"  Found results iframe by URL: {frame.url[:100]}")
                        return frame
                except Exception:
                    continue

    return None


def human_scroll(page, done_event, scroll_target="body", times=20, adaptive=False):
    """Simulate human-like scrolling to trigger lazy-loaded content.
    Stops early if done_event is set (e.g. idle timer fired).

    When adaptive=True, scrolls in batches and checks if new content loaded
    after each batch. Stops when page height and visible result count stop
    growing (handles infinite scroll pages).
    """
    if adaptive:
        stale_batches = 0
        max_batches = max(times // SCROLL_BATCH_SIZE, 4)

        for batch in range(max_batches):
            if done_event.is_set():
                break

            # Measure before scrolling
            try:
                prev_height = page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollHeight"
                )
            except Exception:
                prev_height = 0
            prev_count = count_visible_results(page)

            # Scroll a batch
            for _ in range(SCROLL_BATCH_SIZE):
                if done_event.is_set():
                    break
                distance = random.randint(300, 600)
                page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollBy(0, {distance});"
                )
                page.mouse.wheel(0, distance)
                time.sleep(random.uniform(0.15, 0.5))

            # Wait for lazy content to load
            page.wait_for_timeout(1500)

            # Measure after
            try:
                new_height = page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollHeight"
                )
            except Exception:
                new_height = prev_height
            new_count = count_visible_results(page)

            if new_height <= prev_height and new_count <= prev_count:
                stale_batches += 1
                if stale_batches >= SCROLL_STALE_THRESHOLD:
                    print(f"  Scroll: no new content after {batch + 1} batches "
                          f"({new_count} results), stopping")
                    break
            else:
                stale_batches = 0
                if new_count > prev_count:
                    print(f"  Scroll: {new_count} results (+{new_count - prev_count})")
    else:
        # Original fixed-count scrolling
        for _ in range(times):
            if done_event.is_set():
                break
            distance = random.randint(300, 600)
            page.evaluate(f"document.querySelector('{scroll_target}').scrollBy(0, {distance});")
            page.mouse.wheel(0, distance)
            time.sleep(random.uniform(0.15, 1))

    # Try site-specific scroll container (some sites use custom scrollable divs)
    try:
        container = page.get_by_test_id("scrolling-container")
        container.hover()
        page.mouse.wheel(0, 300)
    except:
        pass


def handle_pagination(page, done_event, link_collector=None, html_collector=None):
    """Click through pagination to capture all pages.

    Handles two types of pagination:
    1. Simple Next/→ buttons — clicks Next repeatedly
    2. Numbered page groups (e.g. [1] 2 3 ... 10 →) — clicks each number
       sequentially, then → to load next group, then continues numbering.

    Args:
        page: Playwright page or Frame object
        done_event: Threading event that signals when to stop
        link_collector: Optional list to accumulate page links into.
        html_collector: Optional list to capture page HTML after each pagination click.

    Returns the number of extra pages loaded.
    """
    pages_loaded = 0
    max_pages = 50
    current_page_num = 1
    stale_clicks = 0  # how many times "next" didn't change the page

    # Record the starting URL path to detect accidental navigation away
    # (e.g. clicking a member detail link instead of a pagination button).
    from urllib.parse import urlparse
    try:
        start_url = page.url
        start_path = urlparse(start_url).path.rstrip("/")
    except Exception:
        start_url = ""
        start_path = ""

    def _navigated_away() -> bool:
        """Check if a pagination click accidentally navigated to a different page.
        If so, go back and return True to stop pagination.

        Uses the parent directory of the start path to allow minor path changes
        from searching (e.g. /directory → /directory/search) while catching
        navigation to a completely different section (e.g. /directory/Find → /directory/Details/...).
        """
        if not start_path:
            return False
        try:
            current_url = page.url
            current_path = urlparse(current_url).path.rstrip("/")
            # Exact same path → definitely still on the listing page
            if current_path == start_path:
                return False
            # Allow paths that share the same parent directory as the start.
            # e.g. start=/member-directory/Find → parent=/member-directory
            #   /member-directory/Find?page=2 → path=/member-directory/Find → OK (same)
            #   /member-directory/search → OK (same parent)
            #   /member-directory/Details/company-123 → NOT OK (deeper than parent)
            start_parent = start_path.rsplit("/", 1)[0] if "/" in start_path else start_path

            # Single-segment paths (e.g. /Minnesota) yield empty start_parent,
            # which matches everything. Anchor on start_path itself instead:
            # allow /Minnesota → /Minnesota/page-2.html, still block
            # /Minnesota → /OtherSection.
            if not start_parent:
                if current_path.startswith(start_path + "/"):
                    return False
            elif current_path.startswith(start_parent):
                # Count path segments after the parent
                remainder = current_path[len(start_parent):].strip("/")
                depth = len(remainder.split("/")) if remainder else 0
                # Allow up to 1 extra segment (e.g. /directory → /directory/search)
                # Block 2+ extra segments (e.g. /directory/Details/company-name)
                if depth <= 1:
                    return False
            # Different section entirely, or too deep → navigated away
            print(f"  Pagination: navigated away from listing ({start_path} → {current_path}), going back")
            try:
                page.go_back()
                page.wait_for_load_state("domcontentloaded", timeout=NETWORK_IDLE_TIMEOUT)
                page.wait_for_timeout(1000)
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _collect_links():
        if link_collector is None:
            return
        links = collect_page_links(page)
        link_collector.extend(links)

    def _wait_for_page():
        try:
            page.wait_for_load_state("domcontentloaded", timeout=NETWORK_IDLE_TIMEOUT)
        except:
            pass
        page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)

    def _capture_html():
        """Capture current page HTML into the html_collector."""
        if html_collector is None:
            return
        try:
            html_collector.append(page.content())
        except Exception:
            pass

    def _find_page_button(target_num: int):
        """Find a visible button or link with exact page number text."""
        target = str(target_num)
        for tag in ["button", "a"]:
            try:
                for btn in page.locator(f"{tag}:has-text('{target}')").all():
                    try:
                        if not btn.is_visible(timeout=500):
                            continue
                        if btn.inner_text().strip() == target:
                            cls = (btn.get_attribute("class") or "").lower()
                            if "primary" not in cls and "active" not in cls:
                                return btn
                    except:
                        continue
            except:
                continue
        return None

    def _read_active_page_num() -> int:
        """Read current page number from the active pagination button."""
        for sel in ["button.btn-primary", "[class*='active']", "li.active a"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    txt = el.inner_text().strip()
                    if txt.isdigit():
                        return int(txt)
            except:
                continue
        return current_page_num

    def _content_snapshot() -> str:
        """Length + tail-hash of body text. The tail (not the head) is where
        paginated results actually change — the first 2000 chars are usually
        static header/nav, which made SPA pagination (results swap, no URL
        change) look 'unchanged' and stop after one page."""
        try:
            text = page.inner_text("body")
            return f"{len(text)}:{hash(text[-2000:])}"
        except:
            return ""

    last_content_hash = _content_snapshot()

    while not done_event.is_set() and pages_loaded < max_pages:
        found_next = False
        next_num = current_page_num + 1

        # --- Strategy 1: Click next numbered page button ---
        try:
            num_btn = _find_page_button(next_num)
            if num_btn:
                before_hash = _content_snapshot()
                before_url = page.url
                num_btn.click()
                _wait_for_page()
                if _navigated_away():
                    break
                if page.url == before_url and _content_snapshot() == before_hash:
                    print(f"  Pagination: page {next_num} — URL and content unchanged, stopping")
                    break
                elif _content_snapshot() == before_hash:
                    stale_clicks += 1
                    if stale_clicks >= 2:
                        print(f"  Pagination: content unchanged, stopping")
                        break
                else:
                    stale_clicks = 0
                pages_loaded += 1
                current_page_num = next_num
                print(f"  Pagination: page {current_page_num}")
                _collect_links()
                _capture_html()
                found_next = True
        except:
            pass

        if found_next:
            continue

        # --- Strategy 2: Click → / Next to advance page group ---
        try:
            next_btn = page.locator(NEXT_BUTTON_SELECTORS).first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                cls = (next_btn.get_attribute("class") or "").lower()
                if "disabled" not in cls and "active" not in cls:
                    before_hash = _content_snapshot()
                    before_url = page.url
                    next_btn.click()
                    _wait_for_page()
                    if _navigated_away():
                        break
                    # Check if page actually changed (URL or content)
                    after_url = page.url
                    after_hash = _content_snapshot()
                    if after_url == before_url and after_hash == before_hash:
                        stale_clicks += 1
                        if stale_clicks >= 1:
                            print(f"  Pagination: URL and content unchanged after click, stopping (last page)")
                            break
                    elif after_hash == before_hash:
                        stale_clicks += 1
                        if stale_clicks >= 2:
                            print(f"  Pagination: content unchanged, stopping")
                            break
                    else:
                        stale_clicks = 0
                    pages_loaded += 1
                    detected_num = _read_active_page_num()
                    if detected_num > current_page_num:
                        current_page_num = detected_num
                    else:
                        current_page_num += 1
                    print(f"  Pagination: next/arrow → page {current_page_num}")
                    _collect_links()
                    _capture_html()
                    found_next = True
        except:
            pass

        if found_next:
            continue

        # --- Strategy 3: Load More button ---
        # Check if Load More exists in the DOM first, THEN scroll to it.
        try:
            all_load_more = page.locator(LOAD_MORE_SELECTORS)
            lm_count = all_load_more.count()
            if lm_count > 0:
                print(f"  Load More: found {lm_count} element(s), clicking...")
                load_more = all_load_more.first
                try:
                    load_more.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    load_more.click()
                except:
                    # Fallback: force click even if not "actionable"
                    load_more.click(force=True)
                page.wait_for_timeout(2000)
                if _navigated_away():
                    break
                pages_loaded += 1
                current_page_num += 1
                print(f"  Load More: click #{pages_loaded}")
                _collect_links()
                found_next = True
        except:
            pass

        if found_next:
            continue

        break

    if pages_loaded > 0:
        print(f"  Pagination complete: {pages_loaded} pages loaded (reached page {current_page_num})")
    return pages_loaded


# --- LOGIN WALL DETECTION & COOKIE MANAGEMENT ---

_LOGIN_SIGNALS = [
    "sign in", "log in", "login", "username",
    "members only", "member login", "member sign in",
    "forgot password", "forgot your password",
    "click here for login", "portal login",
]

# Directory where per-domain cookies are persisted
_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cookies")


def _is_login_page(page) -> bool:
    """Check if the current page is a login/authentication wall.

    Requires password field + 2+ login-related phrases in the HTML.
    Low false-positive rate — sites with public directories that also have
    a login link in the nav won't trigger this.
    """
    try:
        html = page.content().lower()
    except Exception:
        return False

    has_password = 'type="password"' in html or "type='password'" in html
    if not has_password:
        return False

    signals = sum(1 for phrase in _LOGIN_SIGNALS if phrase in html)
    return signals >= 2


def _load_cookies(page, domain: str) -> bool:
    """Load saved cookies for a domain into the browser context.

    Returns True if cookies were loaded, False if no cookie file exists.
    """
    cookie_file = os.path.join(_COOKIE_DIR, f"{domain}.json")
    if not os.path.exists(cookie_file):
        return False
    try:
        with open(cookie_file, "r") as f:
            cookies = json.load(f)
        page.context.add_cookies(cookies)
        print(f"  Loaded {len(cookies)} cookies for {domain}")
        return True
    except Exception as e:
        print(f"  Failed to load cookies for {domain}: {e}")
        return False


def _save_cookies(page, domain: str):
    """Save current browser cookies to disk for reuse on future scrapes."""
    os.makedirs(_COOKIE_DIR, exist_ok=True)
    cookie_file = os.path.join(_COOKIE_DIR, f"{domain}.json")
    try:
        cookies = page.context.cookies()
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"  Saved {len(cookies)} cookies for {domain}")
    except Exception as e:
        print(f"  Failed to save cookies for {domain}: {e}")


# --- CAPTCHA / ANTI-BOT CHALLENGE DETECTION & HUMAN HANDOFF ---

# Unmistakable challenge copy — any one of these in the page text means the
# WHOLE page is a "prove you're human" wall (not real content).
_CAPTCHA_TEXT_SIGNALS = [
    "activate and hold",                      # DataDome press-and-hold
    "press and hold",
    "hold the button",
    "verify you are human",
    "verify you are a human",
    "please verify you are a human",
    "are you a robot",
    "robot or human",
    "checking your browser before",           # Cloudflare interstitial
    "just a moment",                          # Cloudflare <title>/body
    "please enable javascript and cookies",   # DataDome
    "complete the security check",
    "additional verification required",
    "unusual traffic from your",              # Google soft-block
]

# Very specific phrases that fire regardless of page size (a genuine challenge
# wall even when the surrounding markup happens to be large).
_CAPTCHA_STRONG_TEXT = {
    "activate and hold", "press and hold", "hold the button",
    "just a moment", "please enable javascript and cookies",
    "checking your browser before",
}

# Challenge-only hosts. These load an iframe/script ONLY when a real challenge
# is on screen, so their presence in the DOM is a strong signal. (reCAPTCHA
# uses api2/bframe — the popped-open challenge — not the ever-present invisible
# badge, to avoid pausing on a contact form that merely embeds reCAPTCHA.)
_CAPTCHA_HOST_SIGNALS = {
    "captcha-delivery.com": "DataDome",
    "challenges.cloudflare.com": "Cloudflare Turnstile",
    "hcaptcha.com": "hCaptcha",
    "recaptcha/api2/bframe": "reCAPTCHA challenge",
}

# Page <title> substrings that mark a block/challenge page.
_CAPTCHA_TITLE_SIGNALS = [
    "just a moment", "attention required", "access denied",
    "security check", "are you human", "robot or human",
]

_CAPTCHA_MAX_ATTEMPTS = 3


def detect_captcha(page) -> str | None:
    """Return the anti-bot vendor name if the CURRENT page is a challenge/block
    wall, else None. Conservative by design — a false positive would needlessly
    pause a scrape that could have continued."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    for sig in _CAPTCHA_TITLE_SIGNALS:
        if sig in title:
            return "anti-bot challenge"

    try:
        html = page.content().lower()
    except Exception:
        return None

    # Strong: a known challenge host embedded in the page (iframe/script src).
    for host, vendor in _CAPTCHA_HOST_SIGNALS.items():
        if host in html:
            return vendor

    # Unmistakable, specific challenge copy — fire at any page size.
    hits = {s for s in _CAPTCHA_TEXT_SIGNALS if s in html}
    if hits & _CAPTCHA_STRONG_TEXT:
        return "anti-bot challenge"
    # Generic copy ("robot or human", "are you a robot") — only trust it on a
    # tiny page. A real interstitial is small; a full content page that merely
    # mentions the phrase in prose or a FAQ is not a challenge.
    if hits and len(html) < 15000:
        return "anti-bot challenge"
    return None


def handle_captcha(page, domain: str, captcha_callback) -> bool:
    """If the current page is an anti-bot challenge, pause for a human to solve
    it in the (headed) browser window, then verify it cleared before resuming.

    captcha_callback(page, domain, vendor) -> bool
        Returns True after the human reports they've solved it (we re-check and
        loop if it's still up), or False to give up on this site. If None
        (unattended run), we log and bail — nobody is there to solve it.

    Returns True if the page is clear (no challenge, or solved), False if a
    challenge remains / was skipped. Idempotent: no-op fast path when clear."""
    vendor = detect_captcha(page)
    if not vendor:
        return True

    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║  CAPTCHA / ANTI-BOT CHALLENGE DETECTED        ║")
    print(f"  ║  Vendor: {vendor[:35]:<35} ║")
    print(f"  ║  A human must solve it in the browser window. ║")
    print(f"  ╚══════════════════════════════════════════════╝")
    debug.log("CAPTCHA", f"Challenge on {domain}: {vendor}", level="warn")

    if captcha_callback is None:
        print(f"  No captcha_callback (unattended run) — cannot solve, skipping site.")
        return False

    # Let the human actually SEE and interact with the challenge: drop the
    # image/font block so image-based challenges render, and focus the window.
    unblock_resources(page)
    try:
        page.bring_to_front()
    except Exception:
        pass

    for attempt in range(1, _CAPTCHA_MAX_ATTEMPTS + 1):
        cont = captcha_callback(page, domain, vendor)
        if not cont:
            print(f"  CAPTCHA solve skipped by user — scrape may return 0 results.")
            block_unnecessary_resources(page)  # restore blocking for the rest of the run
            return False
        # A successful solve makes DataDome/Cloudflare RELOAD the page to the
        # real content — checking too early sees the challenge still mid-reload
        # and false-reports failure. Wait for the reload to settle first.
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        if not detect_captcha(page):
            print(f"  CAPTCHA cleared — resuming scrape on {page.url}")
            debug.log("CAPTCHA", f"Challenge cleared on {domain}")
            # Persist the vendor's clearance cookie so future runs on this
            # domain aren't re-challenged from scratch (loaded by _load_cookies
            # at the start of capture_responses).
            try:
                _save_cookies(page, domain)
            except Exception:
                pass
            block_unnecessary_resources(page)
            return True
        remaining = _CAPTCHA_MAX_ATTEMPTS - attempt
        if remaining > 0:
            print(f"  Challenge still present. {remaining} attempt(s) left — finish "
                  f"solving in the browser window, then respond again.")

    print(f"  CAPTCHA still present after {_CAPTCHA_MAX_ATTEMPTS} attempts — giving up on this site.")
    block_unnecessary_resources(page)
    return False


def _page_actually_loaded(page) -> bool:
    """True when the page is showing real site content. A failed navigation
    leaves the page on about:blank OR commits Chromium's own error UI
    (chrome-error://chromewebdata/ — how DNS/connection failures surface on
    the real-Chrome channel instead of raising)."""
    url = page.url or ""
    return bool(url) and not url.startswith(("about:", "chrome-error://"))


def _navigate_with_fallback(page, link: str) -> str | None:
    """Load the target URL. Returns the URL that actually loaded, else None.

    goto() raises both on hard failures (DNS, refused connection, SSL) and on
    slow loads that blow the nav timeout — only a page still showing no real
    content afterwards counts as a failure. app.py guesses "https://" onto
    bare domains, and plenty of small-org directory sites never got TLS, so
    an https failure retries the http:// variant once before giving up.

    Chromium quirk this has to survive: a failed navigation parks the page on
    chrome-error://chromewebdata/ ASYNCHRONOUSLY, up to a few seconds after
    goto() raised. The settle-poll below (a) catches slow navigations that
    commit after goto's timeout raise, and (b) absorbs that pending error-page
    commit so it can't interrupt the next candidate's navigation. If a stale
    commit still lands mid-navigation, Playwright raises "...interrupted by
    another navigation" — retried once from the now-settled page.
    """
    candidates = [link]
    if link.startswith("https://"):
        candidates.append("http://" + link[len("https://"):])

    for i, candidate in enumerate(candidates):
        for attempt in (1, 2):
            nav_error = None
            try:
                # First candidate keeps Playwright's default nav timeout (slow
                # but real directories); the http retry gets a shorter leash.
                page.goto(candidate, **({} if i == 0 else {"timeout": 15000}))
            except Exception as e:
                nav_error = e
                debug.log("BROWSER", f"goto failed for {candidate}: {e}", level="warn")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass

            loaded = _page_actually_loaded(page)
            if not loaded:
                for _ in range(6):  # settle poll (~3s)
                    page.wait_for_timeout(500)
                    if _page_actually_loaded(page):
                        loaded = True
                        break
            if loaded:
                if candidate != link:
                    print(f"  https failed — loaded via http fallback: {candidate}")
                    debug.decision("BROWSER", "http fallback",
                                   f"https did not load; {candidate} did")
                return candidate

            if (attempt == 1 and nav_error
                    and "interrupted by another" in str(nav_error).lower()):
                print(f"  Navigation to {candidate} was interrupted — retrying once")
                continue
            break

        if i + 1 < len(candidates):
            print(f"  {candidate} did not load — retrying over plain http")
    return None


def capture_responses(playwright: Playwright, link: str, mode: str = "auto",
                      priority_fields: list | None = None,
                      login_callback=None,
                      captcha_callback=None,
                      intent: dict | None = None,
                      is_aggregator: bool = False) -> tuple[list, list]:
    """Main browser automation entry point.

    Launches browser, navigates to directory page, captures all responses.

    mode: "auto" = find directory page + search (default)
          "direct" = skip navigation/search, scrape the page as-is

    login_callback: Optional callable(page, domain) -> bool.
        Called when a login wall is detected. The callback should pause
        and let the user log in manually, then return True to retry or
        False to skip. If None and a login wall is hit, the scrape fails.

    captcha_callback: Optional callable(page, domain, vendor) -> bool.
        Called when an anti-bot challenge (DataDome press-and-hold,
        Cloudflare, hCaptcha, reCAPTCHA) is detected. The callback should
        pause and let the user solve it in the headed browser window, then
        return True to re-check/resume or False to skip. If None, the
        challenge is logged and the scrape continues (likely empty).

    intent: Optional dict from intent_filter.intent_from_plan. When set
        (Agent mode), used to (a) hint the AI navigator toward intent-
        relevant sub-directory links and (b) narrow detected category
        lists before iteration. Playground callers pass None and every
        downstream consumer falls back to existing behavior.

    is_aggregator: True when Phase 0's classifier identified `link` as a
        cross-vertical business aggregator (AGGREGATOR_DOMAINS in
        DiscoveryBot/classifier.py). Forwarded to trigger_search so the
        search box gets the user's intent term instead of a wildcard that
        would pull every industry. Defaults to False — Playground callers
        and any non-aggregator URL behave exactly as before.

    Returns:
        Tuple of (results, detail_urls):
        - results: list of dicts [{"url": str, "data": dict}, ...]
        - detail_urls: list of member detail page URLs (may be empty)
    """
    results = []
    detail_urls = []
    all_page_links = []  # accumulated across all paginated pages
    all_page_htmls = []  # accumulated HTML from each page/category
    done = threading.Event()
    idle_timer = None
    idle_timeout_value = DEFAULT_IDLE_TIMEOUT
    pending_html_responses = []
    timer_enabled = False  # Don't start idle timer until after search/scroll phase

    domain = urlparse(link).netloc.replace(".", "_")

    browser = launch_browser(playwright)
    page = new_stealth_page(browser)

    # Apply the playwright-stealth JS patches — but ONLY on stock Playwright.
    # patchright already applies its own, more careful patches (and closes the
    # Runtime.enable CDP leak the stealth plugin can't touch); stacking the
    # plugin on top re-introduces detectable modifications.
    if not IS_PATCHRIGHT:
        try:
            from playwright_stealth import Stealth
            Stealth(
                webgl_vendor=True,
                webgl_renderer_override="Intel Iris OpenGL Engine",
                webgl_vendor_override="Intel Inc.",
                navigator_hardware_concurrency=True,
                sec_ch_ua=True,
            ).apply_stealth_sync(page)
        except ImportError:
            pass

    # Block images, fonts, media, analytics — bot only needs JSON + HTML
    block_unnecessary_resources(page)

    # --- Load saved cookies for this domain (if any) ---
    had_cookies = _load_cookies(page, domain)

    def reset_idle_timer():
        """Reset the idle timer. Called each time a relevant response arrives.
        Only actually starts the timer if timer_enabled is True.
        This prevents the idle timer from firing during trigger_search,
        which navigates through multiple pages and takes longer than the timeout."""
        nonlocal idle_timer
        if not timer_enabled:
            return
        if idle_timer:
            idle_timer.cancel()
        idle_timer = threading.Timer(idle_timeout_value, done.set)
        idle_timer.start()

    def on_response(response):
        """Listener for all network responses. Captures JSON and queues HTML."""
        # Skip known third-party domains that never contain member data
        resp_domain = urlparse(response.url).netloc.lower()
        if any(junk in resp_domain for junk in JSON_JUNK_DOMAINS):
            return

        content_type = response.headers.get("content-type", "")
        print(f"RESPONSE: [{content_type}] {response.url}")
        debug.log("CAPTURE", f"Response: [{content_type[:30]}] {response.url[:120]}")

        # --- JSON responses ---
        if "application/json" in content_type:
            try:
                data = response.json()
                if _is_directory_json(data, response.url):
                    print("Likely directory data at:", response.url)
                    results.append({
                        "url": response.url,
                        "data": data
                    })
                    reset_idle_timer()
            except Exception:
                pass

        # --- HTML/text responses (queued for later reading) ---
        elif "text/plain" in content_type or "text/html" in content_type:
            url_lower = response.url.lower()
            if any(kw in url_lower for kw in DIRECTORY_URL_KEYWORDS):
                # Directory-shaped URL — read the body NOW. Playwright drops
                # response bodies on navigation, and pagination navigates up
                # to 50 times; reading at the end lost the ASP.NET
                # UpdatePanel payloads this queue exists for.
                try:
                    text = response.body().decode("utf-8", errors="ignore")
                    pending_html_responses.append(
                        {"url": response.url, "text": text})
                except Exception:
                    pending_html_responses.append(
                        {"url": response.url, "response": response})
                reset_idle_timer()
            else:
                # Non-keyword URLs are rarely read later — keep them lazy to
                # avoid buffering every page document.
                pending_html_responses.append(
                    {"url": response.url, "response": response})

    page.on("response", on_response)

    # --- Step 0: Initial navigation + anti-bot challenge gate ---
    # Load the target FIRST so a DataDome/Cloudflare "prove you're human" wall
    # can be cleared by a human before the navigation/search logic runs against
    # it — running find_directory_url on a challenge page yields garbage. Once
    # solved, the vendor's clearance cookie rides the browser context, so later
    # navigations in this run are usually not re-challenged.
    loaded_link = _navigate_with_fallback(page, link)
    if loaded_link is None:
        print(f"  NAVIGATION FAILED: {link} did not load (dead domain, refused "
              f"connection, or not a web page) — aborting this scrape")
        debug.log("BROWSER", f"Navigation failed, aborting: {link}", level="error")
        browser.close()
        return results, detail_urls
    link = loaded_link  # http fallback may have downgraded the scheme
    handle_captcha(page, domain, captcha_callback)

    # --- Step 1: Find and navigate to directory page ---
    if mode == "direct":
        # Direct mode: user already picked the page — it's loaded above.
        print(f"  Direct mode: using loaded page {link}")
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except Exception:
            pass
        directory_url = link
        search_triggered = False
        debug.log("NAV", f"Direct mode — skipping navigation and search")
    else:
        directory_url = find_directory_url(page, link, intent=intent)
        debug.log("NAV", f"Directory URL resolved: {directory_url}")
        if page.url.rstrip("/") != directory_url.rstrip("/"):
            page.goto(directory_url)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass
            # A deeper page can trip its own challenge (rare once cleared above).
            handle_captcha(page, domain, captcha_callback)

    # --- Login gate: detect and handle authentication walls ---
    # Runs after initial navigation in BOTH modes. If cookies were loaded
    # but are stale, the page will still show a login wall.
    if _is_login_page(page):
        if login_callback is None:
            print(f"  LOGIN WALL DETECTED — no login_callback provided, "
                  f"scrape will likely return 0 results")
        else:
            print(f"\n  ╔══════════════════════════════════════════╗")
            print(f"  ║  LOGIN WALL DETECTED                    ║")
            print(f"  ║  This directory requires authentication. ║")
            print(f"  ╚══════════════════════════════════════════╝")
            # Up to MAX_LOGIN_ATTEMPTS rounds of prompt-then-verify.
            # If the user presses Enter prematurely (before actually logging
            # in), the post-navigation _is_login_page check catches it and
            # we re-prompt instead of saving useless cookies.
            #
            # First attempt: goto directory_url after login_callback
            #   returns. Handles the common case where the site
            #   auto-redirected to a dashboard after login.
            # Retry attempt: skip the goto and verify whatever page the
            #   user is on. After being told "verification failed", the
            #   user may have manually navigated to the right page —
            #   don't yank them away from it.
            MAX_LOGIN_ATTEMPTS = 2
            for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
                retry = login_callback(page, domain)
                if not retry:
                    print(f"  Login skipped — scrape will likely return 0 results")
                    break

                if attempt == 1:
                    # Common case: login redirected the user to /dashboard
                    # or similar. Navigate to our target URL so we end up
                    # on the page we actually want to scrape.
                    print(f"  Navigating to directory page after login: {directory_url}")
                    page.goto(directory_url)
                    try:
                        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                    except Exception:
                        pass
                else:
                    # Retry: trust the user's current location. They may
                    # have manually navigated to a better page than
                    # directory_url after the first verification failed.
                    print(f"  Verifying current page: {page.url}")

                # Verify login actually worked. If still a login wall, the
                # cookies are useless — do NOT save them (would poison the
                # cache and make future scrapes silently fail).
                if not _is_login_page(page):
                    _save_cookies(page, domain)
                    print(f"  Login verified on {page.url} — continuing scrape")
                    break

                remaining = MAX_LOGIN_ATTEMPTS - attempt
                if remaining > 0:
                    print(f"  Login verification FAILED — page still shows a "
                          f"login wall. {remaining} attempt(s) remaining.")
                    print(f"  If login redirected you elsewhere, you can "
                          f"manually navigate to the directory page before "
                          f"pressing Enter on the next prompt.")
                else:
                    print(f"  Login verification FAILED after {MAX_LOGIN_ATTEMPTS} "
                          f"attempts — NOT saving cookies. Scrape will likely "
                          f"return 0 results.")

    # --- Fast path: URL-parameter enumeration ---
    # If the page has a GET form with a static <select> (e.g.
    # hoa-usa.com's ?state=Alabama dropdown), we can fetch every
    # parameter value in parallel via curl_cffi and skip the entire
    # browser-based search/scroll/paginate flow. ~20–50x faster.
    try:
        from url_enumeration import try_url_enumeration_cached
        if try_url_enumeration_cached(page, domain, link, results, intent=intent):
            print(f"  URL enumeration captured {len(results)} pages — "
                  f"skipping browser search flow")
            browser.close()
            return results, []
    except Exception as e:
        print(f"  URL enumeration error (non-fatal, falling through): {e}")

    hub_categories = []
    search_triggered = False  # stays False when the hub check skips search
    # --- Step 1.9: Listing-hub check (BEFORE search; both modes) ---
    # Pages like walmart.com/store-directory/mn are partition indexes:
    # dozens of same-template child links (one per city/category) and no
    # member data of their own. Searching such a page grabs the site-wide
    # search box and never comes back, so the child pages holding the
    # actual records are never visited. Detect the hub shape first and
    # skip search for it. All guards must hold: zero member-shaped JSON,
    # <3 visible member cards (checked inside detect_category_links), and
    # ≥CHILD_HUB_MIN_LINKS same-template children of THIS page's path —
    # nav/footer noise on busy sites doesn't satisfy that. Aggregator+
    # intent runs keep their intent-first search behavior.
    # Direct mode runs this too: a pasted state/region index holds its
    # records in the child pages — scraping the hub flat yields bare link
    # text (city names, no contacts) that the cleaner rejects as garbage.
    if not (is_aggregator and intent) and _count_json_member_records(results) == 0:
        hub_categories = detect_category_links(
            page, child_hub_of=page.url, min_links=CHILD_HUB_MIN_LINKS)
    if hub_categories:
        print(f"  Listing hub detected: {len(hub_categories)} child listing "
              f"pages — iterating them instead")
        debug.decision("SEARCH", "listing hub — iterate children",
                       f"{len(hub_categories)} same-template child links of "
                       f"{page.url}",
                       data={"sample": [c["text"] for c in hub_categories[:8]]})
    elif mode != "direct":
        # --- Step 2: Try search strategies ---
        pre_search_count = len(results)
        debug.log("SEARCH", f"Starting search. JSON results so far: {pre_search_count}")
        search_triggered = trigger_search(page, results,
                                          is_aggregator=is_aggregator,
                                          intent=intent,
                                          html_collector=all_page_htmls)
        # A search submission can occasionally trip a fresh challenge.
        handle_captcha(page, domain, captcha_callback)
        debug.log("SEARCH", f"Search complete. triggered={search_triggered}, "
                  f"results before={pre_search_count} after={len(results)}")
        if search_triggered and len(results) > pre_search_count:
            idle_timeout_value = SEARCH_IDLE_TIMEOUT
            print(f"Idle timeout set to: {idle_timeout_value}s (search mode)")
    if search_triggered:
        # Search results frequently lazy-load below the fold (Algolia-
        # style grids, "infinite" result lists). Without this scroll, a
        # searched directory captures exactly one viewport — there was
        # previously NO code path where search and scrolling both ran.
        human_scroll(page, done, scroll_target="body", adaptive=True)

    # --- Step 2.5: Intent-driven deep capture (Agent mode, targeted only) ---
    # The search flow above (or a hub) may have left the user's TARGETED intent
    # unfulfilled: a weak search, a complicated engine, or data that lives
    # behind category/city sub-pages. When yield is low, first replay any
    # captured directory-API XHRs with mutated params (cheapest, best-targeted
    # source), then BFS-crawl intent-matched sub-pages. Both are pure no-ops
    # when intent is None, so Playground / direct / "scrape everything" runs
    # are untouched. Skipped for hubs (their own iterator owns partitions) and
    # aggregators (they keep intent-first search; their trees explode).
    intent_expanded = False
    if intent and mode != "direct" and not hub_categories and not is_aggregator:
        # Fail-open: this is new code on the critical path — a failure here
        # must never sink an otherwise-working scrape.
        try:
            if (_count_json_member_records(results) < INTENT_LOW_RECORDS
                    and count_visible_results(page) < INTENT_LOW_VISIBLE):
                replay_directory_xhrs(page, results, intent)
                if _count_json_member_records(results) < INTENT_LOW_RECORDS:
                    intent_expanded = discover_intent_subpages(
                        page, intent, results,
                        link_collector=all_page_links,
                        html_collector=all_page_htmls)
        except Exception as e:
            print(f"  Intent deep capture error (non-fatal): {e}")
            debug.log("EXPAND", f"intent deep capture failed: {e}", level="error")

    # Enable and start the idle timer AFTER search/scroll decision.
    timer_enabled = True
    reset_idle_timer()

    # --- Step 3: If no search, try view-all / categories / scroll ---
    # In direct mode the user already chose the page, so view-all hunting and
    # generic category discovery stay off — but a detected listing hub DOES
    # get iterated (the pasted page's own children hold the records).
    categories_handled = False
    view_all_clicked = False
    if not search_triggered and not intent_expanded and (mode != "direct" or hub_categories):
        visible_count = count_visible_results(page)
        debug.log("SEARCH", f"No search triggered. visible_results={visible_count}, "
                  f"json_results={len(results)}")
        # Count member RECORDS, not responses — junk JSON (Partytown proxies,
        # cart GraphQL) fills `results` on sites like Walmart and used to
        # block category discovery here even though it holds zero members.
        if _count_json_member_records(results) == 0 and visible_count < CATEGORY_SKIP_VISIBLE_THRESHOLD:
            # No search, no member-shaped JSON, no members visible.
            # Try the simplest discovery method first.

            # 1. Try "View All" / "Show All" link (loads everything at once).
            # Not in direct mode — it only reaches this block for a hub, and
            # the hub's children are iterated directly, no clicking around.
            if mode != "direct":
                view_all_clicked = try_view_all(page)
                debug.log("SEARCH", f"View All attempt: {'clicked' if view_all_clicked else 'not found'}")

            # 2. If no View All, try category iteration
            if not view_all_clicked:
                if hub_categories:
                    # Child-partition hub (per-city / per-letter pages):
                    # every partition must be crawled for complete data —
                    # the industry intent filter does not apply to geography.
                    categories = hub_categories
                else:
                    categories = detect_category_links(page)
                    # Agent mode narrows categories to the user's intent. Fall-open
                    # if intent is None or no matches found — never accidentally drop
                    # every category and end up scraping nothing.
                    categories = filter_categories_by_intent(categories, intent)
                if categories:
                    print(f"  Iterating {len(categories)} categories...")
                    timer_enabled = False
                    for ci, cat in enumerate(categories):
                        try:
                            page.goto(cat["href"], timeout=15000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                            except Exception:
                                pass
                            page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
                            print(f"  Category {ci + 1}/{len(categories)}: {cat['text']}")

                            cat_links = collect_page_links(page)
                            all_page_links.extend(cat_links)

                            try:
                                cat_html = page.content()
                                # We navigated here on purpose — keep the HTML
                                # on either signal. Phone numbers catch listing
                                # pages that use none of the generic keywords.
                                if (any(kw in cat_html.lower() for kw in
                                        _DIRECTORY_CONTENT_KEYWORDS)
                                        or _PHONE_RE.search(cat_html)):
                                    all_page_htmls.append(cat_html)
                            except Exception:
                                pass

                            cat_done = threading.Event()
                            handle_pagination(page, cat_done,
                                              link_collector=all_page_links,
                                              html_collector=all_page_htmls)

                        except Exception as e:
                            print(f"  Error on category '{cat['text']}': {e}")
                            continue
                    print(f"  Category iteration complete")
                    categories_handled = True
                    timer_enabled = True
                    reset_idle_timer()

        # 3. Scroll — but only what's appropriate. Direct mode scrolls in its
        # own block below (running both would double-scroll a hub page whose
        # iteration gate didn't hold). Member RECORDS gate the light scroll —
        # junk JSON (cart GraphQL etc.) must not suppress the adaptive one.
        # intent_expanded means the crawler already left the page on an
        # exhausted sub-page — scrolling it would capture nothing new.
        if not categories_handled and not intent_expanded and mode != "direct":
            if _count_json_member_records(results) > 0 or view_all_clicked:
                # Data already captured — just light scroll in case of lazy stragglers
                print(f"Already captured data, minimal scrolling")
                human_scroll(page, done, scroll_target="body", times=5)
            else:
                # Nothing found yet — adaptive scroll for infinite scroll pages
                human_scroll(page, scroll_target="body", done_event=done, adaptive=True)

    # Direct mode: scroll to trigger lazy content. With data already captured
    # a light scroll catches stragglers; with NOTHING captured yet, scroll
    # adaptively — the user pointed at this exact page, and infinite-scroll
    # listings keep loading well past a fixed 5-batch scroll (a fixed scroll
    # silently truncated them to roughly one viewport). Member RECORDS, not
    # raw responses: a captured cart/session blob used to force the light
    # scroll here. After hub iteration there's nothing left to scroll — the
    # child pages' HTML is already collected.
    if mode == "direct" and not search_triggered and not categories_handled:
        if _count_json_member_records(results) > 0:
            print(f"  Direct mode: scrolling to load lazy content")
            human_scroll(page, done, scroll_target="body", times=5)
        else:
            print(f"  Direct mode: adaptive scroll (no data captured yet)")
            human_scroll(page, done, scroll_target="body", adaptive=True)

    # --- Step 3.5: Detect if results are inside an iframe ---
    # Some platforms (YourMembership, etc.) load search results in an iframe.
    # If so, we need to collect links, paginate, and capture HTML from the
    # iframe's Frame object — not the main page.
    # Skip iframe detection if we already captured member-shaped JSON —
    # iframe is a fallback for sites that ONLY render results in an iframe.
    # Count RECORDS, not responses: junk JSON (cart GraphQL etc.) used to
    # suppress iframe detection on sites whose real data sits in a frame.
    content_frame = None
    json_member_count = _count_json_member_records(results)
    if json_member_count == 0:
        content_frame = find_content_frame(page)
    else:
        print(f"  Skipping iframe detection (already have {json_member_count} JSON member records)")
    content_context = content_frame if content_frame else page
    if content_frame:
        print(f"  Operating inside iframe for link collection and pagination")

    # --- Step 4: Collect links from the current content (before pagination) ---
    initial_links = collect_page_links(content_context)
    all_page_links.extend(initial_links)
    if content_frame:
        print(f"  Collected {len(initial_links)} links from iframe (page 1)")

    # --- Step 4.5: Capture initial page HTML before pagination ---
    # Pagination navigates away from each page, so we must capture page 1 now.
    # Subsequent pages are captured inside handle_pagination via html_collector.
    # Direct mode: the user pasted THIS page as the directory — never gate it
    # on the (English-only) keyword list, which drops foreign-language and
    # unusually-worded listings. Auto mode keeps the keyword gate, with the
    # same phone-number fallback the category iterator uses.
    try:
        initial_html = content_context.content()
        if (mode == "direct"
                or any(kw in initial_html.lower() for kw in _DIRECTORY_CONTENT_KEYWORDS)
                or _PHONE_RE.search(initial_html)):
            all_page_htmls.append(initial_html)
            debug.log("CAPTURE", f"Captured initial HTML: {len(initial_html)} chars")
        else:
            debug.log("CAPTURE", "Initial HTML has no directory keywords — skipped", level="warn")
    except Exception:
        pass

    # --- Step 5: Handle pagination (also collects links and HTML from each new page) ---
    # Pagination buttons (Next, →, Load More) are inside the content context.
    # Skip pagination if the search already loaded a large number of results —
    # sites that show 600+ results on one page don't need pagination, and
    # false "next" button matches (carousel arrows, nav links) can navigate away.
    skip_pagination = False
    # The intent sub-page crawler already paginated every page it visited; the
    # page now sits on the last sub-page, so a fresh handle_pagination here
    # would re-walk that one sub-page's numbered links and duplicate its HTML.
    if intent_expanded:
        print(f"  Skipping pagination — intent sub-page crawl already paginated each page")
        skip_pagination = True
    try:
        visible_now = count_visible_results(content_context)
        if not skip_pagination and visible_now >= 600:
            print(f"  Skipping pagination — already have {visible_now} visible results")
            skip_pagination = True
    except:
        pass

    # Also skip pagination if JSON already has substantial member data.
    # Prevents false Next button matches (carousel arrows, nav links) from
    # navigating away when we already have what we need.
    if not skip_pagination:
        json_record_count = _count_json_member_records(results)
        if json_record_count >= 50:
            print(f"  Skipping pagination — already have {json_record_count} JSON records")
            skip_pagination = True

    if not skip_pagination:
        # Always attempt pagination — clear any previously fired done event and
        # give a fresh 30s window. The old 4s/20s timer may have fired during
        # iframe detection and link collection, but we still need to paginate.
        done.clear()
        idle_timeout_value = PAGINATION_IDLE_TIMEOUT
        reset_idle_timer()
        extra_pages = handle_pagination(content_context, done, link_collector=all_page_links,
                                        html_collector=all_page_htmls)
        if extra_pages > 0:
            reset_idle_timer()  # give time for last page's responses
        else:
            # No pagination found — no reason to wait 30s
            idle_timeout_value = DEFAULT_IDLE_TIMEOUT
            reset_idle_timer()
    else:
        # Already have enough results — just give a short window for any
        # remaining responses to arrive, then move on.
        done.clear()
        idle_timeout_value = DEFAULT_IDLE_TIMEOUT
        reset_idle_timer()

    # --- Early exit: cut the dead tail wait when data is already captured ---
    # JSON results reset the idle timer on each arrival via on_response, so if
    # the timer is close to firing it means the network has gone quiet.  Three
    # scenarios, ordered by how much we can safely skip:
    #   1. HTML + JSON in hand → exit immediately (nothing left to wait for)
    #   2. HTML only, zero JSON → short grace for straggler network responses
    #   3. Neither → keep the full timeout (still waiting for first data)
    # "JSON in hand" means member RECORDS — a junk capture (cart GraphQL,
    # i18n bundle) used to trigger the immediate exit and cut the idle wait
    # the real data still needed.
    _has_json_results = _count_json_member_records(results) > 0
    if all_page_htmls and _has_json_results:
        # Both sources satisfied — kill the timer and move on
        if idle_timer:
            idle_timer.cancel()
        done.set()
        print("  Early exit: HTML + JSON captured, skipping idle wait")
    elif all_page_htmls and not _has_json_results:
        # Have HTML but JSON might still be in-flight — give it a short window
        if idle_timer:
            idle_timer.cancel()
        page.wait_for_timeout(1500)  # 1.5 s grace for straggler JSON
        done.set()
        print("  Early exit: HTML captured (no JSON), short grace period done")

    # Wait until idle timer fires (or already set above)
    done.wait()

    # --- Step 6: Add captured page HTML(s) to results ---
    # If pagination captured multiple pages, add all of them.
    # If no pagination, all_page_htmls has just the initial page (same as before).
    # If pagination used Load More (no navigation), capture final page state now.
    if all_page_htmls:
        source_url = content_frame.url if content_frame else page.url
        print(f"Captured {len(all_page_htmls)} HTML page(s)")
        for html in all_page_htmls:
            results.append({
                "url": source_url,
                "data": {"raw_html": html}
            })
    else:
        # Fallback: capture whatever is on screen now. Same gate as Step 4.5 —
        # direct mode trusts the user's page unconditionally.
        try:
            html = content_context.content()
            if (mode == "direct"
                    or any(kw in html.lower() for kw in _DIRECTORY_CONTENT_KEYWORDS)
                    or _PHONE_RE.search(html)):
                source_url = content_frame.url if content_frame else page.url
                print(f"Captured plain HTML from: {source_url}")
                results.append({
                    "url": source_url,
                    "data": {"raw_html": html}
                })
        except Exception as e:
            print(f"Error capturing page HTML: {e}")

    # --- Step 7: Read pending HTML responses (ASP.NET UpdatePanel etc.) ---
    # Entries are dicts: {"url", "text"} for eagerly-read bodies (directory-
    # keyword URLs), {"url", "response"} for lazily-kept ones whose bodies
    # may already be gone after navigation.
    print(f"Processing {len(pending_html_responses)} pending HTML responses...")
    for r in pending_html_responses:
        try:
            r_url = r["url"]
            text = r.get("text")
            if text is None:
                body = r["response"].body()
                text = body.decode("utf-8", errors="ignore")
            if not text:
                continue

            # Legacy ASP.NET / PHP backends sometimes return JSON with
            # Content-Type: text/html (or text/plain), so the application/json
            # gate in on_response misses them. Cheap pre-filter on the first
            # non-whitespace char keeps the cost negligible — only payloads
            # that *look* like JSON pay the parse + detection cost.
            stripped = text.lstrip()
            if stripped and stripped[0] in "{[":
                try:
                    data = json.loads(stripped)
                except (json.JSONDecodeError, ValueError):
                    data = None
                if data is not None and _is_directory_json(data, r_url):
                    print(f"JSON-as-text/html detected at: {r_url}")
                    results.append({"url": r_url, "data": data})
                    continue  # already routed — don't also try UpdatePanel parse

            # Detect ASP.NET UpdatePanel response
            if "updatepanel" in text.lower() and any(
                kw in text.lower() for kw in ["member", "contact", "directory"]
            ):
                print("ASP.NET UpdatePanel response detected at:", r_url)
                # Extract HTML chunk from pipe-delimited format
                # Format: length|#||type|length|updatePanel|id|<HTML>
                parts = text.split("|", 7)
                html_content = parts[7] if len(parts) >= 8 else text
                results.append({
                    "url": r_url,
                    "data": {"raw_html": html_content}
                })
        except Exception as e:
            print(f"Error reading pending response: {e}")

    # --- Step 8: Detect detail links if data is shallow ---
    if all_page_links:
        detected = detect_detail_links(all_page_links)
        if detected:
            # Check if we have any structured JSON data
            has_structured_json = any(
                (isinstance(r.get("data"), list) and len(r.get("data", [])) > 0) or
                (isinstance(r.get("data"), dict) and "raw_html" not in r.get("data", {}))
                for r in results
            )

            # If priority fields are set, always pass detail URLs through
            # and let main.py decide based on what fields are actually missing.
            # Without priorities, use the original heuristic checks.
            if priority_fields:
                detail_urls = detected
                print(f"\n  Found {len(detail_urls)} member detail page links (priority fields requested)")
            elif has_structured_json:
                # JSON data exists — check if it has contact info
                if is_shallow_data(results):
                    detail_urls = detected
                    print(f"\n  JSON data appears shallow (names only, no contact info)")
                    print(f"  Found {len(detail_urls)} member detail page links")
                else:
                    print(f"  Detail links found but JSON data already has contact info — skipping")
            else:
                # No JSON data — HTML only. Check if HTML has contact info.
                if html_has_contact_info(results):
                    print(f"  Detail links found but HTML already has contact info — skipping")
                else:
                    detail_urls = detected
                    print(f"\n  HTML-only listing with no contact info detected")
                    print(f"  Found {len(detail_urls)} member detail page links")

    # --- Step 8.5: Construct detail URLs from UIDs in shallow JSON data ---
    # MembershipWorks and similar platforms return JSON with uid fields but no
    # detail links in the DOM (they use hash-fragment routes like #!biz/id/{uid}).
    # If no detail links were found, check UID-bearing records directly for
    # shallowness (don't use is_shallow_data — it gets fooled by unrelated JSON
    # like chat widget localization files that have keys like "email"/"phone").
    if not detail_urls:
        uid_list = []
        for result in results:
            data = result.get("data", {})
            # Check top-level list
            members = data if isinstance(data, list) else None
            # Check nested list inside dict (e.g. {"typ":"a", "usr":[...]})
            if not members and isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list) and len(val) >= 3:
                        if isinstance(val[0], dict) and "uid" in val[0]:
                            members = val
                            break
            if members:
                # Check if these specific records lack contact info
                sample = members[:20]
                has_contact = 0
                for m in sample:
                    if isinstance(m, dict) and any(
                        k.lower() in CONTACT_KEYS and m[k] and str(m[k]).strip()
                        for k in m
                    ):
                        has_contact += 1
                if has_contact / len(sample) >= 0.2:
                    print(f"  UID records already have contact info ({has_contact}/{len(sample)} sampled) — skipping")
                    continue
                for m in members:
                    if isinstance(m, dict) and "uid" in m:
                        uid_list.append(m["uid"])

        if uid_list:
            # Deduplicate while preserving order
            seen = set()
            unique_uids = []
            for uid in uid_list:
                if uid not in seen:
                    seen.add(uid)
                    unique_uids.append(uid)
            uid_list = unique_uids
            # Build detail URLs using the page's base URL + hash fragment
            base_url = page.url.split("#")[0].rstrip("/")
            detail_urls = [f"{base_url}#!biz/id/{uid}" for uid in uid_list]
            print(f"\n  Shallow JSON data with UIDs detected (MembershipWorks pattern)")
            print(f"  Constructed {len(detail_urls)} detail URLs from JSON uid fields")

    browser.close()
    print(f"Total results captured: {len(results)}")

    # Debug summary of everything captured
    json_count = sum(1 for r in results if isinstance(r.get("data"), (list, dict)) and "raw_html" not in r.get("data", {}))
    html_count = sum(1 for r in results if isinstance(r.get("data"), dict) and "raw_html" in r.get("data", {}))
    debug.log("CAPTURE", f"Final capture summary", data={
        "total_results": len(results),
        "json_responses": json_count,
        "html_pages": html_count,
        "detail_urls_found": len(detail_urls),
        "page_links_collected": len(all_page_links),
        "final_page_url": page.url if not page.is_closed() else "closed",
    })
    if not results:
        print("No responses were captured!")

    return results, detail_urls