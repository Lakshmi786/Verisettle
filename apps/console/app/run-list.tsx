"use client";

import { useEffect, useState } from "react";

type Run = {
  thread_id: string;
  task_state: string | null;
  invoice_id: string | null;
  extraction: { vendor?: string; total?: number } | null;
  requires_human: boolean;
  next: string[];
};

const STATE_COLOR: Record<string, string> = {
  extracted: "bg-blue-900 text-blue-200",
  risk_scored: "bg-purple-900 text-purple-200",
  approved: "bg-emerald-900 text-emerald-200",
  pending_human: "bg-amber-900 text-amber-200",
  rejected: "bg-red-900 text-red-200",
  blocked: "bg-red-900 text-red-200",
  settled: "bg-emerald-900 text-emerald-200",
  failed: "bg-red-900 text-red-200",
};

export function RunList() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch("/api/runs");
        const data = await res.json();
        if (!cancelled) {
          if (data.error) setError(data.error);
          else setRuns(data.runs);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    load();
    const id = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error) return <p className="text-red-400">Failed to load runs: {error}</p>;
  if (runs === null) return <p className="text-neutral-400">Loading live pipeline state...</p>;
  if (runs.length === 0) return <p className="text-neutral-400">No invoice runs yet.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-800 text-left text-neutral-400">
            <th className="py-2 pr-4">Invoice</th>
            <th className="py-2 pr-4">Vendor</th>
            <th className="py-2 pr-4">Amount</th>
            <th className="py-2 pr-4">State</th>
            <th className="py-2 pr-4">Next step</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.thread_id} className="border-b border-neutral-900">
              <td className="py-2 pr-4 font-mono text-xs">{r.invoice_id ?? r.thread_id}</td>
              <td className="py-2 pr-4">{r.extraction?.vendor ?? "-"}</td>
              <td className="py-2 pr-4">{r.extraction?.total != null ? `$${r.extraction.total.toFixed(2)}` : "-"}</td>
              <td className="py-2 pr-4">
                <span className={`rounded px-2 py-0.5 text-xs ${STATE_COLOR[r.task_state ?? ""] ?? "bg-neutral-800"}`}>
                  {r.task_state ?? "unknown"}
                </span>
              </td>
              <td className="py-2 pr-4 text-neutral-400">{r.next.join(", ") || "done"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
