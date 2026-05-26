"""
Phase 0 — Source Discovery (Strategy A: Web search)

Runs each search query from the intent plan through DuckDuckGo and collects
candidate URLs. Adds a few `site:<platform>` dorks from platform_hints.

Reuses Phase2Bot/page_fetcher.py — does NOT modify it. Strategies B/C/D
from the design doc are intentionally deferred for v1.
"""

import os
import sys
from urllib.parse import urlparse

# Reuse Phase 2's TLS-impersonated DDG fetcher (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Phase2Bot.page_fetcher import _ddg_fetch_results, reset_search_state  # type: ignore  # noqa: E402


MAX_RESULTS_PER_QUERY = 10
MAX_PLATFORM_DORKS = 3

# Domains we never treat as candidate directories — social, search, encyclopedias, etc.
SKIP_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "yahoo.com",
    "youtube.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "instagram.com", "tiktok.com", "pinterest.com",
    "wikipedia.org", "wikimedia.org",
    "reddit.com", "quora.com",
    "amazon.com", "ebay.com", "yelp.com",
    "indeed.com", "glassdoor.com",
    "yelp.com", "tripadvisor.com",
}


def _is_skippable(url: str) -> bool:
    """True if the URL's domain is on the skip list (social, search engines, etc.)."""
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return True
    if not domain:
        return True
    return any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)


def _build_queries(plan: dict) -> list[str]:
    """Combine the LLM's search_queries with platform-dork variants."""
    queries = list(plan.get("search_queries", []))
    industry = (plan.get("industry") or {}).get("canonical", "")
    platforms = plan.get("platform_hints") or []

    for platform in platforms[:MAX_PLATFORM_DORKS]:
        if not platform or "." not in platform:
            # Bare platform name like "growthzone" — turn it into a known TLD
            platform_query = f'site:{platform}app.com {industry}' if industry else ""
        else:
            platform_query = f"site:{platform} {industry}" if industry else f"site:{platform}"
        if platform_query.strip():
            queries.append(platform_query.strip())

    return [q for q in queries if q and q.strip()]


def discover_candidates(plan: dict, event_cb=None) -> list[dict]:
    """Run all queries from the plan and return deduplicated candidate URLs.

    Returns list of dicts: {"url", "title", "via_query"}.
    """
    # Phase 2's DDG client has a sticky kill-switch; reset it so a prior
    # 429/403 from an earlier session doesn't silently swallow our queries.
    reset_search_state()

    queries = _build_queries(plan)
    if not queries:
        return []

    seen_keys: set[tuple[str, str]] = set()
    candidates: list[dict] = []

    for query in queries:
        if event_cb:
            event_cb({"type": "discovery_query", "query": query})

        results = _ddg_fetch_results(query)
        added_for_query = 0
        for r in results[:MAX_RESULTS_PER_QUERY]:
            url = (r.get("href") or "").strip()
            title = (r.get("title") or "").strip()
            if not url.startswith("http"):
                continue
            if _is_skippable(url):
                continue

            try:
                parsed = urlparse(url)
            except Exception:
                continue

            # Dedup on netloc + path; query strings can differ for the same listing page
            key = (parsed.netloc.lower(), parsed.path.rstrip("/").lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)

            candidates.append({"url": url, "title": title, "via_query": query})
            added_for_query += 1

        if event_cb:
            event_cb({
                "type": "discovery_query_done",
                "query": query,
                "added": added_for_query,
                "total": len(candidates),
            })

    return candidates
