"""
Phase 0 — Intent Parsing
One LLM call: free-form user goal → structured search plan.

Also acts as the SCOPE GATE for the whole pipeline. The tool scrapes
directories of businesses/organizations/professionals/members — not jobs,
news, products, real estate, recipes, events, or individual people.
Out-of-scope queries return is_actionable=false with a clarification
explaining the tool's scope, so the user doesn't waste time on a scrape
whose schema (company_name/phone/address/website) doesn't fit their goal.

Reuses Bot/llm.py's ask() client (DeepSeek, OpenAI-compatible) without
modifying it. Falls back to a deterministic plan if the call fails.
"""

import json
import os
import re
import sys

# Reuse Bot/llm.py — additive import, we do not modify the file.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from llm import ask  # type: ignore  # noqa: E402


# Deterministic region → state expansion. Used as a safety net when the
# LLM forgets to expand a region keyword.
# Inputs that obviously aren't scraping goals. Short-circuit these
# without burning an LLM call — we'd just get garbage queries back
# (e.g. "hi" → "hi directory" → generic business-directory junk).
_TRIVIAL_INPUTS = {
    "hi", "hello", "hey", "yo", "sup", "howdy", "greetings",
    "test", "testing", "hello world",
    "what", "huh", "?", "??", "???",
    "ok", "okay", "k", "kk",
    "help", "what can you do", "what do you do", "what is this",
    "thanks", "thank you", "ty", "thx",
    "bye", "goodbye", "cya",
    "yes", "no", "y", "n",
}


REGION_TO_STATES = {
    "midwest": ["IL", "OH", "MI", "IN", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
    "northeast": ["NY", "NJ", "PA", "MA", "CT", "RI", "NH", "VT", "ME"],
    "southeast": ["FL", "GA", "AL", "MS", "SC", "NC", "TN", "KY", "VA", "WV", "AR", "LA"],
    "southwest": ["TX", "OK", "NM", "AZ"],
    "west coast": ["CA", "OR", "WA"],
    "west": ["CA", "OR", "WA", "NV", "ID", "UT", "AZ", "MT", "WY", "CO"],
    "northwest": ["WA", "OR", "ID", "MT"],
    "new england": ["ME", "NH", "VT", "MA", "CT", "RI"],
    "south": ["TX", "FL", "GA", "AL", "MS", "SC", "NC", "TN", "KY", "VA", "AR", "LA", "OK"],
    "pacific northwest": ["WA", "OR", "ID"],
}


def _build_prompt(goal: str) -> str:
    return f"""Parse this user message into a structured search plan for finding business or organization directories.

User message: {goal}

This tool scrapes DIRECTORIES of businesses, organizations, professionals, and members. It extracts fields like company_name, phone, address, website, contacts. It does NOT handle jobs, news, products, real estate listings, recipes, events, or individual people.

FIRST decide if this is an actionable goal FOR THIS TOOL.

ACTIONABLE — the user wants a directory or list of ENTITIES (businesses/orgs/professionals/members):
  • "HOAs in Washington", "dentists in Austin", "roofing contractors in Florida"
  • "restaurants in Austin", "law firms in New York", "chambers of commerce in Texas"
  • "Austin Chamber members", "AGA member list", "alumni directory of UCLA"
  • Qualifiers like "best", "top", "all" are fine — the underlying ask is still a list of entities.

NOT ACTIONABLE — the user wants something this tool can't produce. Set is_actionable=false and return a helpful clarification:
  • JOBS / employment ("jobs in NYC", "openings at Google", "hiring near me", "remote dev jobs", "career opportunities")
  • NEWS / articles ("news about X", "press releases", "articles on Y")
  • REVIEWS / opinion ("reviews of X", "what people say about Y", "ratings for Z")
  • PRODUCTS / shopping ("laptops under $1000", "Nike shoes", "buy X")
  • REAL ESTATE listings ("homes for sale", "apartments for rent", "houses in Austin")
  • RECIPES / how-to / blog content
  • INDIVIDUAL PERSON searches ("find John Smith", "LinkedIn profile of X")
  • EVENTS ("concerts this weekend", "conferences in 2026")
  • PURE DATA / statistics ("how many X exist", "average salary of Y")
  • Greetings, tool questions, vague requests ("hi", "what can you do", "scrape something", random text)

DISAMBIGUATION RULE — focus on the PRIMARY thing the user wants:
  • "staffing agencies in Austin" → ACTIONABLE (directory of staffing businesses)
  • "jobs at staffing agencies in Austin" → NOT actionable (user wants job postings)
  • "real estate companies in Austin" → ACTIONABLE (directory of agencies)
  • "homes for sale in Austin" → NOT actionable (user wants property listings)
  • "marketing agencies" → ACTIONABLE
  • "marketing jobs" → NOT actionable
If genuinely ambiguous, default to ACTIONABLE.

Return ONLY a JSON object — no markdown fences, no explanation. Use this schema:
{{
  "is_actionable": <true | false>,
  "clarification": "<REQUIRED when NOT actionable. 1-2 friendly sentences. For greetings/vague messages: ask what they want to scrape with an example like 'HOAs in Washington' or 'dentists in Austin'. For OUT-OF-SCOPE data types: briefly say this tool scrapes business/member directories (not jobs/products/news/etc.) and suggest a related directory query that WOULD work — e.g. for 'jobs in Austin' suggest 'staffing agencies in Austin'; for 'homes for sale in Austin' suggest 'real estate agencies in Austin'; for 'best restaurants reviews' suggest 'restaurants in <city>'. Omit when actionable.>",
  "industry": {{
    "canonical": "<lowercase canonical name, e.g. 'homeowners associations'>",
    "aliases": ["<2-5 alternate names the directory might use>"],
    "entity_type": "<one of: business, nonprofit_organization, professional_practice, restaurant, service_provider>"
  }},
  "locations": [
    {{"state": "<2-letter US state code>", "cities_hint": ["<1-3 major cities in that state>"]}}
  ],
  "search_queries": [
    "<3-6 search queries, each under 80 chars, that would find directory pages for this industry + location>"
  ],
  "platform_hints": ["<known directory platforms or domains, e.g. 'growthzone', 'yourmembership', 'hoa-usa.com'>"]
}}

When is_actionable is false, only "is_actionable" and "clarification" are required — omit the other fields.

Rules when actionable:
- If the user mentions a region (Midwest, Northeast, etc.), expand to all states in that region.
- If no location is mentioned, set "locations" to [] and write queries without location.
- "Washington" without other context means WA state, not DC.
- search_queries should be diverse — mix "<state> <industry> directory", "find a <industry>", "<industry> member list", etc.
- platform_hints may be [] if you don't know any specific platform for this industry.
"""


def _strip_fences(text: str) -> str:
    """Strip markdown code fences if the model wrapped the response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _expand_regions(goal: str, plan: dict) -> dict:
    """If the LLM didn't expand a region keyword, do it deterministically."""
    if plan.get("locations"):
        return plan
    goal_lower = goal.lower()
    # Check longer region phrases first (e.g. "new england" before "england")
    for region in sorted(REGION_TO_STATES.keys(), key=len, reverse=True):
        if region in goal_lower:
            plan["locations"] = [
                {"state": s, "cities_hint": []} for s in REGION_TO_STATES[region]
            ]
            break
    return plan


def _fallback_plan(goal: str) -> dict:
    """Used when LLM parsing completely fails on an apparently-actionable
    goal. Degrades to keyword-only search rather than asking for clarification."""
    return {
        "is_actionable": True,
        "industry": {
            "canonical": goal.lower(),
            "aliases": [],
            "entity_type": "business",
        },
        "locations": [],
        "search_queries": [
            f"{goal} directory",
            f"find a {goal}",
            f"{goal} member list",
            f"{goal} association",
        ],
        "platform_hints": [],
    }


def _clarification_plan(question: str) -> dict:
    """Returned when the user's message isn't a real scraping goal."""
    return {
        "is_actionable": False,
        "clarification": question,
        "industry": {"canonical": "", "aliases": [], "entity_type": "business"},
        "locations": [],
        "search_queries": [],
        "platform_hints": [],
    }


def _is_trivial(goal: str) -> bool:
    """Deterministic short-circuit: obvious non-goals get rejected
    without an LLM call."""
    g = goal.lower().strip().strip("?.!,'\" ")
    if len(g) < 2:
        return True
    if g in _TRIVIAL_INPUTS:
        return True
    return False


_DEFAULT_CLARIFICATION = (
    "This tool scrapes ONLY directory type data of businesses, organizations, and professionals "
    "What kind of directory are you looking for? "
    "Try something like 'HOAs in Washington' or 'dentists in Austin, TX'."
)


def parse_intent(goal: str) -> dict:
    """Parse a free-form user message into a structured search plan.

    Always returns a dict with `is_actionable`. When False, the dict also
    has a `clarification` string — the pipeline emits it back to the user
    instead of running discovery.
    """
    goal = (goal or "").strip()

    # Layer 1: deterministic guard — saves an LLM call on obvious junk
    if _is_trivial(goal):
        return _clarification_plan(_DEFAULT_CLARIFICATION)

    # Layer 2: LLM-side gate
    try:
        raw = ask(_build_prompt(goal), max_tokens=1200)
    except Exception as e:
        print(f"  Intent: LLM call failed ({e}) — using fallback plan")
        return _fallback_plan(goal)

    text = _strip_fences(raw) #strips response to make it cleaner
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  Intent: LLM returned non-JSON ({e}) — using fallback plan")
        return _fallback_plan(goal)

    if not isinstance(plan, dict):
        return _fallback_plan(goal)

    # Honor the LLM's clarification call
    if plan.get("is_actionable") is False:
        question = (plan.get("clarification") or "").strip() or _DEFAULT_CLARIFICATION
        return _clarification_plan(question)

    # Even if the LLM said "actionable", require search_queries to actually
    # exist — otherwise we'd send DDG empty queries.
    queries = plan.get("search_queries") or []
    if not queries:
        print("  Intent: LLM said actionable but returned no queries — fallback")
        return _fallback_plan(goal)

    # Normalize minimum shape so downstream code can assume keys exist
    plan["is_actionable"] = True
    plan.setdefault("industry", {"canonical": goal.lower(), "aliases": [], "entity_type": "business"})
    plan.setdefault("locations", [])
    plan.setdefault("platform_hints", [])

    # Safety net: catch region keywords the LLM may have ignored
    plan = _expand_regions(goal, plan)
    return plan
