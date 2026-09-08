# 19 — Settlement hold window + a kill switch trip mid-hold

**What this proves:** even a payment every single agent (extraction, risk,
approval, *and* the independent critic) genuinely agreed to pay can still be
stopped, because there's a deliberate pause between "everyone agreed" and
"the money actually moves" — and the kill switch is re-checked at the end of
that pause, not just at the start.

## Steps

1. Submit a clean, ordinary invoice that every layer will genuinely approve
   (known vendor, amount matching its history) — but don't wait for the
   response, since it'll be sitting in its 20s hold:
   ```sh
   curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
     "invoice_id": "killswitch-during-hold-1",
     "ocr_text": "Reliable Vendor LLC\nInvoice Date: 2026-08-13\n123 Business Ave, Springfield\nTotal: 145.00",
     "source": "manual"
   }' &
   ```

2. A few seconds in — while extraction/risk/approval/critic are still
   running or just finished, and the hold has started — trip a kill switch
   scoped to just this one session (not the whole system):
   ```sh
   curl -X POST http://localhost:8095/kill-switch/trip -H "Content-Type: application/json" -d '{
     "scope":"session","target":"killswitch-during-hold-1",
     "reason":"scenario 19 test - trip during settlement hold","triggered_by":"scenario-test"
   }'
   ```

3. Wait for the original request to finish and read its result.

4. Reset the kill switch and confirm nothing was actually written to the
   ledger:
   ```sh
   curl -X POST http://localhost:8095/kill-switch/reset -H "Content-Type: application/json" -d '{
     "scope":"session","target":"killswitch-during-hold-1","reset_by":"scenario-test"
   }'
   curl http://localhost:8090/accounts/operating-cash/balance -H "Authorization: Bearer $LEDGER_API_KEY"
   ```