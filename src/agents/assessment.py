from typing import Optional

from pydantic import BaseModel

from src.agents.base import BaseAgent
from src.llm.client import LLMClient
from src.llm.utils import parse_llm_json
from src.models.case_file import CaseFile

_EXTRACTION_PROMPT = """\
You are analyzing a completed debt collections assessment conversation.
Extract structured data and return ONLY valid JSON — no explanation, no markdown fences.

JSON schema:
{
  "identity_verified": boolean,
  "income_status": string or null,
  "monthly_income_est": number or null,
  "obligations": string or null,
  "hardship_flags": [string],
  "borrower_sentiment": "cooperative" | "evasive" | "combative" | "distressed" | "confused" | null,
  "cooperation_level": "high" | "medium" | "low" | null,
  "ai_disclosed": boolean,
  "recording_disclosed": boolean,
  "stop_contact_requested": boolean,
  "assessment_complete": boolean
}

Rules:
- identity_verified = true only if borrower confirmed their account digits
- ai_disclosed = true if agent stated it is an AI or automated system
- recording_disclosed = true if agent mentioned the call may be recorded
- assessment_complete = true if agent gathered sufficient financial information
"""


class AssessmentExtraction(BaseModel):
    identity_verified: bool = False
    income_status: Optional[str] = None
    monthly_income_est: Optional[float] = None
    obligations: Optional[str] = None
    hardship_flags: list[str] = []
    borrower_sentiment: Optional[str] = None
    cooperation_level: Optional[str] = None
    ai_disclosed: bool = False
    recording_disclosed: bool = False
    stop_contact_requested: bool = False
    assessment_complete: bool = False


class AssessmentAgent(BaseAgent):
    agent_name = "assessment"
    max_turns = 8

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    def is_complete(self, messages: list[dict], case_file: CaseFile) -> bool:
        assistant_turns = sum(1 for m in messages if m["role"] == "assistant")
        if assistant_turns >= 5:
            return True
        if case_file.compliance.stop_contact:
            return True
        last_agent = next(
            (m["content"] for m in reversed(messages) if m["role"] == "assistant"), ""
        )
        closing_signals = [
            "we'll be in touch",
            "resolution options",
            "next steps",
            "transfer you",
            "specialist will",
            "follow up",
        ]
        return any(signal in last_agent.lower() for signal in closing_signals)

    def extract_updates(self, messages: list[dict], case_file: CaseFile) -> CaseFile:
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages
        )
        raw = self.llm.complete(
            system_prompt=_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": conversation_text}],
            max_tokens=300,
        )

        try:
            extracted = parse_llm_json(raw, AssessmentExtraction)
        except ValueError:
            # Partial failure — return case file as-is with whatever was set during the loop
            return case_file

        case_file.identity_verified = extracted.identity_verified
        case_file.financial.income_status = extracted.income_status
        case_file.financial.monthly_income_est = extracted.monthly_income_est
        case_file.financial.obligations = extracted.obligations
        if extracted.hardship_flags:
            case_file.financial.hardship_flags.extend(extracted.hardship_flags)
        case_file.borrower_sentiment = extracted.borrower_sentiment
        case_file.cooperation_level = extracted.cooperation_level
        case_file.compliance.ai_disclosed = extracted.ai_disclosed
        case_file.compliance.recording_disclosed = extracted.recording_disclosed
        if extracted.stop_contact_requested:
            case_file.compliance.stop_contact = True

        return case_file
