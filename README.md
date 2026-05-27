# Kosomic Scraper 
(a directory built scraper)
**FEEL FREE TO PULL REQUEST OR GIVE ME ADVICE ON STUFF**
A universal directory scraping tool that extracts data from directory website. Combines Playwright browser automation with AI-powered selector learning (DeepSeek V4 Flash) to adapt to different website structuring.

Built by **Stefan O'Leary**

---

## How It Works

Two primary phases in the system:

**Phase 1 — Directory Scraping**: Discovers directory pages, listens to network or captures page html to learns CSS selectors via AI/regex, extracts structured member data into a structured json file

**Phase 2 — Website Enrichment**: Takes the phase output website, then enriches the data by Fetching homepage or other important subpahes (curl_cffi with Chrome TLS fingerprint)

---

## Phase 1 Flow

```
User provides URL:

1. NAVIGATE, AI and regex find apporaite direcory (up to 3 pages deep)
2. SEARCH,  Tries blank/"all"/"a"/"%"/"*" queries, detects starts-with sites
3. CAPTURE — Intercepts JSON API responses + captures page HTML
4. PAGINATE — Clicks Next/Load More, numbered pages, handles infinite scroll (captues the html subsequntly after scrolling or paginating)
5. EXTRACT: uses chache sleectors/learns them via AI or buetifulsoup
6. DETAIL CRAWL (optional) — Visits individual profile pages for full contact info. for example example.com/member/{memberid}
        ↓
7. OUTPUT the output is a cleaned json file
```


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



***TLS Fingerprint Impersonation***

So basically, Phase 2 uses `curl_cffi` because many sites use TLS fingerprinting (JA3/JA4) to detect bots. `curl_cffi` impersonates real Chrome/Safari TLS handshakes — servers can't distinguish it from a real browser.

- Rotates between 7 browser fingerprints chrome and others
- On 403: retries with a different fingerprint
- Thread-local sessions for connection pooling + cookie persistence


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

All Phase 1 fields preserved, plus: (basically data to build consumer profile)

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

***External APIs & Libraries***

### DeepSeek (deepseek-v4-flash)
- **Page analysis**: "Is this a directory page?" — 1 call per navigation depth
- **Selector learning**: 1 call per new domain (cached forever after)
- All LLM calls go through `Bot/llm.py` — swap providers there.

PLAYWRIGHT:

Browser automation: navigation, form filling, clicking, scrolling
Network response catching
In this project ***playwright-stealth*** is also utlized to  bypass Cloudflare/DataDome bot detection

Formally ***requests*** now switched to  curl_cffi  for better function(Phase 2)
- HTTP requests with Chrome/Safari TLS fingerprint impersonation
- Bypasses JA3/JA4 fingerprint-based bot detection that blocks `requests` and `httpx`

***BeautifulSoup***
- HTML parsing and CSS selector application
- Junk container removal (nav, header, footer, sidebar, cookie banners)
- used in mutiple scnearious as a fallback when ai fails to learn

### Flask + React
- Flask backend with SSE (Server-Sent Events) for real-time progress streaming
- React frontend with interactive terminal, multiple scraping modes

---

## Anti-Detection Stack

| Layer | What | How |


## Installation
YOU WILL NEED A DEEPSEEK API KEY FOR THIS TO WORK (this bot doesn't use many tokens). Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY`.
```bash
git clone https://github.com/StefanIsCool1/UnderDeckScraper.git
cd UnderDeckScraper/UnderDeckScraper

# Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install flask flask-cors playwright openai python-dotenv curl-cffi beautifulsoup4 playwright-stealth

# Install Chromium
playwright install chromium

# Frontend
cd frontend && npm install && cd ..
```

The LLM client uses the OpenAI-compatible DeepSeek endpoint (`https://api.deepseek.com`). The `openai` SDK is installed only as the HTTP client — it is pointed at DeepSeek in `Bot/llm.py`. Swap `_BASE_URL` and `_MODEL` there to change providers.

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
 Update read me, to have actual dependcies 