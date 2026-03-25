import { motion } from 'framer-motion'
import Button from '../../components/Button'

export default function CTASection() {
  return (
    <section className="bg-[#FAFAFA] px-6 py-20 md:py-28">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.6 }}
        className="mx-auto max-w-lg text-center"
      >
        <h2 className="text-3xl font-bold tracking-tighter text-gray-900 sm:text-4xl">
          Ready to scrape your first directory?
        </h2>
        <p className="mt-4 text-gray-500">
          Try the playground for free. No account required.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Button to="/playground">Try the Playground &rarr;</Button>
          <Button variant="secondary" to="/pricing">
            View Pricing
          </Button>
        </div>
      </motion.div>
    </section>
  )
}
