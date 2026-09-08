"use client";

import { useEffect, useState } from "react";
import { useSession, signIn } from "next-auth/react";

type Status = {
  global_stop: boolean;
  paused_agents: string[];
  halted_sessions: string[];
  frozen_tools: string[];
};

export default function KillSwitchPage() {
  const { data: session, status: authStatus } = useSession();
  const [status, setStatus] = useState<Status | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const res = await fetch("/api/kill-switch");
    setStatus(await res.json());
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  async function trip() {
    setBusy(true);
    await fetch("/api/kill-switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "trip", scope: "global", target: "*", reason: reason || "manual console trip" }),
    });
    setBusy(false);
    load();
  }

  async function reset() {
    setBusy(true);
    await fetch("/api/kill-switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "reset", scope: "global", target: "*" }),
    });
    setBusy(false);
    load();
  }

  if (authStatus !== "authenticated") {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Kill switch</h1>
        <p className="text-neutral-400">Sign in to trip or reset the fleet-wide kill switch.</p>
        <button onClick={() => signIn("keycloak")} className="w-fit rounded bg-white px-4 py-2 text-sm font-medium text-black">
          Sign in with Keycloak
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Kill switch</h1>

      <div
        className={`rounded border p-4 ${
          status?.global_stop ? "border-red-700 bg-red-950" : "border-neutral-800"
        }`}
      >
        <div className="text-sm text-neutral-400">Global stop</div>
        <div className="text-2xl font-semibold">{status?.global_stop ? "TRIPPED" : "Normal"}</div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <div className="text-neutral-500">Paused agents</div>
          <div>{status?.paused_agents.join(", ") || "none"}</div>
        </div>
        <div>
          <div className="text-neutral-500">Halted sessions</div>
          <div>{status?.halted_sessions.join(", ") || "none"}</div>
        </div>
        <div>
          <div className="text-neutral-500">Frozen tools</div>
          <div>{status?.frozen_tools.join(", ") || "none"}</div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason for tripping (audit-logged)"
          className="rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm"
        />
        <div className="flex gap-2">
          <button
            onClick={trip}
            disabled={busy || status?.global_stop}
            className="rounded bg-red-800 px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            Trip global kill switch
          </button>
          <button
            onClick={reset}
            disabled={busy || !status?.global_stop}
            className="rounded bg-emerald-800 px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            Reset
          </button>
        </div>
        <p className="text-xs text-neutral-500">
          Signed in as {session?.user?.name}. Every trip and reset is written to the tamper-proof audit log.
        </p>
      </div>
    </div>
  );
}
