"use client";

import { useEffect, useState } from "react";
import { useSession, signIn } from "next-auth/react";

type Run = {
  thread_id: string;
  task_state: string | null;
  invoice_id: string | null;
  extraction: { vendor?: string; total?: number; date?: string } | null;
  risk?: { risk_level?: string; risk_score?: number; reasons?: string[] };
  next: string[];
};

const APPROVER_ROLES = ["controller", "cfo-approver"];

export default function ApprovalsPage() {
  const { data: session, status } = useSession();
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const res = await fetch("/api/runs");
    const data = await res.json();
    setRuns((data.runs ?? []).filter((r: Run) => r.next.includes("human_review")));
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const canApprove = session?.roles?.some((r) => APPROVER_ROLES.includes(r));

  async function act(threadId: string, decision: "approve" | "reject") {
    setBusy(threadId);
    setMessage(null);
    const res = await fetch(`/api/runs/${threadId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    const data = await res.json();
    if (!res.ok) setMessage(`Failed: ${data.error}`);
    else setMessage(`${threadId}: ${decision}d`);
    setBusy(null);
    load();
  }

  if (status === "loading") return <p className="text-neutral-400">Loading session...</p>;

  if (status !== "authenticated") {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Approval queue</h1>
        <p className="text-neutral-400">Sign in with a controller or cfo-approver account to review escalated payments.</p>
        <button onClick={() => signIn("keycloak")} className="w-fit rounded bg-white px-4 py-2 text-sm font-medium text-black">
          Sign in with Keycloak
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Approval queue</h1>
      {!canApprove && (
        <p className="rounded bg-amber-950 px-3 py-2 text-sm text-amber-300">
          Signed in as {session.user?.name}, but your role ({session.roles?.join(", ") || "none"}) has no approval
          authority - actions below will be rejected server-side.
        </p>
      )}
      {message && <p className="text-sm text-neutral-300">{message}</p>}
      {runs.length === 0 ? (
        <p className="text-neutral-400">Nothing waiting on human review.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {runs.map((r) => (
            <div key={r.thread_id} className="rounded border border-neutral-800 p-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm">{r.invoice_id}</span>
                <span className="text-xs text-neutral-500">{r.task_state}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="text-neutral-500">Vendor</div>
                  <div>{r.extraction?.vendor ?? "-"}</div>
                </div>
                <div>
                  <div className="text-neutral-500">Amount</div>
                  <div>{r.extraction?.total != null ? `$${r.extraction.total.toFixed(2)}` : "-"}</div>
                </div>
                <div>
                  <div className="text-neutral-500">Risk level</div>
                  <div>{r.risk?.risk_level ?? "-"} ({r.risk?.risk_score ?? "-"})</div>
                </div>
                <div>
                  <div className="text-neutral-500">Reasons</div>
                  <div className="text-xs text-neutral-400">{r.risk?.reasons?.join("; ") ?? "-"}</div>
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  disabled={busy === r.thread_id}
                  onClick={() => act(r.thread_id, "approve")}
                  className="rounded bg-emerald-700 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  disabled={busy === r.thread_id}
                  onClick={() => act(r.thread_id, "reject")}
                  className="rounded bg-red-800 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
