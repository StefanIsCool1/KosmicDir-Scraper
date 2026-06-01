"""
Phase 2 — Vertical-aware enrichment routing.

Different professional verticals have different authoritative data sources:
  - Healthcare (doctors, dentists, therapists, vets, etc.)
        → NPI Registry (free public CMS API — phone, practice address, taxonomy)
  - Lawyers / attorneys
        → Smart DDG that prefers Avvo / Martindale-Hubbell / Justia profiles
  - Real estate agents
        → Smart DDG that prefers Realtor.com / Zillow / major brokerage sites
  - General business
        → existing ddg_search_website flow (no change)

A small classifier (heuristic-first, LLM-fallback) routes each record to the
right vertical BEFORE the generic DDG search runs, so a dentist gets NPI
data instead of being treated like a company-with-a-self-named-domain.

Honest scope:
  - NPI Registry is a single universal API — implemented end-to-end.
  - State bar APIs are 50+ different systems (CA, NY, TX, FL each have a
    different lookup, many with CAPTCHAs). OUT OF SCOPE for v1. Today's
    lawyer path uses tuned DDG queries that prefer the big three aggregators
    (Avvo, Martindale, Justia) which together cover most active US attorneys.
  - NAR / state real-estate license boards are similarly fragmented and most
    are bot-protected. OUT OF SCOPE for v1. Today's RE path uses tuned DDG
    queries that prefer Realtor.com, Zillow agent pages, and major brokerages.

To add a state-specific API for a vertical, extend the appropriate _enrich_*
function with a custom path BEFORE the smart-DDG fallback returns.

Fail-open everywhere: if a vertical-specific lookup fails for any reason,
the caller's existing DDG flow still runs and the record gets the same
treatment it would have without this module.
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote_plus, urlparse

from curl_cffi.requests import Session
from curl_cffi import CurlError

# Reuse Bot/llm.py for the classifier
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Bot"))
from llm import ask  # type: ignore  # noqa: E402


# --- VERTICAL CONSTANTS ---

VERTICAL_HEALTHCARE = "healthcare"
VERTICAL_LAWYER = "lawyer"
VERTICAL_REAL_ESTATE = "real_estate"
VERTICAL_BUSINESS = "business"

ALL_VERTICALS = (VERTICAL_HEALTHCARE, VERTICAL_LAWYER, VERTICAL_REAL_ESTATE, VERTICAL_BUSINESS)


# --- HEURISTIC CLASSIFIER HINTS ---

# Lowercase category-fragment substrings that strongly signal vertical.
_HEALTHCARE_HINTS = (
    "general practice", "periodontics", "endodontics", "orthodont",
    "oral and maxillofacial", "pediatric dentistry", "prosthodont",
    "dental", "dentist", "dentistry",
    "physician", "doctor", "medical practice",
    "chiropract", "optometry", "podiatry",
    "psychiatry", "psychology", "psychotherap",
    "physical therapy", "occupational therapy", "speech therapy",
    "nurse practitioner", "nursing",
    "hospital", "clinic", "health system", "urgent care",
    "veterinar",
    "radiology", "cardiology", "dermatology", "neurology",
    "pediatric", "obstetric", "gynecolog", "anesthesi", "oncology",
)

_LAWYER_HINTS = (
    "attorney", "lawyer", "legal", "law firm", "law office",
    "law practice", "litigation", "counsel", "bar association",
    "criminal defense", "personal injury", "estate planning",
    "family law", "corporate law", "tax law", "patent attorney",
)

_REAL_ESTATE_HINTS = (
    "real estate", "realtor", "realty",
    "real estate agent", "real estate broker", "real estate brokerage",
    "property management", "residential real estate",
    "commercial real estate", "mls",
)

# Honorifics / credentials in the name field.
_DR_PREFIX_RE = re.compile(r"^\s*dr\.?\s+", re.I)
_ESQ_SUFFIX_RE = re.compile(r",?\s*esq\.?\s*$", re.I)
# A separator (comma or whitespace) is REQUIRED before the credential so the
# 2-letter tokens don't match the tail of ordinary surnames — without it "do"
# matches Acevedo / Maldonado / Toledo and "od" matches MacLeod. ("odd" was a
# typo for the optometry credential "od".)
_DDS_SUFFIX_RE = re.compile(r"(?:,\s*|\s+)(dds|dmd|md|do|phd|dvm|dpm|od|optometrist)\.?\s*$", re.I)

# Strip-from-name patterns: honorifics at start, credentials at end.
_NAME_NOISE_RE = re.compile(
    r"^(dr|mr|mrs|ms|prof|rev|fr|hon)\.?\s+"
    r"|\s+(dds|dmd|md|do|phd|esq|dvm|dpt|dpm|otd|mph|mba|cpa|"
    r"jr|sr|ii|iii|iv|v)\.?\s*$",
    re.I,
)


# --- NPI REGISTRY CLIENT ---

_NPI_API_URL = "https://npiregistry.cms.hhs.gov/api/"
_NPI_TIMEOUT = 8
_NPI_RATE_LIMIT_DELAY = 0.1  # polite citizen pause between calls


def _parse_person_name(name: str) -> tuple[str, str] | None:
    """Strip honorifics/credentials and split into (first, last).

    "Dr. A Keith Lethco DDS" → ("A", "Lethco")
    "Jane M. Smith"          → ("Jane", "Smith")
    Returns None if the cleaned name doesn't yield at least two parts.
    """
    if not name:
        return None
    cleaned = name.strip()
    # Strip honorifics + credentials, repeat in case both ends have one
    for _ in range(3):
        prev = cleaned
        cleaned = _NAME_NOISE_RE.sub("", cleaned).strip()
        if cleaned == prev:
            break
    # Remove punctuation
    cleaned = re.sub(r"[,.]", " ", cleaned)
    parts = [p for p in cleaned.split() if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def _state_from_address(street_address: str | None) -> str | None:
    """Extract a 2-letter US state code from an address string.

    Matches the high-signal pattern "XX 12345" (state code followed by ZIP).
    Avoids false positives that would happen with a generic 2-letter scan.
    """
    if not street_address:
        return None
    m = re.search(r"\b([A-Z]{2})\s+\d{5}", street_address)
    return m.group(1) if m else None


def _format_npi_address(a: dict | None) -> str | None:
    """Format an NPI address dict into a single-line string."""
    if not a:
        return None
    parts = [
        (a.get("address_1") or "").strip(),
        (a.get("address_2") or "").strip(),
        (a.get("city") or "").strip(),
        f"{(a.get('state') or '').strip()} {(a.get('postal_code') or '').strip()}".strip(),
    ]
    formatted = ", ".join(p for p in parts if p)
    return formatted or None


def npi_lookup(first_name: str, last_name: str, state: str | None = None,
               taxonomy_hint: str | None = None) -> dict | None:
    """Query NPI Registry for a single individual provider.

    Returns a normalized dict {npi, phone, fax, practice_address,
    mailing_address_npi, taxonomy, license_number} or None on miss / error.
    """
    params = {
        "version": "2.1",
        "first_name": first_name,
        "last_name": last_name,
        "enumeration_type": "NPI-1",  # individuals only
        "limit": "10",
    }
    if state:
        params["state"] = state

    url = _NPI_API_URL + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())

    try:
        time.sleep(_NPI_RATE_LIMIT_DELAY)
        session = Session(timeout=_NPI_TIMEOUT)
        resp = session.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (CurlError, Exception) as e:
        print(f"    NPI: request failed for {first_name} {last_name}: {str(e)[:80]}")
        return None

    results = data.get("results") or []
    if not results:
        return None

    # Pick the best match. If a taxonomy hint is given (e.g. "Periodontics"),
    # prefer the result whose primary taxonomy description contains it.
    best = results[0]
    if taxonomy_hint and len(results) > 1:
        hint_words = [w for w in taxonomy_hint.lower().split() if len(w) > 3]
        for r in results:
            for t in (r.get("taxonomies") or []):
                desc = (t.get("desc") or "").lower()
                if any(w in desc for w in hint_words):
                    best = r
                    break
            else:
                continue
            break

    addresses = best.get("addresses") or []
    location = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), None)
    mailing = next((a for a in addresses if a.get("address_purpose") == "MAILING"), None)
    primary = location or mailing or (addresses[0] if addresses else {})

    taxonomies = best.get("taxonomies") or []
    primary_tax = next((t for t in taxonomies if t.get("primary")), None) or (taxonomies[0] if taxonomies else {})

    return {
        "npi": best.get("number"),
        "phone": (primary.get("telephone_number") or "").strip() or None,
        "fax": (primary.get("fax_number") or "").strip() or None,
        "practice_address": _format_npi_address(location),
        "mailing_address_npi": _format_npi_address(mailing),
        "taxonomy": (primary_tax.get("desc") or "").strip() or None,
        "license_number": (primary_tax.get("license") or "").strip() or None,
    }


# --- NPI BULK SEARCH (Phase 0 API-route source) ---
#
# The DISCOVERY counterpart to npi_lookup()'s per-record ENRICHMENT: same
# endpoint and normalization, but searched by taxonomy + location and
# paginated. Used when Phase 0 routes a healthcare-practitioner goal straight
# to NPI instead of scraping (DiscoveryBot/pipeline.py:_maybe_api_route).
#
# Completeness note (deliberate MVP choice): the public NPI API caps at
# limit=200 and skip<=1000 — ~1200 records per query. For small states /
# specific taxonomies that's the full set; for "every dentist in CA" it's
# partial, surfaced via the returned `hit_ceiling` flag rather than silently
# truncating. True completeness would mean ingesting the monthly NPPES bulk
# data file (~9GB + local index) — out of scope for this slice.

# Common user/LLM terms → NPI taxonomy_description query value(s). The API
# partial-matches taxonomy_description, so we send the canonical NPI label.
# Intentionally NARROW: only professions that map cleanly to ONE taxonomy.
# Broad asks ("doctors"/"physicians" — hundreds of taxonomies) and non-NPI
# professions ("veterinarian" — NPI is HIPAA health providers only, not vets)
# are deliberately ABSENT so resolve_npi_taxonomies() returns [] and the
# caller falls back to directory discovery instead of partial/empty API data.
_NPI_TAXONOMY_MAP: dict[str, list[str]] = {
    "dentist": ["Dentist"],
    "dental": ["Dentist"],
    "orthodontist": ["Orthodontics and Dentofacial Orthopedics"],
    "endodontist": ["Endodontics"],
    "periodontist": ["Periodontics"],
    "oral surgeon": ["Oral & Maxillofacial Surgery"],
    "chiropractor": ["Chiropractor"],
    "optometrist": ["Optometrist"],
    "podiatrist": ["Podiatrist"],
    "physical therapist": ["Physical Therapist"],
    "physical therapy": ["Physical Therapist"],
    "occupational therapist": ["Occupational Therapist"],
    "speech therapist": ["Speech-Language Pathologist"],
    "speech language pathologist": ["Speech-Language Pathologist"],
    "psychologist": ["Psychologist"],
    "acupuncturist": ["Acupuncturist"],
    "dietitian": ["Dietitian, Registered"],
    "audiologist": ["Audiologist"],
    "midwife": ["Midwife"],
    "nurse practitioner": ["Nurse Practitioner"],
    "pharmacist": ["Pharmacist"],
    "clinical social worker": ["Social Worker, Clinical"],
    "naturopath": ["Naturopath"],
    "massage therapist": ["Massage Therapist"],
}


def resolve_npi_taxonomies(term: str) -> list[str]:
    """Map a user/LLM industry term to NPI taxonomy_description query strings.

    Returns [] when the term is NOT cleanly NPI-routable — broad 'doctors'/
    'physicians' (hundreds of taxonomies) or non-NPI professions like
    veterinarians (NPI covers HIPAA health providers only). An empty list is
    the signal to fall back to normal directory discovery rather than serve
    partial or empty API data.
    """
    if not term:
        return []
    t = " ".join(term.strip().lower().split())
    if t in _NPI_TAXONOMY_MAP:
        return _NPI_TAXONOMY_MAP[t]
    if t.endswith("s") and t[:-1] in _NPI_TAXONOMY_MAP:   # "dentists" -> "dentist"
        return _NPI_TAXONOMY_MAP[t[:-1]]
    for key, vals in _NPI_TAXONOMY_MAP.items():           # "family dentist" -> "dentist"
        if key in t:
            return vals
    return []


def _npi_request_page(taxonomy_description: str, state: str, city: str | None,
                      enumeration_type: str, skip: int) -> list[dict] | None:
    """Fetch one NPI API page. Returns the results list, or None on error."""
    params = {
        "version": "2.1",
        "state": state,
        "taxonomy_description": taxonomy_description,
        "enumeration_type": enumeration_type,
        "limit": "200",
        "skip": str(skip),
    }
    if city:
        params["city"] = city
    url = _NPI_API_URL + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    try:
        time.sleep(_NPI_RATE_LIMIT_DELAY)
        resp = Session(timeout=_NPI_TIMEOUT).get(url)
        if resp.status_code != 200:
            return None
        return resp.json().get("results") or []
    except (CurlError, Exception) as e:
        print(f"    NPI bulk: request failed (skip={skip}): {str(e)[:80]}")
        return None


def _npi_result_to_member(r: dict) -> dict:
    """Map one NPI API result to the pipeline's standard member schema."""
    basic = r.get("basic") or {}
    etype = (r.get("enumeration_type") or "").upper()
    if etype == "NPI-2":
        company_name = (basic.get("organization_name") or "").strip()
    else:
        name = f"{(basic.get('first_name') or '').strip()} {(basic.get('last_name') or '').strip()}".strip()
        cred = (basic.get("credential") or "").strip().strip(".")
        company_name = f"{name}, {cred}" if (name and cred) else name

    addresses = r.get("addresses") or []
    location = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), None)
    mailing = next((a for a in addresses if a.get("address_purpose") == "MAILING"), None)
    primary = location or mailing or (addresses[0] if addresses else {})

    taxonomies = r.get("taxonomies") or []
    primary_tax = next((t for t in taxonomies if t.get("primary")), None) or (taxonomies[0] if taxonomies else {})
    tax_desc = (primary_tax.get("desc") or "").strip() or None

    npi_num = r.get("number")
    return {
        "company_name": company_name,
        "phone": (primary.get("telephone_number") or "").strip() or None,
        "fax": (primary.get("fax_number") or "").strip() or None,
        "street_address": _format_npi_address(location),
        "mailing_address": _format_npi_address(mailing),
        "website": "",
        "category": tax_desc,
        "description": f"{tax_desc} (NPI {npi_num})" if tax_desc else (f"NPI {npi_num}" if npi_num else None),
        "contacts": [],
        "npi": npi_num,
        "enrichment_source": f"npi_registry:{npi_num}" if npi_num else None,
    }


def npi_search_by_taxonomy(taxonomy_queries: list[str], state: str,
                           city: str | None = None,
                           enumeration_type: str = "NPI-1",
                           progress_cb=None) -> tuple[list[dict], bool]:
    """Bulk-search NPI for all providers of given taxonomies in a state/city.

    Args:
        taxonomy_queries: NPI taxonomy_description values (from
            resolve_npi_taxonomies). Each is searched; results are merged.
        state: 2-letter US state code (required for a bounded search).
        city: optional city to narrow (and stay under the API result cap).
        enumeration_type: "NPI-1" (individual practitioners — the default, best
            match for "professionals") or "NPI-2" (organizations/practices).
        progress_cb: optional callable(count) for streaming progress.

    Returns:
        (members, hit_ceiling). `members` are normalized + de-duped by NPI
        number. `hit_ceiling=True` means a taxonomy hit the API's ~1200-record
        cap, so results are partial (narrow by city for the rest).
    """
    state = (state or "").strip().upper()
    if not state or not taxonomy_queries:
        return [], False

    collected: dict[str, dict] = {}
    hit_ceiling = False
    for tq in taxonomy_queries:
        skip = 0
        while True:
            page = _npi_request_page(tq, state, city, enumeration_type, skip)
            if page is None:          # error — stop this taxonomy, keep what we have
                break
            for r in page:
                num = r.get("number")
                key = str(num) if num is not None else f"_{len(collected)}"
                collected.setdefault(key, _npi_result_to_member(r))
            if progress_cb:
                progress_cb(len(collected))
            if len(page) < 200:       # last page for this taxonomy
                break
            skip += 200
            if skip > 1000:           # API hard ceiling (skip<=1000)
                hit_ceiling = True
                break

    return list(collected.values()), hit_ceiling


def _enrich_healthcare(record: dict) -> dict | None:
    """NPI Registry path for healthcare records.

    Returns fields to merge (phone, fax, mailing_address, description) or None
    if the record doesn't yield a parseable person name or NPI has no match.
    """
    parsed = _parse_person_name(record.get("company_name") or "")
    if not parsed:
        return None
    first, last = parsed
    state = _state_from_address(record.get("street_address"))
    taxonomy_hint = record.get("category") or None

    npi = npi_lookup(first, last, state=state, taxonomy_hint=taxonomy_hint)
    if not npi and state:
        # Fallback: no state filter (some practitioners' NPI states differ
        # from the directory's listed address state)
        npi = npi_lookup(first, last, state=None, taxonomy_hint=taxonomy_hint)
    if not npi:
        return None

    merged = {}
    if npi.get("phone") and not record.get("phone"):
        merged["phone"] = npi["phone"]
    if npi.get("fax") and not record.get("fax"):
        merged["fax"] = npi["fax"]
    if npi.get("mailing_address_npi") and not record.get("mailing_address"):
        merged["mailing_address"] = npi["mailing_address_npi"]
    if npi.get("taxonomy") and not record.get("description"):
        merged["description"] = f"{npi['taxonomy']} (NPI {npi['npi']})"
    # Use a vertical-specific source field so we don't collide with the
    # main pipeline's enrichment_source (set during website fetch).
    merged["vertical_source"] = f"npi_registry:{npi.get('npi', 'unknown')}"
    return merged


# --- LAWYER ENRICHMENT (smart DDG, not state bar APIs) ---

# Aggregators that cover most active US attorneys with structured profiles.
_LAWYER_PREFERRED_DOMAINS = (
    "avvo.com", "martindale.com", "justia.com",
    "lawyers.com", "findlaw.com", "superlawyers.com",
    "lawyers.justia.com",
)


def _enrich_lawyer(record: dict, ddg_fetcher) -> dict | None:
    """Smart DDG for lawyers — prefer Avvo / Martindale / Justia profiles.

    State bar API integration is intentionally out of scope (50 states, each
    different system, many CAPTCHA-protected). This produces meaningfully
    better results than generic name-search by surfacing the structured
    aggregator pages that have most US attorneys.

    Extension point: prepend per-state API logic here when desired.
    """
    parsed = _parse_person_name(record.get("company_name") or "")
    if not parsed:
        return None
    first, last = parsed
    state = _state_from_address(record.get("street_address")) or ""

    queries = [
        f'"{first} {last}" attorney {state} site:avvo.com',
        f'"{first} {last}" attorney {state} site:martindale.com',
        f'"{first} {last}" {state} lawyer',
    ]

    for q in queries:
        try:
            results = ddg_fetcher(q.strip()) or []
        except Exception:
            continue
        for r in results[:5]:
            href = (r.get("href") or "").strip()
            if not href.startswith("http"):
                continue
            try:
                domain = urlparse(href).netloc.lower().replace("www.", "")
            except Exception:
                continue
            if any(domain == d or domain.endswith("." + d) for d in _LAWYER_PREFERRED_DOMAINS):
                return {
                    "website": href,
                    "vertical_source": f"lawyer_directory:{domain}",
                }
    return None


# --- REAL ESTATE ENRICHMENT (smart DDG, not NAR / license boards) ---

_REAL_ESTATE_PREFERRED_DOMAINS = (
    "realtor.com", "zillow.com",
    "compass.com", "redfin.com",
    "kw.com", "remax.com",
    "coldwellbanker.com", "century21.com",
    "berkshirehathawayhs.com", "exprealty.com",
    "sothebysrealty.com", "douglaselliman.com",
)


def _enrich_real_estate(record: dict, ddg_fetcher) -> dict | None:
    """Smart DDG for real estate agents — prefer Realtor.com / Zillow agent
    pages / major brokerage sites.

    NAR direct integration is gated; state real-estate license boards are
    50+ different systems. This produces better results than generic search
    by surfacing the structured agent pages on major aggregator sites.

    Extension point: prepend per-state license-board logic here when desired.
    """
    parsed = _parse_person_name(record.get("company_name") or "")
    if not parsed:
        return None
    first, last = parsed
    state = _state_from_address(record.get("street_address")) or ""

    queries = [
        f'"{first} {last}" realtor {state} site:realtor.com',
        f'"{first} {last}" agent {state} site:zillow.com',
        f'"{first} {last}" {state} real estate agent',
    ]

    for q in queries:
        try:
            results = ddg_fetcher(q.strip()) or []
        except Exception:
            continue
        for r in results[:5]:
            href = (r.get("href") or "").strip()
            if not href.startswith("http"):
                continue
            try:
                domain = urlparse(href).netloc.lower().replace("www.", "")
            except Exception:
                continue
            if any(domain == d or domain.endswith("." + d) for d in _REAL_ESTATE_PREFERRED_DOMAINS):
                return {
                    "website": href,
                    "vertical_source": f"real_estate_directory:{domain}",
                }
    return None


# --- CLASSIFIER ---

# Cached per (category, name-shape) so identical-shape records share results.
# Module-level so it persists across all records in one enrichment run.
_VERTICAL_CACHE: dict[tuple, str] = {}


def _heuristic_vertical(category: str, name: str) -> str | None:
    """Cheap heuristic classifier. Returns vertical or None if unclear."""
    cat_lower = (category or "").lower()

    has_dr = bool(_DR_PREFIX_RE.match(name))
    has_esq = bool(_ESQ_SUFFIX_RE.search(name))
    has_dds = bool(_DDS_SUFFIX_RE.search(name))

    # Strong signals from name suffix
    if has_esq:
        return VERTICAL_LAWYER
    if has_dds:
        return VERTICAL_HEALTHCARE

    # Category-driven (overrides ambiguous "Dr." prefix)
    if any(h in cat_lower for h in _HEALTHCARE_HINTS):
        return VERTICAL_HEALTHCARE
    if any(h in cat_lower for h in _LAWYER_HINTS):
        return VERTICAL_LAWYER
    if any(h in cat_lower for h in _REAL_ESTATE_HINTS):
        return VERTICAL_REAL_ESTATE

    # "Dr." prefix with no category → most often healthcare (PhDs are rarer
    # in business directories than physicians/dentists)
    if has_dr:
        return VERTICAL_HEALTHCARE

    return None


def _llm_vertical(record: dict) -> str:
    """LLM fallback for records the heuristics couldn't classify."""
    prompt = f"""Classify this directory record into ONE of these verticals.

VERTICALS:
- healthcare: doctors, dentists, nurses, therapists, vets, hospitals, clinics, any medical practitioner
- lawyer: attorneys, law firms, legal practices, legal services
- real_estate: real estate agents, brokers, realtors, real-estate brokerages
- business: any other company, organization, member listing, professional service that isn't one of the above

Record:
  Name: {record.get('company_name', '') or '(none)'}
  Category: {record.get('category', '') or '(none)'}
  Address: {record.get('street_address', '') or '(none)'}

Return ONLY one word from the list: healthcare, lawyer, real_estate, business
No explanation."""
    try:
        raw = ask(prompt, max_tokens=10).strip().lower()
        for v in ALL_VERTICALS:
            if v in raw:
                return v
    except Exception as e:
        print(f"    Classifier: LLM failed ({str(e)[:60]}) — defaulting to business")
    return VERTICAL_BUSINESS


def classify_vertical(record: dict) -> str:
    """Determine the enrichment vertical for a record.

    Heuristic-first (free), LLM-fallback for ambiguous cases. Results cached
    by (category, name-shape) so a dental directory with 90 General-Practice
    records makes at most one classifier call total (and usually zero, since
    "General Practice" hits the healthcare hint list directly).
    """
    category = (record.get("category") or "").strip().lower()
    name = (record.get("company_name") or "").strip()

    cache_key = (
        category,
        bool(_DR_PREFIX_RE.match(name)),
        bool(_ESQ_SUFFIX_RE.search(name)),
        bool(_DDS_SUFFIX_RE.search(name)),
    )
    cached = _VERTICAL_CACHE.get(cache_key)
    if cached:
        return cached

    h = _heuristic_vertical(category, name)
    if h:
        _VERTICAL_CACHE[cache_key] = h
        return h

    v = _llm_vertical(record)
    _VERTICAL_CACHE[cache_key] = v
    return v


def reset_vertical_cache():
    """Clear the per-(category, name-shape) classifier cache. Call between
    distinct enrichment runs if you want to force re-classification."""
    _VERTICAL_CACHE.clear()


# --- MAIN ENTRY POINT ---

def enrich_by_vertical(record: dict, ddg_fetcher=None) -> tuple[str, dict | None]:
    """Route a record to vertical-specific enrichment.

    Returns (vertical, fields_dict_or_None). When fields_dict is not None,
    the caller should merge those fields into the record (preferring existing
    non-empty values).

    ddg_fetcher: callable(query) -> list[{href, title, snippet}]. Required
    for lawyer/real-estate verticals; pass page_fetcher._ddg_fetch_results.
    Healthcare doesn't need it (uses NPI directly).
    """
    vertical = classify_vertical(record)

    if vertical == VERTICAL_HEALTHCARE:
        return vertical, _enrich_healthcare(record)
    if vertical == VERTICAL_LAWYER and ddg_fetcher:
        return vertical, _enrich_lawyer(record, ddg_fetcher)
    if vertical == VERTICAL_REAL_ESTATE and ddg_fetcher:
        return vertical, _enrich_real_estate(record, ddg_fetcher)

    # Business or no fetcher provided — caller's existing DDG flow handles it.
    return vertical, None
