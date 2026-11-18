import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000/api/v1";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${BACKEND_URL}/${path}${search}`;

  try {
    const res = await fetch(targetUrl, {
      headers: {
        Accept: "application/json",
      },
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, {
      status: res.status,
    });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : "Failed to proxy request to backend";
    return NextResponse.json({ detail: errorMsg }, { status: 502 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${BACKEND_URL}/${path}${search}`;

  try {
    const body = await request.text();
    const res = await fetch(targetUrl, {
      method: "POST",
      headers: {
        "Content-Type": request.headers.get("Content-Type") || "application/json",
      },
      body: body || undefined,
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, {
      status: res.status,
    });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : "Failed to proxy request to backend";
    return NextResponse.json({ detail: errorMsg }, { status: 502 });
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${BACKEND_URL}/${path}${search}`;

  try {
    const body = await request.text();
    const res = await fetch(targetUrl, {
      method: "PUT",
      headers: {
        "Content-Type": request.headers.get("Content-Type") || "application/json",
      },
      body: body || undefined,
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : "Failed to proxy request to backend";
    return NextResponse.json({ detail: errorMsg }, { status: 502 });
  }
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${BACKEND_URL}/${path}${search}`;

  try {
    const body = await request.text();
    const res = await fetch(targetUrl, {
      method: "PATCH",
      headers: {
        "Content-Type": request.headers.get("Content-Type") || "application/json",
      },
      body: body || undefined,
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : "Failed to proxy request to backend";
    return NextResponse.json({ detail: errorMsg }, { status: 502 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const search = request.nextUrl.search;
  const targetUrl = `${BACKEND_URL}/${path}${search}`;

  try {
    const res = await fetch(targetUrl, {
      method: "DELETE",
      cache: "no-store",
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const errorMsg = err instanceof Error ? err.message : "Failed to proxy request to backend";
    return NextResponse.json({ detail: errorMsg }, { status: 502 });
  }
}
