import { motion } from 'framer-motion'
import { EASE } from '../lib/motion'

// A quiet fade-up on every route change. Mount-only (no exit) so navigation
// never feels laggy — the old page leaves instantly, the new one settles in.
export default function PageTransition({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}
