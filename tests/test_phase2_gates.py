"""Fixture tests for UNIVERSALITY_PLAN Phase 2 — one per exit criterion:

1. short-count fixture sets metadata.partial and recovers on re-drive (R3)
2. name-only roster auto-crawls details in Agent mode, prompts in
   Playground (R4)
3. a two-layout domain keeps both schemas in the selector cache (R5)
4. sparse-field fixture learns the union schema via one re-ask (R6)

Deterministic — no network, no LLM (ask is monkeypatched), no browser.
The selector cache is isolated to a tmp file per test.
"""

import json
import os

import pytest
from bs4 import BeautifulSoup

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture()
def isolated_cache(tmp_path, monkeypatch):
    """Redirect the selector cache to a per-test tmp file so tests never
    touch (or depend on) the real Bot/selector_cache.json."""
    import cache
    monkeypatch.setattr(cache, "SELECTOR_CACHE_FILE",
                        str(tmp_path / "selector_cache.json"))
    monkeypatch.setattr(cache, "_selector_cache", {})
    yield cache


@pytest.fixture()
def archetype_mod():
    import archetype
    archetype.reset()
    yield archetype
    archetype.reset()


# --- synthetic fixture pages ---

def _card_page(n: int, start: int = 0, with_phone: bool = True,
               email_every: int | None = None) -> str:
    """A listing page of n business cards. Names are globally unique via
    `start` so a re-driven page extends (not duplicates) the first pass."""
    cards = []
    for i in range(start, start + n):
        email = (f'<div class="mail">contact{i}@example.com</div>'
                 if email_every and i % email_every == 0 else "")
        phone = (f'<span class="tel">(555) 201-{i % 10000:04d}</span>'
                 if with_phone else "")
        cards.append(
            f'<div class="member-card"><h3 class="name">Acme {i} LLC</h3>'
            f'{phone}{email}</div>'
        )
    return f"<html><body><div id='listing'>{''.join(cards)}</div></body></html>"


def _roster_page(n: int) -> str:
    """A link-index roster: names + profile links only — contact info lives
    on the detail pages (the R4 shape)."""
    rows = "".join(
        f'<div class="card"><h3 class="nm">Firm {i} Inc</h3>'
        f'<a class="profile" href="https://example.test/member/{i}">profile</a></div>'
        for i in range(n)
    )
    return f"<html><body><div id='roster'>{rows}</div></body></html>"


def _table_page(n: int) -> str:
    """The same directory rendered as a table — a second layout."""
    rows = "".join(
        f'<tr class="row"><td class="name">Acme {i} LLC</td>'
        f'<td class="tel">(555) 301-{i % 10000:04d}</td></tr>'
        for i in range(n)
    )
    return f"<html><body><table id='dir'>{rows}</table></body></html>"


CARD_SCHEMA = {
    "entity_type": "business",
    "card_selector": "div.member-card",
    "company_name": "h3.name",
    "phone": "span.tel",
}

TABLE_SCHEMA = {
    "entity_type": "business",
    "card_selector": "tr.row",
    "company_name": "td.name",
    "phone": "td.tel",
}

ROSTER_SCHEMA = {
    "entity_type": "business",
    "card_selector": "div.card",
    "company_name": "h3.nm",
    "website": "a.profile",
}


def _html_result(html: str, url: str = "https://example.test/dir") -> dict:
    return {"url": url, "data": {"raw_html": html}}


def _read_structured(tmp_path, domain):
    with open(os.path.join(tmp_path, f"{domain}_structured.json")) as f:
        return json.load(f)


# --- count_gate_verdict unit behavior ---

def test_count_gate_flags_shortfall():
    import main
    assert main.count_gate_verdict(100, 213) == {"expected": 213, "extracted": 100}


def test_count_gate_falls_open_without_numeric_total():
    import main
    assert main.count_gate_verdict(100, None) is None


def test_count_gate_passes_when_reconciled():
    import main
    assert main.count_gate_verdict(213, 213) is None
    assert main.count_gate_verdict(180, 213) is None  # >= 0.8x


def test_count_gate_clamps_marketing_copy():
    """'one of 5,000 members nationwide' must degrade to unknown when every
    piece of extraction evidence is an order of magnitude smaller."""
    import main
    assert main.count_gate_verdict(120, 5000, observed=130) is None


def test_count_gate_ignores_failed_scrapes():
    import main
    assert main.count_gate_verdict(0, 213) is None
    assert main.count_gate_verdict(2, 213) is None


def test_count_gate_flag_off(monkeypatch):
    import main
    monkeypatch.setattr(main, "PHASE2_RECONCILIATION", False)
    assert main.count_gate_verdict(100, 213) is None


# --- expected-count plumbing (navigator -> archetype -> gate) ---

def test_note_expected_count_records_run_total(archetype_mod):
    ctx = object()
    archetype_mod.note_expected_count(ctx, {"type": "number", "count": 213})
    archetype_mod.note_expected_count(ctx, {"type": "number", "count": 48})
    archetype_mod.note_expected_count(ctx, {"type": "all"})
    archetype_mod.note_expected_count(ctx, {"type": "unknown"})
    expected, _observed = archetype_mod.run_count_evidence()
    assert expected == 213


def test_reset_clears_run_evidence(archetype_mod):
    archetype_mod.note_expected_count(object(), {"type": "number", "count": 99})
    archetype_mod.note_observed(50)
    archetype_mod.reset()
    assert archetype_mod.run_count_evidence() == (None, 0)


# --- Exit criterion 1: partial + recovery on re-drive ---

def test_short_count_sets_partial_then_recovers_on_redrive(
        tmp_path, isolated_cache, archetype_mod):
    import main
    domain = "phase2_countgate_test"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)
    archetype_mod.note_expected_count(object(), {"type": "number", "count": 100})

    redrives = []

    def redrive():
        redrives.append(1)
        # Second pass reaches everything: the full 100-card listing.
        return [_html_result(_card_page(100))], []

    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_card_page(40))], [],
        prompt_callback=lambda c, m=None: False,
        priority_fields=[], intent=None, redrive_fn=redrive)

    assert len(redrives) == 1
    assert len(members) == 100
    meta = _read_structured(tmp_path, domain)["metadata"]
    assert "partial" not in meta  # recovered — flag cleared by the re-parse
    assert meta["total_members"] == 100


def test_short_count_stays_partial_when_redrive_finds_nothing(
        tmp_path, isolated_cache, archetype_mod):
    import main
    domain = "phase2_countgate_stuck"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)
    archetype_mod.note_expected_count(object(), {"type": "number", "count": 100})

    redrives = []

    def redrive():
        redrives.append(1)
        return [], []

    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_card_page(40))], [],
        prompt_callback=lambda c, m=None: False,
        priority_fields=[], intent=None, redrive_fn=redrive)

    assert len(redrives) == 1  # re-driven once, never twice
    assert len(members) == 40
    meta = _read_structured(tmp_path, domain)["metadata"]
    assert meta["partial"] is True
    assert meta["expected_count"] == 100


def test_no_redrive_without_expected_total(tmp_path, isolated_cache, archetype_mod):
    """Sites that show no count must never be gated (fall open)."""
    import main
    domain = "phase2_countgate_nototal"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)

    def redrive():
        raise AssertionError("re-drive must not fire without a stated total")

    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_card_page(40))], [],
        prompt_callback=lambda c, m=None: False,
        priority_fields=[], intent=None, redrive_fn=redrive)
    assert len(members) == 40
    assert "partial" not in _read_structured(tmp_path, domain)["metadata"]


# --- Exit criterion 2: name-only roster auto-crawls details ---

def _fake_detail_members(n: int) -> list:
    return [{
        "company_name": f"Firm {i} Inc",
        "description": None, "category": None,
        "website": f"https://firm{i}.example.com",
        "phone": f"(555) 401-{i % 10000:04d}",
        "fax": None,
        "street_address": None, "mailing_address": None,
        "contacts": [],
    } for i in range(n)]


def test_name_only_roster_auto_crawls_in_agent_mode(
        tmp_path, isolated_cache, archetype_mod, monkeypatch):
    import main
    import intent_record_filter
    domain = "phase2_completeness_agent"
    isolated_cache.set_cached_selectors(domain, ROSTER_SCHEMA)
    monkeypatch.setattr(intent_record_filter, "filter_records_by_intent",
                        lambda records, intent: records)

    crawled = []

    def fake_crawl(detail_urls, dom):
        crawled.append(len(detail_urls))
        return _fake_detail_members(12)

    monkeypatch.setattr(main, "crawl_detail_pages", fake_crawl)

    def exploding_prompt(count, message=None):
        raise AssertionError("Agent mode must auto-trigger, not prompt")

    detail_urls = [f"https://example.test/member/{i}" for i in range(12)]
    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_roster_page(12))], detail_urls,
        prompt_callback=exploding_prompt,
        priority_fields=[], intent={"industry_canonical": "widgets"},
        redrive_fn=None)

    assert crawled == [12]
    assert len(members) == 12
    assert all(m.get("phone") for m in members)


def test_name_only_roster_prompts_in_playground(
        tmp_path, isolated_cache, archetype_mod, monkeypatch):
    import main
    domain = "phase2_completeness_playground"
    isolated_cache.set_cached_selectors(domain, ROSTER_SCHEMA)

    monkeypatch.setattr(
        main, "crawl_detail_pages",
        lambda urls, dom: pytest.fail("declined crawl must not run"))

    prompts = []

    def prompt(count, message=None):
        prompts.append(message)
        return False

    detail_urls = [f"https://example.test/member/{i}" for i in range(12)]
    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_roster_page(12))], detail_urls,
        prompt_callback=prompt,
        priority_fields=[], intent=None, redrive_fn=None)

    assert len(prompts) == 1
    assert "name-only" in prompts[0]
    assert len(members) == 12  # roster still ships, just without detail data


def test_contact_rich_listing_does_not_trigger_completeness(
        tmp_path, isolated_cache, archetype_mod, monkeypatch):
    """Parity: records WITH contact data keep the legacy decision — with no
    priority fields that's the ordinary prompt, without the name-only text."""
    import main
    domain = "phase2_completeness_negative"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)

    prompts = []

    def prompt(count, message=None):
        prompts.append(message)
        return False

    members = main._finish_scrape(
        "https://example.test/dir", domain, str(tmp_path),
        [_html_result(_card_page(12))],
        [f"https://example.test/member/{i}" for i in range(12)],
        prompt_callback=prompt,
        priority_fields=[], intent=None, redrive_fn=None)
    assert len(members) == 12
    assert len(prompts) == 1
    assert prompts[0] is None  # default message, not the completeness one


def test_name_only_ratio_shapes(isolated_cache):
    import main
    domain = "phase2_ratio_test"
    isolated_cache.set_cached_selectors(domain, ROSTER_SCHEMA)
    name_only = {"company_name": "A Corp", "website": "https://a.example.com",
                 "contacts": []}
    rich = dict(name_only, phone="(555) 111-2222")
    assert main._name_only_ratio([name_only] * 8 + [rich] * 2, domain) == 0.8
    assert main._name_only_ratio([rich] * 10, domain) == 0.0
    assert main._name_only_ratio([], domain) == 0.0


# --- Exit criterion 3: two-layout domain keeps both schemas ---

def test_two_layout_domain_keeps_both_schemas(isolated_cache):
    domain = "phase2_layouts_test"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)
    isolated_cache.set_cached_selectors(domain, TABLE_SCHEMA)

    layouts = isolated_cache.get_cached_layouts(domain)
    assert len(layouts) == 2
    fps = {isolated_cache.layout_fingerprint(l) for l in layouts}
    assert fps == {isolated_cache.layout_fingerprint(CARD_SCHEMA),
                   isolated_cache.layout_fingerprint(TABLE_SCHEMA)}
    # Most recently learned schema is the primary (legacy readers see it).
    primary = isolated_cache.get_cached_selectors(domain)
    assert primary["card_selector"] == TABLE_SCHEMA["card_selector"]
    assert primary["fingerprint"]
    assert primary["learned_at"]


def test_parse_uses_alternate_layout_and_promotes(isolated_cache):
    import html_parser
    domain = "phase2_layouts_parse"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)
    isolated_cache.set_cached_selectors(domain, TABLE_SCHEMA)  # primary now

    # A card-grid page: the primary (table) schema fails, the alternate
    # validates — no LLM call, and the alternate is promoted to primary.
    members = html_parser.parse_member_html(_card_page(12), domain=domain)
    assert len(members) == 12
    assert all(m["company_name"] for m in members)
    primary = isolated_cache.get_cached_selectors(domain)
    assert primary["card_selector"] == CARD_SCHEMA["card_selector"]
    assert len(isolated_cache.get_cached_layouts(domain)) == 2

    # And back: a table page still parses via the (now-demoted) table schema.
    members = html_parser.parse_member_html(_table_page(12), domain=domain)
    assert len(members) == 12
    assert len(isolated_cache.get_cached_layouts(domain)) == 2


def test_legacy_entry_reads_as_fingerprintless_primary(isolated_cache):
    domain = "phase2_layouts_legacy"
    isolated_cache._selector_cache[domain] = dict(CARD_SCHEMA)  # pre-Phase-2 shape
    layouts = isolated_cache.get_cached_layouts(domain)
    assert len(layouts) == 1
    assert "fingerprint" not in layouts[0]
    # A new learn demotes the legacy entry instead of destroying it.
    isolated_cache.set_cached_selectors(domain, TABLE_SCHEMA)
    assert len(isolated_cache.get_cached_layouts(domain)) == 2


def test_remove_cached_layout_restores_demoted_primary(isolated_cache):
    domain = "phase2_layouts_scrub"
    isolated_cache.set_cached_selectors(domain, CARD_SCHEMA)
    isolated_cache.set_cached_selectors(domain, TABLE_SCHEMA)
    # The just-learned table schema fails validation -> scrubbed by
    # fingerprint; the demoted card schema is promoted back.
    isolated_cache.remove_cached_layout(domain, TABLE_SCHEMA)
    layouts = isolated_cache.get_cached_layouts(domain)
    assert len(layouts) == 1
    assert layouts[0]["card_selector"] == CARD_SCHEMA["card_selector"]


# --- Exit criterion 4: sparse-field fixture learns the union schema ---

def test_sparse_field_learns_union_schema(isolated_cache, monkeypatch):
    import html_parser
    domain = "phase2_union_test"
    html = _card_page(20, email_every=2)  # email visible on 10 of 20 cards

    responses = [
        json.dumps({"entity_type": "business",
                    "card_selector": "div.member-card",
                    "company_name": "h3.name",
                    "phone": "span.tel"}),      # learned schema misses email
        json.dumps({"contact_email": "div.mail"}),  # the one re-ask
    ]
    calls = []

    def fake_ask(prompt, max_tokens=0):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(html_parser, "ask", fake_ask)
    selectors = html_parser.learn_selectors(html, domain)

    assert len(calls) == 2  # learn + exactly one re-ask
    assert "contact_email" in calls[1]  # re-ask names the missed field
    assert selectors["contact_email"] == "div.mail"
    cached = isolated_cache.get_cached_selectors(domain)
    assert cached["contact_email"] == "div.mail"  # union schema cached
    members = html_parser.apply_selectors(html, cached)
    captured = sum(1 for m in members
                   if any(c.get("email") for c in m["contacts"]))
    assert captured == 10


def test_no_reask_when_schema_captures_fields(isolated_cache, monkeypatch):
    import html_parser
    domain = "phase2_union_negative"
    html = _card_page(20, email_every=2)

    responses = [
        json.dumps({"entity_type": "business",
                    "card_selector": "div.member-card",
                    "company_name": "h3.name",
                    "phone": "span.tel",
                    "contact_email": "div.mail"}),  # complete first time
    ]
    calls = []

    def fake_ask(prompt, max_tokens=0):
        calls.append(prompt)
        return responses[len(calls) - 1]

    monkeypatch.setattr(html_parser, "ask", fake_ask)
    html_parser.learn_selectors(html, domain)
    assert len(calls) == 1  # no re-ask when nothing was missed


def test_diverse_samples_cover_sparse_signatures():
    """First-4 sampling never showed the LLM an email-bearing card when
    emails start at card 5; signature-diverse sampling must."""
    import html_parser
    cards = []
    for i in range(12):
        email = (f'<a href="mailto:p{i}@x.com">mail</a>' if i >= 5 else "")
        soup = BeautifulSoup(
            f'<div class="c"><h3>Firm {i}</h3>'
            f'<span>(555) 123-45{i:02d}</span>{email}</div>', "html.parser")
        cards.append(soup.div)
    picked = html_parser._pick_diverse_samples(cards)
    assert len(picked) <= 5
    assert cards[0] in picked  # always keeps the first card
    assert any("mailto:" in str(el) for el in picked)


# --- partial propagation into the consolidated deliverable ---

def test_exporter_propagates_partial(tmp_path):
    import exporter
    partial_dump = {
        "metadata": {"source_url": "https://a.example.com", "partial": True,
                     "expected_count": 100, "total_members": 40},
        "members": [{"company_name": f"A {i}", "phone": f"(555) 1{i:02d}-0000"}
                    for i in range(40)],
    }
    full_dump = {
        "metadata": {"source_url": "https://b.example.com", "total_members": 5},
        "members": [{"company_name": f"B {i}", "phone": f"(555) 2{i:02d}-0000"}
                    for i in range(5)],
    }
    for name, dump in [("a_structured.json", partial_dump),
                       ("b_structured.json", full_dump)]:
        with open(tmp_path / name, "w") as f:
            json.dump(dump, f)

    info = exporter.export_final_dataset(
        ["a_structured.json", "b_structured.json"],
        [str(tmp_path)], str(tmp_path), "combo")
    assert info["partial"] is True
    partial_sources = [s for s in info["sources"] if s.get("partial")]
    assert len(partial_sources) == 1
    assert partial_sources[0]["expected_count"] == 100

    with open(tmp_path / "combo_final.json") as f:
        final = json.load(f)
    assert final["metadata"]["partial"] is True
