"""Enforces policies/temporal/05-vendor-approval-rate-limit.dw: no more
than 3 approvals to the same vendor within a rolling 24h window.

The .dw file (real Dogwood syntax) is the authoritative spec. This module
enforces its semantics directly against the real decision log rather than
shelling out to Dogwood's reference interpreter, which its own maintainers
document as built for policy exploration, not production authorization.
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg2

RATE_LIMIT_WINDOW_HOURS = 24
RATE_LIMIT_MAX_APPROVALS = 3


def _connect():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname="custodian_backend",
        user="custodian_backend",
        password=os.environ["PGPASS_CUSTODIAN_BACKEND"],
    )


def ensure_schema():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS policy_decisions (
                id BIGSERIAL PRIMARY KEY,
                principal_type TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                vendor TEXT,
                decision TEXT NOT NULL,
                denial_reason TEXT,
                decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    conn.commit()
    conn.close()


def record_decision(principal, action, resource, decision, denial_reason=None):
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO policy_decisions
                (principal_type, principal_id, action, resource_type, resource_id, vendor, decision, denial_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (principal["type"], principal["id"], action, resource["type"], resource["id"],
             resource.get("attrs", {}).get("vendor"), decision, denial_reason),
        )
    conn.commit()
    conn.close()


def check_vendor_rate_limit(vendor: str) -> tuple[bool, str | None]:
    """Returns (allowed, reason). Mirrors the .dw policy: forbid ApprovePayment
    if this vendor already has >= 3 Allow decisions in the last 24h."""
    if not vendor:
        return True, None

    conn = _connect()
    since = datetime.now(timezone.utc) - timedelta(hours=RATE_LIMIT_WINDOW_HOURS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM policy_decisions
            WHERE action = 'ApprovePayment' AND vendor = %s
              AND decision = 'Allow' AND decided_at >= %s
            """,
            (vendor, since),
        )
        count = cur.fetchone()[0]
    conn.close()

    if count >= RATE_LIMIT_MAX_APPROVALS:
        return False, (f"vendor {vendor!r} already has {count} approvals in the last "
                        f"{RATE_LIMIT_WINDOW_HOURS}h (limit {RATE_LIMIT_MAX_APPROVALS}) - escalation required")
    return True, None
