import os
import uuid

import psycopg
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from pydantic import BaseModel

from .control_plane_client import TERMINAL_TASK_STATES, SessionHalted, ensure_not_halted, pause_thread
from .graph import build_graph
from .identity import current_identity, fetch_identity
from .tracing import setup_tracing

SANDBOX_RUNNER_URL = os.environ.get("SANDBOX_RUNNER_URL", "http://sandbox-runner:8000")
UPLOAD_DIR = "/data/invoices/uploads"

# No valid identity, no action (Identity Governance, INSTRUCTIONS.md 5.1):
# module-level, not inside a startup hook, so the process never reaches a
# state where it could serve a request without first proving who it is - a
# failure here crashes the container instead of coming up falsely healthy.
fetch_identity()

app = FastAPI(title="verisettle-backend", version="1.0.0")
setup_tracing(app)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@app.get("/health")
def health():
    return {"status": "ok", "spiffe_id": current_identity()}


class StartRunRequest(BaseModel):
    invoice_id: str
    ocr_text: str
    source: str = "manual"


@app.post("/runs")
def start_run(req: StartRunRequest):
    return _run_pipeline(invoice_id=req.invoice_id, ocr_text=req.ocr_text, source=req.source)


def _run_pipeline(invoice_id: str, ocr_text: str, source: str):
    thread_id = invoice_id
    try:
        ensure_not_halted(thread_id)
    except SessionHalted as e:
        raise HTTPException(status_code=423, detail=str(e))

    graph = get_graph()
    initial_state = {
        # vendor_first_seen/vendor_payment_count are deliberately not
        # accepted here (Vendor Governance): risk_scoring.py looks these up
        # for real from the ledger's vendor history instead of trusting a
        # client-supplied, self-reportable fraud-relevant flag.
        "invoice_id": invoice_id,
        "ocr_text": ocr_text,
        "source": source,
        "audit_trail": [],
        "task_state": "submitted",
    }
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(initial_state, config=config)
    _pause_if_terminal(thread_id, result)
    return {"thread_id": thread_id, "state": result}


@app.post("/runs/from-image")
async def start_run_from_image(
    file: UploadFile = File(...),
    invoice_id: str = Form(...),
):
    """Real path for a user-supplied invoice image: write it where
    sandbox-runner can see it, run real OCR inside the Landlock-sandboxed
    container, then feed the extracted text into the same pipeline /runs
    uses. Two real hops (this service -> sandbox-runner -> a throwaway
    sandboxed container), not a shortcut around either the OCR sandbox or
    the governed graph."""
    try:
        ensure_not_halted(invoice_id)
    except SessionHalted as e:
        raise HTTPException(status_code=423, detail=str(e))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{invoice_id}-{uuid.uuid4().hex[:8]}-{os.path.basename(file.filename or 'upload')}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(await file.read())

    try:
        resp = requests.post(
            f"{SANDBOX_RUNNER_URL}/ocr",
            json={"image_path": dest_path, "invoice_id": invoice_id},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        detail = e.response.text if getattr(e, "response", None) is not None else str(e)
        raise HTTPException(status_code=502, detail=f"sandboxed OCR failed: {detail}")

    ocr_text = resp.json()["ocr_text"]
    return _run_pipeline(invoice_id=invoice_id, ocr_text=ocr_text, source="image-upload")


def _pause_if_terminal(thread_id: str, result: dict):
    """A finished run never heartbeats again - without this the watchdog
    eventually treats "done" as "agent went silent" and halts it."""
    if result.get("task_state") in TERMINAL_TASK_STATES:
        pause_thread(thread_id, reason=f"run reached terminal state {result.get('task_state')!r}")


@app.get("/runs/{thread_id}")
def get_run(thread_id: str):
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no such run")
    return {"thread_id": thread_id, "values": snapshot.values, "next": snapshot.next}


@app.get("/runs")
def list_runs(limit: int = 50):
    """Thread listing straight from the checkpointer's own Postgres table
    (LangGraph has no generic list-threads call); each thread's state is
    read back through the same get_state() path /runs/{id} uses."""
    db_uri = (
        f"postgresql://verisettle_backend:{os.environ['PGPASS_VERISETTLE_BACKEND']}"
        f"@{os.environ.get('POSTGRES_HOST', 'postgres')}:{os.environ.get('POSTGRES_PORT', '5432')}/verisettle_backend"
    )
    with psycopg.connect(db_uri) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT thread_id, max(checkpoint_id) FROM checkpoints GROUP BY thread_id "
            "ORDER BY max(checkpoint_id) DESC LIMIT %s",
            (limit,),
        )
        thread_ids = [row[0] for row in cur.fetchall()]

    graph = get_graph()
    runs = []
    for thread_id in thread_ids:
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        if snapshot is None:
            continue
        runs.append({
            "thread_id": thread_id,
            "task_state": snapshot.values.get("task_state"),
            "invoice_id": snapshot.values.get("invoice_id"),
            "extraction": snapshot.values.get("extraction"),
            "risk": snapshot.values.get("risk"),
            "requires_human": snapshot.values.get("requires_human", False),
            "next": list(snapshot.next),
        })
    return {"runs": runs}


class ResumeRequest(BaseModel):
    decision: str  # "approve" or "reject"
    approver: str


@app.post("/runs/{thread_id}/resume")
def resume_run(thread_id: str, req: ResumeRequest):
    try:
        ensure_not_halted(thread_id)
    except SessionHalted as e:
        raise HTTPException(status_code=423, detail=str(e))

    from langgraph.types import Command
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(Command(resume=req.decision), config=config)
    _pause_if_terminal(thread_id, result)
    return {"thread_id": thread_id, "state": result}


@app.websocket("/runs/{thread_id}/stream")
async def stream_run(websocket: WebSocket, thread_id: str):
    """Live, step-by-step view of a run in progress."""
    await websocket.accept()
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = graph.get_state(config)
        if snapshot is not None:
            await websocket.send_json({"values": _jsonable(snapshot.values), "next": list(snapshot.next)})
    finally:
        await websocket.close()


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj
