# 20 — Temporal policy: vendor approval rate limit (Dogwood)

**What this proves:** Cedar alone can only judge one request at a time — it
has no memory of what happened five minutes ago. This project's real
Dogwood-inspired rule adds exactly that: no more than 3 approved payments to
the same vendor within a rolling 24-hour window, enforced against the real
decision history, not a per-request guess.

## Steps

Call `/authorize` for `ApprovePayment` on the same brand-new vendor four
times in a row:
```sh
for i in 1 2 3 4; do
  curl -X POST http://localhost:8091/authorize -H "Content-Type: application/json" -d '{
    "principal": {"type":"Agent","id":"approval","attrs":{"trustTier":"read-and-flag"}},
    "action": "ApprovePayment",
    "resource": {"type":"Payment","id":"dogwood-rate-test-'"$i"'","attrs":{"amount":50,"vendorFirstSeen":false,"vendor":"Dogwood Rate Test Co","approvalCount":0}},
    "context": {}
  }'
done
```

## What you'll see

Calls 1-3: `{"decision":"Allow","cedar_decision":"Allow","determining_policies":["policy2"],"temporal_denial_reason":null}`.

Call 4 — real output, not illustrative:
```json
{"decision":"Deny","cedar_decision":"Allow","determining_policies":["policy2"],
 "temporal_denial_reason":"vendor 'Dogwood Rate Test Co' already has 3 approvals in the last 24h (limit 3) - escalation required"}
```

Notice `"cedar_decision":"Allow"` **stays** `Allow` on the 4th call — Cedar,
looking at this one request in isolation, genuinely sees nothing wrong with
it. It's the temporal layer, sitting on top and reading real history Cedar
never sees, that overrides the final `decision` to `Deny`. Same pattern as
the kill switch in scenario 13: the underlying rulebook says one thing, a
separate stateful check has the final word.
