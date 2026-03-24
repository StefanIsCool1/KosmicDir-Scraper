# UnderDeck Scraper

A universal directory scraping tool that extracts member/business data from any directory website. Combines Playwright browser automation with AI-powered selector learning (Claude Haiku) to adapt to any directory structure — no per-site configuration needed.

Built by **Stefan O'Leary**

---

## How It Works

### Two-Phase System

**Phase 1 — Directory Scraping**: Discovers directory pages, captures JSON APIs and HTML, learns CSS selectors via AI, extracts structured member data.

**Phase 2 — Website Enrichment**: Takes Phase 1 output, visits each company's website, extracts additional contact info, descriptions, social media, hours, services, and more.

---

## Phase 1 Flow

```
User provides URL
        ↓
1. NAVIGATE — AI finds the directory page (up to 3 clicks deep)
        ↓
2. SEARCH — Tries blank/"all"/"a"/"%"/"*" queries, detects starts-with sites
        ↓
3. CAPTURE — Intercepts JSON API responses + captures page HTML
        ↓
4. PAGINATE — Clicks Next/Load More, numbered pages, handles infinite scroll
        ↓
5. EXTRACT — 3-tier: cached selectors → AI-learned selectors → regex fallback
        ↓
6. DETAIL CRAWL (optional) — Visits individual profile pages for full contact info
        ↓
7. OUTPUT — Cleaned, deduplicated JSON in Data-dump/
```

### Step 1: Navigation (`navigator.py`)

The bot uses **Claude Haiku** to analyze each page and decide: is this the directory page, or should I click a link to go deeper?

- Sends the page's links + visible text to Haiku
- Haiku responds: `STAY` (we're on the directory), `CLICK 7` (click link #7), or `NONE`
- Navigates up to 3 pages deep (Homepage → Membership → Find a Member → Directory)
- Detects both single search inputs and multi-field forms (Name/Company/City + Submit)

### Step 2: Search Strategy (`navigator.py`)

Smart search with escalating queries:

1. **Blank search** — most sites return all results
2. **"all"** — catches sites that need a keyword
3. **"a"** — if results only start with 'A', detected as starts-with site → iterates full alphabet
4. **"%"** — wildcard patterns some CMS platforms support

After each query, reads the result count (regex first, Haiku fallback) and keeps the best result. Re-executes the winning query so the page shows maximum results for HTML capture.

### Step 3: Network Capture (`browser.py`)

A Playwright response listener intercepts every network request:

- **JSON responses**: Inspected for directory keywords (`member`, `company`, `listing`), URL patterns (`/api/members`, `/GetDirectoryInfo`), and structural fields (objects with `name` + `phone` + `address`). Junk domains (analytics, ads, social) are silently skipped.
- **HTML responses**: Queued for later parsing if they match directory URL patterns.

### Step 4: Pagination (`browser.py`)

Handles three pagination patterns:
- **Numbered pages** — clicks 2, 3, 4, 5...
- **Next/Arrow buttons** — clicks →, Next, ›, »
- **Load More buttons** — clicks "Load More", "Show More"

Detects stale clicks (URL + content unchanged after click = last page) and stops. Skips pagination entirely if JSON already captured 50+ records.

### Step 5: HTML Extraction (`html_parser.py`)

Three-tier strategy, each more expensive than the last:

**Tier 1 — Cached Selectors** (zero cost):
Previously learned CSS selectors are stored in `selector_cache.json`. If a domain was scraped before, selectors are reused instantly.

**Tier 2 — AI Selector Learning** (one Haiku call, then cached forever):
- Scores repeating HTML elements to find member cards (class-based grouping + schema.org detection)
- Sends 4 sample cards to Claude Haiku with a prompt asking for CSS selectors
- Haiku returns: `card_selector`, `company_name`, `phone`, `website`, `street_address`, etc.
- Applied with BeautifulSoup — zero AI cost after initial learning

**Tier 3 — Regex Fallback** (zero cost, no AI):
When selectors fail:
- **Layer A**: Uses the card container from Tier 2's scoring, runs regex within each card
- **Layer B**: Scans the page for clusters of contact signals (phone + email near a heading)

### Step 6: Detail Crawling (`detail_crawler.py`)

When listing data is shallow (names only, no contact info):
- Detects detail page links by URL templatizing (`/members/{ID}`, `/profile/{ID}`)
- Prompts user: "Found 748 detail pages. Crawl them? (y/n)"
- Learns selectors for detail pages (separate from listing selectors)
- Adaptive throttle — speeds up when server responds fast, backs off on slow responses

### Step 7: Normalization (`main.py`, `cleaner.py`)

- **Field mapping**: Maps 20+ variant field names to a standard schema
- **Platform support**: Unwraps Airtable (`fields:{}`), Procore (`addresses:[]`), GrowthZone, ChamberMaster formats
- **Deduplication**: Case-insensitive company name matching
- **Phone formatting**: Normalizes to `(XXX) XXX-XXXX`
- **Website normalization**: Adds `https://` to bare domains

---

## Phase 2 Flow

```
Select a _structured.json from Phase 1
        ↓
1. Filter entries with website but missing data
        ↓
2. For each company website (8 parallel workers):
   a. Fetch homepage (curl_cffi with Chrome TLS fingerprint)
   b. Extract: emails, phones, address, description, social, JSON-LD
   c. Discover subpages: /contact, /about, /team, /services
   d. Fetch + extract each subpage
   e. Merge (contact page overrides homepage)
        ↓
3. Build enriched record (original fields preserved, new data fills gaps)
        ↓
4. Output → Phase2-Dump/{domain}_enriched.json
```

### What Phase 2 Extracts

| Field | Method |
|-------|--------|
| **Email** | `mailto:` links → regex on visible text |
| **Phone** | `tel:` links → regex with fax context detection |
| **Address** | Full street address regex (number + street type + city/state/zip) |
| **Description** | JSON-LD → `<meta description>` → og:description → first substantial `<p>` |
| **Social Media** | Links to Facebook, LinkedIn, Twitter, Instagram, YouTube, TikTok, Pinterest, Yelp |
| **Hours** | Elements near "hours"/"schedule" keywords |
| **Services** | List items under "Services"/"What We Do" headings |
| **Team** | Name+title pairs from team/staff page structures |
| **Founded Year** | Regex: "founded/established/since" + 4-digit year |
| **JSON-LD** | Structured data from `<script type="application/ld+json">` — highest confidence source |

### TLS Fingerprint Impersonation

Phase 2 uses `curl_cffi` because many sites use TLS fingerprinting (JA3/JA4) to detect bots. `curl_cffi` impersonates real Chrome/Safari TLS handshakes — servers can't distinguish it from a real browser.

- Rotates between 7 browser fingerprints
- On 403: retries with a different fingerprint
- Thread-local sessions for connection pooling + cookie persistence

---

## Output Schema

### Phase 1 (`Data-dump/{domain}_structured.json`)

```json
{
    "company_name": "ABC Construction Inc.",
    "description": null,
    "category": "Builder/Residential",
    "website": "https://abcconstruction.com",
    "phone": "(320) 555-1234",
    "fax": "(320) 555-1235",
    "street_address": "123 Main St, St. Cloud, MN 56301",
    "mailing_address": null,
    "contacts": [
        {"name": "John Smith", "email": "john@abcconstruction.com"}
    ]
}
```

### Phase 2 (`Phase2-Dump/{domain}_enriched.json`)

All Phase 1 fields preserved, plus:

```json
{
    "social_media": {
        "facebook": "https://facebook.com/abcconstruction",
        "linkedin": "https://linkedin.com/company/abc-construction"
    },
    "hours": "Mon-Fri 7:00am - 5:00pm",
    "services": ["Custom Homes", "Remodeling", "Additions"],
    "founded": "1985",
    "team": [{"name": "John Smith", "title": "Owner"}],
    "enrichment_source": "https://abcconstruction.com",
    "enrichment_status": "enriched"
}
```

---

## External APIs & Libraries

### Anthropic Claude Haiku
- **Page analysis**: "Is this a directory page?" — 1 call per navigation depth
- **Selector learning**: "What CSS selectors extract member data?" — 1 call per domain, cached forever
- **Cost**: ~$0.001 per new domain (subsequent scrapes are free)

### Playwright (Chromium)
- Browser automation: navigation, form filling, clicking, scrolling
- Network response interception for JSON API capture
- `playwright-stealth` patches to bypass Cloudflare/DataDome bot detection

### curl_cffi (Phase 2)
- HTTP requests with Chrome/Safari TLS fingerprint impersonation
- Bypasses JA3/JA4 fingerprint-based bot detection that blocks `requests` and `httpx`

### BeautifulSoup
- HTML parsing and CSS selector application
- Junk container removal (nav, header, footer, sidebar, cookie banners)

### Flask + React
- Flask backend with SSE (Server-Sent Events) for real-time progress streaming
- React frontend with interactive terminal, multiple scraping modes

---

## Anti-Detection Stack

| Layer | What | How |
|-------|------|-----|
| **TLS Fingerprint** | Browser-identical TLS handshake | `curl_cffi impersonate="chrome"` (Phase 2), `playwright-stealth` (Phase 1) |
| **HTTP Headers** | Realistic Sec-Fetch-*, Accept headers | Randomized per request |
| **Browser Fingerprint** | navigator.webdriver=false, real plugin list | `playwright-stealth` patches |
| **Behavioral** | Human-like scrolling, random delays | `human_scroll()`, per-domain throttle |

---

## Installation

```bash
git clone https://github.com/StefanIsCool1/UnderDeckScraper.git
cd UnderDeckScraper/UnderDeckScraper

# Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install flask flask-cors playwright anthropic curl-cffi beautifulsoup4 playwright-stealth

# Install Chromium
playwright install chromium

# Frontend
cd frontend && npm install && cd ..
```

## Running

```bash
# Terminal 1: Backend
source .venv/bin/activate
python3 app.py
# → http://localhost:5000

# Terminal 2: Frontend
cd frontend
npm start
# → http://localhost:3000
```

## Usage Modes

| Mode | Description |
|------|-------------|
| **Auto Discover** | Provide any URL — bot finds the directory page and scrapes it |
| **Direct Scrape** | Provide the exact directory page URL — skips navigation |
| **CSV** | Upload a CSV of URLs for batch scraping |
| **Phase 2** | Select a Phase 1 JSON — enriches companies with website data |

---

## Project Structure

```
UnderDeckScraper/
├── Bot/
│   ├── config.py          # All constants, keywords, selectors, timeouts
│   ├── browser.py         # Playwright automation, response capture, pagination
│   ├── navigator.py       # AI navigation, search strategies
│   ├── html_parser.py     # 3-tier extraction (cache → AI → regex)
│   ├── detail_crawler.py  # Detail page detection and crawling
│   ├── main.py            # Pipeline orchestration, JSON normalization
│   ├── cleaner.py         # Deduplication, phone formatting
│   ├── cache.py           # Selector cache persistence
│   └── debug.py           # Optional debug logging
├── Phase2Bot/
│   ├── email_extractor.py # Website enrichment (all extractors + JSON-LD)
│   └── page_fetcher.py    # curl_cffi with TLS fingerprinting
├── Data-dump/             # Phase 1 output (raw + structured JSON)
├── Phase2-Dump/           # Phase 2 output (enriched JSON)
├── frontend/
│   └── src/App.js         # React UI with terminal and modes
├── app.py                 # Flask backend with SSE streaming
└── README.md
```

---

## Performance

| Metric | Typical Value |
|--------|---------------|
| Phase 1 scrape time | 30s - 5min (depends on pagination depth) |
| Phase 2 enrichment (245 entries) | ~2 min (8 parallel workers) |
| AI cost per new domain | ~$0.001 (cached after first scrape) |
| Phase 2 success rate | ~80% enrichment rate |
| Selector cache | 100% hit rate after first scrape |

---

## Troubleshooting

**Port 5000 conflict**: macOS AirPlay Receiver uses port 5000. Disable it in System Settings → General → AirDrop & Handoff → AirPlay Receiver, or run Flask on a different port.

**No results**: Check the terminal for specific errors. Common causes:
- Site requires login (member portal)
- Site blocks automated browsers (Cloudflare challenge)
- JavaScript-rendered SPA with no static HTML content

**Phase 2 failures**: Sites returning "failed to fetch" are typically:
- Dead domains or expired SSL certificates
- Cloudflare JS challenges (requires full browser, not HTTP requests)
- Server timeout (slow hosting)

---

## License

MIT
