import os

import psycopg
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .control_plane_client import pause_thread, unpause_thread
from .nodes import approval, extraction, payment_execution, risk_scoring
from .schemas import InvoiceRunState


def human_review_node(state: InvoiceRunState) -> InvoiceRunState:
    """Pauses here (durable, checkpointed) until a human calls resume.
    Excluded from the missed-heartbeat watchdog while parked - a human's
    review time is unbounded."""
    pause_thread(state["invoice_id"], reason="awaiting human review")
    decision = interrupt({
        "invoice_id": state["invoice_id"],
        "task_state": state["task_state"],
        "extraction": state.get("extraction"),
        "risk": state.get("risk"),
        "approval": state.get("approval"),
    })
    unpause_thread(state["invoice_id"])
    state["human_decision"] = decision
    state["audit_trail"].append({"step": "human_decision", "decision": decision})
    return state


def route_after_extraction(state: InvoiceRunState) -> str:
    return "end" if state["task_state"] == "failed" else "risk_scoring"


def route_after_risk(state: InvoiceRunState) -> str:
    return "human_review" if state.get("requires_human") else "approval"


def route_after_approval(state: InvoiceRunState) -> str:
    if state["task_state"] == "rejected":
        return "end"
    return "human_review" if state.get("requires_human") else "payment_execution"


def route_after_human(state: InvoiceRunState) -> str:
    if state.get("human_decision") == "approve":
        state["task_state"] = "approved"
        return "payment_execution"
    state["task_state"] = "rejected"
    return "end"


def build_graph():
    graph = StateGraph(InvoiceRunState)
    graph.add_node("extraction", extraction.run)
    graph.add_node("risk_scoring", risk_scoring.run)
    graph.add_node("approval", approval.run)
    graph.add_node("human_review", human_review_node)
    graph.add_node("payment_execution", payment_execution.run)

    graph.set_entry_point("extraction")
    graph.add_conditional_edges("extraction", route_after_extraction, {"risk_scoring": "risk_scoring", "end": END})
    graph.add_conditional_edges("risk_scoring", route_after_risk, {"approval": "approval", "human_review": "human_review"})
    graph.add_conditional_edges("approval", route_after_approval,
                                 {"payment_execution": "payment_execution", "human_review": "human_review", "end": END})
    graph.add_conditional_edges("human_review", route_after_human, {"payment_execution": "payment_execution", "end": END})
    graph.add_edge("payment_execution", END)

    db_uri = (
        f"postgresql://custodian_backend:{os.environ['PGPASS_CUSTODIAN_BACKEND']}"
        f"@{os.environ.get('POSTGRES_HOST', 'postgres')}:{os.environ.get('POSTGRES_PORT', '5432')}/custodian_backend"
    )
    # Plain long-lived connection, not from_conn_string()'s context manager
    # (that closes on exit, wrong for a checkpointer outliving many requests).
    conn = psycopg.connect(db_uri, autocommit=True, row_factory=dict_row)
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()

    return graph.compile(checkpointer=checkpointer)
