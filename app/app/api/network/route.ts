/**
 * GET /api/network — Proxy network topology from ReAct server
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const REACT_URL = process.env.REACT_URL || "http://localhost:7900";

export async function GET() {
  try {
    const res = await fetch(`${REACT_URL}/api/network`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) throw new Error(`ReAct ${res.status}`);
    const data = await res.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ devices: [], gateway: "192.168.0.1" });
  }
}
