# 18 — Dry-run before commit

**What this proves:** before any payment actually moves money, the ledger
computes what *would* happen — without writing anything — and a bad
transaction gets caught there, before it's ever real.

## Steps

Called directly against `verisettle-ledger` (same real endpoint the agent
pipeline calls internally) to isolate the ledger's own guarantees from the
AI layer:

1. **Unbalanced entries** — a debit and credit that don't match (a real
   double-entry bookkeeping violation):
   ```sh
   curl -X POST http://localhost:8090/transactions/dry-run -H "Authorization: Bearer $LEDGER_API_KEY" -H "Content-Type: application/json" -d '{
     "idempotency_key":"scenario18-unbalanced-1","description":"test","requested_by":"scenario-test",
     "entries": [
       {"account_name":"vendor-expense","direction":"debit","amount":"100.00"},
       {"account_name":"operating-cash","direction":"credit","amount":"90.00"}
     ]
   }'
   ```

2. **Insufficient funds** — a payment bigger than the account is allowed to
   go negative for:
   ```sh
   curl -X POST http://localhost:8090/transactions/dry-run -H "Authorization: Bearer $LEDGER_API_KEY" -H "Content-Type: application/json" -d '{
     "idempotency_key":"scenario18-insufficient-1","description":"test","requested_by":"scenario-test",
     "entries": [
       {"account_name":"vendor-expense","direction":"debit","amount":"99999999.00"},
       {"account_name":"operating-cash","direction":"credit","amount":"99999999.00"}
     ]
   }'
   ```

3. **Unknown account**:
   ```sh
   curl -X POST http://localhost:8090/transactions/dry-run -H "Authorization: Bearer $LEDGER_API_KEY" -H "Content-Type: application/json" -d '{
     "idempotency_key":"scenario18-noaccount-1","description":"test","requested_by":"scenario-test",
     "entries": [
       {"account_name":"vendor-expense","direction":"debit","amount":"50.00"},
       {"account_name":"nonexistent-account","direction":"credit","amount":"50.00"}
     ]
   }'
   ```

4. Confirm nothing was actually written:
   ```sh
   curl http://localhost:8090/accounts/operating-cash/balance -H "Authorization: Bearer $LEDGER_API_KEY"
   ```

5. Confirm the *real* commit endpoint (not dry-run) independently rejects
   the same bad transaction — proving the dry-run isn't just theater, it's
   sharing the actual validation:
   ```sh
   curl -X POST http://localhost:8090/transactions -H "Authorization: Bearer $LEDGER_API_KEY" -H "Content-Type: application/json" -d '{
     "idempotency_key":"scenario18-real-commit-reject-1","description":"test","requested_by":"scenario-test",
     "entries": [
       {"account_name":"vendor-expense","direction":"debit","amount":"100.00"},
       {"account_name":"operating-cash","direction":"credit","amount":"90.00"}
     ]
   }'
   ```
> This time it went to the real payment endpoint (/transactions, not /transactions/dry-run) — the actual one that would move money for real. 