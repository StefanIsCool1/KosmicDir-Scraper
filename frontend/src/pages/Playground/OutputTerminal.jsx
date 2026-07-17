import { useRef, useEffect, useState, useMemo } from 'react'
import { Download, FileJson, FileSpreadsheet } from 'lucide-react'
import { lineStyle } from '../../lib/terminalTheme'
import { deriveFeed, friendlyPrompt } from '../../lib/simpleFeed'
import LiveView from '../../components/LiveView'

const VIEW_KEY = 'trawlbase_output_view'

// Simple-view feed rows. Monochrome like everything else: hierarchy comes
// from weight and the marker glyph, not color.
const KIND_STYLE = {
  step: { marker: '→', markerCls: 'text-gray-300', textCls: 'text-gray-500' },
  data: { marker: '+', markerCls: 'font-semibold text-black', textCls: 'text-black' },
  ok: { marker: '✓', markerCls: 'text-black', textCls: 'font-medium text-black' },
  warn: { marker: '!', markerCls: 'font-bold text-black', textCls: 'font-medium text-black' },
  error: { marker: '✕', markerCls: 'font-bold text-black', textCls: 'font-semibold text-black' },
  done: { marker: '✓', markerCls: 'font-bold text-black', textCls: 'font-semibold text-black' },
  input: { marker: '↳', markerCls: 'text-gray-300', textCls: 'text-gray-500' },
}

const formatElapsed = (sec) =>
  `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

function PhaseMarker({ status }) {
  if (status === 'error') {
    return (
      <span className="z-10 bg-white font-mono text-[11px] font-bold leading-none text-black">✕</span>
    )
  }
  if (status === 'active') return <span className="z-10 h-[9px] w-[9px] shrink-0 animate-pulse bg-black" />
  if (status === 'done') return <span className="z-10 h-[9px] w-[9px] shrink-0 bg-black" />
  return <span className="z-10 h-[9px] w-[9px] shrink-0 border border-hairline bg-white" />
}

function PhaseRail({ phases, statuses }) {
  return (
    <div className="relative flex flex-col gap-3.5">
      <span aria-hidden="true" className="absolute bottom-2 left-[4px] top-2 w-px bg-hairline" />
      {phases.map((p) => {
        const st = statuses[p.id] || 'pending'
        return (
          <div key={p.id} className="relative flex items-center gap-3">
            <PhaseMarker status={st} />
            <span
              className={`text-[13px] leading-none ${
                st === 'active' || st === 'error'
                  ? 'font-semibold text-black'
                  : st === 'done'
                  ? 'text-gray-500'
                  : 'text-gray-300'
              }`}
            >
              {p.label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="min-w-0 px-3 py-2.5 sm:px-5">
      <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-gray-300">{label}</div>
      <div className="mt-0.5 truncate font-mono text-lg leading-tight tracking-tight text-black tabular-nums sm:text-2xl">
        {value}
      </div>
    </div>
  )
}

function FeedRow({ item }) {
  const s = KIND_STYLE[item.kind] || KIND_STYLE.step
  return (
    <div className="flex animate-fade-in items-baseline gap-3 py-[3px]">
      <span aria-hidden="true" className={`w-4 shrink-0 text-center font-mono text-[13px] ${s.markerCls}`}>
        {s.marker}
      </span>
      <span className={`min-w-0 flex-1 text-[15px] leading-snug ${s.textCls}`}>
        {item.text}
        {item.count > 1 && (
          <span className="ml-2 font-mono text-[11px] text-gray-300">×{item.count}</span>
        )}
      </span>
    </div>
  )
}

function DividerRow({ text }) {
  return (
    <div className="flex animate-fade-in items-center gap-3 pb-1 pt-3">
      <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">
        {text}
      </span>
      <span className="h-px min-w-[24px] flex-1 bg-hairline" />
    </div>
  )
}

export default function OutputTerminal({
  lines,
  isComplete,
  awaitingInput,
  promptMessage = '',
  onInput,
  outputFile,
  detailed,
  onDetailedChange,
  isRunning,
  hasError = false,
  liveSessionId,
  livePaused = false,
}) {
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const [inputValue, setInputValue] = useState('')
  const [view, setView] = useState(() => {
    try {
      return localStorage.getItem(VIEW_KEY) === 'advanced' ? 'advanced' : 'simple'
    } catch {
      return 'simple'
    }
  })

  // Per-run elapsed clock
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(null)
  const wasRunning = useRef(false)

  useEffect(() => {
    if (isRunning && !wasRunning.current) {
      startRef.current = Date.now()
      setElapsed(0)
    }
    wasRunning.current = isRunning
  }, [isRunning])

  useEffect(() => {
    if (!isRunning) return undefined
    const id = setInterval(() => {
      if (startRef.current) setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [isRunning])

  const feed = useMemo(
    () => deriveFeed(lines, { isRunning, isComplete, hasError }),
    [lines, isRunning, isComplete, hasError]
  )

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines, view])

  useEffect(() => {
    if (awaitingInput && view === 'advanced' && inputRef.current) {
      inputRef.current.focus()
    }
  }, [awaitingInput, view])

  const switchView = (v) => {
    setView(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      // private mode — non-critical
    }
  }

  const handleInputSubmit = (e) => {
    e.preventDefault()
    if (onInput && inputValue.trim()) {
      onInput(inputValue.trim())
      setInputValue('')
    }
  }

  const prompt = awaitingInput ? friendlyPrompt(promptMessage) : null
  const { enrich } = feed
  const enrichPct =
    enrich.total > 0 && !isComplete ? Math.min(100, Math.round((enrich.done / enrich.total) * 100)) : null

  return (
    <div data-tour="playground-terminal" className="flex flex-col overflow-hidden border border-hairline bg-white">
      {/* Title bar — output stream + Simple/Advanced view switch. */}
      <div className="flex items-center justify-between gap-3 border-b border-hairline py-2 pl-4 pr-2">
        <span className="flex min-w-0 items-center gap-2 font-mono text-xs text-gray-500">
          <span className="inline-flex gap-1" aria-hidden="true">
            <span className="h-2 w-2 border border-hairline" />
            <span className="h-2 w-2 border border-hairline" />
            <span className="h-2 w-2 border border-hairline" />
          </span>
          <span className="truncate">trawlbase — {view === 'simple' ? 'activity' : 'console'}</span>
        </span>

        <div className="flex shrink-0 items-center gap-3">
          {/* Live View — sits right on the terminal the user is watching, so
              it's obvious mid-run and flashes when a CAPTCHA needs solving.
              Renders nothing unless a real scrape is running. */}
          <LiveView sessionId={liveSessionId} running={isRunning} paused={livePaused} />
          {view === 'advanced' && (
            <label
              className={`flex select-none items-center gap-1.5 font-mono text-[11px] ${
                isRunning ? 'text-gray-300' : 'cursor-pointer text-gray-500 hover:text-black'
              }`}
              title="Show every step the bot takes, not just the highlights"
            >
              <input
                type="checkbox"
                checked={detailed}
                onChange={(e) => onDetailedChange?.(e.target.checked)}
                disabled={isRunning}
                className="h-3 w-3 border-gray-300 disabled:opacity-50"
              />
              detailed
            </label>
          )}
          <div className="flex border border-hairline p-0.5" role="tablist" aria-label="Output view">
            {[
              ['simple', 'Simple'],
              ['advanced', 'Advanced'],
            ].map(([v, label]) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => switchView(v)}
                className={`px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  view === v ? 'bg-black text-white' : 'text-gray-500 hover:text-black'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Body — height tuned so the whole page fits a laptop screen. */}
      <div className="h-[340px] lg:h-[clamp(340px,calc(100vh-560px),600px)]">
        {view === 'simple' ? (
          /* ── Simple: phase rail + live counters + plain-English feed ── */
          <div key="simple" className="flex h-full animate-fade-in flex-col lg:flex-row">
            {lines.length === 0 ? (
              <div className="flex h-full w-full select-none flex-col items-center justify-center gap-1.5 px-6 text-center">
                <span className="font-mono text-2xl text-gray-200" aria-hidden="true">⌖</span>
                <p className="text-sm font-medium text-black">Ready when you are</p>
                <p className="max-w-xs text-xs leading-relaxed text-gray-300">
                  Paste a link above and press Run — progress shows up here in plain English.
                </p>
              </div>
            ) : (
              <>
                <aside className="hidden shrink-0 border-r border-hairline px-5 py-5 lg:block lg:w-[210px]">
                  <PhaseRail phases={feed.visiblePhases} statuses={feed.statuses} />
                </aside>

                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                  {/* Mobile phase strip */}
                  <div className="flex gap-1.5 overflow-x-auto border-b border-hairline px-4 py-2 lg:hidden">
                    {feed.visiblePhases.map((p) => {
                      const st = feed.statuses[p.id] || 'pending'
                      return (
                        <span
                          key={p.id}
                          className={`whitespace-nowrap border px-2 py-0.5 text-[11px] font-medium ${
                            st === 'active' || st === 'error'
                              ? 'border-black text-black'
                              : st === 'done'
                              ? 'border-hairline text-gray-500'
                              : 'border-hairline text-gray-300'
                          }`}
                        >
                          {p.label}
                        </span>
                      )
                    })}
                  </div>

                  {/* Live counters */}
                  <div className="grid shrink-0 grid-cols-3 divide-x divide-hairline border-b border-hairline">
                    <Stat
                      label={isComplete && !hasError ? 'Records ready' : 'Records found'}
                      value={feed.records > 0 ? feed.records.toLocaleString() : '—'}
                    />
                    {enrich.total > 0 ? (
                      <Stat label="Websites checked" value={`${enrich.done}/${enrich.total}`} />
                    ) : (
                      <Stat label="Pages" value={feed.pages > 0 ? feed.pages : '—'} />
                    )}
                    <Stat label="Time" value={formatElapsed(elapsed)} />
                  </div>
                  {enrichPct != null && (
                    <div className="h-[3px] w-full shrink-0 bg-hairline">
                      <div
                        className="h-full bg-black transition-[width] duration-500 ease-out"
                        style={{ width: `${enrichPct}%` }}
                      />
                    </div>
                  )}

                  {/* Activity feed */}
                  <div ref={scrollRef} aria-live="polite" className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-5">
                    {feed.items.map((item) =>
                      item.kind === 'divider' ? (
                        <DividerRow key={item.key} text={item.text} />
                      ) : (
                        <FeedRow key={item.key} item={item} />
                      )
                    )}

                    {isRunning && enrich.total > 0 && enrich.done < enrich.total && (
                      <div className="flex items-baseline gap-3 py-[3px]">
                        <span aria-hidden="true" className="w-4 shrink-0 text-center font-mono text-[13px] font-semibold text-black">+</span>
                        <span className="min-w-0 flex-1 truncate text-[15px] leading-snug text-black">
                          Checking websites — {enrich.done} of {enrich.total}
                          {enrich.last && <span className="text-gray-500"> · latest: {enrich.last}</span>}
                        </span>
                      </div>
                    )}

                    {isRunning && !awaitingInput && (
                      <div className="flex items-center gap-3 py-[3px]">
                        <span className="flex w-4 shrink-0 justify-center" aria-hidden="true">
                          <span className="h-3.5 w-[7px] animate-pulse bg-black" />
                        </span>
                        <span className="text-[15px] text-gray-300">{feed.activeLabel || 'Working'}…</span>
                      </div>
                    )}

                    {isComplete && feed.coverage && (
                      <div className="mt-2 flex flex-wrap gap-1.5 pl-7">
                        {feed.coverage.map((c) => (
                          <span key={c.field} className="border border-hairline px-2 py-1 font-mono text-[11px] text-gray-500">
                            {c.field} <span className="text-black">{c.have}</span>/{c.total}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        ) : (
          /* ── Advanced: the raw console, untranslated ── */
          <div
            key="advanced"
            ref={scrollRef}
            className="h-full animate-fade-in overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed"
          >
            {lines.length === 0 && <p className="select-none text-gray-300">Waiting for input…</p>}
            {lines.map((line, i) => (
              <div key={i} style={lineStyle(line.category)} className="whitespace-pre-wrap">
                {line.text}
                {i === lines.length - 1 && !isComplete && !awaitingInput && line.text && (
                  <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-black align-middle" />
                )}
              </div>
            ))}

            {awaitingInput && (
              <form onSubmit={handleInputSubmit} className="mt-1 flex items-center gap-1">
                <span className="text-black">&gt;</span>
                <input
                  ref={inputRef}
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="y/n"
                  className="flex-1 bg-transparent font-mono text-xs text-black outline-none placeholder-gray-300"
                />
              </form>
            )}
          </div>
        )}
      </div>

      {/* Simple-view prompt — the backend question as buttons, no typing. */}
      {awaitingInput && view === 'simple' && prompt && (
        <div className="animate-fade-in border-t border-black bg-surface px-4 py-3.5 sm:px-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-snug text-black">{prompt.question}</p>
              {prompt.hint && <p className="mt-0.5 text-xs leading-relaxed text-gray-500">{prompt.hint}</p>}
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={() => onInput?.('y')}
                className="bg-black px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#222222]"
              >
                {prompt.yes}
              </button>
              <button
                type="button"
                onClick={() => onInput?.('n')}
                className="border border-hairline bg-white px-4 py-2 text-sm font-medium text-gray-500 transition-colors hover:border-black hover:text-black"
              >
                {prompt.no}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Download bar */}
      {isComplete && outputFile && (
        <div className="flex items-center gap-3 border-t border-hairline px-4 py-3">
          <Download size={14} className="text-gray-500" aria-hidden="true" />
          <span className="mr-auto truncate font-mono text-xs text-gray-500">{outputFile}</span>
          <a
            href={`/download/${outputFile}?format=json`}
            download
            className="inline-flex items-center gap-1.5 border border-black px-3 py-1.5 text-xs font-medium text-black transition-colors hover:bg-black hover:text-white"
          >
            <FileJson size={13} aria-hidden="true" />
            JSON
          </a>
          <a
            href={`/download/${outputFile}?format=csv`}
            download
            className="inline-flex items-center gap-1.5 bg-black px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[#222222]"
          >
            <FileSpreadsheet size={13} aria-hidden="true" />
            CSV
          </a>
        </div>
      )}
    </div>
  )
}
