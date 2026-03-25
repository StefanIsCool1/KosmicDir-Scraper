import { motion } from 'framer-motion'
import { Check, X, Minus } from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { COMPARISON_FEATURES, COMPARISON_DATA } from '../../lib/constants'

function CellValue({ value }) {
  if (value === true) return <Check size={18} className="text-accent" strokeWidth={2.5} />
  if (value === false) return <X size={18} className="text-gray-300" strokeWidth={2} />
  return <span className="text-xs text-gray-400">{value}</span>
}

const competitors = Object.keys(COMPARISON_DATA)

export default function ComparisonTable() {
  return (
    <SectionWrapper gray>
      <div className="text-center">
        <h2 className="text-3xl font-bold tracking-tighter text-gray-900 sm:text-4xl">
          How Kosmic Scraper compares
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-gray-500">
          The only tool with built-in enrichment, real-time monitoring, and full anti-bot bypass.
        </p>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.6 }}
        className="mt-12 overflow-x-auto"
      >
        <table className="w-full min-w-[640px] border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-[#FAFAFA] pb-4 pr-4 text-left text-xs font-medium uppercase tracking-wide text-gray-400">
                Feature
              </th>
              {competitors.map((name) => (
                <th
                  key={name}
                  className={`pb-4 px-4 text-center text-xs font-semibold uppercase tracking-wide ${
                    name === 'Kosmic Scraper'
                      ? 'text-accent'
                      : 'text-gray-400'
                  }`}
                >
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARISON_FEATURES.map((feature, rowIdx) => (
              <tr key={feature} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}>
                <td className="sticky left-0 z-10 bg-inherit py-3.5 pr-4 text-gray-700 font-medium whitespace-nowrap">
                  {feature}
                </td>
                {competitors.map((name) => (
                  <td
                    key={name}
                    className={`py-3.5 px-4 text-center ${
                      name === 'Kosmic Scraper' ? 'bg-accent-50/40' : ''
                    }`}
                  >
                    <div className="flex items-center justify-center">
                      <CellValue value={COMPARISON_DATA[name][rowIdx]} />
                    </div>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </motion.div>
    </SectionWrapper>
  )
}
