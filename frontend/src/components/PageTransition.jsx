import { motion } from 'framer-motion'
import { EASE } from '../lib/motion'

// A 0.3s pure fade on route change — no slide. Mount-only (no exit) so
// navigation never feels laggy.
export default function PageTransition({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}
