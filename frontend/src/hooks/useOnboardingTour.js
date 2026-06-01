import { useState, useCallback, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

const STORAGE_KEY = 'trawlbase_onboarded'

/**
 * Steps in the interactive onboarding tour.
 * Each step has a `target` (data-tour attribute value) and `route`
 * (the page it expects to be on). When `route` changes or the user
 * clicks the target element, the step advances.
 *
 * `waitForClick` — step advances ONLY when the user clicks the target element.
 * Used for nav links where we want the user to physically click.
 */
const TOUR_STEPS = [
  {
    target: null,
    route: null,
    title: 'Welcome to Trawlbase',
    body: 'A quick 2-minute tour to show you how everything works.',
    placement: 'center',
    waitForClick: false,
  },
  {
    target: 'nav-playground',
    route: null,
    title: 'Scraper — Your Scraping Terminal',
    body: 'Click Scraper in the nav. This is where you paste directory URLs and get results instantly.',
    placement: 'bottom',
    waitForClick: true,
  },
  {
    target: 'playground-task-type',
    route: '/playground',
    title: 'Auto Discover vs Direct Scrape',
    body: 'Auto Discover finds the directory page for you — just paste the homepage. Direct Scrape skips the search and scrapes the exact URL you give it.',
    placement: 'bottom',
    waitForClick: false,
  },
  {
    target: 'playground-terminal',
    route: '/playground',
    title: 'The Terminal',
    body: 'Results stream here in real time. Every click, every extraction, every pagination — you see it all. When done, download as JSON or CSV.',
    placement: 'top',
    waitForClick: false,
  },
  {
    target: 'nav-agent',
    route: null,
    title: 'Discover — Describe What You Want',
    body: 'Now click Discover in the nav. Instead of pasting URLs, you just describe what you\'re looking for.',
    placement: 'bottom',
    waitForClick: true,
  },
  {
    target: 'agent-chat-input',
    route: '/agent',
    title: 'Try Discover',
    body: 'Type something like "HOAs in Washington" or "dentists in Austin, TX." Trawlbase finds matching directories on the web, qualifies them, and lets you pick which to scrape.',
    placement: 'top',
    waitForClick: false,
  },
  {
    target: null,
    route: null,
    title: "You're all set!",
    body: 'Scraper for direct scraping. Discover when you don\'t have a URL yet. Go scrape some directories.',
    placement: 'center',
    waitForClick: false,
  },
]

export default function useOnboardingTour() {
  const [step, setStep] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1' ? -1 : 0 }
    catch { return -1 }
  })
  const [targetRect, setTargetRect] = useState(null)
  const location = useLocation()
  const clickHandlerRef = useRef(null)

  const currentStep = step >= 0 && step < TOUR_STEPS.length ? TOUR_STEPS[step] : null

  const complete = useCallback(() => {
    try { localStorage.setItem(STORAGE_KEY, '1') } catch { /* noop */ }
    setStep(-1)
  }, [])

  // Measure target element position whenever step or route changes
  useEffect(() => {
    if (!currentStep || !currentStep.target) {
      setTargetRect(null)
      return
    }
    // Poll briefly in case the element hasn't rendered yet (route transition)
    let attempts = 0
    const measure = () => {
      const el = document.querySelector(`[data-tour="${currentStep.target}"]`)
      if (el) {
        setTargetRect(el.getBoundingClientRect())
      } else if (attempts < 10) {
        attempts++
        requestAnimationFrame(measure)
      }
    }
    measure()
    return () => { attempts = 999 } // stop polling on cleanup
  }, [step, location.pathname])

  // Attach click listeners to the target element for waitForClick steps
  useEffect(() => {
    if (!currentStep || !currentStep.waitForClick || !currentStep.target) return

    const el = document.querySelector(`[data-tour="${currentStep.target}"]`)
    if (!el) return

    const handler = () => setStep((s) => s + 1)
    clickHandlerRef.current = handler
    el.addEventListener('click', handler)
    return () => el.removeEventListener('click', handler)
  }, [step, currentStep?.target])

  // Auto-advance when route matches the step's expected route
  useEffect(() => {
    if (!currentStep || currentStep.waitForClick) return
    if (currentStep.route && location.pathname !== currentStep.route) return
    // Route matches (or step has no route constraint) — step is valid
  }, [location.pathname, step])

  const next = useCallback(() => setStep((s) => s + 1), [])
  const prev = useCallback(() => setStep((s) => Math.max(0, s - 1)), [])

  const show = step >= 0

  return { show, step, currentStep, targetRect, totalSteps: TOUR_STEPS.length, next, prev, complete }
}
