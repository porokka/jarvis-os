/**
 * POST /api/generate-image — Generate image via bridge server
 * Calls FLUX skill directly through a dedicated endpoint.
 * Body: { prompt: string, width?: number, height?: number }
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BRIDGE_URL = process.env.BRIDGE_URL || "http://localhost:4000";

export async function POST(request: Request) {
  try {
    const { prompt, width = 1024, height = 1024 } = await request.json();
    if (!prompt) {
      return NextResponse.json({ error: "No prompt provided" }, { status: 400 });
    }

    const res = await fetch(`${BRIDGE_URL}/api/flux`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, width, height }),
      signal: AbortSignal.timeout(300000),
    });

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
