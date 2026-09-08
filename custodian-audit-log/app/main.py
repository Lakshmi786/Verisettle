"""The tamper-proof audit log: every event is a JSON entry embedding the
SHA-256 hash of the previous entry, written to MinIO with Object Lock in
compliance mode (genuine WORM). Postgres is a fast-queryable mirror; MinIO
is the source of truth.

Continuous integrity watchdog: /verify is a point-in-time check - on its
own, a tamper that's reverted before anyone happens to call it leaves no
trace. The background loop below closes that gap by calling the same real
check on a schedule and, the moment it finds a *new* break, writing that
finding as its own entry into this same tamper-proof chain. Object Lock
can't stop an entry once written from being altered - but nothing stops a
new entry being added, so "we detected tampering at this timestamp" becomes
just as permanent as anything else here, even if the tampered value itself
gets quietly put back afterward.
"""
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import boto3
import psycopg2
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="custodian-audit-log", version="1.0.0")

MINIO_BUCKET = "custodian-audit-log"
VERIFY_INTERVAL_SECONDS = int(os.environ.get("VERIFY_INTERVAL_SECONDS", "30"))

_logger = logging.getLogger("custodian-audit-log")

# In-memory only, same pattern as control-plane's own watchdog state
# (halted_sessions/paused_agents): tracks which entry IDs are *currently*
# known broken, so a persisting break isn't re-logged every single tick -
# only the transition into and out of a broken state gets its own entry.
_known_broken_ids: set[int] = set()
_watchdog_lock = threading.Lock()


def _pg_connect():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname="custodian_backend",
        user="custodian_backend",
        password=os.environ["PGPASS_CUSTODIAN_BACKEND"],
    )


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        region_name="us-east-1",
    )


@app.on_event("startup")
def ensure_schema():
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log_chain (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                source_service TEXT NOT NULL,
                payload JSONB NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL UNIQUE,
                minio_key TEXT NOT NULL,
                hashed_timestamp TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    conn.commit()
    conn.close()

    thread = threading.Thread(target=_verify_watchdog_loop, daemon=True)
    thread.start()


class AppendRequest(BaseModel):
    event_type: str
    source_service: str
    payload: dict


def _canonical(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)


def _append_internal(event_type: str, source_service: str, payload: dict) -> dict:
    """The real append logic, shared by the /append endpoint and the
    watchdog - a tamper-detection finding is written through the exact same
    path as any other event, not a separate/weaker one."""
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute("SELECT entry_hash FROM audit_log_chain ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        prev_hash = row[0] if row else "0" * 64

        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "event_type": event_type,
            "source_service": source_service,
            "payload": payload,
            "prev_hash": prev_hash,
            "timestamp": timestamp,
        }
        entry_hash = hashlib.sha256(_canonical(entry).encode()).hexdigest()
        entry["entry_hash"] = entry_hash
        minio_key = f"{timestamp}-{entry_hash[:16]}.json"

        # MinIO first: if this fails, we haven't committed a Postgres row
        # claiming a WORM copy exists when it doesn't.
        s3 = _s3_client()
        s3.put_object(
            Bucket=MINIO_BUCKET, Key=minio_key,
            Body=_canonical(entry).encode(), ContentType="application/json",
        )

        cur.execute(
            """
            INSERT INTO audit_log_chain
                (event_type, source_service, payload, prev_hash, entry_hash, minio_key, hashed_timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (event_type, source_service, json.dumps(payload), prev_hash, entry_hash, minio_key, timestamp),
        )
    conn.commit()
    conn.close()
    return {"entry_hash": entry_hash, "prev_hash": prev_hash, "minio_key": minio_key}


def _compute_breaks() -> list[dict]:
    """The real check, shared by the /verify endpoint and the watchdog."""
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, event_type, source_service, payload, prev_hash, entry_hash, minio_key, hashed_timestamp "
            "FROM audit_log_chain ORDER BY id ASC"
        )
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    s3 = _s3_client()
    expected_prev = "0" * 64
    breaks = []
    for r in rows:
        entry = {
            "event_type": r["event_type"],
            "source_service": r["source_service"],
            "payload": r["payload"],
            "prev_hash": r["prev_hash"],
            "timestamp": r["hashed_timestamp"],
        }
        recomputed = hashlib.sha256(_canonical(entry).encode()).hexdigest()
        if recomputed != r["entry_hash"]:
            breaks.append({"id": r["id"], "reason": "entry_hash does not match recomputed hash - payload or "
                                                      "prev_hash was modified after the fact"})
        elif r["prev_hash"] != expected_prev:
            breaks.append({"id": r["id"], "reason": "prev_hash does not match the previous entry's entry_hash "
                                                      "- an entry was inserted, deleted, or reordered"})
        else:
            entry["entry_hash"] = r["entry_hash"]
            try:
                obj = s3.get_object(Bucket=MINIO_BUCKET, Key=r["minio_key"])
                minio_body = obj["Body"].read()
                if minio_body != _canonical(entry).encode():
                    breaks.append({"id": r["id"], "reason": "MinIO object content no longer matches this entry - "
                                                              "a new version was written over the original"})
            except s3.exceptions.NoSuchKey:
                breaks.append({"id": r["id"], "reason": "MinIO object is gone (delete marker or removed) - the "
                                                          "current version no longer serves the original entry"})
            except Exception as e:
                code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
                if code in ("NoSuchKey", "404"):
                    breaks.append({"id": r["id"], "reason": "MinIO object is gone (delete marker or removed) - the "
                                                              "current version no longer serves the original entry"})
                else:
                    raise
        expected_prev = r["entry_hash"]

    return breaks


def _verify_watchdog_loop():
    while True:
        try:
            _watchdog_tick()
        except Exception as e:
            _logger.warning("verify watchdog tick error: %s", e)
        time.sleep(VERIFY_INTERVAL_SECONDS)


def _watchdog_tick():
    breaks = _compute_breaks()
    current_broken = {b["id"]: b["reason"] for b in breaks}

    with _watchdog_lock:
        newly_broken = {i: r for i, r in current_broken.items() if i not in _known_broken_ids}
        newly_recovered = _known_broken_ids - current_broken.keys()
        _known_broken_ids.clear()
        _known_broken_ids.update(current_broken.keys())

    # Writing these calls _append_internal, which is itself a new real
    # entry chained onto the log - it does not touch or need to touch the
    # broken entry itself, so it succeeds even while that entry is broken.
    for entry_id, reason in newly_broken.items():
        _logger.warning("audit log tamper detected: entry %s - %s", entry_id, reason)
        _append_internal("audit_log_tamper_detected", "audit-log-watchdog", {
            "entry_id": entry_id, "reason": reason,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        })
    for entry_id in newly_recovered:
        _append_internal("audit_log_tamper_resolved", "audit-log-watchdog", {
            "entry_id": entry_id,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        })


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/append")
def append_entry(req: AppendRequest):
    return _append_internal(req.event_type, req.source_service, req.payload)


@app.get("/entries")
def list_entries(limit: int = 50):
    conn = _pg_connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, event_type, source_service, payload, prev_hash, entry_hash, created_at "
            "FROM audit_log_chain ORDER BY id DESC LIMIT %s", (limit,),
        )
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows


@app.get("/verify")
def verify_chain():
    """Recomputes every entry_hash, confirms prev_hash linkage, and
    cross-checks each entry's MinIO copy still reads back byte-identical.
    Object Lock stops a locked version from being purged, but a new
    version or delete marker can still shadow it - a root credential
    bypasses bucket policy the same way AWS root does. Postgres-only
    verification would miss that; this endpoint doesn't.

    This is still only a point-in-time check when called directly - see
    the module docstring and _verify_watchdog_loop for the continuous
    version that makes even a reverted tamper leave a permanent trace."""
    breaks = _compute_breaks()
    entries_checked = _pg_connect()
    with entries_checked.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_log_chain")
        count = cur.fetchone()[0]
    entries_checked.close()
    return {"valid": len(breaks) == 0, "entries_checked": count, "breaks": breaks}
