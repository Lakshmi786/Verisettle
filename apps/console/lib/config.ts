// Server-side only URLs - these hit the docker network hostnames in
// production and localhost-mapped ports in local dev. Never imported from
// a client component; API routes are the only callers.
export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
export const LEDGER_URL = process.env.LEDGER_URL ?? "http://localhost:8090";
export const LEDGER_API_KEY = process.env.LEDGER_API_KEY ?? "";
export const AUDIT_LOG_URL = process.env.AUDIT_LOG_URL ?? "http://localhost:8094";
export const CONTROL_PLANE_URL = process.env.CONTROL_PLANE_URL ?? "http://localhost:8095";
export const PROMETHEUS_URL = process.env.PROMETHEUS_URL ?? "http://localhost:9095";
export const POLICIES_DIR = process.env.POLICIES_DIR ?? "../policies";
