"""
Browser automation with Playwright.
Handles: launching browser, capturing responses, human-like scrolling, pagination,
         and detecting detail page links for nested member directories.
         Supports results loaded inside iframes (e.g. YourMembership searchserver).
"""

import random
import time
import threading
import json
import os
from urllib.parse import urlparse
from config import (
    DEFAULT_IDLE_TIMEOUT, SEARCH_IDLE_TIMEOUT, PAGINATION_IDLE_TIMEOUT,
    NETWORK_IDLE_TIMEOUT, PAGE_WAIT_AFTER_ACTION,
    JSON_JUNK_DOMAINS,
    JSON_DIRECTORY_KEYWORDS, JSON_URL_KEYWORDS, JSON_URL_EXCLUDE_PATTERNS, JSON_STRUCTURE_FIELDS,
    DIRECTORY_URL_KEYWORDS,
    NEXT_BUTTON_SELECTORS, LOAD_MORE_SELECTORS,
    SCROLL_BATCH_SIZE, SCROLL_STALE_THRESHOLD,
    CATEGORY_SKIP_VISIBLE_THRESHOLD,
    block_unnecessary_resources,
)
from navigator import find_directory_url, trigger_search, count_visible_results, detect_category_links, try_view_all
from intent_filter import filter_categories_by_intent
from debug import debug
from playwright.sync_api import Playwright
from detail_crawler import collect_page_links, detect_detail_links, is_shallow_data, html_has_contact_info, CONTACT_KEYS


# Content keywords that indicate directory-related HTML (used in multiple checks)
_DIRECTORY_CONTENT_KEYWORDS = [
    "member", "directory", "listing", "result", "profile",
    "load more", "company", "contact",
    "doctor", "restaurant", "attorney", "clinic",
]

# --- IFRAME DETECTION ---

# URL patterns that indicate an iframe contains directory/search results
IFRAME_CONTENT_URL_PATTERNS = [
    "searchserver", "people", "directory", "member",
    "searchresults", "search_results",
    "widget", "feeds", "membee",
    "doctor", "restaurant", "attorney", "clinic",
    "listing",
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


def _find_member_array(data, max_depth: int = 3) -> bool:
    """Recursively look for a list of member-shape dicts inside an envelope JSON.

    Catches platforms where the directory data is wrapped, which Method 3
    (which only checks data[0] or top-level keys) misses:
      - GraphQL:   {"data": {"members": {"edges": [{"node": {...}}, ...]}}}
      - Drupal:    {"data": [{"attributes": {...}}, ...]}
      - SharePoint:{"d": {"results": [{...}]}}
      - WP custom: {"items": [{"acf": {...}}, ...]}

    Thresholds tuned conservatively so config blobs, i18n bundles, and
    chat-widget agent lists don't trip a false positive:
      - List must have >=3 entries
      - >=2 of the first 5 entries must each have >=3 matching JSON_STRUCTURE_FIELDS keys
      - Handles 1-key wrapper entries by unwrapping one level (node/attributes/fields)

    Bounded: max_depth=3, 20 list items per level, 25 dict values per level.
    Wrapped in try/except by the caller; any exception → no detection.
    """
    if max_depth < 0:
        return False

    if isinstance(data, list):
        if len(data) >= 3:
            matching = 0
            for entry in data[:5]:
                if not isinstance(entry, dict):
                    continue
                keys_lower = {k.lower() for k in entry.keys()}
                if len(keys_lower & set(JSON_STRUCTURE_FIELDS)) >= 3:
                    matching += 1
                    continue
                # Wrapper unwrap: if any nested value is a dict with member-shape
                # keys, treat as a wrapped record. Handles JSON:API ({id, type,
                # attributes:{...}}), Elasticsearch ({_id, _source:{...}}),
                # Salesforce ({Id, fields:{...}}), GraphQL ({node:{...}}), etc.
                for v in entry.values():
                    if isinstance(v, dict):
                        v_keys = {k.lower() for k in v.keys()}
                        if len(v_keys & set(JSON_STRUCTURE_FIELDS)) >= 3:
                            matching += 1
                            break
            if matching >= 2:
                return True
        # Recurse — bounded sample of items
        for item in data[:20]:
            if _find_member_array(item, max_depth - 1):
                return True
    elif isinstance(data, dict):
        # Bounded sample of values — pathological cases (large i18n bundles,
        # config blobs) can have hundreds of keys
        for value in list(data.values())[:25]:
            if _find_member_array(value, max_depth - 1):
                return True
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
                                   _DIRECTORY_CONTENT_KEYWORDS):
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


def human_scroll(page, done_event, scroll_target="body", times=20, adaptive=False):
    """Simulate human-like scrolling to trigger lazy-loaded content.
    Stops early if done_event is set (e.g. idle timer fired).

    When adaptive=True, scrolls in batches and checks if new content loaded
    after each batch. Stops when page height and visible result count stop
    growing (handles infinite scroll pages).
    """
    if adaptive:
        stale_batches = 0
        max_batches = max(times // SCROLL_BATCH_SIZE, 4)

        for batch in range(max_batches):
            if done_event.is_set():
                break

            # Measure before scrolling
            try:
                prev_height = page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollHeight"
                )
            except Exception:
                prev_height = 0
            prev_count = count_visible_results(page)

            # Scroll a batch
            for _ in range(SCROLL_BATCH_SIZE):
                if done_event.is_set():
                    break
                distance = random.randint(300, 600)
                page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollBy(0, {distance});"
                )
                page.mouse.wheel(0, distance)
                time.sleep(random.uniform(0.15, 0.5))

            # Wait for lazy content to load
            page.wait_for_timeout(1500)

            # Measure after
            try:
                new_height = page.evaluate(
                    f"document.querySelector('{scroll_target}').scrollHeight"
                )
            except Exception:
                new_height = prev_height
            new_count = count_visible_results(page)

            if new_height <= prev_height and new_count <= prev_count:
                stale_batches += 1
                if stale_batches >= SCROLL_STALE_THRESHOLD:
                    print(f"  Scroll: no new content after {batch + 1} batches "
                          f"({new_count} results), stopping")
                    break
            else:
                stale_batches = 0
                if new_count > prev_count:
                    print(f"  Scroll: {new_count} results (+{new_count - prev_count})")
    else:
        # Original fixed-count scrolling
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
    max_pages = 50
    current_page_num = 1
    stale_clicks = 0  # how many times "next" didn't change the page

    # Record the starting URL path to detect accidental navigation away
    # (e.g. clicking a member detail link instead of a pagination button).
    from urllib.parse import urlparse
    try:
        start_url = page.url
        start_path = urlparse(start_url).path.rstrip("/")
    except Exception:
        start_url = ""
        start_path = ""

    def _navigated_away() -> bool:
        """Check if a pagination click accidentally navigated to a different page.
        If so, go back and return True to stop pagination.

        Uses the parent directory of the start path to allow minor path changes
        from searching (e.g. /directory → /directory/search) while catching
        navigation to a completely different section (e.g. /directory/Find → /directory/Details/...).
        """
        if not start_path:
            return False
        try:
            current_url = page.url
            current_path = urlparse(current_url).path.rstrip("/")
            # Exact same path → definitely still on the listing page
            if current_path == start_path:
                return False
            # Allow paths that share the same parent directory as the start.
            # e.g. start=/member-directory/Find → parent=/member-directory
            #   /member-directory/Find?page=2 → path=/member-directory/Find → OK (same)
            #   /member-directory/search → OK (same parent)
            #   /member-directory/Details/company-123 → NOT OK (deeper than parent)
            start_parent = start_path.rsplit("/", 1)[0] if "/" in start_path else start_path
            # The current path must start with the parent AND not go more than
            # one level deeper. This catches /parent/Details/slug (2 levels deeper).
            if current_path.startswith(start_parent):
                # Count path segments after the parent
                remainder = current_path[len(start_parent):].strip("/")
                depth = len(remainder.split("/")) if remainder else 0
                # Allow up to 1 extra segment (e.g. /directory → /directory/search)
                # Block 2+ extra segments (e.g. /directory/Details/company-name)
                if depth <= 1:
                    return False
            # Different section entirely, or too deep → navigated away
            print(f"  Pagination: navigated away from listing ({start_path} → {current_path}), going back")
            try:
                page.go_back()
                page.wait_for_load_state("domcontentloaded", timeout=NETWORK_IDLE_TIMEOUT)
                page.wait_for_timeout(1000)
            except Exception:
                pass
            return True
        except Exception:
            return False

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

    def _content_snapshot() -> str:
        """Quick hash of visible text to detect if page actually changed."""
        try:
            text = page.inner_text("body")[:2000]
            return str(hash(text))
        except:
            return ""

    last_content_hash = _content_snapshot()

    while not done_event.is_set() and pages_loaded < max_pages:
        found_next = False
        next_num = current_page_num + 1

        # --- Strategy 1: Click next numbered page button ---
        try:
            num_btn = _find_page_button(next_num)
            if num_btn:
                before_hash = _content_snapshot()
                before_url = page.url
                num_btn.click()
                _wait_for_page()
                if _navigated_away():
                    break
                if page.url == before_url and _content_snapshot() == before_hash:
                    print(f"  Pagination: page {next_num} — URL and content unchanged, stopping")
                    break
                elif _content_snapshot() == before_hash:
                    stale_clicks += 1
                    if stale_clicks >= 2:
                        print(f"  Pagination: content unchanged, stopping")
                        break
                else:
                    stale_clicks = 0
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
                    before_hash = _content_snapshot()
                    before_url = page.url
                    next_btn.click()
                    _wait_for_page()
                    if _navigated_away():
                        break
                    # Check if page actually changed (URL or content)
                    after_url = page.url
                    after_hash = _content_snapshot()
                    if after_url == before_url and after_hash == before_hash:
                        stale_clicks += 1
                        if stale_clicks >= 1:
                            print(f"  Pagination: URL and content unchanged after click, stopping (last page)")
                            break
                    elif after_hash == before_hash:
                        stale_clicks += 1
                        if stale_clicks >= 2:
                            print(f"  Pagination: content unchanged, stopping")
                            break
                    else:
                        stale_clicks = 0
                    pages_loaded += 1
                    detected_num = _read_active_page_num()
                    if detected_num > current_page_num:
                        current_page_num = detected_num
                    else:
                        current_page_num += 1
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
                if _navigated_away():
                    break
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


# --- LOGIN WALL DETECTION & COOKIE MANAGEMENT ---

_LOGIN_SIGNALS = [
    "sign in", "log in", "login", "username",
    "members only", "member login", "member sign in",
    "forgot password", "forgot your password",
    "click here for login", "portal login",
]

# Directory where per-domain cookies are persisted
_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cookies")


def _is_login_page(page) -> bool:
    """Check if the current page is a login/authentication wall.

    Requires password field + 2+ login-related phrases in the HTML.
    Low false-positive rate — sites with public directories that also have
    a login link in the nav won't trigger this.
    """
    try:
        html = page.content().lower()
    except Exception:
        return False

    has_password = 'type="password"' in html or "type='password'" in html
    if not has_password:
        return False

    signals = sum(1 for phrase in _LOGIN_SIGNALS if phrase in html)
    return signals >= 2


def _load_cookies(page, domain: str) -> bool:
    """Load saved cookies for a domain into the browser context.

    Returns True if cookies were loaded, False if no cookie file exists.
    """
    cookie_file = os.path.join(_COOKIE_DIR, f"{domain}.json")
    if not os.path.exists(cookie_file):
        return False
    try:
        with open(cookie_file, "r") as f:
            cookies = json.load(f)
        page.context.add_cookies(cookies)
        print(f"  Loaded {len(cookies)} cookies for {domain}")
        return True
    except Exception as e:
        print(f"  Failed to load cookies for {domain}: {e}")
        return False


def _save_cookies(page, domain: str):
    """Save current browser cookies to disk for reuse on future scrapes."""
    os.makedirs(_COOKIE_DIR, exist_ok=True)
    cookie_file = os.path.join(_COOKIE_DIR, f"{domain}.json")
    try:
        cookies = page.context.cookies()
        with open(cookie_file, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"  Saved {len(cookies)} cookies for {domain}")
    except Exception as e:
        print(f"  Failed to save cookies for {domain}: {e}")


def capture_responses(playwright: Playwright, link: str, mode: str = "auto",
                      priority_fields: list | None = None,
                      login_callback=None,
                      intent: dict | None = None) -> tuple[list, list]:
    """Main browser automation entry point.

    Launches browser, navigates to directory page, captures all responses.

    mode: "auto" = find directory page + search (default)
          "direct" = skip navigation/search, scrape the page as-is

    login_callback: Optional callable(page, domain) -> bool.
        Called when a login wall is detected. The callback should pause
        and let the user log in manually, then return True to retry or
        False to skip. If None and a login wall is hit, the scrape fails.

    intent: Optional dict from intent_filter.intent_from_plan. When set
        (Agent mode), used to (a) hint the AI navigator toward intent-
        relevant sub-directory links and (b) narrow detected category
        lists before iteration. Playground callers pass None and every
        downstream consumer falls back to existing behavior.

    Returns:
        Tuple of (results, detail_urls):
        - results: list of dicts [{"url": str, "data": dict}, ...]
        - detail_urls: list of member detail page URLs (may be empty)
    """
    results = []
    detail_urls = []
    all_page_links = []  # accumulated across all paginated pages
    all_page_htmls = []  # accumulated HTML from each page/category
    done = threading.Event()
    idle_timer = None
    idle_timeout_value = DEFAULT_IDLE_TIMEOUT
    pending_html_responses = []
    timer_enabled = False  # Don't start idle timer until after search/scroll phase

    domain = urlparse(link).netloc.replace(".", "_")

    browser = playwright.chromium.launch(headless=False)
    page = browser.new_page()

    # Apply stealth patches to avoid bot detection (Cloudflare, DataDome, etc.)
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

    # Block images, fonts, media, analytics — bot only needs JSON + HTML
    block_unnecessary_resources(page)

    # --- Load saved cookies for this domain (if any) ---
    had_cookies = _load_cookies(page, domain)

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
        # Skip known third-party domains that never contain member data
        resp_domain = urlparse(response.url).netloc.lower()
        if any(junk in resp_domain for junk in JSON_JUNK_DOMAINS):
            return

        content_type = response.headers.get("content-type", "")
        print(f"RESPONSE: [{content_type}] {response.url}")
        debug.log("CAPTURE", f"Response: [{content_type[:30]}] {response.url[:120]}")

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

                # Method 4: Recursive envelope unwrap — catches GraphQL, Drupal
                # JSON:API, SharePoint, and other platforms that wrap the member
                # array in a deeper structure that Method 3 doesn't see.
                # Purely additive: only fires when Methods 1-3 all said False.
                if not is_directory_data and _find_member_array(data):
                    is_directory_data = True
                    print(f"  Method 4 (envelope unwrap): member array detected")

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
    if mode == "direct":
        # Direct mode: user already picked the page, just load it
        print(f"  Direct mode: loading {link}")
        page.goto(link)
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except Exception:
            pass
        directory_url = link
        search_triggered = False
        debug.log("NAV", f"Direct mode — skipping navigation and search")
    else:
        directory_url = find_directory_url(page, link, intent=intent)
        debug.log("NAV", f"Directory URL resolved: {directory_url}")
        if page.url.rstrip("/") != directory_url.rstrip("/"):
            page.goto(directory_url)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
            except Exception:
                pass

    # --- Login gate: detect and handle authentication walls ---
    # Runs after initial navigation in BOTH modes. If cookies were loaded
    # but are stale, the page will still show a login wall.
    if _is_login_page(page):
        if login_callback is None:
            print(f"  LOGIN WALL DETECTED — no login_callback provided, "
                  f"scrape will likely return 0 results")
        else:
            print(f"\n  ╔══════════════════════════════════════════╗")
            print(f"  ║  LOGIN WALL DETECTED                    ║")
            print(f"  ║  This directory requires authentication. ║")
            print(f"  ╚══════════════════════════════════════════╝")
            # Up to MAX_LOGIN_ATTEMPTS rounds of prompt-then-verify.
            # If the user presses Enter prematurely (before actually logging
            # in), the post-navigation _is_login_page check catches it and
            # we re-prompt instead of saving useless cookies.
            #
            # First attempt: goto directory_url after login_callback
            #   returns. Handles the common case where the site
            #   auto-redirected to a dashboard after login.
            # Retry attempt: skip the goto and verify whatever page the
            #   user is on. After being told "verification failed", the
            #   user may have manually navigated to the right page —
            #   don't yank them away from it.
            MAX_LOGIN_ATTEMPTS = 2
            for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
                retry = login_callback(page, domain)
                if not retry:
                    print(f"  Login skipped — scrape will likely return 0 results")
                    break

                if attempt == 1:
                    # Common case: login redirected the user to /dashboard
                    # or similar. Navigate to our target URL so we end up
                    # on the page we actually want to scrape.
                    print(f"  Navigating to directory page after login: {directory_url}")
                    page.goto(directory_url)
                    try:
                        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                    except Exception:
                        pass
                else:
                    # Retry: trust the user's current location. They may
                    # have manually navigated to a better page than
                    # directory_url after the first verification failed.
                    print(f"  Verifying current page: {page.url}")

                # Verify login actually worked. If still a login wall, the
                # cookies are useless — do NOT save them (would poison the
                # cache and make future scrapes silently fail).
                if not _is_login_page(page):
                    _save_cookies(page, domain)
                    print(f"  Login verified on {page.url} — continuing scrape")
                    break

                remaining = MAX_LOGIN_ATTEMPTS - attempt
                if remaining > 0:
                    print(f"  Login verification FAILED — page still shows a "
                          f"login wall. {remaining} attempt(s) remaining.")
                    print(f"  If login redirected you elsewhere, you can "
                          f"manually navigate to the directory page before "
                          f"pressing Enter on the next prompt.")
                else:
                    print(f"  Login verification FAILED after {MAX_LOGIN_ATTEMPTS} "
                          f"attempts — NOT saving cookies. Scrape will likely "
                          f"return 0 results.")

    # --- Fast path: URL-parameter enumeration ---
    # If the page has a GET form with a static <select> (e.g.
    # hoa-usa.com's ?state=Alabama dropdown), we can fetch every
    # parameter value in parallel via curl_cffi and skip the entire
    # browser-based search/scroll/paginate flow. ~20–50x faster.
    try:
        from url_enumeration import try_url_enumeration_cached
        if try_url_enumeration_cached(page, domain, link, results):
            print(f"  URL enumeration captured {len(results)} pages — "
                  f"skipping browser search flow")
            browser.close()
            return results, []
    except Exception as e:
        print(f"  URL enumeration error (non-fatal, falling through): {e}")

    if mode != "direct":
        # --- Step 2: Try search strategies ---
        pre_search_count = len(results)
        debug.log("SEARCH", f"Starting search. JSON results so far: {pre_search_count}")
        search_triggered = trigger_search(page, results)
        debug.log("SEARCH", f"Search complete. triggered={search_triggered}, "
                  f"results before={pre_search_count} after={len(results)}")
        if search_triggered and len(results) > pre_search_count:
            idle_timeout_value = SEARCH_IDLE_TIMEOUT
            print(f"Idle timeout set to: {idle_timeout_value}s (search mode)")

    # Enable and start the idle timer AFTER search/scroll decision.
    timer_enabled = True
    reset_idle_timer()

    # --- Step 3: If no search, try view-all / categories / scroll ---
    # In direct mode, skip view-all/categories (user already chose the page).
    # Still scroll for lazy-loaded content.
    categories_handled = False
    view_all_clicked = False
    if not search_triggered and mode != "direct":
        visible_count = count_visible_results(page)
        debug.log("SEARCH", f"No search triggered. visible_results={visible_count}, "
                  f"json_results={len(results)}")
        if not results and visible_count < CATEGORY_SKIP_VISIBLE_THRESHOLD:
            # No search input, no JSON captured, no members visible.
            # Try the simplest discovery method first.

            # 1. Try "View All" / "Show All" link (loads everything at once)
            view_all_clicked = try_view_all(page)
            debug.log("SEARCH", f"View All attempt: {'clicked' if view_all_clicked else 'not found'}")

            # 2. If no View All, try category iteration
            if not view_all_clicked:
                categories = detect_category_links(page)
                # Agent mode narrows categories to the user's intent. Fall-open
                # if intent is None or no matches found — never accidentally drop
                # every category and end up scraping nothing.
                categories = filter_categories_by_intent(categories, intent)
                if categories:
                    print(f"  Iterating {len(categories)} categories...")
                    timer_enabled = False
                    for ci, cat in enumerate(categories):
                        try:
                            page.goto(cat["href"], timeout=15000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
                            except Exception:
                                pass
                            page.wait_for_timeout(PAGE_WAIT_AFTER_ACTION)
                            print(f"  Category {ci + 1}/{len(categories)}: {cat['text']}")

                            cat_links = collect_page_links(page)
                            all_page_links.extend(cat_links)

                            try:
                                cat_html = page.content()
                                if any(kw in cat_html.lower() for kw in
                                       _DIRECTORY_CONTENT_KEYWORDS):
                                    all_page_htmls.append(cat_html)
                            except Exception:
                                pass

                            cat_done = threading.Event()
                            handle_pagination(page, cat_done,
                                              link_collector=all_page_links,
                                              html_collector=all_page_htmls)

                        except Exception as e:
                            print(f"  Error on category '{cat['text']}': {e}")
                            continue
                    print(f"  Category iteration complete")
                    categories_handled = True
                    timer_enabled = True
                    reset_idle_timer()

        # 3. Scroll — but only what's appropriate
        if not categories_handled:
            if results or view_all_clicked:
                # Data already captured — just light scroll in case of lazy stragglers
                print(f"Already captured data, minimal scrolling")
                human_scroll(page, done, scroll_target="body", times=5)
            else:
                # Nothing found yet — adaptive scroll for infinite scroll pages
                human_scroll(page, scroll_target="body", done_event=done, adaptive=True)

    # Direct mode: light scroll to trigger any lazy content
    if mode == "direct" and not search_triggered:
        print(f"  Direct mode: scrolling to load lazy content")
        human_scroll(page, done, scroll_target="body", times=5)

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
    try:
        initial_html = content_context.content()
        if any(kw in initial_html.lower() for kw in _DIRECTORY_CONTENT_KEYWORDS):
            all_page_htmls.append(initial_html)
            debug.log("CAPTURE", f"Captured initial HTML: {len(initial_html)} chars")
        else:
            debug.log("CAPTURE", "Initial HTML has no directory keywords — skipped", level="warn")
    except Exception:
        pass

    # --- Step 5: Handle pagination (also collects links and HTML from each new page) ---
    # Pagination buttons (Next, →, Load More) are inside the content context.
    # Skip pagination if the search already loaded a large number of results —
    # sites that show 600+ results on one page don't need pagination, and
    # false "next" button matches (carousel arrows, nav links) can navigate away.
    skip_pagination = False
    try:
        visible_now = count_visible_results(content_context)
        if visible_now >= 600:
            print(f"  Skipping pagination — already have {visible_now} visible results")
            skip_pagination = True
    except:
        pass

    # Also skip pagination if JSON already has substantial member data.
    # Prevents false Next button matches (carousel arrows, nav links) from
    # navigating away when we already have what we need.
    if not skip_pagination:
        json_record_count = 0
        for r in results:
            data = r.get("data", {})
            if isinstance(data, list):
                json_record_count += len(data)
            elif isinstance(data, dict) and "raw_html" not in data:
                for val in data.values():
                    if isinstance(val, list):
                        json_record_count += len(val)
        if json_record_count >= 50:
            print(f"  Skipping pagination — already have {json_record_count} JSON records")
            skip_pagination = True

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
            # No pagination found — no reason to wait 30s
            idle_timeout_value = DEFAULT_IDLE_TIMEOUT
            reset_idle_timer()
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
            if any(kw in html.lower() for kw in _DIRECTORY_CONTENT_KEYWORDS):
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

            # If priority fields are set, always pass detail URLs through
            # and let main.py decide based on what fields are actually missing.
            # Without priorities, use the original heuristic checks.
            if priority_fields:
                detail_urls = detected
                print(f"\n  Found {len(detail_urls)} member detail page links (priority fields requested)")
            elif has_structured_json:
                # JSON data exists — check if it has contact info
                if is_shallow_data(results):
                    detail_urls = detected
                    print(f"\n  JSON data appears shallow (names only, no contact info)")
                    print(f"  Found {len(detail_urls)} member detail page links")
                else:
                    print(f"  Detail links found but JSON data already has contact info — skipping")
            else:
                # No JSON data — HTML only. Check if HTML has contact info.
                if html_has_contact_info(results):
                    print(f"  Detail links found but HTML already has contact info — skipping")
                else:
                    detail_urls = detected
                    print(f"\n  HTML-only listing with no contact info detected")
                    print(f"  Found {len(detail_urls)} member detail page links")

    # --- Step 8.5: Construct detail URLs from UIDs in shallow JSON data ---
    # MembershipWorks and similar platforms return JSON with uid fields but no
    # detail links in the DOM (they use hash-fragment routes like #!biz/id/{uid}).
    # If no detail links were found, check UID-bearing records directly for
    # shallowness (don't use is_shallow_data — it gets fooled by unrelated JSON
    # like chat widget localization files that have keys like "email"/"phone").
    if not detail_urls:
        uid_list = []
        for result in results:
            data = result.get("data", {})
            # Check top-level list
            members = data if isinstance(data, list) else None
            # Check nested list inside dict (e.g. {"typ":"a", "usr":[...]})
            if not members and isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list) and len(val) >= 3:
                        if isinstance(val[0], dict) and "uid" in val[0]:
                            members = val
                            break
            if members:
                # Check if these specific records lack contact info
                sample = members[:20]
                has_contact = 0
                for m in sample:
                    if isinstance(m, dict) and any(
                        k.lower() in CONTACT_KEYS and m[k] and str(m[k]).strip()
                        for k in m
                    ):
                        has_contact += 1
                if has_contact / len(sample) >= 0.2:
                    print(f"  UID records already have contact info ({has_contact}/{len(sample)} sampled) — skipping")
                    continue
                for m in members:
                    if isinstance(m, dict) and "uid" in m:
                        uid_list.append(m["uid"])

        if uid_list:
            # Deduplicate while preserving order
            seen = set()
            unique_uids = []
            for uid in uid_list:
                if uid not in seen:
                    seen.add(uid)
                    unique_uids.append(uid)
            uid_list = unique_uids
            # Build detail URLs using the page's base URL + hash fragment
            base_url = page.url.split("#")[0].rstrip("/")
            detail_urls = [f"{base_url}#!biz/id/{uid}" for uid in uid_list]
            print(f"\n  Shallow JSON data with UIDs detected (MembershipWorks pattern)")
            print(f"  Constructed {len(detail_urls)} detail URLs from JSON uid fields")

    browser.close()
    print(f"Total results captured: {len(results)}")

    # Debug summary of everything captured
    json_count = sum(1 for r in results if isinstance(r.get("data"), (list, dict)) and "raw_html" not in r.get("data", {}))
    html_count = sum(1 for r in results if isinstance(r.get("data"), dict) and "raw_html" in r.get("data", {}))
    debug.log("CAPTURE", f"Final capture summary", data={
        "total_results": len(results),
        "json_responses": json_count,
        "html_pages": html_count,
        "detail_urls_found": len(detail_urls),
        "page_links_collected": len(all_page_links),
        "final_page_url": page.url if not page.is_closed() else "closed",
    })
    if not results:
        print("No responses were captured!")

    return results, detail_urls