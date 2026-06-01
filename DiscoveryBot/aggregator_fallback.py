"""
Phase 0 — Aggregator fallback.

When normal discovery qualifies NO scrapable directory — the query has no
dedicated niche directory (e.g. "Chinese restaurants in Austin", "barbershops
in Denver") — this builds direct category+location search URLs on a few general
business-listing sites that aggregate standalone businesses, and hands them back
as candidates for the normal preflight -> classify -> Phase 1 path.

Why direct URLs instead of more DDG queries: discovery usually comes up empty
*because* DDG is rate-limited (the sticky kill-switch in page_fetcher). Seeding
real search URLs sidesteps DDG entirely, so the fallback works exactly when the
primary path can't.

These are the cross-vertical aggregators the classifier already knows how to
drive (see classifier.AGGREGATOR_DOMAINS); Phase 1 paginates their result pages.
Yelp / TripAdvisor are deliberately excluded — JS-rendered + aggressive anti-bot,
they reliably 403 the curl_cffi preflight. The templates below are server-rendered
HTML. URL schemes are best-effort: any that 404/403/return junk are dropped by
preflight, so a stale template costs nothing but the reliable ones still land.
"""

from urllib.parse import quote_plus


def _geo(city: str, state: str) -> str:
    """'City, ST' when we have a city, else just the state code."""
    city = (city or "").strip()
    state = (state or "").strip()
    return f"{city}, {state}" if city and state else (city or state)


# --- URL templates -------------------------------------------------------
# Each entry: (label, builder(query, city, state) -> url | "").
# YellowPages is the anchor — its scheme has been stable for years and its
# result pages are plain server-rendered listing cards. The rest are
# best-effort; preflight filters out any that don't pan out.

def _yellowpages(q: str, city: str, state: str) -> str:
    return (
        "https://www.yellowpages.com/search?"
        f"search_terms={quote_plus(q)}&geo_location_terms={quote_plus(_geo(city, state))}"
    )


def _manta(q: str, city: str, state: str) -> str:
    return f"https://www.manta.com/search?search={quote_plus(q)}&location={quote_plus(_geo(city, state))}"


def _cylex(q: str, city: str, state: str) -> str:
    return f"https://www.cylex-usa.com/s?q={quote_plus(q)}&l={quote_plus(_geo(city, state))}"


def _chamberofcommerce(q: str, city: str, state: str) -> str:
    return f"https://www.chamberofcommerce.com/search?what={quote_plus(q)}&where={quote_plus(_geo(city, state))}"


TEMPLATES = [
    ("YellowPages", _yellowpages),
    ("Manta", _manta),
    ("Cylex", _cylex),
    ("ChamberOfCommerce", _chamberofcommerce),
]


def _pick_location(plan: dict) -> tuple[str, str]:
    """First location that carries a US-shaped (2-letter) state. Returns
    (city, state); city may be empty (statewide search is still useful).

    The intent schema stores the city under `cities_hint` (a list), not a
    `city` key — only NPI's api_params uses `city`. We take the first hint as
    the user's intended city; a statewide YellowPages search still works when
    it's absent, so this is best-effort, not load-bearing.
    """
    for loc in plan.get("locations") or []:
        state = (loc.get("state") or "").strip()
        if len(state) == 2 and state.isalpha():
            city = (loc.get("city") or "").strip()
            if not city:
                hints = loc.get("cities_hint") or []
                city = (hints[0] if hints else "").strip()
            return city, state.upper()
    return "", ""


def build_fallback_candidates(plan: dict) -> list[dict]:
    """Direct aggregator search URLs for this plan, or [] if we can't build a
    sensible one (no industry term, or no US location to scope the search).

    Returned dicts match the shape discover_candidates emits, so they drop
    straight into preflight_all / classify_all.
    """
    industry = ((plan.get("industry") or {}).get("canonical") or "").strip()
    if not industry:
        return []

    city, state = _pick_location(plan)
    # No geography → an aggregator search would return the whole country, which
    # is never what the user meant. Bail and let discovery's empty result stand.
    if not state:
        return []

    candidates: list[dict] = []
    for label, builder in TEMPLATES:
        try:
            url = builder(industry, city, state)
        except Exception:
            continue
        if url:
            candidates.append({
                "url": url,
                "title": f"{industry} — {label}",
                "via_query": "aggregator_fallback",
                "rank": 0,
            })
    return candidates
