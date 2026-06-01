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
    Structured JSON / CSV output
```

### Beyond the diagram (added since it was drawn)

- **Phase 0 API fast-path.** When a goal maps to an authoritative public registry, Phase 0 skips DDG / preflight / classify / browser and pulls structured data directly. One vertical today — **NPI** (US healthcare practitioners: dentists, chiropractors, optometrists, PTs, etc.). `intent.py` emits `api_vertical`/`api_params`; `pipeline._maybe_api_route` validates the taxonomy (`vertical_enrichment.resolve_npi_taxonomies`) + a US state and returns early; `app.py` calls `npi_search_by_taxonomy` and saves a normal `_structured.json`. Misses (vets, broad "doctors", no state) fall back to discovery.
- **Intent-aware Phase 1** (Agent mode only — Playground passes `intent=None`, so it stays byte-for-byte unchanged). *Stage 2 — source narrowing*: fetch only the relevant `<select>` categories (`url_enumeration.py` + `intent_filter.py`) or run an intent-first search-box query on cross-vertical aggregators (`navigator.py`). *Stage 1 — record filter*: drop off-target records after extraction (`intent_record_filter.py`), gated by a `scope` knob ("specialist" vs "inclusive") the user sets via a `scope_refinement_required` prompt. Both fail-open.
- **Standalone sites are selectable.** The Phase 0 picker lets the user choose WEBSITE-class single businesses to enrich via Phase 2, not just directories.

## Data Acquisition Strategies (how records are actually extracted)

Phase 1 tries the cheapest viable path first:
1. **URL-param enumeration** (`url_enumeration.py`) — GET-form `<select>` → fetch each option's URL in parallel via curl_cffi, no browser. Detects *narrowing filter vs partition* (probes the unfiltered URL); with intent, enumerates only the matching categories.
2. **Network / JSON capture** (`browser.py`) — member data lifted from the page's own XHR/JSON beats HTML parsing.
3. **Search + pagination** (`navigator.py`) — fill the search box (blank/`%`/`all`/`a`, or intent-first on aggregators), then paginate (path/segment-aware).
4. **3-tier HTML parse** (`html_parser.py`) — cached selector → AI-learned (DeepSeek) → regex. Selectors cached per-domain in `selector_cache.json` forever (~1 AI call per new domain).
5. **Detail-page crawl** (`detail_crawler.py`) — optional per-member profile pages: API fast-path → Haiku selector learning (validated) → regex; merges, aborts on invalid.
6. **NPI API** — the Phase 0 fast-path above; no scraping at all.
7. **Phase 2 enrichment** (`Phase2Bot/`) — fill gaps from each company's site: derive the domain from a contact email, else DDG-find (with opt-in verify-by-fetch "accurate" mode that fetches+scores top candidates), then TLS-fetch + JSON-LD/regex. Vertical-routed first (NPI for healthcare, tuned DDG for lawyers/realtors).

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
│   ├── debug.py           # Optional debug logging
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
├── Data-dump/             # Phase 1 output (_structured.json files)
├── Phase2-Dump/           # Phase 2 output (_enriched.json files)
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
| `/download/<filename>` | GET | Download results as JSON (?format=json) or CSV (?format=csv). |

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
- Phase 0 also uses `curl_cffi` (via Phase 2's `fetch_page`) for pre-flight qualification. Same TLS fingerprint rotation applies.

## Roadmap / Known Gaps

Open work, roughly by leverage:

- **Search resilience.** `Phase2Bot/page_fetcher.py:_ddg_fetch_results` hard-stops *all* queries on the first DDG 429/403 (`_search_stopped`), silently truncating discovery. Add a fallback engine / search API, and surface "search blocked" vs "no sources".
- **Phase 2 accuracy.** The DDG website-find writes unverified matches → false positives. Score the DDG snippet/title/domain against the record's **phone** (the join key) *before* fetching; fail **closed** (a blank field beats a wrong company); attach a per-record confidence label. The `accurate` verify-by-fetch mode exists but is slow (3–9 fetches/record).
- **More API verticals.** NPI proved the pattern; clean next sources are the IRS exempt-org file (nonprofits), FDIC/NCUA (banks/credit unions), SEC EDGAR, FEC. Route on canonical industry + taxonomy, not the coarse `entity_type`.
- **NPI completeness.** The public API caps at ~1,200 records/query (surfaced via `hit_ceiling`); the monthly NPPES bulk file is the real path for "every X in a large state".
- **Vertical-aware queries.** Discovery queries are generic ("X directory / find a X / X member list"); bias toward authoritative aggregators per vertical for better candidates.
- **Last mile.** Email deliverability check, dedup against the customer's existing list, and push to Google Sheets / CRM — turns the JSON dump into a usable workflow.
- **Product direction.** Pre-built per-vertical datasets and done-for-you lists (sell the *data*, not the scrape); the scraper becomes the data-production engine rather than the product.
