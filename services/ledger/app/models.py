import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String,
    UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    """Maps to the real vendors table verisettle-data-loader seeds from
    USAspending.gov (loader/db.py's VENDORS_SCHEMA) - read-only here, this
    service doesn't create or own the table, just the real lookup used by
    risk-scoring's first-seen-vendor check (Vendor Governance integration)."""
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recipient_name: Mapped[str] = mapped_column(String, unique=True)
    recipient_uei: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_awarded: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    award_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HistoricalPayment(Base):
    """Maps to the real historical_payments table verisettle-data-loader
    seeds from USAspending.gov (loader/db.py's HISTORICAL_PAYMENTS_SCHEMA) -
    one row per real individual payment, not a summary. record_vendor_payment
    now adds a real row here on every genuine settlement too, so this table
    keeps growing with live payments the same way the seeded data grew from
    real government awards (Vendor Governance integration, amount-pattern
    check)."""
    __tablename__ = "historical_payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    award_id: Mapped[str] = mapped_column(String, unique=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    action_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    awarding_agency: Mapped[str | None] = mapped_column(String, nullable=True)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    revenue = "revenue"
    expense = "expense"


class Direction(str, enum.Enum):
    debit = "debit"
    credit = "credit"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"))
    # Cached running balance (asset/expense increase on debit, others on credit).
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["Entry"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(String(1000))
    requested_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list["Entry"]] = relationship(back_populates="transaction")


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("transaction_id", "account_id", "direction"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    direction: Mapped[Direction] = mapped_column(Enum(Direction, name="entry_direction"))
    amount: Mapped[float] = mapped_column(Numeric(18, 2))

    transaction: Mapped[Transaction] = relationship(back_populates="entries")
    account: Mapped[Account] = relationship(back_populates="entries")
