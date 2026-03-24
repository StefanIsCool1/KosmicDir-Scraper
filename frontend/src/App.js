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

/* ── Bouncing Ball — sucked into the black hole with spaghettification ── */
function BouncingBall({ type, onDone }) {
  const ballRef = useRef(null);
  const animRef = useRef(null);
  const state = useRef({
    x: Math.random() * (window.innerWidth - 60) + 30,
    y: window.innerHeight * 0.8,
    vx: (Math.random() > 0.5 ? 1 : -1) * (2 + Math.random() * 3),
    vy: -(6 + Math.random() * 4),
    radius: 20,
  });

  useEffect(() => {
    const s = state.current;
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    let consumed = false;

    const animate = () => {
      // Gravitational pull — inverse square, violent near center
      const dx = cx - s.x;
      const dy = cy - s.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = 18000 / (dist * dist);
      s.vx += (dx / dist) * force;
      s.vy += (dy / dist) * force;
      s.vx *= 0.997;
      s.vy *= 0.997;
      s.x += s.vx;
      s.y += s.vy;

      // Weak wall bounces — gravity wins eventually
      const d = 0.7;
      if (s.x - s.radius < 0) { s.x = s.radius; s.vx = Math.abs(s.vx) * d; }
      if (s.x + s.radius > window.innerWidth) { s.x = window.innerWidth - s.radius; s.vx = -Math.abs(s.vx) * d; }
      if (s.y - s.radius < 0) { s.y = s.radius; s.vy = Math.abs(s.vy) * d; }
      if (s.y + s.radius > window.innerHeight) { s.y = window.innerHeight - s.radius; s.vy = -Math.abs(s.vy) * d; }

      // Spaghettification — stretch toward center, shrink, fade
      const pull = Math.max(0, 1 - dist / 400);
      const scale = Math.max(0.05, 1 - pull * 0.95);
      const opacity = Math.max(0.05, 1 - pull * 1.1);
      const angle = Math.atan2(dy, dx) * (180 / Math.PI);
      const stretch = 1 + pull * 1.5;
      const squash = Math.max(0.3, scale / (stretch * 0.7));

      if (ballRef.current) {
        ballRef.current.style.transform =
          `translate(${s.x - s.radius}px, ${s.y - s.radius}px) ` +
          `rotate(${angle}deg) scale(${scale * stretch}, ${squash}) rotate(${-angle}deg)`;
        ballRef.current.style.opacity = String(opacity);
      }

      // Consumed by the void
      if (dist < 25 && !consumed) {
        consumed = true;
        if (ballRef.current) ballRef.current.style.opacity = "0";
        setTimeout(() => onDone(), 200);
        return;
      }

      animRef.current = requestAnimationFrame(animate);
    };

    animRef.current = requestAnimationFrame(animate);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [onDone]);

  const color = type === "github" ? "#2a2a30" : "#2a2a3a";
  const iconColor = type === "github" ? "#888" : "#999";

  return (
    <div ref={ballRef} style={{
      position: "fixed",
      top: 0, left: 0,
      width: state.current.radius * 2,
      height: state.current.radius * 2,
      zIndex: 1,
      pointerEvents: "none",
      willChange: "transform, opacity",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      filter: `drop-shadow(0 0 6px ${color}60)`,
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
  const historyRef = useRef([]);
  const historyIdxRef = useRef(-1);
  const savedInputRef = useRef("");

  const KNOWN_COMMANDS = [
    "cat", "ls", "pwd", "whoami", "hostname", "date", "uptime", "echo",
    "uname", "id", "clear", "exit", "quit", "help", "cd", "tree", "file",
    "wc", "head", "tail", "neofetch", "screenfetch",
  ];
  const KNOWN_FILES = ["readme.md", "rainbow_mode.sh"];
  const TAB_COMPLETIONS = [...KNOWN_COMMANDS, ...KNOWN_FILES,
    "cat readme.md", "cat rainbow_mode.sh", "./rainbow_mode.sh",
    "bash rainbow_mode.sh", "ls -la", "ls -a", "ls -l",
    "uname -a", "wc readme.md", "wc -l readme.md",
    "head readme.md", "tail readme.md", "file readme.md",
    "file rainbow_mode.sh",
  ];

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
    if (trimmed) {
      historyRef.current.push(trimmed);
      historyIdxRef.current = -1;
      savedInputRef.current = "";
    }
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
              if (e.key === "Enter") {
                handleCommand(input);
              } else if (e.key === "Tab") {
                e.preventDefault();
                const partial = input.toLowerCase();
                if (!partial) return;
                const matches = TAB_COMPLETIONS.filter(c => c.startsWith(partial) && c !== partial);
                if (matches.length === 1) {
                  setInput(matches[0]);
                } else if (matches.length > 1) {
                  // Find longest common prefix
                  let prefix = matches[0];
                  for (const m of matches) {
                    while (!m.startsWith(prefix)) prefix = prefix.slice(0, -1);
                  }
                  if (prefix.length > partial.length) {
                    setInput(prefix);
                  }
                }
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                const hist = historyRef.current;
                if (hist.length === 0) return;
                if (historyIdxRef.current === -1) {
                  savedInputRef.current = input;
                  historyIdxRef.current = hist.length - 1;
                } else if (historyIdxRef.current > 0) {
                  historyIdxRef.current--;
                }
                setInput(hist[historyIdxRef.current]);
              } else if (e.key === "ArrowDown") {
                e.preventDefault();
                const hist = historyRef.current;
                if (historyIdxRef.current === -1) return;
                if (historyIdxRef.current < hist.length - 1) {
                  historyIdxRef.current++;
                  setInput(hist[historyIdxRef.current]);
                } else {
                  historyIdxRef.current = -1;
                  setInput(savedInputRef.current);
                }
              }
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
  const hudRef = useRef(null);
  const animRef = useRef(null);
  const audioRef = useRef(null);
  const winAudioRef = useRef(null);
  const [bouncesLeft, setBouncesLeft] = useState(25);
  const [timeLeft, setTimeLeft] = useState(60);
  const [gameOver, setGameOver] = useState(null);
  const gameOverRef = useRef(false);
  const bouncesRef = useRef(25);

  const state = useRef({
    x: window.innerWidth / 2 - 60,
    y: window.innerHeight / 2 - 40,
    vx: 2, vy: 1.5, rotation: 0,
  });

  const mouseRef = useRef({ x: -999, y: -999 });

  useEffect(() => {
    const handler = (e) => { mouseRef.current = { x: e.clientX, y: e.clientY }; };
    window.addEventListener("mousemove", handler);
    return () => window.removeEventListener("mousemove", handler);
  }, []);

  // Single audio — playbackRate changed directly, no React state involved
  useEffect(() => {
    const audio = new Audio("/nyancat.mp3");
    audio.loop = true;
    audio.volume = 0.5;
    audio.preload = "auto";
    audio.load();
    audioRef.current = audio;

    const win = new Audio("/winning.mp3");
    win.preload = "auto";
    win.volume = 0.6;
    win.load();
    winAudioRef.current = win;

    audio.play().catch(() => {});
    return () => { audio.pause(); audio.src = ""; };
  }, []);

  const startAudio = useCallback(() => {
    if (audioRef.current && audioRef.current.paused) {
      audioRef.current.play().catch(() => {});
    }
  }, []);

  // Countdown timer
  useEffect(() => {
    const interval = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          clearInterval(interval);
          if (!gameOverRef.current && bouncesRef.current > 0) {
            gameOverRef.current = true;
            if (audioRef.current) audioRef.current.pause();
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

  // Game loop — ALL touch effects via direct DOM. Zero React re-renders.
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
      const isTouching = dist < (CW / 2 + 40);

      // Touch state changed 
      if (isTouching !== lastTouchState) {
        lastTouchState = isTouching;
        if (audioRef.current) audioRef.current.playbackRate = isTouching ? 1.4 : 1.0;
        if (hudRef.current) {
          hudRef.current.style.fontSize = isTouching ? "26px" : "16px";
          hudRef.current.style.color = isTouching ? "" : "#ffffff40";
          hudRef.current.style.animation = isTouching ? "scoreRainbow 0.4s linear infinite" : "none";
          hudRef.current.style.textShadow = isTouching ? "0 0 15px rgba(255,255,255,0.3)" : "none";
        }
      }

      if (isTouching) {
        const angle = Math.atan2(catCy - my, catCx - mx);
        s.vx += Math.cos(angle) * 0.8;
        s.vy += Math.sin(angle) * 0.8;
      }

      s.x += s.vx;
      s.y += s.vy;

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
          if (audioRef.current) audioRef.current.pause();
          if (winAudioRef.current) winAudioRef.current.play().catch(() => {});
          setGameOver("win");
          return;
        }
      }

      s.vx *= 0.998;
      s.vy *= 0.998;
      const speed = Math.sqrt(s.vx ** 2 + s.vy ** 2);
      if (speed < 1.5) { s.vx *= 1.5 / speed; s.vy *= 1.5 / speed; }

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          0%   { transform: translate(-50%, -50%) scale(0) rotate(0deg); opacity: 0; }
          12%  { transform: translate(-50%, -50%) scale(1.15) rotate(720deg); opacity: 1; }
          20%  { transform: translate(-50%, -50%) scale(1) rotate(720deg); }
          30%  { transform: translate(-50%, -50%) scale(1.05) rotate(900deg); }
          40%  { transform: translate(-50%, -50%) scale(1) rotate(900deg); }
          50%  { transform: translate(-50%, -50%) scale(1.1) rotate(1440deg); }
          60%  { transform: translate(-50%, -50%) scale(0.95) rotate(1440deg); }
          70%  { transform: translate(-50%, -50%) scale(1.05) rotate(1620deg); }
          80%  { transform: translate(-50%, -50%) scale(1) rotate(1620deg); }
          90%  { transform: translate(-50%, -50%) scale(1.02) rotate(1800deg); }
          100% { transform: translate(-50%, -50%) scale(1) rotate(1800deg); opacity: 1; }
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
                    "radial-gradient(ellipse at 80% 20%,rgb(63, 33, 71) 0%, transparent 50%)",
      }} />

      {/* Stars */}
      {stars.map((s, i) => (
        <div key={i} style={{
          position: "absolute",
          left: `${s.x}%`, top: `${s.y}%`,
          width: s.size, height: s.size,
          borderRadius: "50%",
          background: s.size > 2.5 ? "#e8e0ff" : "rgba(0, 42, 255, 0.15)",
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

        {/* Bounces left — styled via hudRef from game loop */}
        <div ref={hudRef} style={{
          fontSize: 16,
          color: "#ffffff40",
          transition: "font-size 0.2s ease, color 0.2s",
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
                animation: "popIn 3s ease-in-out forwards",
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
          color: "#fff",
          fontFamily: "'Hacked', monospace",
          fontSize: 15, letterSpacing: 2, textTransform: "uppercase",
          textAlign: "center",
        }}>
          hover the cat to make it bounce | click for music | WHEN THIS CAT BOUNCES ON ALL, U WIN
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────
   KOCMOC Particle System — Spiral Decay
   ─────────────────────────────────────────── */
function ParticleCanvas() {
  const canvasRef = useRef(null);
  const particles = useRef(null);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    let w = window.innerWidth, h = window.innerHeight;
    cvs.width = w; cvs.height = h;

    const cx = w / 2, cy = h / 2;
    const N = 60;

    // init particles in polar coords
    if (!particles.current) {
      particles.current = Array.from({ length: N }, () => {
        const dist = 200 + Math.random() * Math.max(w, h) * 0.6;
        return {
          angle: Math.random() * Math.PI * 2,
          dist,
          speed: 0.005 + Math.random() * 0.015,
          decay: 0.08 + Math.random() * 0.15,
          size: Math.pow(Math.floor(Math.random() * 2) + 1, 3),
          hasTrail: Math.random() < 0.3,
        };
      });
    }

    let raf;
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      const ps = particles.current;
      for (let i = 0; i < ps.length; i++) {
        const p = ps[i];
        // angular velocity increases as it gets closer (Kepler-like)
        const angularSpeed = p.speed * (400 / Math.max(p.dist, 20));
        p.angle += angularSpeed;
        p.dist -= p.decay;

        // respawn if consumed
        if (p.dist < 10) {
          p.dist = 200 + Math.random() * Math.max(w, h) * 0.5;
          p.angle = Math.random() * Math.PI * 2;
        }

        const x = cx + Math.cos(p.angle) * p.dist;
        const y = cy + Math.sin(p.angle) * p.dist;

        // color: dim gray far → brighter white close
        const t = Math.max(0, 1 - p.dist / 500);
        const v = Math.round(100 + t * 120);
        const r = v, g = v, b = v;
        const a = 0.08 + t * 0.35;

        // trail
        if (p.hasTrail && p.dist < 300) {
          const tx = cx + Math.cos(p.angle - angularSpeed * 8) * (p.dist + 6);
          const ty = cy + Math.sin(p.angle - angularSpeed * 8) * (p.dist + 6);
          ctx.beginPath();
          ctx.moveTo(x, y);
          ctx.lineTo(tx, ty);
          ctx.strokeStyle = `rgba(${r},${g},${b},${a * 0.3})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(x, y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    };

    draw();

    const onResize = () => {
      w = window.innerWidth; h = window.innerHeight;
      cvs.width = w; cvs.height = h;
    };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);

  return <canvas ref={canvasRef} style={{ position: "fixed", inset: 0, zIndex: 1, pointerEvents: "none" }} />;
}


/* ───────────────────────────────────────────
   Glitch Text — Chromatic Aberration
   ─────────────────────────────────────────── */
function GlitchText({ children, style }) {
  const [glitch, setGlitch] = useState(false);
  const [clipA, setClipA] = useState("inset(0 0 100% 0)");
  const [clipB, setClipB] = useState("inset(100% 0 0 0)");

  useEffect(() => {
    const trigger = () => {
      const y1 = Math.random() * 80;
      const y2 = y1 + 5 + Math.random() * 20;
      setClipA(`inset(${y1}% 0 ${100 - y2}% 0)`);
      setClipB(`inset(${y2}% 0 ${100 - y1 - 30}% 0)`);
      setGlitch(true);
      setTimeout(() => setGlitch(false), 100 + Math.random() * 100);
    };
    const interval = setInterval(trigger, 2000 + Math.random() * 4000);
    return () => clearInterval(interval);
  }, []);

  return (
    <span style={{ position: "relative", display: "inline-block", ...style }}>
      {children}
      {glitch && (
        <>
          <span style={{
            position: "absolute", top: 0, left: -2,
            color: "rgba(255,255,255,0.15)", clipPath: clipA,
            pointerEvents: "none",
          }}>{children}</span>
          <span style={{
            position: "absolute", top: 0, left: 2,
            color: "rgba(160,160,160,0.1)", clipPath: clipB,
            pointerEvents: "none",
          }}>{children}</span>
        </>
      )}
    </span>
  );
}


/* ───────────────────────────────────────────
   Status Bar — Bottom HUD
   ─────────────────────────────────────────── */
function StatusBar() {
  const [time, setTime] = useState("");
  const [entropy, setEntropy] = useState(99.7);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(`${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}:${String(now.getSeconds()).padStart(2,"0")}`);
      setEntropy(99.7 + Math.sin(Date.now() / 3000) * 0.25);
    };
    tick();
    const i = setInterval(tick, 1000);
    return () => clearInterval(i);
  }, []);

  const mono = { fontFamily: "'Courier New', monospace", fontSize: 9, letterSpacing: 3, textTransform: "uppercase" };

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 0, right: 0,
      height: 28, display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 20px",
      background: "#050505", borderTop: "1px solid #111",
      zIndex: 20,
    }}>
      <span style={{ ...mono, color: "rgba(80,80,80,0.4)" }}>SYS.TIME: {time}</span>
      <span style={{ ...mono, color: "rgba(120,120,120,0.2)" }}>◉ ACTIVE</span>
      <span style={{ ...mono, color: "rgba(80,80,80,0.4)" }}>ENTROPY: {entropy.toFixed(1)}%</span>
    </div>
  );
}


/* ───────────────────────────────────────────
   Main App
   ─────────────────────────────────────────── */
export default function App() {
  const [mode, setMode] = useState("auto"); // "auto" | "direct" | "csv" | "enrich"
  const [enrichFiles, setEnrichFiles] = useState([]);
  const [enrichFile, setEnrichFile] = useState("");
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
  const [showScraped, setShowScraped] = useState(false);
  const [scrapedSites, setScrapedSites] = useState([
    { domain: "agcwa.performancepublishing.net", count: 711 },
    { domain: "business.hbagbr.org", count: 747 },
    { domain: "business.uvhba.com", count: 915 },
    { domain: "contractorhub.com", count: 57 },
    { domain: "members.agc-utah.org", count: 668 },
    { domain: "members.buildingncw.org", count: 239 },
    { domain: "members.cmbaonline.org", count: 275 },
    { domain: "mnmca.com", count: 53 },
    { domain: "obd.hcraontario.ca", count: 45839 },
    { domain: "thebuildersagc.com", count: 100 },
    { domain: "www.abcwestwamembership.org", count: 334 },
    { domain: "www.agcmn.org", count: 356 },
    { domain: "www.agcwa.com", count: 711 },
    { domain: "www.bomaseattle.org", count: 609 },
    { domain: "www.hbade.org", count: 215 },
    { domain: "www.mbaks.com", count: 2381 },
    { domain: "www.mnrba.com", count: 100 },
    { domain: "www.nadra.org", count: 693 },
    { domain: "www.northstatebia.org", count: 26 },
  ]);
  const fileRef = useRef();

  const spawnBall = useCallback((type) => {
    const id = Date.now() + Math.random();
    setBalls(prev => [...prev, { id, type }]);
  }, []);

  const removeBall = useCallback((id) => {
    setBalls(prev => prev.filter(b => b.id !== id));
  }, []);

  const fetchScrapedSites = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:5000/scraped-sites");
      if (res.ok) {
        const data = await res.json();
        if (data.length > 0) setScrapedSites(data);
      }
    } catch { /* keep existing data on failure */ }
  }, []);

  // Fetch available files when switching to enrich mode
  useEffect(() => {
    if (mode === "enrich") {
      fetch("http://localhost:5000/phase2/files")
        .then(r => r.ok ? r.json() : [])
        .then(data => { if (data.length > 0) setEnrichFiles(data); })
        .catch(() => {});
    }
  }, [mode]);

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
      if (mode === "auto" || mode === "direct") {
        const res = await fetch("http://localhost:5000/scrape/single", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ link, debug: debugMode, mode }),
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

      } else if (mode === "enrich") {
        setTerminalLines([{ text: "Starting Phase 2 enrichment...", category: "SYSTEM" }]);
        const res = await fetch("http://localhost:5000/phase2/enrich", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ json_file: enrichFile }),
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
                setTerminalLines(prev => [...prev, { text: event.message, category: event.category }]);
              } else if (event.type === "complete") {
                setStatus(event.success ? "done" : "error");
                setTerminalLines(prev => [...prev, {
                  text: event.success
                    ? `Done! Enriched ${event.enriched}/${event.records} records → ${event.output_file}`
                    : "Enrichment completed with 0 results.",
                  category: "SYSTEM",
                }]);
              } else if (event.type === "error") {
                setStatus("error");
                setTerminalLines(prev => [...prev, { text: `Error: ${event.message}`, category: "ERROR" }]);
              }
            } catch { /* ignore malformed chunks */ }
          }
        }
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

  const ready = (mode === "auto" || mode === "direct") ? link.trim().length > 0
    : mode === "enrich" ? enrichFile !== ""
    : fileName !== null;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#050505",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "'Courier New', Courier, monospace",
      overflow: "hidden",
      position: "relative",
      cursor: "crosshair",
    }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::placeholder { color: rgba(80,80,80,0.4); }
        input[type=file] { display: none; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes blink { 50% { opacity: 0; } }
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
        @keyframes photonFlicker {
          0%, 100% { opacity: 0.5; box-shadow: 0 0 30px 8px rgba(255,255,255,0.06), 0 0 60px 20px rgba(255,255,255,0.03); }
          30% { opacity: 0.7; box-shadow: 0 0 40px 12px rgba(255,255,255,0.08), 0 0 80px 30px rgba(255,255,255,0.04); }
          70% { opacity: 0.35; box-shadow: 0 0 25px 6px rgba(255,255,255,0.04); }
        }
        @keyframes masterPulse {
          0%, 100% { transform: translate(-50%, -50%) scale(1.0); }
          50% { transform: translate(-50%, -50%) scale(1.03); }
        }
        @keyframes lensingPulse {
          0%, 100% { transform: translate(-50%, -50%) scale(1.0); opacity: 0.7; }
          50% { transform: translate(-50%, -50%) scale(1.08); opacity: 1; }
        }
        /* Accretion disk spins — each ring at different tilt and speed */
        @keyframes diskSpin1 { to { transform: translate(-50%,-50%) rotateX(72deg) rotate(360deg); } }
        @keyframes diskSpin2 { to { transform: translate(-50%,-50%) rotateX(74deg) rotate(-360deg); } }
        @keyframes diskSpin3 { to { transform: translate(-50%,-50%) rotateX(70deg) rotate(360deg); } }
        @keyframes diskSpin4 { to { transform: translate(-50%,-50%) rotateX(76deg) rotate(-360deg); } }
        @keyframes diskSpin5 { to { transform: translate(-50%,-50%) rotateX(73deg) rotate(360deg); } }
        @keyframes diskSpin6 { to { transform: translate(-50%,-50%) rotateX(71deg) rotate(-360deg); } }
        /* Doppler beaming — one side brighter as matter approaches observer */
        @keyframes dopplerGlow {
          0%   { box-shadow: 8px 0 25px 4px rgba(255,255,255,0.08), -8px 0 15px 2px rgba(255,255,255,0.01); }
          25%  { box-shadow: 0 8px 25px 4px rgba(255,255,255,0.08), 0 -8px 15px 2px rgba(255,255,255,0.01); }
          50%  { box-shadow: -8px 0 25px 4px rgba(255,255,255,0.08), 8px 0 15px 2px rgba(255,255,255,0.01); }
          75%  { box-shadow: 0 -8px 25px 4px rgba(255,255,255,0.08), 0 8px 15px 2px rgba(255,255,255,0.01); }
          100% { box-shadow: 8px 0 25px 4px rgba(255,255,255,0.08), -8px 0 15px 2px rgba(255,255,255,0.01); }
        }
        @keyframes scanDrift {
          0% { background-position: 0 0; }
          100% { background-position: 0 4px; }
        }
        .name-hover { transition: color 0.15s, text-shadow 0.15s; cursor: default; }
        .name-hover:hover {
          color: rgba(255,255,255,0.6) !important;
          text-shadow: 0 0 6px rgba(255,255,255,0.1);
          animation: shake 0.4s ease-in-out;
        }
        .social-link {
          transition: transform 0.2s ease, color 0.2s ease;
          display: inline-flex; align-items: center; gap: 6px;
        }
        .social-link:hover { transform: scale(1.15); }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background:rgb(75, 75, 75); border-radius: 2px; }
      `}</style>

      {/* ── BLACK HOLE ── */}
      <div style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}>

        {/* Gravitational Lensing Glow (outermost) */}
        <div style={{
          position: "absolute", top: "50%", left: "50%",
          width: "80vmin", height: "80vmin", borderRadius: "50%",
          background: "radial-gradient(circle, transparent 35%, rgba(255,255,255,0.02) 50%, rgba(200,200,200,0.015) 65%, transparent 85%)",
          animation: "lensingPulse 4s ease-in-out infinite",
        }} />

        {/* Master pulse container — heartbeat */}
        <div style={{
          position: "absolute", top: "50%", left: "50%",
          width: 0, height: 0,
          animation: "masterPulse 5.5s ease-in-out infinite",
        }}>

          {/* === ACCRETION DISK — layered for depth === */}

          {/* Outer glow haze — soft wide disk halo */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            width: 600, height: 600, borderRadius: "50%",
            transform: "translate(-50%, -50%) rotateX(73deg)",
            background: "radial-gradient(ellipse, transparent 30%, rgba(255,255,255,0.015) 50%, rgba(200,200,220,0.01) 65%, transparent 80%)",
            filter: "blur(8px)",
          }} />

          {/* Disk rings — static, no spinning. Subtle concentric halos */}
          {[
            { size: 520, w: 1, color: "rgba(180,180,200,0.015)", blur: 6 },
            { size: 460, w: 1, color: "rgba(200,200,220,0.025)", blur: 4 },
            { size: 400, w: 1, color: "rgba(210,210,230,0.035)", blur: 3 },
            { size: 340, w: 1.5, color: "rgba(230,230,240,0.05)", blur: 1 },
            { size: 290, w: 1.5, color: "rgba(240,240,250,0.07)", blur: 0 },
            { size: 250, w: 1.5, color: "rgba(255,255,255,0.09)", blur: 0 },
          ].map((ring, i) => (
            <div key={i} style={{
              position: "absolute", top: "50%", left: "50%",
              width: ring.size, height: ring.size, borderRadius: "50%",
              border: `${ring.w}px solid ${ring.color}`,
              background: "transparent",
              transform: "translate(-50%, -50%) rotateX(73deg)",
              filter: ring.blur ? `blur(${ring.blur}px)` : "none",
            }} />
          ))}

          {/* === PHOTON RING — last light orbit === */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            width: 185, height: 185, borderRadius: "50%",
            border: "1.5px solid rgba(255,255,255,0.12)",
            background: "transparent",
            animation: "photonFlicker 2.5s ease-in-out infinite",
          }} />

          {/* === BLACK HOLE SHADOW — dark region that occludes the back half of the disk === */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            width: 175, height: 175, borderRadius: "50%",
            background: "radial-gradient(circle, #000 55%, rgba(0,0,0,0.95) 70%, rgba(0,0,0,0.6) 85%, transparent 100%)",
            boxShadow: "0 0 60px 25px #000, 0 0 100px 40px rgba(0,0,0,0.7), 0 0 150px 60px rgba(0,0,0,0.3)",
            zIndex: 1,
          }} />

          {/* === EVENT HORIZON — true black, nothing escapes === */}
          <div style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)",
            width: 140, height: 140, borderRadius: "50%",
            background: "#000000",
            boxShadow: "0 0 30px 10px #000, 0 0 60px 25px rgba(0,0,0,0.9)",
            zIndex: 2,
          }} />
        </div>
      </div>

      {/* ── Particle System ── */}
      <ParticleCanvas />

      {/* ── Atmospheric Overlays ── */}
      {/* Vignette */}
      <div style={{
        position: "fixed", inset: 0, zIndex: 15, pointerEvents: "none",
        background: "radial-gradient(circle at center, transparent 30%, rgba(0,0,0,0.6) 100%)",
      }} />
      {/* Scan lines */}
      <div style={{
        position: "fixed", inset: 0, zIndex: 16, pointerEvents: "none",
        backgroundImage: "repeating-linear-gradient(0deg, transparent 0px, transparent 2px, rgba(0,0,0,0.06) 2px, rgba(0,0,0,0.06) 4px)",
        animation: "scanDrift 0.5s steps(2) infinite",
      }} />
      {/* (no red pulse — pure void) */}

      {/* ── Main Card ── */}
      <div style={{
        position: "relative", zIndex: 10,
        width: 460, maxWidth: "88vw",
      }}>
        <div style={{
          background: "rgba(10,10,14,0.88)",
          border: "1px solid rgba(200,200,200,0.18)",
          borderRadius: 2,
          padding: "32px 28px 28px",
          backdropFilter: "blur(12px)",
          boxShadow: "0 0 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(200,200,200,0.02)",
        }}>

          {/* Title */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              fontSize: 9, color: "rgba(200,200,200,0.45)", letterSpacing: 6,
              textTransform: "uppercase", marginBottom: 6,
            }}>
              UnderDeck
            </div>
            <GlitchText style={{
              fontSize: 14, color: "rgba(220,220,220,0.75)", fontWeight: "bold",
              letterSpacing: 10, textTransform: "uppercase",
            }}>
              SCRAPER BOT
            </GlitchText>
          </div>

          {/* Mode Tabs */}
          <div style={{
            display: "flex", marginBottom: 20,
            borderBottom: "1px solid rgba(200,200,200,0.04)",
          }}>
            {[
              { key: "auto", label: "Auto Discover" },
              { key: "direct", label: "Direct Scrape" },
              { key: "csv", label: "CSV" },
              { key: "enrich", label: "Phase 2" },
            ].map((tab) => (
              <button key={tab.key} onClick={() => setMode(tab.key)} style={{
                flex: 1, padding: "9px 0", border: "none",
                fontFamily: "'Courier New', monospace", fontSize: 9,
                letterSpacing: 3, textTransform: "uppercase",
                cursor: "pointer", transition: "all 0.2s",
                background: "transparent",
                color: mode === tab.key ? "rgba(220,220,220,0.8)" : "rgba(150,150,150,0.4)",
                position: "relative",
                borderBottom: mode === tab.key ? "1px solid rgba(220,220,220,0.5)" : "1px solid transparent",
                marginBottom: -1,
              }}>
                {tab.label}
              </button>
            ))}
          </div>

          {/* Auto Discover Input */}
          {mode === "auto" && (
            <div>
              <div style={{ fontSize: 9, color: "rgba(180,180,180,0.7)", letterSpacing: 3, textTransform: "uppercase", marginBottom: 8 }}>
                Target URL
              </div>
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://example-association.org"
                autoFocus
                style={{
                  width: "100%", background: "rgba(0,0,0,0.4)", border: "1px solid rgba(200,200,200,0.05)",
                  borderRadius: 2, color: "rgba(220,220,220,0.85)", fontFamily: "'Courier New', monospace",
                  fontSize: 11, padding: "11px 12px", outline: "none",
                  transition: "border-color 0.3s",
                }}
                onFocus={e => e.target.style.borderColor = "rgba(200,200,200,0.2)"}
                onBlur={e => e.target.style.borderColor = "rgba(200,200,200,0.05)"}
              />
              <div style={{ fontSize: 8, color: "rgba(140,140,140,0.5)", marginTop: 5, letterSpacing: 2, textTransform: "uppercase" }}>
                bot navigates to find the directory page
              </div>
            </div>
          )}

          {/* Direct Scrape Input */}
          {mode === "direct" && (
            <div>
              <div style={{ fontSize: 9, color: "rgba(180,180,180,0.7)", letterSpacing: 3, textTransform: "uppercase", marginBottom: 8 }}>
                Directory Page URL
              </div>
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://members.example.org/directory?search=all"
                autoFocus
                style={{
                  width: "100%", background: "rgba(0,0,0,0.4)", border: "1px solid rgba(200,200,200,0.05)",
                  borderRadius: 2, color: "rgba(220,220,220,0.85)", fontFamily: "'Courier New', monospace",
                  fontSize: 11, padding: "11px 12px", outline: "none",
                  transition: "border-color 0.3s",
                }}
                onFocus={e => e.target.style.borderColor = "rgba(200,200,200,0.2)"}
                onBlur={e => e.target.style.borderColor = "rgba(200,200,200,0.05)"}
              />
              <div style={{ fontSize: 8, color: "rgba(140,140,140,0.5)", marginTop: 5, letterSpacing: 2, textTransform: "uppercase" }}>
                skips navigation — scrapes page as-is
              </div>
            </div>
          )}

          {/* CSV Upload */}
          {mode === "csv" && (
            <div>
              <div style={{ fontSize: 9, color: "rgba(180,180,180,0.7)", letterSpacing: 3, textTransform: "uppercase", marginBottom: 8 }}>
                Upload CSV
              </div>
              <div onClick={() => fileRef.current.click()} style={{
                border: "1px dashed rgba(200,200,200,0.06)", borderRadius: 2, padding: "22px",
                textAlign: "center", cursor: "pointer",
                transition: "border-color 0.2s",
              }}>
                <input type="file" accept=".csv" ref={fileRef} onChange={handleFile} />
                {fileName
                  ? <div style={{ color: "rgba(200,200,200,0.6)", fontSize: 10, letterSpacing: 2 }}>{fileName}</div>
                  : <div style={{ color: "rgba(80,80,80,0.3)", fontSize: 9, letterSpacing: 2 }}>SELECT .CSV FILE</div>
                }
              </div>
            </div>
          )}

          {/* Phase 2 Enrich */}
          {mode === "enrich" && (
            <div>
              <div style={{ fontSize: 9, color: "rgba(180,180,180,0.7)", letterSpacing: 3, textTransform: "uppercase", marginBottom: 8 }}>
                Select Structured JSON
              </div>
              <select
                value={enrichFile}
                onChange={(e) => setEnrichFile(e.target.value)}
                style={{
                  width: "100%",
                  background: "rgba(255,255,255,0.02)",
                  border: "1px solid rgba(200,200,200,0.06)",
                  borderRadius: 2, color: "rgba(200,200,200,0.6)",
                  fontFamily: "'Courier New', monospace", fontSize: 10,
                  padding: "10px 8px", outline: "none",
                  letterSpacing: 1,
                }}
              >
                <option value="" style={{ background: "#0a0a0a" }}>— select file —</option>
                {enrichFiles.map((f) => (
                  <option key={f.file} value={f.file} style={{ background: "#0a0a0a" }}>
                    {f.file.replace("_structured.json", "")} — {f.count} records, {f.with_website} with website
                  </option>
                ))}
              </select>

              {/* Stats for selected file */}
              {enrichFile && (() => {
                const sel = enrichFiles.find(f => f.file === enrichFile);
                if (!sel) return null;
                const stats = [
                  { label: "HAVE WEBSITE", val: sel.with_website, total: sel.count, good: true },
                  { label: "MISSING DESC", val: sel.missing_desc, total: sel.with_website },
                  { label: "MISSING PHONE", val: sel.missing_phone, total: sel.with_website },
                  { label: "MISSING EMAIL", val: sel.missing_email, total: sel.with_website },
                  { label: "MISSING ADDR", val: sel.missing_addr, total: sel.with_website },
                ];
                return (
                  <div style={{ marginTop: 12, padding: "10px 12px", background: "rgba(255,255,255,0.015)", border: "1px solid rgba(200,200,200,0.04)", borderRadius: 2 }}>
                    <div style={{ fontSize: 8, color: "rgba(180,180,180,0.5)", letterSpacing: 3, textTransform: "uppercase", marginBottom: 8 }}>
                      Enrichment Potential
                    </div>
                    {stats.map((s, i) => (
                      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 9, color: "rgba(180,180,180,0.5)", letterSpacing: 2, fontFamily: "'Courier New', monospace" }}>
                          {s.label}
                        </span>
                        <span style={{
                          fontSize: 9, letterSpacing: 1, fontFamily: "'Courier New', monospace",
                          color: s.good ? "rgba(160,230,120,0.7)" : s.val > 0 ? "rgba(220,180,100,0.7)" : "rgba(100,100,100,0.3)",
                        }}>
                          {s.val}/{s.total}
                        </span>
                      </div>
                    ))}
                    <div style={{ fontSize: 8, color: "rgba(120,120,120,0.35)", letterSpacing: 1, marginTop: 8, fontFamily: "'Courier New', monospace", lineHeight: 1.5 }}>
                      Phase 2 visits each website to find: description, phone, email, address, social media, hours, services, team, founding year
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* Debug + Run Row */}
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 18 }}>
            <label style={{
              display: "flex", alignItems: "center", gap: 6,
              cursor: "pointer", userSelect: "none", flexShrink: 0,
            }}>
              <div onClick={() => setDebugMode(!debugMode)} style={{
                width: 12, height: 12,
                border: `1px solid ${debugMode ? "rgba(200,200,200,0.5)" : "rgba(200,200,200,0.08)"}`,
                borderRadius: 1, background: debugMode ? "rgba(200,200,200,0.15)" : "transparent",
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "all 0.15s", cursor: "pointer",
              }}>
                {debugMode && <span style={{ color: "rgba(200,200,200,0.8)", fontSize: 9, fontWeight: "bold", lineHeight: 1 }}>✓</span>}
              </div>
              <span style={{ color: "rgba(150,150,150,0.6)", fontSize: 8, letterSpacing: 3, textTransform: "uppercase" }}>
                Debug
              </span>
            </label>

            <button onClick={handleRun} disabled={!ready || status === "running"} style={{
              flex: 1, padding: "10px",
              background: ready && status !== "running" ? "rgba(220,220,220,0.12)" : "transparent",
              color: ready && status !== "running" ? "rgba(220,220,220,0.75)" : "rgba(100,100,100,0.3)",
              border: `1px solid ${ready && status !== "running" ? "rgba(220,220,220,0.25)" : "rgba(200,200,200,0.06)"}`,
              borderRadius: 2,
              fontFamily: "'Courier New', monospace", fontSize: 9, letterSpacing: 4,
              textTransform: "uppercase", fontWeight: "bold",
              cursor: ready && status !== "running" ? "pointer" : "not-allowed",
              transition: "all 0.3s",
            }}>
              {status === "running" ? "TRANSMITTING..." : mode === "enrich" ? "ENRICH" : mode === "direct" ? "EXTRACT" : "INITIATE"}
            </button>
          </div>

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
              marginTop: 12, padding: "8px 12px", borderRadius: 2,
              fontSize: 9, letterSpacing: 2, textTransform: "uppercase",
              background: status === "done" ? "rgba(200,200,200,0.05)" : "rgba(200,200,200,0.07)",
              color: status === "done" ? "rgba(200,200,200,0.65)" : "rgba(220,180,180,0.7)",
              border: `1px solid ${status === "done" ? "rgba(200,200,200,0.1)" : "rgba(200,200,200,0.15)"}`,
            }}>
              {status === "done" && "TRANSMISSION COMPLETE — CHECK DATA-DUMP"}
              {status === "error" && "██████ SIGNAL LOST ██████"}
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

      {/* Scraped Sites button */}
      <div onClick={() => { setShowScraped(s => !s); if (!showScraped) fetchScrapedSites(); }} style={{
        position: "fixed", top: 16, right: 110,
        padding: "4px 10px",
        background: "rgba(8,8,10,0.8)",
        border: "1px solid rgba(200,200,200,0.04)",
        borderRadius: 1,
        color: "rgba(80,80,80,0.4)",
        fontFamily: "'Courier New', monospace",
        fontSize: 8, letterSpacing: 3, textTransform: "uppercase",
        cursor: "pointer", transition: "all 0.3s",
        zIndex: 50,
      }}
        onMouseEnter={e => { e.currentTarget.style.color = "rgba(200,200,200,0.5)"; e.currentTarget.style.borderColor = "rgba(200,200,200,0.15)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "rgba(80,80,80,0.4)"; e.currentTarget.style.borderColor = "rgba(200,200,200,0.04)"; }}
      >
        LOG [{scrapedSites.length || "·"}]
      </div>

      {/* Scraped Sites panel */}
      {showScraped && (
        <div style={{
          position: "fixed", top: 38, right: 110,
          width: 280, maxHeight: "55vh",
          background: "rgba(8,8,10,0.95)", border: "1px solid rgba(200,200,200,0.04)",
          borderRadius: 2, overflow: "hidden",
          zIndex: 100, fontFamily: "'Courier New', monospace",
        }}>
          <div style={{
            padding: "8px 12px", borderBottom: "1px solid rgba(200,200,200,0.03)",
            fontSize: 8, letterSpacing: 3, color: "rgba(80,80,80,0.4)",
            textTransform: "uppercase",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span>TRANSMISSION LOG</span>
            <span onClick={() => setShowScraped(false)} style={{ cursor: "pointer", color: "rgba(80,80,80,0.3)", fontSize: 12 }}>×</span>
          </div>
          <div style={{ overflowY: "auto", maxHeight: "calc(55vh - 32px)", padding: "2px 0" }}>
            {scrapedSites.length === 0 && (
              <div style={{ padding: "16px 12px", color: "rgba(80,80,80,0.2)", fontSize: 8, textAlign: "center", letterSpacing: 2 }}>
                NO TRANSMISSIONS RECORDED
              </div>
            )}
            {scrapedSites.map((site, i) => (
              <div key={i} style={{
                padding: "6px 12px", borderBottom: "1px solid rgba(200,200,200,0.02)",
                display: "flex", justifyContent: "space-between", alignItems: "center",
                transition: "background 0.15s", cursor: "default",
              }}
                onMouseEnter={e => e.currentTarget.style.background = "rgba(200,200,200,0.02)"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              >
                <span style={{ color: "rgba(140,140,140,0.3)", fontSize: 8, letterSpacing: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 190 }}>
                  {site.domain}
                </span>
                <span style={{ color: site.count > 0 ? "rgba(200,200,200,0.4)" : "rgba(200,200,200,0.2)", fontSize: 8, letterSpacing: 1, flexShrink: 0 }}>
                  {site.count > 0 ? site.count : "NULL"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div onClick={() => setShowReadme(true)} style={{
        position: "fixed", top: 16, right: 16,
        padding: "4px 10px",  
        background: "rgba(8,8,10,0.8)",
        border: "1px solid rgba(200,200,200,0.04)",
        borderRadius: 1,
        color: "rgba(80,80,80,0.4)",
        fontFamily: "'Courier New', monospace",
        fontSize: 8, letterSpacing: 3, textTransform: "uppercase",
        cursor: "pointer", transition: "all 0.3s",
        zIndex: 50,
      }}
        onMouseEnter={e => { e.currentTarget.style.color = "rgba(200,200,200,0.5)"; e.currentTarget.style.borderColor = "rgba(200,200,200,0.15)"; }}
        onMouseLeave={e => { e.currentTarget.style.color = "rgba(80,80,80,0.4)"; e.currentTarget.style.borderColor = "rgba(200,200,200,0.04)"; }}
      >
        readme.md
      </div>

      {/* Mini terminal */}
      {showReadme && <MiniTerminal onClose={() => setShowReadme(false)} onRainbow={() => setRainbowActive(true)} />}

      {/* Rainbow mode overlay */}
      {rainbowActive && <RainbowMode onClose={() => setRainbowActive(false)} />}

      {/* Status Bar */}
      <StatusBar />

      {/* Credits — above status bar */}
      <div style={{
        position: "fixed", bottom: 32, left: 0, right: 0,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 5,
        fontFamily: "'Courier New', monospace", zIndex: 18, pointerEvents: "none",
      }}>
        <div style={{ fontSize: 8, letterSpacing: 4, color: "rgba(80,80,80,0.2)", textTransform: "uppercase" }}>
          built by{" "}
          <span className="name-hover" style={{ color: "rgba(140,140,140,0.25)", pointerEvents: "auto" }}>
            Stefan O'Leary
          </span>
        </div>
        <div style={{ display: "flex", gap: 14, alignItems: "center", pointerEvents: "auto" }}>
          <a href="https://github.com/StefanIsCool1/UnderDeckScraper" target="_blank" rel="noopener noreferrer"
            className="social-link"
            style={{ color: "rgba(80,80,80,0.25)", fontSize: 8, letterSpacing: 3, textDecoration: "none", textTransform: "uppercase" }}
            onMouseEnter={e => { e.currentTarget.style.color = "rgba(200,200,200,0.5)"; spawnBall("github"); }}
            onMouseLeave={e => { e.currentTarget.style.color = "rgba(80,80,80,0.25)"; }}
          >
            <GitHubIcon size={11} color="currentColor" />
            GitHub
          </a>
          <span style={{ color: "rgba(80,80,80,0.1)" }}>·</span>
          <a href="https://www.linkedin.com/in/stefan-o%27leary-b94079361" target="_blank" rel="noopener noreferrer"
            className="social-link"
            style={{ color: "rgba(80,80,80,0.25)", fontSize: 8, letterSpacing: 3, textDecoration: "none", textTransform: "uppercase" }}
            onMouseEnter={e => { e.currentTarget.style.color = "rgba(200,200,200,0.4)"; spawnBall("linkedin"); }}
            onMouseLeave={e => { e.currentTarget.style.color = "rgba(80,80,80,0.25)"; }}
          >
            <LinkedInIcon size={11} color="currentColor" />
            LinkedIn
          </a>
        </div>
      </div>
    </div>
  );
}
