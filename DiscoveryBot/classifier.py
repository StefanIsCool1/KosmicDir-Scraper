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

# Reuse Phase 1's structural card detector (additive import)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from html_parser import extract_sample_html  # type: ignore  # noqa: E402


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

    # No repeating cards and no directory link — single-entity website?
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
