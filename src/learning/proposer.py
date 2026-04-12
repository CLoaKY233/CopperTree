"""
Prompt proposer — uses LLM to generate a targeted mutation of an agent prompt
based on failure analysis from the worst-performing evaluation conversations.
"""

from typing import Optional

from pydantic import BaseModel

from src.llm.client import LLMClient
from src.llm.utils import parse_llm_json

_PROPOSER_PROMPT = """\
You are a prompt engineer improving a debt collections AI agent.

Current prompt:
{current_prompt}

Failure analysis (worst-performing conversations, sorted by composite score ascending):
{failure_analysis}

Your task: propose ONE specific, small modification to the prompt that directly addresses
the most common failure pattern in the worst conversations above.

Rules (MANDATORY — violating these disqualifies the proposal):
1. Keep ALL compliance instructions completely intact — do not remove, weaken, or reword any legal requirement
2. Change exactly ONE aspect of the prompt (tone, a specific instruction, handling of a scenario)
3. The modified prompt must not exceed {token_budget} tokens
4. Do not add new compliance instructions — the compliance block is appended separately

Return ONLY valid JSON — no explanation, no markdown fences:
{{"change_description": "<one sentence describing what changed and why>", "modified_prompt": "<full updated prompt text>"}}
"""


class ProposerOutput(BaseModel):
    change_description: str
    modified_prompt: str


class PromptProposer:
    """
    Analyzes the worst eval conversations and proposes a targeted prompt mutation.

    The proposer follows a strict single-change rule to ensure:
    1. Changes are attributable (we know what caused any improvement/regression)
    2. Compliance instructions are never weakened
    3. The learning signal is clean and interpretable
    """

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self.llm = llm or LLMClient()

    def propose(
        self,
        current_prompt: str,
        worst_conversations: list[dict],
        token_budget: int = 1500,
    ) -> str:
        """
        Propose a modified prompt addressing failures in the worst conversations.

        Args:
            current_prompt: the current active prompt text (without compliance block)
            worst_conversations: list of score dicts from the worst N eval conversations
            token_budget: max tokens allowed in the modified prompt

        Returns:
            modified prompt text (just the prompt, not JSON wrapper)
        """
        failure_summary = self._summarize_failures(worst_conversations)

        filled_prompt = _PROPOSER_PROMPT.format(
            current_prompt=current_prompt,
            failure_analysis=failure_summary,
            token_budget=token_budget,
        )

        raw = self.llm.complete(
            system_prompt=filled_prompt,
            messages=[{"role": "user", "content": "Propose the improvement."}],
            max_tokens=2000,
        )

        output = parse_llm_json(raw, ProposerOutput)
        print(f"[proposer] Change: {output.change_description}")
        return output.modified_prompt

    def _summarize_failures(self, worst_conversations: list[dict]) -> str:
        """Build a concise failure analysis from the worst conversation score dicts."""
        lines = []
        for i, score in enumerate(worst_conversations[:10], 1):
            persona = score.get("persona", "unknown")
            composite = score.get("composite", 0.0)
            violations = []

            compliance = score.get("compliance", {})
            if isinstance(compliance, dict):
                violations = compliance.get("violations", [])
                if not compliance.get("ai_disclosed"):
                    violations.append("AI not disclosed")
                if not compliance.get("mini_miranda"):
                    violations.append("Mini-Miranda missing")

            effectiveness = score.get("effectiveness", {})
            outcome = (
                effectiveness.get("resolution_outcome", "unknown")
                if isinstance(effectiveness, dict)
                else "unknown"
            )

            lines.append(
                f"  {i}. persona={persona}, composite={composite:.3f}, "
                f"outcome={outcome}, violations={violations}"
            )

        return "\n".join(lines) if lines else "No failure data available."
