import { NextRequest, NextResponse } from "next/server";

const JARVIS_URL = process.env.JARVIS_URL || "https://localhost:3100";

// GET /api/approvals — list pending approvals
export async function GET() {
  try {
    const res = await fetch(`${JARVIS_URL}/approvals`, {
      headers: authHeaders(),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json([], { status: 502 });
  }
}

// POST /api/approvals — resolve an approval { id, approved }
export async function POST(req: NextRequest) {
  const { id, approved } = await req.json();

  if (!id || typeof approved !== "boolean") {
    return NextResponse.json({ error: "Missing id or approved" }, { status: 400 });
  }

  try {
    const res = await fetch(`${JARVIS_URL}/approvals/${id}`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Failed to reach Jarvis server" }, { status: 502 });
  }
}

function authHeaders(): Record<string, string> {
  const token = process.env.JARVIS_TOKEN;
  if (token) return { Authorization: `Bearer ${token}` };
  return {};
}
