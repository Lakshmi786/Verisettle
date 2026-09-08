#!/usr/bin/env python3
"""Manual validation, run by hand per the README (not wired into CI - see
INSTRUCTIONS.md 5.4) against every .cedar file: rejects
anything that fails real Cedar schema validation, anything with a fully
unconstrained permit (no principal/action/resource restriction and no
when/unless clause at all), and confirms the shipped policy set produces
the expected allow/deny outcome for a small real authorization test matrix.

Usage: python validate-cedar-policies.py [policies_dir]
Exit 0 = accepted, exit 1 = rejected (real failure, not a rubber stamp).
"""
import glob
import json
import os
import re
import sys

import cedarpy

POLICIES_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "policies")
SCHEMA_PATH = os.path.join(POLICIES_DIR, "schema.cedarschema.json")

# A permit/forbid with no scope constraint (principal/action/resource all
# wildcarded) and no when/unless body - i.e. the exact shape of "everyone
# can do everything" or "everyone is blocked from everything unconditionally".
UNCONSTRAINED_RE = re.compile(
    r"(permit|forbid)\s*\(\s*principal\s*,\s*action\s*,\s*resource\s*\)\s*;",
    re.MULTILINE,
)


def load_cedar_files():
    return sorted(glob.glob(os.path.join(POLICIES_DIR, "*.cedar")))


def check_unconstrained(path, text):
    errors = []
    for m in UNCONSTRAINED_RE.finditer(text):
        line = text[:m.start()].count("\n") + 1
        errors.append(f"{path}:{line}: unconstrained {m.group(1)} - no principal/action/resource "
                       f"restriction and no when/unless clause. Overly permissive, rejected.")
    return errors


def run_authorization_matrix(policy_text, schema_json):
    """Real authorization calls proving the shipped policy set produces the
    outcomes the docs claim, not just that it parses."""
    entities = cedarpy.Entities.from_json_str(json.dumps([
        {"uid": {"type": "VeriSettle::Agent", "id": "payment-execution"},
         "attrs": {"trustTier": "write-ledger"}, "parents": []},
        {"uid": {"type": "VeriSettle::Agent", "id": "extraction"},
         "attrs": {"trustTier": "read-only"}, "parents": []},
        {"uid": {"type": "VeriSettle::Agent", "id": "risk-scoring"},
         "attrs": {"trustTier": "read-and-flag"}, "parents": []},
        {"uid": {"type": "VeriSettle::User", "id": "controller.demo"},
         "attrs": {"approvalAuthorityTier": 2}, "parents": []},
        {"uid": {"type": "VeriSettle::Payment", "id": "routine-1"},
         "attrs": {"amount": 500, "vendorFirstSeen": False, "vendor": "Acme", "approvalCount": 0}, "parents": []},
        {"uid": {"type": "VeriSettle::Payment", "id": "large-1"},
         "attrs": {"amount": 50000, "vendorFirstSeen": False, "vendor": "Acme", "approvalCount": 0}, "parents": []},
    ]))

    cases = [
        ("agent may auto-approve a routine payment",
         "VeriSettle::Agent::\"payment-execution\"", "VeriSettle::Action::\"ApprovePayment\"", "VeriSettle::Payment::\"routine-1\"",
         cedarpy.Decision.Allow),
        ("agent may NOT auto-approve a payment above threshold",
         "VeriSettle::Agent::\"payment-execution\"", "VeriSettle::Action::\"ApprovePayment\"", "VeriSettle::Payment::\"large-1\"",
         cedarpy.Decision.Deny),
        ("a tier-2 human MAY approve a payment above threshold",
         "VeriSettle::User::\"controller.demo\"", "VeriSettle::Action::\"ApprovePayment\"", "VeriSettle::Payment::\"large-1\"",
         cedarpy.Decision.Allow),
        ("risk-scoring MAY flag a payment for review",
         "VeriSettle::Agent::\"risk-scoring\"", "VeriSettle::Action::\"FlagForReview\"", "VeriSettle::Payment::\"large-1\"",
         cedarpy.Decision.Allow),
        ("risk-scoring may NOT update a vendor record (approval-only action)",
         "VeriSettle::Agent::\"risk-scoring\"", "VeriSettle::Action::\"UpdateVendorRecord\"", "VeriSettle::Payment::\"large-1\"",
         cedarpy.Decision.Deny),
    ]

    failures = []
    for label, principal, action, resource, expected in cases:
        result = cedarpy.is_authorized(
            {"principal": principal, "action": action, "resource": resource, "context": {}},
            policy_text,
            entities,
            schema=schema_json,
        )
        if result.decision != expected:
            failures.append(f"expected {expected} but got {result.decision} for: {label}")
    return failures, len(cases)


def main():
    files = load_cedar_files()
    if not files:
        print(f"no .cedar files found under {POLICIES_DIR}", file=sys.stderr)
        return 1

    all_text = ""
    structural_errors = []
    for path in files:
        text = open(path).read()
        all_text += text + "\n"
        structural_errors.extend(check_unconstrained(path, text))
        try:
            cedarpy.PolicySet.from_str(text)
        except ValueError as e:
            structural_errors.append(f"{path}: parse error: {e}")

    if structural_errors:
        print("REJECTED:")
        for e in structural_errors:
            print(f"  {e}")
        return 1

    schema_json = open(SCHEMA_PATH).read()
    validation = cedarpy.validate_policies(all_text, schema_json)
    if not validation.validation_passed:
        print("REJECTED: schema validation failed:")
        for e in validation.errors:
            print(f"  {e}")
        return 1

    matrix_failures, case_count = run_authorization_matrix(all_text, schema_json)
    if matrix_failures:
        print("REJECTED: policy set does not produce the expected authorization outcomes:")
        for f in matrix_failures:
            print(f"  {f}")
        return 1

    print(f"ACCEPTED: {len(files)} policy file(s), schema-valid, no unconstrained rules, "
          f"authorization matrix ({case_count} cases) matches expected outcomes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
