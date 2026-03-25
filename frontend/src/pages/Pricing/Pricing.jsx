import { useState } from 'react'
import { motion } from 'framer-motion'
import { Check, ChevronDown } from 'lucide-react'
import Button from '../../components/Button'
import { PRICING_TIERS, PRICING_FAQ } from '../../lib/constants'

function PricingCard({ tier, annual }) {
  const price = annual ? tier.price.annual : tier.price.monthly
  const isPopular = tier.popular

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5 }}
      className={`relative flex flex-col rounded-2xl border p-8 ${
        isPopular
          ? 'border-accent bg-accent-50/40 shadow-lg shadow-accent/10'
          : 'border-gray-200 bg-white'
      }`}
    >
      {isPopular && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-0.5 text-xs font-semibold text-white">
          Most Popular
        </span>
      )}

      <h3 className="text-lg font-semibold text-gray-900">{tier.name}</h3>
      <p className="mt-1 text-sm text-gray-500">{tier.description}</p>

      <div className="mt-6">
        <span className="text-4xl font-bold tracking-tight text-gray-900">
          ${price}
        </span>
        <span className="text-sm text-gray-500">/mo</span>
        {annual && tier.price.monthly > 0 && (
          <p className="mt-1 text-xs text-accent-600">
            Save ${(tier.price.monthly - tier.price.annual) * 12}/year
          </p>
        )}
      </div>

      <div className="my-8 h-px bg-gray-100" />

      <ul className="flex-1 space-y-3">
        {tier.features.map((feat) => (
          <li key={feat} className="flex items-start gap-2.5 text-sm text-gray-600">
            <Check size={16} className="mt-0.5 shrink-0 text-accent" />
            {feat}
          </li>
        ))}
      </ul>

      <Button
        to={tier.name === 'Enterprise' ? undefined : '/playground'}
        href={tier.name === 'Enterprise' ? 'mailto:hello@kosmic.dev' : undefined}
        variant={isPopular ? 'primary' : 'secondary'}
        className="mt-8 w-full"
      >
        {tier.cta}
      </Button>
    </motion.div>
  )
}

function FAQItem({ item }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border-b border-gray-100">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-5 text-left"
      >
        <span className="text-sm font-medium text-gray-900">{item.q}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-gray-400 transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
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

  return (
    <div className="bg-white pt-24">
      {/* Header */}
      <section className="px-6 pb-12 pt-12 text-center md:pt-20">
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-4xl font-bold tracking-tighter text-gray-900 sm:text-5xl"
        >
          Simple, transparent pricing
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mx-auto mt-4 max-w-md text-gray-500"
        >
          Start free. Upgrade when you need enrichment, batch scraping, or API access.
        </motion.p>

        {/* Billing toggle */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mt-8 inline-flex items-center gap-3 rounded-full border border-gray-200 bg-gray-50 px-1 py-1"
        >
          <button
            onClick={() => setAnnual(false)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
              !annual
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setAnnual(true)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${
              annual
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Annual
            <span className="ml-1.5 text-xs text-accent">-20%</span>
          </button>
        </motion.div>
      </section>

      {/* Pricing cards */}
      <section className="mx-auto max-w-site px-6 pb-20">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {PRICING_TIERS.map((tier) => (
            <PricingCard key={tier.name} tier={tier} annual={annual} />
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="bg-[#FAFAFA] px-6 py-20">
        <div className="mx-auto max-w-2xl">
          <h2 className="text-center text-2xl font-bold tracking-tighter text-gray-900 sm:text-3xl">
            Frequently asked questions
          </h2>
          <div className="mt-12">
            {PRICING_FAQ.map((item) => (
              <FAQItem key={item.q} item={item} />
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
