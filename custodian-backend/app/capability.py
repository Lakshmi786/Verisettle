import json
import os

_MANIFEST_DIR = os.path.join(os.path.dirname(__file__), "capability-manifests")
_manifests: dict[str, dict] = {}

for fname in os.listdir(_MANIFEST_DIR):
    if fname.endswith(".json"):
        with open(os.path.join(_MANIFEST_DIR, fname)) as f:
            m = json.load(f)
            _manifests[m["agent"]] = m


class CapabilityDenied(Exception):
    pass


def require_capability(agent: str, action: str):
    """The independent second check alongside the Cedar policy (Ground Rule
    4.5): a single Cedar misconfiguration must never alone grant a
    lower-tier agent write access. Checked in code, not just policy."""
    manifest = _manifests.get(agent)
    if manifest is None:
        raise CapabilityDenied(f"no capability manifest for agent {agent!r}")
    if action not in manifest.get("allowedActions", []):
        raise CapabilityDenied(
            f"agent {agent!r} (trustTier={manifest['trustTier']}) is not permitted action {action!r} "
            f"by its capability manifest (allowed: {manifest['allowedActions']})"
        )
