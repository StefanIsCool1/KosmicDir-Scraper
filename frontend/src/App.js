import { useState, useRef, useEffect, useCallback } from "react";

/* ── SVG Icons ── */
const GitHubIcon = ({ size = 16, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
  </svg>
);

const LinkedInIcon = ({ size = 16, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
  </svg>
);

/* ── Bouncing Ball Component ── */
function BouncingBall({ type, onDone }) {
  const ballRef = useRef(null);
  const animRef = useRef(null);
  const state = useRef({
    x: Math.random() * (window.innerWidth - 60) + 30,
    y: window.innerHeight * 0.7,
    vx: (Math.random() > 0.5 ? 1 : -1) * (3 + Math.random() * 4),
    vy: -(8 + Math.random() * 4),
    gravity: 0.35,
    dampening: 0.75,
    friction: 0.995,
    radius: 20,
  });

  useEffect(() => {
    const s = state.current;
    let ticks = 0;
    const maxTicks = 600; // ~10 seconds at 60fps

    const animate = () => {
      s.vy += s.gravity;
      s.vx *= s.friction;
      s.x += s.vx;
      s.y += s.vy;

      // Bounce off walls
      if (s.x - s.radius < 0) { s.x = s.radius; s.vx = Math.abs(s.vx) * s.dampening; }
      if (s.x + s.radius > window.innerWidth) { s.x = window.innerWidth - s.radius; s.vx = -Math.abs(s.vx) * s.dampening; }
      // Bounce off ceiling
      if (s.y - s.radius < 0) { s.y = s.radius; s.vy = Math.abs(s.vy) * s.dampening; }
      // Bounce off floor
      if (s.y + s.radius > window.innerHeight) {
        s.y = window.innerHeight - s.radius;
        s.vy = -Math.abs(s.vy) * s.dampening;
        // Stop micro-bouncing
        if (Math.abs(s.vy) < 1) s.vy = 0;
      }

      if (ballRef.current) {
        ballRef.current.style.transform = `translate(${s.x - s.radius}px, ${s.y - s.radius}px)`;
      }

      ticks++;
      if (ticks < maxTicks && (Math.abs(s.vx) > 0.1 || Math.abs(s.vy) > 0.1 || s.y < window.innerHeight - s.radius - 1)) {
        animRef.current = requestAnimationFrame(animate);
      } else {
        // Fade out then remove
        if (ballRef.current) ballRef.current.style.opacity = "0";
        setTimeout(() => onDone(), 500);
      }
    };

    animRef.current = requestAnimationFrame(animate);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [onDone]);

  const color = type === "github" ? "#4a6b1a" : "#2a4a7a";
  const iconColor = type === "github" ? "#7a9b3a" : "#5a8aba";

  return (
    <div ref={ballRef} style={{
      position: "fixed",
      top: 0,
      left: 0,
      width: state.current.radius * 2,
      height: state.current.radius * 2,
      zIndex: 1,
      pointerEvents: "none",
      transition: "opacity 0.5s",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      filter: `drop-shadow(0 0 4px ${color}40)`,
    }}>
      <div style={{
        width: "100%",
        height: "100%",
        borderRadius: "50%",
        background: `radial-gradient(circle at 35% 35%, ${color}, ${color}88)`,
        border: `1px solid ${iconColor}30`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}>
        {type === "github"
          ? <GitHubIcon size={18} color={iconColor} />
          : <LinkedInIcon size={18} color={iconColor} />
        }
      </div>
    </div>
  );
}

/* ── Color maps ── */
const CAT_COLORS = {
  NAV: "#60a5fa", SEARCH: "#facc15", SCROLL: "#a78bfa",
  PAGE: "#34d399", CAPTURE: "#38bdf8", IFRAME: "#c084fc",
  PARSE: "#fb923c", DETAIL: "#f472b6", CLEAN: "#4ade80",
  BROWSER: "#94a3b8", LOG: "#666", PROMPT: "#facc15",
  INPUT: "#a3e635", ERROR: "#f87171", SYSTEM: "#555",
};

const LEVEL_COLORS = { info: "#888", warn: "#facc15", error: "#f87171" };

/* ───────────────────────────────────────────
   Terminal Component
   ─────────────────────────────────────────── */
function Terminal({ lines, awaitingInput, onInput }) {
  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  useEffect(() => {
    if (awaitingInput && inputRef.current) {
      inputRef.current.focus();
    }
  }, [awaitingInput]);

  if (!lines || lines.length === 0) return null;

  return (
    <div style={{
      marginTop: 20,
      background: "#0a0a0a",
      border: "1px solid #1a1a1a",
      borderRadius: 6,
      overflow: "hidden",
    }}>
      {/* Title bar — macOS-style dots */}
      <div style={{
        padding: "8px 14px",
        borderBottom: "1px solid #1a1a1a",
        display: "flex",
        alignItems: "center",
        gap: 8,
        background: "#111",
      }}>
        <div style={{ display: "flex", gap: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#f87171" }} />
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#facc15" }} />
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#4ade80" }} />
        </div>
        <span style={{
          color: "#555", fontSize: 10, letterSpacing: 2,
          textTransform: "uppercase", fontFamily: "'Hacked', monospace", marginLeft: 8,
        }}>
          underdeck@scraper ~ bot
        </span>
        <span style={{ marginLeft: "auto", color: "#333", fontSize: 9 }}>
          {lines.length} events
        </span>
      </div>

      {/* Log output */}
      <div ref={scrollRef} style={{
        maxHeight: 280,
        overflowY: "auto",
        padding: "10px 14px",
        scrollBehavior: "smooth",
      }}>
        {/* Boot message */}
        <div style={{ color: "#333", fontSize: 10, fontFamily: "'Hacked', monospace", marginBottom: 6 }}>
          UnderDeck Scraper Bot v2.0 — initializing...
        </div>

        {lines.map((line, i) => (
          <div key={i} style={{
            fontFamily: "'Hacked', monospace",
            fontSize: 11,
            lineHeight: "20px",
            padding: "1px 0",
            animation: "fadeIn 0.3s ease-out",
          }}>
            {/* Prefix */}
            <span style={{ color: "#333" }}>
              {line.isInput ? "$ " : line.isPrompt ? "? " : "> "}
            </span>
            {/* Category tag */}
            {line.category && !line.isInput && (
              <span style={{
                color: CAT_COLORS[line.category] || "#555",
                fontWeight: "bold",
                opacity: 0.7,
              }}>
                [{line.category}]{" "}
              </span>
            )}
            {/* Message */}
            <span style={{
              color: line.isInput ? "#a3e635"
                : line.isPrompt ? "#facc15"
                : line.category === "ERROR" ? "#f87171"
                : "#aaa",
            }}>
              {line.text}
            </span>
          </div>
        ))}

        {/* Blinking cursor when running */}
        {!awaitingInput && lines.length > 0 && lines[lines.length - 1]?.category !== "SYSTEM" && (
          <span style={{
            display: "inline-block",
            width: 7, height: 14,
            background: "#a3e635",
            animation: "blink 1s step-end infinite",
            verticalAlign: "middle",
            marginTop: 2,
          }} />
        )}
      </div>

      {/* Input area — visible when bot asks a question */}
      {awaitingInput && (
        <div style={{
          borderTop: "1px solid #1a1a1a",
          padding: "10px 14px",
          display: "flex",
          alignItems: "center",
          gap: 8,
          background: "#0d0d0d",
        }}>
          <span style={{ color: "#a3e635", fontFamily: "'Hacked', monospace", fontSize: 12 }}>$</span>
          <input
            ref={inputRef}
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && inputValue.trim()) {
                onInput(inputValue.trim());
                setInputValue("");
              }
            }}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              color: "#fff",
              fontFamily: "'Hacked', monospace",
              fontSize: 12,
              outline: "none",
              caretColor: "#a3e635",
            }}
            placeholder="type y or n..."
          />
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────
   Debug Panel Component
   ─────────────────────────────────────────── */
function DebugPanel({ entries, summary }) {
  const [filter, setFilter] = useState("all");
  if (!entries || entries.length === 0) return null;

  const filtered = filter === "all" ? entries
    : filter === "warnings" ? entries.filter(e => e.level === "warn" || e.level === "error")
    : entries.filter(e => e.category === filter);

  return (
    <div style={{
      marginTop: 20, background: "#111",
      border: "1px solid #2a2a2a", borderRadius: 6, overflow: "hidden",
    }}>
      <div style={{
        padding: "10px 14px", borderBottom: "1px solid #2a2a2a",
        display: "flex", justifyContent: "space-between", alignItems: "center",
      }}>
        <span style={{ color: "#a3e635", fontSize: 11, letterSpacing: 2, textTransform: "uppercase" }}>
          Debug Log
        </span>
        {summary && (
          <span style={{ color: "#555", fontSize: 10 }}>
            {summary.total_entries} entries | {summary.total_time_seconds}s
            {summary.warnings > 0 && <span style={{ color: "#facc15" }}> | {summary.warnings} warn</span>}
            {summary.errors > 0 && <span style={{ color: "#f87171" }}> | {summary.errors} err</span>}
          </span>
        )}
      </div>
      <div style={{
        padding: "6px 14px", borderBottom: "1px solid #2a2a2a",
        display: "flex", gap: 6, flexWrap: "wrap",
      }}>
        {["all", "warnings", ...Object.keys(CAT_COLORS).filter(c => !["PROMPT","INPUT","ERROR","SYSTEM","LOG"].includes(c))].map(cat => (
          <button key={cat} onClick={() => setFilter(cat)} style={{
            padding: "2px 8px", fontSize: 9, fontFamily: "monospace",
            background: filter === cat ? "#333" : "transparent",
            color: cat === "all" ? "#888" : cat === "warnings" ? "#facc15" : (CAT_COLORS[cat] || "#888"),
            border: `1px solid ${filter === cat ? "#555" : "#2a2a2a"}`,
            borderRadius: 3, cursor: "pointer", textTransform: "uppercase", letterSpacing: 1,
          }}>
            {cat}
          </button>
        ))}
      </div>
      <div style={{ maxHeight: 400, overflowY: "auto", padding: "8px 14px" }}>
        {filtered.map((entry, i) => (
          <div key={i} style={{
            fontFamily: "monospace", fontSize: 11, lineHeight: "18px",
            borderBottom: "1px solid #1a1a1a", padding: "4px 0",
          }}>
            <span style={{ color: "#555" }}>{entry.time.toFixed(2)}s </span>
            <span style={{ color: CAT_COLORS[entry.category] || "#888", fontWeight: "bold" }}>
              [{entry.category}]
            </span>
            {entry.level !== "info" && (
              <span style={{ color: LEVEL_COLORS[entry.level], fontWeight: "bold" }}>
                {" "}[{entry.level.toUpperCase()}]
              </span>
            )}
            <span style={{ color: entry.level === "error" ? "#f87171" : entry.level === "warn" ? "#facc15" : "#ccc" }}>
              {" "}{entry.message}
            </span>
            {entry.data && (
              <div style={{ color: "#555", fontSize: 10, marginLeft: 20, marginTop: 2 }}>
                {JSON.stringify(entry.data).substring(0, 300)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ───────────────────────────────────────────
   Main App
   ─────────────────────────────────────────── */
export default function App() {
  const [mode, setMode] = useState("link");
  const [link, setLink] = useState("");
  const [fileName, setFileName] = useState(null);
  const [status, setStatus] = useState(null);
  const [debugMode, setDebugMode] = useState(false);
  const [debugData, setDebugData] = useState(null);
  const [terminalLines, setTerminalLines] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [awaitingInput, setAwaitingInput] = useState(false);
  const [balls, setBalls] = useState([]);
  const fileRef = useRef();

  const spawnBall = useCallback((type) => {
    const id = Date.now() + Math.random();
    setBalls(prev => [...prev, { id, type }]);
  }, []);

  const removeBall = useCallback((id) => {
    setBalls(prev => prev.filter(b => b.id !== id));
  }, []);

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (f) setFileName(f.name);
  };

  const handleRun = async () => {
    setStatus("running");
    setDebugData(null);
    setTerminalLines([{ text: "Initializing scraper...", category: "SYSTEM", isPrompt: false, isInput: false }]);
    setAwaitingInput(false);
    setSessionId(null);

    try {
      if (mode === "link") {
        const res = await fetch("http://localhost:5000/scrape/single", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ link, debug: debugMode }),
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop();

          for (const chunk of chunks) {
            if (!chunk.startsWith("data: ")) continue;
            try {
              const event = JSON.parse(chunk.slice(6));

              if (event.type === "session") {
                setSessionId(event.session_id);
              } else if (event.type === "log") {
                setTerminalLines(prev => [...prev, {
                  text: event.message,
                  category: event.category,
                }]);
              } else if (event.type === "prompt") {
                setAwaitingInput(true);
                setTerminalLines(prev => [...prev, {
                  text: event.message,
                  category: "PROMPT",
                  isPrompt: true,
                }]);
              } else if (event.type === "complete") {
                setStatus(event.success ? "done" : "error");
                setTerminalLines(prev => [...prev, {
                  text: event.success
                    ? `Done! Extracted ${event.records} members.`
                    : "Scrape completed with 0 members.",
                  category: "SYSTEM",
                }]);
                if (event.debug_entries) {
                  setDebugData({ entries: event.debug_entries, summary: event.debug_summary });
                }
              } else if (event.type === "error") {
                setStatus("error");
                setTerminalLines(prev => [...prev, {
                  text: `Error: ${event.message}`,
                  category: "ERROR",
                }]);
              }
            } catch (parseErr) {
              // Ignore malformed SSE chunks
            }
          }
        }
        // If status wasn't set by an event (stream ended without complete/error)
        setStatus(prev => prev === "running" ? "done" : prev);

      } else if (mode === "csv") {
        const form = new FormData();
        form.append("file", fileRef.current.files[0]);

        setTerminalLines(prev => [...prev, { text: "Processing CSV...", category: "SYSTEM" }]);

        await fetch("http://localhost:5000/scrape/csv", {
          method: "POST",
          body: form,
        });
        setStatus("done");
        setTerminalLines(prev => [...prev, { text: "CSV processing complete.", category: "SYSTEM" }]);
      }
    } catch (err) {
      setStatus("error");
      setTerminalLines(prev => [...prev, { text: `Connection error: ${err.message}`, category: "ERROR" }]);
    }
  };

  const handleTerminalInput = async (value) => {
    if (!sessionId) return;

    setTerminalLines(prev => [...prev, {
      text: value,
      category: "INPUT",
      isInput: true,
    }]);
    setAwaitingInput(false);

    try {
      await fetch("http://localhost:5000/scrape/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, value }),
      });
    } catch (err) {
      setTerminalLines(prev => [...prev, { text: `Failed to send response: ${err.message}`, category: "ERROR" }]);
    }
  };

  const ready = mode === "link" ? link.trim().length > 0 : fileName !== null;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0f0f0f",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "'Hacked', monospace",
    }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::placeholder { color: #555; }
        input[type=file] { display: none; }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        @keyframes blink {
          50% { opacity: 0; }
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          10% { transform: translateX(-3px) rotate(-1deg); }
          20% { transform: translateX(3px) rotate(1deg); }
          30% { transform: translateX(-3px) rotate(-0.5deg); }
          40% { transform: translateX(3px) rotate(0.5deg); }
          50% { transform: translateX(-2px); }
          60% { transform: translateX(2px); }
          70% { transform: translateX(-1px); }
          80% { transform: translateX(1px); }
          90% { transform: translateX(0); }
        }
        .name-hover {
          transition: color 0.15s, text-shadow 0.15s;
          cursor: default;
        }
        .name-hover:hover {
          color: #f87171 !important;
          text-shadow: 0 0 8px #f8717140;
          animation: shake 0.4s ease-in-out;
        }
        .social-link {
          transition: transform 0.2s ease, color 0.2s ease;
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }
        .social-link:hover {
          transform: scale(1.15);
        }
        .rainbow-wrapper {
          position: relative;
          width: 520px;
          border-radius: 10px;
          padding: 3px;
          overflow: hidden;
        }
        .rainbow-wrapper::before {
          content: '';
          position: absolute;
          inset: -50%;
          background: conic-gradient(red, orange, yellow, green, blue, violet, red);
          animation: spin 3s linear infinite;
        }
        /* Scrollbar styling for terminal */
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
      `}</style>

      {/* ── Card ── */}
      <div className="rainbow-wrapper">
        <div style={{
          position: "relative",
          width: "100%",
          background: "#1a1a1a",
          borderRadius: 8,
          padding: 40,
        }}>

          {/* Title */}
          <div style={{ marginBottom: 32, fontFamily: "'Hacked'" }}>
            <div style={{ fontSize: 11, color: "#555", letterSpacing: 3, textTransform: "uppercase", marginBottom: 6 }}>
              UnderDeck
            </div>
            <div style={{ fontSize: 28, color: "#fff", fontWeight: "bold", letterSpacing: 1 }}>
              Scraper Bot
            </div>
            <div style={{ fontSize: 28, color: "#fff", fontWeight: "bold", letterSpacing: 1, marginBottom: 10 }}>
              Created BY STEFAN :)
            </div>
          </div>

          {/* Toggle */}
          <div style={{ display: "flex", marginBottom: 28, border: "1px solid #2a2a2a", borderRadius: 6, overflow: "hidden" }}>
            {["link", "csv"].map((m) => (
              <button key={m} onClick={() => setMode(m)} style={{
                flex: 1, padding: "10px 0",
                background: mode === m ? "#fff" : "transparent",
                color: mode === m ? "#0f0f0f" : "#555",
                border: "none", fontFamily: "monospace", fontSize: 11,
                letterSpacing: 2, textTransform: "uppercase",
                cursor: "pointer", transition: "all 0.15s",
              }}>
                {m === "link" ? "Single Link" : "CSV File"}
              </button>
            ))}
          </div>

          {/* Single Link Input */}
          {mode === "link" && (
            <div>
              <div style={{ fontSize: 10, color: "#555", letterSpacing: 2, textTransform: "uppercase", marginBottom: 10 }}>
                Target URL
              </div>
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://www.WeHaveTheBestUnderDeckTeamEver.com"
                autoFocus
                style={{
                  width: "100%", background: "#111", border: "1px solid #2a2a2a",
                  borderRadius: 4, color: "#fff", fontFamily: "monospace",
                  fontSize: 13, padding: "12px 14px", outline: "none",
                }}
              />
            </div>
          )}

          {/* CSV Upload */}
          {mode === "csv" && (
            <div>
              <div style={{ fontSize: 10, color: "#555", letterSpacing: 2, textTransform: "uppercase", marginBottom: 10 }}>
                Upload CSV
              </div>
              <div onClick={() => fileRef.current.click()} style={{
                border: "1px dashed #2a2a2a", borderRadius: 4, padding: "28px",
                textAlign: "center", cursor: "pointer", transition: "border-color 0.2s",
              }}>
                <input type="file" accept=".csv" ref={fileRef} onChange={handleFile} />
                {fileName
                  ? <div style={{ color: "#a3e635", fontSize: 12 }}>📄 {fileName}</div>
                  : <div style={{ color: "#555", fontSize: 11, letterSpacing: 1 }}>PLS UPLOAD .csv {">"}:) </div>
                }
              </div>
            </div>
          )}

          {/* Debug Mode Toggle */}
          <label style={{
            display: "flex", alignItems: "center", gap: 8,
            marginTop: 16, cursor: "pointer", userSelect: "none",
          }}>
            <div onClick={() => setDebugMode(!debugMode)} style={{
              width: 16, height: 16,
              border: `1px solid ${debugMode ? "#a3e635" : "#2a2a2a"}`,
              borderRadius: 3, background: debugMode ? "#a3e635" : "transparent",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.15s", cursor: "pointer",
            }}>
              {debugMode && <span style={{ color: "#0f0f0f", fontSize: 11, fontWeight: "bold", lineHeight: 1 }}>✓</span>}
            </div>
            <span style={{ color: "#555", fontSize: 10, letterSpacing: 2, textTransform: "uppercase" }}>
              Debug Mode
            </span>
          </label>

          {/* Run Button */}
          <button onClick={handleRun} disabled={!ready || status === "running"} style={{
            width: "100%", marginTop: 20, padding: "14px",
            background: ready && status !== "running" ? "#a3e635" : "#1a1a1a",
            color: ready && status !== "running" ? "#0f0f0f" : "#333",
            border: "1px solid #2a2a2a", borderRadius: 4,
            fontFamily: "monospace", fontSize: 11, letterSpacing: 3,
            textTransform: "uppercase", fontWeight: "bold",
            cursor: ready && status !== "running" ? "pointer" : "not-allowed",
            transition: "all 0.15s",
          }}>
            {status === "running" ? "Running..." : "run scrap →"}
          </button>

          {/* ── Live Terminal ── */}
          {terminalLines.length > 0 && (
            <Terminal
              lines={terminalLines}
              awaitingInput={awaitingInput}
              onInput={handleTerminalInput}
            />
          )}

          {/* Status bar */}
          {status && status !== "running" && (
            <div style={{
              marginTop: 12, padding: "10px 14px", borderRadius: 4,
              fontSize: 11, letterSpacing: 1,
              background: status === "done" ? "#0a1a0a" : "#1a0a0a",
              color: status === "done" ? "#a3e635" : "#f87171",
              border: `1px solid ${status === "done" ? "#a3e63530" : "#f8717130"}`,
            }}>
              {status === "done" && "YAY :)))))). DONE!, check the Data-dump folder"}
              {status === "error" && "Something went wrong, or unable to scrap."}
            </div>
          )}

          {/* Debug Panel */}
          {debugData && <DebugPanel entries={debugData.entries} summary={debugData.summary} />}

        </div>
      </div>

      {/* Bouncing balls */}
      {balls.map(b => (
        <BouncingBall key={b.id} type={b.type} onDone={() => removeBall(b.id)} />
      ))}

      {/* Footer */}
      <div style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        padding: "16px 0",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        fontFamily: "'Hacked', monospace",
        zIndex: 10,
      }}>
        <div style={{ fontSize: 10, letterSpacing: 3, color: "#2a2a2a" }}>
          built by{" "}
          <span className="name-hover" style={{ color: "#444" }}>
            Stefan O'Leary
          </span>
        </div>
        <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
          <a href="https://github.com/StefanIsCool1/UnderDeckScraper" target="_blank" rel="noopener noreferrer"
            className="social-link"
            style={{ color: "#333", fontSize: 9, letterSpacing: 2, textDecoration: "none", textTransform: "uppercase" }}
            onMouseEnter={e => { e.currentTarget.style.color = "#a3e635"; spawnBall("github"); }}
            onMouseLeave={e => { e.currentTarget.style.color = "#333"; }}
          >
            <GitHubIcon size={14} color="currentColor" />
            GitHub
          </a>
          <span style={{ color: "#1a1a1a" }}>|</span>
          <a href="https://www.linkedin.com/in/stefan-o%27leary-b94079361" target="_blank" rel="noopener noreferrer"
            className="social-link"
            style={{ color: "#333", fontSize: 9, letterSpacing: 2, textDecoration: "none", textTransform: "uppercase" }}
            onMouseEnter={e => { e.currentTarget.style.color = "#60a5fa"; spawnBall("linkedin"); }}
            onMouseLeave={e => { e.currentTarget.style.color = "#333"; }}
          >
            <LinkedInIcon size={14} color="currentColor" />
            LinkedIn
          </a>
        </div>
      </div>
    </div>
  );
}
