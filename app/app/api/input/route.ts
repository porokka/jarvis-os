/**
 * POST /api/input — Send text to Jarvis
 *
 * Body: { text: string }
 * Returns: { response, emotion, state }
 */

import { NextRequest, NextResponse } from "next/server";
import { bridge } from "@/lib/bridge";
import * as tts from "@/lib/tts";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const text = body.text?.trim();

  if (!text) {
    return NextResponse.json({ error: "No text provided" }, { status: 400 });
  }

  // Process through Claude
  const response = await bridge.processInput(text);
  const status = bridge.getStatus();

  // Generate TTS audio if available
  let audioBase64: string | null = null;
  const ttsAvailable = await tts.isAvailable();

  if (ttsAvailable) {
    const wavBuffer = await tts.synthesize(response, status.emotion);
    if (wavBuffer) {
      audioBase64 = wavBuffer.toString("base64");
    }
  }

  // Mark speaking done after response is ready
  // (actual speaking duration handled client-side)
  setTimeout(() => bridge.finishSpeaking(), 2000);

  return NextResponse.json({
    response,
    emotion: status.emotion,
    state: status.state,
    audio: audioBase64, // base64 WAV or null
    ttsAvailable,
  });
}
