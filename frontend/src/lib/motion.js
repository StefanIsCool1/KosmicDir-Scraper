// Shared motion language — keep it consistent and Apple-quiet across the site.
// Only transform + opacity are animated (GPU-friendly), so it stays smooth on phones.

// easeOutQuint-ish: a soft, confident settle. This single curve is what makes
// the whole site feel cohesive rather than each section easing differently.
export const EASE = [0.22, 1, 0.36, 1]

// Standard "rise + fade" reveal used by section content.
export const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
}

// Staggered variant for grids/lists — pass the index as `custom`.
export const fadeUpStagger = {
  hidden: { opacity: 0, y: 16 },
  visible: (i = 0) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, duration: 0.5, ease: EASE },
  }),
}

// Reveal slightly before the element is fully on-screen; fire once.
export const viewportOnce = { once: true, margin: '-60px' }
