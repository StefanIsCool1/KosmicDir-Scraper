# Repository Guidelines

## Pipeline Overview

```
User: "HOAs in Washington"
         │
    ┌────▼─────────────────────────────────┐
    │  Phase 0 — Discovery & Routing       │
    │  DiscoveryBot/                        │
    │                                       │
    │  1. Intent Parsing (1 LLM call)       │
    │     "HOA" → canonical name + aliases  │
    │     "Washington" → WA, major cities   │
    │                                       │
    │  2. Source Discovery (DDG search)     │
    │     Runs generated search queries,    │
    │     collects candidate URLs           │
    │                                       │
    │  3. Pre-flight Check (curl_cffi)      │
    │     Rejects dead, login-gated, thin,  │
    │     and non-directory URLs in parallel│
    │                                       │
    │  4. Classification & Routing          │
    │     DIRECTORY → Phase 1               │
    │     WEBSITE   → Phase 2 directly      │
    │     REJECT    → discarded             │
    └────┬──────────┬──────────────────────┘
         │          │
    ┌────▼────┐     │
    │ Phase 1 │     │
    │ Bot/    │     │
    │         │     │
    │ Playwright browser                  │
    │ AI navigation + search strategies   │
    │ Pagination + iframe handling        │
    │ Detail page crawling                │
    │ 3-tier HTML parsing (cache→AI→regex)│
    │ Dedup + normalization               │
    └────┬────┘     │
         │          │
         ▼          ▼
    ┌─────────────────────────────┐
    │  Phase 2 — Website Enrichment│
    │  Phase2Bot/                  │
    │                              │
    │  DDG search for missing URLs │
    │  TLS-impersonated HTTP fetch │
    │  JSON-LD + regex extraction  │
    │  Social, hours, team, etc.   │
    └──────────────────────────────┘
         │
         ▼
    Structured JSON / CSV / Excel output
```

### Beyond the diagram (added since it was drawn)

- **Phase 0 API fast-path.** When a goal maps to an authoritative public registry, Phase 0 skips DDG / preflight / classify / browser and pulls structured data directly. One vertical today — **NPI** (US healthcare practitioners: dentists, chiropractors, optometrists, PTs, etc.). `intent.py` emits `api_vertical`/`api_params`; `pipeline._maybe_api_route` validates the taxonomy (`vertical_enrichment.resolve_npi_taxonomies`) + a US state and returns early; `app.py` calls `npi_search_by_taxonomy` and saves a normal `_structured.json`. Misses (vets, broad "doctors", no state) fall back to discovery.
- **Intent-aware Phase 1** (Agent mode only — Playground passes `intent=None`, so it stays byte-for-byte unchanged). *Stage 2 — source narrowing*: fetch only the relevant `<select>` categories (`url_enumeration.py` + `intent_filter.py`) or run an intent-first search-box query on cross-vertical aggregators (`navigator.py`). *Stage 1 — record filter*: drop off-target records after extraction (`intent_record_filter.py`), gated by a `scope` knob ("specialist" vs "inclusive") the user sets via a `scope_refinement_required` prompt. Both fail-open.
  - **"Scrape everything" is `intent=None`.** `intent.py` emits a `coverage` field (`all` | `targeted`); `intent_filter.intent_from_plan` maps `coverage=="all"` → `None`, so a whole-directory goal runs today's plain wildcard flow with zero intent behavior. Everything below is therefore gated on a non-`None` (targeted) intent.
  - **Intent deep capture** (`browser.py` Step 2.5, targeted intent only, non-aggregator, non-hub) fires when the normal flow left yield low (`< INTENT_LOW_RECORDS` member records AND `< INTENT_LOW_VISIBLE` visible). Two reuse-heavy passes: (a) `replay_directory_xhrs` re-fetches captured directory-API endpoints through `page.context.request` (browser cookies/clearance ride along) with mutated page / intent-term / letter params, gated back through the same `_is_directory_json`; (b) `discover_intent_subpages` BFS-crawls intent-matched category/sub-directory links (`detect_category_links(ignore_visible=True, top_groups=3)` for candidates, `filter_categories_by_intent` strict-subset for the pick, cached per domain+industry under `intent_nav_<domain>`), feeding each page into the existing collect-links / capture-HTML / paginate recipe. Caps in `config.py` (`INTENT_MAX_SUBPAGES`, `INTENT_SUBPAGE_DEPTH`, `XHR_MAX_REPLAYS`, …). Complicated-search sites also get an intent-terms search fallback in `trigger_search` when the wildcard chain finds nothing usable.
- **Standalone sites are selectable.** The Phase 0 picker lets the user choose WEBSITE-class single businesses to enrich via Phase 2, not just directories.
- **Final deliverable.** Every `/discover` run with output ends by consolidating ALL its files (Phase 1 structured, Phase 2 enriched — read from `Phase2-Dump/`, which the old Data-dump-only merge silently skipped — NPI pulls, standalone sites) into `Data-dump/{industry}_{states}_final.json` + `.xlsx` via `exporter.py`: duplicates across sources merged field-by-field, canonical key order, empty fields dropped, records sorted and source-tagged, metadata with per-source counts + field coverage. The `complete` SSE event carries `final_json` / `final_xlsx` (plus legacy `merged_file`), and the Agent result bubble shows JSON / CSV / Excel buttons. `exporter.py` is also the single home of the flatten/CSV logic `/download` uses.
- **Run tracing.** `/discover` always writes debug traces: Phase 0 → `Debug-dump/discover_<ts>_phase0_debug.json`, then each Phase 1 site → `Debug-dump/{domain}_debug.json`. Every entry carries elapsed seconds; `span` entries carry durations (where the time went); `decision` entries carry what the bot chose at each fork and why (STAY/CLICK, skip pagination, intent XHR replay + sub-page expansion, back-out, garbage gate, Phase 0 routing). Enable for CLI runs with `SCRAPER_DEBUG=1`; `Bot/debug.py` is the singleton, `save_report()` writes the file.

## Data Acquisition Strategies (how records are actually extracted)

Phase 1 tries the cheapest viable path first:
1. **URL-param enumeration** (`url_enumeration.py`) — GET-form `<select>` → fetch each option's URL in parallel via curl_cffi, no browser. Detects *narrowing filter vs partition* (probes the unfiltered URL); with intent, enumerates only the matching categories.
2. **Network / JSON capture** (`browser.py`) — member data lifted from the page's own XHR/JSON beats HTML parsing.
3. **Search + pagination** (`navigator.py`, `browser.py`) — fill the search box (blank/`%`/`all`/`a`, or intent-first on aggregators), then paginate: URL-template pagination first (`?page=N` / `/page/N/` links fetched over parallel HTTP), clicking (Next / numbered / Load More) as the fallback. **Skipped entirely on listing hubs**: when the page shows ≥`CHILD_HUB_MIN_LINKS` same-template child links of its own path (walmart.com/store-directory/mn → per-city pages), no member-shaped JSON, and <3 visible cards, `detect_category_links(child_hub_of=…)` flags it pre-search and the child pages are iterated as categories instead — a site-wide search box would otherwise hijack the run. Hub partitions (geography/A-Z) bypass the intent category filter; gates count member *records* via `_count_json_member_records`, so junk JSON (Partytown proxies, cart GraphQL) can't block category discovery.
4. **Intent-driven sub-page expansion** (`browser.py:discover_intent_subpages` + `replay_directory_xhrs`, Step 2.5) — after search/pagination, when a *targeted* intent is still under-served (`< INTENT_LOW_VISIBLE` visible AND `< INTENT_LOW_RECORDS` JSON records), replay captured directory XHRs with mutated params, then BFS-crawl intent-matched category/city sub-pages (depth `INTENT_SUBPAGE_DEPTH`, ≤`INTENT_MAX_SUBPAGES`, same-origin), each crawled + paginated like a category. Reuses `detect_category_links` (relaxed via `ignore_visible`/`top_groups`) and `filter_categories_by_intent` (strict-subset so it fails closed). No-op when `intent is None` (Playground / direct / "scrape everything"), on hubs, and on aggregators. (Supersedes an earlier `ai_discover_listing_links` LLM-nav design that was documented here but never landed in code.)
5. **3-tier HTML parse** (`html_parser.py`) — JSON-LD (zero AI) → cached selector → AI-learned (DeepSeek) → regex. Selectors cached per-domain in `selector_cache.json` forever (~1 AI call per new domain). The learner classifies each domain's cards into one of three entity types, all cached in the same schema entry: **business** (default fixed schema: `company_name`/phone/address/contacts — byte-for-byte unchanged), **person** (fixed schema for rosters, faculty/staff/team pages: `full_name`, `pronouns`, `title`, `department`, `office`, `email`, `phone`, `personal_website`; dedup on name+email; no regex fallback), and **dynamic** (any other noun — product, vehicle, … — free-form role-tagged `fields[]`). `main.py`/`cleaner.py`/`exporter.py`/CSV all route on the cached `entity_type` + `name_field`.
6. **Detail-page crawl** (`detail_crawler.py`) — optional per-member profile pages, cheapest first: **curl-first** (parallel curl_cffi; extraction mode picked on samples: JSON-LD → cached/learned selectors → regex → merge) → API fast-path (browser probes one page for a per-member JSON endpoint) → Playwright crawl. Falls down the ladder on hash-route URLs, JS shells, blocked fetches, or failed validation; merges, aborts on invalid.
7. **NPI API** — the Phase 0 fast-path above; no scraping at all.
8. **Phase 2 enrichment** (`Phase2Bot/`) — fill gaps from each company's site: derive the domain from a contact email, else DDG-find (with opt-in verify-by-fetch "accurate" mode that fetches+scores top candidates), then TLS-fetch + JSON-LD/regex. Vertical-routed first (NPI for healthcare, tuned DDG for lawyers/realtors).

## Project Structure & Module Organization

```
KosmicDir-Scraper/
├── DiscoveryBot/          # Phase 0: source discovery & intelligent routing
│   ├── __init__.py        # Package exports: run_discovery, parse_intent
│   ├── intent.py          # 1 LLM call: free-form goal → structured search plan
│   ├── sources.py         # Web search discovery (DDG), platform dorking
│   ├── preflight.py       # Parallel curl_cffi qualification per candidate URL
│   ├── classifier.py      # DIRECTORY vs WEBSITE vs REJECT routing
│   └── pipeline.py        # Orchestrates steps 1→4, emits SSE progress events
├── Bot/                   # Phase 1: directory scraping (Playwright + AI)
│   ├── config.py          # Constants, timeouts, keywords, API settings
│   ├── browser.py         # Playwright automation, network capture, pagination
│   ├── navigator.py       # AI-driven site navigation & search strategies
│   ├── html_parser.py     # 3-tier extraction: cache → AI-learned → regex fallback
│   ├── detail_crawler.py  # Detail-page detection and crawling
│   ├── main.py            # Pipeline orchestration & JSON normalization
│   ├── cleaner.py         # Deduplication & phone formatting
│   ├── cache.py           # Per-domain selector & URL-enumeration cache persistence
│   ├── llm.py             # LLM client (DeepSeek V4 Flash, OpenAI-compatible)
│   ├── debug.py           # Run tracing: timed spans + decisions → Debug-dump reports
│   ├── url_enumeration.py # URL-param enumeration (narrowing-filter detect + intent narrowing)
│   ├── intent_filter.py   # Stage 2: scope-aware source category selection; intent_from_plan()
│   └── intent_record_filter.py # Stage 1: drop off-target records after extraction (fail-open)
├── Phase2Bot/             # Phase 2: website enrichment (curl_cffi)
│   ├── __init__.py
│   ├── page_fetcher.py    # TLS-fingerprinted HTTP requests, DDG search, verify-and-pick
│   ├── email_extractor.py # Email/phone/social/JSON-LD extraction
│   └── vertical_enrichment.py # Per-vertical enrichment + NPI bulk search (Phase 0 API route)
├── frontend/              # React + Vite + TailwindCSS UI
│   ├── src/pages/
│   │   ├── Landing/       # Marketing landing page
│   │   ├── Playground/    # Manual URL scraper (Phase 1 + Phase 2 UI)
│   │   ├── Agent/         # AI chat agent (Phase 0 UI: describe goal → scrape)
│   │   ├── Pricing/       # Pricing page
│   │   └── Docs/          # Documentation page
│   ├── src/components/    # Shared: Navbar, Footer, Button
│   └── src/hooks/         # useSSE (streaming), useTypewriter
├── Data-dump/             # Phase 1 output (_structured.json) + per-run _final.json/_final.xlsx
├── Phase2-Dump/           # Phase 2 output (_enriched.json files)
├── Debug-dump/            # Per-run debug traces (_debug.json — actions, timings, decisions)
├── exporter.py            # Final deliverable: consolidated clean JSON + Excel; flatten/CSV logic
├── cookies/               # Per-domain Playwright cookies (login persistence)
├── app.py                 # Flask backend with SSE streaming
└── .env                   # DEEPSEEK_API_KEY (gitignored)
```

## Modules That Cross-Reference Each Other

DiscoveryBot reuses components from both Phase 1 and Phase 2 without modifying them:

| DiscoveryBot Module | Reuses |
|---|---|
| `intent.py` | `Bot/llm.py:ask()` — the LLM client |
| `sources.py` | `Phase2Bot/page_fetcher.py:_ddg_fetch_results()` — DDG HTML search |
| `preflight.py` | `Phase2Bot/page_fetcher.py:fetch_page()` — TLS-impersonated HTTP fetch |
| `classifier.py` | `Bot/html_parser.py:extract_sample_html()` — structural card detection |
| `pipeline.py` | `Phase2Bot/vertical_enrichment.py:resolve_npi_taxonomies()`/`npi_search_by_taxonomy()` — Phase 0 NPI API route |

(Within Phase 1, `url_enumeration.py` and `intent_record_filter.py` reuse `Bot/intent_filter.py` for scope-aware category/record matching.)

No DiscoveryBot module imports from Bot modules that pull in Playwright — the dependency chain is strictly curl_cffi and BeautifulSoup, keeping Phase 0 lightweight and fast.

## Backend API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/scrape/single` | POST | Phase 1: scrape a single directory URL. Streams SSE. |
| `/scrape/respond` | POST | Interactive y/n response from frontend terminal. |
| `/scrape/csv` | POST | Batch scrape from uploaded CSV. |
| `/scraped-sites` | GET | List previously scraped domains. |
| `/discover` | POST | Phase 0: parse goal → discover → classify → auto-scrape via Phase 1 + Phase 2. Streams SSE. |
| `/phase2/enrich` | POST | Standalone Phase 2 enrichment on an existing structured JSON file. |
| `/phase2/files` | GET | List structured JSON files with enrichment potential stats. |
| `/download/<filename>` | GET | Download results as JSON (?format=json) or CSV (?format=csv); `.xlsx` filenames are served as binary Excel. |
| `/a` | POST | Analytics beacon — page views + events from `frontend/src/hooks/useAnalytics.js`. SQLite-backed (`Data-dump/analytics.db`). |
| `/analytics/stats` | GET | Aggregate analytics, gated by `ANALYTICS_PASSWORD`. Backs the dashboard served at stats.trawlbase.com (host-detected in `frontend/src/main.jsx`). |

## SSE Event Types (for Frontend Integration)

### Phase 0 (`/discover`) events:
`stage` (carries a `stage` value: `intent` / `discovery` / `preflight` / `classify` / `api_route`), `intent_parsed`, `needs_clarification`, `discovery_query`, `discovery_query_done`, `candidates_found`, `preflight_result`, `preflight_done`, `classified`, `discovery_complete`, `scope_refinement_required`, `confirmation_required`, `confirmation_accepted`, `scrape_started`, `scrape_skipped`, `log`, `scrape_done`, `scrape_error`, `complete`

The `confirmation_required` payload carries both `directories` and `websites`; the frontend posts back a JSON list of selected URLs (mixed) via `/scrape/respond`, which `app.py` partitions. `scope_refinement_required` and the picker share one blocking `response_event`, so they run sequentially.

### Phase 1 (`/scrape/single`) events:
`session`, `log` (with category), `prompt` (y/n detail crawl), `complete` (with field_coverage), `error`

## Build, Test & Development Commands

```bash
# Backend setup
python3 -m venv .venv && source .venv/bin/activate
pip install flask flask-cors playwright openai python-dotenv curl-cffi beautifulsoup4 playwright-stealth
playwright install chromium

# Start backend (port 5000)
python3 app.py

# Frontend setup & dev server (port 3000)
cd frontend && npm install && npm run dev

# Vite production build
cd frontend && npm run build
```

**Note:** macOS AirPlay Receiver occupies port 5000. Disable it in System Settings, or set `FLASK_RUN_PORT` to an alternative.

There are currently no automated tests in this repository.

## Coding Style & Naming Conventions

- **Python:** 4-space indentation, `snake_case` for functions/variables, `CAPITALIZED_SNAKE_CASE` for constants. Docstrings use triple-double-quote format (`""" ... """`). Import order: stdlib → third-party → local modules.
- **JavaScript/React:** Follows Vite + React conventions. Functional components only. TailwindCSS for styling — avoid inline styles.
- **File naming:** `snake_case.py` for Python modules, PascalCase for React components.
- **Environment variables:** Store secrets in `.env` (see `.env.example`). The `config.py` module loads them via `python-dotenv`.
- **No linters or formatters** are currently configured. Run your code through `python -m flake8` or `npx eslint` locally before contributing.

## Testing Guidelines

The project does not yet have a test suite. When adding tests:

- Use `pytest` for Python and `vitest` (or Jest) for the frontend.
- Name test files `test_*.py` and place them alongside the module under test or in a `tests/` directory.
- Run Python tests with `python -m pytest`. Run frontend tests with `cd frontend && npm test`.

## Commit & Pull Request Guidelines

- **Commit messages:** Use imperative mood, descriptive but concise (e.g., `add pagination timeout config`, `fix json output for empty fields` — following the existing history style).
- **PRs:** Reference the issue or feature you're addressing. Include a brief summary of changes and how to test them. If your change affects output formats (JSON schema, field names), state that explicitly.
- **Data files:** Do not commit data dumps or `.env` files. These are gitignored via `*.json` and `.env` rules.

## Security & Configuration Tips

- Never commit your `.env` file. Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` with your own key.
- The `api_key/` directory is gitignored — it contains the original key file for local use only.
- Phase 2 uses `curl_cffi` with rotating TLS fingerprints to avoid bot detection. Respect `DETAIL_CRAWL_DELAY_MIN/MAX` timing constants in `config.py` to avoid overwhelming target servers.
- The LLM module (`Bot/llm.py`) uses DeepSeek V4 Flash via the OpenAI-compatible protocol; swap `_BASE_URL` and `_MODEL` to change providers without touching any other code.
- Playwright launches **headed** by default (the login flow needs a visible window). Set `SCRAPER_HEADLESS=1` to run headless on servers/CI — all three launch sites go through `Bot/config.py:launch_browser`.
- Phase 0 also uses `curl_cffi` (via Phase 2's `fetch_page`) for pre-flight qualification. Same TLS fingerprint rotation applies.

## Roadmap / Known Gaps

Open work, roughly by leverage:

- **Search resilience.** ~~Hard-stop on first DDG 429/403~~ — `_ddg_fetch_results` now falls back to Bing HTML search (`_bing_fetch_results`) for the rest of the run when DDG blocks. Still open: surface "search blocked / running on fallback engine" as an SSE event, and a real search API for when both HTML endpoints break.
- **Phase 2 accuracy.** The DDG website-find writes unverified matches → false positives. Score the DDG snippet/title/domain against the record's **phone** (the join key) *before* fetching; fail **closed** (a blank field beats a wrong company); attach a per-record confidence label. The `accurate` verify-by-fetch mode exists but is slow (3–9 fetches/record).
- **More API verticals.** NPI proved the pattern; clean next sources are the IRS exempt-org file (nonprofits), FDIC/NCUA (banks/credit unions), SEC EDGAR, FEC. Route on canonical industry + taxonomy, not the coarse `entity_type`.
- **NPI completeness.** The public API caps at ~1,200 records/query (surfaced via `hit_ceiling`); the monthly NPPES bulk file is the real path for "every X in a large state".
- **Vertical-aware queries.** Discovery queries are generic ("X directory / find a X / X member list"); bias toward authoritative aggregators per vertical for better candidates.
- **Last mile.** Email deliverability check, dedup against the customer's existing list, and push to Google Sheets / CRM — turns the JSON dump into a usable workflow.
- **Product direction.** Pre-built per-vertical datasets and done-for-you lists (sell the *data*, not the scrape); the scraper becomes the data-production engine rather than the product.
