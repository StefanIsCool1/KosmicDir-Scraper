"""
Data cleaning and normalization.
Runs AFTER extraction — completely separate from scraping/parsing logic.
Handles: deduplication, phone formatting, website normalization, address cleanup,
         label-name rejection, and shared-email pruning.
"""

import re
from collections import Counter

# UI labels that frequently leak into company_name when extraction misfires.
# A record whose entire name (minus whitespace and trailing colon) matches
# one of these is not a real company — drop it.
_LABEL_WORDS = {
    "phone", "email", "website", "fax", "address", "mailing address",
    "street address", "contact", "contact us", "hours", "services",
    "service area", "category", "specialty", "specialties", "type",
    "description", "about", "summary", "name", "title", "company",
    "tel", "telephone", "e-mail", "url", "web",
}

# Phrases that, when found anywhere in a company_name, strongly indicate
# the text is NOT a real company/organization. This catches extraction
# failures where navigation items, FAQ headings, CTA text, or content
# sections leak in as "members" (e.g. matchhoa.com extracting "Cities in
# Alabama" or "Ready to Find Your Match?" as member records).
_FALSE_POSITIVE_NAME_PHRASES = [
    "faq", "faqs", "laws & regulations", "laws and regulations",
    "guides for", "guide to",
    "ready to", "find your", "why use", "why choose",
    "click here", "learn more", "read more", "get started",
    "sign up", "log in", "login", "register now",
    "privacy policy", "terms of", "cookie", "cookies",
    "all rights reserved", "copyright",
]

# Prefixes that, when a company_name starts with them, indicate
# the text is navigational or content-section text, not a real company.
_FALSE_POSITIVE_NAME_PREFIXES = [
    "cities in", "city in",
    "management in", "managers in",
    "hoa management", "property management",
    "search results for",
    "showing results",
    "page",  # "Page 1 of 10"
]

# Words that, when a company_name consists entirely of one of them
# (possibly with a trailing colon), are too generic to be a real company.
_GENERIC_SINGLE_WORDS = {
    "member", "members", "vendor", "vendors", "supplier", "suppliers",
    "provider", "providers", "customer", "customers", "client", "clients",
    "partner", "partners", "user", "users", "account", "accounts",
    "profile", "profiles", "listing", "listings",
    "details", "detail", "information", "info",
}

# Thresholds for shared-email pruning. An email appearing in BOTH
# (a) at least this many records, AND
# (b) this fraction of all records,
# is treated as a referral/contact-us email shared across the directory,
# not a per-company contact. Stripped from every record it pollutes.
_SHARED_EMAIL_MIN_COUNT = 5
_SHARED_EMAIL_MIN_FRACTION = 0.20

# An entire value that is just an email address. A person record whose
# full_name matches this is an extraction misfire (the mailto link text
# leaked in as the name), not a person.
_EMAIL_ONLY_RE = re.compile(
    r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'
)
_EMAIL_IN_TEXT_RE = re.compile(
    r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
)

# CMS link annotations ("(link sends e-mail)", "(link is external)",
# "(opens in a new tab)"). The parser strips these at extraction time; the
# cleaner strips them again as a safety net for records that arrive from
# other paths. Kept local so cleaner.py stays import-free.
_LINK_BOILERPLATE_RE = re.compile(
    r'\(\s*link\s+(?:sends\s+e-?mail|is\s+external)\s*\)'
    r'|\(\s*opens\s+in\s+(?:a\s+)?new\s+(?:tab|window)\s*\)',
    re.I,
)


# --- Dedup key normalization ---
# Previously the dedup key was just name.lower().strip(). That caused obvious
# dupes to slip through whenever extraction picked up two formatted variants
# of the same name — e.g. "Acme Corp" / "Acme Corp." / "Acme Corporation" /
# "Acme, Corp." would all hash to different keys.
#
# Normalization:
#   1. Lowercase + collapse internal whitespace
#   2. Strip commas (formatting variation, almost never meaningful)
#   3. Strip trailing punctuation
#   4. Strip dots from all tokens (handles "L.L.C." -> "llc", "Inc." -> "inc")
#   5. Map the trailing token to a canonical form for common business
#      suffixes (incorporated -> inc, corporation -> corp, etc.)
#
# Only the TRAILING token is rewritten so an internal "Co" (e.g. "Co-op
# Market") isn't accidentally normalized to anything weird.

_TRAILING_PUNCT_RE = re.compile(r'[.,;:!?\-\s]+$')

# Canonical forms for common business-suffix variants. Used after step 4
# (dot-stripping), so the keys here are dot-free.
_SUFFIX_CANONICAL = {
    "incorporated": "inc",
    "corporation": "corp",
    "company": "co",
    "limited": "ltd",
    # Dot-stripped variants of acronym forms collapse to the same canonical
    # already (l.l.c. -> llc after step 4), so they don't need entries here.
}


def _normalize_name_key(name: str) -> str:
    """Build a dedup key for a company name.

    Conflates common formatting variations: "Acme Corp", "Acme Corp.",
    "Acme Corporation", "Acme, Corp", "ACME CORP" all → "acme corp".
    Acronym suffixes with dots collapse: "Acme L.L.C." → "acme llc".
    """
    if not name:
        return ""
    # Lowercase + collapse internal whitespace
    key = " ".join(name.lower().split())
    # Strip commas (formatting variation, not semantically meaningful in
    # company names — "Smith, Jones LLC" almost always = "Smith Jones LLC")
    key = key.replace(",", " ")
    # Strip all dots — converts "L.L.C." -> "LLC", "Inc." -> "Inc"
    key = key.replace(".", "")
    # Collapse whitespace again (comma->space may have left doubles)
    key = " ".join(key.split())
    # Strip remaining trailing punctuation
    key = _TRAILING_PUNCT_RE.sub('', key)
    if not key:
        return ""
    # Rewrite trailing token if it matches a known full-form suffix
    tokens = key.split()
    if tokens:
        canonical = _SUFFIX_CANONICAL.get(tokens[-1])
        if canonical:
            tokens[-1] = canonical
    return " ".join(tokens).strip()


def _is_false_positive_name(name: str) -> bool:
    """True if `name` looks like navigational text, CTA copy, FAQ headings,
    or content-section labels — not a real company/organization name.

    Triggered by patterns like:
      "Cities in Alabama", "HOA Management in Alaska",
      "Ready to Find Your Match?", "Alaska HOA Laws & Regulations",
      "Guides for HOA Boards", "Why Use Match HOA?"
    """
    if not name:
        return True

    stripped = name.strip().lower()

    # Empty or whitespace-only
    if not stripped:
        return True

    # Question marks — real organizations don't have them
    if "?" in stripped:
        return True

    # Generic single words
    if stripped in _GENERIC_SINGLE_WORDS:
        return True

    # Known false-positive phrases anywhere in the name
    if any(fp in stripped for fp in _FALSE_POSITIVE_NAME_PHRASES):
        return True

    # Known false-positive prefixes
    if any(stripped.startswith(prefix) for prefix in _FALSE_POSITIVE_NAME_PREFIXES):
        return True

    return False


def _is_label_name(name: str) -> bool:
    """True if `name` looks like a UI label, not a real company name.

    Catches extractor false positives like 'Phone:', 'Email:', 'Website:',
    'Service Area:', etc. — text that came from a <strong> label in the
    DOM, not a heading.
    """
    if not name:
        return True
    # Strip whitespace, trailing colon, and surrounding punctuation/quotes
    stripped = name.strip().strip(":").strip(" \t\"'*•·-—").lower()
    if not stripped:
        return True
    # Multi-word labels like "service area"
    if stripped in _LABEL_WORDS:
        return True

    return False


def _prune_shared_emails(members: list) -> int:
    """Remove emails that appear across many records — they're referral
    addresses (e.g. 'hoausa@associaonline.com'), not per-company contacts.

    Mutates `members` in place. Returns the number of email entries removed.
    """
    if len(members) < _SHARED_EMAIL_MIN_COUNT:
        return 0

    # Count: how many DISTINCT records contain each email at least once?
    email_record_counts: Counter[str] = Counter()
    for m in members:
        seen_in_this_record = set()
        for c in m.get("contacts") or []:
            e = (c.get("email") or "").lower().strip()
            if e and e not in seen_in_this_record:
                email_record_counts[e] += 1
                seen_in_this_record.add(e)

    total = len(members)
    poisoned = {
        email for email, count in email_record_counts.items()
        if count >= _SHARED_EMAIL_MIN_COUNT
        and count / total >= _SHARED_EMAIL_MIN_FRACTION
    }
    if not poisoned:
        return 0

    print(
        f"  Cleaner: pruning {len(poisoned)} shared email(s) "
        f"appearing across many records: " + ", ".join(sorted(poisoned))
    )

    removed = 0
    for m in members:
        contacts = m.get("contacts") or []
        new_contacts = []
        for c in contacts:
            e = (c.get("email") or "").lower().strip()
            if e in poisoned:
                # If the contact has only the email (no name), drop the
                # whole contact. Otherwise just blank the email and keep
                # the name.
                if not (c.get("name") or "").strip():
                    removed += 1
                    continue
                c["email"] = None
            new_contacts.append(c)
        m["contacts"] = new_contacts
    return removed


def clean_members(members: list, name_field: str = "company_name",
                  is_dynamic: bool = False, field_roles: dict | None = None,
                  entity_type: str = "business") -> list:
    """Clean and deduplicate extracted member data.

    Business path (default, is_dynamic=False) is unchanged. entity_type="person"
    routes to _clean_members_person (dedup on full_name + email, person field
    normalization). For any other non-"business" entity_type, is_dynamic=True
    routes to _clean_members_dynamic, which dedups on `name_field` and applies
    role-based normalization (phone/url/email) using `field_roles`
    ({field_key: role}) instead of the fixed business keys.

    Operations (business):
    - Reject false-positive names (nav text, CTA, FAQ headings, etc.)
    - Deduplicate by company name (case-insensitive)
    - Normalize phone/fax to (XXX) XXX-XXXX format
    - Prefix bare domain websites with https://
    - Strip URL-slug categories
    - Deduplicate contacts by email within each card
    - Remove redundant mailing addresses that match street addresses
    """
    if entity_type == "person":
        return _clean_members_person(members)
    if is_dynamic:
        return _clean_members_dynamic(members, name_field, field_roles or {})

    seen_companies = set()
    cleaned = []
    dropped_false_positives = 0

    for m in members:
        # --- COMPANY NAME ---
        name = " ".join((m.get("company_name") or "").split())  # collapse whitespace
        if not name:
            continue  # skip entries with no company name
        # Drop label-only records ("Phone:", "Email:", "Website:", etc.)
        # that leak in when the regex fallback grabs <strong> labels.
        if _is_label_name(name):
            continue
        # Drop false-positive names ("Cities in Alabama", "Ready to Find Your Match?",
        # "Alaska HOA Laws & Regulations", etc.) that leak in when the parser scrapes
        # navigation / content sections as member cards.
        if _is_false_positive_name(name):
            dropped_false_positives += 1
            continue
        # Normalized dedup key collapses "Acme Corp" / "Acme Corp." /
        # "Acme Corporation" / "Acme, Corp" into a single bucket.
        # Phone is included in the key so chain locations (e.g. multiple
        # "Les Schwab Tire Center" branches) aren't conflated — same name
        # + different phone = different location → keep both.
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        phone_digits = re.sub(r'\D', '', m.get("phone") or "")
        dedup_key = f"{name_key}|{phone_digits}" if phone_digits else name_key
        if dedup_key in seen_companies:
            continue  # deduplicate
        seen_companies.add(dedup_key)
        m["company_name"] = name

        # --- PHONE / FAX ---
        for field in ["phone", "fax"]:
            val = m.get(field) or ""
            digits = re.sub(r'\D', '', val)
            if len(digits) == 10:
                m[field] = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            elif len(digits) == 11 and digits[0] == "1":
                m[field] = f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
            else:
                m[field] = val.strip() or None

        # --- WEBSITE ---
        website = m.get("website") or ""
        if website:
            if not website.startswith("http"):
                # Looks like a bare domain (e.g. "example.com")
                if re.match(r'^[\w.-]+\.[a-z]{2,}', website):
                    m["website"] = "https://" + website
                else:
                    m["website"] = None
            # else: already starts with http, keep as is

        # --- CATEGORY ---
        # Strip URL slugs like "/services/banks/l/55" - keep only real text labels
        category = m.get("category") or ""
        if category.startswith("/") or re.match(r'^https?://', category):
            m["category"] = None

        # --- CONTACTS ---
        contacts = m.get("contacts") or []
        seen_emails = set()
        clean_contacts = []
        for c in contacts:
            email = (c.get("email") or "").lower().strip()
            contact_name = " ".join((c.get("name") or "").split())
            if not email and not contact_name:
                continue  # skip empty contacts
            if email and email in seen_emails:
                continue  # skip duplicate emails
            if email:
                seen_emails.add(email)
            c["name"] = contact_name or None
            c["email"] = email or None
            clean_contacts.append(c)
        m["contacts"] = clean_contacts

        # --- ADDRESSES ---
        # If street and mailing are identical, clear mailing to avoid redundancy
        if m.get("street_address") and m.get("mailing_address"):
            if m["street_address"].strip() == m["mailing_address"].strip():
                m["mailing_address"] = None

        cleaned.append(m)

    if dropped_false_positives:
        print(f"  Cleaner: dropped {dropped_false_positives} false-positive name(s)")

    # Strip shared/poisoned emails — emails that appear across many
    # records (e.g. a referral contact address) are NOT per-company data.
    _prune_shared_emails(cleaned)

    return cleaned


def _clean_members_person(members: list) -> list:
    """Clean + dedup a "person" member list (rosters, faculty/team pages).

    Person-aware rules:
    - full_name that is a bare email address or URL is an extraction misfire → drop
    - dedup key is full_name + email, NOT name alone — two "John Smith"s with
      different emails are different people; pagination overlap (same name, same
      email) still collapses
    - email: strip mailto:, lowercase, keep only a well-formed address
    - personal_website: drop mailto:/tel: hrefs, prefix bare domains with https://
    - phone formatted like the business path
    Skips the business false-positive name heuristics (tuned for company
    directories) apart from the shared label-word check."""
    seen = set()
    cleaned = []
    dropped_email_names = 0

    for m in members:
        if not isinstance(m, dict):
            continue

        # --- FULL NAME ---
        name = _LINK_BOILERPLATE_RE.sub(" ", m.get("full_name") or "")
        name = " ".join(name.split())
        if not name:
            continue  # no identity → drop
        if _is_label_name(name):
            continue  # header rows: "Name", "Email", ...
        if _EMAIL_ONLY_RE.match(name) or name.lower().startswith(
                ("http://", "https://", "www.")):
            dropped_email_names += 1
            continue
        m["full_name"] = name

        # --- EMAIL ---
        email = (m.get("email") or "").strip()
        if email.lower().startswith("mailto:"):
            email = email[7:].split("?")[0].strip()
        email = email.lower()
        if email and not _EMAIL_ONLY_RE.match(email):
            # salvage an address from surrounding garbage, else discard
            em = _EMAIL_IN_TEXT_RE.search(email)
            email = em.group() if em else ""
        m["email"] = email or None

        # --- DEDUP (name + email) ---
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        key = f"{name_key}|{email}"
        if key in seen:
            continue
        seen.add(key)

        # --- PRONOUNS ---
        pronouns = " ".join((m.get("pronouns") or "").split()).strip("()[]")
        m["pronouns"] = pronouns or None

        # --- TITLE / DEPARTMENT / OFFICE ---
        for field in ("title", "department", "office"):
            if field in m:
                val = " ".join((m.get(field) or "").split())
                m[field] = val or None

        # --- PHONE ---
        val = m.get("phone") or ""
        digits = re.sub(r'\D', '', val)
        if len(digits) == 10:
            m["phone"] = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            m["phone"] = f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            m["phone"] = val.strip() or None

        # --- PERSONAL WEBSITE ---
        site = (m.get("personal_website") or "").strip()
        if site.lower().startswith(("mailto:", "tel:", "javascript:")):
            site = ""
        if site and not site.startswith("http"):
            site = "https://" + site if re.match(r'^[\w.-]+\.[a-z]{2,}', site) else ""
        m["personal_website"] = site or None

        cleaned.append(m)

    if dropped_email_names:
        print(f"  Cleaner: dropped {dropped_email_names} person record(s) whose "
              f"name was an email address or URL")

    return cleaned


def _clean_members_dynamic(members: list, name_field: str, field_roles: dict) -> list:
    """Clean + dedup a non-business (free-form, role-tagged) member list.

    Dedups on `name_field`, applies role-based normalization to the fields whose
    role is phone/url/email, and passes everything else through verbatim. Does NOT
    apply the business-specific false-positive name heuristics (those are tuned for
    company directories and would mislabel product/spec names)."""
    seen = set()
    cleaned = []
    for m in members:
        if not isinstance(m, dict):
            continue
        name = " ".join((m.get(name_field) or "").split())
        if not name:
            continue  # no identity → drop
        m[name_field] = name
        name_key = _normalize_name_key(name)
        if not name_key or name_key in seen:
            continue
        seen.add(name_key)

        for key, role in field_roles.items():
            val = m.get(key)
            if not val or not isinstance(val, str):
                continue
            role = (role or "").lower()
            if role == "phone":
                digits = re.sub(r'\D', '', val)
                if len(digits) == 10:
                    m[key] = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
                elif len(digits) == 11 and digits[0] == "1":
                    m[key] = f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
            elif role == "url":
                if not val.startswith("http") and re.match(r'^[\w.-]+\.[a-z]{2,}', val):
                    m[key] = "https://" + val
            elif role == "email":
                m[key] = val.strip().lower()

        cleaned.append(m)

    return cleaned


def is_extraction_garbage_dynamic(members: list, name_field: str,
                                  min_populated_ratio: float = 0.3,
                                  ignore_fields: set | None = None) -> bool:
    """Quality gate for a non-business extraction.

    Business `is_extraction_garbage` keys on contact data (phone/email/address),
    which products legitimately lack. Here "valid" means: most records have the
    identity field AND at least one other populated field. Returns True (garbage)
    when fewer than `min_populated_ratio` of records meet that bar.

    `ignore_fields` (main.py passes the url-role keys) never count as the
    "other populated field" — a record that is only name + link is scraped
    navigation (city/category link lists), not data."""
    if not members:
        return True
    ignore = ignore_fields or set()
    n = len(members)
    good = 0
    for m in members:
        if not isinstance(m, dict) or not m.get(name_field):
            continue
        has_extra = any(
            k != name_field and k not in ignore and v not in (None, "", [], {})
            for k, v in m.items()
        )
        if has_extra:
            good += 1
    if (good / n) < min_populated_ratio:
        print(f"  Cleaner: dynamic extraction is garbage — only {good}/{n} "
              f"records have identity + data ({good / n:.1%})")
        return True
    return False


def is_extraction_garbage_person(members: list) -> bool:
    """Quality gate for a "person" extraction.

    Same bar as the dynamic gate, keyed on full_name: most records must have
    an identity plus at least one other populated field (pronouns, title,
    email, ...). A list of bare names with nothing else is a scraped nav menu,
    not a roster — matching how the business gate treats name-only output."""
    return is_extraction_garbage_dynamic(members, "full_name")


def is_extraction_garbage(members: list, min_contact_ratio: float = 0.05) -> bool:
    """Check if cleaned member records are mostly garbage — names with
    no contact data, likely extracted from navigation/content sections
    rather than real directory listings.

    Returns True when fewer than `min_contact_ratio` of records have any
    contact info (phone, email, website, or address). Also returns True
    when the majority of names look like false positives.

    Used by main.py to detect failed extractions and invalidate cached
    selectors so future scrapes don't reuse bad selectors.
    """
    if not members:
        return True

    n = len(members)
    with_contact = sum(
        1 for m in members
        if m.get("phone")
        or m.get("website")
        or m.get("street_address")
        or m.get("mailing_address")
        or (m.get("contacts") and any(c.get("email") for c in m["contacts"]))
    )
    contact_ratio = with_contact / n

    # Check how many names still look like false positives (should have been
    # caught by _is_false_positive_name, but some slip through)
    still_false = sum(1 for m in members if _is_false_positive_name(m.get("company_name", "")))
    false_ratio = still_false / n

    if contact_ratio < min_contact_ratio:
        print(f"  Cleaner: extraction is garbage — only {with_contact}/{n} "
              f"records have contact data ({contact_ratio:.1%})")
        return True

    if false_ratio > 0.3:
        print(f"  Cleaner: extraction is garbage — {still_false}/{n} names "
              f"still look like false positives after cleaning ({false_ratio:.1%})")
        return True

    return False