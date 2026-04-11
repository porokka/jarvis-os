/**
 * GET /api/logs — Read log file directly
 */
import { NextResponse } from "next/server";
import { readFileSync, existsSync } from "fs";

const LOG_PATH = process.platform === "win32"
  ? "D:/Jarvis_vault/jarvis.log"
  : "/mnt/d/Jarvis_vault/jarvis.log";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    if (!existsSync(LOG_PATH)) {
      return NextResponse.json({ lines: [] });
    }
    const content = readFileSync(LOG_PATH, "utf-8");
    const lines = content.trim().split("\n").slice(-50);
    return NextResponse.json({ lines }, {
      headers: { "Cache-Control": "no-store, no-cache, must-revalidate" },
    });
  } catch {
    return NextResponse.json({ lines: [] });
  }
}
