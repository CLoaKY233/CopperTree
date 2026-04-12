"""
Full 3-stage CopperTree pipeline — YOU are the borrower.

Stage 1: Assessment  — text chat in this terminal
Stage 2: Resolution  — voice via mic/speakers (Azure Voice Live)
Stage 3: Final Notice — text chat in this terminal

Usage:
    PYTHONPATH=. uv run python scripts/run_live.py
    PYTHONPATH=. uv run python scripts/run_live.py --borrower-id your_id

What happens:
    1. Loads (or seeds) a borrower case from MongoDB
    2. Runs Assessment: agent chats with you in terminal
    3. Runs Resolution: agent SPEAKS to you, you respond via mic
    4. Runs Final Notice: agent chats with you in terminal again
    5. Prints final outcome + transcript summary
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient

from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.final_notice import FinalNoticeAgent
from src.agents.resolution import ResolutionAgent
from src.agents.terminal_io import TerminalIO
from src.compliance.checker import check_contact_time
from src.compliance.pii_redactor import redact_messages
from src.config import settings
from src.handoff.summarizer import build_handoff_packet
from src.llm.client import LLMClient
from src.models.case_file import (
    CaseFile,
    ComplianceState,
    DebtInfo,
    FinancialInfo,
    NegotiationLedger,
    Stage,
)


def get_or_seed_case(borrower_id: str) -> CaseFile:
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    doc = db.case_files.find_one({"borrower_id": borrower_id})
    if doc:
        doc.pop("_id", None)
        case = CaseFile(**doc)
        if case.stage not in (Stage.ASSESSMENT, Stage.RESOLUTION, Stage.FINAL_NOTICE):
            print(
                f"[!] Case is at stage '{case.stage}' — resetting to ASSESSMENT for a fresh run."
            )
            case.stage = Stage.ASSESSMENT
            case.compliance = type(case.compliance)()
            case.dispute_validation_required = False
        return case

    # Seed a fresh case
    print(f"[!] No case found for '{borrower_id}' — seeding a test case.")
    case = CaseFile(
        borrower_id=borrower_id,
        stage=Stage.ASSESSMENT,
        attempt=1,
        identity_verified=False,
        partial_account="4321",
        borrower_timezone="Asia/Kolkata",
        debt=DebtInfo(
            amount=12450.0,
            creditor="XYZ Bank",
            default_date="2025-01-15",
            allowed_actions=["settlement", "payment_plan", "hardship_referral"],
        ),
        financial=FinancialInfo(),
        negotiation=NegotiationLedger(),
        compliance=ComplianceState(),
        borrower_sentiment="unknown",
        cooperation_level="unknown",
    )
    db.case_files.insert_one({"_id": borrower_id, **case.model_dump()})
    return case


def save_case(case: CaseFile) -> None:
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    db.case_files.update_one(
        {"_id": case.borrower_id},
        {
            "$set": {
                **case.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


def save_transcript(borrower_id: str, stage: str, messages: list, flags: list) -> None:
    client = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    db.transcripts.update_one(
        {"borrower_id": borrower_id, "stage": stage, "run": "live"},
        {
            "$set": {
                "messages": redact_messages(messages),
                "injection_flags": flags,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )


def print_banner(stage_num: int, title: str, description: str) -> None:
    print(f"\n{'=' * 65}")
    print(f"  STAGE {stage_num} OF 3 — {title}")
    print(f"  {description}")
    print(f"{'=' * 65}\n")


def run_pipeline(borrower_id: str) -> None:
    llm = LLMClient()
    case = get_or_seed_case(borrower_id)

    print(f"\n{'=' * 65}")
    print("  CopperTree Live Pipeline")
    print(f"  Borrower: {borrower_id}  |  Stage: {case.stage.value}")
    print(f"  Debt: ${case.debt.amount:,.0f} to {case.debt.creditor}")
    print(f"{'=' * 65}")

    # ── STAGE 1: ASSESSMENT ─────────────────────────────────────────────────
    if case.stage == Stage.ASSESSMENT:
        print_banner(
            1,
            "ASSESSMENT",
            "Text chat — the agent verifies your identity and assesses the debt.",
        )
        print("  Type your replies below. Type 'quit' to end early.\n")

        agent = AssessmentAgent(llm)
        io = TerminalIO(stage_label="Assessment Agent")
        budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)

        messages, case, flags = agent.run_conversation(
            case_file=case, io=io, budget=budget
        )
        save_transcript(borrower_id, "assessment", messages, flags)

        if case.compliance.stop_contact:
            print(
                "\n[Pipeline] Stop-contact requested — halting. Confirmation will be sent in writing."
            )
            save_case(case)
            return

        case.stage = Stage.RESOLUTION
        save_case(case)
        handoff = build_handoff_packet(case)
        print("\n[Pipeline] Assessment complete. Moving to Resolution (voice)...")
    else:
        handoff = build_handoff_packet(case)

    # ── STAGE 2: RESOLUTION (VOICE) ─────────────────────────────────────────
    if case.stage == Stage.RESOLUTION:
        print_banner(
            2,
            "RESOLUTION",
            "Voice call — speak via your mic, hear the agent through your speakers.",
        )
        print("  Press Ctrl+C to end the call early.\n")

        check_contact_time(case.borrower_timezone)  # FDCPA guard

        from src.storage.prompt_registry import get_current_prompt
        from src.voice.azure_voice_client import AzureVoiceClient

        system_prompt_doc = get_current_prompt("resolution")
        system_prompt = system_prompt_doc["prompt_text"] if system_prompt_doc else ""
        # Inject template variables into the voice system prompt
        from src.config import settings as _cfg

        _cur = _cfg.currency_symbol
        system_prompt = system_prompt.replace("{{currency}}", _cur)
        system_prompt = system_prompt.replace(
            "{{debt_amount}}", f"{_cur}{case.debt.amount:,.2f}"
        )
        system_prompt = system_prompt.replace("{{creditor}}", case.debt.creditor)
        system_prompt = system_prompt.replace(
            "{{account_ending}}", case.partial_account or ""
        )
        system_prompt = system_prompt.replace("{{borrower_id}}", case.borrower_id)
        handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)
        full_system = (
            f"{system_prompt}\n\n<prior_context>\n{handoff_context}\n</prior_context>"
        )

        voice_client = AzureVoiceClient()
        call_result = voice_client.run_session(
            system_prompt=full_system, borrower_id=borrower_id
        )

        resolution_agent = ResolutionAgent(llm)
        messages = [
            {
                "role": "assistant" if t["role"] == "agent" else "user",
                "content": t["content"],
            }
            for t in call_result.transcript_turns
        ]
        case = resolution_agent.extract_updates(messages, case)
        save_transcript(borrower_id, "resolution", messages, [])

        if case.compliance.stop_contact:
            print("\n[Pipeline] Stop-contact requested during resolution — halting.")
            save_case(case)
            return

        if case.stage != Stage.FLAGGED:
            case.stage = Stage.FINAL_NOTICE
        save_case(case)
        handoff = build_handoff_packet(case)

        commitments = case.negotiation.commitments
        if commitments and commitments[-1].get("outcome") == "settled":
            print("\n[Pipeline] Deal agreed during resolution — pipeline complete!")
            _print_outcome(case)
            return

        print("\n[Pipeline] Resolution complete. Moving to Final Notice (text)...")

    # ── STAGE 3: FINAL NOTICE ───────────────────────────────────────────────
    if case.stage == Stage.FINAL_NOTICE:
        print_banner(
            3, "FINAL NOTICE", "Text chat — last opportunity before legal referral."
        )
        print("  Type your replies below. Type 'quit' to end early.\n")

        handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)
        agent = FinalNoticeAgent(llm)
        io = TerminalIO(stage_label="Final Notice Agent")
        budget = ConversationBudget(max_turns=8, max_cost_usd=0.75)

        messages, case, flags = agent.run_conversation(
            case_file=case, io=io, handoff_context=handoff_context, budget=budget
        )
        save_transcript(borrower_id, "final_notice", messages, flags)

        if case.compliance.stop_contact:
            print("\n[Pipeline] Stop-contact requested — halting.")
            save_case(case)
            return

        case.stage = Stage.COMPLETE
        save_case(case)

    _print_outcome(case)


def _print_outcome(case: CaseFile) -> None:
    print(f"\n{'=' * 65}")
    print("  PIPELINE COMPLETE")
    print(f"  Final stage: {case.stage.value}")
    commitments = case.negotiation.commitments
    if commitments:
        last = commitments[-1]
        print(f"  Outcome: {last.get('outcome', 'unknown')}")
        if last.get("commitment_amount"):
            print(f"  Amount: ${last['commitment_amount']:,.2f}")
        if last.get("commitment_type"):
            print(f"  Type: {last['commitment_type']}")
    else:
        print("  Outcome: no commitment reached")
    print(f"  Stop-contact: {case.compliance.stop_contact}")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full CopperTree pipeline with you as the borrower."
    )
    parser.add_argument(
        "--borrower-id", default="live_borrower_001", help="Borrower ID to load/seed"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset borrower case to ASSESSMENT stage"
    )
    args = parser.parse_args()

    if args.reset:
        client = MongoClient(settings.mongo_uri)
        db = client[settings.mongo_db]
        db.case_files.delete_one({"_id": args.borrower_id})
        db.case_files.delete_one({"borrower_id": args.borrower_id})
        db.transcripts.delete_many({"borrower_id": args.borrower_id})
        print(f"Reset: {args.borrower_id} → deleted (will re-seed fresh)")

    run_pipeline(args.borrower_id)
