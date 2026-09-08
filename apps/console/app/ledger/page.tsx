"use client";

import { useEffect, useState } from "react";

type Balance = { account: string; type?: string; balance?: number; error?: string };
type Spend = {
  spendByAgent: { agent: string; usd: number }[];
  totalSpend24h: number;
  deniedByAgent24h: { agent: string; count: number }[];
};

export default function LedgerPage() {
  const [balances, setBalances] = useState<Balance[]>([]);
  const [spend, setSpend] = useState<Spend | null>(null);

  async function load() {
    const [b, s] = await Promise.all([
      fetch("/api/ledger/balances").then((r) => r.json()),
      fetch("/api/metrics/spend").then((r) => r.json()),
    ]);
    setBalances(b.accounts ?? []);
    setSpend(s);
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Ledger balances</h1>
        <div className="mt-3 grid grid-cols-3 gap-4">
          {balances.map((b) => (
            <div key={b.account} className="rounded border border-neutral-800 p-4">
              <div className="text-sm text-neutral-500">{b.account}</div>
              <div className="mt-1 text-2xl font-semibold">
                {b.balance != null ? `$${b.balance.toFixed(2)}` : "-"}
              </div>
              <div className="text-xs text-neutral-600">{b.type ?? b.error}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold">LLM cost (last 24h)</h2>
        <div className="mt-2 text-3xl font-semibold">${spend?.totalSpend24h.toFixed(4) ?? "-"}</div>
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-neutral-400">
              <th className="py-2 pr-4">Agent (LiteLLM virtual key)</th>
              <th className="py-2 pr-4">Spend, last hour</th>
            </tr>
          </thead>
          <tbody>
            {spend?.spendByAgent.map((r) => (
              <tr key={r.agent} className="border-b border-neutral-900">
                <td className="py-2 pr-4">{r.agent}</td>
                <td className="py-2 pr-4">${r.usd.toFixed(5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="text-lg font-semibold">Policy denials (last 24h)</h2>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-neutral-400">
              <th className="py-2 pr-4">Agent</th>
              <th className="py-2 pr-4">Denials</th>
            </tr>
          </thead>
          <tbody>
            {spend?.deniedByAgent24h.map((r) => (
              <tr key={r.agent} className="border-b border-neutral-900">
                <td className="py-2 pr-4">{r.agent}</td>
                <td className="py-2 pr-4">{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
