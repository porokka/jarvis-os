"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Hls from "hls.js";

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
  const [needsInteraction, setNeedsInteraction] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);
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

  // Clean up HLS on unmount
  useEffect(() => {
    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, []);

  const playStream = useCallback((url: string) => {
    const audio = audioRef.current;
    if (!audio) return;

    // Destroy previous HLS instance
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    const isHls = url.includes(".m3u8");

    if (isHls && Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
      });
      hls.loadSource(url);
      hls.attachMedia(audio);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        audio.play().then(() => {
          setAudioPlaying(true);
          setNeedsInteraction(false);
        }).catch(() => {
          setNeedsInteraction(true);
        });
      });
      hlsRef.current = hls;
    } else if (isHls && audio.canPlayType("application/vnd.apple.mpegurl")) {
      // Native HLS (Safari)
      audio.src = url;
      audio.play().then(() => {
        setAudioPlaying(true);
        setNeedsInteraction(false);
      }).catch(() => {
        setNeedsInteraction(true);
      });
    } else {
      // Direct stream (AAC, MP3, etc.)
      audio.src = url;
      audio.load();
      audio.play().then(() => {
        setAudioPlaying(true);
        setNeedsInteraction(false);
      }).catch(() => {
        setNeedsInteraction(true);
      });
    }

    lastUrlRef.current = url;
  }, []);

  // Sync audio element with radio state
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (radio.playing && radio.stream_url) {
      if (radio.stream_url !== lastUrlRef.current) {
        playStream(radio.stream_url);
      }
    } else if (!radio.playing && lastUrlRef.current) {
      audio.pause();
      audio.src = "";
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      lastUrlRef.current = null;
      setAudioPlaying(false);
      setNeedsInteraction(false);
    }
  }, [radio.playing, radio.stream_url, playStream]);

  // User clicked play after autoplay was blocked
  const handleUnblock = () => {
    const audio = audioRef.current;
    if (audio) {
      audio.play().then(() => {
        setAudioPlaying(true);
        setNeedsInteraction(false);
      }).catch(() => {});
    }
  };

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
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
    }
    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }
    lastUrlRef.current = null;
    setAudioPlaying(false);
    setNeedsInteraction(false);
    setRadio(prev => ({ ...prev, playing: false, station: null, label: null, stream_url: null }));
    sendCommand("stop radio");
  };

  const handlePlay = (station: string) => {
    sendCommand(`play ${station} radio`);
  };

  const stationList = Object.entries(radio.stations || {});

  return (
    <div className="radio-player">
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
          {audioPlaying ? (
            <div className="radio-eq">
              <span className="eq-bar" />
              <span className="eq-bar" />
              <span className="eq-bar" />
            </div>
          ) : needsInteraction ? (
            <button className="radio-play-btn" onClick={handleUnblock} title="Click to play">
              &#9654;
            </button>
          ) : (
            <div className="radio-loading" />
          )}
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
        .radio-play-btn {
          width: 18px;
          height: 18px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          color: #40f080;
          background: rgba(64, 240, 128, 0.1);
          border: 1px solid #40f08060;
          border-radius: 50%;
          cursor: pointer;
          animation: play-pulse 1.5s ease-in-out infinite;
        }
        .radio-play-btn:hover {
          background: rgba(64, 240, 128, 0.2);
        }
        .radio-loading {
          width: 12px;
          height: 12px;
          border: 1.5px solid rgba(255, 255, 255, 0.1);
          border-top-color: var(--accent);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
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
        @keyframes play-pulse {
          0%, 100% { opacity: 0.7; }
          50% { opacity: 1; }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
