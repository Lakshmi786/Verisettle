import { NextResponse } from "next/server";
import { PROMETHEUS_URL } from "@/lib/config";

async function query(promql: string) {
  const url = `${PROMETHEUS_URL}/api/v1/query?query=${encodeURIComponent(promql)}`;
  const res = await fetch(url, { cache: "no-store" });
  const data = await res.json();
  return (data.data?.result ?? []) as { metric: Record<string, string>; value: [number, string] }[];
}

export async function GET() {
  const [spendByAgent, totalSpend24h, deniedByAgent24h] = await Promise.all([
    query("sum(increase(litellm_spend_metric_total[1h])) by (api_key_alias)"),
    query("sum(increase(litellm_spend_metric_total[24h]))"),
    query('sum(increase(policy_decisions_total{decision="Deny"}[24h])) by (principal_id)'),
  ]);

  return NextResponse.json({
    spendByAgent: spendByAgent.map((r) => ({ agent: r.metric.api_key_alias, usd: Number(r.value[1]) })),
    totalSpend24h: Number(totalSpend24h[0]?.value[1] ?? 0),
    deniedByAgent24h: deniedByAgent24h.map((r) => ({ agent: r.metric.principal_id, count: Number(r.value[1]) })),
  });
}
