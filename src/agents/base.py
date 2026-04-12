import re
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

    def load_system_prompt(
        self,
        case_file: CaseFile | None = None,
        handoff_context: str | None = None,
    ) -> str:
        """
        Load the current prompt from the registry, inject template variables,
        append the compliance block, then enforce token budget.
        If handoff_context is provided, it is budget-checked alongside the prompt.
        """
        doc = get_current_prompt(self.agent_name)
        if doc is None:
            raise RuntimeError(f"No current prompt found for agent '{self.agent_name}'")

        prompt_text = doc["prompt_text"]

        # Inject case-specific template variables
        if case_file is not None:
            from src.config import settings
            currency = settings.currency_symbol
            prompt_text = prompt_text.replace("{{currency}}", currency)
            prompt_text = prompt_text.replace("{{debt_amount}}", f"{currency}{case_file.debt.amount:,.2f}")
            prompt_text = prompt_text.replace("{{creditor}}", case_file.debt.creditor)
            prompt_text = prompt_text.replace("{{account_ending}}", case_file.partial_account or "UNKNOWN")
            prompt_text = prompt_text.replace("{{borrower_id}}", case_file.borrower_id)

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
    ) -> tuple[list[dict], CaseFile, list[str]]:
        """
        Run the full multi-turn conversation. Returns (messages, updated_case_file).

        Compliance checks run deterministically on every borrower message BEFORE
        the LLM is called. If stop_contact is detected, the LLM is bypassed.
        """
        if budget is None:
            budget = ConversationBudget(max_turns=self.max_turns)

        system_prompt = self.load_system_prompt(case_file=case_file, handoff_context=handoff_context)
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

            if triggers.get("dispute_flag") and not case_file.dispute_validation_required:
                # FDCPA §809: dispute triggers validation notice obligation — halt collection
                case_file.dispute_validation_required = True
                messages.append({"role": "user", "content": borrower_text})
                messages.append({
                    "role": "assistant",
                    "content": (
                        "I've noted your dispute. As required by the Fair Debt Collection Practices Act, "
                        "we will send you a written validation notice with details about this debt. "
                        "Collection activity is paused pending your review of that notice."
                    ),
                })
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
            except Exception as e:
                # Transient LLM error — log and end conversation gracefully
                print(f"[ERROR] LLM call failed: {e}")
                messages.append(
                    {
                        "role": "assistant",
                        "content": "I'm having a technical issue. Please allow us to follow up shortly.",
                    }
                )
                break

            budget.record_turn()
            messages.append({"role": "assistant", "content": agent_response})

            # Post-LLM guardrail: reject amounts exceeding debt ceiling
            if case_file.debt and case_file.debt.amount:
                from src.config import settings as _cfg
                _cur = _cfg.currency_symbol
                amounts = re.findall(r'[\$₹₱€£]\s*([\d,]+(?:\.\d+)?)', agent_response)
                for amt_str in amounts:
                    try:
                        amt = float(amt_str.replace(',', ''))
                    except ValueError:
                        continue
                    if amt > case_file.debt.amount * 1.05:
                        corrected = (
                            f"I need to clarify — the total outstanding balance on this "
                            f"account is {_cur}{case_file.debt.amount:,.2f}. Let me present "
                            f"the correct options for resolving this."
                        )
                        messages[-1]["content"] = corrected
                        break

            if self.is_complete(messages, case_file):
                break

        # Final structured extraction
        updated_case_file = self.extract_updates(messages, case_file)
        return messages, updated_case_file, injection_log

    @abstractmethod
    def extract_updates(self, messages: list[dict], case_file: CaseFile) -> CaseFile:
        """
        Parse the completed conversation, extract structured data, and return
        an updated CaseFile. Uses a second LLM call with a structured extraction prompt.
        """

    @abstractmethod
    def is_complete(self, messages: list[dict], case_file: CaseFile) -> bool:
        """Return True to end the conversation after the last agent turn."""
