import json
import os
from datetime import datetime, timezone

from temporalio import activity

from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.final_notice import FinalNoticeAgent
from src.agents.resolution import ResolutionAgent
from src.agents.simulator import SimulatedBorrower
from src.agents.terminal_io import TerminalIO
from src.compliance.checker import check_contact_time
from src.compliance.pii_redactor import redact_messages
from src.handoff.summarizer import build_handoff_packet
from src.llm.client import LLMClient
from src.models.case_file import CaseFile, Stage
from src.models.handoff import HandoffPacket
from src.storage.mongo import case_files, transcripts


def get_case(borrower_id: str) -> CaseFile:
    """Load a CaseFile from MongoDB. Type-checks borrower_id (MongoDB injection guard)."""
    if not isinstance(borrower_id, str):
        raise TypeError(f"borrower_id must be str, got {type(borrower_id)}")
    doc = case_files.find_one({"_id": borrower_id})
    if doc is None:
        raise ValueError(f"No case file found for borrower_id={borrower_id!r}")
    doc.pop("_id", None)
    return CaseFile(**doc)


def save_case(case_file: CaseFile) -> None:
    case_files.update_one(
        {"_id": case_file.borrower_id},
        {
            "$set": {
                **case_file.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@activity.defn
def run_assessment(borrower_id: str) -> dict:
    llm = LLMClient()
    agent = AssessmentAgent(llm)
    case_file = get_case(borrower_id)

    if case_file.stage != Stage.ASSESSMENT:
        return {
            "status": "skipped",
            "reason": f"stage is {case_file.stage}, expected ASSESSMENT",
            "stop_contact": case_file.compliance.stop_contact,
        }

    eval_mode = os.environ.get("EVAL_MODE", "false").lower() == "true"
    if eval_mode:
        borrower_io = SimulatedBorrower(
            llm=llm,
            persona_description=(
                "You are a borrower being contacted about an outstanding debt. "
                "Be cooperative but hesitant. Answer questions briefly. "
                "When asked to verify your account, confirm it ends in 4521."
            ),
        )
    else:
        print("\n" + "="*65)
        print("STAGE 1 OF 3 — ASSESSMENT (text chat)")
        print("The collections agent will type to you. You type back.")
        print("Type 'quit' or press Ctrl+C to end early.")
        print("="*65 + "\n")
        borrower_io = TerminalIO(stage_label="Assessment Agent")
    budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)

    messages, updated_case, injection_flags = agent.run_conversation(
        case_file=case_file,
        io=borrower_io,
        budget=budget,
    )

    workflow_run_id = activity.info().workflow_run_id
    transcripts.update_one(
        {
            "borrower_id": borrower_id,
            "stage": "assessment",
            "workflow_run_id": workflow_run_id,
        },
        {
            "$setOnInsert": {
                "messages": redact_messages(messages),
                "injection_flags": injection_flags,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    updated_case.stage = Stage.RESOLUTION
    save_case(updated_case)

    handoff = build_handoff_packet(updated_case)

    return {
        "status": "complete",
        "handoff": handoff.model_dump(mode="json"),
        "stop_contact": updated_case.compliance.stop_contact,
    }


@activity.defn
def run_resolution(borrower_id: str, handoff_json: str) -> dict:
    # Guard 1: deserialize handoff (fail fast on bad data)
    try:
        handoff = HandoffPacket.model_validate_json(handoff_json)
        handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)
    except Exception as e:
        raise ValueError(f"run_resolution received invalid handoff_json: {e}") from e

    llm = LLMClient()
    case_file = get_case(borrower_id)

    # Guard 2: stage check (idempotency)
    if case_file.stage != Stage.RESOLUTION:
        return {
            "status": "skipped",
            "reason": f"stage is {case_file.stage}, expected RESOLUTION",
            "stop_contact": case_file.compliance.stop_contact,
        }

    # Guard 3: stop_contact (FDCPA)
    if case_file.compliance.stop_contact:
        return {"status": "stop_contact", "stop_contact": True}

    # Guard 4: time-of-day (FDCPA §805(a)(1))
    check_contact_time(case_file.borrower_timezone)

    eval_mode = os.environ.get("EVAL_MODE", "false").lower() == "true"

    if eval_mode:
        # Text simulation via SimulatedBorrower
        agent = ResolutionAgent(llm)
        borrower_io = SimulatedBorrower(
            llm=llm,
            persona_description=(
                "You are a borrower being contacted about an outstanding debt. "
                "You are cooperative and willing to discuss payment options. "
                "Ask about payment plans and what options are available."
            ),
        )
        budget = ConversationBudget(max_turns=12, max_cost_usd=1.50)
        messages, updated_case, injection_flags = agent.run_conversation(
            case_file=case_file,
            io=borrower_io,
            handoff_context=handoff_context,
            budget=budget,
        )
    else:
        # Production: Azure Voice Live session (user speaks via mic/speakers, no phone needed)
        from src.voice.azure_voice_client import AzureVoiceClient
        from src.storage.prompt_registry import get_current_prompt

        system_prompt = get_current_prompt("resolution")
        voice_client = AzureVoiceClient()
        call_result = voice_client.run_session(
            system_prompt=system_prompt,
            borrower_id=borrower_id,
        )

        # Extract updates from voice transcript
        agent = ResolutionAgent(llm)
        messages = [
            {"role": "assistant" if t["role"] == "agent" else "user", "content": t["content"]}
            for t in call_result.transcript_turns
        ]
        updated_case = agent.extract_updates(messages, case_file)
        injection_flags = []

    workflow_run_id = activity.info().workflow_run_id
    transcripts.update_one(
        {
            "borrower_id": borrower_id,
            "stage": "resolution",
            "workflow_run_id": workflow_run_id,
        },
        {
            "$setOnInsert": {
                "messages": redact_messages(messages),
                "injection_flags": injection_flags,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    if updated_case.stage != Stage.FLAGGED:
        updated_case.stage = Stage.FINAL_NOTICE
    save_case(updated_case)

    handoff_out = build_handoff_packet(updated_case)
    # Extract resolution outcome for workflow outcome-based branching
    commitments = updated_case.negotiation.commitments
    resolution_outcome = commitments[-1].get("outcome") if commitments else None
    return {
        "status": "complete",
        "handoff": handoff_out.model_dump(mode="json"),
        "stop_contact": updated_case.compliance.stop_contact,
        "resolution_outcome": resolution_outcome,
        "commitments": commitments,
    }


@activity.defn
def run_final_notice(borrower_id: str, handoff_json: str) -> dict:
    llm = LLMClient()
    agent = FinalNoticeAgent(llm)
    case_file = get_case(borrower_id)

    if case_file.stage != Stage.FINAL_NOTICE:
        return {
            "status": "skipped",
            "reason": f"stage is {case_file.stage}, expected FINAL_NOTICE",
            "stop_contact": case_file.compliance.stop_contact,
        }

    if case_file.compliance.stop_contact:
        return {"status": "stop_contact", "stop_contact": True}

    try:
        handoff = HandoffPacket.model_validate_json(handoff_json)
        handoff_context = json.dumps(handoff.model_dump(mode="json"), indent=2)
    except Exception as e:
        raise ValueError(f"run_final_notice received invalid handoff_json: {e}") from e

    eval_mode_final = os.environ.get("EVAL_MODE", "false").lower() == "true"
    if eval_mode_final:
        borrower_io = SimulatedBorrower(
            llm=llm,
            persona_description=(
                "You are a borrower receiving a final notice about an outstanding debt. "
                "You are tired of being contacted. Consider the situation carefully. "
                "You may be willing to make a small payment arrangement if terms are reasonable."
            ),
        )
    else:
        print("\n" + "="*65)
        print("STAGE 3 OF 3 — FINAL NOTICE (text chat)")
        print("This is the agent's last contact before legal action.")
        print("Type 'quit' or press Ctrl+C to end early.")
        print("="*65 + "\n")
        borrower_io = TerminalIO(stage_label="Final Notice Agent")
    budget = ConversationBudget(max_turns=8, max_cost_usd=0.75)

    messages, updated_case, injection_flags = agent.run_conversation(
        case_file=case_file,
        io=borrower_io,
        handoff_context=handoff_context,
        budget=budget,
    )

    workflow_run_id = activity.info().workflow_run_id
    transcripts.update_one(
        {
            "borrower_id": borrower_id,
            "stage": "final_notice",
            "workflow_run_id": workflow_run_id,
        },
        {
            "$setOnInsert": {
                "messages": redact_messages(messages),
                "injection_flags": injection_flags,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    updated_case.stage = Stage.COMPLETE
    save_case(updated_case)

    commitments = updated_case.negotiation.commitments
    final_decision = commitments[-1].get("outcome") if commitments else None
    return {
        "status": "complete",
        "stop_contact": updated_case.compliance.stop_contact,
        "commitments": commitments,
        "final_decision": final_decision,
    }
