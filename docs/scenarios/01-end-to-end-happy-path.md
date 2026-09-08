# 01 — End-to-end happy path (all six governance layers, one invoice)


**Heads up before you run this:** the demo vendor below has a real policy
rule capping it at 3 auto-approved payments per 24h (this is itself part of
the Policy-layer walkthrough below). If you've already run this exact
vendor name 3+ times today, it'll land in human review instead of settling
— still a real, correct result, just a different one. Use a fresh
`invoice_id` each time either way; the ledger refuses to pay the same
`invoice_id` twice ([see Layer 6](#layer-6--ledger-and-the-double-entry-books)).

## Step 1 — submit the invoice

```sh
curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
  "invoice_id": "scenario-01-happy-path",
  "ocr_text": "OFFICE DEPOT #4471\n455 Commerce Blvd, Austin TX\nDate: 2026-08-05\nTotal: 128.50",
  "source": "manual"
}'
```

Sends one real invoice into the live pipeline (extraction → risk scoring → approval → payment) and waits for the full result back — this is the "submit an invoice" step of the happy-path walkthrough.


```sh
curl http://localhost:8000/runs/scenario-01-happy-path
```

If `"task_state"` comes back `"pending_human"`, approve it before
continuing:

```sh
curl -X POST http://localhost:8000/runs/scenario-01-happy-path/resume \
  -H "Content-Type: application/json" \
  -d '{"decision":"approve","approver":"controller.demo"}'
```

## Now walk the six layers, in the order this run actually touched them

| # | Layer | What it checked | `audit_trail` step |
|---|---|---|---|
| 1 | Agent Runtime | Is this invoice text safe to hand to an AI agent at all? | `guardrail_check` |
| 2 | Data | Strip personal/financial data before anything gets logged permanently | `pii_scan` |
| 3 | Model | Read the invoice fields — real LLM call | `extraction` |
| 4 | Model | Score fraud/anomaly risk — real LLM call | `risk_scoring` |
| 5 | Model + Agent Runtime | Decide, then get a second opinion from a *different* AI provider | `approval_decision`, `critic_review` |
| 6 | Policy | A deterministic rulebook gets the final say — can override all of the above | (only appears if it denies) |
| 7 | Agent Runtime | Two more independent locks before the ledger-writing tool can be called | (no step unless denied — see scenario 09) |
| 8 | Identity | Fetch the ledger credential — never stored in the agent | (invisible in the trail — see scenario 02) |
| 9 | Operations | Hold, then re-check the kill switch right before committing money | `settlement_hold_start`, `settlement_hold_cleared` |
| 10 | Ledger | The real double-entry transaction | `ledger_commit` |
| 11 | Operations | Every step above becomes a permanent, tamper-evident record | (MinIO, not in the JSON response) |
| 12 | Operations | Every AI call and every policy decision is separately observable | (Langfuse / Grafana, not in the JSON response) |

### Layer 1 — Agent Runtime: the guardrail

Before any AI agent is even allowed to *read* the invoice for real, a
dedicated safety-classifier model (Groq's `gpt-oss-safeguard-20b` — a model
whose only job is spotting attacks, not extracting data) scans the raw text
for hidden instructions, jailbreak attempts, etc.

**You'll see:** `audit_trail[0]` — `"step": "guardrail_check", "safe": true`.
If this had said `false`, the run would have stopped right here

### Layer 2 — Data: PII redaction

The raw OCR text is scanned by Presidio for personal/financial data
(names, card numbers, emails, phone numbers) *before* anything is written
to the permanent audit trail. This invoice happens to be clean, but the
mechanism ran anyway.

**You'll see:** `audit_trail[1]` — `"step": "pii_scan", "entities_found": []`
(or a list of tags, if any were present) and a `redacted_ocr_text` field —
that's the version that gets kept forever, not the raw original.
`docs/scenarios/03-pii-redaction.md` runs the same check against an
invoice deliberately stuffed with a card number, bank routing number,
email, and phone number, so you can see real redaction happen.


### Layer 3 — Model: extraction

The real Extraction agent calls a real LLM — through LiteLLM, using its own
scoped API key (`LITELLM_KEY_AGENT_EXTRACTION`), routed to Groq's cheap,
fast `gpt-oss-120b` model, since reading fields off a receipt doesn't need
a reasoning model.

**You'll see:** `audit_trail[2]` — the parsed `vendor`, `date`, `address`,
`total`, and a `confidence` score. In **Langfuse** (`:3010` → Traces), find
this trace and show the real token count and real dollar cost of that one
call. In **LiteLLM UI** (`:4000/ui`), show that key's running spend just
ticked up.

### Layer 4 — Model: risk scoring

A second, independent LLM call assesses fraud/anomaly risk using the
extracted fields plus this vendor's real history — looked up live from
`custodian-ledger` (`GET /vendors/lookup`), not supplied by the request.
That's deliberate: a self-reported "I'm not a first-time vendor" flag would
let anyone bypass the first-seen-vendor rule just by asserting it. Which
model answers this depends on the amount: **above $5,000** it escalates to the expensive
reasoning model; below it, same cheap Groq model as extraction. This
invoice is $128.50, so it stays cheap.

**You'll see:** `audit_trail[3]` — `risk_level`, a numeric `risk_score`,
and the model's own written `reasons`.

### Layer 5 — Model + Agent Runtime: approval, then a second opinion

The Approval agent makes the actual pay/escalate/reject call — always on
the OpenAI reasoning model (`gpt-5.6-sol`), regardless of amount, since
this is the one decision the system never lets the cheap model make alone.
If it decides to auto-approve, a **second, independent AI agent** ("the
critic") reviews that decision before it's allowed to proceed — and it's
deliberately called using the *other* provider from whichever one just
decided (if approval used OpenAI, the critic runs on Groq), specifically so
the critic isn't just asking the same model to agree with itself.

**You'll see:** `audit_trail[4]` (`approval_decision`) and `audit_trail[5]`
(`critic_review`, `"agent": "critic(groq)"`, `"agrees": true`). If the
critic disagrees, the run gets escalated to a human even though the first
agent wanted to auto-approve .


### Layer 6 — Policy: the rulebook has the final word

Right before the Approval agent finalizes, it asks the Cedar policy engine
"is this agent allowed to approve this specific payment?" — a
**deterministic, non-AI rulebook**, completely separate from every AI
opinion above it. This is real enough to override three AI agents that all
just agreed to pay: e.g. a real rule caps any one vendor at 3 auto-approved
payments per 24 hours — if you've run this vendor a few times already
today, you'll see exactly that in `audit_trail` as
`"step": "approval_policy_denied"`, with a `temporal_denial_reason`
spelling out which rule fired.


### Layer 7 — Identity: the ledger credential is never stored

Right before Payment-Execution calls the ledger, it authenticates as its
own machine identity to Infisical and fetches `LEDGER_API_KEY` fresh — the
key is used once and never kept in the agent's own memory or environment
between calls. Open **Infisical** (`:8443`) and show students the secret
sitting in the vault.

### Layer 8 — Operations: the settlement hold

Even after every check above passes, the payment doesn't fire immediately
— it waits `SETTLEMENT_HOLD_SECONDS` (20s by default), then re-checks the
kill switch's live status *again* right before committing. A kill-switch
trip during that window blocks the payment even though everything upstream
already said yes.

### Layer 9 — Operations: the permanent, tamper-evident record

Every step you just walked through was also written, in real time, as its
own object in MinIO's `custodian-audit-log` bucket, locked with Object Lock
in compliance mode — nobody, including an admin, can quietly edit or
delete one during its retention period.

### Layer 10 — Operations: everything is observable, in aggregate

Beyond this one run's trail, every LLM call across every agent and every
policy decision across the whole fleet is continuously visible: **Langfuse**
for per-call traces/cost, **Grafana**'s Custodian Governance Overview
dashboard for fleet-wide policy-decision and LLM-spend rates. Neither of
these is specific to this one invoice — that's the point: one run gives you
an audit trail, the dashboards give you the pattern across all of them.
