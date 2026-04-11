/**
 * GET /api/radio — Proxy radio state from ReAct server
 * POST /api/radio — Play/stop radio via ReAct server
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const REACT_URL = process.env.REACT_URL || "http://localhost:7900";

export async function GET() {
  try {
    const res = await fetch(`${REACT_URL}/api/radio`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) throw new Error(`ReAct ${res.status}`);
    const data = await res.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ playing: false, stations: {} });
  }
}
