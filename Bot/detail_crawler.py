"""
Detail page crawler.
Handles: detecting detail links on listing pages, crawling individual member
detail pages headlessly, learning selectors for detail pages.

Triggered when:
1. Listing page data is "shallow" (names only, no contact info)
2. Member detail links are detected (e.g. /members/?id=81707594)
3. User confirms they want to crawl

Strategy:
1. Check cache for detail selectors → apply with BS4 (zero AI cost)
2. Crawl 3 sample detail pages
3. Send samples to Haiku to learn CSS selectors (one cheap call per domain)
4. Apply learned selectors to all remaining pages with BS4 (zero AI cost)
"""

import re
import json
import time
from urllib.parse import urlparse
import random
import ssl
import urllib.request
import anthropic
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from config import (
    DETAIL_CRAWL_DELAY_MIN, DETAIL_CRAWL_DELAY_MAX,
    DETAIL_SAMPLE_COUNT, DETAIL_URL_KEYWORDS,
    NETWORK_IDLE_TIMEOUT, EXTERNAL_SKIP_DOMAINS,
    block_unnecessary_resources,
)
from html_parser import strip_junk, regex_extract_from_card, _merge_member_data
from cache import get_cached_selectors, set_cached_selectors, delete_cached_selectors


# ───────────────────────────────────────────
#  DETECTION: Are there detail links?
# ───────────────────────────────────────────

def detect_detail_links(collected_links: list) -> list:
    """Detect member detail page links from collected page links.

    Looks for groups of content-area links that follow the same URL template
    with different numeric IDs (e.g. /members/?id=111, /members/?id=222).

    Args:
        collected_links: List of dicts with 'href' and 'inNav' keys,
                         gathered during browsing via collect_page_links().

    Returns:
        Deduplicated list of detail page URL strings, or [] if none detected.
    """
    if not collected_links:
        return []

    # Filter out nav/header/footer links
    content_links = [l for l in collected_links if not l.get("inNav")]

    def templatize(url: str) -> str:
        """Replace varying parts of URL with {ID} to find repeating patterns.
        Handles numeric IDs, UUIDs, and slug-based paths."""
        t = url
        # Query param IDs: ?id=12345 → ?id={ID}
        t = re.sub(r'([?&]\w*id\w*=)\d+', r'\1{ID}', t, flags=re.IGNORECASE)
        # Generic numeric query params with 4+ digits: ?foo=12345 → ?foo={ID}
        t = re.sub(r'([?&]\w+=)\d{4,}', r'\1{ID}', t)
        # Path segment numeric IDs (3+ digits): /members/12345 → /members/{ID}
        t = re.sub(r'/(\d{3,})(?=/|$|\?)', '/{ID}', t)
        # UUID-style path segments: /abc12def-3456-... → /{ID}
        t = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '/{ID}', t, flags=re.IGNORECASE
        )
        # Slug-based last segment: /p/company-name-here → /p/{ID}
        # Only applies when no numeric/UUID replacement happened above,
        # the last segment contains a hyphen (slug-like), and is 4+ chars.
        if t == url:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/")
            if "/" in path:
                parent, slug = path.rsplit("/", 1)
                if slug and "-" in slug and len(slug) >= 4:
                    t = url.replace(path, parent + "/{ID}")
        return t

    # Group links by their URL template
    template_groups: dict[str, list[str]] = {}
    for link in content_links:
        href = link.get("href", "")
        if not href or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue

        # Skip external domains — these are never member detail pages
        href_lower = href.lower()
        if any(d in href_lower for d in EXTERNAL_SKIP_DOMAINS):
            continue

        template = templatize(href)
        # Only consider links where templatizing changed something (has an ID)
        if template != href:
            template_groups.setdefault(template, []).append(href)

    if not template_groups:
        return []

    # Score each template group
    best_template = None
    best_score = 0

    for template, urls in template_groups.items():
        if len(urls) < 3:
            continue

        score = len(urls)  # base: more links = better

        # Bonus if URL contains directory-related keywords
        template_lower = template.lower()
        keyword_matches = sum(1 for kw in DETAIL_URL_KEYWORDS if kw in template_lower)
        score += keyword_matches * 10

        # Penalty for non-directory URL patterns (blog posts, events, classes, etc.)
        non_directory_keywords = [
            "blog", "news", "article", "post", "press",
            "event", "class", "course", "training", "workshop",
            "seminar", "webinar", "calendar", "schedule",
            "job", "career", "faq", "help", "support",
            "about", "team", "staff", "board", "committee",
            "gallery", "photo", "video", "podcast",
            "product", "shop", "store", "cart",
            "page", "tag", "archive",
        ]
        penalty = sum(1 for kw in non_directory_keywords if kw in template_lower)
        score -= penalty * 15

        if score > best_score:
            best_score = score
            best_template = template

    if best_template is None:
        return []

    detail_urls = template_groups[best_template]

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in detail_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    # Require at least 3 unique URLs after dedup.
    # Fewer than 3 is not a real member directory pattern — it's likely
    # stray links (pagination, footer, etc.) that appeared across multiple
    # paginated pages and accumulated duplicate entries.
    if len(unique_urls) < 3:
        print(f"  Only {len(unique_urls)} unique detail URLs after dedup — not enough, skipping")
        return []

    print(f"  Detected {len(unique_urls)} detail page links (pattern: {best_template})")
    return unique_urls


# ───────────────────────────────────────────
#  DETECTION: Is captured data shallow?
# ───────────────────────────────────────────

CONTACT_KEYS = {
    "phone", "email", "website", "address", "addresses",
    "mainphone", "phonenumber", "telephone",
    "url", "web", "homepage", "fax",
}


def is_shallow_data(results: list) -> bool:
    """Check if captured data lacks contact details (phone, email, website).
    Returns True if data appears shallow — names only, no real contact info.

    Checks both JSON list responses and JSON dict responses.
    Ignores raw_html entries (those are fallback captures, not structured data).
    """
    total_records = 0
    records_with_contact = 0

    for result in results:
        data = result.get("data", {})

        records = []
        if isinstance(data, list):
            records = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict) and "raw_html" not in data:
            records = [data]

        for item in records:
            total_records += 1

            # Check if any contact-like key exists AND has a non-empty value
            for k, v in item.items():
                if k.lower() in CONTACT_KEYS and v and str(v).strip():
                    records_with_contact += 1
                    break

    if total_records == 0:
        # No structured data at all — could be HTML only.
        # Not "shallow" in the JSON sense; HTML parser handles this separately.
        return False

    # If fewer than 20% of records have contact info, data is shallow
    return (records_with_contact / total_records) < 0.2


def html_has_contact_info(results: list) -> bool:
    """Check if captured HTML responses contain contact information.

    Scans raw_html entries for phone numbers, email addresses, and other
    contact signals. Used to determine whether an HTML-only listing page
    already has full member data (and thus doesn't need detail page crawling).

    Args:
        results: List of result dicts from capture_responses.

    Returns:
        True if the HTML contains meaningful contact info.
    """
    phone_count = 0
    email_count = 0

    for result in results:
        data = result.get("data", {})
        if not isinstance(data, dict) or "raw_html" not in data:
            continue

        html = data["raw_html"]
        if not html:
            continue

        # Sample from multiple positions in the HTML to catch contact info
        # regardless of where member cards start (some sites have 100K+ of
        # header/nav before the first card)
        html_lower = html.lower()
        chunks = [
            html_lower[:50000],                    # beginning
            html_lower[len(html)//3:len(html)//3 + 50000],  # middle third
            html_lower[len(html)//2:len(html)//2 + 50000],  # midpoint
        ]
        sample = " ".join(chunks)

        # Count phone number patterns:
        # (206) 555-1234, 206-555-1234, 206.555.1234, 2065551234
        phones = re.findall(
            r'(?:\(\d{3}\)\s*|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}',
            sample
        )
        phone_count += len(phones)

        # Count email signals: mailto: links and @ in text near common TLDs
        email_count += sample.count("mailto:")
        email_count += len(re.findall(r'[\w.\-]+@[\w.\-]+\.\w{2,}', sample))

    # If we found 3+ phone numbers OR 3+ emails across all HTML responses,
    # the listing page likely has contact info embedded
    has_contact = phone_count >= 3 or email_count >= 3

    if has_contact:
        print(f"  HTML contact check: {phone_count} phones, {email_count} emails — data is rich")
    else:
        print(f"  HTML contact check: {phone_count} phones, {email_count} emails — data may be shallow")

    return has_contact


# ───────────────────────────────────────────
#  DETAIL PAGE SELECTOR LEARNING
# ───────────────────────────────────────────

def _get_ancestors(el):
    """Return list of parent elements from el up to the root."""
    ancestors = []
    parent = el.parent
    while parent and parent.name:
        ancestors.append(parent)
        parent = parent.parent
    return ancestors


def _find_common_ancestor(elements):
    """Find the smallest common ancestor of a list of BeautifulSoup elements."""
    if not elements:
        return None
    if len(elements) == 1:
        return elements[0].parent

    # Get ancestor chains for each element
    ancestor_chains = [_get_ancestors(el) for el in elements]

    # Find common ancestors (present in ALL chains)
    common = set(id(a) for a in ancestor_chains[0])
    ancestor_map = {id(a): a for a in ancestor_chains[0]}
    for chain in ancestor_chains[1:]:
        chain_ids = set(id(a) for a in chain)
        ancestor_map.update({id(a): a for a in chain})
        common &= chain_ids

    if not common:
        return None

    # Pick the smallest (deepest) common ancestor by text length
    candidates = [ancestor_map[aid] for aid in common]
    return min(candidates, key=lambda a: len(a.get_text(strip=True)))


def clean_detail_html(raw_html: str) -> str:
    """Extract the contact/member detail section from a full page HTML.

    Universal approach:
    1. Remove scripts/styles (safe cleanup)
    2. Find contact signal elements (itemprop, tel:, mailto: links)
    3. Walk up to their smallest common ancestor — that's the detail panel
    4. Fall back to standard content selectors if no contact signals found
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Safe cleanup — only remove elements that never contain useful text
    for tag in soup(["script", "style", "svg", "noscript"]):
        tag.decompose()

    # --- Strategy 1: Find contact signal elements and their common ancestor ---
    signal_elements = []

    # Schema.org markup (itemprop="telephone", "email", "streetAddress", etc.)
    for el in soup.find_all(attrs={"itemprop": True}):
        prop = str(el.get("itemprop", "")).lower()
        if prop in ("telephone", "email", "streetaddress", "addresslocality",
                     "postalcode", "addressregion", "url", "name", "contactpoint"):
            signal_elements.append(el)

    # tel: and mailto: links
    for el in soup.find_all("a", href=True):
        href = str(el.get("href", ""))
        if href.startswith("tel:") or href.startswith("mailto:"):
            signal_elements.append(el)

    if len(signal_elements) >= 2:
        ancestor = _find_common_ancestor(signal_elements)
        if ancestor and ancestor.name not in ("html", "body", "[document]"):
            text_len = len(ancestor.get_text(strip=True))
            # Good ancestor: has real content but isn't the whole page
            if 50 < text_len < 20000:
                return str(ancestor)

    # --- Strategy 2: Standard content container selectors (on unstripped soup) ---
    content_selectors = [
        "#SpContent_Container", "#SpContent", "#sp-content",
        "main", "[role='main']", "article",
        "#content", "#main-content", "#primary", "#main",
        ".main-content", ".page-content", ".entry-content", ".post-content",
    ]

    for selector in content_selectors:
        try:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                return str(el)
        except Exception:
            continue

    # --- Strategy 3: Strip junk, then find largest content block ---
    soup = strip_junk(soup)

    tables = soup.find_all("table")
    if tables:
        best_table = max(tables, key=lambda t: len(t.get_text(strip=True)))
        if len(best_table.get_text(strip=True)) > 100:
            return str(best_table)

    divs = soup.find_all("div")
    if divs:
        best = max(divs, key=lambda d: len(d.get_text(strip=True)))
        if len(best.get_text(strip=True)) > 100:
            return str(best)

    return str(soup)


def learn_detail_selectors(sample_htmls: list, domain: str) -> dict:
    """Ask Haiku to identify CSS selectors from sample detail pages.

    Receives 3-4 cleaned detail page HTMLs, sends them to Haiku,
    gets back absolute CSS selectors for each field.
    Result is cached with a 'detail_' prefix to avoid colliding with
    listing-page selectors.
    """
    # Clean and truncate each sample — 8000 chars to ensure contact section is included
    # (detail panels often have description/images before the contact info at the bottom)
    samples = []
    for html in sample_htmls[:DETAIL_SAMPLE_COUNT]:
        cleaned = clean_detail_html(html)
        samples.append(cleaned[:8000])

    combined = "\n\n---PAGE BREAK---\n\n".join(samples)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Analyze these {len(samples)} detail page HTML samples from the same directory website.
Each page shows info about ONE listing (a company, person, provider, restaurant, practice, etc.). Return CSS selectors to extract data from any detail page on this site.

Return ONLY a JSON object (no markdown) with these keys:
- company_name: CSS selector for the primary name (company, person, practice, restaurant — usually in an h1, h2, or b.big)
- description: selector for description/about text
- category: selector for category or classification
- website: selector for website link (the <a> tag with the URL)
- phone: selector for phone number
- fax: selector for fax number
- street_address: selector for street/physical address
- mailing_address: selector for mailing address
- contact_name: selector for contact person name (or null)
- contact_email: selector for contact email (or null)

Rules:
- ALL selectors are ABSOLUTE (from document root)
- Use ID selectors (#tdWorkPhone), class selectors (.member-phone), or tag selectors as needed
- If a field doesn't exist in the samples, use null
- Never use :contains() pseudo-selectors (not supported by BeautifulSoup)
- For phone/website: target the element containing the text (could be <a>, <td>, <div>, <span>, etc.)

HTML SAMPLES:
{combined}"""
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
    if not selectors.get("company_name"):
        print(f"  Haiku returned no company_name selector for {domain}, skipping cache")
        return selectors

    cache_key = f"detail_{domain}"
    set_cached_selectors(cache_key, selectors)
    return selectors


# ───────────────────────────────────────────
#  DETAIL PAGE SELECTOR APPLICATION (BS4)
# ───────────────────────────────────────────

def apply_detail_selectors(raw_html: str, selectors: dict) -> dict:
    """Apply learned selectors to extract member data from a single detail page.
    Pure BeautifulSoup — no AI calls."""
    soup = BeautifulSoup(raw_html, "html.parser")

    def get_text(sel):
        """Extract text from an absolute selector."""
        if not sel or not str(sel).strip():
            return None
        try:
            el = soup.select_one(sel)
            if not el:
                return None
            text = el.get_text(strip=True)
            # Strip common label prefixes like "Phone:" or "Website:"
            text = re.sub(r'^[\w\s]+:\s*', '', text)
            return text or None
        except Exception:
            return None

    def get_href(sel):
        """Extract href (or text fallback) from an absolute selector."""
        if not sel or not str(sel).strip():
            return None
        try:
            el = soup.select_one(sel)
            if not el:
                return None
            return el.get("href") or el.get_text(strip=True)
        except Exception:
            return None

    # Build contacts list
    contacts = []
    contact_name = get_text(selectors.get("contact_name"))
    contact_email = None
    email_sel = selectors.get("contact_email")
    if email_sel:
        try:
            el = soup.select_one(email_sel)
            if el:
                href = el.get("href", "")
                if "mailto:" in str(href):
                    contact_email = str(href).replace("mailto:", "").strip()
                else:
                    contact_email = el.get_text(strip=True)
        except Exception:
            pass

    if contact_name or contact_email:
        contacts.append({"name": contact_name, "email": contact_email})

    return {
        "company_name":    get_text(selectors.get("company_name")),
        "description":     get_text(selectors.get("description")),
        "category":        get_text(selectors.get("category")),
        "website":         get_href(selectors.get("website")),
        "phone":           get_text(selectors.get("phone")),
        "fax":             get_text(selectors.get("fax")),
        "street_address":  get_text(selectors.get("street_address")),
        "mailing_address": get_text(selectors.get("mailing_address")),
        "contacts":        contacts,
    }


# ───────────────────────────────────────────
#  REGEX FALLBACK FOR DETAIL PAGES
# ───────────────────────────────────────────

def regex_extract_from_detail_html(raw_html: str, domain: str) -> dict:
    """Extract member data from a detail page using regex fallback.
    Uses clean_detail_html() to isolate the detail panel first,
    then applies the same regex extraction used for listing cards."""
    cleaned = clean_detail_html(raw_html)
    detail_soup = BeautifulSoup(cleaned, "html.parser")
    return regex_extract_from_card(detail_soup, domain)


# ───────────────────────────────────────────
#  VALIDATION
# ───────────────────────────────────────────

def is_detail_extraction_valid(members: list) -> bool:
    """Check if detail page extraction produced real results.
    - At least 50% must have a company_name
    - At least 20% must have some contact info (phone, website, or email)
    """
    if not members:
        return False

    with_name = sum(1 for m in members if m.get("company_name"))
    if with_name < len(members) * 0.5:
        return False

    with_contact = sum(
        1 for m in members
        if m.get("phone") or m.get("website") or
           (m.get("contacts") and any(c.get("email") for c in m["contacts"]))
    )
    return with_contact >= len(members) * 0.2


# ───────────────────────────────────────────
#  LINK COLLECTION HELPER (used by browser.py)
# ───────────────────────────────────────────

def collect_page_links(page) -> list:
    """Collect all <a href> links from the current page with nav context.

    Returns list of dicts: [{"href": str, "inNav": bool}, ...]
    Called from browser.py during browsing to accumulate links across
    multiple paginated pages.
    """
    try:
        return page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.href,
                inNav: !!(
                    el.closest('nav') ||
                    el.closest('header') ||
                    el.closest('footer') ||
                    el.closest('[role="navigation"]') ||
                    el.closest('[class*="menu"]')
                )
            }))"""
        )
    except Exception:
        return []


# ───────────────────────────────────────────
#  API FAST PATH: Detect & use JSON API endpoints
# ───────────────────────────────────────────

def _extract_uid_from_url(url: str) -> str:
    """Extract a UID/ID from a detail URL. Works for hash and path-based URLs."""
    # Hash-based: ...#!biz/id/68fbd440c81c665af209c70d
    hash_match = re.search(r'[/#]([0-9a-f]{24})(?:/|$)', url)
    if hash_match:
        return hash_match.group(1)
    # Numeric ID in query: ?id=12345
    query_match = re.search(r'[?&]\w*id\w*=(\d+)', url, re.IGNORECASE)
    if query_match:
        return query_match.group(1)
    # Numeric ID in path: /members/12345
    path_match = re.search(r'/(\d{3,})(?:/|$|\?)', url)
    if path_match:
        return path_match.group(1)
    return ""


def _detect_detail_api(sample_urls: list) -> dict | None:
    """Navigate to one detail page and listen for API calls that return member JSON.

    If the page's JavaScript makes a fetch/XHR that returns JSON containing the
    member's UID, we've found the API pattern.

    Returns:
        {"template": "https://api.example.com/v2/account/{uid}/profile",
         "headers": {...}} or None
    """
    if not sample_urls:
        return None

    url = sample_urls[0]
    uid = _extract_uid_from_url(url)
    if not uid:
        return None

    api_responses = []

    def on_response(response):
        try:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            resp_url = response.url
            # Must contain the UID in the URL — that's the per-member API call
            if uid not in resp_url:
                return
            body = response.text()
            if uid in body and len(body) > 50:
                api_responses.append({
                    "url": resp_url,
                    "headers": dict(response.request.headers),
                    "body": body,
                })
        except Exception:
            pass

    print(f"  Probing for API endpoint (navigating to first detail page)...")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            from playwright_stealth import Stealth
            Stealth(
                webgl_vendor=True,
                webgl_renderer_override="Intel Iris OpenGL Engine",
                webgl_vendor_override="Intel Inc.",
                navigator_hardware_concurrency=True,
                sec_ch_ua=True,
            ).apply_stealth_sync(page)
        except ImportError:
            pass
        block_unnecessary_resources(page)
        page.on("response", on_response)

        try:
            page.goto(url, timeout=15000)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"  API probe failed: {e}")
            browser.close()
            return None

        browser.close()

    if not api_responses:
        print(f"  No API endpoint detected, falling back to HTML crawl")
        return None

    # Pick the best API response (most data)
    best = max(api_responses, key=lambda r: len(r["body"]))
    api_url = best["url"]

    # Build a URL template by replacing the UID with {uid}
    template = api_url.replace(uid, "{uid}")
    # Copy relevant headers (auth tokens, API keys, etc.)
    headers = {k: v for k, v in best["headers"].items()
               if k.lower() not in ("host", "connection", "content-length",
                                     "accept-encoding", "user-agent")}

    # Verify the template works — try parsing the response as JSON
    try:
        data = json.loads(best["body"])
        if not isinstance(data, dict):
            return None
        # Must have name-like field
        has_name = any(k.lower() in ("nam", "name", "companyname", "company_name",
                                      "businessname", "title", "displayname",
                                      "providername", "practicename", "firmname",
                                      "restaurantname", "doctorname", "fullname",
                                      "entityname", "officename", "attorneyname")
                       for k in data.keys())
        if not has_name:
            return None
    except (json.JSONDecodeError, ValueError):
        return None

    return {"template": template, "headers": headers}


def _fetch_all_via_api(api_pattern: dict, detail_urls: list) -> list:
    """Fetch all member profiles via direct API calls. No browser needed.

    Args:
        api_pattern: {"template": "...{uid}...", "headers": {...}}
        detail_urls: Original detail URLs (used to extract UIDs)

    Returns:
        List of member dicts, or empty list if too many failures.
    """
    template = api_pattern["template"]
    headers = api_pattern["headers"]
    # Add a reasonable user-agent
    headers["user-agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    uids = []
    for url in detail_urls:
        uid = _extract_uid_from_url(url)
        if uid:
            uids.append(uid)

    if not uids:
        return []

    total = len(uids)
    print(f"  Fetching {total} member profiles via API (fast path)...")

    all_members = []
    failed = 0

    for i, uid in enumerate(uids):
        api_url = template.replace("{uid}", uid)
        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
                if resp.status != 200:
                    failed += 1
                    if failed <= 3:
                        print(f"    API error for {uid}: HTTP {resp.status}")
                    elif failed == 4:
                        print(f"    (suppressing further API errors)")
                    if failed >= 20:
                        print(f"  Too many API failures ({failed}), aborting fast path")
                        return []
                    continue

                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    all_members.append(data)

        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"    API error for {uid}: {e}")
            continue

        # Progress reporting
        done = i + 1
        if done % 50 == 0 or done == total:
            print(f"    Progress: {done}/{total} fetched ({len(all_members)} OK)")

        # Small delay to be polite
        time.sleep(random.uniform(0.1, 0.3))

    print(f"  API fast path complete: {len(all_members)} members fetched")
    return all_members


# ───────────────────────────────────────────
#  MAIN CRAWL ENTRY POINT
# ───────────────────────────────────────────

def crawl_detail_pages(detail_urls: list, domain: str) -> list:
    """Crawl individual member detail pages using a headless browser.

    Flow:
    1. Check cache for detail selectors
    2. If not cached: crawl sample pages → learn selectors with Haiku → validate
    3. Crawl all remaining pages → apply selectors with BS4 (zero AI cost)

    Args:
        detail_urls: List of detail page URLs to crawl
        domain: Site domain (for cache key)

    Returns:
        List of parsed member dicts
    """
    if not detail_urls:
        return []

    cache_key = f"detail_{domain}"
    cached = get_cached_selectors(cache_key)

    all_members = []
    sample_htmls = []
    use_regex_fallback = False
    use_merge_mode = False

    total = len(detail_urls)
    print(f"\n  Starting detail page crawl ({total} pages)...")

    # --- Fast path: detect API endpoints behind detail pages ---
    # Navigate to one detail page with a network listener. If the SPA makes
    # an API call that returns JSON with the member's data, we can skip
    # Playwright entirely and fetch all members via direct HTTP requests.
    api_pattern = _detect_detail_api(detail_urls[:1])
    if api_pattern:
        print(f"  API endpoint detected: {api_pattern['template']}")
        api_members = _fetch_all_via_api(api_pattern, detail_urls)
        if api_members:
            return api_members

    # Detect if detail URLs use hash-fragment routing (SPA pattern)
    is_hash_route = any("#" in url for url in detail_urls[:3])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            from playwright_stealth import Stealth
            Stealth(
                webgl_vendor=True,
                webgl_renderer_override="Intel Iris OpenGL Engine",
                webgl_vendor_override="Intel Inc.",
                navigator_hardware_concurrency=True,
                sec_ch_ua=True,
            ).apply_stealth_sync(page)
        except ImportError:
            pass
        block_unnecessary_resources(page)

        def _navigate_detail(url):
            """Navigate to a detail page URL — handles both regular and hash-fragment URLs.
            For hash URLs (SPA routes like #!biz/id/xxx), changes the hash via JS
            and waits for the SPA to render, since page.goto() may not re-navigate
            when only the hash changes."""
            if is_hash_route and "#" in url:
                base_url = url.split("#")[0]
                hash_fragment = url.split("#", 1)[1]
                current_base = page.url.split("#")[0]

                if current_base.rstrip("/") != base_url.rstrip("/"):
                    # First visit — full navigation needed
                    page.goto(url, timeout=15000)
                else:
                    # Already on the same page — just change the hash
                    page.evaluate(f"window.location.hash = '{hash_fragment}'")

                # Wait for SPA to render the new member profile
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                except Exception:
                    pass
                # Extra wait for SPA rendering (hash changes don't trigger full navigation)
                page.wait_for_timeout(2000)
            else:
                page.goto(url, timeout=15000)
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                except Exception:
                    pass

        # ── Phase 1: Learn selectors from sample pages ──
        if not cached:
            sample_urls = detail_urls[:DETAIL_SAMPLE_COUNT]
            print(f"  Phase 1: Crawling {len(sample_urls)} sample pages for selector learning...")

            for i, url in enumerate(sample_urls):
                try:
                    _navigate_detail(url)
                    html = page.content()
                    sample_htmls.append(html)
                    print(f"    Sample {i + 1}/{len(sample_urls)}: OK")
                    time.sleep(random.uniform(DETAIL_CRAWL_DELAY_MIN, DETAIL_CRAWL_DELAY_MAX))
                except Exception as e:
                    print(f"    Sample {i + 1}/{len(sample_urls)}: FAILED — {e}")

            if len(sample_htmls) < 2:
                print("  ERROR: Not enough sample pages loaded, aborting detail crawl")
                browser.close()
                return []

            # Learn selectors from samples
            print("  Learning detail page selectors via Haiku...")
            try:
                selectors = learn_detail_selectors(sample_htmls, domain)
                print(f"  Selectors learned: {json.dumps({k: v for k, v in selectors.items() if v}, indent=2)}")
            except Exception as e:
                print(f"  ERROR: Failed to learn detail selectors — {e}")
                browser.close()
                return []

            # Validate on the sample pages
            sample_members = [apply_detail_selectors(html, selectors) for html in sample_htmls]
            if not is_detail_extraction_valid(sample_members):
                print("  Detail selectors failed validation, trying regex fallback...")
                regex_sample_members = [
                    regex_extract_from_detail_html(html, domain) for html in sample_htmls
                ]
                if is_detail_extraction_valid(regex_sample_members):
                    print("  Regex fallback succeeded on sample pages!")
                    use_regex_fallback = True
                    all_members.extend(regex_sample_members)
                else:
                    # Try merging selector + regex results
                    merged_samples = [
                        _merge_member_data(sel, reg)
                        for sel, reg in zip(sample_members, regex_sample_members)
                    ]
                    if is_detail_extraction_valid(merged_samples):
                        print("  Merged selector+regex succeeded on sample pages!")
                        use_merge_mode = True
                        all_members.extend(merged_samples)
                    else:
                        print("  ERROR: All detail extraction methods failed")
                        delete_cached_selectors(cache_key)
                        browser.close()
                        return []
            else:
                all_members.extend(sample_members)

            remaining_urls = detail_urls[DETAIL_SAMPLE_COUNT:]
            print(f"  Selectors validated! {len(all_members)} members from samples.")
        else:
            selectors = cached
            remaining_urls = detail_urls
            print(f"  Using cached detail selectors for {domain}")

        # ── Phase 2: Crawl all remaining pages ──
        remaining_count = len(remaining_urls)
        if remaining_count > 0:
            print(f"  Phase 2: Crawling {remaining_count} remaining detail pages...")

        failed = 0
        consecutive_429s = 0

        # Adaptive throttle: tracks last N response times to adjust delay
        recent_times = []
        current_delay = DETAIL_CRAWL_DELAY_MAX  # start conservative

        for i, url in enumerate(remaining_urls):
            try:
                t_start = time.time()
                _navigate_detail(url)
                response_time = time.time() - t_start

                # Check for rate limiting (page might load but show a 429/403 message)
                # If navigation itself threw, we'd be in the except block
                html = page.content()

                # Track response times (rolling window of last 10)
                recent_times.append(response_time)
                if len(recent_times) > 10:
                    recent_times.pop(0)

                # Adjust delay based on server speed
                avg_time = sum(recent_times) / len(recent_times)
                if consecutive_429s > 0:
                    # Back off: double delay for each consecutive 429, cap at 5s
                    current_delay = min(5.0, DETAIL_CRAWL_DELAY_MAX * (2 ** consecutive_429s))
                elif avg_time < 0.3 and len(recent_times) >= 5:
                    # Server is fast — reduce delay (floor 0.15s)
                    current_delay = max(0.15, avg_time * 0.5)
                elif avg_time < 0.8 and len(recent_times) >= 5:
                    # Server is moderate — use shorter delay
                    current_delay = max(0.3, avg_time * 0.6)
                else:
                    # Server is slow or we don't have enough data yet — stay conservative
                    current_delay = DETAIL_CRAWL_DELAY_MAX

                consecutive_429s = 0  # reset on success

                if use_regex_fallback:
                    member = regex_extract_from_detail_html(html, domain)
                elif use_merge_mode:
                    sel_member = apply_detail_selectors(html, selectors)
                    reg_member = regex_extract_from_detail_html(html, domain)
                    member = _merge_member_data(sel_member, reg_member)
                else:
                    member = apply_detail_selectors(html, selectors)

                if member.get("company_name"):
                    all_members.append(member)

                # Progress reporting
                done = i + 1
                if done % 25 == 0 or done == remaining_count:
                    print(f"    Progress: {done}/{remaining_count} pages crawled "
                          f"({len(all_members)} members extracted, delay={current_delay:.2f}s)")

                time.sleep(current_delay + random.uniform(0, 0.15))

            except Exception as e:
                failed += 1
                err_str = str(e).lower()
                if "429" in err_str or "rate" in err_str or "too many" in err_str:
                    consecutive_429s += 1
                    current_delay = min(5.0, DETAIL_CRAWL_DELAY_MAX * (2 ** consecutive_429s))
                    print(f"    Rate limited! Backing off to {current_delay:.1f}s delay")
                    time.sleep(current_delay)
                elif failed <= 5:
                    print(f"    Error crawling page {i + 1}: {e}")
                elif failed == 6:
                    print(f"    (suppressing further error messages)")
                continue

        browser.close()

    if failed > 0:
        print(f"  {failed}/{remaining_count} pages failed to load")
    print(f"  Detail crawl complete: {len(all_members)} members extracted")
    return all_members