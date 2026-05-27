"""
Phase 0 — Source Discovery (Strategy A: Web search)

Runs each search query from the intent plan through DuckDuckGo and collects
candidate URLs. Adds a few `site:<platform>` dorks from platform_hints.

Two filter layers per query, cheapest first:
  1. Rule-based skip (`_is_skippable`): domain blocklist, path prefixes,
     file extensions, dated paths.
  2. LLM relevance filter (`_llm_filter_results`): one DeepSeek call per
     query batch — drops obvious-mismatch results before HTTP fetches.

Reuses Phase2Bot/page_fetcher.py and Bot/llm.py via additive imports.
"""

import json
import os
import re
import sys
from urllib.parse import urlparse

# Reuse Phase 2's TLS-impersonated DDG fetcher (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Phase2Bot.page_fetcher import _ddg_fetch_results, reset_search_state  # type: ignore  # noqa: E402

# Reuse Bot/llm.py for the relevance filter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from llm import ask  # type: ignore  # noqa: E402


# DDG result quality drops sharply past rank ~5; take top 6 instead of 10.
MAX_RESULTS_PER_QUERY = 6
MAX_PLATFORM_DORKS = 3
# Cap paths from a single domain to stop one site dominating the candidate set
# via its /about, /contact, /news clones.
MAX_PER_DOMAIN = 2

# Domains we never treat as candidate directories — social, search, encyclopedias,
# news majors, content farms, real estate, and bot-heavy listing aggregators that
# either don't expose data or block scraping.
SKIP_DOMAINS = {
    # Search engines / portals
    "duckduckgo.com", "google.com", "bing.com", "yahoo.com", "msn.com",
    # Social
    "youtube.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "instagram.com", "tiktok.com", "pinterest.com",
    "reddit.com", "quora.com",
    # Reference
    "wikipedia.org", "wikimedia.org",
    # Commerce
    "amazon.com", "ebay.com",
    # Big-name listing aggregators (mostly blocked or wrong shape for our scrapers)
    "yelp.com", "tripadvisor.com",
    "angi.com", "angieslist.com",
    "thumbtack.com", "homeadvisor.com", "houzz.com",
    "manta.com", "bbb.org", "yellowpages.com", "yp.com",
    "mapquest.com",
    # B2B contact-data aggregators / "people search" sites — these mirror
    # public company info into single-company profile pages that pattern-
    # match as directories (keywords + employee lists) but the actual data
    # is gated behind a signup wall. The primary source (company website,
    # underlying chamber directory) is always better.
    "leadiq.com", "leadiq.co",
    "zoominfo.com",
    "rocketreach.co",
    "apollo.io",
    "hunter.io",
    "datanyze.com",
    "lusha.com",
    "signalhire.com",
    "contactout.com",
    "getprospect.com",
    "snov.io",
    "seamless.ai",
    "wiza.co",
    "intellispect.co",
    "causeiq.com",
    "crunchbase.com",
    "pitchbook.com",
    # Job boards
    "indeed.com", "glassdoor.com", "monster.com", "ziprecruiter.com",
    # Real estate (rarely member directories)
    "zillow.com", "realtor.com", "redfin.com", "trulia.com",
    # News majors (articles ABOUT directories, not directories themselves)
    "nytimes.com", "washingtonpost.com", "forbes.com", "businessinsider.com",
    "bloomberg.com", "reuters.com", "cnn.com", "cnbc.com", "nbcnews.com",
    "abcnews.go.com", "cbsnews.com", "foxnews.com", "usatoday.com",
    # Content farms / blogging platforms
    "medium.com", "substack.com", "dev.to", "blogspot.com", "wordpress.com",
    # Archive
    "archive.org", "web.archive.org",
}

# Path prefixes that almost never appear on real directory pages.
SKIP_PATH_PREFIXES = (
    "/blog/", "/blogs/",
    "/news/",
    "/article/", "/articles/",
    "/post/", "/posts/",
    "/story/", "/stories/",
    "/forum/", "/forums/",
    "/discussion/", "/discussions/", "/thread/",
)

# Dated paths — strong signal of an article (/2024/03/post-name), weak elsewhere.
_DATED_PATH_RE = re.compile(r"/20[12][0-9]/")

# File extensions: not HTML, never a directory listing.
SKIP_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".rar", ".7z")


def _is_skippable(url: str) -> bool:
    """True if the URL's domain, path prefix, or extension should be rejected upfront."""
    try:
        parsed = urlparse(url)
    except Exception:
        return True
    domain = parsed.netloc.lower().replace("www.", "")
    if not domain:
        return True
    if any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS):
        return True

    path = parsed.path.lower()
    if any(path.startswith(p) for p in SKIP_PATH_PREFIXES):
        return True
    if _DATED_PATH_RE.search(path):
        return True
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True
    return False


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


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _llm_filter_results(
    query: str,
    results: list[dict],
    industry: str,
    location_hint: str,
) -> tuple[list[dict], int]:
    """One DeepSeek call: drop obvious-mismatch results before HTTP fetching.

    Returns (kept_results, dropped_count). On ANY failure path — LLM error,
    bad JSON, unexpected shape — returns the input unchanged. Fail-open is
    deliberate: the heuristic preflight downstream will still catch junk,
    so we'd rather over-include than lose a real directory to a transient
    LLM hiccup.
    """
    if not results:
        return results, 0

    enumerated = "\n\n".join(
        f"{i+1}. Title: {r.get('title', '') or '(no title)'}\n"
        f"   URL: {r.get('href', '')}\n"
        f"   Snippet: {r.get('snippet', '') or '(no snippet)'}"
        for i, r in enumerate(results)
    )

    target = industry or "the target businesses or organizations"
    location_phrase = f" in {location_hint}" if location_hint else ""

    prompt = f"""You are filtering DuckDuckGo search results for a scraper.

GOAL: Find DIRECTORY or LISTING PAGES of {target}{location_phrase}.

A directory/listing page contains MULTIPLE member or business entries on one page (cards, table rows, search results). Examples of what to KEEP: "Member Directory", "Find a Doctor", "Search Our Members", "Browse Providers", chamber-of-commerce member lists, association rosters, and homepages of organizations that have such a directory linked from them.

REJECT results that are obviously:
- News articles or press releases about the topic
- Blog posts, opinion pieces, or "Top 10" / review listicles
- Government regulations, laws, or PDF documents
- Individual single-business homepages with no listing of others
- B2B contact-data aggregators / people-search sites (LeadIQ, ZoomInfo, RocketReach, Wiza, Apollo, Lusha, Hunter, Crunchbase, etc.) — these mirror public info into gated profile pages, not real directories
- Social media profiles, forum threads, podcast episodes
- Conference/event pages, course/training pages
- Unrelated topics that share a keyword

The search query that produced these was: "{query}"

Results:
{enumerated}

Return ONLY a JSON object — no markdown fences, no explanation:
{{"keep": [<1-based result numbers you want to KEEP>]}}

If none of the results look like plausible directory candidates, return {{"keep": []}}.
"""

    try:
        raw = ask(prompt, max_tokens=200)
    except Exception as e:
        print(f"  LLM filter: call failed ({e}) — keeping all {len(results)} results")
        return results, 0

    text = _strip_fences(raw)
    try:
        decision = json.loads(text)
    except json.JSONDecodeError:
        print(f"  LLM filter: non-JSON response — keeping all {len(results)} results")
        return results, 0

    if not isinstance(decision, dict):
        return results, 0
    keep_indices = decision.get("keep")
    if not isinstance(keep_indices, list):
        return results, 0

    kept: list[dict] = []
    seen: set[int] = set()
    for idx in keep_indices:
        if not isinstance(idx, int):
            continue
        if idx < 1 or idx > len(results):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        kept.append(results[idx - 1])

    dropped = len(results) - len(kept)
    return kept, dropped


def _location_hint(plan: dict) -> str:
    """Render the plan's locations as a short string for the LLM prompt."""
    locations = plan.get("locations") or []
    states = [loc.get("state", "") for loc in locations if loc.get("state")]
    return ", ".join(states)


def discover_candidates(
    plan: dict,
    event_cb=None,
    use_llm_filter: bool = True,
) -> list[dict]:
    """Run all queries and return rank-aware, per-domain-capped candidates.

    Returns list of dicts: {"url", "title", "via_query", "rank"}, sorted by rank.
    Pass `use_llm_filter=False` to skip the relevance LLM call (e.g. for A/B).
    """
    # Phase 2's DDG client has a sticky kill-switch; reset it so a prior
    # 429/403 from an earlier session doesn't silently swallow our queries.
    reset_search_state()

    queries = _build_queries(plan)
    if not queries:
        return []

    industry = (plan.get("industry") or {}).get("canonical", "")
    location_hint = _location_hint(plan)

    # When the same (netloc, path) appears under multiple queries, keep the
    # better-ranked occurrence rather than first-seen.
    by_key: dict[tuple[str, str], dict] = {}
    domain_counts: dict[str, int] = {}

    for query in queries:
        if event_cb:
            event_cb({"type": "discovery_query", "query": query})

        raw_results = _ddg_fetch_results(query)[:MAX_RESULTS_PER_QUERY]

        # Tag with DDG rank before any filtering, so dedup-prefer-better-rank
        # still reflects DDG's original ordering rather than post-filter index.
        for rank, r in enumerate(raw_results):
            r["_ddg_rank"] = rank

        # Layer 1: rule-based skip (cheap)
        survivors = [
            r for r in raw_results
            if (r.get("href") or "").startswith("http") and not _is_skippable(r.get("href") or "")
        ]

        # Layer 2: LLM relevance filter (one call, fail-open)
        llm_dropped = 0
        if use_llm_filter and survivors:
            survivors, llm_dropped = _llm_filter_results(
                query, survivors, industry, location_hint
            )

        added_for_query = 0
        for r in survivors:
            url = (r.get("href") or "").strip()
            title = (r.get("title") or "").strip()
            ddg_rank = r.get("_ddg_rank", MAX_RESULTS_PER_QUERY)

            try:
                parsed = urlparse(url)
            except Exception:
                continue

            domain = parsed.netloc.lower().replace("www.", "")
            if not domain:
                continue
            key = (domain, parsed.path.rstrip("/").lower())

            existing = by_key.get(key)
            if existing is not None:
                if ddg_rank < existing["rank"]:
                    existing["rank"] = ddg_rank
                    existing["via_query"] = query
                continue

            if domain_counts.get(domain, 0) >= MAX_PER_DOMAIN:
                continue

            by_key[key] = {
                "url": url,
                "title": title,
                "via_query": query,
                "rank": ddg_rank,
            }
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            added_for_query += 1

        if event_cb:
            event_cb({
                "type": "discovery_query_done",
                "query": query,
                "added": added_for_query,
                "total": len(by_key),
                "llm_dropped": llm_dropped,
            })

    return sorted(by_key.values(), key=lambda c: c["rank"])
