"""
Resolution agent — Stage 2 of the collections pipeline.

Handles structured negotiation after assessment. Attempts to reach
a payment arrangement (lump sum, plan, hardship referral) or cleanly
close without one. Voice channel (Retell) in production; text simulation
in eval mode.
"""

from typing import Literal, Optional

from pydantic import BaseModel

from src.agents.base import BaseAgent
from src.llm.client import LLMClient
from src.llm.utils import parse_llm_json
from src.models.case_file import CaseFile, Stage

_EXTRACTION_PROMPT = """\
You are analyzing a completed debt collections resolution conversation.
Extract structured data and return ONLY valid JSON — no explanation, no markdown fences.

JSON schema:
{
  "resolution_outcome": "settled" | "payment_plan" | "hardship_referred" | "declined" | "no_response" | null,
  "commitment_amount": number or null,
  "commitment_type": "lump_sum" | "payment_plan" | null,
  "commitment_months": integer or null,
  "offers_made": [{"type": "settlement" | "payment_plan", "amount": number}],
  "hardship_offered": boolean,
  "identity_verified": boolean,
  "ai_disclosed": boolean,
  "recording_disclosed": boolean,
  "mini_miranda_delivered": boolean,
  "dispute_flag": boolean,
  "stop_contact_requested": boolean,
  "resolution_complete": boolean
}

Rules:
- commitment_amount: the specific amount the borrower committed to (in whatever currency discussed)
- commitment_months: number of months in a payment plan (null for lump sum)
- offers_made: list of ALL offers the agent presented (not just the final one)
- hardship_offered: true if agent offered hardship program or referral
- mini_miranda_delivered: true if agent said "This is an attempt to collect a debt" or equivalent
- dispute_flag: true if borrower disputed the debt or requested validation
- resolution_complete: true if a definitive outcome was reached (deal, decline, or hardship referral)
- stop_contact_requested: true if borrower said stop calling, cease contact, or equivalent
"""


class ResolutionExtraction(BaseModel):
    resolution_outcome: Optional[
        Literal[
            "settled", "payment_plan", "hardship_referred", "declined", "no_response"
        ]
    ] = None
    commitment_amount: Optional[float] = None
    commitment_type: Optional[Literal["lump_sum", "payment_plan"]] = None
    commitment_months: Optional[int] = None
    offers_made: list[dict] = []
    hardship_offered: bool = False
    identity_verified: bool = False
    ai_disclosed: bool = False
    recording_disclosed: bool = False
    mini_miranda_delivered: bool = False
    dispute_flag: bool = False
    stop_contact_requested: bool = False
    resolution_complete: bool = False


class ResolutionAgent(BaseAgent):
    agent_name = "resolution"
    max_turns = 10

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    def is_complete(self, messages: list[dict], case_file: CaseFile) -> bool:
        agent_turns = sum(1 for m in messages if m["role"] == "assistant")

        # Too early — always continue
        if agent_turns < 3:
            return False

        # FDCPA: stop contact immediately
        if case_file.compliance.stop_contact:
            return True

        # Hard turn limit
        if agent_turns >= self.max_turns:
            return True

        # Use a lightweight LLM signal (not keyword matching) to detect completion
        last_agent = next(
            (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
        )
        completion_check = self.llm.complete(
            system_prompt=(
                "You are analyzing a debt collections conversation turn. "
                "Has the conversation reached a definitive resolution? "
                "A definitive resolution means: a payment arrangement was agreed, "
                "the borrower explicitly declined, a hardship referral was made, "
                "or the borrower disengaged. "
                "Reply with exactly one word: YES or NO."
            ),
            messages=[
                {"role": "user", "content": f"Agent's last message:\n{last_agent}"}
            ],
            max_tokens=5,
        )
        return completion_check.strip().upper().startswith("YES")

    def extract_updates(self, messages: list[dict], case_file: CaseFile) -> CaseFile:
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages
        )
        raw = self.llm.complete(
            system_prompt=_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": conversation_text}],
            max_tokens=350,
        )

        try:
            extracted = parse_llm_json(raw, ResolutionExtraction)
        except ValueError:
            return case_file

        # Validate commitment_amount range before accepting
        if extracted.commitment_amount is not None:
            if extracted.commitment_amount <= 0:
                extracted.commitment_amount = None
            elif extracted.commitment_amount > case_file.debt.amount:
                # Clamp to debt ceiling — borrower likely confused amounts, not fraud
                print(
                    f"[WARN] resolution: clamping commitment_amount "
                    f"{extracted.commitment_amount} → {case_file.debt.amount} (debt ceiling)"
                )
                extracted.commitment_amount = case_file.debt.amount

        # Update negotiation ledger — offers made
        if extracted.offers_made:
            case_file.negotiation.offers_made.extend(extracted.offers_made)

        # Update negotiation ledger — commitments
        if extracted.commitment_amount is not None:
            case_file.negotiation.commitments.append(
                {
                    "type": extracted.commitment_type,
                    "amount": extracted.commitment_amount,
                    "months": extracted.commitment_months,
                    "outcome": extracted.resolution_outcome,
                }
            )

        # Update compliance state
        if extracted.ai_disclosed:
            case_file.compliance.ai_disclosed = True
        if extracted.recording_disclosed:
            case_file.compliance.recording_disclosed = True
        if extracted.hardship_offered:
            case_file.compliance.hardship_offered = True
        if extracted.stop_contact_requested:
            case_file.compliance.stop_contact = True

        # Update identity
        if extracted.identity_verified:
            case_file.identity_verified = True

        return case_file
