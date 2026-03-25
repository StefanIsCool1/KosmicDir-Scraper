"""
HTTP page fetcher with rate limiting and subpage discovery.
Uses curl_cffi with browser TLS fingerprint impersonation.
"""

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

# Search rate limiting — reset per run, not global
_search_stopped = False


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

    Returns list of result dicts with 'href' and 'title' keys.
    The duckduckgo-search library gets blocked; curl_cffi doesn't.
    """
    global _search_stopped
    if _search_stopped:
        return []

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
            print("    Search blocked, stopping website discovery")
            _search_stopped = True
            return []

        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for a in soup.select("a.result__a"):
            href = str(a.get("href", ""))
            title = a.get_text(strip=True)

            # Extract actual URL from DDG redirect
            if "uddg=" in href:
                href = unquote(href.split("uddg=")[1].split("&")[0])
            elif not href.startswith("http"):
                continue

            results.append({"href": href, "title": title})

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


def ddg_search_website(
    company_name: str,
    street_address: str | None = None,
    category: str | None = None,
    phone: str | None = None,
    source_domain: str | None = None,
) -> tuple[str | None, str]:
    """Search DuckDuckGo for a company's website using available data.

    Strategy:
      1. Exact quoted company name + location + category (precise)
      2. If no match: unquoted significant words + location (broader)

    Returns (url_or_none, best_query_used).
    """
    global _search_stopped
    if _search_stopped:
        return None, ""

    company_words = _build_company_words(company_name)
    if not company_words:
        return None, ""

    source_root = _extract_source_root(source_domain)
    location = _extract_search_location(street_address)

    # --- Attempt 1: Full company name + all context (no quotes) ---
    parts = [company_name]
    if location:
        parts.append(location)
    if category and len(category) < 40:
        parts.append(category)
    query1 = " ".join(parts)

    results1 = _ddg_fetch_results(query1)
    if results1:
        match = _match_from_results(results1, company_words, source_root)
        if match:
            return match, query1

    # --- Attempt 2: Cleaned name (no suffixes) + all context ---
    # Strips "INC", "LLC", "OF WPB" etc. but keeps location + category
    if _search_stopped:
        return None, query1

    broad_words = sorted(company_words, key=len, reverse=True)[:4]
    parts2 = broad_words[:]
    if location:
        parts2.append(location)
    if category and len(category) < 40:
        parts2.append(category)
    query2 = " ".join(parts2)

    # Don't repeat if cleaning didn't change anything
    if query2 == query1:
        return None, query1

    results2 = _ddg_fetch_results(query2)
    if results2:
        match = _match_from_results(results2, company_words, source_root)
        if match:
            return match, query2

    return None, query1
