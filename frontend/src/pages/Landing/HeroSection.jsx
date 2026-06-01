import { motion } from 'framer-motion'
import Button from '../../components/Button'
import useTypewriter from '../../hooks/useTypewriter'
import { HERO_TERMINAL_LINES } from '../../lib/constants'
import { EASE } from '../../lib/motion'

function TerminalPreview() {
  const { visibleLines } = useTypewriter(HERO_TERMINAL_LINES, {
    speed: 18,
    lineDelay: 300,
    loop: true,
    loopPause: 4000,
  })

  return (
    <div className="mx-auto mt-12 max-w-2xl overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
      {/* Title bar */}
      <div className="flex items-center gap-2 border-b border-gray-800 px-4 py-3">
        <div className="h-3 w-3 rounded-full bg-red-500/80" />
        <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
        <div className="h-3 w-3 rounded-full bg-green-500/80" />
        <span className="ml-2 text-xs text-gray-500 font-mono">trawlbase</span>
      </div>
      {/* Terminal body */}
      <div className="h-72 overflow-hidden px-5 py-4 font-mono text-sm leading-relaxed">
        {visibleLines.map((line, i) => (
          <div key={i} style={{ color: line.color || '#9CA3AF' }}>
            {line.text}
            {i === visibleLines.length - 1 && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-middle" />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-white px-6 pb-20 pt-32 md:pb-28 md:pt-40">
      <div className="mx-auto max-w-site text-center">
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE }}
          className="mx-auto max-w-3xl text-4xl font-bold leading-tight tracking-tighter text-gray-900 sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Turn any directory into{' '}
          <span className="text-accent">structured data.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1, ease: EASE }}
          className="mx-auto mt-6 max-w-xl text-lg text-gray-500"
        >
          Point Trawlbase at a directory &mdash; HOAs, chambers of commerce, trade associations. It pulls every record, enriches each from its own website, and hands you clean JSON or CSV.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: EASE }}
          className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row"
        >
          <Button to="/playground">Open the Scraper &rarr;</Button>
          <Button variant="secondary" to="/docs">
            Read the docs
          </Button>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.35, ease: EASE }}
        >
          <TerminalPreview />
        </motion.div>
      </div>
    </section>
  )
}
