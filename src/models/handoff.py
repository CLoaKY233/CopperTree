from typing import Optional

from pydantic import BaseModel

from src.models.case_file import Stage


class HandoffPacket(BaseModel):
    borrower_id: str
    stage: Stage
    key_facts: list[str]
    compliance_flags: dict[str, bool]
    sentiment: Optional[str]
    token_count: int
    # Structured fields for cross-stage context
    monthly_income_est: Optional[float] = None
    obligations: Optional[str] = None
    offers_made: list[dict] = []
    commitments: list[dict] = []
    account_ending: Optional[str] = None
    debt_amount: Optional[float] = None
    creditor: Optional[str] = None
    dispute_status: bool = False
    hardship_type: Optional[str] = None
    identity_verified: bool = False
