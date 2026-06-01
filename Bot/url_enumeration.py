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
_VALIDATION_SAMPLE_SIZE = 8        # how many fetched pages we inspect for signals
_STRUCTURAL_SAMPLE_SIZE = 6        # how many we re-inspect for repeating card structure
_MIN_PAGES_WITH_SIGNAL = 2         # min pages that must have a signal
_MIN_CARDS_FRACTION = 0.5          # fraction of structural-sample pages that must have cards

# --- Pre-enumeration probe ---
# Before enumerating, fetch the form's action URL with NO filter parameter.
# If that page already shows a directory (cards visible), the <select> is
# a NARROWING filter, not a partition — the browser flow can use the
# wildcard view (often via the search button or pagination) and will yield
# the full membership instead of the sparse per-category subsets.
_PROBE_MIN_CARDS = 5               # unfiltered cards >= this → form is a narrowing filter

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
            options = []
            for opt in select.find_all("option"):
                if opt.get("disabled") is not None:
                    continue
                v = (opt.get("value") or "").strip()
                t = opt.get_text(strip=True)
                if _is_placeholder_option(v, t):
                    continue
                values.append(v)
                # Keep the visible label too — Agent mode matches the user's
                # intent against these (e.g. "Decks") to enumerate only the
                # relevant category instead of all of them. See
                # _match_intent_category_values.
                options.append({"value": v, "label": t})

            if len(values) < MIN_OPTIONS:
                continue

            candidates.append({
                "template_url": f"{clean_action}?{name}={{value}}",
                "param": name,
                "values": values,
                "options": options,
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

    Samples the first few fetched pages and looks for:
      - email or phone number (regex)
      - mailto: / tel: links
      - 2+ directory keywords on a non-tiny page
      - AND at least one page must have repeating card structure
        (extract_sample_html returns a card_selector)

    Returns (is_useful, reason). False means enumeration produced junk
    and the caller should fall back to the browser flow.
    """
    if not fetched:
        return False, "no successful fetches"

    sample = fetched[:_VALIDATION_SAMPLE_SIZE]
    pages_with_signal = 0
    pages_with_cards = 0

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
            f"{pages_with_signal}/{len(sample)} sampled pages contain contact info or "
            f"directory signals — site looks empty"
        )

    # Structural check: do most sampled pages contain repeating card-like
    # elements? Keyword matching alone produces false positives on wrapper
    # pages (WordPress templates, GrowthZone embeds) whose nav/footer text
    # contains "member", "directory", "contact" but no actual member cards.
    # We require a MAJORITY of the structural sample to have cards — a
    # single lucky page won't rescue a sparse-partition enumeration like
    # category filters where most subsets are empty.
    from html_parser import extract_sample_html
    structural_sample = sample[:_STRUCTURAL_SAMPLE_SIZE]
    structural_checked = 0
    for entry in structural_sample:
        html = entry.get("html") or ""
        if not html or len(html) < 3000:
            continue
        structural_checked += 1
        try:
            _, card_selector = extract_sample_html(html)
            if card_selector:
                pages_with_cards += 1
        except Exception:
            continue

    min_required = max(2, int(structural_checked * _MIN_CARDS_FRACTION + 0.5)) if structural_checked else 1
    if pages_with_cards < min_required:
        return False, (
            f"{pages_with_cards}/{structural_checked} sampled pages have card structure "
            f"(need {min_required}+) — keywords matched but most pages have no repeating "
            f"member cards (likely a sparse narrowing filter, not a partition)"
        )

    return True, (
        f"{pages_with_signal}/{len(sample)} pages have signals, "
        f"{pages_with_cards}/{structural_checked} have card structure"
    )


def _probe_unfiltered_url(form_action: str) -> int:
    """Fetch the form's action URL with NO filter and count repeating cards.

    Used to detect "narrowing filter" forms (where the unfiltered view is
    itself a viable directory page) vs "partition" forms (where the
    unfiltered URL is a landing/picker page with no member cards).

    Returns the number of cards detected by html_parser's structural
    scorer, or 0 if the probe failed for any reason. Callers should treat
    0 as "no signal, proceed with enumeration".
    """
    try:
        soup, _ = fetch_page(form_action)
    except Exception as e:
        print(f"  Unfiltered probe: fetch failed ({e}) — falling through")
        return 0
    if soup is None:
        return 0
    html = str(soup)
    if len(html) < 3000:
        return 0
    try:
        from html_parser import extract_sample_html
        _, card_selector = extract_sample_html(html)
        if not card_selector:
            return 0
        return len(BeautifulSoup(html, "html.parser").select(card_selector))
    except Exception as e:
        print(f"  Unfiltered probe: card detection failed ({e}) — falling through")
        return 0


def _match_intent_category_values(options: list, intent: dict) -> list:
    """Match the user's intent against <select> option LABELS and return the
    subset of option VALUES whose labels match (scope-aware).

    Returns [] when intent can't narrow the options — the caller then falls
    back to whole-form behavior (probe + wildcard). Reuses
    Bot/intent_filter.filter_categories_by_intent so category matching here is
    identical to the browser-flow category iterator.
    """
    if not options or not intent:
        return []
    cats = [{"text": o.get("label") or "", "value": o.get("value")} for o in options]
    # If the labels are blank (codes only, no human-readable category), there's
    # nothing to match against.
    if not any((c["text"] or "").strip() for c in cats):
        return []
    try:
        from intent_filter import filter_categories_by_intent
        matched = filter_categories_by_intent(cats, intent)
    except Exception as e:
        print(f"  URL enum intent match: failed ({e}) — using whole form")
        return []
    # filter_categories_by_intent falls open (returns the full list) when
    # nothing matched. Only treat a STRICT subset as a real narrowing hit.
    if len(matched) >= len(cats):
        return []
    return [c.get("value") for c in matched if c.get("value") is not None]


def _negative_cache_narrowing(domain: str, plan: dict, reason: str):
    """Cache a narrowing-filter result, preserving the plan's options.

    Unlike a hard validation failure, a narrowing filter is REUSABLE: a later
    intent-driven run can still enumerate just the matching category. So we keep
    the full plan and tag it, rather than writing a bare {"failed": True}.
    """
    try:
        from cache import set_cached_url_template
        entry = dict(plan)
        entry["failed"] = True
        entry["narrowing_filter"] = True
        entry["reason"] = reason
        set_cached_url_template(domain, entry)
        print(f"  Marked {domain} as narrowing-filter "
              f"(negative cache, reusable with intent)")
    except Exception as e:
        print(f"  Could not write negative cache: {e}")


def _enumerate_and_append(plan: dict, results: list, domain: str | None = None,
                          intent: dict | None = None) -> bool:
    """Run the enumeration for a known plan and append HTMLs to `results`.

    If `domain` is provided, a failed validation also writes a negative
    cache entry so subsequent runs skip the wasted work entirely.

    When `intent` is supplied (Agent mode) and the form's options carry real
    category labels, enumerate ONLY the matching category value(s) — turning a
    narrowing filter from a problem into the precise, cheap path.
    """
    print(f"  URL-filtered form: param='{plan['param']}', "
          f"{len(plan['values'])} values")
    print(f"  Template: {plan['template_url']}")

    # --- Intent-narrowing path (Agent mode) ---
    # Fetch just the deck-builder category instead of all 240 categories or the
    # whole wildcard membership. We trust the match, so we skip the sparse-
    # partition validation (a small but correct category is a feature here).
    intent_values = _match_intent_category_values(plan.get("options") or [], intent)
    if intent_values:
        print(f"  Intent match: enumerating only {len(intent_values)} matching "
              f"category value(s) of {len(plan['values'])}")
        fetched = enumerate_param_urls(plan["template_url"], intent_values)
        if fetched:
            print(f"  URL enumeration: {len(fetched)}/{len(intent_values)} "
                  f"intent-matched category fetches")
            for f in fetched:
                results.append({"url": f["url"], "data": {"raw_html": f["html"]}})
            return True
        print(f"  Intent-matched enumeration produced 0 fetches — falling through")

    # If we already know this is a narrowing filter and intent couldn't pick a
    # category, don't re-probe — just defer to the browser/wildcard flow.
    if plan.get("narrowing_filter"):
        print(f"  Narrowing filter with no intent match — deferring to browser flow")
        return False

    # Pre-check: if the form's action URL (with no filter) already shows
    # a real directory page, the <select> is a narrowing filter rather
    # than a true partition. Enumerating each value would yield sparse
    # subsets while the browser flow can hit the wildcard view directly.
    form_action = plan.get("form_action")
    if form_action:
        unfiltered_cards = _probe_unfiltered_url(form_action)
        if unfiltered_cards >= _PROBE_MIN_CARDS:
            reason = (
                f"unfiltered URL has {unfiltered_cards} cards (>= {_PROBE_MIN_CARDS}) — "
                f"form is a narrowing filter, not a partition; browser flow will use "
                f"the wildcard view"
            )
            print(f"  URL enumeration skipped: {reason}")
            if domain is not None:
                _negative_cache_narrowing(domain, plan, reason)
            return False

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


def try_url_enumeration(html: str, current_url: str, results: list,
                        intent: dict | None = None) -> bool:
    """Stateless entry point: detect from HTML, enumerate, append.

    Returns True if enumeration produced data; False if no pattern was
    detected or all fetches failed. Used in tests with HTML in hand.
    """
    plan = detect_url_filtered_form(html, current_url)
    if plan is None:
        return False
    return _enumerate_and_append(plan, results, intent=intent)


def try_url_enumeration_cached(page, domain: str, link: str,
                                 results: list, intent: dict | None = None) -> bool:
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
        # Negative-cache short-circuit. A hard validation failure is never
        # reusable. A NARROWING-FILTER entry, though, IS reusable when we have
        # an intent that might match a category label — fall through to the
        # intent-narrowing path in _enumerate_and_append instead of skipping.
        if plan.get("failed"):
            reusable = plan.get("narrowing_filter") and intent and plan.get("options")
            if not reusable:
                reason = plan.get("reason", "no useful content")
                print(f"  URL enum cache: {domain} previously failed ({reason}) — skipping")
                return False
            print(f"  URL enum cache: {domain} is a narrowing filter — "
                  f"retrying with intent to pick a category")
        else:
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

    return _enumerate_and_append(plan, results, domain=domain, intent=intent)
