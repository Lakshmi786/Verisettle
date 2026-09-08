"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";

const LINKS = [
  { href: "/", label: "Pipeline" },
  { href: "/submit", label: "Submit Invoice" },
  { href: "/approvals", label: "Approvals" },
  { href: "/audit", label: "Audit Log" },
  { href: "/ledger", label: "Ledger & Cost" },
  { href: "/kill-switch", label: "Kill Switch" },
  { href: "/policies", label: "Policies" },
];

export function Nav() {
  const pathname = usePathname();
  const { data: session, status } = useSession();

  return (
    <nav className="border-b border-neutral-800 bg-neutral-950">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="font-semibold text-neutral-100">VeriSettle</span>
          <div className="flex gap-4 text-sm">
            {LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={
                  pathname === l.href
                    ? "text-white font-medium"
                    : "text-neutral-400 hover:text-neutral-200"
                }
              >
                {l.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="text-sm">
          {status === "authenticated" ? (
            <div className="flex items-center gap-3 text-neutral-300">
              <span>
                {session.user?.name} ({session.roles?.join(", ") || "no role"})
              </span>
              <button onClick={() => signOut()} className="text-neutral-400 hover:text-neutral-200">
                Sign out
              </button>
            </div>
          ) : (
            <button onClick={() => signIn("keycloak")} className="text-neutral-400 hover:text-neutral-200">
              Sign in
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
