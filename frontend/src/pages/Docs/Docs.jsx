import { motion } from 'framer-motion'
import SectionWrapper from '../../components/SectionWrapper'
import {
  Brain, Globe, ShieldCheck, Layers, Search, FileJson, Zap,
  Navigation, Terminal, Users, ArrowRight, Database, Code,
  ChevronDown,
} from 'lucide-react'
import { useState } from 'react'

const fade = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
}

function Collapse({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-gray-100">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-4 text-left text-sm font-semibold text-gray-900 hover:text-accent transition-colors"
      >
        {title}
        <ChevronDown
          size={16}
          className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && <div className="pb-5 text-sm leading-relaxed text-gray-600">{children}</div>}
    </div>
  )
}

function SectionCard({ icon: Icon, title, children }) {
  return (
    <motion.div
      variants={fade}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true }}
      className="rounded-xl border border-gray-100 p-6"
    >
      <div className="mb-3 inline-flex rounded-lg bg-accent-50 p-2.5 text-accent">
        <Icon size={20} strokeWidth={1.8} />
      </div>
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      <div className="mt-3 text-sm leading-relaxed text-gray-600">{children}</div>
    </motion.div>
  )
}

export default function Docs() {
  return (
    <div className="pt-20">
      {/* Hero */}
      <SectionWrapper>
        <div className="max-w-2xl">
          <h1 className="text-4xl font-bold tracking-tighter text-gray-900 sm:text-5xl">
            Documentation
          </h1>
          <p className="mt-4 text-lg text-gray-500">
            How Trawlbase works under the hood — the extraction pipeline,
            anti-detection stack, enrichment system, and output format.
          </p>
        </div>
      </SectionWrapper>

      {/* Architecture Overview */}
      <SectionWrapper className="bg-gray-50/60">
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">Architecture</h2>
        <p className="mt-3 max-w-2xl text-sm text-gray-500">
          The scraper runs in two phases. Phase 1 extracts structured data from
          directory listing pages. Phase 2 visits each company's own website to
          enrich the records with data the directory doesn't have.
        </p>

        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          <SectionCard icon={Navigation} title="Phase 1 — Directory Scraping">
            <ol className="mt-2 space-y-2 list-decimal list-inside">
              <li><strong>Navigate</strong> — AI analyzes links up to 3 levels deep to find the directory page.</li>
              <li><strong>Search</strong> — Detects search forms, tries blank/"%"/"all"/"a" queries. Detects starts-with (A-Z) sites and iterates the full alphabet.</li>
              <li><strong>Capture</strong> — Intercepts JSON API responses and captures rendered HTML from the browser.</li>
              <li><strong>Paginate</strong> — Clicks Next/Load More buttons, handles numbered pagination and infinite scroll.</li>
              <li><strong>Extract</strong> — 3-tier system: cached selectors (instant), AI-learned selectors (Claude Haiku), regex fallback.</li>
              <li><strong>Detail crawl</strong> — Optionally visits individual profile pages (e.g. <code>/members/123</code>) for full contact info.</li>
            </ol>
          </SectionCard>

          <SectionCard icon={Layers} title="Phase 2 — Website Enrichment">
            <ol className="mt-2 space-y-2 list-decimal list-inside">
              <li><strong>Filter</strong> — Identifies entries with a website but missing data (email, description, social).</li>
              <li><strong>Search</strong> — Companies without a website get searched on DuckDuckGo using name + address context.</li>
              <li><strong>Fetch</strong> — Visits homepage with curl_cffi (Chrome TLS fingerprint). Discovers /contact, /about, /team, /services subpages.</li>
              <li><strong>Extract</strong> — Pulls emails, phones, fax, address, description, social media, hours, services, team, founded year, and JSON-LD structured data.</li>
              <li><strong>Merge</strong> — Contact page data overrides homepage data. Original Phase 1 fields are preserved.</li>
            </ol>
            <p className="mt-3">Runs 8 parallel workers with thread-local sessions for connection pooling.</p>
          </SectionCard>
        </div>
      </SectionWrapper>

      {/* AI Extraction */}
      <SectionWrapper>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">AI Selector Learning</h2>
        <p className="mt-3 max-w-2xl text-sm text-gray-500">
          Most scrapers force you to write CSS selectors by hand. Trawlbase
          learns them automatically from 3 sample HTML cards using Claude Haiku,
          then applies those selectors to extract thousands of records with zero AI cost.
        </p>

        <div className="mt-8 grid gap-5 sm:grid-cols-3">
          <SectionCard icon={Database} title="Layer 1: Cached Selectors">
            <p>
              Previously learned selectors are cached per-domain. On repeat scrapes,
              extraction is instant — no AI calls, no regex parsing.
              100% cache hit rate after the first visit to a domain.
            </p>
          </SectionCard>

          <SectionCard icon={Brain} title="Layer 2: AI Learning">
            <p>
              For new domains, 3 sample member cards are sent to Claude Haiku.
              The AI returns CSS selectors for name, email, phone, address, and more.
              Cost: ~$0.001 per domain. One call learns selectors for the entire site.
            </p>
          </SectionCard>

          <SectionCard icon={Zap} title="Layer 3: Regex Fallback">
            <p>
              When AI is unavailable or the HTML structure is unusual, regex patterns
              detect phone numbers, emails, and addresses directly from the card HTML.
              No API key needed for this path.
            </p>
          </SectionCard>
        </div>
      </SectionWrapper>

      {/* Anti-Detection */}
      <SectionWrapper className="bg-gray-50/60">
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">Anti-Detection Stack</h2>
        <p className="mt-3 max-w-2xl text-sm text-gray-500">
          Modern websites use multiple layers of bot detection. Trawlbase
          defeats each one with a corresponding countermeasure.
        </p>

        <div className="mt-8 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-gray-500">
                <th className="pb-3 pr-6 font-medium">Detection Method</th>
                <th className="pb-3 pr-6 font-medium">What They Check</th>
                <th className="pb-3 font-medium">How We Bypass</th>
              </tr>
            </thead>
            <tbody className="text-gray-700">
              <tr className="border-b border-gray-50">
                <td className="py-3 pr-6 font-medium">TLS Fingerprinting</td>
                <td className="py-3 pr-6">JA3/JA4 hash of the TLS handshake</td>
                <td className="py-3">curl_cffi impersonates Chrome 136, Safari 184, Firefox TLS signatures</td>
              </tr>
              <tr className="border-b border-gray-50">
                <td className="py-3 pr-6 font-medium">navigator.webdriver</td>
                <td className="py-3 pr-6">Browser JS property set to true for automation</td>
                <td className="py-3">playwright-stealth patches it to undefined</td>
              </tr>
              <tr className="border-b border-gray-50">
                <td className="py-3 pr-6 font-medium">WebGL Fingerprint</td>
                <td className="py-3 pr-6">GPU vendor/renderer strings</td>
                <td className="py-3">Overridden to "Intel Iris OpenGL Engine" / "Intel Inc."</td>
              </tr>
              <tr className="border-b border-gray-50">
                <td className="py-3 pr-6 font-medium">Chrome Runtime</td>
                <td className="py-3 pr-6">Missing chrome.app, chrome.csi objects</td>
                <td className="py-3">Stealth injects chrome.app, chrome.csi, chrome.loadTimes</td>
              </tr>
              <tr className="border-b border-gray-50">
                <td className="py-3 pr-6 font-medium">Sec-CH-UA Headers</td>
                <td className="py-3 pr-6">Client hint headers mismatching user agent</td>
                <td className="py-3">Auto-derived from the impersonated user agent string</td>
              </tr>
              <tr>
                <td className="py-3 pr-6 font-medium">Resource Loading</td>
                <td className="py-3 pr-6">Bots load pages unusually fast (no images/fonts)</td>
                <td className="py-3">CSS and JS are fully loaded; only images, fonts, and media are blocked</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionWrapper>

      {/* Output Schema */}
      <SectionWrapper>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">Output Schema</h2>
        <p className="mt-3 max-w-2xl text-sm text-gray-500">
          Every scrape produces a normalized JSON file. Phase 2 enrichment adds
          fields without overwriting existing data.
        </p>

        <div className="mt-8 grid gap-5 sm:grid-cols-2">
          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Phase 1 — Directory Data</h3>
            <pre className="rounded-xl border border-gray-100 bg-gray-50/60 p-5 text-xs leading-relaxed text-gray-700 overflow-x-auto">
{`{
  "company_name": "ABC Construction Inc.",
  "description": null,
  "category": "Builder/Residential",
  "website": "https://abcconstruction.com",
  "phone": "(320) 555-1234",
  "fax": "(320) 555-1235",
  "street_address": "123 Main St, St. Cloud, MN",
  "mailing_address": null,
  "contacts": [
    { "name": "John Smith",
      "email": "john@abcconstruction.com" }
  ]
}`}
            </pre>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Phase 2 — Enriched Data</h3>
            <pre className="rounded-xl border border-gray-100 bg-gray-50/60 p-5 text-xs leading-relaxed text-gray-700 overflow-x-auto">
{`{
  // ...all Phase 1 fields preserved
  "social_media": {
    "facebook": "https://facebook.com/abc",
    "linkedin": "https://linkedin.com/company/abc"
  },
  "hours": "Mon-Fri 7:00am - 5:00pm",
  "services": ["Custom Homes", "Remodeling"],
  "founded": "1985",
  "team": [
    { "name": "John Smith", "title": "Owner" }
  ],
  "enrichment_source": "https://abcconstruction.com",
  "enrichment_status": "enriched"
}`}
            </pre>
          </div>
        </div>
      </SectionWrapper>

      {/* FAQ */}
      <SectionWrapper className="bg-gray-50/60">
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">FAQ</h2>
        <div className="mt-6 max-w-2xl">
          <Collapse title="What kind of sites does this work on?" defaultOpen>
            <p>
              Any public directory or listing page — HOA rosters, chambers of
              commerce, trade and professional associations, medical and attorney
              directories, real estate agent pages. The AI adapts to each site's
              structure. Sites built on GrowthZone, ChamberMaster, YourMembership,
              WordPress, and custom CMS platforms are all supported.
            </p>
          </Collapse>

          <Collapse title="How much does the AI cost?">
            <p>
              About $0.001 per new domain. Claude Haiku analyzes 3 sample cards
              to learn selectors, then all further extraction uses those cached
              selectors with zero AI cost. A typical session costs under a penny.
            </p>
          </Collapse>

          <Collapse title="Why do some Phase 2 enrichments fail?">
            <p>
              Common reasons: the company's domain is expired, the site uses
              Cloudflare JS challenges (requires a full browser, not HTTP requests),
              or the server is slow and times out. The enrichment status in the
              output JSON tells you exactly what happened for each entry.
            </p>
          </Collapse>

          <Collapse title="Can it scrape sites that require login?">
            <p>
              Not currently. The bot works on publicly accessible directory pages
              only. Member portals behind authentication are not supported.
            </p>
          </Collapse>

          <Collapse title="How does it handle pagination?">
            <p>
              The bot detects Next/Previous buttons, numbered page links, "Load More"
              buttons, and infinite scroll. It captures network responses during each
              page transition and stops when no new data arrives or a configurable
              threshold is reached.
            </p>
          </Collapse>

          <Collapse title="What is the starts-with (A-Z) search?">
            <p>
              Some directories only show members starting with a specific letter.
              The bot detects this pattern by checking if &gt;80% of visible names
              start with "A", then automatically iterates through all 26 letters
              plus digits 0-9 to capture the full directory.
            </p>
          </Collapse>
        </div>
      </SectionWrapper>
    </div>
  )
}
