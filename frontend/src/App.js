import { useState, useRef } from "react";

export default function App() {
  const [mode, setMode] = useState("link"); // "link" | "csv"
  const [link, setLink] = useState("");
  const [fileName, setFileName] = useState(null);
  const [status, setStatus] = useState(null); // null | "running" | "done" | "error"
  const fileRef = useRef();

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (f) setFileName(f.name);
  };

 const handleRun = async () => {
  console.log("RUN CLICKED");
  setStatus("running");

  try {
    if (mode === "link") {
      const res = await fetch("http://localhost:5000/scrape/single", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ link }),
      });
      setStatus("done");
      const data = await res.json();
      setStatus(data.success ? "done" : "error");
    }

    if (mode === "csv") {
      const form = new FormData();
      form.append("file", fileRef.current.files[0]);

      const res = await fetch("http://localhost:5000/scrape/csv", {
        method: "POST",
        body: form,
      });

      // CSV route streams events, so you can't just res.json()
      // For now, treat it as success when the request completes.
      setStatus("done");
    }
  } catch (err) {
    setStatus("error");
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
        .rainbow-wrapper {
          position: relative;
          width: 446px;
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
                flex: 1,
                padding: "10px 0",
                background: mode === m ? "#fff" : "transparent",
                color: mode === m ? "#0f0f0f" : "#555",
                border: "none",
                fontFamily: "monospace",
                fontSize: 11,
                letterSpacing: 2,
                textTransform: "uppercase",
                cursor: "pointer",
                transition: "all 0.15s",
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
                  width: "100%",
                  background: "#111",
                  border: "1px solid #2a2a2a",
                  borderRadius: 4,
                  color: "#fff",
                  fontFamily: "monospace",
                  fontSize: 13,
                  padding: "12px 14px",
                  outline: "none",
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
                border: "1px dashed #2a2a2a",
                borderRadius: 4,
                padding: "28px",
                textAlign: "center",
                cursor: "pointer",
                transition: "border-color 0.2s",
              }}>
                <input type="file" accept=".csv" ref={fileRef} onChange={handleFile} />
                {fileName ? (
                  <div style={{ color: "#a3e635", fontSize: 12 }}>📄 {fileName}</div>
                ) : (
                  <div style={{ color: "#555", fontSize: 11, letterSpacing: 1 }}>PLS UPLOAD .csv {">"}:) </div>
                )}
              </div>
            </div>
          )}

          {/* Status */}
          {status && (
            <div style={{
              marginTop: 20,
              padding: "10px 14px",
              borderRadius: 4,
              fontSize: 11,
              letterSpacing: 1,
              background: status === "running" ? "#1a1a00" : status === "done" ? "#0a1a0a" : "#1a0a0a",
              color: status === "running" ? "#facc15" : status === "done" ? "#a3e635" : "#f87171",
              border: `1px solid ${status === "running" ? "#facc1530" : status === "done" ? "#a3e63530" : "#f8717130"}`,
            }}>
              {status === "running" && "Stefan bot is currently scrapping your dreams way"}
              {status === "done" && "YAY :)))))). DONE!, check the Data-dump folder"}
              {status === "error" && "❌ Something went wrong, or unable to scrap."}
            </div>
          )}

          {/* Run Button */}
          <button onClick={handleRun} disabled={!ready || status === "running"} style={{
            width: "100%",
            marginTop: 20,
            padding: "14px",
            background: ready && status !== "running" ? "#a3e635" : "#1a1a1a",
            color: ready && status !== "running" ? "#0f0f0f" : "#333",
            border: "1px solid #2a2a2a",
            borderRadius: 4,
            fontFamily: "monospace",
            fontSize: 11,
            letterSpacing: 3,
            textTransform: "uppercase",
            fontWeight: "bold",
            cursor: ready && status !== "running" ? "pointer" : "not-allowed",
            transition: "all 0.15s",
          }}>
            {status === "running" ? "Running..." : "run scrap →"}
          </button>

        </div>
      </div>
    </div>
  );
}