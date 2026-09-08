import os
import time
import uuid

import requests

from .. import ledger_client
from ..capability import require_capability
from ..control_plane_client import heartbeat, kill_switch_status
from ..policy_client import PolicyDenied, authorize
from ..schemas import InvoiceRunState

# An approved payment waits here, then kill-switch state is re-read right
# before commit - a trip during the hold blocks it.
SETTLEMENT_HOLD_SECONDS = int(os.environ.get("SETTLEMENT_HOLD_SECONDS", "20"))


def run(state: InvoiceRunState) -> InvoiceRunState:
    heartbeat("payment-execution", state["invoice_id"])
    audit = state["audit_trail"]
    extraction, risk = state["extraction"], state["risk"]
    amount = extraction.get("total") or 0
    vendor = extraction.get("vendor") or "unknown"

    require_capability("payment-execution", "CreateLedgerEntry")
    resource = {
        "type": "Payment", "id": state["invoice_id"],
        "attrs": {
            "amount": amount,
            "vendorFirstSeen": risk.get("vendor_first_seen", False),
            "vendor": vendor,
            "approvalCount": state.get("prior_approval_count", 0),
        },
    }
    try:
        authorize({"type": "Agent", "id": "payment-execution", "attrs": {"trustTier": "write-ledger"}},
                  "CreateLedgerEntry", resource)
    except PolicyDenied as e:
        state["payment"] = {"status": "blocked", "reason": str(e)}
        audit.append({"step": "payment_policy_denied", "reason": str(e)})
        state["task_state"] = "blocked"
        return state

    idempotency_key = f"invoice-{state['invoice_id']}"
    entries = [
        {"account_name": "vendor-expense", "direction": "debit", "amount": f"{amount:.2f}"},
        {"account_name": "operating-cash", "direction": "credit", "amount": f"{amount:.2f}"},
    ]

    # Dry-run before commit: a bad decision is visible before it's recorded.
    dry_run = ledger_client.dry_run_payment(idempotency_key, f"Payment to {vendor}", "payment-execution", entries)
    audit.append({"step": "ledger_dry_run", "result": dry_run})
    if not dry_run["valid"]:
        state["payment"] = {"status": "blocked", "reason": dry_run.get("error")}
        state["task_state"] = "blocked"
        return state

    audit.append({"step": "settlement_hold_start", "hold_seconds": SETTLEMENT_HOLD_SECONDS})
    time.sleep(SETTLEMENT_HOLD_SECONDS)

    status = kill_switch_status()
    frozen = (
        status.get("global_stop")
        or "payment-execution" in status.get("paused_agents", [])
        or state["invoice_id"] in status.get("halted_sessions", [])
        or "create-ledger-entry" in status.get("frozen_tools", [])
    )
    if frozen:
        state["payment"] = {"status": "blocked", "reason": "kill-switch tripped during settlement hold"}
        audit.append({"step": "settlement_hold_blocked", "kill_switch_status": status})
        state["task_state"] = "blocked"
        return state
    audit.append({"step": "settlement_hold_cleared"})

    # The dry-run above only validates balances - it doesn't check for a
    # duplicate idempotency_key, so a real duplicate (e.g. this exact
    # invoice_id already settled once before) is only caught here, by the
    # ledger's own real commit-time check. Surface that as a clean blocked
    # result instead of letting the raw HTTP error crash the request -
    # "already paid, refusing to pay twice" is an expected outcome, not a
    # bug.
    try:
        result = ledger_client.commit_payment(idempotency_key, f"Payment to {vendor}", "payment-execution", entries)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            state["payment"] = {"status": "blocked", "reason": f"duplicate payment: {e.response.json().get('detail', {}).get('message', 'idempotency_key already used')}"}
            audit.append({"step": "ledger_commit_duplicate", "reason": state["payment"]["reason"]})
            state["task_state"] = "blocked"
            return state
        raise
    audit.append({"step": "ledger_commit", "result": result})

    # Closes the vendor-history loop (Vendor Governance): only a genuinely
    # settled payment updates the real record risk-scoring's lookup reads
    # next time, so this vendor's next payment is correctly recognized as
    # known instead of being flagged first-seen forever. Fails open - the
    # payment already settled above; a bookkeeping-update failure here must
    # not turn a successful payment into an error response.
    try:
        vendor_record = ledger_client.record_vendor_payment(vendor, amount, idempotency_key)
        audit.append({"step": "vendor_history_recorded", "result": vendor_record})
    except Exception as e:
        audit.append({"step": "vendor_history_record_failed", "reason": str(e)})

    state["payment"] = {"status": "settled", "ledger_transaction_id": result["transaction_id"]}
    state["task_state"] = "settled"
    return state
