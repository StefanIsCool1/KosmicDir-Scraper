"""Validation suite for the smart-navigation / fast-bail-out / debug-trace work.

Run:  python3 test_smart_discover.py            (pure-Python tests only)
      python3 test_smart_discover.py --browser  (also run Playwright fixture tests)

Covers:
  Debug   span/decision/save_report round-trip, disabled no-op
  Expand  ai_discover_listing_links candidate filtering + answer parsing
  Yield   _count_json_member_records member-list counting
  Fixture "Recently Added" landing (5 members) + city links in the NAV →
          AI sub-listing expansion crawls the city pages (the exact miss
          this work fixes: detect_category_links skips nav links)
  Fixture dead page (no member content) → fast bail-out decisions recorded,
          no pagination, quick exit
"""

import json
import os
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["SCRAPER_HEADLESS"] = "1"  # fixture tests never need a window

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Bot"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_FAILURES = []
_PASSES = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASSES
    if cond:
        _PASSES += 1
        print(f"  PASS  {name}")
    else:
        _FAILURES.append(f"{name}  {detail}")
        print(f"  FAIL  {name}  {detail}")


# ─────────────────────────────────────────────
#  1. Debug trace module
# ─────────────────────────────────────────────

def test_debug_module():
    print("\n[debug.py trace facility]")
    from debug import DebugLogger

    d = DebugLogger()
    d.enabled = False
    d.log("NAV", "should not be stored")
    d.decision("NAV", "nope")
    with d.span("NAV", "noop"):
        pass
    check("disabled logger stores nothing", d.entries == [])

    d.enabled = True
    d.reset()
    d.log("SEARCH", "found input", data={"n": 3})
    d.decision("PAGE", "skip pagination", "no member signal")
    with d.span("SCROLL", "probe"):
        time.sleep(0.05)

    kinds = [e.get("kind") for e in d.entries]
    check("action/decision/span entries recorded",
          kinds == ["action", "decision", "span"], f"kinds={kinds}")
    span_entry = d.entries[2]
    check("span carries duration", span_entry.get("duration_s", 0) >= 0.05,
          str(span_entry))
    dec_entry = d.entries[1]
    check("decision carries decision+reason",
          dec_entry.get("decision") == "skip pagination"
          and dec_entry.get("reason") == "no member signal")

    summary = d.get_summary()
    check("summary counts decisions", summary.get("decisions") == 1, str(summary))
    check("summary tracks span time",
          "SCROLL: probe" in summary.get("time_spent", {}), str(summary))

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "nested", "trace_debug.json")
        saved = d.save_report(path)
        check("save_report writes file", saved == path and os.path.isfile(path))
        with open(path) as f:
            report = json.load(f)
        check("report has summary + entries",
              "summary" in report and len(report["entries"]) == 3)

    d.enabled = False
    check("save_report no-op when disabled", d.save_report("/tmp/x.json") is None)


# ─────────────────────────────────────────────
#  2. ai_discover_listing_links (no browser — fake page + fake LLM)
# ─────────────────────────────────────────────

class FakePage:
    def __init__(self, url, links):
        self.url = url
        self._links = links

    def eval_on_selector_all(self, selector, js):
        return self._links

    def title(self):
        return "Contractor Directory"


def test_ai_discover_listing_links():
    print("\n[ai_discover_listing_links]")
    import navigator

    links = [
        {"text": "Home", "href": "https://dir.example.com/"},          # self
        {"text": "Dallas", "href": "https://dir.example.com/city/dallas"},
        {"text": "Houston", "href": "https://dir.example.com/city/houston"},
        {"text": "Austin", "href": "https://dir.example.com/city/austin"},
        {"text": "Email us", "href": "mailto:hi@example.com"},          # junk
        {"text": "Facebook", "href": "https://facebook.com/dir"},       # external
        {"text": "Bylaws", "href": "https://dir.example.com/bylaws.pdf"},  # file
        {"text": "Top", "href": "https://dir.example.com/#top"},        # fragment/self
    ]
    page = FakePage("https://dir.example.com/", links)

    captured = {}

    def fake_ask(prompt, max_tokens=1000):
        captured["prompt"] = prompt
        # Answer with the city link numbers exactly as a model would
        idxs = []
        for m in re.finditer(r"^(\d+)\. \[.*?\] → (\S+)", prompt, re.M):
            if "/city/" in m.group(2):
                idxs.append(m.group(1))
        return ", ".join(idxs) if idxs else "NONE"

    real_ask = navigator.ask
    navigator.ask = fake_ask
    try:
        picked = navigator.ai_discover_listing_links(page, visible_count=5)
        hrefs = [p["href"] for p in picked]
        check("picks all 3 city links",
              len(picked) == 3 and all("/city/" in h for h in hrefs), str(hrefs))
        check("junk links never reach the prompt",
              "mailto:" not in captured["prompt"]
              and "facebook.com" not in captured["prompt"]
              and "bylaws.pdf" not in captured["prompt"])
        check("prompt mentions visible count", "~5 member entries" in captured["prompt"])

        # NONE answer → []
        navigator.ask = lambda p, max_tokens=1000: "NONE"
        check("NONE answer returns []",
              navigator.ai_discover_listing_links(page, visible_count=0) == [])

        # Out-of-range + duplicate indexes are dropped (candidates after junk
        # filtering: 0=Dallas, 1=Houston, 2=Austin — 99 and 3 are out of range)
        navigator.ask = lambda p, max_tokens=1000: "1, 1, 2, 99, 3"
        picked = navigator.ai_discover_listing_links(page, visible_count=5)
        check("dedup + bounds-check AI indexes",
              [p["text"] for p in picked] == ["Houston", "Austin"], str(picked))

        # LLM failure → []
        def boom(p, max_tokens=1000):
            raise RuntimeError("api down")
        navigator.ask = boom
        check("LLM failure returns []",
              navigator.ai_discover_listing_links(page, visible_count=5) == [])

        # Fewer than 2 candidates → no LLM call at all
        tiny = FakePage("https://dir.example.com/", links[:1])
        navigator.ask = boom  # would raise if called
        check("<2 candidates skips the LLM",
              navigator.ai_discover_listing_links(tiny, visible_count=5) == [])
    finally:
        navigator.ask = real_ask


# ─────────────────────────────────────────────
#  3. _count_json_member_records
# ─────────────────────────────────────────────

def test_count_json_member_records():
    print("\n[_count_json_member_records]")
    import browser

    member = {"name": "Acme", "phone": "555", "city": "Dallas",
              "website": "a.com", "email": "x@a.com"}
    results = [
        {"url": "u1", "data": [member] * 5},                      # top-level list
        {"url": "u2", "data": {"Members": [member] * 4}},          # nested list
        {"url": "u3", "data": {"raw_html": "<html>..."}},          # html — ignored
        {"url": "u4", "data": [{"locale": "en"}] * 60},            # i18n junk — ignored
    ]
    n = browser._count_json_member_records(results)
    check("counts member-shaped lists only", n == 9, f"n={n}")
    check("empty results → 0", browser._count_json_member_records([]) == 0)


# ─────────────────────────────────────────────
#  4. Browser fixture tests (--browser)
# ─────────────────────────────────────────────

_CITIES = ["dallas", "houston", "austin", "elpaso", "plano", "frisco"]


def _member_card(name, phone):
    return (f'<div class="member-card"><h3>{name}</h3>'
            f'<p>Phone: {phone}</p><p>123 Main Street, Texas</p></div>')


def _landing_html():
    nav = "".join(f'<a href="/city/{c}">{c.title()}</a> ' for c in _CITIES)
    cards = "".join(_member_card(f"Recent Builder {i}", f"555-000{i}")
                    for i in range(5))
    return f"""<html><head><title>TX Contractor Directory</title></head><body>
<nav>{nav}<a href="/about-us">About</a></nav>
<h1>Member Directory — Recently Added</h1>
<div class="members">{cards}</div>
</body></html>"""


def _city_html(city):
    cards = "".join(_member_card(f"Acme {city.title()} {i}", f"555-1{i:03d}")
                    for i in range(4))
    return f"""<html><head><title>{city.title()} Members</title></head><body>
<nav><a href="/">Directory Home</a></nav>
<h1>Members in {city.title()}</h1>
<div class="members">{cards}</div>
</body></html>"""


def _dead_html():
    # Deliberately avoids every _DIRECTORY_CONTENT_KEYWORDS token and every
    # RESULT_COUNT/RESULT_LINK selector pattern — a page with nothing to scrape.
    return """<html><head><title>Blue Sky Consulting</title></head><body>
<nav><a href="/pricing">Pricing</a> <a href="/story">Our Story</a></nav>
<h1>We build great software</h1>
<p>Reach out via the form on our pricing page. We love shipping quality tools.</p>
</body></html>"""


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            body = _landing_html()
        elif path.startswith("/city/"):
            body = _city_html(path.rsplit("/", 1)[-1])
        elif path == "/dead":
            body = _dead_html()
        else:
            body = "<html><body><p>ok</p></body></html>"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _fake_ask_factory():
    """One fake LLM that answers every prompt shape capture_responses can send."""
    def fake_ask(prompt, max_tokens=1000):
        # ai_discover_listing_links prompt
        if "Reply with ONLY the link numbers" in prompt:
            idxs = []
            for m in re.finditer(r"^(\d+)\. \[.*?\] → (\S+)", prompt, re.M):
                if "/city/" in m.group(2):
                    idxs.append(m.group(1))
            return ", ".join(idxs) if idxs else "NONE"
        # ai_analyze_page (find_directory_url) prompt
        if "Is this already a directory" in prompt:
            return "NONE" if "/dead" in prompt else "STAY"
        # read_result_count prompt
        if "How many total results" in prompt:
            return "unknown"
        return "NONE"
    return fake_ask


def _run_capture(url):
    import navigator
    import browser
    from debug import debug
    from playwright.sync_api import sync_playwright

    real_ask = navigator.ask
    navigator.ask = _fake_ask_factory()
    debug.enabled = True
    debug.reset()
    t0 = time.time()
    try:
        with sync_playwright() as p:
            results, detail_urls = browser.capture_responses(
                p, url, mode="auto", login_callback=lambda page, domain: False)
    finally:
        navigator.ask = real_ask
    return results, detail_urls, time.time() - t0, list(debug.entries)


def test_fixture_expansion(base):
    print("\n[fixture: Recently Added landing + city links in nav]")
    results, detail_urls, elapsed, entries = _run_capture(f"{base}/")

    htmls = [r["data"]["raw_html"] for r in results
             if isinstance(r.get("data"), dict) and "raw_html" in r["data"]]
    check("captured landing + city pages",
          len(htmls) >= 1 + len(_CITIES), f"got {len(htmls)} HTML pages")
    combined = " ".join(htmls)
    missing = [c for c in _CITIES if f"Acme {c.title()} 2" not in combined]
    check("city members present in capture", not missing, f"missing={missing}")
    check("recently-added members also present", "Recent Builder 3" in combined)

    decisions = [e for e in entries if e.get("kind") == "decision"]
    check("expansion decision recorded",
          any("sub-listing" in e["message"] for e in decisions),
          str([e["message"] for e in decisions]))
    spans = [e["message"] for e in entries if e.get("kind") == "span"]
    check("expansion crawl span recorded",
          any("sub-listing crawl" in s for s in spans), str(spans))
    print(f"  (elapsed {elapsed:.1f}s)")


def test_fixture_dead_page(base):
    print("\n[fixture: dead page → fast bail-out]")
    results, detail_urls, elapsed, entries = _run_capture(f"{base}/dead")

    htmls = [r for r in results
             if isinstance(r.get("data"), dict) and "raw_html" in r["data"]]
    check("no HTML captured from dead page", len(htmls) == 0, f"got {len(htmls)}")
    check("no detail urls", detail_urls == [])

    decisions = [e["message"] for e in entries if e.get("kind") == "decision"]
    check("no-member-signal decision recorded",
          any("no member signal" in m for m in decisions), str(decisions))
    check("pagination skipped",
          any("skip pagination" in m for m in decisions), str(decisions))
    check("back-out decision recorded",
          any("back out early" in m for m in decisions), str(decisions))
    check("dead page exits fast", elapsed < 60, f"elapsed={elapsed:.1f}s")
    print(f"  (elapsed {elapsed:.1f}s)")


def main():
    test_debug_module()
    test_ai_discover_listing_links()
    test_count_json_member_records()

    if "--browser" in sys.argv:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            test_fixture_expansion(base)
            test_fixture_dead_page(base)
        finally:
            server.shutdown()
    else:
        print("\n(skipping browser fixture tests — pass --browser to run them)")

    print("\n" + "=" * 50)
    print(f"{_PASSES} passed, {len(_FAILURES)} failed")
    for f in _FAILURES:
        print(f"  FAILED: {f}")
    sys.exit(1 if _FAILURES else 0)


if __name__ == "__main__":
    main()
