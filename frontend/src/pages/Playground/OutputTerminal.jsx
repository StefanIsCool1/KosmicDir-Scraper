import { useRef, useEffect, useState } from 'react'
import { Download, FileJson, FileSpreadsheet } from 'lucide-react'
import { lineStyle } from '../../lib/terminalTheme'

export default function OutputTerminal({
  lines,
  isComplete,
  awaitingInput,
  onInput,
  outputFile,
  detailed,
  onDetailedChange,
  isRunning,
}) {
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
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
    <div data-tour="playground-terminal" className="flex flex-col overflow-hidden border border-hairline bg-white">
      {/* Title bar — output stream + a detailed-output switch. */}
      <div className="flex items-center justify-between border-b border-hairline px-4 py-2.5">
        <span className="flex items-center gap-2 font-mono text-xs text-gray-500">
          <span className="inline-flex gap-1" aria-hidden="true">
            <span className="h-2 w-2 border border-hairline" />
            <span className="h-2 w-2 border border-hairline" />
            <span className="h-2 w-2 border border-hairline" />
          </span>
          trawlbase — output
        </span>
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
      </div>

      {/* Terminal body */}
      <div ref={scrollRef} className="h-[420px] overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed lg:h-[480px]">
        {lines.length === 0 && (
          <p className="select-none text-gray-300">Waiting for input…</p>
        )}
        {lines.map((line, i) => (
          <div key={i} style={lineStyle(line.category)} className="whitespace-pre-wrap">
            {line.text}
            {i === lines.length - 1 && !isComplete && !awaitingInput && line.text && (
              <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-black align-middle" />
            )}
          </div>
        ))}

        {/* Interactive input prompt */}
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
