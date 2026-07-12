import { useState, useRef, useCallback } from 'react'
import InputPanel from './InputPanel'
import OutputTerminal from './OutputTerminal'
import useSSE from '../../hooks/useSSE'
import useAnalytics from '../../hooks/useAnalytics'
import { MOCK_TERMINAL_EVENTS } from '../../lib/mockData'

export default function Playground() {
  const sse = useSSE()
  const { trackEvent } = useAnalytics()
  const [mockLines, setMockLines] = useState([])
  const [mockRunning, setMockRunning] = useState(false)
  const [mockComplete, setMockComplete] = useState(false)
  const [currentIndex, setCurrentIndex] = useState(null)
  const [totalUrls, setTotalUrls] = useState(0)
  const [useRealBackend, setUseRealBackend] = useState(true)
  const [detailed, setDetailed] = useState(false)
  const timeouts = useRef([])

  const clearTimeouts = () => {
    timeouts.current.forEach(clearTimeout)
    timeouts.current = []
  }

  const runMock = useCallback(() => {
    clearTimeouts()
    setMockLines([])
    setMockRunning(true)
    setMockComplete(false)
    setCurrentIndex(0)
    setTotalUrls(1)

    let cumDelay = 0
    MOCK_TERMINAL_EVENTS.forEach((event, i) => {
      cumDelay += event.delay
      const t = setTimeout(() => {
        setMockLines((prev) => [...prev, { text: event.text, category: event.category }])
        if (i === MOCK_TERMINAL_EVENTS.length - 1) {
          setMockRunning(false)
          setMockComplete(true)
          setCurrentIndex(null)
        }
      }, cumDelay)
      timeouts.current.push(t)
    })
  }, [])

  const handleRun = useCallback(async ({ urls, taskType, priorityFields, accurateEnrichment, goal }) => {
    if (!urls || urls.length === 0 || !useRealBackend) {
      runMock()
      return
    }

    const mode = taskType === 'Direct Scrape' ? 'direct' : 'auto'
    const scraperMode = mode === 'direct' ? 'direct_scrape' : 'auto_discover'
    setTotalUrls(urls.length)

    // Scrape each URL sequentially
    for (let i = 0; i < urls.length; i++) {
      setCurrentIndex(i)
      trackEvent('scrape_started', { mode: scraperMode, url: urls[i] })
      await sse.startScrape(urls[i], {
        mode,
        append: i > 0,
        priorityFields,
        accurateEnrichment,
        goal,
        debug: detailed,
      })
      // Report result after each URL completes
      if (sse.result) {
        trackEvent('scrape_done', {
          mode: scraperMode,
          url: urls[i],
          records: sse.result.records || 0,
          enriched: sse.result.enriched || 0,
        })
      }
    }

    setCurrentIndex(null)
  }, [useRealBackend, sse, runMock, detailed, trackEvent])

  // Use real SSE data if backend is active, otherwise mock
  const isBackendActive = sse.status !== null
  const lines = isBackendActive ? sse.lines : mockLines
  const isRunning = isBackendActive ? sse.status === 'running' : mockRunning
  const isComplete = isBackendActive
    ? (sse.status === 'done' || sse.status === 'error') && currentIndex === null
    : mockComplete

  return (
    <div className="min-h-screen bg-white pt-20">
      <div className="mx-auto max-w-site px-6 py-12">
        {/* Header */}
        <div className="mx-auto flex max-w-2xl items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tighter text-black sm:text-4xl">Scraper</h1>
            <p className="mt-1.5 text-sm text-gray-500">
              Point it at a directory. Choose to scrape the page or let it discover the listings itself.
            </p>
          </div>
          <label className="mt-1 flex shrink-0 select-none items-center gap-1.5 font-mono text-[11px] text-gray-300 hover:text-gray-500">
            <input
              type="checkbox"
              checked={useRealBackend}
              onChange={(e) => setUseRealBackend(e.target.checked)}
              className="h-3 w-3 border-gray-300"
            />
            live
          </label>
        </div>

        {/* Control stack — the URL bar and its options, centered. */}
        <div className="mx-auto mt-8 max-w-2xl">
          <InputPanel
            onRun={handleRun}
            isRunning={isRunning}
            currentIndex={currentIndex}
            totalUrls={totalUrls}
          />
        </div>

        {/* Output — full width, cleanly at the bottom. */}
        <div className="mt-12">
          <OutputTerminal
            lines={lines}
            isComplete={isComplete}
            isRunning={isRunning}
            awaitingInput={sse.awaitingInput}
            onInput={sse.sendInput}
            outputFile={sse.result?.output_file}
            detailed={detailed}
            onDetailedChange={setDetailed}
          />
        </div>
      </div>
    </div>
  )
}
