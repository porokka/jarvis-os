/**
 * POST /api/tts — Direct TTS synthesis endpoint
 *
 * Body: { text, emotion?, voice? }
 * Returns: WAV audio binary
 */

import { NextRequest, NextResponse } from "next/server";
import * as tts from "@/lib/tts";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const text = body.text?.trim();

  if (!text) {
    return NextResponse.json({ error: "No text provided" }, { status: 400 });
  }

  const available = await tts.isAvailable();
  if (!available) {
    return NextResponse.json(
      { error: "TTS server not running. Start: python tts/server.py" },
      { status: 503 }
    );
  }

  const wavBuffer = await tts.synthesize(
    text,
    body.emotion || "neutral",
    body.voice || "tara"
  );

  if (!wavBuffer) {
    return NextResponse.json({ error: "TTS synthesis failed" }, { status: 500 });
  }

  return new NextResponse(new Uint8Array(wavBuffer), {
    headers: {
      "Content-Type": "audio/wav",
      "Content-Length": String(wavBuffer.length),
    },
  });
}

export async function GET() {
  const available = await tts.isAvailable();
  const voices = available ? await tts.getVoices() : null;

  return NextResponse.json({
    available,
    voices: voices?.voices || [],
    emotions: voices?.emotions || [],
  });
}
