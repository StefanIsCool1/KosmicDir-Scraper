# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` contains the canonical pipeline diagram, module-by-module layout, API endpoint table, and SSE event vocabulary. Read it first when touching anything beyond a single file — this CLAUDE.md only covers what's not already there.

## Commands

```bash
# Backend (port 5000 — disable macOS AirPlay Receiver or override FLASK_RUN_PORT)
source .venv/bin/activate
python3 app.py

# Frontend (port 3000)
cd frontend && npm run dev      # dev server
cd frontend && npm run build    # production build

# Ad-hoc test scripts (not a real suite — plain `python3` scripts, no pytest config)
python3 test_url_enumeration.py
python3 test_cleaner_fixes.py

# Install / first-time setup
pip install flask flask-cors playwright openai python-dotenv curl-cffi beautifulsoup4 playwright-stealth
playwright install chromium
cd frontend && npm install
```

No linter, formatter, or test runner is configured. There is no `requirements.txt` — dependencies are documented in `AGENTS.md` and must be pip-installed manually.

## Architecture (the parts you can't see by reading one file)

Three phases, each in its own top-level package, chained but independently runnable:

- **DiscoveryBot/** (Phase 0) — free-form goal → DDG search → preflight qualification → classifier routes each URL to Phase 1 (DIRECTORY), Phase 2 (WEBSITE), or REJECT. Strictly `curl_cffi` + BeautifulSoup; **never imports Playwright code from Bot/**, which keeps Phase 0 fast and light. It reuses `Bot/llm.py:ask`, `Phase2Bot/page_fetcher.py:_ddg_fetch_results`/`fetch_page`, and `Bot/html_parser.py:extract_sample_html` — see the cross-reference table in AGENTS.md.
- **Bot/** (Phase 1) — Playwright + AI directory scraper. The extraction pipeline in `html_parser.py` is **3-tier and order matters**: cached selector → AI-learned (DeepSeek) → regex fallback. Selectors are cached per-domain in `cache.py` and reused forever, so AI cost is ~one call per new domain. `main.py` orchestrates; `navigator.py` decides where to click; `browser.py` owns the Playwright session and network capture; `detail_crawler.py` optionally visits per-member profile pages.
- **Phase2Bot/** (Phase 2) — website enrichment via `curl_cffi` with rotating Chrome/Safari TLS fingerprints (bypasses JA3/JA4 detection that blocks `requests`/`httpx`). 8 parallel workers, on 403 retry with a different fingerprint, thread-local sessions for cookie/connection reuse.

**`app.py` is a single ~1000-line Flask file.** It owns every endpoint listed in AGENTS.md and streams progress to the frontend over SSE. Event names are a contract with `frontend/src/hooks/useSSE` and the page components in `frontend/src/pages/`; see the SSE event-type list in AGENTS.md before renaming or adding events.

**LLM provider swap** is intentionally single-point: change `_BASE_URL` and `_MODEL` in `Bot/llm.py`. Everything else uses the OpenAI-compatible client through `ask()`.

**Output layout:** Phase 1 writes `Data-dump/{domain}_structured.json` as `{"metadata": {...counts...}, "members": [...]}` — older bare-list dumps still read fine via `Bot/main.py:read_members`/`read_metadata`, which accept both shapes. Phase 2 writes `Phase2-Dump/{domain}_enriched.json` (a bare list) preserving all Phase 1 fields and filling gaps. The Phase 0 **NPI route** and **standalone-site** scrape also write `Data-dump/*_structured.json` in the same metadata+members shape. `.gitignore` excludes `*.json`, so dumps never get committed — `git status` won't show new output files.

**Agent-mode intelligence is layered and Playground-safe.** Everything intent-driven — scope filtering (Stage 1 record filter + Stage 2 source category narrowing), aggregator intent-search, URL-enum category narrowing, and Phase 0 API routing — is gated on a non-`None` `intent`. Playground (`/scrape/single`, `/scrape/csv`) passes `intent=None`, so those paths stay unchanged. Two single-point seams: **API routing** lives in `DiscoveryBot/pipeline.py:_maybe_api_route` + `Phase2Bot/vertical_enrichment.py` (a new vertical = one `resolve_npi_taxonomies`-style entry + one bulk fn), and **scope** flows from the Phase 0 question through `Bot/intent_filter.py:intent_from_plan`. See AGENTS.md → *Beyond the diagram* and *Data Acquisition Strategies* for the full map, and *Roadmap / Known Gaps* for open work.

## Gotchas

- The `.gitignore` rule `*.json` is repo-wide and unscoped — it also hides `frontend/package.json` from `git status` if it were ever deleted. Don't add new JSON config without forcing an add.
- `.env` holds `DEEPSEEK_API_KEY` (loaded by `Bot/config.py` via python-dotenv). The `api_key/` directory is gitignored and is local-only.
- Playwright cookies persist per-domain in `cookies/` — login state survives across runs, which can mask "logged-out" behavior when testing.
- README.md is partly aspirational (mentions OpenAI/Claude; actual LLM is DeepSeek V4 Flash). Trust AGENTS.md and the code over the README.
- `DiscoveryBot/intent.py:_build_prompt` is an **f-string** — every literal `{`/`}` in the embedded JSON schema must be doubled (`{{`/`}}`). A single brace throws at format time and `parse_intent` silently falls back to a keyword-only plan (no scope, no API route) on *every* goal.
- Phase 0 search has a **sticky engine switch**: `Phase2Bot/page_fetcher.py:_search_stopped` trips on the first DDG 429/403; all further queries in that run are transparently routed to the Bing HTML fallback (`_bing_fetch_results`; flag reset at the start of `discover_candidates` / each Phase 2 run). If Bing's markup or `/ck/a` redirect wrapping changes, the fallback degrades to `[]` — the old silent truncation — so grep logs for "DDG blocked".
- Browsers launch **headed** by default (`Bot/config.py:launch_browser`) because the interactive login flow needs a visible window. Set `SCRAPER_HEADLESS=1` for servers/CI — headed Chromium crashes without a display.
- The **NPI API caps ~1,200 records/query** (limit 200 × skip ≤ 1000); `npi_search_by_taxonomy` returns a `hit_ceiling` flag, so large states are partial. `resolve_npi_taxonomies` returns `[]` for vets / broad "doctors" → those deliberately fall back to scraping.
- Scope, the directory picker, and standalone-site selection share the **one** blocking `response_event` + `/scrape/respond` round-trip; they run sequentially (each waits, then clears). Don't add a parallel gate without clearing between waits.
