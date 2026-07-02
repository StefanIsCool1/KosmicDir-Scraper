"""
HTTP page fetcher with rate limiting and subpage discovery.
Uses curl_cffi with browser TLS fingerprint impersonation.
"""

import base64
import random
import re
import time
import threading
from curl_cffi.requests import Session
from curl_cffi import CurlError
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote_plus, unquote

REQUEST_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.5

# Rotate browser fingerprints — each has a unique TLS/HTTP2 signature
# curl_cffi v0.14: "chrome"/"safari"/"firefox" auto-select latest available version
_IMPERSONATE_TARGETS = [
    "chrome",       # auto-latest (currently chrome136)
    "chrome136",    # explicit latest Chrome
    "chrome124",    # slightly older — diversity helps avoid pattern detection
    "safari",       # auto-latest (currently safari184)
    "safari184",    # explicit latest Safari
    "firefox",      # Firefox support added in v0.11+
]

# Headers that match a real browser navigation (do NOT set User-Agent — curl_cffi does that)
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_last_request_time: dict[str, float] = {}

# Thread-local sessions — each worker thread gets its own persistent session
_thread_local = threading.local()

# Subpage patterns: {category: ([href_keywords], [text_keywords])}
SUBPAGE_PATTERNS = {
    "contact": (
        ["contact", "contact-us", "contactus", "get-in-touch"],
        ["contact us", "contact", "get in touch", "reach us"],
    ),
    "about": (
        ["about", "about-us", "aboutus", "who-we-are", "our-story", "our-company"],
        ["about us", "about", "who we are", "our story", "our company", "learn more about"],
    ),
    "team": (
        ["team", "our-team", "staff", "leadership", "people", "meet-the-team"],
        ["our team", "meet the team", "staff", "leadership", "our people"],
    ),
    "services": (
        ["services", "what-we-do", "our-services", "capabilities", "solutions"],
        ["services", "what we do", "our services", "capabilities"],
    ),
}


def _get_session(browser: str) -> Session:
    """Get or create a thread-local session for the given browser fingerprint.
    Reuses sessions within the same thread for connection pooling + cookie persistence."""
    key = f"session_{browser}"
    session = getattr(_thread_local, key, None)
    if session is None:
        session = Session(impersonate=browser, timeout=REQUEST_TIMEOUT)  # type: ignore[arg-type]
        setattr(_thread_local, key, session)
    return session


def _make_request(url: str, browser: str, verify: bool = True,
                   extra_fp: dict[str, bool] | None = None):
    """Single request attempt with a specific browser fingerprint.
    Optional extra_fp tweaks the TLS fingerprint (e.g. GREASE, extension permutation)."""
    session = _get_session(browser)
    resp = session.get(
        url,
        headers=_BROWSER_HEADERS,
        allow_redirects=True,
        timeout=REQUEST_TIMEOUT,
        verify=verify,
        extra_fp=extra_fp,  # type: ignore[arg-type]
    )
    return resp, str(resp.url)

# TLS tweaks that make the fingerprint look more like a real browser.
# GREASE = Generate Random Extensions And Sustain Extensibility (Chrome does this).
# Permuting extensions shuffles their order — defeats static JA3 blocklists.
_EXTRA_FP_TWEAKS = {
    "tls_permute_extensions": True,
    "tls_grease": True,
}


def fetch_page(url: str) -> tuple[BeautifulSoup | None, str | None]:
    """Fetch a URL with browser TLS fingerprint impersonation.

    Retry strategy on 403:
      1. Different browser fingerprint
      2. Same browser + TLS tweaks (GREASE + extension permutation)
    Returns (soup, final_url) or (None, None) on failure."""
    domain = urlparse(url).netloc
    now = time.time()
    last = _last_request_time.get(domain, 0)
    wait = RATE_LIMIT_DELAY - (now - last)
    if wait > 0:
        time.sleep(wait)

    # Pick two random browsers for fingerprint diversity
    browsers = random.sample(_IMPERSONATE_TARGETS, min(2, len(_IMPERSONATE_TARGETS)))

    for attempt, browser in enumerate(browsers):
        try:
            resp, final_url = _make_request(url, browser)
            _last_request_time[domain] = time.time()

            if resp.status_code == 403 and attempt == 0:
                # Retry with different fingerprint
                time.sleep(1)
                continue

            if resp.status_code == 403 and attempt == 1:
                # Both fingerprints got 403 — try TLS tweaks as last resort
                time.sleep(1)
                try:
                    resp, final_url = _make_request(url, browsers[0], extra_fp=_EXTRA_FP_TWEAKS)
                    _last_request_time[domain] = time.time()
                    if resp.status_code >= 400:
                        print(f"    [403] {url[:60]}")
                        return None, None
                    content_type = resp.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return None, None
                    soup = BeautifulSoup(resp.text, "html.parser")
                    return soup, final_url
                except Exception:
                    print(f"    [403] {url[:60]}")
                    return None, None

            if resp.status_code in (403, 429, 503):
                print(f"    [{resp.status_code}] {url[:60]}")
                return None, None
            if resp.status_code >= 400:
                return None, None

            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None, None

            soup = BeautifulSoup(resp.text, "html.parser")
            return soup, final_url

        except CurlError as e:
            err = str(e)[:80]
            if "SSL" in err or "certificate" in err.lower():
                try:
                    resp, final_url = _make_request(url, browser, verify=False)
                    _last_request_time[domain] = time.time()
                    if resp.status_code >= 400:
                        return None, None
                    soup = BeautifulSoup(resp.text, "html.parser")
                    return soup, final_url
                except Exception:
                    pass
            if "timeout" in err.lower() or "timed out" in err.lower():
                print(f"    Timeout ({REQUEST_TIMEOUT}s): {url[:60]}")
            elif "resolve" in err.lower() or "name" in err.lower():
                print(f"    DNS error: {url[:60]}")
            else:
                print(f"    Connection error: {err}")
            return None, None

        except Exception as e:
            print(f"    Fetch error: {type(e).__name__}: {str(e)[:80]}")
            return None, None

    return None, None


def discover_subpages(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    """Find links to contact, about, team, services pages.
    Only same-domain links, first match per category."""
    base_domain = urlparse(base_url).netloc.lower()
    found: dict[str, str] = {}

    all_links = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        text = a.get_text(strip=True).lower()
        resolved = _resolve_url(href, base_url)
        if not resolved:
            continue
        link_domain = urlparse(resolved).netloc.lower()
        if link_domain != base_domain:
            continue
        all_links.append({"href": resolved, "text": text, "path": urlparse(resolved).path.lower()})

    for category, (href_kws, text_kws) in SUBPAGE_PATTERNS.items():
        if category in found:
            continue
        for link in all_links:
            path = link["path"].rstrip("/")
            path_parts = path.split("/")
            last_segment = path_parts[-1] if path_parts else ""

            href_match = any(kw == last_segment or kw in path for kw in href_kws)
            text_match = any(kw in link["text"] for kw in text_kws)

            if href_match or text_match:
                found[category] = link["href"]
                break

    return found


def _resolve_url(href: str, base_url: str) -> str | None:
    """Resolve a relative URL, filter out non-navigable links."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    if href.startswith(("data:", "blob:")):
        return None
    try:
        resolved = urljoin(base_url, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            return None
        return resolved
    except Exception:
        return None


# --- DUCKDUCKGO SEARCH FOR MISSING WEBSITES ---
# Uses curl_cffi with browser TLS impersonation to scrape DDG HTML results.
# The duckduckgo-search library gets blocked because it lacks TLS fingerprinting.

# Domains that are ABOUT companies but are NOT a company's own website
_SKIP_DOMAINS = {
    "google.com", "google.co", "googleapis.com",
    "facebook.com", "fb.com", "linkedin.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "tiktok.com", "pinterest.com",
    "yelp.com", "yellowpages.com", "bbb.org", "mapquest.com",
    "manta.com", "angi.com", "angieslist.com", "homeadvisor.com",
    "thumbtack.com", "houzz.com", "buildzoom.com",
    "dnb.com", "dandb.com", "zoominfo.com", "crunchbase.com",
    "bloomberg.com", "indeed.com", "glassdoor.com",
    "wikipedia.org", "wikimedia.org",
    "amazon.com", "ebay.com", "etsy.com",
    "nextdoor.com", "patch.com",
    "chamberofcommerce.com", "chambermaster.com",
    "growthzone.com", "micronet.com",
    "apple.com", "microsoft.com", "reddit.com",
    "tripadvisor.com", "healthgrades.com", "vitals.com",
    "npidb.org", "opencorporates.com", "sec.gov",
    "bizapedia.com", "buzzfile.com", "spoke.com",
}

# Business suffixes to strip when building company word set
_BUSINESS_SUFFIXES = {
    "the", "and", "of", "for",
    "inc", "llc", "ltd", "corp", "co", "company", "corporation",
    "incorporated", "limited", "enterprises", "holdings", "associates",
    "international", "partners", "consulting", "group", "pllc", "lp",
    "pc", "pa", "dba",
}

# Generic industry words that appear in too many unrelated domains.
# These should NOT be used for domain matching (too many false positives)
# but ARE kept in the search query for context.
_GENERIC_INDUSTRY_WORDS = {
    "construction", "building", "builders", "electric", "electrical",
    "plumbing", "roofing", "painting", "heating", "cooling", "hvac",
    "landscaping", "cleaning", "concrete", "drywall", "flooring",
    "remodeling", "renovation", "restoration", "demolition", "excavating",
    "contracting", "contractor", "services", "solutions", "supply",
    "industries", "industrial", "mechanical", "environmental",
    "design", "designs", "homes", "home", "house", "properties",
    "real", "estate", "realty", "mortgage", "insurance", "financial",
    "management", "development", "systems", "technology", "technologies",
    "engineering", "fabrication", "fabricators", "manufacturing",
    "cabinets", "cabinetry", "windows", "doors", "fencing",
    "paving", "welding", "steel", "iron", "wood", "lumber",
    "pest", "defense", "quality", "custom", "premier", "advanced",
    "national", "american", "western", "eastern", "northern", "southern",
    "pro", "plus", "first", "best", "elite", "superior", "precision",
}

# Free-email / consumer-ISP domains — personal accounts, not company sites.
# Used to skip the "derive website from email domain" shortcut for records
# whose only contact is a personal address.
_FREE_EMAIL_PROVIDERS = frozenset({
    # Major free providers
    "gmail.com", "googlemail.com",
    "yahoo.com", "ymail.com", "rocketmail.com",
    "hotmail.com", "outlook.com", "live.com", "msn.com",
    "aol.com", "aim.com",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me",
    "gmx.com", "gmx.us", "mail.com",
    "zoho.com", "yandex.com", "fastmail.com", "hey.com", "tutanota.com",
    # US consumer ISPs (often the only email a small business publishes)
    "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "cox.net",
    "bellsouth.net", "charter.net", "earthlink.net", "juno.com",
    "netzero.net", "frontier.com", "windstream.net", "centurylink.net",
    "optimum.net", "rr.com", "roadrunner.com", "twc.com",
    # Placeholders
    "example.com", "example.org", "test.com",
})


def website_from_emails(contacts: list[dict]) -> str | None:
    """Derive a business website from contact email domains.

    Skips free providers and consumer ISPs. Returns the first usable domain
    as https://<domain>, or None if no contact qualifies.

    Lets Phase 2 bypass DDG search when the Phase 1 record already exposes
    an email like john@acmecorp.com — that domain is almost always the
    company website. No network call, no rate limit, no false-positive risk
    from search-result matching.
    """
    if not contacts:
        return None
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        domain = email.rsplit("@", 1)[-1].strip()
        if not domain or "." not in domain or " " in domain:
            continue
        if domain in _FREE_EMAIL_PROVIDERS:
            continue
        return f"https://{domain}"
    return None


def _build_phone_query(phone: str | None) -> str | None:
    """Build a quoted DDG query from a 10-digit US phone number.

    A formatted phone like "(512) 555-1234" is often a near-unique
    identifier — businesses display it in their site header/footer, and
    DDG indexes those pages. Returns None for malformed or non-US shapes.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    formatted = f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return f'"{formatted}"'


# Search rate limiting — reset per run, not global.
# When DDG blocks (429/403), this flips and all subsequent queries are routed
# to the Bing HTML fallback instead of returning [] — a mid-run DDG block
# used to silently truncate discovery and Phase 2 website-finding.
_search_stopped = False


def _bing_fetch_results(query: str) -> list[dict[str, str]]:
    """Bing HTML search fallback — same result shape as _ddg_fetch_results
    ({'href', 'title', 'snippet'}). Used once DDG rate-limits for the run.
    Returns [] on any failure, which matches the old dead-engine behavior."""
    search_url = f"https://www.bing.com/search?q={quote_plus(query)}&count=25"
    time.sleep(random.uniform(0.8, 1.6))
    browser = random.choice(_IMPERSONATE_TARGETS)
    try:
        session = _get_session(browser)
        resp = session.get(search_url,
                           headers={**_BROWSER_HEADERS,
                                    "Referer": "https://www.bing.com/"},
                           allow_redirects=True, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for block in soup.select("li.b_algo"):
            a = block.select_one("h2 a")
            if not a:
                continue
            href = str(a.get("href", ""))
            # Bing wraps organic links: /ck/a?...&u=a1<base64url-of-target>
            if href.startswith("https://www.bing.com/ck/"):
                m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", href)
                if not m:
                    continue
                try:
                    pad = "=" * (-len(m.group(1)) % 4)
                    href = base64.urlsafe_b64decode(
                        m.group(1) + pad).decode("utf-8", "ignore")
                except Exception:
                    continue
            if not href.startswith("http"):
                continue
            snippet_el = block.select_one(".b_caption p") or block.select_one("p")
            results.append({
                "href": href,
                "title": a.get_text(strip=True),
                "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
            })
        return results

    except Exception:
        return []


def _build_company_words(company_name: str) -> set[str]:
    """Build a set of significant words from a company name for domain matching.
    Uses word-boundary splitting (not substring replace) to avoid mangling words."""
    name = company_name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    words = name.split()
    words = [w for w in words if w not in _BUSINESS_SUFFIXES]
    words = [w for w in words if len(w) >= 3 or (w.isdigit() and len(w) >= 2)]
    return set(words)


def _extract_search_location(street_address: str | None) -> str:
    """Extract city/state from address for search context.
    Handles comma-separated, multi-line, and minimal address formats."""
    if not street_address:
        return ""

    parts = [p.strip() for p in street_address.split(",")]
    location_parts = []

    for part in parts:
        stripped = part.strip()
        # Skip street address lines (start with number)
        if re.match(r'^\d', stripped):
            continue
        # Skip PO Box lines (handles "PO Box", "P.O. Box", "P.O BOX", etc.)
        if re.match(r'^p\.?o\.?\s*box', stripped, re.IGNORECASE):
            continue
        # Skip if it's just a zip code
        if re.match(r'^\d{5}(-\d{4})?$', stripped):
            continue
        location_parts.append(stripped)

    # Try to extract state abbreviation from remaining text
    # Handles "Kalispell MT 59901" → "Kalispell MT"
    if not location_parts:
        # Last resort: look for a 2-letter state code anywhere in the address
        _NOT_STATES = {"PO", "US", "ST", "DR", "RD", "CT", "LN", "PL", "SW", "NW", "NE", "SE"}
        for m in re.finditer(r'\b([A-Z]{2})\b', street_address):
            if m.group(1) not in _NOT_STATES:
                return m.group(1)

    return " ".join(location_parts) if location_parts else ""


def _extract_source_root(source_domain: str | None) -> str | None:
    """Get root domain from source (e.g. 'members.buildingflathead.com' → 'buildingflathead.com')."""
    if not source_domain:
        return None
    src = source_domain.lower()
    return ".".join(src.rsplit(".", 2)[-2:]) if src.count(".") >= 2 else src


def reset_search_state():
    """Reset the search-stopped flag. Call at the start of each Phase 2 run."""
    global _search_stopped
    _search_stopped = False


def _ddg_fetch_results(query: str) -> list[dict[str, str]]:
    """Execute a DDG HTML search via curl_cffi (TLS-impersonated).

    Returns list of result dicts with 'href', 'title', and 'snippet' keys.
    'snippet' may be an empty string when DDG didn't render one.
    The duckduckgo-search library gets blocked; curl_cffi doesn't.
    """
    global _search_stopped
    if _search_stopped:
        # DDG already blocked this run — go straight to the Bing fallback.
        return _bing_fetch_results(query)

    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    # Rate limit — randomized to avoid pattern detection
    time.sleep(random.uniform(1.5, 3.0))

    browser = random.choice(_IMPERSONATE_TARGETS)
    try:
        session = _get_session(browser)
        search_headers = {
            **_BROWSER_HEADERS,
            "Referer": "https://duckduckgo.com/",
        }
        resp = session.get(search_url, headers=search_headers,
                           allow_redirects=True, timeout=REQUEST_TIMEOUT)

        if resp.status_code in (429, 403):
            print("    DDG blocked — switching to Bing for the rest of this run")
            _search_stopped = True
            return _bing_fetch_results(query)

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        # Iterate per-result block so we can grab the snippet element that
        # belongs to each title rather than guessing pair-wise.
        for block in soup.select(".result"):
            a = block.select_one("a.result__a")
            if not a:
                continue
            href = str(a.get("href", ""))
            title = a.get_text(strip=True)

            # Extract actual URL from DDG redirect
            if "uddg=" in href:
                href = unquote(href.split("uddg=")[1].split("&")[0])
            elif not href.startswith("http"):
                continue

            snippet_el = block.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

            results.append({"href": href, "title": title, "snippet": snippet})

        return results

    except (CurlError, Exception):
        return []


def _match_from_results(
    results: list[dict[str, str]],
    company_words: set[str],
    source_root: str | None,
) -> str | None:
    """Find the best matching company website from search results."""
    # Split words into distinctive vs generic to avoid false positives
    # like "construction" matching "constructiondive.com"
    distinctive = {w for w in company_words if w not in _GENERIC_INDUSTRY_WORDS and len(w) >= 3}
    generic = {w for w in company_words if w in _GENERIC_INDUSTRY_WORDS and len(w) >= 3}

    for r in results:
        href = r.get("href", "")
        if not href or not href.startswith("http"):
            continue

        try:
            parsed = urlparse(href)
            domain = parsed.netloc.lower().replace("www.", "")
        except Exception:
            continue

        # Skip known non-company domains
        if any(domain == skip or domain.endswith("." + skip) for skip in _SKIP_DOMAINS):
            continue

        if "duckduckgo" in domain:
            continue

        # Skip the source directory domain (compare root domains)
        if source_root:
            dom_root = ".".join(domain.rsplit(".", 2)[-2:]) if domain.count(".") >= 2 else domain
            if source_root == dom_root:
                continue

        # Skip documents
        if parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls")):
            continue

        # Domain must contain a significant word from company name
        domain_clean = domain.replace("-", "").replace(".", "")

        def _word_matches_domain(word: str, dom: str) -> bool:
            """Check if word matches in domain. Short words (< 5 chars) must appear
            at the start of the domain or right after a digit — prevents 'star'
            matching 'northstar' but allows '5starbuilders'."""
            if word not in dom:
                return False
            if len(word) >= 5:
                return True
            # Short word — check position
            idx = dom.find(word)
            # At the very start of domain
            if idx == 0:
                return True
            # After a digit (e.g. "5star", "84lumber")
            if idx > 0 and dom[idx - 1].isdigit():
                return True
            return False

        distinctive_matches = sum(1 for w in distinctive if _word_matches_domain(w, domain_clean))
        generic_matches = sum(1 for w in generic if _word_matches_domain(w, domain_clean))

        if distinctive:
            # Has distinctive words — require at least ONE distinctive match
            if distinctive_matches >= 1:
                return f"{parsed.scheme}://{parsed.netloc}"
        else:
            # ALL words are generic (e.g. "Custom Homes LLC") —
            # require at least TWO generic words to match in domain
            if generic_matches >= 2:
                return f"{parsed.scheme}://{parsed.netloc}"

    return None


# ────────────────────────────────────────────────────────────────────────────
# Verify-by-fetch scoring
# ────────────────────────────────────────────────────────────────────────────
# Replaces the legacy domain-word match (_match_from_results) for picking
# which DDG result is actually the company's website. Instead of trusting
# that "smith" in the domain proves it's the right Smith, we fetch the top
# candidates and check whether other record signals (phone, email, address,
# name in heading) actually appear on the page.
#
# Only the page DDG returned is fetched — no subpage crawl, no link
# following. The user's signals are expected to be on the home/main page.

_MIN_VERIFY_SCORE = 3
# Tiebreaker bonus by DDG rank. Added AFTER threshold check so it can't
# push a weak candidate over the bar — it only decides between qualified ones.
_RANK_BONUS = (0.5, 0.25, 0.0)


def _digits_only(s: str | None) -> str:
    """Strip everything but digits. Returns '' for None/empty."""
    if not s:
        return ""
    return re.sub(r"\D", "", s)


def _page_has_phone(page_text_digits: str, phone: str | None) -> bool:
    """True if a 10-digit US phone appears anywhere on the page in any format.

    Both sides are pre-stripped to digits-only, so (612) 555-1234 on the
    record matches 612.555.1234, 6125551234, or +1 612 555 1234 on the page.
    Returns False for non-US shapes — international numbers vary too much
    in format for a substring match to be reliable.
    """
    digits = _digits_only(phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return False
    return digits in page_text_digits


def _page_has_email(text_lower: str, mailto_emails: set[str],
                    contacts: list[dict]) -> bool:
    """True if ANY contact email (excluding free providers) appears on the page.

    Checks both plain-text occurrence and mailto: anchor hrefs. Free-provider
    addresses (gmail, yahoo, etc.) are skipped — an unrelated page mentioning
    a gmail address would coincidentally match too easily.
    """
    if not contacts:
        return False
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        if not email or "@" not in email:
            continue
        domain = email.rsplit("@", 1)[-1]
        if domain in _FREE_EMAIL_PROVIDERS:
            continue
        if email in mailto_emails or email in text_lower:
            return True
    return False


def _page_has_location(text_lower: str, street_address: str | None) -> bool:
    """True if BOTH city and state tokens from the address appear on the page.

    Uses _extract_search_location to parse city + state from the record's
    address (it already handles PO boxes, zip-only addresses, etc.). State-
    only locations are too weak to count — any business in MN would match.
    """
    if not street_address:
        return False
    location = _extract_search_location(street_address)
    if not location:
        return False
    parts = [p.lower() for p in location.split() if p]
    if len(parts) < 2:
        # Only state code parsed out — not enough on its own
        return False
    return all(p in text_lower for p in parts)


def _page_has_name_in_heading(soup: BeautifulSoup, company_words: set[str]) -> bool:
    """True if at least one company word (≥4 chars) appears in <title> or any <h1>.

    Headings are where a business actually identifies itself — much
    higher-signal than a substring anywhere on the page.
    """
    if not company_words:
        return False
    significant = {w for w in company_words if len(w) >= 4}
    if not significant:
        return False

    chunks: list[str] = []
    title = soup.find("title")
    if title and title.get_text():
        chunks.append(title.get_text().lower())
    for h1 in soup.find_all("h1"):
        chunks.append(h1.get_text(separator=" ").lower())

    heading_text = " ".join(chunks)
    if not heading_text.strip():
        return False
    return any(w in heading_text for w in significant)


def _score_candidate(
    fetch_url: str,
    phone: str | None,
    contacts: list[dict] | None,
    street_address: str | None,
    company_words: set[str],
) -> tuple[int, bool]:
    """Fetch the URL once and score signal matches against the record.

    Returns (raw_score, fetch_ok). fetch_ok=False means fetch_page returned
    no soup — caller should drop this candidate entirely (per user spec).
    """
    soup, _ = fetch_page(fetch_url)
    if soup is None:
        return 0, False

    text_lower = soup.get_text(separator=" ").lower()
    text_digits = _digits_only(text_lower)

    # Collect mailto: hrefs once — cheaper than scanning text for "mailto:"
    mailto_emails: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not isinstance(href, str):
            continue
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?", 1)[0].strip().lower()
            if addr:
                mailto_emails.add(addr)

    score = 0
    if _page_has_phone(text_digits, phone):
        score += 2
    if _page_has_email(text_lower, mailto_emails, contacts or []):
        score += 2
    if _page_has_location(text_lower, street_address):
        score += 1
    if _page_has_name_in_heading(soup, company_words):
        score += 1
    return score, True


def _verify_and_pick_website(
    results: list[dict[str, str]],
    company_words: set[str],
    source_root: str | None,
    phone: str | None = None,
    contacts: list[dict] | None = None,
    street_address: str | None = None,
) -> str | None:
    """Take top 3 viable DDG results, fetch+score each, return the best match.

    Selection pipeline:
      1. Apply basic skip filters (mirrors _match_from_results): non-http,
         _SKIP_DOMAINS, source root, duckduckgo, document extensions.
      2. Take the first 3 survivors in DDG rank order.
      3. Fetch + score each. Fetch failures are excluded — they don't compete.
      4. Filter to candidates with raw_score >= _MIN_VERIFY_SCORE.
      5. Among survivors, return the URL with the highest
         (raw_score + rank_bonus). Bonus only breaks ties; doesn't qualify.

    Returns None if no candidate qualified (including the case where all
    three fetches failed). The caller's existing 3-attempt cascade will
    then try the next query variant.
    """
    # Step 1+2: collect up to 3 viable candidates in rank order
    candidates: list[tuple[str, str]] = []  # (fetch_url, return_url)
    for r in results:
        if len(candidates) >= 3:
            break
        href = (r.get("href") or "").strip()
        if not href or not href.startswith("http"):
            continue
        try:
            parsed = urlparse(href)
            domain = parsed.netloc.lower().replace("www.", "")
        except Exception:
            continue
        if any(domain == skip or domain.endswith("." + skip) for skip in _SKIP_DOMAINS):
            continue
        if "duckduckgo" in domain:
            continue
        if source_root:
            dom_root = ".".join(domain.rsplit(".", 2)[-2:]) if domain.count(".") >= 2 else domain
            if source_root == dom_root:
                continue
        if parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls")):
            continue
        candidates.append((href, f"{parsed.scheme}://{parsed.netloc}"))

    if not candidates:
        return None

    # Step 3+4: fetch and score; keep only those that fetched AND cleared threshold
    qualified: list[tuple[float, int, str]] = []  # (effective_score, rank_idx, return_url)
    for rank_idx, (fetch_url, return_url) in enumerate(candidates):
        raw_score, fetch_ok = _score_candidate(
            fetch_url, phone, contacts, street_address, company_words
        )
        if not fetch_ok:
            # Per spec: unfetchable candidates are thrown out entirely
            continue
        if raw_score < _MIN_VERIFY_SCORE:
            continue
        bonus = _RANK_BONUS[rank_idx] if rank_idx < len(_RANK_BONUS) else 0.0
        qualified.append((raw_score + bonus, rank_idx, return_url))

    if not qualified:
        return None

    # Step 5: highest effective score wins; rank index is the natural tiebreaker
    # (lower index = higher DDG rank = preferred when raw scores are equal)
    qualified.sort(key=lambda x: (-x[0], x[1]))
    return qualified[0][2]


def ddg_search_website(
    company_name: str,
    street_address: str | None = None,
    category: str | None = None,
    phone: str | None = None,
    source_domain: str | None = None,
    contacts: list[dict] | None = None,
    accurate: bool = False,
) -> tuple[str | None, str]:
    """Search DuckDuckGo for a company's website using all available signal.

    Strategy (each attempt only fires if earlier ones returned nothing useful):
      1. Quoted exact company name + location + category — precise.
      2. Cleaned name words (no suffixes) + location + category — broader.
      3. Quoted phone number — a uniquely formatted phone often nails the
         company's own pages because they display it in headers/footers.

    Each attempt's DDG results are filtered to a single best URL by the
    match strategy chosen by `accurate`:
      - accurate=False (default): _match_from_results — fast, domain-word
        match. Higher FP rate but no extra HTTP fetches.
      - accurate=True (opt-in via UI toggle): _verify_and_pick_website —
        fetches the top 3 candidate pages and scores them against the
        record's phone / email / address / name. Lower FP rate, ~3-9 extra
        HTTP fetches per record. Surfaced as "More accurate web enrichment"
        in the Agent and Playground UIs.

    Email-domain shortcuts run BEFORE this function in enrich_from_websites
    (see website_from_emails) — records with a usable contact-email domain
    skip DDG entirely.

    Returns (url_or_none, best_query_used). The query string in the failure
    case is whichever attempt ran last, useful for debugging which strategies
    were tried.

    Note: a DDG rate-limit no longer aborts the search — _ddg_fetch_results
    transparently falls back to Bing for the rest of the run.
    """
    company_words = _build_company_words(company_name)
    if not company_words:
        return None, ""

    source_root = _extract_source_root(source_domain)
    location = _extract_search_location(street_address)

    def _pick(results: list[dict[str, str]]) -> str | None:
        """Pick a single URL from a result set, honoring the `accurate` flag.
        Default path (fast): legacy domain-word match.
        Accurate path (opt-in): fetch + score the top 3 candidates.
        """
        if accurate:
            return _verify_and_pick_website(
                results, company_words, source_root,
                phone=phone, contacts=contacts, street_address=street_address,
            )
        return _match_from_results(results, company_words, source_root)

    # --- Attempt 1: Quoted exact name + context ---
    # Quoting forces DDG to treat the name as a phrase, not a bag of words.
    # Strip nested quotes defensively (e.g. 'Joe "The Builder" Inc') so we
    # don't generate malformed query syntax.
    clean_name = company_name.replace('"', '').strip()
    parts = [f'"{clean_name}"'] if clean_name else []
    if location:
        parts.append(location)
    if category and len(category) < 40:
        parts.append(category)
    query1 = " ".join(parts)
    last_query = query1

    results1 = _ddg_fetch_results(query1)
    if results1:
        match = _pick(results1)
        if match:
            return match, query1

    # --- Attempt 2: Cleaned name (no suffixes) + context ---
    # Strips "INC", "LLC", "OF WPB" etc. but keeps location + category.
    broad_words = sorted(company_words, key=len, reverse=True)[:4]
    parts2 = broad_words[:]
    if location:
        parts2.append(location)
    if category and len(category) < 40:
        parts2.append(category)
    query2 = " ".join(parts2)

    if query2 and query2 != query1:
        last_query = query2
        results2 = _ddg_fetch_results(query2)
        if results2:
            match = _pick(results2)
            if match:
                return match, query2

    # --- Attempt 3: Quoted phone number ---
    # A formatted phone like "(512) 555-1234" is often a near-unique
    # identifier — DDG indexes the business's own header/footer pages.
    phone_query = _build_phone_query(phone)
    if phone_query:
        last_query = phone_query
        results3 = _ddg_fetch_results(phone_query)
        if results3:
            match = _pick(results3)
            if match:
                return match, phone_query

    return None, last_query
