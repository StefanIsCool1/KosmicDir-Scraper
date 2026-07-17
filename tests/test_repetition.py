"""Offline fixture tests for Bot/repetition.py (UNIVERSALITY_PLAN Phase 1).

Deterministic — no network, no LLM, no browser. Truth lives in
tests/fixture_truth.py; fixtures in tests/fixtures/*.html (harvested from
Data-dump raw captures by tests/harvest_fixtures.py).

Phase 1 exit criteria covered here:
- hashed-CSS fixture yields a selector + count within ±10% of truth
- nav-menu-heavy fixture yields no false run
- Finalsite wrapper fixture counts cards, not wrappers
(the fourth criterion — the truncation site paginating past 600 — is a live
smoke check, not an offline test)
"""

import os

import pytest
from bs4 import BeautifulSoup

from fixture_truth import NEGATIVE, POSITIVE

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


@pytest.fixture(scope="module")
def detector():
    from repetition import find_repeated_records
    return find_repeated_records


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_positive_selector_and_count(detector, name):
    """Every positive fixture yields a selector and a count within ±10%
    of the true card count."""
    truth = POSITIVE[name]["truth"]
    selector, count, samples = detector(_load(name))

    assert selector is not None, f"{name}: no run detected (truth={truth})"
    assert samples, f"{name}: no sample nodes returned"
    lo, hi = truth * 0.9, truth * 1.1
    assert lo <= count <= hi, (
        f"{name}: count {count} outside ±10% of truth {truth}"
    )


@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_positive_selector_round_trips(detector, name):
    """The emitted selector must re-select the same population on a fresh
    parse (this is what the live JS-side counter will querySelectorAll),
    and must use browser-valid CSS only."""
    truth = POSITIVE[name]["truth"]
    html = _load(name)
    selector, count, _ = detector(html)
    assert selector is not None

    # No bs4/soupsieve-only syntax — the selector goes to querySelectorAll.
    assert ":-soup" not in selector and ":contains" not in selector

    fresh = BeautifulSoup(html, "html.parser")
    matched = [
        el for el in fresh.select(selector)
        if len(el.get_text(strip=True)) >= 15
    ]
    assert truth * 0.9 <= len(matched) <= truth * 1.1, (
        f"{name}: selector '{selector}' re-selects {len(matched)} "
        f"(truth {truth})"
    )


@pytest.mark.parametrize(
    "name",
    sorted(n for n in POSITIVE if POSITIVE[n]["card_class"]),
)
def test_positive_samples_are_cards_not_layout(detector, name):
    """Sample nodes must be the member card itself or its 1:1 wrapper —
    never a container holding many cards, never a card sub-element.
    This is the Finalsite/containment regression: outermost-only collapsed
    50 cards to ~1, leaf-only dropped to ~15."""
    card_class = POSITIVE[name]["card_class"]
    _, _, samples = detector(_load(name))
    assert samples

    for node in samples[:4]:
        classes = node.get("class") or []
        if card_class in classes:
            continue  # the card itself
        inner = node.find_all(class_=card_class)
        assert len(inner) == 1, (
            f"{name}: sample node <{node.name} class={classes[:3]}> holds "
            f"{len(inner)} '{card_class}' cards — not a card or 1:1 wrapper"
        )


@pytest.mark.parametrize("name", NEGATIVE)
def test_negative_no_false_run(detector, name):
    """Menu-heavy homepages and link-hub pages must not be elected as
    member-record runs."""
    selector, count, samples = detector(_load(name))
    assert selector is None, (
        f"{name}: false run '{selector}' with count {count} "
        f"(sample: {str(samples[0])[:120] if samples else ''})"
    )


def test_navheavy_never_elects_nav(detector):
    """Phase 1 exit criterion (nav-menu-heavy fixture yields no false run):
    enigma's 693 adjacent a.dropdown-option and 401 industry links are the
    most repetitive structures on the page; the elected run must be the
    real ~20-cafe listing, nowhere near the nav runs."""
    selector, count, samples = detector(_load("enigma_navheavy.html"))
    assert selector is not None
    assert count < 60, f"nav-sized run elected: {count} via '{selector}'"
    assert "dropdown" not in selector
    for node in samples[:4]:
        assert "dropdown-option" not in (node.get("class") or [])


def test_finalsite_counts_cards_not_wrappers(detector):
    """Explicit Phase 1 exit criterion. The 50 fsConstituentItem cards sit
    inside fsConstituentColumnLayout_3 — a container that also matches
    [class*='constituent']. The count must be 50: not ~1 (outermost-only
    containment collapse) and not ~15 (leaf-only + text filter)."""
    selector, count, samples = detector(_load("minnetonka_finalsite.html"))
    assert count == 50
    for node in samples[:4]:
        assert "fsConstituentItem" in (node.get("class") or [])


def test_growthzone_defeats_class_substring_inflation(detector):
    """The legacy [class*='card'] counter reads 1608 on this page for 212
    real members (the premature-STOP_THRESHOLD bug). The structural count
    must sit at truth, nowhere near the inflated figure."""
    _, count, _ = detector(_load("buildingncw_growthzone.html"))
    assert 191 <= count <= 233
