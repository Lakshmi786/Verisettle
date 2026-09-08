// Only the Payment-Execution agent may ever call the ledger-creation tool.
// This is the Cedar-level half of the trust-tier check; the capability
// manifest (infra/agent-runtime/capability-manifests/*.json, Phase 5) is
// the independent second check - a single policy misconfiguration here
// must never alone grant a lower-tier agent write access to the ledger.
forbid (
    principal is Custodian::Agent,
    action == Custodian::Action::"CreateLedgerEntry",
    resource
)
unless {
    principal.trustTier == "write-ledger"
};

permit (
    principal is Custodian::Agent,
    action == Custodian::Action::"CreateLedgerEntry",
    resource
)
when {
    principal.trustTier == "write-ledger"
};
