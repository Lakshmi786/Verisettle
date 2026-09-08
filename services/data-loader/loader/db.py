import os
import psycopg2
from psycopg2.extras import Json


def _connect(dbname: str, user: str, password: str):
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=dbname,
        user=user,
        password=password,
    )


def backend_conn():
    return _connect("verisettle_backend", "verisettle_backend", os.environ["PGPASS_VERISETTLE_BACKEND"])


def ledger_conn():
    return _connect("verisettle_ledger", "verisettle_ledger", os.environ["PGPASS_VERISETTLE_LEDGER"])


INVOICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    external_key TEXT NOT NULL,
    split TEXT NOT NULL,
    image_path TEXT NOT NULL,
    ground_truth JSONB NOT NULL,
    raw_ground_truth JSONB NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'restricted-financial',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source, external_key)
);
"""

VENDORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    id BIGSERIAL PRIMARY KEY,
    recipient_name TEXT NOT NULL UNIQUE,
    recipient_uei TEXT,
    first_seen DATE,
    total_awarded NUMERIC NOT NULL DEFAULT 0,
    award_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

HISTORICAL_PAYMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_payments (
    id BIGSERIAL PRIMARY KEY,
    vendor_id BIGINT NOT NULL REFERENCES vendors(id),
    award_id TEXT NOT NULL UNIQUE,
    amount NUMERIC NOT NULL,
    action_date DATE,
    awarding_agency TEXT,
    recurring BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_backend_schema(conn):
    with conn.cursor() as cur:
        cur.execute(INVOICES_SCHEMA)
    conn.commit()


def ensure_ledger_schema(conn):
    with conn.cursor() as cur:
        cur.execute(VENDORS_SCHEMA)
        cur.execute(HISTORICAL_PAYMENTS_SCHEMA)
    conn.commit()


def upsert_invoice(conn, source, external_key, split, image_path, ground_truth, raw_ground_truth):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO invoices (source, external_key, split, image_path, ground_truth, raw_ground_truth)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, external_key) DO UPDATE SET
                split = EXCLUDED.split,
                image_path = EXCLUDED.image_path,
                ground_truth = EXCLUDED.ground_truth,
                raw_ground_truth = EXCLUDED.raw_ground_truth
            """,
            (source, external_key, split, image_path, Json(ground_truth), Json(raw_ground_truth)),
        )
    conn.commit()


def upsert_vendor(conn, recipient_name, recipient_uei, first_seen, award_amount):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO vendors (recipient_name, recipient_uei, first_seen, total_awarded, award_count)
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (recipient_name) DO UPDATE SET
                recipient_uei = COALESCE(vendors.recipient_uei, EXCLUDED.recipient_uei),
                first_seen = LEAST(vendors.first_seen, EXCLUDED.first_seen),
                total_awarded = vendors.total_awarded + EXCLUDED.total_awarded,
                award_count = vendors.award_count + 1
            RETURNING id
            """,
            (recipient_name, recipient_uei, first_seen, award_amount),
        )
        vendor_id = cur.fetchone()[0]
    conn.commit()
    return vendor_id


def upsert_historical_payment(conn, vendor_id, award_id, amount, action_date, awarding_agency, recurring):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO historical_payments (vendor_id, award_id, amount, action_date, awarding_agency, recurring)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (award_id) DO UPDATE SET
                amount = EXCLUDED.amount,
                action_date = EXCLUDED.action_date,
                awarding_agency = EXCLUDED.awarding_agency,
                recurring = EXCLUDED.recurring
            """,
            (vendor_id, award_id, amount, action_date, awarding_agency, recurring),
        )
    conn.commit()
