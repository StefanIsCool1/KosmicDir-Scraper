"""
Phase 0 — Classification & Routing

Each preflight-passed URL is classified as:
    DIRECTORY — repeating card structure detected → Phase 1 will scrape it
    WEBSITE   — single-entity page with contact info → could feed Phase 2
    REJECT    — neither (low confidence, no useful data)

Reuses Bot/html_parser.py:extract_sample_html() — that function already
does the structural detection we need (it returns a card_selector when
it finds a repeating group). No AI is called in this module.
"""

import os
import re
import sys
from urllib.parse import urlparse

# Reuse Phase 1's structural card detector (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from html_parser import extract_sample_html  # type: ignore  # noqa: E402


# Known cross-vertical business aggregators. A "general business search engine"
# where searching wildcard ("all", "%", blank) returns every industry —
# restaurants, plumbers, doctors, lawyers, etc. — instead of just the vertical
# the user wants. Phase 1 should fill the search box with the user's intent
# (industry_canonical + aliases) on these sites instead of a wildcard.
#
# Only include domains that span MULTIPLE professional verticals. Vertical-
# specific aggregators (e.g. angi.com for home services, avvo.com for lawyers,
# zocdoc.com for healthcare) are NOT in this list — on those, wildcard search
# is still the right move when the user's intent matches the vertical.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset({
    # --- US general business / yellow pages ---
    "yellowpages.com", "yp.com",
    "superpages.com",
    "yellowbook.com", "yellowbot.com",
    "yellowpagecity.com", "magicyellow.com",
    "whitepages.com",
    "411.com",
    "citysearch.com",
    "merchantcircle.com",
    "local.com", "localdatabase.com", "locallinkz.com",
    "nicelocal.com", "elocal.com", "ezlocal.com",
    "showmelocal.com", "2findlocal.com",
    "ibegin.com", "mojopages.com",
    "americantowns.com", "usdirectory.com",

    # --- US business data / B2B aggregators ---
    "manta.com",
    "bizapedia.com",
    "dnb.com", "dandb.com",
    "hotfrog.com",
    "brownbook.net",
    "chamberofcommerce.com",
    "bbb.org",
    "expertise.com",
    "alignable.com",
    "spoke.com",
    "zoominfo.com",
    "cylex.us.com", "cylex-usa.com",
    "buzzfile.com",
    "corporationwiki.com",
    "opencorporates.com",

    # --- US reviews / discovery (multi-vertical) ---
    "yelp.com",
    "trustpilot.com",
    "bestcompany.com",
    "sitejabber.com",
    "foursquare.com",
    "mapquest.com",

    # --- Canada ---
    "yellowpages.ca", "canpages.ca", "411.ca",

    # --- UK ---
    "yell.com", "192.com", "thomsonlocal.com", "scoot.co.uk",

    # --- Australia / NZ ---
    "yellowpages.com.au", "truelocal.com.au",

    # --- International B2B ---
    "europages.com", "kompass.com",
    "justdial.com", "sulekha.com",
})


# Phase 0 hard-skip: sites that look scrapable from a homepage fetch but
# collapse in Phase 1 — JS-heavy SPAs, multi-step search forms (zip +
# specialty), ad-saturated pages that pollute the raw response capture, or
# anything you've personally confirmed never produces clean output.
#
# This is maintained by hand — add domains as you find them. Phase 0 returns
# REJECT with reason="hard_skip_domain" so the user sees why the site was
# dropped. Use the narrowest domain that covers the bad path; subdomains are
# matched automatically (e.g. "usnews.com" covers "health.usnews.com").
PHASE0_HARD_SKIP_DOMAINS: frozenset[str] = frozenset({
    "usnews.com",   # /health-care/doctors is SPA + ad-saturated; raw dump fills with
                    # crazyegg / atmtd / zc?zip JSON, no clean doctor records emerge
})


def is_hard_skip_domain(url: str) -> bool:
    """True if `url`'s host is in the Phase 0 hard-skip list.

    Matches exact host and subdomains. Strips a leading "www." before
    comparison. Returns False on any parse error (fail-open: if we can't
    parse the URL, let the normal classifier decide).
    """
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    if host in PHASE0_HARD_SKIP_DOMAINS:
        return True
    return any(host.endswith("." + d) for d in PHASE0_HARD_SKIP_DOMAINS)


def is_aggregator_domain(url: str) -> bool:
    """True if `url`'s host matches a known cross-vertical aggregator.

    Matches exact host and subdomains (e.g. chicago.yp.com → yp.com).
    Strips a leading "www." before comparison. Returns False on any parse
    error so unknown URLs fall through to the niche-default path.
    """
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    if host in AGGREGATOR_DOMAINS:
        return True
    return any(host.endswith("." + d) for d in AGGREGATOR_DOMAINS)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])\d{3}[\s.\-]?\d{4}(?!\d)"
)

# Link patterns that suggest the page is a directory LANDING — the actual
# member listing is one click away. These mirror anchor text and href
# fragments commonly used by chamber / association / professional sites.
_DIRECTORY_LINK_TEXT_PATTERNS = [
    re.compile(r"\bmember\s+directory\b", re.I),
    re.compile(r"\bmember\s+search\b", re.I),
    re.compile(r"\bmember\s+list(?:ing)?\b", re.I),
    re.compile(r"\bfind\s+a(?:n)?\s+\w+", re.I),       # find a member / find a doctor / find an attorney
    re.compile(r"\bbrowse\s+members?\b", re.I),
    re.compile(r"\bour\s+members?\b", re.I),
    re.compile(r"\bsearch\s+(?:the\s+)?directory\b", re.I),
    re.compile(r"\bdirectory\s+search\b", re.I),
    re.compile(r"\bprovider\s+search\b", re.I),
    re.compile(r"\bphysician\s+(?:directory|finder|search)\b", re.I),
]

_DIRECTORY_HREF_FRAGMENTS = [
    "/member-directory", "/memberdirectory",
    "/members", "/member-search", "/membersearch",
    "/directory", "/find-a-", "/findadoctor", "/find-doctor",
    "/provider-search", "/providersearch",
    "/member-list", "/memberlist",
    "/search-members", "/searchmembers",
    "/browse",
]


def _has_contact_info(soup) -> bool:
    """True if the page has at least one email or phone number visible.
    Used to distinguish a real single-entity website from a generic landing."""
    text = soup.get_text(separator=" ")
    return bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text))


def _in_site_chrome(el) -> bool:
    """True if `el` (a tag or NavigableString) sits inside nav/header/footer
    or an ARIA landmark for site chrome (navigation/banner/contentinfo).
    Contact details there are the SITE's own repeated phone/email, not
    separate directory entries, so callers exclude them."""
    if el.find_parent(["nav", "header", "footer"]):
        return True
    if el.find_parent(attrs={"role": lambda v: v in ("navigation", "banner", "contentinfo")}):
        return True
    return False


def _has_multi_entry_signals(soup) -> bool:
    """True if the page exposes 3+ DISTINCT businesses' contact details —
    i.e. a directory listing rather than a single business.

    Counts distinct *phone numbers* (normalized to their last 10 digits)
    and distinct *email domains* (from mailto: links), ignoring anything
    inside nav/header/footer. A single business repeats ONE number / ONE
    domain across the page, so it stays under the threshold; a real listing
    exposes many different ones.

    This counts distinct VALUES, not DOM elements, on purpose. Counting
    elements over-counts a single phone nested several levels deep
    (div>div>p each match the same number) and conflates "same number
    repeated" with "many businesses" — both produce false directories out
    of contact-heavy single-business homepages.

    Catches unstructured directories whose entries have no CSS classes
    (e.g. plain-text restaurant / contractor lists) that extract_sample_html
    can't detect structurally."""
    # Distinct phone numbers in visible text (leaf strings don't nest, so
    # each number is counted once regardless of wrapper depth).
    phones: set[str] = set()
    for node in soup.find_all(string=_PHONE_RE):
        if _in_site_chrome(node):
            continue
        for match in _PHONE_RE.findall(str(node)):
            digits = re.sub(r"\D", "", match)[-10:]
            if len(digits) == 10:
                phones.add(digits)
        if len(phones) >= 3:
            return True

    # Distinct email domains from mailto: links. Same business uses one
    # domain (info@acme, sales@acme → one), different businesses don't.
    email_domains: set[str] = set()
    for a in soup.find_all("a", href=lambda h: bool(h and h.lower().startswith("mailto:"))):
        if _in_site_chrome(a):
            continue
        addr = a.get("href", "")[7:].split("?", 1)[0].strip().lower()  # len("mailto:") == 7
        if "@" in addr:
            email_domains.add(addr.rsplit("@", 1)[-1])
        if len(email_domains) >= 3:
            return True

    return False


def _find_directory_landing_link(soup) -> str | None:
    """If the page links to a likely directory subpage, return that href.

    Looks at every <a> on the page and matches BOTH the visible anchor
    text against directory-naming patterns AND the href against known
    URL fragments. Returns the first match so the caller can record it
    for debugging — the actual navigation still happens inside Phase 1's
    AI navigator, not here.
    """
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = (a.get("href") or "").lower()

        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue

        if any(p.search(text) for p in _DIRECTORY_LINK_TEXT_PATTERNS):
            return href
        if any(frag in href for frag in _DIRECTORY_HREF_FRAGMENTS):
            # Guard against false positives where the fragment appears
            # only in a query string (e.g. ?utm_campaign=members)
            try:
                from urllib.parse import urlparse as _u
                path = _u(href).path.lower()
            except Exception:
                path = href
            if any(frag in path for frag in _DIRECTORY_HREF_FRAGMENTS):
                return href

    return None


def classify_one(qualified: dict) -> dict:
    """Classify a single preflight-passed candidate.

    qualified must contain: url, soup (BeautifulSoup), final_url.
    Returns the candidate with "classification" set to DIRECTORY / WEBSITE / REJECT.
    """
    url = qualified["url"]

    # Hard-skip check runs FIRST — known-unscrapable domains (PHASE0_HARD_SKIP_DOMAINS)
    # are rejected before any signal extraction so we don't even consider visiting them
    # in Phase 1. The classifier's other checks would often misclassify these sites
    # as DIRECTORY (their homepages do have card-like structure), wasting Phase 1 time.
    if is_hard_skip_domain(url):
        return {**qualified, "classification": "REJECT", "reason": "hard_skip_domain"}

    soup = qualified.get("soup")
    if soup is None:
        return {**qualified, "classification": "REJECT", "reason": "no_soup"}

    raw_html = str(soup)

    # extract_sample_html is no-AI — it returns a card_selector when it finds
    # 3+ repeating elements with card-like structure. Exactly the signal we need.
    try:
        _, card_selector = extract_sample_html(raw_html)
    except Exception:
        card_selector = None

    if card_selector:
        # Cards on this exact page — Phase 1 can scrape it directly without
        # spending an LLM call on navigation.
        return {
            **qualified,
            "classification": "DIRECTORY",
            "card_selector": card_selector,
            "needs_navigation": False,
        }

    # No cards here, but does the page LINK to a likely directory subpage?
    # Common case: DDG returned a chamber/association homepage with a
    # "Member Directory" link. Phase 1's auto mode can follow the link.
    landing_link = _find_directory_landing_link(soup)
    if landing_link:
        return {
            **qualified,
            "classification": "DIRECTORY",
            "card_selector": None,
            "needs_navigation": True,
            "landing_link": landing_link,
        }

    # No repeating cards and no directory link — check for unstructured
    # directory signals before assuming it's a single-entity website.
    # Pages like "Minnesota Restaurants" have multiple entries
    # (name + phone + address clusters) but no consistent CSS classes,
    # so extract_sample_html returns nothing. Count phone numbers and
    # email/mailto signals — 3+ in distinct elements = directory.
    if _has_multi_entry_signals(soup):
        return {
            **qualified,
            "classification": "DIRECTORY",
            "card_selector": None,
            "needs_navigation": False,
        }

    # Single-entity website with contact info
    if _has_contact_info(soup):
        return {**qualified, "classification": "WEBSITE"}

    return {**qualified, "classification": "REJECT", "reason": "no_contact_info"}


def _strip_soup(d: dict) -> dict:
    """Remove the bs4 soup object before serializing for the frontend."""
    return {k: v for k, v in d.items() if k != "soup"}


def classify_all(qualified_list: list[dict], event_cb=None) -> dict:
    """Classify all preflight-passed candidates.

    Returns a dict with three lists: directories, websites, rejected.
    Soup objects are stripped so the result is JSON-serializable.
    """
    directories: list[dict] = []
    websites: list[dict] = []
    rejected: list[dict] = []

    for q in qualified_list:
        classified = classify_one(q)
        classified["is_aggregator"] = is_aggregator_domain(classified["url"])
        clean = _strip_soup(classified)
        cls = classified["classification"]

        if event_cb:
            event_cb({
                "type": "classified",
                "url": classified["url"],
                "classification": cls,
            })

        if cls == "DIRECTORY":
            directories.append(clean)
        elif cls == "WEBSITE":
            websites.append(clean)
        else:
            rejected.append(clean)

    return {
        "directories": directories,
        "websites": websites,
        "rejected": rejected,
    }
