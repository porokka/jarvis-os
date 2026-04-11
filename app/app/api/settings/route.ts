/**
 * POST /api/settings — Save settings to bridge
 */
import { NextRequest, NextResponse } from "next/server";
import { writeFileSync, mkdirSync } from "fs";
import { join } from "path";

const BRIDGE_DIR = process.platform === "win32" ? "D:/Jarvis_vault" : "/mnt/d/Jarvis_vault";

export async function POST(req: NextRequest) {
  try {
    const settings = await req.json();

    // Write settings to vault for watcher to pick up
    if (settings.voice) {
      writeFileSync(join(BRIDGE_DIR, "settings_voice.txt"), settings.voice);
    }
    if (settings.personality) {
      writeFileSync(join(BRIDGE_DIR, "settings_personality.txt"), settings.personality);
    }

    // Save full config
    const configDir = join(BRIDGE_DIR, ".jarvis");
    try { mkdirSync(configDir, { recursive: true }); } catch {}
    writeFileSync(join(configDir, "settings.json"), JSON.stringify(settings, null, 2));

    return NextResponse.json({ status: "ok" });
  } catch (e) {
    return NextResponse.json({ status: "error", message: String(e) }, { status: 500 });
  }
}
