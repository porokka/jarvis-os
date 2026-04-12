/**
 * POST /api/generate-image — Generate image via FLUX skill (no ComfyUI)
 * Body: { prompt: string }
 * Returns: { status, image_path, message }
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const REACT_URL = process.env.REACT_URL || "http://localhost:7900";

export async function POST(request: Request) {
  try {
    const { prompt, width = 1024, height = 1024 } = await request.json();
    if (!prompt) {
      return NextResponse.json({ error: "No prompt provided" }, { status: 400 });
    }

    // Call ReAct server which runs the flux skill
    const res = await fetch(`${REACT_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "qwen3:30b-a3b",
        messages: [
          { role: "user", content: `generate a ${width}x${height} image of: ${prompt}` },
        ],
      }),
      signal: AbortSignal.timeout(300000), // 5 min timeout
    });

    const data = await res.json();
    const message = data?.message?.content || "Generation complete";

    return NextResponse.json({ status: "ok", message });
  } catch (e) {
    return NextResponse.json(
      { error: String(e) },
      { status: 500 },
    );
  }
}
