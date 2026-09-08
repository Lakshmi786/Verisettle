import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/config";

// Proxies a multipart image upload straight through to custodian-backend's
// /runs/from-image - no auth gate here, same as the read-only /api/runs
// list and the plain `POST /runs` backend route it's testing (submitting a
// test invoice isn't a financial control action; only /resume, which
// actually approves a payment, requires a signed-in approver role).
export async function POST(req: Request) {
  const incoming = await req.formData();

  const outgoing = new FormData();
  const file = incoming.get("file");
  if (!file) {
    return NextResponse.json({ error: "no file provided" }, { status: 400 });
  }
  outgoing.set("file", file);
  outgoing.set("invoice_id", String(incoming.get("invoice_id") ?? ""));

  const res = await fetch(`${BACKEND_URL}/runs/from-image`, {
    method: "POST",
    body: outgoing,
  });
  if (!res.ok) {
    return NextResponse.json({ error: await res.text() }, { status: res.status });
  }
  return NextResponse.json(await res.json());
}
