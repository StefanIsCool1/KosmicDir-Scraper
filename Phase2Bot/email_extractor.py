"""
Phase 2 website enrichment scraper.
Visits company websites from Phase 1 structured JSON, extracts additional
contact info, descriptions, social media, services, team, and more.
"""

import os
import sys
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# Add Bot/ to path so we can reuse existing regex patterns and utilities
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from html_parser import ( #type: ignore
    _PHONE_RE, _EMAIL_RE, _ADDRESS_RE, _STATE_ZIP_RE,
    strip_junk, FAX_CONTEXT_WINDOW,
)
from bs4 import BeautifulSoup

from Phase2Bot.page_fetcher import (
    fetch_page, discover_subpages, ddg_search_website,
    reset_search_state, website_from_emails,
)


# --- CONFIG ---

PHASE2_DUMP_DIR = os.path.join(os.path.dirname(__file__), "..", "Phase2-Dump")

EMAIL_BLACKLIST = [
    "example.com", "sentry.io", "wixpress.com", "wordpress.com",
    "squarespace.com", "domain.com", "email.com", "yourcompany.com",
    "test.com", "sentry-next.wixpress.com", "wix.com",
]

DESCRIPTION_BOILERPLATE = [
    "we use cookies", "cookie policy", "privacy policy",
    "subscribe to", "sign up for", "all rights reserved",
    "terms of service", "terms and conditions", "powered by",
    "skip to content", "javascript is required",
]

SOCIAL_DOMAINS = {
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
    "pinterest.com": "pinterest",
    "yelp.com": "yelp",
}

FOUNDED_RE = re.compile(
    r'(?:founded|established|since|est\.?)\s*(?:in\s+)?(\d{4})',
    re.IGNORECASE,
)


# --- EXTRACTION FUNCTIONS ---

# Email prefixes ranked by contact relevance (lower = better)
_EMAIL_PRIORITY = {
    "info": 0, "contact": 0, "hello": 0, "inquiries": 0, "inquiry": 0,
    "office": 1, "sales": 1, "general": 1,
    "admin": 2, "support": 2, "help": 2,
}
# Prefixes that are never useful — hard-filtered (can't contact anyone through these)
_EMAIL_JUNK_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "root",
    "unsubscribe", "bounce",
}

# Low-priority prefixes — kept but ranked last (tier 8)
_EMAIL_LOW_PRIORITY_PREFIXES = {
    "webmaster", "jobs", "careers", "recruiting", "hr",
    "billing", "invoices", "payments",
    "marketing", "newsletter", "news", "alerts", "feedback",
}

MAX_EMAILS = 10  # Keep top 10 most relevant


def _email_sort_key(email: str) -> tuple[int, int, str]:
    """Sort key: (priority_tier, is_generic, email).
    Tier 0 = best contact emails, tier 3 = personal names, tier 8 = low-priority, tier 9 = unknown."""
    prefix = email.split("@")[0].lower()
    # Check known good prefixes
    if prefix in _EMAIL_PRIORITY:
        return (_EMAIL_PRIORITY[prefix], 0, email)
    # Low-priority but still contactable (marketing@, billing@, etc.)
    # Check BEFORE generic name check so "marketing" doesn't rank as a person's name
    if prefix in _EMAIL_LOW_PRIORITY_PREFIXES:
        return (8, 0, email)
    # Personal name emails (john.smith@) — good, but rank below general inboxes
    if "." in prefix or "_" in prefix:
        return (3, 0, email)
    # Single first-name emails (john@) — decent
    if prefix.isalpha() and len(prefix) >= 3:
        return (4, 0, email)
    # Everything else
    return (9, 0, email)


def _extract_emails(soup):
    """Extract emails, ranked by contact relevance. Returns top 3."""
    emails = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if _EMAIL_RE.match(email):
                emails.add(email.lower())

    text = soup.get_text(separator="\n")
    for m in _EMAIL_RE.finditer(text):
        emails.add(m.group().lower())

    # Filter blacklisted domains and junk prefixes
    filtered = [
        e for e in emails
        if not any(bl in e for bl in EMAIL_BLACKLIST)
        and e.split("@")[0] not in _EMAIL_JUNK_PREFIXES
    ]

    # Sort by relevance and return top results
    filtered.sort(key=_email_sort_key)
    return filtered[:MAX_EMAILS]


MAX_PHONES_PER_PAGE = 5  # Cap to avoid scraping 50+ branch office numbers

def _extract_phones(soup):
    """Extract phones and fax. Returns (phones_list, fax_or_none).
    Prioritizes tel: links over regex matches. Capped to avoid location-list spam."""
    phones = []
    fax = None
    seen_digits: set[str] = set()  # Track by digits-only to avoid dupes like "(555) 123-4567" vs "555-123-4567"

    def _add_phone(number: str) -> bool:
        digits = re.sub(r'\D', '', number)
        if digits in seen_digits or len(digits) < 10:
            return False
        seen_digits.add(digits)
        phones.append(number)
        return True

    # Priority 1: tel: links (intentionally marked as callable = primary numbers)
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if href.lower().startswith("tel:"):
            number = href[4:].strip()
            number = re.sub(r'[^\d+()-.\s]', '', number)
            _add_phone(number)

    # Priority 2: regex matches from page text (but capped)
    text = soup.get_text(separator="\n")
    for match in _PHONE_RE.finditer(text):
        if len(phones) >= MAX_PHONES_PER_PAGE:
            break
        start = max(0, match.start() - FAX_CONTEXT_WINDOW)
        context = text[start:match.start()].lower()
        number = match.group().strip()
        if "fax" in context:
            if not fax:
                fax = number
        else:
            _add_phone(number)

    return phones[:MAX_PHONES_PER_PAGE], fax


def _extract_address(soup):
    """Extract street address from page content."""
    text = soup.get_text(separator=" ")
    m = _ADDRESS_RE.search(text)
    if m:
        return re.sub(r'\s+', ' ', m.group().strip())

    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if _STATE_ZIP_RE.search(line):
            parts = []
            if i > 0 and len(lines[i - 1]) < 100:
                parts.append(lines[i - 1])
            parts.append(line)
            addr = ", ".join(parts)
            addr = re.sub(r'\s+', ' ', addr)
            if len(addr) > 10:
                return addr
    return None


def _extract_description(soup):
    """Extract company description. Priority: meta tags > about content > first paragraph."""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
        if len(desc) >= 30 and not _is_boilerplate(desc):
            return desc[:500]

    og = soup.find("meta", attrs={"property": "og:description"})
    if og and og.get("content"):
        desc = og["content"].strip()
        if len(desc) >= 30 and not _is_boilerplate(desc):
            return desc[:500]

    for tag in ["main", "article", "section"]:
        for container in soup.find_all(tag):
            for p in container.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) >= 50 and not _is_boilerplate(text):
                    return text[:500]

    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) >= 80 and not _is_boilerplate(text):
            return text[:500]

    return None


def _extract_social_media(soup):
    """Extract social media profile links."""
    social = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        try:
            domain = urlparse(href).netloc.lower().replace("www.", "")
        except Exception:
            continue
        for sd, platform in SOCIAL_DOMAINS.items():
            if sd in domain and platform not in social:
                social[platform] = href
                break
    return social


def _extract_hours(soup):
    """Extract hours of operation."""
    for kw in ["hours", "schedule", "business-hours", "office-hours"]:
        for el in soup.find_all(attrs={"class": lambda c: c and kw in " ".join(c).lower()}):
            text = el.get_text(separator=" ").strip()
            if 10 < len(text) < 300:
                return re.sub(r'\s+', ' ', text)
        for el in soup.find_all(attrs={"id": lambda i: i and kw in i.lower()}):
            text = el.get_text(separator=" ").strip()
            if 10 < len(text) < 300:
                return re.sub(r'\s+', ' ', text)

    hour_keywords = ["hours", "open", "schedule", "business hours", "office hours"]
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]):
        h_text = heading.get_text(strip=True).lower()
        if any(kw in h_text for kw in hour_keywords):
            sibling = heading.find_next_sibling()
            if sibling:
                text = sibling.get_text(separator=" ").strip()
                if 10 < len(text) < 300:
                    return re.sub(r'\s+', ' ', text)
    return None


def _extract_services(soup):
    """Extract services list."""
    service_keywords = ["services", "what we do", "our services", "capabilities", "specialties"]
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        h_text = heading.get_text(strip=True).lower()
        if any(kw in h_text for kw in service_keywords):
            next_el = heading.find_next_sibling()
            while next_el:
                if next_el.name in ("ul", "ol"):
                    items = [li.get_text(strip=True) for li in next_el.find_all("li")]
                    items = [i for i in items if 2 < len(i) < 100]
                    if items:
                        return items[:20]
                if next_el.name in ("h1", "h2", "h3", "h4"):
                    break
                next_el = next_el.find_next_sibling()
    return []


def _extract_team(soup):
    """Extract team members (name + title pairs)."""
    team = []
    for kw in ["team", "staff", "leadership", "people", "our-team"]:
        containers = soup.find_all(attrs={
            "class": lambda c: c and kw in " ".join(c).lower()
        })
        for container in containers:
            for card in container.find_all(["div", "li", "article"]):
                name_el = card.find(["h2", "h3", "h4", "h5", "strong"])
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                if len(name) < 2 or len(name) > 80:
                    continue
                title = None
                for tag in ["p", "span", "h5", "h6", "small", "em"]:
                    title_el = card.find(tag)
                    if title_el and title_el != name_el:
                        t = title_el.get_text(strip=True)
                        if 2 < len(t) < 80:
                            title = t
                            break
                if name and not any(m["name"] == name for m in team):
                    team.append({"name": name, "title": title})
            if team:
                return team[:30]
    return []


def _extract_founded_year(soup):
    """Extract founding year from page text."""
    text = soup.get_text(separator=" ")
    m = FOUNDED_RE.search(text)
    if m:
        year = int(m.group(1))
        if 1800 <= year <= 2026:
            return str(year)
    return None


def _is_boilerplate(text):
    lower = text.lower()
    return any(bp in lower for bp in DESCRIPTION_BOILERPLATE)


# --- JSON-LD EXTRACTION ---

# Schema.org types that represent a business/person/place (extractable)
_JSONLD_VALID_TYPES = {
    "localbusiness", "organization", "corporation", "store", "restaurant",
    "person", "place", "medicalorganization", "dentist", "physician",
    "attorney", "legalservice", "autodealer", "autorepair",
    "homeandconstructionbusiness", "electrician", "plumber", "roofingcontractor",
    "generalcontractor", "hvacbusiness", "locksmith", "movingcompany",
    "realestateagent", "travelagency", "financialservice", "insuranceagency",
    "accountingservice", "professionalservice",
}

# Placeholder values that CMS themes ship with — never real data
_JSONLD_PLACEHOLDER_PHONES = {"555-555-5555", "000-000-0000", "123-456-7890", "(555) 555-5555"}
_JSONLD_PLACEHOLDER_ADDRESSES = {"123 main st", "123 main street", "your address here"}


def _extract_jsonld(soup):
    """Extract structured data from JSON-LD script tags.

    Returns dict with: phone, fax, email, address, description, hours, founded.
    Only extracts from business/person/place types — skips WebSite, BreadcrumbList, etc.
    Returns empty dict if no valid JSON-LD found.
    """
    result = {}
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            raw = script.string
            if not raw or len(raw.strip()) < 10:
                continue
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        # Handle @graph arrays — flatten to list of entities
        entities = []
        if isinstance(data, list):
            entities = data
        elif isinstance(data, dict) and "@graph" in data:
            entities = data["@graph"] if isinstance(data["@graph"], list) else [data["@graph"]]
        elif isinstance(data, dict):
            entities = [data]

        for entity in entities:
            if not isinstance(entity, dict):
                continue

            # Check @type is a valid business/person type
            etype = entity.get("@type", "")
            if isinstance(etype, list):
                etype = etype[0] if etype else ""
            if etype.lower() not in _JSONLD_VALID_TYPES:
                continue

            # Phone
            phone = entity.get("telephone") or entity.get("phone")
            if phone and isinstance(phone, str):
                phone = phone.strip()
                if phone.lower() not in _JSONLD_PLACEHOLDER_PHONES and len(re.sub(r'\D', '', phone)) >= 10:
                    result.setdefault("phone", phone)

            # Fax
            fax = entity.get("faxNumber") or entity.get("fax")
            if fax and isinstance(fax, str):
                fax = fax.strip()
                if len(re.sub(r'\D', '', fax)) >= 10:
                    result.setdefault("fax", fax)

            # Email
            email = entity.get("email")
            if email and isinstance(email, str):
                email = email.strip().lower()
                if _EMAIL_RE.match(email) and not any(bl in email for bl in EMAIL_BLACKLIST):
                    result.setdefault("email", email)

            # Address — can be string or PostalAddress object
            addr = entity.get("address")
            if isinstance(addr, dict):
                parts = []
                street = addr.get("streetAddress", "").strip()
                city = addr.get("addressLocality", "").strip()
                state = addr.get("addressRegion", "").strip()
                zipcode = addr.get("postalCode", "").strip()
                if street and street.lower() not in _JSONLD_PLACEHOLDER_ADDRESSES:
                    parts.append(street)
                if city:
                    parts.append(city)
                if state:
                    parts.append(state)
                if zipcode:
                    parts[-1] = parts[-1] + " " + zipcode if parts else zipcode
                if len(parts) >= 2:
                    result.setdefault("address", ", ".join(parts))
            elif isinstance(addr, str) and len(addr) > 10:
                if addr.strip().lower() not in _JSONLD_PLACEHOLDER_ADDRESSES:
                    result.setdefault("address", addr.strip())

            # Description
            desc = entity.get("description")
            if desc and isinstance(desc, str) and len(desc) >= 20 and not _is_boilerplate(desc):
                existing = result.get("description", "")
                if len(desc) > len(existing):
                    result["description"] = desc[:500]

            # Hours
            hours = entity.get("openingHours") or entity.get("openingHoursSpecification")
            if hours:
                if isinstance(hours, list):
                    hours_str = "; ".join(str(h) for h in hours if h)[:200]
                elif isinstance(hours, str):
                    hours_str = hours[:200]
                else:
                    hours_str = None
                if hours_str and len(hours_str) > 3:
                    result.setdefault("hours", hours_str)

            # Founded
            founded = entity.get("foundingDate") or entity.get("foundingYear")
            if founded and isinstance(founded, str):
                year_match = re.search(r'(\d{4})', founded)
                if year_match:
                    y = int(year_match.group(1))
                    if 1800 <= y <= 2026:
                        result.setdefault("founded", str(y))

    return result


# --- MERGE + BUILD ---

def _extract_page(soup, url):
    """Run all extractors on a single page. JSON-LD first (most reliable), then regex."""
    stripped = strip_junk(BeautifulSoup(str(soup), "html.parser"))

    # JSON-LD — structured data, highest confidence
    jsonld = _extract_jsonld(soup)

    # Regex/heuristic extractors
    emails = _extract_emails(stripped)
    phones, fax = _extract_phones(stripped)
    address = _extract_address(stripped)
    description = _extract_description(soup)  # Use original for meta tags
    social = _extract_social_media(soup)       # Social links often in nav/footer
    hours = _extract_hours(stripped)
    services = _extract_services(stripped)
    team = _extract_team(stripped)
    founded = _extract_founded_year(stripped)

    # JSON-LD values take priority over regex (more reliable, structured by site owner)
    if jsonld.get("email") and jsonld["email"] not in emails:
        emails.insert(0, jsonld["email"])
    if jsonld.get("phone"):
        phones.insert(0, jsonld["phone"])
    if jsonld.get("fax"):
        fax = jsonld["fax"]
    if jsonld.get("address"):
        address = jsonld["address"]
    if jsonld.get("description") and (not description or len(jsonld["description"]) > len(description)):
        description = jsonld["description"]
    if jsonld.get("hours"):
        hours = jsonld["hours"]
    if jsonld.get("founded"):
        founded = jsonld["founded"]

    return {
        "emails": emails, "phones": phones, "fax": fax,
        "address": address, "description": description,
        "social_media": social, "hours": hours,
        "services": services, "team": team, "founded": founded,
    }


def _merge_extractions(pages):
    """Merge results from multiple pages. Later pages fill gaps."""
    merged = {
        "emails": [], "phones": [], "fax": None, "address": None,
        "description": None, "social_media": {}, "hours": None,
        "services": [], "team": [], "founded": None,
    }
    seen_emails = set()
    seen_phones = set()

    for pd in pages:
        for email in pd.get("emails", []):
            if email not in seen_emails:
                seen_emails.add(email)
                merged["emails"].append(email)
        for phone in pd.get("phones", []):
            if phone not in seen_phones:
                seen_phones.add(phone)
                merged["phones"].append(phone)
        # Later pages (contact/about) override earlier ones (homepage)
        # since contact pages have more accurate address/fax info
        if pd.get("fax"):
            merged["fax"] = pd["fax"]
        if pd.get("address"):
            merged["address"] = pd["address"]
        desc = pd.get("description")
        if desc and (not merged["description"] or len(desc) > len(merged["description"])):
            merged["description"] = desc
        merged["social_media"].update(pd.get("social_media", {}))
        if not merged["hours"] and pd.get("hours"):
            merged["hours"] = pd["hours"]
        if not merged["services"] and pd.get("services"):
            merged["services"] = pd["services"]
        if not merged["team"] and pd.get("team"):
            merged["team"] = pd["team"]
        if not merged["founded"] and pd.get("founded"):
            merged["founded"] = pd["founded"]

    return merged


def _build_enriched_record(original, extracted):
    """Build enriched record. Original fields preserved, extracted fills gaps."""
    enriched = dict(original)

    if not enriched.get("description") and extracted.get("description"):
        enriched["description"] = extracted["description"]
    if not enriched.get("phone") and extracted.get("phones"):
        enriched["phone"] = extracted["phones"][0]
    if not enriched.get("fax") and extracted.get("fax"):
        enriched["fax"] = extracted["fax"]
    if not enriched.get("street_address") and extracted.get("address"):
        enriched["street_address"] = extracted["address"]

    existing_emails = {c.get("email", "").lower() for c in enriched.get("contacts", []) if c.get("email")}
    for email in extracted.get("emails", []):
        if email.lower() not in existing_emails:
            enriched.setdefault("contacts", []).append({"name": None, "email": email})
            existing_emails.add(email.lower())

    enriched["social_media"] = extracted.get("social_media", {})
    enriched["hours"] = extracted.get("hours")
    enriched["services"] = extracted.get("services", [])
    enriched["founded"] = extracted.get("founded")
    enriched["team"] = extracted.get("team", [])
    enriched["enrichment_source"] = enriched.get("website")
    enriched["enrichment_status"] = "enriched"
    return enriched


# --- MAIN ---

def _needs_enrichment(member):
    """Check if a member needs enrichment. Includes entries with no website (Google search)."""
    has_desc = bool(member.get("description"))
    has_phone = bool(member.get("phone"))
    has_email = any(c.get("email") for c in member.get("contacts", []))
    has_website = bool((member.get("website") or "").strip())
    # Needs enrichment if: missing website, or has website but missing other data
    if not has_website:
        return True  # Will try Google search
    return not (has_desc and has_phone and has_email)


def enrich_from_websites(json_path, event_callback=None):
    """Main entry point. Reads structured JSON, enriches entries, saves to Phase2-Dump."""
    def log(msg):
        print(msg)
        if event_callback:
            event_callback({"type": "log", "message": msg})

    with open(json_path) as f:
        members = json.load(f)

    log(f"Loaded {len(members)} members from {os.path.basename(json_path)}")

    enrichable = [m for m in members if _needs_enrichment(m)]
    complete = [m for m in members if not _needs_enrichment(m)]

    # Separate entries: those with website vs those needing Google search
    has_website = [m for m in enrichable if (m.get("website") or "").strip()]
    no_website = [m for m in enrichable if not (m.get("website") or "").strip()]

    # Pre-DDG shortcut: a contact email like john@acmecorp.com is almost
    # always the company's own domain. Derive the website locally and skip
    # the DDG roundtrip (which has a 1.5–3s rate-limit sleep per record).
    email_derived = 0
    remaining_no_website = []
    for m in no_website:
        derived = website_from_emails(m.get("contacts") or [])
        if derived:
            m["website"] = derived
            has_website.append(m)
            email_derived += 1
        else:
            remaining_no_website.append(m)
    no_website = remaining_no_website
    if email_derived:
        log(f"  Derived {email_derived} websites from contact email domains (DDG skipped)")

    log(f"  {len(has_website)} have website, {len(no_website)} need Google search, {len(complete)} already complete")

    # --- Phase A: Google search for missing websites (sequential to avoid CAPTCHA) ---
    # Extract source domain from filename (e.g. "business_hbagbr_org" → "business.hbagbr.org")
    source_domain = os.path.basename(json_path).replace("_structured.json", "").replace("_", ".")

    found_websites = {}  # {company_name: url}
    if no_website:
        # Reset search-stopped flag from any previous run
        reset_search_state()

        log(f"  Searching DuckDuckGo for {len(no_website)} missing websites...")
        for i, m in enumerate(no_website):
            name = m.get("company_name", "")
            if not name or len(name) < 3:
                continue
            found_url, query = ddg_search_website(
                company_name=name,
                street_address=m.get("street_address"),
                category=m.get("category"),
                phone=m.get("phone"),
                source_domain=source_domain,
            )
            if found_url:
                m["website"] = found_url
                found_websites[name] = found_url
                log(f"    [{i+1}/{len(no_website)}] {name} → {found_url}")
                has_website.append(m)
            else:
                log(f"    [{i+1}/{len(no_website)}] {name} → not found")
        log(f"  DuckDuckGo: found {len(found_websites)}/{len(no_website)} websites")

    # Rebuild enrichable list (only entries that now have a website)
    enrichable = has_website

    WORKERS = 8
    log(f"  Enriching {len(enrichable)} entries with {WORKERS} parallel workers...")

    def _enrich_one(idx, member):
        """Enrich a single member. Returns (idx, enriched_record, found_list_or_none)."""
        website = (member.get("website") or "").strip()
        website_source = "ddg_search" if member.get("company_name") in found_websites else "original"

        # Skip if still no website after Google search phase
        if not website or website == "/" or len(website) < 4:
            record = dict(member)
            record["enrichment_status"] = "no_website"
            record.setdefault("social_media", {})
            record.setdefault("hours", None)
            record.setdefault("services", [])
            record.setdefault("founded", None)
            record.setdefault("team", [])
            return idx, record, None

        # Normalize URL
        if not website.startswith(("http://", "https://")):
            website = "https://" + website

        # Final validation
        parsed = urlparse(website)
        if not parsed.netloc or "." not in parsed.netloc:
            record = dict(member)
            record["enrichment_status"] = "skipped"
            return idx, record, None

        try:
            soup, final_url = fetch_page(website)
            if not soup:
                record = dict(member)
                record["enrichment_status"] = "failed"
                return idx, record, None

            base_url = final_url or website
            page_data = [_extract_page(soup, base_url)]

            subpages = discover_subpages(soup, base_url)
            for ptype, purl in subpages.items():
                if purl and purl.startswith(("http://", "https://")):
                    sub_soup, sub_url = fetch_page(purl)
                    if sub_soup:
                        page_data.append(_extract_page(sub_soup, sub_url))

            merged = _merge_extractions(page_data)
            enriched = _build_enriched_record(member, merged)

            # Track how the website was obtained
            enriched["website_source"] = website_source
            if website_source != "original":
                enriched["website"] = website

            found = []
            if merged["emails"]: found.append(f"{len(merged['emails'])} emails")
            if merged["phones"]: found.append(f"{len(merged['phones'])} phones")
            if merged["address"]: found.append("address")
            if merged["description"]: found.append("description")
            if merged["social_media"]: found.append(f"{len(merged['social_media'])} social")
            if merged["services"]: found.append(f"{len(merged['services'])} services")
            if merged["team"]: found.append(f"{len(merged['team'])} team")
            if merged["founded"]: found.append(f"est. {merged['founded']}")

            if not found:
                enriched["enrichment_status"] = "no_new_data"
            return idx, enriched, found if found else None

        except Exception:
            record = dict(member)
            record["enrichment_status"] = "error"
            return idx, record, None

    results: list[dict | None] = [None] * len(enrichable)
    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(_enrich_one, i, m): i
            for i, m in enumerate(enrichable)
        }
        done_count = 0
        for future in as_completed(futures):
            idx, enriched, found = future.result()
            results[idx] = enriched
            done_count += 1
            name = enrichable[idx].get("company_name", "Unknown")

            if found:
                log(f"  [{done_count}/{len(enrichable)}] {name} — {', '.join(found)}")
                success += 1
            elif enriched.get("enrichment_status") == "failed":
                log(f"  [{done_count}/{len(enrichable)}] {name} — failed to fetch")
                failed += 1
            else:
                log(f"  [{done_count}/{len(enrichable)}] {name} — no new data")
                failed += 1

    # Add entries that still have no website (search didn't find them)
    no_website_remaining = [m for m in no_website if m.get("company_name") not in found_websites]
    for m in no_website_remaining:
        record = dict(m)
        record["enrichment_status"] = "no_website"
        record["social_media"] = {}
        record["hours"] = None
        record["services"] = []
        record["founded"] = None
        record["team"] = []
        results.append(record)

    for m in complete:
        record = dict(m)
        record["enrichment_status"] = "skipped"
        record["enrichment_source"] = m.get("website")
        record["social_media"] = {}
        record["hours"] = None
        record["services"] = []
        record["founded"] = None
        record["team"] = []
        results.append(record)

    basename = os.path.basename(json_path).replace("_structured.json", "_enriched.json")
    output_path = os.path.join(PHASE2_DUMP_DIR, basename)
    os.makedirs(PHASE2_DUMP_DIR, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    # Update original structured JSON with discovered websites
    if found_websites:
        log(f"  Updating {len(found_websites)} websites in original JSON...")
        try:
            with open(json_path) as f:
                original = json.load(f)
            updated = 0
            for m in original:
                name = m.get("company_name", "")
                if name in found_websites and not (m.get("website") or "").strip():
                    m["website"] = found_websites[name]
                    updated += 1
            if updated > 0:
                with open(json_path, "w") as f:
                    json.dump(original, f, indent=4, ensure_ascii=False)
                log(f"  Updated {updated} websites in {os.path.basename(json_path)}")
        except Exception as e:
            log(f"  Failed to update original JSON: {e}")

    ddg_count = sum(1 for r in results if r and r.get("website_source") == "ddg_search")
    log(f"Done! {len(results)} records → {basename}")
    log(f"  Enriched: {success} | Failed: {failed} | Skipped: {len(complete)}")
    if ddg_count:
        log(f"  DuckDuckGo-discovered websites: {ddg_count}")
    return output_path
