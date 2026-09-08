"use client";

import { useEffect, useState } from "react";

type Entry = {
  id: number;
  event_type: string;
  source_service: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
  created_at: string;
};

type VerifyResult = { valid: boolean; entries_checked: number; breaks: { id: number; reason: string }[] };

export default function AuditPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);

  async function load() {
    const res = await fetch("/api/audit/entries");
    const data = await res.json();
    setEntries(Array.isArray(data) ? data : []);
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 6000);
    return () => clearInterval(id);
  }, []);

  async function runVerify() {
    setVerifying(true);
    setVerify(null);
    const res = await fetch("/api/audit/verify");
    setVerify(await res.json());
    setVerifying(false);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Audit log</h1>
        <button
          onClick={runVerify}
          disabled={verifying}
          className="rounded bg-white px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
        >
          {verifying ? "Verifying chain..." : "Verify chain integrity"}
        </button>
      </div>

      {verify && (
        <div
          className={`rounded px-3 py-2 text-sm ${
            verify.valid ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"
          }`}
        >
          {verify.valid
            ? `Chain valid across all ${verify.entries_checked} entries (hash linkage + MinIO WORM copies both confirmed).`
            : `Chain integrity FAILED: ${verify.breaks.map((b) => `#${b.id}: ${b.reason}`).join(" | ")}`}
        </div>
      )}

      <div className="flex flex-col gap-2">
        {entries.map((e) => (
          <details key={e.id} className="rounded border border-neutral-800 p-3">
            <summary className="cursor-pointer text-sm">
              <span className="font-mono text-neutral-500">#{e.id}</span>{" "}
              <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs">{e.event_type}</span>{" "}
              <span className="text-neutral-400">{e.source_service}</span>{" "}
              <span className="text-neutral-600">{new Date(e.created_at).toLocaleString()}</span>
            </summary>
            <pre className="mt-2 overflow-x-auto text-xs text-neutral-400">{JSON.stringify(e.payload, null, 2)}</pre>
            <div className="mt-1 truncate text-[10px] text-neutral-600">
              hash: {e.entry_hash} <br /> prev: {e.prev_hash}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
