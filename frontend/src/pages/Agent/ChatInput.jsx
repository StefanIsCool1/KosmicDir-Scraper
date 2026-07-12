import { useState, useRef, useEffect } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'

export default function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  // Auto-grow the textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [value])

  const handleSubmit = (e) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form
      data-tour="agent-chat-input"
      onSubmit={handleSubmit}
      className="border-t border-hairline bg-white p-3"
    >
      {/* Hairline frame that snaps to black on focus — the terminal prompt
          glyph follows it, tying the composer to the scraper's output UI. */}
      <div className="group flex items-end gap-2 border border-hairline px-3 py-1.5 transition-colors focus-within:border-black">
        <span className="select-none self-start py-1.5 font-mono text-sm text-gray-300 transition-colors group-focus-within:text-black">
          &gt;
        </span>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe what you're looking for..."
          rows={1}
          disabled={disabled}
          className="block max-h-[120px] flex-1 resize-none bg-transparent py-1.5 text-sm text-gray-900 placeholder-gray-300 outline-none disabled:opacity-50"
        />
        <span className="hidden select-none pb-1.5 font-mono text-[10px] text-gray-300 md:block">
          enter ⏎
        </span>
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center bg-black text-white transition-colors hover:bg-accent-600 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="Send"
        >
          {disabled ? <Loader2 size={14} className="animate-spin" /> : <ArrowUp size={14} />}
        </button>
      </div>
    </form>
  )
}
