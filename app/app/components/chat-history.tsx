"use client";

interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: string;
  timestamp: number;
}

interface ChatHistoryProps {
  history: HistoryEntry[];
}

export function ChatHistory({ history }: ChatHistoryProps) {
  if (history.length === 0) return null;

  return (
    <div className="w-full max-w-xl space-y-3 max-h-64 overflow-y-auto px-2 scrollbar-thin">
      {history.map((entry, i) => (
        <div
          key={entry.timestamp + i}
          className={`flex ${entry.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`
              max-w-[80%] px-4 py-2 rounded-lg text-sm leading-relaxed
              ${
                entry.role === "user"
                  ? "bg-white/5 text-white/70"
                  : "bg-[var(--accent)]/10 text-[var(--foreground)]"
              }
            `}
          >
            {entry.text}
          </div>
        </div>
      ))}
    </div>
  );
}
