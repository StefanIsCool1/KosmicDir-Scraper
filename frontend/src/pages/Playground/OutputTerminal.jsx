import { useRef, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Download, FileJson, FileSpreadsheet } from 'lucide-react'
import { MOCK_RESULTS_JSON } from '../../lib/mockData'

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
  LOG: '#555',
  SYSTEM: '#999',
  ERROR: '#DC2626',
}

export default function OutputTerminal({ lines, isComplete, awaitingInput, onInput, outputFile }) {
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const [showResults, setShowResults] = useState(false)
  const [inputValue, setInputValue] = useState('')

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines])

  useEffect(() => {
    if (awaitingInput && inputRef.current) {
      inputRef.current.focus()
    }
  }, [awaitingInput])

  const handleInputSubmit = (e) => {
    e.preventDefault()
    if (onInput && inputValue.trim()) {
      onInput(inputValue.trim())
      setInputValue('')
    }
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-gray-200 bg-[#FAFAFA]">
      {/* Title bar */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="h-2.5 w-2.5 rounded-full bg-gray-300" />
          <div className="h-2.5 w-2.5 rounded-full bg-gray-300" />
          <div className="h-2.5 w-2.5 rounded-full bg-gray-300" />
          <span className="ml-2 text-xs text-gray-400 font-mono">kosmic@scraper ~ output</span>
        </div>
      </div>

      {/* Terminal body */}
      <div ref={scrollRef} className="h-[460px] overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed lg:h-[540px]">
        {lines.length === 0 && lines.length === 0 && (
          <p className="text-gray-300 select-none">Waiting for input...</p>
        )}
        {lines.map((line, i) => (
          <div
            key={i}
            style={{ color: CAT_COLORS[line.category] || '#555' }}
            className="whitespace-pre-wrap"
          >
            {line.text}
            {i === lines.length - 1 && !isComplete && !awaitingInput && line.text && (
              <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-accent align-middle" />
            )}
          </div>
        ))}

        {/* Interactive input prompt */}
        {awaitingInput && (
          <form onSubmit={handleInputSubmit} className="mt-1 flex items-center gap-1">
            <span className="text-accent">&gt;</span>
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="y/n"
              className="flex-1 bg-transparent text-xs text-gray-900 outline-none placeholder-gray-300 font-mono"
            />
          </form>
        )}
      </div>

      {/* Download bar */}
      {isComplete && outputFile && (
        <div className="flex items-center gap-3 border-t border-gray-200 px-4 py-3">
          <Download size={14} className="text-gray-400" />
          <span className="text-xs text-gray-500 mr-auto font-mono truncate">{outputFile}</span>
          <a
            href={`/download/${outputFile}?format=json`}
            download
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <FileJson size={13} />
            JSON
          </a>
          <a
            href={`/download/${outputFile}?format=csv`}
            download
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 transition-colors"
          >
            <FileSpreadsheet size={13} />
            CSV
          </a>
        </div>
      )}
    </div>
  )
}
