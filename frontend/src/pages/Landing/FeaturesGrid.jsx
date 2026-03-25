import { motion } from 'framer-motion'
import * as Icons from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { FEATURES } from '../../lib/constants'

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: (i) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, duration: 0.5 },
  }),
}

export default function FeaturesGrid() {
  return (
    <SectionWrapper id="features">
      <div className="text-center">
        <h2 className="text-3xl font-bold tracking-tighter text-gray-900 sm:text-4xl">
          Everything you need to scrape any directory
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-gray-500">
          One tool. Paste a URL, get structured data.
        </p>
      </div>

      <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature, i) => {
          const Icon = Icons[feature.icon] || Icons.Zap
          return (
            <motion.div
              key={feature.title}
              custom={i}
              variants={cardVariants}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: '-40px' }}
              className="group rounded-xl border border-gray-100 p-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
            >
              <div className="mb-4 inline-flex rounded-lg bg-accent-50 p-2.5 text-accent">
                <Icon size={20} strokeWidth={1.8} />
              </div>
              <h3 className="text-base font-semibold text-gray-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-gray-500">{feature.description}</p>
            </motion.div>
          )
        })}
      </div>
    </SectionWrapper>
  )
}
