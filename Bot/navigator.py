"""
Navigation logic for finding directory pages and triggering searches.
Handles: AI-based multi-depth directory URL discovery, smart search strategy.
"""

import re
import anthropic
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
        # Use a lightweight check here — just see if any matching input is visible
        # The full AI-enabled find_search_input is called later in trigger_search
        has_search = False
        try:
            quick_check = page.locator(SEARCH_INPUT_SELECTORS).first
            has_search = quick_check.is_visible(timeout=1000)
        except:
            pass

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
                "content": f"""This page has multiple search inputs. Which one is the member directory search (to search for member companies)?

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
    """Read the result count indicator from the page.
    
    Strategy:
    1. Regex (free, instant) — handles 90% of sites
    2. AI fallback (cheap, ~250 tokens) — handles weird formats
    
    Returns:
        {"type": "all"} — page says it's showing all results
        {"type": "number", "count": 667} — found a specific count
        {"type": "unknown"} — no count indicator found
    """
    text = get_compressed_page_text(page)
    if not text:
        return {"type": "unknown"}

    # --- REGEX FIRST (free) ---

    # Check for "showing all" / "results: all" / "displaying all"
    if re.search(r'(showing|results|displaying|viewing)[:\s]+all', text, re.IGNORECASE):
        return {"type": "all"}
    if re.search(r'(all)\s+(results|members|companies|listings|entries)', text, re.IGNORECASE):
        return {"type": "all"}

    # "Showing X-Y of Z" pattern (most reliable — Z is the total)
    match = re.search(r'(?:of|\/)\s*(\d[\d,]*)\s*(?:results|members|companies|total|entries|listings|records)?', text, re.IGNORECASE)
    if match:
        count = int(match.group(1).replace(",", ""))
        if count > 0:
            return {"type": "number", "count": count}

    # "X results found" / "Results Found: X" / "X members" / "Found X companies"
    match = re.search(r'(\d[\d,]*)\s*(?:results|members|companies|entries|listings|records)\s*(?:found)?', text, re.IGNORECASE)
    if match:
        count = int(match.group(1).replace(",", ""))
        if count > 0:
            return {"type": "number", "count": count}

    # "Results Found: X" / "Results: X" / "Total: X"
    match = re.search(r'(?:results|total|found|count|matches)[:\s]+(\d[\d,]*)', text, re.IGNORECASE)
    if match:
        count = int(match.group(1).replace(",", ""))
        if count > 0:
            return {"type": "number", "count": count}

    # --- AI FALLBACK (only when regex found nothing) ---
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"""I searched "{query}" on a member directory page.
How many total results does the page say it found?

Respond with ONLY one of:
- A number (e.g. "667")
- "all" if it says showing all results
- "unknown" if no count is visible

Page text:
{text}"""
            }]
        )

        answer = response.content[0].text.strip().lower()  # type: ignore
        print(f"    AI read result count: {answer}")

        if answer == "all":
            return {"type": "all"}
        if answer == "unknown":
            return {"type": "unknown"}

        # Try to parse a number
        num_match = re.match(r'^(\d[\d,]*)', answer)
        if num_match:
            count = int(num_match.group(1).replace(",", ""))
            if count > 0:
                return {"type": "number", "count": count}

    except Exception as e:
        print(f"    AI result count failed: {e}")

    return {"type": "unknown"}


# If a strategy returns this many results or more, stop immediately — we have enough
STOP_THRESHOLD = 600


def try_search_query(page, search_input, query: str) -> int:
    """Execute a single search query and return the visible result count.
    Returns -1 if the search failed."""
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
    """Smart search strategy with result count awareness.
    
    Flow:
    1. Skip if confirmed JSON member data already captured
    2. Check if page already shows all results before searching
    3. Try strategies in order, comparing result counts:
       - "a" → "all" → "" → "*" → "%"
       - If any returns "all" or 600+ results → stop immediately
       - If count is low, keep trying and the listener captures everything
       - All responses are captured regardless, dedup handles overlap
    """
    search_input = find_search_input(page)
    if not search_input:
        print("No search input detected")
        return False

    print("Search input found...")

    baseline_json = len(results_list)

    # --- Check for confirmed JSON member data ---
    has_member_data = False
    for result in results_list:
        data = result.get("data", {})
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

    # --- Check if page already shows all results (before any searching) ---
    pre_count = read_result_count(page)
    pre_visible = count_visible_results(page)
    print(f"  Pre-search: count={pre_count}, visible={pre_visible}")
    if pre_count["type"] == "all":
        print(f"  Page already showing all results, no search needed")
        return True
    if pre_count["type"] == "number" and pre_count["count"] >= STOP_THRESHOLD:
        print(f"  Page already showing {pre_count['count']} results, no search needed")
        return True
    if pre_visible >= STOP_THRESHOLD:
        print(f"  Page already showing {pre_visible} visible results, no search needed")
        return True

    # --- Try strategies in order ---
    strategies = [
        ("a", "a"),
        ("all", "all"),
        ("empty", ""),
        ("wildcard_star", "*"),
        ("wildcard_percent", "%"),
    ]

    best_count = 0
    best_strategy = None
    any_results = False

    for name, query in strategies:
        print(f"  Trying '{name}' (query='{query}')...")
        visible = try_search_query(page, search_input, query)

        if visible < 0:
            print(f"  '{name}' search failed, skipping")
            continue

        if visible >= 3:
            any_results = True

        count_info = read_result_count(page, query=query)

        # Determine the best count: use page indicator if available, else visible count
        if count_info["type"] == "number":
            effective_count = count_info["count"]
        elif count_info["type"] == "all":
            effective_count = visible  # "all" is always good
        else:
            effective_count = visible  # unknown — use visible as fallback

        print(f"  '{name}': ~{visible} visible, count={count_info}, effective={effective_count}")

        # Track best result
        if effective_count > best_count:
            best_count = effective_count
            best_strategy = name

        # STOP CHECK: "all" indicator, or high count from page, or lots of visible results
        should_stop = (
            count_info["type"] == "all" or
            (count_info["type"] == "number" and count_info["count"] >= STOP_THRESHOLD) or
            visible >= STOP_THRESHOLD
        )

        if should_stop:
            print(f"  '{name}' is great (effective={effective_count}), stopping")
            if name == "a" and is_starts_with_site(page):
                search_all_letters(page, search_input)
            return True

        # After "a", check if starts-with before moving on
        if name == "a" and visible >= 3 and is_starts_with_site(page):
            print(f"  Detected starts-with site, iterating alphabet")
            search_all_letters(page, search_input)
            return True

    # --- All strategies tried, check what we got ---
    print(f"  Best strategy: '{best_strategy}' with ~{best_count} results")

    # Check if any JSON was captured during search attempts
    if len(results_list) > baseline_json:
        print(f"  Search captured {len(results_list) - baseline_json} new JSON responses")
        return True

    if any_results:
        print(f"  Got partial results from search attempts")
        return True

    print("  No search strategy produced results")
    return False