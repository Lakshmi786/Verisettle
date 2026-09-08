import os

# Must be set before `import mlflow`: MLflow's REST client reads these once
# at import/first-use, not per-call - setting them later (even inside the
# function that calls mlflow.genai.load_prompt) has no effect, confirmed by
# testing against a real stopped mlflow container (still hung ~90s with the
# 7-retry exponential-backoff default even after a later setdefault(5)).
# MAX_RETRIES=1 too: 5s timeout x 7 retries with backoff_factor=2 is still
# minutes, not the fail-open-fast posture this codebase uses everywhere else.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")

import mlflow

from ..control_plane_client import heartbeat
from ..guardrail import check_content
from ..llm_clients import get_client
from ..pii import redact_for_audit
from ..schemas import ExtractedInvoice, InvoiceRunState
from ..tracing import llm_span

MLFLOW_URL = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
PROMPT_REGISTRY_NAME = "custodian-extraction-prompt"

# Used only if MLflow has no "production"-aliased prompt yet (eval_gate.py
# hasn't run) or is unreachable at startup - the extraction agent must still
# be able to serve requests, same fail-open posture as pii.py/policy_client.py
# use for their own non-security-critical dependencies.
_FALLBACK_PROMPT = """You are an invoice field extraction system. You will be
given raw OCR text tokens from a scanned receipt/invoice, in reading order.

Extract exactly these four fields: vendor, date, address, total (a plain
number, no currency symbol). Use ONLY information present in the OCR text -
never guess or invent a value; use null if a field is not present.

OCR text:
{ocr_text}
"""


def _load_extraction_prompt() -> str:
    """Loads the real MLflow-promoted prompt (Model Governance Ground Rule
    4.3): the version eval_gate.py aliased "production" after it genuinely
    passed the accuracy gate. Loaded once at process startup, not per
    request - a newly promoted version takes effect on the next restart,
    same explicit-refresh pattern as policy-service's /reload."""
    try:
        mlflow.set_tracking_uri(MLFLOW_URL)
        return mlflow.genai.load_prompt(f"prompts:/{PROMPT_REGISTRY_NAME}@production").template
    except Exception:
        return _FALLBACK_PROMPT


EXTRACTION_PROMPT = _load_extraction_prompt()


def run(state: InvoiceRunState) -> InvoiceRunState:
    heartbeat("extraction", state["invoice_id"])
    audit = state.setdefault("audit_trail", [])
    ocr_text = state["ocr_text"]

    guardrail = check_content(ocr_text)
    audit.append({"step": "guardrail_check", "agent": "extraction", "safe": guardrail.safe,
                   "severity": guardrail.severity, "reason": guardrail.reason})

    # The raw OCR text itself is never written to the audit trail - only a
    # Presidio-redacted copy, plus which entity types were found. The
    # extraction call just below still gets the real ocr_text (it
    # legitimately needs the real vendor/address to do its job); this only
    # protects what durably lands in the audit record a human reviews.
    redacted_text, pii_found = redact_for_audit(ocr_text)
    audit.append({"step": "pii_scan", "agent": "extraction", "entities_found": pii_found,
                   "redacted_ocr_text": redacted_text})

    if not guardrail.safe:
        state["task_state"] = "failed"
        state["requires_human"] = True
        audit.append({"step": "extraction_blocked", "reason": "guardrail flagged unsafe content"})
        return state

    client = get_client("extraction")
    with llm_span("extraction", "custodian-routine") as record_usage:
        result: ExtractedInvoice
        result, completion = client.chat.completions.create_with_completion(
            model="custodian-routine",
            response_model=ExtractedInvoice,
            # .replace, not .format: the real MLflow-registered production
            # prompt contains a literal JSON example with {"vendor": ...}
            # braces that .format() would choke on as unmatched fields.
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.replace("{ocr_text}", ocr_text)}],
            max_retries=2,
            extra_body={"reasoning_effort": "low"},
        )
        record_usage(completion)

    state["extraction"] = result.model_dump()
    state["task_state"] = "extracted"
    audit.append({"step": "extraction", "agent": "extraction", "result": result.model_dump()})
    return state
