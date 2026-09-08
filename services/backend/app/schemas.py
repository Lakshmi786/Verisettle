from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class ExtractedInvoice(BaseModel):
    """Instructor-validated typed output of the Extraction agent."""
    vendor: str | None = Field(description="Merchant/company name, or null if not present in the OCR text")
    date: str | None = Field(description="Transaction date as it appears, or null")
    address: str | None = Field(description="Merchant address, or null")
    total: float | None = Field(description="Final total amount as a plain number, or null")
    confidence: float = Field(ge=0, le=1, description="Extraction confidence, 0-1")


class RiskScore(BaseModel):
    """Instructor-validated typed output of the Risk-Scoring agent."""
    risk_level: Literal["low", "medium", "high"]
    risk_score: float = Field(ge=0, le=1)
    reasons: list[str]
    confidence: float = Field(ge=0, le=1)
    vendor_first_seen: bool


class ApprovalDecision(BaseModel):
    """Instructor-validated typed output of the Approval agent."""
    decision: Literal["auto_approve", "escalate_to_human", "reject"]
    reasoning: str
    confidence: float = Field(ge=0, le=1)


class CriticReview(BaseModel):
    """Dual-agent critic verification (the other provider) before payment."""
    agrees: bool
    concerns: list[str]
    confidence: float = Field(ge=0, le=1)


class PaymentResult(BaseModel):
    status: Literal["settled", "held", "blocked"]
    ledger_transaction_id: int | None = None
    reason: str | None = None


class InvoiceRunState(TypedDict, total=False):
    invoice_id: str
    image_path: str
    ocr_text: str
    source: str

    extraction: dict
    risk: dict
    approval: dict
    critic: dict
    payment: dict

    task_state: str  # mirrors a2a.types.TaskState
    audit_trail: list[dict]
    requires_human: bool
    human_decision: str | None
