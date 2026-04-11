"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { JarvisScene } from "./components/face/jarvis-scene";
import { ChatHistory } from "./components/chat-history";
import { InputBar } from "./components/input-bar";
import { ApprovalPanel } from "./components/approval-panel";
import { HudPanel } from "./components/hud-panel";
import { GpuMonitor } from "./components/gpu-monitor";
import { SystemLog } from "./components/system-log";
import { TimersWidget } from "./components/timers-widget";
import { SettingsPanel } from "./components/settings-panel";
import { RadioPlayer } from "./components/radio-player";
import { NetworkMap } from "./components/network-map";

type JarvisState = "standby" | "listening" | "thinking" | "speaking" | "asking";

interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: string;
  timestamp: number;
}

interface BridgeStatus {
  state?: string;
  emotion?: string;
  lastOutput?: string;
  lastInput?: string;
  brain?: string;
}

// ─── Clock Component ───
function HudClock() {
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");

  useEffect(() => {
    function tick() {
      const now = new Date();
      setTime(now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      setDate(now.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="text-right">
      <div className="text-sm tabular-nums glow-text text-[var(--accent)]">{time}</div>
      <div className="text-[8px] tracking-[2px] uppercase opacity-30">{date}</div>
    </div>
  );
}

// ─── Brain Indicator ───
function BrainIndicator({ brain }: { brain: string }) {
  const labels: Record<string, { label: string; color: string }> = {
    claude: { label: "CLAUDE", color: "#c080f0" },
    ollama_fast: { label: "QWEN 8B", color: "#40f080" },
    ollama_code: { label: "QWEN CODER 30B", color: "#40a0f0" },
    ollama_reason: { label: "QWEN 30B", color: "#f0c040" },
    ollama_deep: { label: "LLAMA 70B", color: "#f08040" },
  };

  const b = labels[brain] || { label: brain.toUpperCase(), color: "#40a0f0" };

  return (
    <div className="flex items-center gap-2">
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: b.color, boxShadow: `0 0 6px ${b.color}60` }}
      />
      <span className="text-[9px] tracking-[2px] uppercase" style={{ color: b.color }}>
        {b.label}
      </span>
    </div>
  );
}

// ─── State Indicator with pulsing ───
function StateIndicator({ state, pendingApprovals }: { state: JarvisState; pendingApprovals: number }) {
  const stateLabel: Record<string, string> = {
    standby: "STANDBY",
    listening: "LISTENING",
    thinking: "PROCESSING",
    speaking: "SPEAKING",
    asking: "AWAITING APPROVAL",
  };

  const stateColor: Record<string, string> = {
    standby: "#40f080",
    listening: "#f03c3c",
    thinking: "#f0c040",
    speaking: "#40a0f0",
    asking: "#f0c040",
  };

  const color = stateColor[state] || "#40a0f0";

  return (
    <div className={`flex items-center gap-2 state-${state}`}>
      <span
        className="w-2 h-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 8px ${color}80` }}
      />
      <span
        className="text-[10px] tracking-[3px] uppercase font-medium"
        style={{ color }}
      >
        {stateLabel[state]}
      </span>
      {pendingApprovals > 0 && (
        <span
          className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[8px]"
          style={{ background: `${color}20`, color }}
        >
          {pendingApprovals}
        </span>
      )}
    </div>
  );
}

// ─── Arc Reactor Decorative Ring (SVG) ───
function ArcReactorRing() {
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-[1]">
      <svg
        width="320"
        height="320"
        viewBox="0 0 320 320"
        className="reactor-pulse opacity-40"
      >
        {/* Outer ring */}
        <circle
          cx="160" cy="160" r="155"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.5"
          opacity="0.2"
        />
        {/* Rotating dashed ring */}
        <circle
          cx="160" cy="160" r="148"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.8"
          strokeDasharray="6 14"
          opacity="0.25"
          className="reactor-ring"
        />
        {/* Inner ring */}
        <circle
          cx="160" cy="160" r="140"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.3"
          opacity="0.15"
        />
        {/* Tick marks */}
        {Array.from({ length: 36 }).map((_, i) => {
          const angle = (i * 10 * Math.PI) / 180;
          const r1 = 152;
          const r2 = i % 3 === 0 ? 158 : 155;
          const cos = Math.round(Math.cos(angle) * 1000) / 1000;
          const sin = Math.round(Math.sin(angle) * 1000) / 1000;
          return (
            <line
              key={i}
              x1={160 + r1 * cos}
              y1={160 + r1 * sin}
              x2={160 + r2 * cos}
              y2={160 + r2 * sin}
              stroke="var(--accent)"
              strokeWidth={i % 3 === 0 ? "0.8" : "0.4"}
              opacity={i % 3 === 0 ? "0.3" : "0.15"}
            />
          );
        })}
        {/* Hexagonal center hint */}
        <polygon
          points="160,90 221,125 221,195 160,230 99,195 99,125"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="0.4"
          opacity="0.08"
        />
      </svg>
    </div>
  );
}

// ─── Horizontal HUD Line Decoration ───
function HudLine({ className = "" }: { className?: string }) {
  return (
    <div className={`hud-divider hud-sweep ${className}`} />
  );
}

// ═══════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════
export default function JarvisPage() {
  const [state, setState] = useState<JarvisState>("standby");
  const [emotion, setEmotion] = useState("neutral");
  const [output, setOutput] = useState("Systems online. Ready for input.");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [brain, setBrain] = useState("claude");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  const historyEndRef = useRef<HTMLDivElement>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  // ─── Check TTS on mount ───
  useEffect(() => {
    fetch("/api/tts")
      .then((r) => r.json())
      .then((d) => setTtsAvailable(d.available))
      .catch(() => {});
  }, []);

  // ─── Poll watcher state — single source of truth ───
  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("http://localhost:4000/api/state");
        const data = await res.json();
        if (!active) return;

        // Sync all state from watcher
        if (data.brain) setBrain(data.brain);

        const validStates = ["standby", "thinking", "speaking"];
        if (validStates.includes(data.state)) {
          setState(data.state as JarvisState);
        }

        if (data.emotion) setEmotion(data.emotion);

        // Update output when it changes
        if (data.lastOutput && data.lastOutput !== output) {
          setOutput(data.lastOutput);

          // Add to history if new
          setHistory((h) => {
            const last = h[h.length - 1];
            if (last?.role === "jarvis" && last.text === data.lastOutput) return h;
            return [...h, { role: "jarvis", text: data.lastOutput, timestamp: Date.now() }];
          });

          // Browser TTS — toggle via BROWSER_TTS
          const BROWSER_TTS = false; // off — mic picks up speaker output causing loops
          if (BROWSER_TTS && data.lastOutput !== lastSpokenRef.current) {
            lastSpokenRef.current = data.lastOutput;
            if ("speechSynthesis" in window) {
              // Set speaking state so voice capture mutes the mic
              fetch("http://localhost:4000/api/input", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: "__TTS_START__" }),
              }).catch(() => {});
              // Write speaking state directly
              fetch("http://localhost:4000/api/state-override", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ state: "speaking" }),
              }).catch(() => {});

              const utter = new SpeechSynthesisUtterance(data.lastOutput);
              utter.lang = "en-GB";
              utter.rate = 1;
              utter.pitch = 0.9;
              const voices = speechSynthesis.getVoices();
              const british = voices.find(v => v.lang === "en-GB") || voices.find(v => v.lang.startsWith("en"));
              if (british) utter.voice = british;
              utter.onend = () => {
                // Unmute mic
                fetch("http://localhost:4000/api/state-override", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ state: "standby" }),
                }).catch(() => {});
              };
              speechSynthesis.cancel();
              speechSynthesis.speak(utter);
            }
          }
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 500);
    return () => { active = false; clearInterval(id); };
  }, []);

  // ─── Send input ───
  const lastSpokenRef = useRef("");

  const handleSend = useCallback(async (text: string) => {
    setHistory((h) => [...h, { role: "user", text, timestamp: Date.now() }]);

    try {
      await fetch("http://localhost:4000/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
    } catch {
      setOutput("Connection error. Is the bridge server running?");
    }
  }, []);

  // ─── WAV encoder ───
  function audioBufferToWav(buffer: AudioBuffer): Blob {
    const numChannels = 1;
    const sampleRate = buffer.sampleRate;
    const samples = buffer.getChannelData(0);
    const dataLength = samples.length * 2;
    const arrayBuffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(arrayBuffer);

    function writeStr(offset: number, s: string) {
      for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
    }

    writeStr(0, "RIFF");
    view.setUint32(4, 36 + dataLength, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, dataLength, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      offset += 2;
    }

    return new Blob([arrayBuffer], { type: "audio/wav" });
  }

  // ─── Browser voice: always-on with wake word ───
  const WAKE_WORDS = ["hey jarvis", "ok jarvis", "jarvis", "hey travis", "hey jervis", "hey charvis"];
  const AWAKE_TIMEOUT = 60_000; // 60s of listening after wake word
  const awakeUntilRef = useRef(0);
  const alwaysOnRef = useRef(false);
  const [micActive, setMicActive] = useState(false);

  function hasWakeWord(text: string): boolean {
    const lower = text.toLowerCase();
    return WAKE_WORDS.some(w => lower.includes(w));
  }

  function stripWakeWord(text: string): string {
    let lower = text.toLowerCase();
    for (const wake of WAKE_WORDS) {
      const idx = lower.indexOf(wake);
      if (idx !== -1 && idx < 20) {
        return text.slice(idx + wake.length).replace(/^[,.\s]+/, "").trim();
      }
    }
    return text;
  }

  // Record a single utterance → WAV → Whisper → return text
  function captureUtterance(stream: MediaStream, analyser: AnalyserNode): Promise<string> {
    return new Promise((resolve) => {
      // Clone the stream so we get a fresh recorder each time
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };

      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: recorder.mimeType });
        try {
          const arrayBuf = await blob.arrayBuffer();
          const decodeCtx = new AudioContext({ sampleRate: 16000 });
          const audioBuf = await decodeCtx.decodeAudioData(arrayBuf);
          const wavBlob = audioBufferToWav(audioBuf);
          decodeCtx.close();

          const res = await fetch("/api/transcribe", { method: "POST", body: wavBlob });
          const data = await res.json();
          resolve(data.echo ? "" : (data.text || ""));
        } catch (e) {
          console.error("Transcribe error:", e);
          resolve("");
        }
      };

      recorder.start();

      // Silence detection — stop after ~2.5s silence
      let silentFrames = 0;
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const check = () => {
        if (recorder.state === "inactive") return;
        analyser.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        if (avg < 5) {
          silentFrames++;
          if (silentFrames > 8) { recorder.stop(); return; }
        } else {
          silentFrames = 0;
        }
        setTimeout(check, 300);
      };
      setTimeout(check, 800);

      // Hard limit — 15s max
      setTimeout(() => { if (recorder.state !== "inactive") recorder.stop(); }, 15000);
    });
  }

  // Wait for speech (volume above threshold), with timeout
  function waitForSpeech(analyser: AnalyserNode, timeoutMs = 30000): Promise<boolean> {
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const start = Date.now();
    return new Promise((resolve) => {
      const check = () => {
        if (!alwaysOnRef.current) { resolve(false); return; }
        if (Date.now() - start > timeoutMs) {
          // Timeout — just loop again (don't exit)
          resolve(true);
          return;
        }
        analyser.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        if (avg > 8) { resolve(true); return; }
        setTimeout(check, 100);
      };
      check();
    });
  }

  // Main always-on loop
  const startAlwaysOn = useCallback(async () => {
    if (alwaysOnRef.current) return;
    alwaysOnRef.current = true;
    setMicActive(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      console.log("[JARVIS] Always-on voice started — say 'Hey JARVIS'");

      while (alwaysOnRef.current) {
        // Skip while JARVIS is talking (use ref to avoid stale closure)
        if (stateRef.current === "thinking" || stateRef.current === "speaking") {
          await new Promise(r => setTimeout(r, 500));
          continue;
        }

        // Wait for speech
        const hasSpeech = await waitForSpeech(analyser);
        if (!hasSpeech) break;

        console.log("[JARVIS] Speech detected, recording...");

        // Record utterance
        const text = await captureUtterance(stream, analyser);
        if (!text || text.length < 3) {
          console.log("[JARVIS] Empty/short transcription, skipping");
          continue;
        }

        console.log("[JARVIS] Heard:", text);

        const now = Date.now();
        const isAwake = now < awakeUntilRef.current;

        if (hasWakeWord(text)) {
          awakeUntilRef.current = now + AWAKE_TIMEOUT;
          const command = stripWakeWord(text);
          if (command && command.length > 2) {
            console.log("[JARVIS] Wake + command:", command);
            handleSend(command);
          } else {
            console.log("[JARVIS] Awake — listening for 60s...");
          }
        } else if (isAwake) {
          console.log("[JARVIS] Command:", text);
          handleSend(text);
          awakeUntilRef.current = now + AWAKE_TIMEOUT;
        } else {
          console.log("[JARVIS] Sleeping, ignored:", text);
        }

        // Brief pause before next listen cycle
        await new Promise(r => setTimeout(r, 500));
      }

      // Only reach here if alwaysOnRef was set to false

      stream.getTracks().forEach(t => t.stop());
      audioCtx.close();
      console.log("[JARVIS] Always-on voice stopped");
    } catch (err) {
      console.error("[JARVIS] Mic error:", err);
    }

    alwaysOnRef.current = false;
    setMicActive(false);
    setState("standby");
  }, [handleSend]);

  const stopAlwaysOn = useCallback(() => {
    alwaysOnRef.current = false;
  }, []);

  // ─── Auto-scroll chat ───
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  // ─── Voice toggle ───
  function handleVoiceToggle() {
    if (alwaysOnRef.current) {
      stopAlwaysOn();
    } else {
      startAlwaysOn();
    }
  }

  const isProcessing = state === "thinking" || state === "speaking";

  return (
    <main className="h-screen w-screen overflow-hidden bg-[var(--background)] hud-grid scan-lines select-none relative">
      {/* ════════════ Approval Panel ════════════ */}
      <ApprovalPanel
        onApprovalChange={(count) => {
          setPendingApprovals(count);
          if (count > 0) setState("asking");
          else setState((s) => (s === "asking" ? "standby" : s));
        }}
      />

      {/* ════════════ TOP BAR ════════════ */}
      <header className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-6 py-3">
        {/* Left: Title + TTS */}
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-sm tracking-[6px] uppercase glow-text text-[var(--accent)] font-bold">
              J.A.R.V.I.S
            </h1>
            <div className="text-[7px] tracking-[3px] uppercase opacity-25 mt-0.5">
              {ttsAvailable ? "ORPHEUS TTS ACTIVE" : "TEXT MODE"} &middot; LOCAL AI ASSISTANT
            </div>
          </div>
        </div>

        {/* Center: State */}
        <StateIndicator state={state} pendingApprovals={pendingApprovals} />

        {/* Right: Brain + Clock + Settings */}
        <div className="flex items-center gap-6">
          <BrainIndicator brain={brain} />
          <div className="w-px h-6 bg-[var(--panel-border)]" />
          <HudClock />
          <button
            onClick={() => setSettingsOpen(true)}
            className="w-7 h-7 flex items-center justify-center rounded-full opacity-30 hover:opacity-70 transition-opacity"
            title="Settings"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </div>
      </header>

      <HudLine className="absolute top-[52px] left-0 right-0 z-20" />

      {/* ════════════ MAIN GRID ════════════ */}
      <div className="absolute inset-0 top-[53px] bottom-0 flex">

        {/* ──── LEFT PANEL ──── */}
        <aside className="w-[260px] flex-shrink-0 flex flex-col gap-3 p-3 overflow-y-auto scrollbar-hud z-10">
          <RadioPlayer />

          <GpuMonitor />

          {/* Emotion indicator */}
          <HudPanel title="EMOTION STATE">
            <div className="p-3 flex items-center gap-3">
              <div className={`
                w-8 h-8 rounded-full flex items-center justify-center text-lg
                ${emotion === "happy" ? "bg-green-400/10 text-green-400" :
                  emotion === "thinking" ? "bg-yellow-400/10 text-yellow-400" :
                  emotion === "serious" ? "bg-orange-400/10 text-orange-400" :
                  emotion === "confused" ? "bg-purple-400/10 text-purple-400" :
                  "bg-[var(--accent)]/10 text-[var(--accent)]"}
              `}>
                {emotion === "happy" ? "\u2713" :
                 emotion === "thinking" ? "?" :
                 emotion === "serious" ? "!" :
                 emotion === "confused" ? "~" : "\u2022"}
              </div>
              <div>
                <div className="text-[10px] tracking-[2px] uppercase text-[var(--foreground)] opacity-60">
                  {emotion.toUpperCase()}
                </div>
                <div className="text-[8px] tracking-[1px] opacity-25">
                  EMOTION VECTOR
                </div>
              </div>
            </div>
          </HudPanel>

          {/* TTS Status */}
          <HudPanel title="AUDIO SYSTEM">
            <div className="p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-1.5 h-1.5 rounded-full ${ttsAvailable ? "bg-green-400" : "bg-red-400/50"}`} />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  {ttsAvailable ? "ORPHEUS TTS ONLINE" : "TTS OFFLINE"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                <span className="text-[9px] tracking-[2px] uppercase opacity-50">
                  WHISPER STT
                </span>
              </div>
            </div>
          </HudPanel>
        </aside>

        {/* ──── CENTER: 3D Face ──── */}
        <div className="flex-1 relative flex flex-col min-w-0">
          {/* Face area */}
          <div
            className="flex-1 relative cursor-pointer min-h-0"
            onClick={handleVoiceToggle}
          >
            {/* Arc reactor decoration */}
            <ArcReactorRing />

            {/* 3D Face */}
            <JarvisScene
              emotion={emotion}
              speaking={state === "speaking"}
              thinking={state === "thinking"}
            />

            {/* Listening overlay */}
            {state === "listening" && (
              <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10">
                <div className="text-red-400 text-[10px] tracking-[4px] uppercase state-listening flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
                  LISTENING &mdash; CLICK TO STOP
                </div>
              </div>
            )}
          </div>

          {/* ──── BOTTOM: Output + Chat + Input ──── */}
          <div className="flex-shrink-0 px-6 pb-4 pt-2 z-10 relative">
            <HudLine className="mb-3" />

            {/* Current response */}
            <div className="text-center mb-3">
              <p className="text-sm leading-relaxed opacity-75 max-w-xl mx-auto data-flicker">
                {output}
              </p>
            </div>

            {/* Chat history toggle */}
            {history.length > 0 && (
              <div className="mb-3">
                <button
                  onClick={() => setChatOpen((o) => !o)}
                  className="text-[8px] tracking-[2px] uppercase text-[var(--accent)] opacity-30 hover:opacity-60 transition-opacity cursor-pointer mx-auto block mb-2"
                >
                  {chatOpen ? "HIDE HISTORY" : `SHOW HISTORY (${history.length})`}
                </button>
                {chatOpen && (
                  <div className="max-w-xl mx-auto">
                    <HudPanel className="mb-2">
                      <div className="p-2">
                        <ChatHistory history={history} />
                        <div ref={historyEndRef} />
                      </div>
                    </HudPanel>
                  </div>
                )}
              </div>
            )}

            {/* Hint */}
            <p className="text-[8px] text-white/15 tracking-[2px] text-center mb-2 uppercase">
              {micActive ? 'Listening\u2026 say "Hey JARVIS"' : "Click face to start voice"} &middot; Type below for text
            </p>

            {/* Input bar */}
            <div className="max-w-xl mx-auto">
              <InputBar
                onSend={handleSend}
                disabled={isProcessing}
                listening={state === "listening"}
                onVoiceToggle={handleVoiceToggle}
              />
            </div>
          </div>
        </div>

        {/* ──── RIGHT PANEL ──── */}
        <aside className="w-[280px] flex-shrink-0 flex flex-col gap-3 p-3 overflow-y-auto scrollbar-hud z-10">
          <TimersWidget />
          <SystemLog />

          <HudPanel title="NETWORK">
            <NetworkMap />
          </HudPanel>

          {/* Quick Status Cards */}
          <HudPanel title="SYSTEM STATUS">
            <div className="p-3 space-y-2.5">
              <div className="flex justify-between items-center">
                <span className="text-[9px] tracking-[2px] uppercase opacity-40">BRAIN</span>
                <BrainIndicator brain={brain} />
              </div>
              <div className="hud-divider" />
              <div className="flex justify-between items-center">
                <span className="text-[9px] tracking-[2px] uppercase opacity-40">STATE</span>
                <StateIndicator state={state} pendingApprovals={0} />
              </div>
              <div className="hud-divider" />
              <div className="flex justify-between items-center">
                <span className="text-[9px] tracking-[2px] uppercase opacity-40">EMOTION</span>
                <span className="text-[10px] tracking-[2px] uppercase text-[var(--accent)] opacity-60">
                  {emotion}
                </span>
              </div>
              <div className="hud-divider" />
              <div className="flex justify-between items-center">
                <span className="text-[9px] tracking-[2px] uppercase opacity-40">MESSAGES</span>
                <span className="text-[10px] tabular-nums text-[var(--accent)] opacity-60">
                  {history.length}
                </span>
              </div>
            </div>
          </HudPanel>

          {/* Connection Status */}
          <HudPanel title="CONNECTIONS">
            <div className="p-3 space-y-2">
              {[
                { name: "NEXT.JS SERVER", status: true },
                { name: "BRIDGE (4000)", status: true },
                { name: "OLLAMA (7900)", status: brain.startsWith("ollama") },
                { name: "TTS ENGINE", status: ttsAvailable },
              ].map((conn) => (
                <div key={conn.name} className="flex items-center gap-2">
                  <span className={`w-1 h-1 rounded-full ${conn.status ? "bg-green-400" : "bg-white/15"}`} />
                  <span className={`text-[9px] tracking-[2px] uppercase ${conn.status ? "opacity-50" : "opacity-20"}`}>
                    {conn.name}
                  </span>
                </div>
              ))}
            </div>
          </HudPanel>

          {/* Decorative data overlay */}
          <div className="flex-1" />
          <div className="text-[7px] tracking-[1px] opacity-10 font-mono px-2 pb-2 leading-relaxed data-flicker">
            SYS.KERNEL.V4.2.1<br />
            MEM.ALLOC.OK<br />
            NET.BRIDGE.ACTIVE<br />
            VAULT.SYNC.NOMINAL<br />
            SEC.CLEARANCE.ALPHA
          </div>
        </aside>
      </div>

      {/* ════════════ Edge decorations ════════════ */}
      {/* Top-left corner bracket */}
      <div className="absolute top-1 left-1 w-4 h-4 border-t border-l border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      {/* Top-right corner bracket */}
      <div className="absolute top-1 right-1 w-4 h-4 border-t border-r border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      {/* Bottom-left corner bracket */}
      <div className="absolute bottom-1 left-1 w-4 h-4 border-b border-l border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      {/* Bottom-right corner bracket */}
      <div className="absolute bottom-1 right-1 w-4 h-4 border-b border-r border-[var(--accent)] opacity-15 z-30 pointer-events-none" />
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </main>
  );
}
