"""
Phase 0 — Discovery Pipeline Orchestrator

Wires intent → sources → preflight → classifier into a single callable.
Emits progress events through an optional callback so the Flask SSE
endpoint can stream them to the frontend.
"""

from .intent import parse_intent
from .sources import discover_candidates
from .preflight import preflight_all
from .classifier import classify_all


def run_discovery(goal: str, event_cb=None) -> dict:
    """Run the full Phase 0 pipeline.

    Args:
        goal: Free-form user text describing what they want to scrape.
        event_cb: Optional callable(dict). Called for each progress event.
                  See README in this module for event types.

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

    # --- Step 2: Source discovery (web search) ---
    queries = plan.get("search_queries") or []
    emit({
        "type": "stage", "stage": "discovery",
        "message": f"Searching {len(queries)} queries for candidate sources...",
        "query_count": len(queries),
    })
    candidates = discover_candidates(plan, event_cb=emit)
    emit({"type": "candidates_found", "count": len(candidates)})

    if not candidates:
        emit({"type": "warning", "message": "No candidates returned from web search."})
        return {
            "plan": plan,
            "directories": [],
            "websites": [],
            "rejected_count": 0,
            "reject_reasons": {},
        }

    # --- Step 3: Pre-flight qualification ---
    emit({
        "type": "stage", "stage": "preflight",
        "message": f"Qualifying {len(candidates)} candidates (parallel HTTP)...",
        "total": len(candidates),
    })
    passed, rejected_pre = preflight_all(candidates, event_cb=emit)
    emit({
        "type": "preflight_done",
        "passed": len(passed),
        "rejected": len(rejected_pre),
    })

    # --- Step 4: Classify survivors ---
    emit({
        "type": "stage", "stage": "classify",
        "message": f"Classifying {len(passed)} qualified URLs...",
        "total": len(passed),
    })
    classified = classify_all(passed, event_cb=emit)

    # Combine rejection reasons from preflight + classify
    all_rejected = rejected_pre + classified["rejected"]
    reject_reasons: dict[str, int] = {}
    for r in all_rejected:
        reason = r.get("reason") or "unknown"
        reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    result = {
        "plan": plan,
        "directories": classified["directories"],
        "websites": classified["websites"],
        "rejected_count": len(all_rejected),
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
