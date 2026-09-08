"""The Model Governance promotion gate: scores two extraction prompt
versions against the real held-out SROIE test split with a deterministic
metric, registers both in MLflow, and promotes to "production" only the
version that clears PROMOTION_THRESHOLD.
"""
import json
import os
import re
import time
import sys

import mlflow
import psycopg2
import requests
from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY = os.environ["LITELLM_KEY"]
MLFLOW_URL = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
PROMOTION_THRESHOLD = float(os.environ.get("PROMOTION_THRESHOLD", "0.6"))
REGISTERED_MODEL_NAME = "verisettle-extraction-prompt"
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

PROMPT_VERSIONS = {
    "v1-production": "extraction_v1_production.txt",
    "v2-candidate": "extraction_v2_candidate.txt",
}


def fetch_test_records(limit=60):
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname="verisettle_backend",
        user="verisettle_backend",
        password=os.environ["PGPASS_VERISETTLE_BACKEND"],
    )
    with conn.cursor() as cur:
        cur.execute("""
            SELECT external_key, ground_truth, raw_ground_truth
            FROM invoices
            WHERE source = 'sroie' AND split = 'test'
            ORDER BY external_key
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
    conn.close()
    return [{"key": k, "ground_truth": gt, "raw": raw} for k, gt, raw in rows]


def call_extraction(prompt_template, ocr_text, max_retries=5):
    prompt = prompt_template.replace("{ocr_text}", ocr_text)
    for attempt in range(max_retries):
        resp = requests.post(
            f"{LITELLM_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            json={
                "model": "verisettle-routine",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 800,
                # "low" leaves room in max_tokens for the answer after
                # gpt-oss's reasoning trace.
                "reasoning_effort": "low",
            },
            timeout=60,
        )
        if resp.status_code == 429 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        break
    content = resp.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _amount_close(a, b, tol=0.02):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= tol


class FieldExtractionAccuracyMetric(BaseMetric):
    """Deterministic (non-LLM-judged) field-level accuracy against real
    ground truth - total is numeric-tolerant, text fields are substring
    matched after normalization."""

    def __init__(self, threshold: float = PROMOTION_THRESHOLD):
        self.threshold = threshold

    def measure(self, test_case: LLMTestCase) -> float:
        predicted = json.loads(test_case.actual_output)
        expected = json.loads(test_case.expected_output)

        checks = []
        if expected.get("total") is not None:
            checks.append(_amount_close(predicted.get("total"), expected["total"]))
        for field in ("vendor", "address"):
            if expected.get(field):
                pred_val = _norm(predicted.get(field))
                exp_val = _norm(expected.get(field))
                checks.append(bool(pred_val) and (pred_val in exp_val or exp_val in pred_val))
        if expected.get("date"):
            checks.append(_norm(predicted.get("date")) == _norm(expected.get("date")))

        self.score = sum(checks) / len(checks) if checks else 0.0
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return "FieldExtractionAccuracy"


def run_prompt_version(version_name, filename, records):
    with open(os.path.join(PROMPTS_DIR, filename)) as f:
        template = f.read()

    test_cases = []
    for rec in records:
        ocr_text = " ".join(rec["raw"].get("words") or [])
        predicted = call_extraction(template, ocr_text)
        test_cases.append(LLMTestCase(
            input=ocr_text,
            actual_output=json.dumps(predicted),
            expected_output=json.dumps(rec["ground_truth"]),
        ))
        time.sleep(1.0)  # stay under Groq free-tier requests-per-minute limits

    metric = FieldExtractionAccuracyMetric()
    result = evaluate(
        test_cases,
        [metric],
        display_config=DisplayConfig(print_results=False, show_indicator=False),
        async_config=AsyncConfig(run_async=False),
    )
    scores = [r.metrics_data[0].score for r in result.test_results]
    overall = sum(scores) / len(scores) if scores else 0.0
    passed = sum(1 for s in scores if s >= PROMOTION_THRESHOLD)

    return {
        "template": template,
        "overall_accuracy": overall,
        "n_records": len(records),
        "n_passed": passed,
        "pass_rate": passed / len(records) if records else 0.0,
    }


def register_and_gate(version_name, result):
    with mlflow.start_run(run_name=f"extraction-prompt-{version_name}") as run:
        mlflow.log_param("prompt_version", version_name)
        mlflow.log_param("promotion_threshold", PROMOTION_THRESHOLD)
        mlflow.log_metric("overall_accuracy", result["overall_accuracy"])
        mlflow.log_metric("pass_rate", result["pass_rate"])
        mlflow.log_metric("n_records", result["n_records"])

        # MLflow's dedicated Prompt Registry, not the generic Model Registry.
        promoted = result["overall_accuracy"] >= PROMOTION_THRESHOLD
        pv = mlflow.genai.register_prompt(
            name=REGISTERED_MODEL_NAME,
            template=result["template"],
            commit_message=f"eval gate run {run.info.run_id}: "
                            f"accuracy={result['overall_accuracy']:.3f} "
                            f"({'PROMOTED' if promoted else 'BLOCKED'})",
            tags={
                "prompt_version": version_name,
                "gate_result": "PROMOTED" if promoted else "BLOCKED",
                "overall_accuracy": f"{result['overall_accuracy']:.3f}",
            },
        )
        if promoted:
            mlflow.genai.set_prompt_alias(REGISTERED_MODEL_NAME, "production", pv.version)

        return pv.version, promoted


def main():
    mlflow.set_tracking_uri(MLFLOW_URL)
    mlflow.set_experiment("verisettle-model-governance")

    records = fetch_test_records()
    print(f"Loaded {len(records)} real held-out SROIE test records for the eval gate.\n")

    outcomes = {}
    for version_name, filename in PROMPT_VERSIONS.items():
        print(f"=== evaluating prompt version {version_name!r} ===")
        result = run_prompt_version(version_name, filename, records)
        print(f"  overall_accuracy={result['overall_accuracy']:.3f} "
              f"pass_rate={result['pass_rate']:.3f} "
              f"(threshold={PROMOTION_THRESHOLD})")
        mv_version, promoted = register_and_gate(version_name, result)
        outcomes[version_name] = {"mlflow_version": mv_version, "promoted": promoted, **result}
        verdict = "PROMOTED to production" if promoted else "BLOCKED (below threshold)"
        print(f"  MLflow model version {mv_version}: {verdict}\n")

    print("=== summary ===")
    for name, o in outcomes.items():
        print(f"{name}: accuracy={o['overall_accuracy']:.3f} -> "
              f"{'PROMOTED' if o['promoted'] else 'BLOCKED'} (mlflow v{o['mlflow_version']})")

    if not outcomes["v1-production"]["promoted"]:
        print("FAIL: expected v1-production to pass the gate", file=sys.stderr)
        sys.exit(1)
    if outcomes["v2-candidate"]["promoted"]:
        print("FAIL: expected v2-candidate to be genuinely blocked by the gate", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
