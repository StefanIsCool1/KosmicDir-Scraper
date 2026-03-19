"""
HTML parsing and selector learning.
Handles: sample extraction, Haiku-based selector learning, BeautifulSoup application,
         and regex fallback extraction when selectors fail.

Strategy:
1. Check cache for known selectors → apply with BS4 (zero AI cost)
2. Extract a small sample of repeating cards using scoring (not first-match)
3. Send sample to Haiku to learn CSS selectors (one cheap call per domain ever)
4. Apply learned selectors with BS4 (zero AI cost forever after)
5. FALLBACK: If selectors fail, extract data via regex/heuristics from cards or raw HTML
"""

import re
import json
import anthropic
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from collections import Counter

from config import (
    JUNK_TAGS, JUNK_CONTAINER_SELECTORS,
    CARD_CANDIDATE_TAGS, LAYOUT_CLASS_EXACT, LAYOUT_CLASS_FRAGMENTS,
    CARD_CLASS_HINTS, CONTACT_SIGNALS,
    SCALAR_KEYS, EXTRACTION_NULL_THRESHOLD, MIN_CARDS_FOR_LEARNING,
    EXTERNAL_SKIP_DOMAINS, MIN_REGEX_RESULTS, FAX_CONTEXT_WINDOW,
)
from cache import get_cached_selectors, set_cached_selectors, delete_cached_selectors
from debug import debug


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

    # Tags that must never be removed — removing these wipes the entire page
    PROTECTED_TAGS = {"html", "body", "main", "article", "section"}

    # Remove junk tags entirely
    for tag in soup(JUNK_TAGS):
        tag.decompose()

    # Remove layout/navigation containers
    for sel in JUNK_CONTAINER_SELECTORS:
        try:
            for el in soup.select(sel):
                if el.name in PROTECTED_TAGS:
                    debug.log("PARSE", f"strip_junk: protected <{el.name}> from '{sel}' "
                              f"(classes: {el.get('class', [])[:3]})", level="warn")
                    continue
                el.decompose()
        except Exception:
            # Some selectors may fail on malformed HTML, skip gracefully
            continue

    return soup


# --- REGEX FALLBACK EXTRACTION ---

# Phone: matches (206) 555-1234, 206-555-1234, 206.555.1234, 1-206-555-1234
# Anchored so it won't match ZIP codes or random digit strings
_PHONE_RE = re.compile(
    r'(?<!\d)'                                # no digit before
    r'(?:\+?1[\s.\-]?)?'                      # optional country code
    r'(?:\(\d{3}\)[\s.\-]?|\d{3}[\s.\-])'     # area code: (206)- or 206-
    r'\d{3}[\s.\-]?\d{4}'                      # exchange + subscriber
    r'(?!\d)'                                  # no digit after
)

# Email: standard pattern, run on get_text() output only (not raw HTML)
_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)

# Website text: catches www.example.com in plain text
_WEBSITE_TEXT_RE = re.compile(r'\bwww\.\S+\.\w{2,}')

# US address: street number + street type + optional city/state/zip
_ADDRESS_RE = re.compile(
    r'\d{1,6}\s+'                              # street number
    r'[A-Za-z0-9.\s]{2,40}'                    # street name
    r'(?:St\.?|Street|Ave\.?|Avenue|Blvd\.?|Boulevard|Dr\.?|Drive|Rd\.?|Road|'
    r'Ln\.?|Lane|Way|Ct\.?|Court|Pl\.?|Place|Cir\.?|Circle|'
    r'Pkwy\.?|Parkway|Hwy\.?|Highway|Suite|Ste\.?|Trl\.?|Trail)\b'
    r'[^<\n]{0,80}?'                           # rest of address line
    r'(?:,\s*)?'
    r'[A-Z]{2}\s+'                             # state abbreviation
    r'\d{5}(?:-\d{4})?',                       # ZIP code
    re.IGNORECASE
)

# Simpler fallback: just state + ZIP (for addresses without street type keywords)
_STATE_ZIP_RE = re.compile(
    r'[A-Z]{2}\s+\d{5}(?:-\d{4})?'
)

_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5"]
_BOLD_TAGS = ["strong", "b"]


def _extract_company_name(element) -> str | None:
    """Extract company name from a card/detail element.
    Priority: headings > bold/strong > first link text."""
    for tag in _HEADING_TAGS:
        el = element.find(tag)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 1:
                return text
    for tag in _BOLD_TAGS:
        el = element.find(tag)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 1 and len(text) < 200:
                return text
    a = element.find("a")
    if a:
        text = a.get_text(strip=True)
        if text and len(text) > 1 and len(text) < 200:
            return text
    return None


def _extract_phone_fax(text: str) -> tuple[str | None, str | None]:
    """Extract phone and fax from text, using context to distinguish them."""
    phone = None
    fax = None
    for match in _PHONE_RE.finditer(text):
        start = max(0, match.start() - FAX_CONTEXT_WINDOW)
        context_before = text[start:match.start()].lower()
        if "fax" in context_before:
            if not fax:
                fax = match.group().strip()
        else:
            if not phone:
                phone = match.group().strip()
    return phone, fax


def _extract_email(element) -> str | None:
    """Extract email from mailto: hrefs first, then from visible text."""
    # Priority 1: mailto: links (most reliable)
    for a_tag in element.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if _EMAIL_RE.match(email):
                return email
    # Priority 2: visible text (run on text, not raw HTML, to avoid CSS/JS noise)
    text = element.get_text(separator="\n")
    m = _EMAIL_RE.search(text)
    if m:
        return m.group()
    return None


def _extract_website(element, site_domain: str) -> str | None:
    """Extract member website, skipping the association's own domain and social media."""
    for a_tag in element.find_all("a", href=True):
        href = a_tag["href"]
        if not href.startswith(("http://", "https://", "//")):
            continue
        try:
            parsed = urlparse(href)
        except Exception:
            continue
        netloc = parsed.netloc.lower()
        # Skip the association's own domain
        if site_domain and site_domain.lower() in netloc:
            continue
        # Skip social media / platform links
        if any(d in netloc for d in EXTERNAL_SKIP_DOMAINS):
            continue
        # Skip common non-website hrefs (maps directions, tel:, etc.)
        if "/maps/" in href.lower() or "directions" in href.lower():
            continue
        return href
    # Fallback: check for www. in visible text
    text = element.get_text(separator="\n")
    m = _WEBSITE_TEXT_RE.search(text)
    if m:
        return "http://" + m.group()
    return None


def _extract_address(text: str) -> str | None:
    """Extract US street address from text."""
    # Try full address pattern first (street type + state + zip)
    m = _ADDRESS_RE.search(text)
    if m:
        addr = m.group().strip()
        # Clean up extra whitespace
        addr = re.sub(r'\s+', ' ', addr)
        return addr

    # Fallback: look for lines near a state+zip pattern
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if _STATE_ZIP_RE.search(line):
            # Grab this line and possibly the one before it (street line)
            parts = []
            if i > 0 and len(lines[i-1]) < 100:
                parts.append(lines[i-1])
            parts.append(line)
            addr = ", ".join(parts)
            addr = re.sub(r'\s+', ' ', addr)
            if len(addr) > 10:
                return addr
    return None


def regex_extract_from_card(card_element, site_domain: str) -> dict:
    """Extract member data from a single card/element using regex and heuristics.
    No AI calls — pure pattern matching."""
    company_name = _extract_company_name(card_element)
    # Use newline separator for phone/fax (need context window for "fax" label).
    # Use space separator for address (spans like <span>CO </span><span>80014</span>
    # get fragmented by newlines but stay together with spaces).
    card_text = card_element.get_text(separator="\n")
    card_text_spaced = card_element.get_text(separator=" ")

    phone, fax = _extract_phone_fax(card_text)
    email = _extract_email(card_element)
    website = _extract_website(card_element, site_domain)
    # Try space-joined text first (handles <span>CO </span><span>80014</span>),
    # fall back to newline-joined text for line-based detection.
    address = _extract_address(card_text_spaced) or _extract_address(card_text)

    contacts = []
    if email:
        contacts.append({"name": None, "email": email})

    return {
        "company_name": company_name,
        "description": None,
        "category": None,
        "website": website,
        "phone": phone,
        "fax": fax,
        "street_address": address,
        "mailing_address": None,
        "contacts": contacts,
    }


def regex_fallback_extract(raw_html: str, domain: str) -> list[dict]:
    """Fallback extraction using regex when selector learning fails.

    Layer A: Use the card container selector from extract_sample_html to scope extraction
             to individual cards, then run regex within each card.
    Layer B: If no card container was found, scan for elements containing clusters
             of contact signals (phone + email near a name-like heading).
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    soup = strip_junk(soup)

    # Layer A: card-scoped regex
    _sample_html, card_selector = extract_sample_html(raw_html)
    if card_selector:
        try:
            cards = soup.select(card_selector)
        except Exception:
            cards = []
        if cards:
            members = []
            for card in cards:
                member = regex_extract_from_card(card, domain)
                if member.get("company_name"):
                    members.append(member)
            if len(members) >= MIN_REGEX_RESULTS:
                print(f"  Regex Layer A: extracted {len(members)} members from '{card_selector}'")
                return members

    # Layer B: chunk-based — find elements with contact signal clusters
    print("  Regex Layer A failed or no card selector, trying Layer B (signal clustering)...")
    signal_elements = []
    for el in soup.find_all(["div", "li", "tr", "article", "td", "section"]):
        el_text = el.get_text(separator="\n")
        if len(el_text) < 20 or len(el_text) > 2000:
            continue
        score = 0
        if _PHONE_RE.search(el_text):
            score += 2
        if _EMAIL_RE.search(el_text) or el.find("a", href=lambda h: bool(h and h.startswith("mailto:"))):
            score += 2
        # tel: links count as phone signal (even if number isn't in visible text)
        if el.find("a", href=lambda h: bool(h and h.startswith("tel:"))):
            score += 2
        if _STATE_ZIP_RE.search(el_text):
            score += 1
        if _extract_company_name(el):
            score += 1
        # Schema.org itemprop attributes are a strong structural signal —
        # GrowthZone cards have itemprop="name", "streetAddress", etc.
        if el.find(attrs={"itemprop": True}):
            score += 2
        if score >= 3:
            signal_elements.append(el)

    # Deduplicate: keep only the most specific elements (no parent-child overlap)
    filtered = []
    for el in signal_elements:
        is_ancestor = False
        for other in signal_elements:
            if other is not el and other in el.descendants:
                is_ancestor = True
                break
        if not is_ancestor:
            filtered.append(el)

    members = []
    for el in filtered:
        member = regex_extract_from_card(el, domain)
        if member.get("company_name"):
            members.append(member)

    if len(members) >= MIN_REGEX_RESULTS:
        print(f"  Regex Layer B: extracted {len(members)} members from signal clusters")
        return members

    print(f"  Regex fallback: only found {len(members)} members (below threshold of {MIN_REGEX_RESULTS})")
    return []


# --- MERGE LOGIC ---

def _merge_member_data(selector_result: dict, regex_result: dict) -> dict:
    """Merge selector-extracted and regex-extracted data for a single member.
    Selector values win when they exist; regex fills gaps."""
    merged = {}
    fields = [
        "company_name", "description", "category", "website",
        "phone", "fax", "street_address", "mailing_address",
    ]
    for field in fields:
        sel_val = selector_result.get(field)
        reg_val = regex_result.get(field)
        merged[field] = sel_val if sel_val else reg_val

    # Merge contacts: combine both lists, deduplicate by email
    sel_contacts = selector_result.get("contacts") or []
    reg_contacts = regex_result.get("contacts") or []
    seen_emails = set()
    merged_contacts = []
    for c in sel_contacts + reg_contacts:
        email = (c.get("email") or "").lower().strip()
        if email and email in seen_emails:
            continue
        if email:
            seen_emails.add(email)
        merged_contacts.append(c)
    merged["contacts"] = merged_contacts
    return merged


def _merge_member_lists(selector_members: list, regex_members: list) -> list:
    """Merge two member lists card-by-card by position.
    Assumes both lists come from the same HTML and are in the same order."""
    merged = []
    max_len = max(len(selector_members), len(regex_members))
    for i in range(max_len):
        sel = selector_members[i] if i < len(selector_members) else {}
        reg = regex_members[i] if i < len(regex_members) else {}
        if sel and reg:
            merged.append(_merge_member_data(sel, reg))
        elif sel:
            merged.append(sel)
        else:
            merged.append(reg)
    return merged


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


def _has_schema_markup(el) -> bool:
    """Check if an element has schema.org markup indicating a business/person listing."""
    itemtype = (el.get("itemtype") or "").lower()
    return any(t in itemtype for t in [
        "localbusiness", "organization", "person", "place",
    ])


def extract_sample_html(raw_html: str) -> tuple[str, str | None]:
    """Extract a small sample of member cards for selector learning.

    Uses scoring to pick the best candidate group instead of first-match.
    Strips junk containers first to reduce noise.
    Sends 4 sample cards to Haiku (minimal tokens).

    Returns: (sample_html, card_selector_or_none)
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Strip junk before analyzing
    soup = strip_junk(soup)

    candidates = []

    # --- Strategy 0: Schema.org itemscope detection ---
    # Elements with itemtype="LocalBusiness" (or Organization, Person) are
    # almost certainly member cards. This catches GrowthZone, ChamberMaster,
    # and any site using structured data — no class guessing needed.
    schema_elements = soup.find_all(attrs={"itemscope": True})
    schema_cards = [
        el for el in schema_elements
        if _has_schema_markup(el) and el.find("a") and len(el.find_all()) >= 3
    ]
    if len(schema_cards) >= MIN_CARDS_FOR_LEARNING:
        # Build a selector from the itemtype attribute
        itemtype = schema_cards[0].get("itemtype", "")
        tag = schema_cards[0].name
        selector = f'{tag}[itemtype="{itemtype}"]'
        score = score_candidate_group(soup, tag, "schema.org", schema_cards)
        score += 100  # strong bonus — schema.org is the most reliable signal
        candidates.append({
            "tag": tag,
            "class": "schema.org",
            "selector": selector,
            "count": len(schema_cards),
            "score": score,
            "sample": schema_cards[:4],
        })
        print(f"  Sample: found {len(schema_cards)} schema.org elements ({itemtype})")

    # --- Strategy 1: Class-based grouping ---
    for tag in CARD_CANDIDATE_TAGS:
        elements = soup.find_all(tag)

        # Pre-filter: must have a link, 3+ child elements, and enough text.
        # Use a lower text threshold (40 chars) for elements with schema.org
        # markup, since some cards are sparse (just name + category).
        elements = [
            el for el in elements
            if el.find("a")
            and len(el.find_all()) >= 3
            and (len(el.get_text(strip=True)) > 40 if _has_schema_markup(el)
                 else len(el.get_text(strip=True)) > 100)
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
        print("  Sample: no repeating card candidates found, scanning for densest content region")
        # Find the region with the most links and contact signals instead of
        # blindly taking first 5000 chars (which is often headers/forms/nav)
        html_str = str(soup)
        chunk_size = 5000
        if len(html_str) <= chunk_size:
            return (html_str, None)

        best_chunk = html_str[:chunk_size]
        best_score = 0

        # Slide a window across the HTML, scoring each chunk
        step = chunk_size // 2
        for i in range(0, len(html_str) - step, step):
            chunk = html_str[i:i + chunk_size]
            chunk_lower = chunk.lower()
            # Score by link density and contact-like content
            score = chunk_lower.count('<a ') + chunk_lower.count('href=')
            score += sum(2 for sig in CONTACT_SIGNALS if sig in chunk_lower)
            if score > best_score:
                best_score = score
                best_chunk = chunk

        print(f"  Sample: picked chunk with score {best_score} (links + contact signals)")
        return (best_chunk, None)

    # Pick the highest scoring candidate
    best = max(candidates, key=lambda c: c["score"])
    print(
        f"  Sample: best candidate '{best['selector']}' "
        f"(score={best['score']}, count={best['count']}), sending {len(best['sample'])} samples"
    )

    return ("\n".join(str(el) for el in best["sample"]), best["selector"])


# --- SELECTOR LEARNING (HAIKU) ---

def learn_selectors(raw_html: str, domain: str) -> dict:
    """Ask Haiku to identify CSS selectors from a small sample.
    Called ONCE per domain, then the result is cached permanently."""
    sample, _card_selector = extract_sample_html(raw_html)

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

    # Don't cache useless selectors — Haiku couldn't find anything
    if not selectors.get("card_selector"):
        print(f"  Haiku returned no card_selector for {domain}, skipping cache")
        return selectors

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
            "website":         get_href(selectors.get("website")),
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
    """Parse member directory HTML using learned CSS selectors, with regex fallback.

    Step 1: check cache for known selectors → apply free BS4 parsing
    Step 2: learn selectors from small sample (one Haiku call) → apply free BS4 parsing
    Step 3: regex fallback → extract via pattern matching, merge with partial selector results

    Returns list of member dicts.
    """
    debug.log("PARSE", f"parse_member_html called for {domain}, HTML length: {len(raw_html)} chars")

    # Step 1: use cached selectors if available (zero AI cost)
    cached = get_cached_selectors(domain)
    if cached:
        print(f"  Using cached selectors for {domain}")
        members = apply_selectors(raw_html, cached)
        if is_extraction_valid(members):
            debug.log("PARSE", f"Step 1 (cached selectors): extracted {len(members)} members")
            return members
        print(f"  Cached selectors invalid for {domain}, re-learning...")
        debug.log("PARSE", "Cached selectors failed validation, re-learning", level="warn")
        delete_cached_selectors(domain)

    # Step 2: learn selectors from a small sample
    selector_members = []
    print(f"  Learning selectors for {domain}...")
    try:
        selectors = learn_selectors(raw_html, domain)
        debug.log("PARSE", f"Step 2 (Haiku): learned selectors", data={
            k: v for k, v in selectors.items() if v
        })
        selector_members = apply_selectors(raw_html, selectors)
        if is_extraction_valid(selector_members):
            print(f"SUCCESS: Selector learned for {domain}!")
            debug.log("PARSE", f"Step 2 success: {len(selector_members)} members extracted")
            return selector_members
        print(f"  WARNING: Selector learning failed for {domain} - 0 valid members extracted")
        debug.log("PARSE", f"Step 2 failed: {len(selector_members)} members, validation failed", level="warn")
    except Exception as e:
        print(f"  WARNING: Selector learning error for {domain}: {e}")
        debug.log("PARSE", f"Step 2 error: {e}", level="error")

    # Step 3: regex fallback
    print(f"  Attempting regex fallback for {domain}...")
    debug.log("PARSE", "Step 3: trying regex fallback")
    regex_members = regex_fallback_extract(raw_html, domain)

    if regex_members:
        # If selectors partially worked, merge selector + regex per card
        if selector_members:
            print(f"  Merging {len(selector_members)} selector results with {len(regex_members)} regex results")
            merged = _merge_member_lists(selector_members, regex_members)
            if is_extraction_valid(merged):
                return merged
            # If merge didn't help, prefer whichever list is better
            if is_extraction_valid(regex_members):
                return regex_members
        else:
            if is_extraction_valid(regex_members):
                return regex_members

        # Even if below validation threshold, return regex results with company names
        # — better than nothing
        named = [m for m in regex_members if m.get("company_name")]
        if len(named) >= MIN_REGEX_RESULTS:
            print(f"  Regex extracted {len(named)} members (below validation threshold but returning anyway)")
            return named

    print(f"  All extraction methods failed for {domain}")
    return []