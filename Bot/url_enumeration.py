"""URL-parameter enumeration for GET-form directory sites.

When a directory uses a server-rendered GET form with a static <select>
(e.g. hoa-usa.com's ?state=Alabama, ?state=Alaska, ...), we can skip
the entire Playwright pipeline — typing, clicking, waiting for responses —
and just fetch each URL variant in parallel via curl_cffi. Roughly
25–50x faster than the browser-based search path on sites that fit.

Detection is deterministic; no LLM calls.
"""

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup

# Reuse Phase 2's TLS-fingerprinted HTTP fetcher
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Phase2Bot.page_fetcher import fetch_page  # noqa: E402

MIN_OPTIONS = 5  # below this, a <select> is probably not a directory filter

# --- Post-fetch validation ---
# After enumeration fetches all variants, we sanity-check that the pages
# contain SOMETHING extractable. Sites with hollow per-state pages (no
# members, no contact info, just marketing copy) would otherwise pollute
# Phase 1's selector-learning step and produce false positives. If the
# sample we check has zero signal, we mark the domain as failed and fall
# back to the browser flow.
_VALIDATION_SAMPLE_SIZE = 8        # how many fetched pages we inspect
_MIN_PAGES_WITH_SIGNAL = 1         # min pages that must have a signal

# Cheap, no-soup regex checks. Same patterns Phase 0's classifier uses
# so behavior is consistent across the codebase.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}(?!\d)"
)
# Strong directory keywords. We require 2+ in a non-tiny page to count
# as a signal, since single occurrences (e.g. footer "Contact us" link)
# show up on every marketing page.
_DIRECTORY_KEYWORDS = (
    "member", "directory", "contact", "phone", "email", "address",
    "listing", "browse", "search results",
)


_PLACEHOLDER_VALUES = {"", "0", "all", "any", "select", "choose", "none", "-1"}
_PLACEHOLDER_TEXT_PATTERNS = [
    re.compile(r"^\s*select\b", re.I),
    re.compile(r"^\s*choose\b", re.I),
    re.compile(r"^\s*pick\b", re.I),
    re.compile(r"^---", re.I),
    re.compile(r"^\s*all\b", re.I),
]


def _is_placeholder_option(value: str, text: str) -> bool:
    """An <option> is a placeholder if its value is empty/'select'/'all'/etc.,
    or its visible text starts with 'Select…', 'Choose…', etc."""
    if value.strip().lower() in _PLACEHOLDER_VALUES:
        return True
    return any(pat.match(text) for pat in _PLACEHOLDER_TEXT_PATTERNS)


def detect_url_filtered_form(html: str, current_url: str) -> dict | None:
    """Find a GET form whose <select> maps directly to a URL query parameter.

    Returns None if no such form exists, otherwise:
        {
            "template_url": "https://example.com/path?state={value}",
            "param": "state",
            "values": ["Alabama", "Alaska", ...],
            "form_action": "https://example.com/path",
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    current_params = parse_qs(urlparse(current_url).query)
    candidates = []

    for form in soup.find_all("form"):
        method = (form.get("method") or "get").lower()
        if method != "get":
            continue

        # Resolve action to absolute URL, strip query/fragment. A GET
        # form's submission REPLACES the action's query string, so the
        # query in the action attribute is irrelevant.
        action = form.get("action") or current_url
        action_url = urljoin(current_url, action)
        ap = urlparse(action_url)
        clean_action = f"{ap.scheme}://{ap.netloc}{ap.path}"

        for select in form.find_all("select"):
            name = (select.get("name") or "").strip()
            if not name:
                continue

            values = []
            for opt in select.find_all("option"):
                if opt.get("disabled") is not None:
                    continue
                v = (opt.get("value") or "").strip()
                t = opt.get_text(strip=True)
                if _is_placeholder_option(v, t):
                    continue
                values.append(v)

            if len(values) < MIN_OPTIONS:
                continue

            candidates.append({
                "template_url": f"{clean_action}?{name}={{value}}",
                "param": name,
                "values": values,
                "form_action": clean_action,
                "_url_match": name in current_params,
            })

    if not candidates:
        return None

    # Prefer selects whose name appears in the current URL's query
    # (strong signal we're on a queried page); then prefer larger
    # option sets (state lists, categories, etc.).
    candidates.sort(key=lambda c: (not c["_url_match"], -len(c["values"])))
    chosen = candidates[0]
    chosen.pop("_url_match", None)
    return chosen


def enumerate_param_urls(template_url: str, values: list,
                          max_workers: int = 8) -> list[dict]:
    """Fetch every (template, value) URL via curl_cffi in parallel.

    Failures are silently dropped — caller can decide whether enough
    succeeded for the scrape to be viable.

    Returns list of {"url": str, "value": str, "html": str}.
    """
    urls = [
        (value, template_url.replace("{value}", quote(value, safe="")))
        for value in values
    ]

    out = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_page, url): (value, url)
                   for value, url in urls}
        for fut in as_completed(futures):
            value, url = futures[fut]
            try:
                soup, final_url = fut.result()
            except Exception as e:
                print(f"  URL enum: error fetching {value!r}: {e}")
                continue
            if soup is None:
                continue
            out.append({
                "url": final_url or url,
                "value": value,
                "html": str(soup),
            })
    return out


def _validate_enumeration_results(fetched: list[dict]) -> tuple[bool, str]:
    """Check that the enumerated pages actually contain extractable data.

    Samples the first few fetched pages and looks for ANY of:
      - email or phone number (regex)
      - mailto: / tel: links
      - 2+ directory keywords on a non-tiny page

    Returns (is_useful, reason). False means enumeration produced junk
    and the caller should fall back to the browser flow.
    """
    if not fetched:
        return False, "no successful fetches"

    sample = fetched[:_VALIDATION_SAMPLE_SIZE]
    pages_with_signal = 0

    for entry in sample:
        html = entry.get("html") or ""
        if not html:
            continue

        if _EMAIL_RE.search(html) or _PHONE_RE.search(html):
            pages_with_signal += 1
            continue
        if "mailto:" in html or "tel:" in html:
            pages_with_signal += 1
            continue

        # Bag-of-keywords check on a non-tiny page. Single occurrences
        # leak from headers/footers, so require 2+ distinct keywords.
        if len(html) >= 3000:
            html_lower = html.lower()
            hits = sum(1 for kw in _DIRECTORY_KEYWORDS if kw in html_lower)
            if hits >= 2:
                pages_with_signal += 1

    if pages_with_signal < _MIN_PAGES_WITH_SIGNAL:
        return False, (
            f"0/{len(sample)} sampled pages contain contact info or "
            f"directory signals — site looks empty"
        )

    return True, f"{pages_with_signal}/{len(sample)} sampled pages have signals"


def _enumerate_and_append(plan: dict, results: list, domain: str | None = None) -> bool:
    """Run the enumeration for a known plan and append HTMLs to `results`.

    If `domain` is provided, a failed validation also writes a negative
    cache entry so subsequent runs skip the wasted work entirely.
    """
    print(f"  URL-filtered form: param='{plan['param']}', "
          f"{len(plan['values'])} values")
    print(f"  Template: {plan['template_url']}")
    print(f"  Enumerating in parallel via curl_cffi...")

    fetched = enumerate_param_urls(plan["template_url"], plan["values"])
    if not fetched:
        print(f"  URL enumeration produced 0 successful fetches — "
              f"falling back to browser flow")
        return False

    # --- Sanity check: did we actually get useful content? ---
    is_useful, reason = _validate_enumeration_results(fetched)
    if not is_useful:
        print(f"  URL enumeration rejected: {reason}")
        if domain is not None:
            # Negative-cache the domain so the next run doesn't repeat
            # the parallel-fetch step for the same junk pages.
            try:
                from cache import set_cached_url_template
                set_cached_url_template(domain, {"failed": True, "reason": reason})
                print(f"  Marked {domain} as URL-enum-failed (negative cache)")
            except Exception as e:
                print(f"  Could not write negative cache: {e}")
        return False

    print(f"  URL enumeration: {len(fetched)}/{len(plan['values'])} "
          f"successful fetches — {reason}")
    for f in fetched:
        results.append({
            "url": f["url"],
            "data": {"raw_html": f["html"]},
        })
    return True


def try_url_enumeration(html: str, current_url: str, results: list) -> bool:
    """Stateless entry point: detect from HTML, enumerate, append.

    Returns True if enumeration produced data; False if no pattern was
    detected or all fetches failed. Used in tests with HTML in hand.
    """
    plan = detect_url_filtered_form(html, current_url)
    if plan is None:
        return False
    return _enumerate_and_append(plan, results)


def try_url_enumeration_cached(page, domain: str, link: str,
                                 results: list) -> bool:
    """Cache-aware variant used from the browser pipeline.

    On cache hit: skip detection and enumerate directly (unless the cache
    entry is a negative result — then short-circuit immediately).
    On miss: detect from the current page HTML, cache the plan if found,
    then enumerate.

    Returns True if enumeration succeeded; False to fall through to the
    existing Playwright-based search flow.
    """
    # Local import to avoid cache.py loading at module-import time
    from cache import get_cached_url_template, set_cached_url_template

    plan = get_cached_url_template(domain)
    if plan is not None:
        # Negative-cache short-circuit: a previous run already proved
        # this domain's enumeration produces no useful content.
        if plan.get("failed"):
            reason = plan.get("reason", "no useful content")
            print(f"  URL enum cache: {domain} previously failed ({reason}) — skipping")
            return False
        print(f"  Cache hit for {domain} — skipping form detection")
    else:
        try:
            html = page.content()
        except Exception as e:
            print(f"  URL enum: couldn't read page content: {e}")
            return False
        current_url = page.url or link
        plan = detect_url_filtered_form(html, current_url)
        if plan is None:
            return False
        set_cached_url_template(domain, plan)

    return _enumerate_and_append(plan, results, domain=domain)
