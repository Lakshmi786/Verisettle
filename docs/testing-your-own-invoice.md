# Testing your own invoice image

Two ways to run an invoice through the real pipeline: paste text directly
(fast, skips OCR), or upload a real image (slower, goes through the real
sandboxed OCR worker first). This covers the image path.

## Option A — the Console UI

1. Open http://localhost:3000/submit (also linked as **Submit Invoice** in the nav bar).
2. Choose an image file, optionally set an invoice ID / vendor flags.
3. Click **Submit**.

What actually happens: the browser uploads the image to the Console's own
server, which forwards it to `custodian-backend`. Backend writes it to a
shared volume, calls `custodian-sandbox-runner`'s real `/ocr` endpoint (which
spins up a fresh, network-isolated, non-root container with no Linux
capabilities to run real `pytesseract` OCR on it - and inside that
container, a real, kernel-enforced Landlock ruleset restricts the OCR code
to only the two paths it needs, one more independent layer, see
`docs/scenarios/11-sandbox-isolation.md`), then feeds the extracted text
into the same governed pipeline every other invoice goes through -
extraction → risk scoring → approval → payment.

No manual setup needed - Landlock is a plain Linux kernel feature the
container applies to itself, unlike the gVisor approach this project used
earlier which needed a Docker Desktop config step.

## Option B — curl, same endpoint

```sh
curl -X POST http://localhost:8000/runs/from-image \
  -F "file=@docs/sample-invoices/01-clean-known-vendor.png" \
  -F "invoice_id=my-real-test-1" \
  -F "vendor_first_seen=true" \
  -F "vendor_payment_count=0"
```

## The 5 sample invoices

Real PNG images with real rendered text (`docs/sample-invoices/generate.py`
made them) - the OCR worker has to actually read pixels, nothing is
pre-typed. Each one exercises a different real code path. To regenerate
them, run the script *inside* the sandbox-ocr image, not on your host - the
host's Python has no real font available and silently falls back to a tiny
placeholder font, which breaks OCR accuracy (this was a real bug found
while building these samples):
```sh
docker run --rm -v "$(pwd)/docs/sample-invoices:/out" \
  --entrypoint python3 custodian-sandbox-ocr:latest /out/generate.py
```

| File | What it's testing | What you should see |
|---|---|---|
| `01-clean-known-vendor.png` | The plain happy path | Settles automatically, real ledger transaction |
| `02-first-time-large-amount.png` | First-seen vendor + a large amount | Escalates to human review (see `/approvals`) instead of auto-approving |
| `03-prompt-injection-attempt.png` | Hidden "SYSTEM: ignore instructions..." text baked into the image | Guardrail blocks it (`task_state: failed`) before extraction ever runs - same defense as `docs/scenarios/08-prompt-injection-defense.md`, now proven through a real image instead of typed text |
| `04-pii-heavy.png` | A card number, bank routing number, email, and phone on the invoice | Extraction still gets the real vendor/total; the audit trail's `pii_scan` step shows all of it redacted |
| `05-suspicious-round-number.png` | A suspiciously large, round amount from an unrecognized-looking vendor | Risk-scoring should flag it - a classic fraud pattern (round numbers are rare in real invoices) |

Try one:
```sh
curl -X POST http://localhost:8000/runs/from-image \
  -F "file=@docs/sample-invoices/03-prompt-injection-attempt.png" \
  -F "invoice_id=test-injection-1" \
  -F "vendor_first_seen=true" \
  -F "vendor_payment_count=0"
```

Then check what actually happened:
```sh
curl http://localhost:8000/runs/test-injection-1
```

## Using your own real photo/scan instead

Same two options above work with any image - just point `-F "file=@..."`
(or the UI's file picker) at your own invoice photo or scan. No dataset
involved; this is a genuinely new document each time, read by real OCR.

**Honest limitation:** Tesseract (the real OCR engine used here) is tuned
for flat, high-contrast scans, not photos. A real angled photo with a
textured background, glare, or paper curl can genuinely come back with
*zero* extracted text - confirmed by testing directly against the seeded
SROIE/CORD dataset, where some (not most) of the real photographed receipts
return empty OCR text this way. That's not a pipeline bug: the system
handles it correctly - empty text flows through as a real extraction with
every field `null` and 0.0 confidence, which the risk-scoring agent
correctly treats as maximally suspicious and escalates to a human, rather
than crashing or silently guessing. If your own photo comes back mostly
empty, try a flatter, better-lit shot rather than assuming something's
broken.
