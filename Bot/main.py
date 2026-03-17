"""
Directory Scraper — Main Entry Point

Usage:
    python main.py <url>
    python main.py https://www.someassociation.org

Pipeline:
    1. browser.py  → Navigate to directory, capture network responses
    2. detail_crawler.py → (optional) Crawl nested detail pages if data is shallow
    3. parser.py   → Extract member data from HTML using learned selectors
    4. cleaner.py  → Clean, normalize, deduplicate
    5. Save raw + structured JSON to Data-dump/
"""

import sys
import os
import json
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from browser import capture_responses
from html_parser import parse_member_html
from cleaner import clean_members
from detail_crawler import crawl_detail_pages


def normalize_json_member(raw: dict) -> dict:
    """Map common API field names to our standard schema.

    Different directory APIs use different keys:
      Name / CompanyName / company_name / name / nam → company_name
      MainPhone / Phone / phone / PhoneNumber → phone
      WebSite / Website / website / URL / url → website
    etc.

    Also handles APIs with nested address objects (e.g. adr: {ad1, cit, sta, zip})
    by flattening them into the top-level dict before field lookup.

    This normalizes them all so clean_members() works correctly.
    """
    # Flatten nested address/location dicts into top-level for field lookup
    # e.g. {"adr": {"ad1": "123 Main", "cit": "NYC"}} → {"ad1": "123 Main", "cit": "NYC", ...}
    flat = dict(raw)
    for key in ["adr", "address", "ShippingAddress"]:
        nested = raw.get(key)
        if isinstance(nested, dict):
            for nk, nv in nested.items():
                if nk not in flat:  # don't overwrite top-level keys
                    flat[nk] = nv
            break  # only flatten one address object

    def find_field(candidates: list, data: dict):
        """Return the value of the first matching key (case-insensitive)."""
        data_lower = {k.lower(): v for k, v in data.items()}
        for key in candidates:
            val = data_lower.get(key.lower())
            if val is not None:
                # Skip non-scalar values (dicts, lists) — those are nested objects, not field values
                if isinstance(val, (dict, list)):
                    continue
                return str(val).strip() if val else None
        return None

    # Phone: combine area code + number if split across fields
    phone = find_field(["MainPhone", "Phone", "PhoneNumber", "phone", "telephone", "tel"], flat)
    area_code = find_field(["PhoneAreaCode", "AreaCode", "areacode", "phone_area_code"], flat)
    if phone and area_code and not phone.startswith(area_code):
        phone = f"{area_code}-{phone}"

    # Fax: same treatment
    fax = find_field(["Fax", "FaxNumber", "fax", "fax_number"], flat)
    fax_area = find_field(["FaxAreaCode", "fax_area_code"], flat)
    if fax and fax_area and not fax.startswith(fax_area):
        fax = f"{fax_area}-{fax}"

    # Address: try to build from parts or use full string
    street = find_field(["Address", "StreetAddress", "street_address", "Address1", "AddressLine1",
                         "ShippingAddress1", "ad1"], flat)
    city = find_field(["City", "city", "ShippingCity", "cit"], flat)
    state = find_field(["State", "state", "StateProvince", "Province", "ShippingState", "sta"], flat)
    zipcode = find_field(["ZipCode", "Zip", "zip", "PostalCode", "postal_code", "zipcode",
                          "ShippingZip"], flat)

    # Build a combined street address if we have parts
    address_parts = [p for p in [street, city, state, zipcode] if p]
    full_address = ", ".join(address_parts) if address_parts else None

    # Email: capture top-level email into contacts
    email = find_field(["Email", "email", "EmailAddress", "email_address"], flat)
    contacts = []
    if email:
        contacts.append({"name": None, "email": email})

    return {
        "company_name":    find_field(["Name", "CompanyName", "company_name", "BusinessName",
                                       "OrganizationName", "name", "Title", "title", "nam"], flat),
        "description":     find_field(["Description", "description", "About", "about",
                                       "Bio", "bio", "Summary", "summary", "cnm"], flat),
        "category":        find_field(["Specialties", "Category", "category", "Type",
                                       "type", "Classification", "Industry",
                                       "specialty", "specialties"], flat),
        "website":         find_field(["WebSite", "Website", "website", "URL", "url",
                                       "Web", "web", "Homepage", "homepage"], flat),
        "phone":           phone,
        "fax":             fax,
        "street_address":  full_address,
        "mailing_address": find_field(["MailingAddress", "mailing_address", "Address2", "ad2"], flat),
        "contacts":        contacts,
    }


def is_member_list(data: list) -> bool:
    """Check if a JSON list looks like member/directory data.
    Must be a list of dicts with name-like fields."""
    if not data or not isinstance(data[0], dict):
        return False
    if len(data) < 3:
        return False
    # Check first few items for name-like keys
    name_keys = {"name", "companyname", "company_name", "businessname",
                 "organizationname", "title", "nam"}
    sample = data[:5]
    matches = 0
    for item in sample:
        item_keys = {k.lower() for k in item.keys()}
        if item_keys & name_keys:
            matches += 1
    if matches < len(sample) * 0.5:
        return False

    # Reject simple option/filter lists (e.g. {"Name":"Accounting","Value":405810})
    # Real member records have 5+ fields, not just name+value pairs
    avg_keys = sum(len(item.keys()) for item in sample) / len(sample)
    if avg_keys < 5:
        return False

    return True


def parse_and_save_results(results: list, data_dump_dir: str, domain: str,
                           detail_members: list | None = None) -> list:
    """Parse all captured responses, save both raw and structured data.

    Handles:
    - JSON list responses (e.g. /GetDirectoryBasicInfo returns [{...}, {...}, ...])
    - JSON dict responses with nested member lists (e.g. {"Status":"OK", "Members":[...]})
    - JSON dict responses (single member or config-like data)
    - Raw HTML responses (parse with selector learning strategy)
    - Pre-parsed detail page members (from detail_crawler)
    """
    all_members = []
    has_json_members = False

    # --- Include detail crawl results first (already parsed) ---
    if detail_members:
        all_members.extend(detail_members)
        print(f"Included {len(detail_members)} members from detail page crawl")

    for result in results:
        data = result.get("data", {})

        # --- JSON list of members (most common for API-based directories) ---
        if isinstance(data, list) and is_member_list(data):
            print(f"JSON member list from {result['url']}: {len(data)} entries")
            for item in data:
                normalized = normalize_json_member(item)
                if normalized.get("company_name"):
                    all_members.append(normalized)
            has_json_members = True

        # --- JSON dict (check for nested member list first, then single record) ---
        elif isinstance(data, dict) and "raw_html" not in data:
            # Check if any value in the dict is a member list
            nested_list = None
            nested_key = None
            for key, val in data.items():
                if isinstance(val, list) and len(val) >= 3 and is_member_list(val):
                    nested_list = val
                    nested_key = key
                    break

            if nested_list:
                print(f"JSON nested member list '{nested_key}' from {result['url']}: {len(nested_list)} entries")
                for item in nested_list:
                    normalized = normalize_json_member(item)
                    if normalized.get("company_name"):
                        all_members.append(normalized)
                has_json_members = True
            else:
                # Check if it looks like a single member record
                name_keys = {"name", "companyname", "company_name", "businessname"}
                data_keys_lower = {k.lower() for k in data.keys()}
                if data_keys_lower & name_keys:
                    normalized = normalize_json_member(data)
                    if normalized.get("company_name"):
                        all_members.append(normalized)
                        has_json_members = True
            # else: skip non-member JSON (config files, auth responses, etc.)

        # --- HTML response — parse with selector strategy ---
        elif isinstance(data, dict) and "raw_html" in data:
            # Skip HTML parsing if we already got good data from JSON or detail crawl
            if (has_json_members or detail_members) and len(all_members) >= 10:
                print(f"Skipping HTML parse (already have {len(all_members)} members)")
                continue
            print(f"Parsing HTML response from {result['url']}...")
            try:
                members = parse_member_html(data["raw_html"], domain=domain)
                print(f"  Extracted {len(members)} members")
                all_members.extend(members)
            except Exception as e:
                print(f"  Failed to parse: {e}")

    # Clean and deduplicate all members
    all_members = clean_members(all_members)

    # --- Sanity checks ---
    if len(all_members) < 3:
        print(f"WARNING: Only {len(all_members)} members extracted for {domain} — scrape likely failed")

    empty_names = sum(1 for m in all_members if not m.get("company_name"))
    if all_members and empty_names > len(all_members) * 0.3:
        print(
            f"WARNING: {empty_names}/{len(all_members)} members missing company name "
            f"in {domain} — extraction may be wrong"
        )

    # --- Save structured output ---
    structured_path = os.path.join(data_dump_dir, f"{domain}_structured.json")
    with open(structured_path, "w") as f:
        json.dump(all_members, f, indent=4)
    print(f"Saved {len(all_members)} structured members to {structured_path}")

    return all_members


def prompt_detail_crawl(detail_url_count: int) -> bool:
    """Ask the user whether to crawl nested detail pages.

    Called when the scraper detects that member data is shallow (names only)
    and detail page links exist that likely contain full contact info.

    Returns True if the user confirms.
    """
    print("\n" + "=" * 60)
    print("NESTED DETAIL PAGES DETECTED")
    print("=" * 60)
    print(f"  Found {detail_url_count} member profile links.")
    print(f"  The listing page only shows names — full details (phone,")
    print(f"  email, website, address) require visiting each profile page.")
    print()

    while True:
        answer = input(f"  Crawl all {detail_url_count} detail pages? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            print("  Skipping detail crawl.")
            return False
        print("  Please enter 'y' or 'n'.")


def scrape_directory(url: str) -> list:
    """Full pipeline: scrape a directory URL and return structured member data."""
    domain = urlparse(url).netloc.replace(".", "_")

    # Set up output directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    data_dump_dir = os.path.join(parent_dir, "Data-dump")
    os.makedirs(data_dump_dir, exist_ok=True)

    # --- Step 1: Browser automation — capture all responses ---
    with sync_playwright() as playwright:
        results, detail_urls = capture_responses(playwright, url)

    # --- Step 2: Save raw responses ---
    raw_output_path = os.path.join(data_dump_dir, f"{domain}.json")
    print(f"Saving {len(results)} raw responses to {raw_output_path}")
    with open(raw_output_path, "w") as f:
        json.dump(results, f, indent=4)

    # --- Step 3: (Optional) Crawl nested detail pages ---
    detail_members = []
    if detail_urls:
        if prompt_detail_crawl(len(detail_urls)):
            detail_members = crawl_detail_pages(detail_urls, domain)

            # Save detail crawl results separately for debugging
            if detail_members:
                detail_path = os.path.join(data_dump_dir, f"{domain}_detail_raw.json")
                with open(detail_path, "w") as f:
                    json.dump(detail_members, f, indent=4)
                print(f"Saved {len(detail_members)} detail members to {detail_path}")

    # --- Step 4: Parse, clean, and save structured data ---
    members = parse_and_save_results(results, data_dump_dir, domain,
                                     detail_members=detail_members)

    return members


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <url>")
        print("Example: python main.py https://www.someassociation.org")
        sys.exit(1)

    url = sys.argv[1]
    print(f"Scraping directory: {url}")
    print("=" * 60)

    members = scrape_directory(url)

    print("=" * 60)
    print(f"Done! Extracted {len(members)} members")

    # Print a quick summary
    if members:
        with_phone = sum(1 for m in members if m.get("phone"))
        with_email = sum(1 for m in members if m.get("contacts") and any(c.get("email") for c in m["contacts"]))
        with_website = sum(1 for m in members if m.get("website"))
        print(f"  With phone:   {with_phone}")
        print(f"  With email:   {with_email}")
        print(f"  With website: {with_website}")


if __name__ == "__main__":
    main()