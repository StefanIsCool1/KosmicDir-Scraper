import { motion } from 'framer-motion'
import * as Icons from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { WHY_TRAWLBASE } from '../../lib/constants'
import { fadeUpStagger as cardVariants } from '../../lib/motion'

export default function WhyChooseUs() {
  return (
    <SectionWrapper>
      <div className="text-center">
        <h2 className="text-3xl font-bold tracking-tighter text-gray-900 sm:text-4xl">
          Why Trawlbase
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-gray-500">
          Most scrapers stop at the listing. This one finishes the job.
        </p>
      </div>

      <div className="mt-14 grid gap-5 md:grid-cols-3">
        {WHY_TRAWLBASE.map((item, i) => {
          const Icon = Icons[item.icon] || Icons.Check
          return (
            <motion.div
              key={item.title}
              custom={i}
              variants={cardVariants}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: '-40px' }}
              className="flex gap-4 rounded-xl border border-gray-100 p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
            >
              <div className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent-50 text-accent">
                <Icon size={22} strokeWidth={1.8} />
              </div>
              <div>
                <h3 className="text-base font-semibold text-gray-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-500">{item.description}</p>
              </div>
            </motion.div>
          )
        })}
      </div>
    </SectionWrapper>
  )
}
