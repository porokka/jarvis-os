"use client";

import { ReactNode } from "react";

interface HudPanelProps {
  title?: string;
  children: ReactNode;
  className?: string;
  /** Extra corner decorations */
  corners?: boolean;
  /** Stronger glow variant */
  glow?: boolean;
  onClick?: () => void;
}

export function HudPanel({
  title,
  children,
  className = "",
  corners = true,
  glow = false,
  onClick,
}: HudPanelProps) {
  return (
    <div
      onClick={onClick}
      className={`
        hud-panel rounded-sm
        ${glow ? "glow-strong" : "glow-border"}
        ${onClick ? "cursor-pointer" : ""}
        ${className}
      `}
    >
      {/* Inner corners overlay */}
      {corners && <div className="hud-panel-corners absolute inset-0 pointer-events-none" />}

      {/* Title bar */}
      {title && (
        <div className="hud-title flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] opacity-60" />
          <span>{title}</span>
        </div>
      )}

      {/* Content */}
      <div className="relative z-[1]">{children}</div>
    </div>
  );
}
