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
import random
import anthropic
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from config import (
    DETAIL_CRAWL_DELAY_MIN, DETAIL_CRAWL_DELAY_MAX,
    DETAIL_SAMPLE_COUNT, DETAIL_URL_KEYWORDS,
    NETWORK_IDLE_TIMEOUT,
)
from html_parser import strip_junk
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
        """Replace numeric IDs in URL with {ID} to find repeating patterns."""
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
        return t

    # Known external domains that are never detail pages
    EXTERNAL_DOMAINS = [
        "google.com", "facebook.com", "twitter.com", "linkedin.com",
        "instagram.com", "youtube.com", "yelp.com", "maps.google",
        "goo.gl", "bit.ly", "apple.com", "microsoft.com",
    ]

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
        if any(domain in href_lower for domain in EXTERNAL_DOMAINS):
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
    "phone", "email", "website", "address",
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

        # Take first 50K chars to avoid scanning massive HTML
        sample = html[:50000].lower()

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

def clean_detail_html(raw_html: str) -> str:
    """Strip junk from a detail page HTML, return the main content area."""
    soup = BeautifulSoup(raw_html, "html.parser")
    soup = strip_junk(soup)

    # Try to find the main content container — ordered from most specific to broadest
    content_selectors = [
        # YourMembership / association platforms (most specific)
        "#SpContent_Container", "#SpContent", "#sp-content",
        # Standard HTML5 semantic elements
        "main", "[role='main']", "article",
        # Common CMS content wrappers (ID-based — more specific)
        "#content", "#main-content", "#primary", "#main",
        # Class-based (less specific — could match sidebar/footer divs)
        ".main-content", ".page-content", ".entry-content", ".post-content",
    ]

    for selector in content_selectors:
        try:
            el = soup.select_one(selector)
            if el and len(el.get_text(strip=True)) > 100:
                return str(el)
        except Exception:
            continue

    # Fallback: look for tables with member data (YourMembership uses ViewTable1)
    tables = soup.find_all("table")
    if tables:
        # Pick the table with the most text (likely the member info table)
        best_table = max(tables, key=lambda t: len(t.get_text(strip=True)))
        if len(best_table.get_text(strip=True)) > 100:
            return str(best_table)

    # Last resort: largest div by text content
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
    # Clean and truncate each sample — 5000 chars to capture full member info
    samples = []
    for html in sample_htmls[:DETAIL_SAMPLE_COUNT]:
        cleaned = clean_detail_html(html)
        samples.append(cleaned[:5000])

    combined = "\n\n---PAGE BREAK---\n\n".join(samples)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Analyze these {len(samples)} member detail page HTML samples from the same website.
Each page shows info about ONE member/company. Return CSS selectors to extract data from any detail page on this site.

Return ONLY a JSON object (no markdown) with these keys:
- company_name: CSS selector for the company/member name (usually in an h1, h2, or b.big)
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
- For phone: target the <td> or <div> that contains the phone number text

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

    total = len(detail_urls)
    print(f"\n  Starting detail page crawl ({total} pages)...")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()

        # ── Phase 1: Learn selectors from sample pages ──
        if not cached:
            sample_urls = detail_urls[:DETAIL_SAMPLE_COUNT]
            print(f"  Phase 1: Crawling {len(sample_urls)} sample pages for selector learning...")

            for i, url in enumerate(sample_urls):
                try:
                    page.goto(url, timeout=15000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                    except Exception:
                        pass
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
                print("  ERROR: Detail selector validation failed — selectors don't extract real data")
                delete_cached_selectors(cache_key)
                browser.close()
                return []

            all_members.extend(sample_members)
            remaining_urls = detail_urls[DETAIL_SAMPLE_COUNT:]
            print(f"  Selectors validated! {len(sample_members)} members from samples.")
        else:
            selectors = cached
            remaining_urls = detail_urls
            print(f"  Using cached detail selectors for {domain}")

        # ── Phase 2: Crawl all remaining pages ──
        remaining_count = len(remaining_urls)
        if remaining_count > 0:
            print(f"  Phase 2: Crawling {remaining_count} remaining detail pages...")

        failed = 0
        for i, url in enumerate(remaining_urls):
            try:
                page.goto(url, timeout=15000)
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                except Exception:
                    pass

                html = page.content()
                member = apply_detail_selectors(html, selectors)
                if member.get("company_name"):
                    all_members.append(member)

                # Progress reporting
                done = i + 1
                if done % 25 == 0 or done == remaining_count:
                    print(f"    Progress: {done}/{remaining_count} pages crawled "
                          f"({len(all_members)} members extracted)")

                time.sleep(random.uniform(DETAIL_CRAWL_DELAY_MIN, DETAIL_CRAWL_DELAY_MAX))

            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"    Error crawling page {i + 1}: {e}")
                elif failed == 6:
                    print(f"    (suppressing further error messages)")
                continue

        browser.close()

    if failed > 0:
        print(f"  {failed}/{remaining_count} pages failed to load")
    print(f"  Detail crawl complete: {len(all_members)} members extracted")
    return all_members