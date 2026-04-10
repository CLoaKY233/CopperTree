import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.workflows.activities import run_assessment, run_final_notice


@workflow.defn
class CollectionsWorkflow:
    """
    Orchestrates the full debt collections pipeline:
      Stage 1: Assessment (Agent 1 — chat)
      Stage 2: Resolution (Agent 2 — voice/Retell) — STUBBED
      Stage 3: Final Notice (Agent 3 — chat)

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
            return {"outcome": "stop_contact", "stage": "assessment", "borrower_id": borrower_id}

        # Stage 2 — Resolution (voice) is not yet implemented
        # When ready, insert: await workflow.execute_activity(run_resolution, ...)

        # Stage 3 — Final Notice
        handoff_json = json.dumps(assessment.get("handoff", {}))
        final = await workflow.execute_activity(
            run_final_notice,
            args=[borrower_id, handoff_json],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry,
        )

        return {
            "outcome": final.get("status", "complete"),
            "stage": "final_notice",
            "borrower_id": borrower_id,
            "stop_contact": final.get("stop_contact", False),
            "commitments": final.get("commitments", []),
        }
