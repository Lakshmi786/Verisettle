// Explicit per-agent tool allowlist, checked via policy-service on every
// InvokeTool request (e.g. verisettle-sandbox-runner's own authorization
// check before spawning a sandbox) - default deny, no open discovery.
// Each permit names exactly the tools that agent's role needs; nothing else.
// Standalone Cedar logic - not related to the removed mcp_trust_proxy
// check (see INSTRUCTIONS.md 5.5), which was a separate Python-level gate.
permit (
    principal == VeriSettle::Agent::"extraction",
    action == VeriSettle::Action::"InvokeTool",
    resource
)
when {
    ["request-additional-documentation", "sandbox-ocr"].contains(resource.name)
};

permit (
    principal == VeriSettle::Agent::"risk-scoring",
    action == VeriSettle::Action::"InvokeTool",
    resource
)
when {
    ["flag-for-review", "request-additional-documentation"].contains(resource.name)
};

permit (
    principal == VeriSettle::Agent::"approval",
    action == VeriSettle::Action::"InvokeTool",
    resource
)
when {
    ["flag-for-review", "request-additional-documentation", "update-vendor-record"].contains(resource.name)
};

permit (
    principal == VeriSettle::Agent::"payment-execution",
    action == VeriSettle::Action::"InvokeTool",
    resource
)
when {
    ["create-ledger-entry", "flag-for-review"].contains(resource.name)
};
