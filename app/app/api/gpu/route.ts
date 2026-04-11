/**
 * GET /api/gpu — Proxy GPU stats from bridge server
 */
import { NextResponse } from "next/server";

const BRIDGE = process.env.BRIDGE_URL || "http://localhost:4000";

export async function GET() {
  try {
    const res = await fetch(`${BRIDGE}/api/gpu`, { cache: "no-store" });
    if (!res.ok) throw new Error(`Bridge ${res.status}`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ gpus: [] });
  }
}
