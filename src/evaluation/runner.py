"""
Evaluation runner — executes N conversations with a given prompt version,
scores each with ConversationJudge (Claude Sonnet 4.6), and saves full records.

Records:
  - Per-conversation: eval_conversations collection + JSONL
  - Per-run aggregate: eval_runs collection + _summary.json + _failures.jsonl
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agents.assessment import AssessmentAgent
from src.agents.base import ConversationBudget
from src.agents.final_notice import FinalNoticeAgent
from src.agents.resolution import ResolutionAgent
from src.agents.simulator import SimulatedBorrower
from src.config import settings
from src.evaluation.judge import ConversationJudge, FullEvalResult
from src.llm.client import LLMClient
from src.llm.cost_tracker import get_provider_spend
from src.models.case_file import (
    CaseFile,
    ComplianceState,
    DebtInfo,
    FinancialInfo,
    NegotiationLedger,
)
from src.storage.mongo import eval_conversations as eval_conversations_collection
from src.storage.mongo import eval_runs as eval_runs_collection
from src.storage.prompt_registry import get_current_prompt

_PROFILES_PATH = (
    Path(__file__).parent.parent.parent
    / "data"
    / "scenarios"
    / "borrower_profiles.json"
)
_EVAL_RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "eval_runs"


def _load_profiles() -> list[dict]:
    return json.loads(_PROFILES_PATH.read_text())


def _build_case_file(profile: dict, seed: int) -> CaseFile:
    borrower_id = f"eval_{profile['persona']}_{seed}"
    return CaseFile(
        borrower_id=borrower_id,
        partial_account=profile["account_ending"],
        debt=DebtInfo(
            amount=profile["debt_amount"],
            creditor=profile["creditor"],
            default_date="2025-01-15",
        ),
        financial=FinancialInfo(
            income_status=profile.get("income_status"),
            monthly_income_est=profile.get("monthly_income"),
        ),
        negotiation=NegotiationLedger(),
        compliance=ComplianceState(),
    )


@dataclass
class EvalRunResult:
    run_id: str
    prompt_version_id: str
    agent_name: str
    scores: list[dict] = field(default_factory=list)  # serialized FullEvalResult dicts
    composite_mean: float = 0.0
    composite_std: float = 0.0
    compliance_pass_rate: float = 0.0
    seed: int = 42
    n_conversations: int = 0
    # Enhanced fields
    metric_stats: dict = field(default_factory=dict)
    persona_breakdown: dict = field(default_factory=dict)
    outcome_distribution: dict = field(default_factory=dict)
    cost_breakdown: dict = field(default_factory=dict)
    bootstrap_ci_95: tuple[float, float] = (0.0, 0.0)


def _bootstrap_ci(data: list[float], n: int = 2000) -> tuple[float, float]:
    import random

    if not data:
        return (0.0, 0.0)
    size = len(data)
    means = sorted(sum(random.choices(data, k=size)) / size for _ in range(n))
    lo = int(0.025 * n)
    hi = int(0.975 * n) - 1
    return (means[lo], means[hi])


def _metric_stats(values: list[float]) -> dict:
    if not values:
        return {}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    sorted_v = sorted(values)
    return {
        "mean": round(mean, 4),
        "std": round(variance**0.5, 4),
        "min": round(sorted_v[0], 4),
        "max": round(sorted_v[-1], 4),
        "median": round(sorted_v[n // 2], 4),
        "p25": round(sorted_v[n // 4], 4),
        "p75": round(sorted_v[3 * n // 4], 4),
    }


class EvalRunner:
    """
    Runs N conversations with a given agent + prompt version.
    Scores each with Claude Sonnet 4.6 judge.
    Saves per-conversation records and run aggregates.
    """

    def __init__(self, judge: Optional[ConversationJudge] = None) -> None:
        self.judge = judge or ConversationJudge()

    def run_evaluation(
        self,
        agent_name: str,
        prompt_version_id: Optional[str] = None,
        n_conversations: int = 20,
        seed: int = 42,
        persist: bool = False,
    ) -> EvalRunResult:
        profiles = _load_profiles()
        if not profiles:
            raise RuntimeError("No borrower profiles found.")

        # Dual-budget check
        self._check_budgets()

        if prompt_version_id is None:
            doc = get_current_prompt(agent_name)
            if doc is None:
                raise RuntimeError(f"No current prompt for agent '{agent_name}'")
            prompt_version_id = str(doc.get("_id", "unknown"))

        run_id = f"eval_{agent_name}_{seed}_{uuid.uuid4().hex[:8]}"
        llm = LLMClient()
        scores_raw: list[dict] = []
        conversation_records: list[dict] = []

        print(f"[eval] Run {run_id} — {n_conversations} conversations, seed={seed}")
        print(
            f"[eval] Agent model: {settings.azure_openai_deployment}  |  Judge: {settings.anthropic_model}"
        )

        for i in range(n_conversations):
            profile = profiles[i % len(profiles)]
            conversation_seed = seed + i
            conversation_id = f"{run_id}_c{i:03d}"

            try:
                score_dict, conv_record = self._run_single(
                    agent_name=agent_name,
                    profile=profile,
                    conversation_seed=conversation_seed,
                    llm=llm,
                    run_id=run_id,
                    conversation_id=conversation_id,
                )
                score_dict["persona"] = profile["persona"]
                score_dict["seed"] = conversation_seed
                score_dict["run_index"] = i
                score_dict["conversation_id"] = conversation_id
                scores_raw.append(score_dict)
                conv_record["persona"] = profile["persona"]
                conv_record["seed"] = conversation_seed
                conversation_records.append(conv_record)
                print(
                    f"  [{i + 1}/{n_conversations}] persona={profile['persona']:12s} "
                    f"composite={score_dict.get('composite', 0):.3f}  "
                    f"gate={str(score_dict.get('gate_failed') or 'none'):12s}  "
                    f"outcome={score_dict.get('full_metrics', {}).get('outcome', {}).get('resolution_label', '?')}"
                )
            except Exception as e:
                print(f"  [{i + 1}/{n_conversations}] ERROR: {e}")
                scores_raw.append(
                    {
                        "persona": profile["persona"],
                        "seed": conversation_seed,
                        "run_index": i,
                        "conversation_id": conversation_id,
                        "error": str(e),
                        "composite": 0.0,
                    }
                )

        result = self._build_result(
            run_id, prompt_version_id, agent_name, seed, scores_raw
        )
        self._save_results(result, scores_raw, conversation_records)
        return result

    def _check_budgets(self) -> None:
        azure_spent = get_provider_spend("azure")
        anthropic_spent = get_provider_spend("anthropic")
        print(
            f"[eval] Budget: Azure ${azure_spent:.2f}/${settings.azure_budget_usd:.2f}  |  "
            f"Anthropic ${anthropic_spent:.2f}/${settings.anthropic_budget_usd:.2f}"
        )
        if azure_spent >= settings.azure_budget_usd:
            raise RuntimeError(
                f"Azure budget ceiling reached: ${azure_spent:.2f} >= ${settings.azure_budget_usd:.2f}"
            )
        if anthropic_spent >= settings.anthropic_budget_usd:
            raise RuntimeError(
                f"Anthropic budget ceiling reached: ${anthropic_spent:.2f} >= ${settings.anthropic_budget_usd:.2f}"
            )

    def _run_single(
        self,
        agent_name: str,
        profile: dict,
        conversation_seed: int,
        llm: LLMClient,
        run_id: str,
        conversation_id: str,
    ) -> tuple[dict, dict]:
        case_before = _build_case_file(profile, conversation_seed)
        case_file = _build_case_file(profile, conversation_seed)

        borrower_io = SimulatedBorrower(
            llm=llm, persona_description=profile["description"]
        )
        budget = ConversationBudget(max_turns=10, max_cost_usd=1.00)

        if agent_name == "assessment":
            agent = AssessmentAgent(llm)
        elif agent_name == "resolution":
            agent = ResolutionAgent(llm)
        elif agent_name == "final_notice":
            agent = FinalNoticeAgent(llm)
        else:
            raise ValueError(f"Unknown agent_name: {agent_name!r}")

        messages, updated_case, _flags = agent.run_conversation(
            case_file=case_file,
            io=borrower_io,
            budget=budget,
        )

        score: FullEvalResult = self.judge.score_conversation(
            transcript=messages,
            case_before=case_before.model_dump(mode="json"),
            case_after=updated_case.model_dump(mode="json"),
            stage=agent_name,
            persona=profile.get("persona"),
            run_id=run_id,
            conversation_id=conversation_id,
        )

        score_dict = score.to_legacy_dict()
        score_dict["full_metrics"] = score.model_dump(mode="json")

        conv_record = {
            "conversation_id": conversation_id,
            "run_id": run_id,
            "agent_name": agent_name,
            "transcript": messages,
            "case_before": case_before.model_dump(mode="json"),
            "case_after": updated_case.model_dump(mode="json"),
            "scores": score.model_dump(mode="json"),
            "judge_reasoning": score.reasoning,
            "gate_failed": score.gate_failed,
            "conversation_turns": len(messages),
            "judge_variant": score.judge_variant,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return score_dict, conv_record

    def _build_result(
        self,
        run_id: str,
        prompt_version_id: str,
        agent_name: str,
        seed: int,
        scores_raw: list[dict],
    ) -> EvalRunResult:
        composites = [s.get("composite", 0.0) for s in scores_raw]
        mean = sum(composites) / len(composites) if composites else 0.0
        variance = (
            sum((c - mean) ** 2 for c in composites) / len(composites)
            if composites
            else 0.0
        )
        std = variance**0.5
        compliance_pass_rate = (
            sum(1 for c in composites if c > 0.0) / len(composites)
            if composites
            else 0.0
        )

        # Per-metric stats
        def extract_metric(key_path: list[str]) -> list[float]:
            vals = []
            for s in scores_raw:
                v = s
                try:
                    for k in key_path:
                        v = v[k]
                    vals.append(float(v))
                except (KeyError, TypeError):
                    pass
            return vals

        metric_stats = {
            "composite": _metric_stats(composites),
            "quality": _metric_stats(
                extract_metric(["full_metrics", "quality", "score"])
            ),
            "outcome": _metric_stats(
                extract_metric(["full_metrics", "outcome", "score"])
            ),
            "safety": _metric_stats(
                extract_metric(["full_metrics", "safety", "score"])
            ),
            "compliance": _metric_stats(
                extract_metric(["full_metrics", "compliance", "score"])
            ),
        }

        # Per-persona breakdown
        persona_breakdown: dict = {}
        for s in scores_raw:
            p = s.get("persona", "unknown")
            persona_breakdown.setdefault(p, []).append(s.get("composite", 0.0))
        persona_breakdown = {
            p: {
                "mean": round(sum(vs) / len(vs), 4),
                "std": round(
                    (sum((v - sum(vs) / len(vs)) ** 2 for v in vs) / len(vs)) ** 0.5, 4
                ),
                "n": len(vs),
                "compliance_rate": sum(1 for v in vs if v > 0) / len(vs),
            }
            for p, vs in persona_breakdown.items()
        }

        # Outcome distribution
        outcome_counts: dict[str, int] = {}
        for s in scores_raw:
            label = (
                s.get("full_metrics", {})
                .get("outcome", {})
                .get("resolution_label", "unknown")
                if "full_metrics" in s
                else "unknown"
            )
            outcome_counts[label] = outcome_counts.get(label, 0) + 1

        # Bootstrap CI
        ci = _bootstrap_ci(composites)

        return EvalRunResult(
            run_id=run_id,
            prompt_version_id=prompt_version_id,
            agent_name=agent_name,
            scores=scores_raw,
            composite_mean=mean,
            composite_std=std,
            compliance_pass_rate=compliance_pass_rate,
            seed=seed,
            n_conversations=len(scores_raw),
            metric_stats=metric_stats,
            persona_breakdown=persona_breakdown,
            outcome_distribution=outcome_counts,
            bootstrap_ci_95=ci,
        )

    def _save_results(
        self,
        result: EvalRunResult,
        scores_raw: list[dict],
        conversation_records: list[dict],
    ) -> None:
        _EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)

        # MongoDB: per-conversation records
        if conversation_records:
            try:
                eval_conversations_collection.insert_many(
                    conversation_records, ordered=False
                )
            except Exception as e:
                print(f"[WARN] eval_runner: failed to save conversation records — {e}")

        # MongoDB: run aggregate
        try:
            eval_runs_collection.insert_one(
                {
                    "_id": result.run_id,
                    "prompt_version_id": result.prompt_version_id,
                    "agent_name": result.agent_name,
                    "composite_mean": result.composite_mean,
                    "composite_std": result.composite_std,
                    "compliance_pass_rate": result.compliance_pass_rate,
                    "seed": result.seed,
                    "n_conversations": result.n_conversations,
                    "metric_stats": result.metric_stats,
                    "persona_breakdown": result.persona_breakdown,
                    "outcome_distribution": result.outcome_distribution,
                    "bootstrap_ci_95": list(result.bootstrap_ci_95),
                    "scores": scores_raw,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            print(f"[WARN] eval_runner: failed to save to MongoDB — {e}")

        # JSONL: full conversation records (one per line)
        jsonl_path = _EVAL_RUNS_DIR / f"{result.run_id}.jsonl"
        with jsonl_path.open("w") as f:
            for score in scores_raw:
                f.write(json.dumps(score, default=str) + "\n")

        # JSON: summary
        summary_path = _EVAL_RUNS_DIR / f"{result.run_id}_summary.json"
        summary = {
            "run_id": result.run_id,
            "prompt_version_id": result.prompt_version_id,
            "agent_name": result.agent_name,
            "n_conversations": result.n_conversations,
            "composite_mean": result.composite_mean,
            "composite_std": result.composite_std,
            "compliance_pass_rate": result.compliance_pass_rate,
            "bootstrap_ci_95": list(result.bootstrap_ci_95),
            "metric_stats": result.metric_stats,
            "persona_breakdown": result.persona_breakdown,
            "outcome_distribution": result.outcome_distribution,
        }
        summary_path.write_text(json.dumps(summary, indent=2, default=str))

        # JSONL: failures only (gate failures for triage)
        failures = [
            s
            for s in scores_raw
            if s.get("gate_failed") or s.get("composite", 1.0) == 0.0
        ]
        if failures:
            failures_path = _EVAL_RUNS_DIR / f"{result.run_id}_failures.jsonl"
            with failures_path.open("w") as f:
                for s in failures:
                    f.write(json.dumps(s, default=str) + "\n")

        print(f"[eval] Saved: {jsonl_path.name}")
        self._print_summary(result)

    def _print_summary(self, result: EvalRunResult) -> None:
        width = 65
        bar = "═" * width
        print(f"\n{bar}")
        print("  CopperTree Eval Report")
        print(f"  Run: {result.run_id}")
        print(
            f"  N={result.n_conversations}  Seed={result.seed}  Prompt: {result.prompt_version_id}"
        )
        print(
            f"  Agent: {settings.azure_openai_deployment}  Judge: {settings.anthropic_model}"
        )
        print(f"{'─' * width}")
        ci = result.bootstrap_ci_95
        print(
            f"  COMPOSITE:   {result.composite_mean:.4f} ± {result.composite_std:.4f}"
            f"  [95% CI: {ci[0]:.3f}, {ci[1]:.3f}]"
        )
        print(f"  Compliance pass: {result.compliance_pass_rate:.1%}")
        print(f"{'─' * width}")
        print("  Per-Dimension:")
        for dim in ["compliance", "quality", "outcome", "safety"]:
            stats = result.metric_stats.get(dim, {})
            if stats:
                print(
                    f"    {dim:12s}: {stats.get('mean', 0):.3f} ± {stats.get('std', 0):.3f}"
                )
        print(f"{'─' * width}")
        print("  Per-Persona:")
        for persona, pb in sorted(result.persona_breakdown.items()):
            print(
                f"    {persona:12s}: {pb['mean']:.3f} (n={pb['n']}, compliance={pb['compliance_rate']:.0%})"
            )
        if result.outcome_distribution:
            print(f"{'─' * width}")
            print(f"  Outcomes: {result.outcome_distribution}")
        print(f"{bar}\n")
