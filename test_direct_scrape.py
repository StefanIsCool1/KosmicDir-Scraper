"""End-to-end checks for the Playground direct-scrape path (/scrape/single, mode="direct").

Covers the edge cases fixed alongside this script:
1. app._normalize_link — pasted-URL cleanup: uppercase/missing scheme, <>/quote
   wrappers, scheme-relative //host, and readable rejection of garbage input.
2. Direct mode captures the user's page even when its HTML contains NO English
   directory keywords (German fixture) — the old keyword gate dropped it → 0 members.
3. https→http fallback: app.py guesses https:// onto bare domains, but http-only
   hosts exist; navigation now retries http instead of scraping about:blank.
4. Dead domain fails fast with a clear message instead of grinding through
   scroll/pagination against about:blank for minutes.

Run: python3 test_direct_scrape.py
(Spins a local HTTP server and launches headless Chromium — takes a few minutes.)
"""
import contextlib
import glob
import io
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ["SCRAPER_HEADLESS"] = "1"

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "Bot"))
sys.path.insert(0, ROOT)

# German trade directory: six businesses, schema.org JSON-LD, no English
# directory keywords anywhere, phones in +49 format (the US phone regex
# fallback must not fire either). Direct mode has to capture this page purely
# because the user chose it.
FIXTURE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Handwerksbetriebe in Berlin</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "LocalBusiness", "name": "Bäckerei Steinofen", "telephone": "+49 30 4816 2201",
     "address": {"@type": "PostalAddress", "streetAddress": "Hauptstraße 12", "postalCode": "10827", "addressLocality": "Berlin"}},
    {"@type": "LocalBusiness", "name": "Tischlerei Eichenholz", "telephone": "+49 30 4816 2202",
     "address": {"@type": "PostalAddress", "streetAddress": "Lindenweg 4", "postalCode": "10115", "addressLocality": "Berlin"}},
    {"@type": "LocalBusiness", "name": "Elektro Funke", "telephone": "+49 30 4816 2203",
     "address": {"@type": "PostalAddress", "streetAddress": "Ringallee 88", "postalCode": "12043", "addressLocality": "Berlin"}},
    {"@type": "LocalBusiness", "name": "Malerei Farbenfroh", "telephone": "+49 30 4816 2204",
     "address": {"@type": "PostalAddress", "streetAddress": "Gartenstraße 7", "postalCode": "13089", "addressLocality": "Berlin"}},
    {"@type": "LocalBusiness", "name": "Dachdeckerei Himmelblick", "telephone": "+49 30 4816 2205",
     "address": {"@type": "PostalAddress", "streetAddress": "Bergpfad 21", "postalCode": "14059", "addressLocality": "Berlin"}},
    {"@type": "LocalBusiness", "name": "Schlosserei Eisenhart", "telephone": "+49 30 4816 2206",
     "address": {"@type": "PostalAddress", "streetAddress": "Uferpromenade 3", "postalCode": "10999", "addressLocality": "Berlin"}}
  ]
}
</script>
</head>
<body>
<h1>Handwerksbetriebe in Berlin</h1>
<div class="karte"><h2>Bäckerei Steinofen</h2><p>Hauptstraße 12, 10827 Berlin</p><p>+49 30 4816 2201</p></div>
<div class="karte"><h2>Tischlerei Eichenholz</h2><p>Lindenweg 4, 10115 Berlin</p><p>+49 30 4816 2202</p></div>
<div class="karte"><h2>Elektro Funke</h2><p>Ringallee 88, 12043 Berlin</p><p>+49 30 4816 2203</p></div>
<div class="karte"><h2>Malerei Farbenfroh</h2><p>Gartenstraße 7, 13089 Berlin</p><p>+49 30 4816 2204</p></div>
<div class="karte"><h2>Dachdeckerei Himmelblick</h2><p>Bergpfad 21, 14059 Berlin</p><p>+49 30 4816 2205</p></div>
<div class="karte"><h2>Schlosserei Eisenhart</h2><p>Uferpromenade 3, 10999 Berlin</p><p>+49 30 4816 2206</p></div>
</body>
</html>"""

_FORBIDDEN_KEYWORDS = [  # mirror of browser._DIRECTORY_CONTENT_KEYWORDS
    "member", "directory", "listing", "result", "profile",
    "load more", "company", "contact",
    "doctor", "restaurant", "attorney", "clinic",
]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = FIXTURE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _QuietServer(HTTPServer):
    def handle_error(self, request, client_address):
        pass  # TLS handshakes against this plain-HTTP server are expected noise


def _start_server() -> tuple[HTTPServer, int]:
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def _cleanup_artifacts(port: int):
    """Remove Data-dump files and cache entries the test scrapes created."""
    domain = f"127_0_0_1:{port}"
    for pattern in (f"{domain}*.json", "kein-solcher-host-*.json"):
        for path in glob.glob(os.path.join(ROOT, "Data-dump", pattern)):
            os.remove(path)
    import cache
    dirty = False
    for key in (domain, f"url_enum_{domain}"):
        if key in cache._selector_cache:
            del cache._selector_cache[key]
            dirty = True
    if dirty:
        cache.save_selector_cache()


def test_normalize_link():
    from app import _normalize_link

    ok_cases = {
        "example.com/dir": "https://example.com/dir",
        "HTTPS://Example.COM/Dir": "https://Example.COM/Dir",
        "HTTP://example.com": "http://example.com",
        "//example.com/x": "https://example.com/x",
        "<https://example.com/a>": "https://example.com/a",
        '"https://example.com"': "https://example.com",
        "  www.example.com  ": "https://www.example.com",
        "http://localhost:8000/x": "http://localhost:8000/x",
    }
    for raw, expected in ok_cases.items():
        link, err = _normalize_link(raw)
        assert err is None, f"{raw!r} unexpectedly rejected: {err}"
        assert link == expected, f"{raw!r} → {link!r}, expected {expected!r}"

    bad_cases = ["", "   ", "ftp://example.com", "javascript://alert(1)",
                 "hoa directory texas", "not a url at all"]
    for raw in bad_cases:
        link, err = _normalize_link(raw)
        assert err, f"{raw!r} should have been rejected, got {link!r}"
    print("PASS: _normalize_link (pasted-URL cleanup + garbage rejection)")


def test_fixture_has_no_keyword_escape_hatch():
    lower = FIXTURE_HTML.lower()
    hits = [kw for kw in _FORBIDDEN_KEYWORDS if kw in lower]
    assert not hits, f"fixture accidentally contains directory keywords: {hits}"
    from browser import _PHONE_RE
    assert not _PHONE_RE.search(FIXTURE_HTML), "fixture phones must not match the US phone regex"
    print("PASS: fixture really has no keyword/phone-regex escape hatch")


def _run_scrape(url: str) -> list:
    from Bot.main import scrape_directory
    return scrape_directory(url, prompt_callback=lambda count, message=None: False,
                            mode="direct")


def test_direct_scrape_foreign_language_page(port: int):
    members = _run_scrape(f"http://127.0.0.1:{port}/betriebe")
    names = {m.get("company_name") for m in members}
    assert len(members) == 6, f"expected 6 members, got {len(members)}: {names}"
    assert "Bäckerei Steinofen" in names, f"missing expected business, got: {names}"
    assert all(m.get("phone") for m in members), "phones lost in cleaning"
    print(f"PASS: direct scrape of keyword-free page → {len(members)} members via JSON-LD")


def test_https_to_http_fallback(port: int):
    members = _run_scrape(f"https://127.0.0.1:{port}/betriebe")
    assert len(members) == 6, f"https→http fallback failed, got {len(members)} members"
    print("PASS: https→http fallback on an http-only host")


def test_dead_domain_fails_fast():
    start = time.time()
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        members = _run_scrape("https://kein-solcher-host-9482.invalid/verzeichnis")
    elapsed = time.time() - start
    output = captured.getvalue()
    assert members == [], f"dead domain should yield no members, got {len(members)}"
    assert "NAVIGATION FAILED" in output, (
        "expected explicit navigation-failure message; the scrape must not "
        f"grind on about:blank / chrome-error pages. Output was:\n{output[-2000:]}")
    assert elapsed < 30, f"dead domain took {elapsed:.0f}s — should abort fast"
    print(f"PASS: dead domain aborted cleanly in {elapsed:.0f}s with 0 members")


if __name__ == "__main__":
    test_normalize_link()
    test_fixture_has_no_keyword_escape_hatch()

    server, port = _start_server()
    try:
        test_direct_scrape_foreign_language_page(port)
        test_https_to_http_fallback(port)
        test_dead_domain_fails_fast()
    finally:
        server.shutdown()
        _cleanup_artifacts(port)

    print("\nAll direct-scrape tests passed.")
