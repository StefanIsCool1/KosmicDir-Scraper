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

from _pw import sync_playwright
from browser import capture_responses, sanitize_results_for_dump
from html_parser import parse_member_html, apply_selectors
from cleaner import (
    clean_members, is_extraction_garbage, is_extraction_garbage_dynamic,
    is_extraction_garbage_person,
)
from detail_crawler import crawl_detail_pages
from cache import delete_cached_selectors, get_cached_selectors
from config import (
    PHASE2_RECONCILIATION, COUNT_GATE_RATIO, COUNT_GATE_CLAMP_FACTOR,
    NAME_ONLY_CRAWL_RATIO,
)
from debug import debug
import archetype

# Fields that can only be found via Phase 2 (website enrichment), not detail pages.
PHASE2_ONLY_FIELDS = {"social_media"}


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
    # Handle Airtable format: {"id": "recXYZ", "fields": {"Name": "...", "Phone": "..."}}
    # Unwrap the "fields" dict so the rest of the function can find the real data.
    if "fields" in raw and isinstance(raw["fields"], dict) and "id" in raw:
        raw = raw["fields"]

    # Handle Procore format: addresses is a list of address objects
    if "addresses" in raw and isinstance(raw.get("addresses"), list) and raw["addresses"]:
        addr = raw["addresses"][0]
        if isinstance(addr, dict):
            raw = {**raw, **{k: v for k, v in addr.items() if k not in raw}}

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

    # Handle address arrays (e.g. Procore: "addresses": [{"address1": "...", "city": "...", ...}])
    # Flatten the primary (or first) address dict into top-level
    for key in ["addresses", "Addresses", "locations", "Locations"]:
        nested_list = raw.get(key)
        if isinstance(nested_list, list) and nested_list:
            # Prefer the primary address, fall back to first
            addr = next((a for a in nested_list if isinstance(a, dict) and a.get("primary")), None)
            if not addr:
                addr = nested_list[0] if isinstance(nested_list[0], dict) else None
            if addr:
                for nk, nv in addr.items():
                    if nk not in flat:
                        flat[nk] = nv
            break

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
                         "ShippingAddress1", "ad1", "address1"], flat)
    city = find_field(["City", "city", "ShippingCity", "cit", "locality"], flat)
    state = find_field(["State", "state", "StateProvince", "Province", "ShippingState", "sta",
                        "province", "countryCode"], flat)
    zipcode = find_field(["ZipCode", "Zip", "zip", "PostalCode", "postal_code", "zipcode",
                          "ShippingZip", "postalCode1", "postalcode1"], flat)

    # Build a combined street address if we have parts
    address_parts = [p for p in [street, city, state, zipcode] if p]
    full_address = ", ".join(address_parts) if address_parts else None

    # Email: capture top-level email into contacts
    email = find_field(["Email", "email", "EmailAddress", "email_address"], flat)
    contacts = []
    if email:
        contacts.append({"name": None, "email": email})

    normalized = {
        "company_name":    find_field(["Name", "CompanyName", "company_name", "BusinessName",
                                       "OrganizationName", "name", "Title", "title", "nam",
                                       "DisplayName", "ProviderName", "PracticeName",
                                       "FirmName", "RestaurantName", "DoctorName",
                                       "AttorneyName", "OfficeName", "FullName",
                                       "EntityName", "displayName", "fullName",
                                       "full_name"], flat),
        "description":     find_field(["Description", "description", "About", "about",
                                       "Bio", "bio", "Summary", "summary", "cnm",
                                       "Overview", "overview", "Details", "details"], flat),
        "category":        find_field(["Specialties", "Category", "category", "Type",
                                       "type", "Classification", "Industry",
                                       "specialty", "specialties",
                                       "Cuisine", "cuisine", "CuisineType",
                                       "PracticeArea", "practiceArea", "Discipline",
                                       "Department", "ServiceArea", "Services"], flat),
        "website":         find_field(["WebSite", "Website", "website", "URL", "url",
                                       "Web", "web", "Homepage", "homepage",
                                       "PersonalWebsite", "personal_website",
                                       "personalWebsite", "PersonalURL"], flat),
        "phone":           phone,
        "fax":             fax,
        "street_address":  full_address,
        "mailing_address": find_field(["MailingAddress", "mailing_address", "Address2", "ad2"], flat),
        "contacts":        contacts,
    }

    # Person-directory aliases: attached only when the API actually carries
    # them, so business records keep their exact 9-key shape.
    pronouns = find_field(["Pronouns", "pronouns", "PreferredPronouns",
                           "preferred_pronouns", "preferredPronouns"], flat)
    if pronouns:
        normalized["pronouns"] = pronouns

    return normalized


def is_member_list(data: list) -> bool:
    """Check if a JSON list looks like member/directory data.
    Must be a list of dicts with name-like fields."""
    if not data or not isinstance(data[0], dict):
        return False
    if len(data) < 3:
        return False
    # Check first few items for name-like keys
    name_keys = {"name", "companyname", "company_name", "businessname",
                 "organizationname", "title", "nam", "displayname",
                 "providername", "practicename", "firmname",
                 "restaurantname", "doctorname", "fullname", "full_name",
                 "entityname", "officename", "attorneyname"}
    sample = data[:5]
    matches = 0
    for item in sample:
        item_keys = {k.lower() for k in item.keys()}
        # Direct match — name key at top level
        if item_keys & name_keys:
            matches += 1
        # Airtable format — name key inside "fields" dict
        elif "fields" in item_keys and isinstance(item.get("fields"), dict):
            field_keys = {k.lower() for k in item["fields"].keys()}
            if field_keys & name_keys:
                matches += 1
    if matches < len(sample) * 0.5:
        return False

    # Reject simple option/filter lists (e.g. {"Name":"Accounting","Value":405810})
    # Real member records have 5+ fields, not just name+value pairs.
    # For Airtable format, count keys inside "fields" instead of top-level.
    def _effective_key_count(item):
        if isinstance(item.get("fields"), dict):
            return len(item["fields"])
        return len(item)
    avg_keys = sum(_effective_key_count(item) for item in sample) / len(sample)
    if avg_keys < 5:
        return False

    return True


def parse_and_save_results(results: list, data_dump_dir: str, domain: str,
                           detail_members: list | None = None,
                           intent: dict | None = None,
                           source_url: str = "") -> tuple[list, dict | None]:
    """Parse all captured responses, save both raw and structured data.

    Handles:
    - JSON list responses (e.g. /GetDirectoryBasicInfo returns [{...}, {...}, ...])
    - JSON dict responses with nested member lists (e.g. {"Status":"OK", "Members":[...]})
    - JSON dict responses (single member or config-like data)
    - Raw HTML responses (parse with selector learning strategy)
    - Pre-parsed detail page members (from detail_crawler)

    Returns (members, count_gate_verdict): the verdict is None when the
    scrape reconciles against the site's stated total (or no total exists),
    else {"expected": E, "extracted": N} — mirrored into metadata as
    partial=true + expected_count (Phase 2, R3).
    """
    all_members = []
    has_json_members = False
    zero_yield_htmls = []

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
                name_keys = {"name", "companyname", "company_name", "businessname",
                             "displayname", "providername", "practicename",
                             "firmname", "restaurantname", "doctorname",
                             "fullname", "full_name", "entityname", "officename"}
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
                if members:
                    all_members.extend(members)
                else:
                    zero_yield_htmls.append(data["raw_html"])
            except Exception as e:
                print(f"  Failed to parse: {e}")

    # --- Second pass: recover pages parsed before selectors were learned ---
    # A category/hub run learns the schema mid-iteration (on the first page
    # with enough cards to validate). Pages parsed before that — e.g. one-store
    # city pages, which can't meet the ≥3-record validation bar on their own —
    # yielded 0. Re-apply the final cached selectors to them (pure BS4, no AI).
    # Tiny per-page yields are fine here: the schema already validated
    # elsewhere, and the garbage gate below still sees the full population.
    if zero_yield_htmls:
        _final_sel = get_cached_selectors(domain)
        if _final_sel:
            recovered = 0
            for html in zero_yield_htmls:
                try:
                    extra = [m for m in apply_selectors(html, _final_sel)
                             if isinstance(m, dict)]
                except Exception:
                    continue
                recovered += len(extra)
                all_members.extend(extra)
            if recovered:
                print(f"  Second pass: recovered {recovered} members from "
                      f"{len(zero_yield_htmls)} zero-yield page(s) using final selectors")
                debug.log("PARSE", f"Second pass recovered {recovered} members "
                          f"from {len(zero_yield_htmls)} zero-yield pages")

    # Determine the detected schema for this domain (set during selector learning).
    # Defaults to the business schema when absent — legacy cache entries, regex-only
    # extractions, and JSON-API paths all stay on the unchanged business path.
    # "person" (rosters, faculty/team pages) is a fixed schema keyed on full_name;
    # any other non-business type is the free-form dynamic schema.
    _sel = get_cached_selectors(domain) or {}
    entity_type = (_sel.get("entity_type") or "business")
    is_person = entity_type == "person"
    name_field = _sel.get("name_field") or ("full_name" if is_person else "company_name")
    is_dynamic = entity_type not in ("business", "person")
    field_roles = (
        {f["key"]: (f.get("role") or "other")
         for f in _sel.get("fields", []) if isinstance(f, dict) and f.get("key")}
        if is_dynamic else None
    )

    # Raw pre-dedup yield is extraction-side evidence for the count gate's
    # marketing-copy clamp (what the walked pages actually carried).
    archetype.note_observed(len(all_members))

    # Clean and deduplicate all members
    all_members = clean_members(all_members, name_field=name_field,
                                is_dynamic=is_dynamic, field_roles=field_roles,
                                entity_type=entity_type)

    # --- Quality gate: reject garbage extractions ---
    # When the extractor scrapes navigation / content sections (not real
    # member records), every "member" lacks data. Detect this and invalidate the
    # cached selectors so future scrapes don't reuse them. Business keys on contact
    # data; the person and dynamic gates key on identity + at least one other
    # populated field.
    if is_person:
        garbage = is_extraction_garbage_person(all_members)
    elif is_dynamic:
        # URL-role fields aren't data — a record that is only name + link is
        # navigation (see the link-list guards in html_parser).
        url_keys = {k for k, r in (field_roles or {}).items()
                    if (r or "").lower() == "url"}
        garbage = is_extraction_garbage_dynamic(all_members, name_field,
                                                ignore_fields=url_keys)
    else:
        garbage = is_extraction_garbage(all_members)
    if garbage:
        print(f"WARNING: Extraction appears to be garbage for {domain} — "
              f"purging cached selectors and returning 0 members")
        debug.decision("CLEAN", "extraction rejected as garbage",
                       "records lack contact/identity data — cached selectors purged",
                       data={"members_before_rejection": len(all_members)})
        delete_cached_selectors(domain)
        return [], None

    # Count gate reconciles the CLEANED, pre-intent count against the site's
    # stated total — intent narrowing drops records deliberately, and the
    # site total counts all of them.
    cleaned_total = len(all_members)
    expected, observed = archetype.run_count_evidence()
    verdict = count_gate_verdict(cleaned_total, expected, observed)

    # --- Intent filter (Agent mode only) ---
    # Trim the validated members to the user's actual target — e.g. deck
    # builders, not every trade listed in a general builders association.
    # No-op when intent is None (Playground Direct/Auto/CSV paths). Runs after
    # the garbage gate so junk detection still sees the full population, and
    # is fail-open so a flaky classifier never silently empties a real scrape.
    intent_dropped = 0
    if intent:
        from intent_record_filter import filter_records_by_intent
        pre_intent = len(all_members)
        all_members = filter_records_by_intent(all_members, intent)
        intent_dropped = pre_intent - len(all_members)

    # --- Sanity checks ---
    if len(all_members) < 3:
        print(f"WARNING: Only {len(all_members)} members extracted for {domain} — scrape likely failed")

    empty_names = sum(1 for m in all_members if not m.get(name_field))
    if all_members and empty_names > len(all_members) * 0.3:
        print(
            f"WARNING: {empty_names}/{len(all_members)} members missing {name_field} "
            f"in {domain} — extraction may be wrong"
        )

    # --- Save structured output ---
    structured_path = os.path.join(data_dump_dir, f"{domain}_structured.json")

    # Compute metadata (shared shape with Phase 2 enrichment — see compute_metadata)
    total = len(all_members)
    metadata = compute_metadata(all_members, source_url=source_url, intent=intent,
                                entity_type=entity_type, name_field=name_field,
                                **({"intent_dropped": intent_dropped} if intent else {}))
    if verdict:
        # Additive fields — every existing reader of the metadata block is
        # untouched when the scrape reconciles.
        metadata["partial"] = True
        metadata["expected_count"] = verdict["expected"]
        print(f"  PARTIAL: extracted {verdict['extracted']} of a stated "
              f"{verdict['expected']} total")

    with open(structured_path, "w") as f:
        json.dump({"metadata": metadata, "members": all_members}, f, indent=4)
    print(f"Saved {total} structured members to {structured_path}")

    return all_members, verdict


def read_members(json_path: str) -> list:
    """Read members from a structured or enriched JSON file.

    Handles both formats:
      - New:  {"metadata": {...}, "members": [...]}
      - Old:  [...]  (plain list, no metadata)
    Returns the member list in both cases.
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "members" in data:
        return data["members"]
    return []


def read_metadata(json_path: str) -> dict | None:
    """Read metadata from a structured or enriched JSON file.

    Returns the metadata dict, or None if the file is old-format (plain list).
    """
    with open(json_path, "r") as f:
        data = json.load(f)
    if isinstance(data, dict) and "metadata" in data:
        return data["metadata"]
    return None


def compute_metadata(members: list, source_url: str = "", intent: dict | None = None,
                     entity_type: str = "business", name_field: str = "company_name",
                     **extra) -> dict:
    """Build the standard coverage-metadata block for a member list.

    Shared by Phase 1 (structured dumps) and Phase 2 (enriched dumps) so both
    files carry the same shape. Counts are computed over `members` as given, so
    when Phase 2 passes its enriched list the numbers reflect post-enrichment
    coverage. `extra` is merged last, so a caller can add fields (e.g.
    enriched_at) or override defaults like scraped_at.

    For a non-"business" entity_type the named business counts don't apply, so the
    block instead carries `entity_type`, `name_field`, and a generic per-field
    `field_coverage` map. The business branch is left byte-for-byte unchanged.
    """
    from datetime import datetime, timezone
    if entity_type != "business":
        keys: list = []
        for m in members:
            if isinstance(m, dict):
                for k in m.keys():
                    if k not in keys:
                        keys.append(k)
        metadata = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "entity_type": entity_type,
            "name_field": name_field,
            "total_members": len(members),
            "with_name": sum(1 for m in members if m.get(name_field)),
            "field_coverage": {k: sum(1 for m in members if m.get(k)) for k in keys},
        }
        if intent:
            # intent is the FLATTENED dict from intent_from_plan — keys are
            # industry_canonical / location_states (already a list of state
            # strings), NOT the plan's industry.canonical / locations[].state.
            metadata["intent_industry"] = intent.get("industry_canonical") or ""
            metadata["intent_locations"] = list(intent.get("location_states") or [])
        metadata.update(extra)
        return metadata

    metadata = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "total_members": len(members),
        "with_name": sum(1 for m in members if m.get("company_name")),
        "with_phone": sum(1 for m in members if m.get("phone")),
        "with_email": sum(1 for m in members
                          if m.get("contacts") and any(c.get("email") for c in m["contacts"])),
        "with_website": sum(1 for m in members if m.get("website")),
        "with_address": sum(1 for m in members
                            if m.get("street_address") or m.get("mailing_address")),
        "with_description": sum(1 for m in members if m.get("description")),
        "with_category": sum(1 for m in members if m.get("category")),
        "with_contacts": sum(1 for m in members
                             if m.get("contacts") and any(
                                 c.get("name") or c.get("email") for c in m["contacts"])),
    }
    if intent:
        metadata["intent_industry"] = intent.get("canonical") or ""
        metadata["intent_locations"] = [
            loc.get("state", "") for loc in (intent.get("locations") or [])
        ]
    metadata.update(extra)
    return metadata


def count_gate_verdict(cleaned_count: int, expected: int | None,
                       observed: int = 0) -> dict | None:
    """Count gate (UNIVERSALITY_PLAN Phase 2, R3): decide whether a finished
    parse is PARTIAL against the site's stated total.

    Returns {"expected": E, "extracted": N} when the cleaned count falls
    below COUNT_GATE_RATIO x the stated total, else None (gate doesn't
    apply: flag off, no numeric total ("all"/unknown fall open — never gate
    sites that show no count), a failed scrape (<3 records — re-driving
    garbage reproduces garbage), or a stated total the sanity clamp rejects).

    The clamp: read_result_count takes the largest anchored match over full
    page text, so marketing copy ("one of 5,000 members nationwide") can
    inflate the expected total. When it exceeds COUNT_GATE_CLAMP_FACTOR x
    every piece of extraction-side evidence (`observed` = best of live
    rendered counts and raw parse yields), degrade to unknown instead of
    flagging partial and re-driving for nothing."""
    if not PHASE2_RECONCILIATION:
        return None
    if not isinstance(expected, int) or expected <= 0:
        return None
    if cleaned_count < 3:
        return None
    evidence = max(observed, cleaned_count)
    if expected > COUNT_GATE_CLAMP_FACTOR * evidence:
        debug.decision("CLEAN", "count gate: stated total rejected",
                       f"claimed {expected} is >{COUNT_GATE_CLAMP_FACTOR}x the "
                       f"extraction evidence ({evidence}) — treating as unknown",
                       data={"expected": expected, "evidence": evidence})
        return None
    if cleaned_count >= COUNT_GATE_RATIO * expected:
        return None
    return {"expected": expected, "extracted": cleaned_count}


def _name_only_ratio(members: list, domain: str) -> float:
    """Share of records carrying a name but NO contact data — the shape of
    a link-index roster (contacts live on profile pages). Contact data =
    phone / email / address (business), the person data fields, or any
    non-identity, non-url field (dynamic) — website/category alone don't
    count, since a detail crawl is exactly what fills the rest in (R4)."""
    if not members:
        return 0.0
    sel = get_cached_selectors(domain) or {}
    entity_type = sel.get("entity_type") or "business"
    name_field = sel.get("name_field") or (
        "full_name" if entity_type == "person" else "company_name")
    url_keys = {f["key"] for f in sel.get("fields") or []
                if isinstance(f, dict) and f.get("key")
                and (f.get("role") or "").lower() == "url"}

    def _has_contact_data(m: dict) -> bool:
        if entity_type == "business":
            if m.get("phone") or m.get("street_address") or m.get("mailing_address"):
                return True
            return any(isinstance(c, dict) and (c.get("email") or c.get("name"))
                       for c in m.get("contacts") or [])
        if entity_type == "person":
            return any(m.get(f) for f in ("phone", "email", "title",
                                          "department", "office", "pronouns"))
        return any(v for k, v in m.items()
                   if k != name_field and k not in url_keys and k != "source_url")

    name_only = sum(1 for m in members
                    if isinstance(m, dict) and m.get(name_field)
                    and not _has_contact_data(m))
    return name_only / len(members)


def _detect_login_wall(results: list) -> bool:
    """Check if the captured HTML contains a login/authentication wall.

    Only called when 0 members were extracted — this is the key guard
    against false positives. Sites with public directories that ALSO have
    a login portal will have already returned member data by this point.

    Requires MULTIPLE login signals to trigger (not just one "login" link
    in the nav). A real login wall has password fields + login-specific text
    concentrated together.
    """
    for result in results:
        data = result.get("data", {})
        if not isinstance(data, dict) or "raw_html" not in data:
            continue

        html_lower = data["raw_html"].lower()

        # Must have a password field — strongest single signal
        has_password = 'type="password"' in html_lower or "type='password'" in html_lower
        if not has_password:
            continue

        # Count additional login signals (need 2+ besides password field)
        signals = 0
        login_phrases = [
            "sign in", "log in", "login", "username",
            "members only", "member login", "member sign in",
            "forgot password", "forgot your password",
            "click here for login", "portal login",
        ]
        for phrase in login_phrases:
            if phrase in html_lower:
                signals += 1

        # Require password field + at least 2 login phrases
        if signals >= 2:
            return True

    return False


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


def _login_interactive(page, domain: str) -> bool:
    """Interactive login handler for gated directories.

    A browser window is already open showing the login page.  The user
    logs in manually in that window, then presses Enter here to continue.
    Cookies are saved automatically after login by capture_responses.

    Returns True if the user logged in and wants to retry the scrape,
    False to skip this directory entirely.
    """
    print(f"\n  A browser window should be open showing the login page.")
    print(f"\n  → Log in manually in the browser window.")
    print(f"  → Navigate to the directory/search page after logging in.")
    print(f"  → Press Enter here to continue scraping.")
    print(f"  → Or type 'skip' to abandon this directory.\n")

    while True:
        answer = input("  Press Enter when logged in, or type 'skip': ").strip().lower()
        if answer == "":
            print("  Continuing scrape with authenticated session...")
            return True
        if answer == "skip":
            print("  Skipping this directory.")
            return False
        print("  Press Enter to continue or type 'skip'.")


def _check_fields_from_raw(results: list) -> set:
    """Quick-check which fields exist in raw captured JSON responses.
    Looks at the first few JSON member records without full parsing."""
    fields = {"name"}
    found_keys = set()

    for result in results:
        data = result.get("data", {})
        records = []
        if isinstance(data, list) and len(data) >= 3:
            records = data[:10]
        elif isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list) and len(val) >= 3:
                    records = val[:10]
                    break
        for record in records:
            if isinstance(record, dict):
                found_keys.update(k.lower().replace("_", "") for k in record.keys())

    # Map raw JSON keys to our priority field names
    if found_keys & {"phone", "mainphone", "phonenumber", "telephone"}:
        fields.add("phone")
    if found_keys & {"email", "emailaddress", "contactemail"}:
        fields.add("email")
    if found_keys & {"streetaddress", "address", "mailingaddress", "street", "city"}:
        fields.add("address")
    if found_keys & {"description", "about", "bio", "summary"}:
        fields.add("description")
    if found_keys & {"website", "url", "web", "homepage", "websiteurl"}:
        fields.add("website")

    return fields


def _check_fields(members: list) -> set:
    """Check which data fields are present across the member list (sample of first 20)."""
    fields = {"name"}
    if not members:
        return fields
    sample = members[:20]
    if any(m.get("phone") for m in sample):
        fields.add("phone")
    if any(c.get("email") for m in sample for c in m.get("contacts", [])):
        fields.add("email")
    if any(m.get("street_address") or m.get("mailing_address") for m in sample):
        fields.add("address")
    if any(m.get("description") for m in sample):
        fields.add("description")
    if any(m.get("website") for m in sample):
        fields.add("website")
    return fields


def scrape_directory(url: str, prompt_callback=None, mode: str = "auto",
                     priority_fields: list | None = None,
                     intent: dict | None = None,
                     is_aggregator: bool = False,
                     login_callback=None,
                     captcha_callback=None,
                     landing_hint: str | None = None,
                     live_session_id: str | None = None,
                     crawl_all: bool = False) -> list:
    """Full pipeline: scrape a directory URL and return structured member data.

    Args:
        url: The directory URL to scrape.
        prompt_callback: Optional callback for interactive prompts (e.g. detail crawl y/n).
                         If None, falls back to terminal input() for CLI usage.
                         Signature: prompt_callback(detail_url_count, message=None) -> bool
        login_callback: Optional callable(page, domain) -> bool for login walls.
                        If None, falls back to the terminal input() handler —
                        which HANGS in server contexts (Flask/SSE) because
                        nobody is at the server's stdin. app.py passes a
                        frontend-prompt handler (Playground) or an auto-skip
                        (Agent batch mode).
        captcha_callback: Optional callable(page, domain, vendor) -> bool for
                        anti-bot challenges (DataDome press-and-hold, Cloudflare,
                        hCaptcha, reCAPTCHA). Pauses so a human can solve it in
                        the headed browser window, then resumes. If None, the
                        challenge is logged and skipped (batch/unattended runs).
        mode: "auto" = find directory page + search (default)
              "direct" = skip navigation/search, scrape the page as-is
        priority_fields: List of field names the user wants (e.g. ["email", "phone", "address"]).
                         Used to make smarter detail crawl decisions.
        intent: Optional dict from intent_filter.intent_from_plan. Only the
                Agent (/discover) entry point sets this. Forwarded to the
                browser/navigator so the AI picks intent-relevant links and
                the category iterator only walks matching tabs.
        is_aggregator: True when Phase 0 classified this URL as a cross-vertical
                       business aggregator (SuperPages, YellowPages, BBB, etc.).
                       Combined with `intent`, makes the search box use the
                       industry term instead of a wildcard. Defaults to False.
        landing_hint: Absolute same-site URL of a likely directory sub-page,
                      found by Phase 0's classifier on the landing page
                      (e.g. the "/member-directory" link). Auto mode starts the
                      AI navigation from this page instead of re-deriving the
                      first hop from the homepage. Ignored in direct mode;
                      fail-open if it doesn't load. Only /discover sets this.
        live_session_id: The scrape's SSE session id, when the caller registered
                      it with Bot/live_view. Binds the browser page to the Live
                      View stream so the frontend can watch it and take control
                      during a CAPTCHA/login pause. None (Playground batch, CLI)
                      disables live view entirely — a pure no-op.
        crawl_all: Crawl every detected detail page unconditionally, skipping
                      the priority-field/shallow-data gates (the y/n prompt is
                      never shown). /discover sets this when the user selected
                      no priority fields — an empty selection means "give me
                      everything", not "nothing is missing".
    """
    if priority_fields is None:
        priority_fields = []

    domain = urlparse(url).netloc.replace(".", "_")

    # Set up output directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    data_dump_dir = os.path.join(parent_dir, "Data-dump")
    os.makedirs(data_dump_dir, exist_ok=True)

    # Per-scrape debug trace: entries restart here so each site gets its own
    # timeline; saved to Debug-dump/{domain}_debug.json in the finally below.
    if debug.enabled:
        debug.reset()
        debug.log("BROWSER", f"Scrape started: {url}", data={
            "mode": mode, "priority_fields": priority_fields,
            "intent": bool(intent), "is_aggregator": is_aggregator,
            "landing_hint": landing_hint, "crawl_all": crawl_all,
        })

    # Run boundary for the profile cache + count evidence (expected totals
    # and observed counts must not leak between sites in one process).
    archetype.reset()

    def _run_capture():
        """One full browser capture pass. Also the count gate's re-drive:
        re-running the capture re-walks pagination and XHR replay with the
        selector cache warm and the count evidence already accumulated."""
        with sync_playwright() as playwright:
            return capture_responses(
                playwright, url, mode=mode,
                priority_fields=priority_fields,
                login_callback=login_callback or _login_interactive,
                captcha_callback=captcha_callback,
                intent=intent,
                is_aggregator=is_aggregator,
                landing_hint=landing_hint,
                live_session_id=live_session_id,
                crawl_all=crawl_all,
            )

    try:
        # --- Step 1: Browser automation — capture all responses ---
        with debug.span("BROWSER", "browser capture (navigate/search/paginate)"):
            results, detail_urls = _run_capture()
        return _finish_scrape(url, domain, data_dump_dir, results, detail_urls,
                              prompt_callback, priority_fields, intent,
                              redrive_fn=_run_capture, crawl_all=crawl_all)
    finally:
        if debug.enabled:
            debug_dump_dir = os.path.join(parent_dir, "Debug-dump")
            debug.save_report(os.path.join(debug_dump_dir, f"{domain}_debug.json"))


def _finish_scrape(url: str, domain: str, data_dump_dir: str, results: list,
                   detail_urls: list, prompt_callback, priority_fields: list,
                   intent: dict | None, redrive_fn=None,
                   crawl_all: bool = False) -> list:
    """Steps 2-5 of scrape_directory: save raw, parse, reconcile counts,
    optional detail crawl, warn on empty. Split out so scrape_directory can
    wrap the whole pipeline in one try/finally that saves the debug trace
    even on errors.

    Phase 2 reordering: the parse now runs BEFORE the detail-crawl decision
    — both the count gate (extracted vs stated total) and the completeness
    gate (name-only records) need per-record evidence that only exists
    after a parse. When a crawl then runs, the parse re-runs with the
    detail members merged in (cheap: selectors are cached by then).
    `redrive_fn() -> (results, detail_urls)` re-runs the browser capture;
    it is invoked at most ONCE, when the count gate flags a shortfall."""
    # --- Step 2: Save raw responses ---
    # Credential exclusion (Phase 3, non-negotiable): the interactive login
    # flow runs while capture is live, so a login POST's member-shaped
    # response must never be persisted. sanitize_results_for_dump drops any
    # auth-shaped entry before it reaches Data-dump/ — belt-and-braces for
    # the capture-time gate in browser._admit_json_capture.
    raw_output_path = os.path.join(data_dump_dir, f"{domain}.json")
    print(f"Saving {len(results)} raw responses to {raw_output_path}")
    with open(raw_output_path, "w") as f:
        json.dump(sanitize_results_for_dump(results), f, indent=4)

    # --- Step 3: Parse, clean, and save structured data ---
    with debug.span("PARSE", "parse + clean + save structured data"):
        members, verdict = parse_and_save_results(results, data_dump_dir, domain,
                                                  intent=intent,
                                                  source_url=url)

    # --- Step 3.5: Count gate re-drive (Phase 2, R3) — at most once ---
    if verdict and redrive_fn is not None:
        print(f"  Count gate: {verdict['extracted']} extracted vs stated "
              f"{verdict['expected']} — re-driving pagination/XHR replay once")
        debug.decision("CLEAN", "count gate: partial extraction — re-driving",
                       f"{verdict['extracted']} < "
                       f"{COUNT_GATE_RATIO:.0%} of {verdict['expected']}",
                       data=dict(verdict))
        more_results, more_detail_urls = [], []
        try:
            with debug.span("BROWSER", "count-gate re-drive capture"):
                more_results, more_detail_urls = redrive_fn()
        except Exception as e:
            print(f"  Re-drive failed (keeping first-pass results): {e}")
            debug.log("BROWSER", f"re-drive failed: {e}", level="error")
        if more_results:
            results = results + more_results
            detail_urls = list(dict.fromkeys([*detail_urls, *more_detail_urls]))
            with open(raw_output_path, "w") as f:
                json.dump(sanitize_results_for_dump(results), f, indent=4)
            with debug.span("PARSE", "re-parse after re-drive"):
                members, verdict = parse_and_save_results(
                    results, data_dump_dir, domain,
                    intent=intent, source_url=url)

    # --- Step 4: (Optional) Crawl nested detail pages ---
    # Quick-check what fields are available in captured JSON (without full parse)
    found_fields = _check_fields_from_raw(results)
    # Exclude phase2-only fields from detail crawl decisions — detail pages can't provide them
    crawl_relevant = set(priority_fields) - PHASE2_ONLY_FIELDS if priority_fields else set()
    missing_for_crawl = crawl_relevant - found_fields if crawl_relevant else set()

    # Completeness gate (Phase 2, R4): the raw-JSON field check above sees
    # field PRESENCE anywhere in captured responses, not per-record coverage
    # — a link-index roster (names only, contacts on profile pages) sails
    # past it. Per-record evidence from the parse closes that hole.
    name_only = _name_only_ratio(members, domain) if PHASE2_RECONCILIATION else 0.0
    completeness_trigger = bool(
        detail_urls and members and name_only >= NAME_ONLY_CRAWL_RATIO)

    detail_members = []
    if detail_urls:
        should_crawl = False

        if crawl_all:
            # No priority fields selected = the user wants everything —
            # crawl unconditionally, no field-gap gating, no prompt.
            print(f"  Crawl-all: no priority fields selected — crawling "
                  f"all {len(detail_urls)} detail pages")
            debug.decision("DETAIL", "crawl-all: unconditional detail crawl",
                           "no priority fields selected",
                           data={"detail_urls": len(detail_urls)})
            should_crawl = True
        elif completeness_trigger and intent is not None:
            # Agent mode: nobody is at a prompt — auto-trigger the crawl.
            # Playground/CLI fall through to their usual y/n below.
            print(f"  Completeness gate: {name_only:.0%} of records are "
                  f"name-only with {len(detail_urls)} detail pages — auto-crawling")
            debug.decision("DETAIL", "completeness gate: auto detail crawl",
                           f"{name_only:.0%} of records name-only",
                           data={"detail_urls": len(detail_urls)})
            should_crawl = True
        elif priority_fields and not crawl_relevant and not completeness_trigger:
            # All selected priorities are phase2-only (e.g. social_media) — detail pages can't help
            print(f"  Priority fields ({', '.join(priority_fields)}) require Phase 2 enrichment, skipping detail crawl")
        elif crawl_relevant and not missing_for_crawl and not completeness_trigger:
            # All crawl-relevant priority fields already captured — skip detail crawl
            print(f"  All priority fields already found ({', '.join(found_fields)}), skipping detail crawl")
        elif prompt_callback:
            # Build smart prompt with found/missing info
            if completeness_trigger:
                msg = (
                    f"{name_only:.0%} of extracted records are name-only — "
                    f"contact info likely lives on the {len(detail_urls)} "
                    f"member profile pages. Crawl them? (y/n)"
                )
            elif crawl_relevant and missing_for_crawl:
                msg = (
                    f"Found: {', '.join(sorted(found_fields))}. "
                    f"Missing: {', '.join(sorted(missing_for_crawl))}. "
                    f"Found {len(detail_urls)} detail pages — crawl for missing fields? (y/n)"
                )
            else:
                msg = None  # use default message
            should_crawl = prompt_callback(len(detail_urls), msg)
        else:
            should_crawl = prompt_detail_crawl(len(detail_urls))

        if should_crawl:
            with debug.span("DETAIL", f"detail crawl ({len(detail_urls)} pages)"):
                detail_members = crawl_detail_pages(detail_urls, domain)
            if detail_members:
                detail_path = os.path.join(data_dump_dir, f"{domain}_detail_raw.json")
                with open(detail_path, "w") as f:
                    json.dump(detail_members, f, indent=4)
                print(f"Saved {len(detail_members)} detail members to {detail_path}")

    # --- Step 4.5: Re-parse with detail members merged in (only when a
    # crawl ran; otherwise the Step 3 parse IS the final state) ---
    if detail_members:
        with debug.span("PARSE", "final parse (detail merge)"):
            members, _ = parse_and_save_results(results, data_dump_dir, domain,
                                                detail_members=detail_members,
                                                intent=intent,
                                                source_url=url)
    debug.log("CLEAN", f"Final member count: {len(members)}")

    # --- Step 5: If zero results, warn (login gate already handled in browser) ---
    if len(members) == 0:
        print("WARNING: 0 members extracted — the page may be login-gated "
              "or the extraction strategy failed")

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