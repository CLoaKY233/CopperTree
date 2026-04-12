"""
Learning loop — orchestrates one iteration of the prompt improvement cycle:
  1. Baseline eval
  2. Failure analysis
  3. Candidate proposal
  4. Candidate eval (same seeds, paired comparison)
  5. Statistical gate
  6. Promote or reject
  7. Log result
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.evaluation.judge import ConversationJudge
from src.evaluation.runner import EvalRunner, EvalRunResult
from src.learning.proposer import PromptProposer
from src.learning.stats import should_promote
from src.storage.mongo import eval_runs as eval_runs_collection
from src.storage.prompt_registry import (
    get_current_prompt,
    promote_version,
    save_new_version,
)

try:
    from src.storage.mongo import db

    _learning_iterations = db["learning_iterations"]
except Exception:
    _learning_iterations = None


@dataclass
class IterationResult:
    agent: str
    baseline_version: str
    candidate_version: str
    decision: str              # "promoted" | "rejected"
    reason: str
    baseline_mean: float
    candidate_mean: float
    baseline_compliance_rate: float
    candidate_compliance_rate: float
    n_conversations: int
    seed: int


class LearningLoop:
    """
    Runs one iteration of the prompt improvement cycle for a given agent.

    Each iteration:
    - Evaluates the current prompt (baseline)
    - Uses the worst conversations to propose a targeted modification
    - Evaluates the candidate prompt on identical seeds (paired comparison)
    - Applies statistical gate before any promotion
    - Logs the full trace to MongoDB

    The loop is intentionally one-iteration-at-a-time. Call run_iteration()
    in a loop from scripts/run_eval.py --loop to run multiple iterations.
    """

    def __init__(
        self,
        judge: Optional[ConversationJudge] = None,
        proposer: Optional[PromptProposer] = None,
    ) -> None:
        self.judge = judge or ConversationJudge()
        self.runner = EvalRunner(judge=self.judge)
        self.proposer = proposer or PromptProposer()

    def run_iteration(
        self,
        agent_name: str,
        n_conversations: int = 60,
        seed: int = 42,
    ) -> IterationResult:
        """
        Run one full improvement iteration for the given agent.

        Args:
            agent_name: which agent to improve ("assessment", "resolution", "final_notice")
            n_conversations: conversations per eval run (same for baseline and candidate)
            seed: base seed — candidate uses same seed for paired comparison

        Returns:
            IterationResult with decision, reason, and score deltas
        """
        print(f"\n[loop] Starting iteration for agent='{agent_name}', n={n_conversations}, seed={seed}")

        # Step 1: Get current prompt
        current_doc = get_current_prompt(agent_name)
        if current_doc is None:
            raise RuntimeError(f"No current prompt found for agent '{agent_name}'")
        baseline_version = str(current_doc.get("_id", "unknown"))
        current_prompt_text = current_doc.get("prompt_text", "")
        current_version_num = current_doc.get("version", 1)

        # Step 2: Baseline eval
        print(f"[loop] Running baseline eval (version={baseline_version})")
        baseline_result: EvalRunResult = self.runner.run_evaluation(
            agent_name=agent_name,
            prompt_version_id=baseline_version,
            n_conversations=n_conversations,
            seed=seed,
        )

        # Step 3: Analyze worst conversations (bottom 10 by composite)
        worst = sorted(baseline_result.scores, key=lambda s: s.get("composite", 0.0))[:10]
        print(f"[loop] Worst composite in baseline: {worst[0].get('composite', 0):.4f}")

        # Step 4: Propose candidate
        print("[loop] Proposing candidate prompt...")
        candidate_text = self.proposer.propose(
            current_prompt=current_prompt_text,
            worst_conversations=worst,
        )

        # Step 5: Save candidate (not promoted yet)
        candidate_version = save_new_version(
            agent=agent_name,
            prompt_text=candidate_text,
            parent_version=current_version_num,
            change_description=f"Learning loop iteration — targeting failures from {baseline_version}",
            token_count=len(candidate_text.split()),
        )
        print(f"[loop] Candidate saved as version={candidate_version}")

        # Step 6: Evaluate candidate on SAME seeds (paired comparison)
        print(f"[loop] Running candidate eval (same seed={seed})")
        candidate_result: EvalRunResult = self.runner.run_evaluation(
            agent_name=agent_name,
            prompt_version_id=candidate_version,
            n_conversations=n_conversations,
            seed=seed,
        )

        # Step 7: Statistical gate
        baseline_scores = [s.get("composite", 0.0) for s in baseline_result.scores]
        candidate_scores = [s.get("composite", 0.0) for s in candidate_result.scores]

        promote, reason = should_promote(
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
            candidate_compliance_rate=candidate_result.compliance_pass_rate,
        )

        # Step 8: Act on decision
        decision = "promoted" if promote else "rejected"
        if promote:
            promote_version(candidate_version)
            print(f"[loop] PROMOTED {candidate_version}: {reason}")
        else:
            print(f"[loop] REJECTED {candidate_version}: {reason}")

        iteration_result = IterationResult(
            agent=agent_name,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            decision=decision,
            reason=reason,
            baseline_mean=baseline_result.composite_mean,
            candidate_mean=candidate_result.composite_mean,
            baseline_compliance_rate=baseline_result.compliance_pass_rate,
            candidate_compliance_rate=candidate_result.compliance_pass_rate,
            n_conversations=n_conversations,
            seed=seed,
        )

        # Step 9: Log to MongoDB
        self._log_iteration(iteration_result, baseline_result.run_id, candidate_result.run_id)
        return iteration_result

    def _log_iteration(
        self,
        result: IterationResult,
        baseline_run_id: str,
        candidate_run_id: str,
    ) -> None:
        if _learning_iterations is None:
            return
        try:
            _learning_iterations.insert_one({
                "agent": result.agent,
                "baseline_version": result.baseline_version,
                "candidate_version": result.candidate_version,
                "decision": result.decision,
                "reason": result.reason,
                "baseline_mean": result.baseline_mean,
                "candidate_mean": result.candidate_mean,
                "baseline_compliance_rate": result.baseline_compliance_rate,
                "candidate_compliance_rate": result.candidate_compliance_rate,
                "delta_mean": result.candidate_mean - result.baseline_mean,
                "n_conversations": result.n_conversations,
                "seed": result.seed,
                "baseline_run_id": baseline_run_id,
                "candidate_run_id": candidate_run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            print(f"[WARN] loop: failed to log iteration to MongoDB — {e}")
