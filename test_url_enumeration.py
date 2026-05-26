"""Tests for Bot/url_enumeration.py

Two layers:
  1. Detection unit tests (crafted HTML, no network)
  2. Live fetch test against hoa-usa.com — verifies enumeration end-to-end
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))

from url_enumeration import (  # noqa: E402
    detect_url_filtered_form,
    enumerate_param_urls,
    _is_placeholder_option,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Mirrors hoa-usa.com's form structure (trimmed). The real page also has
# four POST gravity-forms with state selects; we include one of those
# below to test discrimination.
HOA_USA_LIKE_HTML = """
<html><body>
    <!-- The real directory form: GET, single select, 50 options. -->
    <form action="/management-directory/?state=Massachusetts#directory" method="get">
        <select name="state" id="state" required>
            <option value="">Select Your State</option>
            <option value="Alabama">Alabama</option>
            <option value="Alaska">Alaska</option>
            <option value="Arizona">Arizona</option>
            <option value="Arkansas">Arkansas</option>
            <option value="California">California</option>
            <option value="Colorado">Colorado</option>
            <option value="Connecticut">Connecticut</option>
            <option value="Delaware">Delaware</option>
            <option value="Florida">Florida</option>
            <option value="Georgia">Georgia</option>
            <option value="Hawaii">Hawaii</option>
            <option value="Idaho">Idaho</option>
            <option value="Massachusetts" selected="selected">Massachusetts</option>
            <option value="Wyoming">Wyoming</option>
        </select>
        <button type="submit">Search</button>
    </form>

    <!-- A gravity form with method=post and a state select. Should be REJECTED. -->
    <form action="/management-directory/" method="post" id="gform_7">
        <input name="input_1" type="text" placeholder="FULL NAME"/>
        <select name="input_2">
            <option value="" selected>SELECT STATE</option>
            <option value="Alabama">Alabama</option>
            <option value="Alaska">Alaska</option>
            <option value="Arizona">Arizona</option>
            <option value="Massachusetts">Massachusetts</option>
            <option value="Wyoming">Wyoming</option>
        </select>
        <input type="submit" value="Submit"/>
    </form>
</body></html>
"""

# Site-wide search bar — GET method but text input, no select.
SITE_SEARCH_ONLY_HTML = """
<html><body>
    <form action="/" method="get">
        <input type="search" name="s" placeholder="Search the site..."/>
        <button>Go</button>
    </form>
</body></html>
"""

# GET form with a select that has too few options (probably not a filter).
SHORT_SELECT_HTML = """
<html><body>
    <form action="/results" method="get">
        <select name="sort">
            <option value="">Default</option>
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
        </select>
        <button>Apply</button>
    </form>
</body></html>
"""

# JS-populated select — empty options in static HTML.
JS_POPULATED_HTML = """
<html><body>
    <form action="/search" method="get">
        <select name="category" id="categories"></select>
        <button>Search</button>
    </form>
    <script>fillCategories('#categories', [...]);</script>
</body></html>
"""

# Multiple GET forms — one with select matching URL param, one without.
# Detector should prefer the URL-param-matching one.
MULTI_FORM_HTML = """
<html><body>
    <form action="/blog" method="get">
        <select name="topic">
            <option value="news">News</option>
            <option value="reviews">Reviews</option>
            <option value="tutorials">Tutorials</option>
            <option value="opinion">Opinion</option>
            <option value="releases">Releases</option>
            <option value="interviews">Interviews</option>
        </select>
        <button>Filter</button>
    </form>
    <form action="/find-a-doctor" method="get">
        <select name="state">
            <option value="">Select State</option>
            <option value="AL">Alabama</option>
            <option value="AK">Alaska</option>
            <option value="AZ">Arizona</option>
            <option value="CA">California</option>
            <option value="NY">New York</option>
        </select>
        <button>Search</button>
    </form>
</body></html>
"""


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

def test(name, condition, detail=""):
    status = "OK  " if condition else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def run_detection_tests():
    print("=== Detection tests ===")
    passed = 0
    total = 0

    # 1. HOA-USA-like fixture
    plan = detect_url_filtered_form(
        HOA_USA_LIKE_HTML,
        "https://hoa-usa.com/management-directory/?state=Massachusetts",
    )
    total += 1
    passed += test(
        "Detects HOA-USA-style GET form",
        plan is not None and plan["param"] == "state",
        f"plan={plan and plan.get('param')}",
    )
    total += 1
    passed += test(
        "  Extracts 14 state options (placeholder excluded)",
        plan and len(plan["values"]) == 14,
        f"got {plan and len(plan['values'])} values",
    )
    total += 1
    passed += test(
        "  Builds template URL correctly",
        plan and plan["template_url"] == "https://hoa-usa.com/management-directory/?state={value}",
        f"template={plan and plan['template_url']}",
    )
    total += 1
    passed += test(
        "  Strips query/fragment from action",
        plan and plan["form_action"] == "https://hoa-usa.com/management-directory/",
    )
    total += 1
    passed += test(
        "  Rejects the sibling gravity POST form's state select",
        plan and plan["param"] == "state" and "input_2" not in plan["template_url"],
    )

    # 2. Negative case: site-wide search only (no select)
    plan = detect_url_filtered_form(SITE_SEARCH_ONLY_HTML, "https://example.com/")
    total += 1
    passed += test("Rejects search-only page (no <select>)", plan is None)

    # 3. Negative case: short select (sort dropdown)
    plan = detect_url_filtered_form(SHORT_SELECT_HTML, "https://example.com/results")
    total += 1
    passed += test("Rejects sort dropdown with 2 options", plan is None)

    # 4. Negative case: JS-populated select
    plan = detect_url_filtered_form(JS_POPULATED_HTML, "https://example.com/search")
    total += 1
    passed += test("Rejects empty (JS-populated) select", plan is None)

    # 5. Multi-form preference — URL-param-match wins
    plan = detect_url_filtered_form(
        MULTI_FORM_HTML, "https://example.com/find-a-doctor?state=CA"
    )
    total += 1
    passed += test(
        "Prefers select whose name matches a URL query param",
        plan and plan["param"] == "state",
        f"chose param={plan and plan['param']}",
    )

    # 6. Multi-form fallback — no URL match, pick the larger select
    plan = detect_url_filtered_form(MULTI_FORM_HTML, "https://example.com/")
    total += 1
    passed += test(
        "Falls back to larger select when no URL param matches",
        plan and plan["param"] == "topic",
        f"chose param={plan and plan['param']}",
    )

    # 7. Placeholder helper sanity
    total += 1
    passed += test(
        "Placeholder helper recognizes 'Select Your State'",
        _is_placeholder_option("", "Select Your State"),
    )
    total += 1
    passed += test(
        "Placeholder helper does NOT flag 'California'",
        not _is_placeholder_option("California", "California"),
    )

    print(f"\n  {passed}/{total} detection tests passed")
    return passed == total


# ---------------------------------------------------------------------------
# Live end-to-end test against hoa-usa.com
# ---------------------------------------------------------------------------

def run_live_test():
    print("\n=== Live test: hoa-usa.com ===")
    print("Fetching landing page to discover the form...")

    from Phase2Bot.page_fetcher import fetch_page
    soup, final_url = fetch_page("https://hoa-usa.com/management-directory/")
    if soup is None:
        print("  FAIL — couldn't fetch landing page; skipping live test")
        return False

    html = str(soup)
    print(f"  Got {len(html)} bytes from {final_url}")

    plan = detect_url_filtered_form(html, final_url or "https://hoa-usa.com/management-directory/")
    if plan is None:
        print("  FAIL — detector did NOT recognize the form on the real page")
        return False

    print(f"  Detected param='{plan['param']}', {len(plan['values'])} values")
    print(f"  Template: {plan['template_url']}")

    if len(plan["values"]) < 40:
        print(f"  FAIL — expected ~50 states, got {len(plan['values'])}")
        return False

    # Enumerate a small sample (3 states) to validate the fetch pipeline
    # without hammering the server for a full 50 in a smoke test.
    sample_values = ["Massachusetts", "California", "Texas"]
    print(f"\n  Enumerating sample: {sample_values}")
    t0 = time.time()
    fetched = enumerate_param_urls(plan["template_url"], sample_values,
                                    max_workers=3)
    elapsed = time.time() - t0
    print(f"  Fetched {len(fetched)}/{len(sample_values)} in {elapsed:.1f}s")

    ok = True
    for f in fetched:
        member_marker = "hoa-management-directory-result"
        count = f["html"].count(member_marker)
        # Each member appears once in the result row class; ~5-40 per state
        ok_count = count >= 3
        ok = ok and ok_count
        print(f"  {f['value']:>15}: {count:>3} member rows  "
              f"[{'OK' if ok_count else 'FAIL'}]")
    return ok


# ---------------------------------------------------------------------------
# Cache-aware integration test (mocks Playwright's page object)
# ---------------------------------------------------------------------------

class _MockPage:
    """Stand-in for a Playwright page — just needs `url` and `content()`."""
    def __init__(self, html, url):
        self._html = html
        self.url = url

    def content(self):
        return self._html


def run_cache_integration_test():
    print("\n=== Cache-aware integration test ===")
    from url_enumeration import try_url_enumeration_cached
    from cache import get_cached_url_template, _selector_cache

    domain = "test_hoa-usa_com"  # use a test-prefixed key so we don't pollute real cache
    link = "https://hoa-usa.com/management-directory/?state=Massachusetts"

    # Clean slate
    _selector_cache.pop(f"url_enum_{domain}", None)

    page = _MockPage(HOA_USA_LIKE_HTML, link)

    # 1. Cache miss → detect → cache → enumerate (will fail to fetch since
    #    these are fake URLs against hoa-usa.com but they'll return REAL data
    #    since the template was built from the real path)
    print("  First call (cache miss, will detect from fixture HTML)...")
    results = []
    ok = try_url_enumeration_cached(page, domain, link, results)
    test("First call returns True", ok)
    test(
        "First call cached the plan",
        get_cached_url_template(domain) is not None,
    )
    test(
        "First call fetched at least some states",
        len(results) > 0,
        f"fetched {len(results)} pages",
    )

    # 2. Cache hit → no detection needed → enumerate directly
    print("\n  Second call (cache hit, skips detection)...")
    page2 = _MockPage("<html></html>", link)  # empty page — should not matter
    results2 = []
    ok2 = try_url_enumeration_cached(page2, domain, link, results2)
    test("Second call returns True via cache", ok2)
    test(
        "Second call fetched without needing fixture HTML",
        len(results2) > 0,
        f"fetched {len(results2)} pages",
    )

    # Cleanup — pop from memory AND persist so the disk cache stays clean
    from cache import save_selector_cache
    _selector_cache.pop(f"url_enum_{domain}", None)
    save_selector_cache()


# ---------------------------------------------------------------------------
# Full 51-state enumeration — proves the scale claim
# ---------------------------------------------------------------------------

def run_full_enumeration_test():
    print("\n=== Full 51-state enumeration (~25s with rate limiting) ===")
    from Phase2Bot.page_fetcher import fetch_page
    from url_enumeration import detect_url_filtered_form, enumerate_param_urls

    soup, final_url = fetch_page("https://hoa-usa.com/management-directory/")
    if soup is None:
        print("  SKIP — couldn't fetch landing page")
        return False

    plan = detect_url_filtered_form(
        str(soup),
        final_url or "https://hoa-usa.com/management-directory/",
    )
    if plan is None:
        print("  FAIL — detection broke")
        return False

    t0 = time.time()
    fetched = enumerate_param_urls(
        plan["template_url"], plan["values"], max_workers=8,
    )
    elapsed = time.time() - t0

    total_rows = sum(
        f["html"].count("hoa-management-directory-result") for f in fetched
    )
    states_with_data = sum(
        1 for f in fetched
        if f["html"].count("hoa-management-directory-result") >= 3
    )

    print(f"  Fetched {len(fetched)}/{len(plan['values'])} states in {elapsed:.1f}s")
    print(f"  Total member-row markers: {total_rows}")
    print(f"  States with >=3 listings: {states_with_data}")
    print(f"  Avg per state: {total_rows / max(len(fetched), 1):.1f}")

    # Compare to baseline: browser flow would be ~10s/state * 51 = 510s.
    speedup = (10 * len(plan["values"])) / max(elapsed, 0.1)
    print(f"  Speedup vs ~10s/state browser baseline: ~{speedup:.0f}x")

    ok = len(fetched) >= 45 and total_rows > 500
    test("Full enumeration produced complete data",
         ok, f"fetched={len(fetched)}, rows={total_rows}")
    return ok


if __name__ == "__main__":
    detect_ok = run_detection_tests()
    live_ok = run_live_test()
    run_cache_integration_test()
    full_ok = run_full_enumeration_test()
    print()
    print(f"Detection:  {'OK' if detect_ok else 'FAIL'}")
    print(f"Live:       {'OK' if live_ok else 'FAIL'}")
    print(f"Full enum:  {'OK' if full_ok else 'FAIL'}")
    sys.exit(0 if (detect_ok and live_ok and full_ok) else 1)
