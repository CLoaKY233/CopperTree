from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from src.compliance.checker import check_compliance_triggers, sanitize_borrower_input
from src.handoff.token_budget import enforce_budget
from src.llm.client import LLMClient
from src.models.case_file import CaseFile
from src.storage.prompt_registry import get_current_prompt

_COMPLIANCE_BLOCK_PATH = (
    Path(__file__).parent.parent.parent / "prompts" / "shared" / "compliance_block.txt"
)
_STOP_CONTACT_RESPONSE = (
    "I understand. I will note your request to cease contact immediately. "
    "You will receive a written confirmation. Thank you for letting us know."
)


class BudgetExceeded(Exception):
    pass


@dataclass
class ConversationBudget:
    max_turns: int = 30
    max_cost_usd: float = 0.50
    _turns: int = field(default=0, init=False, repr=False)
    _cost: float = field(default=0.0, init=False, repr=False)

    def record_turn(self, cost_usd: float = 0.0) -> None:
        self._turns += 1
        self._cost += cost_usd
        if self._turns > self.max_turns:
            raise BudgetExceeded(f"Turn limit ({self.max_turns}) reached")
        if self._cost > self.max_cost_usd:
            raise BudgetExceeded(
                f"Cost limit (${self.max_cost_usd:.2f}) reached — spent ${self._cost:.4f}"
            )


class ConversationIO(Protocol):
    def get_response(self, agent_message: str) -> str | None:
        """Return the borrower's next message, or None to end the conversation."""
        ...


class BaseAgent(ABC):
    """
    Synchronous base agent. Matches LLMClient.complete() which is synchronous.
    Subclasses implement extract_updates() and is_complete() for their stage.
    """

    agent_name: str
    max_turns: int = 30

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._compliance_block = _COMPLIANCE_BLOCK_PATH.read_text().strip()

    def load_system_prompt(self, handoff_context: str | None = None) -> str:
        """
        Load the current prompt from the registry, append the compliance block,
        then enforce token budget. Returns the final system prompt string.
        If handoff_context is provided, it is budget-checked alongside the prompt.
        """
        doc = get_current_prompt(self.agent_name)
        if doc is None:
            raise RuntimeError(f"No current prompt found for agent '{self.agent_name}'")

        prompt_text = doc["prompt_text"]
        full_prompt = f"{prompt_text}\n\n{self._compliance_block}"

        full_prompt, handoff_context = enforce_budget(full_prompt, handoff_context)

        if handoff_context:
            full_prompt = (
                f"{full_prompt}\n\n<prior_context>\n{handoff_context}\n</prior_context>"
            )

        return full_prompt

    def run_conversation(
        self,
        case_file: CaseFile,
        io: ConversationIO,
        handoff_context: str | None = None,
        budget: ConversationBudget | None = None,
    ) -> tuple[list[dict], CaseFile]:
        """
        Run the full multi-turn conversation. Returns (messages, updated_case_file).

        Compliance checks run deterministically on every borrower message BEFORE
        the LLM is called. If stop_contact is detected, the LLM is bypassed.
        """
        if budget is None:
            budget = ConversationBudget(max_turns=self.max_turns)

        system_prompt = self.load_system_prompt(handoff_context)
        messages: list[dict] = []
        injection_log: list[str] = []

        # Agent speaks first
        first_response = self.llm.complete(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=400,
        )
        budget.record_turn()
        messages.append({"role": "assistant", "content": first_response})

        while True:
            borrower_raw = io.get_response(
                first_response if len(messages) == 1 else messages[-1]["content"]
            )
            if borrower_raw is None:
                break

            borrower_text, flags = sanitize_borrower_input(borrower_raw)
            if flags:
                injection_log.extend(flags)

            triggers = check_compliance_triggers(borrower_text)

            if triggers["stop_contact"]:
                case_file.compliance.stop_contact = True
                messages.append({"role": "user", "content": borrower_text})
                messages.append(
                    {"role": "assistant", "content": _STOP_CONTACT_RESPONSE}
                )
                break

            if triggers["hardship_flag"] and not case_file.compliance.hardship_offered:
                case_file.financial.hardship_flags.append("borrower_self_reported")

            messages.append({"role": "user", "content": borrower_text})

            try:
                agent_response = self.llm.complete(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=400,
                )
            except BudgetExceeded:
                raise
            except Exception:
                # Transient LLM error — log and end conversation gracefully
                messages.append(
                    {
                        "role": "assistant",
                        "content": "I'm having a technical issue. Please allow us to follow up shortly.",
                    }
                )
                break

            budget.record_turn()
            messages.append({"role": "assistant", "content": agent_response})

            if self.is_complete(messages, case_file):
                break

        # Final structured extraction
        updated_case_file = self.extract_updates(messages, case_file)
        return messages, updated_case_file

    @abstractmethod
    def extract_updates(self, messages: list[dict], case_file: CaseFile) -> CaseFile:
        """
        Parse the completed conversation, extract structured data, and return
        an updated CaseFile. Uses a second LLM call with a structured extraction prompt.
        """

    @abstractmethod
    def is_complete(self, messages: list[dict], case_file: CaseFile) -> bool:
        """Return True to end the conversation after the last agent turn."""
