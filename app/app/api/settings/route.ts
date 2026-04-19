/**
 * POST /api/settings — Save settings to bridge
 */
import { NextRequest, NextResponse } from "next/server";
import {
  writeFileSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  existsSync,
} from "fs";
import { join } from "path";

const BRIDGE_DIR =
  process.platform === "win32" ? "D:/Jarvis_vault" : "/mnt/d/Jarvis_vault";

const PROFILES_DIR = join(BRIDGE_DIR, "profiles");
const CONFIG_DIR = join(BRIDGE_DIR, ".jarvis");

type Settings = {
  personality: string;
  voice: string;
  ttsEngine: string;
  audioOutput: string;
  wakeWord: boolean;
};

const DEFAULT_SETTINGS: Settings = {
  personality: "jarvis",
  voice: "tara",
  ttsEngine: "system",
  audioOutput: "default",
  wakeWord: true,
};

function getAvailableProfileIds(): string[] {
  if (!existsSync(PROFILES_DIR)) return [];

  return readdirSync(PROFILES_DIR)
    .filter((name) => name.toLowerCase().endsWith(".json"))
    .map((name) => name.replace(/\.json$/i, "").trim().toLowerCase())
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
}

function normalizeSettings(input: any): Settings {
  const availableProfiles = getAvailableProfileIds();
  const fallbackProfile =
    availableProfiles.includes(DEFAULT_SETTINGS.personality)
      ? DEFAULT_SETTINGS.personality
      : (availableProfiles[0] ?? DEFAULT_SETTINGS.personality);

  const personalityRaw =
    typeof input?.personality === "string"
      ? input.personality.trim().toLowerCase()
      : "";

  return {
    personality: availableProfiles.includes(personalityRaw)
      ? personalityRaw
      : fallbackProfile,
    voice:
      typeof input?.voice === "string" && input.voice.trim()
        ? input.voice.trim().toLowerCase()
        : DEFAULT_SETTINGS.voice,
    ttsEngine:
      typeof input?.ttsEngine === "string" && input.ttsEngine.trim()
        ? input.ttsEngine.trim().toLowerCase()
        : DEFAULT_SETTINGS.ttsEngine,
    audioOutput:
      typeof input?.audioOutput === "string" && input.audioOutput.trim()
        ? input.audioOutput.trim()
        : DEFAULT_SETTINGS.audioOutput,
    wakeWord:
      typeof input?.wakeWord === "boolean"
        ? input.wakeWord
        : DEFAULT_SETTINGS.wakeWord,
  };
}

function loadProfile(profileId: string) {
  const profilePath = join(PROFILES_DIR, `${profileId}.json`);
  if (!existsSync(profilePath)) return null;

  try {
    return JSON.parse(readFileSync(profilePath, "utf8"));
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  try {
    const incoming = await req.json();
    const settings = normalizeSettings(incoming);

    mkdirSync(CONFIG_DIR, { recursive: true });

    // Write watcher-friendly files
    writeFileSync(
      join(BRIDGE_DIR, "settings_voice.txt"),
      settings.voice,
      "utf8"
    );
    writeFileSync(
      join(BRIDGE_DIR, "settings_personality.txt"),
      settings.personality,
      "utf8"
    );

    // Save full normalized settings
    writeFileSync(
      join(CONFIG_DIR, "settings.json"),
      JSON.stringify(settings, null, 2),
      "utf8"
    );

    // Optional but strongly recommended:
    // Write resolved active profile for the bridge/runtime
    const activeProfile = loadProfile(settings.personality);
    if (activeProfile) {
      writeFileSync(
        join(CONFIG_DIR, "active_profile.json"),
        JSON.stringify(activeProfile, null, 2),
        "utf8"
      );
    }

    return NextResponse.json(
      {
        status: "ok",
        settings,
        profileLoaded: activeProfile?.id ?? null,
      },
      {
        status: 200,
        headers: { "Cache-Control": "no-store" },
      }
    );
  } catch (e) {
    return NextResponse.json(
      { status: "error", message: String(e) },
      {
        status: 500,
        headers: { "Cache-Control": "no-store" },
      }
    );
  }
}