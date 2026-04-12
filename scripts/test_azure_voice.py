"""
Standalone Azure Voice Live test — runs resolution agent voice session outside Temporal.

Usage:
    PYTHONPATH=. uv run python scripts/test_azure_voice.py

What happens:
    1. Loads resolution agent prompt from prompt_registry (or fallback to prompts/v1/resolution.txt)
    2. Starts Azure Voice Live session — agent speaks through your speakers
    3. You respond via microphone
    4. Say "goodbye" or let agent say "end_call" to finish
    5. Prints full transcript + extracted resolution outcome

Requirements:
    - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT in .env
    - Working microphone + speakers
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.llm.client import LLMClient
from src.models.case_file import CaseFile, Stage, DebtInfo, FinancialInfo, NegotiationLedger, ComplianceState
from src.agents.resolution import ResolutionAgent
from src.voice.azure_voice_client import AzureVoiceClient
from src.handoff.summarizer import build_handoff_packet

# Test case — mimics what Assessment agent would have built
TEST_CASE = CaseFile(
    borrower_id="voice_test_001",
    stage=Stage.RESOLUTION,
    attempt=1,
    identity_verified=True,
    partial_account="4321",
    phone_number="+917000035904",
    borrower_timezone="Asia/Kolkata",
    debt=DebtInfo(
        amount=12450.0,
        creditor="XYZ Bank",
        default_date="2025-01-15",
        allowed_actions=["settlement", "payment_plan", "hardship_referral"],
    ),
    financial=FinancialInfo(
        income_status="employed",
        monthly_income_est=50000.0,
        obligations=None,
        hardship_flags=[],
    ),
    negotiation=NegotiationLedger(
        offers_made=[],
        borrower_responses=[],
        commitments=[],
        objections=[],
    ),
    compliance=ComplianceState(
        ai_disclosed=True,
        recording_disclosed=True,
        stop_contact=False,
        hardship_offered=False,
    ),
    borrower_sentiment="cooperative",
    cooperation_level="medium",
)


def get_system_prompt() -> str:
    """Load resolution prompt from registry or fall back to file."""
    try:
        from src.storage.prompt_registry import get_current_prompt
        prompt = get_current_prompt("resolution")
        print("[prompt] Loaded from registry")
        return prompt
    except Exception as e:
        print(f"[prompt] Registry unavailable ({e}), loading from file")
        prompt_file = Path(__file__).parent.parent / "prompts" / "v1" / "resolution.txt"
        return prompt_file.read_text()


def main():
    print("Loading prompt...")
    system_prompt = get_system_prompt()

    # Inject handoff context into system prompt
    handoff = build_handoff_packet(TEST_CASE)
    handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)
    full_prompt = f"{system_prompt}\n\n--- HANDOFF CONTEXT ---\n{handoff_context}"

    print(f"\nBorrower: voice_test_001 | Debt: ₹{TEST_CASE.debt.amount:,.0f} to {TEST_CASE.debt.creditor}")
    print(f"Identity already verified | Account ends: {TEST_CASE.partial_account}")
    print()

    # Run voice session
    voice_client = AzureVoiceClient()
    call_result = voice_client.run_session(
        system_prompt=full_prompt,
        borrower_id=TEST_CASE.borrower_id,
    )

    if not call_result.transcript_turns:
        print("No transcript captured.")
        return

    # Extract resolution outcome
    print("Extracting resolution outcome...\n")
    llm = LLMClient()
    agent = ResolutionAgent(llm)
    messages = [
        {"role": "assistant" if t["role"] == "agent" else "user", "content": t["content"]}
        for t in call_result.transcript_turns
    ]
    updated_case = agent.extract_updates(messages, TEST_CASE)

    print("=" * 60)
    print("RESOLUTION OUTCOME")
    print("=" * 60)
    print(f"Stage: {updated_case.stage}")
    print(f"Identity verified: {updated_case.identity_verified}")
    print(f"AI disclosed: {updated_case.compliance.ai_disclosed}")
    print(f"Stop contact: {updated_case.compliance.stop_contact}")
    commitments = updated_case.negotiation.commitments
    if commitments:
        print(f"\nCommitments ({len(commitments)}):")
        for c in commitments:
            print(f"  {c}")
    else:
        print("\nNo commitments recorded")
    print(f"\nCall duration: {call_result.duration_seconds:.1f}s")
    print(f"Turns: {len(call_result.transcript_turns)}")


if __name__ == "__main__":
    main()
