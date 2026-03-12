"""
Navigation logic for finding directory pages and triggering searches.
Handles: AI-based multi-depth directory URL discovery, smart search strategy.
"""

import re
import json
import anthropic
from urllib.parse import urlparse
from config import (
    SEARCH_INPUT_SELECTORS,
    RESULT_COUNT_SELECTORS,
    RESULT_LINK_SELECTORS, NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
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


def ai_analyze_page(filtered_links: list, page_url: str, has_search_input: bool) -> dict:
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

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{
            "role": "user",
            "content": f"""I'm on {page_url} trying to find the member directory/company search page.
{search_hint}
Here are the links on this page:
{link_list}

Is this already the member directory or search page where I can find member companies?
- If YES (this page has a search form for members or shows member listings), respond: STAY
- If NO but a link leads there, respond: CLICK followed by the link number (e.g. CLICK 7)
- If no directory exists, respond: NONE"""
        }]
    )

    answer = response.content[0].text.strip().upper()  # type: ignore
    print(f"  AI says: {answer}")

    if answer.startswith("STAY"):
        return {"action": "stay"}

    if answer.startswith("CLICK"):
        match = re.search(r'(\d+)', answer)
        if match:
            idx = int(match.group(1))
            if 0 <= idx < len(candidates):
                chosen = candidates[idx]
                print(f"  AI wants to click: [{chosen['text'][:60]}] → {chosen['href'][:100]}")
                return {"action": "click", "index": idx, "link": chosen}

    if answer.startswith("NONE"):
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

        # Check if this page has a search input (strong signal we're on the directory)
        has_search = find_search_input(page) is not None

        print(f"  Depth {depth}: {len(filtered)} links, search_input={has_search}, asking AI...")

        try:
            result = ai_analyze_page(filtered, current_url, has_search)
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
    """Locate a search input on the page. Returns the locator or None."""
    try:
        search = page.locator(SEARCH_INPUT_SELECTORS).first
        if search.is_visible(timeout=2000):
            return search
    except:
        pass
    return None


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


def search_all_letters(page, search_input):
    """Iterate through the alphabet + digits for starts-with search engines.
    The response listener in browser.py captures results from each search."""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    print(f"  Iterating alphabet search ({len(chars)} queries)...")

    for char in chars:
        try:
            search_input.fill("")
            search_input.type(char, delay=100)
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


def try_search_query(page, search_input, query: str) -> int:
    """Execute a single search query and return the visible result count.
    Returns -1 if the search failed or made things worse."""
    try:
        search_input.click()
        search_input.fill("")
        if query:
            search_input.type(query, delay=100)
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


def trigger_search(page, results_list: list) -> bool:
    """Smart search strategy.
    
    Priority order:
    1. Skip if JSON already captured or enough visible results
    2. Try "a" first — works on most sites (contains and starts-with)
    3. If "a" worked, check if starts-with → iterate alphabet if so
    4. Only if "a" failed, try fallbacks: empty → "all" → "*" → "%"
    5. Stop as soon as something works
    """
    search_input = find_search_input(page)
    if not search_input:
        print("No search input detected")
        return False

    print("Search input found...")

    baseline_count = count_visible_results(page)
    baseline_json = len(results_list)
    print(f"  Baseline: {baseline_count} visible results, {baseline_json} JSON responses")

    # If REAL member data was already captured on page load, skip search entirely
    # Check that at least one response is a list of member-like records, not just
    # config files or auth responses that happened to contain directory keywords
    has_member_data = False
    for result in results_list:
        data = result.get("data", {})
        # Check for list of dicts with name-like fields (actual member data)
        if isinstance(data, list) and len(data) >= 3:
            sample = data[0] if data else {}
            if isinstance(sample, dict):
                keys_lower = {k.lower() for k in sample.keys()}
                name_fields = {"name", "companyname", "company_name", "businessname",
                               "organizationname", "title"}
                if keys_lower & name_fields:
                    has_member_data = True
                    break

    if has_member_data:
        print(f"  Already have member data from page load ({len(results_list)} JSON responses), skipping search")
        return True

    # Note: we do NOT skip based on visible result count alone.
    # Many sites show 20-30 cards on page load but have hundreds more behind search.
    # Only confirmed JSON member data (above) should skip search.

    # --- Step 1: Try "a" first (most common, works on most sites) ---
    print(f"  Trying 'a' search...")
    a_count = try_search_query(page, search_input, "a")
    print(f"  'a' search returned ~{a_count} visible results")

    if a_count >= 3:
        # "a" worked! Check if it's a starts-with site
        if is_starts_with_site(page):
            search_all_letters(page, search_input)
        # Either way, we got results
        return True

    # --- Step 2: "a" didn't work — try fallbacks ---
    # These are strategies that might reveal all results without a specific letter
    fallback_strategies = [
        ("empty", ""),
        ("wildcard_all", "all"),
        ("wildcard_star", "*"),
        ("wildcard_percent", "%"),
    ]

    for name, query in fallback_strategies:
        print(f"  Trying fallback '{name}' (query='{query}')...")
        count = try_search_query(page, search_input, query)
        print(f"  '{name}' returned ~{count} visible results")

        # If this strategy reduced results to near zero, revert
        if count < baseline_count and count < 5:
            print(f"  '{name}' reduced results, reverting")
            try_search_query(page, search_input, "")
            continue

        # If it worked, stop trying
        if count >= 3:
            print(f"  '{name}' worked, stopping")
            return True

    # --- Step 3: Nothing worked with visible results, but responses may have been captured ---
    # Check if any JSON was captured during our search attempts
    if len(results_list) > baseline_json:
        print(f"  Search captured {len(results_list) - baseline_json} new JSON responses")
        return True

    print("  No search strategy produced results")
    return False