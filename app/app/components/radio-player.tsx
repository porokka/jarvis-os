"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface RadioState {
  playing: boolean;
  station: string | null;
  label: string | null;
  stream_url: string | null;
  stations: Record<string, { label: string; type: string }>;
}

export function RadioPlayer() {
  const [radio, setRadio] = useState<RadioState>({
    playing: false,
    station: null,
    label: null,
    stream_url: null,
    stations: {},
  });
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastUrlRef = useRef<string | null>(null);

  // Poll radio state from ReAct server
  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("/api/radio", { cache: "no-store" });
        const data = await res.json();
        if (active) setRadio(data);
      } catch {}
    }

    poll();
    const id = setInterval(poll, 3000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Sync audio element with radio state
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (radio.playing && radio.stream_url) {
      if (radio.stream_url !== lastUrlRef.current) {
        // New station — load and play
        audio.src = radio.stream_url;
        audio.load();
        audio.play().catch(() => {});
        lastUrlRef.current = radio.stream_url;
        setAudioPlaying(true);
      }
    } else if (!radio.playing && lastUrlRef.current) {
      // Stopped
      audio.pause();
      audio.src = "";
      lastUrlRef.current = null;
      setAudioPlaying(false);
    }
  }, [radio.playing, radio.stream_url]);

  // Send command to JARVIS via input bridge
  const sendCommand = useCallback(async (command: string) => {
    try {
      await fetch("/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: command }),
      });
    } catch {}
  }, []);

  const handleStop = () => {
    // Stop locally immediately
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
    }
    lastUrlRef.current = null;
    setAudioPlaying(false);
    setRadio(prev => ({ ...prev, playing: false, station: null, label: null, stream_url: null }));
    sendCommand("stop radio");
  };

  const handlePlay = (station: string) => {
    sendCommand(`play ${station} radio`);
  };

  const stationList = Object.entries(radio.stations || {});

  return (
    <div className="radio-player">
      {/* Hidden audio element */}
      <audio ref={audioRef} crossOrigin="anonymous" />

      {/* Header */}
      <div className="radio-header" onClick={() => setExpanded(!expanded)}>
        <span className={`radio-dot ${audioPlaying ? "active" : ""}`} />
        <span className="radio-title">RADIO</span>
        <span className="radio-expand">{expanded ? "\u25B4" : "\u25BE"}</span>
      </div>

      {/* Now playing */}
      {radio.playing && radio.label && (
        <div className="radio-now-playing">
          <div className="radio-eq">
            <span className="eq-bar" />
            <span className="eq-bar" />
            <span className="eq-bar" />
          </div>
          <span className="radio-station-name">{radio.label}</span>
          <button className="radio-stop" onClick={handleStop} title="Stop">
            &#9632;
          </button>
        </div>
      )}

      {!radio.playing && (
        <div className="radio-offline">
          <span className="text-[9px] tracking-[1px] opacity-30">NO STATION</span>
        </div>
      )}

      {/* Station list */}
      {expanded && (
        <div className="radio-stations">
          {stationList.map(([key, info]) => (
            <button
              key={key}
              className={`radio-station-btn ${radio.station === key ? "active" : ""}`}
              onClick={() => handlePlay(key)}
            >
              {info.label}
            </button>
          ))}
        </div>
      )}

      <style jsx>{`
        .radio-player {
          padding: 0;
        }
        .radio-header {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 12px 4px;
          cursor: pointer;
          user-select: none;
        }
        .radio-title {
          font-size: 8px;
          letter-spacing: 3px;
          text-transform: uppercase;
          color: var(--accent);
          opacity: 0.4;
          flex: 1;
        }
        .radio-expand {
          font-size: 8px;
          opacity: 0.3;
          color: var(--accent);
        }
        .radio-dot {
          width: 4px;
          height: 4px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.15);
          transition: all 0.3s;
        }
        .radio-dot.active {
          background: #40f080;
          box-shadow: 0 0 6px #40f08080;
          animation: radio-pulse 2s ease-in-out infinite;
        }
        .radio-now-playing {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 12px 8px;
        }
        .radio-eq {
          display: flex;
          align-items: flex-end;
          gap: 1.5px;
          height: 12px;
        }
        .eq-bar {
          width: 2px;
          background: var(--accent);
          border-radius: 1px;
          animation: eq-bounce 0.8s ease-in-out infinite;
        }
        .eq-bar:nth-child(1) { height: 4px; animation-delay: 0s; }
        .eq-bar:nth-child(2) { height: 8px; animation-delay: 0.2s; }
        .eq-bar:nth-child(3) { height: 6px; animation-delay: 0.4s; }
        .radio-station-name {
          font-size: 10px;
          color: rgba(255, 255, 255, 0.7);
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .radio-stop {
          width: 16px;
          height: 16px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 8px;
          color: rgba(255, 255, 255, 0.3);
          background: none;
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 3px;
          cursor: pointer;
          transition: all 0.2s;
        }
        .radio-stop:hover {
          color: #f04040;
          border-color: #f0404060;
        }
        .radio-offline {
          padding: 4px 12px 8px;
        }
        .radio-stations {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          padding: 4px 12px 10px;
        }
        .radio-station-btn {
          font-size: 8px;
          letter-spacing: 1px;
          padding: 3px 8px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 3px;
          color: rgba(255, 255, 255, 0.4);
          cursor: pointer;
          transition: all 0.2s;
          text-transform: uppercase;
        }
        .radio-station-btn:hover {
          background: rgba(255, 255, 255, 0.06);
          border-color: var(--accent);
          color: var(--accent);
        }
        .radio-station-btn.active {
          background: rgba(64, 240, 128, 0.08);
          border-color: #40f080;
          color: #40f080;
        }
        @keyframes radio-pulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; box-shadow: 0 0 8px #40f080; }
        }
        @keyframes eq-bounce {
          0%, 100% { transform: scaleY(0.4); }
          50% { transform: scaleY(1); }
        }
      `}</style>
    </div>
  );
}
