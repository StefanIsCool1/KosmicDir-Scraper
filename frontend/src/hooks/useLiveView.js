import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Live View client. Streams the scraper's browser frames over SSE
 * (/live/stream) and relays the user's input/controls back (/live/input,
 * /live/control). Only runs while `enabled` and a `sessionId` are set — the
 * caller (the Live View modal) mounts it when opened and unmounts to stop.
 *
 * Returns:
 *   frame     data: URL of the latest JPEG (or null before the first frame)
 *   status    'connecting' | 'running' | 'captcha' | 'login' | 'paused' | 'closed'
 *   vendor    anti-bot vendor name when status === 'captcha'
 *   paused    convenience bool — the backend is accepting input right now
 *   sendInput(cmd) / resume() / skip() / requestPause()
 */
export default function useLiveView(sessionId, enabled) {
  const [frame, setFrame] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [vendor, setVendor] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (!enabled || !sessionId) return undefined

    const controller = new AbortController()
    abortRef.current = controller
    let cancelled = false
    setStatus('connecting')
    setFrame(null)

    ;(async () => {
      try {
        const resp = await fetch(`/live/stream?session=${encodeURIComponent(sessionId)}`, {
          signal: controller.signal,
          headers: { Accept: 'text/event-stream' },
        })
        if (!resp.ok || !resp.body) {
          if (!cancelled) setStatus('closed')
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
            let event
            try {
              event = JSON.parse(part.slice(6))
            } catch {
              continue
            }
            if (cancelled) return
            if (event.type === 'frame') {
              setFrame(`data:image/jpeg;base64,${event.data}`)
            } else if (event.type === 'status' || event.type === 'meta') {
              if (event.status) setStatus(event.status)
              setVendor(event.vendor || null)
            }
          }
        }
        if (!cancelled) setStatus('closed')
      } catch {
        if (!cancelled) setStatus('closed')
      }
    })()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [sessionId, enabled])

  const post = useCallback((path, body) => {
    if (!sessionId) return
    fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sessionId, ...body }),
    }).catch(() => {
      /* fire-and-forget */
    })
  }, [sessionId])

  const sendInput = useCallback((cmd) => post('/live/input', { cmd }), [post])
  const resume = useCallback(() => post('/live/control', { action: 'resume' }), [post])
  const skip = useCallback(() => post('/live/control', { action: 'skip' }), [post])
  const requestPause = useCallback(() => post('/live/control', { action: 'pause' }), [post])

  const paused = status === 'captcha' || status === 'login' || status === 'paused'

  return { frame, status, vendor, paused, sendInput, resume, skip, requestPause }
}
