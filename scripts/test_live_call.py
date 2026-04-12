"""
Quick live call test — bypasses Temporal, calls borrower directly via Retell.

Usage:
    EVAL_MODE=false PYTHONPATH=. uv run python scripts/test_live_call.py

What it does:
    1. Seeds a test case with your real phone number
    2. Calls run_resolution() directly (no Temporal needed)
    3. Prints transcript + outcome after call ends

Requirements:
    - RETELL_API_KEY, RETELL_AGENT_ID, RETELL_PHONE_NUMBER set in .env
    - Webhook server running (or EVAL_MODE=false uses polling fallback)
    - Real Retell FROM number purchased on dashboard
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timezone

from src.config import settings
from src.llm.client import LLMClient
from src.models.case_file import CaseFile, Stage
from src.agents.resolution import ResolutionAgent
from src.handoff.summarizer import build_handoff_packet
from src.voice.retell_client import RetellVoiceClient

# ── Test case ────────────────────────────────────────────────────────────────
TEST_CASE = CaseFile(
    borrower_id="live_test_001",
    stage=Stage.RESOLUTION,
    attempt=1,
    identity_verified=True,           # already verified in assessment
    partial_account="4321",
    phone_number="+917000035904",      # your number
    borrower_timezone="Asia/Kolkata",
    debt=dict(
        amount=12450.0,
        creditor="XYZ Bank",
        default_date="2025-01-15",
        allowed_actions=["settlement", "payment_plan", "hardship_referral"],
    ),
    financial=dict(
        income_status="employed",
        monthly_income_est=50000.0,
        obligations=None,
        hardship_flags=[],
    ),
    negotiation=dict(
        offers_made=[],
        borrower_responses=[],
        commitments=[],
        objections=[],
    ),
    compliance=dict(
        ai_disclosed=True,             # disclosed in assessment
        recording_disclosed=True,
        stop_contact=False,
        hardship_offered=False,
    ),
    borrower_sentiment="cooperative",
    cooperation_level="medium",
)

def main():
    eval_mode = os.environ.get("EVAL_MODE", "false").lower() == "true"
    print(f"\n{'='*60}")
    print(f"CopperTree Live Call Test")
    print(f"EVAL_MODE={eval_mode}")
    print(f"Target: {TEST_CASE.phone_number}")
    print(f"Agent ID: {settings.retell_agent_id}")
    print(f"From: {settings.retell_phone_number}")
    print(f"{'='*60}\n")

    if not eval_mode:
        if not settings.retell_agent_id:
            print("ERROR: RETELL_AGENT_ID not set")
            return
        if not settings.retell_phone_number or settings.retell_phone_number == "+1XXXXXXXXXX":
            print("ERROR: RETELL_PHONE_NUMBER not set — buy a number from Retell dashboard first")
            return

    llm = LLMClient()

    # Build handoff context (simulates what assessment stage would provide)
    handoff = build_handoff_packet(TEST_CASE)
    handoff_json = handoff.model_dump_json()
    handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)

    print("Handoff context:")
    print(handoff_context[:500] + "...\n" if len(handoff_context) > 500 else handoff_context)

    if eval_mode:
        from src.agents.simulator import SimulatedBorrower
        from src.agents.base import ConversationBudget

        print("Running TEXT simulation (EVAL_MODE=true)...\n")
        agent = ResolutionAgent(llm)
        borrower_io = SimulatedBorrower(
            llm=llm,
            persona_description=(
                "You are a borrower being contacted about a $12,450 debt to XYZ Bank. "
                "You are cooperative and employed. You want to explore payment plan options. "
                "Account ends in 4321. Your identity was already verified."
            ),
        )
        budget = ConversationBudget(max_turns=12, max_cost_usd=1.50)
        messages, updated_case, injection_flags = agent.run_conversation(
            case_file=TEST_CASE,
            io=borrower_io,
            handoff_context=handoff_context,
            budget=budget,
        )
        print("\n── Transcript ──")
        for m in messages:
            role = "Agent" if m["role"] == "assistant" else "Borrower"
            print(f"{role}: {m['content']}\n")
        print(f"\n── Outcome ──")
        print(f"Stage: {updated_case.stage}")
        print(f"Commitments: {updated_case.negotiation.get('commitments', [])}")

    else:
        print("Making REAL call via Retell...\n")
        voice_client = RetellVoiceClient()
        call_id = voice_client.make_call(
            to_number=TEST_CASE.phone_number,
            metadata={"borrower_id": TEST_CASE.borrower_id, "stage": "resolution"},
        )
        print(f"Call initiated. call_id={call_id}")
        print("Waiting for call to complete (polling every 3s, timeout 600s)...")
        print("Answer your phone!\n")

        call_result = voice_client.get_transcript(call_id)

        print(f"\n── Call Result ──")
        print(f"Status: {call_result.status}")
        print(f"Duration: {call_result.duration_seconds}s")
        print(f"Call Successful: {call_result.call_successful}")
        print(f"User Sentiment: {call_result.user_sentiment}")
        print(f"\nSummary: {call_result.call_summary}")
        print(f"\n── Transcript ──")
        for t in call_result.transcript_turns:
            role = "Agent" if t["role"] == "agent" else "You"
            print(f"{role}: {t['content']}\n")

        # Extract resolution outcome
        agent = ResolutionAgent(llm)
        messages = [
            {"role": "assistant" if t["role"] == "agent" else "user", "content": t["content"]}
            for t in call_result.transcript_turns
        ]
        updated_case = agent.extract_updates(messages, TEST_CASE)
        print(f"\n── Extracted Outcome ──")
        print(f"Stage: {updated_case.stage}")
        print(f"Commitments: {updated_case.negotiation.get('commitments', [])}")


if __name__ == "__main__":
    main()
