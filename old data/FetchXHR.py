from playwright.sync_api import sync_playwright, Playwright
from urllib.parse import urlparse
#import dependencies
import random
import re
import time
import json
import os
import threading
import anthropic
from bs4 import BeautifulSoup
from collections import Counter

#APIS KEYS FOR AI
os.environ["ANTHROPIC_API_KEY"] = "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"


idle_timeout = [4]  #default time out

# --- SELECTOR CACHE ---
# Stores learned CSS selectors per domain so Haiku is only called once per site ever
_selector_cache = {}
SELECTOR_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selector_cache.json")

def load_selector_cache():
    global _selector_cache
    if os.path.exists(SELECTOR_CACHE_FILE):
        with open(SELECTOR_CACHE_FILE, "r") as f:
            _selector_cache = json.load(f)
        print(f"Loaded {len(_selector_cache)} cached selector mappings")

def save_selector_cache():
    with open(SELECTOR_CACHE_FILE, "w") as f:
        json.dump(_selector_cache, f, indent=4)

load_selector_cache()


def find_directory_url(page, link):
    page.goto(link)
    # Grab all links from the page
    links = page.eval_on_selector_all("a", "els => els.map(el => ({text: el.innerText, href: el.href}))")

    # Zero pass - prioritize any link that goes to a search page URL
    search_url_keywords = ["search", "find-a-member", "find_a_member", "member-search", "member_search"]
    for l in links:
        if any(kw in l["href"].lower() for kw in search_url_keywords):
            print("Found search page via URL pattern:", l["href"])
            return l["href"]

    # First pass - priority keywords in link text
    priority_keywords = ["directory", "find a member", "company directory", "member directory", "member search", "find a contractor", "find contractor", "search members", "member list", "our members"]
    for l in links:
        if any(kw in l["text"].lower() for kw in priority_keywords):
            print("Found directory link:", l["href"])
            return l["href"]

    # Second pass - check href URLs for directory-like patterns
    url_keywords = ["directory", "members", "member-list"]
    for l in links:
        if any(kw in l["href"].lower() for kw in url_keywords):
            print("Found directory link via URL pattern:", l["href"])
            return l["href"]

    # Third pass - fallback keywords in link text
    fallback_keywords = ["membership", "contractor", "search", "find", "members"]
    for l in links:
        if any(kw in l["text"].lower() for kw in fallback_keywords):
            print("Found directory link:", l["href"])
            return l["href"]

    return link

def trigger_search_if_exists(page):
    try:
        search = page.locator(
            "input[type='search'], "
            "input[placeholder*='search' i], "
            "input[placeholder*='name' i], "
            "input[placeholder*='find' i], "
            "input[placeholder*='filter' i], "
            "input[id*='search' i], "
            "input[name*='search' i], "
            "input[id*='find' i], "
            "input[name*='find' i], "
            "input[id*='query' i], "
            "input[name*='query' i], "
            "input[id*='keyword' i], "
            "input[name*='keyword' i]"
        ).first
        if search.is_visible():
            print("Search input detected, triggering broad search with 'a'")
            try:
                search.click()
                search.fill("")
                search.type("a", delay=100)
                page.wait_for_timeout(500)
                search.press("Enter")
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                print("Search triggered successfully")
                return True
            except Exception as e:
                print("Error during search interaction:", e)
    except Exception as e:
        print("Error finding search input:", e)
    print("No search input detected, using scroll-based scraping")
    return False

LAYOUT_CLASS_FRAGMENTS = [
    "fl-row", "fl-col", "fl-module",         # Beaver Builder
    "elementor-section", "elementor-column",  # Elementor
    "wp-block",                               # Gutenberg
    "vc_row", "vc_column",                    # WPBakery
]

def is_layout_class(cls_string):
    classes = cls_string.lower().split()
    exact_blacklist = {"container", "wrapper", "layout", "header", "footer", "nav", "sidebar"}
    fragment_blacklist = ["fl-row", "fl-col", "fl-module", "elementor-section",
                          "elementor-column", "wp-block", "vc_row", "vc_column"]
    if any(cls in exact_blacklist for cls in classes):
        return True
    if any(frag in cls_string.lower() for frag in fragment_blacklist):
        return True
    return False

def has_card_structure(el):
    has_link = bool(el.find("a"))
    text_tags = el.find_all(["p", "span", "h1", "h2", "h3", "h4", "h5", "address"])
    return has_link and len(text_tags) >= 2
# --- SELECTOR LEARNING ---

def extract_sample_html(raw_html: str) -> str:
    """Extract a small sample containing complete member cards for selector learning."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "svg", "img"]):
        tag.decompose()

    candidate_tags = ["tr", "article", "figure", "li", "div"]

    for tag in candidate_tags:
        elements = soup.find_all(tag)

        # Pre-filter: must have a link, 3+ child elements, 100+ chars
        elements = [
            el for el in elements
            if el.find("a")
            and len(el.find_all()) >= 3
            and len(el.get_text(strip=True)) > 100
        ]

        class_counts = Counter(
            " ".join(el.get("class") or []) for el in elements if el.get("class")
        )

        repeating = [
            (cls, count) for cls, count in class_counts.items()
            if count >= 4 and not is_layout_class(cls)
        ]

        if not repeating:
            continue

        def avg_text_len(cls):
            samples = soup.find_all(tag, class_=" ".join(cls.split()))[:4]
            return sum(len(s.get_text(strip=True)) for s in samples) / max(len(samples), 1)

        best_cls = max(repeating, key=lambda x: avg_text_len(x[0]))[0]

        cards = soup.find_all(tag, class_=best_cls.split())
        cards = [c for c in cards if has_card_structure(c)]

        if len(cards) >= 3 and len(cards[0].get_text(strip=True)) > 100:
            sample = "\n".join(str(c) for c in cards[:4])
            print(f"  Sample: found repeating '{best_cls}' ({len(cards)} total cards), sending first 6 to learn selectors")
            return sample

    print("  Sample: no repeating cards found, sending first 5000 chars")
    return str(soup)[:5000]


def learn_selectors(raw_html: str, domain: str) -> dict:
    """Ask Haiku to identify CSS selectors from a small sample - called ONCE per domain ever."""
    sample = extract_sample_html(raw_html)

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

    raw = response.content[0].text.strip() # type: ignore
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    selectors = json.loads(raw.strip())
    _selector_cache[domain] = selectors
    save_selector_cache()
    print(f"  Learned and cached selectors for {domain}")
    return selectors


def apply_selectors(raw_html: str, selectors: dict) -> list:
    """Apply learned CSS selectors to extract all members - pure BeautifulSoup, zero AI cost."""
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
            if not sel or not str(sel).strip():
                return None
            try:
                el = card.select_one(sel)
                if not el:
                    return None
                text = el.get_text(strip=True)
                text = re.sub(r'^[\w\s]+:\s*', '', text)
                return text or None
            except Exception:
                return None

        def get_href(sel):
            if not sel or not str(sel).strip():
                return None
            try:
                el = card.select_one(sel)
                if not el:
                    return None
                return el.get("href") or el.get_text(strip=True)
            except Exception:
                return None

        # Extract contact sub-blocks
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
                        "email": (email_el.get("href", "").replace("mailto:", "") or email_el.get_text(strip=True)) if email_el else None #type: ignore
                    })
            except Exception:
                pass

        members.append({
            "company_name":    get_text(selectors.get("company_name")),
            "description":     get_text(selectors.get("description")),
            "category":        get_text(selectors.get("category")),
            "website":         get_href("a[href^='http']") or get_href(selectors.get("website")),
            "phone":           get_text(selectors.get("phone")),
            "fax":             get_text(selectors.get("fax")),
            "street_address":  get_text(selectors.get("street_address")),
            "mailing_address": get_text(selectors.get("mailing_address")),
            "contacts":        contacts
        })

    return members


def is_extraction_valid(members: list) -> bool:
    """Check if selector-based extraction produced real results - validates before accepting."""
    if not members:
        return False
    scalar_keys = ["company_name", "description", "category", "website", "phone"]
    null_counts = sum(
        1 for m in members
        for k in scalar_keys
        if not m.get(k)
    )
    total = len(members) * len(scalar_keys)
    return (null_counts / total) < 0.7 if total else False


def parse_member_html_with_ai(raw_html: str, domain: str = "unknown") -> list:
    """Parse member directory HTML using learned CSS selectors.
    Step 1: check cache for known selectors → apply free BS4 parsing
    Step 2: learn selectors from small sample (one cheap Haiku call) → apply free BS4 parsing"""

    # Step 1 - use cached selectors if available (zero AI cost)
    if domain in _selector_cache:
        print(f"  Using cached selectors for {domain}")
        members = apply_selectors(raw_html, _selector_cache[domain])
        if is_extraction_valid(members):
            return members
        print(f"  Cached selectors invalid for {domain}, re-learning...")
        del _selector_cache[domain]

    # Step 2 - learn selectors from a small sample (cheap - only a few cards sent to Haiku)
    print(f"  Learning selectors for {domain}...")
    try:
        selectors = learn_selectors(raw_html, domain)
        members = apply_selectors(raw_html, selectors)
        if is_extraction_valid(members):
            return members
        print(f"⚠️  WARNING: Selector learning failed for {domain} - 0 members extracted")
    except Exception as e:
        print(f"⚠️  WARNING: Selector learning error for {domain}: {e}")

    return []


# --- DATA CLEANING ---

def clean_members(members: list) -> list:
    """Clean and deduplicate extracted member data.
    Runs after extraction - completely separate from scraping/parsing logic."""
    seen_companies = set()
    cleaned = []

    for m in members:
        # --- COMPANY NAME ---
        name = " ".join((m.get("company_name") or "").split())  # strip extra whitespace/newlines
        if not name:
            continue  # skip entries with no company name
        name_key = name.lower().strip()
        if name_key in seen_companies:
            continue  # deduplicate by company name
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
                m[field] = val or None

        # --- WEBSITE ---
        website = m.get("website") or ""
        if website:
            if not website.startswith("http"):
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


def parse_and_save_results(results: list, data_dump_dir: str, domain: str):
    """Parse all captured responses, save both raw and structured data to Data-dump."""
    all_members = []

    for result in results:
        data = result.get("data", {})

        # Already JSON - store directly
        if isinstance(data, dict) and "raw_html" not in data:
            all_members.append(data)

        # HTML from UpdatePanel or raw HTML response - parse with selector strategy
        elif isinstance(data, dict) and "raw_html" in data:
            print(f"Parsing HTML response from {result['url']} with AI...")
            try:
                members = parse_member_html_with_ai(data["raw_html"], domain=domain)
                print(f"  Extracted {len(members)} members")
                all_members.extend(members)
            except Exception as e:
                print(f"  Failed to parse: {e}")

    # Clean and deduplicate all members before saving
    all_members = clean_members(all_members)

    # Sanity check - warn loudly if extraction looks wrong so bad data doesn't go unnoticed
    if len(all_members) < 3:
        print(f"⚠️  WARNING: Only {len(all_members)} members extracted for {domain} - scrape likely failed")
    empty_names = sum(1 for m in all_members if not m.get("company_name"))
    if all_members and empty_names > len(all_members) * 0.3:
        print(f"⚠️  WARNING: {empty_names}/{len(all_members)} members missing company name in {domain} - extraction may be wrong")

    # Save structured output to Data-dump
    structured_path = os.path.join(data_dump_dir, f"{domain}_structured.json")
    with open(structured_path, "w") as f:
        json.dump(all_members, f, indent=4)
    print(f"Saved {len(all_members)} structured members to {structured_path}")

    return all_members


def responsepull(playwright: Playwright, link):
    xhr_list=[]
    results = []
    done = threading.Event()
    idle_timer = None
    idle_timeout[0] = 4  # reset idle timeout at start of each site - prevents previous site's value bleeding over
    browser = playwright.chromium.launch(headless=False)
    #no headless becauses lots of websites will stop this
    page = browser.new_page()
    # Only capture XHR + fetch
    def reset_idle_timer():
        #purpose of this function is to save energy (called evertime a json response)
        nonlocal idle_timer
        if idle_timer:
            idle_timer.cancel()
        # Close browser after N seconds of no new directory responses
        idle_timer = threading.Timer(idle_timeout[0], done.set) # change this value here to change the amount of idle between json response before closure
        idle_timer.start()

    pending_html_responses = []  # store response objects to read body after done

    def on_response(response):
        content_type = response.headers.get("content-type", "")
        print(f"RESPONSE: [{content_type}] {response.url}")

        # Handle JSON responses
        if "application/json" in content_type:
            try:
                data = response.json()
                # Look for directory-like keys
                if any(key in str(data).lower() for key in ["member", "user", "directory", "contact"]):
                    print("Likely directory data at:", response.url)
                    print(data)
                    results.append({
                        "url": response.url,
                        "data": data
                    })
                    reset_idle_timer()
            except:
                pass

        # Handle ASP.NET UpdatePanel and raw HTML responses
        # Only reset timer if URL looks like directory data - not for every page asset
        # previously reset on ALL html/text responses which caused premature closure on fast-loading sites
        elif "text/plain" in content_type or "text/html" in content_type:
            pending_html_responses.append(response)
            url_lower = response.url.lower()
            if any(kw in url_lower for kw in ["member", "directory", "search", "contact", "listing", "result"]):
                reset_idle_timer()

    def human_scroll(page, scroll_target="body", times = 20):
        #purpose of this function is to bypass anti bot stuff
        for _ in range(times):
            if done.is_set():
                break
            distance = random.randint(300,600)
            page.evaluate(f"""document.querySelector('{scroll_target}').scrollBy(0, {distance});""")
            page.mouse.wheel(0,distance)
            #add realism so idk cuz prob anti boy stuff is bad
            time.sleep(random.uniform(0.15,1))
        try:
            container = page.get_by_test_id("scrolling-container")
            container.hover()
            page.mouse.wheel(0, 300)
        except:
            #scrolling-container not found on this site, skip
            pass

    page.on("response", on_response)
    # Find and navigate to directory page
    directory_url = find_directory_url(page, link)
    page.goto(directory_url)
    page.wait_for_load_state("networkidle")
    # If search exists trigger it, otherwise scroll
    search_triggered = trigger_search_if_exists(page)
    if search_triggered:
        idle_timeout[0] = 20 #20 second leeway
        print("idle timeout changed to:", idle_timeout[0])
    reset_idle_timer()  # start timer ONCE after search/scroll decision - not before on page load
    if not search_triggered: #if no search do human scroll
        human_scroll(page, scroll_target='body')
    # Wait until idle timer fires
    done.wait()

     # --- PLAIN HTML FALLBACK ---
    # Always grab the live page HTML directly from the browser DOM
    # Covers sites that render member cards server-side with no XHR/API calls
    try:
        html = page.content()
        if any(kw in html.lower() for kw in ["member", "directory", "contact", "listing"]):
            print(f"Captured plain HTML from: {page.url}")
            results.append({
                "url": page.url,
                "data": {"raw_html": html}
            })
    except Exception as e:
        print(f"Error capturing page HTML: {e}")
    # Read pending HTML response bodies while browser is still open
    print(f"Processing {len(pending_html_responses)} pending HTML responses...")
    for r in pending_html_responses:
        try:
            body = r.body()
            text = body.decode("utf-8", errors="ignore")
            if not text:
                continue
            # Detect ASP.NET UpdatePanel response
            if "updatepanel" in text.lower() and any(kw in text.lower() for kw in ["member", "contact", "directory"]):
                print("ASP.NET UpdatePanel response detected at:", r.url)
                # Extract the HTML chunk from the pipe-delimited format
                # Format: length|#||type|length|updatePanel|id|<HTML>
                parts = text.split("|", 7)
                html_content = parts[7] if len(parts) >= 8 else text
                results.append({
                    "url": r.url,
                    "data": {"raw_html": html_content}
                })
        except Exception as e:
            print(f"Error reading pending response: {e}")

    browser.close()

    print(f"Total results captured: {len(results)}")
    if not results:
        print("No JSON responses were captured!")

    domain = urlparse(link).netloc.replace(".", "_")

    current_dir = os.path.dirname(__file__)  # This is bot directory
    parent_dir = os.path.dirname(current_dir)  # This goes up one level above

    # Create Data-dump in the parent directory
    data_dump_dir = os.path.join(parent_dir, "Data-dump")

    # Create the directory if it doesn't exist
    os.makedirs(data_dump_dir, exist_ok=True)

    # Save raw results to Data-dump
    raw_output_path = os.path.join(data_dump_dir, f"{domain}.json")
    print(f"Attempting to save raw data to: {raw_output_path}")
    with open(raw_output_path, "w") as f:
        json.dump(results, f, indent=4)
    print(f"Saved {len(results)} raw responses to {raw_output_path}")

    # Parse and save structured data to Data-dump
    parse_and_save_results(results, data_dump_dir, domain)
