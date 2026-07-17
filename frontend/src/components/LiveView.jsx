import { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, X, Play, SkipForward, Hand } from 'lucide-react'
import useLiveView from '../hooks/useLiveView'

// Playwright key names line up with DOM KeyboardEvent.key for these; anything
// else printable is sent as typed text.
const RELAY_KEYS = new Set([
  'Enter', 'Backspace', 'Tab', 'Delete', 'Escape',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
])

const clamp01 = (n) => Math.max(0, Math.min(1, n))

function StatusPill({ status, vendor }) {
  const map = {
    connecting: 'Connecting…',
    running: '● Live — the bot is driving',
    captcha: `⏸ Paused · CAPTCHA${vendor ? ` (${vendor})` : ''}`,
    login: '⏸ Paused · Login wall',
    paused: '⏸ Paused · you have control',
    closed: 'Stream ended',
  }
  const isPaused = status === 'captcha' || status === 'login' || status === 'paused'
  return (
    <span
      className={`select-none whitespace-nowrap border px-2.5 py-1 font-mono text-[11px] ${
        isPaused
          ? 'border-black bg-black text-white'
          : status === 'running'
          ? 'border-hairline text-black'
          : 'border-hairline text-gray-300'
      }`}
    >
      {map[status] || status}
    </span>
  )
}

/**
 * Live View launcher button. Flashes when the run is paused so the user knows
 * a CAPTCHA is waiting. Exported so the Agent header + the in-chat terminal
 * callout can both open the same (context-controlled) modal.
 */
export function LiveViewButton({ paused, onClick, className = '' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Watch the scraper live and take control to solve CAPTCHAs"
      className={`inline-flex items-center gap-1.5 border px-3 py-2 text-xs font-medium transition-colors ${
        paused
          ? 'animate-pulse border-black bg-black text-white'
          : 'border-black bg-white text-black hover:bg-black hover:text-white'
      } ${className}`}
    >
      <Eye size={13} aria-hidden="true" />
      {paused ? 'Solve CAPTCHA — Live View' : 'Live View'}
    </button>
  )
}

/**
 * Live View — a self-contained launcher (button + modal) that streams the
 * scraper's browser and, while a run is paused (CAPTCHA / login / manual
 * take-control), relays the user's clicks, scrolls and keystrokes into the real
 * page so they can solve the challenge or move around, then resume the bot.
 * Used as-is by the Playground. The Agent drives {@link LiveViewModal} directly
 * (open state lives in AgentContext so an in-chat callout can open it too).
 *
 * Props:
 *   sessionId  the running scrape's SSE session id (from the main stream)
 *   running    the scrape is in progress (button only shows while true)
 *   paused     the main stream reported a pause — flashes the button for
 *              attention even before the modal is open
 */
export default function LiveView({ sessionId, running, paused }) {
  const [open, setOpen] = useState(false)

  // Auto-open the modal on the rising edge of a pause (CAPTCHA / login), so the
  // user isn't left hunting for the button while the clock ticks.
  const prevPaused = useRef(false)
  useEffect(() => {
    if (paused && !prevPaused.current && running && sessionId) setOpen(true)
    prevPaused.current = paused
  }, [paused, running, sessionId])

  if (!running || !sessionId) return null

  return (
    <>
      <LiveViewButton paused={paused} onClick={() => setOpen(true)} />
      {open && (
        <LiveViewModal sessionId={sessionId} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

export function LiveViewModal({ sessionId, onClose }) {
  const { frame, status, vendor, paused, sendInput, resume, skip, requestPause } =
    useLiveView(sessionId, true)
  const frameRef = useRef(null)

  const relPos = useCallback((e) => {
    const el = frameRef.current
    if (!el) return null
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) return null
    return {
      x: clamp01((e.clientX - r.left) / r.width),
      y: clamp01((e.clientY - r.top) / r.height),
    }
  }, [])

  const onFrameClick = useCallback((e) => {
    if (!paused) return
    const p = relPos(e)
    if (p) sendInput({ type: 'click', x: p.x, y: p.y, clicks: e.detail > 1 ? 2 : 1 })
  }, [paused, relPos, sendInput])

  const onFrameWheel = useCallback((e) => {
    if (!paused) return
    sendInput({ type: 'wheel', dx: e.deltaX, dy: e.deltaY })
  }, [paused, sendInput])

  const onFrameKeyDown = useCallback((e) => {
    if (!paused) return
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (e.key.length === 1) {
      e.preventDefault()
      sendInput({ type: 'type', text: e.key })
    } else if (RELAY_KEYS.has(e.key)) {
      e.preventDefault()
      sendInput({ type: 'key', key: e.key })
    }
  }, [paused, sendInput])

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-4xl flex-col border border-black bg-white"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-hairline px-4 py-2.5">
          <span className="flex items-center gap-2 font-mono text-xs text-gray-500">
            <Eye size={14} aria-hidden="true" />
            trawlbase — live view
          </span>
          <div className="flex items-center gap-3">
            <StatusPill status={status} vendor={vendor} />
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 transition-colors hover:text-black"
              title="Close (the scrape keeps running)"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Frame */}
        <div className="min-h-0 flex-1 overflow-hidden bg-surface">
          <div
            ref={frameRef}
            tabIndex={0}
            role="application"
            aria-label="Live browser view"
            onMouseDown={(e) => e.currentTarget.focus()}
            onClick={onFrameClick}
            onWheel={onFrameWheel}
            onKeyDown={onFrameKeyDown}
            className={`relative mx-auto aspect-[1440/900] w-full outline-none ${
              paused ? 'cursor-crosshair' : 'cursor-default'
            }`}
          >
            {frame ? (
              <img
                src={frame}
                alt="Live browser frame"
                draggable={false}
                className="block h-full w-full select-none"
              />
            ) : (
              <div className="flex h-full w-full select-none flex-col items-center justify-center gap-2 text-center">
                <span className="h-3.5 w-3.5 animate-pulse bg-black" aria-hidden="true" />
                <p className="font-mono text-xs text-gray-500">
                  {status === 'closed' ? 'Stream ended.' : 'Waiting for the first frame…'}
                </p>
              </div>
            )}

            {/* When the bot is driving, dim the frame and explain that input is
                off until the user takes control. */}
            {!paused && status !== 'closed' && frame && (
              <div className="pointer-events-none absolute inset-0 flex items-end justify-center bg-black/5 pb-3">
                <span className="pointer-events-none select-none bg-white/90 px-3 py-1 font-mono text-[11px] text-gray-500">
                  the bot is driving — take control to click around
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-col gap-3 border-t border-hairline px-4 py-3 sm:flex-row sm:items-center">
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-gray-500">
            {paused ? (
              <>
                <span className="font-semibold text-black">You have control.</span>{' '}
                Click, scroll and type directly on the page — solve the challenge or
                move to another page — then press Resume to hand it back to the bot.
              </>
            ) : status === 'closed' ? (
              'The scrape finished or the connection closed.'
            ) : (
              'Watching the scraper work. Take control to pause it and interact with the page yourself.'
            )}
          </p>
          <div className="flex shrink-0 gap-2">
            {paused ? (
              <>
                <button
                  type="button"
                  onClick={skip}
                  className="inline-flex items-center gap-1.5 border border-hairline bg-white px-3 py-2 text-xs font-medium text-gray-500 transition-colors hover:border-black hover:text-black"
                  title="Give up on this site and move on"
                >
                  <SkipForward size={13} />
                  Skip site
                </button>
                <button
                  type="button"
                  onClick={resume}
                  className="inline-flex items-center gap-1.5 bg-black px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-[#222222]"
                >
                  <Play size={13} />
                  Resume bot
                </button>
              </>
            ) : (
              status !== 'closed' && (
                <button
                  type="button"
                  onClick={requestPause}
                  className="inline-flex items-center gap-1.5 border border-black bg-white px-4 py-2 text-xs font-medium text-black transition-colors hover:bg-black hover:text-white"
                  title="Pause the bot at the next safe point so you can interact"
                >
                  <Hand size={13} />
                  Take control
                </button>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
