/**
 * TTS Client — Calls the local Orpheus TTS Python server
 *
 * The Python server (tts/server.py) runs separately on :5100
 * and handles the heavy GPU inference. This module is just the HTTP client.
 */

const TTS_URL = process.env.TTS_URL || "http://localhost:5100";

// Orpheus emotion tag mapping
const EMOTION_TAGS: Record<string, string> = {
  happy: "<chuckle>",
  serious: "",
  thinking: "<sigh>",
  confused: "",
  neutral: "",
  laughing: "<laugh>",
  surprised: "<gasp>",
  tired: "<yawn>",
  annoyed: "<groan>",
};

export async function isAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${TTS_URL}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Generate speech audio from text.
 * Injects Orpheus emotion tags based on the detected emotion.
 * Returns WAV bytes or null if TTS is unavailable.
 */
export async function synthesize(
  text: string,
  emotion: string = "neutral",
  voice: string = "tara"
): Promise<Buffer | null> {
  // Inject emotion tag
  const tag = EMOTION_TAGS[emotion] || "";
  const ttsText = tag ? `${tag} ${text}` : text;

  try {
    const res = await fetch(`${TTS_URL}/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: ttsText, voice }),
      signal: AbortSignal.timeout(30000),
    });

    if (!res.ok) return null;

    const arrayBuf = await res.arrayBuffer();
    return Buffer.from(arrayBuf);
  } catch (err) {
    console.error("[TTS] Synthesis failed:", err);
    return null;
  }
}

export async function getVoices(): Promise<{ voices: string[]; emotions: string[] } | null> {
  try {
    const res = await fetch(`${TTS_URL}/voices`, { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
