from pydantic import BaseModel
from typing import Optional
from enum import Enum


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
