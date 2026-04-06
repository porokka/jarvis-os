/**
 * POST /api/speak — Make Jarvis say something directly (bypass Claude)
 *
 * Body: { message, emotion? }
 * Useful for MCP integration and scripted responses.
 */

import { NextRequest, NextResponse } from "next/server";
import { bridge, JarvisEmotion } from "@/lib/bridge";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const message = body.message?.trim();
  const emotion: JarvisEmotion = body.emotion || "neutral";

  if (!message) {
    return NextResponse.json({ error: "No message" }, { status: 400 });
  }

  bridge.setEmotion(emotion);

  return NextResponse.json({
    message,
    emotion,
    state: bridge.getStatus().state,
  });
}
