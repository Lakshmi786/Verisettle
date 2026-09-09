#!/usr/bin/env python3
"""Provisions the 'verisettle' Infisical project, one Universal Auth machine
identity per VeriSettle service, and pushes the real bootstrap secrets
(provider API keys, per-service Postgres passwords) into it - all via the
REST API using the instance-admin token from .infisical-bootstrap.json.

Re-runnable: skips creation if the project/identity/secret already exists.
"""
import json
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_FILE = os.path.join(ROOT, ".infisical-bootstrap.json")
DOMAIN = "http://localhost:8443"

SERVICES = [
    "litellm", "mlflow", "langfuse",
    "verisettle-backend", "verisettle-ledger", "verisettle-data-loader",
    "verisettle-payment-execution",
]


def load_env():
    env = {}
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v.strip('"')
    return env


def api(method, path, token, body=None):
    url = f"{DOMAIN}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"{method} {path} -> {e.code}: {body}", file=sys.stderr)
        raise


def main():
    if not os.path.exists(STATE_FILE):
        print(f"{STATE_FILE} not found - run infra/scripts/bootstrap-infisical.sh first", file=sys.stderr)
        sys.exit(1)

    state = json.load(open(STATE_FILE))
    admin_token = state["identity"]["credentials"]["token"]
    org_id = state["organization"]["id"]
    env = load_env()

    projects = api("GET", "/api/v1/projects", admin_token)
    project = next((p for p in projects.get("projects", []) if p["name"] == "verisettle"), None)
    if project is None:
        project = api("POST", "/api/v1/projects", admin_token, {"projectName": "verisettle", "type": "secret-manager"})["project"]
        print(f"created project verisettle ({project['id']})")
    else:
        print(f"project verisettle already exists ({project['id']})")
    project_id = project["id"]

    memberships = api("GET", f"/api/v1/projects/{project_id}/identity-memberships", admin_token)
    existing_names = {m["identity"]["name"] for m in memberships.get("identityMemberships", [])}

    created = []
    for svc in SERVICES:
        name = f"verisettle-{svc}" if not svc.startswith("verisettle-") else svc
        if name in existing_names:
            print(f"identity {name} already exists in project, skipping")
            continue
        identity = api("POST", "/api/v1/identities", admin_token, {
            "name": name,
            "organizationId": org_id,
            "role": "no-access",
        })["identity"]
        ua = api("POST", f"/api/v1/auth/universal-auth/identities/{identity['id']}", admin_token, {
            "accessTokenTTL": 7200,
            "accessTokenMaxTTL": 86400,
            "accessTokenNumUsesLimit": 0,
        })
        # Universal Auth's login clientId is NOT the identity's own id -
        # using identity['id'] here silently 401s at login.
        ua_client_id = ua["identityUniversalAuth"]["clientId"]
        api("POST", f"/api/v1/projects/{project_id}/identity-memberships/{identity['id']}", admin_token, {
            "roles": [{"role": "admin"}],
        })
        client_secret = api("POST", f"/api/v1/auth/universal-auth/identities/{identity['id']}/client-secrets", admin_token, {})
        created.append({"service": svc, "identityId": identity["id"], "clientId": ua_client_id, "clientSecret": client_secret["clientSecret"]})
        print(f"created machine identity {name} ({identity['id']})")

    if created:
        out_path = os.path.join(ROOT, ".infisical-identities.json")
        with open(out_path, "w") as f:
            json.dump(created, f, indent=2)
        print(f"wrote {len(created)} new identity credentials to {out_path} (gitignored)")

    # verisettle-payment-execution is the one identity actually consumed by
    # name at runtime (services/backend/app/ledger_client.py) - print its
    # real values as ready-to-paste .env lines instead of leaving them
    # buried in the JSON dump above.
    payment_exec = next((c for c in created if c["service"] == "verisettle-payment-execution"), None)
    if payment_exec is None:
        m = next((m for m in memberships.get("identityMemberships", [])
                   if m["identity"]["name"] == "verisettle-payment-execution"), None)
        if m is not None:
            print("verisettle-payment-execution identity already existed - its clientSecret was only "
                  "shown once, at creation time. If .env's PAYMENT_EXECUTION_CLIENT_ID/SECRET are "
                  "missing or stale, delete this identity in Infisical and re-run this script.")
    print()
    print("Add these to .env:")
    print(f"INFISICAL_PROJECT_ID={project_id}")
    if payment_exec is not None:
        print(f"PAYMENT_EXECUTION_CLIENT_ID={payment_exec['clientId']}")
        print(f"PAYMENT_EXECUTION_CLIENT_SECRET={payment_exec['clientSecret']}")

    secrets_to_set = {}
    if env["OPENAI_API_KEY"] != "sk-replace-me":
        secrets_to_set["OPENAI_API_KEY"] = env["OPENAI_API_KEY"]
    else:
        print("OPENAI_API_KEY still a placeholder in .env - skipping, re-run this script after filling it in")
    if env["GROQ_API_KEY"] != "gsk-replace-me":
        secrets_to_set["GROQ_API_KEY"] = env["GROQ_API_KEY"]
    else:
        print("GROQ_API_KEY still a placeholder in .env - skipping, re-run this script after filling it in")
    secrets_to_set.update({
        "PGPASS_LITELLM": env["PGPASS_LITELLM"],
        "PGPASS_MLFLOW": env["PGPASS_MLFLOW"],
        "PGPASS_LANGFUSE": env["PGPASS_LANGFUSE"],
        "PGPASS_VERISETTLE_LEDGER": env["PGPASS_VERISETTLE_LEDGER"],
        "PGPASS_VERISETTLE_BACKEND": env["PGPASS_VERISETTLE_BACKEND"],
        # The one secret services/backend/app/ledger_client.py actually
        # fetches from Infisical at runtime (Payment-Execution's Universal
        # Auth identity reads this fresh before every ledger call).
        "LEDGER_API_KEY": env["LEDGER_API_KEY"],
    })
    for key, value in secrets_to_set.items():
        try:
            api("POST", f"/api/v3/secrets/raw/{key}", admin_token, {
                "workspaceId": project_id,
                "environment": "dev",
                "secretPath": "/",
                "secretValue": value,
            })
            print(f"set secret {key}")
        except urllib.error.HTTPError:
            api("PATCH", f"/api/v3/secrets/raw/{key}", admin_token, {
                "workspaceId": project_id,
                "environment": "dev",
                "secretPath": "/",
                "secretValue": value,
            })
            print(f"updated secret {key}")


if __name__ == "__main__":
    main()
