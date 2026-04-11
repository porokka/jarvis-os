"use client";

import { useState, useEffect, useRef } from "react";

function classifyLine(text: string): string {
  if (text.includes("HEARD:")) return "log-heard";
  if (text.includes("SAID:")) return "log-said";
  if (text.includes("Router") || text.includes("Ollama") || text.includes("TTS")) return "log-route";
  if (text.includes("Tool:") || text.includes("REACT") || text.includes("Planner")) return "log-tool";
  if (text.includes("WAKE:")) return "log-wake";
  if (text.includes("Error") || text.includes("WARN")) return "log-error";
  if (text.includes("Ready.")) return "log-ready";
  return "log-default";
}

export function SystemLog() {
  const [lines, setLines] = useState<string[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [lastLine, setLastLine] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("/api/logs", { cache: "no-store" });
        const data = await res.json();
        if (active && Array.isArray(data.lines)) {
          const last = data.lines[data.lines.length - 1] || "";
          if (last !== lastLine) {
            setLines(data.lines);
            setLastLine(last);
          }
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 1000);
    return () => { active = false; clearInterval(id); };
  }, [lastLine]);

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, expanded]);

  const visibleLines = expanded ? lines : lines.slice(-8);

  return (
    <div
      className={`system-log ${expanded ? "expanded" : ""}`}
      onClick={() => setExpanded((e) => !e)}
    >
      {/* Holographic header */}
      <div className="log-header">
        <span className="log-header-dot" />
        <span>SYSTEM LOG</span>
        <span className="log-header-count">{lines.length}</span>
      </div>

      {/* Log lines */}
      <div ref={scrollRef} className={`log-content ${expanded ? "log-expanded" : ""}`}>
        {visibleLines.length === 0 ? (
          <div className="log-empty">AWAITING DATA STREAM</div>
        ) : (
          visibleLines.map((line, i) => {
            const age = visibleLines.length - 1 - i;
            const cls = classifyLine(line);
            return (
              <div
                key={`${i}-${line.slice(0, 20)}`}
                className={`log-line ${cls}`}
                style={{
                  opacity: expanded ? 0.8 : Math.max(0.05, 1 - age * 0.18),
                  animationDelay: `${i * 0.05}s`,
                }}
              >
                {line}
              </div>
            );
          })
        )}
      </div>

      {/* Expand hint */}
      <div className="log-hint">
        {expanded ? "COLLAPSE" : "EXPAND"}
      </div>

      <style jsx>{`
        .system-log {
          position: relative;
          width: 100%;
          cursor: pointer;
          user-select: none;
        }

        .log-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 8px;
          letter-spacing: 3px;
          text-transform: uppercase;
          color: var(--accent);
          opacity: 0.3;
          padding: 4px 0;
          margin-bottom: 4px;
        }

        .log-header-dot {
          width: 4px;
          height: 4px;
          border-radius: 50%;
          background: var(--accent);
          animation: dot-pulse 2s ease-in-out infinite;
        }

        .log-header-count {
          margin-left: auto;
          opacity: 0.5;
          font-size: 7px;
        }

        .log-content {
          font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
          font-size: 9px;
          line-height: 1.7;
          overflow: hidden;
          max-height: 160px;
          mask-image: linear-gradient(to bottom, transparent 0%, black 15%, black 85%, transparent 100%);
          -webkit-mask-image: linear-gradient(to bottom, transparent 0%, black 15%, black 85%, transparent 100%);
        }

        .log-content.log-expanded {
          overflow-y: auto;
          max-height: 500px;
          mask-image: none;
          -webkit-mask-image: none;
        }

        .log-content.log-expanded::-webkit-scrollbar {
          width: 2px;
        }
        .log-content.log-expanded::-webkit-scrollbar-thumb {
          background: rgba(64, 160, 240, 0.2);
        }

        .log-line {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          padding: 1px 0;
          animation: line-in 0.3s ease-out;
        }

        .log-heard { color: #40f060; }
        .log-said { color: #40a0f0; }
        .log-route { color: #f0c040; }
        .log-tool { color: #c060f0; }
        .log-wake { color: #f07040; }
        .log-error { color: #f04040; }
        .log-ready { color: #304050; }
        .log-default { color: rgba(255, 255, 255, 0.2); }

        .log-empty {
          color: var(--accent);
          opacity: 0.15;
          text-align: center;
          letter-spacing: 3px;
          font-size: 8px;
          padding: 20px 0;
        }

        .log-hint {
          font-size: 7px;
          letter-spacing: 2px;
          text-align: right;
          color: var(--accent);
          opacity: 0.15;
          padding-top: 4px;
        }

        .system-log.expanded {
          background: rgba(0, 8, 20, 0.6);
          border: 1px solid rgba(64, 160, 240, 0.08);
          border-radius: 4px;
          padding: 8px 10px;
          backdrop-filter: blur(8px);
        }

        @keyframes dot-pulse {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 1; box-shadow: 0 0 6px var(--accent); }
        }

        @keyframes line-in {
          from { opacity: 0; transform: translateX(10px); }
          to { opacity: inherit; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
