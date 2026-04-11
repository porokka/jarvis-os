"use client";

import { useState, useRef } from "react";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
  listening?: boolean;
  onVoiceToggle?: () => void;
}

export function InputBar({ onSend, disabled, listening, onVoiceToggle }: InputBarProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    inputRef.current?.focus();
  }

  return (
    <div className="flex gap-2 w-full items-center">
      {/* Voice button */}
      {onVoiceToggle && (
        <button
          onClick={onVoiceToggle}
          disabled={disabled}
          className={`
            relative flex-shrink-0 w-10 h-10 rounded-full
            border transition-all duration-300
            ${listening
              ? "border-red-400/60 bg-red-400/10 text-red-400 shadow-[0_0_16px_rgba(240,60,60,0.3)]"
              : "border-[var(--panel-border)] bg-[var(--panel-bg)] text-[var(--accent)] opacity-60 hover:opacity-100"
            }
            disabled:opacity-20 disabled:cursor-not-allowed cursor-pointer
            flex items-center justify-center
          `}
          title={listening ? "Stop listening" : "Start voice input"}
        >
          {/* Mic icon */}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>

          {/* Pulsing ring when listening */}
          {listening && (
            <span className="absolute inset-0 rounded-full border border-red-400/40 animate-ping" />
          )}
        </button>
      )}

      {/* Input field */}
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder={disabled ? "Processing..." : "Command JARVIS..."}
        disabled={disabled}
        className="
          hud-input flex-1
          bg-[var(--panel-bg)] border border-[var(--panel-border)] rounded-sm
          px-4 py-2.5 text-xs text-[var(--foreground)]
          placeholder:text-white/20
          focus:outline-none focus:border-[var(--accent)]/40
          disabled:opacity-30
          font-[family-name:var(--font-mono)]
          transition-all duration-300
        "
        autoComplete="off"
      />

      {/* Send button */}
      <button
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
        className="
          flex-shrink-0 px-4 py-2.5 rounded-sm text-[10px] tracking-[2px] uppercase
          bg-[var(--accent)]/10 border border-[var(--accent)]/25
          text-[var(--accent)]
          hover:bg-[var(--accent)]/20 hover:border-[var(--accent)]/40
          disabled:opacity-20 disabled:cursor-not-allowed
          cursor-pointer transition-all duration-200
          font-[family-name:var(--font-mono)]
        "
      >
        SEND
      </button>
    </div>
  );
}
