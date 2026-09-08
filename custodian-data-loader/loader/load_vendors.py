import os
from collections import Counter
from datetime import datetime

import requests

from . import db

API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AGENCY = os.environ.get("USASPENDING_AGENCY", "Department of Health and Human Services")
FISCAL_YEAR = int(os.environ.get("USASPENDING_FISCAL_YEAR", "2024"))
PAGE_LIMIT = int(os.environ.get("USASPENDING_PAGE_LIMIT", "100"))
MAX_PAGES = int(os.environ.get("USASPENDING_MAX_PAGES", "3"))

FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Start Date",
    "Award Amount", "Awarding Agency", "Awarding Sub Agency", "generated_internal_id",
]


def _fetch_page(page):
    payload = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{
                "start_date": f"{FISCAL_YEAR - 1}-10-01",
                "end_date": f"{FISCAL_YEAR}-09-30",
            }],
            "agencies": [{"type": "awarding", "tier": "toptier", "name": AGENCY}],
        },
        "fields": FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "sort": "Award Amount",
        "order": "desc",
    }
    resp = requests.post(API_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def run():
    conn = db.ledger_conn()
    db.ensure_ledger_schema(conn)

    name_counts = Counter()
    awards = []
    for page in range(1, MAX_PAGES + 1):
        data = _fetch_page(page)
        results = data.get("results", [])
        if not results:
            break
        awards.extend(results)
        if not data.get("page_metadata", {}).get("hasNext", False):
            break

    for a in awards:
        name_counts[a.get("Recipient Name")] += 1

    seeded = 0
    for a in awards:
        name = a.get("Recipient Name")
        amount = a.get("Award Amount")
        award_id = a.get("generated_internal_id") or a.get("Award ID")
        if not name or amount is None or not award_id:
            continue
        start_date = a.get("Start Date")
        first_seen = None
        if start_date:
            try:
                first_seen = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                first_seen = None
        vendor_id = db.upsert_vendor(conn, name, a.get("Recipient UEI"), first_seen, amount)
        db.upsert_historical_payment(
            conn, vendor_id, award_id, amount, first_seen,
            a.get("Awarding Agency"), recurring=name_counts[name] > 1,
        )
        seeded += 1

    conn.close()
    print(f"USAspending: seeded {seeded} historical payments across {len(name_counts)} vendors "
          f"(agency={AGENCY!r}, FY{FISCAL_YEAR})")
    return {"awards_seeded": seeded, "vendor_count": len(name_counts)}


if __name__ == "__main__":
    run()
