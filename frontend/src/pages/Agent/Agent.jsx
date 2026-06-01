import { useRef, useEffect } from 'react'
import { Sparkles, RotateCcw } from 'lucide-react'
import ChatMessage from './ChatMessage'
import ChatInput from './ChatInput'
import { useAgent } from '../../context/AgentContext'

const SUGGESTIONS = [
  'Find all HOAs in Washington state',
  'Chambers of commerce in Texas',
  'Members of the State Bar of California',
  'Every dentist in Austin, TX',
]

export default function Agent() {
  // State + the live /discover stream live in AgentProvider (above the router),
  // so this view can unmount on navigation without losing the conversation.
  const {
    messages,
    isRunning,
    accurateEnrichment,
    setAccurateEnrichment,
    handleSend,
    newChat,
  } = useAgent()
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const hasHistory = messages.length > 1

  return (
    <div className="min-h-screen bg-white pt-20">
      <div className="mx-auto max-w-site px-6 py-8">
        <div className="mb-6 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white shadow-sm">
              <Sparkles size={14} />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tighter text-gray-900">Discover</h1>
              <p className="text-xs text-gray-400">
                Describe what you want. Trawlbase finds the directory; you pick which to scrape.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* New chat — clears the saved transcript. Disabled mid-scrape. */}
            {hasHistory && (
              <button
                onClick={newChat}
                disabled={isRunning}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-500 transition-colors hover:border-gray-300 hover:text-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                title={isRunning ? 'Finish or stop the current scrape first' : 'Start a new conversation'}
              >
                <RotateCcw size={13} />
                New chat
              </button>
            )}

            {/* Accurate enrichment toggle */}
            <label
              className="flex max-w-xs items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 cursor-pointer"
              title="Verifies each candidate website by fetching and matching phone, email, address, and name against the page."
            >
              <input
                type="checkbox"
                checked={accurateEnrichment}
                onChange={(e) => setAccurateEnrichment(e.target.checked)}
                disabled={isRunning}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-accent focus:ring-accent disabled:opacity-50"
              />
              <span className="flex-1">
                <span className="block text-xs font-medium text-gray-700">
                  More accurate web enrichment
                </span>
                <span className="mt-0.5 block text-[10px] leading-tight text-amber-600">
                  ⚠ WARNING: takes longer
                </span>
              </span>
            </label>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div ref={scrollRef} className="h-[600px] overflow-y-auto px-4 py-5 lg:h-[680px]">
            <div className="flex flex-col gap-4">
              {messages.map((msg, i) => (
                <ChatMessage key={msg.id ?? i} message={msg} />
              ))}
            </div>

            {messages.length <= 1 && !isRunning && (
              <div className="mt-6 space-y-2">
                <p className="text-xs text-gray-300 font-medium">Try asking for:</p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSend(s)}
                      className="rounded-full border border-gray-200 px-3.5 py-1.5 text-xs text-gray-500 transition-all hover:border-accent hover:text-accent hover:bg-accent-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <ChatInput onSend={handleSend} disabled={isRunning} />
        </div>
      </div>
    </div>
  )
}
