import { useState, useRef, useEffect } from 'react'
import {
  Sparkles, User, CheckCircle2, Loader2, XCircle,
  FileJson, FileSpreadsheet, Download,
  Folder, Globe, ChevronDown, ChevronRight,
} from 'lucide-react'

// Category → color mapping. Mirrors the Playground OutputTerminal so the
// Agent's embedded terminal feels visually consistent with the rest of the app.
const CAT_COLORS = {
  INPUT: '#111',
  BROWSER: '#6C5CE7',
  NAV: '#2563EB',
  SEARCH: '#0891B2',
  SCROLL: '#7C3AED',
  CAPTURE: '#16A34A',
  PARSE: '#6C5CE7',
  DETAIL: '#059669',
  CLEAN: '#D97706',
  LOG: '#9CA3AF',
  SYSTEM: '#6B7280',
  ERROR: '#DC2626',
}


function AgentAvatar() {
  return (
    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-100 text-accent">
      <Sparkles size={13} />
    </div>
  )
}


function StatusStep({ step }) {
  let Icon = Loader2
  let iconClass = 'text-gray-400 animate-spin'
  if (step.status === 'done') {
    Icon = CheckCircle2
    iconClass = 'text-accent'
  } else if (step.status === 'error') {
    Icon = XCircle
    iconClass = 'text-red-500'
  }
  return (
    <div className="flex items-start gap-2 text-xs leading-relaxed">
      <Icon size={13} className={`mt-0.5 shrink-0 ${iconClass}`} />
      <span className={step.status === 'error' ? 'text-red-600' : 'text-gray-600'}>
        {step.label}
      </span>
    </div>
  )
}


function StatusBubble({ steps }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-2xl rounded-tl-md bg-gray-50 border border-gray-100 px-4 py-3 max-w-[80%]">
      {steps.length === 0 ? (
        <span className="text-xs text-gray-400">Thinking...</span>
      ) : (
        steps.map((s, i) => <StatusStep key={i} step={s} />)
      )}
    </div>
  )
}


function SelectableDirectoryList({ items, selected, onToggle, locked }) {
  if (!items || items.length === 0) return null
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden">
      <div className="flex items-center gap-2 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-700">
        <Folder size={13} className="text-accent" />
        <span>Directories</span>
        <span className="ml-auto rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
          {items.filter((it) => selected.has(it.url)).length}/{items.length}
        </span>
      </div>
      <div className="max-h-52 overflow-y-auto px-2 py-1 flex flex-col">
        {items.map((it, i) => {
          const isSelected = selected.has(it.url)
          return (
            <label
              key={i}
              className={`flex items-start gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                locked ? 'cursor-default' : 'hover:bg-gray-50'
              }`}
            >
              <input
                type="checkbox"
                className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 text-accent focus:ring-1 focus:ring-accent/30 disabled:opacity-50"
                checked={isSelected}
                disabled={locked}
                onChange={() => onToggle(it.url)}
              />
              <div className="min-w-0 flex-1">
                {it.title && (
                  <div className={`text-[11px] truncate ${isSelected ? 'text-gray-700' : 'text-gray-400'}`}>
                    {it.title}
                  </div>
                )}
                <a
                  href={it.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`block text-[10px] truncate font-mono ${
                    isSelected ? 'text-gray-500 hover:text-accent' : 'text-gray-300 hover:text-gray-400'
                  }`}
                  onClick={(e) => e.stopPropagation()}
                >
                  {it.url}
                </a>
              </div>
            </label>
          )
        })}
      </div>
    </div>
  )
}


function WebsiteList({ items, selected, onToggle, locked }) {
  // Standalone single-business sites. Selectable (checkboxes) like the
  // directory list, but DEFAULT-UNSELECTED — they're optional extras the
  // user opts into. Starts expanded so the checkboxes are visible.
  const [open, setOpen] = useState(true)
  if (!items || items.length === 0) return null
  const selCount = items.filter((it) => selected?.has(it.url)).length
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-100 transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Globe size={13} className="text-accent" />
        <span>Standalone sites</span>
        <span className="ml-auto rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
          {selCount}/{items.length}
        </span>
      </button>
      {open && (
        <div className="max-h-44 overflow-y-auto px-2 py-1 flex flex-col">
          {items.map((it, i) => {
            const isSelected = selected?.has(it.url)
            return (
              <label
                key={i}
                className={`flex items-start gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                  locked ? 'cursor-default' : 'hover:bg-gray-50'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 h-3.5 w-3.5 rounded border-gray-300 text-accent focus:ring-1 focus:ring-accent/30 disabled:opacity-50"
                  checked={!!isSelected}
                  disabled={locked}
                  onChange={() => onToggle && onToggle(it.url)}
                />
                <div className="min-w-0 flex-1">
                  {it.title && (
                    <div className={`text-[11px] truncate ${isSelected ? 'text-gray-700' : 'text-gray-400'}`}>
                      {it.title}
                    </div>
                  )}
                  <a
                    href={it.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`block text-[10px] truncate font-mono ${
                      isSelected ? 'text-gray-500 hover:text-accent' : 'text-gray-300 hover:text-gray-400'
                    }`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {it.url}
                  </a>
                </div>
              </label>
            )
          })}
        </div>
      )}
    </div>
  )
}


function SourcesBubble({
  directories = [],
  websites = [],
  rejectedCount = 0,
  isSelectable = false,
  onConfirm,
  onCancel,
}) {
  const [selected, setSelected] = useState(
    () => new Set(directories.map((d) => d.url))
  )

  const toggle = (url) => {
    if (!isSelectable) return
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  const dCount = directories.length
  const wCount = websites.length
  const hasAny = dCount > 0 || wCount > 0
  const selectedCount = selected.size

  return (
    <div className="flex flex-col gap-2.5 rounded-2xl rounded-tl-md bg-gray-50 border border-gray-100 px-4 py-3 max-w-[85%]">
      <div className="text-sm text-gray-700">
        {hasAny
          ? <>I found{' '}
            {dCount > 0 && <><span className="font-semibold text-gray-900">{dCount}</span> {dCount === 1 ? 'directory' : 'directories'}</>}
            {dCount > 0 && wCount > 0 && <> and </>}
            {wCount > 0 && <><span className="font-semibold text-gray-900">{wCount}</span> standalone {wCount === 1 ? 'site' : 'sites'}</>}.
            {isSelectable && <> Pick which to scrape:</>}
            </>
          : "I couldn't find any usable sources for that goal."}
        {rejectedCount > 0 && (
          <span className="text-gray-400"> {rejectedCount} candidate{rejectedCount === 1 ? '' : 's'} rejected.</span>
        )}
      </div>

      <SelectableDirectoryList
        items={directories}
        selected={selected}
        onToggle={toggle}
        locked={!isSelectable}
      />
      <WebsiteList
        items={websites}
        selected={selected}
        onToggle={toggle}
        locked={!isSelectable}
      />

      {isSelectable && wCount > 0 && (
        <p className="text-[11px] text-gray-400 -mt-1">
          Standalone sites are optional — tick any you want scraped &amp; enriched.
        </p>
      )}

      {isSelectable && hasAny && (
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => onConfirm && onConfirm([...selected])}
            disabled={selectedCount === 0}
            className="flex-1 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Scrape selected ({selectedCount})
          </button>
          <button
            onClick={() => onCancel && onCancel()}
            className="rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-white transition-colors"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}


function ScopeBubble({ question, options = [], answered = false, chosenLabel, onChoose }) {
  // options[0] = specialists-only label, options[1] = anyone-who-does-it label.
  const specialistLabel = options[0] || 'Specialists only'
  const inclusiveLabel = options[1] || 'Anyone who does it'

  return (
    <div className="flex flex-col gap-2.5 rounded-2xl rounded-tl-md bg-gray-50 border border-gray-100 px-4 py-3 max-w-[85%]">
      <div className="text-sm text-gray-700">{question}</div>
      {answered ? (
        <div className="text-xs text-gray-500">
          You chose: <span className="font-semibold text-gray-900">{chosenLabel}</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 pt-0.5">
          <button
            onClick={() => onChoose && onChoose('specialist', specialistLabel)}
            className="flex-1 rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-600 transition-colors"
          >
            {specialistLabel}
          </button>
          <button
            onClick={() => onChoose && onChoose('inclusive', inclusiveLabel)}
            className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-white transition-colors"
          >
            {inclusiveLabel}
          </button>
        </div>
      )}
    </div>
  )
}


function TerminalBubble({ lines = [], isComplete = false, outputFiles = [] }) {
  const scrollRef = useRef(null)
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines])

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-[#FAFAFA] max-w-[85%]">
      {/* Title bar — matches Playground OutputTerminal styling */}
      <div className="flex items-center justify-between border-b border-gray-200 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-gray-300" />
          <div className="h-2 w-2 rounded-full bg-gray-300" />
          <div className="h-2 w-2 rounded-full bg-gray-300" />
          <span className="ml-2 text-[11px] text-gray-400 font-mono">trawlbase ~ scraping</span>
        </div>
        {isComplete && (
          <span className="text-[10px] text-accent font-mono">done</span>
        )}
      </div>

      {/* Body */}
      <div ref={scrollRef} className="h-[320px] overflow-y-auto px-3 py-2 font-mono text-[11px] leading-relaxed">
        {lines.length === 0 ? (
          <p className="text-gray-300 select-none">Waiting for output...</p>
        ) : (
          lines.map((line, i) => (
            <div
              key={i}
              style={{ color: CAT_COLORS[line.category] || '#6B7280' }}
              className="whitespace-pre-wrap"
            >
              {line.text}
              {i === lines.length - 1 && !isComplete && line.text && (
                <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-accent align-middle" />
              )}
            </div>
          ))
        )}
      </div>

      {/* Download bar — appears when files exist (one row per file) */}
      {outputFiles.length > 0 && (
        <div className="border-t border-gray-200 px-3 py-2 flex flex-col gap-1.5">
          {outputFiles.map((file) => (
            <div key={file} className="flex items-center gap-2">
              <Download size={11} className="text-gray-400 shrink-0" />
              <span className="flex-1 truncate text-[11px] text-gray-500 font-mono">{file}</span>
              <a
                href={`/download/${file}?format=json`}
                download
                className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-0.5 text-[10px] text-gray-600 hover:bg-white"
              >
                <FileJson size={10} /> JSON
              </a>
              <a
                href={`/download/${file}?format=csv`}
                download
                className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-0.5 text-[10px] text-white hover:bg-accent-600"
              >
                <FileSpreadsheet size={10} /> CSV
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


function ResultBubble({ result }) {
  const {
    records = 0,
    directories_scraped = 0,
    per_site = [],
    stats = {},
  } = result
  const rejected = stats.rejected_count || 0
  const totalEnriched = per_site.reduce((acc, s) => acc + (s.enriched || 0), 0)

  return (
    <div className="flex flex-col gap-1.5 rounded-2xl rounded-tl-md bg-accent-50/40 border border-accent-100 px-4 py-3 max-w-[80%]">
      <div className="text-sm font-medium text-gray-900">
        {records > 0
          ? `Done — ${records.toLocaleString()} record${records === 1 ? '' : 's'}${directories_scraped > 0 ? ` across ${directories_scraped} ${directories_scraped === 1 ? 'directory' : 'directories'}` : ''}.`
          : 'Done. No records extracted.'}
      </div>
      {totalEnriched > 0 && (
        <div className="text-xs text-gray-600">
          {totalEnriched.toLocaleString()} record{totalEnriched === 1 ? '' : 's'} enriched via Phase 2.
        </div>
      )}
      {rejected > 0 && (
        <div className="text-[11px] text-gray-400">
          {rejected} candidate{rejected === 1 ? '' : 's'} rejected during discovery.
        </div>
      )}
    </div>
  )
}


export default function ChatMessage({ message }) {
  const isUser = message.role === 'user'

  if (message.type === 'status') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <AgentAvatar />
        <StatusBubble steps={message.steps || []} />
      </div>
    )
  }

  if (message.type === 'sources') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <AgentAvatar />
        <SourcesBubble
          directories={message.directories}
          websites={message.websites}
          rejectedCount={message.rejectedCount}
          isSelectable={message.isSelectable}
          onConfirm={message.onConfirm}
          onCancel={message.onCancel}
        />
      </div>
    )
  }

  if (message.type === 'scope') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <AgentAvatar />
        <ScopeBubble
          question={message.question}
          options={message.options}
          answered={message.answered}
          chosenLabel={message.chosenLabel}
          onChoose={message.onChoose}
        />
      </div>
    )
  }

  if (message.type === 'terminal') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <AgentAvatar />
        <TerminalBubble
          lines={message.lines || []}
          isComplete={message.isComplete}
          outputFiles={message.outputFiles || []}
        />
      </div>
    )
  }

  if (message.type === 'result') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <AgentAvatar />
        <ResultBubble result={message.result} />
      </div>
    )
  }

  if (message.type === 'error') {
    return (
      <div className="flex gap-3 animate-fade-in" style={{ animationDelay: '0.05s' }}>
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-50 text-red-500">
          <XCircle size={13} />
        </div>
        <div className="max-w-[80%] rounded-2xl rounded-tl-md bg-red-50 border border-red-100 px-4 py-2.5 text-sm leading-relaxed text-red-700">
          {message.text}
        </div>
      </div>
    )
  }

  // Plain text bubble (user input or agent welcome message)
  return (
    <div
      className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-fade-in`}
      style={{ animationDelay: '0.05s' }}
    >
      <div
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
          isUser ? 'bg-accent text-white' : 'bg-gray-100 text-accent'
        }`}
      >
        {isUser ? <User size={13} /> : <Sparkles size={13} />}
      </div>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-accent text-white rounded-tr-md'
            : 'bg-gray-100 text-gray-700 rounded-tl-md'
        }`}
      >
        {message.text}
      </div>
    </div>
  )
}
