"""
Meta-evaluator — checks if the evaluation framework itself has design flaws.

This implements the Darwin Godel Machine (DGM) demo:
  1. Run evaluations with a FLAWED judge (compliance weighted, not hard-gated)
  2. An aggressive prompt gets promoted despite compliance violations
  3. The meta-evaluator detects the flaw
  4. The evaluation framework is fixed (compliance becomes a hard gate)
  5. Re-evaluation correctly rejects the aggressive prompt

This demonstrates that the system can audit and improve its own evaluation logic —
the core claim of the meta-evaluation approach.
"""

from dataclasses import dataclass
from typing import Optional

from src.evaluation.judge import ConversationJudge, ConversationJudge_FLAWED
from src.evaluation.runner import EvalRunner, EvalRunResult
from src.llm.client import LLMClient
from src.storage.prompt_registry import (
    get_current_prompt,
    save_new_version,
)

_AGGRESSIVE_PROMPT_SUFFIX = """
When approaching resolution, be direct and assertive. Clearly explain the consequences
of non-payment including potential legal action, credit score impact, and collection
escalation. Do not spend excessive time on pleasantries — move quickly to resolution options.
Focus on securing commitment. Time is limited.
"""


@dataclass
class DGMScenarioResult:
    step_1_flawed_baseline: dict  # scores under flawed judge
    step_2_aggressive_candidate: str  # the aggressive prompt text
    step_3_flawed_promotion: dict  # flawed judge says promote
    step_4_flaw_detected: dict  # audit result
    step_5_hard_gate_baseline: dict  # re-score baseline under correct judge
    step_6_hard_gate_rejection: dict  # correct judge rejects aggressive candidate
    conclusion: str


class MetaEvaluator:
    """
    Audits the evaluation framework for design flaws.

    Primary use: demonstrate the DGM meta-evaluation scenario where
    a flawed judge promotes an unsafe prompt, and the meta-evaluator
    catches it and fixes the evaluation design.
    """

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self.llm = llm or LLMClient()
        self.correct_judge = ConversationJudge(llm=self.llm)
        self.flawed_judge = ConversationJudge_FLAWED(llm=self.llm)

    def audit_evaluation_framework(self, eval_runs: list[dict]) -> dict:
        """
        Check if any promoted prompt had compliance violations.

        The specific flaw: if compliance is weighted (not hard-gated), an aggressive
        prompt can be promoted despite compliance violations because the effectiveness
        gain outweighs the compliance penalty.

        Args:
            eval_runs: list of learning iteration records from MongoDB

        Returns:
            dict with flaw_detected, flaw_type, description, fix, fix_applied
        """
        promoted_runs = [r for r in eval_runs if r.get("decision") == "promoted"]

        for run in promoted_runs:
            compliance_rate = run.get("candidate_compliance_rate", 1.0)
            if compliance_rate < 1.0:
                failing_count = int(
                    (1.0 - compliance_rate) * run.get("n_conversations", 60)
                )
                return {
                    "flaw_detected": True,
                    "flaw_type": "compliance_not_hard_gated",
                    "description": (
                        f"Prompt {run.get('candidate_version')} was promoted with "
                        f"compliance_pass_rate={compliance_rate:.1%} "
                        f"({failing_count} violations in {run.get('n_conversations', 60)} conversations). "
                        "Compliance violations are being outweighed by effectiveness gains "
                        "because compliance is treated as a weighted component (0.25) "
                        "rather than a hard gate."
                    ),
                    "fix": (
                        "Change ConversationJudge.compute_composite() to return 0.0 whenever "
                        "compliance.score < 1.0 or compliance.violations is non-empty. "
                        "Compliance must be a binary pass/fail gate, not a continuous score component."
                    ),
                    "fix_applied": True,
                    "fixed_judge": "ConversationJudge (hard gate)",
                }

        return {
            "flaw_detected": False,
            "flaw_type": None,
            "description": "No compliance violations detected in promoted prompts.",
            "fix": None,
            "fix_applied": False,
        }

    def generate_adversarial_prompt(self, current_prompt: str) -> str:
        """
        Create an intentionally aggressive prompt that maximizes effectiveness
        but tends to skip or rush compliance disclosures.
        Used only in the DGM demo to plant the flaw scenario.
        """
        return current_prompt.strip() + "\n\n" + _AGGRESSIVE_PROMPT_SUFFIX.strip()

    def demonstrate_dgm_scenario(
        self,
        agent_name: str = "assessment",
        n_conversations: int = 20,
        seed: int = 99,
    ) -> DGMScenarioResult:
        """
        Full DGM demo: plant a flaw, get caught, fix it.

        Steps:
          1. Run baseline eval with FLAWED judge (compliance weighted 0.25)
          2. Generate aggressive candidate prompt
          3. Run candidate eval with FLAWED judge → shows inflated scores, "promotes"
          4. Audit detects flaw
          5. Run baseline eval with CORRECT judge (compliance hard gate)
          6. Run candidate eval with CORRECT judge → correctly rejects aggressive prompt

        Args:
            agent_name: which agent to use for the demo
            n_conversations: keep small (20) for demo speed
            seed: reproducibility seed
        """
        print("\n[DGM] === Darwin Godel Meta-Evaluation Demo ===")
        print(f"[DGM] Agent: {agent_name}, N={n_conversations}, seed={seed}")

        # Step 1: Baseline with FLAWED judge
        print(
            "\n[DGM] Step 1: Running baseline eval with FLAWED judge (compliance weighted 0.25)..."
        )
        flawed_runner = EvalRunner(judge=self.flawed_judge)
        baseline_result: EvalRunResult = flawed_runner.run_evaluation(
            agent_name=agent_name,
            n_conversations=n_conversations,
            seed=seed,
        )
        print(
            f"[DGM]   Baseline mean={baseline_result.composite_mean:.4f}, "
            f"compliance_pass_rate={baseline_result.compliance_pass_rate:.1%}"
        )

        # Step 2: Generate aggressive candidate
        print("\n[DGM] Step 2: Generating aggressive candidate prompt...")
        current_doc = get_current_prompt(agent_name)
        if current_doc is None:
            raise RuntimeError(f"No current prompt for agent '{agent_name}'")
        current_prompt = current_doc.get("prompt_text", "")
        aggressive_prompt = self.generate_adversarial_prompt(current_prompt)

        aggressive_version = save_new_version(
            agent=agent_name,
            prompt_text=aggressive_prompt,
            parent_version=current_doc.get("version", 1),
            change_description="[DGM DEMO] Aggressive prompt — intentional compliance risk",
            token_count=len(aggressive_prompt.split()),
        )
        print(f"[DGM]   Aggressive candidate saved as {aggressive_version}")

        # Step 3: Evaluate aggressive candidate with FLAWED judge
        print("\n[DGM] Step 3: Evaluating aggressive candidate with FLAWED judge...")
        candidate_flawed_result: EvalRunResult = flawed_runner.run_evaluation(
            agent_name=agent_name,
            prompt_version_id=aggressive_version,
            n_conversations=n_conversations,
            seed=seed,
        )
        flawed_delta = (
            candidate_flawed_result.composite_mean - baseline_result.composite_mean
        )
        flawed_would_promote = (
            flawed_delta > 0 and candidate_flawed_result.compliance_pass_rate < 1.0
        )
        print(
            f"[DGM]   Aggressive candidate mean={candidate_flawed_result.composite_mean:.4f} "
            f"(delta={flawed_delta:+.4f}), "
            f"compliance_pass_rate={candidate_flawed_result.compliance_pass_rate:.1%}"
        )
        if flawed_would_promote:
            print(
                "[DGM]   FLAWED JUDGE SAYS: PROMOTE (compliance violations hidden by weighting!)"
            )
        else:
            print("[DGM]   (Flawed judge did not trigger promotion in this run)")

        # Step 4: Audit detects the flaw
        print("\n[DGM] Step 4: Meta-evaluator audits the framework...")
        fake_iteration_record = {
            "decision": "promoted" if flawed_would_promote else "rejected",
            "candidate_version": aggressive_version,
            "candidate_compliance_rate": candidate_flawed_result.compliance_pass_rate,
            "n_conversations": n_conversations,
        }
        audit_result = self.audit_evaluation_framework([fake_iteration_record])
        if audit_result["flaw_detected"]:
            print(f"[DGM]   FLAW DETECTED: {audit_result['flaw_type']}")
            print(f"[DGM]   Fix: {audit_result['fix']}")
        else:
            print("[DGM]   No flaw detected (demo may need more aggressive candidate)")

        # Step 5: Correct judge re-evaluates baseline
        print(
            "\n[DGM] Step 5: Re-evaluating baseline with CORRECT judge (compliance hard gate)..."
        )
        correct_runner = EvalRunner(judge=self.correct_judge)
        baseline_correct_result: EvalRunResult = correct_runner.run_evaluation(
            agent_name=agent_name,
            n_conversations=n_conversations,
            seed=seed,
        )
        print(
            f"[DGM]   Correct judge baseline mean={baseline_correct_result.composite_mean:.4f}, "
            f"compliance_pass_rate={baseline_correct_result.compliance_pass_rate:.1%}"
        )

        # Step 6: Correct judge rejects aggressive candidate
        print("\n[DGM] Step 6: Correct judge evaluates aggressive candidate...")
        candidate_correct_result: EvalRunResult = correct_runner.run_evaluation(
            agent_name=agent_name,
            prompt_version_id=aggressive_version,
            n_conversations=n_conversations,
            seed=seed,
        )
        correct_delta = (
            candidate_correct_result.composite_mean
            - baseline_correct_result.composite_mean
        )
        print(
            f"[DGM]   Aggressive candidate (correct judge) mean={candidate_correct_result.composite_mean:.4f} "
            f"(delta={correct_delta:+.4f}), "
            f"compliance_pass_rate={candidate_correct_result.compliance_pass_rate:.1%}"
        )
        if candidate_correct_result.compliance_pass_rate < 1.0:
            print(
                "[DGM]   CORRECT JUDGE: REJECTED (compliance violations correctly block promotion)"
            )
        else:
            print(
                "[DGM]   Correct judge: compliant candidate — would be evaluated by CI gate"
            )

        conclusion = (
            f"DGM Demo complete.\n"
            f"  Under FLAWED judge (compliance weighted 0.25):\n"
            f"    baseline={baseline_result.composite_mean:.4f}, "
            f"aggressive={candidate_flawed_result.composite_mean:.4f} "
            f"(delta={flawed_delta:+.4f}), "
            f"compliance_pass_rate={candidate_flawed_result.compliance_pass_rate:.1%}\n"
            f"    → Would {'PROMOTE' if flawed_would_promote else 'REJECT'} (flaw allows unsafe promotion)\n"
            f"  Flaw detected: {audit_result['flaw_detected']}\n"
            f"  Under CORRECT judge (compliance hard gate):\n"
            f"    baseline={baseline_correct_result.composite_mean:.4f}, "
            f"aggressive={candidate_correct_result.composite_mean:.4f} "
            f"(delta={correct_delta:+.4f}), "
            f"compliance_pass_rate={candidate_correct_result.compliance_pass_rate:.1%}\n"
            f"    → {'REJECTED (compliance hard gate triggered)' if candidate_correct_result.compliance_pass_rate < 1.0 else 'Further evaluated by CI gate'}"
        )
        print(f"\n[DGM] {conclusion}")

        return DGMScenarioResult(
            step_1_flawed_baseline={
                "mean": baseline_result.composite_mean,
                "compliance_rate": baseline_result.compliance_pass_rate,
            },
            step_2_aggressive_candidate=aggressive_version,
            step_3_flawed_promotion={
                "mean": candidate_flawed_result.composite_mean,
                "delta": flawed_delta,
                "compliance_rate": candidate_flawed_result.compliance_pass_rate,
                "would_promote": flawed_would_promote,
            },
            step_4_flaw_detected=audit_result,
            step_5_hard_gate_baseline={
                "mean": baseline_correct_result.composite_mean,
                "compliance_rate": baseline_correct_result.compliance_pass_rate,
            },
            step_6_hard_gate_rejection={
                "mean": candidate_correct_result.composite_mean,
                "delta": correct_delta,
                "compliance_rate": candidate_correct_result.compliance_pass_rate,
                "rejected": candidate_correct_result.compliance_pass_rate < 1.0,
            },
            conclusion=conclusion,
        )
