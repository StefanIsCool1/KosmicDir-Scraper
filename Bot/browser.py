"""
Browser automation with Playwright.
Handles: launching browser, capturing responses, human-like scrolling, pagination.
"""

import random
import time
import threading
from config import (
    DEFAULT_IDLE_TIMEOUT, SEARCH_IDLE_TIMEOUT, PAGINATION_IDLE_TIMEOUT,
    NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
    JSON_DIRECTORY_KEYWORDS, JSON_URL_KEYWORDS, JSON_STRUCTURE_FIELDS,
    DIRECTORY_URL_KEYWORDS,
    NEXT_BUTTON_SELECTORS, LOAD_MORE_SELECTORS,
)
from navigator import find_directory_url, trigger_search


def human_scroll(page, done_event, scroll_target="body", times=20):
    """Simulate human-like scrolling to trigger lazy-loaded content.
    Stops early if done_event is set (e.g. idle timer fired)."""
    for _ in range(times):
        if done_event.is_set():
            break
        distance = random.randint(300, 600)
        page.evaluate(f"document.querySelector('{scroll_target}').scrollBy(0, {distance});")
        page.mouse.wheel(0, distance)
        time.sleep(random.uniform(0.15, 1))

    # Try site-specific scroll container (some sites use custom scrollable divs)
    try:
        container = page.get_by_test_id("scrolling-container")
        container.hover()
        page.mouse.wheel(0, 300)
    except:
        pass


def handle_pagination(page, done_event):
    """Click through pagination (Next buttons, Load More) to capture all pages.
    The response listener captures data from each page automatically.
    Returns the number of extra pages loaded."""
    pages_loaded = 0
    max_pages = 100  # safety limit

    while not done_event.is_set() and pages_loaded < max_pages:
        found_next = False

        # --- Try "Next" button ---
        try:
            next_btn = page.locator(NEXT_BUTTON_SELECTORS).first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                # Check it's not a disabled/current-page element
                classes = next_btn.get_attribute("class") or ""
                if "disabled" not in classes.lower() and "active" not in classes.lower():
                    next_btn.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                    except:
                        pass
                    page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
                    pages_loaded += 1
                    print(f"  Pagination: loaded page {pages_loaded + 1}")
                    found_next = True
        except:
            pass

        if found_next:
            continue

        # --- Try "Load More" button ---
        try:
            load_more = page.locator(LOAD_MORE_SELECTORS).first
            if load_more.is_visible(timeout=1000):
                load_more.click()
                page.wait_for_timeout(2000)
                pages_loaded += 1
                print(f"  Load More: click #{pages_loaded}")
                found_next = True
        except:
            pass

        if found_next:
            continue

        # No more pagination controls found
        break

    if pages_loaded > 0:
        print(f"  Pagination complete: loaded {pages_loaded} extra pages")
    return pages_loaded


def capture_responses(playwright, link: str) -> list:
    """Main browser automation entry point.
    
    Launches browser, navigates to directory page, captures all responses.
    Returns list of result dicts: [{"url": str, "data": dict}, ...]
    
    Flow:
    1. Navigate to site, find directory page
    2. Try search strategies (empty → all → * → a → alphabet)
    3. If no search, scroll to trigger lazy loading
    4. Handle pagination (Next/Load More buttons)
    5. Capture JSON responses + page HTML as fallback
    """
    results = []
    done = threading.Event()
    idle_timer = None
    idle_timeout_value = DEFAULT_IDLE_TIMEOUT
    pending_html_responses = []

    browser = playwright.chromium.launch(headless=False)
    page = browser.new_page()

    def reset_idle_timer():
        """Reset the idle timer. Called each time a relevant response arrives."""
        nonlocal idle_timer
        if idle_timer:
            idle_timer.cancel()
        idle_timer = threading.Timer(idle_timeout_value, done.set)
        idle_timer.start()

    def on_response(response):
        """Listener for all network responses. Captures JSON and queues HTML."""
        content_type = response.headers.get("content-type", "")
        print(f"RESPONSE: [{content_type}] {response.url}")

        # --- JSON responses ---
        if "application/json" in content_type:
            try:
                data = response.json()
                is_directory_data = False

                # Method 1: keyword in stringified data (original approach)
                data_str = str(data).lower()
                if any(key in data_str for key in JSON_DIRECTORY_KEYWORDS):
                    is_directory_data = True

                # Method 2: URL contains directory-related patterns
                url_lower = response.url.lower()
                if not is_directory_data:
                    if any(kw in url_lower for kw in JSON_URL_KEYWORDS):
                        is_directory_data = True

                # Method 3: JSON structure has member-like fields
                # Works for both list-of-dicts and single dict
                if not is_directory_data:
                    sample = data[0] if isinstance(data, list) and data else data
                    if isinstance(sample, dict):
                        keys_lower = {k.lower() for k in sample.keys()}
                        matches = keys_lower & set(JSON_STRUCTURE_FIELDS)
                        if len(matches) >= 3:
                            is_directory_data = True

                if is_directory_data:
                    print("Likely directory data at:", response.url)
                    results.append({
                        "url": response.url,
                        "data": data
                    })
                    reset_idle_timer()
            except:
                pass

        # --- HTML/text responses (queued for later reading) ---
        elif "text/plain" in content_type or "text/html" in content_type:
            pending_html_responses.append(response)
            url_lower = response.url.lower()
            if any(kw in url_lower for kw in DIRECTORY_URL_KEYWORDS):
                reset_idle_timer()

    page.on("response", on_response)

    # --- Step 1: Find and navigate to directory page ---
    directory_url = find_directory_url(page, link)
    # Only navigate if we're not already on the directory page
    # (find_directory_url may have already clicked a JS link to get there)
    if page.url.rstrip("/") != directory_url.rstrip("/"):
        page.goto(directory_url)
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except:
            pass

    # --- Step 2: Try search strategies ---
    search_triggered = trigger_search(page, results)
    if search_triggered:
        idle_timeout_value = SEARCH_IDLE_TIMEOUT
        print(f"Idle timeout set to: {idle_timeout_value}s (search mode)")

    # Start the idle timer AFTER search/scroll decision
    reset_idle_timer()

    # --- Step 3: If no search, scroll to trigger lazy loading ---
    if not search_triggered:
        # Check if results were already captured from page load (pre-loaded JSON)
        if results:
            print(f"Already captured {len(results)} JSON responses, minimal scrolling")
            human_scroll(page, done, scroll_target="body", times=5)
        else:
            human_scroll(page, scroll_target="body", done_event=done)

    # --- Step 4: Handle pagination ---
    # Wait a moment for initial results to settle, then try pagination
    if not done.is_set():
        idle_timeout_value = PAGINATION_IDLE_TIMEOUT
        extra_pages = handle_pagination(page, done)
        if extra_pages > 0:
            reset_idle_timer()  # give time for last page's responses

    # Wait until idle timer fires
    done.wait()

    # --- Step 5: Capture page HTML as fallback ---
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

    # --- Step 6: Read pending HTML responses (ASP.NET UpdatePanel etc.) ---
    print(f"Processing {len(pending_html_responses)} pending HTML responses...")
    for r in pending_html_responses:
        try:
            body = r.body()
            text = body.decode("utf-8", errors="ignore")
            if not text:
                continue
            # Detect ASP.NET UpdatePanel response
            if "updatepanel" in text.lower() and any(
                kw in text.lower() for kw in ["member", "contact", "directory"]
            ):
                print("ASP.NET UpdatePanel response detected at:", r.url)
                # Extract HTML chunk from pipe-delimited format
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
        print("No responses were captured!")

    return results