const JARVIS_URL = process.env.JARVIS_URL || "https://localhost:3100";

// SSE proxy: browser → Next.js → Jarvis MCP server
export async function GET() {
  try {
    const upstream = await fetch(`${JARVIS_URL}/approvals/stream`, {
      headers: authHeaders(),
      // @ts-expect-error - Node fetch supports this
      agent: new (await import("node:https")).Agent({ rejectUnauthorized: false }),
    });

    if (!upstream.body) {
      return new Response("data: []\n\n", {
        headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
      });
    }

    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  } catch {
    return new Response("data: []\n\n", {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
    });
  }
}

function authHeaders(): Record<string, string> {
  const token = process.env.JARVIS_TOKEN;
  if (token) return { Authorization: `Bearer ${token}` };
  return {};
}
