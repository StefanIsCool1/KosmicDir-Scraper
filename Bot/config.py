"""
Configuration constants for the directory scraper.
All keywords, timeouts, selectors, and API settings live here.
"""

import os

# --- API KEYS ---
os.environ["ANTHROPIC_API_KEY"] = "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"

# --- TIMEOUTS ---
DEFAULT_IDLE_TIMEOUT = 4        # seconds of silence before closing browser
SEARCH_IDLE_TIMEOUT = 20        # seconds after search trigger (results take longer)
PAGINATION_IDLE_TIMEOUT = 30    # seconds when paginating through results
NETWORK_IDLE_TIMEOUT = 5000     # ms for page.wait_for_load_state("networkidle")
PAGE_WAIT_AFTER_ACTION = 1500   # ms to wait after clicking/searching

# --- SEARCH INPUT DETECTION ---
SEARCH_INPUT_SELECTORS = (
    "input[type='search'], "
    "input[placeholder*='search' i], "
    "input[placeholder*='name' i], "
    "input[placeholder*='find' i], "
    "input[placeholder*='filter' i], "
    "input[placeholder*='keyword' i], "
    "input[placeholder*='company' i], "
    "input[id*='search' i], "
    "input[name*='search' i], "
    "input[id*='find' i], "
    "input[name*='find' i], "
    "input[id*='query' i], "
    "input[name*='query' i], "
    "input[id*='keyword' i], "
    "input[name*='keyword' i]"
)

# Minimum result count to accept a search strategy as "good enough"
SEARCH_GOOD_ENOUGH_THRESHOLD = 20

# --- RESPONSE CAPTURE: KEYWORDS ---
# JSON responses containing these words (in data OR url) are treated as directory data
JSON_DIRECTORY_KEYWORDS = [
    "member", "user", "directory", "contact", "company",
    "listing", "organization", "vendor", "supplier",
    "contractor", "provider", "business", "firm",
    "result", "roster",
]

# URL patterns that indicate a JSON response is directory-related
# Checked separately from data content — catches APIs like /GetDirectoryBasicInfo
JSON_URL_KEYWORDS = [
    "directory", "member", "getdirectory", "company",
    "listing", "search", "roster", "find",
    "contact", "vendor", "supplier", "provider",
]

# Field names that signal a JSON response contains member/company records
# If a JSON object/array has 3+ of these keys, it's probably directory data
JSON_STRUCTURE_FIELDS = [
    "name", "companyname", "company_name", "businessname",
    "phone", "mainphone", "phonenumber", "telephone",
    "website", "url", "web", "homepage",
    "address", "city", "state", "zipcode", "zip", "postalcode",
    "email", "fax", "specialties", "category", "type",
]

# URL patterns that indicate a response is directory-related (for HTML responses)
DIRECTORY_URL_KEYWORDS = [
    "member", "directory", "search", "contact", "listing",
    "result", "roster", "find", "company",
]

# --- PAGINATION ---
NEXT_BUTTON_SELECTORS = (
    "a:has-text('Next'), a:has-text('next'), "
    "a:has-text('>>'), a:has-text('›'), "
    "a[rel='next'], "
    "button:has-text('Next'), button:has-text('next'), "
    "[class*='next']:not([class*='disabled']):not([class*='prev']), "
    "a[aria-label='Next page'], a[aria-label='next page'], "
    "a[aria-label='Next'], "
    "li.next > a, li.pagination-next > a"
)

LOAD_MORE_SELECTORS = (
    "button:has-text('Load More'), button:has-text('load more'), "
    "button:has-text('Show More'), button:has-text('show more'), "
    "button:has-text('View More'), button:has-text('view more'), "
    "a:has-text('Load More'), a:has-text('Show More'), "
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
    "table tbody tr",
]

RESULT_LINK_SELECTORS = (
    "a[href*='member'], a[href*='profile'], "
    "a[href*='company'], a[href*='detail'], "
    "a[href*='listing']"
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

# --- SELECTOR CACHE ---
SELECTOR_CACHE_FILENAME = "selector_cache.json"