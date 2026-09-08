from ..capability import require_capability
from ..control_plane_client import heartbeat
from ..llm_clients import get_client
from ..policy_client import PolicyDenied, authorize
from ..schemas import InvoiceRunState, RiskScore
from ..tracing import llm_span
from ..vendor_lookup import lookup_vendor

ROUTINE_AMOUNT_THRESHOLD = 5000

RISK_PROMPT = """You are a fraud/anomaly risk-scoring system for vendor
invoice payments. Given the extracted invoice fields and vendor history,
assess the risk of this being fraudulent, duplicated, or anomalous.

Extracted invoice: {extraction}
Vendor first seen: {vendor_first_seen}
Vendor historical payment count: {vendor_payment_count}
Vendor's average past payment amount: {vendor_avg_amount}
Vendor's most recent past payment amounts (newest first): {vendor_recent_amounts}

Weigh amount-pattern consistency explicitly: a payment far above this
vendor's normal amount is a real fraud signal, even for a known vendor with
many prior payments - a compromised or spoofed vendor account making one
unusually large request is a classic pattern. A payment in line with their
usual amounts, from a known vendor, should score low risk.

Return a risk_level (low/medium/high), a 0-1 risk_score, your reasons, and
your confidence.
"""


def run(state: InvoiceRunState) -> InvoiceRunState:
    heartbeat("risk-scoring", state["invoice_id"])
    audit = state["audit_trail"]
    extraction = state["extraction"]
    amount = extraction.get("total") or 0

    # Above the routine-amount threshold uses the reasoning-tier model;
    # routine amounts use the fast/cheap route.
    model = "custodian-reasoning" if amount > ROUTINE_AMOUNT_THRESHOLD else "custodian-routine"

    # Real lookup against the ledger's vendor history, not a client-supplied
    # flag: vendor_first_seen is a fraud-relevant signal the dual-approval
    # policy (02-first-seen-vendor-dual-approval.cedar) depends on directly -
    # trusting whatever the request body claims would let anyone bypass that
    # rule just by asserting vendor_first_seen=false. No vendor name at all
    # (extraction failed) is treated as unknown/first-seen, the safer default.
    vendor_name = extraction.get("vendor")
    lookup = lookup_vendor(vendor_name) if vendor_name else {
        "known": False, "award_count": 0, "avg_amount": None, "recent_amounts": [],
    }
    vendor_first_seen = not lookup["known"]
    vendor_payment_count = lookup["award_count"]
    vendor_avg_amount = lookup.get("avg_amount")
    vendor_recent_amounts = lookup.get("recent_amounts") or []
    audit.append({"step": "vendor_lookup", "agent": "risk-scoring", "vendor": vendor_name, "result": lookup})

    # gpt-5.6-sol rejects function-tool calls with reasoning_effort != "none";
    # the Groq gpt-oss route needs "low" to leave room in max_tokens after
    # its reasoning trace.
    reasoning_effort = "none" if model == "custodian-reasoning" else "low"

    client = get_client("risk-scoring")
    with llm_span("risk-scoring", model) as record_usage:
        result: RiskScore
        result, completion = client.chat.completions.create_with_completion(
            model=model,
            response_model=RiskScore,
            messages=[{"role": "user", "content": RISK_PROMPT.format(
                extraction=extraction, vendor_first_seen=vendor_first_seen,
                vendor_payment_count=vendor_payment_count,
                vendor_avg_amount=vendor_avg_amount, vendor_recent_amounts=vendor_recent_amounts,
            )}],
            max_retries=2,
            extra_body={"reasoning_effort": reasoning_effort},
        )
        record_usage(completion)
    result_dict = result.model_dump()
    result_dict["vendor_first_seen"] = vendor_first_seen
    state["risk"] = result_dict
    audit.append({"step": "risk_scoring", "agent": "risk-scoring", "model": model, "result": result_dict})

    if result.risk_level == "high":
        require_capability("risk-scoring", "FlagForReview")
        try:
            authorize(
                {"type": "Agent", "id": "risk-scoring", "attrs": {"trustTier": "read-and-flag"}},
                "FlagForReview",
                {"type": "Payment", "id": state["invoice_id"], "attrs": {
                    "amount": amount, "vendorFirstSeen": vendor_first_seen,
                    "vendor": state["extraction"].get("vendor") or "unknown", "approvalCount": 0,
                }},
            )
            audit.append({"step": "flag_for_review", "agent": "risk-scoring", "reason": "high risk score"})
            state["requires_human"] = True
        except PolicyDenied as e:
            audit.append({"step": "flag_for_review_denied", "reason": str(e)})

    state["task_state"] = "risk_scored"
    return state
