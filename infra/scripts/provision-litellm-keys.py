#!/usr/bin/env python3
"""Creates one LiteLLM virtual key per agent, scoped to its allowed model
routes and capped with a real per-day budget. Pushes the keys into
Infisical. Re-runnable: skips a key alias that already exists.
"""
import json
import os
import sys
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
INFISICAL_URL = "http://localhost:8443"

# Mirrors each agent's capability manifest: allowed model routes + per-day budget.
AGENT_KEYS = {
    "agent-extraction": {
        "models": ["custodian-routine", "custodian-guardrail"],
        "max_budget": 2.00,
        "metadata": {"agent": "extraction", "trust_tier": "read-only"},
    },
    "agent-risk-scoring": {
        "models": ["custodian-routine", "custodian-reasoning", "custodian-guardrail"],
        "max_budget": 5.00,
        "metadata": {"agent": "risk-scoring", "trust_tier": "read-and-flag"},
    },
    "agent-approval": {
        "models": ["custodian-reasoning", "custodian-guardrail"],
        "max_budget": 3.00,
        "metadata": {"agent": "approval", "trust_tier": "read-and-flag"},
    },
    "agent-payment-execution": {
        "models": ["custodian-reasoning", "custodian-guardrail"],
        "max_budget": 3.00,
        "metadata": {"agent": "payment-execution", "trust_tier": "write-ledger"},
    },
}


def litellm_api(path, body, master_key):
    req = urllib.request.Request(
        f"{LITELLM_URL}{path}",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {master_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def infisical_api(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{INFISICAL_URL}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def main():
    env = {}
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v.strip('"')

    master_key = env["LITELLM_MASTER_KEY"]
    infisical_state = json.load(open(os.path.join(ROOT, ".infisical-bootstrap.json")))
    infisical_token = infisical_state["identity"]["credentials"]["token"]

    projects = infisical_api("GET", "/api/v1/projects", infisical_token)["projects"]
    project_id = next(p["id"] for p in projects if p["name"] == "custodian")

    created = {}
    for alias, cfg in AGENT_KEYS.items():
        try:
            result = litellm_api("/key/generate", {
                "key_alias": alias,
                "models": cfg["models"],
                "max_budget": cfg["max_budget"],
                "budget_duration": "24h",
                "metadata": cfg["metadata"],
            }, master_key)
        except urllib.error.HTTPError as e:
            print(f"{alias}: generate failed ({e.code}) - likely already exists, skipping", file=sys.stderr)
            continue
        key = result["key"]
        created[alias] = key
        secret_name = f"LITELLM_KEY_{alias.upper().replace('-', '_')}"
        try:
            infisical_api("POST", "/api/v3/secrets/raw/" + secret_name, infisical_token, {
                "workspaceId": project_id, "environment": "dev", "secretPath": "/", "secretValue": key,
            })
        except urllib.error.HTTPError:
            infisical_api("PATCH", "/api/v3/secrets/raw/" + secret_name, infisical_token, {
                "workspaceId": project_id, "environment": "dev", "secretPath": "/", "secretValue": key,
            })
        print(f"{alias}: key created, budget=${cfg['max_budget']}/24h, "
              f"models={cfg['models']}, stored in Infisical as {secret_name}")

    if created:
        # custodian-backend's own docker-compose.app.yml reads these as
        # ${LITELLM_KEY_AGENT_*} from .env directly (not from Infisical at
        # runtime) - Infisical alone isn't enough to actually run the stack.
        print()
        print("Add these to .env:")
        for alias, key in created.items():
            print(f"LITELLM_KEY_{alias.upper().replace('-', '_')}={key}")
    elif not created:
        print()
        print("No new keys created (all aliases already existed) - if .env's "
              "LITELLM_KEY_AGENT_* values are stale (e.g. after a fresh LiteLLM "
              "instance), delete the existing keys in LiteLLM and re-run this script.")

    return created


if __name__ == "__main__":
    main()
