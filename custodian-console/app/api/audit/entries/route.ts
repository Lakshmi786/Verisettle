import { NextResponse } from "next/server";
import { AUDIT_LOG_URL } from "@/lib/config";

export async function GET() {
  const res = await fetch(`${AUDIT_LOG_URL}/entries?limit=50`, { cache: "no-store" });
  if (!res.ok) return NextResponse.json({ error: await res.text() }, { status: res.status });
  return NextResponse.json(await res.json());
}
