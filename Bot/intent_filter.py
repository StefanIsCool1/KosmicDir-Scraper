"""
Intent-aware filtering for Agent-mode Phase 1 navigation.

Only the /discover (Agent) path supplies an `intent` dict. Playground modes
pass intent=None everywhere and every consumer falls back to the original
behavior, so Direct Scrape, Auto Discover, and CSV are bit-for-bit unchanged.

The two consumers are:
  1. `ai_analyze_page` in navigator.py — appends an intent hint to the STAY
     /CLICK prompt so the AI picks the relevant sub-directory link.
  2. `capture_responses` in browser.py — narrows `detect_category_links`
     output before the iteration loop, so we don't iterate all 25 chamber
     categories when the user only wants restaurants.

Both consumers are fall-open: if intent is None, no matches found, or the
LLM hiccups, they return/iterate the full set rather than dropping work.
"""

import json
import re

from llm import ask


# Cap how many categories we keep after intent filtering. Keeps the iteration
# loop bounded even when several sibling categories all look relevant
# (e.g. "Food", "Dining", "Restaurants" on the same chamber).
MAX_KEEP_PER_INTENT = 3


def intent_from_plan(plan: dict | None) -> dict | None:
    """Flatten a Phase 0 parse_intent plan into a small dict for Phase 1.

    Returns None if the plan isn't actionable or has no industry — callers
    treat None as "no intent context" and use default behavior.
    """
    if not plan or not plan.get("is_actionable"):
        return None

    industry = plan.get("industry") or {}
    canonical = (industry.get("canonical") or "").strip()
    if not canonical:
        return None

    aliases = [
        (a or "").strip()
        for a in (industry.get("aliases") or [])
        if (a or "").strip()
    ]
    locations = plan.get("locations") or []
    return {
        "industry_canonical": canonical,
        "industry_aliases": aliases,
        "entity_type": industry.get("entity_type") or "",
        "location_states": [loc.get("state", "") for loc in locations if loc.get("state")],
        "location_cities": [c for loc in locations for c in (loc.get("cities_hint") or [])],
    }


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _llm_pick_categories(
    categories: list[dict],
    intent: dict,
    max_keep: int = MAX_KEEP_PER_INTENT,
) -> list[dict]:
    """One DeepSeek call: pick up to `max_keep` categories that match intent.

    Used when substring matching finds zero hits — catches synonyms
    ("Dining Out" → restaurants) and broader umbrellas ("Food & Beverage").
    Returns [] on any failure path; the caller treats that as "fall open".
    """
    if not categories:
        return []

    canonical = intent.get("industry_canonical", "") or "the user's target"
    aliases = intent.get("industry_aliases", []) or []
    alias_hint = f" (also known as: {', '.join(aliases[:5])})" if aliases else ""

    enumerated = "\n".join(
        f"{i + 1}. {cat.get('text', '')}"
        for i, cat in enumerate(categories)
    )

    prompt = f"""You are picking category labels from a directory listing page.

The user wants entries about: {canonical}{alias_hint}.

Pick up to {max_keep} category labels below that are MOST LIKELY to contain {canonical}.
Include synonyms and broader umbrella terms (e.g. "Food & Beverage" is relevant for restaurants).
If none of the labels could plausibly contain {canonical}, return an empty list.

Categories:
{enumerated}

Return ONLY a JSON object — no markdown fences, no explanation:
{{"keep": [<1-based numbers, at most {max_keep}>]}}
"""

    try:
        raw = ask(prompt, max_tokens=150)
    except Exception as e:
        print(f"  Intent category filter: LLM call failed ({e}) — falling open")
        return []

    text = _strip_fences(raw)
    try:
        decision = json.loads(text)
    except json.JSONDecodeError:
        print(f"  Intent category filter: non-JSON response — falling open")
        return []

    if not isinstance(decision, dict):
        return []
    keep = decision.get("keep")
    if not isinstance(keep, list):
        return []

    picked: list[dict] = []
    seen: set[int] = set()
    for idx in keep:
        if not isinstance(idx, int):
            continue
        if idx < 1 or idx > len(categories):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(categories[idx - 1])
        if len(picked) >= max_keep:
            break
    return picked


def filter_categories_by_intent(
    categories: list[dict],
    intent: dict | None,
) -> list[dict]:
    """Narrow detected category links to ones matching the user's intent.

    Layers, cheapest first:
      1. Substring match on canonical + aliases → keep up to MAX_KEEP_PER_INTENT
      2. One LLM call to pick from labels (catches synonyms substring misses)
      3. Fall open: return the original list

    Safety: the upstream guards in detect_category_links (visible-result
    threshold) and capture_responses (no JSON results AND no visible members)
    already prevent this from running when the page itself is showing the
    relevant content. So narrowing here can only remove sibling categories
    we'd otherwise have wasted time iterating.
    """
    if not intent or not categories:
        return categories

    canonical = (intent.get("industry_canonical") or "").lower()
    aliases = {(a or "").lower() for a in intent.get("industry_aliases", []) if a}
    if canonical:
        aliases.add(canonical)
    if not aliases:
        return categories

    matches: list[dict] = []
    for cat in categories:
        text = (cat.get("text") or "").lower()
        if any(a and a in text for a in aliases):
            matches.append(cat)

    if matches:
        capped = matches[:MAX_KEEP_PER_INTENT]
        print(
            f"  Intent category filter: substring matched {len(capped)}/{len(categories)} "
            f"for '{canonical}'"
        )
        return capped

    picked = _llm_pick_categories(categories, intent, max_keep=MAX_KEEP_PER_INTENT)
    if picked:
        print(
            f"  Intent category filter: LLM picked {len(picked)}/{len(categories)} "
            f"for '{canonical}'"
        )
        return picked

    print(
        f"  Intent category filter: no matches for '{canonical}' — "
        f"iterating all {len(categories)} categories"
    )
    return categories
