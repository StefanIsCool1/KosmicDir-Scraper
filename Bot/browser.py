"""
Browser automation with Playwright.
Handles: launching browser, capturing responses, human-like scrolling, pagination,
         and detecting detail page links for nested member directories.
         Supports results loaded inside iframes (e.g. YourMembership searchserver).
"""

import random
import time
import threading
from urllib.parse import urlparse
from config import (
    DEFAULT_IDLE_TIMEOUT, SEARCH_IDLE_TIMEOUT, PAGINATION_IDLE_TIMEOUT,
    NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
    JSON_DIRECTORY_KEYWORDS, JSON_URL_KEYWORDS, JSON_URL_EXCLUDE_PATTERNS, JSON_STRUCTURE_FIELDS,
    DIRECTORY_URL_KEYWORDS,
    NEXT_BUTTON_SELECTORS, LOAD_MORE_SELECTORS,
)
from navigator import find_directory_url, trigger_search
from playwright.sync_api import Playwright
from detail_crawler import collect_page_links, detect_detail_links, is_shallow_data, html_has_contact_info


# --- IFRAME DETECTION ---

# URL patterns that indicate an iframe contains directory/search results
IFRAME_CONTENT_URL_PATTERNS = [
    "searchserver", "people", "directory", "member",
    "searchresults", "search_results",
    "widget", "feeds", "membee",
]

# CSS selectors for known result iframes
IFRAME_SELECTORS = [
    "iframe#SearchResultsFrame",      # YourMembership
    "iframe[id*='search' i]",
    "iframe[id*='result' i]",
    "iframe[id*='directory' i]",
    "iframe[id*='member' i]",
    "iframe[id*='membee' i]",         # Membee widget
    "iframe[src*='searchserver']",
    "iframe[src*='directory']",
    "iframe[src*='member']",
    "iframe[src*='widget']",
    "iframe[src*='feeds']",
]

# Third-party domains that are NEVER directory result frames
THIRD_PARTY_FRAME_DOMAINS = [
    "stripe.com", "js.stripe.com", "m.stripe.network", "m.stripe.com",
    "facebook.com", "connect.facebook.net",
    "google.com", "googleapis.com", "gstatic.com",
    "youtube.com", "twitter.com", "linkedin.com",
    "newrelic.com", "nr-data.net",
    "cloudflare.com", "recaptcha.net",
    "doubleclick.net", "googlesyndication.com",
]


def _is_third_party_frame(frame_url: str) -> bool:
    """Check if a frame URL belongs to a known third-party domain."""
    try:
        frame_domain = urlparse(frame_url).netloc.lower()
        return any(domain in frame_domain for domain in THIRD_PARTY_FRAME_DOMAINS)
    except Exception:
        return False


def find_content_frame(page):
    """Detect if search results are loaded inside an iframe.

    Checks for known iframe patterns (YourMembership's SearchResultsFrame, etc.).
    If found, returns the Playwright Frame object for that iframe.
    If no iframe is found, returns None.

    Retries up to 3 times with waits ONLY if there are promising non-junk frames
    that might still be loading (e.g. membee widgets).
    """
    JUNK_FRAME_PATTERNS = [
        "about:blank", "recaptcha", "google.com/recaptcha", "doubleclick",
        "maps.google", "maps.googleapis", "analytics", "gtag",
    ]

    def _has_promising_frames():
        """Check if any non-main frames exist that aren't known junk."""
        for f in page.frames:
            if f == page.main_frame:
                continue
            url = f.url.lower()
            if any(junk in url for junk in JUNK_FRAME_PATTERNS):
                continue
            if _is_third_party_frame(f.url):
                continue
            # This frame has a real URL — might be a content iframe loading
            return True
        return False

    for attempt in range(3):
        if attempt > 0:
            # Only retry if there are promising frames that might still be loading
            if not _has_promising_frames():
                break
            print(f"  Iframe detection: retry {attempt + 1}/3...")
            page.wait_for_timeout(3000)

        # Method 1: Check known iframe selectors in the main page
        for selector in IFRAME_SELECTORS:
            try:
                iframe_el = page.locator(selector).first
                if iframe_el.is_visible(timeout=2000):
                    frame = iframe_el.content_frame()
                    if frame:
                        # Skip third-party iframes
                        if _is_third_party_frame(frame.url):
                            continue
                        try:
                            frame_html = frame.content()
                            if any(kw in frame_html.lower() for kw in
                                   ["member", "directory", "listing", "result",
                                    "profile", "load more", "company"]):
                                print(f"  Found results iframe: {selector}")
                                return frame
                        except Exception:
                            pass
            except Exception:
                continue

        # Method 2: Scan all frames by URL pattern
        # Match against the iframe's path only — not the full URL with fragments/params.
        # This prevents false matches where the site's own URL (containing "directory"
        # or "member") is embedded in a third-party iframe's hash/query params.
        for frame in page.frames:
            if frame == page.main_frame:
                continue

            # Skip third-party iframes
            if _is_third_party_frame(frame.url):
                continue

            frame_path = urlparse(frame.url).path.lower()
            if any(pattern in frame_path for pattern in IFRAME_CONTENT_URL_PATTERNS):
                try:
                    frame_html = frame.content()
                    if any(kw in frame_html.lower() for kw in
                           ["member", "directory", "listing", "result",
                            "profile", "load more", "company"]):
                        print(f"  Found results iframe by URL: {frame.url[:100]}")
                        return frame
                except Exception:
                    continue

    return None


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


def handle_pagination(page, done_event, link_collector=None, html_collector=None):
    """Click through pagination to capture all pages.

    Handles two types of pagination:
    1. Simple Next/→ buttons — clicks Next repeatedly
    2. Numbered page groups (e.g. [1] 2 3 ... 10 →) — clicks each number
       sequentially, then → to load next group, then continues numbering.

    Args:
        page: Playwright page or Frame object
        done_event: Threading event that signals when to stop
        link_collector: Optional list to accumulate page links into.
        html_collector: Optional list to capture page HTML after each pagination click.

    Returns the number of extra pages loaded.
    """
    pages_loaded = 0
    max_pages = 200
    current_page_num = 1

    def _collect_links():
        if link_collector is None:
            return
        links = collect_page_links(page)
        link_collector.extend(links)

    def _wait_for_page():
        try:
            page.wait_for_load_state("domcontentloaded", timeout=NETWORK_IDLE_TIMEOUT)
        except:
            pass
        page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)

    def _capture_html():
        """Capture current page HTML into the html_collector."""
        if html_collector is None:
            return
        try:
            html_collector.append(page.content())
        except Exception:
            pass

    def _find_page_button(target_num: int):
        """Find a visible button or link with exact page number text."""
        target = str(target_num)
        for tag in ["button", "a"]:
            try:
                for btn in page.locator(f"{tag}:has-text('{target}')").all():
                    try:
                        if not btn.is_visible(timeout=500):
                            continue
                        if btn.inner_text().strip() == target:
                            cls = (btn.get_attribute("class") or "").lower()
                            if "primary" not in cls and "active" not in cls:
                                return btn
                    except:
                        continue
            except:
                continue
        return None

    def _read_active_page_num() -> int:
        """Read current page number from the active pagination button."""
        for sel in ["button.btn-primary", "[class*='active']", "li.active a"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    txt = el.inner_text().strip()
                    if txt.isdigit():
                        return int(txt)
            except:
                continue
        return current_page_num

    while not done_event.is_set() and pages_loaded < max_pages:
        found_next = False
        next_num = current_page_num + 1

        # --- Strategy 1: Click next numbered page button ---
        try:
            num_btn = _find_page_button(next_num)
            if num_btn:
                num_btn.click()
                _wait_for_page()
                pages_loaded += 1
                current_page_num = next_num
                print(f"  Pagination: page {current_page_num}")
                _collect_links()
                _capture_html()
                found_next = True
        except:
            pass

        if found_next:
            continue

        # --- Strategy 2: Click → / Next to advance page group ---
        try:
            next_btn = page.locator(NEXT_BUTTON_SELECTORS).first
            if next_btn.is_visible(timeout=1000) and next_btn.is_enabled():
                cls = (next_btn.get_attribute("class") or "").lower()
                if "disabled" not in cls and "active" not in cls:
                    next_btn.click()
                    _wait_for_page()
                    pages_loaded += 1
                    # Read actual page number from the active button (numbered pagination)
                    detected_num = _read_active_page_num()
                    if detected_num > current_page_num:
                        current_page_num = detected_num
                    else:
                        current_page_num += 1  # no numbered buttons — just increment
                    print(f"  Pagination: next/arrow → page {current_page_num}")
                    _collect_links()
                    _capture_html()
                    found_next = True
        except:
            pass

        if found_next:
            continue

        # --- Strategy 3: Load More button ---
        # Check if Load More exists in the DOM first, THEN scroll to it.
        try:
            all_load_more = page.locator(LOAD_MORE_SELECTORS)
            lm_count = all_load_more.count()
            if lm_count > 0:
                print(f"  Load More: found {lm_count} element(s), clicking...")
                load_more = all_load_more.first
                try:
                    load_more.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    load_more.click()
                except:
                    # Fallback: force click even if not "actionable"
                    load_more.click(force=True)
                page.wait_for_timeout(2000)
                pages_loaded += 1
                current_page_num += 1
                print(f"  Load More: click #{pages_loaded}")
                _collect_links()
                found_next = True
        except:
            pass

        if found_next:
            continue

        break

    if pages_loaded > 0:
        print(f"  Pagination complete: {pages_loaded} pages loaded (reached page {current_page_num})")
    return pages_loaded


def capture_responses(playwright: Playwright, link: str) -> tuple[list, list]:
    """Main browser automation entry point.

    Launches browser, navigates to directory page, captures all responses.

    Returns:
        Tuple of (results, detail_urls):
        - results: list of dicts [{"url": str, "data": dict}, ...]
        - detail_urls: list of member detail page URLs (may be empty)

    Flow:
    1. Navigate to site, find directory page
    2. Try search strategies (empty → all → * → a → alphabet)
    3. If no search, scroll to trigger lazy loading
    4. Handle pagination (Next/Load More buttons)
    5. Collect links from all paginated pages for detail detection
    6. Capture JSON responses + page HTML as fallback
    7. Detect detail links if data is shallow
    """
    results = []
    detail_urls = []
    all_page_links = []  # accumulated across all paginated pages
    done = threading.Event()
    idle_timer = None
    idle_timeout_value = DEFAULT_IDLE_TIMEOUT
    pending_html_responses = []
    timer_enabled = False  # Don't start idle timer until after search/scroll phase

    browser = playwright.chromium.launch(headless=False)
    page = browser.new_page()

    def reset_idle_timer():
        """Reset the idle timer. Called each time a relevant response arrives.
        Only actually starts the timer if timer_enabled is True.
        This prevents the idle timer from firing during trigger_search,
        which navigates through multiple pages and takes longer than the timeout."""
        nonlocal idle_timer
        if not timer_enabled:
            return
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
                        # Exclude known non-data endpoints (filters, config, analytics, etc.)
                        if not any(excl in url_lower for excl in JSON_URL_EXCLUDE_PATTERNS):
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

                # Final veto: exclude known non-data endpoints even if content matched
                # (e.g. /memberdirectory/Filters contains "member" in data but isn't member data)
                if is_directory_data and any(excl in url_lower for excl in JSON_URL_EXCLUDE_PATTERNS):
                    is_directory_data = False

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

    # Enable and start the idle timer AFTER search/scroll decision.
    # Before this point, on_response does NOT start timers — this prevents
    # the browser from closing while trigger_search is still running.
    timer_enabled = True
    reset_idle_timer()

    # --- Step 3: If no search, scroll to trigger lazy loading ---
    if not search_triggered:
        # Check if results were already captured from page load (pre-loaded JSON)
        if results:
            print(f"Already captured {len(results)} JSON responses, minimal scrolling")
            human_scroll(page, done, scroll_target="body", times=5)
        else:
            human_scroll(page, scroll_target="body", done_event=done)

    # --- Step 3.5: Detect if results are inside an iframe ---
    # Some platforms (YourMembership, etc.) load search results in an iframe.
    # If so, we need to collect links, paginate, and capture HTML from the
    # iframe's Frame object — not the main page.
    # Skip iframe detection if we already captured JSON directory data —
    # iframe is a fallback for sites that ONLY render results in an iframe.
    content_frame = None
    if not results:
        content_frame = find_content_frame(page)
    else:
        print(f"  Skipping iframe detection (already have {len(results)} captured responses)")
    content_context = content_frame if content_frame else page
    if content_frame:
        print(f"  Operating inside iframe for link collection and pagination")

    # --- Step 4: Collect links from the current content (before pagination) ---
    initial_links = collect_page_links(content_context)
    all_page_links.extend(initial_links)
    if content_frame:
        print(f"  Collected {len(initial_links)} links from iframe (page 1)")

    # --- Step 4.5: Capture initial page HTML before pagination ---
    # Pagination navigates away from each page, so we must capture page 1 now.
    # Subsequent pages are captured inside handle_pagination via html_collector.
    all_page_htmls = []
    try:
        initial_html = content_context.content()
        if any(kw in initial_html.lower() for kw in ["member", "directory", "contact", "listing"]):
            all_page_htmls.append(initial_html)
    except Exception:
        pass

    # --- Step 5: Handle pagination (also collects links and HTML from each new page) ---
    # Pagination buttons (Next, →, Load More) are inside the content context.
    # Skip pagination if the search already loaded a large number of results —
    # sites that show 600+ results on one page don't need pagination, and
    # false "next" button matches (carousel arrows, nav links) can navigate away.
    skip_pagination = False
    try:
        from navigator import count_visible_results
        visible_now = count_visible_results(content_context)
        if visible_now >= 600:
            print(f"  Skipping pagination — already have {visible_now} visible results")
            skip_pagination = True
    except:
        pass

    if not skip_pagination:
        # Always attempt pagination — clear any previously fired done event and
        # give a fresh 30s window. The old 4s/20s timer may have fired during
        # iframe detection and link collection, but we still need to paginate.
        done.clear()
        idle_timeout_value = PAGINATION_IDLE_TIMEOUT
        reset_idle_timer()
        extra_pages = handle_pagination(content_context, done, link_collector=all_page_links,
                                        html_collector=all_page_htmls)
        if extra_pages > 0:
            reset_idle_timer()  # give time for last page's responses
    else:
        # Already have enough results — just give a short window for any
        # remaining responses to arrive, then move on.
        done.clear()
        idle_timeout_value = DEFAULT_IDLE_TIMEOUT
        reset_idle_timer()

    # Wait until idle timer fires
    done.wait()

    # --- Step 6: Add captured page HTML(s) to results ---
    # If pagination captured multiple pages, add all of them.
    # If no pagination, all_page_htmls has just the initial page (same as before).
    # If pagination used Load More (no navigation), capture final page state now.
    if all_page_htmls:
        source_url = content_frame.url if content_frame else page.url
        print(f"Captured {len(all_page_htmls)} HTML page(s)")
        for html in all_page_htmls:
            results.append({
                "url": source_url,
                "data": {"raw_html": html}
            })
    else:
        # Fallback: capture whatever is on screen now
        try:
            html = content_context.content()
            if any(kw in html.lower() for kw in ["member", "directory", "contact", "listing"]):
                source_url = content_frame.url if content_frame else page.url
                print(f"Captured plain HTML from: {source_url}")
                results.append({
                    "url": source_url,
                    "data": {"raw_html": html}
                })
        except Exception as e:
            print(f"Error capturing page HTML: {e}")

    # --- Step 7: Read pending HTML responses (ASP.NET UpdatePanel etc.) ---
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

    # --- Step 8: Detect detail links if data is shallow ---
    if all_page_links:
        detected = detect_detail_links(all_page_links)
        if detected:
            # Check if we have any structured JSON data
            has_structured_json = any(
                (isinstance(r.get("data"), list) and len(r.get("data", [])) > 0) or
                (isinstance(r.get("data"), dict) and "raw_html" not in r.get("data", {}))
                for r in results
            )

            if has_structured_json:
                # JSON data exists — check if it has contact info
                if is_shallow_data(results):
                    detail_urls = detected
                    print(f"\n  JSON data appears shallow (names only, no contact info)")
                    print(f"  Found {len(detail_urls)} member detail page links")
                else:
                    print(f"  Detail links found but JSON data already has contact info — skipping")
            else:
                # No JSON data — HTML only. Check if HTML has contact info.
                # Sites like agcwa put full details (phone, email, address) right
                # in the listing page HTML. Only trigger detail crawl if the HTML
                # lacks contact signals.
                if html_has_contact_info(results):
                    print(f"  Detail links found but HTML already has contact info — skipping")
                else:
                    detail_urls = detected
                    print(f"\n  HTML-only listing with no contact info detected")
                    print(f"  Found {len(detail_urls)} member detail page links")

    browser.close()
    print(f"Total results captured: {len(results)}")
    if not results:
        print("No responses were captured!")

    return results, detail_urls