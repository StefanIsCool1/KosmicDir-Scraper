import * as Icons from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { WHY_TRAWLBASE } from '../../lib/constants'

export default function WhyChooseUs() {
  return (
    <SectionWrapper>
      <div className="max-w-xl">
        <h2 className="text-3xl font-semibold tracking-tighter text-black sm:text-4xl">
          Why Trawlbase
        </h2>
        <p className="mt-4 text-gray-500">
          Most scrapers stop at the listing. This one finishes the job.
        </p>
      </div>

      <div className="mt-16 grid gap-x-8 gap-y-12 md:grid-cols-3">
        {WHY_TRAWLBASE.map((item) => {
          const Icon = Icons[item.icon] || Icons.Check
          return (
            <div key={item.title} className="border-t border-hairline pt-6">
              <Icon size={20} strokeWidth={2} className="text-black" aria-hidden="true" />
              <h3 className="mt-6 text-base font-semibold text-black">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-500">{item.description}</p>
            </div>
          )
        })}
      </div>
    </SectionWrapper>
  )
}
