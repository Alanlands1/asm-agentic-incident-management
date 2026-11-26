import { NextRequest, NextResponse } from "next/server";

// Server side only: the admin key is added here and never reaches the browser. The caller's session cookie goes
// along, and the backend lets only a signed-in admin through.
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000/api/v1";

type Ctx = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, { params }: Ctx) {
  const key = process.env.ADMIN_API_KEY;
  if (!key) {
    return NextResponse.json({ detail: "Admin API is switched off: set ADMIN_API_KEY in frontend/.env.local" }, { status: 503 });
  }
  const { path } = await params;
  const target = `${BACKEND_URL}/admin/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers: Record<string, string> = { Accept: "application/json", "X-Admin-Key": key };
  const by = request.headers.get("x-admin-user");
  if (by) headers["X-Admin-User"] = by;
  const cookie = request.headers.get("cookie");
  if (cookie) headers["Cookie"] = cookie;
  const hasBody = request.method === "PUT" || request.method === "POST";
  if (hasBody) headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
    });
    const text = await res.text();
    return new NextResponse(text, { status: res.status, headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" } });
  } catch {
    return NextResponse.json({ detail: "Couldn't reach the backend" }, { status: 502 });
  }
}

export const GET = forward;
export const PUT = forward;
export const DELETE = forward;
