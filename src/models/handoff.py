from pydantic import BaseModel
from typing import Optional
from src.models.case_file import Stage


class HandoffPacket(BaseModel):
    borrower_id: str
    stage: Stage
    key_facts: list[str]
    compliance_flags: dict[str, bool]
    sentiment: Optional[str]
    token_count: int
