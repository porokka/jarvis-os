"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { JarvisScene } from "./components/face/jarvis-scene";
import { ChatHistory } from "./components/chat-history";
import { InputBar } from "./components/input-bar";
import { ApprovalPanel } from "./components/approval-panel";

type JarvisState = "standby" | "listening" | "thinking" | "speaking" | "asking";

interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: string;
  timestamp: number;
}

export default function JarvisPage() {
  const [state, setState] = useState<JarvisState>("standby");
  const [emotion, setEmotion] = useState("neutral");
  const [output, setOutput] = useState("Ready.");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const historyEndRef = useRef<HTMLDivElement>(null);

  // Check TTS availability on mount
  useEffect(() => {
    fetch("/api/tts")
      .then((r) => r.json())
      .then((d) => setTtsAvailable(d.available))
      .catch(() => {});
  }, []);

  // Initialize speech recognition
  useEffect(() => {
    const SR =
      typeof window !== "undefined"
        ? window.SpeechRecognition || window.webkitSpeechRecognition
        : null;

    if (SR) {
      const recognition = new SR();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = "en-US";

      recognition.onresult = (e: SpeechRecognitionEvent) => {
        const text = e.results[0][0].transcript;
        handleSend(text);
      };

      recognition.onend = () =>
        setState((s) => (s === "listening" ? "standby" : s));
      recognition.onerror = () =>
        setState((s) => (s === "listening" ? "standby" : s));

      recognitionRef.current = recognition;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll history
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  const handleSend = useCallback(async (text: string) => {
    setState("thinking");
    setOutput(`"${text}"`);

    setHistory((h) => [...h, { role: "user", text, timestamp: Date.now() }]);

    try {
      const res = await fetch("/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      const data = await res.json();

      setState("speaking");
      setOutput(data.response);
      setEmotion(data.emotion || "neutral");

      setHistory((h) => [
        ...h,
        {
          role: "jarvis",
          text: data.response,
          emotion: data.emotion,
          timestamp: Date.now(),
        },
      ]);

      // Play TTS audio if available
      if (data.audio) {
        const wav = Uint8Array.from(atob(data.audio), (c) =>
          c.charCodeAt(0)
        );
        const blob = new Blob([wav], { type: "audio/wav" });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => {
          URL.revokeObjectURL(url);
          setState("standby");
          setEmotion("neutral");
          fetch("/api/state", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ finishSpeaking: true }),
          });
        };
        audio.play().catch(() => setState("standby"));
      } else {
        setTimeout(() => {
          setState("standby");
          setEmotion("neutral");
        }, 2000);
      }
    } catch {
      setOutput("Connection error. Is the server running?");
      setState("standby");
    }
  }, []);

  function handleVoiceToggle() {
    if (!recognitionRef.current) {
      setOutput("Voice not supported. Use text input.");
      return;
    }

    if (state === "listening") {
      recognitionRef.current.stop();
      setState("standby");
    } else if (state === "standby") {
      setState("listening");
      recognitionRef.current.start();
    }
  }

  const stateLabel: Record<string, string> = {
    standby: "STANDBY",
    listening: "LISTENING",
    thinking: "THINKING",
    speaking: "SPEAKING",
    asking: "AWAITING APPROVAL",
  };

  const stateColor: Record<string, string> = {
    standby: "text-green-400/50",
    listening: "text-red-400/70",
    thinking: "text-yellow-400/60",
    speaking: "text-blue-400/60",
    asking: "text-amber-400/70",
  };

  return (
    <main className="flex-1 flex flex-col items-center select-none h-screen overflow-hidden bg-[#06060b]">
      {/* Approval Panel */}
      <ApprovalPanel
        onApprovalChange={(count) => {
          setPendingApprovals(count);
          if (count > 0) setState("asking");
          else setState((s) => (s === "asking" ? "standby" : s));
        }}
      />

      {/* State indicator */}
      <div
        className={`fixed top-6 right-6 text-xs tracking-[3px] uppercase z-10 ${stateColor[state]}`}
      >
        {stateLabel[state]}
        {pendingApprovals > 0 && (
          <span className="ml-2 inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-400/20 text-amber-400 text-[9px]">
            {pendingApprovals}
          </span>
        )}
      </div>

      {/* TTS indicator */}
      <div className="fixed top-6 left-6 text-xs tracking-[2px] uppercase text-white/20 z-10">
        {ttsAvailable ? "ORPHEUS TTS" : "NO TTS"}
      </div>

      {/* 3D Face — takes upper portion */}
      <div
        className="w-full flex-1 min-h-0 cursor-pointer relative"
        onClick={handleVoiceToggle}
      >
        <JarvisScene
          emotion={emotion}
          speaking={state === "speaking"}
          thinking={state === "thinking"}
        />

        {/* Listening overlay */}
        {state === "listening" && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-red-400/70 text-xs tracking-[3px] uppercase animate-pulse">
            LISTENING — CLICK TO STOP
          </div>
        )}
      </div>

      {/* Bottom panel — output + history + input */}
      <div className="w-full max-w-2xl px-6 pb-6 pt-2 flex flex-col gap-3 shrink-0">
        {/* Current output */}
        <p className="text-center text-base leading-relaxed opacity-80 min-h-[28px]">
          {output}
        </p>

        {/* Chat history */}
        <ChatHistory history={history} />
        <div ref={historyEndRef} />

        {/* Hint */}
        <p className="text-[10px] text-white/15 tracking-wider text-center">
          Click face for voice &middot; Type below for text
        </p>

        {/* Input */}
        <InputBar
          onSend={handleSend}
          disabled={state === "thinking" || state === "speaking"}
        />
      </div>
    </main>
  );
}
