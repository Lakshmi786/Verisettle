# 05 — Eval gate: a bad prompt genuinely fails

**What this proves:** the same gate really does block a worse prompt, not just approve everything.

## Steps

This uses the same run as scenario 04 (it grades two prompt versions in one pass). Check the second version:
```sh
curl "http://localhost:5500/api/2.0/mlflow/model-versions/get?name=custodian-extraction-prompt&version=2"
```

## What you'll see

`v2-candidate` is a deliberately vague prompt (`infra/deepeval/prompts/extraction_v2_candidate.txt` — no format rules, no field names). It scores **0.000** against the same 60 real records and gets tagged `gate_result: BLOCKED`.
