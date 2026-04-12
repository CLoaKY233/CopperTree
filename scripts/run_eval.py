"""
Evaluation pipeline entrypoint.

Usage:
    # Run N scored conversations with the current prompt
    uv run python scripts/run_eval.py --agent assessment --n 60 --seed 42

    # Run and promote if statistically better
    uv run python scripts/run_eval.py --agent assessment --n 60 --seed 42 --promote

    # Run the full learning loop for N iterations
    uv run python scripts/run_eval.py --loop --agent assessment --iterations 3

    # Run the DGM meta-evaluation demo
    uv run python scripts/run_eval.py --meta-eval --demo
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.evaluation.judge import ConversationJudge
from src.evaluation.runner import EvalRunner
from src.learning.loop import LearningLoop
from src.learning.stats import should_promote


def cmd_eval(args: argparse.Namespace) -> None:
    """Run evaluation and optionally promote if better."""
    runner = EvalRunner()
    result = runner.run_evaluation(
        agent_name=args.agent,
        n_conversations=args.n,
        seed=args.seed,
    )

    print(f"\n=== Eval Results: {result.agent_name} ===")
    print(f"Run ID:            {result.run_id}")
    print(f"Prompt version:    {result.prompt_version_id}")
    print(f"Conversations:     {result.n_conversations}")
    print(
        f"Composite mean:    {result.composite_mean:.4f} ± {result.composite_std:.4f}"
    )
    print(f"Compliance pass:   {result.compliance_pass_rate:.1%}")

    print("\nPer-persona breakdown:")
    by_persona: dict[str, list[float]] = {}
    for score in result.scores:
        p = score.get("persona", "unknown")
        by_persona.setdefault(p, []).append(score.get("composite", 0.0))
    for persona, scores in sorted(by_persona.items()):
        mean = sum(scores) / len(scores)
        print(f"  {persona:12s}: mean={mean:.3f} (n={len(scores)})")

    if args.promote:
        print("\n[promote] Checking statistical gate before promotion...")
        # Need a baseline to compare against — print warning if no baseline available
        print(
            "[promote] --promote requires a comparison run. Use --loop for full learning iteration."
        )


def cmd_loop(args: argparse.Namespace) -> None:
    """Run the full learning loop for N iterations."""
    loop = LearningLoop()
    results = []

    for i in range(args.iterations):
        print(f"\n=== Iteration {i + 1}/{args.iterations} ===")
        result = loop.run_iteration(
            agent_name=args.agent,
            n_conversations=args.n,
            seed=args.seed + i * 1000,  # different seed per iteration
        )
        results.append(result)

        print(f"\nIteration {i + 1} Result:")
        print(f"  Baseline version:  {result.baseline_version}")
        print(f"  Candidate version: {result.candidate_version}")
        print(f"  Decision:          {result.decision.upper()}")
        print(f"  Reason:            {result.reason}")
        print(f"  Baseline mean:     {result.baseline_mean:.4f}")
        print(f"  Candidate mean:    {result.candidate_mean:.4f}")
        print(
            f"  Delta:             {result.candidate_mean - result.baseline_mean:+.4f}"
        )

    print(f"\n=== Loop Complete: {len(results)} iterations ===")
    promoted = [r for r in results if r.decision == "promoted"]
    print(f"Promoted: {len(promoted)}/{len(results)}")
    if promoted:
        for r in promoted:
            print(
                f"  {r.candidate_version}: {r.baseline_mean:.4f} → {r.candidate_mean:.4f}"
            )


def cmd_meta_eval(args: argparse.Namespace) -> None:
    """Run the DGM meta-evaluation demo."""
    from src.evaluation.meta_eval import MetaEvaluator

    meta = MetaEvaluator()

    if args.demo:
        print("\n=== DGM Meta-Evaluation Demo ===")
        print(
            "This demo demonstrates that the system can detect flaws in its own evaluation."
        )
        print(
            "Step-by-step: flawed judge → flaw detected → correct judge → safe rejection.\n"
        )

        result = meta.demonstrate_dgm_scenario(
            agent_name=args.agent,
            n_conversations=args.n,
            seed=args.seed,
        )

        print("\n=== Final Summary ===")
        print(result.conclusion)
    else:
        print("Use --demo to run the DGM demonstration scenario.")
        print("Use --audit with a run_id to audit specific evaluation runs.")


def main() -> None:
    parser = argparse.ArgumentParser(description="CopperTree evaluation pipeline")
    parser.add_argument(
        "--agent",
        default="assessment",
        choices=["assessment", "resolution", "final_notice"],
        help="Which agent to evaluate",
    )
    parser.add_argument("--n", type=int, default=60, help="Number of conversations")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility"
    )

    # Mode flags (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loop", action="store_true", help="Run learning loop")
    mode.add_argument("--meta-eval", action="store_true", help="Run meta-evaluation")

    # Sub-options
    parser.add_argument(
        "--iterations", type=int, default=3, help="Iterations for --loop"
    )
    parser.add_argument(
        "--promote", action="store_true", help="Promote if better (with --eval)"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Run DGM demo (with --meta-eval)"
    )

    args = parser.parse_args()

    if args.loop:
        cmd_loop(args)
    elif args.meta_eval:
        cmd_meta_eval(args)
    else:
        cmd_eval(args)


if __name__ == "__main__":
    main()
