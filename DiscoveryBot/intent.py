"""
Phase 0 — Intent Parsing
One LLM call: free-form user goal → structured search plan.

Also acts as the SCOPE GATE for the whole pipeline. The test is simple:
does an online DIRECTORY or LISTING of these entities exist? The unit may
be a business, an organization, OR an individual professional/member —
dentists, lawyers, and real-estate agents are all in scope, because
directories of them exist (Phase 2 even has dedicated per-vertical lookups
for them). Out of scope is data that doesn't live in a directory: jobs,
news, products, real-estate *property* listings, recipes, events, raw
statistics, a single named private person, or a category of people no
directory indexes (retail clerks, employees, residents). Those return
is_actionable=false with a clarification, so the user doesn't waste time on
a scrape whose schema (company_name/phone/address/website) doesn't fit.

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

This tool scrapes DIRECTORIES and LISTINGS of entities — businesses, organizations, professionals, and members. It extracts fields like company_name, phone, address, website, contacts. The entity CAN be an individual professional: a dentist, lawyer, or real-estate agent is in scope, because directories of them exist. The real test for any goal is: "would I find these on a directory or listing page?" It does NOT handle data that has no such directory — job postings, news, products for sale, real-estate PROPERTY listings (homes/apartments), recipes, events, raw statistics, or a SINGLE named private person.

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
  • A SINGLE NAMED private person ("find John Smith", "LinkedIn profile of Jane Doe"). NOTE: a CATEGORY of listed professionals is IN scope — "dentists in Austin", "real estate agents in Denver" are ACTIONABLE because directories of them exist.
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
  • "dentists in Austin" → ACTIONABLE (a directory of dentists exists)
  • "retail stores in Minnesota" → ACTIONABLE; "retail workers/employees in Minnesota" → NOT actionable (no directory of individual store employees)
If genuinely ambiguous, default to ACTIONABLE.

Return ONLY a JSON object — no markdown fences, no explanation. Use this schema:
{{
  "is_actionable": <true | false>,
  "clarification": "<REQUIRED when NOT actionable. 1-2 friendly sentences. For greetings/vague messages: ask what they want to scrape with an example like 'HOAs in Washington' or 'dentists in Austin'. For OUT-OF-SCOPE goals: explain it in terms of whether a DIRECTORY of the thing exists — this tool needs a directory/listing to scrape — then suggest the closest query that WOULD work. Do NOT claim it can't do individual professionals; it can (dentists, lawyers, agents). Examples: 'jobs in Austin' → suggest 'staffing agencies in Austin'; 'homes for sale in Austin' → suggest 'real estate agencies in Austin'; 'retail workers in Minnesota' → suggest 'retail stores in Minnesota'; 'best restaurants reviews' → suggest 'restaurants in <city>'. Omit when actionable.>",
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
  "platform_hints": ["<known directory platforms or domains, e.g. 'growthzone', 'yourmembership', 'hoa-usa.com'>"],
  "api_vertical": "<'npi' if the goal is US HEALTHCARE PRACTITIONERS the NPI registry covers — dentists, chiropractors, optometrists, podiatrists, physical/occupational/speech therapists, psychologists, audiologists, dietitians, nurse practitioners, midwives, pharmacists, acupuncturists, etc. — AND a US state is given. Otherwise null. Do NOT use 'npi' for veterinarians (not in NPI), hospitals/clinics (use a directory), or broad 'doctors'/'physicians' (too many taxonomies — leave null).>",
  "api_params": {{"taxonomy": "<the practitioner type, singular, e.g. 'dentist'>", "state": "<2-letter US state>", "city": "<optional single city, or empty string>"}},
  "scope_ambiguous": <true | false>,
  "scope_question": "<REQUIRED when scope_ambiguous=true: ONE friendly sentence asking whether they want specialists only, or anyone who does this work. Empty string otherwise.>",
  "scope_options": ["<short label for the SPECIALISTS-ONLY choice>", "<short label for the ANYONE-WHO-DOES-IT choice>"],
  "coverage": "<'all' when the user wants EVERYTHING a directory or site lists, with NO industry qualifier — 'all businesses in the Duluth chamber', 'everything from this directory', 'every member/listing'. 'targeted' when they want a specific industry, profession, or subset. Default 'targeted'.>"
}}

When is_actionable is false, only "is_actionable" and "clarification" are required — omit the other fields.

Rules when actionable:
- If the user mentions a region (Midwest, Northeast, etc.), expand to all states in that region.
- If no location is mentioned, set "locations" to [] and write queries without location.
- "Washington" without other context means WA state, not DC.
- search_queries should be diverse — mix "<state> <industry> directory", "find a <industry>", "<industry> member list", etc.
- platform_hints may be [] if you don't know any specific platform for this industry.
- api_vertical: set "npi" ONLY for the healthcare practitioners listed above with a US state.
  When unsure, leave it null — a downstream check validates the taxonomy and falls back to
  normal directory discovery anyway, so a wrong "npi" guess wastes the routing, not the run.
- coverage: "all" ONLY when no industry narrows the ask — the user wants a whole directory
  ("all businesses in the Duluth chamber", "the entire member list"). An "all"/"every" that
  modifies a specific industry is still "targeted": "all dentists in Austin" → "targeted".

SCOPE AMBIGUITY — decide whether the target is a specific build/remodel/trade CAPABILITY that
general contractors, remodelers, or broader firms also provide, so "the results" could mean two
different things to the user:
- Set scope_ambiguous=TRUE when the industry is a capability generalists also offer and would be
  found mixed into general builder/contractor directories: decks, fences, kitchens, bathrooms,
  basements, remodeling, flooring, siding, patios, sunrooms, additions, landscaping, painting,
  concrete, etc. These directories list both specialists AND general firms that do this work
  among many other things — so the user must tell us which they want.
- Set scope_ambiguous=FALSE for self-contained categories where membership is unambiguous: HOAs,
  dentists, doctors, law firms, restaurants, chambers of commerce, accounting/CPA firms, real
  estate agencies, staffing agencies, insurance agencies, veterinarians.
- When TRUE, write scope_question as ONE friendly sentence and scope_options as exactly two short
  labels [specialists-only, anyone-who-does-it]. Example for "deck builders":
  scope_question: "Do you want only companies that specialize in decks, or also general contractors and remodelers who build decks among other work?"
  scope_options: ["Deck specialists only", "Anyone who builds decks"]
- When FALSE, set scope_question to "" and scope_options to [].
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
        "scope_ambiguous": False,
        "scope_question": "",
        "scope_options": [],
        "api_vertical": None,
        "api_params": {},
        "coverage": "targeted",
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
        "scope_ambiguous": False,
        "scope_question": "",
        "scope_options": [],
        "api_vertical": None,
        "api_params": {},
        "coverage": "targeted",
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
    "This tool scrapes directory-style listings — businesses, organizations, "
    "and individual professionals (e.g. dentists, lawyers, agents). "
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

    # Scope refinement: only a clean boolean + question/options survive. If the
    # LLM marked it ambiguous but gave no usable question/options, treat it as
    # unambiguous so the gate doesn't ask a blank question.
    plan["scope_ambiguous"] = bool(plan.get("scope_ambiguous")) and bool(
        (plan.get("scope_question") or "").strip()
    )
    plan.setdefault("scope_question", "")
    options = plan.get("scope_options")
    plan["scope_options"] = options if isinstance(options, list) and len(options) == 2 else []
    if not plan["scope_options"]:
        plan["scope_ambiguous"] = False

    # API-route normalization: only "npi" is supported today. The real
    # gate is pipeline._maybe_api_route (it resolves the taxonomy and falls
    # back to discovery on a miss), so here we just clean the shape.
    plan["api_vertical"] = plan.get("api_vertical") if plan.get("api_vertical") in ("npi",) else None
    plan["api_params"] = plan["api_params"] if isinstance(plan.get("api_params"), dict) else {}

    # Coverage: "all" = scrape the whole directory (intent_from_plan maps it
    # to intent=None so Phase 1 runs the plain wildcard flow). Anything the
    # LLM didn't answer cleanly stays "targeted" — today's behavior.
    coverage = plan.get("coverage")
    plan["coverage"] = coverage if isinstance(coverage, str) and coverage.lower() in ("all", "targeted") else "targeted"
    plan["coverage"] = plan["coverage"].lower()

    # Safety net: catch region keywords the LLM may have ignored
    plan = _expand_regions(goal, plan)
    return plan
