// A payment to a vendor bank account seen for the first time always
// requires dual human approval, regardless of amount - this forbid
// overrides policy 01's routine-amount auto-approve for agents, and also
// blocks a single human approval; resource.approvalCount must already be
// >= 2 (enforced together with the Dogwood temporal policy, which is what
// actually counts distinct human approvers across time - Cedar alone only
// sees a single point-in-time request and can't count prior approvals by
// itself).
forbid (
    principal,
    action == VeriSettle::Action::"ApprovePayment",
    resource is VeriSettle::Payment
)
when {
    resource.vendorFirstSeen == true &&
    resource.approvalCount < 2
};
