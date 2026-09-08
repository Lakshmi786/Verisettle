"""policy-service: the single Policy Decision Point every tool call from
every agent goes through, default-deny (Agent Runtime Governance).
Wraps the real Cedar engine (structural/static rules) and a real temporal
rate-limit check (the Dogwood-specified vendor rate limit), enforced
against the real decision log rather than fabricated. Also consults
control-plane's kill-switch state on every call - a tripped kill-switch
overrides whatever Cedar/temporal would otherwise allow.
"""
import os

import requests
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel

from .cedar_engine import engine
from .temporal import check_vendor_rate_limit, ensure_schema, record_decision

app = FastAPI(title="custodian-policy-service", version="1.0.0")

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000")
AUDIT_LOG_URL = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")

POLICY_DECISIONS = Counter(
    "policy_decisions_total",
    "Authorization decisions made by the policy-service PDP",
    ["principal_id", "action", "decision"],
)


@app.on_event("startup")
def startup():
    ensure_schema()


class Entity(BaseModel):
    type: str
    id: str
    attrs: dict = {}


class AuthorizeRequest(BaseModel):
    principal: Entity
    action: str
    resource: Entity
    context: dict = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _kill_switch_denial(principal: dict, resource: dict) -> str | None:
    try:
        resp = requests.get(f"{CONTROL_PLANE_URL}/status", timeout=5)
        resp.raise_for_status()
        cp = resp.json()
    except requests.RequestException:
        return None  # control-plane being briefly unreachable must not itself deny everything

    if cp["global_stop"]:
        return "global kill-switch is tripped"
    if principal["id"] in cp["paused_agents"]:
        return f"agent {principal['id']!r} is paused by the kill-switch"
    tool_name = resource.get("attrs", {}).get("name")
    if tool_name and tool_name in cp["frozen_tools"]:
        return f"tool {tool_name!r} is frozen fleet-wide by the kill-switch"
    return None


def _audit(event_type: str, payload: dict):
    try:
        requests.post(f"{AUDIT_LOG_URL}/append", json={
            "event_type": event_type, "source_service": "policy-service", "payload": payload,
        }, timeout=5)
    except requests.RequestException:
        pass


@app.post("/authorize")
def authorize(req: AuthorizeRequest):
    principal = req.principal.model_dump()
    resource = req.resource.model_dump()

    cedar_result = engine.authorize(principal, req.action, resource, req.context)
    decision = cedar_result["decision"]
    reason = None

    if decision == "Allow" and req.action == "ApprovePayment":
        vendor = resource.get("attrs", {}).get("vendor")
        ok, temporal_reason = check_vendor_rate_limit(vendor)
        if not ok:
            decision = "Deny"
            reason = temporal_reason

    if decision == "Allow":
        kill_switch_reason = _kill_switch_denial(principal, resource)
        if kill_switch_reason:
            decision = "Deny"
            reason = kill_switch_reason

    record_decision(principal, req.action, resource, decision, reason)
    POLICY_DECISIONS.labels(principal_id=principal["id"], action=req.action, decision=decision).inc()
    _audit("policy_decision", {
        "principal": principal, "action": req.action, "resource": resource,
        "decision": decision, "reason": reason,
    })

    return {
        "decision": decision,
        "cedar_decision": cedar_result["decision"],
        "determining_policies": cedar_result["determining_policies"],
        "temporal_denial_reason": reason,
    }


@app.post("/reload")
def reload_policies():
    engine.reload()
    return {"status": "reloaded"}
