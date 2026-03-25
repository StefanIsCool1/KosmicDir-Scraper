import { useState, useRef, useCallback } from 'react'
import InputPanel from './InputPanel'
import OutputTerminal from './OutputTerminal'
import useSSE from '../../hooks/useSSE'
import { MOCK_TERMINAL_EVENTS } from '../../lib/mockData'

export default function Playground() {
  const sse = useSSE()
  const [mockLines, setMockLines] = useState([])
  const [mockRunning, setMockRunning] = useState(false)
  const [mockComplete, setMockComplete] = useState(false)
  const [currentIndex, setCurrentIndex] = useState(null)
  const [totalUrls, setTotalUrls] = useState(0)
  const [useRealBackend, setUseRealBackend] = useState(true)
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

  const handleRun = useCallback(async ({ urls, taskType, priorityFields }) => {
    if (!urls || urls.length === 0) {
      runMock()
      return
    }

    if (!useRealBackend) {
      runMock()
      return
    }

    const mode = taskType === 'Direct Scrape' ? 'direct' : 'auto'
    setTotalUrls(urls.length)

    // Scrape each URL sequentially
    for (let i = 0; i < urls.length; i++) {
      setCurrentIndex(i)
      await sse.startScrape(urls[i], { mode, append: i > 0, priorityFields })
    }

    setCurrentIndex(null)
  }, [useRealBackend, sse, runMock])

  // Use real SSE data if backend is active, otherwise mock
  const isBackendActive = sse.status !== null
  const lines = isBackendActive ? sse.lines : mockLines
  const isRunning = isBackendActive ? sse.status === 'running' : mockRunning
  const isComplete = isBackendActive
    ? (sse.status === 'done' || sse.status === 'error') && currentIndex === null
    : mockComplete

  return (
    <div className="min-h-screen bg-white pt-20">
      <div className="mx-auto max-w-site px-6 py-8">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tighter text-gray-900 sm:text-3xl">Playground</h1>
            <p className="mt-1 text-sm text-gray-500">
              Add one or more directory URLs and scrape them sequentially. Results stream in real-time.
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-400">
            <input
              type="checkbox"
              checked={useRealBackend}
              onChange={(e) => setUseRealBackend(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-gray-300 text-accent focus:ring-accent"
            />
            Live backend
          </label>
        </div>

        <div className="grid gap-8 lg:grid-cols-[400px_1fr]">
          <div className="rounded-xl border border-gray-100 bg-white p-6 shadow-sm h-fit">
            <InputPanel
              onRun={handleRun}
              isRunning={isRunning}
              currentIndex={currentIndex}
              totalUrls={totalUrls}
            />
          </div>
          <OutputTerminal
            lines={lines}
            isComplete={isComplete}
            awaitingInput={sse.awaitingInput}
            onInput={sse.sendInput}
            outputFile={sse.result?.output_file}
          />
        </div>
      </div>
    </div>
  )
}
