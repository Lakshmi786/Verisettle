#!/usr/bin/env python3
"""Catalogs VeriSettle's three real data sources in OpenMetadata with a
sensitivity tag, per Data Governance Ground Rule (INSTRUCTIONS.md 5.2):
invoice inbox, vendor master, payment ledger. Uses PUT (createOrUpdate)
throughout so this is safely re-runnable.
"""
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv():
    # Unlike the shell scripts (which `. ./.env` before calling into
    # Python), this one is invoked directly - it must not assume the
    # caller's shell already exported these.
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip('"'))


_load_dotenv()

OM_URL = os.environ.get("OPENMETADATA_URL", "http://localhost:8585")
SERVICE_NAME = "verisettle-postgres"

SENSITIVITY_TAGS = {
    "Public": "Non-sensitive reference data.",
    "Internal": "Internal operational data, not financial PII.",
    "RestrictedFinancial": (
        "Contains financial data and/or PII (vendor identity, bank/tax "
        "identifiers, payment amounts). Real Presidio redaction is required "
        "before this reaches an agent's context or gets persisted in any log."
    ),
}

TABLES = [
    {
        "database": "verisettle_backend",
        "schema": "public",
        "name": "invoices",
        "description": "Real SROIE/CORD invoice records with ground-truth annotations, used by the Extraction agent and the Model Governance eval gate.",
        "sensitivity": "RestrictedFinancial",
        "columns": [
            {"name": "id", "dataType": "BIGINT"},
            {"name": "source", "dataType": "VARCHAR", "dataLength": 50},
            {"name": "external_key", "dataType": "VARCHAR", "dataLength": 255},
            {"name": "split", "dataType": "VARCHAR", "dataLength": 20},
            {"name": "image_path", "dataType": "VARCHAR", "dataLength": 500},
            {"name": "ground_truth", "dataType": "JSON"},
            {"name": "raw_ground_truth", "dataType": "JSON"},
        ],
    },
    {
        "database": "verisettle_ledger",
        "schema": "public",
        "name": "vendors",
        "description": "Real vendor master data seeded from USAspending.gov award data - vendor master data source.",
        "sensitivity": "RestrictedFinancial",
        "columns": [
            {"name": "id", "dataType": "BIGINT"},
            {"name": "recipient_name", "dataType": "VARCHAR", "dataLength": 500},
            {"name": "recipient_uei", "dataType": "VARCHAR", "dataLength": 50},
            {"name": "total_awarded", "dataType": "NUMERIC"},
            {"name": "award_count", "dataType": "INT"},
        ],
    },
    {
        "database": "verisettle_ledger",
        "schema": "public",
        "name": "historical_payments",
        "description": "Real historical award/payment records seeded from USAspending.gov - payment ledger data source used for recurring-vs-one-off pattern detection.",
        "sensitivity": "RestrictedFinancial",
        "columns": [
            {"name": "id", "dataType": "BIGINT"},
            {"name": "vendor_id", "dataType": "BIGINT"},
            {"name": "award_id", "dataType": "VARCHAR", "dataLength": 255},
            {"name": "amount", "dataType": "NUMERIC"},
            {"name": "action_date", "dataType": "DATE"},
            {"name": "recurring", "dataType": "BOOLEAN"},
        ],
    },
]


def login():
    import base64
    pw = base64.b64encode(os.environ.get("OM_ADMIN_PASSWORD", "admin").encode()).decode()
    resp = requests.post(f"{OM_URL}/api/v1/users/login", json={
        "email": os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org"),
        "password": pw,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["accessToken"]


def put(session, path, body):
    resp = session.put(f"{OM_URL}{path}", json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    token = login()
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    put(session, "/api/v1/classifications", {
        "name": "DataSensitivity",
        "description": "VeriSettle data sensitivity classification: public, internal, restricted-financial",
    })
    for tag_name, desc in SENSITIVITY_TAGS.items():
        put(session, "/api/v1/tags", {
            "name": tag_name,
            "classification": "DataSensitivity",
            "description": desc,
        })
    print("classification + sensitivity tags ready")

    put(session, "/api/v1/services/databaseServices", {
        "name": SERVICE_NAME,
        "serviceType": "Postgres",
        "connection": {
            "config": {
                "type": "Postgres",
                "username": "verisettle_root",
                "authType": {"password": os.environ["POSTGRES_SUPERUSER_PASSWORD"]},
                "hostPort": "postgres:5432",
                "database": "verisettle_backend",
            }
        },
    })
    print(f"database service {SERVICE_NAME!r} ready")

    seen_databases = set()
    seen_schemas = set()
    for t in TABLES:
        if t["database"] not in seen_databases:
            put(session, "/api/v1/databases", {"name": t["database"], "service": SERVICE_NAME})
            seen_databases.add(t["database"])

        schema_key = (t["database"], t["schema"])
        if schema_key not in seen_schemas:
            put(session, "/api/v1/databaseSchemas", {
                "name": t["schema"],
                "database": f"{SERVICE_NAME}.{t['database']}",
            })
            seen_schemas.add(schema_key)

        put(session, "/api/v1/tables", {
            "name": t["name"],
            "databaseSchema": f"{SERVICE_NAME}.{t['database']}.{t['schema']}",
            "description": t["description"],
            "columns": t["columns"],
            "tags": [{
                "tagFQN": f"DataSensitivity.{t['sensitivity']}",
                "labelType": "Manual",
                "state": "Confirmed",
            }],
        })
        print(f"table {t['database']}.{t['schema']}.{t['name']} cataloged, "
              f"tagged {t['sensitivity']}")


if __name__ == "__main__":
    sys.exit(main())
