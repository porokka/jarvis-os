"use client";

import { useState, useEffect, useMemo, useRef } from "react";

interface Device {
  ip: string;
  mac: string;
  hostname: string;
  type: string;
  vendor: string;
  icon: string;
  ports: number[];
}

interface Topology {
  devices: Device[];
  gateway: string;
  subnet: string;
  scan_time?: number;
}

// Device type → color
const TYPE_COLORS: Record<string, string> = {
  router: "#f0c040",
  switch: "#f0c040",
  ap: "#f0a040",
  desktop: "#40a0f0",
  laptop: "#40a0f0",
  server: "#40f080",
  ai: "#c080f0",
  media: "#f06040",
  shield: "#76b900",
  tv: "#f06040",
  phone: "#80d0f0",
  nas: "#40f080",
  printer: "#a0a0a0",
  speaker: "#f080c0",
  iot: "#60c0a0",
  camera: "#f04040",
  receiver: "#d09040",
  cast: "#f06040",
  unknown: "#606060",
};

// Device type → SVG icon path
function DeviceIcon({ type, x, y, size = 18 }: { type: string; x: number; y: number; size?: number }) {
  const color = TYPE_COLORS[type] || "#606060";
  const half = size / 2;

  switch (type) {
    case "router":
      return (
        <g transform={`translate(${x - half},${y - half})`}>
          <rect width={size} height={size} rx="3" fill={color} opacity="0.15" stroke={color} strokeWidth="1" />
          <circle cx={half} cy={half - 3} r="2" fill={color} />
          <line x1={half} y1={half - 1} x2={half - 5} y2={half + 5} stroke={color} strokeWidth="1" />
          <line x1={half} y1={half - 1} x2={half + 5} y2={half + 5} stroke={color} strokeWidth="1" />
          <line x1={half} y1={half - 1} x2={half} y2={half + 5} stroke={color} strokeWidth="1" />
        </g>
      );
    case "desktop":
    case "laptop":
    case "server":
      return (
        <g transform={`translate(${x - half},${y - half})`}>
          <rect width={size} height={size} rx="3" fill={color} opacity="0.15" stroke={color} strokeWidth="1" />
          <rect x={half - 5} y={half - 5} width="10" height="7" rx="1" fill="none" stroke={color} strokeWidth="1" />
          <line x1={half - 3} y1={half + 4} x2={half + 3} y2={half + 4} stroke={color} strokeWidth="1" />
        </g>
      );
    case "phone":
      return (
        <g transform={`translate(${x - half},${y - half})`}>
          <rect width={size} height={size} rx="3" fill={color} opacity="0.15" stroke={color} strokeWidth="1" />
          <rect x={half - 3} y={half - 5} width="6" height="10" rx="1" fill="none" stroke={color} strokeWidth="1" />
        </g>
      );
    case "media":
    case "shield":
    case "tv":
    case "cast":
      return (
        <g transform={`translate(${x - half},${y - half})`}>
          <rect width={size} height={size} rx="3" fill={color} opacity="0.15" stroke={color} strokeWidth="1" />
          <rect x={half - 6} y={half - 4} width="12" height="7" rx="1" fill="none" stroke={color} strokeWidth="1" />
          <line x1={half - 2} y1={half + 5} x2={half + 2} y2={half + 5} stroke={color} strokeWidth="1" />
        </g>
      );
    default:
      return (
        <g transform={`translate(${x - half},${y - half})`}>
          <rect width={size} height={size} rx="3" fill={color} opacity="0.15" stroke={color} strokeWidth="1" />
          <circle cx={half} cy={half} r="3" fill="none" stroke={color} strokeWidth="1" />
        </g>
      );
  }
}

export function NetworkMap({ onScanComplete }: { onScanComplete?: () => void } = {}) {
  const [topology, setTopology] = useState<Topology>({ devices: [], gateway: "192.168.0.1", subnet: "" });
  const [hoveredDevice, setHoveredDevice] = useState<Device | null>(null);
  const [scanning, setScanning] = useState(false);
  const lastScanRef = useRef(0);

  // Poll for topology — detect fresh scans
  useEffect(() => {
    let active = true;

    async function poll() {
      try {
        const res = await fetch("/api/network", { cache: "no-store" });
        const data = await res.json();
        if (!active) return;
        if (data.devices && data.devices.length > 0) {
          setTopology(data);
          // Detect fresh scan
          if (data.scan_time && data.scan_time > lastScanRef.current && lastScanRef.current > 0) {
            setScanning(false);
            onScanComplete?.();
          }
          lastScanRef.current = data.scan_time || 0;
        }
      } catch {}
    }

    poll();
    const id = setInterval(poll, 5000);
    return () => { active = false; clearInterval(id); };
  }, [onScanComplete]);

  const handleScan = async () => {
    setScanning(true);
    try {
      await fetch("/api/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "scan network" }),
      });
      // Poll for results
      const poll = setInterval(async () => {
        const res = await fetch("/api/network", { cache: "no-store" });
        const data = await res.json();
        if (data.devices && data.devices.length > 0) {
          setTopology(data);
          setScanning(false);
          clearInterval(poll);
        }
      }, 3000);
      // Timeout after 2 minutes
      setTimeout(() => { setScanning(false); clearInterval(poll); }, 120000);
    } catch {
      setScanning(false);
    }
  };

  // Layout: router at top, devices in a grid below with proper spacing
  const layout = useMemo(() => {
    const devices = topology.devices || [];
    if (devices.length === 0) return [];

    const router = devices.find(d => d.type === "router");
    const others = devices.filter(d => d.type !== "router");

    const positioned: { device: Device; x: number; y: number }[] = [];

    // Grid layout params
    const cols = Math.min(6, Math.max(3, Math.ceil(Math.sqrt(others.length))));
    const cellW = 90;
    const cellH = 55;
    const gridW = cols * cellW;
    const totalW = Math.max(gridW + 60, 500);
    const centerX = totalW / 2;
    const routerY = 35;

    // Router at top center
    if (router) {
      positioned.push({ device: router, x: centerX, y: routerY });
    }

    // Sort devices: group by type for visual clustering
    const typeOrder = ["desktop", "server", "ai", "media", "shield", "tv", "phone", "speaker", "nas", "printer", "iot", "receiver", "cast", "unknown"];
    others.sort((a, b) => {
      const ai = typeOrder.indexOf(a.type);
      const bi = typeOrder.indexOf(b.type);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });

    // Place in grid
    const startY = routerY + 65;
    const startX = centerX - ((Math.min(cols, others.length) - 1) * cellW) / 2;

    for (let i = 0; i < others.length; i++) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      positioned.push({
        device: others[i],
        x: startX + col * cellW,
        y: startY + row * cellH,
      });
    }

    return positioned;
  }, [topology]);

  const maxX = Math.max(500, ...layout.map(l => l.x + 50));
  const maxY = Math.max(200, ...layout.map(l => l.y + 40));
  const svgWidth = maxX;
  const svgHeight = maxY;
  const routerPos = layout.find(l => l.device.type === "router");

  // Better display name: prefer hostname, fallback to vendor + last octet
  function displayName(d: Device): string {
    if (d.hostname && d.hostname !== d.ip && d.hostname.length > 1) {
      return d.hostname.length > 16 ? d.hostname.slice(0, 14) + ".." : d.hostname;
    }
    if (d.vendor) {
      const lastOctet = d.ip.split(".").pop();
      return `${d.vendor} (.${lastOctet})`;
    }
    return d.ip.replace("192.168.0.", ".0.");
  }

  return (
    <div className="network-map">
      <div className="nm-header">
        <span className="nm-title">NETWORK TOPOLOGY</span>
        <button
          className={`nm-scan-btn ${scanning ? "scanning" : ""}`}
          onClick={handleScan}
          disabled={scanning}
        >
          {scanning ? "SCANNING..." : "SCAN"}
        </button>
      </div>

      {layout.length === 0 ? (
        <div className="nm-empty">
          <span>No topology data. Click SCAN to discover devices.</span>
        </div>
      ) : (
        <div className="nm-svg-wrap">
          <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="nm-svg">
            {/* Connection lines from router to each device */}
            {routerPos && layout.filter(l => l.device.type !== "router").map((l, i) => (
              <line
                key={`line-${i}`}
                x1={routerPos.x} y1={routerPos.y + 9}
                x2={l.x} y2={l.y - 9}
                stroke={TYPE_COLORS[l.device.type] || "#333"}
                strokeWidth="0.5"
                opacity="0.3"
                strokeDasharray="3,3"
              />
            ))}

            {/* Devices */}
            {layout.map((l, i) => {
              const color = TYPE_COLORS[l.device.type] || "#606060";
              return (
                <g
                  key={i}
                  className="nm-device"
                  onMouseEnter={() => setHoveredDevice(l.device)}
                  onMouseLeave={() => setHoveredDevice(null)}
                >
                  <DeviceIcon type={l.device.type} x={l.x} y={l.y} />
                  {/* Label */}
                  <text
                    x={l.x} y={l.y + 16}
                    textAnchor="middle"
                    fill={color}
                    fontSize="7"
                    opacity="0.8"
                    fontWeight="500"
                  >
                    {displayName(l.device)}
                  </text>
                  <text
                    x={l.x} y={l.y + 24}
                    textAnchor="middle"
                    fill="rgba(255,255,255,0.3)"
                    fontSize="5.5"
                  >
                    {l.device.ip}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredDevice && (
        <div className="nm-tooltip">
          <div className="nm-tt-name">{hoveredDevice.hostname}</div>
          <div className="nm-tt-detail">{hoveredDevice.ip} &middot; {hoveredDevice.mac}</div>
          <div className="nm-tt-detail">{hoveredDevice.type}{hoveredDevice.vendor ? ` (${hoveredDevice.vendor})` : ""}</div>
          {hoveredDevice.ports.length > 0 && (
            <div className="nm-tt-detail">Ports: {hoveredDevice.ports.join(", ")}</div>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="nm-legend">
        {topology.devices.length > 0 && (
          <span className="nm-count">{topology.devices.length} devices</span>
        )}
      </div>

      <style jsx>{`
        .network-map {
          padding: 0;
          position: relative;
        }
        .nm-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 10px 12px 6px;
        }
        .nm-title {
          font-size: 8px; letter-spacing: 3px; text-transform: uppercase;
          color: var(--accent); opacity: 0.4;
        }
        .nm-scan-btn {
          font-size: 7px; letter-spacing: 2px; padding: 2px 8px;
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 2px; color: var(--accent); opacity: 0.5;
          cursor: pointer; transition: all 0.2s; text-transform: uppercase;
        }
        .nm-scan-btn:hover { opacity: 1; border-color: var(--accent); }
        .nm-scan-btn.scanning {
          color: #f0c040; border-color: #f0c04040;
          animation: scan-pulse 1s ease-in-out infinite;
        }
        .nm-scan-btn:disabled { cursor: wait; }
        .nm-empty {
          padding: 20px 12px; text-align: center;
          font-size: 9px; color: rgba(255,255,255,0.2);
        }
        .nm-svg-wrap {
          padding: 0 8px 8px;
          overflow: hidden;
        }
        .nm-svg {
          width: 100%;
          height: auto;
        }
        .nm-device { cursor: pointer; }
        .nm-device:hover { filter: brightness(1.5); }
        .nm-tooltip {
          position: absolute; bottom: 30px; left: 12px; right: 12px;
          background: rgba(0,0,0,0.85); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 4px; padding: 8px 10px;
        }
        .nm-tt-name {
          font-size: 10px; color: var(--accent); margin-bottom: 2px;
        }
        .nm-tt-detail {
          font-size: 8px; color: rgba(255,255,255,0.4); line-height: 1.4;
        }
        .nm-legend {
          padding: 0 12px 8px; display: flex; justify-content: flex-end;
        }
        .nm-count {
          font-size: 7px; letter-spacing: 1px; opacity: 0.25;
          text-transform: uppercase;
        }
        @keyframes scan-pulse {
          0%, 100% { opacity: 0.5; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
