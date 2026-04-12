/**
 * GET /api/file?path=... — Proxy file from bridge server (images etc)
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BRIDGE_URL = process.env.BRIDGE_URL || "http://localhost:4000";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const filePath = searchParams.get("path");

  if (!filePath) {
    return NextResponse.json({ error: "No path" }, { status: 400 });
  }

  try {
    const res = await fetch(
      `${BRIDGE_URL}/api/file?path=${encodeURIComponent(filePath)}`,
      { signal: AbortSignal.timeout(10000) },
    );

    if (!res.ok) {
      return NextResponse.json({ error: `Bridge ${res.status}` }, { status: res.status });
    }

    const contentType = res.headers.get("Content-Type") || "application/octet-stream";
    const data = await res.arrayBuffer();

    return new NextResponse(data, {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch {
    return NextResponse.json({ error: "Failed to fetch file" }, { status: 500 });
  }
}
