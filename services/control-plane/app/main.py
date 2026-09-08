"""The kill switch, independent of the agent runtime so a malfunctioning
agent can never decide whether it gets stopped. Graduated scopes: pause an
agent, halt a session, freeze a tool fleet-wide, or full stop.
"""
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import psycopg2
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="verisettle-control-plane", version="1.0.0")

AUDIT_LOG_URL = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "45"))
DENIAL_WINDOW_MINUTES = int(os.environ.get("DENIAL_WINDOW_MINUTES", "5"))
DENIAL_THRESHOLD = int(os.environ.get("DENIAL_THRESHOLD", "3"))
CANARY_VENDOR = os.environ.get("CANARY_VENDOR", "CANARY-DO-NOT-USE")
WATCHDOG_INTERVAL_SECONDS = int(os.environ.get("WATCHDOG_INTERVAL_SECONDS", "10"))

# In-memory kill-switch state - control-plane is the sole source of truth
# for it; policy-service consults /status on every authorize call.
state_lock = threading.Lock()
state = {
    "global_stop": False,
    "paused_agents": set(),
    "halted_sessions": set(),
    "frozen_tools": set(),
}
_last_canary_check_id = 0
_seen_denial_trip_keys = set()


def _pg_connect():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname="verisettle_backend",
        user="verisettle_backend",
        password=os.environ["PGPASS_VERISETTLE_BACKEND"],
    )


def _audit(event_type: str, payload: dict):
    try:
        requests.post(f"{AUDIT_LOG_URL}/append", json={
            "event_type": event_type, "source_service": "control-plane", "payload": payload,
        }, timeout=10)
    except requests.RequestException:
        pass  # the audit log being unreachable must never block a trip from taking effect


@app.on_event("startup")
def ensure_schema():
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS heartbeats (
                agent TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (agent, thread_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS paused_threads (
                thread_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                paused_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    conn.commit()

    # Seed the watermark from the real table so a restart doesn't replay
    # old canary touches as new ones. policy_decisions is owned by
    # policy-service, not this service, and nothing enforces it starting
    # first - on a genuinely fresh database the table may not exist yet,
    # which correctly means there's no history to worry about replaying.
    global _last_canary_check_id
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT COALESCE(max(id), 0) FROM policy_decisions")
            _last_canary_check_id = cur.fetchone()[0]
        except psycopg2.errors.UndefinedTable:
            conn.rollback()
            _last_canary_check_id = 0
    conn.close()

    thread = threading.Thread(target=_watchdog_loop, daemon=True)
    thread.start()


def _watchdog_loop():
    while True:
        try:
            _check_stale_heartbeats()
            _check_repeated_denials()
            _check_canary_vendor()
        except Exception as e:
            print(f"watchdog tick error: {e}")
        time.sleep(WATCHDOG_INTERVAL_SECONDS)


def _check_stale_heartbeats():
    """Flags a thread only when its most recent heartbeat, from ANY agent,
    is stale - not when any single agent's row is stale. Each of the 4
    agents heartbeats once as it starts its step, then moves on; extraction
    heartbeats once near the very start of a run and never again once its
    step is done. Checking each (agent, thread_id) row independently (the
    original bug here) meant extraction's one early heartbeat would always
    eventually cross the staleness threshold on its own, even while
    risk-scoring/approval/payment-execution were actively and correctly
    working the same thread afterward - confirmed for real: a genuine,
    still-progressing run got auto-halted mid-settlement-hold this way,
    18 real seconds after payment-execution's own fresh heartbeat, because
    extraction's heartbeat from earlier in the same run had aged past 45s."""
    conn = _pg_connect()
    with conn.cursor() as cur:
        # Threads paused for human review are excluded - a human's review
        # time is unbounded, not a missed heartbeat.
        cur.execute(
            "SELECT thread_id, max(last_seen) AS last_seen FROM heartbeats h "
            "WHERE NOT EXISTS (SELECT 1 FROM paused_threads p WHERE p.thread_id = h.thread_id) "
            "GROUP BY thread_id "
            "HAVING max(last_seen) < now() - interval '%s seconds'",
            (HEARTBEAT_STALE_SECONDS,),
        )
        stale = cur.fetchall()
    conn.close()
    for thread_id, last_seen in stale:
        if thread_id in state["halted_sessions"]:
            continue
        with state_lock:
            state["halted_sessions"].add(thread_id)
        _audit("kill_switch_trip", {
            "scope": "session", "target": thread_id, "automatic": True,
            "reason": f"no heartbeat from any agent since {last_seen}",
        })


def _check_repeated_denials():
    conn = _pg_connect()
    since = datetime.now(timezone.utc) - timedelta(minutes=DENIAL_WINDOW_MINUTES)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT principal_id, count(*) FROM policy_decisions "
            "WHERE decision = 'Deny' AND decided_at >= %s GROUP BY principal_id HAVING count(*) >= %s",
            (since, DENIAL_THRESHOLD),
        )
        offenders = cur.fetchall()
    conn.close()
    for principal_id, count in offenders:
        key = f"{principal_id}:{since.isoformat()}"
        if principal_id in state["paused_agents"] or key in _seen_denial_trip_keys:
            continue
        _seen_denial_trip_keys.add(key)
        with state_lock:
            state["paused_agents"].add(principal_id)
        _audit("kill_switch_trip", {
            "scope": "agent", "target": principal_id, "automatic": True,
            "reason": f"{count} policy denials in the last {DENIAL_WINDOW_MINUTES}m (threshold {DENIAL_THRESHOLD})",
        })


def _check_canary_vendor():
    global _last_canary_check_id
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, principal_id, vendor FROM policy_decisions "
            "WHERE vendor = %s AND id > %s ORDER BY id ASC",
            (CANARY_VENDOR, _last_canary_check_id),
        )
        hits = cur.fetchall()
    conn.close()
    for entry_id, principal_id, vendor in hits:
        _last_canary_check_id = max(_last_canary_check_id, entry_id)
        with state_lock:
            state["global_stop"] = True
        _audit("kill_switch_trip", {
            "scope": "global", "target": "*", "automatic": True,
            "reason": f"canary vendor {vendor!r} was touched by {principal_id!r} - no legitimate flow ever does this",
        })


class TripRequest(BaseModel):
    scope: str  # "agent" | "session" | "tool" | "global"
    target: str
    reason: str
    triggered_by: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    with state_lock:
        return {
            "global_stop": state["global_stop"],
            "paused_agents": sorted(state["paused_agents"]),
            "halted_sessions": sorted(state["halted_sessions"]),
            "frozen_tools": sorted(state["frozen_tools"]),
        }


@app.post("/kill-switch/trip")
def trip(req: TripRequest):
    with state_lock:
        if req.scope == "global":
            state["global_stop"] = True
        elif req.scope == "agent":
            state["paused_agents"].add(req.target)
        elif req.scope == "session":
            state["halted_sessions"].add(req.target)
        elif req.scope == "tool":
            state["frozen_tools"].add(req.target)
        else:
            return {"error": f"unknown scope {req.scope!r}"}
    _audit("kill_switch_trip", {
        "scope": req.scope, "target": req.target, "automatic": False,
        "reason": req.reason, "triggered_by": req.triggered_by,
    })
    return {"tripped": True, "scope": req.scope, "target": req.target}


class ResetRequest(BaseModel):
    scope: str
    target: str
    reset_by: str


@app.post("/kill-switch/reset")
def reset(req: ResetRequest):
    with state_lock:
        if req.scope == "global":
            state["global_stop"] = False
        elif req.scope == "agent":
            state["paused_agents"].discard(req.target)
        elif req.scope == "session":
            state["halted_sessions"].discard(req.target)
        elif req.scope == "tool":
            state["frozen_tools"].discard(req.target)
    _audit("kill_switch_reset", {"scope": req.scope, "target": req.target, "reset_by": req.reset_by})
    return {"reset": True, "scope": req.scope, "target": req.target}


class PauseThreadRequest(BaseModel):
    reason: str


@app.post("/threads/{thread_id}/pause")
def pause_thread(thread_id: str, req: PauseThreadRequest):
    """Excludes a thread from the missed-heartbeat watchdog while it's
    genuinely waiting on a human, not an agent - call when a run enters
    the human-review interrupt."""
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO paused_threads (thread_id, reason) VALUES (%s, %s) "
            "ON CONFLICT (thread_id) DO UPDATE SET reason = EXCLUDED.reason, paused_at = now()",
            (thread_id, req.reason),
        )
    conn.commit()
    conn.close()
    return {"paused": True, "thread_id": thread_id}


@app.post("/threads/{thread_id}/unpause")
def unpause_thread(thread_id: str):
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM paused_threads WHERE thread_id = %s", (thread_id,))
    conn.commit()
    conn.close()
    return {"paused": False, "thread_id": thread_id}


class HeartbeatRequest(BaseModel):
    agent: str
    thread_id: str


@app.post("/heartbeat")
def heartbeat(req: HeartbeatRequest):
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO heartbeats (agent, thread_id, last_seen) VALUES (%s, %s, now())
            ON CONFLICT (agent, thread_id) DO UPDATE SET last_seen = now()
            """,
            (req.agent, req.thread_id),
        )
    conn.commit()
    conn.close()
    return {"ok": True}
