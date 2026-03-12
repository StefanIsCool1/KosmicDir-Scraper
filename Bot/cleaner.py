"""
Data cleaning and normalization.
Runs AFTER extraction — completely separate from scraping/parsing logic.
Handles: deduplication, phone formatting, website normalization, address cleanup.
"""

import re


def clean_members(members: list) -> list:
    """Clean and deduplicate extracted member data.
    
    Operations:
    - Deduplicate by company name (case-insensitive)
    - Normalize phone/fax to (XXX) XXX-XXXX format
    - Prefix bare domain websites with https://
    - Strip URL-slug categories
    - Deduplicate contacts by email within each card
    - Remove redundant mailing addresses that match street addresses
    """
    seen_companies = set()
    cleaned = []

    for m in members:
        # --- COMPANY NAME ---
        name = " ".join((m.get("company_name") or "").split())  # collapse whitespace
        if not name:
            continue  # skip entries with no company name
        name_key = name.lower().strip()
        if name_key in seen_companies:
            continue  # deduplicate
        seen_companies.add(name_key)
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

    return cleaned