// FlagForReview, RequestAdditionalDocumentation, and UpdateVendorRecord had
// no Cedar rule at all until this file - the schema declared the actions
// and the capability manifests (verisettle-backend/app/capability-manifests/
// *.json) enforced them in code, but Cedar itself default-denied every
// call, silently, since project inception. Found by testing the real
// authorize() call risk_scoring.py makes, not by code review. These rules
// mirror the capability manifests exactly - Cedar and the manifests must
// agree, since either one alone denying an action is enough to block it.
permit (
    principal == VeriSettle::Agent::"risk-scoring",
    action == VeriSettle::Action::"FlagForReview",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"approval",
    action == VeriSettle::Action::"FlagForReview",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"payment-execution",
    action == VeriSettle::Action::"FlagForReview",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"extraction",
    action == VeriSettle::Action::"RequestAdditionalDocumentation",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"risk-scoring",
    action == VeriSettle::Action::"RequestAdditionalDocumentation",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"approval",
    action == VeriSettle::Action::"RequestAdditionalDocumentation",
    resource is VeriSettle::Payment
);

permit (
    principal == VeriSettle::Agent::"approval",
    action == VeriSettle::Action::"UpdateVendorRecord",
    resource is VeriSettle::Payment
);
