"""
Navigation logic for finding directory pages and triggering searches.
Handles: AI-based multi-depth directory URL discovery, smart search strategy,
         both single-input search and multi-field form search.
"""

import re
import anthropic
from urllib.parse import urlparse, parse_qs
from debug import debug
from config import (
    SEARCH_INPUT_SELECTORS,
    FORM_INPUT_SELECTORS,
    PREFERRED_NAME_FIELD_LABELS,
    FORM_SUBMIT_SELECTORS,
    RESULT_COUNT_SELECTORS,
    RESULT_LINK_SELECTORS, NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
    EXTERNAL_SKIP_DOMAINS, CATEGORY_URL_KEYWORDS, CATEGORY_SKIP_VISIBLE_THRESHOLD,
)

MAX_NAVIGATION_DEPTH = 3  # max clicks deep to find the directory page


# --- DIRECTORY PAGE DISCOVERY ---

def filter_navigation_links(links: list, source_url: str) -> list:
    """Filter raw page links down to plausible navigation links.
    Removes obvious junk (mailto, tel, anchors, self-links, assets, etc.)
    Returns cleaned list of {text, href, index} dicts."""
    filtered = []
    seen_hrefs = set()

    for l in links:
        href = l.get("href", "")
        text = l.get("text", "").strip()

        if not href or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("#"):
            continue
        if any(href.lower().endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"]):
            continue
        if not href.startswith("javascript:") and (
            href == source_url or href.rstrip("/") == source_url.rstrip("/")
        ):
            continue
        if not text or len(text) > 200:
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        filtered.append({
            "text": text,
            "href": href,
            "index": l.get("index", -1),
        })

    return filtered


def navigate_to_link(page, chosen_link: dict, fallback_url: str) -> str:
    """Navigate to a chosen link — handles both normal URLs and javascript: links.
    Returns the URL we ended up on."""
    href = chosen_link["href"]
    idx = chosen_link["index"]

    if href.startswith("javascript:") and idx >= 0:
        try:
            print(f"  Clicking javascript link (element index {idx})...")
            all_links = page.locator("a")
            all_links.nth(idx).click()
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except:
                pass
            page.wait_for_timeout(2000)
            print(f"  After click, now on: {page.url}")
            return page.url
        except Exception as e:
            print(f"  Error clicking javascript link: {e}")
            return fallback_url
    else:
        return href


def ai_analyze_page(filtered_links: list, page_url: str, has_search_input: bool, page_text: str = "") -> dict:
    """Ask Haiku to analyze the current page:
    - Is this already a directory/search page? (has search input or member listings)
    - If not, which link should we click to get there?

    Returns dict with:
      {"action": "stay"}  — we're already on the directory page
      {"action": "click", "index": 7}  — click link #7 to go deeper
      {"action": "none"}  — no directory found on this site
    """
    candidates = filtered_links[:80]
    link_list = "\n".join(
        f"{i}. [{l['text'][:80]}] → {l['href'][:150]}"
        for i, l in enumerate(candidates)
    )

    search_hint = ""
    if has_search_input:
        search_hint = "\nNOTE: This page has a search input field visible."

    content_hint = ""
    if page_text:
        content_hint = f"\nVisible page content (preview):\n{page_text[:500]}\n"

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": f"""I'm on {page_url} trying to find the directory or search/listing page (for businesses, members, doctors, restaurants, attorneys, providers, or any directory).
{search_hint}{content_hint}
Here are the links on this page:
{link_list}

Is this already a directory, search, or listing page where I can find entries (companies, people, providers, restaurants, etc.)?
- If YES (this page has a search form, shows listings, or shows categories to browse), respond with ONLY: STAY
- If NO but a link leads there, respond with ONLY: CLICK followed by the link number (e.g. CLICK 7)
- If no directory exists, respond with ONLY: NONE

Respond with a single word/command. Do not explain."""
        }]
    )

    answer = response.content[0].text.strip().upper()  # type: ignore
    print(f"  AI says: {answer}")

    # Parse the response — search anywhere in text, not just at the start.
    # Haiku sometimes wraps the command in explanation text.
    if "STAY" in answer:
        return {"action": "stay"}

    # Search for "CLICK" + number anywhere in the response
    click_match = re.search(r'CLICK\s*(\d+)', answer)
    if click_match:
        idx = int(click_match.group(1))
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            print(f"  AI wants to click: [{chosen['text'][:60]}] → {chosen['href'][:100]}")
            return {"action": "click", "index": idx, "link": chosen}

    if "NONE" in answer:
        return {"action": "none"}

    # Fallback — if AI just returned a number, treat it as CLICK
    match = re.match(r'^(\d+)', answer)
    if match:
        idx = int(match.group(1))
        if 0 <= idx < len(candidates):
            chosen = candidates[idx]
            return {"action": "click", "index": idx, "link": chosen}

    return {"action": "none"}


def find_directory_url(page, link: str) -> str:
    """Navigate to a site and find the member directory page.

    Multi-depth: clicks through up to 3 pages to find the actual directory.
    At each page, AI decides: are we there yet, or do we need to click deeper?

    Examples:
    - Depth 1: Homepage → "Member Directory" → lands on search page (done)
    - Depth 2: Homepage → "Membership" → "Find a Member" → search page (done)
    - Depth 0: Homepage already has the directory loaded (done immediately)

    Returns the URL of the page we ended up on.
    """
    page.goto(link)
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
    except:
        pass

    current_url = link
    visited = set()

    for depth in range(MAX_NAVIGATION_DEPTH):
        visited.add(current_url)

        # Grab all links from the current page
        raw_links = page.eval_on_selector_all(
            "a",
            "els => els.map((el, i) => ({text: el.innerText.trim(), href: el.href, index: i}))"
        )

        if not raw_links:
            print(f"  No links found on page, stopping at depth {depth}")
            break

        filtered = filter_navigation_links(raw_links, current_url)
        if not filtered:
            print(f"  No usable links after filtering, stopping at depth {depth}")
            break

        # Check if this page has a DIRECTORY search form (not a site-wide search bar).
        # A site-wide search bar in the nav exists on every page — it's not a signal
        # that we're on the directory page. Only flag form-based directory inputs
        # (Name/Company fields with a submit button) which are specific to directory pages.
        has_search = False
        try:
            form_inputs = page.locator(FORM_INPUT_SELECTORS)
            form_count = form_inputs.count()
            for i in range(form_count):
                inp = form_inputs.nth(i)
                try:
                    if not inp.is_visible(timeout=500):
                        continue
                    # Make sure it's NOT inside a nav/header (site-wide search)
                    in_nav = inp.evaluate("""el => !!(
                        el.closest('nav') ||
                        el.closest('header') ||
                        el.closest('[role="navigation"]') ||
                        el.closest('[role="banner"]')
                    )""")
                    if not in_nav:
                        has_search = True
                        break
                except:
                    continue
        except:
            pass

        # Also check for primary selectors, but only if NOT in nav/header
        if not has_search:
            try:
                search_inputs = page.locator(SEARCH_INPUT_SELECTORS)
                search_count = search_inputs.count()
                for i in range(search_count):
                    inp = search_inputs.nth(i)
                    try:
                        if not inp.is_visible(timeout=500):
                            continue
                        in_nav = inp.evaluate("""el => !!(
                            el.closest('nav') ||
                            el.closest('header') ||
                            el.closest('[role="navigation"]') ||
                            el.closest('[role="banner"]')
                        )""")
                        if not in_nav:
                            has_search = True
                            break
                    except:
                        continue
            except:
                pass

        # Grab visible page text for AI context (helps detect member listings on screen)
        page_text = get_compressed_page_text(page)

        print(f"  Depth {depth}: {len(filtered)} links, search_input={has_search}, asking AI...")
        debug.log("NAV", f"Depth {depth}: {len(filtered)} links, search={has_search}, url={current_url[:100]}")

        try:
            result = ai_analyze_page(filtered, current_url, has_search, page_text=page_text)
        except Exception as e:
            print(f"  AI analysis failed: {e}, stopping here")
            break

        if result["action"] == "stay":
            print(f"  AI says we're on the directory page")
            return current_url

        if result["action"] == "none":
            print(f"  AI found no directory links, stopping")
            break

        if result["action"] == "click":
            chosen = result["link"]
            new_url = navigate_to_link(page, chosen, current_url)

            # If navigate_to_link returned a URL (not a JS click), we need to goto it
            if new_url != current_url and page.url != new_url:
                page.goto(new_url)
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                except:
                    pass

            current_url = page.url
            print(f"  Now on: {current_url}")

            # Avoid loops
            if current_url in visited:
                print(f"  Already visited this URL, stopping")
                break

            continue

    return current_url


# --- SEARCH INPUT & STRATEGIES ---

def find_search_input(page):
    """Locate the member directory search input on the page.

    If only one visible search input → use it.
    If multiple → ask AI which one is the member directory search.

    Returns the Playwright locator or None.
    """
    try:
        all_matches = page.locator(SEARCH_INPUT_SELECTORS)
        match_count = all_matches.count()
    except:
        return None

    if match_count == 0:
        return None

    # Collect info about each visible input
    visible = []
    for i in range(match_count):
        inp = all_matches.nth(i)
        try:
            if not inp.is_visible(timeout=500):
                continue
        except:
            continue

        # Skip honeypot inputs
        try:
            is_honeypot = inp.evaluate("""el => {
                if (el.tabIndex === -1) return true;
                const rect = el.getBoundingClientRect();
                if (rect.left < -100 || rect.top < -100) return true;
                if (rect.width === 0 || rect.height === 0) return true;
                const name = (el.name || '').toLowerCase();
                if (name.startsWith('b_') || name.includes('honeypot') || name.includes('hp_')) return true;
                return false;
            }""")
            if is_honeypot:
                continue
        except:
            pass

        # Grab context about this input for AI
        try:
            info = inp.evaluate("""el => {
                let label = '';
                if (el.id) {
                    const labelEl = document.querySelector('label[for="' + el.id + '"]');
                    if (labelEl) label = labelEl.innerText.trim();
                }
                let nearby = '';
                let parent = el.parentElement;
                for (let i = 0; i < 3 && parent; i++) {
                    nearby = parent.innerText.trim().substring(0, 150);
                    if (nearby.length > 20) break;
                    parent = parent.parentElement;
                }
                return {
                    placeholder: el.placeholder || '',
                    id: el.id || '',
                    name: el.name || '',
                    label: label,
                    nearby: nearby
                };
            }""")
        except:
            info = {}

        visible.append({"index": i, "info": info})

    if not visible:
        return None

    # Only one visible input — use it directly
    if len(visible) == 1:
        return all_matches.nth(visible[0]["index"])

    # Multiple visible inputs — ask AI which is the directory search
    print(f"  Found {len(visible)} search inputs, asking AI to pick...")

    input_descriptions = "\n".join(
        f"{j}. placeholder='{v['info'].get('placeholder', '')}' "
        f"id='{v['info'].get('id', '')}' "
        f"name='{v['info'].get('name', '')}' "
        f"label='{v['info'].get('label', '')}' "
        f"nearby='{v['info'].get('nearby', '')[:80]}'"
        for j, v in enumerate(visible)
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"""This page has multiple search inputs. Which one is the directory search (to search for listings — companies, people, providers, restaurants, etc.)?

{input_descriptions}

Return ONLY the number (e.g. "0" or "1")."""
            }]
        )

        answer = response.content[0].text.strip()  # type: ignore
        match = re.match(r'^(\d+)', answer)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < len(visible):
                chosen = visible[idx]
                print(f"  AI picked input {idx}: {chosen['info'].get('placeholder', chosen['info'].get('id', ''))}")
                return all_matches.nth(chosen["index"])
    except Exception as e:
        print(f"  AI input selection failed: {e}")

    # Fallback — return the first visible one
    print(f"  Falling back to first visible input")
    return all_matches.nth(visible[0]["index"])


def find_form_search(page):
    """Detect multi-field form-based directory search (e.g. Name/Company/City + Continue).

    Tried FIRST in trigger_search (more specific than generic search inputs).

    Strategy:
    1. Find visible text inputs matching FORM_INPUT_SELECTORS
    2. Among them, pick the "name" field (preferred for searching)
    3. Find the nearest submit button
    4. Return (name_input, submit_button) or (None, None)

    Returns:
        Tuple of (input_locator, submit_locator) or (None, None).
    """
    try:
        all_form_inputs = page.locator(FORM_INPUT_SELECTORS)
        form_count = all_form_inputs.count()
    except:
        return None, None

    if form_count == 0:
        return None, None

    # Collect visible form inputs with their labels/context
    # Exclude inputs inside nav/header (those are site-wide search, not directory forms)
    visible_inputs = []
    for i in range(form_count):
        inp = all_form_inputs.nth(i)
        try:
            if not inp.is_visible(timeout=500):
                continue
        except:
            continue

        # Skip honeypot inputs (tabindex=-1, off-viewport, or hidden bot-traps)
        try:
            is_honeypot = inp.evaluate("""el => {
                // tabindex=-1 is a classic honeypot signal
                if (el.tabIndex === -1) return true;
                // Check if element is positioned off-screen
                const rect = el.getBoundingClientRect();
                if (rect.left < -100 || rect.top < -100) return true;
                if (rect.width === 0 || rect.height === 0) return true;
                // Honeypot names: b_name, b_email, hp_field, etc.
                const name = (el.name || '').toLowerCase();
                if (name.startsWith('b_') || name.includes('honeypot') || name.includes('hp_')) return true;
                return false;
            }""")
            if is_honeypot:
                continue
        except:
            pass

        # Skip inputs inside forms that submit to external/non-directory domains
        # (newsletter signups via Mailchimp, Constant Contact, etc.)
        try:
            is_external_form = inp.evaluate("""el => {
                const form = el.closest('form');
                if (!form) return false;
                const action = (form.action || '').toLowerCase();
                const junkDomains = [
                    'list-manage.com', 'mailchimp.com', 'constantcontact.com',
                    'campaignmonitor.com', 'sendgrid.com', 'mailerlite.com',
                    'convertkit.com', 'aweber.com', 'getresponse.com',
                    'hubspot.com', 'salesforce.com', 'pardot.com',
                ];
                return junkDomains.some(d => action.includes(d));
            }""")
            if is_external_form:
                continue
        except:
            pass

        # Skip inputs inside nav/header — they're site-wide search, not directory forms
        try:
            in_nav = inp.evaluate("""el => !!(
                el.closest('nav') ||
                el.closest('header') ||
                el.closest('[role="navigation"]') ||
                el.closest('[role="banner"]')
            )""")
            if in_nav:
                continue
        except:
            pass

        try:
            info = inp.evaluate("""el => {
                let label = '';
                // Check for <td> label in table-based forms (YourMembership pattern)
                let prevTd = el.closest('td')?.previousElementSibling;
                if (prevTd) label = prevTd.innerText.trim();
                // Also check <label for="...">
                if (!label && el.id) {
                    const labelEl = document.querySelector('label[for="' + el.id + '"]');
                    if (labelEl) label = labelEl.innerText.trim();
                }
                // Walk up for nearby text
                let nearby = '';
                let parent = el.parentElement;
                for (let i = 0; i < 3 && parent; i++) {
                    nearby = parent.innerText.trim().substring(0, 150);
                    if (nearby.length > 20) break;
                    parent = parent.parentElement;
                }
                return {
                    placeholder: el.placeholder || '',
                    id: el.id || '',
                    name: el.name || '',
                    label: label,
                    nearby: nearby
                };
            }""")
        except:
            info = {}

        visible_inputs.append({"index": i, "info": info, "locator": inp})

    if not visible_inputs:
        return None, None

    print(f"  Form search: found {len(visible_inputs)} form inputs")

    # --- Pick the "name" field ---
    # Score each input: prefer fields whose label/name/placeholder contains "name"
    best_input = None
    best_score = -1

    for v in visible_inputs:
        info = v["info"]
        score = 0
        # Build a combined text for matching
        combined = " ".join([
            info.get("label", ""),
            info.get("name", ""),
            info.get("placeholder", ""),
            info.get("id", ""),
        ]).lower()

        # Check against preferred label patterns
        for pattern in PREFERRED_NAME_FIELD_LABELS:
            if pattern in combined:
                score += 10
                break

        # Penalize city/state/zip fields — we never want to search by location
        location_words = ["city", "town", "state", "zip", "postal", "address", "county"]
        if any(w in combined for w in location_words):
            score -= 20

        # Penalize employer/company fields slightly (name is better)
        company_words = ["company", "employer", "business", "organization"]
        if any(w in combined for w in company_words):
            score -= 5

        if score > best_score:
            best_score = score
            best_input = v

    if best_input is None:
        best_input = visible_inputs[0]

    input_label = best_input["info"].get("label") or best_input["info"].get("name") or "unknown"
    print(f"  Form search: selected input '{input_label}' (score={best_score})")

    # --- Find the submit button ---
    # Look within the same form element first, then fall back to page-wide search
    submit_btn = None
    try:
        # Try to find the form ancestor of the selected input
        form_locator = best_input["locator"].locator("xpath=ancestor::form")
        if form_locator.count() > 0:
            # Look for submit button within the form
            submit_in_form = form_locator.first.locator(FORM_SUBMIT_SELECTORS).first
            if submit_in_form.is_visible(timeout=1000):
                submit_btn = submit_in_form
                print(f"  Form search: found submit button inside form")
    except:
        pass

    if submit_btn is None:
        # Fall back to page-wide search for submit button
        try:
            # Try within the same table (YourMembership forms use tables, not <form> tags)
            table_locator = best_input["locator"].locator("xpath=ancestor::table")
            if table_locator.count() > 0:
                submit_in_table = table_locator.first.locator(FORM_SUBMIT_SELECTORS).first
                if submit_in_table.is_visible(timeout=1000):
                    submit_btn = submit_in_table
                    print(f"  Form search: found submit button inside table")
        except:
            pass

    if submit_btn is None:
        # Last resort: any visible submit button on the page
        try:
            page_submit = page.locator(FORM_SUBMIT_SELECTORS).first
            if page_submit.is_visible(timeout=1000):
                submit_btn = page_submit
                print(f"  Form search: found submit button on page (fallback)")
        except:
            pass

    if submit_btn is None:
        print(f"  Form search: no submit button found")
        return None, None

    return best_input["locator"], submit_btn


def count_visible_results(page) -> int:
    """Quick estimate of how many member cards are currently visible on the page."""
    for sel in RESULT_COUNT_SELECTORS:
        try:
            count = page.locator(sel).count()
            if count >= 3:
                return count
        except:
            continue

    try:
        return page.locator(RESULT_LINK_SELECTORS).count()
    except:
        return 0


def is_starts_with_site(page) -> bool:
    """After searching 'a', check if results only contain names starting with 'a'.
    If so, this is a starts-with search engine and we need to iterate the alphabet."""
    try:
        names = page.eval_on_selector_all(
            "h2, h3, h4, [class*='name'], [class*='title'], [class*='company']",
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 2 && t.length < 200)"
        )
    except:
        return False

    if len(names) < 3:
        return False

    starts_with_a = sum(1 for n in names if n.lower().startswith("a"))
    ratio = starts_with_a / len(names)

    if ratio > 0.8:
        print(f"  Detected 'starts with' search ({starts_with_a}/{len(names)} start with 'a')")
        return True
    return False


def search_all_letters(page, search_input, submit_btn=None):
    """Iterate through the alphabet + digits for starts-with search engines.
    The response listener in browser.py captures results from each search.

    Args:
        page: Playwright page object
        search_input: The input locator to type into
        submit_btn: Optional submit button locator. If provided, clicks it
                    instead of pressing Enter.
    """
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    print(f"  Iterating alphabet search ({len(chars)} queries)...")

    for char in chars:
        try:
            search_input.fill("")
            search_input.type(char, delay=100)
            if submit_btn:
                submit_btn.click()
            else:
                search_input.press("Enter")
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except:
                pass
            page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
        except Exception as e:
            print(f"  Error searching '{char}': {e}")
            continue

    print("  Alphabet search complete")


def get_compressed_page_text(page) -> str:
    """Grab visible text from the page, compressed for AI input.
    Strips HTML, collapses whitespace, takes first 1000 chars.
    Result is ~250 tokens — cheap to send to Haiku."""
    try:
        text = page.inner_text("body")[:5000]
    except:
        return ""
    # Collapse all whitespace (newlines, tabs, multiple spaces) into single spaces
    text = re.sub(r'\s+', ' ', text).strip()
    # First 1000 chars — count is always near the top, before the member cards
    return text[:1000]


def read_result_count(page, query: str = "") -> dict:
    """Read the result count from the page — regex first, AI fallback.

    Returns:
        {"type": "all"} — page says showing all results
        {"type": "number", "count": N} — found specific count
        {"type": "unknown"} — no count visible
    """
    text = get_compressed_page_text(page)
    if not text:
        return {"type": "unknown"}

    text_lower = text.lower()

    # --- Regex pre-check: catch common "X results" patterns ---
    # This avoids an AI call when the count is in a standard format.
    # Shared entity words for all count patterns
    _E = (
        r'results?|members?|companies?|listings?|records?|'
        r'builders?|vendors?|providers?|businesses?|organizations?|'
        r'doctors?|physicians?|attorneys?|lawyers?|restaurants?|'
        r'clinics?|specialists?|consultants?|therapists?|'
        r'firms?|dentists?'
    )
    result_patterns = [
        # "Results Found: 48", "Results: 48"
        r'results?\s*(?:found)?\s*:\s*(\d[\d,]*)',
        # "48 results found", "48 members found"
        rf'(\d[\d,]*)\s+(?:{_E})\s*(?:found)?',
        # "Showing 48 results", "Displaying 48 members"
        rf'(?:showing|displaying)\s+(\d[\d,]*)\s+(?:{_E})',
        # "1-20 of 48 results", "Showing 1-20 of 48"
        rf'of\s+(\d[\d,]*)\s+(?:{_E}|total)',
        # "Total: 48", "Total Members: 48"
        rf'total\s*(?:{_E})?\s*:\s*(\d[\d,]*)',
    ]

    for pattern in result_patterns:
        match = re.search(pattern, text_lower)
        if match:
            count = int(match.group(1).replace(",", ""))
            if count > 0:
                print(f"    Regex result count: {count}")
                return {"type": "number", "count": count}

    # Check for "all results" / "showing all" phrases
    all_patterns = [
        rf'showing\s+all\s+(?:{_E})',
        rf'all\s+(?:\d[\d,]*\s+)?(?:{_E})',
        r'your\s+search\s+results?\s+include\s+all',
    ]
    for pattern in all_patterns:
        if re.search(pattern, text_lower):
            print(f"    Regex: detected 'all' results")
            return {"type": "all"}

    # --- AI fallback: send more text (first 800 chars) for better coverage ---
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": f"""How many total results does this directory page show?
Reply ONLY: a number, "all", or "unknown".

{text[:800]}"""
            }]
        )

        answer = response.content[0].text.strip().lower()  # type: ignore
        print(f"    AI result count: {answer}")

        if "all" in answer:
            return {"type": "all"}

        num_match = re.match(r'^(\d[\d,]*)', answer)
        if num_match:
            count = int(num_match.group(1).replace(",", ""))
            if count > 0:
                return {"type": "number", "count": count}

        return {"type": "unknown"}

    except Exception as e:
        print(f"    AI result count failed: {e}")
        return {"type": "unknown"}


# If a strategy returns this many results or more, stop immediately — we have enough
STOP_THRESHOLD = 600


def try_search_query(page, search_input, query: str, submit_btn=None) -> int:
    """Execute a single search query and return the visible result count.

    Args:
        page: Playwright page object
        search_input: The input locator to type into
        query: The search query string
        submit_btn: Optional submit button locator. If provided, clicks it
                    instead of pressing Enter. Used for form-based directories
                    where Enter doesn't trigger the search.

    Returns -1 if the search failed.
    """
    try:
        # Short timeout — if the input isn't visible (e.g. collapsed after
        # navigating to a results page), fail fast instead of hanging 30 seconds
        search_input.click(timeout=3000)
        search_input.fill("")
        if query:
            search_input.type(query, delay=100)

        if submit_btn:
            submit_btn.click()
        else:
            search_input.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except:
            pass
        page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)

        return count_visible_results(page)
    except Exception as e:
        print(f"  Search query '{query}' failed: {e}")
        return -1


def try_form_search_query(page, search_input, submit_btn, query: str) -> int:
    """Execute a search query using a multi-field form.

    Tries Enter key first (works on React/SPA forms where button.click()
    may not trigger the onSubmit handler), then clicks the submit button
    as fallback.

    Returns the visible result count on the results page, or -1 on failure.
    """
    try:
        search_input.click(timeout=3000)
        search_input.fill("")
        if query:
            search_input.type(query, delay=100)

        # Store current URL to detect navigation
        url_before = page.url

        # Try Enter first — works on React/SPA forms and standard forms
        search_input.press("Enter")
        page.wait_for_timeout(1000)

        # If nothing happened (no navigation, no new content), click the button
        url_after_enter = page.url
        visible_after_enter = count_visible_results(page)
        if url_after_enter == url_before and visible_after_enter <= 1:
            submit_btn.click()

        # Wait for results to load
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except:
            pass
        page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)

        # If we navigated to a new page, wait a bit more for results to render
        if page.url != url_before:
            print(f"  Form navigated to: {page.url}")
            page.wait_for_timeout(1000)

        return count_visible_results(page)
    except Exception as e:
        print(f"  Form search query '{query}' failed: {e}")
        return -1


def trigger_search(page, results_list: list) -> bool:
    """Smart search strategy with result count awareness.

    Flow:
    1. Skip if confirmed JSON member data already captured
    2. Detect search method: prefer form-based search (more specific) over
       generic site-wide search inputs when both exist
    3. Pre-search: check visible results (skip for form pages)
    4. Search "a" → check starts-with → ask AI for count
    5. If "all" or ≥600: stop
       If "unknown" (no counter): search blank, stop
       If low number: try more strategies ("all", "", "*", "%")
    """
    # --- Detect search method ---
    # Try form-based search FIRST (more specific: Name/Company/City + Submit).
    # If a form exists, it's almost certainly the directory search.
    # Only fall back to generic search inputs if no form is found.
    search_input = None
    submit_btn = None
    is_form_search = False

    form_input, form_submit = find_form_search(page)
    if form_input and form_submit:
        search_input = form_input
        submit_btn = form_submit
        is_form_search = True
        print("  Form-based search detected (Name/Company form with submit button)")
        debug.log("SEARCH", "Form-based search detected")
    else:
        # No form found — try standard single-input search
        search_input = find_search_input(page)
        if search_input:
            print("Search input found...")
            debug.log("SEARCH", "Standard search input found")
        else:
            print("No search input detected (standard or form-based)")
            debug.log("SEARCH", "No search input found on page", level="warn")
            return False

    baseline_json = len(results_list)

    # --- Check for confirmed JSON member data ---
    has_member_data = False
    for result in results_list:
        data = result.get("data", {})

        # Check top-level list
        if isinstance(data, list) and len(data) >= 3:
            sample = data[0] if data else {}
            if isinstance(sample, dict):
                keys_lower = {k.lower() for k in sample.keys()}
                name_fields = {"name", "companyname", "company_name", "businessname",
                               "organizationname", "title", "nam", "displayname",
                               "providername", "practicename", "firmname",
                               "restaurantname", "doctorname", "fullname",
                               "entityname", "officename", "attorneyname"}
                if keys_lower & name_fields:
                    has_member_data = True
                    break
                # Airtable format: name is inside "fields" dict
                if "fields" in keys_lower and isinstance(sample.get("fields"), dict):
                    field_keys = {k.lower() for k in sample["fields"].keys()}
                    if field_keys & name_fields:
                        has_member_data = True
                        break

        # Check nested list inside dict (e.g. {"Status":"OK", "Members":[...]})
        elif isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list) and len(val) >= 3:
                    sample = val[0]
                    if isinstance(sample, dict):
                        keys_lower = {k.lower() for k in sample.keys()}
                        name_fields = {"name", "companyname", "company_name", "businessname",
                                       "organizationname", "title", "nam", "displayname",
                                       "providername", "practicename", "firmname",
                                       "restaurantname", "doctorname", "fullname",
                                       "entityname", "officename", "attorneyname"}
                        if keys_lower & name_fields and len(sample.keys()) >= 5:
                            has_member_data = True
                            break
                        # Airtable format
                        if "fields" in keys_lower and isinstance(sample.get("fields"), dict):
                            field_keys = {k.lower() for k in sample["fields"].keys()}
                            if field_keys & name_fields and len(sample["fields"]) >= 5:
                                has_member_data = True
                                break
            if has_member_data:
                break

    if has_member_data:
        print(f"  Already have member data from page load ({len(results_list)} JSON responses), skipping search")
        return True

    # --- Pre-search: check if page already shows lots of results ---
    # Only use visible count — no AI call. Skip for form pages (form not submitted yet).
    if not is_form_search:
        pre_visible = count_visible_results(page)
        print(f"  Pre-search: {pre_visible} visible results")
        if pre_visible >= STOP_THRESHOLD:
            print(f"  Page already showing {pre_visible} results, no search needed")
            return True
    else:
        print(f"  Form-based search — skipping pre-search check")

    url_before = page.url

    # Pick the right query executor based on search type
    def execute_query(query: str) -> int:
        if is_form_search:
            return try_form_search_query(page, search_input, submit_btn, query)
        else:
            return try_search_query(page, search_input, query, submit_btn=None)

    def go_back_to_form() -> bool:
        """Navigate back to the search page if a search navigated away.
        Works for both form-based and standard search inputs.
        Returns True if successful (or no navigation happened), False if failed."""
        nonlocal search_input, submit_btn
        if page.url == url_before:
            return True  # no navigation happened, nothing to do

        # Check if the search input is still visible on the current page
        try:
            if search_input.is_visible(timeout=1000): #type: ignore
                return True  # input still usable, no need to go back
        except Exception:
            pass

        # Search input is hidden or gone — navigate back
        debug.log("SEARCH", f"Search input not visible after navigation, going back to {url_before[:100]}")
        try:
            page.go_back()
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            page.wait_for_timeout(1000)

            if is_form_search:
                search_input, submit_btn = find_form_search(page)
                if not search_input or not submit_btn:
                    print(f"  Could not re-find form after navigating back")
                    debug.log("SEARCH", "Failed to re-find form after go_back", level="error")
                    return False
            else:
                search_input = find_search_input(page)
                if not search_input:
                    print(f"  Could not re-find search input after navigating back")
                    debug.log("SEARCH", "Failed to re-find search input after go_back", level="error")
                    return False

            debug.log("SEARCH", "Successfully navigated back and re-found search input")
            return True
        except Exception as e:
            print(f"  Error navigating back: {e}")
            debug.log("SEARCH", f"go_back failed: {e}", level="error")
            return False

    # Track the best query to re-execute at the end
    best_visible = 0
    best_query = ""

    # ─────────────────────────────────────────────────
    #  STEP 1: Search "" (blank) — most sites return all results
    # ─────────────────────────────────────────────────
    print(f"  Trying '' (blank)...")
    visible_blank = execute_query("")

    if visible_blank < 0:
        # Blank failed — try "a" as fallback
        print(f"  Blank failed, trying 'a'...")
        if go_back_to_form():
            execute_query("a")
        return len(results_list) > baseline_json

    if visible_blank > best_visible:
        best_visible = visible_blank
        best_query = ""

    # ─────────────────────────────────────────────────
    #  STEP 2: Read result count after blank
    # ─────────────────────────────────────────────────
    count_info = read_result_count(page, query="")
    count_type = str(count_info.get("type", "unknown"))
    count_number = int(count_info.get("count", 0))
    print(f"  '': ~{visible_blank} visible, count: {count_type}"
          f"{f' ({count_number})' if count_type == 'number' else ''}")

    # ─────────────────────────────────────────────────
    #  STEP 3: Decide based on count
    # ─────────────────────────────────────────────────

    # "all" or high count → we have everything, stop
    if count_type == "all":
        print(f"  Blank shows all results, stopping")
        return True
    if count_type == "number" and count_number >= STOP_THRESHOLD:
        print(f"  Blank shows {count_number} results, stopping")
        return True
    if visible_blank >= STOP_THRESHOLD:
        print(f"  Blank shows {visible_blank} visible results, stopping")
        return True

    # ─────────────────────────────────────────────────
    #  STEP 4: Try more strategies to get better results
    # ─────────────────────────────────────────────────
    # "unknown" or low count → try more queries
    best_count = count_number if count_type == "number" else 0
    site_has_counter = count_type != "unknown"

    remaining = [
        ("all", "all"),
        ("a", "a"),
        ("wildcard_percent", "%"),
    ]

    for strat_name, strat_query in remaining:
        if not go_back_to_form():
            break

        print(f"  Trying '{strat_name}' (query='{strat_query}')...")
        visible = execute_query(strat_query)

        if visible < 0:
            print(f"  '{strat_name}' failed, skipping")
            continue

        if visible > best_visible:
            best_visible = visible
            best_query = strat_query

        # --- Special handling for "a": check starts-with ---
        if strat_query == "a" and visible >= 3 and is_starts_with_site(page):
            print(f"  Detected starts-with site, iterating alphabet")
            search_all_letters(page, search_input, submit_btn=submit_btn)
            return True

        # Check visible count threshold
        if visible >= STOP_THRESHOLD:
            print(f"  '{strat_name}': {visible} visible results, stopping")
            return True

        # Read result count (skip AI if site had no counter on blank search)
        if site_has_counter:
            count_info = read_result_count(page, query=strat_query)
            ct = str(count_info.get("type", "unknown"))
            cn = int(count_info.get("count", 0))
            print(f"  '{strat_name}': ~{visible} visible, count: {ct}"
                  f"{f' ({cn})' if ct == 'number' else ''}")

            if ct == "all":
                print(f"  '{strat_name}' shows all results, stopping")
                return True
            if ct == "number" and cn >= STOP_THRESHOLD:
                print(f"  '{strat_name}' shows {cn} results, stopping")
                return True
            if ct == "number" and cn > best_count:
                best_count = cn

            # If counter disappeared, stop trying
            if ct == "unknown":
                print(f"  Counter no longer visible, stopping")
                break
        else:
            print(f"  '{strat_name}': ~{visible} visible (no counter)")

    # --- Re-execute the best query so the page shows the most results ---
    # This ensures the HTML capture in browser.py gets the best page,
    # not the last strategy which may have returned fewer results.
    current_visible = count_visible_results(page)
    if best_visible > current_visible and best_visible > 3:
        print(f"  Re-executing best query '{best_query}' ({best_visible} visible vs current {current_visible})")
        if go_back_to_form():
            execute_query(best_query)

    # --- Done trying strategies ---
    print(f"  Best result count: {best_count}")
    return best_count > 0 or len(results_list) > baseline_json or visible_blank >= 3


# --- VIEW ALL DETECTION ---

def try_view_all(page) -> bool:
    """Detect and click a 'View All' / 'Show All' link or button.

    Only looks in the main content area (not nav/header/footer).
    Returns True if found and clicked, False otherwise.
    """
    VIEW_ALL_SELECTORS = (
        "a:has-text('View All'), a:has-text('view all'), "
        "a:has-text('Show All'), a:has-text('show all'), "
        "a:has-text('See All'), a:has-text('see all'), "
        "a:has-text('All Members'), a:has-text('all members'), "
        "a:has-text('View all members'), a:has-text('Show all members'), "
        "a:has-text('View All Members'), a:has-text('Show All Members'), "
        "button:has-text('View All'), button:has-text('Show All'), "
        "button:has-text('See All'), button:has-text('All Members')"
    )

    try:
        all_matches = page.locator(VIEW_ALL_SELECTORS)
        match_count = all_matches.count()
    except Exception:
        return False

    for i in range(match_count):
        try:
            el = all_matches.nth(i)
            if not el.is_visible(timeout=500):
                continue

            # Must not be in nav/header/footer
            in_nav = el.evaluate("""el => !!(
                el.closest('nav') ||
                el.closest('header') ||
                el.closest('footer') ||
                el.closest('[role="navigation"]') ||
                el.closest('[role="banner"]')
            )""")
            if in_nav:
                continue

            # Text must be short — a real "View All" label, not a sentence
            text = el.inner_text().strip()
            if len(text) > 40:
                continue

            print(f"  Found 'View All' link: '{text}'")
            el.click()
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass
            page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
            return True
        except Exception:
            continue

    return False


# --- CATEGORY DETECTION ---

def detect_category_links(page) -> list:
    """Detect category/browse links on a directory landing page.

    Looks for groups of content-area links that share a URL prefix template
    and have short, descriptive text (typical of category labels like
    "Plumbing", "Electrical", "Roofing").

    Anti-false-positive rules:
    - Skips links inside nav/header/footer/breadcrumbs
    - Skips single characters (alphabet filters) and pure numbers (pagination)
    - Skips external domains
    - Requires 3-50 links with unique text in the same URL group
    - Only triggers when members aren't already visible on page

    Returns:
        List of {"text": str, "href": str} dicts, or [] if none found.
    """
    # Check if members are already visible — if so, no need for categories
    visible = count_visible_results(page)
    if visible >= CATEGORY_SKIP_VISIBLE_THRESHOLD:
        return []

    try:
        links = page.eval_on_selector_all("a[href]", """els => els.map(el => ({
            text: el.innerText.trim(),
            href: el.href,
            inNav: !!(
                el.closest('nav') ||
                el.closest('header') ||
                el.closest('footer') ||
                el.closest('[role="navigation"]') ||
                el.closest('[role="banner"]') ||
                el.closest('[class*="menu"]') ||
                el.closest('[class*="breadcrumb"]')
            )
        }))""")
    except Exception:
        return []

    # Filter: content-area links, short text, not junk
    site_domain = ""
    try:
        site_domain = urlparse(page.url).netloc.lower()
    except Exception:
        pass

    filtered = []
    seen = set()
    for link in links:
        if link.get("inNav"):
            continue
        text = link.get("text", "").strip()
        href = link.get("href", "")
        if not text or not href:
            continue
        # Skip alphabet filters and pagination numbers
        if len(text) <= 2 and (text.isalpha() or text.isdigit()):
            continue
        if text.isdigit():
            continue
        # Category names are short labels
        if len(text) > 60:
            continue
        if href in seen:
            continue
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        # Skip external domains
        try:
            link_domain = urlparse(href).netloc.lower()
            if link_domain and site_domain and link_domain != site_domain:
                if any(d in link_domain for d in EXTERNAL_SKIP_DOMAINS):
                    continue
        except Exception:
            pass
        seen.add(href)
        filtered.append({"text": text, "href": href})

    if len(filtered) < 3:
        return []

    # Group links by URL prefix template
    groups: dict[str, list] = {}
    for link in filtered:
        parsed = urlparse(link["href"])
        path = parsed.path.rstrip("/")

        if parsed.query:
            # Query-param categories: /members?category=X → prefix = /members?category=
            params = parse_qs(parsed.query)
            param_keys = sorted(params.keys())
            prefix = path + "?" + "&".join(f"{k}=" for k in param_keys)
        elif "/" in path and len(path.split("/")) >= 3:
            # Path-based categories: /directory/plumbing → prefix = /directory
            prefix = path.rsplit("/", 1)[0]
        else:
            continue

        groups.setdefault(prefix, []).append(link)

    # Score and pick the best group
    best_group = None
    best_score = 0
    for prefix, group_links in groups.items():
        count = len(group_links)
        if count < 3 or count > 50:
            continue

        # Category links must have mostly unique text (not duplicate labels)
        texts = [l["text"].lower() for l in group_links]
        unique_texts = set(texts)
        if len(unique_texts) < count * 0.7:
            continue

        score = min(count, 30)

        # Bonus if prefix contains category-related keywords
        prefix_lower = prefix.lower()
        if any(kw in prefix_lower for kw in CATEGORY_URL_KEYWORDS):
            score += 20

        # Bonus if link texts are short category-like labels
        avg_len = sum(len(t) for t in texts) / count
        if avg_len < 30:
            score += 10

        if score > best_score:
            best_score = score
            best_group = group_links

    if not best_group:
        return []

    # Deduplicate by href, preserve order
    seen_hrefs: set[str] = set()
    result = []
    for link in best_group:
        if link["href"] not in seen_hrefs:
            seen_hrefs.add(link["href"])
            result.append(link)

    print(f"  Detected {len(result)} category links (score={best_score})")
    return result