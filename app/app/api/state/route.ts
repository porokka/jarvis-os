/**
 * GET  /api/state — Get current Jarvis status
 * POST /api/state — Set state/emotion manually
 */

import { NextRequest, NextResponse } from "next/server";
import { bridge } from "@/lib/bridge";

export async function GET() {
  return NextResponse.json(bridge.getStatus());
}

export async function POST(req: NextRequest) {
  const body = await req.json();

  if (body.emotion) {
    bridge.setEmotion(body.emotion);
  }

  if (body.finishSpeaking) {
    bridge.finishSpeaking();
  }

  return NextResponse.json(bridge.getStatus());
}
