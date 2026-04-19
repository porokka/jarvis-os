import { NextResponse } from "next/server";
import { readdirSync, readFileSync, existsSync } from "fs";
import { join } from "path";

const BRIDGE_DIR =
  process.platform === "win32" ? "D:/Jarvis_vault" : "/mnt/d/Jarvis_vault";

const PROFILES_DIR = join(BRIDGE_DIR, "profiles");

type ProfileSummary = {
  id: string;
  label: string;
  description?: string;
  voicePreferred?: string;
};

export async function GET() {
  try {
    if (!existsSync(PROFILES_DIR)) {
      return NextResponse.json([], { status: 200 });
    }

    const files = readdirSync(PROFILES_DIR)
      .filter(name => name.toLowerCase().endsWith(".json"))
      .sort((a, b) => a.localeCompare(b));

    const profiles: ProfileSummary[] = [];

    for (const file of files) {
      try {
        const fullPath = join(PROFILES_DIR, file);
        const raw = readFileSync(fullPath, "utf8");
        const json = JSON.parse(raw);

        if (!json?.id || !json?.label) continue;

        profiles.push({
          id: String(json.id),
          label: String(json.label),
          description: typeof json.description === "string" ? json.description : undefined,
          voicePreferred: typeof json?.voice?.preferred === "string"
            ? json.voice.preferred
            : undefined,
        });
      } catch {
        // skip bad profile files instead of breaking the whole menu
      }
    }

    return NextResponse.json(profiles);
  } catch (e) {
    return NextResponse.json(
      { status: "error", message: String(e) },
      { status: 500 }
    );
  }
}