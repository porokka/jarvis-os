"use client";

import { useState, useEffect } from "react";

interface Timer {
  id: number;
  message: string;
  remaining: number;
  total: number;
}

function formatTime(seconds: number): string {
  if (seconds <= 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TimersWidget() {
  const [timers, setTimers] = useState<Timer[]>([]);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("/api/timers", { cache: "no-store" });
        const data = await res.json();
        if (active && Array.isArray(data.timers)) {
          setTimers(data.timers);
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 1000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Client-side countdown between polls
  useEffect(() => {
    if (timers.length === 0) return;
    const id = setInterval(() => {
      setTimers(prev => prev.map(t => ({
        ...t,
        remaining: Math.max(0, t.remaining - 1),
      })).filter(t => t.remaining > 0));
    }, 1000);
    return () => clearInterval(id);
  }, [timers.length]);

  if (timers.length === 0) return null;

  return (
    <div className="timers-widget">
      <div className="timers-header">
        <span className="timers-dot" />
        ACTIVE TIMERS
      </div>
      {timers.map((t) => {
        const pct = t.total > 0 ? ((t.total - t.remaining) / t.total) * 100 : 0;
        const urgent = t.remaining < 60;
        return (
          <div key={t.id} className={`timer-item ${urgent ? "urgent" : ""}`}>
            <div className="timer-top">
              <span className="timer-msg">{t.message}</span>
              <span className="timer-time">{formatTime(t.remaining)}</span>
            </div>
            <div className="timer-bar">
              <div className="timer-bar-fill" style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}

      <style jsx>{`
        .timers-widget {
          padding: 8px 0;
        }
        .timers-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 8px;
          letter-spacing: 3px;
          text-transform: uppercase;
          color: var(--accent);
          opacity: 0.4;
          margin-bottom: 8px;
        }
        .timers-dot {
          width: 4px;
          height: 4px;
          border-radius: 50%;
          background: #f0c040;
          animation: timer-pulse 1s ease-in-out infinite;
        }
        .timer-item {
          margin-bottom: 8px;
        }
        .timer-item.urgent {
          animation: urgent-flash 1s ease-in-out infinite;
        }
        .timer-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 3px;
        }
        .timer-msg {
          font-size: 10px;
          color: rgba(255, 255, 255, 0.6);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 180px;
        }
        .timer-time {
          font-size: 13px;
          font-family: 'SF Mono', 'Cascadia Code', monospace;
          color: #f0c040;
          font-weight: 600;
          letter-spacing: 1px;
        }
        .timer-item.urgent .timer-time {
          color: #f04040;
        }
        .timer-bar {
          height: 2px;
          background: rgba(255, 255, 255, 0.06);
          border-radius: 1px;
          overflow: hidden;
        }
        .timer-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--accent), #f0c040);
          border-radius: 1px;
          transition: width 1s linear;
        }
        .timer-item.urgent .timer-bar-fill {
          background: linear-gradient(90deg, #f04040, #f0c040);
        }
        @keyframes timer-pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; box-shadow: 0 0 4px #f0c040; }
        }
        @keyframes urgent-flash {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
      `}</style>
    </div>
  );
}
