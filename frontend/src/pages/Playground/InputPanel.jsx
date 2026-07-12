import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, ArrowRight, Plus, X, Trash2, ChevronRight } from 'lucide-react'
import { EASE } from '../../lib/motion'

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

const PLACEHOLDER_URLS = [
  'https://en.wikipedia.org/wiki/Web_scraping',
  'https://www.chamberofcommerce.com/directory',
  'https://members.hoa-usa.com/washington',
  'https://example.com/business-directory',
]

const PLACEHOLDER_TYPE_SPEED = 55   // ms per character
const PLACEHOLDER_PAUSE = 2200      // pause after fully typed before cycling

export default function InputPanel({ onRun, isRunning, currentIndex, totalUrls }) {
  const [urls, setUrls] = useState([])
  const [taskType, setTaskType] = useState('Auto Discover')
  const [inputValue, setInputValue] = useState('')
  const [goal, setGoal] = useState('')
  const [priorities, setPriorities] = useState(new Set(DEFAULT_PRIORITIES))
  const [accurateEnrichment, setAccurateEnrichment] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [placeholderText, setPlaceholderText] = useState('')

  const isAuto = taskType === 'Auto Discover'

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

  const removeUrl = (index) => setUrls((prev) => prev.filter((_, i) => i !== index))

  const clearAll = () => {
    setUrls([])
    setInputValue('')
  }

  const handleUrlKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handlePaste = (e) => {
    const text = e.clipboardData.getData('text')
    const pasted = text
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter((s) => s && s.includes('.'))

    if (pasted.length > 1) {
      e.preventDefault()
      setUrls((prev) => {
        const existing = new Set(prev)
        const newUrls = pasted.filter((u) => !existing.has(u))
        return [...prev.filter(Boolean), ...newUrls]
      })
      setInputValue('')
    }
  }

  const handleSubmit = (e) => {
    if (e) e.preventDefault()
    const allUrls = [...urls.filter(Boolean)]
    const trimmed = inputValue.trim()
    if (trimmed && !allUrls.includes(trimmed)) allUrls.push(trimmed)
    if (allUrls.length === 0) return
    setUrls(allUrls)
    setInputValue('')
    onRun({
      urls: allUrls,
      taskType,
      priorityFields: [...priorities],
      accurateEnrichment,
      goal: isAuto ? goal.trim() : '',
    })
  }

  const activeUrls = urls.filter(Boolean)
  const canRun = !isRunning && (activeUrls.length > 0 || inputValue.trim())
  const queued = activeUrls.length + (inputValue.trim() && !activeUrls.includes(inputValue.trim()) ? 1 : 0)

  // ── Live-typing placeholder: cycles through example URLs ──
  const shouldAnimate = !isFocused && !inputValue.trim() && activeUrls.length === 0

  useEffect(() => {
    if (!shouldAnimate) {
      setPlaceholderText('')
      return
    }

    let urlIdx = 0
    let charIdx = 0
    let timeout

    const type = () => {
      const url = PLACEHOLDER_URLS[urlIdx]
      if (charIdx <= url.length) {
        setPlaceholderText(url.slice(0, charIdx))
        charIdx++
        timeout = setTimeout(type, PLACEHOLDER_TYPE_SPEED)
      } else {
        timeout = setTimeout(() => {
          charIdx = 0
          urlIdx = (urlIdx + 1) % PLACEHOLDER_URLS.length
          type()
        }, PLACEHOLDER_PAUSE)
      }
    }

    type()
    return () => clearTimeout(timeout)
  }, [shouldAnimate])

  return (
    <form onSubmit={handleSubmit} className="flex flex-col items-stretch">
      {/* ── The bar. One line: paste a directory URL, press run. ── */}
      <div
        className={`flex items-stretch border transition-colors ${
          isRunning ? 'border-hairline' : 'border-black'
        }`}
      >
        <div className="flex select-none items-center pl-4 pr-3 font-mono text-sm text-gray-300">
          {isAuto ? '⌖' : '↳'}
        </div>
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleUrlKeyDown}
          onPaste={handlePaste}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={activeUrls.length > 0 ? 'Add another URL…' : placeholderText}
          disabled={isRunning}
          autoFocus
          className="min-w-0 flex-1 bg-transparent py-4 pr-3 font-mono text-base text-black placeholder-gray-300 outline-none disabled:opacity-50"
        />
        {inputValue.trim() && !isRunning && (
          <button
            type="button"
            onClick={addUrl}
            title="Add another URL"
            className="border-l border-hairline px-3 text-gray-400 transition-colors hover:text-black"
          >
            <Plus size={16} />
          </button>
        )}
        <button
          type="submit"
          disabled={!canRun}
          className="flex items-center gap-2 bg-black px-5 text-sm font-medium text-white transition-colors hover:bg-[#222222] disabled:cursor-not-allowed disabled:opacity-30"
        >
          {isRunning ? (
            <>
              <Loader2 size={15} className="animate-spin" />
              {currentIndex !== null ? `${(currentIndex ?? 0) + 1}/${totalUrls}` : 'Running'}
            </>
          ) : (
            <>
              {queued > 1 ? `Run ${queued}` : 'Run'}
              <ArrowRight size={15} />
            </>
          )}
        </button>
      </div>

      {/* Queued URLs — appear only when more than one is staged. */}
      {activeUrls.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] text-gray-300">
              {activeUrls.length} queued
            </span>
            {!isRunning && (
              <button
                type="button"
                onClick={clearAll}
                className="flex items-center gap-1 text-[11px] text-gray-300 transition-colors hover:text-black"
              >
                <Trash2 size={10} /> clear
              </button>
            )}
          </div>
          {activeUrls.map((url, i) => (
            <div
              key={url}
              className={`flex items-center gap-2 border px-3 py-1.5 font-mono text-[11px] ${
                isRunning && i === currentIndex
                  ? 'border-black text-black'
                  : isRunning && i < (currentIndex ?? -1)
                  ? 'border-hairline text-gray-300 line-through'
                  : 'border-hairline text-gray-500'
              }`}
            >
              <span className="flex-1 truncate">{url}</span>
              {isRunning && i === currentIndex ? (
                <Loader2 size={11} className="shrink-0 animate-spin text-black" />
              ) : (
                !isRunning && (
                  <button type="button" onClick={() => removeUrl(i)} className="shrink-0 text-gray-300 transition-colors hover:text-black">
                    <X size={12} />
                  </button>
                )
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Mode. Auto Discover reveals the intent bar; Direct just scrapes. ── */}
      <div className="mt-3 flex border border-hairline p-0.5">
        {TASK_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            data-tour={type === TASK_TYPES[0] ? 'playground-task-type' : undefined}
            onClick={() => setTaskType(type)}
            disabled={isRunning}
            className={`flex-1 px-3 py-2 text-sm font-medium transition-colors disabled:opacity-70 ${
              taskType === type ? 'bg-black text-white' : 'text-gray-500 hover:text-black'
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {/* ── The magical bit: tell it what to look for. Auto Discover only. ── */}
      <AnimatePresence initial={false}>
        {isAuto && (
          <motion.div
            key="intent"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.35, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="mt-3 border border-hairline bg-surface">
              <div className="flex items-start gap-3 px-4 py-3">
                <span className="mt-0.5 animate-pulse select-none font-mono text-base leading-none text-black">✦</span>
                <div className="min-w-0 flex-1">
                  <label className="block text-xs font-medium text-black">
                    What should it discover?
                  </label>
                  <input
                    type="text"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    placeholder="all the restaurants · every plumber · leave blank for everything"
                    disabled={isRunning}
                    className="mt-1.5 w-full bg-transparent font-mono text-sm text-black placeholder-gray-300 outline-none disabled:opacity-50"
                  />
                </div>
                {goal.trim() && !isRunning && (
                  <button
                    type="button"
                    onClick={() => setGoal('')}
                    className="mt-0.5 shrink-0 text-gray-300 transition-colors hover:text-black"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Advanced. Priority fields + enrichment, tucked out of the way. ── */}
      <div className="mt-3">
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="flex items-center gap-1.5 text-xs font-medium text-gray-500 transition-colors hover:text-black"
        >
          <ChevronRight
            size={13}
            className="transition-transform"
            style={{ transform: showAdvanced ? 'rotate(90deg)' : 'none' }}
          />
          Advanced
          {(priorities.size > 0 || accurateEnrichment) && (
            <span className="font-mono text-[11px] text-gray-300">
              · {priorities.size} field{priorities.size === 1 ? '' : 's'}{accurateEnrichment ? ' · verify' : ''}
            </span>
          )}
        </button>

        <AnimatePresence initial={false}>
          {showAdvanced && (
            <motion.div
              key="advanced"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="overflow-hidden"
            >
              <div className="mt-3 flex flex-col gap-4 border border-hairline px-4 py-4">
                <div>
                  <span className="block text-xs font-medium text-black">Priority fields</span>
                  <p className="mt-0.5 text-[11px] text-gray-300">
                    Detail-crawl and enrich to fill these in.
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {PRIORITY_FIELDS.map(({ key, label }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => togglePriority(key)}
                        disabled={isRunning}
                        className={`border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-70 ${
                          priorities.has(key)
                            ? 'border-black bg-black text-white'
                            : 'border-hairline text-gray-500 hover:border-black hover:text-black'
                        }`}
                      >
                        {priorities.has(key) && <span className="mr-1">✓</span>}
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <label className="flex cursor-pointer items-start gap-2.5 border-t border-hairline pt-3">
                  <input
                    type="checkbox"
                    checked={accurateEnrichment}
                    onChange={(e) => setAccurateEnrichment(e.target.checked)}
                    disabled={isRunning}
                    className="mt-0.5 h-4 w-4 border-gray-300 disabled:opacity-50"
                  />
                  <span className="flex-1">
                    <span className="block text-sm font-medium text-black">More accurate web enrichment</span>
                    <span className="mt-0.5 block text-[11px] text-gray-500">
                      Slower — verifies each candidate site by matching its phone, email,
                      address, and name against the page.
                    </span>
                  </span>
                </label>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </form>
  )
}
