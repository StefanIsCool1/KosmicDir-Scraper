"""
Configuration constants for the directory scraper.
All keywords, timeouts, selectors, and API settings live here.
"""

import os
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# --- API KEYS ---
# Set in .env file: DEEPSEEK_API_KEY=sk-...
# LLM client wiring lives in Bot/llm.py

# --- TIMEOUTS ---
DEFAULT_IDLE_TIMEOUT = 4        # seconds of silence before closing browser
SEARCH_IDLE_TIMEOUT = 20        # seconds after search trigger (results take longer)
PAGINATION_IDLE_TIMEOUT = 30    # seconds when paginating through results
NETWORK_IDLE_TIMEOUT = 5000     # ms for page.wait_for_load_state("networkidle")
PAGE_WAIT_AFTER_ACTION = 1500   # ms to wait after clicking/searching

# --- DETAIL PAGE CRAWLING ---
DETAIL_CRAWL_DELAY_MIN = 0.5   # min seconds between detail page requests
DETAIL_CRAWL_DELAY_MAX = 1.5   # max seconds between detail page requests
DETAIL_SAMPLE_COUNT = 3         # number of sample pages to learn selectors from

# URL keywords that indicate a detail link is directory-related
# Used to score template groups — templates with these keywords rank higher
DETAIL_URL_KEYWORDS = [
    "member", "profile", "company", "detail", "listing",
    "vendor", "supplier", "directory", "contact", "business",
    "organization", "firm", "provider",
    "doctor", "physician", "dentist", "attorney", "lawyer",
    "restaurant", "clinic", "specialist", "consultant", "therapist",
]

# --- SEARCH INPUT DETECTION ---
# Primary selectors: standard search inputs (type=search, placeholder hints, id/name hints)
SEARCH_INPUT_SELECTORS = (
    "input[type='search'], "
    "input[placeholder*='search' i], "
    "input[placeholder*='name' i], "
    "input[placeholder*='find' i], "
    "input[placeholder*='filter' i], "
    "input[placeholder*='keyword' i], "
    "input[placeholder*='company' i], "
    "input[placeholder*='doctor' i], "
    "input[placeholder*='restaurant' i], "
    "input[placeholder*='attorney' i], "
    "input[placeholder*='provider' i], "
    "input[placeholder*='business' i], "
    "input[placeholder*='practice' i], "
    "input[id*='search' i], "
    "input[name*='search' i], "
    "input[id*='find' i], "
    "input[name*='find' i], "
    "input[id*='query' i], "
    "input[name*='query' i], "
    "input[id*='keyword' i], "
    "input[name*='keyword' i]"
)

# Fallback selectors: form-based directory inputs (e.g. YourMembership, GrowthZone)
# These match inputs in multi-field forms like Name / Company / City + Continue button.
# Only used when primary selectors find nothing.
FORM_INPUT_SELECTORS = (
    "input[name*='name' i][type='text'], "
    "input[name*='company' i][type='text'], "
    "input[name*='employer' i][type='text'], "
    "input[name*='member' i][type='text'], "
    "input[name*='business' i][type='text'], "
    "input[name*='organization' i][type='text'], "
    "input[name*='doctor' i][type='text'], "
    "input[name*='provider' i][type='text'], "
    "input[name*='practice' i][type='text'], "
    "input[name*='restaurant' i][type='text'], "
    "input[name*='attorney' i][type='text']"
)

# Labels / nearby-text patterns that indicate a "name" field (preferred for searching).
# When multiple form inputs match, we pick the one whose label matches these patterns.
PREFERRED_NAME_FIELD_LABELS = [
    "name", "member name", "company name", "business name",
    "organization name", "last name", "first name",
    "practice name", "restaurant name", "firm name",
    "provider name", "office name", "doctor name",
    "attorney name", "clinic name", "professional name",
]

# --- SEARCH CONTEXT VALIDATION ---
# Words/phrases found in the surrounding DOM context (label, nearby text, heading,
# button text) that STRONGLY indicate the input is for a member/business directory search.
# Each entry is scored +15 confidence.
DIRECTORY_SEARCH_POSITIVE_CONTEXT = [
    "member directory", "find a member", "search members", "member search",
    "find a doctor", "doctor search", "physician directory", "physician search",
    "find an attorney", "attorney search", "lawyer directory",
    "find a restaurant", "restaurant search",
    "find a provider", "provider directory", "provider search",
    "company search", "business directory", "business search",
    "search by name", "search by company", "search by keyword",
    "browse members", "member listing", "directory search",
    "find a dentist", "dentist search", "clinic search",
    "search our directory", "search the directory",
]

# Words/phrases that STRONGLY indicate the input is NOT a directory search
# (newsletter, login, contact-form, site-wide blog search, etc.).
# Each entry is scored -15 confidence.
DIRECTORY_SEARCH_NEGATIVE_CONTEXT = [
    "newsletter", "subscribe", "email signup", "join our mailing list",
    "enter your email", "sign up for", "signup",
    "username", "password", "sign in", "log in", "login",
    "forgot password", "forgot your password", "remember me",
    "contact us", "send message", "get in touch", "your message",
    "search site", "search website", "search blog", "search articles",
    "search products", "search shop", "product search",
    "request a quote", "get a quote", "request quote",
    "register", "create account", "new account",
]

# Submit button texts that suggest a directory search form (preferred).
DIRECTORY_SEARCH_BUTTON_TEXTS = [
    "search", "find", "continue", "go", "submit",
    "search directory", "find members", "find a member",
    "find a doctor", "find an attorney",
]

# Submit button texts that suggest a NON-directory form (rejected).
NON_DIRECTORY_BUTTON_TEXTS = [
    "send", "subscribe", "sign up", "signup", "sign in",
    "log in", "login", "register", "contact", "reset password",
    "request quote", "get quote",
]

# --- FORM DETECTION ---
# Submit button selectors for form-based directories.
# Used when form inputs are detected via FORM_INPUT_SELECTORS.
FORM_SUBMIT_SELECTORS = (
    "input[type='submit'], "
    "button[type='submit'], "
    "input[type='button'][value*='search' i], "
    "input[type='button'][value*='continue' i], "
    "input[type='button'][value*='find' i], "
    "button:has-text('Search'), "
    "button:has-text('Continue'), "
    "button:has-text('Find'), "
    "button:has-text('Submit'), "
    "button:has-text('Go')"
)


# --- RESPONSE CAPTURE: KEYWORDS ---
# JSON responses containing these words (in data OR url) are treated as directory data
# Third-party domains that NEVER contain directory member data.
# Responses from these domains are silently skipped — no content inspection needed.
JSON_JUNK_DOMAINS = [
    "split.io", "cookielaw.org", "onetrust.com",       # feature flags / cookie consent
    "google-analytics.com", "googletagmanager.com",     # analytics
    "google.com/maps", "maps.googleapis.com",           # maps
    "facebook.com", "facebook.net", "fbcdn.net",        # social
    "twitter.com", "x.com",                             # social
    "linkedin.com",                                     # social
    "doubleclick.net", "googlesyndication.com",         # ads
    "list-manage.com", "mailchimp.com", "mcsv.net",    # newsletter / Mailchimp
    "youtube.com", "youtu.be", "ytimg.com",             # video
    "cloudflare.com", "cloudflareinsights.com",         # CDN / security
    "newrelic.com", "nr-data.net",                      # monitoring
    "sentry.io", "sentry-cdn.com",                      # error tracking
    "hotjar.com", "hotjar.io",                          # heatmaps
    "clarity.ms",                                       # Microsoft Clarity
    "stripe.com", "stripe.network",                     # payments
    "recaptcha.net", "gstatic.com",                     # captcha / static
    "segment.io", "segment.com",                        # analytics
    "hubspot.com", "hsforms.com",                       # marketing
    "intercom.io",                                      # chat
    "zendesk.com", "zdassets.com",                      # support
    "amplitude.com",                                    # analytics
    "mixpanel.com",                                     # analytics
    "optimizely.com",                                   # A/B testing
    "launchdarkly.com",                                 # feature flags
    "unpkg.com", "cdnjs.cloudflare.com", "jsdelivr.net", # CDN
    "fontawesome.com", "fonts.googleapis.com",          # fonts
    # --- Publisher analytics / session recording / heatmaps ---
    "crazyegg.com",                                     # heatmaps + session recording
    "chartbeat.com", "chartbeat.net",                   # publisher real-time analytics
    "scorecardresearch.com", "comscore.com",            # audience measurement
    "quantcast.com", "quantserve.com",                  # audience data
    "piwik.pro", "matomo.cloud",                        # analytics (alternative to GA)
    "parsely.com", "parsely.net",                       # publisher analytics
    "adobedtm.com", "demdex.net", "omtrdc.net",         # Adobe Analytics / Audience Manager
    "krxd.net",                                         # Salesforce / Krux DMP
    # --- Ad bidders / exchanges / SSPs ---
    "atmtd.com", "automatad.com",                       # header bidding (floor prices)
    "adsrvr.org",                                       # The Trade Desk
    "criteo.com", "criteo.net",                         # retargeting
    "indexww.com",                                      # Index Exchange
    "openx.net",                                        # OpenX SSP
    "pubmatic.com",                                     # PubMatic SSP
    "rubiconproject.com",                               # Magnite / Rubicon SSP
    "bidswitch.net",                                    # ad cookie sync
    "adnxs.com", "adnxs.net",                           # Xandr / AppNexus
    "casalemedia.com",                                  # Index Exchange affiliate
    "smartadserver.com",                                # Smart AdServer
    "taboola.com", "outbrain.com",                      # content recommendation widgets
    "moatads.com",                                      # ad verification (Oracle)
    "adsafeprotected.com",                              # IAS ad verification
    "doubleverify.com",                                 # ad verification
    # --- B2B / intent data (returns JSON but never directory members) ---
    "6sc.co", "6sense.com",                             # B2B intent data
    "bizible.com", "marketo.com",                       # marketing attribution
]

JSON_DIRECTORY_KEYWORDS = [
    "member", "user", "directory", "contact", "company",
    "listing", "organization", "vendor", "supplier",
    "contractor", "provider", "business", "firm",
    "result", "roster",
    "doctor", "physician", "dentist", "attorney", "lawyer",
    "restaurant", "clinic", "specialist", "consultant", "therapist",
]

# URL patterns that indicate a JSON response is directory-related
# Checked separately from data content — catches APIs like /GetDirectoryBasicInfo
JSON_URL_KEYWORDS = [
    "directory", "member", "getdirectory", "company",
    "listing", "search", "roster", "find",
    "contact", "vendor", "supplier", "provider",
    "doctor", "physician", "attorney", "lawyer",
    "restaurant", "clinic", "practice", "professional",
]

# URL patterns that EXCLUDE a JSON response from being treated as directory data
# These endpoints match JSON_URL_KEYWORDS but never contain actual member records
JSON_URL_EXCLUDE_PATTERNS = [
    "filter", "config", "setting", "auth", "token",
    "login", "session", "analytics", "visitor",
    "tracking", "nrdata", "nr-data", "newrelic", "stripe",
    "partytown",  # web-worker proxy (walmart etc.) — forwards browser API
                  # calls as JSON; tokens like "user"/"vendor" pass Method 1
]

# Whole-word URL tokens that veto a JSON response (matched with the same
# camelCase-aware tokenizer as Method 1, NOT substring like the patterns
# above). Commerce endpoints — cart/checkout GraphQL ops like Walmart's
# MergeAndGetCart — never hold directory members, but their multi-KB
# payloads carry stray keyword tokens ("member" via membership-upsell
# fields), so Method 1 flags them. A substring "cart" pattern above would
# also veto legit URLs like ?city=Cartersville; tokenizing splits
# MergeAndGetCart into {merge, and, get, cart} while "cartersville" stays
# one token, so only real cart endpoints match.
JSON_URL_EXCLUDE_TOKENS = {
    "cart", "carts", "checkout", "basket", "wishlist",
}

# Field names that signal a JSON response contains member/company records
# If a JSON object/array has 3+ of these keys, it's probably directory data
JSON_STRUCTURE_FIELDS = [
    "name", "companyname", "company_name", "businessname",
    "organizationname", "providername", "practicename",
    "restaurantname", "firmname", "doctorname", "displayname",
    "phone", "mainphone", "phonenumber", "telephone",
    "website", "url", "web", "homepage",
    "address", "city", "state", "zipcode", "zip", "postalcode",
    "email", "fax", "specialties", "category", "type",
    "specialty", "cuisine", "practicearea", "services",
]

# URL patterns that indicate a response is directory-related (for HTML responses)
DIRECTORY_URL_KEYWORDS = [
    "member", "directory", "search", "contact", "listing",
    "result", "roster", "find", "company",
    "doctor", "provider", "attorney", "restaurant",
    "clinic", "practice", "professional",
]

# --- PAGINATION ---
NEXT_BUTTON_SELECTORS = (
    "a:has-text('Next'), a:has-text('next'), "
    "a:has-text('>>'), a:has-text('»'), "
    "a:has-text('›'), a:has-text('→'), "
    "a[rel='next'], "
    "button:has-text('Next'), button:has-text('next'), "
    "button:has(i.fa-arrow-right), "
    "button:has(i.fa-chevron-right), "
    "button:has(i[class*='arrow-right']), "
    "button:has(i[class*='chevron-right']), "
    "a:has(i.fa-arrow-right), "
    "a:has(i.fa-chevron-right), "
    "[class*='next']:not([class*='disabled']):not([class*='prev']), "
    "a[aria-label='Next page'], a[aria-label='next page'], "
    "a[aria-label='Next'], a[aria-label='Go to next page'], "
    "li.next > a, li.pagination-next > a"
)

LOAD_MORE_SELECTORS = (
    "button:has-text('Load More'), button:has-text('load more'), "
    "button:has-text('LOAD MORE'), "
    "button:has-text('Show More'), button:has-text('show more'), "
    "button:has-text('View More'), button:has-text('view more'), "
    "a:has-text('Load More'), a:has-text('LOAD MORE'), "
    "a:has-text('Show More'), a:has-text('View More'), "
    "input[value*='Load More' i], "
    "input[value*='Show More' i], "
    "input[value*='View More' i], "
    "[role='button']:has-text('Load More'), "
    "[role='button']:has-text('LOAD MORE'), "
    "[class*='load-more'], [class*='loadmore'], "
    "[class*='show-more'], [class*='showmore']"
)

# --- RESULT COUNTING (for search strategy evaluation) ---
RESULT_COUNT_SELECTORS = [
    "[class*='member']",
    "[class*='listing']",
    "[class*='directory']",
    "[class*='result']",
    "[class*='card']",
    "[class*='company']",
    "[class*='vendor']",
    "[class*='doctor']",
    "[class*='restaurant']",
    "[class*='attorney']",
    # Staff/roster directories (schools, universities, government).
    # Finalsite renders div.fsConstituentItem — without 'constituent' here a
    # 50-card page counted ~7 via the link fallback, and every downstream
    # decision (search strategy, alphabet commit, pagination skip) ran blind.
    # The `i` flag is required: class names camelCase ('fsConstituentItem'),
    # and attribute selectors are case-sensitive by default.
    "[class*='constituent' i]",
    "[class*='staff' i]",
    "[class*='faculty' i]",
    "[class*='employee' i]",
    "[class*='people' i]",
    "table tbody tr",
]

RESULT_LINK_SELECTORS = (
    "a[href*='member'], a[href*='profile'], "
    "a[href*='company'], a[href*='detail'], "
    "a[href*='listing'], a[href*='doctor'], "
    "a[href*='restaurant'], a[href*='attorney']"
)

# --- HTML PARSING ---

# Tags to strip entirely before analyzing page structure
JUNK_TAGS = ["script", "style", "svg", "img", "noscript"]

# CSS selectors for junk containers to remove before card detection
JUNK_CONTAINER_SELECTORS = [
    "nav", "header", "footer", "aside",
    "[class*='menu']", "[class*='sidebar']",
    "[class*='cookie']", "[class*='modal']",
    "[class*='popup']", "[class*='banner']",
    "[class*='toolbar']", "[class*='breadcrumb']",
    "[class*='social']", "[class*='share']",
    "[class*='newsletter']", "[class*='subscribe']",
    "[role='navigation']", "[role='banner']",
    "[role='complementary']",
]

# Tags to search for member cards, in priority order
CARD_CANDIDATE_TAGS = ["article", "tr", "li", "div", "figure", "section"]

# Class fragments that indicate layout wrappers (not real content cards)
LAYOUT_CLASS_EXACT = {
    "container", "wrapper", "layout", "header", "footer",
    "nav", "sidebar", "row", "col", "column", "section",
    "page", "site", "main", "content", "body", "inner", "outer",
}

LAYOUT_CLASS_FRAGMENTS = [
    "fl-row", "fl-col", "fl-module",           # Beaver Builder
    "elementor-section", "elementor-column",    # Elementor
    "elementor-widget", "elementor-container",
    "wp-block",                                 # Gutenberg
    "vc_row", "vc_column",                      # WPBakery
    "divi_", "et_pb_",                          # Divi
    "avada-", "fusion-",                        # Avada
]

# Keywords in class names that suggest real member cards
CARD_CLASS_HINTS = [
    "member", "listing", "card", "result",
    "company", "directory", "profile", "vendor",
    "supplier", "contractor", "provider", "business",
    "entry", "item", "record", "row",
    "doctor", "physician", "attorney", "lawyer",
    "restaurant", "clinic", "specialist", "consultant",
]

# Contact-like content signals inside cards
CONTACT_SIGNALS = [
    "phone", "email", "tel:", "mailto:", "@",
    "address", "fax", "website", "www.", "http",
]

# --- EXTRACTION VALIDATION ---
SCALAR_KEYS = ["company_name", "description", "category", "website", "phone"]
EXTRACTION_NULL_THRESHOLD = 0.70  # if more than 70% of fields are null, extraction failed

# Minimum cards needed before calling Haiku (avoids learning from tiny samples)
MIN_CARDS_FOR_LEARNING = 3

# Minimum candidate cards a page must show before an INVALID cached-selector
# result is allowed to delete the cache and re-learn. Near-empty pages (an
# alphabet letter with 0-2 staff, a no-results skeleton) legitimately yield
# nothing under good cached selectors; re-learning on them caches nav chrome
# and poisons every subsequent page. A genuine redesign re-learns on the next
# full listing page instead.
RELEARN_MIN_CARDS = 10

# --- REGEX FALLBACK ---
# Domains to skip when extracting member websites (never a member's own site)
EXTERNAL_SKIP_DOMAINS = [
    "google.com", "facebook.com", "twitter.com", "linkedin.com",
    "instagram.com", "youtube.com", "yelp.com", "maps.google",
    "goo.gl", "bit.ly", "apple.com", "microsoft.com",
    "x.com", "tiktok.com", "pinterest.com",
]

# Minimum regex extraction results to accept (anti-false-positive)
MIN_REGEX_RESULTS = 3

# Characters to search before a phone number for "fax" label
FAX_CONTEXT_WINDOW = 50

# --- ADAPTIVE SCROLL ---
SCROLL_BATCH_SIZE = 5           # scrolls per batch before checking for new content
SCROLL_STALE_THRESHOLD = 3     # consecutive batches with no growth before stopping

# --- CATEGORY BROWSING ---
# URL keywords that suggest a link group is category-based navigation
CATEGORY_URL_KEYWORDS = [
    "category", "categories", "browse", "type", "specialty",
    "specialties", "trade", "service", "industry", "sector",
    "classification", "division", "cuisine", "practice-area",
    "discipline",
]

# Minimum visible results on page before skipping category iteration
# (if members are already visible, no need to iterate categories)
CATEGORY_SKIP_VISIBLE_THRESHOLD = 3

# Largest link group detect_category_links will accept. State/city partition
# hubs routinely exceed the old cap of 50 (Walmart Minnesota lists 65 cities);
# the uniqueness + nav-exclusion filters keep tag clouds out.
CATEGORY_MAX_LINKS = 200

# Minimum same-template child links (of the CURRENT page path) for a page to
# count as a listing hub — used by the pre-search hub check in browser.py.
# High on purpose: skipping search is only safe when the page is clearly a
# partition index (per-city / per-category sub-pages), not a busy nav.
CHILD_HUB_MIN_LINKS = 8

# --- INTENT-DRIVEN DEEP CAPTURE (Agent mode only; intent=None skips all) ---
# Step 2.5 in capture_responses fires only when the run captured LESS than
# both of these — i.e. the normal search flow left the targeted intent
# unfulfilled and it's worth replaying XHRs / crawling intent sub-pages.
INTENT_LOW_RECORDS = 30    # JSON member records
INTENT_LOW_VISIBLE = 25    # visible result cards

# Intent sub-page crawl (discover_intent_subpages): BFS over intent-matched
# category/sub-directory links. Depth 2 covers /directory/{category}/{city}.
INTENT_MAX_SUBPAGES = 40
INTENT_SUBPAGE_DEPTH = 2

# XHR replay (replay_directory_xhrs): re-fetch captured directory APIs with
# mutated page/term/letter params through the browser's own cookie jar.
XHR_MAX_REPLAYS = 60             # total replayed requests per run
XHR_MAX_PAGINATION_PAGES = 30    # pages walked per paginated endpoint

# Query-param names recognized by _find_enumerable_params. Matched on the
# lowercased param name; page-like params get incremented, term-like params
# get the intent terms substituted, letter-like params iterate a-z0-9.
XHR_PAGE_PARAMS = {"page", "pg", "pagenum", "pagenumber", "offset", "start", "skip", "p"}
XHR_TERM_PARAMS = {"q", "query", "search", "keyword", "keywords", "term",
                   "name", "category", "cat", "type", "specialty", "industry"}
XHR_LETTER_PARAMS = {"letter", "alpha", "startswith", "char"}

# --- RESOURCE BLOCKING ---
# Block these resource types — the bot only uses JSON and HTML responses.
# CSS is kept (needed for is_visible() checks and element positioning).
# JS is kept (needed for SPAs, AJAX, form submission).
# We ONLY block by resource type, not by domain — some sites detect
# blocked analytics (anti-adblock) and refuse to show content.
_BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}


# --- STEALTH / ANTI-BOT EVASION ---
# Launch flags that lower the automation fingerprint. The single most important
# one is --disable-blink-features=AutomationControlled, which removes the
# navigator.webdriver=true tell at the browser level (the cheapest check
# DataDome/Cloudflare run). We deliberately keep this list SHORT and safe:
# flags like --disable-features=IsolateOrigins,site-per-process are omitted
# because they break the iframe result-frame flow this scraper depends on.
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

# Playwright adds these by default; they advertise automation to anti-bot
# fingerprinters. Dropping them is safe for normal scraping.
_IGNORE_DEFAULT_ARGS = ["--enable-automation"]


def launch_browser(playwright):
    """Launch a browser for scraping. Single point for all three launch sites
    (browser.py, detail_crawler.py x2).

    Default is HEADED — the interactive login/CAPTCHA flow needs a visible
    window. Set SCRAPER_HEADLESS=1 to run headless (servers / CI, where headed
    Chromium crashes on a missing display).

    Prefers real Google Chrome (channel="chrome") when it's installed — a
    genuine Chrome build has a much stronger fingerprint (real UA, media
    codecs, component-updater traffic) than bundled headless Chromium. Falls
    back to the bundled Chromium when Chrome isn't present on this machine."""
    headless = os.environ.get("SCRAPER_HEADLESS", "").strip() == "1"
    launch_kwargs = dict(
        headless=headless,
        args=STEALTH_LAUNCH_ARGS,
        ignore_default_args=_IGNORE_DEFAULT_ARGS,
    )
    try:
        return playwright.chromium.launch(channel="chrome", **launch_kwargs)
    except Exception:
        # Real Chrome not installed / not launchable — use bundled Chromium.
        return playwright.chromium.launch(**launch_kwargs)


def _clean_user_agent(browser) -> str | None:
    """Build a realistic desktop-Chrome user agent matching the launched
    browser's major version and the host OS. Used to strip the 'HeadlessChrome'
    token that headless Chromium leaks (its loudest tell). Returns None if the
    version can't be read, so the caller keeps the native UA rather than risk a
    mismatched one."""
    try:
        version = browser.version  # e.g. "140.0.7339.5"
        major = version.split(".")[0]
        if not major.isdigit():
            return None
    except Exception:
        return None
    import sys as _sys
    if _sys.platform == "darwin":
        platform_token = "Macintosh; Intel Mac OS X 10_15_7"
    elif _sys.platform.startswith("win"):
        platform_token = "Windows NT 10.0; Win64; x64"
    else:
        platform_token = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_token}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def new_stealth_page(browser):
    """Create a page inside a context tuned to look like a normal desktop-Chrome
    session: consistent locale/timezone/viewport, a clean user agent (no
    'HeadlessChrome' token when headless), and navigator.webdriver removed.

    Single point used by browser.py and detail_crawler.py so every page the
    scraper opens carries the same, non-automated-looking fingerprint. Cookie
    persistence still works — page.context is the context created here."""
    headless = os.environ.get("SCRAPER_HEADLESS", "").strip() == "1"
    context_opts = dict(
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1440, "height": 900},
        color_scheme="light",
    )
    # Only override the UA when headless (to strip 'HeadlessChrome'). In headed
    # mode the native UA is already clean, and overriding risks a UA vs.
    # sec-ch-ua client-hint mismatch (which is itself a fingerprint).
    if headless:
        ua = _clean_user_agent(browser)
        if ua:
            context_opts["user_agent"] = ua

    context = browser.new_context(**context_opts)
    # Belt-and-suspenders webdriver cover via an init script (runs before any
    # page script). Redundant with the launch flag and with patchright, but
    # it's the only webdriver protection detail_crawler pages get without the
    # stealth plugin.
    try:
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
    except Exception:
        pass
    return context.new_page()


def block_unnecessary_resources(page):
    """Block images, fonts, and media to speed up page loads.
    Call AFTER stealth setup, BEFORE navigation.
    Only blocks by resource type — no domain blocking to avoid
    triggering anti-adblock walls on directory sites."""
    def _route_handler(route):
        if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    page.route("**/*", _route_handler)


def unblock_resources(page):
    """Remove the image/font/media route block (see block_unnecessary_resources)
    so a paused human sees a fully-rendered page — e.g. an image-based CAPTCHA
    challenge that would otherwise show broken tiles. Call
    block_unnecessary_resources(page) again to restore blocking afterwards.
    This module is the only place that routes "**/*", so unrouting it is safe."""
    try:
        page.unroute("**/*")
    except Exception:
        pass


# --- SELECTOR CACHE ---
SELECTOR_CACHE_FILENAME = "selector_cache.json"