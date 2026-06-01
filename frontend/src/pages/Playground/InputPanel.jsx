import { useState } from 'react'
import { Loader2, Play, Plus, X, Trash2 } from 'lucide-react'

const TASK_TYPES = ['Auto Discover', 'Direct Scrape']

const PRIORITY_FIELDS = [
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'address', label: 'Address' },
  { key: 'description', label: 'Description' },
  { key: 'website', label: 'Website' },
  { key: 'social_media', label: 'Social Media' },
]

const DEFAULT_PRIORITIES = ['email', 'phone']

export default function InputPanel({ onRun, isRunning, currentIndex, totalUrls }) {
  const [urls, setUrls] = useState([''])
  const [taskType, setTaskType] = useState('Auto Discover')
  const [inputValue, setInputValue] = useState('')
  const [priorities, setPriorities] = useState(new Set(DEFAULT_PRIORITIES))
  const [accurateEnrichment, setAccurateEnrichment] = useState(false)

  const togglePriority = (key) => {
    setPriorities((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const addUrl = () => {
    const trimmed = inputValue.trim()
    if (trimmed && !urls.includes(trimmed)) {
      setUrls((prev) => [...prev.filter(Boolean), trimmed])
      setInputValue('')
    }
  }

  const removeUrl = (index) => {
    setUrls((prev) => prev.filter((_, i) => i !== index))
  }

  const clearAll = () => {
    setUrls([])
    setInputValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addUrl()
    }
  }

  const handlePaste = (e) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text')
    const pasted = text
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter((s) => s && s.includes('.'))

    if (pasted.length > 1) {
      setUrls((prev) => {
        const existing = new Set(prev)
        const newUrls = pasted.filter((u) => !existing.has(u))
        return [...prev.filter(Boolean), ...newUrls]
      })
      setInputValue('')
    } else {
      setInputValue(text.trim())
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const allUrls = [...urls.filter(Boolean)]
    const trimmed = inputValue.trim()
    if (trimmed && !allUrls.includes(trimmed)) {
      allUrls.push(trimmed)
    }
    if (allUrls.length === 0) return
    setUrls(allUrls)
    setInputValue('')
    onRun({ urls: allUrls, taskType, priorityFields: [...priorities], accurateEnrichment })
  }

  const activeUrls = urls.filter(Boolean)

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {/* URL input */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-medium text-gray-400">
            Target URLs
            {activeUrls.length > 0 && (
              <span className="ml-1.5 text-accent">({activeUrls.length})</span>
            )}
          </label>
          {activeUrls.length > 1 && (
            <button type="button" onClick={clearAll} className="text-xs text-gray-300 hover:text-red-400 transition-colors flex items-center gap-1">
              <Trash2 size={11} /> Clear all
            </button>
          )}
        </div>

        {activeUrls.length > 0 && (
          <div className="mb-2 flex flex-col gap-1.5 max-h-40 overflow-y-auto">
            {activeUrls.map((url, i) => (
              <div
                key={i}
                className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-mono ${
                  isRunning && i === currentIndex
                    ? 'border-accent bg-accent-50 text-accent'
                    : isRunning && i < (currentIndex ?? -1)
                    ? 'border-green-200 bg-green-50 text-green-600'
                    : 'border-gray-100 text-gray-500'
                }`}
              >
                <span className="flex-1 truncate">{url}</span>
                {!isRunning && (
                  <button type="button" onClick={() => removeUrl(i)} className="text-gray-300 hover:text-red-400 transition-colors shrink-0">
                    <X size={13} />
                  </button>
                )}
                {isRunning && i === currentIndex && (
                  <Loader2 size={12} className="animate-spin text-accent shrink-0" />
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={activeUrls.length === 0 ? 'https://members.example.org' : 'Add another URL...'}
            disabled={isRunning}
            className="block flex-1 rounded-lg border border-gray-200 px-3.5 py-2.5 text-sm text-gray-700 placeholder-gray-300 outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent/20 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={addUrl}
            disabled={isRunning || !inputValue.trim()}
            className="rounded-lg border border-gray-200 px-3 py-2.5 text-gray-400 hover:text-accent hover:border-accent transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Plus size={16} />
          </button>
        </div>
        <p className="mt-1.5 text-[11px] text-gray-300">
          Paste multiple URLs (one per line) or add them one at a time.
        </p>
      </div>

      {/* Task type */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1.5">Task Type</label>
        <div data-tour="playground-task-type" className="flex rounded-lg border border-gray-200 p-0.5">
          {TASK_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setTaskType(type)}
              disabled={isRunning}
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                taskType === type
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              } disabled:opacity-70`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Priority fields */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-2">Priority Fields</label>
        <div className="flex flex-wrap gap-2">
          {PRIORITY_FIELDS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => togglePriority(key)}
              disabled={isRunning}
              className={`rounded-full px-3 py-1 text-xs font-medium border transition-all ${
                priorities.has(key)
                  ? 'border-accent bg-accent-50 text-accent'
                  : 'border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'
              } disabled:opacity-70`}
            >
              {priorities.has(key) && <span className="mr-1">✓</span>}
              {label}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-[11px] text-gray-300">
          The bot will try detail crawl + enrichment to find these fields.
        </p>
      </div>

      {/* Accurate enrichment toggle */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={accurateEnrichment}
            onChange={(e) => setAccurateEnrichment(e.target.checked)}
            disabled={isRunning}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-accent focus:ring-accent disabled:opacity-50"
          />
          <span className="flex-1">
            <span className="block text-sm font-medium text-gray-700">
              More accurate web enrichment
            </span>
            <span className="mt-0.5 block text-[11px] text-amber-600">
              ⚠ WARNING: takes longer — verifies each candidate website by fetching and matching
              phone, email, address, and name against the page.
            </span>
          </span>
        </label>
      </div>

      {/* Run button */}
      <button
        type="submit"
        disabled={isRunning || (activeUrls.length === 0 && !inputValue.trim())}
        className="mt-1 flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-semibold text-white shadow-sm transition-all hover:bg-accent-600 disabled:opacity-70 disabled:cursor-not-allowed"
      >
        {isRunning ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            Scraping {currentIndex !== null ? `(${(currentIndex ?? 0) + 1}/${totalUrls})` : '...'}
          </>
        ) : (
          <>
            <Play size={16} />
            {activeUrls.length > 1 || (activeUrls.length === 1 && inputValue.trim())
              ? `Scrape ${activeUrls.length + (inputValue.trim() ? 1 : 0)} Sites`
              : 'Run Trawlbase'}
          </>
        )}
      </button>
    </form>
  )
}
