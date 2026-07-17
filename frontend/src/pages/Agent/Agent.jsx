import { useRef, useEffect } from 'react'
import { RotateCcw } from 'lucide-react'
import ChatMessage from './ChatMessage'
import ChatInput from './ChatInput'
import { LiveViewButton, LiveViewModal } from '../../components/LiveView'
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
    liveSessionId,
    paused,
    liveViewOpen,
    openLiveView,
    closeLiveView,
  } = useAgent()
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const hasHistory = messages.length > 1

  return (
    // Viewport-fit: the panel flexes to fill the screen below the navbar, so
    // the transcript scrolls internally and the composer never sits below the
    // fold. h-screen is the fallback where dvh isn't supported.
    <div className="flex h-screen flex-col bg-white pt-20 supports-[height:100dvh]:h-dvh">
      <div className="mx-auto flex min-h-0 w-full max-w-site flex-1 flex-col px-6 py-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <div className="flex items-baseline gap-3">
            <h1 className="text-xl font-bold tracking-tighter text-black">Discover</h1>
            <p className="hidden text-xs text-gray-500 sm:block">
              Describe what you want. Trawlbase finds the directory; you pick which to scrape.
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* Live View — appears while a scrape is running; flashes on a
                CAPTCHA pause the user needs to solve. Opens the shared modal
                (the in-chat terminal callout opens the same one). */}
            {isRunning && liveSessionId && (
              <LiveViewButton paused={paused} onClick={openLiveView} />
            )}

            {/* New chat — clears the saved transcript. Disabled mid-scrape. */}
            {hasHistory && (
              <button
                onClick={newChat}
                disabled={isRunning}
                className="flex items-center gap-1.5 border border-hairline px-3 py-2 text-xs font-medium text-gray-500 transition-colors hover:border-black hover:text-black disabled:opacity-40 disabled:cursor-not-allowed"
                title={isRunning ? 'Finish or stop the current scrape first' : 'Start a new conversation'}
              >
                <RotateCcw size={13} />
                New chat
              </button>
            )}

            {/* Accurate enrichment toggle */}
            <label
              className="flex cursor-pointer items-center gap-2 border border-hairline bg-surface px-3 py-2"
              title="Verifies each candidate website by fetching and matching phone, email, address, and name against the page. Takes longer."
            >
              <input
                type="checkbox"
                checked={accurateEnrichment}
                onChange={(e) => setAccurateEnrichment(e.target.checked)}
                disabled={isRunning}
                className="h-3.5 w-3.5 border-gray-300 text-accent focus:ring-accent disabled:opacity-50"
              />
              <span className="text-xs font-medium text-gray-700">Accurate enrichment</span>
              <span className="hidden text-[10px] text-gray-400 md:block">slower</span>
            </label>
          </div>
        </div>

        {/* min-h floor doubles as the min-h-0 override flexbox needs to shrink. */}
        <div className="flex min-h-[280px] flex-1 flex-col overflow-hidden border border-hairline bg-white">
          {/* Title bar — same chrome as the Playground terminal. */}
          <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
            <span className="font-mono text-[11px] text-gray-500">trawlbase — discover</span>
            <span
              className={`select-none font-mono text-[10px] ${
                isRunning ? 'animate-pulse font-medium text-black' : 'text-gray-300'
              }`}
            >
              {isRunning ? '■ running' : '□ idle'}
            </span>
          </div>

          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-5">
            <div className="flex flex-col gap-4">
              {messages.map((msg, i) => (
                <ChatMessage
                  key={msg.id ?? i}
                  message={msg}
                  paused={paused}
                  onOpenLive={openLiveView}
                />
              ))}
            </div>

            {messages.length <= 1 && !isRunning && (
              <div className="mt-6 space-y-2 pl-10">
                <p className="font-mono text-[11px] text-gray-400">Try asking for:</p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSend(s)}
                      className="border border-hairline px-3.5 py-1.5 text-xs text-gray-500 transition-colors hover:border-black hover:bg-surface hover:text-black"
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

      {/* Shared Live View modal — opened by the header button, the in-chat
          terminal callout, or auto-opened on a CAPTCHA pause. */}
      {liveViewOpen && liveSessionId && isRunning && (
        <LiveViewModal sessionId={liveSessionId} onClose={closeLiveView} />
      )}
    </div>
  )
}
