import json

from src.handoff.token_budget import _count, enforce_budget
from src.models.case_file import CaseFile
from src.models.handoff import HandoffPacket


def build_handoff_packet(case_file: CaseFile) -> HandoffPacket:
    key_facts: list[str] = []

    if case_file.identity_verified:
        key_facts.append("Identity verified")
    if case_file.financial.income_status:
        key_facts.append(f"Income status: {case_file.financial.income_status}")
    if case_file.financial.hardship_flags:
        key_facts.append(
            f"Hardship flags: {', '.join(case_file.financial.hardship_flags)}"
        )
    if case_file.negotiation.commitments:
        key_facts.append(f"Commitments made: {len(case_file.negotiation.commitments)}")
    if case_file.negotiation.offers_made:
        key_facts.append(f"Offers made: {len(case_file.negotiation.offers_made)}")

    packet = HandoffPacket(
        borrower_id=case_file.borrower_id,
        stage=case_file.stage,
        key_facts=key_facts,
        compliance_flags=case_file.compliance.model_dump(),
        sentiment=case_file.borrower_sentiment,
        token_count=0,
        # Structured fields for cross-stage context
        monthly_income_est=case_file.financial.monthly_income_est,
        obligations=case_file.financial.obligations,
        offers_made=case_file.negotiation.offers_made,
        commitments=case_file.negotiation.commitments,
        account_ending=case_file.partial_account,
        debt_amount=case_file.debt.amount,
        creditor=case_file.debt.creditor,
        dispute_status=case_file.dispute_validation_required,
        hardship_type=(
            case_file.financial.hardship_flags[0]
            if case_file.financial.hardship_flags
            else None
        ),
        identity_verified=case_file.identity_verified,
    )

    serialized = json.dumps(packet.model_dump(), default=str)
    _, serialized = enforce_budget(system_prompt="", handoff_context=serialized)
    serialized = serialized or json.dumps(packet.model_dump(), default=str)
    token_count = _count(serialized)
    packet.token_count = token_count

    return packet
