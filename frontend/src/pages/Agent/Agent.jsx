import { useState, useRef, useEffect, useCallback } from 'react'
import { Sparkles } from 'lucide-react'
import ChatMessage from './ChatMessage'
import ChatInput from './ChatInput'
import formatTerminalLine, { STEALTH_BANNER } from '../../lib/formatTerminalLine'

const SUGGESTIONS = [
  'Find all HOAs in Washington state',
  'Find every dentist in Austin, TX',
  'Get me roofing contractors in Florida',
  'Scrape all restaurants in Portland',
]

const INITIAL_MESSAGE = {
  role: 'agent',
  text: "Hi! I'm the Kosmic Agent. Tell me what you're looking for and I'll find directories on the web. You pick which to scrape; I'll handle Phase 1 and Phase 2 from there.",
}

const REJECT_REASONS = {
  login_wall: 'login wall',
  no_directory_signals: 'no directory signals',
  thin_content: 'thin page',
  fetch_failed: 'unreachable',
  no_contact_info: 'no contact info',
}

export default function Agent() {
  const [messages, setMessages] = useState([INITIAL_MESSAGE])
  const [isRunning, setIsRunning] = useState(false)
  const scrollRef = useRef(null)

  // Per-stream mutable bag — survives renders without triggering them.
  // Holds the active session id (for /scrape/respond), the in-flight
  // status/sources/terminal bubble ids, and running counters.
  const streamRef = useRef({
    sessionId: null,
    statusId: null,
    sourcesId: null,
    terminalId: null,
    counters: null,
  })

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // --- Message updaters (memoized) ----------------------------------------

  const appendStep = useCallback((statusId, step) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === statusId ? { ...m, steps: [...(m.steps || []), step] } : m
      )
    )
  }, [])

  const updateLastStep = useCallback((statusId, patch) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== statusId) return m
        const steps = m.steps || []
        if (steps.length === 0) return m
        const last = steps[steps.length - 1]
        return { ...m, steps: [...steps.slice(0, -1), { ...last, ...patch }] }
      })
    )
  }, [])

  const patchMessage = useCallback((id, patch) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)))
  }, [])

  const appendTerminalLines = useCallback((terminalId, newLines) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === terminalId ? { ...m, lines: [...(m.lines || []), ...newLines] } : m
      )
    )
  }, [])

  // --- Confirmation handlers ----------------------------------------------

  const postRespond = useCallback(async (value) => {
    const { sessionId } = streamRef.current
    if (!sessionId) return
    try {
      await fetch('/scrape/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, value }),
      })
    } catch {
      // non-critical — backend will time out and treat as skip
    }
  }, [])

  const handleConfirmScrape = useCallback((selectedUrls) => {
    const { sourcesId } = streamRef.current
    if (!sourcesId) return
    // Lock the bubble — disables the checkboxes and hides the buttons.
    patchMessage(sourcesId, { isSelectable: false })
    // Start the terminal bubble where Phase 1/2 output will land.
    const terminalId = `term-${Date.now()}`
    streamRef.current.terminalId = terminalId
    setMessages((prev) => [
      ...prev,
      {
        id: terminalId,
        role: 'agent',
        type: 'terminal',
        lines: [...STEALTH_BANNER],
        outputFiles: [],
        isComplete: false,
      },
    ])
    postRespond(JSON.stringify(selectedUrls))
  }, [patchMessage, postRespond])

  const handleCancelScrape = useCallback(() => {
    const { sourcesId } = streamRef.current
    if (!sourcesId) return
    patchMessage(sourcesId, { isSelectable: false })
    postRespond('skip')
  }, [patchMessage, postRespond])

  // --- Event router -------------------------------------------------------

  const handleEvent = useCallback((event) => {
    const { statusId, sourcesId, terminalId, counters } = streamRef.current

    switch (event.type) {
      case 'session':
        streamRef.current.sessionId = event.session_id
        break

      case 'stage':
        updateLastStep(statusId, { status: 'done' })
        appendStep(statusId, { label: event.message, status: 'running' })
        break

      case 'needs_clarification': {
        // Intent parser decided the message wasn't a real scraping goal.
        // Close the status bubble and respond conversationally instead.
        updateLastStep(statusId, {
          label: 'Need more info',
          status: 'done',
        })
        setMessages((prev) => [
          ...prev,
          { role: 'agent', text: event.question },
        ])
        break
      }

      case 'intent_parsed': {
        const plan = event.plan || {}
        const industry = plan.industry?.canonical || 'something'
        const states = (plan.locations || []).map((l) => l.state).filter(Boolean)
        const locLabel = states.length === 0
          ? ''
          : states.length <= 3
            ? ` in ${states.join(', ')}`
            : ` across ${states.length} states`
        updateLastStep(statusId, {
          label: `Understood: ${industry}${locLabel}`,
          status: 'done',
        })
        break
      }

      case 'discovery_query_done':
        counters.candidateCount = event.total ?? counters.candidateCount
        updateLastStep(statusId, {
          label: `Searching — ${counters.candidateCount} candidates so far...`,
        })
        break

      case 'candidates_found':
        updateLastStep(statusId, {
          label: `Found ${event.count} candidate URLs`,
          status: 'done',
        })
        break

      case 'preflight_result':
        if (event.status === 'rejected') counters.preflightRejected += 1
        else counters.preflightPassed += 1
        updateLastStep(statusId, {
          label: `Qualifying — ${counters.preflightPassed} passed, ${counters.preflightRejected} rejected`,
        })
        break

      case 'preflight_done':
        updateLastStep(statusId, {
          label: `Qualified ${event.passed}, rejected ${event.rejected}`,
          status: 'done',
        })
        break

      case 'classified':
        if (event.classification === 'DIRECTORY') counters.directories += 1
        else if (event.classification === 'WEBSITE') counters.websites += 1
        updateLastStep(statusId, {
          label: `Classifying — ${counters.directories} directories, ${counters.websites} websites`,
        })
        break

      case 'discovery_complete': {
        // Close out the status bubble. If there are 0 directories we won't
        // get a confirmation_required event, so show the result here too.
        updateLastStep(statusId, { status: 'done' })
        const reasons = event.reject_reasons || {}
        const breakdown = Object.entries(reasons)
          .map(([reason, count]) => `${count} ${REJECT_REASONS[reason] || reason}`)
          .join(', ')
        if (breakdown) {
          appendStep(statusId, { label: `Rejected: ${breakdown}`, status: 'done' })
        }

        // If nothing scrapable, show a static sources bubble for any
        // standalone websites that turned up.
        if ((event.directories_count || 0) === 0 && (event.websites_count || 0) > 0) {
          setMessages((prev) => [
            ...prev,
            {
              id: `src-${Date.now()}`,
              role: 'agent',
              type: 'sources',
              directories: [],
              websites: event.websites || [],
              rejectedCount: event.rejected_count || 0,
              isSelectable: false,
            },
          ])
        }
        break
      }

      case 'confirmation_required': {
        // Create the selectable sources bubble — the user picks here.
        const sId = `src-${Date.now()}`
        streamRef.current.sourcesId = sId
        setMessages((prev) => [
          ...prev,
          {
            id: sId,
            role: 'agent',
            type: 'sources',
            directories: event.directories || [],
            websites: event.websites || [],
            rejectedCount: 0, // already shown in status bubble
            isSelectable: true,
            onConfirm: handleConfirmScrape,
            onCancel: handleCancelScrape,
          },
        ])
        break
      }

      case 'confirmation_accepted':
        // Backend acknowledged the selection. Terminal was already created
        // synchronously when the user clicked Scrape, so nothing to do here.
        break

      case 'log': {
        if (!terminalId) break
        const formatted = formatTerminalLine(event.message)
        if (!formatted) break
        appendTerminalLines(terminalId, [{
          text: formatted.text,
          category: formatted.category || event.category || 'LOG',
        }])
        break
      }

      case 'scrape_started':
        if (!terminalId) break
        appendTerminalLines(terminalId, [
          { text: '', category: 'SYSTEM' },
          { text: `━━━ (${event.index + 1}/${event.total}) ${event.url} ━━━`, category: 'SYSTEM' },
        ])
        break

      case 'scrape_done': {
        if (!terminalId) break
        appendTerminalLines(terminalId, [{
          text: `✓ ${event.records} records${event.enriched ? `, ${event.enriched} enriched` : ''} → ${event.output_file}`,
          category: 'CLEAN',
        }])
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== terminalId) return m
            const files = m.outputFiles || []
            if (files.includes(event.output_file)) return m
            return { ...m, outputFiles: [...files, event.output_file] }
          })
        )
        break
      }

      case 'scrape_error':
        if (!terminalId) break
        appendTerminalLines(terminalId, [{
          text: `⚠ Scrape failed for ${event.url}: ${event.error}`,
          category: 'ERROR',
        }])
        break

      case 'complete':
        if (terminalId) {
          patchMessage(terminalId, { isComplete: true })
        }
        setMessages((prev) => [
          ...prev,
          { role: 'agent', type: 'result', result: event },
        ])
        break

      case 'error':
        if (terminalId) {
          appendTerminalLines(terminalId, [{
            text: `⚠ ${event.message}`,
            category: 'ERROR',
          }])
        } else {
          setMessages((prev) => [
            ...prev,
            { role: 'agent', type: 'error', text: event.message },
          ])
        }
        break

      default:
        break
    }
  }, [appendStep, updateLastStep, patchMessage, appendTerminalLines,
      handleConfirmScrape, handleCancelScrape])

  // --- Main send handler --------------------------------------------------

  const handleSend = useCallback(async (text) => {
    if (isRunning) return

    const statusId = `status-${Date.now()}`
    streamRef.current = {
      sessionId: null,
      statusId,
      sourcesId: null,
      terminalId: null,
      counters: {
        candidateCount: 0,
        preflightPassed: 0,
        preflightRejected: 0,
        directories: 0,
        websites: 0,
      },
    }

    setMessages((prev) => [
      ...prev,
      { role: 'user', text },
      { id: statusId, role: 'agent', type: 'status', steps: [] },
    ])
    setIsRunning(true)

    try {
      const resp = await fetch('/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: text, priority_fields: ['email', 'phone'] }),
      })

      if (!resp.ok) {
        setMessages((prev) => [
          ...prev,
          { role: 'agent', type: 'error', text: `Request failed: ${resp.status} ${resp.statusText}` },
        ])
        setIsRunning(false)
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          try {
            const event = JSON.parse(part.slice(6))
            handleEvent(event)
          } catch {
            // ignore malformed SSE frames
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'agent', type: 'error', text: `Connection error: ${err.message}` },
      ])
    } finally {
      setIsRunning(false)
    }
  }, [isRunning, handleEvent])

  return (
    <div className="min-h-screen bg-white pt-20">
      <div className="mx-auto max-w-site px-6 py-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white shadow-sm">
            <Sparkles size={14} />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tighter text-gray-900">Kosmic Agent</h1>
            <p className="text-xs text-gray-400">
              Describe what you want. The agent finds directories; you pick which to scrape.
            </p>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div ref={scrollRef} className="h-[600px] overflow-y-auto px-4 py-5 lg:h-[680px]">
            <div className="flex flex-col gap-4">
              {messages.map((msg, i) => (
                <ChatMessage key={msg.id ?? i} message={msg} />
              ))}
            </div>

            {messages.length <= 1 && !isRunning && (
              <div className="mt-6 space-y-2">
                <p className="text-xs text-gray-300 font-medium">Try asking for:</p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSend(s)}
                      className="rounded-full border border-gray-200 px-3.5 py-1.5 text-xs text-gray-500 transition-all hover:border-accent hover:text-accent hover:bg-accent-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <ChatInput onSend={handleSend} disabled={isRunning} />
        </div>
      </div>
    </div>
  )
}
