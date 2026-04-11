"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ── Config ────────────────────────────────────────────────────
const _host       = typeof window !== "undefined" ? window.location.hostname : "localhost";
const _proto      = typeof window !== "undefined" ? window.location.protocol : "http:";
const API_BASE    = `${_proto}//${_host}:7800`;
const BRIDGE_BASE = `${_proto}//${_host}:7799`;
const TOKEN       = process.env.NEXT_PUBLIC_JARVIS_TOKEN || "jarvis-local-token";

const headers = {
  "Content-Type": "application/json",
  "Authorization": `Bearer ${TOKEN}`,
};

// ── Data fetching ─────────────────────────────────────────────
async function api(path, options = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, { headers, ...options });
    return await res.json();
  } catch { return null; }
}

// ── Styles ────────────────────────────────────────────────────
const C = {
  bg:      "#000d1a",
  panel:   "rgba(0,20,40,0.85)",
  border:  "rgba(0,100,160,0.25)",
  blue:    "#00b4ff",
  green:   "#00ff88",
  orange:  "#ff9900",
  purple:  "#b400ff",
  pink:    "#ff4488",
  teal:    "#44ffdd",
  yellow:  "#ffdd44",
  red:     "#ff3344",
  text:    "#a0d8ff",
  muted:   "rgba(160,216,255,0.4)",
  dimmed:  "rgba(160,216,255,0.2)",
};

const font = { mono: "'Share Tech Mono', monospace", orb: "'Orbitron', monospace" };

// ── Reusable components ───────────────────────────────────────
function Dot({ status }) {
  const col = { active:"#00ff88", thinking:"#ff9900", speaking:"#00b4ff", standby:"#1a3a5a", running:"#00ff88", stopped:"#ff3344", unknown:"#555" }[status] || "#555";
  return <span style={{ display:"inline-block", width:7, height:7, borderRadius:"50%", background:col, boxShadow: status !== "standby" && status !== "stopped" ? `0 0 6px ${col}` : "none", flexShrink:0 }} />;
}

function Panel({ children, title, style = {} }) {
  return (
    <div style={{ background:C.panel, border:`1px solid ${C.border}`, borderRadius:8, padding:16, ...style }}>
      {title && <div style={{ fontFamily:font.orb, fontSize:10, color:C.blue, letterSpacing:3, marginBottom:14, opacity:0.7 }}>{title}</div>}
      {children}
    </div>
  );
}

function Btn({ children, onClick, color = C.blue, disabled, small, danger, style = {} }) {
  const col = danger ? C.red : color;
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background:`${col}11`, border:`1px solid ${col}55`,
      borderRadius:6, color:col, fontFamily:font.orb,
      fontSize:small ? 9 : 10, letterSpacing:1,
      padding: small ? "6px 10px" : "10px 18px",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.4 : 1, transition:"all 0.2s",
      ...style
    }}>
      {children}
    </button>
  );
}

function Input({ value, onChange, placeholder, style = {} }) {
  return (
    <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
      style={{ background:"rgba(0,20,40,0.8)", border:`1px solid ${C.border}`, borderRadius:6,
        padding:"10px 14px", color:C.text, fontFamily:"monospace", fontSize:13, outline:"none",
        width:"100%", ...style }} />
  );
}

function Badge({ label, color }) {
  return <span style={{ fontSize:9, padding:"3px 8px", borderRadius:4, background:`${color}22`, color, border:`1px solid ${color}44`, letterSpacing:1, fontFamily:font.orb }}>{label}</span>;
}

function ProgressBar({ value, max, color = C.blue }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div style={{ height:4, background:"rgba(0,80,120,0.2)", borderRadius:2 }}>
      <div style={{ height:"100%", width:`${pct}%`, background:color, borderRadius:2, transition:"width 0.5s" }} />
    </div>
  );
}

// ── GPU Card ──────────────────────────────────────────────────
function GpuCard({ gpu }) {
  const col = gpu.index === 0 ? C.blue : C.green;
  const vramPct = (gpu.vram_used / gpu.vram_total) * 100;
  const powerPct = (gpu.power_draw / gpu.power_limit) * 100;
  return (
    <Panel style={{ position:"relative", overflow:"hidden" }}>
      <div style={{ position:"absolute", top:0, left:0, right:0, height:2, background:col }} />
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:12 }}>
        <div>
          <div style={{ fontFamily:font.orb, fontSize:10, color:col, letterSpacing:2 }}>GPU {gpu.index}</div>
          <div style={{ fontSize:11, color:C.muted, marginTop:2 }}>{gpu.name}</div>
        </div>
        <Badge label={`${gpu.temp}°C`} color={gpu.temp > 80 ? C.red : gpu.temp > 70 ? C.orange : C.green} />
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
        <div>
          <div style={{ fontSize:10, color:C.dimmed, marginBottom:4 }}>VRAM</div>
          <div style={{ fontSize:18, color:C.text, fontWeight:500 }}>{gpu.vram_used.toFixed(0)}<span style={{ fontSize:11, color:C.muted }}>/{gpu.vram_total.toFixed(0)}GB</span></div>
          <ProgressBar value={gpu.vram_used} max={gpu.vram_total} color={col} />
        </div>
        <div>
          <div style={{ fontSize:10, color:C.dimmed, marginBottom:4 }}>POWER</div>
          <div style={{ fontSize:18, color:C.text, fontWeight:500 }}>{gpu.power_draw.toFixed(0)}<span style={{ fontSize:11, color:C.muted }}>W</span></div>
          <ProgressBar value={gpu.power_draw} max={gpu.power_limit} color={powerPct > 90 ? C.red : C.orange} />
        </div>
      </div>
      <div style={{ marginTop:12 }}>
        <div style={{ fontSize:10, color:C.dimmed, marginBottom:4 }}>UTILIZATION</div>
        <ProgressBar value={gpu.utilization} max={100} color={col} />
        <div style={{ fontSize:10, color:C.muted, marginTop:4 }}>{gpu.utilization}%</div>
      </div>
    </Panel>
  );
}

// ── Upload Zone ───────────────────────────────────────────────
function UploadZone({ label, onUpload, accept = ".zip", extra }) {
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const inputRef = useRef();

  async function handleFile(file) {
    if (!file) return;
    setLoading(true);
    setStatus(`Uploading ${file.name}...`);
    try {
      await onUpload(file);
      setStatus(`✓ ${file.name} synced`);
    } catch (e) {
      setStatus(`✗ Upload failed: ${e.message}`);
    }
    setLoading(false);
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
      onClick={() => inputRef.current?.click()}
      style={{
        border:`1px dashed ${dragging ? C.blue : C.border}`,
        borderRadius:8, padding:24, textAlign:"center",
        cursor:"pointer", transition:"all 0.2s",
        background: dragging ? "rgba(0,180,255,0.05)" : "transparent",
      }}
    >
      <input ref={inputRef} type="file" accept={accept} style={{ display:"none" }}
        onChange={e => handleFile(e.target.files[0])} />
      <div style={{ fontSize:24, marginBottom:8 }}>⬆</div>
      <div style={{ fontFamily:font.orb, fontSize:10, color:C.blue, letterSpacing:2, marginBottom:4 }}>{label}</div>
      <div style={{ fontSize:11, color:C.muted }}>Drag & drop or click • .zip only</div>
      {extra && <div style={{ fontSize:10, color:C.dimmed, marginTop:4 }}>{extra}</div>}
      {status && <div style={{ fontSize:11, color: status.startsWith("✓") ? C.green : C.red, marginTop:8 }}>{status}</div>}
      {loading && <div style={{ fontSize:11, color:C.orange, marginTop:4 }}>Processing...</div>}
    </div>
  );
}

// ── Model Manager ─────────────────────────────────────────────
function ModelManager() {
  const [models, setModels] = useState([]);
  const [pullName, setPullName] = useState("");
  const [pullGpu, setPullGpu] = useState(0);
  const [pulling, setPulling] = useState(false);
  const [pullStatus, setPullStatus] = useState("");

  useEffect(() => { loadModels(); }, []);

  async function loadModels() {
    const data = await api("/api/ollama/models");
    if (data?.models) setModels(data.models);
  }

  async function pullModel() {
    if (!pullName.trim()) return;
    setPulling(true);
    setPullStatus("Pulling... this may take several minutes");
    const result = await api("/api/ollama/pull", {
      method:"POST",
      body: JSON.stringify({ model: pullName, gpu: pullGpu })
    });
    setPullStatus(result?.success ? `✓ ${pullName} ready` : `✗ ${result?.stderr || "Failed"}`);
    setPulling(false);
    loadModels();
  }

  async function deleteModel(name) {
    if (!confirm(`Delete ${name}?`)) return;
    await api(`/api/ollama/models/${encodeURIComponent(name)}`, { method:"DELETE" });
    loadModels();
  }

  const suggested = ["mistral-nemo", "qwen3-coder:30b", "llama3.1:70b", "qwen3:30b-a3b", "qwen3-coder:8b"];

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
      <Panel title="INSTALLED MODELS">
        {models.length === 0 && <div style={{ color:C.muted, fontSize:12 }}>No models found. Pull one below.</div>}
        {models.map(m => (
          <div key={m.name} style={{ display:"flex", alignItems:"center", gap:12, padding:"10px 0", borderBottom:`1px solid ${C.border}` }}>
            <Dot status="active" />
            <div style={{ flex:1 }}>
              <div style={{ fontSize:13, color:C.text, fontFamily:"monospace" }}>{m.name}</div>
              <div style={{ fontSize:10, color:C.muted }}>{m.size}</div>
            </div>
            <Btn small danger onClick={() => deleteModel(m.name)}>REMOVE</Btn>
          </div>
        ))}
      </Panel>

      <Panel title="PULL NEW MODEL">
        <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
          <Input value={pullName} onChange={setPullName} placeholder="e.g. qwen3-coder:30b" />
          <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
            {suggested.map(s => (
              <button key={s} onClick={() => setPullName(s)} style={{
                background:"rgba(0,180,255,0.06)", border:`1px solid ${C.border}`,
                borderRadius:4, color:C.muted, fontSize:10, padding:"4px 10px", cursor:"pointer", fontFamily:"monospace"
              }}>{s}</button>
            ))}
          </div>
          <div style={{ display:"flex", gap:10, alignItems:"center" }}>
            <select value={pullGpu} onChange={e => setPullGpu(Number(e.target.value))} style={{
              background:"rgba(0,20,40,0.8)", border:`1px solid ${C.border}`, borderRadius:6,
              color:C.text, fontFamily:"monospace", fontSize:12, padding:"8px 12px"
            }}>
              <option value={0}>GPU 0 — RTX 3090 (24GB)</option>
              <option value={1}>GPU 1 — RTX 2080 (8GB)</option>
            </select>
            <Btn onClick={pullModel} disabled={pulling || !pullName.trim()}>
              {pulling ? "PULLING..." : "PULL MODEL"}
            </Btn>
          </div>
          {pullStatus && <div style={{ fontSize:11, color: pullStatus.startsWith("✓") ? C.green : pullStatus.startsWith("✗") ? C.red : C.orange }}>{pullStatus}</div>}
        </div>
      </Panel>
    </div>
  );
}

// ── Service Manager ───────────────────────────────────────────
function ServiceManager() {
  const [statuses, setStatuses] = useState({});
  const [actionStatus, setActionStatus] = useState("");

  const services = [
    { id:"ollama",          label:"Ollama",           color:C.blue },
    { id:"jarvis-watcher",  label:"JARVIS Watcher",   color:C.green },
    { id:"jarvis-api",      label:"System API",       color:C.orange },
    { id:"jarvis-nextjs",   label:"Next.js UI",       color:C.purple },
    { id:"jarvis-bridge",   label:"Voice Bridge",     color:C.teal },
  ];

  useEffect(() => { loadStatuses(); const t = setInterval(loadStatuses, 5000); return () => clearInterval(t); }, []);

  async function loadStatuses() {
    const data = await api("/api/services/status");
    if (data) setStatuses(data);
  }

  async function control(service, action) {
    setActionStatus(`${action}ing ${service}...`);
    const result = await api("/api/services/control", {
      method:"POST",
      body: JSON.stringify({ service, action })
    });
    setActionStatus(result?.success ? `✓ ${service} ${action}ed` : `✗ Failed`);
    setTimeout(loadStatuses, 1000);
  }

  return (
    <Panel title="SERVICES">
      {services.map(s => (
        <div key={s.id} style={{ display:"flex", alignItems:"center", gap:12, padding:"10px 0", borderBottom:`1px solid ${C.border}` }}>
          <Dot status={statuses[s.id] === "active" ? "active" : "stopped"} />
          <div style={{ flex:1 }}>
            <div style={{ fontSize:12, color:C.text, fontFamily:"monospace" }}>{s.label}</div>
            <div style={{ fontSize:10, color:C.muted }}>{statuses[s.id] || "checking..."}</div>
          </div>
          <div style={{ display:"flex", gap:6 }}>
            <Btn small color={C.green} onClick={() => control(s.id, "start")}>START</Btn>
            <Btn small color={C.orange} onClick={() => control(s.id, "restart")}>RESTART</Btn>
            <Btn small danger onClick={() => control(s.id, "stop")}>STOP</Btn>
          </div>
        </div>
      ))}
      {actionStatus && <div style={{ fontSize:11, color:C.orange, marginTop:10 }}>{actionStatus}</div>}
    </Panel>
  );
}

// ── Package Manager ───────────────────────────────────────────
function PackageManager() {
  const [pkg, setPkg] = useState("");
  const [mgr, setMgr] = useState("apt");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function install() {
    if (!pkg.trim()) return;
    setLoading(true);
    setStatus(`Installing ${mgr}:${pkg}...`);
    const result = await api("/api/packages/install", {
      method:"POST",
      body: JSON.stringify({ package: pkg, manager: mgr })
    });
    setStatus(result?.success ? `✓ ${pkg} installed` : `✗ ${result?.stderr?.slice(0,100) || "Failed"}`);
    setLoading(false);
  }

  async function upgrade() {
    setLoading(true);
    setStatus("Running apt upgrade...");
    const result = await api("/api/packages/upgrade", { method:"POST" });
    setStatus(result?.success ? "✓ System upgraded" : "✗ Upgrade failed");
    setLoading(false);
  }

  return (
    <Panel title="PACKAGE MANAGER">
      <div style={{ display:"flex", gap:10, marginBottom:10 }}>
        <select value={mgr} onChange={e => setMgr(e.target.value)} style={{
          background:"rgba(0,20,40,0.8)", border:`1px solid ${C.border}`, borderRadius:6,
          color:C.text, fontFamily:"monospace", fontSize:12, padding:"10px 12px"
        }}>
          <option value="apt">apt</option>
          <option value="pip">pip</option>
          <option value="npm">npm</option>
        </select>
        <Input value={pkg} onChange={setPkg} placeholder="package name" />
        <Btn onClick={install} disabled={loading || !pkg.trim()}>INSTALL</Btn>
      </div>
      <Btn onClick={upgrade} disabled={loading} color={C.orange}>UPGRADE ALL (apt)</Btn>
      {status && <div style={{ fontSize:11, color: status.startsWith("✓") ? C.green : status.startsWith("✗") ? C.red : C.orange, marginTop:10 }}>{status}</div>}
    </Panel>
  );
}

// ── Upload Page ───────────────────────────────────────────────
function UploadPage() {
  const [project, setProject] = useState("bullishbeat");
  const projects = ["bullishbeat", "caskra", "dravn", "gps-paintball", "varha", "alchemians", "jarvis-os"];

  async function uploadVault(file) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/upload/vault`, {
      method:"POST", headers:{ Authorization:`Bearer ${TOKEN}` }, body:form
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.message);
  }

  async function uploadCode(file) {
    const form = new FormData();
    form.append("file", file);
    form.append("project", project);
    const res = await fetch(`${API_BASE}/api/upload/code`, {
      method:"POST", headers:{ Authorization:`Bearer ${TOKEN}` }, body:form
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.message);
  }

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:20 }}>
      <Panel title="OBSIDIAN VAULT SYNC">
        <div style={{ fontSize:12, color:C.muted, marginBottom:16 }}>
          Export your Obsidian vault as a .zip and upload here.
          Files are merged into the JARVIS vault — existing files are updated, nothing deleted.
        </div>
        <UploadZone
          label="UPLOAD OBSIDIAN VAULT"
          extra="Export from Obsidian: File → Export vault as zip"
          onUpload={uploadVault}
        />
      </Panel>

      <Panel title="CODE DIRECTORY SYNC">
        <div style={{ fontSize:12, color:C.muted, marginBottom:16 }}>
          Upload a project directory as .zip. JARVIS agents can then read and work with the code.
        </div>
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:10, color:C.muted, marginBottom:6 }}>TARGET PROJECT</div>
          <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
            {projects.map(p => (
              <button key={p} onClick={() => setProject(p)} style={{
                background: project === p ? `${C.blue}22` : "transparent",
                border:`1px solid ${project === p ? C.blue : C.border}`,
                borderRadius:4, color: project === p ? C.blue : C.muted,
                fontSize:11, padding:"6px 12px", cursor:"pointer", fontFamily:"monospace"
              }}>{p}</button>
            ))}
          </div>
        </div>
        <UploadZone
          label={`UPLOAD ${project.toUpperCase()} CODE`}
          extra={`Will sync to ~/code/${project}/`}
          onUpload={uploadCode}
        />
      </Panel>

      <Panel title="AUDIT LOG">
        <AuditLog />
      </Panel>
    </div>
  );
}

// ── Audit Log ─────────────────────────────────────────────────
function AuditLog() {
  const [log, setLog] = useState([]);
  useEffect(() => {
    async function load() {
      const data = await api("/api/system/audit?lines=20");
      if (data?.log) setLog(data.log);
    }
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ fontFamily:"monospace", fontSize:11, color:C.muted, maxHeight:200, overflowY:"auto" }}>
      {log.length === 0 && <div>No audit entries yet.</div>}
      {log.map((line, i) => (
        <div key={i} style={{ padding:"3px 0", borderBottom:`1px solid ${C.border}` }}>
          {line}
        </div>
      ))}
    </div>
  );
}

// ── TTS helper ────────────────────────────────────────────────
function speak(text) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 0.95;
  utter.pitch = 0.85;
  const voices = speechSynthesis.getVoices();
  const v = voices.find(v => v.name.includes("Daniel") || v.lang === "en-GB");
  if (v) utter.voice = v;
  speechSynthesis.speak(utter);
}

// ── Chat ──────────────────────────────────────────────────────
function ChatPage() {
  const [messages, setMessages] = useState([
    { role:"jarvis", text:"Good day. All systems nominal. How may I assist you?", brain:"mistral" }
  ]);
  const [input, setInput] = useState("");
  const [state, setState] = useState("standby");
  const [brain, setBrain] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const [sttSupported, setSttSupported] = useState(false);
  const endRef = useRef();
  const recRef = useRef(null);
  const lastSpokenRef = useRef("");

  // Init speech recognition once
  useEffect(() => {
    const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
    if (!SR) return;
    setSttSupported(true);
    const rec = new SR();
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = false;
    rec.onresult = (e) => {
      const text = e.results[0][0].transcript;
      sendText(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    // Pre-load voices
    speechSynthesis?.getVoices();
  }, []);

  // Poll bridge for state + output
  useEffect(() => {
    const t = setInterval(async () => {
      const data = await fetch(`${BRIDGE_BASE}/state`).then(r => r.text()).catch(() => "standby");
      const out  = await fetch(`${BRIDGE_BASE}/output`).then(r => r.text()).catch(() => "");
      setState(data.trim());
      if (data.trim() === "speaking" && out.trim()) {
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.role === "jarvis" && last.text === out.trim()) return prev;
          // Speak aloud if voice is on and this is a new response
          if (voiceOn && out.trim() !== lastSpokenRef.current) {
            lastSpokenRef.current = out.trim();
            speak(out.trim());
          }
          return [...prev, { role:"jarvis", text:out.trim(), brain:"auto" }];
        });
      }
    }, 800);
    return () => clearInterval(t);
  }, [voiceOn]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior:"smooth" }); }, [messages]);

  const sendText = useCallback(async (text) => {
    if (!text.trim()) return;
    setMessages(prev => [...prev, { role:"user", text:text.trim() }]);
    setInput("");
    await fetch(`${BRIDGE_BASE}/input`, { method:"POST", headers:{ "Content-Type":"text/plain" }, body:text.trim() });
  }, []);

  async function send() { sendText(input); }

  function toggleMic() {
    if (!recRef.current) return;
    if (listening) { recRef.current.stop(); }
    else { recRef.current.start(); setListening(true); }
  }

  const brainCol = { claude:C.orange, mistral:C.green, qwen:C.blue, auto:C.teal };

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"calc(100vh - 160px)" }}>
      <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:16 }}>
        <Dot status={state} />
        <span style={{ fontSize:10, color:C.muted, letterSpacing:2 }}>{state.toUpperCase()}</span>
        {listening && <span style={{ fontSize:10, color:C.green, letterSpacing:2, animation:"pulse 0.8s ease-in-out infinite" }}>LISTENING</span>}
        <div style={{ marginLeft:"auto", display:"flex", gap:8 }}>
          <Btn small color={voiceOn ? C.green : C.muted} onClick={() => setVoiceOn(v => !v)}>
            {voiceOn ? "VOICE ON" : "VOICE OFF"}
          </Btn>
        </div>
      </div>
      <div style={{ flex:1, overflowY:"auto", background:"rgba(0,10,25,0.5)", border:`1px solid ${C.border}`, borderRadius:8, padding:16, marginBottom:16 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ display:"flex", flexDirection:"column", alignItems: m.role === "user" ? "flex-end" : "flex-start", marginBottom:14 }}>
            {m.role === "jarvis" && m.brain && (
              <div style={{ fontSize:9, color:C.dimmed, letterSpacing:2, marginBottom:4, paddingLeft:4, fontFamily:font.orb }}>
                JARVIS {m.brain && <span style={{ color:brainCol[m.brain] || C.muted }}>via {m.brain}</span>}
              </div>
            )}
            <div style={{
              maxWidth:"80%", padding:"10px 14px", fontFamily:"monospace", fontSize:13, lineHeight:1.6, color:C.text,
              borderRadius: m.role === "user" ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
              background: m.role === "user" ? "rgba(0,100,180,0.15)" : "rgba(0,40,60,0.8)",
              border:`1px solid ${m.role === "user" ? "rgba(0,180,255,0.2)" : C.border}`,
            }}>{m.text}</div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div style={{ display:"flex", gap:10 }}>
        {sttSupported && (
          <button onClick={toggleMic} style={{
            width:44, height:44, borderRadius:"50%",
            border:`2px solid ${listening ? C.green : "rgba(0,180,255,0.4)"}`,
            background: listening ? "rgba(0,255,136,0.12)" : "rgba(0,180,255,0.08)",
            color: listening ? C.green : C.blue,
            fontSize:20, cursor:"pointer", transition:"all 0.2s", flexShrink:0,
          }}>
            {listening ? "..." : "\uD83C\uDFA4"}
          </button>
        )}
        <Input value={input} onChange={setInput} placeholder="Command JARVIS..." style={{ flex:1 }}
          onKeyDown={e => e.key === "Enter" && send()} />
        <Btn onClick={send}>SEND</Btn>
      </div>
      {!sttSupported && (
        <div style={{ fontSize:10, color:C.orange, marginTop:8 }}>
          Voice input unavailable — requires HTTPS for external access
        </div>
      )}
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────
function Dashboard({ gpus }) {
  const projects = [
    { name:"BullishBeat", metric:"AUC 0.7951",    status:"live",     color:C.green },
    { name:"Caskra",      metric:"F2 Day 2",       status:"active",   color:C.orange },
    { name:"DRAVN",       metric:"28 connectors",  status:"active",   color:C.purple },
    { name:"GPS Game",    metric:"MVP phase",       status:"planning", color:C.teal },
    { name:"Varha ETL",   metric:"11 pipelines",   status:"active",   color:C.pink },
    { name:"Alchemians",  metric:"3 restaurants",  status:"active",   color:C.yellow },
  ];

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:16 }}>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit, minmax(180px, 1fr))", gap:10 }}>
        {projects.map(p => (
          <Panel key={p.name} style={{ position:"relative", overflow:"hidden" }}>
            <div style={{ position:"absolute", top:0, left:0, right:0, height:2, background:p.color, opacity:0.7 }} />
            <div style={{ fontFamily:font.orb, fontSize:9, color:p.color, letterSpacing:2, marginBottom:8 }}>{p.name}</div>
            <div style={{ fontSize:20, color:C.text, fontWeight:500, marginBottom:4 }}>{p.metric}</div>
            <Badge label={p.status.toUpperCase()} color={p.color} />
          </Panel>
        ))}
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit, minmax(280px, 1fr))", gap:12 }}>
        {gpus.map(g => <GpuCard key={g.index} gpu={g} />)}
      </div>
    </div>
  );
}

// ── Settings ──────────────────────────────────────────────────
function Settings() {
  const [tab, setTab] = useState("models");
  const tabs = ["models", "services", "packages"];
  return (
    <div>
      <div style={{ display:"flex", gap:8, marginBottom:16 }}>
        {tabs.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? `${C.blue}22` : "transparent",
            border:`1px solid ${tab === t ? C.blue : C.border}`,
            borderRadius:4, color: tab === t ? C.blue : C.muted,
            fontSize:10, padding:"8px 16px", cursor:"pointer", fontFamily:font.orb, letterSpacing:1
          }}>{t.toUpperCase()}</button>
        ))}
      </div>
      {tab === "models"   && <ModelManager />}
      {tab === "services" && <ServiceManager />}
      {tab === "packages" && <PackageManager />}
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────
export default function JarvisOS() {
  const [page, setPage] = useState("dashboard");
  const [gpus, setGpus] = useState([]);
  const [jarvisState, setJarvisState] = useState("standby");

  useEffect(() => {
    async function loadGpus() {
      const data = await api("/api/gpu/stats");
      if (data?.gpus) setGpus(data.gpus);
    }
    loadGpus();
    const t = setInterval(loadGpus, 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const t = setInterval(async () => {
      const data = await api("/api/jarvis/state");
      if (data?.state) setJarvisState(data.state);
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const pages = [
    { id:"dashboard", label:"DASHBOARD" },
    { id:"chat",      label:"JARVIS" },
    { id:"upload",    label:"UPLOAD" },
    { id:"settings",  label:"SETTINGS" },
  ];

  return (
    <div style={{ minHeight:"100vh", background:C.bg, fontFamily:font.mono,
      backgroundImage:"linear-gradient(rgba(0,180,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(0,180,255,0.025) 1px, transparent 1px)",
      backgroundSize:"40px 40px" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Share+Tech+Mono&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: rgba(0,180,255,0.3); border-radius: 2px; }
        input, select, button { box-sizing: border-box; }
        input:focus { border-color: rgba(0,180,255,0.6) !important; }
      `}</style>

      {/* Header */}
      <div style={{ borderBottom:`1px solid ${C.border}`, padding:"14px 24px",
        display:"flex", alignItems:"center", gap:16,
        background:"rgba(0,8,20,0.95)", position:"sticky", top:0, zIndex:100 }}>
        <div style={{ fontFamily:font.orb, color:C.blue, fontSize:13, letterSpacing:4 }}>J.A.R.V.I.S OS</div>
        <div style={{ width:1, height:18, background:C.border }} />
        <Dot status={jarvisState} />
        <span style={{ fontSize:10, color:C.muted, letterSpacing:2 }}>{jarvisState.toUpperCase()}</span>
        <div style={{ marginLeft:"auto", display:"flex", gap:6, alignItems:"center" }}>
          {gpus.map(g => (
            <div key={g.index} style={{ fontSize:10, color:C.muted, fontFamily:"monospace" }}>
              GPU{g.index}: <span style={{ color: g.index === 0 ? C.blue : C.green }}>{g.vram_used.toFixed(0)}GB</span>
            </div>
          ))}
        </div>
      </div>

      {/* Nav */}
      <div style={{ display:"flex", borderBottom:`1px solid ${C.border}`, padding:"0 24px", background:"rgba(0,5,15,0.5)" }}>
        {pages.map(p => (
          <button key={p.id} onClick={() => setPage(p.id)} style={{
            background:"none", border:"none", padding:"12px 20px",
            fontFamily:font.orb, fontSize:10, letterSpacing:2,
            color: page === p.id ? C.blue : C.muted,
            borderBottom: page === p.id ? `2px solid ${C.blue}` : "2px solid transparent",
            cursor:"pointer", transition:"all 0.2s"
          }}>{p.label}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding:24, maxWidth:1100, margin:"0 auto" }}>
        {page === "dashboard" && <Dashboard gpus={gpus} />}
        {page === "chat"      && <ChatPage />}
        {page === "upload"    && <UploadPage />}
        {page === "settings"  && <Settings />}
      </div>
    </div>
  );
}
