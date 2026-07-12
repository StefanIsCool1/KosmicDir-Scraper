"""Offline tests for intent-driven sub-page discovery.

Replays real page snapshots (Data-dump/{domain}.json raw_html) against the
changed navigator/browser code — no live scraping, no bot-walled sites. Covers:

  1. detect_category_links default-invariance (Playground safety) + the new
     ignore_visible / top_groups kwargs.
  2. filter_categories_by_intent strict-subset vs fall-open (the signal
     discover_intent_subpages keys on), with the LLM layer stubbed.
  3. _find_enumerable_params (pure) over crafted + real captured API URLs.
  4. replay candidate detection over a real dump.

Run: SCRAPER_HEADLESS=1 python3 test_intent_subpages.py
"""

import os
import sys
import json

os.environ.setdefault("SCRAPER_HEADLESS", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))

from _pw import sync_playwright                       # noqa: E402
import intent_filter                                  # noqa: E402
from intent_filter import filter_categories_by_intent  # noqa: E402
from navigator import detect_category_links           # noqa: E402
import browser as B                                   # noqa: E402

_failures = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures.append(name)


def _raw_html(path):
    d = json.load(open(path))
    for r in d:
        if isinstance(r, dict) and isinstance(r.get("data"), dict) and "raw_html" in r["data"]:
            return r["data"]["raw_html"]
    return None


def _hrefs(links):
    return {l["href"] for l in links}


def test_detect_category_links(pg):
    print("detect_category_links kwargs + invariance:")

    # matchhoa: visible gate passes → base returns the single best group.
    html = _raw_html("Data-dump/www_matchhoa_com.json")
    pg.set_content(html, timeout=15000)
    base = detect_category_links(pg)
    explicit = detect_category_links(pg, ignore_visible=False, top_groups=1)
    check("matchhoa: default == explicit(ignore_visible=False, top_groups=1)",
          base == explicit)
    check("matchhoa: base non-empty", len(base) > 0)

    # causeiq: members visible → default is GATED to [] (unchanged behavior);
    # ignore_visible bypasses it; top_groups=3 merges more groups.
    html = _raw_html("Data-dump/www_causeiq_com.json")
    pg.set_content(html, timeout=15000)
    base = detect_category_links(pg)
    explicit = detect_category_links(pg, ignore_visible=False, top_groups=1)
    relaxed1 = detect_category_links(pg, ignore_visible=True, top_groups=1)
    relaxed3 = detect_category_links(pg, ignore_visible=True, top_groups=3)
    check("causeiq: default == explicit defaults (invariance)", base == explicit)
    check("causeiq: default gated to [] (members visible)", base == [])
    check("causeiq: ignore_visible bypasses the gate", len(relaxed1) > 0)
    check("causeiq: top_groups=3 ⊇ top_groups=1", _hrefs(relaxed1) <= _hrefs(relaxed3))
    check("causeiq: top_groups=3 finds strictly more", len(relaxed3) > len(relaxed1))


def test_strict_subset():
    print("filter_categories_by_intent strict-subset vs fall-open:")
    cats = [
        {"text": "Decks", "href": "/c/decks"},
        {"text": "Roofing", "href": "/c/roofing"},
        {"text": "Plumbing", "href": "/c/plumbing"},
    ]
    # Substring match, specialist → strict subset (no LLM call).
    intent = {"industry_canonical": "decks", "industry_aliases": [], "scope": "specialist"}
    picked = filter_categories_by_intent(cats, intent)
    check("substring hit → strict subset", 0 < len(picked) < len(cats))
    check("substring hit → correct category", _hrefs(picked) == {"/c/decks"})

    # No match, specialist, LLM stubbed to empty → falls OPEN (same full list).
    orig_ask = intent_filter.ask
    intent_filter.ask = lambda *a, **k: ""   # deterministic empty pick
    try:
        no_match = {"industry_canonical": "aircraft manufacturing",
                    "industry_aliases": [], "scope": "specialist"}
        fell_open = filter_categories_by_intent(cats, no_match)
    finally:
        intent_filter.ask = orig_ask
    check("no match → falls open (not a strict subset)", len(fell_open) == len(cats))


def test_find_enumerable_params():
    print("_find_enumerable_params (pure):")
    f = B._find_enumerable_params

    r = f("https://x.com/api?page=2&q=dentist&size=20")
    check("page param classified", r["page"] == ["page"])
    check("term param classified", r["term"] == ["q"])

    r = f("https://x.com/api?letter=a&offset=40")
    check("letter param classified", r["letter"] == ["letter"])
    check("offset classified as page", r["offset"] if False else r["page"] == ["offset"])

    # term-like param whose value is a single char → reclassified letter.
    r = f("https://x.com/api?name=a")
    check("single-char term value → letter bucket", r["letter"] == ["name"] and r["term"] == [])

    # No query string → empty buckets.
    r = f("https://x.com/directory")
    check("no query → all empty", r == {"page": [], "term": [], "letter": []})

    # Real captured API URL (webmd): start=0 (page), q= (term).
    real = ("https://www.webmd.com/kapi/secure/d_featuredproviders/care?"
            "sortby=random&start=0&q=&count=8&state=TI")
    r = f(real)
    check("real webmd URL: start→page, q→term",
          "start" in r["page"] and "q" in r["term"])


def test_replay_candidates():
    print("replay candidate detection over a real dump:")
    d = json.load(open("Data-dump/doctor_webmd_com.json"))
    # Mirror the candidate filter inside replay_directory_xhrs.
    cands = []
    for r in d:
        url = r.get("url", "")
        data = r.get("data")
        if not url or not isinstance(data, (list, dict)):
            continue
        if isinstance(data, dict) and "raw_html" in data:
            continue
        p = B._find_enumerable_params(url)
        if p["page"] or p["term"] or p["letter"]:
            cands.append(url)
    check("webmd dump yields >=1 enumerable candidate", len(cands) >= 1)
    print(f"        ({len(cands)} candidate endpoint(s))")


if __name__ == "__main__":
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        try:
            test_detect_category_links(pg)
        finally:
            b.close()
    test_strict_subset()
    test_find_enumerable_params()
    test_replay_candidates()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): {_failures}")
        sys.exit(1)
    print("ALL PASSED")
