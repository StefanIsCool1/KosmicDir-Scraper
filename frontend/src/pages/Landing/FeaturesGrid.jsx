import * as Icons from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { FEATURES } from '../../lib/constants'

// Cards are drawn with a single hairline top rule — no backgrounds, no
// shadows, no hover theatrics (they aren't links).
export default function FeaturesGrid() {
  return (
    <SectionWrapper id="features">
      <div className="max-w-xl">
        <h2 className="text-3xl font-semibold tracking-tighter text-black sm:text-4xl">
          Everything a scraper should do
        </h2>
        <p className="mt-4 text-gray-500">
          Point it at a directory. Get back clean, complete data.
        </p>
      </div>

      <div className="mt-16 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature) => {
          const Icon = Icons[feature.icon] || Icons.Zap
          return (
            <div key={feature.title} className="border-t border-hairline pt-6">
              <Icon size={20} strokeWidth={2} className="text-black" aria-hidden="true" />
              <h3 className="mt-6 text-base font-semibold text-black">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-500">{feature.description}</p>
            </div>
          )
        })}
      </div>
    </SectionWrapper>
  )
}
