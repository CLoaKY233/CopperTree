import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.workflows.activities import run_assessment, run_final_notice, run_resolution


@workflow.defn
class CollectionsWorkflow:
    """
    Orchestrates the full debt collections pipeline:
      Stage 1: Assessment (Agent 1 — chat)
      Stage 2: Resolution (Agent 2 — voice/Retell)
      Stage 3: Final Notice (Agent 3 — chat)

    Outcome-based transitions per spec:
      - stop_contact at any stage → EXIT immediately
      - Resolution deal agreed ("settled") → EXIT, log agreement (skip Final Notice)
      - Resolution no deal → proceed to Final Notice
      - Final Notice resolved → EXIT, log resolution
      - Final Notice no resolution → EXIT, flag for legal/write-off

    Temporal handles retries, timeouts, and durability.
    Each stage is a sync activity run in a thread executor.
    """

    @workflow.run
    async def run(self, borrower_id: str) -> dict:
        retry = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=2.0,
        )

        # Stage 1 — Assessment
        assessment = await workflow.execute_activity(
            run_assessment,
            borrower_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry,
        )

        if assessment.get("stop_contact"):
            return {
                "outcome": "stop_contact",
                "stage": "assessment",
                "borrower_id": borrower_id,
            }

        # Stage 2 — Resolution (voice)
        resolution_retry = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=2.0,
            non_retryable_error_types=["ApplicationError"],
        )
        assessment_handoff_json = json.dumps(assessment.get("handoff", {}))
        resolution = await workflow.execute_activity(
            run_resolution,
            args=[borrower_id, assessment_handoff_json],
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=resolution_retry,
        )

        if resolution.get("stop_contact"):
            return {
                "outcome": "stop_contact",
                "stage": "resolution",
                "borrower_id": borrower_id,
            }

        # Gap 4: deal agreed at Resolution → EXIT (skip Final Notice)
        resolution_outcome = resolution.get("resolution_outcome")
        if resolution_outcome == "settled":
            return {
                "outcome": "deal_agreed",
                "stage": "resolution",
                "borrower_id": borrower_id,
                "commitments": resolution.get("commitments", []),
            }

        # Stage 3 — Final Notice
        handoff_json = json.dumps(resolution.get("handoff", {}))
        final = await workflow.execute_activity(
            run_final_notice,
            args=[borrower_id, handoff_json],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry,
        )

        if final.get("stop_contact"):
            return {
                "outcome": "stop_contact",
                "stage": "final_notice",
                "borrower_id": borrower_id,
            }

        # Gap 5: Final Notice resolved vs legal/write-off
        final_decision = final.get("final_decision")
        if final_decision in ("settled", "payment_plan", "hardship_referred"):
            return {
                "outcome": "resolved",
                "stage": "final_notice",
                "borrower_id": borrower_id,
                "commitments": final.get("commitments", []),
            }

        # No resolution after Final Notice → flag for legal referral / write-off
        return {
            "outcome": "legal_referral",
            "stage": "final_notice",
            "borrower_id": borrower_id,
            "reason": "no resolution after final notice — flagged for legal action or write-off",
        }
