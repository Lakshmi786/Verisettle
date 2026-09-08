import glob
import json
import os

import cedarpy

POLICIES_DIR = os.environ.get("POLICIES_DIR", "/policies")


def _load_policy_text() -> str:
    text = ""
    for path in sorted(glob.glob(os.path.join(POLICIES_DIR, "*.cedar"))):
        text += open(path).read() + "\n"
    return text


def _load_schema() -> str:
    return open(os.path.join(POLICIES_DIR, "schema.cedarschema.json")).read()


class CedarEngine:
    def __init__(self):
        self.reload()

    def reload(self):
        self.policy_text = _load_policy_text()
        self.schema_text = _load_schema()
        self.policy_set = cedarpy.PolicySet.from_str(self.policy_text)

    def authorize(self, principal: dict, action: str, resource: dict, context: dict) -> dict:
        entity_uid = lambda e: f"Custodian::{e['type']}::\"{e['id']}\""

        # Cedar's "Long" is a 64-bit integer, not a decimal - round dollar
        # amounts for policy evaluation (thresholds are whole-dollar anyway).
        resource_attrs = dict(resource.get("attrs", {}))
        if "amount" in resource_attrs and resource_attrs["amount"] is not None:
            resource_attrs["amount"] = round(resource_attrs["amount"])

        entities = [
            {"uid": {"type": f"Custodian::{principal['type']}", "id": principal["id"]},
             "attrs": principal.get("attrs", {}), "parents": []},
            {"uid": {"type": f"Custodian::{resource['type']}", "id": resource["id"]},
             "attrs": resource_attrs, "parents": []},
        ]

        result = cedarpy.is_authorized(
            {
                "principal": entity_uid(principal),
                "action": f"Custodian::Action::\"{action}\"",
                "resource": entity_uid(resource),
                "context": context,
            },
            self.policy_set,
            cedarpy.Entities.from_json_str(json.dumps(entities)),
        )
        return {
            "decision": "Allow" if result.decision == cedarpy.Decision.Allow else "Deny",
            "determining_policies": list(result.diagnostics.reasons) if result.diagnostics else [],
            "errors": [str(e) for e in result.diagnostics.errors] if result.diagnostics else [],
        }


engine = CedarEngine()
