from ..capability import require_capability
from ..control_plane_client import heartbeat
from ..llm_clients import get_client
from ..policy_client import PolicyDenied, authorize
from ..schemas import ApprovalDecision, CriticReview, InvoiceRunState
from ..tracing import llm_span

CONFIDENCE_THRESHOLD = 0.75

APPROVAL_PROMPT = """You are the payment approval decision agent. Given the
extracted invoice and its risk assessment, decide whether to auto-approve,
escalate to a human, or reject.

Extraction: {extraction}
Risk assessment: {risk}
"""

CRITIC_PROMPT = """You are an independent adversarial reviewer checking
another agent's payment approval decision before it executes. Does this
decision look correct given the evidence? Flag any concerns.

Extraction: {extraction}
Risk assessment: {risk}
Proposed decision: {decision}
"""


def run(state: InvoiceRunState) -> InvoiceRunState:
    heartbeat("approval", state["invoice_id"])
    audit = state["audit_trail"]
    extraction, risk = state["extraction"], state["risk"]
    amount = extraction.get("total") or 0

    client = get_client("approval")
    with llm_span("approval", "custodian-reasoning") as record_usage:
        decision: ApprovalDecision
        decision, completion = client.chat.completions.create_with_completion(
            model="custodian-reasoning",
            response_model=ApprovalDecision,
            messages=[{"role": "user", "content": APPROVAL_PROMPT.format(extraction=extraction, risk=risk)}],
            max_retries=2,
            # gpt-5.6-sol rejects function-tool calls with reasoning_effort != "none".
            extra_body={"reasoning_effort": "none"},
        )
        record_usage(completion)
    audit.append({"step": "approval_decision", "agent": "approval", "result": decision.model_dump()})

    # Below threshold, human approval is required regardless of policy.
    if decision.confidence < CONFIDENCE_THRESHOLD:
        state["requires_human"] = True
        state["approval"] = decision.model_dump()
        audit.append({"step": "low_confidence_escalation", "confidence": decision.confidence,
                       "threshold": CONFIDENCE_THRESHOLD})
        state["task_state"] = "pending_human"
        return state

    if decision.decision != "auto_approve":
        state["requires_human"] = decision.decision == "escalate_to_human"
        state["approval"] = decision.model_dump()
        state["task_state"] = "pending_human" if state["requires_human"] else "rejected"
        return state

    # Dual-agent critic: a second opinion from the other provider before a payment executes.
    critic_client = get_client("risk-scoring")  # Groq-backed route: the other provider from approval's OpenAI call
    with llm_span("critic", "custodian-routine") as record_usage:
        critic: CriticReview
        critic, completion = critic_client.chat.completions.create_with_completion(
            model="custodian-routine",
            response_model=CriticReview,
            messages=[{"role": "user", "content": CRITIC_PROMPT.format(
                extraction=extraction, risk=risk, decision=decision.model_dump())}],
            max_retries=2,
            extra_body={"reasoning_effort": "low"},
        )
        record_usage(completion)
    audit.append({"step": "critic_review", "agent": "critic(groq)", "result": critic.model_dump()})

    if not critic.agrees:
        state["requires_human"] = True
        state["approval"] = decision.model_dump()
        state["critic"] = critic.model_dump()
        audit.append({"step": "critic_disagreement_escalation", "concerns": critic.concerns})
        state["task_state"] = "pending_human"
        return state

    require_capability("approval", "ApprovePayment")
    resource = {
        "type": "Payment", "id": state["invoice_id"],
        "attrs": {
            "amount": amount,
            "vendorFirstSeen": risk.get("vendor_first_seen", False),
            "vendor": extraction.get("vendor") or "unknown",
            "approvalCount": state.get("prior_approval_count", 0),
        },
    }
    try:
        authorize({"type": "Agent", "id": "approval", "attrs": {"trustTier": "read-and-flag"}},
                  "ApprovePayment", resource)
    except PolicyDenied as e:
        state["requires_human"] = True
        audit.append({"step": "approval_policy_denied", "reason": str(e)})
        state["task_state"] = "pending_human"
        return state

    state["approval"] = decision.model_dump()
    state["critic"] = critic.model_dump()
    state["task_state"] = "approved"
    return state
