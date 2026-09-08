# 17 — Confidence-gated execution

**What this proves:** it's not enough for the Approval agent to *decide*
auto-approve — it also has to be confident about that decision. Below a
hard-coded threshold, a human gets pulled in regardless of what the decision
itself was.

## Steps — three real, live attempts to trigger it

**Attempt 1 — ambiguous amount** (a known vendor, but the amount is ~3x its
historical average, not obviously fine or obviously fraudulent):
```sh
curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
  "invoice_id": "confidence-test-1",
  "ocr_text": "Reliable Vendor LLC\nInvoice Date: 2026-08-13\n123 Business Ave, Springfield\nTotal: 410.00",
  "source": "manual"
}'
```
**Result:** `"approval": {"decision": "escalate_to_human", "confidence": 0.97}`.
High confidence — the model was very sure it should escalate. Never reached
the confidence gate at all (it never gets there for `decision != auto_approve`
in the first place — see the `if decision.decision != "auto_approve"` branch
right after).

**Attempt 2 — almost no information** (an invoice with only a total, no
vendor/date/address):
```sh
curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
  "invoice_id": "confidence-test-2",
  "ocr_text": "Total: 60.00",
  "source": "manual"
}'
```
**Result:** `"approval": {"decision": "escalate_to_human", "confidence": 0.98}`
— again, very confident (about escalating, given how little it had to work
with). (This attempt also hit the real, already-documented transient Groq
guardrail tool-call failure on the first try — see the main README's
troubleshooting section — and succeeded on a plain retry.)

**Attempt 3 — genuinely self-contradictory OCR text** (two possible dates,
two different addresses, an uncertain surcharge, on an otherwise
known/low-risk vendor):
```sh
curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
  "invoice_id": "confidence-test-3",
  "ocr_text": "Reliable Vendor LLC (formerly Reliable Vendors Inc, merged 2026)\nInvoice Date: 2026-08-13 (or possibly 2026-08-30, date stamp unclear)\n123 Business Ave, Springfield OR 456 Commerce St, Springfield (two addresses listed)\nTotal: 145.00 (may exclude a possible 15% surcharge, unclear if already applied)",
  "source": "manual"
}'
```
**Result — the interesting one:** `extraction.confidence` genuinely dropped
to **0.6** (the model correctly registered the ambiguity). But
`approval.confidence` stayed at **0.91** and the payment auto-approved and
settled. Extraction-confidence and approval-decision-confidence are two
different signals: the underlying facts were fuzzy, but *given* those fuzzy
facts, the amount still cleanly matched the vendor's history, so the
Approval agent was still confident that "approve" was the right call despite
the fuzziness. Only `decision.confidence` gates this code path — not
`extraction.confidence`.