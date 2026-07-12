import SectionWrapper from '../../components/SectionWrapper'
import { HOW_IT_WORKS } from '../../lib/constants'

// The numerals are the structure: this really is a sequence, so 01–04 carry
// the information the icons and connecting line used to decorate.
export default function HowItWorks() {
  return (
    <SectionWrapper gray>
      <div className="max-w-xl">
        <h2 className="text-3xl font-semibold tracking-tighter text-black sm:text-4xl">
          How it works
        </h2>
        <p className="mt-4 text-gray-500">
          Four steps from a directory to structured data.
        </p>
      </div>

      <ol className="mt-16 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
        {HOW_IT_WORKS.map((item) => (
          <li key={item.step} className="border-t border-hairline pt-6">
            <span className="font-mono text-xs tabular-nums text-gray-500">
              0{item.step}
            </span>
            <h3 className="mt-6 text-base font-semibold text-black">{item.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-gray-500">{item.description}</p>
          </li>
        ))}
      </ol>
    </SectionWrapper>
  )
}
