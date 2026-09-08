# 13 — Kill switch: manual trip

**What this proves:** an operator can press a button that overrides everything else, immediately.

## Steps

1. Confirm a payment approval that would normally be allowed:
   ```sh
   curl -X POST http://localhost:8091/authorize -H "Content-Type: application/json" -d '{
     "principal": {"type":"Agent","id":"approval","attrs":{"trustTier":"read-and-flag"}},
     "action": "ApprovePayment",
     "resource": {"type":"Payment","id":"kill-switch-test-1","attrs":{"amount":100,"vendorFirstSeen":false,"vendor":"acme-corp","approvalCount":0}},
     "context": {}
   }'
   ```

2. Trip the kill switch:
   ```sh
   curl -X POST http://localhost:8095/kill-switch/trip -H "Content-Type: application/json" -d '{
     "scope":"global","target":"*","reason":"manual test","triggered_by":"manual-test"
   }'
   ```

3. Repeat step 1's exact same request.

4. Turn it back off:
   ```sh
   curl -X POST http://localhost:8095/kill-switch/reset -H "Content-Type: application/json" -d '{
     "scope":"global","target":"*","reset_by":"manual-test"
   }'
   ```

## What you'll see

Step 1: `"decision":"Allow"`. Step 3 (same request, after tripping): `"decision":"Deny"`, with `"temporal_denial_reason":"global kill-switch is tripped"` — even though the rulebook itself still says `Allow` underneath, the kill switch overrides it.
