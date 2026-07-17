import { createContext, useContext, useState, useRef, useCallback, useEffect } from 'react'
import formatTerminalLine, { STEALTH_BANNER } from '../lib/formatTerminalLine'
import useAnalytics from '../hooks/useAnalytics'

// --- Persistence ----------------------------------------------------------
// The whole point of this provider: the Discover conversation + live scrape
// stream live ABOVE the router, so switching headers doesn't unmount them.
// sessionStorage then restores the transcript across a full page refresh.
const STORE_KEY = 'trawlbase:agent:v1'

const INITIAL_MESSAGE = {
  role: 'agent',
  text: "Tell me what you're looking for — I'll find the right directory, scrape it, and enrich every record for you.",
}

const REJECT_REASONS = {
  login_wall: 'login wall',
  no_directory_signals: 'no directory signals',
  thin_content: 'thin page',
  fetch_failed: 'unreachable',
  no_contact_info: 'no contact info',
}

const INTERRUPTED_NOTE = {
  role: 'agent',
  text: '↻ Restored your session. A scrape was interrupted by the page refresh, so its results may be incomplete — re-run that request if needed.',
}

// Restored bubbles whose backend session is gone can no longer be acted on —
// strip their live affordances so ChatMessage renders them read-only.
function sanitizeRestored(messages) {
  return messages.map((m) => {
    if (m.type === 'sources' && m.isSelectable) return { ...m, isSelectable: false }
    if (m.type === 'scope' && !m.answered) return { ...m, answered: true, chosenLabel: m.chosenLabel || '—' }
    if (m.type === 'terminal' && !m.isComplete) return { ...m, isComplete: true }
    return m
  })
}

function loadInitialState() {
  const fallback = { messages: [INITIAL_MESSAGE], accurate: false }
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.sessionStorage.getItem(STORE_KEY)
    if (!raw) return fallback
    const data = JSON.parse(raw)
    if (!Array.isArray(data.messages) || data.messages.length === 0) return fallback
    const messages = sanitizeRestored(data.messages)
    // If a run was in flight when the page was reloaded, say so honestly.
    if (data.isRunning) messages.push(INTERRUPTED_NOTE)
    return { messages, accurate: !!data.accurate }
  } catch {
    return fallback
  }
}

const AgentContext = createContext(null)

export function useAgent() {
  const ctx = useContext(AgentContext)
  if (!ctx) throw new Error('useAgent must be used within <AgentProvider>')
  return ctx
}

export function AgentProvider({ children }) {
  // Parse sessionStorage exactly once (not on every streamed-message re-render).
  const initial = useRef(undefined)
  if (initial.current === undefined) initial.current = loadInitialState()
  const [messages, setMessages] = useState(initial.current.messages)
  const [isRunning, setIsRunning] = useState(false)
  const [accurateEnrichment, setAccurateEnrichment] = useState(initial.current.accurate)
  // Live View: the current run's session id + whether it paused for a human,
  // plus whether the viewer modal is open (shared so the header button AND the
  // in-chat terminal callout both control the one modal).
  const [liveSessionId, setLiveSessionId] = useState(null)
  const [paused, setPaused] = useState(false)
  const [liveViewOpen, setLiveViewOpen] = useState(false)
  const { trackEvent } = useAnalytics()

  const openLiveView = useCallback(() => setLiveViewOpen(true), [])
  const closeLiveView = useCallback(() => setLiveViewOpen(false), [])

  // Auto-open the viewer on the rising edge of a pause (CAPTCHA / login) so the
  // user doesn't have to hunt for the button while the clock ticks.
  const prevPaused = useRef(false)
  useEffect(() => {
    if (paused && !prevPaused.current) setLiveViewOpen(true)
    prevPaused.current = paused
  }, [paused])

  // Per-stream mutable bag — survives renders without triggering them.
  const streamRef = useRef({
    sessionId: null,
    statusId: null,
    sourcesId: null,
    scopeId: null,
    terminalId: null,
    counters: null,
  })

  // Debounced persistence — coalesces the burst of SSE updates during a scrape.
  const saveTimer = useRef(null)
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      try {
        window.sessionStorage.setItem(
          STORE_KEY,
          JSON.stringify({ messages, isRunning, accurate: accurateEnrichment }),
        )
      } catch {
        // best-effort — quota errors etc. are non-fatal
      }
    }, 400)
    return () => clearTimeout(saveTimer.current)
  }, [messages, isRunning, accurateEnrichment])

  // --- Message updaters ---------------------------------------------------

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
    patchMessage(sourcesId, { isSelectable: false })
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

  const handleScopeChoice = useCallback((token, label) => {
    const { scopeId } = streamRef.current
    if (scopeId) patchMessage(scopeId, { answered: true, chosenLabel: label })
    postRespond(token)
  }, [patchMessage, postRespond])

  // --- Event router -------------------------------------------------------

  const handleEvent = useCallback((event) => {
    const { statusId, sourcesId, terminalId, counters } = streamRef.current

    switch (event.type) {
      case 'session':
        streamRef.current.sessionId = event.session_id
        setLiveSessionId(event.session_id)
        break

      case 'paused':
        // Run paused for a human (CAPTCHA / login). The matching `log` event
        // already printed the message into the terminal bubble; flag the state
        // so the Live View button flashes and its modal auto-opens.
        setPaused(true)
        break

      case 'resumed':
        setPaused(false)
        break

      case 'stage':
        updateLastStep(statusId, { status: 'done' })
        appendStep(statusId, { label: event.message, status: 'running' })
        break

      case 'needs_clarification': {
        streamRef.current.finished = true
        updateLastStep(statusId, { label: 'Need more info', status: 'done' })
        setMessages((prev) => [...prev, { role: 'agent', text: event.question }])
        break
      }

      case 'scope_refinement_required': {
        const sId = `scope-${Date.now()}`
        streamRef.current.scopeId = sId
        setMessages((prev) => [
          ...prev,
          {
            id: sId,
            role: 'agent',
            type: 'scope',
            question: event.question,
            options: event.options || [],
            answered: false,
            onChoose: handleScopeChoice,
          },
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
        updateLastStep(statusId, { status: 'done' })
        const reasons = event.reject_reasons || {}
        const breakdown = Object.entries(reasons)
          .map(([reason, count]) => `${count} ${REJECT_REASONS[reason] || reason}`)
          .join(', ')
        if (breakdown) {
          appendStep(statusId, { label: `Rejected: ${breakdown}`, status: 'done' })
        }
        break
      }

      case 'confirmation_required': {
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
            rejectedCount: 0,
            isSelectable: true,
            onConfirm: handleConfirmScrape,
            onCancel: handleCancelScrape,
          },
        ])
        break
      }

      case 'confirmation_accepted':
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
        streamRef.current.finished = true
        updateLastStep(statusId, { status: 'done' })
        if (terminalId) {
          patchMessage(terminalId, { isComplete: true })
        }
        setMessages((prev) => [...prev, { role: 'agent', type: 'result', result: event }])
        trackEvent('discover_done', {
          records: event.records || 0,
          directories: event.directories_scraped || 0,
          websites: event.websites_found || 0,
          success: event.success || false,
        })
        break

      case 'error':
        streamRef.current.finished = true
        if (terminalId) {
          // Close the terminal too — a crashed run used to leave the cursor
          // blinking forever, which read as "stuck".
          appendTerminalLines(terminalId, [{ text: `⚠ ${event.message}`, category: 'ERROR' }])
          patchMessage(terminalId, { isComplete: true })
        } else {
          setMessages((prev) => [...prev, { role: 'agent', type: 'error', text: event.message }])
        }
        break

      default:
        break
    }
  }, [appendStep, updateLastStep, patchMessage, appendTerminalLines,
      handleConfirmScrape, handleCancelScrape, handleScopeChoice, trackEvent])

  // --- Main send handler --------------------------------------------------

  const handleSend = useCallback(async (text) => {
    if (isRunning) return

    const statusId = `status-${Date.now()}`
    streamRef.current = {
      sessionId: null,
      statusId,
      sourcesId: null,
      scopeId: null,
      terminalId: null,
      finished: false,
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
    setLiveSessionId(null)
    setPaused(false)
    setLiveViewOpen(false)

    trackEvent('discover_started', { goal: text })

    try {
      const resp = await fetch('/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: text,
          priority_fields: ['email', 'phone'],
          accurate_enrichment: accurateEnrichment,
        }),
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

      // Stream closed without a complete / error / clarification event: the
      // connection dropped mid-run. The backend thread keeps going and still
      // writes its files — say so instead of leaving the terminal "stuck".
      if (!streamRef.current.finished) {
        const { statusId: sId, terminalId: tId } = streamRef.current
        updateLastStep(sId, { status: 'done' })
        if (tId) patchMessage(tId, { isComplete: true })
        setMessages((prev) => [
          ...prev,
          {
            role: 'agent',
            type: 'error',
            text: 'Lost the connection to this run. The scrape keeps running on the server and its files are still saved — re-run the same request in a minute and already-scraped sources will be picked up from cache.',
          },
        ])
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'agent', type: 'error', text: `Connection error: ${err.message}` },
      ])
    } finally {
      setIsRunning(false)
    }
  }, [isRunning, handleEvent, accurateEnrichment, trackEvent, updateLastStep, patchMessage])

  // Start a fresh conversation (only allowed when nothing is streaming).
  const newChat = useCallback(() => {
    if (isRunning) return
    streamRef.current = {
      sessionId: null, statusId: null, sourcesId: null,
      scopeId: null, terminalId: null, counters: null,
    }
    setMessages([INITIAL_MESSAGE])
    setLiveSessionId(null)
    setPaused(false)
    setLiveViewOpen(false)
    try { window.sessionStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
  }, [isRunning])

  const value = {
    messages,
    isRunning,
    accurateEnrichment,
    setAccurateEnrichment,
    handleSend,
    newChat,
    liveSessionId,
    paused,
    liveViewOpen,
    openLiveView,
    closeLiveView,
  }

  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
}
