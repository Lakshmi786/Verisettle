import os
from datetime import datetime, timezone
from decimal import Decimal

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import engine, get_db
from .ledger import EntryRequest, LedgerError, dry_run, post_transaction
from .models import Account, AccountType, Base, Direction, HistoricalPayment, Vendor

LEDGER_API_KEY = os.environ["LEDGER_API_KEY"]
# Deliberately separate from LEDGER_API_KEY: risk-scoring needs read access
# to /vendors/lookup, but must never hold the same key that also guards
# /transactions writes - same least-privilege principle as every agent's own
# capability manifest (a key that can only read vendor history can't be
# misused to move money, even if leaked).
VENDOR_LOOKUP_API_KEY = os.environ["VENDOR_LOOKUP_API_KEY"]
AUDIT_LOG_URL = os.environ.get("AUDIT_LOG_URL", "http://audit-log:8000")

app = FastAPI(title="custodian-ledger", version="1.0.0")


def _audit(event_type: str, payload: dict):
    try:
        requests.post(f"{AUDIT_LOG_URL}/append", json={
            "event_type": event_type, "source_service": "custodian-ledger", "payload": payload,
        }, timeout=5)
    except requests.RequestException:
        pass


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    from .db import SessionLocal
    db = SessionLocal()
    try:
        _seed_accounts(db)
    finally:
        db.close()


def _seed_accounts(db: Session):
    seed = [
        ("operating-cash", AccountType.asset, Decimal("500000.00"), False),
        ("accounts-payable", AccountType.liability, Decimal("0.00"), True),
        ("vendor-expense", AccountType.expense, Decimal("0.00"), True),
    ]
    for name, atype, opening_balance, allow_negative in seed:
        existing = db.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
        if existing is None:
            db.add(Account(name=name, type=atype, balance=opening_balance, allow_negative=allow_negative))
    db.commit()


def require_api_key(authorization: str = Header(None)):
    if authorization != f"Bearer {LEDGER_API_KEY}":
        raise HTTPException(status_code=401, detail="invalid or missing ledger API key")


def require_vendor_lookup_key(authorization: str = Header(None)):
    if authorization != f"Bearer {VENDOR_LOOKUP_API_KEY}":
        raise HTTPException(status_code=401, detail="invalid or missing vendor-lookup API key")


class EntryIn(BaseModel):
    account_name: str
    direction: Direction
    amount: Decimal


class PaymentRequest(BaseModel):
    idempotency_key: str
    description: str
    requested_by: str
    entries: list[EntryIn]


def _to_entry_requests(entries: list[EntryIn]) -> list[EntryRequest]:
    return [EntryRequest(account_name=e.account_name, direction=e.direction, amount=e.amount) for e in entries]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/accounts/{name}/balance", dependencies=[Depends(require_api_key)])
def get_balance(name: str, db: Session = Depends(get_db)):
    account = db.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail=f"no account named {name!r}")
    return {"account": name, "type": account.type.value, "balance": float(account.balance)}


@app.get("/vendors/lookup", dependencies=[Depends(require_vendor_lookup_key)])
def lookup_vendor(name: str, db: Session = Depends(get_db)):
    """The real first-seen-vendor check (Vendor Governance): risk-scoring
    calls this with the vendor name extraction actually read off the
    invoice, instead of trusting a client-supplied vendor_first_seen flag -
    a self-reported fraud-relevant flag defeats the point of the check.
    Case/whitespace-insensitive: real recipient names from USAspending.gov
    and OCR'd invoice text won't match byte-for-byte."""
    normalized = name.strip().lower()
    vendor = db.execute(
        select(Vendor).where(func.lower(func.trim(Vendor.recipient_name)) == normalized)
    ).scalar_one_or_none()
    if vendor is None:
        return {"known": False, "first_seen": None, "award_count": 0,
                "avg_amount": None, "recent_amounts": []}

    # Real amount-pattern check (historical_payments, not just the vendors
    # summary): lets risk-scoring reason about "is this amount consistent
    # with what we usually pay this vendor," not just "have we paid them
    # before." Last 10 payments, most recent first.
    rows = db.execute(
        select(HistoricalPayment.amount)
        .where(HistoricalPayment.vendor_id == vendor.id)
        .order_by(HistoricalPayment.action_date.desc().nullslast(), HistoricalPayment.id.desc())
        .limit(10)
    ).scalars().all()
    recent_amounts = [float(a) for a in rows]
    avg_amount = round(sum(recent_amounts) / len(recent_amounts), 2) if recent_amounts else None

    return {
        "known": True,
        "first_seen": vendor.first_seen.isoformat() if vendor.first_seen else None,
        "award_count": vendor.award_count,
        "avg_amount": avg_amount,
        "recent_amounts": recent_amounts,
    }


class RecordVendorPaymentRequest(BaseModel):
    vendor_name: str
    amount: Decimal
    idempotency_key: str


@app.post("/vendors/record-payment", dependencies=[Depends(require_api_key)])
def record_vendor_payment(req: RecordVendorPaymentRequest, db: Session = Depends(get_db)):
    """Closes the loop on vendor-history governance: called only after a
    real payment settles (payment_execution.py, right after ledger_commit),
    so a vendor's first genuine payment here creates a real record and its
    second is correctly recognized as known - not re-flagged as first-seen
    forever. Guarded by LEDGER_API_KEY, not the read-only lookup key: this
    is a write, and only Payment-Execution (the trust tier that already
    holds this key) should ever be able to cause it.

    Writes both tables: vendors (the summary lookup_vendor reads) and a real
    historical_payments row (the itemized amount pattern lookup_vendor now
    also reads) - the same real payment, recorded at both grains."""
    normalized = req.vendor_name.strip().lower()
    vendor = db.execute(
        select(Vendor).where(func.lower(func.trim(Vendor.recipient_name)) == normalized)
    ).scalar_one_or_none()

    if vendor is None:
        vendor = Vendor(
            recipient_name=req.vendor_name.strip(),
            first_seen=datetime.now(timezone.utc).date(),
            total_awarded=req.amount,
            award_count=1,
        )
        db.add(vendor)
        db.flush()  # need vendor.id for the historical_payments FK below
        created = True
    else:
        vendor.total_awarded = vendor.total_awarded + req.amount
        vendor.award_count = vendor.award_count + 1
        created = False

    db.add(HistoricalPayment(
        vendor_id=vendor.id,
        award_id=f"custodian-{req.idempotency_key}",
        amount=req.amount,
        action_date=datetime.now(timezone.utc).date(),
        awarding_agency="Custodian AP",
        # ponytail: real recurring-payment detection (matching amount/cadence
        # across prior rows) is a real upgrade, not built here - every live
        # payment is recorded as non-recurring until that's added.
        recurring=False,
    ))

    db.commit()
    db.refresh(vendor)
    _audit("vendor_payment_recorded", {
        "vendor_name": vendor.recipient_name, "created": created,
        "award_count": vendor.award_count, "total_awarded": float(vendor.total_awarded),
    })
    return {"vendor_name": vendor.recipient_name, "created": created, "award_count": vendor.award_count}


@app.post("/transactions/dry-run", dependencies=[Depends(require_api_key)])
def dry_run_transaction(req: PaymentRequest, db: Session = Depends(get_db)):
    result = dry_run(db, _to_entry_requests(req.entries))
    return result


@app.post("/transactions", dependencies=[Depends(require_api_key)])
def create_transaction(req: PaymentRequest, db: Session = Depends(get_db)):
    try:
        txn = post_transaction(db, req.idempotency_key, req.description, req.requested_by,
                                _to_entry_requests(req.entries))
    except LedgerError as e:
        status = 409 if e.code == "duplicate_transaction" else 422
        raise HTTPException(status_code=status, detail={"code": e.code, "message": e.message})

    entries_out = [
        {"account": e.account.name, "direction": e.direction.value, "amount": float(e.amount)}
        for e in txn.entries
    ]
    _audit("ledger_execution", {
        "transaction_id": txn.id,
        "idempotency_key": txn.idempotency_key,
        "description": txn.description,
        "requested_by": txn.requested_by,
        "entries": entries_out,
    })

    return {
        "transaction_id": txn.id,
        "idempotency_key": txn.idempotency_key,
        "created_at": txn.created_at.isoformat(),
        "entries": entries_out,
    }
