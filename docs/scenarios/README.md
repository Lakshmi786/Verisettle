# Scenarios — try the guardrails yourself

Each file below is a short, self-contained script: run a few real commands
against the running stack, and see a real governance control catch
something (or correctly let something through). Every one of them was
actually run against a live system before being written down — the
commands and outputs shown are real, not illustrations.

**Before you start:** finish the whole [main README](../../README.md) setup
(through Step 6, "Confirm everything is up") so every service is healthy.
These scenarios talk to the real running containers — they don't work
against a partially-started stack.

You can run them in any order — each one is independent — but reading them
in this order tells the project's story: submit a normal invoice, watch it
get paid, then work through each layer that would have stopped it if
something were wrong.

| # | Scenario | What it proves | Governance layer |
|---|---|---|---|
| 01 | [End-to-end happy path](01-end-to-end-happy-path.md) | A real invoice can go all the way from submission to a paid ledger transaction. | (the baseline — start here) |
| 02 | [Identity & credential brokering](02-identity-credential-brokering.md) | The ledger password is never stored inside the agent — it's fetched fresh from a vault right before each use. | Identity |
| 03 | [PII redaction](03-pii-redaction.md) | Personal/financial details in an invoice get blanked out before they're written to the permanent audit log. | Data |
| 04 | [Eval gate — a good prompt passes](04-eval-gate-real-pass.md) | Before a prompt version goes live, it's graded against real data — and a good one really does pass. | Model |
| 05 | [Eval gate — a bad prompt fails](05-eval-gate-real-failure.md) | The same gate really does block a worse prompt, not just approve everything. | Model |
| 06 | [Policy change accepted](06-policy-change-accepted.md) | The real policy rulebook (Cedar) passes a real validation check before it's trusted. | Policy |
| 07 | [Policy change rejected](07-policy-change-rejected.md) | The same validator genuinely blocks a bad policy change — both an obvious mistake and a subtle one. | Policy |
| 08 | [Prompt injection defense](08-prompt-injection-defense.md) | Hidden instructions stuffed into an invoice get caught before any AI agent acts on them. | Agent Runtime |
| 09 | [Tool-call authorization](09-tool-call-authorization.md) | An AI agent can't use a tool it wasn't given permission to use — checked two independent ways. | Agent Runtime |
| 10 | [Cross-agent privilege boundary](10-cross-agent-privilege-boundary.md) | When one AI agent asks a second one for a "second opinion," the second agent still can't do more than it's normally allowed to. | Agent Runtime |
| 11 | [Sandbox isolation](11-sandbox-isolation.md) | The container that reads scanned invoice images has no internet access, no admin rights, and can't write outside its scratch space. | Agent Runtime |
| 12 | [Cost-cap enforcement](12-cost-cap-enforcement.md) | Each AI agent can only use the models it's allowed to, and can only spend up to its daily budget. | Model / Operations |
| 13 | [Kill switch — manual trip](13-kill-switch-manual.md) | An operator can press a button that overrides everything else, immediately. | Operations |
| 14 | [Kill switch — automatic triggers](14-kill-switch-automatic.md) | The kill switch also trips itself, with no human involved, when something looks wrong. | Operations |
| 15 | [Audit log tamper resistance](15-audit-log-tamper-resistance.md) | The audit log detects it if someone tries to secretly edit or delete a past entry. | Operations |
| 16 | [Dual-agent critic verification](16-dual-agent-critic.md) | A second, different-provider AI model independently reviews a payment decision before it executes — and three real attempts to fool it show *why* it rarely disagrees: everything before it already did its job. | Agent Runtime |
| 17 | [Confidence-gated execution](17-confidence-gated-execution.md) | Auto-approval requires the deciding agent to also be confident in its own decision, not just have reached one. | Agent Runtime |
| 18 | [Dry-run before commit](18-dry-run-before-commit.md) | Every payment is computed against the real ledger rules *before* it's committed — and a bad transaction never gets the chance to become real. | Agent Runtime |
| 19 | [Settlement hold + kill switch mid-hold](19-settlement-hold-kill-switch.md) | Even a payment every agent genuinely agreed to pay can still be stopped during its mandatory cooling-off window. | Agent Runtime / Operations |
| 20 | [Self-expiring credentials](20-self-expiring-credentials.md) | Workload identities carry a real ~1-hour certificate lifetime, measured live — plus a real incident showing what happens when one expires with no valid way to renew. | Identity |
| 21 | [Continuous vendor trust scoring](21-continuous-vendor-trust-scoring.md) | The same vendor, same amount, scores completely differently before vs. after real payment history exists — trust is earned from the ledger, not assumed. | Data |
| 22 | [Data quality gate](22-data-quality-gate.md) | A real Great Expectations checkpoint has its own runnable self-test, and genuinely fails on a real $5.5-billion data error already sitting in the real dataset. | Data |
| 23 | [Temporal rate limiting (Dogwood)](23-temporal-rate-limiting.md) | No more than 3 approvals to the same vendor in 24 hours — enforced by a real, stateful check Cedar alone can't do. | Policy |
| 24 | [Continuous tamper watchdog](24-continuous-tamper-watchdog.md) | A tamper that's fixed again before anyone checks still leaves a permanent trace, because something is checking on its own, all the time. | Operations |
| 25 | [MinIO Object Lock immutability](25-minio-object-lock-immutability.md) | The original locked bytes are provably indestructible — even against root credentials — while a plain write can still stack a shadow version on top. | Operations |
| 26 | [Observability: tracing](26-observability-tracing.md) | Every real AI call leaves a real, standardized trace — including an honest look at what's still incomplete about it. | Operations |
| 27 | [Metrics: Prometheus + Grafana](27-metrics-prometheus-grafana.md) | Make a number on a real dashboard move by exactly the amount you'd predict, right after causing exactly that many real events. | Operations |

A few things that hold true across all 27:

- Every command is copy-pasteable as-is from the repo root, in the same
  POSIX shell (Git Bash on Windows) used for the main setup.
- "What you'll see" is the real output from actually running the command —
  if your output differs in a value (an amount, a timestamp, an ID) that's
  fine; if it differs in *shape* (e.g. you get `Allow` where the doc says
  `Deny`), something in your setup is different from a fresh install and
  worth investigating before moving on.
- None of these scenarios modify anything permanently except 13, 14, 15, 19,
  24, and 25 (kill-switch trips, a deliberately tampered audit object) —
  each of those files tells you how to put things back, and each one shown
  here already was, live, before being written down. Scenarios 16, 18, 21,
  and 23 also write real rows (a settled payment, real policy decisions) —
  harmless and left in place, same as any other real invoice you submit
  through the console.
- Scenarios 15 and 25 use the `mc` (MinIO client) CLI. If you don't have it
  installed on your host, every `mc ...` command in this doc can be run the
  same way through a throwaway container instead, with no local install:
  ```sh
  docker run --rm --network custodian-net --entrypoint sh minio/mc:latest -c "
    mc alias set local http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
    mc <rest of the command here>
  "
  ```
  (note the endpoint changes from `localhost:9000` to `minio:9000` — the
  container reaches MinIO over the real Docker network, not your host's
  published port).

## Suggested order for a first walkthrough with students

The table above is grouped by number, but if you're teaching this fresh,
this grouping tells a better story — go top to bottom within each layer:

1. **Start here:** 01 (happy path), then 02, 03 (Identity, Data basics)
2. **Model governance:** 04, 05, 12, 26, 27 (a prompt earning production
   status, cost caps, and the observability that watches it all)
3. **Policy:** 06, 07, 23 (Cedar, then the temporal layer Cedar can't do)
4. **The agent runtime, in the order a real invoice actually hits them:**
   08 (guardrail) → 09 (tool authorization) → 11 (sandbox) → 16 (critic) →
   10 (the critic's own privilege stays boxed in) → 17 (confidence gate) →
   18 (dry-run) → 19 (settlement hold)
5. **Data that grows smarter over time:** 21, 22
6. **Identity's other half:** 20 (credentials expire, not just get checked)
7. **Operations, the safety net under everything above:** 13, 14 (kill
   switch), 15, 24, 25 (the audit log, from "detects tampering" to "detects
   tampering it never got asked to check for")
