from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Account, AccountType, Direction, Entry, Transaction

INCREASES_ON_DEBIT = {AccountType.asset, AccountType.expense}


def signed_delta(account_type: AccountType, direction: Direction, amount: Decimal) -> Decimal:
    increases = direction == Direction.debit if account_type in INCREASES_ON_DEBIT else direction == Direction.credit
    return amount if increases else -amount


class LedgerError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class DuplicateTransactionError(LedgerError):
    def __init__(self, idempotency_key: str):
        super().__init__("duplicate_transaction", f"transaction with idempotency_key={idempotency_key!r} already exists")


class UnbalancedEntriesError(LedgerError):
    def __init__(self, debits: Decimal, credits: Decimal):
        super().__init__("unbalanced_entries", f"debits ({debits}) != credits ({credits}) - a real double-entry transaction must balance")


class InsufficientFundsError(LedgerError):
    def __init__(self, account_name: str, resulting_balance: Decimal):
        super().__init__("insufficient_funds", f"account {account_name!r} would go negative ({resulting_balance}) and does not allow it")


class AccountNotFoundError(LedgerError):
    def __init__(self, name: str):
        super().__init__("account_not_found", f"no account named {name!r}")


@dataclass
class EntryRequest:
    account_name: str
    direction: Direction
    amount: Decimal


def _validate_and_compute(db: Session, entries: list[EntryRequest]) -> list[tuple[Account, Decimal]]:
    total_debits = sum((e.amount for e in entries if e.direction == Direction.debit), Decimal(0))
    total_credits = sum((e.amount for e in entries if e.direction == Direction.credit), Decimal(0))
    if total_debits != total_credits:
        raise UnbalancedEntriesError(total_debits, total_credits)

    results = []
    for e in entries:
        # FOR UPDATE: row-level lock so two concurrent payments can't both
        # pass the balance check before either commits.
        account = db.execute(
            select(Account).where(Account.name == e.account_name).with_for_update()
        ).scalar_one_or_none()
        if account is None:
            raise AccountNotFoundError(e.account_name)

        delta = signed_delta(account.type, e.direction, e.amount)
        new_balance = Decimal(account.balance) + delta
        if new_balance < 0 and not account.allow_negative:
            raise InsufficientFundsError(account.name, new_balance)
        results.append((account, new_balance))
    return results


def dry_run(db: Session, entries: list[EntryRequest]) -> dict:
    """Computes resulting balances and validation outcome WITHOUT writing -
    the ledger dry-run required before every real commit (Agent Runtime
    Governance: dry-run before commit)."""
    try:
        results = _validate_and_compute(db, entries)
        db.rollback()  # the FOR UPDATE locks and any implicit txn - never persisted
        return {
            "valid": True,
            "resulting_balances": {a.name: float(b) for a, b in results},
        }
    except LedgerError as e:
        db.rollback()
        return {"valid": False, "error_code": e.code, "error": e.message}


def post_transaction(db: Session, idempotency_key: str, description: str, requested_by: str,
                      entries: list[EntryRequest]) -> Transaction:
    existing = db.execute(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateTransactionError(idempotency_key)

    results = _validate_and_compute(db, entries)

    txn = Transaction(idempotency_key=idempotency_key, description=description, requested_by=requested_by)
    db.add(txn)
    db.flush()

    for (account, new_balance), e in zip(results, entries):
        db.add(Entry(transaction_id=txn.id, account_id=account.id, direction=e.direction, amount=e.amount))
        account.balance = new_balance

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateTransactionError(idempotency_key)

    db.refresh(txn)
    return txn
