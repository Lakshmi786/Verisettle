# 09 — Tool-call authorization

**What this proves:** an AI agent can't use a tool it wasn't given permission to use — checked two independent ways.

## Steps

1. Ask the policy rulebook whether the Extraction agent may use the ledger-writing tool:
   ```sh
   curl -X POST http://localhost:8091/authorize -H "Content-Type: application/json" -d '{
     "principal": {"type":"Agent","id":"extraction","attrs":{"trustTier":"read-only"}},
     "action": "InvokeTool",
     "resource": {"type":"Tool","id":"create-ledger-entry","attrs":{"name":"create-ledger-entry"}},
     "context": {}
   }'
   ```

2. Check the second, independent gate (plain code, not the rulebook).
   **Copy this exactly as shown, starting from column 1** — if you paste it
   indented (e.g. copied out from inside a numbered-list rendering
   somewhere), Python will reject it with `IndentationError: unexpected
   indent`, since leading spaces are part of Python's real syntax, not just
   formatting:
```sh
docker exec custodian-backend python3 -c "
from app.capability import require_capability, CapabilityDenied
try:
    require_capability('extraction', 'CreateLedgerEntry')
    print('UNEXPECTED: allowed')
except CapabilityDenied as e:
    print('DENIED (expected):', e)
"
```

## What you'll see

Both deny it — `"decision":"Deny"` from the rulebook, and `DENIED (expected): ...`
from the capability check. Two separate, independent locks on the same
door, so one misconfigured rule alone can't accidentally grant access.
