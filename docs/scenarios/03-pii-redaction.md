# 03 — PII redaction

**What this proves:** personal/financial details in an invoice get blanked out before they're written to the permanent audit log.

## Steps

1. Submit an invoice with a planted bank account number, email, phone number, and name:
   ```sh
   curl -X POST http://localhost:8000/runs -H "Content-Type: application/json" -d '{
     "invoice_id": "scenario-03-pii-redaction",
     "ocr_text": "QUICKMART SUPPLIES\n88 Trade St\nDate: 2026-08-06\nTotal: 62.10\nRefund account: 4532015112830366 routing 021000021\nContact: Jane Smith jane.smith@example.com 555-987-6543",
     "source": "manual"
   }'
   ```

2. Look at the run's state:
   ```sh
   curl http://localhost:8000/runs/scenario-03-pii-redaction
   ```

## What you'll see

- `audit_trail` has a `pii_scan` step listing the entity types found (`CREDIT_CARD`, `US_BANK_NUMBER`, `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`) and a `redacted_ocr_text` with each one replaced by a tag like `<EMAIL_ADDRESS>` — that's what gets kept permanently.
- `extraction` still shows the real, correct values (`vendor`, `total`, `address`) — the AI still saw the real text to do its job; only what gets logged is redacted.
