import { motion } from 'framer-motion'
import * as Icons from 'lucide-react'
import SectionWrapper from '../../components/SectionWrapper'
import { HOW_IT_WORKS } from '../../lib/constants'
import { EASE } from '../../lib/motion'

const ICON_ANIMATIONS = {
  MessageSquare: {
    animate: { scale: [1, 1.08, 1] },
    transition: { duration: 2, repeat: Infinity, repeatDelay: 1.5, ease: 'easeInOut' },
  },
  Cog: {
    animate: { rotate: 360 },
    transition: { duration: 6, repeat: Infinity, ease: 'linear' },
  },
  Layers: {
    animate: { y: [0, -4, 0] },
    transition: { duration: 2.4, repeat: Infinity, ease: 'easeInOut' },
  },
  Download: {
    animate: { y: [0, 4, 0] },
    transition: { duration: 1.4, repeat: Infinity, repeatDelay: 2, ease: 'easeInOut' },
  },
}

export default function HowItWorks() {
  return (
    <SectionWrapper>
      <div className="text-center">
        <h2 className="text-3xl font-bold tracking-tighter text-gray-900 sm:text-4xl">
          How it works
        </h2>
        <p className="mx-auto mt-4 max-w-md text-gray-500">
          Four steps from a directory to structured data.
        </p>
      </div>

      <div className="relative mt-16">
        {/* Connecting line (desktop only) */}
        <div className="absolute top-10 left-[12.5%] right-[12.5%] hidden h-px bg-gray-200 lg:block" />

        <div className="grid gap-6 sm:grid-cols-2 sm:gap-8 lg:grid-cols-4 lg:gap-8">
          {HOW_IT_WORKS.map((item, i) => {
            const Icon = Icons[item.icon] || Icons.Zap
            const anim = ICON_ANIMATIONS[item.icon] || {}
            return (
              <motion.div
                key={item.step}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.12, duration: 0.5, ease: EASE }}
                className="relative flex flex-col items-center text-center"
              >
                <div className="relative z-10 flex h-20 w-20 items-center justify-center rounded-2xl border border-gray-100 bg-white shadow-sm">
                  <motion.div
                    animate={anim.animate}
                    transition={anim.transition}
                  >
                    <Icon size={28} className="text-accent" strokeWidth={1.5} />
                  </motion.div>
                </div>
                <div className="mt-1 flex h-7 w-7 items-center justify-center rounded-full bg-accent text-xs font-bold text-white">
                  {item.step}
                </div>
                <h3 className="mt-4 text-lg font-semibold text-gray-900">{item.title}</h3>
                <p className="mt-2 max-w-xs text-sm text-gray-500">{item.description}</p>
              </motion.div>
            )
          })}
        </div>
      </div>
    </SectionWrapper>
  )
}
