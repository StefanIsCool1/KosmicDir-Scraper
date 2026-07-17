"""Wiring tests for UNIVERSALITY_PLAN Phase 1: the repetition detector's
integration into html_parser (Strategy 2.5) and archetype's PageProfile
count lifecycle. Deterministic — no network, no LLM, no browser (the
Playwright context is faked)."""

import os

import pytest
from bs4 import BeautifulSoup

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


# --- extract_sample_html Strategy 2.5 ---

def test_strategy25_gives_selector_on_classless_markup():
    """A classless card grid forms no class group (Strategy 1) and has no
    <table>/<ul> container (Strategy 2); before Phase 1 it fell to the
    blind densest-chunk sample with card_selector=None."""
    from html_parser import extract_sample_html
    sample, card_selector = extract_sample_html(_load("findadentist_classless.html"))
    assert card_selector is not None
    assert sample
    soup = BeautifulSoup(_load("findadentist_classless.html"), "html.parser")
    matched = soup.select(card_selector)
    assert 90 <= len(matched) <= 110


def test_extract_sample_parity_when_strategy1_confident(monkeypatch):
    """Parity: when strategies 0-2 already produce a confident candidate
    (this homepage yields 'div.bde-div' at score 64 via Strategy 1), the
    Phase 1 wiring must not change extract_sample_html's output at all."""
    import html_parser
    html = _load("eatingminnesota_home.html")
    with_flag = html_parser.extract_sample_html(html)
    monkeypatch.setattr(html_parser, "REPETITION_COUNTING", False)
    without_flag = html_parser.extract_sample_html(html)
    assert with_flag == without_flag


# --- archetype PageProfile lifecycle ---

class FakeContext:
    """Stands in for a Playwright Page/Frame: content() serves mutable HTML
    and evaluate() emulates the counting JS with BeautifulSoup (visibility
    can't be emulated; the >=15-char text guard is)."""

    def __init__(self, html: str, url: str = "https://example.test/dir"):
        self.html = html
        self.url = url

    def content(self):
        return self.html

    def evaluate(self, script, arg=None):
        if "querySelectorAll" in script:
            try:
                soup = BeautifulSoup(self.html, "html.parser")
                return sum(
                    1 for el in soup.select(arg)
                    if len(el.get_text(strip=True)) >= 15
                )
            except Exception:
                return -1
        if "innerHTML.length" in script:
            return len(self.html)
        raise AssertionError(f"unexpected script: {script[:60]}")


@pytest.fixture()
def archetype_mod():
    import archetype
    archetype.reset()
    yield archetype
    archetype.reset()


def test_count_records_derives_and_counts(archetype_mod):
    ctx = FakeContext(_load("buildingncw_growthzone.html"))
    assert archetype_mod.count_records(ctx) == 212


def test_count_records_caches_derivation(archetype_mod, monkeypatch):
    ctx = FakeContext(_load("buildingncw_growthzone.html"))
    calls = {"n": 0}
    real = archetype_mod.find_repeated_records

    def counting(html):
        calls["n"] += 1
        return real(html)

    monkeypatch.setattr(archetype_mod, "find_repeated_records", counting)
    archetype_mod.count_records(ctx)
    archetype_mod.count_records(ctx)
    archetype_mod.count_records(ctx)
    assert calls["n"] == 1


def test_count_records_survives_empty_page_and_revalidates(archetype_mod, monkeypatch):
    """SPA lifecycle: listing -> empty search page -> listing again. The
    empty page re-derives once (selector went stale), fails, and falls back
    negative; the restored listing must revalidate the LAST GOOD selector
    with a live count only — no third parse."""
    listing = _load("buildingncw_growthzone.html")
    ctx = FakeContext(listing)
    calls = {"n": 0}
    real = archetype_mod.find_repeated_records

    def counting(html):
        calls["n"] += 1
        return real(html)

    monkeypatch.setattr(archetype_mod, "find_repeated_records", counting)

    assert archetype_mod.count_records(ctx) == 212
    ctx.html = "<html><body><p>No results found for query</p></body></html>"
    assert archetype_mod.count_records(ctx) is None  # legacy fallback turn
    ctx.html = listing
    assert archetype_mod.count_records(ctx) == 212
    assert calls["n"] == 2  # initial derive + empty-page re-derive only


def test_flag_off_short_circuits(archetype_mod, monkeypatch):
    monkeypatch.setattr(archetype_mod, "REPETITION_COUNTING", False)

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError("flag-off path touched the page")

    assert archetype_mod.count_records(Exploding()) is None
    assert archetype_mod.rendered_record_count(Exploding()) == (None, False)
