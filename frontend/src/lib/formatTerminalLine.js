/**
 * Stealth setup banner — injected at the start of every scrape.
 * These are real measures the bot applies (silently in the backend).
 * We surface them here so the user knows what's happening.
 */
export const STEALTH_BANNER = [
  { text: '→ Launching headless browser...', category: 'BROWSER' },
  { text: '→ Stealth: navigator.webdriver patched', category: 'BROWSER' },
  { text: '→ Stealth: WebGL → Intel Iris OpenGL Engine', category: 'BROWSER' },
  { text: '→ Stealth: Sec-CH-UA headers injected', category: 'BROWSER' },
  { text: '→ TLS fingerprint: chrome136 (JA3 rotated)', category: 'BROWSER' },
  { text: '→ Anti-bot ready ✓', category: 'SYSTEM' },
  { text: '', category: 'SYSTEM' },
]

// Messages to skip entirely (noise from the bot internals)
const SKIP_PATTERNS = [
  /^AI says: STAY/i,
  /^AI says: NONE/i,
  /^RESPONSE: \[/,           // raw capture lines like "RESPONSE: [application/json] url"
  /^Now on:/,                // internal navigation tracking
  /^Current URL:/,
  /^Depth /,
  /^Idle timer/,
  /^Timer /,
  /^Waiting for/,
  /^Page text sample/,
  /^\s*$/,                   // empty/whitespace
]

// Transform raw bot messages into clean readable output
const TRANSFORMS = [
  // AI navigation
  { match: /^AI says: CLICK (\d+)/i, format: (m) => ({ text: `→ AI navigating to link ${m[1]}`, category: 'NAV' }) },
  { match: /^AI wants to click: (.+)/i, format: (m) => ({ text: `→ AI clicking: ${m[1]}`, category: 'NAV' }) },

  // Directory detection
  { match: /^Likely directory data at: (.+)/i, format: (m) => ({ text: `→ Found directory data at ${m[1]}`, category: 'CAPTURE' }) },
  { match: /^JSON member list from .+?: (\d+) entries/i, format: (m) => ({ text: `→ Captured ${m[1]} member records (JSON)`, category: 'CAPTURE' }) },
  { match: /^JSON nested member list '(.+?)' from .+?: (\d+) entries/i, format: (m) => ({ text: `→ Captured ${m[2]} records from "${m[1]}" (JSON)`, category: 'CAPTURE' }) },

  // Parsing
  { match: /^Parsing HTML response from/i, format: () => ({ text: '→ Parsing HTML for member data...', category: 'PARSE' }) },
  { match: /^\s*Extracted (\d+) members/i, format: (m) => ({ text: `→ Extracted ${m[1]} members`, category: 'PARSE' }) },
  { match: /^Learning .+ selectors via Haiku/i, format: () => ({ text: '→ AI learning page selectors...', category: 'PARSE' }) },
  { match: /^Selectors learned/i, format: () => ({ text: '→ Selectors learned ✓', category: 'PARSE' }) },
  { match: /^Sample (\d+)\/(\d+)/i, format: (m) => ({ text: `→ Analyzing sample ${m[1]}/${m[2]}...`, category: 'PARSE' }) },

  // Pagination / scrolling
  { match: /^Pagination.*page (\d+)/i, format: (m) => ({ text: `→ Page ${m[1]}...`, category: 'PAGE' }) },
  { match: /^Scroll.*?(\d+) results/i, format: (m) => ({ text: `→ Scrolling... ${m[1]} results found`, category: 'SCROLL' }) },
  { match: /^Load more/i, format: () => ({ text: '→ Loading more results...', category: 'SCROLL' }) },

  // Search
  { match: /^Trying '(.+?)'/i, format: (m) => ({ text: `→ Searching: "${m[1]}"`, category: 'SEARCH' }) },
  { match: /^Found (\d+) search input/i, format: (m) => ({ text: `→ Found ${m[1]} search inputs`, category: 'SEARCH' }) },

  // Detail crawl
  { match: /^Probing for API endpoint/i, format: () => ({ text: '→ Probing for API endpoint...', category: 'DETAIL' }) },
  { match: /^API fast path complete: (\d+) members/i, format: (m) => ({ text: `→ API fast path: ${m[1]} members fetched ✓`, category: 'DETAIL' }) },
  { match: /^Phase 1: Crawling (\d+) sample/i, format: (m) => ({ text: `→ Crawling ${m[1]} sample detail pages...`, category: 'DETAIL' }) },

  // Save / complete
  { match: /^Saved (\d+) structured members to (.+)/i, format: (m) => {
    const filename = m[2].split('/').pop()
    return { text: `✓ Saved ${m[1]} records → ${filename}`, category: 'CLEAN' }
  }},
  { match: /^Saving (\d+)/i, format: (m) => ({ text: `→ Saving ${m[1]} records...`, category: 'CLEAN' }) },

  // Errors
  { match: /^\[403\] (.+)/i, format: (m) => ({ text: `⚠ Blocked (403): ${m[1]} — retrying`, category: 'ERROR' }) },
  { match: /^\[429\] (.+)/i, format: (m) => ({ text: `⚠ Rate limited (429): ${m[1]}`, category: 'ERROR' }) },
  { match: /^Timeout \((\d+)s\): (.+)/i, format: (m) => ({ text: `⚠ Timeout (${m[1]}s): ${m[2]}`, category: 'ERROR' }) },
  { match: /^DNS error: (.+)/i, format: (m) => ({ text: `⚠ DNS error: ${m[1]}`, category: 'ERROR' }) },
  { match: /^Connection error: (.+)/i, format: (m) => ({ text: `⚠ Connection error: ${m[1]}`, category: 'ERROR' }) },

  // Phase 2 enrichment
  { match: /^Loaded (\d+) members from/i, format: (m) => ({ text: `→ Loaded ${m[1]} members for enrichment`, category: 'LOG' }) },
  { match: /^Searching DuckDuckGo for (\d+)/i, format: (m) => ({ text: `→ Searching DuckDuckGo for ${m[1]} missing websites...`, category: 'SEARCH' }) },
  { match: /^DuckDuckGo: found (\d+)\/(\d+)/i, format: (m) => ({ text: `→ Found ${m[1]}/${m[2]} websites via DuckDuckGo`, category: 'SEARCH' }) },
  { match: /^Enriching (\d+) entries with (\d+)/i, format: (m) => ({ text: `→ Enriching ${m[1]} entries (${m[2]} workers)...`, category: 'LOG' }) },
  { match: /^Done! (\d+) records/i, format: (m) => ({ text: `✓ Done — ${m[1]} records processed`, category: 'SYSTEM' }) },
]

/**
 * Format a raw bot terminal message into a clean readable line.
 * Returns { text, category } or null to skip the message.
 */
export default function formatTerminalLine(message) {
  if (!message || typeof message !== 'string') return null
  const trimmed = message.trim()
  if (trimmed.length < 3) return null

  // Check skip patterns
  for (const pattern of SKIP_PATTERNS) {
    if (pattern.test(trimmed)) return null
  }

  // Check transforms
  for (const { match, format } of TRANSFORMS) {
    const m = trimmed.match(match)
    if (m) return format(m)
  }

  // Pass through unmatched messages as-is
  return { text: trimmed }
}
