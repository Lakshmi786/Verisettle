"use client";

import { useEffect, useState } from "react";

type History = { hash: string; author: string; date: string; message: string };
type FileDetail = { path: string; content: string; history: History[] };

export default function PoliciesPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<FileDetail | null>(null);

  useEffect(() => {
    fetch("/api/policies")
      .then((r) => r.json())
      .then((d) => setFiles(d.files ?? []));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetch(`/api/policies/${selected}`)
      .then((r) => r.json())
      .then(setDetail);
  }, [selected]);

  return (
    <div className="flex gap-6">
      <div className="w-64 shrink-0">
        <h1 className="text-xl font-semibold">Policies</h1>
        <ul className="mt-3 flex flex-col gap-1">
          {files.map((f) => (
            <li key={f}>
              <button
                onClick={() => setSelected(f)}
                className={`w-full truncate rounded px-2 py-1 text-left text-sm ${
                  selected === f ? "bg-neutral-800" : "hover:bg-neutral-900"
                }`}
              >
                {f}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex-1">
        {!selected && <p className="text-neutral-400">Select a policy file.</p>}
        {selected && !detail && <p className="text-neutral-400">Loading...</p>}
        {detail && (
          <div className="flex flex-col gap-4">
            <pre className="overflow-x-auto rounded border border-neutral-800 bg-neutral-950 p-4 text-xs">
              {detail.content}
            </pre>
            <div>
              <h2 className="text-sm font-semibold text-neutral-400">Git history</h2>
              {detail.history.length === 0 ? (
                <p className="text-sm text-neutral-500">No commits yet for this file.</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-2">
                  {detail.history.map((h) => (
                    <li key={h.hash} className="rounded border border-neutral-900 p-2 text-xs">
                      <div className="font-mono text-neutral-500">{h.hash.slice(0, 8)}</div>
                      <div>{h.message}</div>
                      <div className="text-neutral-600">
                        {h.author} - {new Date(h.date).toLocaleString()}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
