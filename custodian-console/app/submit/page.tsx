"use client";

import { useState } from "react";
import Link from "next/link";

type RunResult = {
  thread_id: string;
  state: {
    task_state: string;
    extraction?: { vendor?: string; total?: number };
    audit_trail?: { step: string }[];
  };
};

export default function SubmitPage() {
  const [file, setFile] = useState<File | null>(null);
  const [invoiceId, setInvoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file) {
      setError("choose an image file first");
      return;
    }
    const id = invoiceId.trim() || `upload-${Date.now()}`;
    setBusy(true);
    setError(null);
    setResult(null);

    const form = new FormData();
    form.set("file", file);
    form.set("invoice_id", id);

    const res = await fetch("/api/runs/upload", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) {
      setError(data.error ?? "upload failed");
    } else {
      setResult(data);
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Submit an invoice image</h1>
      <p className="text-sm text-neutral-400">
        Uploads a real image, runs it through the sandboxed OCR worker (hardened Docker plus a
        real Landlock kernel ruleset - see <code className="text-neutral-300">docs/scenarios/11-sandbox-isolation.md</code>),
        then feeds the extracted text into the real governed pipeline (extraction → risk scoring
        → approval → payment). No setup step needed - Landlock is a plain kernel feature the
        sandbox applies to itself.
      </p>

      <div className="flex flex-col gap-3 rounded border border-neutral-800 p-4">
        <div>
          <label className="mb-1 block text-sm text-neutral-400">Invoice image</label>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-neutral-400">Invoice ID (optional, auto-generated if blank)</label>
          <input
            type="text"
            value={invoiceId}
            onChange={(e) => setInvoiceId(e.target.value)}
            placeholder="my-test-invoice-1"
            className="w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm"
          />
        </div>
        <p className="text-xs text-neutral-500">
          Whether this vendor is first-seen, and their prior payment count, is looked up for
          real from the ledger&apos;s vendor history during risk-scoring - not something you
          set here. See the <Link href="/policies" className="underline">Policies</Link> page
          for the dual-approval rule this feeds.
        </p>
        <button
          disabled={busy}
          onClick={submit}
          className="w-fit rounded bg-white px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
        >
          {busy ? "Running (real OCR + real LLM calls)..." : "Submit"}
        </button>
      </div>

      {error && <p className="rounded bg-red-950 px-3 py-2 text-sm text-red-300">{error}</p>}

      {result && (
        <div className="rounded border border-neutral-800 p-4 text-sm">
          <p className="mb-2">
            Run <span className="font-mono">{result.thread_id}</span> reached state{" "}
            <span className="font-medium">{result.state.task_state}</span>.
          </p>
          {result.state.extraction && (
            <p className="text-neutral-400">
              Extracted: {result.state.extraction.vendor ?? "-"}
              {result.state.extraction.total != null ? ` — $${result.state.extraction.total.toFixed(2)}` : ""}
            </p>
          )}
          <p className="mt-2">
            <Link href="/" className="text-neutral-300 underline">
              View it in the live pipeline
            </Link>
            {result.state.task_state === "pending_human" && (
              <>
                {" · "}
                <Link href="/approvals" className="text-neutral-300 underline">
                  It needs human approval
                </Link>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
