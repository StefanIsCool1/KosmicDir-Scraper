import { useState, useEffect, useRef } from 'react'

export default function useTypewriter(lines, { speed = 30, lineDelay = 400, loop = true, loopPause = 3000 } = {}) {
  const [visibleLines, setVisibleLines] = useState([])
  const [isTyping, setIsTyping] = useState(true)
  const timeout = useRef(null)

  useEffect(() => {
    if (!lines || lines.length === 0) return

    let lineIdx = 0
    let charIdx = 0
    let current = []

    function typeNext() {
      if (lineIdx >= lines.length) {
        setIsTyping(false)
        if (loop) {
          timeout.current = setTimeout(() => {
            setVisibleLines([])
            lineIdx = 0
            charIdx = 0
            current = []
            setIsTyping(true)
            typeNext()
          }, loopPause)
        }
        return
      }

      const line = lines[lineIdx]
      const text = typeof line === 'string' ? line : line.text

      if (charIdx <= text.length) {
        const partial = { ...line, text: text.slice(0, charIdx) }
        const updated = [...current, partial]
        setVisibleLines(updated)
        charIdx++
        timeout.current = setTimeout(typeNext, speed)
      } else {
        current.push(line)
        setVisibleLines([...current])
        lineIdx++
        charIdx = 0
        timeout.current = setTimeout(typeNext, lineDelay)
      }
    }

    typeNext()
    return () => clearTimeout(timeout.current)
  }, [lines, speed, lineDelay, loop, loopPause])

  return { visibleLines, isTyping }
}
