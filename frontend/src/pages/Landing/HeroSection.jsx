import Button from '../../components/Button'
import useTypewriter from '../../hooks/useTypewriter'
import { HERO_TERMINAL_LINES } from '../../lib/constants'

// The terminal is the hero image: it's the product actually working. Black is
// the page's one dark surface, so the demo reads as the emphasis of the page.
function TerminalPreview() {
  const { visibleLines } = useTypewriter(HERO_TERMINAL_LINES, {
    speed: 18,
    lineDelay: 300,
    loop: true,
    loopPause: 4000,
  })

  return (
    <div className="w-full overflow-hidden border border-black bg-black">
      <div className="border-b border-[#222222] px-4 py-2.5">
        <span className="font-mono text-xs text-[#888888]">trawlbase — live run</span>
      </div>
      <div className="h-72 overflow-hidden px-5 py-4 font-mono text-sm leading-relaxed">
        {visibleLines.map((line, i) => (
          <div key={i} style={{ color: line.color || '#888888' }}>
            {line.text}
            {i === visibleLines.length - 1 && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-white align-middle" />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function HeroSection() {
  return (
    <section className="border-b border-hairline bg-white px-6 pb-24 pt-32 md:pt-40 lg:px-16">
      {/* Asymmetric: thesis left, the working product right. Nothing centered. */}
      <div className="mx-auto grid max-w-site items-center gap-16 lg:grid-cols-[3fr_2fr]">
        <div>
          <h1 className="max-w-[16ch] text-balance text-4xl font-bold leading-[1.1] tracking-tighter text-black sm:text-5xl md:text-[3.5rem]">
            Turn any directory into structured data.
          </h1>

          <p className="mt-8 max-w-xl text-lg leading-relaxed text-gray-500">
            Point Trawlbase at a directory &mdash; HOAs, chambers of commerce, trade associations. It pulls every record, enriches each from its own website, and hands you clean JSON or CSV.
          </p>

          <div className="mt-12 flex flex-wrap items-center gap-8">
            <Button to="/playground">Open the scraper</Button>
          </div>
        </div>

        <TerminalPreview />
      </div>
    </section>
  )
}
