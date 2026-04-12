/**
 * GET /api/flux-status — Proxy FLUX generation status from bridge
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BRIDGE_URL = process.env.BRIDGE_URL || "http://localhost:4000";

export async function GET() {
  try {
    const res = await fetch(`${BRIDGE_URL}/api/flux/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ status: "idle" });
  }
}
