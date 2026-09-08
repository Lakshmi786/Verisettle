import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/config";

export async function GET() {
  const res = await fetch(`${BACKEND_URL}/runs?limit=50`, { cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: await res.text() }, { status: res.status });
  }
  return NextResponse.json(await res.json());
}
