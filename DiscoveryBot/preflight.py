"""
Phase 0 — Pre-Flight Qualification

One lightweight curl_cffi request per candidate. Rejects pages that have no
actual member-card content (or path to it) before they reach the classifier.

After all heuristics pass, an optional AI sanity check looks at the actual
page text to catch false positives the rules can't (e.g. B2B data brokers
that ship past the domain blocklist). Fail-open everywhere.

Runs in parallel (ThreadPoolExecutor) using Phase 2's TLS-impersonated fetcher.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse as _u

# Reuse Phase 2's TLS-fingerprinted HTTP fetcher (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Phase2Bot.page_fetcher import fetch_page  # type: ignore  # noqa: E402

# Reuse Bot/llm.py for the AI sanity check (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from llm import ask  # type: ignore  # noqa: E402


# Toggle the final AI sanity check without changing function signatures.
# Set to False for A/B testing or if DeepSeek is having issues — heuristic
# checks above still run regardless.
LLM_SANITY_CHECK_ENABLED = True


# Below this, the page is a parked domain, SPA shell, login splash, or blank.
# Counted on visible text (after <script>/<style> removal), not raw HTML — a
# 50KB SPA with a 2-char body would otherwise sail through.
MIN_VISIBLE_TEXT_CHARS = 1500

# Number of detail-link-shaped anchors that counts as evidence of a listing
# whose contact info lives one click away (instead of inline on the listing).
MIN_DETAIL_LINKS = 3

# Strong phrases — each alone is enough to satisfy the keyword gate.
STRONG_DIRECTORY_PHRASES = (
    "member directory", "members directory",
    "find a member", "find a doctor", "find an attorney",
    "find a provider", "find a dentist", "find a lawyer",
    "member listing", "member list",
    "our members", "search the directory",
    "browse members", "directory search",
    "provider directory", "provider search",
    "physician directory", "physician finder",
    "results per page",
)

# Weak signals — need at least two distinct hits to pass the keyword gate.
# Both singular AND plural forms must be listed explicitly because the
# tokenize-based matcher uses exact equality (so "chamber" ≠ "chambers").
# Missing a plural here = legitimate pages get rejected; missing a singular
# = same. Keep both.
WEAK_DIRECTORY_SIGNALS = (
    "member", "members", "directory", "directories",
    "listing", "listings", "results",
    "company", "companies",
    "provider", "providers", "doctor", "doctors", "dentist", "dentists",
    "restaurant", "restaurants", "attorney", "attorneys", "lawyer", "lawyers",
    "contractor", "contractors", "vendor", "vendors",
    "association", "associations",
    "chamber", "chambers", "registry", "registries", "roster", "rosters",
)

# Login-wall phrase signals (used alongside <input type=password> + login form action).
LOGIN_WALL_PHRASES = (
    "please log in", "please sign in",
    "log in to view", "sign in to view",
    "log in to access", "sign in to access",
    "log in to see", "sign in to see",
    "must be logged in", "must sign in",
    "members only", "subscribers only", "subscriber only",
    "subscribe to view", "subscribe to read",
)

# Parked / for-sale domain templates have signature strings.
PARKED_DOMAIN_SIGNATURES = (
    "this domain is for sale",
    "this domain may be for sale",
    "buy this domain",
    "domain is available for purchase",
    "domain for sale",
    "inquire about this domain",
    "interested in this domain",
    "godaddy coming soon",
    "domain parking",
    "domain has expired",
    "premium domain for sale",
)

# B2B contact-data aggregator UI patterns. These pages look like directories
# (company name, employee list, phone/email icons) but the data is gated and
# the page is a mirror of public info, not a real source. Safety net for
# aggregator domains that aren't on the SKIP_DOMAINS list in sources.py.
DATA_BROKER_SIGNATURES = (
    "sign up for free to view",
    "sign up for free to see",
    "unlock accurate emails",
    "unlock contact data",
    "find more accurate contact",
    "verified email format",
    "ideal prospects with",
    "looking for contact data",
    "trying to find reliable",
    "company overview page for more information",
    "'s company overview page",
)

# "Find <Company Name> employees' phone numbers or email addresses" — exact
# LeadIQ/Wiza/RocketReach UX pattern, distinctive enough to be a single
# signal of catastrophic mismatch.
_BROKER_EMPLOYEE_RE = re.compile(
    r"find\s+[a-z0-9 .,&'-]{3,80}\s+employees'?\s+(?:phone|email)",
    re.I,
)

# Anchor text patterns suggesting a per-member detail page.
_DETAIL_LINK_TEXT_RE = re.compile(
    r"\b(view\s+(?:profile|member|listing|details?)|"
    r"member\s+profile|"
    r"read\s+more|"
    r"more\s+info|"
    r"learn\s+more|"
    r"see\s+(?:profile|details?))\b",
    re.I,
)

# href path fragments suggesting per-member detail pages.
_DETAIL_LINK_HREF_FRAGMENTS = (
    "/member/", "/members/",
    "/profile/", "/profiles/",
    "/listing/", "/listings/",
    "/business/", "/businesses/",
    "/company/", "/companies/",
    "/practice/", "/practices/",
    "/doctor/", "/doctors/",
    "/dentist/", "/dentists/",
    "/attorney/", "/attorneys/",
    "/provider/", "/providers/",
    "/firm/", "/firms/",
)

# Landing-link patterns (page itself isn't a directory, but links to one).
_LANDING_LINK_HREF_FRAGMENTS = (
    "/member-directory", "/memberdirectory",
    "/members", "/member-search", "/membersearch",
    "/directory", "/find-a-", "/findadoctor", "/find-doctor",
    "/provider-search", "/providersearch",
    "/member-list", "/memberlist",
    "/browse-members", "/browsemembers",
)

# Phone number — minimal US/intl shape, same anchoring as Bot/html_parser.py.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}(?!\d)"
)

# --- Tokenizer for weak-signal keyword check ---
# The legacy `any(s in text for s in WEAK_DIRECTORY_SIGNALS)` substring scan
# matched "member" inside "remembered", "doctor" inside "indoctrinate",
# "chamber" inside "chambermaid", etc. We tokenize into word-shaped pieces
# and use set intersection so only whole-word hits count.
_NON_LETTER_RE = re.compile(r'[^A-Za-z]+')
_CAMEL_BOUNDARY_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _extract_word_tokens(text: str) -> set[str]:
    """Split text into lowercased whole-word tokens.

    Splits on non-letter chars first (paths, punctuation, separators), then
    on camelCase boundaries inside each remaining run. Same shape as the
    helper in Bot/browser.py — kept local here to avoid a cross-package
    import (DiscoveryBot already has enough sys.path hacks).
    """
    tokens: set[str] = set()
    for part in _NON_LETTER_RE.split(text):
        if not part:
            continue
        for sub in _CAMEL_BOUNDARY_RE.split(part):
            if sub:
                tokens.add(sub.lower())
    return tokens


# Pre-compute the lowercase weak-signal set for O(1) lookups.
_WEAK_SIGNAL_TOKENS = {s.lower() for s in WEAK_DIRECTORY_SIGNALS}


def _visible_text(soup) -> str:
    """Lowercased visible text after stripping inert tags. Used for length,
    phrase signals, parked-domain detection, and login-wall phrase checks."""
    for tag in soup(("script", "style", "noscript", "template")):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True).lower()


def _link_path(href: str) -> str:
    """Lowercased path of an href — robust to query strings that happen to
    contain directory-shaped fragments (e.g. ?utm=member-directory)."""
    if not href:
        return ""
    try:
        return _u(href).path.lower()
    except Exception:
        return href.lower()


def _has_login_wall(soup, text: str) -> bool:
    if soup.find("input", attrs={"type": "password"}):
        return True
    for form in soup.find_all("form"):
        action = (form.get("action") or "").lower()
        if any(needle in action for needle in ("login", "signin", "sign-in", "auth", "session")):
            return True
    return any(phrase in text for phrase in LOGIN_WALL_PHRASES)


def _is_parked(text: str) -> bool:
    return any(sig in text for sig in PARKED_DOMAIN_SIGNATURES)


def _is_data_broker_profile(text: str) -> bool:
    """B2B aggregator profile pages. Title says 'Directory' but the data is
    gated and it's not the real source. Safety net for aggregator domains
    that aren't on sources.py's SKIP_DOMAINS list."""
    if any(sig in text for sig in DATA_BROKER_SIGNATURES):
        return True
    if _BROKER_EMPLOYEE_RE.search(text):
        return True
    return False


def _directory_keyword_pass(text: str) -> bool:
    """1 strong phrase OR ≥2 distinct weak signals (as whole words).

    Strong phrases are multi-word ("member directory", "find a doctor") so
    substring match is fine — they're unambiguous. Weak signals are single
    words and go through the tokenizer so "member" doesn't match "remembered",
    "doctor" doesn't match "indoctrinated", etc.
    """
    if any(p in text for p in STRONG_DIRECTORY_PHRASES):
        return True
    tokens = _extract_word_tokens(text)
    return len(tokens & _WEAK_SIGNAL_TOKENS) >= 2


def _count_detail_links(soup) -> int:
    """Anchors that look like per-member detail pages."""
    hits = 0
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "")
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        path = _link_path(href)
        if any(frag in path for frag in _DETAIL_LINK_HREF_FRAGMENTS):
            hits += 1
            continue
        text = a.get_text(strip=True)
        if _DETAIL_LINK_TEXT_RE.search(text):
            hits += 1
    return hits


def _has_landing_link(soup) -> bool:
    """Page itself isn't a listing, but links to a likely directory subpage."""
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        path = _link_path(href)
        if any(frag in path for frag in _LANDING_LINK_HREF_FRAGMENTS):
            return True
    return False


def _has_member_content_signals(soup, text: str) -> bool:
    """Page must contain SOMETHING scrapable — either inline contact data,
    detail-link anchors that lead to it, or a landing link to the real
    listing subpage. Without one of these, the page is just a keyword
    match and Phase 1/2 have nothing to extract."""
    if _PHONE_RE.search(text):
        return True
    if soup.find("a", href=re.compile(r"^mailto:", re.I)):
        return True
    if _count_detail_links(soup) >= MIN_DETAIL_LINKS:
        return True
    if _has_landing_link(soup):
        return True
    return False


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _sample_anchor_texts(soup, limit: int = 15) -> list[str]:
    """Pull short anchor texts to give the LLM a structural sense of the page."""
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        t = a.get_text(strip=True)
        if t and 2 < len(t) < 80:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _llm_sanity_check(url: str, title: str, soup, text: str) -> tuple[bool, str | None]:
    """Final preflight gate. Asks DeepSeek to look at the actual page content
    (not just title + DDG snippet) and decide whether it's a scrapable directory.

    Returns (passed, reason_category). Fail-open: any failure → (True, None).
    """
    samples = _sample_anchor_texts(soup, limit=15)
    samples_str = "\n".join(f"- {s}" for s in samples) or "(no anchor text available)"

    prompt = f"""You are inspecting a webpage to decide if it's a scrapable DIRECTORY or LISTING that contains multiple member, business, or professional entries.

URL: {url}
Title: {title or '(unknown)'}

First 1500 chars of visible page text:
{text[:1500]}

Sample anchor texts on the page:
{samples_str}

ACCEPT if this is:
- A directory listing page with multiple entries (cards, rows, profiles)
- A directory landing or search page that leads to the actual listing
- An organization homepage (chamber, association) that hosts a member directory

REJECT if this is:
- A B2B contact-data aggregator (LeadIQ, ZoomInfo, RocketReach, Wiza, Apollo, Lusha, Hunter, etc.) — these have gated profile pages that pretend to be directories
- A news article, blog post, listicle, or "Best of" / review piece
- A single-business homepage with no listing of others
- A government regulation, law, or PDF document
- An event/conference page, course/training page, or social-media profile
- A page that is mostly empty or generic with no real entries

Return ONLY a JSON object — no markdown fences, no explanation:
{{"verdict": "ACCEPT" or "REJECT", "reason": "<short snake_case category, e.g. 'directory', 'data_broker', 'article', 'single_business', 'event', 'empty'>"}}
"""

    try:
        raw = ask(prompt, max_tokens=80)
    except Exception as e:
        print(f"  AI sanity: call failed for {url[:60]} ({e}) — passing through")
        return True, None

    cleaned = _strip_fences(raw)
    try:
        decision = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"  AI sanity: non-JSON response for {url[:60]} — passing through")
        return True, None

    if not isinstance(decision, dict):
        return True, None
    verdict = str(decision.get("verdict", "")).upper()
    reason = str(decision.get("reason", "ai_rejected")).strip() or "ai_rejected"

    if verdict == "ACCEPT":
        return True, None
    if verdict == "REJECT":
        # Sanitize reason for telemetry — keep it short, snake_case-ish
        reason = re.sub(r"[^a-z0-9_]+", "_", reason.lower())[:40] or "ai_rejected"
        return False, reason

    # Unknown verdict — fail open
    return True, None


def _qualify_soup(soup, url: str = "", title: str = "") -> tuple[bool, str | None]:
    """Apply reject rules. Returns (passed, reason_if_rejected). Cheapest checks first."""
    text = _visible_text(soup)

    if len(text) < MIN_VISIBLE_TEXT_CHARS:
        return False, "thin_content"
    if _is_parked(text):
        return False, "parked_domain"
    if _has_login_wall(soup, text):
        return False, "login_wall"
    if _is_data_broker_profile(text):
        return False, "data_broker_profile"
    if not _directory_keyword_pass(text):
        return False, "no_directory_signals"
    if not _has_member_content_signals(soup, text):
        return False, "no_member_content"

    # Final gate: AI looks at the actual page content (not just heuristics).
    # Catches the long tail of aggregators, disguised articles, and other
    # pages that satisfy every rule but aren't real directories.
    if LLM_SANITY_CHECK_ENABLED:
        passed, ai_reason = _llm_sanity_check(url, title, soup, text)
        if not passed:
            return False, f"ai_sanity:{ai_reason}"

    return True, None


def preflight_one(candidate: dict) -> dict:
    """Qualify a single candidate URL.

    Returns the candidate dict augmented with status / reason / soup / final_url.
    status is "passed" or "rejected".
    """
    url = candidate["url"]
    title = candidate.get("title", "")

    try:
        soup, final_url = fetch_page(url)
    except Exception:
        return {**candidate, "status": "rejected", "reason": "fetch_failed"}

    if soup is None:
        return {**candidate, "status": "rejected", "reason": "fetch_failed"}

    passed, reason = _qualify_soup(soup, url=url, title=title)
    if not passed:
        return {**candidate, "status": "rejected", "reason": reason}

    return {
        **candidate,
        "status": "passed",
        "reason": None,
        "soup": soup,
        "final_url": final_url or url,
    }


def preflight_all(candidates: list[dict], event_cb=None,
                   max_workers: int = 8) -> tuple[list[dict], list[dict]]:
    """Run preflight on all candidates in parallel.

    Returns (passed, rejected) lists. Passed entries carry their soup so
    the classifier can reuse it without re-fetching.
    """
    if not candidates:
        return [], []

    passed: list[dict] = []
    rejected: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(preflight_one, c): c for c in candidates}
        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as e:
                src = futures[fut]
                result = {**src, "status": "rejected", "reason": f"worker_error: {e}"}

            if event_cb:
                event_cb({
                    "type": "preflight_result",
                    "url": result["url"],
                    "status": result["status"],
                    "reason": result.get("reason"),
                })

            if result["status"] == "passed":
                passed.append(result)
            else:
                rejected.append(result)

    return passed, rejected
