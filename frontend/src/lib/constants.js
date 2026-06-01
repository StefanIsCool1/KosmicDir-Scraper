export const NAV_LINKS = [
  { label: 'Features', href: '/#features' },
  { label: 'Scraper', href: '/playground' },
  { label: 'Discover', href: '/agent' },
  { label: 'Docs', href: '/docs' },
  { label: 'Pricing', href: '/pricing' },
]

export const FEATURES = [
  {
    icon: 'Brain',
    title: 'Learns any page',
    description:
      'It reads a few sample cards, works out the selectors, and extracts every record. No templates, no setup.',
  },
  {
    icon: 'Layers',
    title: 'Enriches each record',
    description:
      'It visits each company\'s own site for the emails, socials, and hours the directory left out.',
  },
  {
    icon: 'Globe',
    title: 'Handles JavaScript',
    description:
      'A full browser runs under the hood. Infinite scroll, AJAX, SPAs, pagination — all of it.',
  },
  {
    icon: 'ShieldCheck',
    title: 'Gets past blocks',
    description:
      'Rotating TLS fingerprints and a patched browser. Sites can\'t tell it from a real visitor.',
  },
  {
    icon: 'Sparkles',
    title: 'Finds the directory',
    description:
      'No URL? Name the niche — an HOA roster, a local chamber, a trade-association member list — and Discover finds and qualifies it for you.',
  },
  {
    icon: 'FileJson',
    title: 'Clean JSON & CSV',
    description:
      'One tidy row per company — names, emails, phones, addresses, socials. Ready for your spreadsheet.',
  },
]

export const COMPARISON_FEATURES = [
  'Autonomous agent (describe → data)',
  'Plain-English goals',
  'Built-in data enrichment',
  'Official registry fast-path',
  'AI-powered extraction',
  'TLS fingerprint rotation',
  'Real-time terminal output',
  'Website discovery (search)',
  'Detail page crawling',
  'Directory-optimized',
  'No-code UI + API',
  'Self-hosted / open source',
]

export const COMPARISON_DATA = {
  Trawlbase: [true, true, true, true, true, true, true, true, true, true, true, true],
  Firecrawl: [false, false, false, false, true, true, false, false, false, false, 'API only', true],
  'Browse AI': [false, false, false, false, true, 'Partial', false, false, false, false, 'No-code only', false],
  Crawl4AI: [false, false, false, false, true, false, false, false, false, false, 'Code only', true],
  Octoparse: [false, false, false, false, false, 'Partial', false, false, false, false, 'No-code only', false],
}

export const HOW_IT_WORKS = [
  {
    step: 1,
    title: 'Point it at a directory',
    description: 'Paste a directory URL — or describe what you need and let Discover find one.',
    icon: 'MessageSquare',
  },
  {
    step: 2,
    title: 'It learns the page',
    description: 'It reads a few sample cards, works out the selectors, and extracts every record.',
    icon: 'Cog',
  },
  {
    step: 3,
    title: 'Scrape and enrich',
    description: 'Every record pulled, then filled in from each company\'s own site.',
    icon: 'Layers',
  },
  {
    step: 4,
    title: 'Export clean data',
    description: 'One row per company. Download JSON or CSV.',
    icon: 'Download',
  },
]

export const WHY_TRAWLBASE = [
  {
    icon: 'Layers',
    title: 'It doesn\'t stop at the listing',
    description:
      'Most scrapers hand you whatever the directory shows. Trawlbase visits each company\'s own site to fill in the emails, socials, and hours that were missing.',
  },
  {
    icon: 'Brain',
    title: 'No selectors to write',
    description:
      'No templates, no point-and-click recorder. It reads the page, learns its structure, and extracts every record on its own.',
  },
  {
    icon: 'ShieldCheck',
    title: 'It gets in',
    description:
      'Rotating TLS fingerprints and a patched browser sail past the bot detection that stops simpler tools cold.',
  },
]

export const PRICING_TIERS = [
  {
    name: 'Free',
    price: { monthly: 0, annual: 0 },
    description: 'Scrape real directories. No time limit.',
    cta: 'Start Scraping',
    features: [
      '10 scrapes per month',
      'Directory extraction (Phase 1)',
      'Up to 500 records per scrape',
      'Core fields — name, phone, address, website',
      'JSON & CSV export',
    ],
  },
  {
    name: 'Pro',
    price: { monthly: 9, annual: 7 },
    popular: true,
    description: 'Full pipeline for indie hackers and small teams.',
    cta: 'Start Free Trial',
    features: [
      '50 scrapes per month',
      'Scrape + enrich (Phase 1 + 2)',
      'Up to 2,000 records per scrape',
      'Emails, socials, hours, category, description',
      'Website discovery via search',
      'CSV batch upload (25 URLs)',
      'JSON & CSV export',
      '14-day free trial, no card required',
    ],
  },
  {
    name: 'Scale',
    price: { monthly: 29, annual: 23 },
    description: 'For teams that scrape at volume.',
    cta: 'Get Started',
    features: [
      '200 scrapes per month',
      'Scrape + enrich (Phase 1 + 2)',
      'Up to 5,000 records per scrape',
      'Accurate enrichment (verify-by-fetch)',
      'CSV batch upload (100 URLs)',
      'API access',
      'Priority support',
    ],
  },
]

export const PRICING_FAQ = [
  {
    q: 'What counts as a "scrape"?',
    a: 'One scrape is a single directory URL processed through Phase 1. If you submit a CSV with 5 URLs, that counts as 5 scrapes.',
  },
  {
    q: 'What is Phase 2 enrichment?',
    a: 'Phase 2 visits each company\'s website found during Phase 1 to extract additional data — emails, phone numbers, social profiles, team members, and more. It dramatically increases the completeness of your dataset.',
  },
  {
    q: 'Can I cancel anytime?',
    a: 'Yes. All plans are month-to-month with no long-term commitment. Annual plans are billed upfront but can be cancelled with a prorated refund.',
  },
  {
    q: 'Do you offer a free trial for Pro?',
    a: 'Yes — Pro comes with a 14-day free trial. No credit card required to start.',
  },
  {
    q: 'What happens if I hit my scrape limit?',
    a: 'You\'ll be notified when you\'re close to your limit. You can upgrade at any time and the new limit takes effect immediately.',
  },
]

export const HERO_TERMINAL_LINES = [
  { text: '$ trawlbase scrape hoa-directory.org/members', color: '#6C5CE7' },
  { text: '→ Reading 3 sample cards...', color: '#888' },
  { text: '→ Selectors learned ✓', color: '#22C55E' },
  { text: '→ Stealth: TLS chrome136, WebGL patched', color: '#6C5CE7' },
  { text: '→ Paginating... captured 912 records', color: '#22C55E' },
  { text: '→ Enriching from company sites (8 workers)', color: '#6C5CE7' },
  { text: '→ Filled 814/912 — emails, social, hours', color: '#22C55E' },
  { text: '✓ Saved hoa_members.json (912 rows)', color: '#22C55E' },
]
