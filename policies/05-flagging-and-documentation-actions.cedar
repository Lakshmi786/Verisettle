// FlagForReview, RequestAdditionalDocumentation, and UpdateVendorRecord had
// no Cedar rule at all until this file - the schema declared the actions
// and the capability manifests (custodian-backend/app/capability-manifests/
// *.json) enforced them in code, but Cedar itself default-denied every
// call, silently, since project inception. Found by testing the real
// authorize() call risk_scoring.py makes, not by code review. These rules
// mirror the capability manifests exactly - Cedar and the manifests must
// agree, since either one alone denying an action is enough to block it.
permit (
    principal == Custodian::Agent::"risk-scoring",
    action == Custodian::Action::"FlagForReview",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"approval",
    action == Custodian::Action::"FlagForReview",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"payment-execution",
    action == Custodian::Action::"FlagForReview",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"extraction",
    action == Custodian::Action::"RequestAdditionalDocumentation",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"risk-scoring",
    action == Custodian::Action::"RequestAdditionalDocumentation",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"approval",
    action == Custodian::Action::"RequestAdditionalDocumentation",
    resource is Custodian::Payment
);

permit (
    principal == Custodian::Agent::"approval",
    action == Custodian::Action::"UpdateVendorRecord",
    resource is Custodian::Payment
);
