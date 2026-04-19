"use client";

import { useEffect, useMemo, useState } from "react";

interface Settings {
  personality: string;
  voice: string;
  ttsEngine: string;
  audioOutput: string;
  wakeWord: boolean;
}

interface ProfileOption {
  id: string;
  label: string;
  description?: string;
  voicePreferred?: string;
}

const DEFAULT_SETTINGS: Settings = {
  personality: "jarvis",
  voice: "tara",
  ttsEngine: "system",
  audioOutput: "default",
  wakeWord: true,
};

const VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"];

const TTS_ENGINES = [
  { id: "orpheus", label: "Orpheus (Local GPU)" },
  { id: "system", label: "System (PowerShell/espeak)" },
  { id: "browser", label: "Browser Speech Synthesis" },
];

export function SettingsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const [profiles, setProfiles] = useState<ProfileOption[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("jarvis-settings");
      if (raw) {
        const parsed = JSON.parse(raw);
        setSettings({
          personality:
            typeof parsed?.personality === "string"
              ? parsed.personality
              : DEFAULT_SETTINGS.personality,
          voice:
            typeof parsed?.voice === "string"
              ? parsed.voice
              : DEFAULT_SETTINGS.voice,
          ttsEngine:
            typeof parsed?.ttsEngine === "string"
              ? parsed.ttsEngine
              : DEFAULT_SETTINGS.ttsEngine,
          audioOutput:
            typeof parsed?.audioOutput === "string"
              ? parsed.audioOutput
              : DEFAULT_SETTINGS.audioOutput,
          wakeWord:
            typeof parsed?.wakeWord === "boolean"
              ? parsed.wakeWord
              : DEFAULT_SETTINGS.wakeWord,
        });
      }
    } catch {
      // ignore bad localStorage
    }

    navigator.mediaDevices
      ?.enumerateDevices()
      .then((devices) => {
        setAudioDevices(devices.filter((d) => d.kind === "audiooutput"));
      })
      .catch(() => {});

    fetch("/api/profiles")
      .then(async (res) => {
        if (!res.ok) throw new Error(`Failed to load profiles: ${res.status}`);
        return res.json();
      })
      .then((data: unknown) => {
        if (!Array.isArray(data)) {
          setProfiles([]);
          return;
        }

        const normalized: ProfileOption[] = data
          .map((item: any) => ({
            id: typeof item?.id === "string" ? item.id : "",
            label: typeof item?.label === "string" ? item.label : "",
            description:
              typeof item?.description === "string" ? item.description : undefined,
            voicePreferred:
              typeof item?.voicePreferred === "string"
                ? item.voicePreferred
                : undefined,
          }))
          .filter((p) => p.id && p.label);

        setProfiles(normalized);
      })
      .catch(() => {
        setProfiles([]);
      })
      .finally(() => {
        setProfilesLoading(false);
      });
  }, []);

  useEffect(() => {
    if (profiles.length === 0) return;

    const exists = profiles.some((p) => p.id === settings.personality);
    if (!exists) {
      setSettings((prev) => ({
        ...prev,
        personality: profiles[0].id,
      }));
    }
  }, [profiles, settings.personality]);

  function save() {
    localStorage.setItem("jarvis-settings", JSON.stringify(settings));

    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).catch(() => {});

    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }

  function updatePersonality(personality: string) {
    const selected = profiles.find((p) => p.id === personality);

    setSettings((prev) => ({
      ...prev,
      personality,
      voice: selected?.voicePreferred ?? prev.voice,
    }));
  }

  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === settings.personality),
    [profiles, settings.personality]
  );

  if (!open) return null;

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <span>SYSTEM CONFIGURATION</span>
          <button className="settings-close" onClick={onClose}>
            ESC
          </button>
        </div>

        <div className="settings-body">
          <div className="settings-section">
            <div className="section-title">PROFILE</div>
            <SettingRow label="Character">
              <div>
                <select
                  value={settings.personality}
                  onChange={(e) => updatePersonality(e.target.value)}
                  className="setting-select"
                  disabled={profilesLoading || profiles.length === 0}
                >
                  {profilesLoading ? (
                    <option value={settings.personality}>Loading profiles...</option>
                  ) : profiles.length === 0 ? (
                    <option value={settings.personality}>No profiles found</option>
                  ) : (
                    profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))
                  )}
                </select>

                {selectedProfile?.description && (
                  <div
                    style={{
                      fontSize: 10,
                      opacity: 0.55,
                      marginTop: 6,
                      lineHeight: 1.35,
                    }}
                  >
                    {selectedProfile.description}
                  </div>
                )}
              </div>
            </SettingRow>
          </div>

          <div className="settings-section">
            <div className="section-title">VOICE OUTPUT</div>

            <SettingRow label="TTS Engine">
              <select
                value={settings.ttsEngine}
                onChange={(e) => update("ttsEngine", e.target.value)}
                className="setting-select"
              >
                {TTS_ENGINES.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </SettingRow>

            <SettingRow label="Voice">
              <select
                value={settings.voice}
                onChange={(e) => update("voice", e.target.value)}
                className="setting-select"
              >
                {VOICES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </SettingRow>

            <SettingRow label="Audio Output">
              <select
                value={settings.audioOutput}
                onChange={(e) => update("audioOutput", e.target.value)}
                className="setting-select"
              >
                <option value="default">System Default</option>
                {audioDevices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>
                    {d.label || `Device ${d.deviceId.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </SettingRow>
          </div>

          <div className="settings-section">
            <div className="section-title">VOICE INPUT</div>
            <SettingRow label="Wake Word Mode">
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={settings.wakeWord}
                  onChange={(e) => update("wakeWord", e.target.checked)}
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
        .settings-close:hover {
          color: rgba(255, 255, 255, 0.7);
        }
        .settings-body {
          flex: 1;
          overflow-y: auto;
          padding: 12px 18px;
        }
        .settings-body::-webkit-scrollbar {
          width: 2px;
        }
        .settings-body::-webkit-scrollbar-thumb {
          background: rgba(64, 160, 240, 0.2);
        }
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
        .setting-select:focus {
          border-color: rgba(64, 160, 240, 0.3);
        }
        .setting-select:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .setting-select option {
          background: #0a0a14;
        }
        .toggle {
          position: relative;
          display: inline-block;
          width: 36px;
          height: 18px;
        }
        .toggle input {
          display: none;
        }
        .toggle-slider {
          position: absolute;
          inset: 0;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 9px;
          cursor: pointer;
          transition: 0.2s;
        }
        .toggle-slider::before {
          content: "";
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

function SettingRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        padding: "6px 0",
        gap: 12,
      }}
    >
      <span style={{ fontSize: 11, opacity: 0.5, paddingTop: 6 }}>{label}</span>
      <div style={{ width: "55%" }}>{children}</div>
    </div>
  );
}