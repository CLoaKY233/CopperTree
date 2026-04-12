from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Stage(str, Enum):
    ASSESSMENT = "assessment"
    RESOLUTION = "resolution"
    FINAL_NOTICE = "final_notice"
    COMPLETE = "complete"
    FLAGGED = "flagged"


class DebtInfo(BaseModel):
    amount: float
    creditor: str
    default_date: str
    allowed_actions: list[str] = ["settlement", "payment_plan", "hardship_referral"]


class FinancialInfo(BaseModel):
    income_status: Optional[str] = None
    monthly_income_est: Optional[float] = None
    obligations: Optional[str] = None
    hardship_flags: list[str] = []


class ComplianceState(BaseModel):
    ai_disclosed: bool = False
    recording_disclosed: bool = False
    stop_contact: bool = False
    hardship_offered: bool = False


class NegotiationLedger(BaseModel):
    offers_made: list[dict] = []
    borrower_responses: list[str] = []
    commitments: list[dict] = []
    objections: list[str] = []


class CaseFile(BaseModel):
    borrower_id: str
    stage: Stage = Stage.ASSESSMENT
    attempt: int = 1
    identity_verified: bool = False
    partial_account: str = ""
    debt: DebtInfo
    financial: FinancialInfo = FinancialInfo()
    negotiation: NegotiationLedger = NegotiationLedger()
    compliance: ComplianceState = ComplianceState()
    borrower_sentiment: Optional[str] = None
    cooperation_level: Optional[str] = None
    borrower_timezone: Optional[str] = None  # IANA, e.g. "America/New_York"
    phone_number: Optional[str] = None  # E.164, used only for production Retell calls
    dispute_validation_required: bool = (
        False  # FDCPA §809 — must send validation notice
    )
    validation_notice_sent: bool = False  # True once notice has been dispatched
