import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/app/api/auth/[...nextauth]/route";
import { CONTROL_PLANE_URL } from "@/lib/config";

export async function GET() {
  const res = await fetch(`${CONTROL_PLANE_URL}/status`, { cache: "no-store" });
  if (!res.ok) return NextResponse.json({ error: await res.text() }, { status: res.status });
  return NextResponse.json(await res.json());
}

export async function POST(req: Request) {
  const session = await getServerSession(authOptions);
  if (!session) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }

  const body = await req.json();
  const path = body.action === "reset" ? "/kill-switch/reset" : "/kill-switch/trip";
  const payload =
    body.action === "reset"
      ? { scope: body.scope, target: body.target, reset_by: session.user?.email ?? session.user?.name }
      : {
          scope: body.scope,
          target: body.target,
          reason: body.reason ?? "tripped from verisettle-console",
          triggered_by: session.user?.email ?? session.user?.name,
        };

  const res = await fetch(`${CONTROL_PLANE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return NextResponse.json({ error: await res.text() }, { status: res.status });
  return NextResponse.json(await res.json());
}
