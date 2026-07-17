# TrawlBase Phase 1 — Universality Audit + Forward Roadmap (v2)

## Context

`Bot/` (Phase 1) is the Playwright + AI directory scraper. This document is (1) an audit of
how well it generalizes across directory types today — every claim re-verified against the
code, file:line throughout — and (2) a roadmap to make it reliably good per type. Target
archetypes (user-confirmed, US-English only):

- **A. Association / chamber / member directories** — current sweet spot; harden it.
- **B. Plain rosters & tables** — headerless tables, flat A–Z lists,
  name-header-then-sibling-contact, PDF rosters.
- **C. SPA / JS-heavy + POST pagination + aggregators.**
- **D. ZIP / location-gated provider & store locators.**

Architecture decision (user-chosen): an explicit **archetype detector** classifies the landed
page once and routes to per-archetype strategies, rather than accreting more heuristics behind
the existing entry points. Scope decision (user-chosen): everything in, PDF extraction and
ZIP-grid locator enumeration included.

---

## Part 1 — Audit: realistic universality today

**Headline:** the scraper is genuinely platform-agnostic — no per-directory host/domain
branches exist in `Bot/` (the only domain lists are third-party junk filters and
challenge-host maps in `browser.py`, which is anti-bot plumbing, not platform support).
All "platform" branches key on structure: schema.org microdata, CSS-class fragments, iframe
id patterns, GET-form pagination shapes — vendor names appear only in comments. It is best
described as **broadly heuristic with a strong bias toward directories that (a) expose a
search box accepting a blank/wildcard query, (b) render class-named cards or a JSON XHR,
and (c) paginate via GET query params or Next/Load-More buttons.**

| Archetype | Grade | Why |
|---|---|---|
| A. Association / chamber | **B+** | Best case: schema.org tier (+100 bonus, `html_parser.py:664`), iframe handling (`browser.py:667`), GET/Next/alpha pagination, JSON-XHR sniffing, URL-param enumeration fast path (`url_enumeration.py`), listing-hub detection. Held back by the inflated-count premature stop (R2) + no reconciliation (R3). |
| B. Rosters & tables | **C–** | Header-mapped tables work (`html_parser.py:1049`) and classless `<tr>`/`<li>` sibling grouping exists (`html_parser.py:747-784`) — but rows need ≥2 inner elements, so truly flat rows (one text node) fall through; headerless first-cell names are never read (`_extract_company_name` reads only headings/bold/links, `html_parser.py:260`); `<dl>` and heading-then-siblings unsupported; PDFs excluded outright (`navigator.py:44`). |
| C. SPA / POST / aggregators | **C** | Infinite scroll + SPA tail-hash work. The strong XHR-replay engine is intent-gated (`browser.py:388` — dead on Playground/CLI), GET-only (`browser.py:436`; POST bodies aren't even captured), and hard-capped at **300 records / 60 replays / 30 pages** (`browser.py:456-459`, `config.py:472-473`) — its own truncation bug on big aggregators. The fast URL-template pager is query-param-only (`browser.py:834-893`); `/page/2/` sites drop to click pagination, where the 1-extra-segment cap in `_navigated_away` (`browser.py:996`) **misreads `/dir/page/2` as navigating away** and aborts. No cursor/token pagination. |
| D. Location locators | **D** | ZIP-required locators yield ~0: the search chain assumes blank/`%`/`all`/`a` works (`navigator.py:1556+`), location fields are penalized −20 (`navigator.py:806-808`), and no ZIP/city/radius enumeration exists. (`url_enumeration.py` is the one working relative: a state `<select>` enumerates; a ZIP text input does not.) |

### Cross-cutting risks

(Renumbered — v1's list dangled references to undefined items #6–#14 and never resolved its #5.)

- **R1 — Class-substring visible count, wrong in both directions.** `count_visible_results`
  (`navigator.py:896`) counts elements matching English class-substring selectors
  (`config.py:314-337`), MAX across selectors, any rendered element with ≥15 chars of text.
  Substring selectors match a card AND its sub-elements (`[class*='member']` hits
  `member-card`, `member-name`, `member-phone`…), so the count inflates several-fold on
  verbose markup — and deflates to ~0 on hashed/obfuscated CSS. This one number gates the
  stay-guard, search skip, pagination skip, and scroll-growth detection; both failure
  directions cascade through the whole scrape. Single biggest universality risk.
- **R2 — Premature stop.** The inflated count trips `STOP_THRESHOLD = 600`
  (`navigator.py:1181`, checked at 1423/1525) at ~100 real members and stops paginating.
  A partial fix already exists in the blank-total branch (`navigator.py:1618-1643`): it counts
  distinct detail links via `detect_detail_links` — proof the distinct-count route works.
  Containment-dedup counting was tried and reverted — **dead end, don't re-tread it.**
- **R3 — No expected-vs-extracted reconciliation.** `read_result_count` (`navigator.py:1063`)
  parses "N results" (including mid-page "showing 1–50 of N") but nothing ever compares the
  final extraction to it — silent under-extraction passes every quality gate.
- **R4 — No field-completeness gate.** The detail-crawl decision (`main.py:757-784`) checks
  field *presence anywhere in captured JSON*, not per-record coverage of parsed output. A
  link-index roster (names only, contacts on profile pages) ships name-only records without
  ever triggering the detail crawler. Count reconciliation can't catch this — the count matches.
- **R5 — Selector cache: one slot per domain, no layout fingerprint** (`cache.py`).
  Validate-on-use partially exists (failed extraction → re-learn → restore stale schema on
  failure, `html_parser.py:1782-1788`), but a domain with two listing layouts thrashes and
  silently loses one, and a stale selector that still matches *something* extracts garbage
  without tripping the re-learn.
- **R6 — LLM learns from ≤4 sample cards** (`extract_sample_html`, samples `[:4]` at
  `html_parser.py:671/738/780`). Fields that are sparse on the sampled cards never get a
  selector, and the lossy schema is then cached forever. (v1 listed this and no phase fixed it.)
- **R7 — XHR replay caps are fixed constants** (300 records / 60 replays / 30 pages), blind to
  the site's stated total. For "scrape any directory" they are a second, quieter truncation bug.

### Strengths to build on (reuse, don't reinvent)

JSON-XHR sniffing + envelope unwrap (`browser.py:104-158, 226-271`); schema.org/JSON-LD tier;
deterministic table-header mapper (`html_parser.py:1049`); 3-rung detail crawler
curl→API→browser (`detail_crawler.py`); iframe content-frame handling; alphabet iteration;
**listing-hub detection** (`detect_category_links(child_hub_of=…)` — a working HUB-archetype
detector already); `url_enumeration.py`'s narrowing-filter-vs-partition probe; the classifier
already tags `needs_navigation`/`is_aggregator`; `debug.decision` run tracing → `Debug-dump/`;
the login/cookie + CAPTCHA/Live View layer (access problems are handled orthogonally — this
plan never touches them); and **`Data-dump/{domain}.json` raw captures (written at
`main.py:750`) are a ready-made extraction-fixture corpus for ~40 domains — no re-scraping
needed to build tests.**

---

## Part 2 — Roadmap

The spine is a new archetype detector (`Bot/archetype.py`) that runs after navigation lands on
the candidate directory page (end of `find_directory_url`, before `trigger_search`) and returns
a `PageProfile`. Existing decision points consult the profile instead of re-deriving page shape
ad hoc.

```
PageProfile:
  archetype:         CARD_GRID | TABLE_ROSTER | LOCATOR_FORM | SPA_XHR | HUB | ALPHA_INDEX | UNKNOWN
  record_selector:   class-independent repeating-record selector (or None)
  expected_count:    from read_result_count (or None → never gate on it)
  has_directory_xhr: member-shaped JSON XHR was captured
  form_kind:         NONE | NAME_KEYWORD | LOCATION_ONLY | MIXED
  pager_kind:        query-param | path-segment | numbered | next | load-more | infinite | hash | post-xhr | cursor | none
```

Reuses: `read_result_count`, `_is_directory_json`/`_find_member_array`, `find_form_search` /
`_score_search_context`, `detect_category_links` (HUB), and the repetition detector below.

**Lifecycle rules (v1 under-specified these; they're load-bearing):**

- **Selector, not snapshot.** The profile caches `record_selector`; every *count* is a live
  query (JS-side `querySelectorAll` + the existing rendered/≥15-char guards). No decision ever
  gates on a count captured earlier — pages mutate through search and pagination, so a static
  `record_count` field would be stale by the first gate that read it.
- **Re-profile points.** Derive at landing; re-derive when the cached selector matches <3
  elements (SPA re-render changed the DOM), and once after the first search submit.
- **Frame-aware.** When `browser.py` selects a results iframe (`browser.py:667+`), the profile
  is computed against that frame, not the top page — otherwise every embedded-widget chamber
  profiles as UNKNOWN.
- **UNKNOWN = parity.** UNKNOWN routes to today's exact flow, and every archetype strategy
  falls back to the legacy path when it yields 0 records. Worst case is current behavior,
  never worse. This is the invariant that makes the detector safe to ship incrementally.
- **Classifier hints as priors.** Phase 0 already emits `needs_navigation`/`is_aggregator` —
  seed them into the profile instead of re-deriving.
- **Playground invariant.** The detector runs for all modes including `intent=None`; only
  intent-driven strategies (intent-term search, scope) stay gated. Phase 3 deliberately relaxes
  one mechanism — flagged there.

### Phase 1 — Structural repetition detection (highest leverage; fixes R1 + R2)

New `Bot/repetition.py`: `find_repeated_records(html) -> (selector, count, sample_nodes)`.

- Strip `JUNK_TAGS` + `JUNK_CONTAINER_SELECTORS` first (reuse `config.py`).
- Signature per child: tag + depth-capped descendant-tag multiset + text-length bucket — no
  class names anywhere. Find the largest run of ≥4 near-identical adjacent siblings (~20%
  signature variance allowed: premium vs basic member cards differ slightly).
- **Score runs by record-density, not just length**: phone/email/address regex hits,
  detail-ish links, median text length — and require at least one contact signal or detail
  link in the median node. This is what stops the detector electing a nav menu or footer
  link column, which is often the most structurally repetitive thing on the page. (v1's
  "floor" alone would lose to nav bars.)
- Emit a stable selector (container id > stable class > positional path; child as `> tag`),
  validated by round-trip `select()` count — same pattern Strategy 2 already uses
  (`html_parser.py:764-771`).
- **Cross-check against distinct detail-link count** (`detect_detail_links`) — the signal the
  existing partial fix proved out. Log both; a >2× divergence goes into the debug trace as a
  warning.

Wire-in:

- `count_visible_results` (`navigator.py:896`): try the profile selector first (counted
  JS-side with the same visibility/text guards) → re-derive if missing or matching <3 →
  legacy class-substring MAX as last resort.
- `extract_sample_html` (`html_parser.py:633`): new Strategy 2.5 between classless-sibling
  grouping and the densest-chunk fallback, emitting the existing candidate/score struct — so
  hashed-CSS grids and flat lists get a real `card_selector` instead of the blind 5000-char
  chunk.
- Replace the `STOP_THRESHOLD` trips (`navigator.py:1423/1525`) with the distinct count, and
  **subsume the bespoke detail-link logic in the blank-total branch**
  (`navigator.py:1618-1643`) so there is exactly one counting authority.

Files: new `Bot/repetition.py`; `Bot/navigator.py`, `Bot/html_parser.py`, `Bot/archetype.py`.
Effort: M.
**Exit criteria:** hashed-CSS fixture yields a selector + count within ±10% of truth;
nav-menu-heavy fixture yields no false run; the known truncation site paginates past 600;
and the **Finalsite wrapper fixture** counts cards, not wrappers — per-card wrapper divs
(`fsConstituentColumnLayout` around each `fsConstituentItem`) are what broke the reverted
containment-dedup attempt (outermost-only collapsed to ~1, leaf-only dropped to ~15 of 50),
so this exact markup is the regression test the new counter must pass.

### Phase 2 — Reconciliation, completeness, cache, sample diversity (R3, R4, R5, R6)

- **Count gate** in `_finish_scrape` (`main.py`): when `expected_count` is number-typed and
  final cleaned count < 0.8 × expected → write `metadata.partial = true` with
  `{expected, extracted}` and re-drive pagination/XHR replay **once**. Fall open on
  "all"/unknown — never gate sites that show no count. **Sanity-clamp lies:**
  `read_result_count` takes the largest anchored match over full page text, so marketing
  copy ("one of 5,000 members nationwide") can inflate `expected_count`; when the claimed
  total is wildly above what pagination evidence supports (pages walked × per-page distinct
  count), degrade to unknown instead of flagging partial and re-driving for nothing. Propagate `partial` into
  `exporter.py`'s consolidated metadata and the `complete` SSE payload (additive field next to
  `field_coverage` — no event renames; the SSE vocabulary is a frontend contract).
- **Completeness gate (closes R4):** after parse, if ≥70% of members are name-only AND detail
  links exist, auto-trigger the existing detail crawler in Agent mode (Playground keeps its
  y/n prompt). Count reconciliation cannot catch link-index rosters; this does.
- **Cache layouts (R5):** cache entries gain `{fingerprint, learned_at}`; fingerprint =
  hash(card_selector + sorted field keys). Multiple layouts per domain stored side by side,
  lookup by fingerprint match. **Legacy entries read as a fingerprint-less primary** — no mass
  invalidation, no re-paying the LLM for 40 cached domains.
- **Sample diversity (R6, unresolved in v1):** pick ≤5 sample cards by field-signature
  coverage (first + field-richest + up to 3 with novel signatures) instead of first-4. After
  learning, apply the selectors to ALL detected cards; any regex-visible field (email/phone)
  present in ≥20% of cards but captured in fewer than half of those triggers **one** re-ask on
  a card exhibiting the miss. Cache the union schema. Bounded cost: ≤1 extra LLM call per new
  domain.

Files: `Bot/main.py`, `Bot/navigator.py`, `Bot/cache.py`, `Bot/html_parser.py`,
`Bot/cleaner.py`, `exporter.py`. Effort: M.
**Exit criteria:** short-count fixture sets `partial` and recovers on re-drive; name-only
roster auto-crawls details; a two-layout domain keeps both schemas; sparse-field fixture
learns the union schema.

### Phase 3 — XHR replay universality + pagination shapes (Archetype C; R7)

- **Un-gate pagination mutation** in `replay_directory_xhrs` (`browser.py:388`) for
  `intent=None`; term/letter mutation stays intent-gated. You can page a captured endpoint
  without knowing a search term. (This is the deliberate relaxation of the Playground
  invariant: the *pagination mechanism* becomes universal; intent-term search does not.
  Update the AGENTS.md:60 "byte-for-byte unchanged" wording accordingly.)
- **Caps become expected-aware (R7):** the hardcoded 300-record stop and
  `XHR_MAX_PAGINATION_PAGES` move to config; when `expected_count` is known, stretch to
  expected × 1.2.
- **POST replay:** capture request method/body/content-type at sniff time (today only
  url+data survive capture), then `req.post()` with the page/offset field mutated, handling
  both form-encoded and JSON bodies. Replay already rides `page.context.request`, so cookies
  and CSRF stay live in-session — keep it that way. **Credential exclusion
  (non-negotiable):** the interactive login flow runs while capture is live, so auth-shaped
  requests (login/signin/token/password endpoints, credential-like body fields) must be
  excluded from capture and must never reach the `Data-dump/` raw dumps — with a test
  proving a login POST is not persisted.
- **Cursor/token pagination:** when a captured response carries a continuation key (`next`,
  `cursor`, `nextPageToken`, `paging.next`), follow the chain instead of mutating params;
  same caps. Modern SPA directories increasingly use this; param mutation alone can't page
  them.
- **Path-segment fast path:** extend `_pick_pagination_param`/`_paginate_by_url`
  (`browser.py:834-893, 1093`) to same-path-prefix links differing in one trailing numeric
  segment (`/page/2/`, `/p2`, `-page-2.html`) — and **widen `_navigated_away`'s 1-segment
  allowance when `pager_kind` is path-segment**: today `/dir/page/2` is judged
  navigated-away (`browser.py:996`), which silently breaks even click pagination on those
  sites. (v1 called path-segment "unsupported"; the truth is worse — the fallback that should
  catch it is actively aborted.)
- **Virtualized lists:** when the DOM count plateaus but directory XHRs keep arriving
  (react-window et al. recycle DOM nodes), trust the XHR stream (`has_directory_xhr`) instead
  of stopping on "no growth".

Files: `Bot/browser.py`, `Bot/config.py`. Effort: M–L.
**Exit criteria:** POST-paginated fixture replays all pages on the Playground path; a
2,000-record aggregator exceeds the old 300 cap; a `/page/N/` fixture walks the template
without tripping the navigation guard.

### Phase 4 — Rosters, tables, dl, flat sections, PDF (Archetype B)

- `_extract_company_name` (`html_parser.py:260`): plain first-cell/td text fallback, guarded
  to table context; recognize "Last, First" ordering when `entity_type` is person (the
  business-name heuristics would mangle person rosters).
- Positional column inference for headerless tables (extend
  `learn_selectors_from_table_headers`, `html_parser.py:1049`).
- `<dl>`/`<dt>`/`<dd>` support + a "flat section" mode treating `<hN>` + following siblings
  up to the next `<hN>` as a synthetic card.
- **Truly flat rows** (no inner markup — the case Strategy 2's `≥2 inner elements` filter
  drops): admit single-text-node rows when the text carries a contact signal; extractor
  splits name = text before the first phone/email match.
- **PDF rosters:** stop dropping `.pdf` links (`navigator.py:44`) when the link text is
  roster-ish; new `Bot/pdf_extractor.py` (pdfplumber) → tables/text → the existing
  phone/email/address regexes → `clean_members`. **Text-layer PDFs only — scanned/image PDFs
  are logged and skipped (no OCR), with a size cap.** pdfplumber goes into the AGENTS.md
  dependency list (there is no requirements.txt).
- **Person/dynamic minimal fallback:** non-business entity types get a name+email+phone
  regex fallback instead of returning empty (`html_parser.py:1802-1818`) — but gated behind
  entity-type + validation checks: the deliberate empty-return exists to prevent
  email-as-name garbage, and that must not regress.

Files: `Bot/html_parser.py`, `Bot/navigator.py`, new `Bot/pdf_extractor.py`. Effort: L.
Independent of Phase 3 (different files) — the two can run in parallel.
**Exit criteria:** headerless-table fixture returns named records; `<dl>` fixture parses;
linked-PDF roster produces cleaned members; person roster keeps "Last, First" names intact.

### Phase 5 — Location-gated locator enumeration (Archetype D)

- `LOCATOR_FORM` in the detector: location-only forms become a classification instead of a
  −20 rejection (`navigator.py:806-808` inverted under this archetype only). MIXED forms
  (name + location fields) still prefer the name-field path.
- **Radius first.** Before any grid: if a captured locator XHR exposes a radius/distance
  param, replay once with it maxed — one request often returns the entire dataset. Cheapest
  win by far; the grid is the fallback, not the default.
- New `Bot/location_enum.py` + `Bot/zip_seeds.py` — **a `.py` data module, not `.json`: the
  repo-wide `*.json` gitignore would silently drop a JSON seed file.** Coarse seeds (~1–3
  ZIPs/state), submit each, walk each result set's pagination, dedup across submissions —
  **but not on cleaner's name+phone key**: chain branches share a central 800-number, so a
  name+phone key collapses every location of a chain into one record. Locator records dedup
  on name+address (or name+phone+zip). **Adaptive subdivision:** only subdivide a region when its
  response hits an obvious per-query cap (exactly 25/50/100 results) — a fixed dense grid
  either misses coverage or wastes hundreds of submissions.
- JSON locators go through the (now un-gated) XHR replay, mutating zip/lat/lng (extend
  `XHR_*_PARAMS`); reuse `url_enumeration.py`'s partition-probe pattern.
- **Discipline:** enumerate only when `LOCATOR_FORM` AND wildcard/blank yields 0; hard cap
  (~120 submissions/site) and `DETAIL_CRAWL_DELAY_MIN/MAX` pacing between submissions.

Files: new `Bot/location_enum.py` + `Bot/zip_seeds.py`; `Bot/navigator.py`,
`Bot/browser.py`, `Bot/archetype.py`. Effort: L.
**Exit criteria:** a ZIP-only locator returns >0 deduped records; the radius shortcut is
taken when available; submission count stays under the cap.

### Sequencing

Phases 1+2 are the count spine — land them first and together; every later phase reads
`PageProfile` and the reconciliation gates. Phase 3 ∥ Phase 4 (disjoint files). Phase 5
depends on Phase 3's un-gated replay. One structural change per PR. Each phase ships behind
a `config.py` flag (default ON for CLI) so a misbehaving heuristic can be switched off
without a revert.

Doc updates as phases land: AGENTS.md:60 (Playground wording, Phase 3), AGENTS.md:73
(currently claims `/page/N/` template support that doesn't exist yet — fix with Phase 3),
dependency list (pdfplumber, Phase 4).

---

## Verification

Two tiers. (v1's plan — run the CLI against the live-domain corpus — is neither repeatable
nor fast enough to run per-change: minutes per domain, network- and LLM-dependent, sites
drift.)

1. **Offline fixture tests (pytest, per AGENTS.md testing guidelines) — run on every
   change.** Harvest raw listing HTML from the existing `Data-dump/{domain}.json` raw
   captures (~40 domains already on disk) into `tests/fixtures/*.html` — **`.html`, not
   `.json`, or the gitignore eats them** — plus recorded directory-XHR JSON bodies for the
   replay logic. Deterministic, no network, no LLM: repetition detector (selector + count vs
   known truth; nav-menu negative case), archetype classification, table/dl/flat/PDF
   extractors, pager-param and POST-body mutation (assert the mutated URL/body — no server
   needed).
2. **Live smoke (manual, per release).** ~8 domains, one per archetype variant: hoa-usa + a
   GrowthZone chamber (A); a Finalsite roster + a headerless-table site + a linked-PDF
   roster (B); a POST/SPA aggregator (C); a ZIP locator (D). CLI:
   `SCRAPER_HEADLESS=1 printf 'n\nn\n' | python3 Bot/main.py <url>` (system python3.13, no
   .venv). Assert: no count regression on archetype A, the targeted per-phase improvement,
   and `metadata.partial` correctness.

**Observability:** every detector/strategy decision goes through the existing
`debug.decision` tracing (`Debug-dump/{domain}_debug.json`) plus an SSE `log` line —
archetype, selector, live count, expected count. No new SSE event types; the vocabulary is a
frontend contract.

## Progress

### Phase 1 — landed 2026-07-17

**What shipped** (flag: `config.py:REPETITION_COUNTING`, default ON, kill via
`TRAWL_REPETITION_COUNTING=0`):

- `Bot/repetition.py` — `find_repeated_records(html)` per spec: junk strip →
  per-child signature (tag + depth-3 descendant-tag multiset + text-length
  bucket, no class names) → largest runs of ≥4 near-identical adjacent
  siblings (separators skipped) → record-density scoring → 1:1-wrapper
  descent → selector emission (stable class > container-anchored path >
  unstable/hashed class > positional nth-of-type), round-trip validated on
  the stripped AND intact trees.
- `Bot/archetype.py` — PageProfile selector lifecycle (derive lazily,
  re-derive on <3 live matches, negative-cache guarded by URL/DOM-size
  change, `last_good_selector` revalidation after empty pages; frame-aware
  by keying on the passed context) + `rendered_record_count()`, the single
  counting authority (structural count cross-checked vs distinct
  detail-link count; >2× divergence logs a warning and takes the smaller).
- Wire-ins: `count_visible_results` tries the profile selector first
  (JS-side, same rendered/≥15-char guards), legacy MAX + link fallback kept
  verbatim; STOP_THRESHOLD trips at the pre-search and intent gates consult
  the authority (an exact count below threshold overrides the stop; no
  exact evidence = legacy behavior); the blank-total branch's bespoke
  detail-link logic is subsumed by the authority; `extract_sample_html`
  gained Strategy 2.5 (structural candidates, same score competition).
- `tests/` — pytest corpus (per Verification tier 1): 10 fixtures harvested
  from Data-dump raw captures (`tests/harvest_fixtures.py`, truths in
  `tests/fixture_truth.py` — a .py module, *.json is gitignored), 32 tests,
  no network/LLM/browser. Includes two synthetic findadentist variants
  (hashed-CSS, fully classless).

**Exit criteria:** hashed-CSS fixture → `div.css-… > div`, 100/100 exact ✓.
Nav-heavy: enigma's 693 dropdown options / 401 industry links never elected ✓
(the page's real 20-cafe table is found instead — see deviations).
Finalsite wrapper fixture → 50/50 exact, samples are `fsConstituentItem` ✓;
GrowthZone fixture counts 212 where legacy `[class*='card']` reads 1608 ✓.
Truncation-past-600: mechanism verified offline (the 1608→212 deflation is
the number the 600-gates read) and live on members.buildingncw.org — blank
rendered 50, authority said partial vs site total 213, wildcards re-drove,
full 213 extracted. A ≥1,000-member live confirmation is still owed on the
next big-directory run. **Live smoke:** members.buildingncw.org returned
213 vs the stored 212 — site drift, not regression: the site's own counter
and its 213 unique `/Details/{ID}` links both say 213 today.

**Deviations from spec (and why):**

1. The density gate grew three sub-rules beyond "contact regex or detail
   link": anchor-dominance suppression (a run whose text lives ≥90% inside
   links is a link list), a structured-anchor exemption (whole-card-anchor
   rosters like Berkeley's wrap image+h2+fields in one `<a>` and must
   pass), and a majority-template requirement (a run's detail links must
   share one URL template — kills footer link columns and hyphenated-slug
   nav lists that pass a naive detail-link test).
2. The enigma "nav-heavy negative" turned out to contain a real 20-cafe
   listing (classless table the junk-strip pass was destroying). The
   criterion is enforced as "never elect nav runs" (`test_navheavy_never_
   elects_nav`), not "return None"; a second detection pass over the
   intact tree rescues listings that stripping removes, and positional
   nth-of-type paths are only emitted from the tree they were computed on
   (stripping shifts sibling indexes).
3. Strategy 2.5 also fires when strategies 0–2 produced only weak
   candidates (best score < 20), not just zero — a hidden 4-row
   keyboard-shortcuts table otherwise blocks the rescue on classless pages.
4. Wrapper descent returns the hop chain: descended nodes no longer share
   a parent, so container-anchored selectors route
   `container > wrapper_tag > card_tag`.
5. PageProfile ships as the lifecycle skeleton only: `archetype` stays
   UNKNOWN, `form_kind`/`pager_kind`/`expected_count`/Phase-0 priors are
   declared but unpopulated — classification belongs to later phases.

**Notes for Phase 2:**

- Populate `PageProfile.expected_count` from `read_result_count` at the
  derive points; `rendered_record_count()` is the ready-made input for the
  `_finish_scrape` count gate (it already returns `(count, exact)`).
- Profile derivation currently happens lazily at first count (in practice:
  the pre-search gate). If the count gate wants a landing-time profile,
  call `archetype.count_records(page)` explicitly at the end of
  `find_directory_url`.
- The re-profile point "once after the first search submit" is implicit:
  the old selector matches <3 on the swapped DOM and re-derives. Verified
  live (derive fired right after the blank submit on GrowthZone).
- Strategy 2.5 candidates carry class `"(structural)"` and flow into the
  existing selector cache — the Phase 2 cache fingerprint work should treat
  them like any learned selector.
- `debug.decision("PROFILE", ...)` traces every derive; grep Debug-dump
  for `PROFILE` when auditing counts.

## Out of scope (explicit)

- **Login walls / CAPTCHA / anti-bot** — the cookie-persistence + Live View layer already
  handles access; it is orthogonal to page-shape universality and this plan doesn't touch it.
- **OCR for scanned PDFs**; non-US / non-English directories.
- **LLM-driven navigation planning** (the superseded `ai_discover_listing_links` design
  stays dead).
- Code hygiene, noted not scoped: comments/docstrings say "Haiku" while `llm.py` routes
  DeepSeek (`cache.py:3` and elsewhere) — reconcile opportunistically.
