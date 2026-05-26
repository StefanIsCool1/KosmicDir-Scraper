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
│   └── url_enumeration.py # URL-parameter enumeration for GET-form directories
├── Phase2Bot/             # Phase 2: website enrichment (curl_cffi)
│   ├── __init__.py
│   ├── page_fetcher.py    # TLS-fingerprinted HTTP requests, DDG search
│   └── email_extractor.py # Email/phone/social/JSON-LD extraction
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
`stage`, `intent_parsed`, `needs_clarification`, `discovery_query`, `discovery_query_done`, `candidates_found`, `preflight_result`, `preflight_done`, `classified`, `discovery_complete`, `confirmation_required`, `confirmation_accepted`, `scrape_started`, `log`, `scrape_done`, `scrape_error`, `complete`

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
