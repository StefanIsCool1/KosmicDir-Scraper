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
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from collections import Counter

from config import (
    JUNK_TAGS, JUNK_CONTAINER_SELECTORS,
    CARD_CANDIDATE_TAGS, LAYOUT_CLASS_EXACT, LAYOUT_CLASS_FRAGMENTS,
    CARD_CLASS_HINTS, CONTACT_SIGNALS,
    SCALAR_KEYS, EXTRACTION_NULL_THRESHOLD, MIN_CARDS_FOR_LEARNING,
    RELEARN_MIN_CARDS, REPETITION_COUNTING,
    EXTERNAL_SKIP_DOMAINS, MIN_REGEX_RESULTS, FAX_CONTEXT_WINDOW,
)
from cache import get_cached_selectors, set_cached_selectors, delete_cached_selectors
from debug import debug
from llm import ask


# --- UTILITY FUNCTIONS ---

def is_layout_class(cls_string: str) -> bool:
    """Check if a class string belongs to a layout wrapper (not a content card)."""
    classes = cls_string.lower().split()

    if any(cls in LAYOUT_CLASS_EXACT for cls in classes):
        return True
    if any(frag in cls_string.lower() for frag in LAYOUT_CLASS_FRAGMENTS):
        return True
    return False


# Zebra-striping classes (Drupal/older CMSes alternate rows "odd"/"even").
# Grouping cards by one of these captures only HALF the rows — tr.odd on a
# 170-row roster yields 85. Skipped during class grouping so striped tables
# fall through to the parent-based sibling grouping, which sees every row.
_ZEBRA_CLASS_TOKENS = {
    "odd", "even", "alt", "alternate", "alternating",
    "stripe", "striped", "zebra", "row0", "row1", "row2",
}


def _is_zebra_class(cls_string: str) -> bool:
    """True when a class string consists ONLY of zebra-striping tokens."""
    tokens = set(cls_string.lower().split())
    return bool(tokens) and tokens <= _ZEBRA_CLASS_TOKENS


# Strong card-class hints: when an element's class name contains one of these
# tokens (whole-word, camelCase-aware), treat it as a likely content card
# even if it has no <a> link. Subset of CARD_CLASS_HINTS, intentionally
# narrower — excludes generic words like "row" / "item" / "entry" that match
# layout grid cells too.
_STRONG_CARD_CLASS_HINTS = {
    "member", "listing", "card", "result", "company", "directory",
    "profile", "vendor", "supplier", "contractor", "provider",
    "doctor", "physician", "dentist", "attorney", "lawyer",
    "restaurant", "clinic", "specialist", "consultant", "therapist",
    "firm", "practice", "organization",
    "person", "people", "staff", "faculty", "student", "roster",
}

# --- Tokenizer for class-name word matching ---
# Splits CSS class strings into whole-word tokens (kebab-case, snake_case,
# camelCase, PascalCase, multi-class space-separated). Used for both the
# hint match AND the chrome exclude check below.
_CSS_NON_LETTER_RE = re.compile(r'[^A-Za-z]+')
_CSS_CAMEL_BOUNDARY_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _class_word_tokens(class_string: str) -> set[str]:
    """Split a CSS class string into lowercased whole-word tokens."""
    tokens: set[str] = set()
    for part in _CSS_NON_LETTER_RE.split(class_string):
        if not part:
            continue
        for sub in _CSS_CAMEL_BOUNDARY_RE.split(part):
            if sub:
                tokens.add(sub.lower())
    return tokens


# UI-chrome / notification tokens that override a hint match. Pages bury
# "card", "result", "listing" inside class names for non-content UI: cookie
# banners, error dialogs, modals, toasts. When any of these appear alongside
# a hint, the element is chrome, not a member card.
_CARD_HINT_EXCLUDE_TOKENS = {
    # Cookie / consent / privacy
    "cookie", "consent", "privacy", "gdpr", "cmp",
    # Notifications / alerts
    "banner", "notice", "notification", "alert", "warning", "error",
    "toast", "message", "snackbar", "flash",
    # Modals / overlays
    "modal", "popup", "popover", "dialog", "tooltip", "overlay",
    "dropdown", "lightbox",
    # Empty / loading states
    "skeleton", "placeholder", "empty", "loading", "spinner",
}


def _class_matches_strong_card_hint(el) -> bool:
    """True if the element's class tokens hit a card hint AND no exclude token.

    Two-layer check:
      1. Tokenize the class string (handles kebab/snake/camel/Pascal case)
      2. Reject if any UI-chrome token is present (cookie, banner, alert,
         modal, toast, message, etc.) — those classes use "card"/"result"/
         "listing" for UI containers, not member content
      3. Otherwise, accept if at least one hint token matches

    Kills false positives like "cookieCard" (cookie banner), "result-message"
    (no-results status), "alert-card" (warning dialog), "modal-listing"
    (dropdown overlay), while still catching "member-card", "doctorListing",
    "vendor_profile", etc.
    """
    classes = " ".join(el.get("class") or [])
    tokens = _class_word_tokens(classes)
    if tokens & _CARD_HINT_EXCLUDE_TOKENS:
        return False
    return bool(tokens & _STRONG_CARD_CLASS_HINTS)


def has_card_structure(el) -> bool:
    """Check if an element has enough structure to be a member card.

    Normally requires at least one <a> link plus 2+ text elements. But
    directory sites that render contact info as plain text (no link wrapper
    on the phone, no `tel:` href) would otherwise be rejected. So when the
    element's class strongly indicates a card (e.g. ".hoa-management-directory-result"),
    we accept it without the link requirement.
    """
    has_link = bool(el.find("a"))
    text_tags = el.find_all(["p", "span", "h1", "h2", "h3", "h4", "h5",
                              "address", "strong", "b"])
    if len(text_tags) < 2:
        return False
    return has_link or _class_matches_strong_card_hint(el)


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

# Known field-label prefixes to strip from extracted values ("Phone: 555-1234"
# → "555-1234"). Deliberately a closed list: the old pattern ^[\w\s]+:\s*
# stripped ANY leading "Words:" — turning "Studio 54: NYC" into "NYC" and
# mangling names/descriptions containing a colon.
_LABEL_PREFIX_RE = re.compile(
    r'^(?:phone|tel|telephone|fax|email|e-mail|website|web|url|address|'
    r'street address|mailing address|category|type|specialty)\s*:\s*',
    re.I,
)

# Person-directory label prefixes ("Pronouns: She/Her" → "She/Her"). Separate
# from _LABEL_PREFIX_RE on purpose: adding "name"/"title" to the business list
# would start stripping them from business extractions too.
_PERSON_LABEL_PREFIX_RE = re.compile(
    r'^(?:name|full name|pronouns|preferred pronouns|title|position|role|'
    r'department|dept|office|room|email|e-mail|phone|tel|telephone|'
    r'website|web|url|personal website|homepage)\s*:\s*',
    re.I,
)

# CMS screen-reader/annotation boilerplate that leaks into visible link text.
# Drupal appends "(link sends e-mail)" / "(link is external)" to anchors;
# WordPress themes add "(opens in a new tab)". Never legitimate data in ANY
# entity type, so it is stripped from every extracted value.
_CMS_LINK_BOILERPLATE_RE = re.compile(
    r'\(\s*link\s+(?:sends\s+e-?mail|is\s+external)\s*\)'
    r'|\(\s*opens\s+in\s+(?:a\s+)?new\s+(?:tab|window)\s*\)',
    re.I,
)


def _strip_cms_boilerplate(text: str | None) -> str | None:
    """Remove CMS link annotations like "(link sends e-mail)" from text."""
    if not text:
        return text
    return _CMS_LINK_BOILERPLATE_RE.sub("", text).strip()


def _extract_company_name(element) -> str | None:
    """Extract company name from a card/detail element.
    Priority: headings > bold/strong > first usable link text.

    Skips mailto:/tel: anchors and candidates whose entire text is an email
    address or a URL — on people directories the mailto (or personal-website)
    link is often the card's only link, and its text used to leak in as the
    "name". CMS link boilerplate ("(link sends e-mail)" etc.) is stripped
    before the checks."""
    def _usable(text: str | None) -> bool:
        if not text or len(text) <= 1:
            return False
        if _EMAIL_RE.fullmatch(text):
            return False
        if text.lower().startswith(("http://", "https://", "www.")):
            return False
        return True

    for tag in _HEADING_TAGS:
        el = element.find(tag)
        if el:
            text = _strip_cms_boilerplate(el.get_text(strip=True))
            if _usable(text):
                return text
    for tag in _BOLD_TAGS:
        el = element.find(tag)
        if el:
            text = _strip_cms_boilerplate(el.get_text(strip=True))
            if _usable(text) and len(text) < 200:
                return text
    for a in element.find_all("a", limit=5):
        href = str(a.get("href") or "")
        if href.startswith(("mailto:", "tel:")):
            continue
        text = _strip_cms_boilerplate(a.get_text(strip=True))
        if _usable(text) and len(text) < 200:
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

    # Deduplicate: keep only the deepest signal elements (drop any element
    # that is an ancestor of another signal element). Walking each element's
    # parent chain is O(n × depth); the old per-pair `other in el.descendants`
    # scan was O(n² × subtree) and could hang for minutes on large pages.
    signal_ids = {id(el) for el in signal_elements}
    ancestor_ids: set[int] = set()
    for el in signal_elements:
        parent = el.parent
        while parent is not None:
            if id(parent) in signal_ids:
                ancestor_ids.add(id(parent))
            parent = parent.parent
    filtered = [el for el in signal_elements if id(el) not in ancestor_ids]

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


def _selector_for_container(el) -> str | None:
    """Short stable CSS path for a container element.

    Prefers #id, then tag.class, else walks up to 3 plain-tag hops. Used to
    address classless rows (<tr>, <li>) via their parent, since the rows
    themselves have nothing to select on.
    """
    parts: list[str] = []
    node = el
    for _ in range(3):
        if node is None or not getattr(node, "name", None) \
                or node.name in ("html", "body", "[document]"):
            break
        el_id = node.get("id")
        if el_id and re.match(r'^[A-Za-z][\w-]*$', el_id):
            parts.append(f"{node.name}#{el_id}")
            return " > ".join(reversed(parts))
        classes = [c for c in (node.get("class") or [])
                   if c and not is_layout_class(c) and re.match(r'^[A-Za-z][\w-]*$', c)]
        if classes:
            parts.append(f"{node.name}.{classes[0]}")
            return " > ".join(reversed(parts))
        parts.append(node.name)
        node = node.parent
    return " > ".join(reversed(parts)) if parts else None


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

        # Pre-filter: 3+ child elements, enough text, AND (a link OR a strong
        # card-class hint). The link requirement is bypassed when the class
        # itself flags this as a card — necessary for directory sites that
        # render contact info as plain text (e.g. hoa-usa.com's
        # ".hoa-management-directory-result" cards have no <a> per row).
        elements = [
            el for el in elements
            if (el.find("a") or _class_matches_strong_card_hint(el))
            and len(el.find_all()) >= 3
            and (len(el.get_text(strip=True)) > 40
                 if (_has_schema_markup(el) or _class_matches_strong_card_hint(el))
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
                # Zebra-stripe classes ("odd"/"even") each cover only half the
                # rows — never group on them.
                if cls_str.lower() in _ZEBRA_CLASS_TOKENS:
                    continue
                class_groups.setdefault((tag, cls_str), []).append(el)

        # Also group by full class string for exact-match cases
        full_class_counts = Counter(
            " ".join(el.get("class") or []) for el in elements if el.get("class")
        )
        for full_cls, count in full_class_counts.items():
            if count >= 4 and not is_layout_class(full_cls) \
                    and not _is_zebra_class(full_cls):
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

    # --- Strategy 2: parent-based sibling grouping (classless tables/lists) ---
    # Plain <table><tr> and unclassed <li> listings — the dominant format on
    # older association sites — never form a class group above, so without
    # this they fall through to the blind densest-chunk sample. Group
    # same-tag siblings under one container and address them with a
    # positional selector built from the container.
    if not candidates:
        for parent in soup.find_all(["table", "tbody", "ul", "ol"]):
            rows = [c for c in parent.find_all(recursive=False)
                    if getattr(c, "name", None) in ("tr", "li")]
            if len(rows) < 4:
                continue
            # Real data rows have some text and inner structure; this filters
            # header rows ("NamePhone") and one-link nav items.
            structured = [r for r in rows
                          if len(r.get_text(strip=True)) > 15
                          and len(r.find_all()) >= 2]
            if len(structured) < MIN_CARDS_FOR_LEARNING:
                continue
            container_sel = _selector_for_container(parent)
            if not container_sel:
                continue
            selector = f"{container_sel} > {structured[0].name}"
            try:
                matched = soup.select(selector)
            except Exception:
                continue
            # Under-matching means the selector missed rows; wild over-
            # matching means it hit every table/list on the page.
            if len(matched) < len(structured) or len(matched) > len(rows) * 3:
                continue
            score = score_candidate_group(soup, structured[0].name,
                                          "(classless)", structured)
            candidates.append({
                "tag": structured[0].name,
                "class": "(classless)",
                "selector": selector,
                "count": len(structured),
                "score": score,
                "sample": structured[:4],
            })
        if candidates:
            print(f"  Sample: classless sibling grouping found "
                  f"{len(candidates)} candidate group(s)")

    # --- Strategy 2.5: structural repetition detection ---
    # Hashed/utility-CSS grids and flat lists form no class group (Strategy
    # 1) and no classless <tr>/<li> container (Strategy 2), so they used to
    # fall through to the blind densest-chunk sample below. The class-blind
    # repetition detector gives them a real card_selector instead. It also
    # competes when strategies 0-2 produced only a WEAK group (score < 20 —
    # e.g. a 4-row keyboard-shortcuts table on an otherwise classless page);
    # the shared score scale then picks the winner. Local import:
    # repetition must stay import-light and html_parser-free.
    if REPETITION_COUNTING and (
        not candidates or max(c["score"] for c in candidates) < 20
    ):
        try:
            from repetition import find_repeated_records_in_soup
            r_sel, r_count, r_samples = find_repeated_records_in_soup(soup)
        except Exception as e:
            debug.log("PARSE", f"structural repetition sampling failed: {e}",
                      level="warn")
            r_sel, r_count, r_samples = None, 0, []
        if r_sel and len(r_samples) >= MIN_CARDS_FOR_LEARNING:
            score = score_candidate_group(soup, r_samples[0].name,
                                          "(structural)", r_samples)
            candidates.append({
                "tag": r_samples[0].name,
                "class": "(structural)",
                "selector": r_sel,
                "count": r_count,
                "score": score,
                "sample": r_samples[:4],
            })
            print(f"  Sample: structural repetition found {r_count} "
                  f"record(s) via '{r_sel}'")

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

def _parse_llm_json(raw: str) -> dict | None:
    """Parse a JSON object out of an LLM response.

    Tolerates markdown fences and prose before/after the object ("Here is the
    JSON: {...}"). Returns None when nothing parses — callers retry on that."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(raw[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def learn_selectors(raw_html: str, domain: str) -> dict:
    """Ask Haiku to identify CSS selectors from a small sample.
    Called ONCE per domain, then the result is cached permanently."""
    sample, detected_card_selector = extract_sample_html(raw_html)

    # When structural detection found the card container, tell the model.
    # Classless rows (plain <tr>/<li> samples) give it nothing to anchor a
    # card_selector on otherwise, and it answers with a bare tag name.
    card_hint = ""
    if detected_card_selector:
        card_hint = (
            f"\n- The repeating card container on this page matches the CSS selector: "
            f"{detected_card_selector}\n  Use this EXACT selector as card_selector "
            f"unless it is clearly wrong."
        )

    # NOTE: f-string — every literal brace in the JSON schema below is doubled.
    prompt = f"""Analyze this directory listing HTML sample. FIRST classify the entity each
card represents, THEN return CSS selectors for extracting each card's data.

STEP 1 — entity_type. What does ONE card describe?
- "business" — a company, organization, professional practice, firm, restaurant, agency,
  or any org-level contactable entity (has a name and usually phone/website/address). This is
  the DEFAULT: directories of doctors, lawyers, HOAs, restaurants, vendors, etc. are ALL
  "business" when cards carry business contact info (office phone, street address, company name).
- "person" — cards list individual human beings AS people: university rosters (students,
  faculty, staff), team/about pages, club or committee member lists, alumni directories.
  Signals: a personal name is the card's label, pronouns (He/Him, She/Her), a direct email as
  the main contact, personal websites (github.io, ~username pages), job title/department — and
  usually NO street address or company branding per card. A professional directory row with an
  office phone + address is still "business"; a roster row with name + pronouns + email is "person".
- Otherwise a short lowercase noun for the listed thing: "product", "vehicle", "event",
  "property", "book", "course", etc. Use such a type ONLY when cards describe physical
  items or listings, NOT contactable people/organizations. When in doubt between "business"
  and "person", choose "business".

STEP 2 — selectors.

If entity_type is "business", return ONLY this JSON (no markdown):
{{
  "entity_type": "business",
  "card_selector": "CSS selector for each repeating card (absolute)",
  "company_name": "selector for the primary name",
  "description": "selector for description/about text",
  "category": "selector for category/specialty/classification",
  "website": "selector for website link or text",
  "phone": "selector for phone number",
  "fax": "selector for fax number",
  "street_address": "selector for street address block",
  "mailing_address": "selector for mailing address block",
  "contact_card": "selector for individual contact blocks within a card, or null",
  "contact_name": "selector for contact name relative to contact_card, or null",
  "contact_email": "selector for contact email relative to contact_card, or null"
}}

If entity_type is "person", return ONLY this JSON (no markdown):
{{
  "entity_type": "person",
  "card_selector": "CSS selector for each repeating card/row (absolute)",
  "full_name": "selector for the person's name",
  "pronouns": "selector for preferred pronouns, or null",
  "title": "selector for job title / role / position, or null",
  "department": "selector for department / group / affiliation, or null",
  "office": "selector for office / room location, or null",
  "email": "selector for the email link or text (prefer the mailto: <a>), or null",
  "phone": "selector for phone number, or null",
  "personal_website": "selector for the person's own website link — NOT the mailto: link, or null"
}}

If entity_type is anything else, return ONLY this JSON (no markdown):
{{
  "entity_type": "<the type>",
  "card_selector": "CSS selector for each repeating card (absolute)",
  "name_field": "<the key from fields[] that is the primary identifier>",
  "fields": [
    {{"key": "<snake_case name you choose for this datum>", "selector": "<relative CSS>", "role": "<role>"}}
  ]
}}
- role is one of: identity, category, price, location, url, phone, email, spec, description, other
- EXACTLY ONE field has role "identity", and its key MUST equal name_field
- invent as many "spec" fields as the card exposes (e.g. a graphics card: chipset, memory, tdp, interface)
- omit a datum entirely if it is not present (do NOT emit empty/null entries in fields[])

Rules (all modes):
- Use class-based selectors where possible e.g. "div.listingBox"
- card_selector must be ABSOLUTE; field selectors RELATIVE to the card
- Never use :contains() pseudo-selectors — BeautifulSoup does not support them
- For <table> rows, address columns positionally: "td:nth-of-type(2)"
- For phone/price/spec: target the most specific element holding just that value{card_hint}

HTML SAMPLE:
{sample}"""
    # A single empty/malformed response must not sink the whole scrape into
    # the business regex fallback (which produces garbage on non-business
    # pages) — retry once before giving up.
    selectors = None
    for attempt in range(2):
        raw = ask(prompt, max_tokens=1200)
        selectors = _parse_llm_json(raw)
        if selectors is not None:
            break
        print(f"  LLM returned non-JSON selectors for {domain} "
              f"(attempt {attempt + 1}/2, {len(raw.strip())} chars)")
        debug.log("PARSE", f"learn_selectors attempt {attempt + 1} non-JSON",
                  level="warn")
    if selectors is None:
        return {}

    # Don't cache useless selectors — the model couldn't find a card container
    if not selectors.get("card_selector"):
        print(f"  Model returned no card_selector for {domain}, skipping cache")
        return selectors

    # A bare tag as card_selector ("tr", "li", "div") matches every such
    # element on the page — nav tables, menus, footers. When structural
    # detection produced a scoped selector, prefer it over the model's
    # unanchored guess.
    _model_sel = str(selectors.get("card_selector") or "").strip().lower()
    if detected_card_selector and _model_sel in (
            "tr", "li", "div", "article", "section", "table",
            "table tr", "tbody tr", "table > tr", "tbody > tr",
            "ul li", "ol li", "ul > li", "ol > li"):
        print(f"  Overriding generic card_selector '{_model_sel}' with "
              f"detected '{detected_card_selector}'")
        selectors["card_selector"] = detected_card_selector

    entity_type = (selectors.get("entity_type") or "business").strip().lower() or "business"
    selectors["entity_type"] = entity_type

    # Person: flat fixed schema like business, but keyed on full_name. name_field
    # is stored so main.py / exporter read the right identity column. Without a
    # full_name selector the schema is useless — don't cache it.
    if entity_type == "person":
        if not selectors.get("full_name"):
            print(f"  Person schema for {domain} has no full_name selector, skipping cache")
            return selectors
        selectors["name_field"] = "full_name"
        print(f"  Detected entity_type='person' for {domain}")

    # Non-business, non-person: validate the free-form field/role shape before caching.
    # If it's incomplete, don't cache garbage — let the caller fall through (returns no
    # members, since the contact-regex fallback can't help product/spec data).
    elif entity_type != "business":
        valid_fields = [
            f for f in (selectors.get("fields") or [])
            if isinstance(f, dict) and f.get("key") and f.get("selector")
        ]
        name_field = selectors.get("name_field")
        if not valid_fields:
            print(f"  Non-business schema for {domain} has no usable fields, skipping cache")
            return selectors
        selectors["fields"] = valid_fields
        keys = {f["key"] for f in valid_fields}
        if not name_field or name_field not in keys:
            # Fall back to the identity-role field, else the first field.
            ident = next((f["key"] for f in valid_fields if (f.get("role") or "").lower() == "identity"), None)
            selectors["name_field"] = ident or valid_fields[0]["key"]
        if not _dynamic_schema_has_data_fields(selectors):
            print(f"  Schema for {domain} is a link list (identity+url only) — "
                  f"navigation, not member cards; skipping cache")
            return selectors
        print(f"  Detected entity_type='{entity_type}' for {domain} "
              f"({len(valid_fields)} fields, identity='{selectors['name_field']}')")

    set_cached_selectors(domain, selectors)
    return selectors


# --- HEADER-MAPPED TABLE LEARNING (zero AI) ---

# Column-header keyword → (person_field, business_field), checked in order —
# specific patterns before the generic "name" catch-all. First matching
# pattern wins per column; first column wins per field.
_HEADER_FIELD_PATTERNS = [
    (re.compile(r'pronoun', re.I),                            "pronouns",         None),
    (re.compile(r'e-?mail', re.I),                            "email",            "contact_email"),
    (re.compile(r'phone|telephone|\btel\b', re.I),            "phone",            "phone"),
    (re.compile(r'\bfax\b', re.I),                            None,               "fax"),
    (re.compile(r'web\s?site|homepage|\burl\b', re.I),        "personal_website", "website"),
    (re.compile(r'company|organi[sz]ation|business|firm|employer', re.I),
                                                              None,               "company_name"),
    (re.compile(r'address', re.I),                            "office",           "street_address"),
    (re.compile(r'title|position|\brole\b', re.I),            "title",            None),
    (re.compile(r'department|\bdept\b|division|program', re.I), "department",     None),
    (re.compile(r'office|room|building', re.I),               "office",           None),
    (re.compile(r'category|\btype\b|special', re.I),          None,               "category"),
    (re.compile(r'name', re.I),                               "full_name",        "company_name"),
]

# Name-column headers that flag the rows as PEOPLE (vs the ambiguous "Name").
_PERSON_NAME_HEADER_RE = re.compile(
    r'first\s*name|last\s*name|full\s*name|student|faculty|staff|person|people',
    re.I,
)


def learn_selectors_from_table_headers(raw_html: str) -> tuple[dict, bool]:
    """Deterministically learn selectors from a labeled <table> — zero AI.

    A table with a header row ("Name | Preferred Pronouns | Email | Personal
    Website") maps columns to schema fields directly: no LLM guessing, and it
    still works when the LLM is down. Returns (selectors, confident_person):

      selectors         {} when no table maps (needs an identity column, one
                        more mapped column, and MIN_CARDS_FOR_LEARNING rows)
      confident_person  True when the headers unambiguously describe people
                        (a pronouns column, or a person-flavored name header
                        with no company column). Callers may then skip the
                        LLM entirely; otherwise the mapping is only used as a
                        fallback after LLM learning fails.
    """
    soup = strip_junk(BeautifulSoup(raw_html, "html.parser"))
    best: dict = {}
    best_confident = False
    best_rows = 0

    for table in soup.find_all("table"):
        # --- Header row: <thead>, else a leading <tr> that uses <th> cells ---
        header_row = None
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
        if header_row is None:
            first = table.find("tr")
            if first is not None and first.find("th"):
                header_row = first
        if header_row is None:
            continue
        header_cells = header_row.find_all(["th", "td"], recursive=False)
        if len(header_cells) < 2:
            continue
        headers = [c.get_text(" ", strip=True) for c in header_cells]

        # --- Map columns to fields ---
        person_map: dict[str, int] = {}
        business_map: dict[str, int] = {}
        company_signal = False  # an explicit Company/Organization header
        for idx, htext in enumerate(headers, start=1):
            if not htext:
                continue
            for pattern, p_field, b_field in _HEADER_FIELD_PATTERNS:
                if pattern.search(htext):
                    if p_field and p_field not in person_map:
                        person_map[p_field] = idx
                    if b_field and b_field not in business_map:
                        business_map[b_field] = idx
                    if b_field == "company_name" and p_field is None:
                        company_signal = True
                    break

        # --- Data rows ---
        container = table.find("tbody") or table
        rows = [r for r in container.find_all("tr", recursive=False)
                if r is not header_row and r.find(["td", "th"])]
        if len(rows) < MIN_CARDS_FOR_LEARNING:
            continue

        # --- Person vs business ---
        person_signal = "pronouns" in person_map
        name_idx = person_map.get("full_name")
        if name_idx and _PERSON_NAME_HEADER_RE.search(headers[name_idx - 1]):
            person_signal = True
        if company_signal:
            is_person, confident = False, False
        elif person_signal:
            is_person, confident = True, True
        else:
            # Ambiguous ("Name | Email | Website"): lean person unless
            # business-only columns (address/fax) are present.
            is_person = not (business_map.get("street_address")
                             or business_map.get("fax"))
            confident = False

        field_map = person_map if is_person else business_map
        identity = "full_name" if is_person else "company_name"
        if identity not in field_map or len(field_map) < 2:
            continue

        # --- Card selector, guarded against over-matching ---
        container_sel = _selector_for_container(container)
        if not container_sel:
            continue
        card_selector = f"{container_sel} > tr"
        try:
            matched = soup.select(card_selector)
        except Exception:
            continue
        if len(matched) < len(rows):
            continue
        anchored = ("." in card_selector or "#" in card_selector)
        if not anchored and len(matched) > len(rows) + 1:
            continue  # generic path ("table > tbody > tr") hit other tables too

        # --- Column selectors. Row-header tables put the first column in a
        # <th>; :nth-child keeps the remaining td positions correct there. ---
        first_cells = rows[0].find_all(["th", "td"], recursive=False)
        th_leading = bool(first_cells) and first_cells[0].name == "th"

        def _cell_sel(idx: int) -> str:
            if th_leading:
                return "th" if idx == 1 else f"td:nth-child({idx})"
            return f"td:nth-of-type({idx})"

        selectors = {"entity_type": "person" if is_person else "business",
                     "card_selector": card_selector}
        if is_person:
            selectors["name_field"] = "full_name"
        for field, idx in field_map.items():
            sel = _cell_sel(idx)
            # Business getters read href off the selected element itself, so
            # link-bearing cells need the anchor selected directly. (Person
            # getters already look inside the cell.)
            if not is_person and field in ("website", "contact_email") \
                    and 0 < idx <= len(first_cells) and first_cells[idx - 1].find("a"):
                sel += " a"
            selectors[field] = sel

        if len(rows) > best_rows:
            best, best_confident, best_rows = selectors, confident, len(rows)

    if best:
        print(f"  Header-mapped table: {best_rows} rows, "
              f"entity_type='{best['entity_type']}' "
              f"(confident={best_confident}) via '{best['card_selector']}'")
    return best, best_confident


# --- SELECTOR APPLICATION (PURE BS4, ZERO AI COST) ---

def apply_selectors(raw_html: str, selectors: dict) -> list:
    """Apply learned CSS selectors to extract all members.
    Pure BeautifulSoup — no AI calls.

    Dispatches on entity_type: "person" (flat fixed schema — rosters, faculty/
    team pages) goes through _apply_person_selectors; any other non-"business"
    schema (free-form, role-tagged fields) goes through _apply_dynamic_selectors;
    everything else (the default, incl. all legacy cached entries without an
    entity_type) uses the unchanged fixed business path below."""
    _etype = selectors.get("entity_type") or "business"
    if _etype == "person":
        return _apply_person_selectors(raw_html, selectors)
    if _etype != "business":
        return _apply_dynamic_selectors(raw_html, selectors)

    soup = BeautifulSoup(raw_html, "html.parser")
    members = []

    card_selector = selectors.get("card_selector") or ""
    if not card_selector:
        return []

    cards = soup.select(card_selector)
    if not cards:
        return []

    for card in cards:
        def get_text(sel, separator=""):
            """Extract text from a sub-selector within the card."""
            if not sel or not str(sel).strip():
                return None
            try:
                el = card.select_one(sel)
                if not el:
                    return None
                text = el.get_text(separator=separator, strip=True)
                # Collapse multiple separators and whitespace
                if separator:
                    text = re.sub(r'(\s*' + re.escape(separator) + r'\s*)+', separator + ' ', text)
                # Strip known label prefixes like "Phone:" or "Website:"
                text = _LABEL_PREFIX_RE.sub('', text)
                # Strip CMS link annotations ("(link sends e-mail)", etc.)
                text = _CMS_LINK_BOILERPLATE_RE.sub('', text)
                # Replace non-breaking spaces with regular spaces
                text = text.replace('\u00a0', ' ')
                return text.strip() or None
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
                return el.get("href") or _strip_cms_boilerplate(el.get_text(strip=True))
            except Exception:
                return None

        # Extract contacts sub-blocks
        contacts = []
        contact_sel = selectors.get("contact_card")
        name_sel = selectors.get("contact_name")
        email_sel = selectors.get("contact_email")

        if contact_sel:
            # Multiple contact blocks within each card
            try:
                for cc in card.select(contact_sel):
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
        elif name_sel or email_sel:
            # No contact_card but name/email selectors exist — apply directly to card
            try:
                name_el = card.select_one(name_sel) if name_sel else None
                email_el = card.select_one(email_sel) if email_sel else None
                if name_el or email_el:
                    email_val = None
                    if email_el:
                        href = str(email_el.get("href") or "")
                        email_val = href.replace("mailto:", "").split("?")[0].strip() or email_el.get_text(strip=True)
                    contacts.append({
                        "name": name_el.get_text(strip=True) if name_el else None,
                        "email": email_val,
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
            "street_address":  get_text(selectors.get("street_address"), separator=", "),
            "mailing_address": get_text(selectors.get("mailing_address"), separator=", "),
            "contacts":        contacts,
        })

    return members


# --- PERSON SELECTOR APPLICATION ---

# Scalar text fields of the person schema (email/personal_website have
# link-aware getters below).
_PERSON_TEXT_FIELDS = ("full_name", "pronouns", "title", "department",
                       "office", "phone")


def _person_get_text(card, sel) -> str | None:
    """Text of the first match of `sel` within a person card."""
    if not sel or not str(sel).strip():
        return None
    try:
        el = card.select_one(sel)
        if not el:
            return None
        text = el.get_text(separator=" ", strip=True)
        text = _CMS_LINK_BOILERPLATE_RE.sub('', text)
        text = _PERSON_LABEL_PREFIX_RE.sub('', text)
        text = re.sub(r'\s+', ' ', text)  # folds runs incl. non-breaking spaces
        return text.strip() or None
    except Exception:
        return None


def _person_get_email(card, sel) -> str | None:
    """Email for a person card: mailto: href of the selected element (or an
    anchor inside it), else the first email in its text. When the learned
    selector matches nothing, falls back to any mailto: link in the card —
    cards are per-person, so a mailto inside one is that person's address."""
    el = None
    if sel and str(sel).strip():
        try:
            el = card.select_one(sel)
        except Exception:
            el = None

    def _from_element(node) -> str | None:
        href = str(node.get("href") or "") if getattr(node, "get", None) else ""
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if _EMAIL_RE.match(email):
                return email
        inner = node.find("a", href=lambda h: bool(h and h.startswith("mailto:")))
        if inner:
            email = str(inner["href"])[7:].split("?")[0].strip()
            if _EMAIL_RE.match(email):
                return email
        m = _EMAIL_RE.search(node.get_text(separator=" "))
        return m.group() if m else None

    if el is not None:
        found = _from_element(el)
        if found:
            return found
    return _extract_email(card)


def _person_get_website(card, sel) -> str | None:
    """Personal-website href for a person card, never a mailto:/tel: link
    (the model sometimes points this selector at the email anchor)."""
    if not sel or not str(sel).strip():
        return None
    try:
        el = card.select_one(sel)
        if not el:
            return None
        href = str(el.get("href") or "")
        if not href:
            inner = el.find("a", href=True)
            href = str(inner["href"]) if inner else ""
        if href.startswith(("mailto:", "tel:", "javascript:")):
            return None
        return href or _strip_cms_boilerplate(el.get_text(strip=True)) or None
    except Exception:
        return None


def _apply_person_selectors(raw_html: str, selectors: dict) -> list:
    """Apply a learned "person" schema (flat, like business but person-keyed).

    One record per card: full_name, pronouns, title, department, office,
    email, phone, personal_website. Pure BeautifulSoup, no AI cost."""
    card_selector = selectors.get("card_selector") or ""
    if not card_selector:
        return []
    soup = BeautifulSoup(raw_html, "html.parser")
    try:
        cards = soup.select(card_selector)
    except Exception:
        return []
    if not cards:
        return []

    members = []
    for card in cards:
        rec = {field: _person_get_text(card, selectors.get(field))
               for field in _PERSON_TEXT_FIELDS}
        rec["email"] = _person_get_email(card, selectors.get("email"))
        rec["personal_website"] = _person_get_website(
            card, selectors.get("personal_website"))
        members.append(rec)
    return members


# --- DYNAMIC (NON-BUSINESS) SELECTOR APPLICATION ---

def _dyn_get_text(card, sel) -> str | None:
    """Text of the first match of `sel` within `card` (dynamic-schema path)."""
    if not sel or not str(sel).strip():
        return None
    try:
        el = card.select_one(sel)
        if not el:
            return None
        text = el.get_text(separator=" ", strip=True)
        text = _CMS_LINK_BOILERPLATE_RE.sub('', text)
        text = re.sub(r'\s+', ' ', text)  # folds runs incl. non-breaking spaces
        return text.strip() or None
    except Exception:
        return None


def _dyn_get_href(card, sel) -> str | None:
    """href (or text fallback) of the first match of `sel` (dynamic url role)."""
    if not sel or not str(sel).strip():
        return None
    try:
        el = card.select_one(sel)
        if not el:
            return None
        return el.get("href") or (_strip_cms_boilerplate(el.get_text(strip=True)) or None)
    except Exception:
        return None


def _apply_dynamic_selectors(raw_html: str, selectors: dict) -> list:
    """Apply free-form, role-tagged selectors for a non-"business" entity_type.

    Builds one record per card using the AI-chosen field keys (e.g. a graphics
    card → {chipset, memory, tdp, price}). Pure BeautifulSoup, no AI cost.
    `url`-role fields read href; everything else reads text."""
    card_selector = selectors.get("card_selector") or ""
    if not card_selector:
        return []
    soup = BeautifulSoup(raw_html, "html.parser")
    try:
        cards = soup.select(card_selector)
    except Exception:
        return []
    if not cards:
        return []

    fields = selectors.get("fields") or []
    members = []
    for card in cards:
        rec = {}
        for f in fields:
            if not isinstance(f, dict):
                continue
            key = f.get("key")
            sel = f.get("selector")
            role = (f.get("role") or "other").lower()
            if not key:
                continue
            rec[key] = _dyn_get_href(card, sel) if role == "url" else _dyn_get_text(card, sel)
        members.append(rec)
    return members


def _dynamic_extraction_valid(members: list, name_field: str) -> bool:
    """Validity check for a dynamic extraction: most cards yielded an identity."""
    if not members:
        return False
    if not name_field:
        return False
    with_name = sum(1 for m in members if m.get(name_field))
    return with_name >= max(3, int(len(members) * 0.5))


def _dynamic_schema_has_data_fields(selectors: dict) -> bool:
    """True when a free-form dynamic schema extracts at least one real datum.

    A schema whose only roles are identity + url is a LINK LIST — the shape
    of city/category navigation (walmart.com's state directory taught the
    cache exactly that), not of member records. Such schemas must never be
    accepted or cached: they "validate" on any page with named links and then
    shadow the real cards (address, phone) on every later page, forever.
    """
    for f in selectors.get("fields") or []:
        if isinstance(f, dict) and f.get("key") and f.get("selector") \
                and (f.get("role") or "other").lower() not in ("identity", "url"):
            return True
    return False


# Person-schema fields that carry actual data (vs. name/website, which nav
# links also have). Used by the person link-list guard below.
_PERSON_DATA_FIELDS = ("pronouns", "title", "department", "office",
                       "email", "phone")


def _selectors_valid(selectors: dict, members: list) -> bool:
    """Dispatch validity check by entity_type (business → SCALAR_KEYS)."""
    if isinstance(selectors, dict):
        etype = selectors.get("entity_type") or "business"
        if etype != "business":
            # Link-list schemas are navigation, never valid member data.
            # Failing them here also self-heals poisoned cache entries:
            # parse_member_html purges the cache when validation fails.
            if etype != "person" and not _dynamic_schema_has_data_fields(selectors):
                return False
            name_field = selectors.get("name_field") \
                or ("full_name" if etype == "person" else "")
            if not _dynamic_extraction_valid(members, name_field):
                return False
            if etype == "person":
                # Person link-list guard (the dynamic-schema guard above
                # can't cover person — its fields are flat keys, and the
                # learner may emit selectors that match nothing). A small set
                # of records carrying ONLY names is the shape of nav chrome:
                # 3 of 4 fsStyleAutoclear footer links "validated" as people
                # and poisoned the cache. A long run of name-only records
                # (>=10) is a genuine name-only roster — keep those.
                with_data = sum(1 for m in members
                                if any(m.get(f) for f in _PERSON_DATA_FIELDS))
                if with_data == 0 and len(members) < 10:
                    return False
            return True
    return is_extraction_valid(members)


# --- JSON-LD STRUCTURED DATA (zero AI cost) ---

# @type values that are page furniture, not member entities.
_JSONLD_SKIP_TYPES = {
    "website", "webpage", "breadcrumblist", "searchaction",
    "sitenavigationelement", "imageobject", "article", "newsarticle",
    "blogposting", "event", "product", "faqpage", "question", "answer",
    "review", "aggregaterating", "itemlist", "listitem", "videoobject",
}
# Generic entity types — not useful as a category label.
_JSONLD_GENERIC_TYPES = {"localbusiness", "organization", "person", "place", "thing"}


def _jsonld_iter_entities(node, depth=0):
    """Yield candidate entity dicts from a parsed JSON-LD document.
    Unwraps @graph, ItemList/itemListElement/item wrappers, and plain lists."""
    if depth > 4 or node is None:
        return
    if isinstance(node, list):
        for item in node:
            yield from _jsonld_iter_entities(item, depth + 1)
        return
    if not isinstance(node, dict):
        return
    for key in ("@graph", "itemListElement"):
        if isinstance(node.get(key), list):
            yield from _jsonld_iter_entities(node[key], depth + 1)
    if isinstance(node.get("item"), dict):
        yield from _jsonld_iter_entities(node["item"], depth + 1)
    yield node


def _jsonld_address(addr) -> str | None:
    """Flatten a schema.org address (string or PostalAddress dict)."""
    if isinstance(addr, str):
        return addr.strip() or None
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("streetAddress", "addressLocality",
                                       "addressRegion", "postalCode")]
        parts = [str(p).strip() for p in parts if p]
        return ", ".join(parts) or None
    return None


def extract_jsonld_members(raw_html: str) -> list[dict]:
    """Extract members from <script type="application/ld+json"> blocks.

    Zero AI cost and immune to CSS drift. Returns [] unless the page carries
    3+ distinct entities that have a name AND a contact signal (phone, email,
    or address) — a single blob is almost always the site describing itself,
    and name+url alone matches WebSite-style furniture.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    members: list[dict] = []
    seen_names: set[str] = set()

    for script in soup.find_all("script",
                                type=lambda t: bool(t and "ld+json" in t.lower())):
        payload = script.string or script.get_text()
        if not payload or not payload.strip():
            continue
        try:
            doc = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue

        for ent in _jsonld_iter_entities(doc):
            name = ent.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            types = ent.get("@type") or []
            if isinstance(types, str):
                types = [types]
            types_lower = {str(t).lower() for t in types}
            if types_lower & _JSONLD_SKIP_TYPES:
                continue

            phone = ent.get("telephone")
            email = ent.get("email")
            address = _jsonld_address(ent.get("address"))
            if not (phone or email or address):
                continue

            key = name.strip().lower()
            if key in seen_names:
                continue
            seen_names.add(key)

            email_str = str(email).strip() if isinstance(email, (str, int)) else None
            if email_str and email_str.lower().startswith("mailto:"):
                email_str = email_str[7:].strip()
            url = ent.get("url")
            fax = ent.get("faxNumber")
            desc = ent.get("description")
            specific_types = [t for t in types
                              if str(t).lower() not in _JSONLD_GENERIC_TYPES]

            members.append({
                "company_name":    name.strip(),
                "description":     str(desc).strip() if isinstance(desc, str) and desc.strip() else None,
                "category":        str(specific_types[0]) if specific_types else None,
                "website":         str(url).strip() if isinstance(url, str) and url.strip() else None,
                "phone":           str(phone).strip() if isinstance(phone, (str, int)) else None,
                "fax":             str(fax).strip() if isinstance(fax, str) and fax.strip() else None,
                "street_address":  address,
                "mailing_address": None,
                "contacts":        [{"name": None, "email": email_str}] if email_str else [],
            })

    return members


# --- EXTRACTION VALIDATION ---

def is_extraction_valid(members: list) -> bool:
    """Check if selector-based extraction produced real results.

    Two ways to pass:
      1. Name-dominant: >=80% of cards yielded a company_name. Name-only
         listings (contact info lives on detail pages) are real and common —
         the old null-ratio test rejected correct selectors on them, purged
         the cache, and forced a regex re-learn on every page.
      2. Field coverage: <70% of all scalar fields are null (original test).

    Downstream safety nets (cleaner label/false-positive filters and the
    is_extraction_garbage gate in main.py) still catch nav-menu extractions
    that pass the name-dominant check.
    """
    if not members:
        return False
    n = len(members)
    with_name = sum(1 for m in members if m.get("company_name"))
    if with_name >= max(3, int(n * 0.8)):
        return True
    null_counts = sum(
        1 for m in members
        for k in SCALAR_KEYS
        if not m.get(k)
    )
    total = n * len(SCALAR_KEYS)
    return (null_counts / total) < EXTRACTION_NULL_THRESHOLD if total else False


# --- MAIN PARSE ENTRY POINT ---

def _candidate_card_count(raw_html: str) -> int:
    """How many repeating card candidates the page's own structure shows.
    0 when structural detection finds no repeating card at all (skeleton /
    no-results pages fall back to the 'densest content region', which is
    exactly the case this exists to catch)."""
    try:
        _, card_sel = extract_sample_html(raw_html)
        if not card_sel:
            return 0
        return len(BeautifulSoup(raw_html, "html.parser").select(card_sel))
    except Exception:
        return 0


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
    stale_selectors = None
    if cached:
        print(f"  Using cached selectors for {domain}")
        members = apply_selectors(raw_html, cached)
        if _selectors_valid(cached, members):
            debug.log("PARSE", f"Step 1 (cached selectors): extracted {len(members)} members")
            return members
        # Before blaming the cache, look at the page. A near-empty page (an
        # alphabet letter with 0-2 staff, a no-results skeleton) yields
        # nothing under perfectly GOOD selectors; deleting the cache and
        # re-learning HERE learns nav chrome and poisons every later page.
        # Keep the cache and return nothing — main.py's second pass re-applies
        # the final selectors to this page, so tiny real yields still land.
        page_cards = _candidate_card_count(raw_html)
        if page_cards < RELEARN_MIN_CARDS:
            print(f"  Cached selectors found nothing, but page shows only "
                  f"{page_cards} candidate card(s) — keeping cache, skipping re-learn")
            debug.log("PARSE", f"Thin page ({page_cards} candidate cards) — "
                      f"cache kept, no re-learn")
            return []
        print(f"  Cached selectors invalid for {domain}, re-learning...")
        debug.log("PARSE", "Cached selectors failed validation, re-learning", level="warn")
        delete_cached_selectors(domain)
        stale_selectors = cached

    # Step 1.5: schema.org JSON-LD — zero AI cost, no CSS dependence.
    # Only trusted when it covers at least as much as the visible card
    # structure: partial markup (5 blobs on a 50-card page) must not
    # short-circuit selector learning.
    jsonld_members = extract_jsonld_members(raw_html)
    if len(jsonld_members) >= MIN_CARDS_FOR_LEARNING:
        card_count = 0
        try:
            _, _card_sel = extract_sample_html(raw_html)
            if _card_sel:
                card_count = len(BeautifulSoup(raw_html, "html.parser").select(_card_sel))
        except Exception:
            card_count = 0
        if len(jsonld_members) >= max(MIN_CARDS_FOR_LEARNING, int(card_count * 0.8)):
            print(f"  JSON-LD: extracted {len(jsonld_members)} members (zero AI cost)")
            debug.log("PARSE", f"JSON-LD tier: {len(jsonld_members)} members")
            return jsonld_members

    # Step 1.7: header-mapped table — zero AI. When the page is a labeled
    # table that confidently reads as a person roster ("Name | Pronouns |
    # Email | ..."), the column mapping beats an LLM guess and costs nothing.
    # Ambiguous/business tables keep going to the LLM; the mapping is kept
    # around as a fallback for when learning fails (Step 2.5).
    table_selectors, table_person_confident = learn_selectors_from_table_headers(raw_html)
    if table_selectors and table_person_confident:
        table_members = apply_selectors(raw_html, table_selectors)
        if _selectors_valid(table_selectors, table_members):
            print(f"  Header-mapped table: extracted {len(table_members)} "
                  f"person records (zero AI cost)")
            debug.log("PARSE", f"Header-mapped table tier: {len(table_members)} records")
            set_cached_selectors(domain, table_selectors)
            return table_members

    # Step 2: learn selectors from a small sample
    selector_members = []
    selectors = {}
    print(f"  Learning selectors for {domain}...")
    try:
        selectors = learn_selectors(raw_html, domain)
        debug.log("PARSE", f"Step 2 (Haiku): learned selectors", data={
            k: v for k, v in selectors.items() if v
        })
        selector_members = apply_selectors(raw_html, selectors)
        if _selectors_valid(selectors, selector_members):
            print(f"SUCCESS: Selector learned for {domain}!")
            debug.log("PARSE", f"Step 2 success: {len(selector_members)} members extracted")
            return selector_members
        print(f"  WARNING: Selector learning failed for {domain} - 0 valid members extracted")
        debug.log("PARSE", f"Step 2 failed: {len(selector_members)} members, validation failed", level="warn")
    except Exception as e:
        print(f"  WARNING: Selector learning error for {domain}: {e}")
        debug.log("PARSE", f"Step 2 error: {e}", level="error")

    # Learning failed the yield check — but learn_selectors caches its schema
    # BEFORE that check runs, so scrub it: a schema that can't extract from
    # the very page it was learned on must never shadow later pages. If we
    # displaced a previously-good cache in Step 1, restore it — it validated
    # on a real listing at least once; the new schema never has.
    delete_cached_selectors(domain)
    if stale_selectors is not None:
        set_cached_selectors(domain, stale_selectors)
        print(f"  Restored previous selectors for {domain} "
              f"(re-learned schema failed validation)")
        debug.log("PARSE", "Restored prior cached selectors after failed re-learn")

    # Step 2.5: header-mapped table fallback. The LLM failed or its selectors
    # didn't validate — a deterministic column mapping (any entity type) is
    # strictly better than the business regex fallback here.
    if table_selectors:
        table_members = apply_selectors(raw_html, table_selectors)
        if _selectors_valid(table_selectors, table_members):
            print(f"  Header-mapped table fallback: extracted {len(table_members)} "
                  f"{table_selectors.get('entity_type')} records")
            debug.log("PARSE", f"Header-mapped fallback: {len(table_members)} records")
            set_cached_selectors(domain, table_selectors)
            return table_members

    # Non-business directories (person/product/etc.) have no contact-regex fallback —
    # the regex layer below only produces business-shaped records (email-as-name on
    # rosters was exactly the bug the person schema fixes). Return the best selector
    # result we have (possibly empty) instead of business-shaped garbage.
    _etype = (selectors.get("entity_type") if isinstance(selectors, dict) else None) \
        or (cached.get("entity_type") if cached else None) or "business"
    if _etype != "business":
        # A link-list schema (identity+url roles only) is navigation —
        # returning its records would ship city/category links as "members".
        _schema = selectors if isinstance(selectors, dict) and selectors.get("fields") \
            else (cached or {})
        if _etype != "person" and not _dynamic_schema_has_data_fields(_schema):
            debug.log("PARSE", f"Dynamic link-list schema ({_etype}) — "
                      f"returning 0 members", level="warn")
            return []
        debug.log("PARSE", f"Non-business ({_etype}) — skipping regex fallback", level="warn")
        return selector_members or []

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