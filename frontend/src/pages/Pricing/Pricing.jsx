import { useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import Button from '../../components/Button'
import { PRICING_TIERS, PRICING_FAQ } from '../../lib/constants'

function PricingCard({ tier, annual }) {
  const price = annual ? tier.price.annual : tier.price.monthly
  const isPopular = tier.popular

  return (
    <div
      className={`relative flex flex-col border bg-white p-8 ${
        isPopular ? 'border-black' : 'border-hairline'
      }`}
    >
      {isPopular && (
        <span className="absolute -top-3 left-8 bg-black px-3 py-1 text-xs font-medium text-white">
          Most popular
        </span>
      )}

      <h3 className="text-lg font-semibold text-black">{tier.name}</h3>
      <p className="mt-1 text-sm text-gray-500">{tier.description}</p>

      <div className="mt-6">
        <span className="text-4xl font-bold tracking-tight tabular-nums text-black">
          ${price}
        </span>
        <span className="text-sm text-gray-500">/mo</span>
        {annual && tier.price.monthly > 0 && (
          <p className="mt-1 text-xs text-gray-500">
            Save ${(tier.price.monthly - tier.price.annual) * 12}/year
          </p>
        )}
      </div>

      <div className="my-8 h-px bg-hairline" />

      <ul className="flex-1 space-y-3">
        {tier.features.map((feat) => (
          <li key={feat} className="flex items-start gap-2.5 text-sm text-gray-600">
            <Check size={16} className="mt-0.5 shrink-0 text-black" aria-hidden="true" />
            {feat}
          </li>
        ))}
      </ul>

      <Button
        to="/playground"
        variant={isPopular ? 'primary' : 'secondary'}
        size="sm"
        className="mt-8 w-full py-3"
      >
        {tier.cta}
      </Button>
    </div>
  )
}

function FAQItem({ item }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border-b border-hairline">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-5 text-left"
        aria-expanded={open}
      >
        <span className="text-sm font-medium text-black">{item.q}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-gray-500 transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
          aria-hidden="true"
        />
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ${
          open ? 'max-h-40 pb-5' : 'max-h-0'
        }`}
      >
        <p className="text-sm leading-relaxed text-gray-500">{item.a}</p>
      </div>
    </div>
  )
}

export default function Pricing() {
  const [annual, setAnnual] = useState(false)

  // The billing toggle is a square segmented control: active segment is
  // solid black — state reads instantly, no pill styling.
  const segment = (isActive) =>
    `px-4 py-1.5 text-sm font-medium transition-colors ${
      isActive ? 'bg-black text-white' : 'text-gray-500 hover:text-black'
    }`

  return (
    <div className="bg-white pt-24">
      {/* Header */}
      <section className="mx-auto max-w-site px-6 pb-16 pt-12 md:pt-20 lg:px-16">
        <h1 className="max-w-[16ch] text-4xl font-bold tracking-tighter text-black sm:text-5xl">
          Simple, transparent pricing
        </h1>
        <p className="mt-4 max-w-md text-gray-500">
          Start free. Upgrade when you need enrichment, batch scraping, or API access.
        </p>

        <div className="mt-8 inline-flex border border-black p-0.5">
          <button onClick={() => setAnnual(false)} className={segment(!annual)}>
            Monthly
          </button>
          <button onClick={() => setAnnual(true)} className={segment(annual)}>
            Annual <span className="ml-1 text-xs">&minus;20%</span>
          </button>
        </div>
      </section>

      {/* Pricing cards */}
      <section className="mx-auto max-w-site px-6 pb-24 lg:px-16">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {PRICING_TIERS.map((tier) => (
            <PricingCard key={tier.name} tier={tier} annual={annual} />
          ))}
        </div>
        <p className="mt-12 text-sm text-gray-500">
          Need higher volume or a custom vertical?{' '}
          <a href="mailto:stefan@trawlbase.com" className="text-black underline-offset-4 hover:underline">
            Talk to us
          </a>
          .
        </p>
      </section>

      {/* FAQ */}
      <section className="border-t border-hairline bg-surface px-6 py-24 lg:px-16">
        <div className="mx-auto max-w-site">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-tighter text-black sm:text-3xl">
              Frequently asked questions
            </h2>
            <div className="mt-12">
              {PRICING_FAQ.map((item) => (
                <FAQItem key={item.q} item={item} />
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
