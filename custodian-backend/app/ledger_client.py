"""Credential brokering for Payment-Execution's calls to custodian-ledger:
the ledger API key is never held in the agent's own environment.

Infisical Agent Proxy's "Proxied Services" routing was evaluated first but
never forwarded requests correctly on this self-hosted version - a genuine
upstream gap, not a config mistake. This module gets the same property
directly via Infisical's Universal Auth instead:
payment-execution authenticates as its own machine identity and fetches
LEDGER_API_KEY fresh immediately before each call, never persisting it.
"""
import os
import time

import requests

INFISICAL_URL = os.environ.get("INFISICAL_URL", "http://infisical:8080")
LEDGER_URL = os.environ.get("LEDGER_URL", "http://custodian-ledger:8000")
PROJECT_ID = os.environ["INFISICAL_PROJECT_ID"]

_cached_token = None
_cached_token_expiry = 0


def _identity_access_token() -> str:
    global _cached_token, _cached_token_expiry
    if _cached_token and time.time() < _cached_token_expiry - 30:
        return _cached_token

    resp = requests.post(
        f"{INFISICAL_URL}/api/v1/auth/universal-auth/login",
        json={
            "clientId": os.environ["PAYMENT_EXECUTION_CLIENT_ID"],
            "clientSecret": os.environ["PAYMENT_EXECUTION_CLIENT_SECRET"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["accessToken"]
    _cached_token_expiry = time.time() + data["expiresIn"]
    return _cached_token


def _fetch_ledger_api_key() -> str:
    token = _identity_access_token()
    resp = requests.get(
        f"{INFISICAL_URL}/api/v3/secrets/raw/LEDGER_API_KEY",
        params={"workspaceId": PROJECT_ID, "environment": "dev", "secretPath": "/"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["secret"]["secretValue"]


def _ledger_request(method: str, path: str, json_body: dict | None = None) -> dict:
    api_key = _fetch_ledger_api_key()  # fetched fresh, never stored on this object
    resp = requests.request(
        method, f"{LEDGER_URL}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        json=json_body,
        timeout=30,
    )
    del api_key
    resp.raise_for_status()
    return resp.json()


def dry_run_payment(idempotency_key: str, description: str, requested_by: str, entries: list[dict]) -> dict:
    return _ledger_request("POST", "/transactions/dry-run", {
        "idempotency_key": idempotency_key, "description": description,
        "requested_by": requested_by, "entries": entries,
    })


def commit_payment(idempotency_key: str, description: str, requested_by: str, entries: list[dict]) -> dict:
    return _ledger_request("POST", "/transactions", {
        "idempotency_key": idempotency_key, "description": description,
        "requested_by": requested_by, "entries": entries,
    })


def record_vendor_payment(vendor_name: str, amount: float, idempotency_key: str) -> dict:
    """Called only after a real payment settles - closes the vendor-history
    loop so the same vendor's next payment is correctly recognized as known,
    and adds a real itemized historical_payments row so the next lookup can
    reason about this vendor's real amount pattern (see vendor_lookup.py for
    the read side). Uses the same Infisical-brokered LEDGER_API_KEY as
    commit_payment, not the narrower lookup key: this is a write, and only
    Payment-Execution's trust tier should cause it."""
    return _ledger_request("POST", "/vendors/record-payment", {
        "vendor_name": vendor_name, "amount": f"{amount:.2f}", "idempotency_key": idempotency_key,
    })
