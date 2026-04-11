/**
 * POST /api/transcribe — Proxy audio to bridge server Whisper
 * Accepts raw WAV audio body, forwards to localhost:4000/api/transcribe
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BRIDGE_URL = process.env.BRIDGE_URL || "http://localhost:4000";

export async function POST(request: Request) {
  try {
    const audioBuffer = await request.arrayBuffer();

    const res = await fetch(`${BRIDGE_URL}/api/transcribe`, {
      method: "POST",
      body: audioBuffer,
      headers: { "Content-Type": "audio/wav" },
      signal: AbortSignal.timeout(30000),
    });

    if (!res.ok) throw new Error(`Bridge ${res.status}`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: String(e), text: "" },
      { status: 500 }
    );
  }
}
