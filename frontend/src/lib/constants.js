export const NAV_LINKS = [
  { label: 'Features', href: '/#features' },
  { label: 'Playground', href: '/playground' },
  { label: 'Docs', href: '/docs' },
  { label: 'Pricing', href: '/pricing' },
]

export const FEATURES = [
  {
    icon: 'Brain',
    title: 'Learns page structure',
    description:
      'Reads 3 sample cards, figures out the selectors, then extracts every record on the site. No setup required.',
  },
  {
    icon: 'Globe',
    title: 'Handles JavaScript sites',
    description:
      'Full browser under the hood. Infinite scroll, AJAX loading, SPAs, paginated results — it just works.',
  },
  {
    icon: 'ShieldCheck',
    title: 'Gets past bot detection',
    description:
      'Rotates browser TLS fingerprints and patches every detection vector. Most sites can\'t tell it apart from a real visitor.',
  },
  {
    icon: 'Layers',
    title: 'Enriches from company sites',
    description:
      'After scraping the directory, visits each company\'s website to pull emails, social links, descriptions, and team info.',
  },
  {
    icon: 'Search',
    title: 'Finds missing websites',
    description:
      'No website listed? Searches by company name and address to find it, then enriches like the rest.',
  },
  {
    icon: 'FileJson',
    title: 'Clean JSON and CSV output',
    description:
      'Every scrape produces a normalized file. Names, emails, phones, addresses, social profiles — one row per company.',
  },
  {
    icon: 'Zap',
    title: 'Fast on repeat scrapes',
    description:
      'Selectors are cached per domain. Second scrape of the same site is instant — zero AI calls, zero cost.',
  },
  {
    icon: 'Navigation',
    title: 'Finds the directory for you',
    description:
      'Paste any URL on the site. The bot navigates to the directory page, finds the search form, and starts extracting.',
  },
  {
    icon: 'Terminal',
    title: 'See everything live',
    description:
      'Watch the bot work in real-time. Every click, every extraction, every enrichment — streamed to your terminal.',
  },
  {
    icon: 'Users',
    title: 'Crawls profile pages',
    description:
      'When the listing page only shows names, the bot clicks into each profile to get the full contact details.',
  },
]

export const COMPARISON_FEATURES = [
  'AI-powered extraction',
  'No-code UI + API',
  'Built-in data enrichment',
  'TLS fingerprint rotation',
  'Real-time terminal output',
  'Self-hosted / open source',
  'Directory-optimized',
  'Detail page crawling',
  'Website discovery (search)',
]

export const COMPARISON_DATA = {
  'Kosmic Scraper': [true, true, true, true, true, true, true, true, true],
  Firecrawl: [true, 'API only', false, true, false, true, false, false, false],
  'Browse AI': [true, 'No-code only', false, 'Partial', false, false, false, false, false],
  Crawl4AI: [true, 'Code only', false, false, false, true, false, false, false],
  Octoparse: [false, 'No-code only', false, 'Partial', false, false, false, false, false],
}

export const HOW_IT_WORKS = [
  {
    step: 1,
    title: 'Paste a URL',
    description: 'Any page on the site. The bot finds the directory itself.',
    icon: 'MousePointerClick',
  },
  {
    step: 2,
    title: 'Bot extracts everything',
    description: 'Navigates, paginates, and pulls every record. Learns the page layout on its own.',
    icon: 'Cog',
  },
  {
    step: 3,
    title: 'Enrich from websites',
    description: 'Visits each company site for emails, social links, and descriptions.',
    icon: 'Layers',
  },
  {
    step: 4,
    title: 'Export JSON or CSV',
    description: 'One row per company. Ready for your CRM, spreadsheet, or database.',
    icon: 'Download',
  },
]

export const PRICING_TIERS = [
  {
    name: 'Free',
    price: { monthly: 0, annual: 0 },
    description: 'Try it out. Scrape a few directories.',
    cta: 'Get Started',
    features: [
      '3 scrapes per month',
      'Phase 1 directory extraction',
      'Up to 200 records per scrape',
      'Basic fields (name, phone, email, address)',
      'Web UI access',
      'JSON export',
    ],
  },
  {
    name: 'Pro',
    price: { monthly: 49, annual: 39 },
    popular: true,
    description: 'Scrape + enrich. The full pipeline.',
    cta: 'Start Free Trial',
    features: [
      '30 scrapes per month',
      'Phase 1 + Phase 2 enrichment',
      'Up to 2,000 records per scrape',
      'All fields (social, description, category)',
      'CSV batch upload (10 URLs)',
      'Export to CSV & JSON',
      'Website discovery via search',
      'Email & phone extraction',
    ],
  },
  {
    name: 'Enterprise',
    price: { monthly: 199, annual: 159 },
    description: 'No limits. Scrape everything.',
    cta: 'Contact Sales',
    features: [
      'Unlimited scrapes',
      'Phase 1 + Phase 2 enrichment',
      'Unlimited records',
      'All fields + team, services, hours',
      'CSV batch upload (unlimited)',
      'API access',
      '8 parallel enrichment workers',
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
  { text: '→ Stealth: TLS fingerprint chrome136, WebGL patched', color: '#6C5CE7' },
  { text: '→ Navigating to https://members.example.org', color: '#888' },
  { text: '→ AI found directory page (depth 2)', color: '#6C5CE7' },
  { text: '→ Search: blank query → 847 results', color: '#888' },
  { text: '→ Learning selectors from 3 sample cards...', color: '#6C5CE7' },
  { text: '→ Learned: name, email, phone, address, category ✓', color: '#22C55E' },
  { text: '→ Paginating... page 4 of 17', color: '#888' },
  { text: '→ Captured 847 member records', color: '#22C55E' },
  { text: '', color: '#555' },
  { text: '→ Phase 2: Enriching from company websites (8 workers)', color: '#6C5CE7' },
  { text: '→ Searching for 69 missing websites...', color: '#888' },
  { text: '→ Found 42 websites via DuckDuckGo', color: '#22C55E' },
  { text: '→ Enriched 683/847 — emails, social, services', color: '#22C55E' },
  { text: '', color: '#555' },
  { text: '✓ Saved to members_example_org_enriched.json', color: '#22C55E' },
]
