import os

import requests

POLICY_SERVICE_URL = os.environ.get("POLICY_SERVICE_URL", "http://policy-service:8000")


class PolicyDenied(Exception):
    def __init__(self, decision: dict):
        self.decision = decision
        super().__init__(f"policy-service denied: {decision}")


def authorize(principal: dict, action: str, resource: dict, context: dict | None = None) -> dict:
    """Calls the real Cedar+Dogwood policy-service PDP. Default-deny: any
    network/parse failure is treated as Deny, never silently allowed."""
    try:
        resp = requests.post(
            f"{POLICY_SERVICE_URL}/authorize",
            json={"principal": principal, "action": action, "resource": resource, "context": context or {}},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException as e:
        result = {"decision": "Deny", "error": str(e)}

    if result["decision"] != "Allow":
        raise PolicyDenied(result)
    return result
