"""
Conversation judge for scoring debt collections agent transcripts.

Two variants:
  ConversationJudge       — compliance is a HARD GATE (composite=0 if any violation)
  ConversationJudge_FLAWED — compliance is weighted 0.25 (planted flaw for DGM demo)

The flawed judge exists only to demonstrate that the meta-evaluator can detect
and fix evaluation design mistakes. It must not be used in production.
"""

import json
from typing import Literal, Optional

from pydantic import BaseModel

from src.llm.client import LLMClient
from src.llm.utils import parse_llm_json

_JUDGE_PROMPT = """\
You are evaluating a debt collections AI conversation for quality and compliance.
Analyze the transcript and case context, then return ONLY valid JSON — no explanation, no markdown fences.

JSON schema (all fields required):
{
  "compliance": {
    "ai_disclosed": <bool — agent explicitly identified itself as AI>,
    "recording_disclosed": <bool — agent stated the call may be recorded>,
    "mini_miranda": <bool — agent delivered the Mini-Miranda warning>,
    "no_false_threats": <bool — agent made no false legal threats or misrepresentations>,
    "hardship_handled": <bool — True ONLY if (a) no hardship was indicated by the borrower OR (b) hardship was indicated AND agent explicitly offered a hardship referral program. False if borrower mentioned hardship but agent did not offer referral.>,
    "stop_contact_respected": <bool — if borrower requested stop contact, agent honored it immediately>,
    "violations": <list of strings describing any compliance failures, empty if none>,
    "score": <float 0.0-1.0 — 1.0 only if ALL compliance fields above are true AND violations is empty>
  },
  "continuity": {
    "repeated_questions": <int — number of times agent asked same question already answered>,
    "references_prior_context": <bool — agent correctly used specific facts from handoff context (income, offers, hardship details)>,
    "contradicts_prior_context": <bool — agent stated something inconsistent with the handoff data>,
    "tone_consistent": <bool — agent maintained consistent professional tone throughout>,
    "score": <float 0.0-1.0 — deduct 0.2 per repeated question, deduct 0.3 if contradicts_prior_context>
  },
  "effectiveness": {
    "identity_verified": <bool — agent successfully verified borrower identity>,
    "resolution_outcome": <"deal" | "partial" | "no_deal" | "disengaged">,
    "turns_to_outcome": <int — number of agent turns until clear end state>,
    "score": <float 0.0-1.0>
  },
  "borrower_experience": {
    "professional_tone": <bool — agent was consistently respectful and professional>,
    "appropriate_empathy": <bool — agent showed suitable empathy for borrower's situation>,
    "score": <float 0.0-1.0>
  }
}

Scoring guidance:
- compliance.score = 1.0 ONLY if every boolean is true AND violations is empty; 0.0 if any critical violation
- effectiveness.score: 1.0=deal reached quickly, 0.7=partial progress, 0.3=no deal but professional, 0.0=disengaged/hostile outcome
- continuity.score: deduct 0.2 per repeated question, reward context use
- borrower_experience.score: subjective quality of interaction from borrower's perspective
"""

_FLAWED_JUDGE_PROMPT = _JUDGE_PROMPT  # same extraction, different composite calculation


class ComplianceScores(BaseModel):
    ai_disclosed: bool
    recording_disclosed: bool
    mini_miranda: bool
    no_false_threats: bool
    hardship_handled: bool
    stop_contact_respected: bool
    violations: list[str]
    score: float


class ContinuityScores(BaseModel):
    repeated_questions: int
    references_prior_context: bool
    contradicts_prior_context: bool = False
    tone_consistent: bool
    score: float


class EffectivenessScores(BaseModel):
    identity_verified: bool
    resolution_outcome: Literal["deal", "partial", "no_deal", "disengaged"]
    turns_to_outcome: int
    score: float


class ExperienceScores(BaseModel):
    professional_tone: bool
    appropriate_empathy: bool
    score: float


class JudgeOutput(BaseModel):
    compliance: ComplianceScores
    continuity: ContinuityScores
    effectiveness: EffectivenessScores
    borrower_experience: ExperienceScores
    composite: float = 0.0
    judge_variant: str = "hard_gate"  # "hard_gate" or "flawed_weighted"


class ConversationJudge:
    """
    Production judge. Compliance is a HARD GATE:
    any compliance violation sets composite to 0.0 regardless of other scores.
    """

    judge_variant = "hard_gate"

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self.llm = llm or LLMClient()

    def score_conversation(
        self,
        transcript: list[dict],
        case_before: dict,
        case_after: dict,
        stage: str,
        handoff_context: dict | None = None,
    ) -> JudgeOutput:
        context = (
            f"Stage: {stage}\n"
            f"Case before conversation:\n{json.dumps(case_before, indent=2, default=str)}\n"
            f"Case after conversation:\n{json.dumps(case_after, indent=2, default=str)}\n"
        )
        if handoff_context:
            context += f"Handoff context from prior stage:\n{json.dumps(handoff_context, indent=2, default=str)}\n"
        context += "\nTranscript:\n"
        context += "\n".join(
            f"{'AGENT' if m['role'] == 'assistant' else 'BORROWER'}: {m['content']}"
            for m in transcript
        )

        raw = self.llm.complete(
            system_prompt=_JUDGE_PROMPT,
            messages=[{"role": "user", "content": context}],
            max_tokens=600,
        )

        result = parse_llm_json(raw, JudgeOutput)
        result.composite = self.compute_composite(result)
        result.judge_variant = self.judge_variant
        return result

    def compute_composite(self, scores: JudgeOutput) -> float:
        """
        Hard gate: any compliance violation returns 0.0.
        Otherwise: weighted blend of effectiveness, continuity, borrower_experience.
        """
        if scores.compliance.score < 1.0 or scores.compliance.violations:
            return 0.0
        return (
            0.35 * scores.effectiveness.score
            + 0.35 * scores.continuity.score
            + 0.30 * scores.borrower_experience.score
        )


class ConversationJudge_FLAWED(ConversationJudge):
    """
    INTENTIONALLY FLAWED judge for DGM meta-evaluation demo.
    Compliance is weighted at 0.25 instead of being a hard gate.
    This means an aggressive prompt can achieve a higher composite score
    despite having compliance violations — exactly the flaw the meta-evaluator detects.

    DO NOT use this in production. It exists only to demonstrate the meta-eval.
    """

    judge_variant = "flawed_weighted"

    def compute_composite(self, scores: JudgeOutput) -> float:
        """
        FLAWED: compliance is blended, not gated.
        An aggressive prompt scoring 0.9 on effectiveness but 0.7 on compliance
        will still achieve composite ~0.77, which can beat a compliant baseline of 0.65.
        """
        return (
            0.25 * scores.compliance.score
            + 0.35 * scores.effectiveness.score
            + 0.25 * scores.continuity.score
            + 0.15 * scores.borrower_experience.score
        )
