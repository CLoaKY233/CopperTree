"""
Standalone test harness for Agent 1 (Assessment).
Runs a simulated conversation using a persona-driven LLM borrower.
No Temporal required — pure Python.

Usage:
    uv run python scripts/test_agent1.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.client import LLMClient
from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.simulator import SimulatedBorrower
from src.models.case_file import CaseFile, DebtInfo

PERSONAS = [
    {
        "name": "cooperative",
        "description": (
            "You are a borrower who owes $12,450 to XYZ Bank. You are cooperative and "
            "slightly anxious but willing to engage. You work part-time making about $2,800/month. "
            "You have rent ($1,200/mo) and a car payment ($350/mo). "
            "When asked to verify your account, confirm your account ends in 4521. "
            "Respond naturally in 1-3 sentences."
        ),
    },
    {
        "name": "evasive",
        "description": (
            "You are a borrower who owes money. You are evasive and reluctant to engage. "
            "You give short, deflecting answers. You don't want to discuss finances. "
            "After 3 exchanges, say you need to go and end the conversation. "
            "Respond in 1-2 sentences."
        ),
    },
    {
        "name": "hardship",
        "description": (
            "You are a borrower who recently lost your job three weeks ago. You are genuinely "
            "distressed and overwhelmed. You mention your job loss early. You don't know how "
            "you'll pay rent, let alone a debt. You are cooperative but desperate. "
            "When asked to verify your account, say it ends in 4521. "
            "Respond in 1-3 sentences."
        ),
    },
]




def score_conversation(messages: list[dict]) -> dict[str, bool]:
    """Auto-score compliance disclosures and key behaviors from message content."""
    full_text = " ".join(
        m["content"] for m in messages if m["role"] == "assistant"
    ).lower()
    return {
        "ai_disclosed": any(w in full_text for w in ["ai", "automated system", "artificial intelligence", "virtual"]),
        "recording_disclosed": "record" in full_text,
        "mini_miranda": "attempt to collect a debt" in full_text,
        "identity_attempted": any(p in full_text for p in ["last 4", "account number", "verify your identity", "confirm your"]),
        "hardship_mentioned": any(w in full_text for w in ["hardship", "financial difficulty", "assistance program"]),
    }


def run_persona(persona: dict, llm: LLMClient) -> None:
    print(f"\n{'='*60}")
    print(f"PERSONA: {persona['name'].upper()}")
    print(f"{'='*60}")

    case_file = CaseFile(
        borrower_id="test_001",
        partial_account="4521",
        debt=DebtInfo(amount=12450.0, creditor="XYZ Bank", default_date="2025-01-15"),
    )

    borrower_io = SimulatedBorrower(llm, persona["description"])
    budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)
    agent = AssessmentAgent(llm)

    messages, updated_case = agent.run_conversation(
        case_file=case_file,
        io=borrower_io,
        budget=budget,
    )

    print("\n--- CONVERSATION ---")
    for m in messages:
        role = "AGENT" if m["role"] == "assistant" else "BORROWER"
        print(f"\n{role}:\n{m['content']}")

    print("\n--- EXTRACTED CASE FILE UPDATES ---")
    print(f"  identity_verified:    {updated_case.identity_verified}")
    print(f"  income_status:        {updated_case.financial.income_status}")
    print(f"  monthly_income_est:   {updated_case.financial.monthly_income_est}")
    print(f"  hardship_flags:       {updated_case.financial.hardship_flags}")
    print(f"  borrower_sentiment:   {updated_case.borrower_sentiment}")
    print(f"  cooperation_level:    {updated_case.cooperation_level}")
    print(f"  stop_contact:         {updated_case.compliance.stop_contact}")
    print(f"  ai_disclosed:         {updated_case.compliance.ai_disclosed}")
    print(f"  recording_disclosed:  {updated_case.compliance.recording_disclosed}")

    scores = score_conversation(messages)
    print("\n--- AUTO-SCORES ---")
    for key, passed in scores.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {key}")


def main() -> None:
    print("CopperTree — Agent 1 Test Harness")
    llm = LLMClient()

    for persona in PERSONAS:
        try:
            run_persona(persona, llm)
        except Exception as e:
            print(f"\n[ERROR] Persona '{persona['name']}' failed: {e}")

    print(f"\n{'='*60}")
    print("Test run complete.")


if __name__ == "__main__":
    main()
