import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/app/api/auth/[...nextauth]/route";
import { BACKEND_URL } from "@/lib/config";

const APPROVER_ROLES = ["controller", "cfo-approver"];

export async function POST(req: Request, ctx: RouteContext<"/api/runs/[threadId]/resume">) {
  const session = await getServerSession(authOptions);
  if (!session) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  if (!session.roles?.some((r) => APPROVER_ROLES.includes(r))) {
    return NextResponse.json(
      { error: "your role does not have payment-approval authority" },
      { status: 403 },
    );
  }

  const { threadId } = await ctx.params;
  const body = await req.json();
  const res = await fetch(`${BACKEND_URL}/runs/${threadId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: body.decision, approver: session.user?.email ?? session.user?.name }),
  });
  if (!res.ok) {
    return NextResponse.json({ error: await res.text() }, { status: res.status });
  }
  return NextResponse.json(await res.json());
}
