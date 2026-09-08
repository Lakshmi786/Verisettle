"""Identity Governance (INSTRUCTIONS.md 5.1): this process fetches its own
real SPIFFE identity from the SPIRE Workload API at startup and refuses to
serve any request without one - "no valid identity, no action," checked
before anything else runs. Fails closed, not open: unlike the MLflow prompt
fallback (a quality concern), a missing identity here is a security boundary,
so there is no fallback - a startup crash is the correct, visible failure
mode, not a silent downgrade.

This is the real identity of the custodian-backend *process*, not of an
individual agent - see register-spire-entries.sh for why the 4 per-agent
SPIRE entries can never actually be issued to it (SPIRE attests one identity
per workload; all 4 agents run as function calls inside this one process).
"""
from spiffe.workloadapi.workload_api_client import WorkloadApiClient

_identity = {"spiffe_id": None}


def fetch_identity() -> str:
    """Blocks until the Workload API hands back a real X.509 SVID, or raises.
    Called once at startup (see main.py) - a container that can't prove its
    own identity must not come up healthy."""
    with WorkloadApiClient() as client:
        svid = client.fetch_x509_svid(timeout=10)
    _identity["spiffe_id"] = str(svid.spiffe_id)
    return _identity["spiffe_id"]


def current_identity() -> str | None:
    """The SPIFFE ID fetched at startup, or None if fetch_identity() hasn't
    run yet - exposed for /health so the real identity is externally
    verifiable, not just trusted on faith."""
    return _identity["spiffe_id"]
