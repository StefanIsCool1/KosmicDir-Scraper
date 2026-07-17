"""Validation for the /discover → Phase 1 handoff improvements.

Run:  python3 test_discover_handoff.py

Covers:
  Hint resolve  app._same_site_hint — relative/absolute resolution, subdomain
                and www tolerance, cross-domain + non-http rejection
  Navigator     find_directory_url landing_hint — starts the AI walk on the
                hint page, falls back to `link` when the hint 404s or throws
                (fake page object; no browser, no LLM — the walk stops at
                depth 0 because the fake page has no links)
  Wiring        scrape_directory / capture_responses accept landing_hint, so
                app.py's kwarg can't silently break
  Mode rule     the /discover loop no longer hard-codes mode="auto" (source
                check), and confirmed-listing pages route to "direct"
"""

import inspect
import os
import re
import sys

os.environ["SCRAPER_HEADLESS"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "Bot"))
sys.path.insert(0, _HERE)

_FAILURES = []
_PASSES = 0


def check(name: str, cond: bool, detail: str = ""):
    global _PASSES
    if cond:
        _PASSES += 1
        print(f"  PASS  {name}")
    else:
        _FAILURES.append(name)
        print(f"  FAIL  {name}  {detail}")


# --- app._same_site_hint ---------------------------------------------------

def test_same_site_hint():
    print("\n[_same_site_hint]")
    from app import _same_site_hint

    base = "https://www.example.org/home"
    check("relative href resolves",
          _same_site_hint(base, "/member-directory")
          == "https://www.example.org/member-directory")
    check("absolute same-domain kept",
          _same_site_hint(base, "https://example.org/members")
          == "https://example.org/members")
    check("subdomain kept",
          _same_site_hint("https://example.org/", "https://directory.example.org/m")
          == "https://directory.example.org/m")
    check("www mismatch tolerated",
          _same_site_hint("https://example.org/", "https://www.example.org/members")
          == "https://www.example.org/members")
    check("cross-domain rejected",
          _same_site_hint(base, "https://evil.com/directory") is None)
    check("lookalike suffix domain rejected",
          _same_site_hint("https://example.org/", "https://notexample.org/d") is None)
    check("mailto rejected", _same_site_hint(base, "mailto:a@b.org") is None)
    check("javascript rejected", _same_site_hint(base, "javascript:void(0)") is None)


# --- find_directory_url landing_hint ----------------------------------------

class _FakeResponse:
    def __init__(self, status):
        self.status = status


class _FakePage:
    """Just enough Page for find_directory_url's pre-loop navigation. The
    depth loop exits immediately because eval_on_selector_all returns no
    links — so no AI call is ever made."""

    def __init__(self, start_url, statuses=None):
        self.url = start_url
        self.gotos = []
        self._statuses = statuses or {}

    def goto(self, url, **kw):
        self.gotos.append(url)
        outcome = self._statuses.get(url, 200)
        if isinstance(outcome, Exception):
            raise outcome
        self.url = url
        return _FakeResponse(outcome)

    def wait_for_load_state(self, *a, **kw):
        pass

    def eval_on_selector_all(self, *a, **kw):
        return []


def test_landing_hint_navigation():
    print("\n[find_directory_url landing_hint]")
    from navigator import find_directory_url

    link = "https://example.org/"
    hint = "https://example.org/member-directory"

    # Hint loads fine → walk starts (and here, ends) on the hint page.
    page = _FakePage(link)
    got = find_directory_url(page, link, landing_hint=hint)
    check("good hint becomes the starting page", got == hint, f"got {got}")
    check("good hint navigated exactly once", page.gotos == [hint],
          f"gotos={page.gotos}")

    # Hint 404s → fall back to `link`.
    page = _FakePage(link, statuses={hint: 404})
    got = find_directory_url(page, link, landing_hint=hint)
    check("404 hint falls back to link", got == link, f"got {got}")
    check("404 hint returns to link page", page.gotos == [hint, link],
          f"gotos={page.gotos}")

    # Hint throws (dead URL) → fall back to `link`, no re-goto needed
    # because the fake page never left it.
    page = _FakePage(link, statuses={hint: RuntimeError("net::ERR_FAILED")})
    got = find_directory_url(page, link, landing_hint=hint)
    check("dead hint falls back to link", got == link, f"got {got}")

    # No hint → unchanged behavior: no navigation when already on `link`.
    page = _FakePage(link)
    got = find_directory_url(page, link)
    check("no hint: no extra navigation", page.gotos == [] and got == link,
          f"gotos={page.gotos}, got={got}")

    # Hint identical to link → treated as no hint.
    page = _FakePage(link)
    got = find_directory_url(page, link, landing_hint=link.rstrip("/"))
    check("hint == link: no extra navigation", page.gotos == [] and got == link,
          f"gotos={page.gotos}, got={got}")


# --- parameter wiring --------------------------------------------------------

def test_wiring():
    print("\n[landing_hint wiring]")
    from main import scrape_directory
    from browser import capture_responses

    check("scrape_directory accepts landing_hint",
          "landing_hint" in inspect.signature(scrape_directory).parameters)
    check("capture_responses accepts landing_hint",
          "landing_hint" in inspect.signature(capture_responses).parameters)


# --- /discover loop mode rule (source-level) ---------------------------------

def test_discover_mode_rule():
    print("\n[/discover mode decision]")
    src = open(os.path.join(_HERE, "app.py")).read()

    # The old bug: every discover scrape hard-coded auto mode.
    check("no hard-coded scrape_mode = \"auto\"",
          not re.search(r'^\s*scrape_mode = "auto"\s*$', src, re.M))
    check("mode decided from needs_navigation",
          'scrape_mode = "auto" if (needs_nav or is_agg) else "direct"' in src)
    check("landing hint forwarded to scrape_directory",
          "landing_hint=landing_hint" in src)
    check("preflight's final_url preferred",
          'd.get("final_url") or d["url"]' in src)


def main():
    test_same_site_hint()
    test_landing_hint_navigation()
    test_wiring()
    test_discover_mode_rule()

    print(f"\n{_PASSES} passed, {len(_FAILURES)} failed")
    if _FAILURES:
        for f in _FAILURES:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
