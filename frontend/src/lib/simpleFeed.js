// Plain-language layer for the Playground terminal's Simple view.
//
// Works on the already-formatted lines useSSE stores ({ text, category }) —
// the exact stream the Advanced console prints — and reduces them into three
// things a non-technical customer can read at a glance:
//
//   1. a phase tracker  (setup → open → find → collect → save …)
//   2. live counters    (records found, pages walked, enrichment progress)
//   3. a curated feed   (jargon-free sentences; unmatched bot chatter hidden)
//
// Patterns here match OUR OWN formatted output (formatTerminalLine +
// mockData), which is a stable contract — not the bot's raw prints. The
// Advanced view renders the untranslated stream, so nothing is ever lost.

const num = (s) => parseInt(String(s).replace(/,/g, ''), 10) || 0
const fmt = (s) => num(s).toLocaleString()

const domainOf = (url) => {
  const s = String(url).trim()
  try {
    return new URL(s.includes('://') ? s : `https://${s}`).hostname.replace(/^www\./, '')
  } catch {
    return s.replace(/^https?:\/\//, '').split('/')[0]
  }
}

export const PHASES = [
  { id: 'setup', label: 'Secure browser' },
  { id: 'open', label: 'Opening the site' },
  { id: 'find', label: 'Finding the listings' },
  { id: 'collect', label: 'Collecting records' },
  { id: 'details', label: 'Profile details', optional: true },
  { id: 'save', label: 'Cleaning & saving' },
  { id: 'enrich', label: 'Filling gaps', optional: true },
]
const PHASE_INDEX = Object.fromEntries(PHASES.map((p, i) => [p.id, i]))

// Feed item kinds: step | data | ok | warn | error | done | input | divider

// Each rule: [regex, effect(match) | null-to-hide]. First match wins.
// Effects may carry: item, records (max), pages (max), completeAdd (sum),
// enriched (sum), enrichStart, enrichTotal, enrichTick, coverage, nextSite.
const RULES = [
  // ── Noise for customers (the Advanced console still shows all of it) ──
  [/^\$ /, null],
  [/^→ Stealth:/i, null],
  [/^→ TLS fingerprint/i, null],
  [/^\.{3}$|^…$/, null],
  [/^Intent parse failed/i, null],
  [/^DuckDuckGo-discovered/i, null],

  // ── Setup ──
  [/^→ Launching .*browser/i, () => ({ item: { text: 'Starting a secure browser session', kind: 'step' } })],
  [/^→ Anti-bot ready/i, () => ({ item: { text: 'Anti-blocking protection active', kind: 'ok' } })],

  // ── Multi-site separator (useSSE injects "━━━ url ━━━") ──
  [/^━+ (.+?) ━+$/, (m) => ({ nextSite: true, item: { text: `Next site — ${domainOf(m[1])}`, kind: 'divider' } })],

  // ── Interactive round-trip (the Simple view shows its own prompt card) ──
  [/\(y\/n\)\s*$/i, null],
  [/respond 'y'/i, null],
  [/^> ?(?:y|yes)$/i, () => ({ item: { text: 'You said yes — continuing', kind: 'input' } })],
  [/^> ?(?:n|no)$/i, () => ({ item: { text: 'You said no — moving on', kind: 'input' } })],
  [/^> /, null],

  // ── Navigation & discovery ──
  [/^→ Navigating to (.+)/i, (m) => ({ item: { text: `Opening ${domainOf(m[1])}`, kind: 'step' } })],
  [/^→ AI analyzing page structure/i, () => ({ item: { text: 'Reading the page layout', kind: 'step' } })],
  [/^→ Found member directory/i, () => ({ item: { text: 'Found the listings — studying how they’re laid out', kind: 'ok' } })],
  [/^→ AI learning page selectors/i, () => ({ item: { text: 'Learning how the listings are structured', kind: 'step' } })],
  [/^→ Selectors learned:? ?(.*?) ?✓?$/i, (m) => ({
    item: { text: m[1] ? `Listing format identified — capturing ${m[1]}` : 'Listing format identified', kind: 'ok' },
  })],
  [/^→ Analyzing sample (\d+)\/(\d+)/i, (m) => ({ item: { text: `Studying example listings (${m[1]} of ${m[2]})`, kind: 'step' } })],
  [/^→ AI (?:navigating|clicking)/i, () => ({ item: { text: 'Navigating deeper into the site', kind: 'step' } })],
  [/^→ Found directory data at/i, () => ({ item: { text: 'Located the site’s data feed', kind: 'ok' } })],
  [/^→ Searching: [“"](.+?)[”"]/i, (m) => ({ item: { text: `Searching the directory for “${m[1]}”`, kind: 'step' } })],
  [/^→ Found \d+ search inputs?/i, () => ({ item: { text: 'Found the directory’s search box', kind: 'step' } })],

  // ── Collection ──
  [/^→ Captured ([\d,]+) (?:member )?records/i, (m) => ({ records: num(m[1]), item: { text: `Found ${fmt(m[1])} records`, kind: 'data' } })],
  [/^→ Extracting page (\d+)\.{3} ?([\d,]+) records/i, (m) => ({ pages: +m[1], records: num(m[2]), item: { text: `Page ${m[1]} — ${fmt(m[2])} records so far`, kind: 'data' } })],
  [/^→ Extracted ([\d,]+) members/i, (m) => ({ records: num(m[1]), item: { text: `Collected ${fmt(m[1])} records from this page`, kind: 'data' } })],
  [/^→ Page (\d+)/i, (m) => ({ pages: +m[1], item: { text: `Moving to page ${m[1]}`, kind: 'step' } })],
  [/^→ Pagination detected/i, () => ({ item: { text: 'More pages found — going through them', kind: 'step' } })],
  [/pagination complete: (\d+) pages/i, (m) => ({ pages: +m[1], item: { text: `Went through ${m[1]} pages`, kind: 'ok' } })],
  [/^→ No more pages\.? ?Total:? ?([\d,]+)/i, (m) => ({ records: num(m[1]), item: { text: `Every page collected — ${fmt(m[1])} records`, kind: 'ok' } })],
  [/^→ Scrolling\.{3} ?([\d,]+) results/i, (m) => ({ records: num(m[1]), item: { text: `Scrolling — ${fmt(m[1])} results loaded`, kind: 'data' } })],
  [/^→ Loading more results/i, () => ({ item: { text: 'Loading more results', kind: 'step' } })],
  [/^→ Parsing HTML/i, () => ({ item: { text: 'Reading listings from the page', kind: 'step' } })],
  [/already have ([\d,]+) members/i, (m) => ({ records: num(m[1]) })],
  [/^URL enumeration captured (\d+) pages/i, (m) => ({ item: { text: `Collected ${m[1]} listing pages directly`, kind: 'ok' } })],
  [/^XHR replay: .*?([\d,]+) new member records/i, (m) => ({ item: { text: `Found ${fmt(m[1])} more records in the data feed`, kind: 'data' } })],

  // ── Profile details ──
  [/^→ Probing for API endpoint/i, () => ({ item: { text: 'Checking for a faster data source', kind: 'step' } })],
  [/^→ API fast path: ([\d,]+)/i, (m) => ({ records: num(m[1]), item: { text: `Direct data source worked — ${fmt(m[1])} full records`, kind: 'ok' } })],
  [/^→ Crawling (\d+) sample detail/i, (m) => ({ item: { text: `Checking ${m[1]} example profile pages`, kind: 'step' } })],
  [/^Found ([\d,]+) member profile links/i, (m) => ({ item: { text: `Found ${fmt(m[1])} individual profile pages`, kind: 'step' } })],
  [/^Included ([\d,]+) members from detail/i, (m) => ({ item: { text: `Merged details from ${fmt(m[1])} profile pages`, kind: 'ok' } })],

  // ── Cleaning & saving ──
  [/^→ Saving ([\d,]+) records/i, (m) => ({ item: { text: `Saving ${fmt(m[1])} records`, kind: 'step' } })],
  [/^✓ Saved ([\d,]+) records/i, (m) => ({ records: num(m[1]), item: { text: `Saved ${fmt(m[1])} records`, kind: 'ok' } })],
  [/^Saved ([\d,]+) structured members/i, (m) => ({ records: num(m[1]), item: { text: `Saved ${fmt(m[1])} records`, kind: 'ok' } })],
  [/garbage/i, () => ({ item: { text: 'Some results looked wrong — cleaning them out', kind: 'warn' } })],
  [/^Done! Extracted ([\d,]+) members/i, (m) => ({ records: num(m[1]), item: { text: `Collection finished — ${fmt(m[1])} records`, kind: 'ok' } })],

  // ── Phase 2: gap-filling from company websites ──
  [/^─+ ?Phase 2|^Starting Phase 2/i, () => ({ enrichStart: true, item: { text: 'Filling gaps from company websites', kind: 'divider' } })],
  [/^→ ([\d,]+) entries have websites, ([\d,]+) need/i, (m) => ({ enrichStart: true, item: { text: `${fmt(m[1])} records already list a website · ${fmt(m[2])} need finding`, kind: 'step' } })],
  [/^→ Loaded ([\d,]+) members for enrichment/i, (m) => ({ enrichStart: true, item: { text: `Preparing ${fmt(m[1])} records for gap-filling`, kind: 'step' } })],
  [/^→ Searching DuckDuckGo for ([\d,]+)/i, (m) => ({ enrichStart: true, item: { text: `Searching the web for ${fmt(m[1])} missing websites`, kind: 'step' } })],
  [/^→ Found ([\d,]+)\/([\d,]+) websites/i, (m) => ({ enrichStart: true, item: { text: `Found ${fmt(m[1])} of ${fmt(m[2])} missing websites`, kind: 'ok' } })],
  [/^→ Enriching ([\d,]+) entries/i, (m) => ({ enrichTotal: num(m[1]), item: { text: `Visiting ${fmt(m[1])} company websites for extra details`, kind: 'step' } })],
  [/^\[([\d,]+)\/([\d,]+)\] (.+?) (?:—|→) /, (m) => ({ enrichTick: { done: num(m[1]), total: num(m[2]), last: m[3] } })],

  // ── Completion & summaries ──
  [/^✓ Complete — ([\d,]+) records scraped(?: \(([\d,]+) enriched\))?/i, (m) => ({
    completeAdd: num(m[1]),
    enriched: m[2] ? num(m[2]) : 0,
    item: {
      text: m[2]
        ? `All done — ${fmt(m[1])} records ready (${fmt(m[2])} enriched from the web)`
        : `All done — ${fmt(m[1])} records ready`,
      kind: 'done',
    },
  })],
  [/^✓ Done! ([\d,]+) records/i, (m) => ({ completeAdd: num(m[1]), item: { text: `All done — ${fmt(m[1])} records ready`, kind: 'done' } })],
  [/^✓ Done [—–-] ([\d,]+)\/([\d,]+) records enriched/i, (m) => ({ item: { text: `Gap-filling done — ${fmt(m[1])} of ${fmt(m[2])} records improved`, kind: 'done' } })],
  [/^✓ Done [—–-] ([\d,]+) records processed/i, (m) => ({ records: num(m[1]), item: { text: `Gap-filling finished — ${fmt(m[1])} records checked`, kind: 'ok' } })],
  [/^Enriched: ([\d,]+) \| Failed: ([\d,]+) \| No website: ([\d,]+)/i, (m) => ({
    item: { text: `Improved ${fmt(m[1])} records · ${fmt(m[2])} sites unreachable · ${fmt(m[3])} without a website`, kind: 'ok' },
  })],
  [/^Field coverage: (.+)/i, (m) => ({ coverage: m[1] })],

  // ── Setbacks (kept honest, phrased calmly) ──
  [/^⚠ Blocked \(403\)/i, () => ({ item: { text: 'The site pushed back — retrying with a fresh identity', kind: 'warn' } })],
  [/^⚠ Rate limited/i, () => ({ item: { text: 'The site asked us to slow down — pacing requests', kind: 'warn' } })],
  [/^⚠ Timeout/i, () => ({ item: { text: 'A page took too long — retrying', kind: 'warn' } })],
  [/^⚠ (?:DNS|Connection) error/i, () => ({ item: { text: 'Connection hiccup — retrying', kind: 'warn' } })],
  [/^⚠ (.+)/, (m) => ({ item: { text: m[1], kind: 'warn' } })],
  [/^WARNING: 0 members extracted/i, () => ({ item: { text: 'No records found — the page may need a login or isn’t a directory', kind: 'warn' } })],
  [/^WARNING: Only ([\d,]+) members? extracted/i, (m) => ({ item: { text: `Only ${fmt(m[1])} records found — this page may not have worked`, kind: 'warn' } })],
  [/^WARNING:? (.+)/i, (m) => ({ item: { text: m[1], kind: 'warn' } })],
  [/^Login wall detected/i, () => ({ item: { text: 'This site requires a login', kind: 'warn' } })],
  [/^Error: (.+)/i, (m) => ({ item: { text: `Something went wrong — ${m[1]}`, kind: 'error' } })],
]

// Note: the enrich phase is only entered once a RULE has flipped enrichSeen
// (divider / "Loaded N members" / progress ticks) — matching the word
// "enrichment" in free text would light the phase up from the mere y/n
// question, even when the user declines.
function phaseOf(category, text, enrichSeen) {
  if (enrichSeen && ['DETAIL', 'LOG', 'SEARCH', 'SCROLL', 'PAGE'].includes(category)) return 'enrich'
  switch (category) {
    case 'BROWSER': return 'setup'
    case 'NAV': return /navigating to|opening/i.test(text) ? 'open' : 'find'
    case 'SEARCH': return 'find'
    case 'PARSE': return /extract/i.test(text) ? 'collect' : 'find'
    case 'CAPTURE':
    case 'PAGE':
    case 'SCROLL':
    case 'IFRAME': return 'collect'
    case 'DETAIL': return 'details'
    case 'CLEAN': return 'save'
    case 'SYSTEM': return /anti-bot|stealth/i.test(text) ? 'setup' : null
    default: return null
  }
}

function parseCoverage(str) {
  const out = []
  for (const part of String(str).split(',')) {
    const m = part.trim().match(/^([\w .-]+?):\s*([\d,]+)\/([\d,]+)$/)
    if (m) out.push({ field: m[1], have: num(m[2]), total: num(m[3]) })
  }
  return out.length ? out : null
}

/**
 * Reduce the formatted line stream into everything the Simple view renders.
 * Pure — safe to useMemo on `lines`.
 */
export function deriveFeed(lines, { isRunning = false, isComplete = false, hasError = false } = {}) {
  const items = []
  const seen = new Set()
  let maxPhase = -1
  let siteMax = 0 // best record count seen for the site in progress (max, never sum — undercounts beat overcounts)
  let doneTotal = 0 // records confirmed by completed sites
  let pages = 0
  let enrich = { done: 0, total: 0, last: null }
  let enrichSeen = false
  let enrichedCount = 0
  let coverage = null

  const push = (item) => {
    const last = items[items.length - 1]
    if (last && last.kind === item.kind && last.text === item.text) {
      last.count += 1
      return
    }
    items.push({ ...item, count: 1, key: items.length })
  }

  for (const line of lines) {
    const text = (line.text || '').trim()
    if (!text) continue

    for (const [re, effect] of RULES) {
      const m = text.match(re)
      if (!m) continue
      if (effect) {
        const out = effect(m) || {}
        if (out.item) push(out.item)
        if (out.records) siteMax = Math.max(siteMax, out.records)
        if (out.pages) pages = Math.max(pages, out.pages)
        if (out.completeAdd) {
          doneTotal += out.completeAdd
          siteMax = 0
        }
        if (out.enriched) enrichedCount += out.enriched
        if (out.enrichStart) enrichSeen = true
        if (out.enrichTotal) {
          enrichSeen = true
          enrich = { ...enrich, total: Math.max(enrich.total, out.enrichTotal) }
        }
        if (out.enrichTick) {
          enrichSeen = true
          enrich = {
            done: out.enrichTick.done,
            total: Math.max(enrich.total, out.enrichTick.total),
            last: out.enrichTick.last,
          }
        }
        if (out.coverage) coverage = parseCoverage(out.coverage)
        if (out.nextSite) maxPhase = -1
      }
      break
    }

    const phase = phaseOf(line.category, text, enrichSeen)
    if (phase != null) {
      seen.add(phase)
      maxPhase = Math.max(maxPhase, PHASE_INDEX[phase])
    }
  }

  const statuses = {}
  for (const p of PHASES) {
    const idx = PHASE_INDEX[p.id]
    if (isComplete && !hasError) statuses[p.id] = 'done'
    else if (idx < maxPhase) statuses[p.id] = 'done'
    else if (idx === maxPhase) statuses[p.id] = hasError && !isRunning ? 'error' : isRunning ? 'active' : 'done'
    else statuses[p.id] = 'pending'
  }

  return {
    items,
    statuses,
    visiblePhases: PHASES.filter((p) => !p.optional || seen.has(p.id)),
    records: doneTotal + siteMax,
    pages,
    enrich,
    enrichedCount,
    coverage,
    activeLabel: maxPhase >= 0 ? PHASES[maxPhase].label : null,
  }
}

/**
 * Rewrite a backend y/n prompt into a customer-facing question with
 * action-labelled buttons. Falls back to the raw message minus "(y/n)".
 */
export function friendlyPrompt(message = '') {
  const detail = message.match(/Found ([\d,]+) detail pages\. Crawl/i)
  if (detail) {
    return {
      question: `Found ${fmt(detail[1])} profile pages with extra details.`,
      hint: 'Visiting them takes longer but fills in more fields — emails, phones, addresses.',
      yes: 'Visit them',
      no: 'Skip',
    }
  }
  const missing = message.match(/Still missing: (.+?)\. Run Phase 2/i)
  if (missing) {
    return {
      question: `Some records are still missing: ${missing[1]}.`,
      hint: 'TrawlBase can visit each company’s own website to fill the gaps.',
      yes: 'Fill the gaps',
      no: 'No thanks',
    }
  }
  if (/login wall/i.test(message)) {
    return {
      question: 'This site requires a login.',
      hint: 'Log in using the browser window that just opened, then continue.',
      yes: 'I’ve logged in — continue',
      no: 'Skip this site',
    }
  }
  if (/solve the challenge|captcha|press & hold/i.test(message)) {
    return {
      question: 'The site is showing a human-verification check.',
      hint: 'Complete the check in the browser window that opened, then continue.',
      yes: 'Done — continue',
      no: 'Skip this site',
    }
  }
  return {
    question: message.replace(/\s*\(y\/n\)\s*$/i, ''),
    hint: null,
    yes: 'Yes',
    no: 'No',
  }
}
