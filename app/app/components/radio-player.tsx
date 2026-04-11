"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Hls from "hls.js";

// Station URLs embedded — no server round-trip needed
const STATIONS: Record<string, { label: string; url: string; type: "direct" | "hls" | "bauer" }> = {
  nova:     { label: "Radio Nova",     url: "", type: "bauer" },
  suomipop: { label: "Radio Suomipop", url: "https://www.supla.fi/radiosuomipop", type: "direct" },
  rock:     { label: "Radio Rock",     url: "https://www.supla.fi/radiorock", type: "direct" },
  yle1:     { label: "YLE Radio 1",    url: "https://yleradiolive.akamaized.net/hls/live/2027671/in-YleRadio1/master.m3u8", type: "hls" },
  ylex:     { label: "YLE X",          url: "https://yleradiolive.akamaized.net/hls/live/2027673/in-YleX/master.m3u8", type: "hls" },
  lofi:     { label: "Lo-Fi Radio",    url: "https://play.streamafrica.net/lofiradio", type: "direct" },
  chillhop: { label: "Chillhop",       url: "http://stream.zeno.fm/fyn8eh3h5f8uv", type: "direct" },
};

function getBauerUrl(): string {
  const id = crypto.randomUUID().replace(/-/g, "");
  const skey = Math.floor(Date.now() / 1000).toString();
  return (
    `https://live-bauerfi.sharp-stream.com/fi_radionova_64.aac` +
    `?direct=true&listenerid=${id}` +
    `&aw_0_1st.bauer_listenerid=${id}` +
    `&aw_0_1st.playerid=BMUK_inpage_html5` +
    `&aw_0_1st.skey=${skey}` +
    `&aw_0_1st.bauer_loggedin=false`
  );
}

export function RadioPlayer() {
  const [currentStation, setCurrentStation] = useState<string | null>(null);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [nowPlaying, setNowPlaying] = useState<{ title: string | null; artist: string | null }>({ title: null, artist: null });
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);

  // Also poll ReAct state for voice-triggered radio
  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const res = await fetch("/api/radio", { cache: "no-store" });
        const data = await res.json();
        if (!active) return;

        if (data.playing && data.station) {
          // Play if new station OR same station but browser isn't actually playing
          if (data.station !== currentStation || !audioPlaying) {
            playStation(data.station);
          }
        } else if (!data.playing && (currentStation || audioPlaying)) {
          stopPlayback();
        }
        // Update now-playing metadata
        if (data.now_playing) {
          setNowPlaying(data.now_playing);
        }
      } catch {}
    }
    const id = setInterval(poll, 3000);
    return () => { active = false; clearInterval(id); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStation, audioPlaying]);

  useEffect(() => {
    return () => {
      if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; }
    };
  }, []);

  const playStation = useCallback((key: string) => {
    const station = STATIONS[key];
    if (!station) return;

    const audio = audioRef.current;
    if (!audio) return;

    // Destroy previous HLS
    if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; }

    let url = station.url;
    if (station.type === "bauer") url = getBauerUrl();

    setCurrentStation(key);

    if (station.type === "hls" && Hls.isSupported()) {
      const hls = new Hls({ enableWorker: true, lowLatencyMode: true });
      hls.loadSource(url);
      hls.attachMedia(audio);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        audio.play().then(() => setAudioPlaying(true)).catch(() => {});
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (data.fatal) { setAudioPlaying(false); }
      });
      hlsRef.current = hls;
    } else {
      audio.src = url;
      audio.load();
      audio.play().then(() => setAudioPlaying(true)).catch(() => {});
    }
  }, []);

  const stopPlayback = useCallback(() => {
    const audio = audioRef.current;
    if (audio) { audio.pause(); audio.src = ""; }
    if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null; }
    setCurrentStation(null);
    setAudioPlaying(false);
  }, []);

  const handleStationClick = (key: string) => {
    if (currentStation === key && audioPlaying) {
      stopPlayback();
      // Tell ReAct to update state
      fetch("/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "stop radio" }),
      }).catch(() => {});
    } else {
      playStation(key);
    }
  };

  const handleStop = () => {
    stopPlayback();
    fetch("/api/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "stop radio" }),
    }).catch(() => {});
  };

  const currentLabel = currentStation ? STATIONS[currentStation]?.label : null;

  // Hidden audio element always renders (for voice-triggered playback)
  if (!audioPlaying && !currentStation) {
    return <audio ref={audioRef} crossOrigin="anonymous" />;
  }

  return (
    <div className="radio-player hud-panel rounded-sm glow-border">
      <audio ref={audioRef} crossOrigin="anonymous" />

      <div className="radio-panel-header">
        <span className="radio-dot active" />
        <span className="radio-panel-title">RADIO</span>
      </div>

      <div className="radio-now-playing-wrap">
        <div className="radio-now-playing">
          <div className="radio-eq">
            <span className="eq-bar" />
            <span className="eq-bar" />
            <span className="eq-bar" />
          </div>
          <span className="radio-station-name">{currentLabel}</span>
          <button className="radio-stop" onClick={handleStop} title="Stop">&#9632;</button>
        </div>
        {(nowPlaying.title || nowPlaying.artist) && (
          <div className="radio-track">
            {nowPlaying.artist && <span className="radio-artist">{nowPlaying.artist}</span>}
            {nowPlaying.artist && nowPlaying.title && <span className="radio-sep"> — </span>}
            {nowPlaying.title && <span className="radio-title-text">{nowPlaying.title}</span>}
          </div>
        )}
      </div>

      <style jsx>{`
        .radio-player { padding: 0; }
        .radio-panel-header {
          display: flex; align-items: center; gap: 6px;
          padding: 10px 12px 2px;
        }
        .radio-panel-title {
          font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
          color: var(--accent); opacity: 0.5; font-weight: 600;
        }
        .radio-dot {
          width: 4px; height: 4px; border-radius: 50%;
          background: rgba(255,255,255,0.15); transition: all 0.3s;
        }
        .radio-dot.active {
          background: #40f080; box-shadow: 0 0 6px #40f08080;
          animation: radio-pulse 2s ease-in-out infinite;
        }
        .radio-now-playing-wrap {
          padding: 0;
        }
        .radio-now-playing {
          display: flex; align-items: center; gap: 8px; padding: 6px 12px 4px;
        }
        .radio-track {
          padding: 0 12px 8px 26px;
          font-size: 9px;
          color: rgba(255, 255, 255, 0.45);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .radio-artist {
          color: var(--accent);
          opacity: 0.7;
        }
        .radio-sep {
          opacity: 0.3;
        }
        .radio-title-text {
          opacity: 0.6;
        }
        .radio-eq { display: flex; align-items: flex-end; gap: 1.5px; height: 12px; }
        .eq-bar {
          width: 2px; background: var(--accent); border-radius: 1px;
          animation: eq-bounce 0.8s ease-in-out infinite;
        }
        .eq-bar:nth-child(1) { height: 4px; animation-delay: 0s; }
        .eq-bar:nth-child(2) { height: 8px; animation-delay: 0.2s; }
        .eq-bar:nth-child(3) { height: 6px; animation-delay: 0.4s; }
        .radio-station-name {
          font-size: 10px; color: rgba(255,255,255,0.7); flex: 1;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .radio-stop {
          width: 16px; height: 16px; display: flex; align-items: center;
          justify-content: center; font-size: 8px; color: rgba(255,255,255,0.3);
          background: none; border: 1px solid rgba(255,255,255,0.1);
          border-radius: 3px; cursor: pointer; transition: all 0.2s;
        }
        .radio-stop:hover { color: #f04040; border-color: #f0404060; }
        .radio-offline { padding: 4px 12px 8px; }
        .radio-stations {
          display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 12px 10px;
        }
        .radio-station-btn {
          font-size: 8px; letter-spacing: 1px; padding: 3px 8px;
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
          border-radius: 3px; color: rgba(255,255,255,0.4);
          cursor: pointer; transition: all 0.2s; text-transform: uppercase;
        }
        .radio-station-btn:hover {
          background: rgba(255,255,255,0.06); border-color: var(--accent); color: var(--accent);
        }
        .radio-station-btn.active {
          background: rgba(64,240,128,0.08); border-color: #40f080; color: #40f080;
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
