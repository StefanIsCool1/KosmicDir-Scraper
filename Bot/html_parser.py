"""
HTML parsing and selector learning.
Handles: sample extraction, Haiku-based selector learning, BeautifulSoup application.

Strategy:
1. Check cache for known selectors → apply with BS4 (zero AI cost)
2. Extract a small sample of repeating cards using scoring (not first-match)
3. Send sample to Haiku to learn CSS selectors (one cheap call per domain ever)
4. Apply learned selectors with BS4 (zero AI cost forever after)
"""

import re
import json
import anthropic
from bs4 import BeautifulSoup
from collections import Counter

from config import (
    JUNK_TAGS, JUNK_CONTAINER_SELECTORS,
    CARD_CANDIDATE_TAGS, LAYOUT_CLASS_EXACT, LAYOUT_CLASS_FRAGMENTS,
    CARD_CLASS_HINTS, CONTACT_SIGNALS,
    SCALAR_KEYS, EXTRACTION_NULL_THRESHOLD, MIN_CARDS_FOR_LEARNING,
)
from cache import get_cached_selectors, set_cached_selectors, delete_cached_selectors


# --- UTILITY FUNCTIONS ---

def is_layout_class(cls_string: str) -> bool:
    """Check if a class string belongs to a layout wrapper (not a content card)."""
    classes = cls_string.lower().split()

    if any(cls in LAYOUT_CLASS_EXACT for cls in classes):
        return True
    if any(frag in cls_string.lower() for frag in LAYOUT_CLASS_FRAGMENTS):
        return True
    return False


def has_card_structure(el) -> bool:
    """Check if an element has enough structure to be a member card.
    Needs at least one link and 2+ text elements."""
    has_link = bool(el.find("a"))
    text_tags = el.find_all(["p", "span", "h1", "h2", "h3", "h4", "h5", "address"])
    return has_link and len(text_tags) >= 2


def strip_junk(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove known junk elements from the soup before card detection.
    This dramatically reduces noise so the card finder works on cleaner HTML."""

    # Remove junk tags entirely
    for tag in soup(JUNK_TAGS):
        tag.decompose()

    # Remove layout/navigation containers
    for sel in JUNK_CONTAINER_SELECTORS:
        try:
            for el in soup.select(sel):
                el.decompose()
        except Exception:
            # Some selectors may fail on malformed HTML, skip gracefully
            continue

    return soup


# --- SAMPLE EXTRACTION (WITH SCORING) ---

def score_candidate_group(soup, tag: str, cls: str, group: list) -> int:
    """Score a group of repeating elements on how likely they are to be member cards.
    Higher score = more likely to be the real directory listing."""
    score = 0
    sample = group[:6]

    # More repetitions = more likely a real listing (capped at 50)
    score += min(len(group), 50) * 2

    # Keyword signals in class name
    if any(hint in cls.lower() for hint in CARD_CLASS_HINTS):
        score += 50

    # Rich text content (member cards tend to have substantial text)
    avg_text = sum(len(el.get_text(strip=True)) for el in sample) / max(len(sample), 1)
    score += min(int(avg_text / 10), 30)  # up to 30 points

    # Has links (likely member detail pages or websites)
    has_links = sum(1 for el in sample if el.find("a"))
    score += has_links * 5

    # Has contact-like content (phone, email, address)
    for el in sample:
        el_str = str(el).lower()
        score += sum(3 for sig in CONTACT_SIGNALS if sig in el_str)

    # --- Penalties ---

    # Too short = probably nav items, not member cards
    if avg_text < 50:
        score -= 40

    # Too many links per card = probably a nav/menu section
    avg_links = sum(len(el.find_all("a")) for el in sample) / max(len(sample), 1)
    if avg_links > 10:
        score -= 30

    # Layout class leak (shouldn't happen after is_layout_class filter, but double check)
    if is_layout_class(cls):
        score -= 100

    return score


def extract_sample_html(raw_html: str) -> str:
    """Extract a small sample of member cards for selector learning.
    
    Uses scoring to pick the best candidate group instead of first-match.
    Strips junk containers first to reduce noise.
    Sends 4 sample cards to Haiku (minimal tokens).
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Strip junk before analyzing
    soup = strip_junk(soup)

    candidates = []

    for tag in CARD_CANDIDATE_TAGS:
        elements = soup.find_all(tag)

        # Pre-filter: must have a link, 3+ child elements, 100+ chars
        elements = [
            el for el in elements
            if el.find("a")
            and len(el.find_all()) >= 3
            and len(el.get_text(strip=True)) > 100
        ]

        # Group by individual class (not full class string)
        # This handles cards like "member-card premium active" vs "member-card basic"
        # by grouping on each individual class separately
        class_groups = {}
        for el in elements:
            for cls in (el.get("class") or []):
                cls_str = cls.strip()
                if not cls_str or is_layout_class(cls_str):
                    continue
                class_groups.setdefault((tag, cls_str), []).append(el)

        # Also group by full class string for exact-match cases
        full_class_counts = Counter(
            " ".join(el.get("class") or []) for el in elements if el.get("class")
        )
        for full_cls, count in full_class_counts.items():
            if count >= 4 and not is_layout_class(full_cls):
                group = [
                    el for el in elements
                    if " ".join(el.get("class") or []) == full_cls
                ]
                class_groups[(tag, full_cls)] = group

        for (t, cls), group in class_groups.items():
            if len(group) < 4:
                continue

            # Filter to elements with card-like structure
            structured = [el for el in group if has_card_structure(el)]
            if len(structured) < MIN_CARDS_FOR_LEARNING:
                continue

            score = score_candidate_group(soup, t, cls, structured)

            candidates.append({
                "tag": t,
                "class": cls,
                "selector": f"{t}.{cls}" if " " not in cls else f"{t}.{'.'.join(cls.split())}",
                "count": len(structured),
                "score": score,
                "sample": structured[:4],
            })

    if not candidates:
        print("  Sample: no repeating card candidates found, sending first 5000 chars")
        return str(soup)[:5000]

    # Pick the highest scoring candidate
    best = max(candidates, key=lambda c: c["score"])
    print(
        f"  Sample: best candidate '{best['selector']}' "
        f"(score={best['score']}, count={best['count']}), sending {len(best['sample'])} samples"
    )

    return "\n".join(str(el) for el in best["sample"])


# --- SELECTOR LEARNING (HAIKU) ---

def learn_selectors(raw_html: str, domain: str) -> dict:
    """Ask Haiku to identify CSS selectors from a small sample.
    Called ONCE per domain everthen the result is cached permanently."""
    sample = extract_sample_html(raw_html)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Analyze this member directory HTML sample and return CSS selectors for extracting data.

Return ONLY a JSON object (no markdown) with these keys:
- card_selector: CSS selector for each member card (the repeating container element)
- company_name: selector for company name (relative to card)
- description: selector for description/about text
- category: selector for category or classification
- website: selector for website link or text
- phone: selector for phone number
- fax: selector for fax number
- street_address: selector for street address block
- mailing_address: selector for mailing address block
- contact_card: selector for individual contact blocks within a card (or null)
- contact_name: selector for contact name (relative to contact_card)
- contact_email: selector for contact email (relative to contact_card)

Rules:
- Use class-based selectors where possible e.g. "div.memberBox"
- Selectors for fields inside a card should be relative to the card element
- If a field doesn't exist in the sample, use null
- card_selector must be an absolute selector (not relative)
- Never use :contains() pseudo-selectors as they are not supported by BeautifulSoup
- For phone/fax: target the most specific parent div that contains only the phone number e.g. "div.phoneWrapper" not a broad container

HTML SAMPLE:
{sample}"""
        }]
    )

    raw = response.content[0].text.strip()  # type: ignore
    # Strip markdown fences if Haiku wrapped the response
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    selectors = json.loads(raw.strip())
    set_cached_selectors(domain, selectors)
    return selectors


# --- SELECTOR APPLICATION (PURE BS4, ZERO AI COST) ---

def apply_selectors(raw_html: str, selectors: dict) -> list:
    """Apply learned CSS selectors to extract all members.
    Pure BeautifulSoup — no AI calls."""
    soup = BeautifulSoup(raw_html, "html.parser")
    members = []

    card_selector = selectors.get("card_selector") or ""
    if not card_selector:
        return []

    cards = soup.select(card_selector)
    if not cards:
        return []

    for card in cards:
        def get_text(sel):
            """Extract text from a sub-selector within the card."""
            if not sel or not str(sel).strip():
                return None
            try:
                el = card.select_one(sel)
                if not el:
                    return None
                text = el.get_text(strip=True)
                # Strip common label prefixes like "Phone:" or "Website:"
                text = re.sub(r'^[\w\s]+:\s*', '', text)
                return text or None
            except Exception:
                return None

        def get_href(sel):
            """Extract href from a sub-selector within the card."""
            if not sel or not str(sel).strip():
                return None
            try:
                el = card.select_one(sel)
                if not el:
                    return None
                return el.get("href") or el.get_text(strip=True)
            except Exception:
                return None

        # Extract contacts sub-blocks
        contacts = []
        contact_sel = selectors.get("contact_card")
        if contact_sel:
            try:
                for cc in card.select(contact_sel):
                    name_sel = selectors.get("contact_name")
                    email_sel = selectors.get("contact_email")
                    name_el = cc.select_one(name_sel) if name_sel else None
                    email_el = cc.select_one(email_sel) if email_sel else None
                    contacts.append({
                        "name": name_el.get_text(strip=True) if name_el else None,
                        "email": (
                            email_el.get("href", "").replace("mailto:", "") #type: ignore
                            or email_el.get_text(strip=True)
                        ) if email_el else None
                    })
            except Exception:
                pass

        members.append({
            "company_name":    get_text(selectors.get("company_name")),
            "description":     get_text(selectors.get("description")),
            "category":        get_text(selectors.get("category")),
            "website":         get_href("a[href^='http']") or get_href(selectors.get("website")),
            "phone":           get_text(selectors.get("phone")),
            "fax":             get_text(selectors.get("fax")),
            "street_address":  get_text(selectors.get("street_address")),
            "mailing_address": get_text(selectors.get("mailing_address")),
            "contacts":        contacts,
        })

    return members


# --- EXTRACTION VALIDATION ---

def is_extraction_valid(members: list) -> bool:
    """Check if selector-based extraction produced real results.
    Returns False if too many fields are null (selectors probably wrong)."""
    if not members:
        return False
    null_counts = sum(
        1 for m in members
        for k in SCALAR_KEYS
        if not m.get(k)
    )
    total = len(members) * len(SCALAR_KEYS)
    return (null_counts / total) < EXTRACTION_NULL_THRESHOLD if total else False


# --- MAIN PARSE ENTRY POINT ---

def parse_member_html(raw_html: str, domain: str = "unknown") -> list:
    """Parse member directory HTML using learned CSS selectors.
    
    Step 1: check cache for known selectors → apply free BS4 parsing
    Step 2: learn selectors from small sample (one Haiku call) → apply free BS4 parsing
    
    Returns list of member dicts.
    """
    # Step 1: use cached selectors if available (zero AI cost)
    cached = get_cached_selectors(domain)
    if cached:
        print(f"  Using cached selectors for {domain}")
        members = apply_selectors(raw_html, cached)
        if is_extraction_valid(members):
            return members
        print(f"  Cached selectors invalid for {domain}, re-learning...")
        delete_cached_selectors(domain)

    # Step 2: learn selectors from a small sample
    print(f"  Learning selectors for {domain}...")
    try:
        selectors = learn_selectors(raw_html, domain)
        members = apply_selectors(raw_html, selectors)
        if is_extraction_valid(members):
            print(f"SUCESS: Selector learned for {domain}!")
            return members
        print(f"  WARNING: Selector learning failed for {domain} - 0 valid members extracted")
    except Exception as e:
        print(f"  WARNING: Selector learning error for {domain}: {e}")

    return []