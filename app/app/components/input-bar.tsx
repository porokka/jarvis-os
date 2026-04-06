"use client";

import { useState, useRef } from "react";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function InputBar({ onSend, disabled }: InputBarProps) {
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
    <div className="flex gap-2 w-full max-w-xl">
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder={disabled ? "Thinking..." : "Talk to JARVIS..."}
        disabled={disabled}
        className="
          flex-1 bg-white/5 border border-white/15 rounded-lg
          px-4 py-3 text-sm text-[var(--foreground)]
          placeholder:text-white/25
          focus:outline-none focus:border-[var(--accent)]/50
          disabled:opacity-40
          font-[family-name:var(--font-mono)]
        "
        autoComplete="off"
      />
      <button
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
        className="
          bg-[var(--accent)]/15 border border-[var(--accent)]/30 rounded-lg
          px-5 py-3 text-sm text-[var(--accent)]
          hover:bg-[var(--accent)]/25
          disabled:opacity-30 disabled:cursor-not-allowed
          cursor-pointer transition-colors
          font-[family-name:var(--font-mono)]
        "
      >
        Send
      </button>
    </div>
  );
}
