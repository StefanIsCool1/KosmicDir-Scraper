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
   Mini Linux Terminal (readme.md)
   ─────────────────────────────────────────── */
const README_CONTENT = `Hey, my name is Stefan.

I've always enjoyed working on passion projects like these
(although they always take a lot of my school/work time away :(.

I hope you can play around with this code, good luck :)`;

function MiniTerminal({ onClose, onRainbow }) {
  const [lines, setLines] = useState([
    { text: "stefan@underdeck:~$ ", type: "prompt" },
    { text: "Type 'cat readme.md' to read the readme.", type: "hint" },
  ]);
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lines]);

  useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, [lines]);

  const DESTRUCTIVE = ["mkdir", "touch", "rm", "mv", "cp", "nano", "vim", "vi",
    "chmod", "chown", "write", "dd", "mkfs", "apt", "brew", "npm", "pip",
    "git init", "git commit", "git push", "wget", "curl -o", "sudo"];

  const handleCommand = (cmd) => {
    const trimmed = cmd.trim();
    const lower = trimmed.toLowerCase();
    const newLines = [
      ...lines,
      { text: `stefan@underdeck:~$ ${trimmed}`, type: "command" },
    ];

    if (!trimmed) {
      setLines([...newLines, { text: "stefan@underdeck:~$ ", type: "prompt" }]);
      return;
    }

    if (DESTRUCTIVE.some(d => lower.startsWith(d))) {
      newLines.push({ text: "this ain't a real terminal buddy >:(", type: "error" });
    } else if (lower === "cat readme.md") {
      README_CONTENT.split("\n").forEach(line => {
        newLines.push({ text: line, type: "output" });
      });
    } else if (lower === "cat" || lower.startsWith("cat ")) {
      const file = trimmed.slice(4).trim();
      if (!file) {
        newLines.push({ text: "cat: missing file operand", type: "error" });
      } else {
        newLines.push({ text: `cat: ${file}: No such file or directory`, type: "error" });
      }
    } else if (lower === "ls" || lower === "ls -la" || lower === "ls -a" || lower === "ls -l") {
      if (lower.includes("-a") || lower.includes("-la")) {
        newLines.push({ text: "drwxr-xr-x  stefan  staff  ..", type: "output" });
        newLines.push({ text: "drwxr-xr-x  stefan  staff  .", type: "output" });
      }
      newLines.push({ text: "-rw-r--r--  stefan  staff  readme.md", type: "output" });
      newLines.push({ text: "-rwxr-xr-x  stefan  staff  rainbow_mode.sh", type: "rainbow" });
    } else if (lower === "./rainbow_mode.sh" || lower === "bash rainbow_mode.sh" || lower === "sh rainbow_mode.sh") {
      newLines.push({ text: "🌈 RAINBOW MODE ACTIVATED 🌈", type: "rainbow" });
      newLines.push({ text: "nyan nyan nyan nyan nyan nyan nyan...", type: "rainbow" });
      newLines.push({ text: "stefan@underdeck:~$ ", type: "prompt" });
      setLines(newLines);
      setInput("");
      setTimeout(() => onRainbow(), 300);
      return;
    } else if (lower === "cat rainbow_mode.sh") {
      newLines.push({ text: "#!/bin/bash", type: "output" });
      newLines.push({ text: "# top secret easter egg", type: "hint" });
      newLines.push({ text: 'echo "activating rainbow mode..."', type: "output" });
      newLines.push({ text: 'echo "summoning nyan cat..."', type: "output" });
      newLines.push({ text: "# try running me with ./rainbow_mode.sh", type: "hint" });
    } else if (lower === "file rainbow_mode.sh") {
      newLines.push({ text: "rainbow_mode.sh: Bourne-Again shell script, extremely vibes", type: "output" });
    } else if (lower === "pwd") {
      newLines.push({ text: "/home/stefan", type: "output" });
    } else if (lower === "whoami") {
      newLines.push({ text: "stefan", type: "output" });
    } else if (lower === "hostname") {
      newLines.push({ text: "underdeck", type: "output" });
    } else if (lower === "date") {
      newLines.push({ text: new Date().toString(), type: "output" });
    } else if (lower === "uptime") {
      newLines.push({ text: "up since you opened this page, probably", type: "output" });
    } else if (lower === "echo" || lower.startsWith("echo ")) {
      newLines.push({ text: trimmed.slice(5), type: "output" });
    } else if (lower === "uname" || lower === "uname -a") {
      newLines.push({ text: "UnderDeckOS 2.0 stefan-macbook x86_64", type: "output" });
    } else if (lower === "id") {
      newLines.push({ text: "uid=1000(stefan) gid=1000(staff) groups=1000(staff),27(sudo)", type: "output" });
    } else if (lower === "clear") {
      setLines([{ text: "stefan@underdeck:~$ ", type: "prompt" }]);
      setInput("");
      return;
    } else if (lower === "exit" || lower === "quit") {
      onClose();
      return;
    } else if (lower === "help") {
      newLines.push({ text: "available: ls, cat, pwd, whoami, echo, date, clear, exit", type: "output" });
      newLines.push({ text: "try: cat readme.md", type: "hint" });
    } else if (lower.startsWith("cd")) {
      newLines.push({ text: "you're not going anywhere buddy", type: "error" });
    } else if (lower === "tree") {
      newLines.push({ text: "/home/stefan", type: "output" });
      newLines.push({ text: "├── readme.md", type: "output" });
      newLines.push({ text: "└── rainbow_mode.sh", type: "rainbow" });
    } else if (lower === "file readme.md") {
      newLines.push({ text: "readme.md: UTF-8 Unicode text, with very good vibes", type: "output" });
    } else if (lower === "wc readme.md" || lower === "wc -l readme.md") {
      newLines.push({ text: `  ${README_CONTENT.split("\n").length}  readme.md`, type: "output" });
    } else if (lower === "head readme.md") {
      README_CONTENT.split("\n").slice(0, 3).forEach(line => {
        newLines.push({ text: line, type: "output" });
      });
    } else if (lower === "tail readme.md") {
      README_CONTENT.split("\n").slice(-3).forEach(line => {
        newLines.push({ text: line, type: "output" });
      });
    } else if (lower === "neofetch" || lower === "screenfetch") {
      newLines.push({ text: "      ___       stefan@underdeck", type: "output" });
      newLines.push({ text: "     /   \\      OS: UnderDeckOS 2.0", type: "output" });
      newLines.push({ text: "    | U D |     Host: localhost:3000", type: "output" });
      newLines.push({ text: "     \\___/      Shell: not-real-sh", type: "output" });
      newLines.push({ text: "               Mood: vibing", type: "output" });
    } else {
      newLines.push({ text: `bash: ${trimmed}: command not found`, type: "error" });
    }

    newLines.push({ text: "stefan@underdeck:~$ ", type: "prompt" });
    setLines(newLines);
    setInput("");
  };

  return (
    <div style={{
      position: "fixed",
      top: 40,
      right: 40,
      width: 420,
      background: "#0a0a0a",
      border: "1px solid #1a1a1a",
      borderRadius: 6,
      zIndex: 100,
      boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
      overflow: "hidden",
    }}>
      {/* Title bar */}
      <div style={{
        padding: "8px 12px",
        borderBottom: "1px solid #1a1a1a",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        background: "#111",
      }}>
        <span style={{
          color: "#444", fontSize: 10, letterSpacing: 2,
          fontFamily: "'Hacked', monospace", textTransform: "uppercase",
        }}>
          stefan@underdeck:~
        </span>
        <div onClick={onClose} style={{
          width: 14, height: 14, borderRadius: 2,
          background: "#222", border: "1px solid #333",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", fontSize: 9, color: "#555", lineHeight: 1,
          transition: "background 0.15s",
        }}
          onMouseEnter={e => e.currentTarget.style.background = "#333"}
          onMouseLeave={e => e.currentTarget.style.background = "#222"}
        >
          x
        </div>
      </div>

      {/* Output */}
      <div ref={scrollRef} onClick={() => inputRef.current?.focus()} style={{
        maxHeight: 300,
        overflowY: "auto",
        padding: "10px 14px",
        cursor: "text",
      }}>
        {lines.map((line, i) => (
          <div key={i} style={{
            fontFamily: "'Hacked', monospace",
            fontSize: 11,
            lineHeight: "19px",
            color: line.type === "error" ? "#f87171"
              : line.type === "hint" ? "#555"
              : line.type === "command" ? "#a3e635"
              : line.type === "prompt" ? "#a3e635"
              : line.type === "rainbow" ? "#c084fc"
              : "#888",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}>
            {line.text}
          </div>
        ))}

        {/* Active input line */}
        <div style={{
          display: "flex",
          fontFamily: "'Hacked', monospace",
          fontSize: 11,
          lineHeight: "19px",
        }}>
          <span style={{ color: "#a3e635" }}>stefan@underdeck:~$&nbsp;</span>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") handleCommand(input);
            }}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              color: "#ccc",
              fontFamily: "'Hacked', monospace",
              fontSize: 11,
              outline: "none",
              padding: 0,
              caretColor: "#a3e635",
            }}
          />
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────────────────────────
   Nyan Cat Mini Game
   ─────────────────────────────────────────── */
function RainbowMode({ onClose }) {
  const catRef = useRef(null);
  const animRef = useRef(null);
  const audioRef = useRef(null);
  const [bouncesLeft, setBouncesLeft] = useState(50);
  const [timeLeft, setTimeLeft] = useState(60);
  const [gameOver, setGameOver] = useState(null); // null | "win" | "lose"
  const [touching, setTouching] = useState(false);
  const gameOverRef = useRef(false);
  const bouncesRef = useRef(50);

  const state = useRef({
    x: window.innerWidth / 2 - 60,
    y: window.innerHeight / 2 - 40,
    vx: 2,
    vy: 1.5,
    rotation: 0,
    touching: false,
  });

  const mouseRef = useRef({ x: -999, y: -999 });

  // Mouse tracking
  useEffect(() => {
    const handler = (e) => { mouseRef.current = { x: e.clientX, y: e.clientY }; };
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, []);

  // Audio — preload and start immediately
  useEffect(() => {
    const audio = new Audio("/nyancat.mp3");
    audio.loop = true;
    audio.volume = 0.5;
    audio.preload = "auto";
    audioRef.current = audio;
    // Force browser to buffer the file
    audio.load();
    audio.play().catch(() => {});
  }, []);

  const winAudioRef = useRef(null);
  useEffect(() => {
    const win = new Audio("/winning.mp3");
    win.preload = "auto";
    win.volume = 0.6;
    win.load();
    winAudioRef.current = win;
  }, []);

  const startAudio = useCallback(() => {
    if (audioRef.current && audioRef.current.paused) {
      audioRef.current.play().catch(() => {});
    }
  }, []);

  // Cleanup audio only on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        audioRef.current = null;
      }
    };
  }, []);

  // Countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(interval);
          if (!gameOverRef.current && bouncesRef.current > 0) {
            gameOverRef.current = true;
            if (audioRef.current) { audioRef.current.pause(); }
            setGameOver("lose");
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Stars
  const [stars] = useState(() => {
    const out = [];
    for (let i = 0; i < 120; i++) {
      out.push({
        x: Math.random() * 100, y: Math.random() * 100,
        size: Math.random() < 0.08 ? 2 + Math.random() * 1.5 : 0.5 + Math.random() * 1.2,
        opacity: 0.1 + Math.random() * 0.5,
        twinkle: Math.random() < 0.3,
        duration: 3 + Math.random() * 4,
        delay: Math.random() * 5,
      });
    }
    return out;
  });

  // Game loop
  useEffect(() => {
    const s = state.current;
    const CW = 260;
    const CH = 180;
    let lastTouchState = false;

    const animate = () => {
      if (gameOverRef.current) return;

      const mx = mouseRef.current.x;
      const my = mouseRef.current.y;
      const catCx = s.x + CW / 2;
      const catCy = s.y + CH / 2;
      const dist = Math.sqrt((mx - catCx) ** 2 + (my - catCy) ** 2);
      // Generous hit zone — 40px beyond the cat edge
      const isTouching = dist < (CW / 2 + 40);

      if (isTouching !== lastTouchState) {
        lastTouchState = isTouching;
        s.touching = isTouching;
        setTouching(isTouching);
        if (audioRef.current) audioRef.current.playbackRate = isTouching ? 1.3 : 1.0;
      }

      // Boost while touching — push away from cursor
      if (isTouching) {
        const angle = Math.atan2(catCy - my, catCx - mx);
        s.vx += Math.cos(angle) * 0.8;
        s.vy += Math.sin(angle) * 0.8;
      }

      s.x += s.vx;
      s.y += s.vy;

      // Wall bounces — each one costs a bounce
      let bounced = false;
      if (s.x <= 0) { s.x = 0; s.vx = Math.abs(s.vx); bounced = true; }
      if (s.x + CW >= window.innerWidth) { s.x = window.innerWidth - CW; s.vx = -Math.abs(s.vx); bounced = true; }
      if (s.y <= 0) { s.y = 0; s.vy = Math.abs(s.vy); bounced = true; }
      if (s.y + CH >= window.innerHeight) { s.y = window.innerHeight - CH; s.vy = -Math.abs(s.vy); bounced = true; }

      if (bounced) {
        bouncesRef.current--;
        setBouncesLeft(bouncesRef.current);
        if (bouncesRef.current <= 0 && !gameOverRef.current) {
          gameOverRef.current = true;
          if (audioRef.current) { audioRef.current.pause(); }
          if (winAudioRef.current) { winAudioRef.current.play().catch(() => {}); }
          setGameOver("win");
          return;
        }
      }

      // Friction
      s.vx *= 0.998;
      s.vy *= 0.998;

      // Minimum speed so it never fully stops
      const speed = Math.sqrt(s.vx ** 2 + s.vy ** 2);
      if (speed < 1.5) {
        s.vx *= 1.5 / speed;
        s.vy *= 1.5 / speed;
      }

      // Speed cap
      const cap = isTouching ? 14 : 6;
      s.vx = Math.min(Math.max(s.vx, -cap), cap);
      s.vy = Math.min(Math.max(s.vy, -cap), cap);

      s.rotation = s.vx * 1.5;

      if (catRef.current) {
        const scale = isTouching ? 1.4 : 1;
        catRef.current.style.transform = `translate(${s.x}px, ${s.y}px) rotate(${s.rotation}deg) scale(${scale})`;
      }

      animRef.current = requestAnimationFrame(animate);
    };

    animRef.current = requestAnimationFrame(animate);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, []);

  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div onClick={startAudio} style={{
      position: "fixed", inset: 0, zIndex: 9999,
      cursor: "crosshair", overflow: "hidden",
      background: "#020208",
    }}>
      <style>{`
        @keyframes starPulse {
          0%, 100% { opacity: var(--base-opacity); }
          50% { opacity: 1; }
        }
        @keyframes scoreRainbow {
          0% { color: #ff6b6b; }
          16% { color: #ffa94d; }
          33% { color: #ffd43b; }
          50% { color: #69db7c; }
          66% { color: #74c0fc; }
          83% { color: #b197fc; }
          100% { color: #ff6b6b; }
        }
        @keyframes popIn {
          0% { transform: translate(-50%, -50%) scale(0); opacity: 0; }
          50% { transform: translate(-50%, -50%) scale(1.15); opacity: 1; }
          70% { transform: translate(-50%, -50%) scale(0.95); }
          100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
        }
        @keyframes winTextGlow {
          0%, 100% { text-shadow: 0 0 10px #a3e63540; }
          50% { text-shadow: 0 0 30px #a3e63580, 0 0 60px #a3e63530; }
        }
      `}</style>

      {/* Space */}
      <div style={{
        position: "absolute", inset: 0,
        background: "radial-gradient(ellipse at 20% 80%, #0a0a2e 0%, transparent 50%), " +
                    "radial-gradient(ellipse at 80% 20%, #1a0a1e 0%, transparent 50%)",
      }} />

      {/* Stars */}
      {stars.map((s, i) => (
        <div key={i} style={{
          position: "absolute",
          left: `${s.x}%`, top: `${s.y}%`,
          width: s.size, height: s.size,
          borderRadius: "50%",
          background: s.size > 2.5 ? "#e8e0ff" : "#fff",
          opacity: s.opacity,
          boxShadow: s.size > 2 ? `0 0 ${s.size * 2}px ${s.size}px rgba(200,180,255,0.15)` : "none",
          ...(s.twinkle ? {
            animation: `starPulse ${s.duration}s ease-in-out infinite`,
            animationDelay: `${s.delay}s`,
            "--base-opacity": s.opacity,
          } : {}),
        }} />
      ))}

      {/* HUD — top bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        padding: "16px 30px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        fontFamily: "'Hacked', monospace",
        textTransform: "uppercase",
        letterSpacing: 4,
        zIndex: 2,
      }}>
        {/* Timer */}
        <div style={{
          fontSize: 16,
          color: timeLeft <= 10 ? "#f87171" : "#ffffff40",
          transition: "color 0.3s",
        }}>
          {fmt(timeLeft)}
        </div>

        {/* Bounces left */}
        <div style={{
          fontSize: touching ? 26 : 16,
          transition: "font-size 0.2s ease, color 0.2s",
          ...(touching ? {
            animation: "scoreRainbow 0.4s linear infinite",
            textShadow: "0 0 15px rgba(255,255,255,0.3)",
          } : { color: "#ffffff40" }),
        }}>
          {bouncesLeft} bounces left
        </div>
      </div>

      {/* Nyan Cat */}
      <div ref={catRef} style={{
        position: "absolute", top: 0, left: 0,
        pointerEvents: "none", willChange: "transform",
        transition: "scale 0.15s",
      }}>
        <img
          src="/nyancat.gif" alt="nyan"
          style={{
            width: 260, height: 180,
            imageRendering: "pixelated",
            userSelect: "none", pointerEvents: "none",
          }}
          draggable={false}
        />
      </div>

      {/* Game over overlay */}
      {gameOver && (
        <div onClick={onClose} style={{
          position: "absolute", inset: 0,
          background: "#020208ee",
          zIndex: 10,
          cursor: "pointer",
        }}>
          {/* Winner gif — pops out from center */}
          {gameOver === "win" && (
            <img
              src="/winner.gif" alt="winner"
              style={{
                position: "absolute",
                top: "50%", left: "50%",
                width: "70vw",
                maxWidth: 700,
                borderRadius: 12,
                animation: "popIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
                imageRendering: "auto",
              }}
            />
          )}

          {/* Text over the gif */}
          <div style={{
            position: "absolute",
            top: gameOver === "win" ? "12%" : "50%",
            left: "50%",
            transform: "translateX(-50%)",
            textAlign: "center",
            zIndex: 11,
          }}>
            <div style={{
              fontFamily: "'Hacked', monospace",
              fontSize: 42, letterSpacing: 6,
              color: gameOver === "win" ? "#a3e635" : "#f87171",
              textTransform: "uppercase",
              marginBottom: 8,
              animation: gameOver === "win" ? "winTextGlow 2s ease-in-out infinite" : "none",
            }}>
              {gameOver === "win" ? "you did it!" : "time's up!"}
            </div>
            <div style={{
              fontFamily: "'Hacked', monospace",
              fontSize: 13, color: "#888",
              letterSpacing: 3, marginBottom: 20,
            }}>
              {gameOver === "win"
                ? `cleared all bounces with ${fmt(timeLeft)} remaining`
                : `${bouncesLeft} bounces remaining`
              }
            </div>
            <div style={{
              fontFamily: "'Hacked', monospace",
              fontSize: 10, color: "#ffffff20",
              letterSpacing: 2, textTransform: "uppercase",
            }}>
              click anywhere to close
            </div>
          </div>
        </div>
      )}

      {/* Instructions */}
      {!gameOver && (
        <div style={{
          position: "absolute", bottom: 20, left: "50%",
          transform: "translateX(-50%)",
          color: "#ffffff12",
          fontFamily: "'Hacked', monospace",
          fontSize: 9, letterSpacing: 2, textTransform: "uppercase",
          textAlign: "center",
        }}>
          hover the cat to make it bounce | click for music | deplete all bounces to win
        </div>
      )}
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
  const [showReadme, setShowReadme] = useState(false);
  const [rainbowActive, setRainbowActive] = useState(false);
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

      {/* readme.md button */}
      <div onClick={() => setShowReadme(true)} style={{
        position: "fixed",
        top: 20,
        right: 20,
        padding: "6px 14px",
        background: "rgb(0, 82, 3)",
        border: "2px solidrgb(240, 0, 0)",
        borderRadius: 4,
        color: "#fff",
        fontFamily: "'Hacked', monospace",
        fontSize: 10,
        letterSpacing: 2,
        cursor: "pointer",
        transition: "all 0.2s",
        zIndex: 50,
      }}
        onMouseEnter={e => { e.currentTarget.style.color = "#888"; e.currentTarget.style.borderColor = "#333"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "#fff"; e.currentTarget.style.borderColor = "#1a1a1a"; }}
      >
        readme.md
      </div>

      {/* Mini terminal */}
      {showReadme && <MiniTerminal onClose={() => setShowReadme(false)} onRainbow={() => setRainbowActive(true)} />}

      {/* Rainbow mode overlay */}
      {rainbowActive && <RainbowMode onClose={() => setRainbowActive(false)} />}

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
