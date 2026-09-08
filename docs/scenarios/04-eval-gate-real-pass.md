# 04 — Eval gate: a good prompt genuinely passes

**What this proves:** before a prompt version goes live, it's graded against real data — and a good one really does pass.

## Steps

1. Run the gate (takes a few minutes — real AI calls against 60 real held-out invoices):
   ```sh
   sh infra/scripts/compose.sh up deepeval-gate
   ```

2. Check the result in MLflow:
   ```sh
   curl "http://localhost:5500/api/2.0/mlflow/registered-models/alias?name=verisettle-extraction-prompt&alias=production"
   ```

## What you'll see

In the gate's own log output, `v1-production` scores around **0.64** accuracy against a pass threshold of 0.6, and gets marked `PROMOTED`.

The MLflow API call confirms the `production` alias really points at that version, tagged `gate_result: PROMOTED`.
