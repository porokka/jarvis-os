/**
 * POST /api/input — Send text to Jarvis
 *
 * Body: { text: string }
 * Returns: { response, emotion, state }
 */

import { NextRequest, NextResponse } from "next/server";
import { bridge } from "@/lib/bridge";
import * as tts from "@/lib/tts";
import { appendFileSync, writeFileSync } from "fs";

const LOG_PATH = process.platform === "win32"
  ? "D:/Jarvis_vault/jarvis.log"
  : "/mnt/d/Jarvis_vault/jarvis.log";

function log(msg: string) {
  const ts = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  try { appendFileSync(LOG_PATH, `[${ts}] ${msg}\n`); } catch {}
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const text = body.text?.trim();

  if (!text) {
    return NextResponse.json({ error: "No text provided" }, { status: 400 });
  }

  log(`HEARD: ${text}`);
  log(`Router → ${bridge.getStatus().brain || "bridge"}`);

  // Process through Claude
  const response = await bridge.processInput(text);
  const status = bridge.getStatus();

  log(`SAID: ${response}`);

  // Generate TTS audio if available
  let audioBase64: string | null = null;
  const ttsAvailable = await tts.isAvailable();

  if (ttsAvailable) {
    const wavBuffer = await tts.synthesize(response, status.emotion);
    if (wavBuffer) {
      audioBase64 = wavBuffer.toString("base64");
    }
  }

  // Determine next state — question = listening, else standby
  const isQuestion = response.trim().endsWith("?");
  const nextState = isQuestion ? "listening" : "standby";

  // Write state to bridge files so watcher + React poll stay in sync
  const BRIDGE = process.platform === "win32" ? "C:/tmp/jarvis" : "/tmp/jarvis";
  try {
    writeFileSync(`${BRIDGE}/state.txt`, "speaking");
    writeFileSync(`${BRIDGE}/output.txt`, response);
    writeFileSync(`${BRIDGE}/brain.txt`, status.brain || "bridge");
    // After TTS finishes (estimated), set next state
    setTimeout(() => {
      try { writeFileSync(`${BRIDGE}/state.txt`, nextState); } catch {}
      if (!isQuestion) bridge.finishSpeaking();
    }, isQuestion ? 5000 : 2000);
  } catch {}

  if (isQuestion) {
    log("Response is a question — mic stays open");
  }

  return NextResponse.json({
    response,
    emotion: status.emotion,
    state: "speaking",
    nextState,
    audio: audioBase64,
    ttsAvailable,
  });
}
