import { useState, useRef, useCallback } from 'react'
import formatTerminalLine, { STEALTH_BANNER } from '../lib/formatTerminalLine'

/**
 * SSE streaming hook for Flask backend integration.
 * Handles /scrape/single (Phase 1) and /phase2/enrich (Phase 2) endpoints.
 */
export default function useSSE() {
  const [lines, setLines] = useState([])
  const [status, setStatus] = useState(null) // null | 'running' | 'done' | 'error'
  const [sessionId, setSessionId] = useState(null)
  const [awaitingInput, setAwaitingInput] = useState(false)
  const [promptMessage, setPromptMessage] = useState('')
  const [result, setResult] = useState(null)
  const readerRef = useRef(null)

  const reset = useCallback(() => {
    setLines([])
    setStatus(null)
    setSessionId(null)
    setAwaitingInput(false)
    setPromptMessage('')
    setResult(null)
  }, [])

  const startScrape = useCallback(async (url, { mode = 'auto', debug = false, append = false, priorityFields, accurateEnrichment = false, goal = '' } = {}) => {
    if (!append) {
      reset()
      // Inject stealth banner at the start of every scrape
      setLines([...STEALTH_BANNER])
    } else {
      // Multi-scrape: add separator then stealth banner
      setLines((prev) => [
        ...prev,
        { text: '', category: 'SYSTEM' },
        { text: `━━━ ${url} ━━━`, category: 'SYSTEM' },
        ...STEALTH_BANNER,
      ])
    }
    setStatus('running')

    try {
      const resp = await fetch('/scrape/single', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link: url, mode, debug, priority_fields: priorityFields, accurate_enrichment: accurateEnrichment, goal }),
      })

      if (!resp.ok) {
        setStatus('error')
        setLines((prev) => [...prev, { text: `Error: ${resp.status} ${resp.statusText}`, category: 'ERROR' }])
        return
      }

      const reader = resp.body.getReader()
      readerRef.current = reader
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

            if (event.type === 'session') {
              setSessionId(event.session_id)
            } else if (event.type === 'log') {
              const formatted = formatTerminalLine(event.message)
              if (formatted) {
                setLines((prev) => [...prev, { text: formatted.text, category: formatted.category || event.category || 'LOG' }])
              }
            } else if (event.type === 'prompt') {
              setAwaitingInput(true)
              setPromptMessage(event.message)
              setLines((prev) => [...prev, { text: event.message, category: 'SYSTEM' }])
            } else if (event.type === 'complete') {
              setResult(event)
              setStatus('done')
              const enrichMsg = event.enriched ? ` (${event.enriched} enriched)` : ''
              const newLines = [
                { text: `✓ Complete — ${event.records} records scraped${enrichMsg}`, category: 'SYSTEM' },
              ]
              if (event.field_coverage) {
                const parts = Object.entries(event.field_coverage)
                  .map(([field, count]) => `${field}: ${count}/${event.records}`)
                  .join(', ')
                newLines.push({ text: `  Field coverage: ${parts}`, category: 'SYSTEM' })
              }
              setLines((prev) => [...prev, ...newLines])
            } else if (event.type === 'error') {
              setStatus('error')
              setLines((prev) => [...prev, { text: `Error: ${event.message}`, category: 'ERROR' }])
            }
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err) {
      setStatus('error')
      setLines((prev) => [...prev, { text: `Connection error: ${err.message}`, category: 'ERROR' }])
    }
  }, [reset])

  const startEnrich = useCallback(async (jsonFile) => {
    reset()
    setStatus('running')

    try {
      const resp = await fetch('/phase2/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ json_file: jsonFile }),
      })

      if (!resp.ok) {
        setStatus('error')
        setLines((prev) => [...prev, { text: `Error: ${resp.status} ${resp.statusText}`, category: 'ERROR' }])
        return
      }

      const reader = resp.body.getReader()
      readerRef.current = reader
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

            if (event.type === 'session') {
              setSessionId(event.session_id)
            } else if (event.type === 'log') {
              const formatted = formatTerminalLine(event.message)
              if (formatted) {
                setLines((prev) => [...prev, { text: formatted.text, category: formatted.category || event.category || 'LOG' }])
              }
            } else if (event.type === 'complete') {
              setResult(event)
              setStatus('done')
              setLines((prev) => [
                ...prev,
                { text: `✓ Done — ${event.enriched}/${event.records} records enriched → ${event.output_file}`, category: 'SYSTEM' },
              ])
            } else if (event.type === 'error') {
              setStatus('error')
              setLines((prev) => [...prev, { text: `Error: ${event.message}`, category: 'ERROR' }])
            }
          } catch {
            // skip malformed events
          }
        }
      }
    } catch (err) {
      setStatus('error')
      setLines((prev) => [...prev, { text: `Connection error: ${err.message}`, category: 'ERROR' }])
    }
  }, [reset])

  const sendInput = useCallback(async (value) => {
    if (!sessionId) return
    setAwaitingInput(false)
    setLines((prev) => [...prev, { text: `> ${value}`, category: 'INPUT' }])

    try {
      await fetch('/scrape/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, value }),
      })
    } catch {
      // non-critical
    }
  }, [sessionId])

  return {
    lines,
    status,
    sessionId,
    awaitingInput,
    promptMessage,
    result,
    startScrape,
    startEnrich,
    sendInput,
    reset,
  }
}
