"""Page profiling spine (UNIVERSALITY_PLAN Phase 1 slice).

Owns the PageProfile record-selector lifecycle and the single counting
authority that decision gates consult instead of re-deriving page shape ad
hoc. Phase 1 ships the selector/count machinery; archetype CLASSIFICATION
(CARD_GRID vs TABLE_ROSTER vs LOCATOR_FORM ...) and the form/pager fields
land with later phases — until then every profile stays UNKNOWN, which by
design routes to the legacy flow.

Lifecycle rules (load-bearing, from the plan):
- Selector, not snapshot: the profile caches record_selector; every count is
  a live querySelectorAll with the same rendered/>=15-char guards the legacy
  counter uses. No decision gates on a count captured earlier.
- Re-profile points: derive on first use (landing); re-derive when the
  cached selector matches <3 elements (covers the first search submit and
  SPA re-renders). A failed derivation is cached negatively and only
  retried when the URL changes or the DOM size moves >20% — an empty
  letter-search page must not re-parse 36 times.
- Frame-aware: profiles key on the context object passed in, so a results
  iframe gets its own profile computed against that frame.
- Parity: every public function degrades to None/(None, False) — callers
  keep the legacy path as fallback, worst case is current behavior.
"""

from collections import OrderedDict
from dataclasses import dataclass

from config import REPETITION_COUNTING
from debug import debug
from repetition import find_repeated_records

# Same guards as navigator.count_visible_results' legacy evaluate: rendered
# element (non-zero rect) with >=15 chars of text. Returns -1 on a selector
# querySelectorAll can't parse — distinct from "matched nothing".
_COUNT_JS = """(sel) => {
    let nodes;
    try { nodes = document.querySelectorAll(sel); } catch (e) { return -1; }
    let count = 0;
    for (const el of nodes) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const t = (el.innerText || '').trim();
        if (t.length >= 15) count++;
    }
    return count;
}"""

_DOM_LEN_JS = "() => document.body ? document.body.innerHTML.length : 0"

# Below this many live matches the cached selector is considered stale and
# the page is re-profiled (plan: "re-derive when the cached selector matches
# <3 elements").
_MIN_LIVE_MATCHES = 3

_MAX_PROFILES = 64


@dataclass
class PageProfile:
    archetype: str = "UNKNOWN"
    record_selector: str | None = None
    # Survives a failed re-derivation (empty letter page) so the next full
    # listing revalidates it with one cheap JS count instead of a re-parse.
    last_good_selector: str | None = None
    expected_count: int | None = None
    has_directory_xhr: bool = False
    form_kind: str = "NONE"
    pager_kind: str = "none"
    url: str = ""
    dom_len: int = 0


# Keyed by id(context) — context objects (Page or Frame) aren't reliably
# weakref-able across Playwright versions. Bounded; a recycled id() at worst
# resurrects a stale selector, which the <3-live-matches rule re-derives.
_profiles: OrderedDict[int, PageProfile] = OrderedDict()

# Run-level count evidence (Phase 2). `expected` is the largest number-typed
# read_result_count() result seen this run; `observed` the best
# extraction-side count (live rendered counts, raw parse yields). Both feed
# the finish-time count gate in main.py; reset() clears them at run
# boundaries alongside the profiles.
_run_expected: int | None = None
_run_observed: int = 0


def reset() -> None:
    """Drop all cached profiles and run-level count evidence (test
    isolation / run boundaries)."""
    global _run_expected, _run_observed
    _profiles.clear()
    _run_expected = None
    _run_observed = 0


def note_expected_count(context, info) -> None:
    """Record a read_result_count() result: populates the context's
    profile.expected_count and the run-level expected total. Only
    number-typed results register — "all"/"unknown" never gate."""
    global _run_expected
    if not isinstance(info, dict) or info.get("type") != "number":
        return
    n = info.get("count")
    if not isinstance(n, int) or n <= 0:
        return
    prof = _profiles.get(id(context))
    if prof is not None:
        prof.expected_count = n
    if _run_expected is None or n > _run_expected:
        _run_expected = n


def note_observed(n) -> None:
    """Record extraction-side evidence (a live rendered count or a raw
    parse yield) for the count gate's marketing-copy sanity clamp."""
    global _run_observed
    if isinstance(n, int) and n > _run_observed:
        _run_observed = n


def run_count_evidence() -> tuple[int | None, int]:
    """(expected_total, best_observed) accumulated since the last reset()."""
    return _run_expected, _run_observed


def _store(key: int, prof: PageProfile) -> None:
    _profiles[key] = prof
    _profiles.move_to_end(key)
    while len(_profiles) > _MAX_PROFILES:
        _profiles.popitem(last=False)


def _live_count(context, selector: str) -> int:
    try:
        n = context.evaluate(_COUNT_JS, selector)
        return int(n)
    except Exception:
        return -1


def _dom_len(context) -> int:
    try:
        return int(context.evaluate(_DOM_LEN_JS))
    except Exception:
        return 0


def _derive(context) -> PageProfile:
    """(Re)profile the context: parse its current content and detect the
    record run. Always stores and returns a profile."""
    key = id(context)
    old = _profiles.get(key)
    try:
        url = context.url
        html = context.content()
    except Exception:
        url, html = "", ""
    selector, count, _samples = find_repeated_records(html) if html else (None, 0, [])

    last_good = selector or (old and (old.record_selector or old.last_good_selector)) or None
    prof = PageProfile(
        record_selector=selector,
        last_good_selector=last_good,
        url=url,
        dom_len=_dom_len(context),
    )
    if old is not None:
        prof.archetype = old.archetype
        prof.expected_count = old.expected_count
        prof.has_directory_xhr = old.has_directory_xhr
    _store(key, prof)
    debug.decision(
        "PROFILE",
        "record selector derived" if selector else "no record run detected",
        reason=f"structural repetition over {len(html)} chars",
        data={"selector": selector, "parse_count": count, "url": url[:120]},
    )
    if selector:
        print(f"  Profile: record selector '{selector}' ({count} records at derive)")
    return prof


def _count_via_profile(context, prof: PageProfile) -> int | None:
    for attr in ("record_selector", "last_good_selector"):
        sel = getattr(prof, attr)
        if not sel:
            continue
        n = _live_count(context, sel)
        if n >= _MIN_LIVE_MATCHES:
            if attr == "last_good_selector" and prof.record_selector != sel:
                prof.record_selector = sel
                debug.log("PROFILE", f"selector revalidated: '{sel}' ({n} live)")
            return n
    return None


def _should_rederive(context, prof: PageProfile) -> bool:
    if prof.record_selector:
        # Had a working selector, now <3 matches — page re-rendered.
        return True
    # Negative cache: only re-parse when the page plausibly changed.
    try:
        if context.url != prof.url:
            return True
    except Exception:
        return False
    dom_now = _dom_len(context)
    baseline = max(prof.dom_len, 1)
    return abs(dom_now - baseline) / baseline > 0.2


def count_records(context) -> int | None:
    """Live structural record count for a Page or Frame, or None when no
    validated record selector exists (caller falls back to the legacy
    counter). This is the plan's count_visible_results first rung."""
    if not REPETITION_COUNTING:
        return None
    prof = _profiles.get(id(context))
    if prof is not None:
        n = _count_via_profile(context, prof)
        if n is not None:
            note_observed(n)
            return n
        if not _should_rederive(context, prof):
            return None
    prof = _derive(context)
    n = _count_via_profile(context, prof)
    if n is not None:
        note_observed(n)
    return n


def rendered_record_count(page) -> tuple[int | None, bool]:
    """The single counting authority for decision gates: structural
    repetition count cross-checked against the distinct detail-link count
    (the signal the old blank-total branch proved out). Returns
    (count, exact); (None, False) means no exact evidence — the caller
    keeps its legacy heuristic.

    On >2x divergence between the two signals the smaller wins: an
    overcount at a stop-gate silently truncates the scrape (the R2 bug),
    while an undercount merely spends a few extra seconds on wildcards or
    pagination probes.
    """
    if not REPETITION_COUNTING:
        return None, False
    rep = count_records(page)
    links = 0
    try:
        from detail_crawler import collect_page_links, detect_detail_links
        links = len(detect_detail_links(collect_page_links(page)))
    except Exception:
        links = 0

    if rep is not None and links >= _MIN_LIVE_MATCHES:
        if rep > 2 * links or links > 2 * rep:
            debug.log(
                "PROFILE",
                f"count divergence: repetition={rep} vs detail_links={links} "
                f"— using the smaller",
                level="warn",
            )
            return min(rep, links), True
        return rep, True
    if rep is not None:
        return rep, True
    if links >= _MIN_LIVE_MATCHES:
        note_observed(links)
        return links, True
    return None, False
