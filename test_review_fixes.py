"""Validation suite for the 2026-07 review fixes.

Run:  python3 test_review_fixes.py            (pure-Python tests only)
      python3 test_review_fixes.py --browser  (also run Playwright fixture tests)

Covers:
  Fix 1  count_visible_results honest counting + Enter→button submit fallback
  Fix 2  pagination tail-hash change detection + per-letter alphabet capture
  Fix 3  classless table/list card detection, name-dominant validation,
         scoped label-prefix stripping, bare-tag card_selector override
  Fix 4  preflight js_rendered pass-through, classifier routing, Bing fallback
  Fix 5  deterministic location filter
  QW     member-shaped pagination gate, JSON-LD tier, launch helper,
         login_callback plumbing
"""

import json
import os
import sys
import threading

os.environ["SCRAPER_HEADLESS"] = "1"  # fixture tests never need a window

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Bot"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup  # noqa: E402

_FAILURES = []
_PASSES = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASSES
    if cond:
        _PASSES += 1
        print(f"  PASS  {name}")
    else:
        _FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


# ────────────────────────────────────────────────────────────────────
#  Fix 3 — extraction layer
# ────────────────────────────────────────────────────────────────────

def test_classless_table_detection():
    print("\n[Fix 3] classless <table> card detection")
    import html_parser

    rows = "\n".join(
        f"<tr><td>Acme Company {i:02d}</td><td>(206) 555-01{i:02d}</td></tr>"
        for i in range(12)
    )
    html = f"""<html><body>
      <h1>Member List</h1>
      <table id="members"><tr><th>Name</th><th>Phone</th></tr>{rows}</table>
    </body></html>"""

    sample, selector = html_parser.extract_sample_html(html)
    check("classless table produces a card selector", selector is not None,
          f"selector={selector!r}")
    check("selector is container-scoped (not bare 'tr')",
          bool(selector) and selector != "tr" and "#members" in (selector or ""),
          f"selector={selector!r}")
    if selector:
        matched = BeautifulSoup(html, "html.parser").select(selector)
        check("selector matches the data rows", len(matched) >= 12,
              f"matched={len(matched)}")
    check("sample contains row HTML", "Acme Company 00" in sample)

    # Regression: classed cards must still win via Strategy 1
    cards = "\n".join(
        f'<div class="member-card"><h3>Firm {i}</h3><a href="/m/{i}">site</a>'
        f"<p>Some description text that is long enough to pass the filter "
        f"for real member cards on page {i}.</p><span>(206) 555-02{i:02d}</span></div>"
        for i in range(6)
    )
    _, classed_sel = html_parser.extract_sample_html(f"<html><body>{cards}</body></html>")
    check("classed cards still use class selector", "member-card" in (classed_sel or ""),
          f"selector={classed_sel!r}")


def test_selector_for_container():
    print("\n[Fix 3] _selector_for_container")
    import html_parser

    soup = BeautifulSoup(
        '<div id="wrap"><table><tbody><tr><td>x</td></tr></tbody></table></div>'
        '<ul class="member-list"><li>a</li></ul>'
        '<div><div><ol><li>b</li></ol></div></div>',
        "html.parser")
    tbody = soup.find("tbody")
    check("walks up to #id", html_parser._selector_for_container(tbody) == "div#wrap > table > tbody",
          repr(html_parser._selector_for_container(tbody)))
    ul = soup.find("ul")
    check("uses class when present", html_parser._selector_for_container(ul) == "ul.member-list",
          repr(html_parser._selector_for_container(ul)))
    ol = soup.find("ol")
    sel = html_parser._selector_for_container(ol)
    check("plain-tag path still returns something", sel is not None and "ol" in sel, repr(sel))


def test_extraction_validation():
    print("\n[Fix 3] is_extraction_valid name-dominant pass")
    import html_parser

    name_only = [{"company_name": f"Firm {i}", "description": None, "category": None,
                  "website": None, "phone": None} for i in range(20)]
    check("name-only extraction (100% names) is valid",
          html_parser.is_extraction_valid(name_only))

    sparse = [{"company_name": None, "description": None, "category": None,
               "website": None, "phone": None} for _ in range(20)]
    check("all-null extraction still invalid",
          not html_parser.is_extraction_valid(sparse))

    mixed = [{"company_name": f"F{i}" if i < 5 else None, "description": None,
              "category": None, "website": None, "phone": None} for i in range(20)]
    check("25%-names extraction still invalid",
          not html_parser.is_extraction_valid(mixed))

    rich = [{"company_name": f"F{i}", "description": "d", "category": "c",
             "website": "w", "phone": "p"} for i in range(5)]
    check("field-coverage path unchanged (rich data valid)",
          html_parser.is_extraction_valid(rich))

    two_names = [{"company_name": "A"}, {"company_name": "B"}]
    check("tiny name-only list (<3) not auto-valid",
          not html_parser.is_extraction_valid(two_names))


def test_label_prefix_regex():
    print("\n[Fix 3] scoped label-prefix stripping")
    import html_parser

    r = html_parser._LABEL_PREFIX_RE
    check("strips 'Phone:'", r.sub("", "Phone: (206) 555-1234") == "(206) 555-1234")
    check("strips 'E-mail:'", r.sub("", "E-mail: a@b.com") == "a@b.com")
    check("preserves 'Studio 54: NYC'", r.sub("", "Studio 54: NYC") == "Studio 54: NYC")
    check("preserves 'Note: open late'", r.sub("", "Note: open late") == "Note: open late")

    # End-to-end through apply_selectors
    html = ('<div class="card"><h3 class="nm">Studio 54: NYC</h3>'
            '<span class="ph">Phone: (206) 555-0101</span></div>')
    members = html_parser.apply_selectors(html, {
        "entity_type": "business", "card_selector": "div.card",
        "company_name": "h3.nm", "phone": "span.ph",
    })
    check("apply_selectors keeps colon name", members[0]["company_name"] == "Studio 54: NYC",
          repr(members[0]["company_name"]))
    check("apply_selectors strips phone label", members[0]["phone"] == "(206) 555-0101",
          repr(members[0]["phone"]))


def test_bare_tag_override():
    print("\n[Fix 3] learn_selectors bare-tag card_selector override")
    import html_parser

    canned = {"entity_type": "business", "card_selector": "tr",
              "company_name": "td:nth-of-type(1)", "phone": "td:nth-of-type(2)",
              "description": None, "category": None, "website": None, "fax": None,
              "street_address": None, "mailing_address": None,
              "contact_card": None, "contact_name": None, "contact_email": None}
    prompts = []

    real_ask, real_set = html_parser.ask, html_parser.set_cached_selectors
    html_parser.ask = lambda prompt, max_tokens=1000: (prompts.append(prompt) or json.dumps(canned))
    html_parser.set_cached_selectors = lambda domain, sel: None  # don't touch real cache
    try:
        rows = "\n".join(
            f"<tr><td>Acme Company {i:02d}</td><td>(206) 555-01{i:02d}</td></tr>"
            for i in range(12))
        html = f'<html><body><table id="members">{rows}</table></body></html>'
        selectors = html_parser.learn_selectors(html, "test_domain_fake")
    finally:
        html_parser.ask, html_parser.set_cached_selectors = real_ask, real_set

    check("prompt carries the detected-selector hint",
          any("table#members > tr" in p for p in prompts))
    check("bare 'tr' overridden with scoped selector",
          selectors.get("card_selector") == "table#members > tr",
          repr(selectors.get("card_selector")))


def test_jsonld_extraction():
    print("\n[QW] JSON-LD member extraction")
    import html_parser

    html = """<html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"WebSite","name":"Chamber Site","url":"https://chamber.example"}
    </script>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"LocalBusiness","name":"Acme Plumbing","telephone":"(206) 555-0101",
       "address":{"@type":"PostalAddress","streetAddress":"1 Main St","addressLocality":"Seattle","addressRegion":"WA","postalCode":"98101"},
       "url":"https://acme.example"},
      {"@type":["Dentist","LocalBusiness"],"name":"Bright Smiles","telephone":"206-555-0102","email":"mailto:info@brightsmiles.example"}
    ]}
    </script>
    <script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[
      {"@type":"ListItem","position":1,"item":{"@type":"LocalBusiness","name":"Carter Roofing","telephone":"(206) 555-0103"}}
    ]}
    </script></head><body></body></html>"""

    members = html_parser.extract_jsonld_members(html)
    names = {m["company_name"] for m in members}
    check("extracts 3 entities", len(members) == 3, f"got {len(members)}: {names}")
    check("WebSite blob skipped", "Chamber Site" not in names)
    acme = next((m for m in members if m["company_name"] == "Acme Plumbing"), {})
    check("PostalAddress flattened",
          acme.get("street_address") == "1 Main St, Seattle, WA, 98101",
          repr(acme.get("street_address")))
    bright = next((m for m in members if m["company_name"] == "Bright Smiles"), {})
    check("mailto: stripped from email",
          bright.get("contacts") == [{"name": None, "email": "info@brightsmiles.example"}],
          repr(bright.get("contacts")))
    check("specific @type becomes category", bright.get("category") == "Dentist",
          repr(bright.get("category")))

    lonely = html_parser.extract_jsonld_members(
        '<script type="application/ld+json">{"@type":"LocalBusiness","name":"Solo","telephone":"1"}</script>')
    check("single self-blob still extracted by fn (gate lives in parse_member_html)",
          len(lonely) == 1)


def test_parse_member_html_end_to_end():
    print("\n[Fix 3+QW] parse_member_html end-to-end (mocked LLM)")
    import html_parser

    canned = {"entity_type": "business", "card_selector": "tr",
              "company_name": "td:nth-of-type(1)", "phone": "td:nth-of-type(2)",
              "description": None, "category": None, "website": None, "fax": None,
              "street_address": None, "mailing_address": None,
              "contact_card": None, "contact_name": None, "contact_email": None}
    real = (html_parser.ask, html_parser.set_cached_selectors,
            html_parser.get_cached_selectors)
    ask_calls = []
    html_parser.ask = lambda p, max_tokens=1000: (ask_calls.append(1) or json.dumps(canned))
    html_parser.set_cached_selectors = lambda d, s: None
    html_parser.get_cached_selectors = lambda d: None
    try:
        # 1. Classless table: cache miss → no JSON-LD → learn (mocked) →
        #    bare-tag override → apply → name-dominant validation passes.
        rows = "\n".join(
            f"<tr><td>Acme Company {i:02d}</td><td>(206) 555-01{i:02d}</td></tr>"
            for i in range(12))
        html = (f'<html><body><table id="members">'
                f"<tr><th>Name</th><th>Phone</th></tr>{rows}</table></body></html>")
        members = html_parser.parse_member_html(html, domain="fake_classless_test")
        named = [m for m in members if m.get("company_name")]
        check("classless table extracts 12 named members end-to-end",
              len(named) == 12, f"named={len(named)} of {len(members)}")
        check("phones extracted alongside names",
              sum(1 for m in named if m.get("phone")) == 12)
        check("LLM was called exactly once", len(ask_calls) == 1,
              f"calls={len(ask_calls)}")

        # 2. JSON-LD page: returns before any LLM call.
        ask_calls.clear()
        html_parser.ask = lambda p, max_tokens=1000: (_ for _ in ()).throw(
            AssertionError("LLM should not be called on a JSON-LD page"))
        blobs = "".join(
            '<script type="application/ld+json">'
            + json.dumps({"@type": "LocalBusiness", "name": f"Biz {i}",
                          "telephone": f"(206) 555-04{i:02d}"})
            + "</script>" for i in range(4))
        members = html_parser.parse_member_html(
            f"<html><head>{blobs}</head><body></body></html>",
            domain="fake_jsonld_test")
        check("JSON-LD page short-circuits with members, zero LLM calls",
              len(members) == 4, f"members={len(members)}")
    finally:
        (html_parser.ask, html_parser.set_cached_selectors,
         html_parser.get_cached_selectors) = real


# ────────────────────────────────────────────────────────────────────
#  Fix 5 — location filter
# ────────────────────────────────────────────────────────────────────

def test_location_filter():
    print("\n[Fix 5] deterministic location filter")
    from intent_record_filter import _filter_by_location

    intent = {"location_states": ["WA"]}
    records = [
        {"company_name": "In-state", "street_address": "123 Pine St, Seattle, WA 98101"},
        {"company_name": "Out-of-state", "street_address": "500 Elm St, Portland, OR 97201"},
        {"company_name": "No address"},
        {"company_name": "Court not Connecticut", "street_address": "123 Main Ct, Springfield"},
        {"company_name": "Trailing state", "street_address": "9 Oak Ave, Bend, OR"},
    ]
    kept, dropped = _filter_by_location(records, intent)
    names = {r["company_name"] for r in kept}
    check("in-state kept", "In-state" in names)
    check("out-of-state (state+zip) dropped", "Out-of-state" not in names)
    check("no-address kept (fail-open)", "No address" in names)
    check("'Main Ct' not parsed as Connecticut", "Court not Connecticut" in names)
    check("trailing ', OR' dropped", "Trailing state" not in names)
    check("drop count", dropped == 2, f"dropped={dropped}")

    kept2, dropped2 = _filter_by_location(records, {"location_states": []})
    check("no intent states → no drops", dropped2 == 0 and len(kept2) == len(records))


# ────────────────────────────────────────────────────────────────────
#  Fix 4 — preflight / classifier / Bing fallback
# ────────────────────────────────────────────────────────────────────

def test_preflight_js_rendered():
    print("\n[Fix 4] preflight js_rendered pass-through")
    from DiscoveryBot import preflight

    preflight.LLM_SANITY_CHECK_ENABLED = False  # keep tests offline

    spa = BeautifulSoup(
        "<html><head>" + '<script src="/a.js"></script>' * 3 +
        '</head><body><div id="root"></div></body></html>', "html.parser")
    passed, reason = preflight._qualify_soup(spa, url="https://spa.example")
    check("SPA shell (id=root) passes as js_rendered",
          passed and reason == "js_rendered", f"({passed}, {reason})")

    heavy = BeautifulSoup(
        "<html><head>" + '<script src="/b.js"></script>' * 9 +
        "</head><body><div>hi</div></body></html>", "html.parser")
    passed, reason = preflight._qualify_soup(heavy, url="https://heavy.example")
    check("script-heavy shell passes (raw HTML captured before script strip)",
          passed and reason == "js_rendered", f"({passed}, {reason})")

    thin = BeautifulSoup("<html><body><p>hello</p></body></html>", "html.parser")
    passed, reason = preflight._qualify_soup(thin, url="https://thin.example")
    check("genuinely thin page still rejected",
          not passed and reason == "thin_content", f"({passed}, {reason})")


def test_classifier_js_route():
    print("\n[Fix 4] classifier routes js_rendered to Phase 1")
    from DiscoveryBot import classifier

    out = classifier.classify_one({
        "url": "https://spa.example/directory",
        "soup": BeautifulSoup("<html></html>", "html.parser"),
        "js_rendered": True,
    })
    check("classified DIRECTORY", out["classification"] == "DIRECTORY")
    check("needs_navigation set", out.get("needs_navigation") is True)

    out2 = classifier.classify_one({
        "url": "https://usnews.com/whatever",
        "soup": BeautifulSoup("<html></html>", "html.parser"),
        "js_rendered": True,
    })
    check("hard-skip still wins over js_rendered", out2["classification"] == "REJECT")


def test_bing_fallback():
    print("\n[Fix 4] Bing fallback parsing + DDG routing")
    import base64
    from Phase2Bot import page_fetcher

    target = "https://example.com/directory"
    wrapped = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    canned = f"""<html><body><ol id="b_results">
      <li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&&p=xyz&u=a1{wrapped}&ntb=1">Example Directory</a></h2>
        <div class="b_caption"><p>Member directory of examples.</p></div></li>
      <li class="b_algo"><h2><a href="https://direct.example/members">Direct Result</a></h2>
        <div class="b_caption"><p>Another snippet.</p></div></li>
      <li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=notbase64"> Broken</a></h2></li>
    </ol></body></html>"""

    class FakeResp:
        status_code = 200
        text = canned

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    real_get_session = page_fetcher._get_session
    real_sleep = page_fetcher.time.sleep
    page_fetcher._get_session = lambda browser: FakeSession()
    page_fetcher.time.sleep = lambda s: None
    try:
        results = page_fetcher._bing_fetch_results("test query")
    finally:
        page_fetcher._get_session = real_get_session
        page_fetcher.time.sleep = real_sleep

    hrefs = [r["href"] for r in results]
    check("bing /ck/a redirect unwrapped", target in hrefs, str(hrefs))
    check("direct href kept", "https://direct.example/members" in hrefs, str(hrefs))
    check("unparseable redirect dropped", len(results) == 2, str(hrefs))
    check("snippet extracted",
          results and results[0]["snippet"] == "Member directory of examples.")

    # DDG → Bing routing when the kill switch has tripped
    sentinel = [{"href": "https://bing-sentinel.example", "title": "", "snippet": ""}]
    real_bing = page_fetcher._bing_fetch_results
    page_fetcher._bing_fetch_results = lambda q: sentinel
    try:
        page_fetcher._search_stopped = True
        routed = page_fetcher._ddg_fetch_results("anything")
    finally:
        page_fetcher._bing_fetch_results = real_bing
        page_fetcher.reset_search_state()
    check("_ddg_fetch_results routes to Bing after block", routed == sentinel)
    check("reset_search_state clears the flag", page_fetcher._search_stopped is False)


# ────────────────────────────────────────────────────────────────────
#  Quick wins — pagination JSON gate, plumbing
# ────────────────────────────────────────────────────────────────────

def test_member_shaped_gate():
    print("\n[QW] member-shaped pagination gate")
    import browser as bot_browser

    members = [{"Name": f"Co {i}", "Phone": "1", "City": "X"} for i in range(60)]
    i18n = [{"key": f"k{i}", "value": f"v{i}"} for i in range(60)]
    airtable = [{"id": f"rec{i}", "fields": {"Name": f"Co {i}"}} for i in range(5)]

    check("member list detected", bot_browser._looks_like_member_records(members))
    check("i18n bundle rejected", not bot_browser._looks_like_member_records(i18n))
    check("airtable shape detected", bot_browser._looks_like_member_records(airtable))
    check("string list rejected", not bot_browser._looks_like_member_records(["a", "b", "c"]))
    check("short list rejected", not bot_browser._looks_like_member_records(members[:2]))


def test_plumbing_signatures():
    print("\n[QW] signature / plumbing checks")
    import inspect
    import main as bot_main
    import navigator as bot_navigator
    import config as bot_config

    sig = inspect.signature(bot_main.scrape_directory)
    check("scrape_directory accepts login_callback", "login_callback" in sig.parameters)

    sig2 = inspect.signature(bot_navigator.trigger_search)
    check("trigger_search accepts html_collector", "html_collector" in sig2.parameters)

    sig3 = inspect.signature(bot_navigator.search_all_letters)
    check("search_all_letters accepts html_collector", "html_collector" in sig3.parameters)

    check("launch_browser helper exists", callable(getattr(bot_config, "launch_browser", None)))


# ────────────────────────────────────────────────────────────────────
#  Browser fixture tests (Playwright, file:// pages, headless)
# ────────────────────────────────────────────────────────────────────

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".test_fixtures")


def _write_fixture(name: str, html: str) -> str:
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    path = os.path.join(FIXTURE_DIR, name)
    with open(path, "w") as f:
        f.write(html)
    return "file://" + path


def _promo_and_table_fixture() -> str:
    promo = "\n".join(
        f'<div class="card promo">Featured partner spotlight number {i} here</div>'
        for i in range(3))
    rows = "\n".join(
        f"<tr><td>Acme Company {i:02d}</td><td>(206) 555-01{i:02d}</td></tr>"
        for i in range(12))
    return _write_fixture("count_fixture.html", f"""<html><body>
      {promo}
      <div class="card hidden-card" style="display:none">Hidden card that should not count</div>
      <table><tbody>{rows}</tbody></table>
    </body></html>""")


def _click_only_search_fixture() -> str:
    results = json.dumps([
        f"Acme Search Result {i:02d} — (206) 555-03{i:02d}" for i in range(5)
    ])
    return _write_fixture("search_fixture.html", f"""<html><body>
      <input id="q" type="search" placeholder="Search members">
      <button id="go" type="button">Search</button>
      <div id="out"></div>
      <script>
        // Click-only handler — Enter deliberately does nothing (React-style UI)
        document.getElementById('go').addEventListener('click', () => {{
          document.getElementById('out').innerHTML = {results}
            .map(t => '<div class="result-item">' + t + '</div>').join('');
        }});
      </script>
    </body></html>""")


def _spa_pagination_fixture() -> str:
    header = " ".join(f"static header navigation word{i}" for i in range(120))
    pages = {
        1: "".join(f'<div class="result-item">Page1 Company {i:02d} — (206) 555-11{i:02d}</div>' for i in range(8)),
        2: "".join(f'<div class="result-item">Page2 Company {i:02d} — (206) 555-22{i:02d}</div>' for i in range(8)),
        3: "".join(f'<div class="result-item">Page3 Company {i:02d} — (206) 555-33{i:02d}</div>' for i in range(8)),
    }
    return _write_fixture("pagination_fixture.html", f"""<html><body>
      <header><p>{header}</p></header>
      <div id="results">{pages[1]}</div>
      <button type="button" onclick="go(2)">2</button>
      <button type="button" onclick="go(3)">3</button>
      <script>
        const PAGES = {json.dumps(pages)};
        function go(n) {{ document.getElementById('results').innerHTML = PAGES[n]; }}
      </script>
    </body></html>""")


def _alphabet_fixture() -> str:
    return _write_fixture("alphabet_fixture.html", """<html><body>
      <input id="q" type="search" placeholder="Search members">
      <div id="out">initial</div>
      <script>
        document.getElementById('q').addEventListener('keydown', e => {
          if (e.key === 'Enter') {
            document.getElementById('out').innerHTML =
              'Results for: ' + document.getElementById('q').value;
          }
        });
      </script>
    </body></html>""")


def run_browser_tests():
    from playwright.sync_api import sync_playwright
    import config as bot_config
    import navigator as bot_navigator
    import browser as bot_browser

    # Speed up fixture runs — file:// pages settle instantly.
    bot_navigator.NETWORK_IDLE_TIMEOUT = 500
    bot_navigator.PAGE_WAIT_AFTER_ACTION = 100
    bot_browser.NETWORK_IDLE_TIMEOUT = 500
    bot_browser.PAGE_WAIT_AFTER_ACTION = 100

    with sync_playwright() as pw:
        browser = bot_config.launch_browser(pw)
        page = browser.new_page()

        # --- Fix 1: count_visible_results ---
        print("\n[Fix 1/browser] count_visible_results")
        page.goto(_promo_and_table_fixture())
        count = bot_navigator.count_visible_results(page)
        check("table rows win over 3 promo cards (old code returned 3)",
              count >= 12, f"count={count}")

        # --- Fix 1: Enter→button submit fallback ---
        print("\n[Fix 1/browser] click-only search submit fallback")
        page.goto(_click_only_search_fixture())
        visible = bot_navigator.try_search_query(page, page.locator("#q"), "acme")
        check("click-only search UI produces results via button fallback",
              visible >= 5, f"visible={visible}")

        # --- Fix 2: SPA pagination advances past a static header ---
        print("\n[Fix 2/browser] SPA pagination tail-hash detection")
        page.goto(_spa_pagination_fixture())
        done = threading.Event()
        pages_loaded = bot_browser.handle_pagination(page, done)
        body = page.inner_text("body")
        check("clicked through SPA pages (old code stopped at 0)",
              pages_loaded >= 2, f"pages_loaded={pages_loaded}")
        check("final page content reached", "Page3 Company 00" in body)

        # --- Fix 2: alphabet search captures HTML per letter ---
        print("\n[Fix 2/browser] per-letter HTML capture")
        page.goto(_alphabet_fixture())
        collector = []
        bot_navigator.search_all_letters(page, page.locator("#q"),
                                         html_collector=collector)
        check("36 pages captured (one per character)", len(collector) == 36,
              f"captured={len(collector)}")
        check("first capture is the 'a' results",
              collector and "Results for: a" in collector[0])
        check("last capture is the '9' results",
              collector and "Results for: 9" in collector[-1])

        browser.close()


# ────────────────────────────────────────────────────────────────────

def main():
    test_classless_table_detection()
    test_selector_for_container()
    test_extraction_validation()
    test_label_prefix_regex()
    test_bare_tag_override()
    test_jsonld_extraction()
    test_parse_member_html_end_to_end()
    test_location_filter()
    test_preflight_js_rendered()
    test_classifier_js_route()
    test_bing_fallback()
    test_member_shaped_gate()
    test_plumbing_signatures()

    if "--browser" in sys.argv:
        run_browser_tests()
    else:
        print("\n(skipping Playwright fixture tests — pass --browser to run them)")

    print(f"\n{'=' * 50}\n{_PASSES} passed, {len(_FAILURES)} failed")
    if _FAILURES:
        for f in _FAILURES:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
