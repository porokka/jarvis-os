"use client";

interface OrbProps {
  state: "standby" | "listening" | "thinking" | "speaking";
  onClick: () => void;
}

const stateStyles: Record<string, string> = {
  standby:
    "border-[var(--accent)]/20 bg-[radial-gradient(circle_at_35%_35%,rgba(64,160,240,0.2),rgba(64,160,240,0.03)_60%,transparent_70%)] animate-[orb-idle_4s_ease-in-out_infinite]",
  listening:
    "border-[var(--danger)]/60 bg-[radial-gradient(circle_at_35%_35%,rgba(240,60,60,0.25),rgba(240,60,60,0.03)_60%,transparent_70%)] animate-[orb-listening_1.5s_ease-in-out_infinite]",
  thinking:
    "border-[var(--warning)]/50 bg-[radial-gradient(circle_at_35%_35%,rgba(240,192,64,0.2),rgba(240,192,64,0.03)_60%,transparent_70%)] animate-[orb-thinking_2s_linear_infinite]",
  speaking:
    "border-[var(--accent)]/60 bg-[radial-gradient(circle_at_35%_35%,rgba(64,160,240,0.3),rgba(64,160,240,0.05)_60%,transparent_70%)] animate-[orb-speaking_0.8s_ease-in-out_infinite]",
};

export function Orb({ state, onClick }: OrbProps) {
  return (
    <button
      onClick={onClick}
      className={`
        w-48 h-48 rounded-full border cursor-pointer
        transition-all duration-500 ease-[cubic-bezier(0.19,1,0.22,1)]
        hover:border-[var(--accent)]/50
        focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]
        ${stateStyles[state] || stateStyles.standby}
      `}
      title={state === "listening" ? "Click to stop" : "Click to speak"}
      aria-label={state === "listening" ? "Stop listening" : "Start voice input"}
    />
  );
}
