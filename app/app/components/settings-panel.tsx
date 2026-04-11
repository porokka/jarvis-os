"use client";

import { useState, useEffect } from "react";

interface Settings {
  fastModel: string;
  reasonModel: string;
  codeModel: string;
  deepModel: string;
  personality: string;
  voice: string;
  ttsEngine: string;
  audioOutput: string;
  wakeWord: boolean;
}

const MODEL_OPTIONS = [
  "qwen3:4b", "qwen3:8b", "qwen3:14b", "qwen3:30b-a3b", "qwen3:32b",
  "qwen3-coder:14b", "qwen3-coder:30b",
  "phi4:14b", "gemma3:12b", "mistral-nemo", "mistral-small:24b",
  "llama3.1:8b", "llama3.1:70b",
];

const PERSONALITIES = [
  { id: "jarvis", label: "J.A.R.V.I.S (British butler)" },
  { id: "friday", label: "F.R.I.D.A.Y (Casual)" },
  { id: "edith", label: "E.D.I.T.H (Tactical)" },
  { id: "hal", label: "HAL 9000 (Unsettling)" },
];

const VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"];

const TTS_ENGINES = [
  { id: "orpheus", label: "Orpheus (Local GPU)" },
  { id: "system", label: "System (PowerShell/espeak)" },
  { id: "browser", label: "Browser Speech Synthesis" },
];

export function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [settings, setSettings] = useState<Settings>({
    fastModel: "qwen3:8b",
    reasonModel: "qwen3:30b-a3b",
    codeModel: "qwen3-coder:30b",
    deepModel: "qwen3:30b-a3b",
    personality: "jarvis",
    voice: "tara",
    ttsEngine: "system",
    audioOutput: "default",
    wakeWord: true,
  });
  const [saved, setSaved] = useState(false);
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);

  // Load saved settings
  useEffect(() => {
    try {
      const s = localStorage.getItem("jarvis-settings");
      if (s) setSettings(JSON.parse(s));
    } catch {}

    // Get audio output devices
    navigator.mediaDevices?.enumerateDevices().then(devices => {
      setAudioDevices(devices.filter(d => d.kind === "audiooutput"));
    }).catch(() => {});
  }, []);

  function save() {
    localStorage.setItem("jarvis-settings", JSON.stringify(settings));

    // Send to bridge server
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).catch(() => {});

    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings(prev => ({ ...prev, [key]: value }));
  }

  if (!open) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={e => e.stopPropagation()}>
        <div className="settings-header">
          <span>SYSTEM CONFIGURATION</span>
          <button className="settings-close" onClick={onClose}>ESC</button>
        </div>

        <div className="settings-body">
          {/* Models */}
          <div className="settings-section">
            <div className="section-title">AI MODELS</div>
            <SettingRow label="Fast (chat)">
              <ModelSelect value={settings.fastModel} onChange={v => update("fastModel", v)} />
            </SettingRow>
            <SettingRow label="Reason (analysis)">
              <ModelSelect value={settings.reasonModel} onChange={v => update("reasonModel", v)} />
            </SettingRow>
            <SettingRow label="Code (programming)">
              <ModelSelect value={settings.codeModel} onChange={v => update("codeModel", v)} />
            </SettingRow>
            <SettingRow label="Deep (strategy)">
              <ModelSelect value={settings.deepModel} onChange={v => update("deepModel", v)} />
            </SettingRow>
          </div>

          {/* Personality */}
          <div className="settings-section">
            <div className="section-title">PERSONALITY</div>
            <SettingRow label="Character">
              <select
                value={settings.personality}
                onChange={e => update("personality", e.target.value)}
                className="setting-select"
              >
                {PERSONALITIES.map(p => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </SettingRow>
          </div>

          {/* Voice */}
          <div className="settings-section">
            <div className="section-title">VOICE OUTPUT</div>
            <SettingRow label="TTS Engine">
              <select
                value={settings.ttsEngine}
                onChange={e => update("ttsEngine", e.target.value)}
                className="setting-select"
              >
                {TTS_ENGINES.map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label="Orpheus Voice">
              <select
                value={settings.voice}
                onChange={e => update("voice", e.target.value)}
                className="setting-select"
              >
                {VOICES.map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label="Audio Output">
              <select
                value={settings.audioOutput}
                onChange={e => update("audioOutput", e.target.value)}
                className="setting-select"
              >
                <option value="default">System Default</option>
                {audioDevices.map(d => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || `Device ${d.deviceId.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </SettingRow>
          </div>

          {/* Voice Input */}
          <div className="settings-section">
            <div className="section-title">VOICE INPUT</div>
            <SettingRow label="Wake Word Mode">
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={settings.wakeWord}
                  onChange={e => update("wakeWord", e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </SettingRow>
          </div>
        </div>

        <div className="settings-footer">
          <button className="save-btn" onClick={save}>
            {saved ? "SAVED" : "APPLY"}
          </button>
        </div>
      </div>

      <style jsx>{`
        .settings-overlay {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.6);
          z-index: 100;
          display: flex;
          align-items: center;
          justify-content: center;
          backdrop-filter: blur(4px);
        }
        .settings-panel {
          width: 420px;
          max-height: 80vh;
          background: rgba(6, 10, 18, 0.95);
          border: 1px solid rgba(64, 160, 240, 0.15);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .settings-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 14px 18px;
          border-bottom: 1px solid rgba(64, 160, 240, 0.08);
          font-size: 10px;
          letter-spacing: 3px;
          color: var(--accent);
          opacity: 0.7;
        }
        .settings-close {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 4px;
          padding: 4px 10px;
          color: rgba(255, 255, 255, 0.4);
          font-size: 9px;
          letter-spacing: 1px;
          cursor: pointer;
        }
        .settings-close:hover { color: rgba(255, 255, 255, 0.7); }
        .settings-body {
          flex: 1;
          overflow-y: auto;
          padding: 12px 18px;
        }
        .settings-body::-webkit-scrollbar { width: 2px; }
        .settings-body::-webkit-scrollbar-thumb { background: rgba(64, 160, 240, 0.2); }
        .settings-section {
          margin-bottom: 16px;
        }
        .section-title {
          font-size: 8px;
          letter-spacing: 3px;
          color: var(--accent);
          opacity: 0.35;
          margin-bottom: 8px;
          padding-bottom: 4px;
          border-bottom: 1px solid rgba(64, 160, 240, 0.06);
        }
        .settings-footer {
          padding: 12px 18px;
          border-top: 1px solid rgba(64, 160, 240, 0.08);
          display: flex;
          justify-content: flex-end;
        }
        .save-btn {
          background: rgba(64, 160, 240, 0.1);
          border: 1px solid rgba(64, 160, 240, 0.3);
          border-radius: 4px;
          padding: 8px 24px;
          color: var(--accent);
          font-size: 10px;
          letter-spacing: 2px;
          cursor: pointer;
        }
        .save-btn:hover {
          background: rgba(64, 160, 240, 0.2);
        }
        .setting-select {
          width: 100%;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 4px;
          padding: 6px 8px;
          color: #e0e0e0;
          font-family: inherit;
          font-size: 11px;
          outline: none;
        }
        .setting-select:focus { border-color: rgba(64, 160, 240, 0.3); }
        .setting-select option { background: #0a0a14; }
        .toggle {
          position: relative;
          display: inline-block;
          width: 36px;
          height: 18px;
        }
        .toggle input { display: none; }
        .toggle-slider {
          position: absolute;
          inset: 0;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 9px;
          cursor: pointer;
          transition: 0.2s;
        }
        .toggle-slider::before {
          content: '';
          position: absolute;
          width: 14px;
          height: 14px;
          left: 2px;
          top: 2px;
          background: rgba(255, 255, 255, 0.3);
          border-radius: 50%;
          transition: 0.2s;
        }
        .toggle input:checked + .toggle-slider {
          background: rgba(64, 160, 240, 0.3);
        }
        .toggle input:checked + .toggle-slider::before {
          transform: translateX(18px);
          background: var(--accent);
        }
      `}</style>
    </div>
  );
}

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "6px 0",
    }}>
      <span style={{ fontSize: 11, opacity: 0.5 }}>{label}</span>
      <div style={{ width: "55%" }}>{children}</div>
    </div>
  );
}

function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} className="setting-select">
      {MODEL_OPTIONS.map(m => (
        <option key={m} value={m}>{m}</option>
      ))}
    </select>
  );
}
