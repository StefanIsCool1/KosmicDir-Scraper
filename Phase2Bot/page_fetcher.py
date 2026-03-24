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
from urllib.parse import urljoin, urlparse

REQUEST_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.5

# Rotate browser fingerprints — each has a unique TLS/HTTP2 signature
_IMPERSONATE_TARGETS = ["chrome", "chrome124", "chrome120", "chrome116", "chrome110", "safari", "safari15_5"]

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
        session = Session(impersonate=browser, timeout=REQUEST_TIMEOUT)
        setattr(_thread_local, key, session)
    return session


def _make_request(url: str, browser: str, verify: bool = True):
    """Single request attempt with a specific browser fingerprint."""
    session = _get_session(browser)
    resp = session.get(url, headers=_BROWSER_HEADERS, allow_redirects=True,
                       timeout=REQUEST_TIMEOUT, verify=verify)
    return resp, resp.url


def fetch_page(url: str) -> tuple[BeautifulSoup | None, str | None]:
    """Fetch a URL with browser TLS fingerprint impersonation.
    Retries with a different fingerprint on 403.
    Returns (soup, final_url) or (None, None) on failure."""
    domain = urlparse(url).netloc
    now = time.time()
    last = _last_request_time.get(domain, 0)
    wait = RATE_LIMIT_DELAY - (now - last)
    if wait > 0:
        time.sleep(wait)

    # Pick a random browser, keep a second one ready for retry
    browsers = random.sample(_IMPERSONATE_TARGETS, min(2, len(_IMPERSONATE_TARGETS)))

    for attempt, browser in enumerate(browsers):
        try:
            resp, final_url = _make_request(url, browser)
            _last_request_time[domain] = time.time()

            if resp.status_code == 403 and attempt == 0:
                # Retry with different fingerprint
                time.sleep(1)
                continue

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
        href = a["href"]
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
}

# Business suffixes to strip when building company word set
_BUSINESS_SUFFIXES = {
    "the", "and", "of", "for",
    "inc", "llc", "ltd", "corp", "co", "company", "corporation",
    "incorporated", "limited", "enterprises", "holdings", "associates",
    "international", "partners", "consulting", "group", "pllc", "lp",
    "pc", "pa", "dba",
}

# Search rate limiting — reset per run, not global
_search_stopped = False


def _build_company_words(company_name: str) -> set[str]:
    """Build a set of significant words from a company name for domain matching.
    Uses word-boundary splitting (not substring replace) to avoid mangling words."""
    # Normalize: lowercase, replace punctuation with spaces
    name = company_name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    words = name.split()
    # Remove business suffixes as whole words
    words = [w for w in words if w not in _BUSINESS_SUFFIXES]
    # Keep words with 3+ chars (or digits like "84" in "84 Lumber")
    words = [w for w in words if len(w) >= 3 or (w.isdigit() and len(w) >= 2)]
    return set(words)


def _extract_search_location(street_address: str) -> str:
    """Extract city and state from address for search query context.
    Returns string like 'St Cloud MN' or '' if can't parse."""
    if not street_address:
        return ""

    parts = [p.strip() for p in street_address.split(",")]
    location_parts = []

    for part in parts:
        # Skip parts that look like street addresses (start with number)
        if re.match(r'^\d', part.strip()):
            continue
        # Skip PO Box lines
        if re.match(r'^po\s+box', part.strip(), re.IGNORECASE):
            continue
        location_parts.append(part.strip())

    # Return city + state parts (skip the street line)
    return " ".join(location_parts) if location_parts else ""


def reset_search_state():
    """Reset the search-stopped flag. Call at the start of each Phase 2 run."""
    global _search_stopped
    _search_stopped = False


def ddg_search_website(
    company_name: str,
    street_address: str | None = None,
    category: str | None = None,
    phone: str | None = None,
    source_domain: str | None = None,
) -> tuple[str | None, str]:
    """Search DuckDuckGo for a company's website using available data.

    Returns (url_or_none, query_used).
    Uses DuckDuckGo HTML search (no API key needed, less aggressive anti-bot).
    """
    global _search_stopped
    if _search_stopped:
        return None, ""

    # Build search query with all available context
    parts = [f'"{company_name}"']

    # Add city + state from address (not just last part — include city name)
    location = _extract_search_location(street_address)
    if location:
        parts.append(location)

    if category and len(category) < 40:
        parts.append(category)

    query = " ".join(parts)

    from urllib.parse import quote_plus
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    # Rate limit — randomized to avoid pattern detection
    time.sleep(random.uniform(1.5, 3.0))

    browser = random.choice(_IMPERSONATE_TARGETS)
    try:
        session = _get_session(browser)
        resp = session.get(search_url, allow_redirects=True, timeout=REQUEST_TIMEOUT)

        if resp.status_code in (429, 403):
            print("    Search blocked, stopping website discovery")
            _search_stopped = True
            return None, query

        if resp.status_code != 200:
            return None, query

        soup = BeautifulSoup(resp.text, "html.parser")

        # Build company name word set for domain matching
        company_words = _build_company_words(company_name)

        # DuckDuckGo results are in <a class="result__a"> tags
        # The href contains a redirect: //duckduckgo.com/l/?uddg=ENCODED_URL&...
        from urllib.parse import unquote
        for a in soup.select("a.result__a"):
            href = a.get("href", "")

            # Extract actual URL from DDG redirect
            if "uddg=" in href:
                href = unquote(href.split("uddg=")[1].split("&")[0])
            elif not href.startswith("http"):
                continue

            try:
                parsed = urlparse(href)
                domain = parsed.netloc.lower().replace("www.", "")
            except Exception:
                continue

            # Skip known non-company domains
            if any(skip in domain for skip in _SKIP_DOMAINS):
                continue

            # Skip DDG's own domains
            if "duckduckgo" in domain:
                continue

            # Skip the source directory domain (we're looking for the COMPANY's site)
            if source_domain and source_domain.lower() in domain:
                continue

            # Skip PDFs and documents
            if parsed.path.lower().endswith((".pdf", ".doc", ".docx", ".xls")):
                continue

            # Validate: domain MUST contain a significant word from company name
            # (link text alone is not enough — directory listings mention many companies)
            # Strip hyphens and dots from domain for matching
            domain_clean = domain.replace("-", "").replace(".", "")

            # Check for ANY word match (3+ chars), not just 4+ chars
            # This fixes "ABC Construction" where "abc" is only 3 chars
            has_domain_match = any(
                word in domain_clean
                for word in company_words
                if len(word) >= 3
            )

            if has_domain_match:
                found_url = f"{parsed.scheme}://{parsed.netloc}"
                return found_url, query

        return None, query

    except CurlError:
        return None, query

    except Exception:
        return None, query
