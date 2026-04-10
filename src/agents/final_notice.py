from typing import Optional
from pydantic import BaseModel

from src.agents.base import BaseAgent
from src.llm.client import LLMClient
from src.llm.utils import parse_llm_json
from src.models.case_file import CaseFile

_EXTRACTION_PROMPT = """\
You are analyzing a completed debt collections final notice conversation.
Extract structured data and return ONLY valid JSON — no explanation, no markdown fences.

JSON schema:
{
  "final_decision": "settled" | "payment_plan" | "hardship_referred" | "declined" | "no_response" | null,
  "commitment_amount": number or null,
  "commitment_type": "lump_sum" | "payment_plan" | null,
  "hardship_offered": boolean,
  "stop_contact_requested": boolean,
  "conversation_complete": boolean
}

Rules:
- final_decision = "settled" only if borrower verbally agreed to a specific amount
- final_decision = "declined" if borrower explicitly refused all options
- final_decision = "no_response" if borrower was unresponsive or evasive throughout
- hardship_offered = true if agent explicitly offered a hardship referral
"""


class FinalNoticeExtraction(BaseModel):
    final_decision: Optional[str] = None
    commitment_amount: Optional[float] = None
    commitment_type: Optional[str] = None
    hardship_offered: bool = False
    stop_contact_requested: bool = False
    conversation_complete: bool = False


class FinalNoticeAgent(BaseAgent):
    agent_name = "final_notice"
    max_turns = 6

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    def is_complete(self, messages: list[dict], case_file: CaseFile) -> bool:
        assistant_turns = sum(1 for m in messages if m["role"] == "assistant")
        if assistant_turns >= 4:
            return True
        if case_file.compliance.stop_contact:
            return True
        last_agent = next(
            (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
        )
        closing_signals = [
            "thank you for your time", "we'll proceed", "case will be referred",
            "confirmation will be sent", "best of luck"
        ]
        return any(signal in last_agent.lower() for signal in closing_signals)

    def extract_updates(self, messages: list[dict], case_file: CaseFile) -> CaseFile:
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages
        )
        raw = self.llm.complete(
            system_prompt=_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": conversation_text}],
            max_tokens=200,
        )

        try:
            extracted = parse_llm_json(raw, FinalNoticeExtraction)
        except ValueError:
            return case_file

        if extracted.hardship_offered:
            case_file.compliance.hardship_offered = True
        if extracted.stop_contact_requested:
            case_file.compliance.stop_contact = True
        if extracted.final_decision in ("settled", "payment_plan"):
            if extracted.commitment_amount and extracted.commitment_type:
                case_file.negotiation.commitments.append({
                    "type": extracted.commitment_type,
                    "amount": extracted.commitment_amount,
                    "decision": extracted.final_decision,
                })

        return case_file
