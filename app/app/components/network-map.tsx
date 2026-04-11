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
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
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

  // Layout: 3-tier hierarchy — router → infrastructure → end devices
  const INFRA_TYPES = new Set(["switch", "ap", "router"]);

  const { layout, connections } = useMemo(() => {
    const devices = topology.devices || [];
    if (devices.length === 0) return { layout: [], connections: [] };

    const router = devices.find(d => d.type === "router");
    const infra = devices.filter(d => d.type !== "router" && INFRA_TYPES.has(d.type));
    const endpoints = devices.filter(d => d.type !== "router" && !INFRA_TYPES.has(d.type));

    const positioned: { device: Device; x: number; y: number; tier: number }[] = [];
    const conns: { from: number; to: number }[] = [];

    const cellW = 120;
    const tierGap = 90;

    // Tier 0: Router
    const routerY = 40;
    const maxPerRow = Math.min(8, Math.max(4, Math.ceil(Math.sqrt(endpoints.length + 1))));
    const totalW = Math.max(maxPerRow * cellW + 80, 700);
    const centerX = totalW / 2;

    if (router) {
      positioned.push({ device: router, x: centerX, y: routerY, tier: 0 });
    }

    // Tier 1: Infrastructure (switches, APs)
    const infraY = routerY + tierGap;
    if (infra.length > 0) {
      const startX = centerX - ((infra.length - 1) * cellW) / 2;
      for (let i = 0; i < infra.length; i++) {
        const idx = positioned.length;
        positioned.push({ device: infra[i], x: startX + i * cellW, y: infraY, tier: 1 });
        // Connect to router
        if (router) conns.push({ from: 0, to: idx });
      }
    }

    // Tier 2: End devices — distribute under infra or directly under router
    const endY = (infra.length > 0 ? infraY : routerY) + tierGap;
    const cols = maxPerRow;
    const endStartX = centerX - ((Math.min(cols, endpoints.length) - 1) * cellW) / 2;

    for (let i = 0; i < endpoints.length; i++) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const idx = positioned.length;
      positioned.push({
        device: endpoints[i],
        x: endStartX + col * cellW,
        y: endY + row * 65,
        tier: 2,
      });

      // Connect to nearest infra device, or router if no infra
      if (infra.length > 0) {
        // Assign to infra device by distributing evenly
        const infraIdx = (i % infra.length) + (router ? 1 : 0);
        conns.push({ from: infraIdx, to: idx });
      } else if (router) {
        conns.push({ from: 0, to: idx });
      }
    }

    return { layout: positioned, connections: conns };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topology]);

  const maxX = layout.length > 0 ? Math.max(500, ...layout.map(l => l.x + 50)) : 500;
  const maxY = layout.length > 0 ? Math.max(200, ...layout.map(l => l.y + 40)) : 200;
  const svgWidth = maxX;
  const svgHeight = maxY;

  // Display name: hostname > vendor+type > type+IP
  function displayName(d: Device): string {
    const name = d.hostname && d.hostname !== d.ip && d.hostname.length > 1 ? d.hostname : "";
    if (name) return name.length > 16 ? name.slice(0, 14) + ".." : name;

    const typeLabel: Record<string, string> = {
      router: "Router", desktop: "PC", laptop: "Laptop", server: "Server",
      phone: "Phone", media: "Media", shield: "Shield", tv: "TV",
      nas: "NAS", printer: "Printer", speaker: "Speaker", iot: "IoT",
      camera: "Camera", receiver: "Receiver", cast: "Cast", ai: "AI",
      ap: "Access Point", switch: "Switch", unknown: "Device",
    };
    const t = typeLabel[d.type] || "Device";
    const octet = d.ip.split(".").pop();
    if (d.vendor) return `${d.vendor} ${t}`;
    return `${t} .${octet}`;
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
            {/* Connection lines following hierarchy */}
            {connections.map((conn, i) => {
              const from = layout[conn.from];
              const to = layout[conn.to];
              if (!from || !to) return null;
              const isInfra = from.tier === 0 && to.tier === 1;
              return (
                <line
                  key={`conn-${i}`}
                  x1={from.x} y1={from.y + 10}
                  x2={to.x} y2={to.y - 10}
                  stroke={isInfra ? "#f0c040" : (TYPE_COLORS[to.device.type] || "#333")}
                  strokeWidth={isInfra ? "1" : "0.5"}
                  opacity={isInfra ? "0.5" : "0.2"}
                  strokeDasharray={isInfra ? "" : "3,3"}
                />
              );
            })}

            {/* Devices */}
            {layout.map((l, i) => {
              const color = TYPE_COLORS[l.device.type] || "#606060";
              return (
                <g
                  key={i}
                  className="nm-device"
                  onClick={() => setSelectedDevice(l.device)}
                >
                  <DeviceIcon type={l.device.type} x={l.x} y={l.y} size={22} />
                  {/* Label */}
                  <text
                    x={l.x} y={l.y + 18}
                    textAnchor="middle"
                    fill={color}
                    fontSize="8"
                    opacity="0.85"
                    fontWeight="500"
                  >
                    {displayName(l.device)}
                  </text>
                  <text
                    x={l.x} y={l.y + 28}
                    textAnchor="middle"
                    fill="rgba(255,255,255,0.35)"
                    fontSize="6.5"
                  >
                    {l.device.ip}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {/* Device info modal */}
      {selectedDevice && (
        <div className="nm-modal-overlay" onClick={() => setSelectedDevice(null)}>
          <div className="nm-modal" onClick={e => e.stopPropagation()}>
            <div className="nm-modal-header">
              <svg width="28" height="28" viewBox="0 0 28 28">
                <DeviceIcon type={selectedDevice.type} x={14} y={14} size={24} />
              </svg>
              <div className="nm-modal-title">
                <div className="nm-modal-name">{selectedDevice.hostname || selectedDevice.ip}</div>
                <div className="nm-modal-type" style={{ color: TYPE_COLORS[selectedDevice.type] || "#888" }}>
                  {selectedDevice.type.toUpperCase()}{selectedDevice.vendor ? ` \u2022 ${selectedDevice.vendor}` : ""}
                </div>
              </div>
              <button className="nm-modal-close" onClick={() => setSelectedDevice(null)}>&times;</button>
            </div>

            <div className="nm-modal-body">
              <div className="nm-modal-row">
                <span className="nm-modal-label">IP ADDRESS</span>
                <span className="nm-modal-value">{selectedDevice.ip}</span>
              </div>
              {selectedDevice.mac && (
                <div className="nm-modal-row">
                  <span className="nm-modal-label">MAC ADDRESS</span>
                  <span className="nm-modal-value">{selectedDevice.mac}</span>
                </div>
              )}
              {selectedDevice.hostname && selectedDevice.hostname !== selectedDevice.ip && (
                <div className="nm-modal-row">
                  <span className="nm-modal-label">HOSTNAME</span>
                  <span className="nm-modal-value">{selectedDevice.hostname}</span>
                </div>
              )}

              {selectedDevice.ports.length > 0 && (
                <>
                  <div className="nm-modal-section">OPEN PORTS</div>
                  <div className="nm-modal-ports">
                    {selectedDevice.ports.map(port => {
                      const portLabels: Record<number, string> = {
                        22: "SSH", 80: "HTTP", 443: "HTTPS", 554: "RTSP",
                        631: "IPP", 1400: "Sonos", 3000: "Dev", 3689: "DAAP",
                        5000: "DSM", 5001: "DSM-SSL", 5555: "ADB",
                        8008: "Cast", 8080: "HTTP-Alt", 8200: "DLNA",
                        8443: "HTTPS-Alt", 9100: "Print", 11434: "Ollama",
                        32400: "Plex",
                      };
                      const label = portLabels[port] || `Port ${port}`;
                      const isWeb = [80, 443, 8080, 8443, 5000, 5001, 3000, 8200, 32400].includes(port);
                      const proto = [443, 8443, 5001].includes(port) ? "https" : "http";
                      const url = `${proto}://${selectedDevice.ip}:${port}`;

                      return (
                        <div key={port} className="nm-port-item">
                          <span className="nm-port-num">{port}</span>
                          <span className="nm-port-label">{label}</span>
                          {isWeb && (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="nm-port-link"
                            >
                              OPEN &rarr;
                            </a>
                          )}
                          {port === 5555 && (
                            <button
                              className="nm-port-link"
                              onClick={() => {
                                fetch("/api/input", {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ text: `connect adb to ${selectedDevice.ip}` }),
                                });
                              }}
                            >
                              ADB CONNECT
                            </button>
                          )}
                          {port === 22 && (
                            <span className="nm-port-hint">ssh {selectedDevice.ip}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          </div>
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
          overflow: auto;
          display: flex;
          justify-content: center;
        }
        .nm-svg {
          width: 100%;
          max-width: 900px;
          height: auto;
          min-height: 400px;
        }
        .nm-device { cursor: pointer; }
        .nm-device:hover { filter: brightness(1.5); }
        .nm-modal-overlay {
          position: fixed; inset: 0; z-index: 100;
          background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
        }
        .nm-modal {
          background: #0a0e14; border: 1px solid rgba(255,255,255,0.1);
          border-radius: 6px; width: 380px; max-height: 80vh; overflow-y: auto;
          box-shadow: 0 0 40px rgba(0,200,255,0.1);
        }
        .nm-modal-header {
          display: flex; align-items: center; gap: 10px;
          padding: 16px 16px 12px; border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .nm-modal-title { flex: 1; }
        .nm-modal-name {
          font-size: 13px; color: #fff; font-weight: 500;
        }
        .nm-modal-type {
          font-size: 8px; letter-spacing: 2px; text-transform: uppercase; opacity: 0.7; margin-top: 2px;
        }
        .nm-modal-close {
          font-size: 18px; color: rgba(255,255,255,0.2); background: none; border: none;
          cursor: pointer; padding: 0 4px; line-height: 1;
        }
        .nm-modal-close:hover { color: #f04040; }
        .nm-modal-body { padding: 12px 16px 16px; }
        .nm-modal-row {
          display: flex; justify-content: space-between; align-items: center;
          padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.03);
        }
        .nm-modal-label {
          font-size: 8px; letter-spacing: 2px; color: rgba(255,255,255,0.3);
          text-transform: uppercase;
        }
        .nm-modal-value {
          font-size: 11px; color: rgba(255,255,255,0.7); font-family: 'SF Mono', monospace;
        }
        .nm-modal-section {
          font-size: 8px; letter-spacing: 2px; color: var(--accent); opacity: 0.5;
          text-transform: uppercase; margin-top: 14px; margin-bottom: 8px;
        }
        .nm-modal-ports { display: flex; flex-direction: column; gap: 4px; }
        .nm-port-item {
          display: flex; align-items: center; gap: 8px;
          padding: 5px 8px; background: rgba(255,255,255,0.02);
          border-radius: 3px; border: 1px solid rgba(255,255,255,0.04);
        }
        .nm-port-num {
          font-size: 11px; color: var(--accent); font-family: 'SF Mono', monospace;
          min-width: 40px;
        }
        .nm-port-label {
          font-size: 9px; color: rgba(255,255,255,0.5); flex: 1;
        }
        .nm-port-link {
          font-size: 7px; letter-spacing: 2px; text-transform: uppercase;
          color: #40f080; text-decoration: none; padding: 2px 6px;
          border: 1px solid #40f08040; border-radius: 2px;
          background: none; cursor: pointer; transition: all 0.2s;
        }
        .nm-port-link:hover {
          background: rgba(64,240,128,0.1); border-color: #40f080;
        }
        .nm-port-hint {
          font-size: 8px; color: rgba(255,255,255,0.2); font-family: 'SF Mono', monospace;
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
