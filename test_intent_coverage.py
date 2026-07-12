"""Tests for the `coverage` intent field (scrape-everything recognition).

Two layers:
  1. No-LLM: intent_from_plan mapping + the f-string brace guard on _build_prompt
  2. Live (needs DEEPSEEK_API_KEY): parse_intent classifies real goals

Run: python3 test_intent_coverage.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "DiscoveryBot"))

from intent_filter import intent_from_plan          # noqa: E402  (Bot/)
from intent import parse_intent, _build_prompt       # noqa: E402  (DiscoveryBot/)

_failures = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures.append(name)


def _actionable_plan(**over):
    plan = {
        "is_actionable": True,
        "industry": {"canonical": "deck builders",
                     "aliases": ["deck contractors"], "entity_type": "service_provider"},
        "locations": [{"state": "MN", "cities_hint": ["Minneapolis"]}],
        "search_queries": ["deck builders minnesota"],
        "scope": "specialist",
    }
    plan.update(over)
    return plan


def test_no_llm():
    print("No-LLM layer:")

    # Backward compat: a plan with NO coverage key behaves like targeted → dict.
    got = intent_from_plan(_actionable_plan())
    check("missing coverage → non-None intent dict", isinstance(got, dict))
    check("missing coverage → industry_canonical carried",
          got and got.get("industry_canonical") == "deck builders")

    # coverage="targeted" → dict (unchanged shape).
    got = intent_from_plan(_actionable_plan(coverage="targeted"))
    check("coverage=targeted → non-None intent dict", isinstance(got, dict))

    # coverage="all" → None (maps to plain full-coverage flow).
    check("coverage=all → None", intent_from_plan(_actionable_plan(coverage="all")) is None)
    check("coverage=ALL (case) → None",
          intent_from_plan(_actionable_plan(coverage="ALL")) is None)

    # Non-actionable still None regardless of coverage.
    check("non-actionable → None",
          intent_from_plan({"is_actionable": False, "coverage": "targeted"}) is None)

    # The documented f-string brace hazard: a single stray brace throws at
    # format time and silently degrades EVERY goal. Guard it explicitly.
    try:
        p = _build_prompt("all businesses in the Duluth chamber")
        check("_build_prompt does not raise", isinstance(p, str) and len(p) > 100)
        check("_build_prompt embeds the coverage field", '"coverage"' in p)
    except Exception as e:
        check(f"_build_prompt does not raise (got {e!r})", False)


def test_live():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("Live layer: SKIPPED (no DEEPSEEK_API_KEY)")
        return
    print("Live layer (DeepSeek):")
    cases = [
        ("scrape everything from the Duluth chamber of commerce directory", "all"),
        ("deck builders in Minnesota", "targeted"),
        ("all dentists in Austin", "targeted"),  # 'all' modifies an industry
    ]
    for goal, expected in cases:
        try:
            plan = parse_intent(goal)
            got = plan.get("coverage")
            check(f"{goal!r} → coverage={expected} (got {got})", got == expected)
        except Exception as e:
            check(f"{goal!r} parse raised {e!r}", False)


if __name__ == "__main__":
    test_no_llm()
    test_live()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): {_failures}")
        sys.exit(1)
    print("ALL PASSED")
