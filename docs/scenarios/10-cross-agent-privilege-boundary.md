# 10 — Cross-agent privilege boundary

**What this proves:** when one AI agent asks a second one for a "second opinion," the second agent still can't do more than it's normally allowed to.

## Steps

The critic only runs after the Approval agent reaches a confident
`auto_approve` — and vendor trust is now looked up for real from
`custodian-ledger`, not accepted from the request (see scenario 01, Layer
4), so a made-up, never-seen-before vendor name will get escalated to a
human instead of auto-approved, and the critic step this scenario needs
would never run. Establish real history first, then reuse the exact same
vendor:

1. Submit once to create real payment history for this vendor (likely
   needs human approval, since it's the vendor's first time):
   ```sh
   curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
     "invoice_id": "scenario-10-privilege-boundary-seed-v2",
     "ocr_text": "MERIDIAN OFFICE SYSTEMS\n77 Harbor View Dr, Tampa FL\nDate: 2026-08-09\nTotal: 88.20",
     "source": "manual"
   }'
   ```
   If `"task_state"` comes back `"pending_human"`, approve it:
   ```sh
   curl -X POST http://localhost:8000/runs/scenario-10-privilege-boundary-seed-v2/resume \
     -H "Content-Type: application/json" \
     -d '{"decision":"approve","approver":"controller.demo"}'
   ```

2. Submit the *same* vendor again, same amount — now it's a known vendor
   with a matching payment pattern, clean enough to auto-approve:
   ```sh
   curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
     "invoice_id": "scenario-10-privilege-boundary-v2",
     "ocr_text": "MERIDIAN OFFICE SYSTEMS\n77 Harbor View Dr, Tampa FL\nDate: 2026-08-09\nTotal: 88.20",
     "source": "manual"
   }'
   ```

3. Check that the same three roles are still separately restricted.
   
```sh
docker exec custodian-backend python3 -c "
from app.capability import require_capability, CapabilityDenied
for agent, action in [('risk-scoring','CreateLedgerEntry'), ('approval','CreateLedgerEntry'), ('payment-execution','ApprovePayment')]:
    try:
        require_capability(agent, action)
        print(agent, action, '-> ALLOWED')
    except CapabilityDenied as e:
        print(agent, action, '-> DENIED:', e)
"
```

## What you'll see
 All three checks say `DENIED` - never gets ledger-write access just because it was asked to help with a payment decision.
