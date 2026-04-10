from datetime import datetime, timezone

from temporalio import activity

from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.final_notice import FinalNoticeAgent
from src.agents.simulator import SimulatedBorrower
from src.handoff.summarizer import build_handoff_packet
from src.llm.client import LLMClient
from src.models.case_file import CaseFile, Stage
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
        {"$set": {**case_file.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}},
    )


@activity.defn
def run_assessment(borrower_id: str) -> dict:
    llm = LLMClient()
    agent = AssessmentAgent(llm)
    case_file = get_case(borrower_id)

    borrower_io = SimulatedBorrower(
        llm=llm,
        persona_description=(
            "You are a borrower being contacted about an outstanding debt. "
            "Be cooperative but hesitant. Answer questions briefly. "
            "When asked to verify your account, confirm it ends in 4521."
        ),
    )
    budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)

    messages, updated_case = agent.run_conversation(
        case_file=case_file,
        io=borrower_io,
        budget=budget,
    )

    transcripts.insert_one({
        "borrower_id": borrower_id,
        "stage": "assessment",
        "messages": messages,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    updated_case.stage = Stage.RESOLUTION
    save_case(updated_case)

    handoff = build_handoff_packet(updated_case)

    return {
        "status": "complete",
        "handoff": handoff.model_dump(mode="json"),
        "stop_contact": updated_case.compliance.stop_contact,
    }


@activity.defn
def run_final_notice(borrower_id: str, handoff_json: str) -> dict:
    llm = LLMClient()
    agent = FinalNoticeAgent(llm)
    case_file = get_case(borrower_id)

    handoff_context = handoff_json

    borrower_io = SimulatedBorrower(
        llm=llm,
        persona_description=(
            "You are a borrower receiving a final notice about an outstanding debt. "
            "You are tired of being contacted. Consider the situation carefully. "
            "You may be willing to make a small payment arrangement if terms are reasonable."
        ),
    )
    budget = ConversationBudget(max_turns=8, max_cost_usd=0.75)

    messages, updated_case = agent.run_conversation(
        case_file=case_file,
        io=borrower_io,
        handoff_context=handoff_context,
        budget=budget,
    )

    transcripts.insert_one({
        "borrower_id": borrower_id,
        "stage": "final_notice",
        "messages": messages,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    updated_case.stage = Stage.COMPLETE
    save_case(updated_case)

    return {
        "status": "complete",
        "stop_contact": updated_case.compliance.stop_contact,
        "commitments": updated_case.negotiation.commitments,
    }
