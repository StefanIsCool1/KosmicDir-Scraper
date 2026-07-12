"""
Phase 0 — Discovery Pipeline Orchestrator

Wires intent → sources → preflight → classifier into a single callable.
Emits progress events through an optional callback so the Flask SSE
endpoint can stream them to the frontend.
"""

import os
import sys

from .intent import parse_intent
from .sources import discover_candidates
from .preflight import preflight_all
from .classifier import classify_all
from .aggregator_fallback import build_fallback_candidates

# Reuse Bot/debug.py's trace singleton (stdlib-only module — keeps Phase 0's
# no-Playwright rule intact). Same additive-import pattern as intent.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from debug import debug  # type: ignore  # noqa: E402


def _maybe_api_route(plan: dict, emit) -> dict | None:
    """If the plan maps to a supported authoritative API, return an API-branch
    result dict (no scraping); otherwise None to continue normal discovery.

    Currently supports NPI (US healthcare practitioners). Phase 0's LLM
    proposes `api_vertical`/`api_params`; this is the real gate — it resolves
    the term to NPI taxonomy strings and only routes when that succeeds AND a
    2-letter state is present. A miss falls back to directory discovery, so a
    wrong LLM guess costs the routing, not the run.
    """
    if plan.get("api_vertical") != "npi":
        return None

    raw = plan.get("api_params") or {}
    term = (raw.get("taxonomy") or (plan.get("industry") or {}).get("canonical") or "").strip()
    state = (raw.get("state") or "").strip().upper()
    city = (raw.get("city") or "").strip() or None

    # Lazy import via the same path mechanism sources.py / preflight.py use.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from Phase2Bot.vertical_enrichment import resolve_npi_taxonomies  # type: ignore
    except Exception as e:
        print(f"  API route: NPI client import failed ({e}) — using discovery")
        return None

    taxonomies = resolve_npi_taxonomies(term)
    if not taxonomies or len(state) != 2:
        emit({
            "type": "stage", "stage": "discovery",
            "message": (f"NPI registry can't serve '{term or 'that'}'"
                        + (f" in {state}" if state else " without a US state")
                        + " — searching directories instead."),
        })
        return None

    emit({
        "type": "stage", "stage": "api_route",
        "message": (f"Pulling {term} in {state} straight from the NPI registry "
                    f"— authoritative data, no scraping needed..."),
    })
    return {
        "api_vertical": "npi",
        "api_params": {
            "taxonomy_queries": taxonomies,
            "state": state,
            "city": city,
            "term": term,
        },
        "plan": plan,
        "directories": [],
        "websites": [],
        "rejected_count": 0,
        "reject_reasons": {},
    }


def _qualify_and_classify(candidates: list[dict], emit) -> tuple[list, list, list]:
    """Run preflight + classify over a candidate list.

    Returns (directories, websites, rejected). Safe on an empty list — used for
    both the primary discovery candidates and the aggregator fallback, so the
    two paths qualify identically.
    """
    if not candidates:
        return [], [], []

    emit({
        "type": "stage", "stage": "preflight",
        "message": f"Qualifying {len(candidates)} candidates (parallel HTTP)...",
        "total": len(candidates),
    })
    with debug.span("PHASE0", f"preflight ({len(candidates)} candidates)"):
        passed, rejected_pre = preflight_all(candidates, event_cb=emit)
    emit({"type": "preflight_done", "passed": len(passed), "rejected": len(rejected_pre)})
    debug.log("PHASE0", f"Preflight: {len(passed)} passed, {len(rejected_pre)} rejected",
              data={"rejected": [
                  {"url": r.get("url", "")[:100], "reason": r.get("reason", "")}
                  for r in rejected_pre[:20]
              ]})

    emit({
        "type": "stage", "stage": "classify",
        "message": f"Classifying {len(passed)} qualified URLs...",
        "total": len(passed),
    })
    with debug.span("PHASE0", f"classify ({len(passed)} URLs)"):
        classified = classify_all(passed, event_cb=emit)
    for d in classified["directories"]:
        debug.decision("PHASE0", "route DIRECTORY → Phase 1",
                       data={"url": d.get("url", "")[:120]})
    for w in classified["websites"]:
        debug.decision("PHASE0", "route WEBSITE → Phase 2",
                       data={"url": w.get("url", "")[:120]})
    return (
        classified["directories"],
        classified["websites"],
        rejected_pre + classified["rejected"],
    )


def run_discovery(goal: str, event_cb=None) -> dict:
    """Run the full Phase 0 pipeline.

    Args:
        goal: Free-form user text describing what they want to scrape.
        event_cb: Optional callable(dict). Called for each progress event.
                  See README in this module for event types.

    Note: discovery is deliberately INDEPENDENT of the scope choice
    (specialists vs anyone-who-does-it). The parsed plan carries
    `scope_ambiguous` / `scope_question` / `scope_options`, but the scope
    question is asked by the caller (app.py) AFTER discovery completes, so
    searching never waits on it and the same sites are found either way.
    Scope only tunes Phase 1 filtering, via intent_from_plan.

    Returns:
        {
            "plan": <intent JSON>,
            "directories": [<classified entries>],
            "websites":    [<classified entries>],
            "rejected_count": int,
            "reject_reasons": {<reason>: count}
        }
    """
    def emit(event):
        if event_cb:
            event_cb(event)

    # --- Step 1: Intent ---
    emit({"type": "stage", "stage": "intent", "message": "Parsing your goal..."})
    debug.log("PHASE0", f"Discovery started for goal: {goal[:200]}")
    with debug.span("PHASE0", "intent parsing (1 LLM call)"):
        plan = parse_intent(goal)

    # If the intent parser decided this isn't an actionable scraping goal
    # (greeting, vague request, tool question), bail out here. The frontend
    # renders the clarification question as a normal chat reply and lets the
    # user try again — no discovery, no LLM cost on garbage queries.
    if not plan.get("is_actionable", True):
        emit({
            "type": "needs_clarification",
            "question": plan.get("clarification") or "Could you tell me what you'd like to scrape?",
        })
        return {
            "plan": plan,
            "directories": [],
            "websites": [],
            "rejected_count": 0,
            "reject_reasons": {},
            "needs_clarification": True,
        }

    emit({"type": "intent_parsed", "plan": plan})

    # --- API route: skip scraping for verticals an authoritative API answers ---
    # When Phase 0 recognizes a goal a public registry can serve directly
    # (currently NPI for US healthcare practitioners), resolve it to API params
    # and return WITHOUT running DDG / preflight / classify / browser. app.py
    # sees `api_vertical` and fetches the data directly.
    api_result = _maybe_api_route(plan, emit)
    if api_result is not None:
        debug.decision("PHASE0", "API route (NPI)",
                       "goal answerable by authoritative registry — no scraping",
                       data=api_result.get("api_params"))
        return api_result

    # --- Step 2: Source discovery (web search) ---
    queries = plan.get("search_queries") or []
    emit({
        "type": "stage", "stage": "discovery",
        "message": f"Searching {len(queries)} queries for candidate sources...",
        "query_count": len(queries),
    })
    with debug.span("PHASE0", f"source discovery ({len(queries)} search queries)"):
        candidates = discover_candidates(plan, event_cb=emit)
    emit({"type": "candidates_found", "count": len(candidates)})
    debug.log("PHASE0", f"Discovery found {len(candidates)} candidate URLs")

    if not candidates:
        emit({"type": "warning", "message": "No candidates returned from web search."})

    # --- Steps 3+4: Pre-flight qualification, then classify survivors ---
    directories, websites, rejected = _qualify_and_classify(candidates, emit)

    # --- Fallback: no dedicated directory qualified -> general listings ---
    # Fires ONLY when the primary path found zero directories — so queries that
    # already work (HOAs, chambers, professional associations) are untouched.
    # Builds direct category+location search URLs on general business-listing
    # aggregators (YellowPages, Manta, ...) and qualifies them the same way.
    # Direct URLs sidestep DDG, which is usually *why* discovery came up empty.
    if not directories:
        fb_candidates = build_fallback_candidates(plan)
        if fb_candidates:
            debug.decision("PHASE0", "aggregator fallback",
                           f"0 dedicated directories qualified — trying "
                           f"{len(fb_candidates)} general business listings")
            emit({
                "type": "stage", "stage": "discovery",
                "message": ("No dedicated directory found — searching general "
                            "business listings (YellowPages, Manta, ...)."),
            })
            fb_dirs, fb_sites, fb_rejected = _qualify_and_classify(fb_candidates, emit)
            directories = fb_dirs
            websites = websites + fb_sites
            rejected = rejected + fb_rejected

    # Tally rejection reasons across whichever paths ran.
    reject_reasons: dict[str, int] = {}
    for r in rejected:
        reason = r.get("reason") or "unknown"
        reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    result = {
        "plan": plan,
        "directories": directories,
        "websites": websites,
        "rejected_count": len(rejected),
        "reject_reasons": reject_reasons,
    }

    # Include the actual URL lists in the event so the frontend can show
    # the user exactly what was found before Phase 1/2 start.
    emit({
        "type": "discovery_complete",
        "directories": [
            {
                "url": d["url"],
                "title": d.get("title", ""),
                "needs_navigation": d.get("needs_navigation", False),
                "landing_link": d.get("landing_link"),
            }
            for d in result["directories"]
        ],
        "websites": [
            {"url": w["url"], "title": w.get("title", "")}
            for w in result["websites"]
        ],
        "directories_count": len(result["directories"]),
        "websites_count": len(result["websites"]),
        "rejected_count": result["rejected_count"],
        "reject_reasons": result["reject_reasons"],
    })

    return result
