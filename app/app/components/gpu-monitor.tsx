"use client";

import { useState, useEffect } from "react";
import { HudPanel } from "./hud-panel";

interface GpuData {
  name: string;
  temp: number;
  utilization: number;
  memUsed: number;
  memTotal: number;
  power: number;
  powerLimit: number;
  fan: number;
  clockCore: number;
  clockMem: number;
}

function tempColor(t: number): string {
  if (t < 55) return "#40f080";
  if (t < 75) return "#f0c040";
  return "#f03c3c";
}

function utilColor(u: number): string {
  if (u < 40) return "#40f080";
  if (u < 75) return "#40a0f0";
  return "#f0c040";
}

function HoloBar({
  value,
  max,
  color,
  label,
  unit = "",
}: {
  value: number;
  max: number;
  color: string;
  label: string;
  unit?: string;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;

  return (
    <div className="mb-2.5">
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-[9px] tracking-[2px] uppercase text-[var(--foreground)] opacity-50">
          {label}
        </span>
        <span className="text-[10px] tabular-nums" style={{ color }}>
          {value.toFixed(0)}{unit && <span className="text-[8px] opacity-50 ml-0.5">{unit}</span>}
          <span className="text-[8px] opacity-30">/{max.toFixed(0)}</span>
        </span>
      </div>
      <div className="holo-bar h-[6px]">
        <div
          className="holo-bar-fill"
          style={{
            width: `${pct}%`,
            background: `linear-gradient(90deg, ${color}30, ${color}80)`,
            color,
          }}
        />
      </div>
    </div>
  );
}

/** SVG Arc for utilization */
function UtilRing({ value }: { value: number }) {
  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = utilColor(value);

  return (
    <div className="flex items-center justify-center mb-3">
      <svg width="72" height="72" viewBox="0 0 72 72" className="data-flicker">
        {/* Background ring */}
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          stroke="rgba(64,160,240,0.08)"
          strokeWidth="4"
        />
        {/* Value ring */}
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 36 36)"
          style={{
            transition: "stroke-dashoffset 0.8s ease-out, stroke 0.5s",
            filter: `drop-shadow(0 0 4px ${color})`,
          }}
        />
        {/* Center text */}
        <text
          x="36" y="34"
          textAnchor="middle"
          fill={color}
          fontSize="16"
          fontFamily="monospace"
          fontWeight="bold"
          style={{ filter: `drop-shadow(0 0 4px ${color}40)` }}
        >
          {value.toFixed(0)}
        </text>
        <text
          x="36" y="46"
          textAnchor="middle"
          fill="rgba(200,216,232,0.35)"
          fontSize="7"
          fontFamily="monospace"
          letterSpacing="2"
        >
          GPU %
        </text>
      </svg>
    </div>
  );
}

export function GpuMonitor() {
  const [gpus, setGpus] = useState<GpuData[]>([]);
  const [online, setOnline] = useState(false);

  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("/api/gpu");
        const data = await res.json();
        if (active && Array.isArray(data.gpus)) {
          setGpus(data.gpus);
          setOnline(data.gpus.length > 0);
        }
      } catch {
        if (active) setOnline(false);
      }
    }

    poll();
    const id = setInterval(poll, 3000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const gpu = gpus[0]; // Primary GPU

  return (
    <HudPanel title="GPU TELEMETRY" className="w-full">
      <div className="p-3">
        {!online || !gpu ? (
          <div className="text-[10px] text-[var(--foreground)] opacity-25 tracking-[2px] text-center py-4">
            NO GPU DATA
          </div>
        ) : (
          <>
            {/* GPU name */}
            <div className="text-[8px] tracking-[2px] text-[var(--accent)] opacity-50 mb-3 truncate uppercase">
              {gpu.name}
            </div>

            {/* Utilization ring */}
            <UtilRing value={gpu.utilization} />

            {/* Temperature */}
            <HoloBar
              label="TEMP"
              value={gpu.temp}
              max={100}
              color={tempColor(gpu.temp)}
              unit="C"
            />

            {/* VRAM */}
            <HoloBar
              label="VRAM"
              value={gpu.memUsed}
              max={gpu.memTotal}
              color="#40a0f0"
              unit="MB"
            />

            {/* Power */}
            <HoloBar
              label="POWER"
              value={gpu.power}
              max={gpu.powerLimit}
              color="#c080f0"
              unit="W"
            />

            {/* Clocks + Fan — compact row */}
            <div className="flex justify-between mt-2 text-[9px] tabular-nums opacity-40">
              <span>{gpu.clockCore}MHz core</span>
              <span>{gpu.clockMem}MHz mem</span>
              <span>FAN {gpu.fan}%</span>
            </div>
          </>
        )}
      </div>
    </HudPanel>
  );
}
