"""Real vendor-history lookup (Vendor Governance): risk-scoring calls this
with the vendor name extraction actually read off the invoice, instead of
trusting a client-supplied vendor_first_seen/vendor_payment_count flag - a
self-reported fraud-relevant flag defeats the point of the first-seen-vendor
check. Uses a separate, narrower key (VENDOR_LOOKUP_API_KEY) than the one
that guards ledger writes - risk-scoring can read vendor history, but must
never hold the key that can also move money.
"""
import os

import requests

LEDGER_URL = os.environ.get("LEDGER_URL", "http://custodian-ledger:8000")
VENDOR_LOOKUP_API_KEY = os.environ["VENDOR_LOOKUP_API_KEY"]


def lookup_vendor(vendor_name: str) -> dict:
    """Fails closed to "first seen" on any error - a lookup failure must
    never silently make a genuinely-new vendor look established; that's the
    exact fraud-relevant mistake this check exists to prevent."""
    try:
        resp = requests.get(
            f"{LEDGER_URL}/vendors/lookup",
            params={"name": vendor_name},
            headers={"Authorization": f"Bearer {VENDOR_LOOKUP_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.RequestException:
        return {"known": False, "first_seen": None, "award_count": 0, "avg_amount": None, "recent_amounts": []}
    return result
