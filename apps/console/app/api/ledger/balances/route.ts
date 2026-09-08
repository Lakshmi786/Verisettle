import { NextResponse } from "next/server";
import { LEDGER_URL, LEDGER_API_KEY } from "@/lib/config";

// The ledger has no "list all accounts" endpoint - these three are the only seeded ones.
const ACCOUNTS = ["operating-cash", "accounts-payable", "vendor-expense"];

export async function GET() {
  const results = await Promise.all(
    ACCOUNTS.map(async (name) => {
      const res = await fetch(`${LEDGER_URL}/accounts/${name}/balance`, {
        headers: { Authorization: `Bearer ${LEDGER_API_KEY}` },
        cache: "no-store",
      });
      if (!res.ok) return { account: name, error: await res.text() };
      return res.json();
    }),
  );
  return NextResponse.json({ accounts: results });
}
